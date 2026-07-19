# pull

## NAME

`pull` — refresh an existing local DDEV copy from production

## SYNOPSIS

```
/kntnt-wp-skills:pull [--yes] [--include-media | --exclude-media] [--include-blobs]
                      [--live-mail | --capture-mail] [--no-cron] [--regenerate-all]
/kntnt-wp-skills:pull (help | --help | -h)
```

## DESCRIPTION

`pull` refreshes an existing local DDEV copy from production. It runs the same shared transfer engine as `clone`, differing only at the bookends: it takes a rollback backup of the local database first, transfers only what has changed since the last sync, and re-applies your local state afterwards.

The skill reaches production solely through the Novamira MCP server; there is no SSH. Before anything else it runs a health check that proves the channel is live, confirms it targets production, probes process-spawning, and preflights the download path. It then diffs production against the stored baseline manifest, so only new and changed files are packed, downloaded, and verified; the remote copy is deleted immediately after verification. The database is always dumped in full. Before importing, the skill verifies the local table prefix still matches production and aborts on a mismatch.

After import the skill localises the copy — regenerating the thumbnails of new or changed attachments (a metadata-driven delta), rewriting URLs to the DDEV host, and flushing rewrite rules with plugins loaded so localised subpages keep working — and restores what should stay local: the inactive plugin set you had, and the object-cache drop-in according to who owns it, verified and removed if it cannot serve a request. When enabled, a deletion gate mirrors only files that provably left production and plugin or theme drift, each itemised and moved to a reversible local trash rather than deleted outright; it is off by default.

Every decision is presented as a recommendation with an accept-or-override gate. Form-submission tables (contact-form entries and the like) are excluded by default behind their own gate, since they are the most privacy-sensitive data the copy carries; accept carry there if you need real entries to debug a form locally. When a saved plan exists for the site, the whole walk collapses to a single *replay the saved plan?* gate, which `--yes` runs silently.

By default the site's existing mailer stays active locally so you can test the send flow end to end; discovery scans for a poised mass-send (a campaign queued or scheduled against a real recipient list — not mere plugin presence), and only then does the recommendation flip to capturing all mail in DDEV's Mailpit, with a loud, specific warning. A risk warning is always emitted before the destructive steps, itemising what reaches outward — real mail can send, a running cron can fire real webhooks, capture real payments, post to connected social accounts, or re-validate a plugin licence from the dev domain, and the database holds real user data.

The pre-import rollback backup is written to a durable, gitignored location and its path is reported.

`pull` is user-invoked only: it never runs on its own, because it executes code on production and overwrites the local database.

## OPTIONS

| Option | Description |
|---|---|
| `--yes` | Autonomous run: accept every recommendation (or replay the saved plan) silently, and print a full record of what was decided and done. |
| `--include-media` | Force the media library delta to be included, overriding the discovery-derived default. |
| `--exclude-media` | Force the media library delta to be excluded, overriding the discovery-derived default. |
| `--include-blobs` | Include the heavy blobs (large galleries, `.mmdb` databases, backups, dumps) that are excluded by default. |
| `--live-mail` | Force the site's real mailer even past a detected mass-send (the "send/test anyway" override). |
| `--capture-mail` | Force all mail to DDEV's Mailpit regardless of what discovery finds. |
| `--no-cron` | Disable local WP-Cron (`define('DISABLE_WP_CRON', true)`), so no scheduled job fires against the copy. |
| `--regenerate-all` | Regenerate every thumbnail after import, not just the metadata-driven delta. |
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Refresh the local copy from production, walking each decision (or the single replay gate when a plan exists):

```
/kntnt-wp-skills:pull
```

Refresh unattended, accepting every recommended default or replaying the saved plan:

```
/kntnt-wp-skills:pull --yes
```

## FILES

| File | Purpose |
|---|---|
| `.kntnt-wp-skills.json` | The settled per-site answers, committed so the copy is reproducible. Read to replay, rewritten when a plan is accepted. |
| `.kntnt-wp-skills/last-sync.json` | The stored baseline manifest (path → size + mtime, and its scope). Derived state, gitignored; rewritten after each successful pull. |
| `.kntnt-wp-skills/backups/` | The pre-import rollback backups. Gitignored, durable. |
| `.kntnt-wp-skills/trash/` | Reversible deletions from the deletion gate, timestamped. Gitignored. |
