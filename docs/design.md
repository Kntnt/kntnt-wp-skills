# kntnt-wp-skills — design and build plan

Status: pre-implementation plan, revised after a security/robustness review. This document is the single source of truth for the design agreed during grilling; the build follows it. The **architectural decisions** behind it — with their rationale and rejected alternatives — are recorded as ADRs in [`docs/adr/`](./adr/); the project's **terminology** is defined in [`CONTEXT.md`](../CONTEXT.md). Language of all user-facing text and documentation is British English (`en_GB`); identifiers, flags, and config keys are English.

## 1. Purpose and scope

`kntnt-wp-skills` is a Claude Code plugin, built to the same conventions as `kntnt-code-skills` and `kntnt-text-skills`, that mirrors a live WordPress site down into a local DDEV copy.

It ships two skills:

- **`clone`** — create a fresh local DDEV copy of a production site in an empty directory.
- **`pull`** — refresh an existing local copy from production.

Both are **user-invoked only** (`disable-model-invocation: true`) — see [ADR-0002](./adr/0002-skills-user-invoked-only.md).

Scope is deliberately narrow: single-site WordPress, personal use, driven by hand. There is exactly one control channel (the Novamira MCP) and no SSH ([ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md)).

## 2. Preconditions (documented in the README)

The skills assume the operator has already solved these; the README explains each for someone starting from zero.

- **DDEV up and running**, which in turn needs Docker (or an equivalent such as OrbStack) plus DDEV's own dependencies (mkcert, mutagen). These are DDEV concerns, not this plugin's.
- **The free Novamira plugin installed and enabled on the production site**, with its MCP server connected in Claude Code. This is the sole control channel (§4). The free AGPL build is sufficient — it exposes `execute-php`, `run-wp-cli` (with native background jobs), and file read/write/list. Novamira Pro is not required.
- **`mkwp` available on the operator's `PATH`** — used by `clone` to scaffold the local site.

## 3. Architecture

Two user-invoked skills sit over **one shared transfer engine**. The engine does discovery, packaging on production, the pull, verification, remote cleanup, import, and localisation. `clone` and `pull` differ only at the bookends.

- **`clone` = `pull` against an empty baseline** — see [ADR-0003](./adr/0003-single-transfer-engine-clone-is-pull.md).
- **Decoupled from `mkwp`** (scaffold only; import and localisation live in the skill engine) — see [ADR-0004](./adr/0004-decoupled-from-mkwp.md).

Plugin layout mirrors the sibling plugins:

- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- `skills/clone/SKILL.md`, `skills/pull/SKILL.md`
- `commands/help.md`
- `scripts/` — the shared engine helpers, `help.py`, the pack script template, the Mailpit mu-plugin template
- `docs/man/clone.md`, `docs/man/pull.md` — the manpages (§12)
- `AGENTS.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`

## 4. Control channel

The Novamira MCP is the **sole** channel to production — no SSH, ever; rationale and alternatives in [ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md).

**Mandatory step 0 — health check, on every run of both skills.** It fails *early and cheaply*, before any heavy work, on the things that otherwise surface only after a multi-GB pack has run on production:

1. Locate the connected `novamira-*` MCP server whose `home_url()` matches the target production URL; if several or none match, ask.
2. Call a trivial `execute-php` returning `home_url()`, `ABSPATH`, `phpversion()`, `SERVER_SOFTWARE` — this proves the channel is *live*, not merely connected (ability discovery can 404 even when the server is connected).
3. Confirm it targets **production**, not the local DDEV site (the verify-targets-prod safety rail).
4. **Probe process-spawning.** The pack job runs via `nohup bash … &` from `execute-php`, which dies silently if `exec`/`shell_exec`/`proc_open` sit in `disable_functions` (a common managed-host hardening). Check `function_exists('exec')`, inspect `disable_functions`, and run a live `exec('printf ok')` round-trip. A working `run-wp-cli` does **not** prove this — Novamira may run WP-CLI in-process — so the probe is independent. If blocked, abort with a precise message (a native-`run-wp-cli`-background-job fallback is a possible future path, not built now — [ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md)).
5. **Download-path preflight.** Write a tiny extension-less test file into a throwaway docroot dir, `curl -fsS` it over HTTPS from the local side, then delete it. This exercises the whole chain — file permissions, the host's archive-extension rules, basic-auth, WAF/Cloudflare, CDN caching — before the heavy pack, so a blocked download is caught in seconds rather than after gigabytes.
6. **Stranded-workspace sweep.** List the outside-docroot temp base and the docroot download base for leftover `kntnt-wp-skills-*` dirs from an aborted earlier run and remove them (belt-and-braces with the self-destruct timer of §7.3).
7. On any failure — server missing, abilities route 404, plugin disabled, exec blocked, download blocked — abort with a precise remediation message (e.g. "enable Novamira and its MCP feature on production").

`run-wp-cli` always takes `args` as a JSON **array** (`["plugin","list"]`); a single string silently returns `wp help` with exit 0.

## 5. The decision backbone

Every decision is a **recommendation with an accept/override gate**, three speeds run over one ordered decision list, and defaults layer without precedence ceremony — the full shape and rationale are in [ADR-0005](./adr/0005-decision-backbone-gates-and-layered-defaults.md). Operationally:

- **Interactive** (default) — walk each gate; `Y` accepts the recommendation, `n` reveals the alternatives and you choose.
- **`--yes`** (autonomous) — accept every recommendation, never pause, and print a full record of what was decided and done, to read on return.
- **Replay** — when a saved plan exists for the site, the recommendations *are* the remembered answers, so interactive collapses to a single *"Replay the saved plan? [Y/n]"* gate, and `--yes` runs it silently. This is the "quick and dirty" repeat refresh.

```
built-in default  <  live derivation  <  saved config  <  this run's answer
```

- **built-in** — the skill's baked-in stance.
- **live derivation** — computed fresh each run: production discovery (sizes, heavy dirs, core version, DB engine, PHP version, the mail mass-send risk) and, for `pull`, local state (which plugins are inactive, who owns `object-cache.php`).
- **saved config** — the operator's remembered answers from last time.
- **this run's answer** — interactive only; `--yes` stops at the saved-config layer.

The saved config stores **decisions, not computed lists** — the inactive-plugin set and blob list re-derive from live state each run, so nothing goes stale. It is written whenever a plan is accepted and exists mainly to make replay a one-liner. See §13.

## 6. The decisions and their recommended defaults

| Decision | Recommended default | Notes |
|---|---|---|
| DB — table structure | **All tables, always**, with production's exact schema | No table is ever omitted; nothing hits a missing table |
| DB — table content | Full data for content/config/users/CRM/forms; **empty** for operational tables (analytics / cookie-consent / email-log / search-index) | Binary per table: full or empty. "Full dump" = empty-set is none |
| Table prefix | **Adopt production's prefix locally** | Written into local `wp-config.php` at `clone`; verified at `pull`; see §6.5 |
| DB engine + PHP | **Pin DDEV to production's** | MySQL-vs-MariaDB and PHP `major.minor` from discovery; see §8 |
| Media Library originals | **Included** | `clone`: full; `pull`: delta only (§7.2) |
| Generated thumbnails | **Excluded**, regenerated locally | Only the DB-known sizes (`_wp_attachment_metadata → sizes[*].file`); see §6.1 |
| Side-loaded / orphan files | **Pulled whole** | Cannot be regenerated (`wp media regenerate` is DB-only), so we carry them |
| Heavy blobs (gallery dir, `.mmdb`, backups, dumps) | **Excluded**, behind a prompt | Deterministic heuristic flags outliers; the AI writes the recommendation, does not decide freely |
| `wp-config.php` defines | Copy the plugin/behaviour defines; **auto-exclude** the infra/secret class | See §6.2 |
| Plugins to deactivate (`pull`) | **Preserve the local inactive set** | Derived from live local state each run |
| Object-cache drop-in (`pull`) | **Derive from local-vs-prod ownership**, then verify | keep-local / take-prod / none; auto-remove on failure (§7.6) |
| Transactional email / mail | **Keep the existing mailer active** — flips to **capture via Mailpit** only if discovery finds an imminent mass-send | Lets you test mail end-to-end (Postmark etc.); `--live-mail` / `--capture-mail` force it; see §6.4 |
| Cron | **Leave running** always; `--no-cron` opts out | The mail risk-scan is what keeps this safe; see §6.4 |
| Deletion mirroring | **No** | Scoped, itemised, and reversible (local trash) when enabled; see §6.3 |

### 6.1 Thumbnails and regeneration

The full decision — why only DB-known sizes are excluded, why side-loaded files are pulled whole, and why `pull`-time regeneration is metadata-driven rather than file-diff-driven — is [ADR-0011](./adr/0011-metadata-driven-thumbnail-regeneration.md). Operationally: **exclude** exactly the DB-known generated sizes (`_wp_attachment_metadata → sizes[*].file`); **pull whole** everything not in that set; **regenerate** the affected DB attachments after import — all of them at `clone`, the metadata-driven delta at `pull` (compare each attachment's registered `sizes[*]` against the files on disk), with `--regenerate-all` as the escape hatch.

### 6.2 wp-config.php defines

Discovery extracts production's `define()`s. A class is **auto-excluded** because copying it would break or mis-key the local site:

- DB credentials (`DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_CHARSET`, `DB_COLLATE`)
- auth keys and salts (`AUTH_KEY`, `*_SALT`, `NONCE_*`, …) — never copy production secrets down
- domain and paths (`WP_HOME`, `WP_SITEURL`, `WP_CONTENT_DIR`, `WP_CONTENT_URL`, `ABSPATH`)
- infrastructure (`WP_CACHE`, redis/memcached hosts, `DISABLE_WP_CRON`)

The **remaining** defines — the plugin/behaviour constants a plugin might expect (`WP_MEMORY_LIMIT`, feature flags, custom `define()`s) — are offered as a gate, default **copy [Y]**, deselect on `n`. Chosen defines are written into a clearly **marked block** in the local `wp-config.php`, separate from mkwp's DDEV block, and the chosen set is remembered. Because `pull` never overwrites `wp-config.php`, ported defines persist; if production later grows a new such define, the `pull` report surfaces it.

### 6.3 Deletion mirroring

Why deletion is opt-in, limited to two safe sources, and never a hard `rm` is [ADR-0010](./adr/0010-deletion-mirroring-opt-in-trash.md). Operationally, when enabled, each source is itemised:

- **Production-deleted files** — `baseline − prod_now`, intersected with the current scope (§7.2).
- **Plugin/theme drift** — local plugins/themes with no production counterpart, presented as a checklist.

Confirmed items are **moved to a local trash** (`.kntnt-wp-skills/trash/<timestamp>/`, gitignored) and the path is reported. Default is **No** (and under `--yes` there must be no surprise removals). It is a remembered per-site answer, so "make it identical" is achieved by setting it Yes once for that site.

### 6.4 Outbound side effects — mail, cron, and the mass-send valve

The posture — faithful by default with one risk-adaptive valve, cron left running, a settled departure from the security review — is [ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md). Operationally:

- **Mail gate:** *"Keep the site's existing mail solution active? [Y/n]"*, recommending **Y**. `n` routes mail to DDEV's Mailpit instead.
- **The valve:** when discovery finds a poised mass-send (§7.1), the gate leads with a loud, specific warning (*"FluentCRM has a campaign scheduled to 200 recipients"*) and the recommendation flips to **capture via Mailpit** (Y = Mailpit). Mere presence of FluentCRM/MailPoet/etc. never flips it.
- **Capture, when chosen, is a mu-plugin.** `kntnt-wp-skills-mailpit.php` short-circuits `wp_mail` to Mailpit (`localhost:1025`) at top priority. It is installed **only** in the capture branch.
- **Cron always runs** unless `--no-cron` (`define('DISABLE_WP_CRON', true)`). The residual non-mail outbound channels are itemised in the always-on risk warning (§10).
- **Overrides for unattended runs:** `--yes` accepts the risk-adaptive recommendation — live mail normally, auto-capture on a detected campaign, no flag needed for the common path. `--live-mail` forces the real mailer even past a detected campaign (the "send/test anyway" override); `--capture-mail` forces Mailpit regardless.

### 6.5 Table prefix

Discovery reads production's `$table_prefix`. mkwp scaffolds `wp_`; if production differs, the imported tables exist but WordPress finds none of them. So `clone` writes production's prefix into the local `wp-config.php`'s marked block, and `pull` verifies the local prefix matches production and **aborts on mismatch** rather than importing tables the local install cannot see.

## 7. The transfer engine, phase by phase

Everything on production goes through Novamira `execute-php` / `run-wp-cli`.

### 7.0 Health check

As §4 (now including the exec probe, the download preflight, and the stranded-workspace sweep).

### 7.1 Discovery (production, read-only)

One `execute-php` call gathers: `home_url()`, `site_url()`, `ABSPATH`, `WP_CONTENT_DIR`, uploads basedir; DB total size and top tables by size; a per-top-level-subdir size breakdown of `uploads/` (to see the heavy dirs); `SERVER_SOFTWARE`; **the DB server flavour + version and default collation** (`SELECT VERSION()`, `@@version_comment` — MySQL 8 vs MariaDB, so the local DDEV DB can be pinned and the `utf8mb4_0900_ai_ci` import crash avoided); **whether the content tables are InnoDB** (so `mysqldump --single-transaction` is safe); `phpversion()` (used to pin DDEV's PHP `major.minor`); `disk_free_space`; `is_writable(ABSPATH)`; the table prefix; `get_option('active_plugins')` and whether a multilingual plugin is among them (drives verification, §7.7); the **mass-send risk scan** (§6.4) — for each active bulk-mail engine it recognises (FluentCRM, MailPoet, The Newsletter Plugin, Mailchimp for WP, Brevo, …), whether a campaign is queued/scheduled and the recipient-list size, since a *queued campaign* (not mere installation) is what flips the mail default; for an unrecognised mailer it falls back to a generic signal (a sending WP-cron event plus a large pending queue) and, when uncertain, does **not** flip but surfaces it; drop-ins present; theme list; core version (for mkwp pinning); the DB constants (`DB_HOST` may be `host:port`) — but **never** return `DB_PASSWORD` into context. It also probes binaries (`mysqldump mysql openssl tar gzip sha256sum nohup bash`), runs the blob scan, and computes the generated-thumbnail exclude-list from `_wp_attachment_metadata`.

### 7.2 Baseline diff (files)

Production emits a manifest of the in-scope tree (path + size + mtime) **plus the scope it was taken under**. The diff is **production-now against the stored last-sync baseline** (`.kntnt-wp-skills/last-sync.json`) — why the local filesystem is never a diff side, and why the scope travels with the baseline, is [ADR-0006](./adr/0006-baseline-manifest-diff-with-scope.md). `clone` has no baseline, so everything is new. The diff yields the new/changed set (to pull) and the production-deleted set (for the deletion gate); the deletion set is computed **only over paths that were in scope in both the baseline and this run**. Detection is size + mtime; a checksum mode can be added later. The DB is always dumped in full (it is ~2 MB trimmed — not worth diffing).

### 7.3 Pack on production (background job)

All packing happens in a **working dir outside the docroot** — `sys_get_temp_dir()/kntnt-wp-skills-<rand>`, else a dir above `ABSPATH` if writable, else (last resort) a docroot dir mitigated by the immediate cleanup of §7.5 and the self-destruct timer below. The passphrase file, `.my.cnf` (`0600`), `pack.log`, and every intermediate dump live here, never web-readable. Only the three finished artifacts are published into a **random-named docroot download dir** so `curl` can reach them. The exposure model — encryption, `.enc` naming, passphrase lifecycle — is [ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md); the background-job-plus-polling shape is [ADR-0007](./adr/0007-background-pack-job-with-polling.md).

Via `execute-php`: create the working dir and the download dir, write the `.my.cnf` from the DB constants, generate the encryption passphrase, write `pack.sh`, launch it with `nohup bash pack.sh >> pack.log 2>&1 & echo $!`, then **poll** for `DONE` / `FAILED` (avoids MCP timeouts on the heavy steps).

- **Passphrase** — generated server-side (`random_bytes(32)`, hex) into `pass.key` (`0600`) in the working dir, passed to `openssl` via `-pass file:pass.key`, fetched to the local side through Novamira's authenticated `read-file` (never over HTTP), and deleted in cleanup. It never touches a web-readable path ([ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md) records the read-file trade-off).
- **DB, two passes** — `mysqldump --single-transaction --quick --skip-lock-tables` (safe because discovery confirmed InnoDB; if any content table is MyISAM, fall back with a logged consistency caveat) — full for content tables, then `--no-data` for the empty-classified ones (so all tables exist, some with zero rows). `gzip`, then `openssl enc -aes-256-cbc -pbkdf2 -salt -pass file:pass.key` → **`db.enc`**.
- **Files** — write the exclusion set (DB-known thumbnail paths, excluded blobs, drop-ins, `wp-config.php`, logs, caches, `upgrade*`, `novamira-sandbox`) as **full anchored relative paths to an exclude file**, then `tar --exclude-from=<file> --anchored --no-wildcards --warning=no-file-changed -czf - …` piped straight through `openssl enc …` → **`files.enc`**. Writing paths to a file (not argv) avoids `ARG_MAX`, and `--anchored --no-wildcards` stops `image-150x150.jpg` from matching a legitimate original of the same name elsewhere. For `pull`, only the new/changed set is packed.
- **Checksums + publish** — `sha256sum db.enc files.enc > SHA256` (final names, so `sha256sum -c` matches downstream), then **move** `db.enc`, `files.enc`, `SHA256` into the docroot download dir (`0644`).
- **Robustness** — `pack.sh` runs under `set -euo pipefail` with a `trap` that on error writes `FAILED` plus the last ~40 lines of `pack.log` into the download dir and exits; on success it `touch`es `DONE`. It also arms a self-destruct — a detached `( sleep 3600; rm -rf "$WORKDIR" "$DLDIR" ) &` — so both dirs and the passphrase vanish even if the client never returns.
- **Polling** — check for `DONE` / `FAILED` / `kill -0 $PID` with an explicit maximum wait; on `FAILED`, surface the log tail and abort; on timeout with a live PID, keep waiting to the cap, then abort with the tail.

### 7.4 Download and verify (local)

`curl -fSL -C - --retry 3` the extension-less `SHA256`, then `db.enc` and `files.enc`, from the docroot download URL into the scratchpad; `sha256sum -c SHA256` (names match, no rename games). Then fetch `pass.key` via Novamira `read-file`, `openssl enc -d …` both artifacts, and gunzip the DB.

Both artifacts are named `.enc` **from creation** — not renamed after the fact — for the two reasons recorded in [ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md) (hosts 404 archive extensions; identical create-time/verify-time names keep `sha256sum -c` honest). The download preflight (§4.5) already proved this path works before the pack ran.

### 7.5 Close the exposure window (production)

Immediately after checksums pass, recursively delete **both** the docroot download dir and the outside-docroot working dir (including `pass.key` and `.my.cnf`) via `execute-php`; verify no leftovers. The self-destruct timer (§7.3) is the backstop if the session dies before this runs, and the next health check's sweep (§4.6) is the second backstop.

### 7.6 Import and localise (local, destructive)

1. **`pull` only:** back up to `.kntnt-wp-skills/backups/local-pre-import-<timestamp>.sql.gz` (gitignored, durable — nothing to "remember to move"), via `ddev export-db`.
2. Decrypt + gunzip the DB. Sanity-check with the **discovered prefix**: `CREATE TABLE` count, `INSERT INTO \`<prefix>posts\`` present, each empty-classified table has 1 `CREATE` and 0 `INSERT`.
3. `ddev import-db`. Verify table and posts counts.
4. Extract the tarball over `wp-content` — a **merge**: keeps the local `wp-config.php` (it lives in `ABSPATH`), keeps local-only files, overwrites plugin/theme/media files with production's. `clone` extracts onto the mkwp scaffold.
5. **Deletions**, if enabled (§6.3): move the confirmed production-deleted baseline files and confirmed drift plugins/themes to the local trash (never `rm`).
6. **Object-cache drop-in** (`pull`): apply the ownership rule — no local drop-in → nothing; different owner than production → keep local; same owner → fetch production's via `read-file` and write it. Then **verify a request succeeds**: production's `object-cache.php` may point at `127.0.0.1` while DDEV's Redis is the host `redis`, which is fatal on every request. On failure, remove the drop-in as a fallback and report it (the proper long-term answer is DDEV-native Redis, out of scope here).
7. **wp-config defines + prefix**: write the chosen production defines and (at `clone`) production's `$table_prefix` into the marked block; at `pull`, assert the prefix matches and abort on mismatch (§6.5).
8. **Mail**: apply the resolved choice (§6.4) — keep the existing mailer (do nothing) or install the Mailpit mu-plugin to capture. **Cron**: leave running unless `--no-cron` (writes `DISABLE_WP_CRON`).
9. **`pull` only:** re-apply the preserved local inactive set with `--skip-plugins --skip-themes` (so an object-cache plugin cannot re-drop its drop-in during deactivation).
10. **URL-scoped search-replace** — passes for `https://www.`, `http://www.`, `https://`, `http://`, protocol-relative `//www.` and bare `//`, **and the escaped-slash forms** `https:\/\/www.`, `https:\/\/`, `http:\/\/…` (page builders such as Elementor store URLs as escaped JSON, which a plain pass never touches), each `--all-tables --skip-columns=guid --report-changed-only --skip-plugins --skip-themes`. Never the bare domain (it corrupts `user@domain` addresses). Serialized PHP objects that wp-cli safely skips (Freemius caches, etc.) keep the old domain — harmless.
11. Set `home` and `siteurl` explicitly to the DDEV URL.
12. `wp media regenerate` for the affected DB attachments (all at `clone`; the metadata-driven delta at `pull`, §6.1; `--regenerate-all` forces the lot).
13. **`ddev wp rewrite flush --hard` WITH plugins loaded** (not `--skip-plugins`). This is the bug that caused `/en/` 404s: if a multilingual/rewrite plugin is not loaded during the flush, its language routes never get written and those subpages 404 while default-language pages still work.
14. `ddev restart` — clears PHP-FPM APCu / object cache that `wp cache flush` cannot.
15. Write the new `.kntnt-wp-skills/last-sync.json` baseline manifest (with the scope it was taken under).

### 7.7 Verify

Build the smoke-test URL list from **live state**, not assumption: always the front page plus a couple of real published URLs pulled from the DB. Only if discovery found an active multilingual plugin, add the localised home and a **real localised subpage** (the canary for the rewrite bug) — on a monolingual site those asserts never run. Assert HTTP 200 and grep the HTML for "There has been a critical error" / "Fatal error" / "Error establishing a database". Run `ddev wp db check`. Confirm the object-cache state and the expected active-plugin count.

### 7.8 Cleanup

Remove the large scratch artifacts. The `pull` rollback backup already lives durably in `.kntnt-wp-skills/backups/` (§7.6.1), so there is nothing to move — just report its path. Leave production state-neutral: temp dirs already deleted, no dev servers started.

## 8. `clone` specifics

- **Derive the local project name** from the production URL — strip scheme + `www.`, drop the TLD, take the main label, sanitise to mkwp's charset: `https://www.elfsborgsmarschen.se` → `elfsborgsmarschen` → `elfsborgsmarschen.ddev.site`. Presented as a gate; `--yes` accepts. No public-suffix-list dependency; the confirm gate covers oddball domains.
- **Scaffold** via `mkwp <name> --wp=<production's exact core version>` — gives DDEV + core at production's version + the container-cron tweak + a DDEV `wp-config.php`. Core comes fresh from mkwp; core files are never transferred.
- **Pin DDEV to production**, from discovery: set the DDEV `database` type+version to production's (MySQL 8 vs MariaDB — otherwise a MySQL-8 dump's `utf8mb4_0900_ai_ci` collations crash the MariaDB import) and DDEV's `php_version` to production's `major.minor`. Write production's **table prefix** into the local `wp-config.php`.
- **No** pre-import backup, **no** preserve-inactive, **no** object-cache derivation — nothing local pre-exists.
- After import, local users are production's, so the operator logs in with **production credentials** (mkwp's throwaway admin is overwritten). The report says so, and **offers to remove mkwp's default themes/plugins** left sitting beside production's.

## 9. `pull` specifics

- **Pre-import DB backup** (rollback) to `.kntnt-wp-skills/backups/`, always.
- **Verify the local table prefix matches production**; abort on mismatch.
- **Preserve the local inactive plugin set** (derived each run).
- **Object-cache ownership** derivation, then the verify-and-fallback of §7.6.6.
- **Incremental** file transfer against the stored baseline; **deletion** gate (to local trash).

## 10. Safety rails (non-negotiable)

- Verify the MCP targets **production**, not local, before anything (§4).
- **No SSH**, ever ([ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md)).
- **Never** deactivate or delete Novamira on production — it is the control channel.
- **Never** mutate production except the short-lived temp dirs, deleted immediately after the pull. Any production mutation (e.g. uninstalling a plugin before the dump) is explicit, out of band, confirmed, and **never** part of `--yes`.
- **All remote packing happens outside the docroot**; only the finished, **encrypted** `.enc` artifacts + `SHA256` are briefly published into a docroot download dir. The passphrase lives outside the docroot, travels only over Novamira `read-file`, and is never web-served. A self-destruct timer and the next health check's sweep guarantee no stranded PII even if the session dies mid-run ([ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)).
- Encrypt **both** the DB dump and the file tarball in transit; delete the remote copies immediately; `DB_PASSWORD` is never returned into context.
- Take the pre-import backup before the destructive local step (`pull`); the confirm gate (interactive) guards it. Deletions go to a local trash, not `rm` ([ADR-0010](./adr/0010-deletion-mirroring-opt-in-trash.md)).
- URL-scoped search-replace only (including the escaped-slash forms).
- Final rewrite flush with plugins loaded.
- **Mail keeps the site's real mailer active by default** (so the send flow can be tested); a detected imminent mass-send flips the default to Mailpit capture with a loud, specific warning ([ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md)). `--live-mail` / `--capture-mail` force it.
- The **risk warning is always emitted** — it states that the copy will send real email through the site's mailer unless captured, and itemises the other default-on, outward-reaching behaviours: cron may fire real webhooks / capture real payments / publish scheduled posts to connected social accounts / re-validate plugin licences from the dev domain; analytics may re-download a GeoIP DB; the DB holds real PII. Interactive waits for confirmation; `--yes` prints it for the record and proceeds.

## 11. Run modes and flags (minimal surface)

- Default is interactive; `--yes` is autonomous; replay engages automatically when a saved plan exists.
- A small set of **coarse** scope/behaviour flags for unattended deviation from defaults: `--include-media` / `--exclude-media`, `--include-blobs`, `--live-mail` / `--capture-mail` (force the mail choice past the risk-adaptive default), `--no-cron` (disable local WP-cron), `--regenerate-all` (regenerate every thumbnail, not just the delta). No fine-grained regex.
- The cuts from the original hand-off (`--dry-run`, a static `--help` file, regex filters, the blob-threshold engine) are recorded in [ADR-0013](./adr/0013-minimal-flag-surface.md) so they are not re-proposed.

## 12. Help mechanism (the reference model to retrofit the other plugins)

The decision — Markdown manpages under `docs/man/` as the single source of truth, echoed verbatim by `help.py`, two entry points reaching one source — is [ADR-0012](./adr/0012-manpage-help-mechanism.md). Build notes:

- Manpages follow the one-paragraph-per-line rule, `SYNOPSIS` in a fenced block, `OPTIONS` as a table.
- Each `SKILL.md`'s first step is the help-gate: "if the arguments are `help` / `--help` / `-h`, run `help.py <thisskill>`, emit verbatim, and stop" — so `/clone --help` and `/kntnt-wp-skills:help clone` reach the same manpage.
- The README links to `docs/man/*` rather than restating usage (linking, not embedding, keeps a single source).
- **A consistency test** asserts every skill has a manpage, every documented flag is real, and the README links resolve.
- Retrofitting each sibling plugin is: add `docs/man/*.md`, swap in the echo `help.py`, add the help-gate line to each `SKILL.md`, point the README at `docs/man/`.

## 13. Persistent config

Two small per-project files at the project root:

- **`.kntnt-wp-skills.json`** — the settled answers (committed, so the site is reproducible). All keys optional; a missing key falls back to the built-in default. Illustrative shape:

```jsonc
{
  "source": { "mcpServer": "novamira-<site>", "liveUrl": "https://www.example.com" },
  "target": { "ddevProject": "<name>" },
  "db": { "emptyTables": ["wp_independent_analytics%", "wp_rcb_consent%", "wp_fsmpt_email_logs", "wp_relevanssi%"] },
  "scope": { "includeMedia": true, "excludeBlobs": ["uploads/<gallery>", "uploads/*.mmdb"] },
  "wpConfigDefines": ["WP_MEMORY_LIMIT"],
  "plugins": { "preserveLocalInactive": true },
  "objectCache": "derive",
  "mail": "auto",              // auto = risk-adaptive default; "live" / "capture" pin it
  "cron": "leave",
  "deletions": { "mirror": false }
}
```

- **`.kntnt-wp-skills/`** — derived, **gitignored** state: `last-sync.json` (the stored baseline manifest + its scope), `backups/` (the `pull` rollbacks), `trash/` (reversible deletions).

There is deliberately **no** production-mutation key — mutating production is always a separate, explicit instruction.

## 14. Consolidated gotchas

1. `run-wp-cli` with a **string** arg returns `wp help`, exit 0 → pass `args` as an **array**.
2. `exec`/`shell_exec`/`proc_open` may sit in `disable_functions` on managed hosts, killing the `nohup` pack job → **probe the exec capability in the health check** and abort clearly; a working `run-wp-cli` does not prove it.
3. Managed host **404s archive extensions** → name both artifacts `.enc` **from creation** (never rename), which also keeps `sha256sum -c` matching; the download preflight verifies the path before the pack.
4. Heavy `mysqldump`/`tar` in a single `execute-php` risks MCP timeout → **background `nohup` job** + poll `DONE`/`FAILED`, with a `trap`-written `FAILED` marker, `kill -0 $PID` check, and an explicit max wait so a mid-pack death never hangs the poll.
5. `mysqldump` against a **live** site without `--single-transaction --quick --skip-lock-tables` locks tables or yields inconsistent data → use them (InnoDB confirmed in discovery).
6. `DB_HOST` can be `127.0.0.1:3306` → split host/port for `.my.cnf`.
7. `mysqldump: Deprecated program name…` on stderr (MariaDB) is harmless — do not treat as failure.
8. Never return `DB_PASSWORD` to context, and **the encryption passphrase is generated server-side, kept outside the docroot, fetched only via `read-file`, and deleted at end** → it is never web-readable.
9. **All packing runs outside the docroot**; only encrypted `.enc` artifacts + `SHA256` (`0644`) are briefly moved into a docroot download dir → a dropped session cannot strand plaintext PII in a public path; a self-destruct timer + health-check sweep are the backstops.
10. `tar` exclusions as argv/basename patterns blow `ARG_MAX` and mis-match same-named files → write full anchored relative paths to a file, `tar --exclude-from=<file> --anchored --no-wildcards`.
11. `tar` of a live tree prints "file changed as we read it" → `--warning=no-file-changed`.
12. DB engine/collation mismatch (MySQL 8 `utf8mb4_0900_ai_ci` vs MariaDB) crashes the import, and an unpinned PHP diverges from production → pin DDEV's `database` and `php_version` to production's (from discovery).
13. Production's `$table_prefix` ≠ `wp_` → write it into the local `wp-config.php` (`clone`) and verify it (`pull`), or WordPress finds zero tables.
14. Bare-domain search-replace corrupts `@domain` emails, and page-builder JSON stores **escaped** URLs (`https:\/\/…`) a plain pass misses → URL-scoped passes only, including the escaped-slash forms.
15. Rewrite flush with `--skip-plugins` drops multilingual/custom routes → localised subpages 404. The final flush must load plugins.
16. `wp cache flush` cannot clear PHP-FPM APCu → `ddev restart`.
17. A production `object-cache.php` pointing at `127.0.0.1` is fatal against DDEV's `redis` host → after writing it, verify a request succeeds and auto-remove on failure.
18. `wp-cli` under newer PHP emits `Deprecated:` notices on stderr — cosmetic; filter them in output.
19. Import replaces users with production's → log in locally with **production credentials** afterwards; tell the operator.
20. mtime is unreliable through `tar` → mutagen → diff against a **stored production-side baseline**, never the local filesystem; store the scope with it so a scope change never mis-reads a still-present tree as deleted.
21. A running cron can autonomously blast a queued campaign to real subscribers → keep the real mailer by default (for testability), but **scan discovery for a poised mass-send** (a queued campaign against a real list, not mere plugin presence) and flip the default to Mailpit capture with a loud warning when found; itemise the residual non-mail outbound and offer `--no-cron`.
22. `wp media regenerate` is DB-only and a file diff misses newly-registered sizes → regenerate the **metadata-driven** delta on `pull`, with `--regenerate-all` as the escape hatch.

## 15. Dependencies

- **Host:** DDEV, Docker (or equivalent), `mkwp` (for `clone`), the operator's Claude Code with the target site's Novamira MCP connected.
- **Production:** the free (AGPL) Novamira plugin, enabled. Abilities used: `execute-php`, `run-wp-cli` (+ `get-wp-cli-job`), `read-file`, `write-file`, `list-directory`. Required host capability: process spawning (`exec`) not disabled.

## 16. Reconciliation with the security review

A security/robustness review (pasted in during grilling) raised 20 points. All are addressed; most were adopted outright. Where the design **deliberately departs** from the review's recommendation, the row reads **Departed — settled** and carries the reason (recorded as an ADR where architectural), so a later reader (or agent) never mistakes a conscious decision for an oversight and re-opens it.

| # | Review point | Disposition |
|---|---|---|
| 1 | Encryption passphrase lifecycle undefined | Adopted — server-side passphrase, off the web, `read-file` only (§7.3, [ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)) |
| 2 | Tarball unencrypted | Adopted — both artifacts encrypted (§7.3, [ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)) |
| 3 | `sha256sum -c` breaks on the rename trick | Adopted — `.enc` from creation, no rename (§7.4, [ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)) |
| 4 | Perms don't stop the web server; temp in docroot | Adopted — all packing outside the docroot (§7.3, [ADR-0008](./adr/0008-encrypted-artifacts-outside-docroot.md)) |
| 5 | Aborted run strands the dump publicly | Adopted — self-destruct timer + health-check sweep (§4.6, §7.3) |
| 6 | SMTP live + cron → local mass-mail to real people | **Departed — settled** — mail keeps the real mailer by default with a mass-send valve; cron stays running ([ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md)) |
| 7 | Deletion under replay/`--yes` has no net | Adopted — deletions go to a local trash (§6.3, [ADR-0010](./adr/0010-deletion-mirroring-opt-in-trash.md)) |
| 8 | `exec`/`shell_exec` capability not probed | Adopted (probe, §4.4); the run-wp-cli-job **fallback is deferred — settled** (YAGNI until a host actually blocks exec; [ADR-0001](./adr/0001-novamira-mcp-sole-control-channel.md)) |
| 9 | Table prefix not written locally | Adopted (§6.5) |
| 10 | DB engine/collation + PHP not pinned | Adopted (§8, §7.1) |
| 11 | `mysqldump` lacks consistency flags | Adopted — `--single-transaction --quick --skip-lock-tables` (§7.3) |
| 12 | Scope change poisons the deletion diff | Adopted — **chose "store scope in the baseline"** over a full-scope manifest, to avoid walking excluded trees — settled (§7.2, [ADR-0006](./adr/0006-baseline-manifest-diff-with-scope.md)) |
| 13 | Search-replace misses escaped URLs | Adopted — escaped-slash + bare-`//` passes (§7.6.10) |
| 14 | Tar exclusions need anchored paths, not patterns | Adopted — `--exclude-from` + `--anchored --no-wildcards` (§7.3) |
| 15 | `DONE` polling has no failure path | Adopted — `FAILED` marker, `kill -0`, explicit max wait (§7.3, [ADR-0007](./adr/0007-background-pack-job-with-polling.md)) |
| 16 | Download path tested only when failure is costly | Adopted — health-check preflight (§4.5) |
| 17 | Prod object-cache drop-in can be fatal locally | Adopted — verify a request, auto-remove on failure (§7.6.6) |
| 18 | Rollback backup misplaced in the scratchpad | Adopted — written to `.kntnt-wp-skills/backups/` (§7.6.1) |
| 19 | Verification assumes multilingualism | Adopted — monolingual-aware, URLs pulled from the DB (§7.7) |
| 20 | Smalls: mkwp-default cleanup; prefix-aware grep; media-regen metadata gap | Adopted (§8, §7.6.2); media-regen **extended beyond the review** — metadata-driven delta plus `--regenerate-all` (§6.1, [ADR-0011](./adr/0011-metadata-driven-thumbnail-regeneration.md)) |

**On point 6 — the one substantive departure:** the full rationale is recorded in [ADR-0009](./adr/0009-live-mail-default-with-mass-send-valve.md); the operator explicitly chose the running-cron default over the reviewer's — and the author's — more cautious proposal.
