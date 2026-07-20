# kntnt-wp-skills

[![License](https://img.shields.io/github/license/Kntnt/kntnt-wp-skills)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/Kntnt/kntnt-wp-skills)](https://github.com/Kntnt/kntnt-wp-skills/releases/latest)

A Claude Code plugin that mirrors a live WordPress site down into a local DDEV copy — clone a fresh copy or pull to refresh an existing one — scaffolds a brand-new local site from nothing, and builds one out on the Ollie block theme.

## Description

kntnt-wp-skills brings a live WordPress site down to your machine as a local DDEV copy. It ships four skills: `clone` creates a fresh local copy in an empty directory, `pull` refreshes an existing copy from production, `mkwp` scaffolds a brand-new local site with no production source at all, and `build-ollie-site` builds a site out on the Ollie block theme from a design system and a set of mockups. Each is started by its slash command and runs only when you invoke it; none fires on its own — `clone`/`pull` because each executes code on production and overwrites the local database, `mkwp` because it writes a new local site, and `build-ollie-site` because it writes a theme and content into a WordPress install.

The first three are about *bringing a site down or standing one up*; `build-ollie-site` is about *building one out*. It takes a design system and mockups and builds a coherent, token-correct site on the [Ollie](https://olliewp.com) block theme, bottom-up by Atomic Design — deriving the pattern taxonomy from the mockups' structure, mapping the design system into an Ollie child theme's tokens, then building component patterns, composing them into section patterns by slug reference, and assembling pages from sections. It is the natural next step after a `clone` or `mkwp` has produced the local site to build into.

The plugin reaches production through a single channel — the Novamira MCP server connected to the live site — and never over SSH. Every decision it makes, from which tables to carry with their data to which multi-gigabyte galleries to leave behind, is put to you as a recommendation you accept or override. A routine refresh is a short walk through a handful of gates; an unattended run is a single flag.

### Key features

- Four skills: `clone` and `pull` over one shared transfer engine, the standalone `mkwp` for scaffolding a brand-new local site, and `build-ollie-site` for building a site out on the Ollie block theme.
- Bottom-up, Atomic-Design site building on Ollie: tokens → component patterns → section patterns → pages, derived from your mockups and verified against what the live install actually resolves.
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
- The free Novamira plugin installed and enabled on the production site, with its MCP server connected in Claude Code. This is the only channel to production; the free AGPL build is sufficient, and Novamira Pro is not required. Only `clone` and `pull` need this — `mkwp` does not.
- `mkwp` ≥ 1.8.1 on your `PATH`, used by both the `clone` skill and the `mkwp` skill to scaffold a site. Its `--dirname` flag is what lets the site's directory be named independently of its DDEV project name (e.g. after a full production host, while the DDEV project keeps a shorter, hostname-safe slug); 1.8.1 is the floor because it is the release that fixes [Kntnt/mkwp#3](https://github.com/Kntnt/mkwp/issues/3), where an earlier `mkwp` broke the scaffold outright whenever `--dirname` diverged from the site's name.
- The CLI tools `uv`, `jq`, `curl`, `shasum` or `sha256sum`, and `openssl` on your `PATH` — used by the helper scripts and the transfer pipeline. `clone` and `pull` verify all of the above (and Novamira's abilities) automatically at the start of every run, telling you exactly what is missing and how to fix it rather than failing partway through.

`build-ollie-site` has narrower requirements, because it never touches production: a WordPress install running the **Ollie** block theme as the parent of a child theme you build into (a local DDEV copy that `clone` or `mkwp` produced is the assumed target), WP-CLI reachable as `wp` (or `ddev wp`), and `uv` for its helper scripts. It needs neither Novamira nor `mkwp`; the Ollie Abilities / MCP are optional, used only as a convenience hand for content operations.

## Installation

Add the plugin's marketplace and install it from within Claude Code:

```
/plugin marketplace add Kntnt/kntnt-wp-skills
/plugin install kntnt-wp-skills@kntnt-wp-skills
```

## Usage

Every skill is started by its slash command and runs only when you invoke it. The full option reference lives in the manual pages — [`clone`](docs/man/clone.md), [`pull`](docs/man/pull.md), [`mkwp`](docs/man/mkwp.md), and [`build-ollie-site`](docs/man/build-ollie-site.md) — also reachable as `/kntnt-wp-skills:help clone`, `/kntnt-wp-skills:help pull`, `/kntnt-wp-skills:help mkwp`, and `/kntnt-wp-skills:help build-ollie-site`. `build-ollie-site`'s deeper architecture — how it distils the source skills and where its patterns live — is in its own [`DESIGN-RATIONALE.md`](skills/build-ollie-site/DESIGN-RATIONALE.md).

### Clone a new copy

Run `/kntnt-wp-skills:clone` in an empty directory. The skill derives a local DDEV project name and a clone directory name (the full production host, e.g. `www.example.com`) from the production URL, scaffolds the site with `mkwp` at production's exact core version into that directory, and brings down the database and media. After the import your local users are production's, so you log in with your production credentials.

### Refresh an existing copy

Run `/kntnt-wp-skills:pull` from the project directory. The skill takes a rollback backup of the local database, transfers only what has changed since the last sync, re-applies your local state — the inactive plugins you had, the object-cache drop-in — and localises the result. The path to the rollback backup is reported so you can keep it.

### Scaffold a brand-new local site

Run `/kntnt-wp-skills:mkwp <name>` to create a local WordPress site from nothing — no production source involved. The skill derives what it can from context (site name, directory, title, locale, and so on) and confirms the rest at recommendation gates, the same shape `clone`/`pull` use; `--yes` accepts every recommendation, including installing Novamira so the site is already reachable by a later `/kntnt-wp-skills:clone`/`pull`. The first user's password is always `mkwp`'s own random generation, shown only in its own on-screen output.

### Build a site on Ollie

Run `/kntnt-wp-skills:build-ollie-site` against a local site whose theme is Ollie (or an Ollie child), pointed at your design system and mockups. The skill works bottom-up through gated phases — ground truth → pattern cartography → foundation (tokens) → component patterns → section patterns → pages — and never builds a layer before the one below it is locked and verified. Its distinctive first phase is *pattern cartography*: it derives the pattern taxonomy from the mockups' structure (not their content), proposes it as a manifest, and settles that manifest with you before building anything. Ollie supplies only tokens and global styles; the site's patterns are your own, composed by slug reference so that editing a component cascades to every section and page that uses it.

### Run modes

The transfer-engine skills (`clone`/`pull`) and `mkwp` share these run modes; `build-ollie-site` instead walks its own phase gates, pausing for you to confirm the pattern manifest before the build proceeds.

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
