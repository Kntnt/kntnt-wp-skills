# kntnt-wp-skills — design and build plan

Status: pre-implementation plan. This document is the single source of truth for the design agreed during grilling; the build follows it. Language of all user-facing text and documentation is British English (`en_GB`); identifiers, flags, and config keys are English.

## 1. Purpose and scope

`kntnt-wp-skills` is a Claude Code plugin, built to the same conventions as `kntnt-code-skills` and `kntnt-text-skills`, that mirrors a live WordPress site down into a local DDEV copy.

It ships two skills:

- **`clone`** — create a fresh local DDEV copy of a production site in an empty directory.
- **`pull`** — refresh an existing local copy from production.

Both are **user-invoked only** (`disable-model-invocation: true`): they may be started solely by the slash command, never fired autonomously by the model. This is the correct safety posture, because they execute code on production and overwrite the local database.

Scope is deliberately narrow: single-site WordPress, personal use, driven by hand. There is exactly one control channel (the Novamira MCP) and no SSH.

## 2. Preconditions (documented in the README)

The skills assume the operator has already solved these; the README explains each for someone starting from zero.

- **DDEV up and running**, which in turn needs Docker (or an equivalent such as OrbStack) plus DDEV's own dependencies (mkcert, mutagen). These are DDEV concerns, not this plugin's.
- **The free Novamira plugin installed and enabled on the production site**, with its MCP server connected in Claude Code. This is the sole control channel (see §4). The free AGPL build is sufficient — it exposes `execute-php`, `run-wp-cli` (with native background jobs), and file read/write/list. Novamira Pro is not required.
- **`mkwp` available on the operator's `PATH`** — used by `clone` to scaffold the local site.

## 3. Architecture

Two user-invoked skills sit over **one shared transfer engine**. The engine does discovery, packaging on production, the pull, verification, remote cleanup, import, and localisation. `clone` and `pull` differ only at the bookends.

- **`clone` = `pull` against an empty baseline.** Because the file transfer is a manifest diff against a stored baseline (§7.2), a first-time clone simply has no baseline, so everything is "new" and a full transfer falls straight out of the incremental path. There is one transfer engine, not two.
- **Decoupled from `mkwp`.** The skills ride `mkwp` exactly as it is today (scaffold only); import and localisation live in the skill engine, because `pull` needs them against an already-existing site and `mkwp` is a create-a-new-project tool. `mkwp`'s optional template-seeder capability is a separate, non-blocking track — filed as [Kntnt/mkwp#1](https://github.com/Kntnt/mkwp/issues/1). It is justified on its own merits and is **not** a dependency of these skills.

Plugin layout mirrors the sibling plugins:

- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- `skills/clone/SKILL.md`, `skills/pull/SKILL.md`
- `commands/help.md`
- `scripts/` — the shared engine helpers, `help.py`, the pack script template
- `docs/man/clone.md`, `docs/man/pull.md` — the manpages (§12)
- `AGENTS.md`, `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE`

## 4. Control channel

The Novamira MCP is the **sole** channel to production. There is no SSH, ever, and WordPress core's own Abilities/MCP stack cannot substitute (it exposes only curated, registered abilities — no arbitrary execution). The rationale for Novamira over SSH: not everyone has SSH access, and "enable an admin-gated plugin" is a far smaller ask than "give an AI SSH".

**Mandatory step 0 — health check, on every run of both skills:**

1. Locate the connected `novamira-*` MCP server whose `home_url()` matches the target production URL; if several or none match, ask.
2. Call a trivial `execute-php` returning `home_url()`, `ABSPATH`, `phpversion()`, `SERVER_SOFTWARE` — this proves the channel is *live*, not merely connected (ability discovery can 404 even when the server is connected).
3. Confirm it targets **production**, not the local DDEV site (the verify-targets-prod safety rail).
4. On any failure — server missing, abilities route 404, plugin disabled — abort with a precise remediation message (e.g. "enable Novamira and its MCP feature on production").

`run-wp-cli` always takes `args` as a JSON **array** (`["plugin","list"]`); a single string silently returns `wp help` with exit 0.

## 5. The decision backbone

Every decision the skill makes is presented as a **recommendation with an accept/override gate** — *"Recommended: exclude the 3.1 GB gallery. Accept? [Y/n]"*. This single shape drives all run modes; even multi-valued decisions (e.g. object-cache: keep / take-prod / none) are expressed as a yes/no gate on their recommendation, where `n` reveals the alternatives.

**Three speeds over one ordered decision list:**

- **Interactive** (default) — walk each gate; `Y` accepts the recommendation, `n` reveals the alternatives and you choose.
- **`--yes`** (autonomous) — accept every recommendation, never pause, and print a full record of what was decided and done, to read on return.
- **Replay** — when a saved plan exists for the site, the recommendations *are* the remembered answers, so interactive collapses to a single *"Replay the saved plan? [Y/n]"* gate, and `--yes` runs it silently. This is the "quick and dirty" repeat refresh.

**Layered defaults (no precedence ceremony):**

```
built-in default  <  live derivation  <  saved config  <  this run's answer
```

- **built-in** — the skill's baked-in stance.
- **live derivation** — computed fresh each run: production discovery (sizes, heavy dirs, core version) and, for `pull`, local state (which plugins are inactive, who owns `object-cache.php`).
- **saved config** — the operator's remembered answers from last time.
- **this run's answer** — interactive only; `--yes` stops at the saved-config layer.

The saved config stores **decisions, not computed lists** — the inactive-plugin set and blob list re-derive from live state each run, so nothing goes stale. It is written whenever a plan is accepted and exists mainly to make replay a one-liner. See §13.

## 6. The decisions and their recommended defaults

| Decision | Recommended default | Notes |
|---|---|---|
| DB — table structure | **All tables, always**, with production's exact schema | No table is ever omitted; nothing hits a missing table |
| DB — table content | Full data for content/config/users/CRM/forms; **empty** for operational tables (analytics / cookie-consent / email-log / search-index) | Binary per table: full or empty. "Full dump" = empty-set is none |
| Media Library originals | **Included** | `clone`: full; `pull`: delta only (§7.2) |
| Generated thumbnails | **Excluded**, regenerated locally | Only the DB-known sizes (`_wp_attachment_metadata → sizes[*].file`); see §6.1 |
| Side-loaded / orphan files | **Pulled whole** | Cannot be regenerated (`wp media regenerate` is DB-only), so we carry them |
| Heavy blobs (gallery dir, `.mmdb`, backups, dumps) | **Excluded**, behind a prompt | Deterministic heuristic flags outliers; the AI writes the recommendation, does not decide freely |
| `wp-config.php` defines | Copy the plugin/behaviour defines; **auto-exclude** the infra/secret class | See §6.2 |
| Plugins to deactivate (`pull`) | **Preserve the local inactive set** | Derived from live local state each run |
| Object-cache drop-in (`pull`) | **Derive from local-vs-prod ownership** | keep-local / take-prod / none |
| Transactional email / SMTP | **Keep active on the real SMTP** | So the copy actually works; the risk warning covers it |
| Cron | **Leave running** | mkwp's container cron on the local side |
| Deletion mirroring | **No** | Scoped and itemised when enabled; see §6.3 |

### 6.1 Thumbnails and regeneration

We can only safely exclude a thumbnail if something will rebuild it, and only `wp media regenerate` can — and it operates strictly on **DB-registered attachments** (verified: it cannot process images with no attachment record). Therefore:

- **Exclude** exactly the DB-known generated sizes. This set also resolves the `banner-1920x1080.jpg` case unambiguously (the original is `_wp_attached_file`, kept; its derivatives are in `sizes[*].file`, dropped), so no filename heuristic is needed.
- **Pull whole** everything not in that set — registered originals and rare side-loaded/orphan files (including their thumbnails, which we cannot regenerate).
- **Regenerate** the affected DB attachments after import: all of them at `clone`, only the new/changed ones at `pull`. Because default `wp media regenerate` deletes-then-rebuilds, a changed original's stale thumbnails are wiped and rebuilt when we regenerate its ID.

### 6.2 wp-config.php defines

Discovery extracts production's `define()`s. A class is **auto-excluded** because copying it would break or mis-key the local site:

- DB credentials (`DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_CHARSET`, `DB_COLLATE`)
- auth keys and salts (`AUTH_KEY`, `*_SALT`, `NONCE_*`, …) — never copy production secrets down
- domain and paths (`WP_HOME`, `WP_SITEURL`, `WP_CONTENT_DIR`, `WP_CONTENT_URL`, `ABSPATH`)
- infrastructure (`WP_CACHE`, redis/memcached hosts, `DISABLE_WP_CRON`)

The **remaining** defines — the plugin/behaviour constants a plugin might expect (`WP_MEMORY_LIMIT`, feature flags, custom `define()`s) — are offered as a gate, default **copy [Y]**, deselect on `n`. Chosen defines are written into a clearly **marked block** in the local `wp-config.php`, separate from mkwp's DDEV block, and the chosen set is remembered. Because `pull` never overwrites `wp-config.php`, ported defines persist; if production later grows a new such define, the `pull` report surfaces it.

### 6.3 Deletion mirroring

A blanket "make local identical to production" would delete things we deliberately keep — the locally regenerated thumbnails, deliberately excluded blobs, and wanted local-only dev tools. So deletion, when enabled, draws only from two safe sources, each itemised:

- **Production-deleted files** — present in the stored baseline but gone from production now (`baseline − prod_now`). These provably *were* production's and were removed there. Anything never in a production manifest (thumbnails, dev artefacts) is automatically immune.
- **Plugin/theme drift** — local plugins/themes with no production counterpart, presented as a checklist so junk is removed and dev tools are kept.

Default is **No** (deletion is irreversible and, unlike the DB, no `wp-content` backup is taken; and under `--yes` there must be no surprise removals). It is a remembered per-site answer, so "make it identical" is achieved by setting it Yes once for that site.

## 7. The transfer engine, phase by phase

Everything on production goes through Novamira `execute-php` / `run-wp-cli`.

### 7.0 Health check

As §4.

### 7.1 Discovery (production, read-only)

One `execute-php` call gathers: `home_url()`, `site_url()`, `ABSPATH`, `WP_CONTENT_DIR`, uploads basedir; DB total size and top tables by size; a per-top-level-subdir size breakdown of `uploads/` (to see the heavy dirs); `SERVER_SOFTWARE`; `disk_free_space`; `is_writable(ABSPATH)`; the table prefix; `get_option('active_plugins')`; drop-ins present; theme list; core version (for mkwp pinning); the DB constants (`DB_HOST` may be `host:port`) — but **never** return `DB_PASSWORD` into context. It also probes binaries (`mysqldump mysql openssl tar gzip sha256sum nohup bash`), runs the blob scan, and computes the generated-thumbnail exclude-list from `_wp_attachment_metadata`.

### 7.2 Baseline diff (files)

Production emits a manifest of the in-scope tree (path + size + mtime). The diff is **production-now against the stored last-sync baseline** (`.kntnt-wp-skills/last-sync.json`) — both sides are production mtimes, so whatever mutagen does to local timestamps is irrelevant. `clone` has no baseline, so everything is new. The diff yields the new/changed set (to pull) and the production-deleted set (for the deletion gate). Detection is size + mtime, mirroring rsync's default quick-check; a checksum mode can be added later. The DB is always dumped in full (it is ~2 MB trimmed — not worth diffing).

### 7.3 Pack on production (background job)

Via `execute-php`: make a random-named dir in the docroot (`0755`), write a `.my.cnf` (`0600`) from the DB constants, write `pack.sh`, launch it with `nohup bash pack.sh >> pack.log 2>&1 & echo $!`, then **poll** for a `DONE` marker (avoids MCP timeouts on the heavy steps).

`pack.sh`:

- **DB, two passes** — full `mysqldump` for every table except the empty-classified ones, then `--no-data` for the empty-classified ones (so all tables exist, some with zero rows). `gzip`, then `openssl enc -aes-256-cbc -pbkdf2 -salt` (the dump holds users/CRM/form PII and briefly sits in a public docroot).
- **Files** — `tar` the resolved in-scope subset (for `pull`, only the new/changed set), excluding the DB-known thumbnail sizes, the excluded blobs, `object-cache.php`, `wp-config.php`, logs, caches, `upgrade*`, `novamira-sandbox`. Use `--warning=no-file-changed`.
- `sha256sum` the artifacts; output files `0644`; remove `.my.cnf`; `touch DONE`.

### 7.4 Download and verify (local)

`curl -fSL` the `SHA256` file and the artifacts into the scratchpad; `sha256sum -c`.

**Archive-extension 404 gotcha:** the managed nginx host returns 404 for direct download of `.tar.gz`/`.zip`/`.sql` but serves `.enc` and extension-less files. The DB already ships as `.enc`; **rename the tarball to `.enc`** on the server before fetching (content unchanged, so the sha still matches). Detect the block by fetching the extension-less `SHA256` plus the tarball; if the tarball 404s while `SHA256` succeeds, rename-to-`.enc` and retry.

### 7.5 Close the exposure window (production)

Immediately after checksums pass, recursively delete the whole temp dir via `execute-php`; verify no leftovers and that `.my.cnf` is gone.

### 7.6 Import and localise (local, destructive)

1. **`pull` only:** `ddev export-db --file=<scratch>/local-pre-import.sql.gz` (rollback).
2. Decrypt + gunzip the DB. Sanity-check: `CREATE TABLE` count, `INSERT INTO wp_posts` present, each empty-classified table has 1 `CREATE` and 0 `INSERT`.
3. `ddev import-db`. Verify table and posts counts.
4. Extract the tarball over `wp-content` — a **merge**: keeps the local `wp-config.php` (it lives in `ABSPATH`), keeps local-only files, overwrites plugin/theme/media files with production's. `clone` extracts onto the mkwp scaffold.
5. **Deletions**, if enabled (§6.3): remove the confirmed production-deleted baseline files and the confirmed drift plugins/themes.
6. **Object-cache drop-in** (`pull`): apply the ownership rule — no local drop-in → nothing; different owner than production → keep local; same owner → fetch production's via `read-file` and write it.
7. **wp-config defines**: write the chosen production defines into the marked block.
8. **`pull` only:** re-apply the preserved local inactive set with `--skip-plugins --skip-themes` (so an object-cache plugin cannot re-drop its drop-in during deactivation).
9. **URL-scoped search-replace** — passes for `https://www.`, `http://www.`, `https://`, `http://`, and protocol-relative `//www.`, each `--all-tables --skip-columns=guid --report-changed-only --skip-plugins --skip-themes`. Never the bare domain (it corrupts `user@domain` addresses). Serialized PHP objects that wp-cli safely skips (Freemius caches, etc.) keep the old domain — harmless.
10. Set `home` and `siteurl` explicitly to the DDEV URL.
11. `wp media regenerate` for the affected DB attachments (all at `clone`; new/changed at `pull`).
12. **`ddev wp rewrite flush --hard` WITH plugins loaded** (not `--skip-plugins`). This is the bug that caused `/en/` 404s: if a multilingual/rewrite plugin is not loaded during the flush, its language routes never get written and those subpages 404 while default-language pages still work.
13. `ddev restart` — clears PHP-FPM APCu / object cache that `wp cache flush` cannot.
14. Write the new `.kntnt-wp-skills/last-sync.json` baseline manifest.

### 7.7 Verify

Smoke-test both languages: default-language home + a subpage, the localised home + a **localised subpage** (the thing the rewrite bug breaks), and a couple more. Assert HTTP 200 and grep the HTML for "There has been a critical error" / "Fatal error" / "Error establishing a database". Run `ddev wp db check`. Confirm the object-cache state and the expected active-plugin count.

### 7.8 Cleanup

Remove the large scratch artifacts; **keep** the `pull` DB rollback backup and tell the operator its path (the scratchpad is session-ephemeral, so move it to keep it durable). Leave production state-neutral: temp dir already deleted, no dev servers started.

## 8. `clone` specifics

- **Derive the local project name** from the production URL — strip scheme + `www.`, drop the TLD, take the main label, sanitise to mkwp's charset: `https://www.elfsborgsmarschen.se` → `elfsborgsmarschen` → `elfsborgsmarschen.ddev.site`. Presented as a gate; `--yes` accepts. No public-suffix-list dependency; the confirm gate covers oddball domains.
- **Scaffold** via `mkwp <name> --wp=<production's exact core version>` — gives DDEV + core at production's version + the container-cron tweak + a DDEV `wp-config.php`. Core comes fresh from mkwp; core files are never transferred.
- **No** pre-import backup, **no** preserve-inactive, **no** object-cache derivation — nothing local pre-exists.
- After import, local users are production's, so the operator logs in with **production credentials** (mkwp's throwaway admin is overwritten). The report says so.

## 9. `pull` specifics

- **Pre-import DB backup** (rollback), always.
- **Preserve the local inactive plugin set** (derived each run).
- **Object-cache ownership** derivation.
- **Incremental** file transfer against the stored baseline; **deletion** gate.

## 10. Safety rails (non-negotiable)

- Verify the MCP targets **production**, not local, before anything (§4).
- **No SSH**, ever.
- **Never** deactivate or delete Novamira on production — it is the control channel.
- **Never** mutate production except the short-lived temp dir, deleted immediately after the pull. Any production mutation (e.g. uninstalling a plugin before the dump) is explicit, out of band, confirmed, and **never** part of `--yes`.
- Encrypt PII in transit and delete the remote copy immediately; `DB_PASSWORD` is never returned into context.
- Take the pre-import backup before the destructive local step (`pull`); the confirm gate (interactive) guards it.
- URL-scoped search-replace only.
- Final rewrite flush with plugins loaded.
- The **risk warning is always emitted** — it lists each default-on, outward-reaching behaviour (real SMTP can send mail; cron runs real jobs; analytics may re-download a GeoIP DB; the DB holds real PII). Interactive waits for confirmation; `--yes` prints it for the record and proceeds.

## 11. Run modes and flags (minimal surface)

- Default is interactive; `--yes` is autonomous; replay engages automatically when a saved plan exists.
- A small set of **coarse** scope flags for unattended deviation from defaults (e.g. `--include-media` / `--exclude-media`, `--include-blobs`). No fine-grained regex.
- **Cut** from the original hand-off, as gold-plating for a personal, slash-command-only tool: `--dry-run` (interactive walk-and-decline is the same), a static shipped `--help` usage file (replaced by the manpage mechanism), `--include`/`--exclude` regex filters, and the formal blob-threshold engine (replaced by the discovery report).

## 12. Help mechanism (the reference model to retrofit the other plugins)

The existing `help.py` in the sibling plugins shows only a skill's intro paragraph for `help <skill>`, because there is no per-skill source with flags — a missing-source bug, not a formatting one. The fix:

- **Source of truth:** `docs/man/<skill>.md`, a full manpage in **Markdown** (`NAME`, `SYNOPSIS`, `DESCRIPTION`, `OPTIONS`, `EXAMPLES`, `FILES`), authored under the one-paragraph-per-line rule. `SYNOPSIS` in a fenced block and `OPTIONS` as a table, so the monospace-sensitive parts survive rendering. Markdown is required because the README references these pages and GitHub renders them.
- **The tool echoes, it does not render.** Because Claude Code renders GitHub-flavoured Markdown in the terminal too, `help.py` needs no wrapping/alignment: no arg → overview (`plugin.json` blurb + each manpage's `NAME` line); `<skill>` → echo `docs/man/<skill>.md` verbatim; unknown → the error line.
- **Two entry points, one source:** the plugin command `/kntnt-wp-skills:help [skill]` and a per-skill **help-gate** — each `SKILL.md`'s first step: "if the arguments are `help` / `--help` / `-h`, run `help.py <thisskill>`, emit verbatim, and stop." So `/clone --help` and `/kntnt-wp-skills:help clone` reach the same manpage.
- **README links to `docs/man/*`** rather than restating usage (linking, not embedding, keeps a single source).
- **A consistency test** asserts every skill has a manpage, every documented flag is real, and the README links resolve.

Because the script reads only `plugin.json` + `docs/man/*`, it drops into `kntnt-code-skills` and `kntnt-text-skills` unchanged; retrofitting each is: add `docs/man/*.md`, swap in the echo `help.py`, add the help-gate line to each `SKILL.md`, point the README at `docs/man/`.

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
  "email": "keep",
  "cron": "leave",
  "deletions": { "mirror": false }
}
```

- **`.kntnt-wp-skills/last-sync.json`** — the stored baseline manifest for the incremental diff (path → size + mtime). Derived state, **gitignored**.

There is deliberately **no** production-mutation key — mutating production is always a separate, explicit instruction.

## 14. Consolidated gotchas

1. `run-wp-cli` with a **string** arg returns `wp help`, exit 0 → pass `args` as an **array**.
2. Managed host **404s archive extensions** → encrypt the DB to `.enc`, rename the tarball to `.enc`, fetch those.
3. Heavy `mysqldump`/`tar` in a single `execute-php` risks MCP timeout → **background `nohup` job** + poll a `DONE` marker.
4. `DB_HOST` can be `127.0.0.1:3306` → split host/port for `.my.cnf`.
5. `mysqldump: Deprecated program name…` on stderr (MariaDB) is harmless — do not treat as failure.
6. Never return `DB_PASSWORD` to context → write `.my.cnf` server-side, `0600`, delete at end.
7. Temp dir `0755`, output files `0644`, so the web server can serve the artifacts.
8. Trimmed dump still holds PII → encrypt in transit + delete remote immediately; the copy stays local.
9. `tar` of a live tree prints "file changed as we read it" → `--warning=no-file-changed`.
10. `grep`-ing the tarball for a name like the gallery matches **both** `plugins/…` (keep) and `uploads/…` (exclude) → check the full path; the tarball size is the sanity check.
11. Bare-domain search-replace corrupts `@domain` emails → URL-scoped passes only.
12. Rewrite flush with `--skip-plugins` drops multilingual/custom routes → localised subpages 404. The final flush must load plugins.
13. `wp cache flush` cannot clear PHP-FPM APCu → `ddev restart`.
14. `wp-cli` under newer PHP emits `Deprecated:` notices on stderr — cosmetic; filter them in output.
15. Import replaces users with production's → log in locally with **production credentials** afterwards; tell the operator.
16. mtime is unreliable through `tar` → mutagen → diff against a **stored production-side baseline**, never the local filesystem.

## 15. Dependencies

- **Host:** DDEV, Docker (or equivalent), `mkwp` (for `clone`), the operator's Claude Code with the target site's Novamira MCP connected.
- **Production:** the free (AGPL) Novamira plugin, enabled. Abilities used: `execute-php`, `run-wp-cli` (+ `get-wp-cli-job`), `read-file`, `write-file`, `list-directory`.
