# Plan 008: Retry a locked `consume` instead of failing a finished run

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 2734a2c..HEAD -- agents/extract-transfer.md skills/clone/SKILL.md skills/pull/SKILL.md`
>
> Expected drift: **none**. If any file changed, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `2734a2c`, 2026-08-16
- **Release-sequenced**: this closes a failure mode the Extractor's *unreleased* work introduces. It is worth landing in the same coordinated release, and certainly before any large extraction run — see "Why this matters".

## Why this matters

The Extractor's unreleased work makes `POST /extractions/{id}/consume` and `DELETE /extractions/{id}` take the per-job tick lock, because both purged a job's artifact without it and could delete the directory a live build was still writing into (ADR-0019 in `~/Projects/kntnt-extractor`). When the lock is already held, the route now answers **`409 kntnt_extractor_locked`** — "This extraction job is being built; retry the request." (`classes/Rest/Extractions_Controller.php:608` and `:662`). The server's own changelog states the intended client behaviour plainly: "the caller simply retries."

**This client does not retry, and does not know the code exists.** `agents/extract-transfer.md:45` says only: "Consume the job: `POST /extractions/{id}/consume` and confirm the `{ id, state: "consumed" }` response". Its verdict rules then make the omission expensive: "An unseal that fails, or a job that never reached a consumed state on the happy path, is always `FAILED`, whatever the poll reported" (`:67`), and "Never report `DONE` on a container you have not personally unsealed, nor on a job you have not consumed" (`:76`).

So the concrete failure is: a multi-hour extraction succeeds, the container downloads, the unseal succeeds — and then a single `409` on the last call turns the whole run into `FAILED`. Nothing is lost from the *data* side; the download and unseal precede the consume, so a complete local copy already exists. What is lost is the run's verdict, the operator's confidence, and the closing of the exposure window on a live client site: the artifact then sits on production until its TTL instead of being deleted immediately, which is the exact window ADR-0022 was written to shrink.

**Be precise about the likelihood: this race is narrow, and this plan does not claim otherwise.** The consume is issued against a job in `ready`, whose build is finished, so no build tick should be holding the lock. The realistic holder is the TTL sweep, which takes the same per-job lock during its cycle. That is a small window. It is worth closing anyway because the cost is asymmetric — a few seconds of retry against forfeiting the verdict of a run that costs hours and can only be made against a live client site.

This is not an `api_version` question. The refusal is loud, named, and detectable; it does not make an old client's existing logic unsafe undetectably, which is the only ground ADR-0018 adds. It is an availability fix for one specific client, exactly like the restricted-path handling in `plans/007-*.md`.

## Current state

- `agents/extract-transfer.md:45` — step 5, the consume, quoted above. It enumerates no error handling at all.
- `agents/extract-transfer.md:41` — step 1's error table for `POST /extractions`, the structural pattern to follow: it names each status code and says what the agent does with it.
- `agents/extract-transfer.md:56` — `failure_phase`, whose three values (`never_ready`, `downloaded_unseal_failed`, `ready_download_failed`) let the orchestrator's close-out pick a case directly. A consume that never succeeded currently maps to none of them cleanly.
- `agents/extract-transfer.md:63` — the evidence block's `consumed: true | false`.
- `skills/clone/SKILL.md:121` and `skills/pull/SKILL.md:121` — the operator-facing description of the consume as "the happy-path close", with the TTL sweep named as the backstop.
- `skills/clone/SKILL.md:132` / `skills/pull/SKILL.md:132` — the failure-path close-out cases, which already reason about consuming after a failed unseal.

The relevant server behaviour, quoted because it lives in the other repository:

- `classes/Rest/Extractions_Controller.php:608,662` — `return $this->error( 409, 'kntnt_extractor_locked', __( 'This extraction job is being built; retry the request.', 'kntnt-extractor' ) );`
- Both call sites are reached only when the per-job tick lock is already held. The lock is short-lived by construction; it is taken around a tick or a sweep step, not held across a whole build.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `uvx pytest -q` | exit 0, 962 passing before your change |
| Consistency | `uvx pytest -q tests/test_agent_delegation_consistency.py` | exit 0 |

No Python changes are expected in this plan; if you find yourself editing `scripts/`, stop and report.

## Scope

**In scope**:

- `agents/extract-transfer.md`
- `skills/clone/SKILL.md`
- `skills/pull/SKILL.md`
- `CHANGELOG.md`

**Out of scope**:

- `scripts/poll_extraction.py` — it polls `GET /extractions/{id}`, which does not take the lock and cannot answer `409`. Do not add retry logic there.
- Any retry on `429`. That is a different code with a different meaning (a job is already active) and an existing, deliberate hard stop. Do not touch it.
- The `DELETE /extractions/{id}` cancel path used by the health check's stranded-job sweep. It can also answer `409`, but a failed cancel there is already handled as a reportable condition rather than a run-ending one; widening this plan into it risks changing sweep semantics. Named here as deliberate follow-up, not an oversight.

## Git workflow

- Trunk-based: commit straight to `main`. No branch, no PR. Do not push, tag, or bump a version.

## Steps

### Step 1: Give the consume a bounded retry

In `agents/extract-transfer.md`, replace step 5 (`:45`) with wording that keeps the existing contract and adds the retry. Target content:

> 5. Consume the job: `POST /extractions/{id}/consume` and confirm the `{ id, state: "consumed" }` response — the happy-path close that deletes the artifact on production. A **`409` whose `code` is `kntnt_extractor_locked`** means a tick or the TTL sweep is holding the job's lock at this instant; it is not a failure. Retry the consume up to **five times, 10 seconds apart**, and treat the first `{ state: "consumed" }` as success. Only if all six attempts answer `409` is this a `FAILED` close — report `consumed: false` with the last body, and say in the summary that the artifact is still on production and will be reclaimed by its TTL. Any other non-2xx is a `FAILED` close as before. Use `DELETE /extractions/{id}` **only** to cancel a job you are aborting, never as the happy-path close.

The bound is six attempts over roughly 50 seconds. State that bound in the file rather than leaving it to the agent, for the same reason the poll discipline moved out of prose: an unbounded "retry until it works" against a live client site is exactly the nondeterminism `scripts/poll_extraction.py` exists to remove.

### Step 2: Make the exhausted case reportable

In `agents/extract-transfer.md`, add a fourth `failure_phase` value beside the three at `:56`: `unsealed_consume_locked` — the container downloaded and unsealed successfully, but the consume never got the lock. It is the only failure phase where the local copy is complete and usable, which is precisely what the orchestrator's close-out needs to know so it does not tell the operator the transfer failed.

Keep `consumed: false` in the evidence block (`:63`) — the two carry different facts and both are wanted.

### Step 3: Tell the operator what a stranded artifact means

In `skills/clone/SKILL.md` and `skills/pull/SKILL.md`, at the consume paragraph (`:121` in both), add one sentence: a consume refused with `409` throughout its retry window leaves the sealed artifact on production until its TTL, and the next run's health-check sweep will clear it — the transfer itself is complete and the local copy is sound. Keep the two files' wording identical.

**Verify**: `uvx pytest -q` → exit 0. The consistency suites pin cross-surface wording; a failure there means the two SKILLs have drifted from each other or from the agent file.

### Step 4: Changelog

`CHANGELOG.md`, a `### Fixed` entry under `[Unreleased]`. State what the Extractor changed (both purging routes now take the per-job tick lock and answer `409 kntnt_extractor_locked` when it is held), what this client did before (nothing — it had no handling, and its own rule that an unconsumed job is always `FAILED` turned a narrow lock contention into a failed verdict on a finished multi-hour run), and what it does now. Say explicitly that the data was never at risk: the download and unseal precede the consume.

## Done criteria

ALL must hold:

- [ ] `uvx pytest -q` exits 0 with 962 passing (no test-count change expected — this is a documentation-surface change)
- [ ] `grep -rn "kntnt_extractor_locked" agents/ skills/` returns matches in all three files
- [ ] `grep -n "unsealed_consume_locked" agents/extract-transfer.md` returns one match
- [ ] `git diff --stat` shows no file under `scripts/` modified
- [ ] `git diff --stat` lists only the files in the In-scope list
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The drift check reports changes to any in-scope file.
- `~/Projects/kntnt-extractor/classes/Rest/Extractions_Controller.php` no longer returns `409 kntnt_extractor_locked` at the consume route, or the code string has changed. The server is the authority.
- The test count moves at all. This plan changes no Python and should change no count; a moved count means a consistency suite is parametrised over the wording you edited, which is fine only if you can say in one sentence which one and why.
- You conclude the retry should be unbounded, or should be moved into `scripts/`. Both are defensible directions and both are decisions for the repository owner — report rather than build.

## Maintenance notes

- **What a reviewer should scrutinise**: that the retry is bounded and the bound is written in the file, not left to the agent; that `429` is untouched; and that the exhausted case reports the local copy as sound rather than reporting the transfer as failed.
- **Deliberately deferred**: the same `409` on the cancel path used by the health-check stranded-job sweep. It is real and is named in the Out-of-scope list; it wants its own pass because it changes sweep semantics rather than close-out semantics.
- **If the Extractor ever makes the lock wait rather than refuse**, this retry becomes dead weight and should be deleted rather than left as harmless belt-and-braces — a retry against a route that no longer refuses hides a real error behind five silent attempts.
