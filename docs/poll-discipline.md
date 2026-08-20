# The poll discipline — canonical statement

Every loop in this engine that waits on a Kntnt Extractor job follows one discipline: the health check's preflight, the bootstrap in `discovery-classify`, and the main extraction, which the `clone` and `pull` orchestration runs itself rather than delegating (see *Pinned phrases — who owns the main extraction's poll*, below). This file is its **canonical statement**. The decisions themselves are recorded in [ADR-0018](./adr/0018-poll-discipline-and-two-chunk-preflight.md) with the field evidence that produced them; this is where the settled rules live in one piece.

## Why the rules are also restated elsewhere

A surface is loaded standalone into whatever context executes it. It cannot be trusted to follow a link mid-run, so `skills/clone/SKILL.md` §5 and `skills/pull/SKILL.md` §5 each restate the discipline **in full**, and `skills/clone/roles/discovery-classify.md` carries a compact form of it for the bootstrap loop it owns. That duplication is deliberate — a surface an agent loads alone must contain the whole rule set — and it is exactly why the wording drifts if nothing holds it together.

What is pinned, and what is not: **headings, hard rules, and the numeric literals are carried verbatim; the narrative around them is each surface's own voice.** A SKILL file explaining the discipline to an orchestrator and a role file instructing whoever executes it legitimately read differently, and forcing them word-for-word identical would make both worse. What may not differ is a rule's own statement — that is what drifts unnoticed.

This file is what holds it together. The phrases pinned below are the ones every restatement must carry verbatim, and `tests/test_poll_discipline_consistency.py` and `tests/test_poll_agent_single_verdict_consistency.py` read them **from here**. The numeric literals themselves live in `skills/clone/scripts/poll_extraction.py` — that is the binding, so an agent cannot re-derive the loop — and the consistency suite asserts these phrases match those constants. Changing a rule is one edit in the script, the matching edit here, and the matching edit in each surface; the tests then refuse the change until every surface has followed. Before this file existed the literals lived inside the test, which made a test file the source of truth for a product decision and left every rule stated only in prose free to drift — as it did: two agents came to state the same new ban in different words, and the binding that was supposed to catch that had to be loosened to accommodate both.

## The discipline

**Cadence and timeouts.** Poll every 15 s after a successful poll, with a 120 s per-request timeout. On a transport timeout, connection error, or 5xx, log it and retry after 30 s — 60 s from the second consecutive failure — resetting to the 15 s cadence on the next success. A single bad response is never failure. The cadence is not arbitrary: it matches the Extractor's default `tick_budget`, and on a detachable host every poll advances the job in-process after the response is sent, so polling is propulsion and is never backed off while polls succeed.

**Overall budgets.** 10 minutes for the preflight, 15 minutes for the bootstrap. The main extraction has no overall wall-clock budget — the stall window is the stop.

**What counts as an advance.** A state change, an increase in `progress.chunks_done`, or an increase in the sum `progress.tables_done + progress.files_done`. `chunks_done` (Extractor API version 6 and up) is the one that matters: the other two move only when a whole table or a whole file finishes, so a job slicing one large table looks exactly like a wedged one. A `queued` job carries no counters, so its stall clock runs on state alone. Against an Extractor below API version 6 the field is absent — fall back to the coarse counters, widen the stall window to 40 minutes, and say so in the run's output rather than reading an absent field as a stall. 40 minutes is not a guess: it is the value a live production run against an API-version-5 Extractor was manually widened to before it completed, on a 186-table site working through one large table where the coarse counters stood still for minutes at a time on a completely healthy job.

**Terminal conditions.** `state == "failed"`, a confirmed-vanished job, or no advance within the stall window — 10 minutes normally, widened to 40 minutes once `chunks_done` is observed absent. A preflight or bootstrap loop also fails on exhaustion of its own overall budget. Nothing else — any number of individual transport failures keeps the loop polling.

**How the loop is executed.** One blocking invocation of `scripts/poll_extraction.py` (`../clone/scripts/poll_extraction.py` from `pull`) that polls until it reaches a terminal verdict and exits, never one tool call per poll and never a loop the agent writes itself, and the agent returns exactly once with a verdict. The Application Password is passed in that one process's environment (`KNTNT_EXTRACTOR_APP_PASSWORD`), never on argv. The per-poll progress lines go to a log file under the run's scratchpad with `--log <path>`, so the loop is as quiet in a harness that runs it inline as it is inside a subagent's own context. See *Pinned phrases — the poll-owning subagents*, below.

## Pinned phrases — every surface stating the discipline in full

`skills/clone/SKILL.md` and `skills/pull/SKILL.md` must each carry every phrase below.

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

### coarse stall window

```text
40-minute stall window
```

### main-extraction budget

```text
the stall window is the stop
```

### confirmed-vanished rule, full form

A `404` on `GET /extractions/{id}` is terminal only when confirmed vanished. A server-side non-atomic `job.json` rewrite race returned a spurious `404` twice mid-job on a live production run while the job was alive and progressing ([kntnt-extractor#20](https://github.com/Kntnt/kntnt-extractor/issues/20)), so a single `404` is a transport-class fault.

```text
a confirmed-vanished job (a `404`, treated as a transport-class fault and retried under the existing 30 s / 60 s backoff, that also `404`s on re-poll with the id absent from `GET /extractions` — a single `404` is logged and retried, never terminal on its own, and polling continues within budget)
```

## Pinned phrases — the compact form

`skills/clone/roles/discovery-classify.md` carries the bootstrap loop's own budget and the compact confirmed-vanished rule rather than the full discipline.

### bootstrap budget

```text
15-minute
```

### confirmed-vanished rule, compact form

```text
a confirmed-vanished job (`404`, re-confirmed via `GET /extractions` and a second poll)
```

## Pinned phrases — the poll-owning subagents

`skills/clone/roles/discovery-classify.md` is the one role file that still owns a poll loop — the bootstrap's, bounded by its own 15-minute budget — and it must carry the two execution rules below. Both exist because one subagent, having already completed every call its phase needed, returned three times saying it was still waiting — ~55k tokens each, no evidence block — for want of any way to wait out a job taking minutes or to resume polling after a return. The verdict half of that pair binds every role, poll or no poll: a role that returns without one is read as `FAILED` whatever its prose claims.

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

## Pinned phrases — who owns the main extraction's poll

The main extraction's poll is the only wait in this engine with no overall budget, so it is the only one that can outlast the thing that started it. It is therefore not a role's to own: `skills/clone/SKILL.md` and `skills/pull/SKILL.md` run it themselves, as their own tracked background job, and must each carry every phrase below. The bootstrap poll in `skills/clone/roles/discovery-classify.md` is bounded by its own 15-minute budget and stays where it is.

Twice in production a subagent given the multi-hour wait returned without a verdict, and the second time it had detached the poll first — `poll-output.json` 0 bytes, no exit code ever written, and a job that went on to 13,459 files with nobody watching. The rule below is what a boundary looks like once instructing an agent not to cross it has failed twice.

### the ownership heading

```text
The main extraction's poll is the orchestrator's own work
```

### the never-delegate rule

```text
never delegated to a subagent and never detached from this session
```

### the job record written before the poll starts

```text
extract-job.json
```

### the file the poll's verdict is captured in

```text
extract-poll.json
```

### the file the poll's exit code is captured in

```text
extract-poll.exit
```

### the re-attach rule

```text
polling is read-only, so re-attaching to a job whose id you have costs nothing
```
