# clone

## NAME

`clone` — create a fresh local DDEV copy of a production WordPress site

## SYNOPSIS

```
/kntnt-wp-skills:clone [--yes] [--include-media | --exclude-media] [--include-blobs]
                       [--live-mail | --capture-mail] [--no-cron] [--regenerate-all]
/kntnt-wp-skills:clone (help | --help | -h)
```

## DESCRIPTION

`clone` builds a new local DDEV copy of a production WordPress site in an empty directory. It derives both a local DDEV project name and a clone directory name from the production URL — the directory named after the full original host (e.g. `www.example.com`), the DDEV project kept a valid hostname label (e.g. `example`) — scaffolds the site with `mkwp` at production's exact core version into that directory — pinning DDEV's database engine and PHP version to production's and adopting production's table prefix — then brings down the database and media through the shared transfer engine and localises the result so the copy runs against the DDEV URL.

The skill reaches production solely through the Novamira MCP server connected to the live site; there is no SSH. Before anything else it runs a health check that proves the channel is live, confirms it targets production rather than the local site, probes that process-spawning is available for the pack job, and preflights the download path. It then discovers the site's shape, packs a trimmed and encrypted copy on production as a background job, downloads and verifies it, deletes the remote copy immediately, and imports the result into DDEV. Localisation regenerates the affected thumbnails, rewrites URLs to the DDEV host, and flushes rewrite rules with plugins loaded so language routes survive.

Every decision is presented as a recommendation with an accept-or-override gate — which tables to carry with their data, which heavy blobs to leave behind, which `wp-config.php` defines to port. In interactive mode you walk the gates; under `--yes` every recommendation is accepted, nothing pauses, and a full record of what was decided and done is printed for you to read on return.

By default the site's existing mailer stays active locally so you can test the send flow end to end; discovery scans for a poised mass-send (a campaign queued or scheduled against a real recipient list — not mere plugin presence), and only then does the recommendation flip to capturing all mail in DDEV's Mailpit, with a loud, specific warning. A risk warning is always emitted before the destructive steps, itemising what reaches outward — real mail can send, a running cron can fire real webhooks, capture real payments, post to connected social accounts, or re-validate a plugin licence from the dev domain, and the database holds real user data.

After the import your local users are production's, so you log in with your production credentials — the throwaway admin `mkwp` created is overwritten.

`clone` is user-invoked only: it never runs on its own, because it executes code on production and writes a new local site.

## OPTIONS

| Option | Description |
|---|---|
| `--yes` | Autonomous run: accept every recommendation, never pause, and print a full record of what was decided and done. |
| `--include-media` | Force the media library to be included, overriding the discovery-derived default. |
| `--exclude-media` | Force the media library to be excluded, overriding the discovery-derived default. |
| `--include-blobs` | Include the heavy blobs (large galleries, `.mmdb` databases, backups, dumps) that are excluded by default. |
| `--live-mail` | Force the site's real mailer even past a detected mass-send (the "send/test anyway" override). |
| `--capture-mail` | Force all mail to DDEV's Mailpit regardless of what discovery finds. |
| `--no-cron` | Disable local WP-Cron (`define('DISABLE_WP_CRON', true)`), so no scheduled job fires against the copy. |
| `--regenerate-all` | Regenerate every thumbnail after import, not just the affected set. |
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Clone a production site into the current empty directory, walking each decision:

```
/kntnt-wp-skills:clone
```

Clone unattended, accepting every recommended default:

```
/kntnt-wp-skills:clone --yes
```

Clone unattended, pulling the large galleries too and disabling cron on the copy:

```
/kntnt-wp-skills:clone --yes --include-blobs --no-cron
```

## FILES

| File | Purpose |
|---|---|
| `.kntnt-wp-skills.json` | The settled per-site answers, committed so the copy is reproducible. Written when a plan is accepted. |
| `.kntnt-wp-skills/last-sync.json` | The stored baseline manifest (and its scope) used by `pull` for the incremental diff. Derived state, gitignored. |
