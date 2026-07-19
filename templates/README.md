# Production-side templates

The health-check and discovery step reaches production **only** through the Novamira MCP control channel ([ADR-0001](../docs/adr/0001-novamira-mcp-sole-control-channel.md)). The runtime skill sends these templates over that channel; their raw output is piped to `scripts/discovery.py`, which parses it into the one canonical discovery document every later recommendation derives from.

## These templates are inert here

Nothing in this directory is executed against a live site during the build. Per the specification's Testing Decisions, the sole automated seam is the deterministic helper CLI (`scripts/discovery.py`, exercised by `tests/`); the real Novamira interaction is a **human-verified residual**, exercised by the engine's own verify phase on every run and by the manual end-to-end smoke before release. Treat every payload here as a contract to validate at runtime, not as tested code.

## The templates

| Template | Channel ability | Purpose |
|---|---|---|
| `liveness.php` | `execute-php` | Prove the channel is live and return the four facts the health check compares against the target URL — home URL, `ABSPATH`, PHP version, server software (health check step 2). |
| `exec-probe.php` | `execute-php` | Probe process spawning independently of `run-wp-cli`: `function_exists('exec')`, the `disable_functions` list, and a live `exec('printf ok')` round-trip (health check step 4). |
| `stranded-sweep.php` | `execute-php` | List and remove stranded `kntnt-wp-skills-*` working and download directories left by an aborted earlier run (health check step 5). |
| `download-preflight.php` | `execute-php` | Write a tiny **extension-less** test file into a throwaway docroot directory and return its URL and paths, so the local side can fetch it over HTTPS before the heavy pack (health check step 6). |
| `discovery.php` | `execute-php` | The single read-only discovery call: gather everything the discovery document is built from and echo it as one JSON object (Discovery section). |
| `manifest.php` | `execute-php` | Walk production's **whole** content tree, unfiltered, and echo path, size, and mtime per file. Takes no exclusion payload (issue #18) — `scripts/filter_manifest.py` restricts the result to the resolved scope locally before it reaches `scripts/baseline_diff.py`, which diffs it against the stored last-sync baseline (Baseline diff section). |

## PHP payload convention

Each `.php` payload is a fragment sent over `execute-php` and evaluated in the WordPress runtime's global scope. It therefore has no `declare(strict_types=1)` and no namespace (both are illegal or meaningless in that context), unlike a standalone PHP source file under the project coding standard. Each payload ends by echoing a single `json_encode(...)` object and nothing else, so its stdout is the raw JSON the helper reads.

## The raw discovery contract

`discovery.php` echoes an object whose shape is the `discovery` section of the helper's input. The health-check probe outputs (`liveness`, `exec`) are passed to the helper under sibling keys. The canonical fixtures in `tests/fixtures/` are worked examples of this raw shape for a representative site, a monolingual site, a MariaDB site, a poised-campaign site, and an unrecognised-mailer site. The one hard rule the payload shares with the helper: the database password is a connection constant the document never carries, so nothing downstream can leak it.

## The raw manifest contract

`manifest.php` takes no exclusion payload and echoes an object of the shape `{ "entries": [ { "path", "size", "mtime" }, ... ] }`: **every** file of production's content tree, anchored at the WordPress root, unfiltered (issue #18) — the exclusion set never travels to production as part of a manifest request. The runtime skill pipes this raw object, alongside the resolved exclusion set, to `uv run scripts/filter_manifest.py`, which restricts the entries to the in-scope subset and attaches the resolved set as `{ "scope": { "exclusions": [...] } }` — the shape `scripts/baseline_diff.py` has always consumed as the `current` side of its input alongside the stored last-sync baseline. After a successful run, that locally-filtered object is stored verbatim as the next run's baseline. `filter_manifest.py`'s `is_excluded` mirrors `baseline_diff.py`'s `is_excluded` exactly, so the manifest is filtered under the very scope the deletion diff later re-tests against. The worked examples of the diff's input and output are the `baseline-diff-*` fixtures under `tests/fixtures/`.
