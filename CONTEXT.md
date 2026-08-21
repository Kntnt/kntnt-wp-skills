# kntnt-wp-skills

A Claude Code plugin that mirrors a live WordPress site down into a local DDEV copy via `clone` and `pull`, two user-invoked skills over one shared transfer engine; a third standalone skill, `mkwp`, that scaffolds a brand-new local site; and a fourth standalone skill, `build-ollie-site`, that builds a site out on the Ollie block theme.

## Language

### Skills and engine

**Clone**:
The skill that creates a fresh local DDEV copy of a production site in an empty directory. A clone is a pull with no baseline.
_Avoid_: install, download, copy

**Pull**:
The skill that refreshes an existing local copy from production. Never pushes anything up.
_Avoid_: sync, refresh, update

**mkwp** (skill):
The standalone skill that scaffolds a brand-new local WordPress site by driving the `mkwp` command — no production, no control channel, no transfer engine underneath. Named after, and driving, the `mkwp` command itself.

**build-ollie-site** (skill):
The standalone skill that builds a site out on the **Ollie** block theme from a design system and a set of mockups, bottom-up by Atomic Design — pattern cartography, then tokens, component patterns, section patterns, and pages. Shares none of the transfer engine's machinery — no production, no control channel, no recommendation gates. Its patterns are the operator's own; Ollie supplies only tokens and global styles.
_Avoid_: theme generator, page builder

**Transfer engine**:
The shared machinery `clone` and `pull` run — discovery, extraction on production, download, verification, remote cleanup, import, localisation. Clone and pull differ only at the bookends; `mkwp` and `build-ollie-site` are not part of it.

**Control channel**:
The [Kntnt Extractor](https://github.com/Kntnt/kntnt-extractor) plugin's REST API on the production site — the sole way the skills reach production. There is no SSH ([ADR-0016](docs/adr/0016-kntnt-extractor-replaces-novamira-as-control-channel.md), superseding [ADR-0001](docs/adr/0001-novamira-mcp-sole-control-channel.md)).

**Health check**:
Mandatory step 0 of every run: verify every local and production dependency the run needs, that the Extractor endpoint is live and at API ≥ 2 (`status` handshake), authorised and targeting production (its `environment` `home_url`), that any stranded earlier job is swept, and that the download path serves — before any heavy work, with guided remediation on anything missing.

**Discovery**:
The read-only, two-phase production scan — reconstructed client-side from Kntnt Extractor's `environment`, `tables`, and `files` calls plus a bootstrap extraction parsed locally (small only where `wp_postmeta` is small — a premise, [ADR-0017](docs/adr/0017-discovery-over-extractor-rest-two-phase.md)) — that feeds every live-derived recommendation: sizes, versions, prefix, drop-ins, the mass-send risk scan, the thumbnail exclude-list.

### Decisions and run modes

**Gate**:
A single yes/no prompt on a recommendation — *"Recommended: X. Accept? [Y/n]"* — the one shape every decision takes. `n` reveals the alternatives.
_Avoid_: prompt, dialog, wizard step

**Recommendation**:
The skill's proposed answer at a gate, computed from layered defaults (built-in < live derivation < saved config < this run's answer).

**Saved plan**:
The remembered per-site answers in `.kntnt-wp-skills.json`, at the local project root. Stores decisions, never computed lists.
_Avoid_: profile, preset

**Replay**:
The run mode engaged when a saved plan exists: interactive collapses to one "Replay the saved plan?" gate; `--yes` runs it silently.

**Anomaly**:
A finding a phase reports in full without condemning the run — a step that could not run, one that ran with warnings, or one that exited non-zero for a reason that says nothing about the copy's fidelity. It rides in the evidence block's `anomalies` list beside a `DONE`, and is never a third verdict: a phase is still only ever `DONE` or `FAILED`, and `FAILED` requires evidence that the copy is defective ([ADR-0028](docs/adr/0028-a-phase-fails-on-a-defective-copy-never-on-a-non-zero-exit.md)).
_Avoid_: warning, soft failure, non-fatal error

### Files and sync

**Baseline**:
The stored manifest of the in-scope production tree (path + size + mtime) from the last sync, kept in `.kntnt-wp-skills/last-sync.json` at the local project root, together with the scope it was taken under. Diffs are always production-now against the baseline, never against local files.
_Avoid_: snapshot, cache

**Scope**:
The set of paths included in a transfer after exclusions (thumbnails, blobs, drop-ins, etc.). Stored with the baseline so scope changes never poison the deletion diff.

**Blob**:
A heavy, excludable production file or directory (gallery dirs, `.mmdb`, backups, dumps) flagged by a deterministic heuristic and offered for exclusion behind a gate.

**Generated thumbnails**:
The DB-known resized copies of registered attachments (`_wp_attachment_metadata → sizes[*].file`) — excluded from transfer and regenerated locally.

**Side-loaded files**:
Files in `uploads/` with no attachment record (including their thumbnails). Cannot be regenerated, so they are pulled whole.
_Avoid_: orphan files (as a distinct concept — same thing)

**Deletion mirroring**:
The opt-in removal of local files whose production originals are gone, plus confirmed plugin/theme drift. Always itemised, always to the trash.

**Drift**:
Local plugins/themes with no production counterpart — dev tools to keep or junk to trash, settled by checklist.

**Trash**:
`.kntnt-wp-skills/trash/<timestamp>/` — where "deleted" local files actually go. Nothing is ever hard-`rm`ed.

**Normalisation collision**:
Two or more production paths that differ only by Unicode normalisation — the same name with a code point composed or decomposed — and which the local filesystem therefore stores as one file, the last write winning. Detected at unseal by grouping the file list on its NFC form, counted by the distinct files that landed on disk, reported with every spelling named, and never fatal.
_Avoid_: duplicate file, encoding clash

### Production-side extraction

**Extraction**:
The Kntnt Extractor plugin's own background job that dumps, archives, seals, and publishes the selection outside the docroot. The skills submit it (`POST /extractions`) and poll it to a terminal state; they own none of its mechanics.
_Avoid_: pack, pack job

**Job record**:
`<scratchpad>/extract-job.json` — what the `extract-submit` role writes the moment the main extraction is accepted and before anything begins to wait on it: the job id, the selection exactly as submitted (after any restricted-path drop), and any skipped or refused paths. Polling is read-only, so an id already on disk makes a lost poller a re-poll rather than a lost run; the record is also how the submitted lists reach the unseal without crossing an agent boundary inline.

**Poll helper**:
`skills/clone/scripts/poll_extraction.py` — the one blocking invocation that waits on an extraction job and exits with a terminal verdict plus the poll telemetry. Nobody writes the loop; whoever owns a wait invokes the helper and gives it `--log <path>` so hours of progress lines land in the run's scratchpad rather than in a context. Ownership differs by phase: the health check's preflight and `discovery-classify`'s bootstrap are bounded by their own budgets and stay with the surface that runs them, while the main extraction's poll is the orchestrating skill's own tracked background job — never a role's and never detached, because a subagent's process tree does not outlive its return. Its verdict is captured to `extract-poll.json` and its exit status to `extract-poll.exit` beside the log; the verdict prints only at the end, so the exit file is what separates a poll that answered from one that died. The Application Password is `KNTNT_EXTRACTOR_APP_PASSWORD` in that process's environment, never argv. The main extraction omits the budget argv; the stall window is the stop.
_Avoid_: poll loop (as something an agent writes), poll agent (nothing owns the main extraction's wait but the orchestrator)

**Selection**:
The explicit lists submitted to an extraction — full-data `tables`, structure-only `tables_structure_only`, and `files` — all computed client-side, so only what survives every exclusion is ever named. The main extraction is submitted with `strict: false`, so a file that vanishes between the manifest walk and the POST is dropped by the plugin rather than failing the job.
_Avoid_: pack list

**File-part budget**:
The number of bytes the Extractor packages each file part to, sent on the main extraction's create as `chunk_size` and resolved like every other decision (built-in `262144` — 256 KB, the one value measured to complete a real clone — over an optional saved-plan `chunk_size` key). Only the main extraction carries it: the preflight and the bootstrap submit no files, so neither packages a file part. It is sent whether or not the health check's `honours` list names it; an Extractor that does not know the member resolves the budget itself through a config seam no endpoint reports, which is what the client is taking the decision back from. A site deliberately tuned to a different number records it in the saved plan, or a run overrides it.
_Avoid_: chunk size (as the operator-facing term), slice budget (that is the table-side knob, which nothing here moves)

**Honours list**:
The `honours` member the **authenticated** `GET /status` reports: the additive request members this host actually acts on. Read once in the health check's identity step and carried through the run the way the API version is — passed through, never re-fetched. It never decides what a run sends; it decides only what the run's report can tell the operator was ignored.
_Avoid_: capability list, feature flags

**Skipped file**:
A file named in a `strict: false` submission that no longer existed on production at job creation. The plugin drops it from the packaged selection, records it on the job, and returns it on the create and the poll. The skills surface those paths to the operator and unseal against the remaining file list, because the container does not contain them. A missing table is never skipped.
_Avoid_: ignored file, optional file

**Structure-only table**:
A table carried as DROP/CREATE DDL with no rows — how every empty-classified table travels, so the table exists locally with zero rows.

**Sealed container** (KNTNTEXT):
The plugin's per-segment sealed output for one extraction, opened only client-side. Replaces the old encrypted `.enc` artifacts.
_Avoid_: artifacts, `db.enc`/`files.enc`

**Segment**:
One unit inside the sealed container — a bounded slice of a table's dump or a bounded part of a file — encrypted under its own `crypto_secretbox` key, itself sealed (`crypto_box_seal`) to the run's ephemeral public key. A table or a file contributes one *or more* consecutive segments sharing its name, so an entity is reassembled by concatenating every segment carrying that name, in index order; a structure-only table is DDL alone and is always exactly one segment.
_Avoid_: treating a segment as a whole table

**Ephemeral key pair**:
The per-run X25519 pair the client generates; only the public half is sent to production (in `POST /extractions`), and the private half never leaves the operator's machine and is never transmitted.
_Avoid_: passphrase

**Unseal**:
The client-side reassembly of a sealed container: open each segment key, decrypt each segment, concatenate each table's segments — in index order — into one importable `.sql` with a connection-safe preamble, and write each file's segments to disk by install-root-relative path.
_Avoid_: decrypt (as the whole operation)

**One-time download link** (`download_url`):
The single-use URL the plugin exposes for a finished extraction; fetched once, then the job is consumed.
_Avoid_: download dir

**Exposure window**:
The interval a finished extraction is fetchable on production — closed immediately by consuming the job (`POST /extractions/{id}/consume`) once the download unseals, backstopped by the plugin's own TTL cleanup and the next health check's stranded-job sweep.

**Locked consume**:
A `POST /extractions/{id}/consume` refused `409 kntnt_extractor_locked` because the job's per-job tick lock is held at that instant by a tick or the TTL sweep. Retried on a bounded schedule — five retries, 10 seconds apart — and only an exhausted window is a failure, reported as the `unsealed_consume_locked` failure phase, whose local copy is complete because the download and the unseal both precede the consume.
_Avoid_: consume conflict

**Locked cancel**:
A `DELETE /extractions/{id}` refused `409 kntnt_extractor_locked` because the job's per-job tick lock is held at that instant by a tick or the TTL sweep. The close-out's case 1 retries it on the same bounded schedule as a locked consume — five retries, 10 seconds apart, off the same `tick_budget` — but with weaker cover, since a cancel reaches `queued` and `running` jobs whose ticks keep retaking the lock. An exhausted window is reported, never run-ending: the job is left standing for the plugin's TTL, and for the next run's stranded-job sweep where it is still non-terminal.
_Avoid_: cancel conflict

**Close-out**:
What a run does with a submitted job before it stops on a failure — the *Closing out a failed phase* subsection both SKILLs carry. It is entered on any `FAILED`, absent or malformed verdict from the three roles that can produce one, on any terminal poll verdict other than `ready`, and on any orchestrator abort after a submission, and it ends in exactly one of four cases (cancel, consume, report-only, report-complete-but-unconsumed) or in an explicit *no case*. A run may never end with a job it submitted left unaccounted for ([ADR-0022](docs/adr/0022-close-the-exposure-window-on-every-failure-path.md)).
_Avoid_: cleanup, teardown

**Derived case**:
How the close-out picks among those four: from the job's own state (one `GET /extractions/{id}`) and this machine's own state (the close-out probe), never from a claim a session made. A reported `failure_phase` is a **hint** — corroboration for the report and the run record — and where hint and derivation disagree, the derivation wins. Only one of the three roles reports the field at all, and an absent verdict reports none by definition, so a case selected from it is undefined on most of the routes that reach the close-out.
_Avoid_: reported phase (as the selector), failure phase (as the selector)

**Close-out probe**:
The close-out's read of the run's scratchpad, answering *was a sealed container downloaded?* and *was it unsealed?* from fixed names: `<scratchpad>/extract.container` — reached only by renaming `<scratchpad>/extract.container.part` after a clean transfer, so a truncated download can never answer for a whole one — plus `<scratchpad>/extract.sql` and `<scratchpad>/extract-files/`, and the same shape for the bootstrap job inside `discovery-classify`'s own per-run working directory. It reads only; it creates, moves and deletes nothing.
_Avoid_: disk check, scratchpad scan

### Mail and side effects

**Mass-send valve**:
The discovery-driven flip of the mail default: only a *poised* bulk send — a campaign queued or scheduled against a real recipient list, not mere plugin presence — changes the recommendation from live mail to capture.

**Live mail**:
The default: the site's existing mailer (e.g. Postmark) stays active locally, so the send flow can be tested end-to-end.

**Capture**:
Routing all mail to DDEV's Mailpit via the mu-plugin that short-circuits `wp_mail` — catching API mailers that never touch sendmail.

**Risk warning**:
The always-emitted notice itemising the copy's outward-reaching behaviours (real mail, webhooks, payments, social posts, licence pings, real PII).

### Local site

**Local project root**:
The site directory `<directory_name>/` — the one `mkwp` scaffolds and `clone`/`pull` operate against. The saved plan `.kntnt-wp-skills.json` and the derived `.kntnt-wp-skills/` both live here, never in the operator's invocation `cwd` one level up. Defined once, here; every other reference to "the local project root" or "the site directory" points back at this entry (issue #40).
_Avoid_: project root, working directory, cwd (as a synonym — the root is a specific directory, not wherever the shell happens to be)

**Marked block**:
The clearly delimited section the skills own in the local `wp-config.php` — ported production defines and the table prefix — separate from mkwp's DDEV block.

**Withheld define**:
A production define the auto-excluded class claims per record rather than by name, never ported and always reported with its reason. The Extractor's `disclosure` discriminator decides — `secret`, `not_allow_listed`, or any verdict this client does not recognise — never the value, which the protocol forbids reading it from; a value-based verdict survives only against an Extractor predating the discriminator. A define the server disclosed whose live value is `null` is not withheld, and is reported as its own case, but is not ported either.

**Preserved inactive set**:
The locally deactivated plugins, derived from live local state each `pull` and re-applied after import.

**Ownership rule**:
The object-cache drop-in derivation at `pull`: no local drop-in → nothing; different owner than production → keep local; same owner → take production's, then verify a request and auto-remove on failure.

### Help

**Manpage**:
`docs/man/<skill>.md` — the single Markdown source of truth for a skill's usage, echoed verbatim by `help.py`.

**Help-gate**:
Each `SKILL.md`'s first step: on `help` / `--help` / `-h`, echo the manpage and stop.
