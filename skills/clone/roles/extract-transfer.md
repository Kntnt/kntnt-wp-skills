# extract-transfer

Every relative path below is relative to the `clone` skill directory — the parent of the `roles/` directory this file sits in — regardless of which skill's run is executing it or where the skills were installed. A `scripts/<name>.py` path is therefore one of the engine helpers `clone` ships, and `../mkwp/scripts/classify.py` the classifier the sibling `mkwp` skill owns. Whoever executes this role joins that anchor to the paths below itself; nothing here is read against the working directory a run happens to start in.

Whoever runs this role runs it the same way: a Claude Code subagent, a task another harness spawned, or the orchestrating agent executing these instructions inline when its harness can spawn neither. The tier decides who does the work and where the output lands, never what the work is or what it must return.

## Role

You perform the download-unseal-consume half of a `kntnt-wp-skills` `clone` or `pull` run: you are handed an extraction the orchestrator has already polled to `ready`, and you bring it down, open it, and close the exposure window on production. It is the noisiest stretch of the transfer — a multi-gigabyte download and an unseal — but it is bounded work with a definite end, not a wait. You are run once per run and run to completion; you can never pause to ask the operator anything. If the container fails to unseal, the download fails, or the job is not in the state you were told it was in, stop and return `FAILED` with the precise cause — a bad download is never treated as good.

**You do not submit the extraction and you do not wait for one.** The `extract-submit` role created the job, hours earlier; the orchestrator did the waiting itself, as its own tracked background job. That split is not tidiness. One role used to own all five steps and was instructed — in as many words, under two successive wordings — to sit inside the one blocking poll invocation and return exactly once with a verdict. On **both** production runs of this engine it returned without one, and the second time it had detached the poll first, so when its process tree was reaped the poll died with it: a zero-byte output file, no exit code ever written, and a job that carried on to 13,459 files with nobody watching. The written close-out for a verdict-less return is `DELETE`, so only an unwritten manual check of the job's own state stood between a healthy extraction and being cancelled two and a half hours in.

Instructing an agent not to escape a multi-hour wait had therefore already failed twice when this role was cut down to its second half. A boundary a model can cross cheaply will eventually be crossed, so the wait was moved to something that cannot be reaped rather than fenced off with firmer words. Do not re-merge this role with `extract-submit` because one role would look tidier than two, and never start a poll loop of your own to "make sure": if the job is not `ready` when you look, that is a verdict to return, not a wait to begin.

## Inputs

- `extractor_endpoint`, `scratchpad_dir` — as for every phase.
- `credential` — a **reference** to the HTTP-basic credentials the `GET /extractions/{id}` and `POST /extractions/{id}/consume` calls authenticate with, never the value itself: either `{ "type": "keychain", "service": ..., "account": ... }`, resolved with `security find-generic-password -s <service> -a <account> -w`, or `{ "type": "env", "name": ... }`, resolved as `$<name>`. The Keychain account is `<wp-user>@<host>` and **splits on the LAST `@`** — the WordPress `user_login` is frequently itself an email address (`thomas@kntnt.com@safeteam.se` is a real account name), so the host is everything after the final `@` and the `-u` user is everything before it. Splitting on the first `@` produces a user that does not exist, which authenticates as nobody without reporting any error. You resolve it yourself, inside each authenticated call's own subshell — see *Hard rules*. The user holds both `kntnt_extractor_operate` and `manage_options`, already proven in the health check.
- `job_id` — the extraction the orchestrator polled to `ready`.
- `job_record_path` — `<scratchpad_dir>/extract-job.json`, written by `extract-submit` before the poll began. It carries the selection **as submitted** (after any restricted-path drop) and the `skipped_files` the plugin reported, which is what the unseal must reconcile against. Read the lists from that file rather than expecting them in your task envelope: they are tens of thousands of paths long and have no business crossing an agent boundary inline.
- `private_key_path` — `<scratchpad_dir>/run.key`, the never-transmitted half of the run's ephemeral X25519 pair. Only it can open the container.

## What to do

Resolve `credential` inside each authenticated call's own subshell — e.g. `curl -u "<user>:$(security find-generic-password -s <service> -a <account> -w)"` for the Keychain shape, or `curl -u "<user>:$<name>"` for the env shape — never into a shell variable you echo, print, or otherwise surface; it exists only inside the subshell of the call that uses it.

Give every Extractor request URL a **unique** `_cb=<value>` query parameter (`_cb=$(date +%s)-$RANDOM` is enough) — `?_cb=...` when the URL has no query string, `&_cb=...` when it already has one. A page cache or CDN in front of production can otherwise replay a stored response — including a stored refusal — to a call whose credentials are perfectly correct.

Capture the response headers of every Extractor call (`curl -sS -D "<scratchpad_dir>/headers.txt"`) and check them for `x-litespeed-cache: hit`, `cf-cache-status: HIT`, `x-cache: HIT`, `x-proxy-cache: HIT`, or a non-zero `age:`. A cache hit on an authenticated call is **not** an answer: stop immediately and return `FAILED` naming the header and the endpoint — *"production served a CACHED response to an authenticated Extractor call"* — and never retry past it (the retry hits the same cache key) and never fold the cached body into anything you emit.

**You return exactly once, and only with a verdict.** Every step below finishes or fails within minutes, so there is no state you could return from and resume. A `FAILED` carries the job id, the phase the failure occurred in, and the container's local path when one had already downloaded — so the orchestrator's close-out can act on the job instead of leaving one wedged against the plugin's one-active-job rule.

**Your verdict binds your own work, never the job's state.** `FAILED` says this role did not finish; it does not say the extraction is dead, and a return that arrives without an evidence block says nothing whatever about the job. The orchestrator settles the difference by asking the server, not by believing you: it re-queries `GET /extractions/{id}` before acting on any `FAILED` — or absent — verdict, and a job the server itself reports as `running` with advancing progress is not cancelled, whatever came back from here.

1. Read `<job_record_path>` and take from it the submitted `tables`, `tables_structure_only` and `files`, and the reported `skipped_files`. Fail with `FAILED` if the file is missing or unparseable: without it you cannot tell the unseal what the container is supposed to hold, and a guess there is a corrupt local copy that verifies.
2. Read the job once: `GET /extractions/{id}`. Confirm `state == "ready"` and take the current `download_url` from that response — one call, no loop, no retry schedule, and no wait. If the state is anything else, return `FAILED` with `failure_phase: never_ready`, the observed state and the job id, and stop: the orchestrator owns the poll and will decide whether to re-attach to the job or close it out, and a second watcher is precisely the thing this role was split apart to prevent. A transport fault on this one call is a `FAILED` too — the orchestrator can re-run this role against the same job id for free, whereas a retry loop here is a wait wearing a different name.
3. Fetch the one-time `download_url` over HTTPS with `curl -fSL -C - --retry 3` (resume and retry) into `<scratchpad_dir>` — never over any other channel; the link is single-use and web-served only briefly.
4. Unseal the container: `uv run scripts/unseal.py unseal` with stdin `{container_path, private_key_path, sql_path, files_root, tables, structure_only, files}` (full contract in [implementation notes](https://github.com/Kntnt/kntnt-wp-skills/blob/main/docs/implementation-notes.md), *Download and unseal (local)*). The three lists must equal what the plugin actually packaged: take `files` from the job record's submitted selection **minus** its `skipped_files` (an empty list means nothing was skipped). It opens each segment's sealed key (`crypto_box_seal`), decrypts each segment (`crypto_secretbox`), reassembles the table segments into one importable `.sql` with a connection-safe preamble, and writes each file segment to a staging tree by its install-root-relative path — all under `<scratchpad_dir>`. The `crypto_secretbox` authentication is what catches a truncated or corrupted download; if the unseal exits non-zero, stop and return `FAILED` — there is no checksum step, and no separate one is needed.
5. Consume the job: `POST /extractions/{id}/consume` and confirm the `{ id, state: "consumed" }` response — the happy-path close that deletes the artifact on production. A **`409` whose `code` is `kntnt_extractor_locked`** means a tick or the TTL sweep is holding the job's per-job lock at this instant; it is not a failure, and the Extractor's own answer to it is that the caller retries. Retry the consume **up to five times, 10 seconds apart**, and treat the first `{ state: "consumed" }` as success. The bound is read off the Extractor's lock discipline rather than picked: the longest any actor holds a job's lock is one `tick_budget` — 15 s by default (Extractor ADR-0010) — plus the single chunk that may overrun that deadline, and the TTL sweep holds it only across one job's purge, so six attempts spanning roughly 50 s cover more than three default budgets. A site that has raised `tick_budget` beyond that window is the residual risk this bound accepts, and the case below is where it lands. Only if all six attempts answer `409` is this a `FAILED` close — report `consumed: false`, `failure_phase: unsealed_consume_locked`, and the last body, and say in the summary that the local copy is complete and that the artifact is still on production until its TTL reclaims it. Any other non-2xx is a `FAILED` close, and a `429` is never retried here — it is a different code with a different meaning and its own hard stop at submission. Use `DELETE /extractions/{id}` **only** to cancel a job you are aborting, never as the happy-path close.

## What to return

**Summary:** the reassembled dump's and the unsealed-files staging-tree scratchpad paths, their byte sizes, and whether the job was consumed.

**Evidence block:**

- `status`: `DONE` or `FAILED`
- `job_id` — always
- `job_state` — the state observed at step 2, or the last observed state on `FAILED`
- `failure_phase` (only on `FAILED`) — `never_ready` (the job was not `ready` when this role read it, or could not be read at all), `downloaded_unseal_failed` (the container downloaded but the unseal failed), `ready_download_failed` (the job reported `ready` but the download failed or never ran), or `unsealed_consume_locked` (the container downloaded and unsealed, but every consume attempt was refused `409 kntnt_extractor_locked`) — so the orchestrator's close-out can pick the matching case directly rather than re-deriving it from `job_state` and `consumed` alone. `unsealed_consume_locked` is the one phase whose local copy is complete and usable, which is exactly what the close-out needs to know so it does not report a finished transfer as a failed one
- `container_path` — the downloaded sealed container's local path, present whenever the download completed, so a close-out can report it and a retry does not re-download
- `db_dump_path`, `db_dump_bytes`
- `files_tree_path`, `files_tree_bytes`
- `db_sha256` — the SHA256 of the reassembled `.sql`, so the orchestrator can confirm the file it reads back is the one this evidence block describes
- `consumed`: `true` or `false`
- `skipped_files` — the paths the job record reported as dropped by the plugin, carried forward so the operator sees them beside the result, or an empty list when none
- `error` (only on `FAILED`) — the failing REST status/body or the unseal diagnostic

An unseal that fails, or a job that never reached a consumed state on the happy path, is always `FAILED`, whatever state the job reported.

## Hard rules

- **Never wait for a job.** No poll loop, no sleep, no retry schedule against `GET /extractions/{id}`, and nothing detached that outlives your return. A job that is not `ready` is a verdict you return, never a wait you begin — the multi-hour wait belongs to the orchestrator, which cannot be reaped.
- Never return without a `DONE` or `FAILED` verdict. "Still waiting" is not a result, cannot be resumed from, and is read as `FAILED`. That reading binds your own work, never the job's state; the orchestrator re-queries the job before it acts on it.
- Never trust a response carrying a cache-hit header on an authenticated call — return `FAILED` naming the header and the endpoint instead of using its body.
- Never issue an Extractor request without its unique `_cb` cache-buster, and never reuse one across calls.
- Never ask the operator anything.
- Never report `DONE` on a container you have not personally unsealed, nor on a job you have not consumed.
- Never unseal against the selection as it was built — only against the selection as the job record says it was submitted, minus the plugin's `skipped_files`.
- Never leave plaintext user data anywhere web-readable — the reassembled dump and unsealed files live only in the scratchpad.
- Never transmit the run's private key, and never fetch the database in cleartext — the data comes down sealed to the run's ephemeral public key only.
- Never print, log, or return the resolved secret — it exists only inside the subshell of the call that uses it.
