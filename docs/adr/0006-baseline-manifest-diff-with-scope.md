# File sync diffs production-now against a stored production-side baseline, with the scope stored in it

Incremental file transfer and deletion detection diff **production-now against the stored last-sync baseline** (`.kntnt-wp-skills/last-sync.json`) — never against the local filesystem, because mtime is unreliable through `tar` → mutagen, whereas both sides of a baseline diff are production mtimes. Detection is size + mtime, mirroring rsync's default quick-check; a checksum mode can be added later.

The baseline stores **the scope it was taken under**, and the production-deleted set is computed only over paths in scope in both the baseline and the current run — so excluding a previously-included directory (e.g. finally excluding the gallery) never mis-classifies its still-present files as production-deleted. We **chose "store scope in the baseline" over a full-scope manifest** (the security review's point 12) to avoid walking excluded trees on every run — settled.
