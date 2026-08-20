# thumbnail-smoke-test

Every relative path below is relative to the `clone` skill directory — the parent of the `roles/` directory this file sits in — regardless of which skill's run is executing it or where the skills were installed. A `scripts/<name>.py` path is therefore one of the engine helpers `clone` ships, and `../mkwp/scripts/classify.py` the classifier the sibling `mkwp` skill owns. Whoever executes this role joins that anchor to the paths below itself; nothing here is read against the working directory a run happens to start in.

Whoever runs this role runs it the same way: a Claude Code subagent, a task another harness spawned, or the orchestrating agent executing these instructions inline when its harness can spawn neither. The tier decides who does the work and where the output lands, never what the work is or what it must return.

## Role

You perform the thumbnail-regeneration, search-index-reindex, and/or smoke-test phase of a `kntnt-wp-skills` `clone` or `pull` run — the tail end of the localisation, where WP-CLI's per-image progress output and cosmetic deprecation notices would otherwise flood the orchestrator's context for no decision-relevant reason. You are run once per sub-task, or once for all three together when the orchestrator finds that convenient, and run to completion; you can never pause to ask the operator anything.

## Inputs

The task prompt tells you which sub-tasks to run:

- `regenerate` — `true`/`false`, and if `true`, whether it is the full-library pass (clone, or `--regenerate-all`) or the metadata-driven delta (pull), with the affected attachment IDs.
- `reindex` — `true`/`false`. `true` only when discovery's active-plugin list carried a search-index plugin (issue #10, [ADR-0015](https://github.com/Kntnt/kntnt-wp-skills/blob/main/docs/adr/0015-search-index-excluded-and-rebuilt-locally.md)); the orchestrator has already made that determination from discovery, so you never need to inspect the plugin list yourself. When `true`, also carries `plugin` — `relevanssi` or `searchwp` — naming which family's probe/run pair to use. `false` means no active search-index plugin was found; report the `not-present` outcome without running anything.
- `smoke_test` — `true`/`false`, and if `true`, `clone_dir` (the local site's root) and `expectations` — the object the orchestrator assembled from the resolved plan and live discovery (core version, DDEV PHP/DB pins, table prefix, the local DDEV URL, entity counts, the resolved plan's table split — folded through `rebuiltSearchIndexTables` when the reindex sub-task actually rebuilt a table, so a genuinely rebuilt index is never asserted empty — the excluded drop-ins, the expected object-cache drop-in state, the smoke-test URL list drawn from the copy's own database — including the localised subpage when a multilingual plugin is active — the expected active-plugin count, and, at pull, the rollback-backup expectation) — exactly the shape `scripts/smoke_test.py` consumes as its expectations file.
- `scratchpad_dir` — where to write the expectations file and, for a genuine anomaly, supporting evidence (the script's full JSON report) rather than inlining it.

## What to do

1. If `regenerate` is `true`: run `uv run scripts/wp_quiet.py regenerate --dir <clone_dir> --log <scratchpad_dir>/regenerate.log`, adding `--ids <comma-separated attachment ids>` for the metadata-driven delta at pull and omitting it for the full-library pass at clone (`--regenerate-all`). The wrapper runs `ddev wp media regenerate` itself, keeps every per-image progress line and cosmetic warning in that log file, and prints one JSON summary: the exit code, the regenerated-attachment count (`null` when WP-CLI's own tally could not be read), the log's path and line count, and any genuine `Error:` or fatal line it found. Take those fields as they come — never re-derive a count by reading the log back.
2. If `reindex` is `true`: run `uv run scripts/wp_quiet.py reindex --dir <clone_dir> --log <scratchpad_dir>/reindex.log --plugin <plugin>` (`relevanssi` or `searchwp`, per the `plugin` input). The wrapper owns the probe-then-run pair and reports which of the three outcomes happened: it probes `ddev wp cli has-command "<plugin> index"` and, on success, runs the family's rebuild command — `ddev wp relevanssi index` for `relevanssi`, `ddev wp searchwp index --rebuild` for `searchwp` — recording its exit code with outcome `rebuilt`. On probe failure it records outcome `cli-unavailable` and leaves the index untouched — **never** a `wp eval` workaround or any other undocumented internal. If `reindex` is `false`, omit `--plugin` and the wrapper records outcome `not-present` without running any command, since the orchestrator already determined no active search-index plugin exists.
3. If `smoke_test` is `true`: write `expectations` to `<scratchpad_dir>/smoke-test-expectations.json`, then run `uv run scripts/smoke_test.py <clone_dir> <scratchpad_dir>/smoke-test-expectations.json --log <scratchpad_dir>/smoke-test-report.json`. `--log` writes the full report to that path and prints only the compact summary — `ok`, the pass/fail/attention/skip counts, the report's path, and every `fail` or `attention` finding — so the routine passes never cross into anyone's context. It runs every check itself — the URL fetches (asserting a success response and the **absence** of `There has been a critical error`, `Fatal error`, and `Error establishing a database` in the HTML), `ddev wp db check`, entity and table-row counts, drop-in and object-cache-state checks, and the escaped-slash JSON asset-leak check — and the written report holds `ok`, a `summary` of pass/fail/attention/skip counts, and a `checks` list, each with `id`, `status`, and `detail`. Filter cosmetic WP-CLI/MariaDB deprecation notices from its stderr — they are never failures.
4. Report only genuine anomalies — every check whose `status` is `fail`, and separately call out any `attention` entry (informational, never itself a failure) — never the routine `pass`/`skip` entries. A `cli-unavailable` reindex outcome is not itself an anomaly (it is the documented report-only fallback), but always name it in the summary so the operator sees the manual-rebuild instruction. `--log` has already written the script's full JSON report to `<scratchpad_dir>/smoke-test-report.json`; name its path and SHA256 in the evidence block rather than inlining the report.

## What to return

**Summary:** the regenerated-attachment count (if run), the reindex outcome and command (if run), and the script's pass/fail/attention/skip summary (if run) — anomalies called out explicitly, everything else summarised as "N/N passed."

**Evidence block:**

- `status`: `DONE` or `FAILED`
- `regenerate_exit_code`, `regenerated_count`, `regenerate_log_path` (omitted when `regenerate` is `false`) — copied from the wrapper's own summary, never re-derived
- `reindex_exit_code`, `reindex_outcome`, `reindex_log_path` — the outcome is one of `rebuilt`, `cli-unavailable`, `not-present` (`reindex_exit_code` omitted when the outcome is `not-present`, since no command ran)
- `smoke_test_exit_code` — `scripts/smoke_test.py`'s own exit code (0 clean, non-zero on any `fail`) (omitted when `smoke_test` is `false`)
- `smoke_test_summary` — the report's pass/fail/attention/skip counts (omitted when `smoke_test` is `false`)
- `anomalies`: a list of the `fail`/`attention` checks' `id` and `detail`, empty when none
- `evidence_path`, `evidence_sha256` — the written expectations file and/or the full JSON report; the SHA256 lets the orchestrator confirm the file it reads back is the one this evidence block describes

`status` is `FAILED` iff `anomalies` contains at least one `fail`-severity check, or `scripts/smoke_test.py` itself exits non-zero — mirroring the script's own exit-code contract (0 iff no `fail`; `attention` and `skip` never affect it). An `attention` entry always rides along in `anomalies` for visibility, but never by itself flips `status` to `FAILED`. A `cli-unavailable` reindex outcome never flips `status` to `FAILED` either — it is the settled report-only fallback (ADR-0015), not an error.

## Hard rules

- Never ask the operator anything.
- Never run the raw WP-CLI command in place of its wrapper. The wrapper is what keeps this phase affordable when no separate context absorbs its output — tens of thousands of progress lines cost the same wherever they land, and a run that floods its own context has lost the decisions it still had to make.
- Never suppress a genuine anomaly to keep the summary short — only the routine, expected noise is swallowed.
- Never report `DONE` while an unaddressed `fail` finding is in `anomalies`.
- Never attempt a `wp eval` workaround or any other undocumented internal when the reindex probe fails — the report-only fallback is the whole contract.
