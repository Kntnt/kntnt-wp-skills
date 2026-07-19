# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Plugin help: the `/kntnt-wp-skills:help` command and a full manual page for each skill (`clone`, `pull`) and for the `help` command itself, so `/kntnt-wp-skills:help help` documents the reader (without listing `help` among the skills).
- `clone` — create a fresh local DDEV copy of a production WordPress site in an empty directory: scaffolded at production's core version, its table prefix adopted and DDEV's database engine and PHP version pinned to production's, then the packed database and files imported and localised.
- `pull` — refresh an existing local copy, transferring only the files new or changed since the last sync while always dumping the database in full, with a rollback backup taken before the destructive import.
- The shared transfer engine, reached solely over the Novamira MCP (no SSH): a mandatory health check — starting with a dependency step that verifies `ddev` and its container backend, the required CLI tools (`uv`, `jq`, `curl`, `shasum`/`sha256sum`, `openssl`), `mkwp` for `clone` (via the shared `scripts/mkwp_guard.py` guard), and the target site's connected Novamira server with its full `discover-abilities` inventory, stopping early with per-dependency remediation on the first thing missing — a single read-only discovery scan, a background pack that dumps, archives, and encrypts outside the docroot, download-and-verify with immediate remote cleanup, and a deterministic post-clone/pull smoke test of the finished copy against an expectations file (`scripts/smoke_test.py`), runnable standalone and with a `--generate` mode that derives an expectations file from a discovery document.
- Recommendation-driven decisions behind accept-or-override gates, resolved over layered defaults (built-in < live derivation < saved config < this-run answer); `--yes` runs unattended and records every decision, and a saved plan (`.kntnt-wp-skills.json`) collapses a repeat run to a single replay gate.
- Discovery-derived recommendations: wp-config define porting with secrets auto-excluded, operational tables carried empty, heavy-blob and generated-thumbnail exclusion, and the object-cache drop-in ownership rule at pull.
- A fifth table classification family, `user_submissions` (WS Form, Fluent Forms, Formidable, WPForms, Gravity Forms), with its own carry/empty gate defaulting to empty — the most privacy-sensitive data the transfer handles is excluded by default rather than silently emptied alongside the operational tables ([ADR-0014](docs/adr/0014-user-submissions-own-gate-default-empty.md)).
- Safety behaviours: user data encrypted in transit and deleted from production once verified, deletion mirroring off by default and always to a timestamped trash, and a mass-send valve that keeps the real mailer live by default but flips to Mailpit capture on a poised campaign (`--live-mail` / `--capture-mail` pin it), with the risk warning always emitted.
- The minimal flag surface — `--yes`, `--include-media` / `--exclude-media`, `--include-blobs`, `--live-mail` / `--capture-mail`, `--no-cron`, `--regenerate-all`, and the help forms — as a single canonical registry.
- Automated test suite (pytest via uv) over the deterministic helper seam, with a help/docs consistency test binding the manual pages, the flag registry, and the README links together.
- Four pinned subagents shipped under `agents/` (`discovery-classify`, `pack-transfer`, `manifest-baseline-diff`, `thumbnail-smoke-test`, each with model and reasoning effort fixed in its frontmatter) that both skills delegate their heaviest, noisiest phases to, so the orchestrating agent's own context stays clear of MCP round-trip logs, curl/checksum output, and thumbnail-regeneration warning spam; each returns a structured evidence block (exit codes, artifact paths and SHA256, row/file counts, a DONE/FAILED marker) the orchestrator validates with its own cheap deterministic spot checks rather than trusting a second LLM's prose.
- `mkwp` — a third, standalone skill that scaffolds a brand-new local WordPress site by driving the `mkwp` command directly: no production, no Novamira, no transfer engine. It derives site-identity and content flags (`--dirname`, `--directory`, `--title`, `--email`/`--user`, `--language`, `--php`, `--wp`, `--themes`/`--plugins`/`--mu-plugins`) from context where possible and otherwise presents them as recommendation gates, recommends installing Novamira by default so the site is already reachable by a later `clone`/`pull` ([ADR-0001](docs/adr/0001-novamira-mcp-sole-control-channel.md)), and never gathers or echoes a password — that stays `mkwp`'s own random generation. A shared version guard (`scripts/mkwp_guard.py`) verifies the local `mkwp` on `PATH` supports `--dirname` (>= 1.5.0) before scaffolding.
- The flag registry (`scripts/flags.py`) now keys its surface per skill instead of one flattened set, since `mkwp`'s flags have nothing to do with `clone`/`pull`'s; the help/docs consistency test binds each skill's manual page to its own registry entry accordingly.

## [0.1.0] – 2026-07-18

### Added

- Initial release.

[Unreleased]: https://github.com/Kntnt/kntnt-wp-skills/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Kntnt/kntnt-wp-skills/releases/tag/v0.1.0
