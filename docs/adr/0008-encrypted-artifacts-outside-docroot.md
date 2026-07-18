# Exposure model: pack outside the docroot, publish only encrypted `.enc` artifacts, passphrase over `read-file`

All packing happens in a working dir **outside the docroot**; only the finished artifacts — `db.enc`, `files.enc`, `SHA256` — are briefly published into a random-named docroot download dir for `curl`. Both the DB dump and the file tarball are **encrypted in transit** (`openssl enc -aes-256-cbc -pbkdf2`), so a dropped session can never strand plaintext PII in a web-readable path; a server-side self-destruct timer and the next health check's stranded-workspace sweep guarantee cleanup even if the client never returns.

Artifacts are named `.enc` **from creation** — never renamed — for two reasons at once: managed nginx hosts 404 archive extensions (`.tar.gz`/`.zip`/`.sql`) while serving `.enc` and extension-less files fine, and identical create-time/verify-time names keep `sha256sum -c` honest.

The encryption passphrase is generated **server-side** (`random_bytes(32)`, hex) into a `0600` file outside the docroot, passed to `openssl` via `-pass file:`, fetched locally through Novamira's authenticated `read-file` (never over HTTP), and deleted in cleanup. It does pass through model context on the `read-file` hop — an accepted, stated trade-off, far preferable to PII sitting in a public docroot.
