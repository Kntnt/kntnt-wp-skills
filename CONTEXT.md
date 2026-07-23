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
The [Kntnt Extractor](https://github.com/Kntnt/kntnt-extractor) plugin's REST API on the production site — the sole way the skills reach production. There is no SSH ([ADR-0016](./adr/0016-kntnt-extractor-replaces-novamira-as-control-channel.md), superseding [ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md)).

**Health check**:
Mandatory step 0 of every run: verify every local and production dependency the run needs, that the Extractor endpoint is live and at API ≥ 2 (`status` handshake), authorised and targeting production (its `environment` `home_url`), that any stranded earlier job is swept, and that the download path serves — before any heavy work, with guided remediation on anything missing.

**Discovery**:
The read-only, two-phase production scan — reconstructed client-side from Kntnt Extractor's `environment`, `tables`, and `files` calls plus a small bootstrap extraction parsed locally, no longer a single server-side payload — that feeds every live-derived recommendation: sizes, versions, prefix, drop-ins, the mass-send risk scan, the thumbnail exclude-list ([ADR-0017](./adr/0017-discovery-over-extractor-rest-two-phase.md)).

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

### Production-side extraction

**Extraction**:
The Kntnt Extractor plugin's own background job that dumps, archives, seals, and publishes the selection outside the docroot. The skills submit it (`POST /extractions`) and poll it to a terminal state; they own none of its mechanics.
_Avoid_: pack, pack job

**Selection**:
The explicit lists submitted to an extraction — full-data `tables`, structure-only `tables_structure_only`, and `files` — all computed client-side, so only what survives every exclusion is ever named.
_Avoid_: pack list

**Structure-only table**:
A table carried as DROP/CREATE DDL with no rows — how every empty-classified table travels, so the table exists locally with zero rows.

**Sealed container** (KNTNTEXT):
The plugin's per-segment sealed output for one extraction, opened only client-side. Replaces the old encrypted `.enc` artifacts.
_Avoid_: artifacts, `db.enc`/`files.enc`

**Segment**:
One unit inside the sealed container — a single table's dump or a single file — encrypted under its own `crypto_secretbox` key, itself sealed (`crypto_box_seal`) to the run's ephemeral public key.

**Ephemeral key pair**:
The per-run X25519 pair the client generates; only the public half is sent to production (in `POST /extractions`), and the private half never leaves the operator's machine and is never transmitted.
_Avoid_: passphrase

**Unseal**:
The client-side reassembly of a sealed container: open each segment key, decrypt each segment, concatenate table segments into one importable `.sql` with a connection-safe preamble, and write file segments to disk by install-root-relative path.
_Avoid_: decrypt (as the whole operation)

**One-time download link** (`download_url`):
The single-use URL the plugin exposes for a finished extraction; fetched once, then the job is consumed.
_Avoid_: download dir

**Exposure window**:
The interval a finished extraction is fetchable on production — closed immediately by consuming the job (`POST /extractions/{id}/consume`) once the download unseals, backstopped by the plugin's own TTL cleanup and the next health check's stranded-job sweep.

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
