# kntnt-wp-skills

A Claude Code plugin that mirrors a live WordPress site down into a local DDEV copy via `clone` and `pull`, two user-invoked skills over one shared transfer engine, plus a third standalone skill, `mkwp`, that scaffolds a brand-new local site.

## Language

### Skills and engine

**Clone**:
The skill that creates a fresh local DDEV copy of a production site in an empty directory. A clone is a pull with no baseline.
_Avoid_: install, download, copy

**Pull**:
The skill that refreshes an existing local copy from production. Never pushes anything up.
_Avoid_: sync, refresh, update

**mkwp** (skill):
The standalone skill that scaffolds a brand-new local WordPress site by driving the `mkwp` command — no production, no Novamira, no transfer engine underneath. Named after, and driving, the `mkwp` command itself.

**Transfer engine**:
The shared machinery `clone` and `pull` run — discovery, packing on production, download, verification, remote cleanup, import, localisation. Clone and pull differ only at the bookends; `mkwp` is not part of it.

**Control channel**:
The Novamira MCP server on the production site — the sole way the skills reach production. There is no SSH.

**Health check**:
Mandatory step 0 of every run: verify the channel is live, targets production, can spawn processes, and can serve downloads — before any heavy work.

**Discovery**:
The read-only production scan (one `execute-php` call) that feeds every live-derived recommendation: sizes, versions, prefix, drop-ins, the mass-send risk scan, the thumbnail exclude-list.

### Decisions and run modes

**Gate**:
A single yes/no prompt on a recommendation — *"Recommended: X. Accept? [Y/n]"* — the one shape every decision takes. `n` reveals the alternatives.
_Avoid_: prompt, dialog, wizard step

**Recommendation**:
The skill's proposed answer at a gate, computed from layered defaults (built-in < live derivation < saved config < this run's answer).

**Saved plan**:
The remembered per-site answers in `.kntnt-wp-skills.json`. Stores decisions, never computed lists.
_Avoid_: profile, preset

**Replay**:
The run mode engaged when a saved plan exists: interactive collapses to one "Replay the saved plan?" gate; `--yes` runs it silently.

### Files and sync

**Baseline**:
The stored manifest of the in-scope production tree (path + size + mtime) from the last sync, kept in `.kntnt-wp-skills/last-sync.json` together with the scope it was taken under. Diffs are always production-now against the baseline, never against local files.
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

### Production-side packing

**Pack**:
The background job on production that dumps, archives, encrypts, and publishes the artifacts.

**Artifacts**:
The three published outputs of a pack: `db.enc`, `files.enc`, `SHA256`. Encrypted and `.enc`-named from creation.

**Working dir**:
The outside-docroot temp dir where all packing happens — passphrase, `.my.cnf`, logs, intermediates. Never web-readable.

**Download dir**:
The random-named docroot dir holding only the finished artifacts, briefly, for `curl`.

**Exposure window**:
The interval while artifacts sit in the download dir — closed immediately after checksums pass, backstopped by the self-destruct timer and the next health check's sweep.

**Self-destruct timer**:
The detached `sleep`-then-`rm` armed by the pack job, so the working and download dirs vanish even if the client never returns.

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

**Marked block**:
The clearly delimited section the skills own in the local `wp-config.php` — ported production defines and the table prefix — separate from mkwp's DDEV block.

**Preserved inactive set**:
The locally deactivated plugins, derived from live local state each `pull` and re-applied after import.

**Ownership rule**:
The object-cache drop-in derivation at `pull`: no local drop-in → nothing; different owner than production → keep local; same owner → take production's, then verify a request and auto-remove on failure.

### Help

**Manpage**:
`docs/man/<skill>.md` — the single Markdown source of truth for a skill's usage, echoed verbatim by `help.py`.

**Help-gate**:
Each `SKILL.md`'s first step: on `help` / `--help` / `-h`, echo the manpage and stop.
