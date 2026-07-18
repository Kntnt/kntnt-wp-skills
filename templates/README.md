# Production-side templates

The health-check and discovery step reaches production **only** through the Novamira MCP control channel ([ADR-0001](../docs/adr/0001-novamira-mcp-sole-control-channel.md)). The runtime skill sends these templates over that channel; their raw output is piped to `scripts/discovery.py`, which parses it into the one canonical discovery document every later recommendation derives from.

## These templates are inert here

Nothing in this directory is executed against a live site during the build. Per the specification's Testing Decisions, the sole automated seam is the deterministic helper CLI (`scripts/discovery.py`, exercised by `tests/`); the real Novamira interaction is a **human-verified residual**, exercised by the engine's own verify phase on every run and by the manual end-to-end smoke before release. Treat every payload here as a contract to validate at runtime, not as tested code.

## The templates

| Template | Channel ability | Purpose |
|---|---|---|
| `liveness.php` | `execute-php` | Prove the channel is live and return the four facts the health check compares against the target URL — home URL, `ABSPATH`, PHP version, server software (health check step 2). |
| `exec-probe.php` | `execute-php` | Probe process spawning independently of `run-wp-cli`: `function_exists('exec')`, the `disable_functions` list, and a live `exec('printf ok')` round-trip (health check step 4). |
| `download-preflight.php` | `execute-php` | Write a tiny **extension-less** test file into a throwaway docroot directory and return its URL and paths, so the local side can fetch it over HTTPS before the heavy pack (health check step 5). |
| `stranded-sweep.php` | `execute-php` | List and remove stranded `kntnt-wp-skills-*` working and download directories left by an aborted earlier run (health check step 6). |
| `discovery.php` | `execute-php` | The single read-only discovery call: gather everything the discovery document is built from and echo it as one JSON object (Discovery section). |
| `manifest.php` | `execute-php` | Walk production's in-scope content tree and echo the baseline manifest — path, size, and mtime per file, with the scope (exclusions) it was taken under — that `scripts/baseline_diff.py` diffs against the stored last-sync baseline (Baseline diff section). |

## PHP payload convention

Each `.php` payload is a fragment sent over `execute-php` and evaluated in the WordPress runtime's global scope. It therefore has no `declare(strict_types=1)` and no namespace (both are illegal or meaningless in that context), unlike a standalone PHP source file under the project coding standard. Each payload ends by echoing a single `json_encode(...)` object and nothing else, so its stdout is the raw JSON the helper reads.

## The raw discovery contract

`discovery.php` echoes an object whose shape is the `discovery` section of the helper's input. The health-check probe outputs (`liveness`, `exec`) are passed to the helper under sibling keys. The canonical fixtures in `tests/fixtures/` are worked examples of this raw shape for a representative site, a monolingual site, a MariaDB site, a poised-campaign site, and an unrecognised-mailer site. The one hard rule the payload shares with the helper: the database password is a connection constant the document never carries, so nothing downstream can leak it.

## The raw manifest contract

`manifest.php` echoes an object of the shape `{ "scope": { "exclusions": [...] }, "entries": [ { "path", "size", "mtime" }, ... ] }`: the in-scope files of production's content tree, anchored at the WordPress root, together with the exclusion prefixes the walk applied. The runtime skill injects the resolved exclusion set into the payload's `$exclusions` before sending, wraps the echoed object as the `current` side of `scripts/baseline_diff.py`'s input alongside the stored last-sync baseline, and — after a successful run — stores the same object verbatim as the next run's baseline. The payload's `kntnt_wp_skills_is_excluded` mirrors the helper's `is_excluded` exactly, so the manifest is emitted under the very scope the deletion diff later re-tests against. The worked examples of the diff's input and output are the `baseline-diff-*` fixtures under `tests/fixtures/`.
