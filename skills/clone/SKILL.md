---
name: clone
disable-model-invocation: true
description: >
  Create a fresh local DDEV copy of a production WordPress site in an empty
  directory. Trigger only on the explicit invocations `/clone`,
  `/kntnt-wp-skills:clone`, or an unmistakable request to clone a production
  WordPress site into a new local copy (in any language — the examples here are
  English only). Because it executes code on production and writes a new local
  site, it is user-invoked only and never auto-triggers; when in doubt, ask
  first.
---

# clone

Create a fresh local DDEV copy of a production WordPress site in an empty directory. `clone` and its sibling `pull` run **one shared transfer engine** — discovery, packing on production, download, verification, remote cleanup, import, and localisation — and differ only at the bookends. A clone is a pull with no baseline: everything is new, so the incremental path is the only path. Every run begins with a **health check** that fails early and cheaply, then walks the operator through a series of **gates** whose recommendations come from the deterministic helpers; `--yes` runs the whole thing unattended and prints a full record. A **risk warning** is always emitted before the destructive local steps.

Read `docs/spec.md` (the specification), `CONTEXT.md` (the glossary — its terms are used verbatim below), and `docs/implementation-notes.md` (the invocation-level literals) alongside this file. Where a literal here and the spec diverge, the spec wins.

## 0. Help gate

If the arguments are `help`, `--help`, or `-h`, run `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/help.py" clone`, emit its output verbatim as Markdown, and stop. Do nothing else — no control-channel call, no file operation.

## How the engine works

**Control channel.** Production is reached **solely** through the Novamira MCP server connected to the live site — never SSH ([ADR-0001](../../docs/adr/0001-novamira-mcp-sole-control-channel.md)). The abilities used are `execute-php`, `run-wp-cli`, `read-file`, `write-file`, and `list-directory`. `run-wp-cli` always takes its arguments as a **JSON array** — a single string silently returns the WP-CLI help text with exit 0. Never deactivate or delete Novamira on production; it is the control channel.

**The deterministic helper seam.** Every computation that needs neither production nor DDEV is done by a helper script under `${CLAUDE_PLUGIN_ROOT}/scripts/`, invoked with `uv run` and fed JSON on stdin. **Never compute a diff, a classification, a resolved plan, a pack script, or a dump verdict by hand** — the model orchestrates gates and control-channel calls, the helpers decide the shapes ([ADR-0005](../../docs/adr/0005-decision-backbone-gates-and-layered-defaults.md)). The seam is:

- `scripts/discovery.py` — parses the raw health-check and discovery output into the one canonical discovery document.
- `scripts/classify.py` — turns that document into the table split, the define classes, the flagged blobs, the thumbnail exclude-set, and the derived project name.
- `scripts/resolve_plan.py` — resolves the ordered decision list over the layered defaults (`resolve`), and reduces an accepted plan back to the saved plan (`save`).
- `scripts/pack_script.py` — generates the production-side `pack.sh` from resolved inputs.
- `scripts/dump_sanity.py` — verdicts the decrypted dump against the discovered prefix before the import.

The production-side probes and scans are PHP payloads under `${CLAUDE_PLUGIN_ROOT}/templates/`, sent over `execute-php`; their raw JSON is piped straight into the helpers.

**Run modes.** Interactive walks each gate. `--yes` accepts every recommendation, never pauses, and prints the full decided-and-done record. **Replay** engages automatically when a saved plan exists: interactive collapses to a single *Replay the saved plan?* gate, `--yes` replays silently — except the mass-send valve, which re-surfaces the mail gate even on a silent replay when a freshly-poised campaign would otherwise be masked ([ADR-0009](../../docs/adr/0009-live-mail-default-with-mass-send-valve.md)).

**The gate shape.** Every decision is a **recommendation** behind an accept-or-override gate — *"Recommended: X. Accept? [Y/n]"*. `Y` accepts; `n` reveals the alternatives. Even multi-valued decisions take this shape. The recommendation is whatever `scripts/resolve_plan.py` resolved for that decision; a declined gate records the operator's answer, which the resolver layers above the recommendation.

**Persistent config.** Two per-project files at the local project root: the saved plan `.kntnt-wp-skills.json` (settled per-site answers, committed, all keys optional) and the derived, gitignored `.kntnt-wp-skills/` (baseline manifest, rollback backups, trash). The saved plan stores **decisions, never computed lists**, so nothing in it goes stale.

## 1. Health check

Mandatory step 0 of the engine, before any heavy work. On any failure, abort with a precise remediation message — never a stack trace.

1. **Locate the server.** Find the connected Novamira server whose reported home URL matches the target production URL. If several or none match, ask the operator which to use; never guess.
2. **Prove the channel is live.** Send `templates/liveness.php` over `execute-php`; it returns the home URL, `ABSPATH`, the PHP version, and the server software. A connected-but-dead channel fails here.
3. **Verify it targets production.** Confirm the returned home URL and root path are production's, **not** the local DDEV site — the verify-targets-prod safety rail. If the channel targets the local site, abort: the production-side steps must never run against the wrong site.
4. **Probe process spawning.** Send `templates/exec-probe.php`: `function_exists('exec')`, the `disable_functions` list, and a live `exec('printf ok')` round-trip. A working `run-wp-cli` does **not** prove this (Novamira may run WP-CLI in-process). If spawning is blocked, abort with the precise cause — the detached pack job would die silently otherwise.
5. **Preflight the download path.** Send `templates/download-preflight.php`: it writes a tiny **extension-less** test file into a throwaway docroot directory; fetch it over HTTPS from the local side with `curl -fsS`, then delete it. This exercises permissions, extension rules, basic auth, and WAF/CDN behaviour before the multi-gigabyte pack — managed hosts commonly 404 archive extensions.
6. **Sweep stranded workspaces.** Send `templates/stranded-sweep.php` to list and remove leftover `kntnt-wp-skills-*` working and download directories from an aborted earlier run (belt-and-braces with the self-destruct timer).

## 2. Discovery

One read-only production scan. Send `templates/discovery.php` over `execute-php`; it echoes a single JSON object — sizes and versions, the table prefix, the database flavour and collation, InnoDB status, active plugins and any multilingual plugin, the drop-ins and themes, the core version, the mass-send risk scan, the raw attachment metadata, the wp-config defines, and the required-binary probe. The **database password is never returned** — the connection is rebuilt from an allowlist of non-secret constants, so the one secret that unlocks everything never enters model context.

Combine the discovery output with the liveness and exec-probe outputs into one JSON envelope and pipe it to `uv run scripts/discovery.py`; it validates the input and writes the **canonical discovery document** (redacting any secret define value at the boundary). Pipe that document to `uv run scripts/classify.py` to get the classifications: the full-data / empty table split, the portable vs auto-excluded defines, the flagged heavy blobs, the thumbnail exclude-set, and the derived project name. If either helper exits non-zero, stop and report its stderr diagnostic — a malformed scan never rides into the run.

## 3. Resolve the plan and walk the gates

Assemble the resolve envelope — `{ "operation": "resolve", "skill": "clone", "flags": [...], "discovery": <document>, "classifications": <classifications>, "saved_plan": <.kntnt-wp-skills.json or null>, "answers": {} }` — and run `uv run scripts/resolve_plan.py`. It returns the run mode, whether this is a replay, the ordered **gate** list, and for every decision its **recommendation**, resolved value, and source layer (built-in < live derivation < saved config < this-run answer, with a flag pinning above all four; `--yes` stops at the saved-config layer).

Walk the returned gates in order. For each, present the recommendation and accept on `Y`; on `n`, reveal the alternatives and record the operator's answer, then re-run `scripts/resolve_plan.py` with that answer in `answers` so the resolved value and every dependent recommendation stay consistent. In `--yes` mode present nothing — every recommendation is accepted — and accumulate the record. When a saved plan exists, present only the single *Replay the saved plan?* gate (plus the mail gate if the valve re-surfaced it).

The mail decision leads with its `findings`: when the mass-send valve flipped, the gate opens with the loud, specific warning naming the engine, the campaign, and the recipient count. Once the walk is done, persist the accepted plan by running `scripts/resolve_plan.py` with `{ "operation": "save", "resolved": <resolved plan>, "saved_plan": <.kntnt-wp-skills.json or null> }` and writing the result to `.kntnt-wp-skills.json` — decisions only, never the computed lists. Pass the prior saved plan back so a re-save carries forward any key this skill does not walk rather than dropping it (the symmetric guarantee that keeps a pull's later re-save from stripping the DDEV `target` recorded here).

## 4. Clone bookends — name, scaffold, pin

The clone-only setup, using the resolved plan. It runs before the pack because the import needs a live DDEV site to import into.

- **Name-derivation gate.** The `project_name` decision carries the name `scripts/classify.py` derived from the production URL (scheme and `www.` stripped, main label sanitised to the scaffolder's charset) and its DDEV URL. Present it as the confirm gate; `--yes` accepts. The gate covers oddball domains without a public-suffix-list dependency.
- **Scaffold at production's exact core version.** Run `mkwp <name> --wp=<core_version>` with the core version from discovery; core files are never transferred.
- **Pin the engine.** Pin DDEV's database engine and version and PHP `major.minor` to discovery's `db_engine_php` values, so the import does not crash on MySQL-8-vs-MariaDB collations and the copy behaves like production. Production's table prefix is written into the marked block during localisation (below).

There is no pre-import backup, no preserved inactive set, and no object-cache derivation at clone — nothing local pre-exists.

## 5. Pack on production (background job)

Generate the production-side pack script — **never assemble this shell by hand**. Build the resolved inputs (working dir, download dir, database name, source root, the archive path set, the anchored exclude paths from the classifications, the content-table and empty-table lists, the InnoDB consistency flag) and pipe them to `uv run scripts/pack_script.py`; it emits `pack.sh`.

All packing happens in a working dir **outside the docroot** — `sys_get_temp_dir()`, else a writable dir above `ABSPATH`, else (last resort) a docroot dir mitigated by immediate cleanup ([ADR-0008](../../docs/adr/0008-encrypted-artifacts-outside-docroot.md)). Over the control channel, write into that working dir: the passphrase file `pass.key` (`random_bytes(32)` as hex, mode `0600`), the `.my.cnf` (mode `0600`, built from the DB constants so the **database password never appears on a command line** — consumed via `--defaults-extra-file`), and the generated `pack.sh`. The **passphrase** is passed to OpenSSL by file reference, never as an argument, and is fetched later only over the authenticated `read-file` channel — never web-served over HTTP.

Launch the detached job: `nohup bash pack.sh >> pack.log 2>&1 & echo $!`. The script dumps the database in two live-safe passes (`--single-transaction --quick --skip-lock-tables`; full data for the content tables, `--no-data` for the empty-classified ones — a non-InnoDB content table drops `--single-transaction` with a logged caveat), gzips and encrypts to `db.enc`, archives the in-scope tree through an anchored exclude file (`--anchored --no-wildcards`) straight into `files.enc`, checksums both final names into `SHA256`, publishes the three artifacts world-readable into the docroot download dir, and `touch`es `DONE`. It runs under `set -euo pipefail` with a trap that on failure publishes a `FAILED` marker plus the log tail, and arms a detached self-destruct that removes both directories after a delay even if the client never returns.

**Poll** for the echoed PID: check for `DONE`, `FAILED`, and process liveness (`kill -0 $PID`) up to an explicit maximum wait. On `FAILED`, surface the log tail and abort. A dead process or an exhausted wait aborts with the tail rather than hanging.

## 6. Download, verify, decrypt

Fetch `SHA256` first, then `db.enc` and `files.enc`, each with `curl -fSL -C - --retry 3` into the local scratch area. Verify with `sha256sum -c SHA256` — the artifact names match their creation-time names exactly, never renamed, so the **checksum** verification is honest. A truncated or corrupted transfer is caught here, before anything touches the local site. Then fetch `pass.key` over the authenticated `read-file` ability (never over HTTP), decrypt both artifacts with `openssl enc -d -aes-256-cbc -pbkdf2 -pass file:<local pass.key>`, and `gunzip` the database dump.

## 7. Close the exposure window

Immediately after the checksums pass, delete **both** remote directories over the control channel — the docroot download dir and the outside-docroot working dir, including `pass.key` and `.my.cnf` — and verify they are gone. The self-destruct timer and the next health check's sweep are the backstops; this explicit deletion keeps the exposure window to minutes even so.

## 8. Risk warning (always emitted)

Before the destructive local steps, always emit the risk warning itemising the copy's outward-reaching behaviours: the resolved mail mode (a live mailer can send real mail), a running cron (can fire real webhooks, capture real payments, post to connected social accounts, re-validate a licence from the dev domain), and the real user data now in the database. Interactive waits for the operator's confirmation to proceed; `--yes` prints it for the record and proceeds.

## 9. Import and localise

Local and destructive. Run in this exact order — the order is a safety rail ([spec](../../docs/spec.md) *Import and localise*):

1. **Sanity-check the dump.** Run `uv run scripts/dump_sanity.py` with the discovered prefix and the empty-classified tables against the decrypted dump: the content table created under the prefix, its inserts present, every empty-classified table created but empty. Abort on any failure — a wrong-prefix dump leaves WordPress finding nothing.
2. **Import.** `ddev import-db` the decrypted dump; verify table and post counts afterwards.
3. **Extract the files.** Extract `files.enc`'s decrypted archive over the content directory as a **merge**: the local `wp-config.php` and local-only files survive; production's plugin, theme, and media files overwrite.
4. **Write the marked block.** Write the chosen portable defines and production's table prefix into the marked block the skills own in `wp-config.php`, separate from mkwp's DDEV block.
5. **Apply mail and cron.** For the resolved mail mode, either keep the existing mailer or install the capture mu-plugin `templates/kntnt-wp-skills-mailpit.php` into `wp-content/mu-plugins` (it short-circuits `wp_mail` at top priority to DDEV's Mailpit, catching API mailers that never touch sendmail). For cron, `--no-cron` writes `define('DISABLE_WP_CRON', true);` into the marked block; otherwise leave it running.
6. **URL-scoped search-replace.** One pass per source URL form, each `ddev wp search-replace '<old>' '<new>' --all-tables --skip-columns=guid --report-changed-only --skip-plugins --skip-themes`. The forms, in order: `https://www.<domain>`, `http://www.<domain>`, `https://<domain>`, `http://<domain>`, the protocol-relative `//www.<domain>` and `//<domain>`, and the **escaped-slash** forms `https:\/\/www.<domain>`, `https:\/\/<domain>`, `http:\/\/www.<domain>`, `http:\/\/<domain>` that page builders store inside JSON. **Never the bare domain** — it corrupts `user@domain` email addresses. Serialised objects wp-cli safely skips keep the old domain; harmless.
7. **Set the URLs.** Set the `home` and `siteurl` options explicitly to the DDEV URL.
8. **Regenerate thumbnails.** `ddev wp media regenerate` for every attachment at clone (`--regenerate-all` is the same at clone); the DB-known sizes were excluded from transfer and are rebuilt here.
9. **Flush with plugins loaded.** `ddev wp rewrite flush --hard` — **without** `--skip-plugins`, so the flush runs with **plugins loaded**. A flush that skips plugins silently drops multilingual and custom routes, 404ing every localised subpage.
10. **Restart.** `ddev restart` to clear the PHP-process caches a `wp cache flush` cannot reach.
11. **Write the baseline.** Send `templates/manifest.php` (with the resolved exclusion scope injected) to emit the in-scope manifest — path, size, mtime per file, and the scope it was taken under — and store it as `.kntnt-wp-skills/last-sync.json`, the baseline `pull` diffs against next time.

## 10. Verify (smoke)

Smoke-test from **live state, never assumption**. Build the URL list from the copy's own database: the front page plus a couple of real published URLs; only if discovery found an active multilingual plugin, add the localised home and a real localised subpage — the canary for the rewrite-flush bug. Fetch each and assert a success response and the **absence** of `There has been a critical error`, `Fatal error`, and `Error establishing a database` in the HTML. Run `ddev wp db check`. Confirm the object-cache state and the expected active-plugin count. Filter cosmetic WP-CLI/MariaDB deprecation notices from the report — they are never failures.

## 11. Cleanup and report

Remove the large local scratch artifacts (the decrypted dump and archive). Production is already state-neutral — the remote directories were deleted in step 7 and nothing was left running.

Report the full decided-and-done record. For clone specifically: tell the operator that **local logins now use production credentials** (the import replaced the local users; the throwaway admin mkwp created is overwritten), and offer to remove the scaffold's default themes and plugins left sitting beside production's.

## Testing note

This orchestration is a **human-verified residual** ([spec](../../docs/spec.md) *Testing Decisions*): the deterministic helpers it drives are unit-tested at the seam, the engine's own verify phase (step 10) is the in-run verification, and a **manual** end-to-end smoke — a clone followed by a pull against a real site — is the operator's residual before release. Nothing in this file reaches a live site during the automated suite.
