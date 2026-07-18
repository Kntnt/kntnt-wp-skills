---
name: pull
disable-model-invocation: true
description: >
  Refresh an existing local DDEV copy of a production WordPress site from
  production. Trigger only on the explicit invocations `/pull`,
  `/kntnt-wp-skills:pull`, or an unmistakable request to refresh an existing
  local copy from production (in any language — the examples here are English
  only). Because it will execute code on production and overwrite the local
  database, it is user-invoked only and never auto-triggers; when in doubt, ask
  first. Not yet implemented — currently a no-op stub.
---

# pull

**Status: not yet implemented — this is a stub.** The specification in `docs/design.md` is still being finalised, so this skill performs no work: it does not contact production, call the Novamira MCP, run any health check, back up or overwrite the local database, or touch any file. It exists only so the plugin's wiring can be tested.

## 0. Help gate

If the arguments are `help`, `--help`, or `-h`, run `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/help.py" pull`, emit its output verbatim as Markdown, and stop. Do nothing else.

## Otherwise

Tell the operator, briefly and in one short message, that the `pull` skill is wired up but not yet implemented: once built it will refresh an existing local DDEV copy from production (see `docs/design.md`), and today it makes no changes. Then stop. Do not run any command, MCP call, or file operation, and do not begin the procedure described in `docs/design.md`.

## Planned behaviour (not active)

The full design — the shared transfer engine, the decisions and their defaults, the safety rails, and every gotcha — lives in `docs/design.md`. When the engine helpers under `scripts/` and the `pack.sh` template exist, this file will orchestrate them; until then it stays a stub.
