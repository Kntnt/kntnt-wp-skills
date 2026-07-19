# File sync diffs production-now against a stored production-side baseline, with the scope stored in it

Incremental file transfer and deletion detection diff **production-now against the stored last-sync baseline** (`.kntnt-wp-skills/last-sync.json`) — never against the local filesystem, because mtime is unreliable through `tar` → mutagen, whereas both sides of a baseline diff are production mtimes. Detection is size + mtime, mirroring rsync's default quick-check; a checksum mode can be added later.

The baseline stores **the scope it was taken under**, and the production-deleted set is computed only over paths in scope in both the baseline and the current run — so excluding a previously-included directory (e.g. finally excluding the gallery) never mis-classifies its still-present files as production-deleted. We **chose "store scope in the baseline" over a full-scope manifest** (the security review's point 12) to avoid walking excluded trees on every run — settled.

## Addendum (2026-07-19, explicit operator authority): scope filtering moved locally

Scope filtering happens locally now, not on production. `templates/manifest.php` takes no exclusion payload and walks the whole content tree unfiltered; `scripts/filter_manifest.py` applies the resolved exclusion set locally, restricting the walk to the in-scope entries before the manifest reaches `scripts/baseline_diff.py` (issue #18). This was driven by a real-site smoke test: embedding the exclusion set (6,135 entries, ~436KB) into the manifest request sent to production was wasteful and bloated agent context, whereas requesting the full unfiltered tree is a small request whose large response the harness auto-saves to file.

The decision above — **store scope in the baseline** — is unchanged: the resolved scope still travels with the baseline and still gates the deletion diff's scope-intersection rule exactly as before, and `scripts/baseline_diff.py`'s contract is untouched. Only the *mechanism* changes: what used to be production-side pruning during the walk is now a local post-filter of an unfiltered walk, so the exclusion set itself never rides to production.
