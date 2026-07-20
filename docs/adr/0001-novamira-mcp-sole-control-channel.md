# Novamira MCP is the sole control channel — no SSH, ever

> **Superseded by [ADR-0016](./0016-kntnt-extractor-replaces-novamira-as-control-channel.md)** (2026-07-20): Novamira is no longer the control channel; `clone`/`pull` reach production through Kntnt Extractor's REST API instead. Left below as the historical record.

The skills need to execute code on the production site (discovery, packing, cleanup). We use the Novamira MCP server as the **only** channel to production; there is no SSH path and none will be added. Rationale: not everyone has SSH access, and "enable an admin-gated plugin" is a far smaller ask than "give an AI SSH". WordPress core's own Abilities/MCP stack cannot substitute — it exposes only curated, registered abilities, no arbitrary execution. The free AGPL Novamira build is sufficient (it exposes `execute-php`, `run-wp-cli` with native background jobs, and file read/write/list); Novamira Pro is not required.

## Consequences

- Everything on production goes through `execute-php` / `run-wp-cli`, including heavy packing work — which forces the background-job pattern of [ADR-0007](./0007-background-pack-job-with-polling.md).
- Novamira must never be deactivated or deleted on production by these skills — it is the control channel.
- The host must allow process spawning (`exec` not in `disable_functions`); the health check probes this and aborts clearly when blocked. A native-`run-wp-cli`-background-job fallback is deliberately deferred (YAGNI until a host actually blocks exec).
