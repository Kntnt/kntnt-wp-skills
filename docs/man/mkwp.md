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

`mkwp` scaffolds a brand-new local WordPress site by driving the `mkwp` command. Unlike `clone` and `pull`, it is **not** part of the shared transfer engine — there is no production site, no Novamira, no baseline, and nothing to import: `mkwp` starts from nothing and hands back a running local DDEV site scaffolded by `mkwp` itself.

Before anything else it verifies the local `mkwp` on `PATH` supports `--dirname` — the floor is `mkwp` ≥ 1.5.0 ([Kntnt/mkwp#2](https://github.com/Kntnt/mkwp/issues/2)) — and aborts with precise install guidance if it is missing or too old; the operator installs binaries, this skill does not.

Every flag `mkwp` itself accepts for site identity, ownership, and content is derived from context where the conversation already supplies it, and otherwise presented as a recommendation behind an accept-or-override gate — the same shape `clone` and `pull` use. `NAME` is the one value with no sensible universal default, so it is always settled first, from context or by asking directly. `--dirname` defaults to `NAME` (mkwp's own default) unless the site is meant to mirror a domain that is, or will become, a production site reachable by a later `/clone` — then the recommendation is that domain's full host (scheme, userinfo, port, and path stripped, `www.` and every dot kept), the same convention `clone` uses for its own directory naming (issue #11), so a later `/clone` into this same directory needs no rename. `--yes` accepts every recommendation, never pauses, and prints the full decided-and-done record.

**Value beyond the raw command:** by default `mkwp` recommends adding **Novamira** to `--plugins` — the free control-channel plugin `clone`/`pull` need the moment this site becomes a production site they reach ([ADR-0001](../../docs/adr/0001-novamira-mcp-sole-control-channel.md)). If the parked companion-plugin epic ([issue #24](https://github.com/Kntnt/kntnt-wp-skills/issues/24)) ever replaces the control channel, this recommendation switches to the companion plugin instead.

**Passwords are never gathered.** `mkwp` never offers or passes `--password`: the first user's password is always `mkwp`'s own random generation, and it is never echoed back into this skill's context — only `mkwp`'s own on-screen report shows it, which the operator reads directly.

`mkwp` is user-invoked only: it never runs on its own, because it writes a new local site and runs `mkwp`'s own DDEV scaffold ([ADR-0002](../../docs/adr/0002-skills-user-invoked-only.md)).

## OPTIONS

| Option | Description |
|---|---|
| `--yes` | Autonomous run: accept every recommendation, never pause, and print a full record of what was decided and done. |
| `--dirname` | The directory the site is created in, underneath `--directory`. Recommended default: `NAME`, or the full host when mirroring a future production domain. |
| `--directory` | The home directory the site is created under. Recommended default: the current directory (mkwp's own default). |
| `--title` | The WordPress site's title. Recommended default: `NAME` (mkwp's own default), or a nicer title context supplies. |
| `--email` | The first user's email address. Recommended default: mkwp's own (current OS username @ hostname), or the operator's known email from context. |
| `--user` | The first user's username. Recommended default: mkwp's own (the email's local part), or a username context names. |
| `--language` | The site's locale. Recommended default: mkwp's own (`en_US`), or a locale context indicates. |
| `--php` | The PHP version to scaffold. Recommended default: mkwp's own (currently 8.5), or a version context calls for. |
| `--wp` | The WordPress core version to install. Recommended default: mkwp's own (latest), or a version context calls for. |
| `--themes` | Comma-separated themes to install. Recommended default: none (mkwp's own default theme). |
| `--plugins` | Comma-separated plugins to install. Recommended default: Novamira, plus any plugin context names. |
| `--mu-plugins` | Comma-separated must-use plugins to install. Recommended default: none. |
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Create a new local site, walking each decision:

```
/kntnt-wp-skills:mkwp my-project
```

Create it unattended, accepting every recommended default (Novamira installed, no password ever shown to the agent):

```
/kntnt-wp-skills:mkwp my-project --yes
```

Create it unattended, ahead of a future `/clone` for a known domain — the directory lands under the domain's full host so the later clone needs no rename:

```
/kntnt-wp-skills:mkwp acme --yes --dirname=www.acme.example
```

Create it unattended with an extra plugin alongside the recommended Novamira:

```
/kntnt-wp-skills:mkwp my-project --yes --plugins=woocommerce
```

## FILES

`mkwp` writes no file of its own beyond what `mkwp` itself creates for the new site (`.ddev/config.yaml`, `wp-config.php`, and so on). It never writes `.kntnt-wp-skills.json` or `.kntnt-wp-skills/` — those belong to `clone`, once this site later becomes a `clone` target.
