# Plan 010: Let the job's own state outrank a subagent's verdict, before any close-out acts

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. When done, update the status row in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat <the SHA in "Planned at">..HEAD -- skills/clone/SKILL.md skills/pull/SKILL.md agents/extract-transfer.md docs/spec.md`

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none. Pairs with `plans/009` — that one removes the cause, this one makes the symptom survivable. **This is the smaller and it is the one that saved a run.**
- **Category**: bug
- **Planned at**: commit `b79c98b`, 2026-08-19
- **Evidence**: production clone runs, 2026-08-18 and 2026-08-19

## Why this matters

Two rules combine into a destructive one that neither states on its own.

`agents/extract-transfer.md` says a result without an evidence block is `FAILED` on the first occurrence. The close-out in both SKILLs maps a `FAILED` whose stall window was exhausted to **`DELETE /extractions/{id}`** — cancel the job. Separately those are both defensible: the first keeps a subagent honest, the second cleans up a wedged job.

Together they mean a subagent that returns **nothing** — no verdict, no evidence, no claim about the job at all — can route the orchestrator onto the branch that destroys a healthy extraction. A verdict-less return looks like the least informative thing possible, and the close-out treats it as the most specific.

This is not hypothetical. It happened on both production runs. On 2026-08-19 the subagent returned with no evidence block after two and a half hours; the job was `running` with `chunks_done` climbing the whole time and went on to complete all 48,578 files. **The only thing between that run and a `DELETE` was that the orchestrator queried the job by hand first, on its own initiative, contrary to the written close-out.**

The fix is one sentence of ordering. It costs nothing, it is mechanically checkable, and it is the single step that has now saved a multi-hour run twice.

## What this does not fix

- It does not stop subagents returning without verdicts — that is `plans/009`.
- It does not make a genuinely wedged job easier to detect. A job that really is stuck still looks `running`; this plan only stops a *healthy* one being destroyed on a subagent's silence.
- It adds a round trip before every failure close-out. That is the intended cost.

## Current state

Read these before writing:

- `agents/extract-transfer.md` — the "missing evidence block is `FAILED`" rule, and the `failure_phase` values the close-out branches on.
- `skills/clone/SKILL.md` and `skills/pull/SKILL.md` — the close-out cases. Case 1 (exhausted stall window → `DELETE`) is the destructive branch; case 2 (downloaded but unseal failed → `consume`) is the one that must stay intact, since consuming after a successful download destroys nothing that is not already local and closes the exposure window on a live client site.
- `docs/adr/0022-*.md` — the close-out's own decision record.

The distinction this plan turns on: **a `FAILED` verdict and an absent verdict are different inputs**, and today they reach the same branch.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Suite | `uvx pytest -q` | exit 0, 962 passing |
| Consistency | `uvx pytest -q tests/test_agent_delegation_consistency.py tests/test_health_check_sweep_order.py` | exit 0 |

## Scope

**In scope**: `skills/clone/SKILL.md`, `skills/pull/SKILL.md`, `agents/extract-transfer.md`, `docs/spec.md`, `docs/adr/` (amend 0022 or add a new one), `tests/`, `CHANGELOG.md`.

**Out of scope**:

- The `DELETE` case itself. A genuinely wedged job should still be cancellable; this plan changes *when* that branch is reached, never what it does.
- Case 2's `consume` after a failed unseal. Leave it exactly as it is — it is correct, and weakening it would widen the exposure window ADR-0022 exists to close.
- `scripts/poll_extraction.py`.
- The Extractor.

## Git workflow

Trunk-based, straight to `main`. No push, no tag, no bump.

## Steps

### Step 1: Make the job's state authoritative

In both SKILLs' close-out sections, put one rule ahead of the case selection:

> On any `FAILED` verdict **or any absent or malformed verdict**, re-query `GET /extractions/{id}` before choosing a close-out case. The job's own reported state outranks the subagent's claim. If it reports `running` with progress that has advanced since the last observation, the subagent's result is unreliable and the **job is not** — do not select a close-out case at all; recover the poll and continue.

Then state, in the same place, that an absent verdict is **not** evidence of an exhausted stall window. That inference is what routes silence onto the destructive branch, and it is wrong: silence carries no information about the job.

Keep both files' wording identical.

### Step 2: Say it where the subagent's rule lives

In `agents/extract-transfer.md`, beside "a result without an evidence block is `FAILED`", add that this verdict binds the **subagent's** work, not the job's state, and that the orchestrator resolves the difference by asking the server. Without this, the two documents still read as contradicting each other and a future reader will pick one.

### Step 3: Bind the ordering

Add a consistency test asserting that both SKILLs carry the re-query rule ahead of their close-out cases. The existing consistency suites are regex-over-Markdown by design and honest about it — model the new one on them, and do not pretend it binds behaviour.

**Verify**: `uvx pytest -q` → exit 0.

### Step 4: Documentation round

Amend ADR-0022 (or write a new ADR that names it) with the ordering and the two runs that motivated it. Add a `CHANGELOG.md` entry under `[Unreleased]` stating the concrete cost: a healthy 2.5-hour extraction was one written instruction away from being cancelled, twice, and only an unwritten manual check prevented it.

## Done criteria

- [ ] `uvx pytest -q` exits 0
- [ ] `grep -c "GET /extractions/{id}" skills/clone/SKILL.md skills/pull/SKILL.md` shows the re-query rule in both
- [ ] A test asserts the rule precedes the close-out cases
- [ ] Case 2's `consume` is textually unchanged (`git diff` shows no edit to it)
- [ ] ADR amended; `CHANGELOG.md` entry present; `plans/README.md` row updated

## STOP conditions

- The drift check reports changes to the close-out sections.
- You find yourself changing what the `DELETE` case does, rather than when it is reached.
- You conclude case 2's `consume` should also wait for a re-query. It should not — the download already succeeded, the local copy is complete, and delaying the consume widens an exposure window on a live client site.

## Maintenance notes

- **What a reviewer should scrutinise**: that the rule covers *absent* verdicts and not only `FAILED` ones — the absent case is the one that bit twice; and that the two SKILLs stayed identical.
- **Why this is worth having even after `plans/009`**: 009 removes one way a verdict goes missing. It does not remove every way, and this rule costs one `GET`.
- **The general shape**: when a local claim and a remote authority disagree about remote state, the remote authority wins. That is worth stating once in `docs/spec.md` rather than re-deriving per phase.
