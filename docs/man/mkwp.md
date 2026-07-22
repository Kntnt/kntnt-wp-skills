# mkwp

## NAME

`mkwp` — create a fresh local WordPress site by driving `mkwp`

## SYNOPSIS

```
/kntnt-wp-skills:mkwp NAME [--yes] [--dirname=<dirname>] [--directory=<path>]
                      [--title=<title>] [--email=<email>] [--user=<username>]
                      [--language=<locale>] [--php=<version>] [--wp=<version>]
                      [--themes=<themes>] [--plugins=<plugins>]
                      [--mu-plugins=<plugins>]
/kntnt-wp-skills:mkwp (help | --help | -h)
```

## DESCRIPTION

`mkwp` scaffolds a brand-new local WordPress site by driving the `mkwp` command. Unlike `clone` and `pull`, it is **not** part of the shared transfer engine — there is no production site, no control channel, no baseline, and nothing to import: `mkwp` starts from nothing and hands back a running local DDEV site scaffolded by `mkwp` itself.

Before anything else it verifies the local `mkwp` on `PATH` meets the version floor — `mkwp` ≥ 1.8.1 ([Kntnt/mkwp#3](https://github.com/Kntnt/mkwp/issues/3)) — and aborts with precise install guidance if it is missing or too old; the operator installs binaries, this skill does not.

Every flag `mkwp` itself accepts for site identity, ownership, and content is derived from context where the conversation already supplies it, and otherwise presented as a recommendation behind an accept-or-override gate — the same shape `clone` and `pull` use. `NAME` is the one value with no sensible universal default, so it is always settled first, from context or by asking directly. `--dirname` defaults to `NAME` (mkwp's own default); when the site is meant to mirror a domain that is, or will become, a production site reachable by a later `/clone`, that domain's full host (scheme, userinfo, port, and path stripped, `www.` and every dot kept — the same convention `clone` uses for its own directory naming, issue #11) is recommended instead — an ordinary recommendation, not a warned-against alternative, now that the version floor guarantees the fix below. `--yes` accepts every recommendation, never pauses, and prints the full decided-and-done record.

**Value beyond the raw command:** by default `mkwp` recommends adding **Kntnt Extractor** to `--plugins` — the control-channel plugin `clone`/`pull` need the moment this site becomes a production site they reach ([ADR-0016](../../docs/adr/0016-kntnt-extractor-replaces-novamira-as-control-channel.md)). Kntnt Extractor has no WordPress.org listing, so the exact download URL is resolved at run time from the latest GitHub release of [`Kntnt/kntnt-extractor`](https://github.com/Kntnt/kntnt-extractor), matching the release's asset **by name** against `kntnt-extractor-*.zip` (never the first asset positionally, which a future checksums or SBOM asset could silently mis-resolve) — never a bare repo URL or a `.git` clone URL. If resolution fails — GitHub's unauthenticated rate limit, a network error, or no matching asset — Kntnt Extractor is dropped from that run's `--plugins` rather than passed a guessed URL, and the operator is told to add it manually once a working URL is available. Installing the plugin is a recommended default the operator may decline, not a hard dependency; a site can always add it later.

**Known upstream caveat, fixed.** Every `mkwp` ≤ 1.8.0 had a live-verified defect where a `--dirname` that differs from `NAME` broke the scaffold outright (a database-connection error before `wp-config.php` was ever written), because `mkwp`'s own `ddev config` call let DDEV register the project under the directory's name while `mkwp` still assumed the project was registered under `NAME`. [Kntnt/mkwp#3](https://github.com/Kntnt/mkwp/issues/3) fixed this in 1.8.1 — `ddev config` now passes `--project-name=NAME` — and the version floor above guarantees this skill never scaffolds against a version still carrying the defect, which is why `clone`'s own `--dirname` usage (issue #11) is equally safe. This skill still checks that `wp-config.php` exists after running `mkwp` and cleans up a partial DDEV project and directory on any failure, as general robustness for whatever else could still make a scaffold fail — not as a diagnosis of this specific, now-fixed defect.

**Passwords are never gathered.** `mkwp` never offers or passes `--password`: the first user's password is always `mkwp`'s own random generation. Its whole run is redirected to a log file rather than captured as this skill's tool output, precisely because a successful run's own on-screen report prints that password verbatim — the operator reads the log file (or their own terminal, if they run `mkwp` themselves) directly; it is never echoed back into this skill's context.

`mkwp` is user-invoked only: it never runs on its own, because it writes a new local site and runs `mkwp`'s own DDEV scaffold ([ADR-0002](../../docs/adr/0002-skills-user-invoked-only.md)).

## OPTIONS

| Option | Description |
|---|---|
| `--yes` | Autonomous run: accept every recommendation, never pause, and print a full record of what was decided and done. |
| `--dirname` | The directory the site is created in, underneath `--directory`. Recommended default: `NAME`, or the full host of a domain the site is meant to mirror for a future production `--dirname` (see the fixed caveat above). |
| `--directory` | The home directory the site is created under. Recommended default: the current directory (mkwp's own default). |
| `--title` | The WordPress site's title. Recommended default: `NAME` (mkwp's own default), or a nicer title context supplies. |
| `--email` | The first user's email address. Recommended default: mkwp's own (current OS username @ hostname), or the operator's known email from context. |
| `--user` | The first user's username. Recommended default: mkwp's own (the email's local part), or a username context names. |
| `--language` | The site's locale. Recommended default: mkwp's own (`en_US`), or a locale context indicates. |
| `--php` | The PHP version to scaffold. Recommended default: mkwp's own (currently 8.5), or a version context calls for. |
| `--wp` | The WordPress core version to install. Recommended default: mkwp's own (latest), or a version context calls for. |
| `--themes` | Comma-separated themes to install. Recommended default: none (mkwp's own default theme). |
| `--plugins` | Comma-separated plugins to install. Recommended default: Kntnt Extractor, plus any plugin context names. |
| `--mu-plugins` | Comma-separated must-use plugins to install. Recommended default: none. |
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Create a new local site, walking each decision:

```
/kntnt-wp-skills:mkwp my-project
```

Create it unattended, accepting every recommended default (Kntnt Extractor installed, no password ever shown to the agent):

```
/kntnt-wp-skills:mkwp my-project --yes
```

Create it unattended, ahead of a future `/clone` for a known domain, with the mirroring `--dirname` — the directory lands under the domain's full host so the later clone needs no rename; the version floor above guarantees the local `mkwp` already has the fix this needs:

```
/kntnt-wp-skills:mkwp acme --yes --dirname=www.acme.example
```

Create it unattended with an extra plugin alongside the recommended Kntnt Extractor:

```
/kntnt-wp-skills:mkwp my-project --yes --plugins=woocommerce
```

## FILES

`mkwp` writes no file of its own beyond what `mkwp` itself creates for the new site (`.ddev/config.yaml`, `wp-config.php`, and so on). It never writes `.kntnt-wp-skills.json` or `.kntnt-wp-skills/` — those belong to `clone`, once this site later becomes a `clone` target.
