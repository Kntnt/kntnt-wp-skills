# kntnt-wp-skills — implementation notes

This file preserves the invocation-level literals from the superseded design-and-build-plan document — exact commands, flags, filenames, permissions, timer values, and illustrative shapes — so that implementation never has to re-derive hard-won specifics. The specification ([`docs/spec.md`](./spec.md)) is authoritative for every decision; this file only pins the literals the spec deliberately abstracts, and where the two diverge the spec (or an ADR) wins. Literals marked *free choice* may be changed during implementation if a better value emerges; everything else was settled the hard way — through the security review or real-world debugging — and should be kept unless a test proves otherwise.

## Shipped templates

- The plugin ships two templates alongside its helper scripts: the pack script template and the Mailpit mu-plugin template. The engine instantiates them per run.
- The capture mu-plugin is `kntnt-wp-skills-mailpit.php`: it short-circuits `wp_mail` at top priority and delivers to DDEV's Mailpit at `localhost:1025`. Installed only in the capture branch.

## Health check

- Liveness probe: one trivial `execute-php` returning `home_url()`, `ABSPATH`, `phpversion()`, and `$_SERVER['SERVER_SOFTWARE']`.
- Exec probe (independent of `run-wp-cli`): check `function_exists('exec')`, inspect `disable_functions`, and run a live `exec('printf ok')` round-trip.
- Download preflight: write a tiny **extension-less** test file into a throwaway docroot dir, fetch it with `curl -fsS` over HTTPS from the local side, then delete it.
- Stranded-workspace sweep: look for leftover `kntnt-wp-skills-*` directories in both the outside-docroot temp base and the docroot download base, and remove them.

## Discovery

- DB flavour, version, and default collation: `SELECT VERSION()` and `@@version_comment` (MySQL 8 vs MariaDB).
- Environment probes: `phpversion()`, `disk_free_space()`, `is_writable(ABSPATH)`, `get_option('active_plugins')`.
- Thumbnail exclude-set source: each attachment's `_wp_attachment_metadata → sizes[*].file`; the original is `_wp_attached_file` (this is what disambiguates a `banner-1920x1080.jpg` original from a same-named derivative).
- Binary probe list: `mysqldump mysql openssl tar gzip sha256sum nohup bash`.
- `DB_HOST` may be `host:port` (e.g. `127.0.0.1:3306`) — split host and port for the client credentials file.

## wp-config define classification

- Auto-excluded — DB credentials: `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_CHARSET`, `DB_COLLATE`.
- Auto-excluded — auth keys and salts: `AUTH_KEY` and friends, every `*_SALT`, `NONCE_*` — production secrets never come down.
- Auto-excluded — domain and paths: `WP_HOME`, `WP_SITEURL`, `WP_CONTENT_DIR`, `WP_CONTENT_URL`, `ABSPATH`.
- Auto-excluded — infrastructure: `WP_CACHE`, redis/memcached host constants, `DISABLE_WP_CRON`.
- Everything else is the portable plugin/behaviour class offered at the gate — e.g. `WP_MEMORY_LIMIT`, feature flags, custom defines.

## Pack (production side)

- Working dir preference order: `sys_get_temp_dir()/kntnt-wp-skills-<rand>` → a writable dir above `ABSPATH` → (last resort) a docroot dir, mitigated by immediate cleanup and the self-destruct timer.
- Working-dir contents: `pass.key` (mode `0600`), `.my.cnf` (mode `0600`, written from the DB constants so credentials never appear on a command line; consumed via `--defaults-extra-file`), `pack.sh`, `pack.log`.
- Launch: `nohup bash pack.sh >> pack.log 2>&1 & echo $!` — the echoed PID is what the poll's liveness check uses.
- Passphrase: PHP `random_bytes(32)` as hex into `pass.key`; passed to openssl as `-pass file:pass.key`, never as an argument.
- DB dump, two passes, both with `mysqldump --single-transaction --quick --skip-lock-tables`: full data for the content tables, then `--no-data` for the empty-classified ones. Then `gzip`, then `openssl enc -aes-256-cbc -pbkdf2 -salt -pass file:pass.key` → `db.enc`.
- Files: `tar --exclude-from=<exclude-file> --anchored --no-wildcards --warning=no-file-changed -czf - <tree>` piped straight through the same `openssl enc` invocation → `files.enc` (no intermediate plaintext archive on disk).
- Exclusion-file entries are full anchored relative paths, one per line: the DB-known thumbnail paths, the excluded blobs, drop-ins, `wp-config.php`, logs, caches, `upgrade*`, `novamira-sandbox`.
- Checksums over the final names: `sha256sum db.enc files.enc > SHA256`.
- Publish: move `db.enc`, `files.enc`, `SHA256` into the random-named docroot download dir, mode `0644`.
- Robustness: `pack.sh` runs under `set -euo pipefail`; an error trap writes `FAILED` plus the last ~40 lines of `pack.log` (*free choice*) into the download dir and exits; on success it `touch`es `DONE`.
- Self-destruct: a detached `( sleep 3600; rm -rf "$WORKDIR" "$DLDIR" ) &` — the 3600 s delay is a *free choice*.
- Poll: check for `DONE` / `FAILED` / `kill -0 $PID`, with an explicit maximum wait; on `FAILED` surface the log tail; on timeout with a live PID keep waiting to the cap, then abort with the tail.

## Download and verify (local)

- Fetch order: `SHA256` first, then `db.enc` and `files.enc`, each with `curl -fSL -C - --retry 3`, into the local scratch area.
- Verify: `sha256sum -c SHA256` — the names match creation time exactly, no renaming.
- Fetch `pass.key` via Novamira `read-file` (never over HTTP), decrypt both artifacts with `openssl enc -d -aes-256-cbc -pbkdf2 -pass file:<local pass.key>`, and `gunzip` the DB dump.

## Import and localise (local)

- Pull rollback backup: `ddev export-db` → `.kntnt-wp-skills/backups/local-pre-import-<timestamp>.sql.gz`.
- Dump sanity checks against the discovered prefix: the `CREATE TABLE` count, an `INSERT INTO \`<prefix>posts\`` present, and each empty-classified table having exactly one `CREATE` and zero `INSERT`s.
- Import: `ddev import-db`; verify table and post counts afterwards.
- URL-scoped search-replace, one pass per source form, each `ddev wp search-replace '<old>' '<new>' --all-tables --skip-columns=guid --report-changed-only --skip-plugins --skip-themes`. Source forms, in order: `https://www.<domain>`, `http://www.<domain>`, `https://<domain>`, `http://<domain>`, protocol-relative `//www.<domain>` and `//<domain>`, and the escaped-slash forms `https:\/\/www.<domain>`, `https:\/\/<domain>`, `http:\/\/www.<domain>`, `http:\/\/<domain>` (page builders such as Elementor store URLs as escaped JSON). **Never** the bare domain — it corrupts `user@domain` addresses. Serialised PHP objects that wp-cli safely skips (Freemius caches etc.) keep the old domain; harmless.
- Re-apply the preserved inactive set with `--skip-plugins --skip-themes` on the deactivation calls, so an object-cache plugin cannot re-drop its drop-in mid-step.
- Cron opt-out (`--no-cron`): `define('DISABLE_WP_CRON', true);` in the marked block.
- Thumbnail regeneration: `wp media regenerate` scoped to the affected attachment IDs (all at clone; the metadata-driven delta at pull; `--regenerate-all` forces the lot). Default regenerate deletes-then-rebuilds, which is what wipes stale thumbnails of changed originals.
- Rewrite flush: `ddev wp rewrite flush --hard` — **without** `--skip-plugins`; a flush that skips plugins drops multilingual routes.
- `ddev restart` — clears the PHP-FPM APCu / object cache that `wp cache flush` cannot reach.

## Verify (smoke)

- Grep the fetched HTML for: `There has been a critical error`, `Fatal error`, `Error establishing a database`.
- Run `ddev wp db check`.

## Clone

- Name derivation example: `https://www.elfsborgsmarschen.se` → `elfsborgsmarschen` → DDEV project `elfsborgsmarschen.ddev.site`.
- Scaffold: `mkwp <name> --wp=<production's exact core version>`.

## Harmless stderr noise (never treat as failure)

- `mysqldump: Deprecated program name…` — MariaDB's dump tool announcing itself; cosmetic.
- WP-CLI `Deprecated:` notices under newer PHP — cosmetic; filter them from reports.

## Saved plan — illustrative shape

All keys optional; a missing key falls back to the built-in default. From the superseded design document:

```jsonc
{
  "source": { "mcpServer": "novamira-<site>", "liveUrl": "https://www.example.com" },
  "target": { "ddevProject": "<name>" },
  "db": { "emptyTables": ["wp_independent_analytics%", "wp_rcb_consent%", "wp_fsmpt_email_logs", "wp_relevanssi%"] },
  "scope": { "includeMedia": true, "excludeBlobs": ["wp-content/uploads/<gallery>", "wp-content/uploads/<maxmind-db-dir>"] },
  "wpConfigDefines": ["WP_MEMORY_LIMIT"],
  "plugins": { "preserveLocalInactive": true },
  "objectCache": "derive",
  "mail": "auto",              // auto = risk-adaptive default; "live" / "capture" pin it
  "cron": "leave",
  "deletions": { "mirror": false }
}
```

## Sibling retrofit checklist (out of scope here; recorded for later)

Retrofitting the manpage help model onto each sibling plugin is: add the per-skill manpages under `docs/man/`, swap in the echo-style help script, add the help-gate line as each skill's first step, and point the README at the manpages.

## Appendix — security-review reconciliation (historic record)

The 20-point security/robustness review raised during grilling, row by row, so a later reader never mistakes a conscious decision for an oversight. Rows marked **Departed/Deferred — settled** are recorded as ADRs; do not re-open them.

| # | Review point | Disposition |
|---|---|---|
| 1 | Encryption passphrase lifecycle undefined | Adopted — server-side passphrase, off the web, `read-file` only ([ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)) |
| 2 | Tarball unencrypted | Adopted — both artifacts encrypted ([ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)) |
| 3 | `sha256sum -c` breaks on the rename trick | Adopted — `.enc` from creation, no rename ([ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)) |
| 4 | Perms don't stop the web server; temp in docroot | Adopted — all packing outside the docroot ([ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)) |
| 5 | Aborted run strands the dump publicly | Adopted — self-destruct timer + health-check sweep |
| 6 | SMTP live + cron → local mass-mail to real people | **Departed — settled** — live mail by default with the mass-send valve; cron stays running ([ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md)) |
| 7 | Deletion under replay/`--yes` has no net | Adopted — deletions go to a local trash ([ADR-0010](./adr/0010-deletion-mirroring-opt-in-trash.md)) |
| 8 | `exec`/`shell_exec` capability not probed | Adopted (health-check probe); the native background-job **fallback is deferred — settled** ([ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md)) |
| 9 | Table prefix not written locally | Adopted |
| 10 | DB engine/collation + PHP not pinned | Adopted |
| 11 | `mysqldump` lacks consistency flags | Adopted — `--single-transaction --quick --skip-lock-tables` |
| 12 | Scope change poisons the deletion diff | Adopted — **chose "store scope in the baseline"** over a full-scope manifest, to avoid walking excluded trees — settled ([ADR-0006](./adr/0006-baseline-manifest-diff-with-scope.md)) |
| 13 | Search-replace misses escaped URLs | Adopted — escaped-slash + bare-`//` passes |
| 14 | Tar exclusions need anchored paths, not patterns | Adopted — exclusion file + `--anchored --no-wildcards` |
| 15 | `DONE` polling has no failure path | Adopted — `FAILED` marker, `kill -0`, explicit max wait ([ADR-0007](./adr/0007-background-pack-job-with-polling.md)) |
| 16 | Download path tested only when failure is costly | Adopted — health-check preflight |
| 17 | Prod object-cache drop-in can be fatal locally | Adopted — verify a request, auto-remove on failure |
| 18 | Rollback backup misplaced in the scratchpad | Adopted — written to the durable, gitignored backups dir |
| 19 | Verification assumes multilingualism | Adopted — monolingual-aware, URLs pulled from the DB |
| 20 | Smalls: mkwp-default cleanup; prefix-aware dump checks; media-regen metadata gap | Adopted; media-regen **extended beyond the review** — metadata-driven delta plus `--regenerate-all` ([ADR-0011](./adr/0011-metadata-driven-thumbnail-regeneration.md)) |

On point 6 — the one substantive departure: the operator explicitly chose the running-cron, live-mail default over the reviewer's (and the author's) more cautious proposal; the full rationale is [ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md).
