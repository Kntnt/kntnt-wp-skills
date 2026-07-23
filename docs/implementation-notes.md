# kntnt-wp-skills — implementation notes

This file preserves the invocation-level literals from the superseded design-and-build-plan document — exact commands, flags, filenames, permissions, timer values, and illustrative shapes — so that implementation never has to re-derive hard-won specifics. The specification ([`docs/spec.md`](./spec.md)) is authoritative for every decision; this file only pins the literals the spec deliberately abstracts, and where the two diverge the spec (or an ADR) wins. Literals marked *free choice* may be changed during implementation if a better value emerges; everything else was settled the hard way — through the security review or real-world debugging — and should be kept unless a test proves otherwise.

## Shipped templates

- The plugin ships the Mailpit capture mu-plugin template alongside its helper scripts; the engine instantiates it per run. The extraction, sealing, and cleanup the old client-side pack-script template once produced are now owned by the Kntnt Extractor plugin ([ADR-0017](./adr/0017-discovery-over-extractor-rest-two-phase.md)), so no pack template ships.
- The capture mu-plugin is `kntnt-wp-skills-mailpit.php`: it short-circuits `wp_mail` at top priority and delivers to DDEV's Mailpit at `127.0.0.1:1025`. Installed only in the capture branch.

## Health check

The channel is the Kntnt Extractor REST API over HTTPS with an Application Password (HTTP basic auth); every probe is a REST call, not a PHP payload ([ADR-0016](./adr/0016-kntnt-extractor-replaces-novamira-as-control-channel.md), [ADR-0017](./adr/0017-discovery-over-extractor-rest-two-phase.md)).

- API-version handshake: `GET /status` (unauthenticated) proves the Extractor endpoint is reachable and reports API version ≥ 2 — the version that ships the `environment` endpoint, structure-only extraction, and caller job listing together. An absent, unreachable, or too-old Extractor fails here with a precise install-or-upgrade instruction.
- Liveness, targeting, and authorisation in one round trip: `GET /environment` (requires both `kntnt_extractor_operate` and `manage_options`). A `200` is the liveness proof, its `home_url` is the verify-targets-production check (must match the intended production URL and must not be the local DDEV site), and a `200` proves the user holds both capabilities. A `403` fails fast with a per-capability remediation, disambiguated where useful by whether `GET /audit-log` (which is `manage_options`-only) also refuses.
- Stranded-job sweep (runs before the preflight below): `GET /extractions` lists the caller's own non-terminal jobs, and `DELETE /extractions/{id}` cancels each — belt-and-braces with the plugin's own TTL cleanup. Never concurrent with an in-flight preflight, so a batched pair of calls cannot cancel the preflight's own probe job.
- Download preflight: `POST /extractions` for exactly two tiny structure-only tables and no files — `{table_prefix}options` and `{table_prefix}users`, the prefix from the `GET /environment` round trip — sealed to a fresh key pair from `scripts/unseal.py keygen`: stdin `{"private_key_path": "<path>"}`, stdout `{"public_key": "<base64>"}`; the private key is written to that path (mode 0600) and never emitted into model context. Poll the job to completion under the standard poll discipline (10-minute preflight budget), fetch its one-time `download_url` over HTTPS from the local side, unseal it with `scripts/unseal.py unseal` (full stdin/stdout contract pinned below, in *Download and unseal (local)*), then consume the job with `POST /extractions/{id}/consume`. This exercises the real serving path — permissions, extension rules, basic auth, WAF/CDN behaviour — and, since two tables are two packaging chunks, the continuation path a one-chunk job never touches. Wall time from the `201` to the first `ready` poll is the verdict: ≤ 90 s passes silently; slower but within the budget passes with a loud backstop-cadence warning plus an operator gate (a `--yes` run aborts instead); not ready within the budget aborts with the warning as the remediation ([ADR-0018](./adr/0018-poll-discipline-and-two-chunk-preflight.md)).

Discovery is reconstructed client-side from `GET /environment`, `GET /tables`, `GET /files`, and a small bootstrap extraction parsed locally — no longer a single server-side payload ([ADR-0017](./adr/0017-discovery-over-extractor-rest-two-phase.md)).

- Runtime/config scalars come from `GET /environment`: PHP version, server software, WordPress core version, home and site URL, table prefix, content and uploads dirs, the DB server flavour/version/default collation (MySQL 8 vs MariaDB, to pin DDEV and avoid the collation import crash), active plugins, drop-ins present, and the resolved `wp-config` defines with the secret family masked to `null` server-side. The secrets are never fetched, so there is no `DB_HOST`/`DB_PASSWORD` to split or leak.
- Sizes and enumerations come from `GET /tables` and `GET /files` (the latter paged via an opaque `cursor`): DB total and top tables, the authoritative table list, the per-subdirectory uploads breakdown, plugin/theme directories, drop-in presence, the blob-heuristic inputs, and the candidate generated-thumbnail files.
- Thumbnail exclude-set source: each attachment's `_wp_attachment_metadata → sizes[*].file`, parsed client-side from the bootstrap extraction; the original is `_wp_attached_file` (this is what disambiguates a `banner-1920x1080.jpg` original from a same-named derivative).
- The InnoDB-consistency, disk-space, and production-binary checks the old single-call discovery ran are gone: dumping now happens inside the Extractor plugin, which owns those concerns.

## wp-config define classification

- Auto-excluded — DB credentials: `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_CHARSET`, `DB_COLLATE`.
- Auto-excluded — auth keys and salts: `AUTH_KEY` and friends, every `*_SALT`, `NONCE_*` — production secrets never come down.
- Auto-excluded — domain and paths: `WP_HOME`, `WP_SITEURL`, `WP_CONTENT_DIR`, `WP_CONTENT_URL`, `ABSPATH`.
- Auto-excluded — infrastructure: `WP_CACHE`, redis/memcached host constants, `DISABLE_WP_CRON`.
- Everything else is the portable plugin/behaviour class offered at the gate — e.g. `WP_MEMORY_LIMIT`, feature flags, custom defines.

## Baseline manifest and local filtering (issue #18)

- Production's **whole** install-root tree — not scoped to content, and including WordPress core (`wp-admin/`, `wp-includes/`, the root core PHP files) — comes from `GET /files` (paged via an opaque `cursor`) as `{ "path", "size", "mtime" }` entries, unfiltered and anchored at the install root — the exclusion set never travels to production as part of the request. Core is kept out of the transfer entirely client-side, by `ALWAYS_EXCLUDED` (issue #37); nothing on the server scopes the manifest to exclude it.
- Filter that raw walk locally with `uv run scripts/filter_manifest.py`, feeding it `{ "entries": <the GET /files entries>, "exclusions": <the resolved exclusion set, assembled by `scripts/build_exclusions.py` — the single source of truth for the set, never hand-assembled (issue #35)> }` on stdin. It restricts the entries to the in-scope subset and attaches the resolved set as `{ "scope": { "exclusions": [...] } }` on stdout — the shape `scripts/baseline_diff.py` has always consumed as its `current` side.
- Only the locally-filtered result — never the raw walk — is combined with the stored baseline for `scripts/baseline_diff.py`, and only the locally-filtered result is persisted as the next run's baseline.
- Keeping the exclusion set client-side matters because a real site's set can run into the thousands of entries (one smoke test measured 6,135 / ~436KB), which would be wasteful to embed in a production request and would bloat agent context. The whole enumeration comes down over the paged `GET /files`; the harness auto-saves the (potentially large) response to file.
- Scope semantics are unchanged from the former production-side filter — an exact match or a path-segment-aware descendant of an exclusion prefix.
- The Extractor plugin owns the robustness of the walk itself: a permission-denied subdirectory is skipped rather than aborting the enumeration, and an invalid-UTF-8 filename is handled server-side, so `GET /files` returns a complete, well-formed page regardless of what the tree contains.

## Extraction (production side) — owned by the plugin

The whole client-side pack machinery this section once pinned — the outside-docroot working dir, `pass.key`, `.my.cnf`, `nohup bash pack.sh`, the two `mysqldump` passes, `gzip`, `openssl enc`, `tar`, `sha256sum`, the docroot download dir, the self-destruct timer, and the `DONE`/`FAILED`/`kill -0` poll — is retired. The Kntnt Extractor plugin owns all of it now ([ADR-0017](./adr/0017-discovery-over-extractor-rest-two-phase.md)); `kntnt-wp-skills` generates no shell script, handles no passphrase, runs no `openssl`, and stages nothing in the docroot. What the skills own is only the client side of it:

- Build the **selection** from the resolved plan — `tables` (full data), `tables_structure_only` (DROP/CREATE DDL, no rows, for every empty-classified table), and `files` (install-root-relative paths, already reduced locally by the resolved exclusion set `scripts/build_exclusions.py` assembles — the same set the baseline is filtered under, so the two never diverge (issue #35)). The selection is an explicit list of paths, so no command-line exclusion patterns or argument-limit hazards arise.
- Submit with `POST /extractions`, sealed to the run's ephemeral X25519 `public_key` (base64). The plugin runs the extraction as its own detached background job outside the docroot, seals each table and file segment into the `KNTNTEXT` container, and exposes a **one-time `download_url`** once the job reaches its terminal success state.
- Poll the job by id to that state under the standard poll discipline: every 15 s after a successful poll, a 120 s per-request timeout (`curl --max-time 120`), retry after 30 s on the first consecutive transport timeout / connection error / 5xx and after 60 s on each further one, resetting on the next success; overall wall-clock budgets 10 min (preflight), 15 min (bootstrap), 60 min (`poll_max_wait_seconds = 3600`, main extraction). A job is failed only on `state == "failed"`, a confirmed-vanished job (`404`, re-confirmed via `GET /extractions` and a second poll), no progress-advance (a state change, or an increase in `progress.tables_done + progress.files_done`) within the 10-minute stall window, or budget exhaustion — never on a single transport failure. Structure-only tables count toward poll progress ([ADR-0018](./adr/0018-poll-discipline-and-two-chunk-preflight.md)).
- The DB dump, live-site consistency handling, sealing, TTL/watchdog cleanup, and outside-docroot staging are all the plugin's responsibility — the equivalents of the old `--single-transaction --quick --skip-lock-tables` passes and the self-destruct timer live inside Extractor now.

## Download and unseal (local)

- Fetch the sealed container over HTTPS from the one-time `download_url` with resume and retry: `curl -fSL -C - --retry 3` into the local scratch area.
- Unseal with the deterministic helper `uv run scripts/unseal.py unseal` (`pynacl` inline dependency). Stdin is `{"container_path": ..., "private_key_path": ..., "sql_path": ..., "files_root": ..., "tables": [...], "structure_only": [...], "files": [...]}` — the first four keys are required (a missing one exits 1); the three lists must equal the extraction request's selection, in order, or the container validation refuses the mismatch (`Container's … segments do not match the requested …`). Stdout is `{"sql_path": ..., "tables_written": ..., "structure_only_written": ..., "files_written": ..., "bytes_sql": ...}`. The ephemeral private key — which never leaves the operator's machine and is never transmitted — opens each segment's sealed key (`crypto_box_seal` open), each segment is decrypted (`crypto_secretbox` open), and the container is reassembled — table segments concatenated into one importable `.sql` with a prepended connection-safe preamble, file segments written to disk by their install-root-relative path.
- The `crypto_secretbox` authentication is what catches a truncated or corrupted download — a tampered or short segment fails to open, so a bad transfer is caught before it touches the local site. No separate checksum file is needed, and none is produced.
- Immediately after the container unseals, consume the job with `POST /extractions/{id}/consume` and confirm it is gone. `DELETE /extractions/{id}` is only for cancelling a stranded or aborted job, never the happy-path close. The plugin's own TTL/watchdog cleanup and the next health check's stranded-job sweep are the backstops.

## Import and localise (local)

- Pull rollback backup: `ddev export-db` → `.kntnt-wp-skills/backups/local-pre-import-<timestamp>.sql.gz`.
- Dump sanity checks against the discovered prefix: the `CREATE TABLE` count, an `INSERT INTO \`<prefix>posts\`` present, and each empty-classified table having exactly one `CREATE` and zero `INSERT`s.
- Import: `ddev import-db`; verify table and post counts afterwards.
- URL-scoped search-replace, one pass per source form, each `ddev wp search-replace '<old>' '<new>' --all-tables --skip-columns=guid --report-changed-only --skip-plugins --skip-themes`. Source forms, in order: `https://www.<domain>`, `http://www.<domain>`, `https://<domain>`, `http://<domain>`, protocol-relative `//www.<domain>` and `//<domain>`, the escaped-slash forms `https:\/\/www.<domain>`, `https:\/\/<domain>`, `http:\/\/www.<domain>`, `http:\/\/<domain>` (page builders such as Elementor store URLs as escaped JSON), the escaped-slash protocol-relative forms `\/\/www.<domain>` and `\/\/<domain>` (a stored protocol-relative URL has no scheme to anchor the scheme-ful escaped passes), the double-escaped-slash forms `https:\\/\\/www.<domain>`, `https:\\/\\/<domain>`, `http:\\/\\/www.<domain>`, `http:\\/\\/<domain>` (JSON-within-JSON storage, e.g. one plugin's serialised config nested inside another plugin's JSON option — `\\/\\/` is not a substring of `\/\/`, so the single-escaped pass alone misses it), and, by the same argument, the double-escaped-slash protocol-relative forms `\\/\\/www.<domain>` and `\\/\\/<domain>`. **Never** the bare domain — it corrupts `user@domain` addresses. Serialised PHP objects that wp-cli safely skips (Freemius caches etc.) keep the old domain; harmless.
- Re-apply the preserved inactive set with `--skip-plugins --skip-themes` on the deactivation calls, so an object-cache plugin cannot re-drop its drop-in mid-step.
- Marked-block write: `uv run scripts/wpconfig_block.py` takes the current `wp-config.php` text, the resolved portable defines, the table prefix, and the cron decision, and returns the new full text with the skills' marked block written (delimited by `// BEGIN kntnt-wp-skills` / `// END kntnt-wp-skills`, inserted above the `/* That's all, stop editing!` line when absent) and every scaffold collision it supersedes removed. The collision set is **computed** — the portable defines plus `DISABLE_WP_CRON` intersected with whatever the scaffold shipped — never a hard-coded name list; the smoke test's scaffold carried five collisions where the SKILL prose named two, and a repeated `define()` on the same constant fatals (issue #42). The write is followed by `ddev exec php -l wp-config.php`, aborting the run on any parse error.
- Cron opt-out (`--no-cron`): `define('DISABLE_WP_CRON', true);` in the marked block, applied via the helper's `cron` input.
- Thumbnail regeneration: `wp media regenerate` scoped to the affected attachment IDs (all at clone; the metadata-driven delta at pull, restricted to attachments with a *regenerable-named* size missing — [ADR-0011](adr/0011-metadata-driven-thumbnail-regeneration.md)'s amendment; `--regenerate-all` forces the lot). Default regenerate deletes-then-rebuilds, which is what wipes stale thumbnails of changed originals — and why a non-regenerable-named gap must never reach it.
- Rewrite flush: `ddev wp rewrite flush --hard` — **without** `--skip-plugins`; a flush that skips plugins drops multilingual routes.
- `ddev restart` — clears the PHP-FPM APCu / object cache that `wp cache flush` cannot reach.

## Verify (smoke)

- Grep the fetched HTML for: `There has been a critical error`, `Fatal error`, `Error establishing a database`.
- Run `ddev wp db check`.

## Clone

- Name derivation example: `https://www.elfsborgsmarschen.se` → project `elfsborgsmarschen` (DDEV `elfsborgsmarschen.ddev.site`), directory `www.elfsborgsmarschen.se`.
- Scaffold: `mkwp <name> --dirname=<directory_name> --wp=<production's exact core version>`.

## Harmless stderr noise (never treat as failure)

- WP-CLI `Deprecated:` notices under newer PHP (the local `ddev wp` calls) — cosmetic; filter them from reports.
- Production-side dump noise (e.g. MariaDB's `mysqldump: Deprecated program name…`) no longer reaches the client at all — the Extractor plugin runs the dump inside its own background job, and the skills only fetch the sealed result.

## Saved plan — illustrative shape

All keys optional; a missing key falls back to the built-in default. The saved plan stores **decisions, never computed lists** (ADR-0005) — this is the real flat snake_case shape `resolve_plan.py save` emits (`scripts/resolve_plan.py`'s `SAVED_KEYS` and `PERSISTED_METADATA_KEYS`), from a run against `https://www.example.com`:

```jsonc
{
  "target": "example",
  "directory": "www.example.com",
  "media": "include",
  "blobs": "exclude",
  "ported_defines": ["WP_MEMORY_LIMIT"],
  "plugin_preservation": "preserve",
  "object_cache": "derive",
  "mail": "risk_adaptive",     // accepting the recommendation stores the mode, not the momentary live/capture outcome (ADR-0009)
  "cron": "run",
  "deletion_mirroring": "off",
  "user_submissions": "empty",  // carry/empty privacy gate for form-entry tables (ADR-0014)
  "crm_subscribers": "empty",   // carry/empty privacy gate for CRM/mailer subscriber tables (ADR-0019)
  "source": { "extractor_endpoint": "https://www.example.com/wp-json/kntnt-extractor/v1", "live_url": "https://www.example.com" }
}
```

## Sibling retrofit checklist (out of scope here; recorded for later)

Retrofitting the manpage help model onto each sibling plugin is: add the per-skill manpages under `docs/man/`, swap in the echo-style help script, add the help-gate line as each skill's first step, and point the README at the manpages.

## Appendix — security-review reconciliation (historic record)

The 20-point security/robustness review raised during grilling, row by row, so a later reader never mistakes a conscious decision for an oversight. Rows marked **Departed/Deferred — settled** are recorded as ADRs; do not re-open them.

The table below is a **historic record** of how the review was dispositioned at the time, kept verbatim. Several rows (1–5, 8, 14, 15) describe the retired client-side pack/encryption/exec machinery — the server-side passphrase, the `.enc` artifacts, the `tar` exclusion file, the `DONE` poll, the `exec` probe. That whole mechanism was superseded by the control-channel cutover: the Kntnt Extractor plugin now owns the extraction, per-segment sealing (`crypto_secretbox` under a `crypto_box_seal`-wrapped key, no passphrase and no `openssl`), the one-time download link, and TTL cleanup ([ADR-0016](./adr/0016-kntnt-extractor-replaces-novamira-as-control-channel.md), [ADR-0017](./adr/0017-discovery-over-extractor-rest-two-phase.md)). The security *intents* those rows adopted are all still met — just inside the plugin rather than in a generated `pack.sh`. The rows are not live instructions.

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
| 13 | Search-replace misses escaped URLs | Adopted — escaped-slash, double-escaped-slash, and their protocol-relative (`\/\/`, `\\/\\/`) passes, plus the plain bare-`//` pass |
| 14 | Tar exclusions need anchored paths, not patterns | Adopted — exclusion file + `--anchored --no-wildcards` |
| 15 | `DONE` polling has no failure path | Adopted — `FAILED` marker, `kill -0`, explicit max wait ([ADR-0007](./adr/0007-background-pack-job-with-polling.md)) |
| 16 | Download path tested only when failure is costly | Adopted — health-check preflight |
| 17 | Prod object-cache drop-in can be fatal locally | Adopted — verify a request, auto-remove on failure |
| 18 | Rollback backup misplaced in the scratchpad | Adopted — written to the durable, gitignored backups dir |
| 19 | Verification assumes multilingualism | Adopted — monolingual-aware, URLs pulled from the DB |
| 20 | Smalls: mkwp-default cleanup; prefix-aware dump checks; media-regen metadata gap | Adopted; media-regen **extended beyond the review** — metadata-driven delta plus `--regenerate-all` ([ADR-0011](./adr/0011-metadata-driven-thumbnail-regeneration.md)) |

On point 6 — the one substantive departure: the operator explicitly chose the running-cron, live-mail default over the reviewer's (and the author's) more cautious proposal; the full rationale is [ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md).

On point 12 — refined 2026-07-19 (explicit operator authority): the "avoid walking excluded trees" mechanism moved — the whole tree is now enumerated unfiltered over the Extractor `GET /files` endpoint (paged via `cursor`), and the exclusion set is applied locally by `scripts/filter_manifest.py` instead of being embedded in a production-side walk (issue #18, carried forward under [ADR-0017](./adr/0017-discovery-over-extractor-rest-two-phase.md)). The adopted resolution, "store scope in the baseline", and the deletion diff's scope-intersection rule are unchanged; see the [ADR-0006](./adr/0006-baseline-manifest-diff-with-scope.md) addendum.
