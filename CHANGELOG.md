# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Plugin help: the `/kntnt-wp-skills:help` command and a full manual page for each skill (`clone`, `pull`) and for the `help` command itself, so `/kntnt-wp-skills:help help` documents the reader (without listing `help` among the skills).
- `clone` — create a fresh local DDEV copy of a production WordPress site in an empty directory: scaffolded at production's core version, its table prefix adopted and DDEV's database engine and PHP version pinned to production's, then the packed database and files imported and localised.
- `pull` — refresh an existing local copy, transferring only the files new or changed since the last sync while always dumping the database in full, with a rollback backup taken before the destructive import.
- The shared transfer engine, reached solely over the Novamira MCP (no SSH): a mandatory health check, a single read-only discovery scan, a background pack that dumps, archives, and encrypts outside the docroot, download-and-verify with immediate remote cleanup, and a live-state smoke test of the finished copy.
- Recommendation-driven decisions behind accept-or-override gates, resolved over layered defaults (built-in < live derivation < saved config < this-run answer); `--yes` runs unattended and records every decision, and a saved plan (`.kntnt-wp-skills.json`) collapses a repeat run to a single replay gate.
- Discovery-derived recommendations: wp-config define porting with secrets auto-excluded, operational tables carried empty, heavy-blob and generated-thumbnail exclusion, and the object-cache drop-in ownership rule at pull.
- Safety behaviours: user data encrypted in transit and deleted from production once verified, deletion mirroring off by default and always to a timestamped trash, and a mass-send valve that keeps the real mailer live by default but flips to Mailpit capture on a poised campaign (`--live-mail` / `--capture-mail` pin it), with the risk warning always emitted.
- The minimal flag surface — `--yes`, `--include-media` / `--exclude-media`, `--include-blobs`, `--live-mail` / `--capture-mail`, `--no-cron`, `--regenerate-all`, and the help forms — as a single canonical registry.
- Automated test suite (pytest via uv) over the deterministic helper seam, with a help/docs consistency test binding the manual pages, the flag registry, and the README links together.

## [0.1.0] – 2026-07-18

### Added

- Initial release.

[Unreleased]: https://github.com/Kntnt/kntnt-wp-skills/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Kntnt/kntnt-wp-skills/releases/tag/v0.1.0
