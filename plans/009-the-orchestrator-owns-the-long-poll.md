# Plan 009: Give the long poll to the orchestrator, so it cannot be orphaned

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat <the SHA in "Planned at">..HEAD -- agents/extract-transfer.md skills/clone/SKILL.md skills/pull/SKILL.md docs/spec.md`

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none. **Do this before `plans/010`** — 010 is the guard that catches the symptom; this is the change that removes the cause. Both are worth having.
- **Category**: bug
- **Planned at**: commit `b79c98b`, 2026-08-19
- **Evidence**: two consecutive production clone runs, 2026-08-18 and 2026-08-19

## Why this matters

`agents/extract-transfer.md` tells its subagent to wait inside one blocking invocation and return exactly once with a verdict. On **both** production runs of this engine, it did not.

On 2026-08-19 the subagent returned with the words *"I'll pause here and wait for the background task notification when the poll reaches a terminal verdict"* — no evidence block, no `DONE`/`FAILED`, precisely the return its own definition forbids. Worse, it had already written a launcher script and started the poll **detached** before returning. The poll outlived the agent that owned it and would have reached a terminal verdict that reached nobody: the subagent was gone, and the orchestrator has no channel to a process it did not start.

The orchestrator recovered by hand — it queried `GET /extractions/{id}`, saw `state: running` with `chunks_done` climbing, killed the orphan, and restarted the poll under its own tracked background job. That run then completed: 48,578 files in 3 h 28 m. **Had it followed its own instructions instead, the close-out for a verdict-less return is `DELETE`, and it would have cancelled a healthy job two and a half hours in.**

The instruction is not the problem. Nothing structurally prevents an agent from backgrounding a long wait and returning, and an agent that does so is behaving reasonably by its own lights — a multi-hour blocking wait is exactly the shape a model is inclined to escape. Asking more firmly is not a fix; it has now failed twice under two different wordings.

## What this does not fix

- It does not make the extraction itself more reliable. The server was fine on both occasions; this is entirely about who watches it.
- It does not remove the need for `plans/010`. A subagent can still return without a verdict for other reasons, and the orchestrator still needs a rule for what to believe.
- It does not address `thumbnail-smoke-test` returning `FAILED` on findings that are not failures — a related but separate confusion of "the command exited non-zero" with "the clone is wrong". Named in "Maintenance notes".

## Current state

- `agents/extract-transfer.md` — the subagent definition. Its step 1 submits, step 2–3 poll to a terminal state, step 4 downloads and unseals, step 5 consumes. **One agent owns the whole span, including the multi-hour wait.**
- `skills/clone/SKILL.md` and `skills/pull/SKILL.md` — delegate the phase to that agent, and carry the close-out cases that act on its verdict.
- `scripts/poll_extraction.py` — blocks and returns one terminal verdict. It is correct and this plan does not change it; what changes is **who invokes it**.
- `docs/spec.md` — describes the phase and the delegation.

Read all four before writing. The agent file is the authority on the current split.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Suite | `uvx pytest -q` | exit 0, 962 passing |
| Consistency | `uvx pytest -q tests/test_agent_delegation_consistency.py` | exit 0 |
| Lint | `uvx ruff check <files you touched>` | exit 0 |

Never `ruff check .`.

## Scope

**In scope**:

- `agents/extract-transfer.md` — split at the poll boundary
- A second agent definition under `agents/` (create), if the split calls for one
- `skills/clone/SKILL.md`, `skills/pull/SKILL.md`
- `docs/spec.md`
- `docs/adr/0023-*.md` or the next free number (create)
- `tests/` — consistency coverage
- `CHANGELOG.md`

**Out of scope**:

- `scripts/poll_extraction.py`. It does its job. Do not move the stall window, the cadence, or any of its literals — rules R1 and R4 both bite there, and nothing in this run gives you a measurement to justify a new constant.
- The Extractor. Nothing server-side is involved.
- `agents/discovery-classify.md`. It behaved correctly on both runs — clean `DONE`, full evidence block, SHA256s that verified, `bootstrap_artifacts_deleted: true` confirmed independently. **The defect is specific to `extract-transfer`, not to delegation.** Do not "fix" an agent that is working.

## Git workflow

Trunk-based, straight to `main`. No push, no tag, no version bump.

## Steps

### Step 1: Move the blocking poll to the orchestrator

Restructure the phase so the long wait is owned by the skill itself, as its own tracked background job, rather than by a subagent:

1. **Submit** — a subagent (or the orchestrator directly) does `POST /extractions` and returns the job id and the run's key paths. Short, bounded, verdict-shaped.
2. **Poll** — the **orchestrator** invokes `scripts/poll_extraction.py` as its own background job and waits for it. Nothing is delegated across the multi-hour boundary, so nothing can be orphaned by a return.
3. **Download, unseal, consume** — a subagent, after `ready`. Also short and bounded.

Write the id to disk as soon as the submit returns, before the poll begins. That is what makes a lost poller a re-poll rather than a lost run: the orchestrator can always re-attach to a job whose id it has, and polling is read-only so re-attaching is free.

State the reasoning in the agent file, not just the mechanics. An executor who understands only the steps will re-merge the phases the next time it looks tidier.

### Step 2: Say why, where an agent will read it

In `agents/extract-transfer.md` (or its successors), record that the split exists because a subagent backgrounded the poll and returned twice, and that the previous remedy — instructing it not to — is known to have failed. An instruction whose history is invisible gets "simplified" back out.

### Step 3: Bind it

Add consistency coverage in the style of `tests/test_agent_delegation_consistency.py`: assert that no agent definition owning the poll also owns the submit, or whatever invariant the split you chose actually establishes. Pick an assertion that would have failed before this change — if you cannot write one, the split is not structural and you have written guidance rather than a fix, which is what already failed twice.

**Verify**: `uvx pytest -q` → exit 0.

### Step 4: Documentation round

`docs/spec.md`, both SKILLs' close-out sections, an ADR recording the decision and the two runs behind it, and `CHANGELOG.md`. The ADR must state what this does *not* fix, per this plan's own section.

## Done criteria

- [ ] `uvx pytest -q` exits 0
- [ ] `uvx ruff check <touched files>` exits 0
- [ ] A test exists that would have failed before the split
- [ ] `grep -rn "poll_extraction" agents/ skills/` shows the poll invoked by the orchestrator, not inside a subagent that also submits
- [ ] `scripts/poll_extraction.py` is unmodified (`git diff --stat` shows it absent)
- [ ] ADR written; `CHANGELOG.md` entry present; `plans/README.md` row updated

## STOP conditions

- The drift check reports changes to the agent definitions.
- You find yourself changing `poll_extraction.py`'s constants. Out of scope, and R1/R4 bind.
- You cannot write a test that would have caught the old shape. Report rather than shipping prose.
- The restructure would make the run *less* recoverable than today — e.g. the job id is not on disk before the poll starts.

## Maintenance notes

- **What a reviewer should scrutinise**: that the job id reaches disk before the poll begins; that no agent definition spans the multi-hour boundary; and that `discovery-classify` is untouched.
- **Related, deliberately not taken here**: `thumbnail-smoke-test` returned `FAILED` twice on findings that were not failures — two attachments whose originals are already 404 on production, and a sample URL the orchestrator itself built wrongly. Its `FAILED` is currently reachable from "a command exited non-zero" rather than "the clone is wrong", which is a lower bar than `extract-transfer`'s and a different defect.
- **The class of bug**: this is the second time a structural guarantee was written as an instruction to a model. The lesson worth carrying is that a boundary a model can cross cheaply will eventually be crossed, and the fix is to move the boundary rather than to reinforce the wording.
