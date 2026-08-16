# Plan 005: Close the cleanup handoff the subagents hand back and the SKILLs never discharge

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> This plan changes **Markdown orchestration prose only** — no Python. Its
> verification is therefore the consistency suites plus targeted `grep`s, not
> new unit tests. Read "Test plan" before you start so that does not surprise
> you.
>
> **Drift check (run first)**:
> `git diff --stat 947e28b..HEAD -- skills/clone/SKILL.md skills/pull/SKILL.md agents/extract-transfer.md agents/discovery-classify.md`

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `947e28b`, 2026-08-16

## Why this matters

Both poll-owning subagents shape their `FAILED` verdict specifically so the
orchestrator can clean up after them. `agents/extract-transfer.md:39`:

> An exhausted stall window is a `FAILED` carrying the job id, the elapsed wall
> time, and the last observed state and counters — never an intermediate report
> — **so the orchestrator can cancel the still-active job** instead of leaving
> one wedged against the plugin's one-active-job rule.

`agents/discovery-classify.md:45` says the same for the bootstrap loop
("so the orchestrator can consume or cancel the still-active job").

**The orchestrator never does it.** `DELETE /extractions/{id}` appears in
`skills/clone/SKILL.md` at exactly two places — `:69`, the *next* run's
stranded-job sweep, and `:123`, the prohibition against using it as the
happy-path close — and identically in `skills/pull/SKILL.md` at `:70` and
`:121`. There is no step anywhere that consumes or cancels after a `FAILED`
return. The subagents hand back a responsibility the receiving document does
not know it has.

Three leaks follow. The first two leave sealed production data published on a
live client site until TTL, which is precisely the window `§7` exists to keep
"to minutes". The third leaves a **cleartext** dump of real user and subscriber
rows on local disk with nothing scheduled to remove it.

**Field evidence on the third, gathered 2026-08-16 from the paused
`safeteam.se` run's scratchpads:** it did **not** fire. `bootstrap.sql`,
`bootstrap.key` and `bootstrap.container` were all absent, while
`unseal_config.json` still named them — the bootstrap succeeded, so the success
path cleaned up as designed. So this is real in code and unproven in practice.
That matters for how you scope it: the failure path is the one about to be
exercised deliberately, because the `safeteam.se` clone is being redone from
scratch.

## Current state

### Leak 1 — a failed unseal never consumes

`agents/extract-transfer.md:64`:

> An unseal that fails, or a job that never reached a consumed state on the
> happy path, is always `FAILED`, whatever the poll reported.

The subagent returns. The artifact is still published on production. Note the
sequence that makes this decidable: the unseal happens **after** the download
(`agents/extract-transfer.md:44`), so when an unseal fails a complete local
copy of the container already exists — and consuming the production artifact
destroys nothing that is not already on this machine.

### Leak 2 — an exhausted stall window never cancels

The subagent returns `FAILED` with the job id, expecting a cancel that never
comes. The job stays active, holding the plugin's one-active-job rule against
the operator's next attempt. The next run's §1.3 sweep is the only thing that
clears it — and per the Extractor side, `GET /extractions` lists only
non-terminal jobs, so once that job later *fails* server-side it becomes
invisible to the sweep as well.

### Leak 3 — a failed bootstrap deliberately leaves a cleartext dump

`agents/discovery-classify.md:51`, at the end of the bootstrap step:

> On a `FAILED` bootstrap, leave the dump in place for diagnosis —
> `bootstrap_parse.py` only deletes after a successful parse.

That is a **deliberate decision**, not an oversight, and this plan does not
reverse it. But the same file, at `:84`, states the hard rule it is an
exception to, and `skills/clone/SKILL.md:165` / `skills/pull/SKILL.md:167`
describe §11's sweep as "belt-and-braces, not the primary mechanism" — a sweep
that only runs when the run reaches §11, which by definition a failed
discovery does not. So the exception has no expiry: nothing deletes the dump,
nothing tells the operator it exists, and it holds real user and subscriber
rows.

### What the Extractor side is fixing, and what it is not

Settled on the Extractor side (its plan 013), so that this plan does not
duplicate it:

- `consume` and `cancel` will take the per-job tick lock the sweep and driver
  already take, closing the orphaned-artifact race.
- The sweep will additionally reclaim an artifact in the served directory with
  no corresponding job record.
- `GET /extractions` gains a `state` query parameter admitting **terminal**
  jobs, owner-scoped exactly as today — which is what finally answers "is there
  sealed data of mine still on this site".

**None of that fixes leak 3**, which is entirely local, and none of it removes
the value of closing leaks 1 and 2 promptly rather than at TTL.

**Do not make this plan depend on the `state` parameter.** It must work
against production's current Extractor (0.4.0, API version 5). Step 3 adds an
optional enhancement that uses it *when available*, written so its absence
costs nothing.

### Repo conventions

- These four files are dense, declarative British English. Each instruction
  says what to do and why in the same breath.
- Markdown prose stays on one physical line per paragraph — never hard-wrap at
  a column width.
- Several consistency suites read these files
  (`tests/test_agent_delegation_consistency.py`,
  `tests/test_poll_discipline_consistency.py`,
  `tests/test_poll_agent_single_verdict_consistency.py`,
  `tests/test_api_version_ceiling_consistency.py`). Pinned phrases must survive
  verbatim; a green suite is your check.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full test suite | `uvx pytest -q` | exit 0 |
| Consistency suites | `uvx pytest -q -k consistency` | exit 0 |

Run from `/Users/thomas/Projects/kntnt-wp-skills`. No Python changes, so no
`ruff` run is required unless you touch a `.py` file — in which case lint only
that file.

## Scope

**In scope**:

- `skills/clone/SKILL.md`, `skills/pull/SKILL.md` (modify — add the close-out
  step; amend §11's cleanup)
- `agents/extract-transfer.md`, `agents/discovery-classify.md` (modify — make
  the evidence block carry what the close-out needs)
- `docs/spec.md` (modify — the failure-path guarantee)
- `docs/adr/0022-close-the-exposure-window-on-every-failure-path.md` (create)
- `CHANGELOG.md` (modify)

**Out of scope**:

- **Reversing `agents/discovery-classify.md:51`.** Keeping the dump for
  diagnosis is a deliberate decision with real value on exactly the failure
  path about to be exercised. This plan bounds it; it does not delete it.
- **Auto-destroying a completed extraction.** See Step 1's third case: when a
  *download* fails, the production artifact is the only copy of a possibly
  multi-hour extraction. Consuming it automatically to shrink an exposure
  window would destroy hours of work to save minutes of exposure. That case
  reports and asks; it never acts unilaterally.
- `scripts/` — no helper changes. The close-out is REST calls the orchestrator
  already knows how to make.
- The Extractor's `state` parameter as a *requirement*. Optional enhancement
  only (Step 3).
- Anything in the adaptation family (host-limit raising, budget halving, the
  attempt counter, the floor).

## Git workflow

- Trunk-based: commit straight to `main`. No branch, no PR.
- Message style: one imperative sentence, no prefix. E.g.
  `Close the exposure window when a transfer phase fails`.
- Do NOT push and do NOT tag.

## Steps

### Step 1: Add the close-out step to both SKILLs

Add a new subsection to `skills/clone/SKILL.md` and `skills/pull/SKILL.md`,
placed immediately after each file's §7 ("Close the exposure window") and
covered by the same heading, titled so it is unmissable — e.g.
**"Closing out a failed phase"**.

It must state that **any** `FAILED` return from `discovery-classify` or
`extract-transfer`, and any abort the orchestrator itself takes after a job has
been submitted, is followed by a close-out before the run stops — and that a
run may never end with a job the orchestrator submitted left unaccounted for.

Specify the three cases explicitly, because the right action genuinely differs
and an executor left to infer it will get the third one wrong:

1. **The job never reached `ready`** — a `failed` state, a confirmed-vanished
   job, or an exhausted stall window. `DELETE /extractions/{id}` to cancel.
   There is no artifact to preserve and the job otherwise holds the
   one-active-job rule against the next attempt. This is the case
   `agents/extract-transfer.md:39` and `agents/discovery-classify.md:45`
   already expect the orchestrator to handle.
2. **The job reached `ready` and the container downloaded, but the unseal
   failed** — `POST /extractions/{id}/consume`. A complete local copy already
   exists (the download precedes the unseal,
   `agents/extract-transfer.md:43-44`), so consuming destroys nothing that is
   not on this machine, and it closes the exposure window on a live client
   site. Report the local container's path so the failure stays diagnosable.
3. **The job reached `ready` but the download failed or never ran** — do
   **not** act unilaterally. The production artifact is the only copy of what
   may be hours of extraction. Report the job id, its state, that the artifact
   is still published, and that the plugin's TTL will reclaim it; then offer
   consuming it as its own accept-or-override gate. Under `--yes`, with no
   operator present to own the choice, do not consume — print the same
   information for the record. Losing a completed extraction to a reflex is a
   worse outcome than a bounded, reported, TTL-terminated exposure window.

State the standing rule after the three cases: the close-out is best-effort and
never masks the original failure — a close-out call that itself fails is
reported alongside the original cause, and the run still stops on the original
cause. A cleanup error must never become the headline.

Cross-reference §1.3's stranded-job sweep as the backstop, and say plainly why
it is not sufficient on its own: it runs only on the *next* run, and it lists
only non-terminal jobs, so a job that has since failed server-side is invisible
to it.

Keep §7's existing prohibition intact: `DELETE` is for cancelling, never the
happy-path close. Case 1 is a cancel; case 2 is a consume. That distinction is
load-bearing and the new text must not blur it.

**Verify**: `uvx pytest -q` → exit 0.

### Step 2: Make the evidence blocks carry what the close-out needs

The orchestrator can only close out a job it can name. Both subagents already
return the job id on the happy path; make it explicit that they return it on
the failure path too, and add the one field that decides between cases 2 and 3.

In `agents/extract-transfer.md`'s evidence block (around `:53-62`, which
already lists `consumed`), require on **`FAILED`**:

- the job id, whenever a job was submitted at all;
- the last observed job `state`;
- the phase the failure occurred in — enough to distinguish "never reached
  ready", "downloaded but unseal failed", and "ready but download failed";
- the downloaded container's local path when a download completed, so the
  orchestrator can report it in case 2 and so a retry does not re-download.

In `agents/discovery-classify.md`'s evidence block (around `:62-71`), require on
**`FAILED`**: the bootstrap job id and last observed state, plus — since
`bootstrap_artifacts_deleted` will be `false` by design on this path — the
**path of the cleartext dump left behind**, so Step 4 can report it.

Both files already say the evidence block is returned "always, whether `DONE`
or `FAILED`" (`agents/discovery-classify.md:62`). This step makes its
failure-path contents specific rather than implied.

**Verify**: `uvx pytest -q` → exit 0. `tests/test_agent_delegation_consistency.py`
binds the SKILLs to the agent definitions; a green suite means the two sides
still agree.

### Step 3 (optional, additive): use the terminal-job listing when it exists

The Extractor's plan 013 adds a `state` query parameter to `GET /extractions`
admitting terminal jobs, owner-scoped. When available, it lets the health check
answer "is there sealed data of mine still on this site" rather than only "is
there a job blocking me".

Add to §1.3 in both SKILLs: after the existing non-terminal sweep, if the
Extractor supports the parameter, additionally list terminal jobs and **report**
any that still hold an artifact — report only, never cancel or consume a
terminal job the sweep did not create, since it may be another operator's or a
deliberately retained diagnostic.

Write it so that an Extractor without the parameter costs nothing: the extra
listing is skipped and the sweep behaves exactly as today. **Production runs
0.4.0 and will not have it.** Do not make any part of §1.3 conditional on it
succeeding.

If the parameter's shape is not yet settled when you execute this plan, **skip
Step 3 entirely** and note the skip in `plans/README.md`. Steps 1, 2 and 4 stand
alone and deliver the whole of the fix that does not depend on the server.

**Verify**: `uvx pytest -q` → exit 0.

### Step 4: Bound the cleartext bootstrap dump

Do not reverse the diagnostic exception at `agents/discovery-classify.md:51`.
Bound it, in three edits:

1. **`agents/discovery-classify.md:51`** — keep the exception and add why it is
   safe to keep: the dump is retained *because* the orchestrator is required to
   report and clear it, naming that requirement so the exception is not read as
   fire-and-forget.
2. **Both SKILLs, in the new close-out subsection from Step 1** — on a `FAILED`
   `discovery-classify` that left a dump, report its **exact path** and state
   plainly what it contains: a cleartext dump including real user rows and, when
   a recognised CRM was carried, real subscriber rows. Then delete it before the
   run ends, unless the operator explicitly chooses to keep it for diagnosis —
   an accept-or-override gate, defaulting to **delete**. Under `--yes`, delete
   without asking and say so in the record: an unattended run has no operator to
   read a diagnostic, and leaving production personal data on disk unattended is
   the worse default.
3. **Both SKILLs' §11** (`skills/clone/SKILL.md:165`,
   `skills/pull/SKILL.md:167`) — the cleanup sweep currently describes itself as
   belt-and-braces for artifacts a subagent left behind. Add that it is reached
   only by a run that completes, so the close-out subsection — not §11 — is what
   covers the failure path.

**Verify**: `uvx pytest -q` → exit 0.

### Step 5: Pay the documentation round

1. **`docs/adr/0022-close-the-exposure-window-on-every-failure-path.md`**
   (create). Read `docs/adr/0018-poll-discipline-and-two-chunk-preflight.md`
   first and match its structure. Record the decision — every submitted job is
   accounted for before the run stops, by cancel, by consume, or by an explicit
   reported decision — and the rejected alternatives: *always consume on
   failure* (rejected: destroys a completed multi-hour extraction to save
   minutes of a TTL-bounded window); *always leave it to TTL* (rejected: the
   status quo, and it leaves sealed production data on a live client site for
   the whole TTL while the operator is told nothing); *delete the diagnostic
   bootstrap dump unconditionally* (rejected: it is genuinely useful on exactly
   the failure path about to be exercised — bound it and report it instead).
   Record the consequence that a close-out failure never masks the original
   cause.
2. **`docs/spec.md`** — the transfer engine's failure behaviour. Add that a run
   which aborts after submitting a job accounts for that job before stopping,
   and that a failed discovery reports and clears its cleartext bootstrap dump.
3. **`CHANGELOG.md`** — an entry under `## [Unreleased]` → `### Fixed`, in the
   register of the entries already there: name the concrete gap (the subagents
   shaped a `FAILED` verdict for a cleanup the orchestrator was never told to
   perform), what changed, and the ADR link. Do not create a version heading and
   do not bump any version.

**Verify**: `uvx pytest -q` → exit 0.

## Test plan

**No new unit tests, and that is a deliberate limitation you should understand
rather than work around.** This plan changes orchestration prose — the
"human-verified residual" both SKILLs describe in their *Testing note*. Nothing
in these files reaches a live site during the automated suite, and the repo does
not simulate a failed transfer phase.

What actually verifies this plan:

1. **The consistency suites** (`uvx pytest -q -k consistency`) — they bind the
   SKILLs and the agent definitions to each other and to the pinned poll
   literals. They catch a pinned phrase broken by your edits. They do **not**
   check that the new instruction is correct.
2. **Targeted `grep`s** in the done criteria, which check the instruction is
   present in every file that needs it and that §7's `DELETE`/`consume`
   distinction survived.
3. **The operator's manual end-to-end residual** — a clone followed by a pull
   against a real site, before release.

If you want one thing to hold this in code later, the honest candidate is a new
consistency suite pinning the close-out's three cases across both SKILLs and
both agent files the way `tests/test_poll_discipline_consistency.py` pins the
poll discipline — with the canonical statement in a document, not in the test.
**Do not build it as part of this plan**; note it as a follow-up. The poll
discipline earned its canonical document only after its wording had drifted
across four surfaces, and pre-building that machinery for a rule with one
statement would be the premature version of the same idea.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `uvx pytest -q` exits 0, with no fewer tests than before
- [ ] `grep -c 'DELETE /extractions' skills/clone/SKILL.md` returns at least 3 (was 2: the §1.3 sweep and the §7 prohibition)
- [ ] Same for `skills/pull/SKILL.md`
- [ ] `grep -n "Closing out a failed phase" skills/clone/SKILL.md skills/pull/SKILL.md` matches in both
- [ ] `grep -n 'never the happy-path close' skills/clone/SKILL.md skills/pull/SKILL.md` still matches in both (§7's distinction survived)
- [ ] `grep -rn 'cleartext' skills/clone/SKILL.md skills/pull/SKILL.md` matches in both (leak 3 is reported to the operator)
- [ ] `grep -n 'leave the dump in place for diagnosis' agents/discovery-classify.md` still matches (the deliberate decision was bounded, not reversed)
- [ ] `test -f docs/adr/0022-close-the-exposure-window-on-every-failure-path.md` exits 0
- [ ] `git diff --stat -- scripts/ tests/` is empty
- [ ] `git status --short` lists only files from the "In scope" list
- [ ] `plans/README.md` status row for 005 updated, noting whether Step 3 was done or skipped

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows any of the four files changed since `947e28b` in the
  passages quoted in "Current state".
- Any consistency suite fails after an edit. A pinned phrase has been broken,
  and the fix is to restore the phrase, never to relax the assertion.
- You conclude the close-out needs a helper script. It does not: these are
  REST calls the orchestrator already makes elsewhere in the same file. A
  helper would be a larger change with a different review.
- You find yourself about to make case 3 consume automatically. Re-read the
  scope note: that trade destroys a completed extraction to save a bounded,
  reported exposure window.
- You find yourself about to delete the diagnostic bootstrap dump
  unconditionally at `agents/discovery-classify.md:51`, rather than bounding
  and reporting it.
- The `state` parameter's shape is unsettled — skip Step 3 and say so, rather
  than guessing at a query contract.

## Maintenance notes

- **What a reviewer must scrutinise**: that the three cases in Step 1 stayed
  distinct, and specifically that case 3 still asks rather than acts. The
  compression to "on failure, consume" is the tempting simplification and it
  is the wrong one.
- **What will interact with this**: the Extractor's plan 013. Once server-side
  reclamation is reliable and terminal jobs are listable, leaks 1 and 2 become
  belt-and-braces rather than the primary mechanism — the same relationship
  §7's explicit consume already has with TTL. That is a reason to keep this
  code, not to remove it: the client closing its own window in seconds is
  worth having even when the server would close it eventually.
- **What this does not cover**: an orchestrator that dies outright — a crashed
  session, a killed terminal — cannot run a close-out at all. The §1.3 sweep
  and the plugin's TTL remain the only answer there, and that is inherent
  rather than fixable here.
- **Field status of leak 3**: unproven in practice as of 2026-08-16 — the
  paused `safeteam.se` run's bootstrap succeeded and cleaned up. It is real in
  code and its path is the one the redone clone will exercise deliberately, so
  do not downgrade it on the strength of never having been observed.
