# kntnt-wp-skills

[![License](https://img.shields.io/github/license/Kntnt/kntnt-wp-skills)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/Kntnt/kntnt-wp-skills)](https://github.com/Kntnt/kntnt-wp-skills/releases/latest)

A Claude Code plugin that mirrors a live WordPress site down into a local DDEV copy — clone a fresh copy or pull to refresh an existing one.

## Description

kntnt-wp-skills brings a live WordPress site down to your machine as a local DDEV copy. It ships two skills: `clone` creates a fresh local copy in an empty directory, and `pull` refreshes an existing copy from production. Both are started by their slash command and run only when you invoke them; neither fires on its own, because each executes code on production and overwrites the local database.

The plugin reaches production through a single channel — the Novamira MCP server connected to the live site — and never over SSH. Every decision it makes, from which tables to carry with their data to which multi-gigabyte galleries to leave behind, is put to you as a recommendation you accept or override. A routine refresh is a short walk through a handful of gates; an unattended run is a single flag.

### Key features

- Two skills over one transfer engine: `clone` for the first copy, `pull` for an incremental refresh.
- One control channel — the Novamira MCP — and no SSH.
- A recommendation with an accept-or-override gate for every decision, so nothing surprising happens silently.
- Three speeds: interactive by default, `--yes` for an unattended run, and replay of a saved plan for a quick repeat.
- Incremental file transfer against a stored baseline, so a refresh moves only what has changed.
- User data encrypted in transit, with the remote copy deleted the moment the download verifies.
- URL-scoped search-replace and a rewrite flush with plugins loaded, so localised subpages keep working.
- A per-site configuration committed alongside the project, so a copy is reproducible.

### The problem

A faithful local copy of a production WordPress site is more fiddly than it first looks. The database and uploads are large, they carry real user data that has to move safely, and parts of them — analytics tables, generated thumbnails, oversized galleries — are better left behind or rebuilt locally than carried whole. Doing this by hand, again and again, is slow and easy to get subtly wrong. Not everyone even has SSH access to automate it.

### How this plugin helps

The plugin handles the fiddly parts and asks you only about the decisions that matter. It discovers the site's shape, packs a trimmed and encrypted copy on production, downloads only what has changed, imports it into DDEV, and localises the result — thumbnails regenerated, URLs rewritten, rewrite rules flushed with plugins loaded so language routes are not lost. Because it works solely through the Novamira plugin's admin-gated MCP server, enabling it on production is a far smaller ask than handing over SSH.

## Requirements

The plugin assumes you have already put a few things in place. Each note says why it is needed.

- DDEV up and running, which in turn needs Docker (or an equivalent such as OrbStack) and DDEV's own dependencies. These are DDEV concerns, not this plugin's.
- The free Novamira plugin installed and enabled on the production site, with its MCP server connected in Claude Code. This is the only channel to production; the free AGPL build is sufficient, and Novamira Pro is not required.
- `mkwp` available on your `PATH`, used by `clone` to scaffold the local site.

## Installation

Add the plugin's marketplace and install it from within Claude Code:

```
/plugin marketplace add Kntnt/kntnt-wp-skills
/plugin install kntnt-wp-skills@kntnt-wp-skills
```

## Usage

Both skills are started by their slash command and run only when you invoke them. The full option reference lives in the manual pages — [`clone`](docs/man/clone-manual.md) and [`pull`](docs/man/pull.md) — also reachable as `/kntnt-wp-skills:help clone` and `/kntnt-wp-skills:help pull`.

### Clone a new copy

Run `/kntnt-wp-skills:clone` in an empty directory. The skill derives a local project name from the production URL, scaffolds the site with `mkwp` at production's exact core version, and brings down the database and media. After the import your local users are production's, so you log in with your production credentials.

### Refresh an existing copy

Run `/kntnt-wp-skills:pull` from the project directory. The skill takes a rollback backup of the local database, transfers only what has changed since the last sync, re-applies your local state — the inactive plugins you had, the object-cache drop-in — and localises the result. The path to the rollback backup is reported so you can keep it.

### Run modes

- **Interactive** (default) — walk each recommendation; accept it, or decline to reveal the alternatives and choose.
- **`--yes`** — accept every recommendation, pause for nothing, and print a full record of what was decided and done.
- **Replay** — when a saved plan exists for the site, the whole walk collapses to a single *replay the saved plan?* gate.

By default the site's existing mailer stays active so you can test the real send flow; if discovery finds a campaign queued against a real recipient list, the recommendation flips to capturing all mail in DDEV's Mailpit with a loud warning. A risk warning is always shown before the destructive steps, listing what reaches outward — real mail, a running cron firing real webhooks, payments, or social posts, and the database's real user data. Use `--live-mail` or `--capture-mail` to force the choice. Interactive mode waits for your confirmation; `--yes` prints the warning for the record and proceeds.

## Questions, bugs, and feature requests

Have a usage question or something to discuss? Please use [Discussions](https://github.com/Kntnt/kntnt-wp-skills/discussions).

Found a bug or want to request a feature? Please [open an issue](https://github.com/Kntnt/kntnt-wp-skills/issues). Search the existing issues first to avoid duplicates.

## Development

The plugin's logic lives in Python helpers under `scripts/`, with the production-side packing step shipped as a shell template. Clone the repository, then read the coding standard materialised under [`agents.d/coding-standard/`](agents.d/coding-standard/) — `general.md` plus `python.md` — before changing code.

The helpers are covered by a pytest suite under `tests/`. One command runs the whole suite, provisioning pytest through `uv` (no separate install step):

```
uv run --with pytest pytest
```

## How you can contribute

Contributions are welcome, small or large. Before you start, read [`CONTRIBUTING.md`](CONTRIBUTING.md) — it covers which kinds of change are likely to be merged and how inbound licensing works.

## License

Licensed under the Apache License 2.0. The full licence text is in [`LICENSE`](LICENSE).

## Changelog

Release notes for each version live in [`CHANGELOG.md`](CHANGELOG.md).

The project follows [Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).
