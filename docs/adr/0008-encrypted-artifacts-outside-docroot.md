# Exposure model: pack outside the docroot, publish only encrypted `.enc` artifacts, passphrase over `read-file`

All packing happens in a working dir **outside the docroot**; only the finished artifacts — `db.enc`, `files.enc`, `SHA256` — are briefly published into a random-named docroot download dir for `curl`. Both the DB dump and the file tarball are **encrypted in transit** (`openssl enc -aes-256-cbc -pbkdf2`), so a dropped session can never strand plaintext PII in a web-readable path; a server-side self-destruct timer and the next health check's stranded-workspace sweep guarantee cleanup even if the client never returns.

Artifacts are named `.enc` **from creation** — never renamed — for two reasons at once: managed nginx hosts 404 archive extensions (`.tar.gz`/`.zip`/`.sql`) while serving `.enc` and extension-less files fine, and identical create-time/verify-time names keep `sha256sum -c` honest.

The encryption passphrase is generated **server-side** (`random_bytes(32)`, hex) into a `0600` file outside the docroot, passed to `openssl` via `-pass file:`, fetched locally through Novamira's authenticated `read-file` (never over HTTP), and deleted in cleanup. It does pass through model context on the `read-file` hop — an accepted, stated trade-off, far preferable to PII sitting in a public docroot.

## Amendment (2026-07-19): `read-file`/`write-file` are docroot-only — retrieval goes over `execute-php`

Both smoke-test runs discovered mid-flight that `read-file` and `write-file` are restricted to the docroot, while `pass.key` and the rest of the working dir deliberately live outside it by this ADR's own design. The original text above, read literally, is unreachable: there is no docroot-only ability that can fetch a file this ADR places outside the docroot. The clone run improvised around the gap by briefly **copying `pass.key` into the docroot** to read it back — a workaround that, even with immediate cleanup, contradicts the exposure model this ADR exists to establish. The pull run found the right pattern instead.

Decision: `pass.key` — and every other outside-docroot write or read the pack flow needs (placing `pack.sh` in the working dir, fetching the passphrase back) — goes over `execute-php` with `file_get_contents` / `file_put_contents`, the same authenticated channel, never `read-file` / `write-file`. **`pass.key` must never be copied into the docroot, not even transiently**, to work around this limit. The original text's mention of a `read-file` hop is superseded by this amendment; the ADR's title and body are left as the historical record and are not rewritten.

Recorded under explicit operator authority, 2026-07-19; see issue #16.
