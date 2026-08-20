# A phase fails on a defective copy, never on a non-zero exit

The `thumbnail-smoke-test` role returned `FAILED` when **a command exited non-zero**, rather than when **the clone was wrong**. That is a materially lower bar than the one `extract-transfer` uses, and it fired twice on findings that were not failures during a single production clone (issue #59).

The bar was low for two reasons, and both were structural rather than careless. The phase runs three steps and only one of them looks at the copy at all: the thumbnail regeneration rebuilds *local derivatives* that were deliberately never transferred ([ADR-0011](0011-metadata-driven-thumbnail-regeneration.md)), the search-index rebuild rebuilds a local index that was deliberately never transferred ([ADR-0015](0015-search-index-excluded-and-rebuilt-locally.md)), and neither can produce evidence about what production sent. And `skills/clone/scripts/smoke_test.py` — the step that *does* look at the copy — answered `1` for two opposite conditions: its report carries a `fail`, and it could not read its own expectations file. A verdict read off "non-zero" could not tell those apart, because the exit code did not.

**A false `FAILED` is not free.** The close-out for a failed phase is destructive, and an operator who learns to discount a verdict stops reading it — at which point the verdict has negative value, not merely no value.

## Decision

A phase returns `FAILED` on evidence that the copy is defective, and on nothing else. Everything else it finds is an **anomaly**: reported in full, and never a run condemned.

`smoke_test.py` answers with three exit codes rather than "zero or not": `0` (every activated check passed), `1` (the checks ran and the report carries at least one `fail`), `2` (it could not run at all — a missing clone directory, an unreadable or non-object expectations file, a malformed invocation, or a probe that raised). `1` is the only exit that says anything about the copy, and it is the only one that may become a `FAILED`. The `--generate` mode answers `2` on a malformed envelope for the same reason: it inspects no copy, so nothing it does can be evidence that one is defective.

The role's verdict follows mechanically: `status` is `FAILED` **iff `scripts/smoke_test.py` exits `1`**. The role file carries the classification as a table — every non-zero exit its three steps can provoke, each in one bucket with a stated reason — and the table's last row is the catch-all: **an exit the table cannot place is an anomaly, never a failure.** Defaulting an unknown to `FAILED` is what produced this bug in the first place.

The vocabulary is unchanged, deliberately. There are still exactly two verdicts, `DONE` and `FAILED`, exactly as `extract-transfer` has them, and an anomaly is not a third: it rides in the evidence block's existing `anomalies` list beside a `DONE`, which is the same shape `extract-transfer` already uses for a finding that is real but not fatal — `skipped_files`, `restricted_paths`, and the normalisation collisions of [ADR-0025](0025-a-destination-filesystem-collision-is-reported-never-fatal.md).

**The report does not get quieter.** A step-level anomaly is named in the evidence block with the same specificity a failure would have had — `regenerate_exit`, `reindex_exit`, `smoke_test_could_not_run`, each with the wrapper's own diagnostic and log path. The point of this decision is not a calmer agent; it is one that stops saying "the copy is wrong" when what it means is "a command I ran returned 1".

## Rejected alternatives

- **Keep the bar and let the operator sort it out.** The status quo. It costs a destructive close-out on a healthy copy, and it trains the reader to ignore the one signal this phase exists to produce.
- **Add a third verdict — `DEGRADED`, `WARN`, or similar.** Every consumer of an evidence block would have to learn it, both `SKILL.md` files would have to route it, and it buys nothing: the engine already has a channel for a finding that is not a verdict, and this decision uses it.
- **Leave `smoke_test.py`'s exit code alone and have the role infer the case from whether stdout carried a report.** It works, and it puts the classification back where it just failed — in a reader's judgement, at the moment the reader is under pressure. It also leaves the ambiguous contract standing for every other caller, the operator running the script from a terminal included.
- **Promote a failed thumbnail regeneration to `FAILED`.** WP-CLI reports a regeneration failure as a lump, so a non-zero exit cannot even be attributed to an attachment; and what failed is a derivative this run generates locally, not a byte production sent. `--regenerate-all` is the operator's repair for a gap there, and the smoke test is what judges the copy.
- **Promote a failed search-index rebuild to `FAILED`.** ADR-0015 already settles the empty-index case: the index is excluded from transfer, rebuilt locally, and its absence is a documented degraded state with a manual repair. A rebuild that exited non-zero leaves exactly the state the `cli-unavailable` fallback leaves, and that fallback has never been a failure.
- **Treat a smoke test that could not run as a `FAILED`, on the ground that the role did not finish its work.** It reads well against `extract-transfer`'s "`FAILED` says this role did not finish", and it is the exact substitution this decision exists to refuse: nothing observed the copy, so the run learned nothing that could condemn it. An unreadable expectations file is the caller's input, not the copy's fidelity.

## Consequences

- **`1` now means exactly one thing across the whole helper**, so a shell that tests `$?` gets a usable answer without reading stdout. `2` is the caller's or the environment's problem; `1` is the copy's.
- **The bar is enforced on both halves.** `tests/test_smoke_test.py` pins the script's exit-code behaviour, and `tests/test_smoke_test_verdict_bar.py` pins the classification table and the prose that reads it, so the code half cannot stand while the prose an agent executes drifts back to "non-zero means failed".
- **Issue #60 consumes this vocabulary rather than inventing its own** — a source/clone disagreement over derived sample URLs is an anomaly by this decision, not a failure.
- **A residual, deliberately untouched: a check whose own probe fails still reports `fail`.** If DDEV is down, `ddev wp core version` fails and `check_core_version` reports `fail`, so a run against a stopped project can still reach `FAILED` on a copy nobody has actually examined. That is a question about what an individual check reports, not about how the phase judges what was reported, and this decision changes only the latter.
- **Nothing about the close-out for a genuinely failed phase changes.** What changes is how much rarer, and how much better-earned, that verdict now is.
