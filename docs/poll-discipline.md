# The poll discipline — canonical statement

Every loop in this engine that waits on a Kntnt Extractor job follows one discipline: the health check's preflight, the bootstrap in `discovery-classify`, and the main extraction in `extract-transfer`. This file is its **canonical statement**. The decisions themselves are recorded in [ADR-0018](./adr/0018-poll-discipline-and-two-chunk-preflight.md) with the field evidence that produced them; this is where the settled rules live in one piece.

## Why the rules are also restated elsewhere

A subagent is loaded standalone into its own context. It cannot be trusted to follow a link mid-run, so `skills/clone/SKILL.md` §5, `skills/pull/SKILL.md` §5, and `agents/extract-transfer.md` each restate the discipline **in full**, and `agents/discovery-classify.md` carries a compact form of it. That duplication is deliberate — a surface an agent loads alone must contain the whole rule set — and it is exactly why the wording drifts if nothing holds it together.

What is pinned, and what is not: **headings, hard rules, and the numeric literals are carried verbatim; the narrative around them is each surface's own voice.** A SKILL file explaining the discipline to an orchestrator and an agent definition instructing a subagent legitimately read differently, and forcing them word-for-word identical would make both worse. What may not differ is a rule's own statement — that is what drifts unnoticed.

This file is what holds it together. The phrases pinned below are the ones every restatement must carry verbatim, and `tests/test_poll_discipline_consistency.py` and `tests/test_poll_agent_single_verdict_consistency.py` read them **from here**. The numeric literals themselves live in `scripts/poll_extraction.py` — that is the binding, so an agent cannot re-derive the loop — and the consistency suite asserts these phrases match those constants. Changing a rule is one edit in the script, the matching edit here, and the matching edit in each surface; the tests then refuse the change until every surface has followed. Before this file existed the literals lived inside the test, which made a test file the source of truth for a product decision and left every rule stated only in prose free to drift — as it did: two agents came to state the same new ban in different words, and the binding that was supposed to catch that had to be loosened to accommodate both.

## The discipline

**Cadence and timeouts.** Poll every 15 s after a successful poll, with a 120 s per-request timeout. On a transport timeout, connection error, or 5xx, log it and retry after 30 s — 60 s from the second consecutive failure — resetting to the 15 s cadence on the next success. A single bad response is never failure. The cadence is not arbitrary: it matches the Extractor's default `tick_budget`, and on a detachable host every poll advances the job in-process after the response is sent, so polling is propulsion and is never backed off while polls succeed.

**Overall budgets.** 10 minutes for the preflight, 15 minutes for the bootstrap, 3600 s (`poll_max_wait_seconds`) for the main extraction.

**What counts as an advance.** A state change, an increase in `progress.chunks_done`, or an increase in the sum `progress.tables_done + progress.files_done`. `chunks_done` (Extractor API version 6 and up) is the one that matters: the other two move only when a whole table or a whole file finishes, so a job slicing one large table looks exactly like a wedged one. A `queued` job carries no counters, so its stall clock runs on state alone. Against an Extractor below API version 6 the field is absent — fall back to the coarse counters, widen the stall window, and say so in the run's output rather than reading an absent field as a stall.

**Terminal conditions.** `state == "failed"`, a confirmed-vanished job, no advance within the 10-minute stall window, or exhaustion of the loop's overall budget. Nothing else — any number of individual transport failures keeps the loop polling within its budget.

**How the loop is executed.** One blocking invocation of `scripts/poll_extraction.py` that polls until it reaches a terminal verdict and exits, never one tool call per poll and never a loop the agent writes itself, and the agent returns exactly once with a verdict. The Application Password is passed in that one process's environment (`KNTNT_EXTRACTOR_APP_PASSWORD`), never on argv. See *Pinned phrases — the poll-owning subagents*, below.

## Pinned phrases — every surface stating the discipline in full

`skills/clone/SKILL.md`, `skills/pull/SKILL.md`, and `agents/extract-transfer.md` must each carry every phrase below.

### poll cadence

```text
every 15 s
```

### per-request timeout

```text
120 s per-request timeout
```

### stall window

```text
10-minute stall window
```

### main-extraction budget

```text
3600
```

### confirmed-vanished rule, full form

A `404` on `GET /extractions/{id}` is terminal only when confirmed vanished. A server-side non-atomic `job.json` rewrite race returned a spurious `404` twice mid-job on a live production run while the job was alive and progressing ([kntnt-extractor#20](https://github.com/Kntnt/kntnt-extractor/issues/20)), so a single `404` is a transport-class fault.

```text
a confirmed-vanished job (a `404`, treated as a transport-class fault and retried under the existing 30 s / 60 s backoff, that also `404`s on re-poll with the id absent from `GET /extractions` — a single `404` is logged and retried, never terminal on its own, and polling continues within budget)
```

## Pinned phrases — the compact form

`agents/discovery-classify.md` carries the bootstrap loop's own budget and the compact confirmed-vanished rule rather than the full discipline.

### bootstrap budget

```text
15-minute
```

### confirmed-vanished rule, compact form

```text
a confirmed-vanished job (`404`, re-confirmed via `GET /extractions` and a second poll)
```

## Pinned phrases — the poll-owning subagents

`agents/discovery-classify.md` and `agents/extract-transfer.md` own a poll loop and must each carry the two execution rules below. Both exist because one subagent, having already completed every call its phase needed, returned three times saying it was still waiting — ~55k tokens each, no evidence block — for want of any way to wait out a job taking minutes or to resume polling after a return.

### the wait-in-one-loop heading

```text
Wait inside one poll_extraction.py invocation, never across returns
```

### the give-up line the loop must print

```text
gave up after N minutes
```

### the return-exactly-once heading

```text
You return exactly once, and only with a verdict
```

### the still-active-job consequence

```text
one-active-job rule
```

### the hard rule forbidding a verdictless return

```text
Never return without a `DONE` or `FAILED` verdict
```

### the hard rule forbidding a per-poll tool call

```text
Never spend a poll loop one tool call at a time
```
