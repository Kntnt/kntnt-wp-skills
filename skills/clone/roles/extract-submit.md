# extract-submit

Every relative path below is relative to the `clone` skill directory — the parent of the `roles/` directory this file sits in — regardless of which skill's run is executing it or where the skills were installed. A `scripts/<name>.py` path is therefore one of the engine helpers `clone` ships. Whoever executes this role joins that anchor to the paths below itself; nothing here is read against the working directory a run happens to start in.

Whoever runs this role runs it the same way: a Claude Code subagent, a task another harness spawned, or the orchestrating agent executing these instructions inline when its harness can spawn neither. The tier decides who does the work and where the output lands, never what the work is or what it must return.

## Role

You submit the main extraction of a `kntnt-wp-skills` `clone` or `pull` run, write the job it created to disk, and return. That is the whole of it: one `POST /extractions`, one small file, one verdict. Short, bounded, and over in seconds. You can never pause to ask the operator anything.

**You do not wait for the job you submit, and the wait is not yours to start.** The extraction that follows runs for hours; the orchestrator polls it itself, as its own tracked background job, and hands the finished job to the `extract-transfer` role afterwards. That split is not tidiness. One role used to own the submit, the multi-hour poll, the download, the unseal and the consume, and it was instructed — in as many words, under two successive wordings — to sit inside the one blocking poll invocation and return exactly once with a verdict. On **both** production runs of this engine it returned without one, and the second time it had detached the poll first, so when its process tree was reaped the poll died with it: a zero-byte output file, no exit code ever written, and a job that carried on to 13,459 files with nobody watching. The written close-out for a verdict-less return is `DELETE`, so only an unwritten manual check of the job's own state stood between a healthy extraction and being cancelled two and a half hours in.

Instructing an agent not to escape a multi-hour wait had therefore already failed twice when this role was carved out. A boundary a model can cross cheaply will eventually be crossed, so the wait was moved to something that cannot be reaped rather than fenced off with firmer words. Do not re-merge this role with `extract-transfer` because one role would look tidier than two: the gap between them is the fix.

## Inputs

- `extractor_endpoint`, `scratchpad_dir` — as for every phase.
- `credential` — a **reference** to the HTTP-basic credentials the `POST /extractions` call authenticates with, never the value itself: either `{ "type": "keychain", "service": ..., "account": ... }`, resolved with `security find-generic-password -s <service> -a <account> -w`, or `{ "type": "env", "name": ... }`, resolved as `$<name>`. The Keychain account is `<wp-user>@<host>` and **splits on the LAST `@`** — the WordPress `user_login` is frequently itself an email address (`thomas@kntnt.com@safeteam.se` is a real account name), so the host is everything after the final `@` and the `-u` user is everything before it. Splitting on the first `@` produces a user that does not exist, which authenticates as nobody without reporting any error. You resolve it yourself, inside the authenticated call's own subshell — see *Hard rules*. The user holds both `kntnt_extractor_operate` and `manage_options`, already proven in the health check.
- `selection` — the `{ tables, tables_structure_only, files }` object `scripts/build_selection.py` produced (never assembled by hand). It already refuses a self-overlapping or empty selection, so what you receive is submittable.
- `chunk_size` — the **file-part budget** the main extraction packages at, in bytes: the resolved `chunk_size` decision's value from the run's plan (built-in `262144`, or whatever the site's saved plan pins). An integer of at least 1; you neither derive it nor default it, and a value outside that range never reaches production — `scripts/resolve_plan.py` refuses it locally, so a `422 kntnt_extractor_malformed_body` is never how the run learns of it. Submit it whatever the health check's `honours` list said: the member is additive, an Extractor that does not know it ignores it, and reading the list first would only invent a way to send nothing.
- `public_key` — the base64 half of the run's ephemeral X25519 pair, from `echo '{"private_key_path": "<scratchpad_dir>/run.key"}' | uv run scripts/unseal.py keygen`. Only `public_key` is submitted; the private key never leaves this machine, is never transmitted, and is not yours to touch — `extract-transfer` opens the container with it later.

## What to do

Resolve `credential` inside each authenticated call's own subshell — e.g. `curl -u "<user>:$(security find-generic-password -s <service> -a <account> -w)"` for the Keychain shape, or `curl -u "<user>:$<name>"` for the env shape — never into a shell variable you echo, print, or otherwise surface; it exists only inside the subshell of the call that uses it.

Give every Extractor request URL a **unique** `_cb=<value>` query parameter (`_cb=$(date +%s)-$RANDOM` is enough) — `?_cb=...` when the URL has no query string, `&_cb=...` when it already has one. A page cache or CDN in front of production can otherwise replay a stored response — including a stored refusal — to a call whose credentials are perfectly correct.

Capture the response headers of every Extractor call (`curl -sS -D "<scratchpad_dir>/headers.txt"`) and check them for `x-litespeed-cache: hit`, `cf-cache-status: HIT`, `x-cache: HIT`, `x-proxy-cache: HIT`, or a non-zero `age:`. A cache hit on an authenticated call is **not** an answer: stop immediately and return `FAILED` naming the header and the endpoint — *"production served a CACHED response to an authenticated Extractor call"* — and never retry past it (the retry hits the same cache key) and never fold the cached body into anything you emit.

**Your verdict binds your own work, never the job's state.** `FAILED` says this role did not finish; it does not say the extraction is dead, and a return that arrives without an evidence block says nothing whatever about the job. The orchestrator settles the difference by asking the server, not by believing you: it re-queries `GET /extractions/{id}` before acting on any `FAILED` — or absent — verdict, and a job the server itself reports as `running` with advancing progress is not cancelled, whatever came back from here.

1. Submit the extraction: `POST /extractions` with `{ ...selection, "public_key": public_key, "strict": false, "chunk_size": chunk_size }`. Expect `201 { id, state: "queued", skipped_files? }`. Surface any `skipped_files` the body carries — they vanished on production between the manifest walk and this POST, and the job will not contain them. A `422` (malformed or overlapping selection), `400` (invalid public key), `404` (unknown *table*, or a file the plugin would not skip — a traversal, or a selection that was only vanished files), `403` (capability), or `429` (a job is already active — the sweep or a bootstrap did not finish) is a hard stop: return `FAILED` with the status and body, never a retry. A `404` now names every missing table in `data.tables` and every missing file in `data.files`; put those names in the evidence `error`. An older Extractor that ignores `strict` still 404s a vanished file — that is the same hard stop, with or without names.

   A `422` whose `code` is `kntnt_extractor_restricted_path` is the single exception to that hard stop, and is **not** a hard stop on the first occurrence. The body's `data.paths` names every path the server refused; each is a file this client should never have asked for. Report every named path to the operator with the reason (the Extractor refuses to package it, because its name matches a restricted shape — a configuration-file backup, key material, or a database dump at the install root), drop exactly those paths from the selection's `files` list, and resubmit the create **once**. No job was created by the refused request, so resubmitting starts nothing twice. The corrected selection is the submitted one from that point on — the unseal in `extract-transfer` reconciles against it, not against the list the server refused, which is why step 2 records the selection as submitted rather than as received. A second `kntnt_extractor_restricted_path` on the resubmission **is** a hard stop: return `FAILED` with both bodies, because a refusal that survives dropping every named path means the client and the server disagree about what was named, and guessing further would loop. Your pre-filter can never be provably complete — the restricted shapes are the Extractor's policy, they live in its repository, and they may widen between releases without an `api_version` bump — so this handling is what makes an unanticipated restricted path survivable, not a fallback that should never fire.

2. Write the job to disk at `<scratchpad_dir>/extract-job.json` **before you return**, and before anything begins to wait on it: `{ "job_id": ..., "submitted": { "tables": [...], "tables_structure_only": [...], "files": [...] }, "skipped_files": [...], "restricted_paths": [...] }`, where `submitted` is the selection exactly as the accepted `POST` carried it — after any restricted-path drop, never the original. This one small file is what makes a lost poller a re-poll rather than a lost run: polling is read-only, so anything holding this id can re-attach to the job for free, whereas an id that only ever existed in some agent's context dies with it. It is also how the file lists reach the unseal without crossing an agent boundary inline. Report its SHA256 so whoever reads it back can confirm it is the file this evidence block describes.

3. Return. Do not poll the job, do not sleep on it, do not start anything that outlives you, and do not fetch its `download_url` — the job is `queued` when you last saw it and is nobody's to watch until the orchestrator picks it up.

## What to return

**Summary:** the job id, the job record's scratchpad path, how many tables and files the accepted submission carried, and any paths the server skipped or refused.

**Evidence block:**

- `status`: `DONE` or `FAILED`
- `job_id` — present whenever a job was created at all, including on `FAILED`
- `job_state` — the state the `201` reported (`queued`), or the last observed state on `FAILED`
- `job_record_path` — `<scratchpad_dir>/extract-job.json`
- `job_record_sha256` — the SHA256 of that file, so the orchestrator can confirm the record it reads back is the one this evidence block describes
- `submitted_tables`, `submitted_files` — the counts the accepted submission carried, after any restricted-path drop
- `chunk_size` — the file-part budget the accepted submission carried, so the number this run asked for is on the record rather than inferred
- `skipped_files` — the paths the plugin dropped, or an empty list when none
- `restricted_paths` — the paths the server refused as restricted and this role therefore dropped from the selection, or an empty list when none
- `error` (only on `FAILED`) — the failing REST status and body

A submission that never produced a `201`, or a job whose record never reached disk, is always `FAILED`.

## Hard rules

- **Never wait for the job you submitted** — no poll, no sleep, no loop, no watcher, and nothing detached that outlives your return. The multi-hour wait belongs to the orchestrator, which cannot be reaped; a wait started here is exactly the orphan this role exists to make impossible.
- Never return without a `DONE` or `FAILED` verdict. "Still waiting" is not a result and is read as `FAILED`. That reading binds your own work, never the job's state; the orchestrator re-queries the job before it acts on it.
- Never return before `<scratchpad_dir>/extract-job.json` is on disk. A job id that exists only in a return value is one lost message from an untraceable, still-running extraction.
- Never trust a response carrying a cache-hit header on an authenticated call — return `FAILED` naming the header and the endpoint instead of using its body.
- Never issue an Extractor request without its unique `_cb` cache-buster, and never reuse one across calls.
- Never ask the operator anything.
- Never resubmit a refused create more than once, and never resubmit an *accepted* one at all — the plugin allows one active job, and a second create is how a run ends up racing itself.
- Never print, log, or return the resolved secret — it exists only inside the subshell of the call that uses it.
