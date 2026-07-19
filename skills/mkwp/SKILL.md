---
name: mkwp
disable-model-invocation: true
description: >
  Create a fresh local WordPress site by driving `mkwp`, deriving sensible
  flag values from context and confirming the rest at recommendation gates.
  Trigger only on the explicit invocations `/mkwp`, `/kntnt-wp-skills:mkwp`,
  or an unmistakable request to scaffold a new local WordPress site with
  `mkwp` (in any language — the examples here are English only). Because it
  writes a new local site and runs `mkwp`'s own DDEV scaffold, it is
  user-invoked only and never auto-triggers; when in doubt, ask first.
---

# mkwp

Create a fresh local WordPress site by driving the `mkwp` command. `mkwp` is **not** part of the shared transfer engine `clone` and `pull` run — there is no production site, no Novamira, no baseline, nothing to import. It starts from nothing: gather the flags `mkwp` itself needs, confirm the ones context cannot settle, and run `mkwp` once. `--yes` accepts every recommendation, never pauses, and prints a full decided-and-done record.

Read `docs/spec.md` (the `mkwp` section) and `CONTEXT.md` (the glossary) alongside this file. Where a literal here and the spec diverge, the spec wins.

## 0. Help gate

If the arguments are `help`, `--help`, or `-h`, run `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/help.py" mkwp`, emit its output verbatim as Markdown, and stop. Do nothing else.

## 1. Version guard

Run `mkwp --help` locally. If the command is not found on `PATH` at all, that is itself the failure — do not fabricate help output. Pipe the result to `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/mkwp_guard.py"` as `{ "helpOutput": <the captured stdout, or null when mkwp was not found> }`. This is the **one place** the guard's pass/fail verdict and remediation are computed — `clone`'s own equivalent step (§1.7 of its health check) and the shared dependency health check (issue #23, once it lands) read the same helper rather than re-deriving the check.

If the verdict's `ok` is `false`, abort immediately and print `reason` and `remediation` verbatim — no gate, no further step, no fabricated stack trace. The operator installs or upgrades binaries; this skill does not.

## 2. Settle NAME

`NAME` is the one value with no sensible universal default — it is the site's own identity, both the `mkwp` positional argument and (sanitised by `mkwp` itself) the DDEV project slug. Take it from context when the conversation already names the site unambiguously (an explicit `/kntnt-wp-skills:mkwp <name>` argument, or the operator naming the project in the preceding turns); otherwise ask directly, even under `--yes` — there is nothing to recommend here, so `--yes` cannot skip it silently.

## 3. Resolve the remaining decisions

Present each decision below as a recommendation behind an accept-or-override gate — *"Recommended: X. Accept? [Y/n]"*, the same shape `clone` and `pull` use ([ADR-0005](../../docs/adr/0005-decision-backbone-gates-and-layered-defaults.md)). Walk them in this order (after `NAME`, so `--dirname`'s mirroring recommendation has the settled `NAME` to fall back on) in interactive mode; in `--yes` mode present nothing per gate and accumulate the full record instead. A decision whose recommendation is "omit the flag" needs no operator confirmation of a value — mkwp's own default already is the recommendation.

- **`--dirname`.** Default: `NAME` (mkwp's own default — omit the flag). If the operator names a domain this site is meant to mirror once it becomes, or already is, a production site reachable by a later `/clone`, recommend that domain's full host instead: pipe `{ "site": { "home_url": "https://<domain>" } }` to `uv run scripts/classify.py` and read `classifications.project_name.directory_name` — the exact function `clone` uses for its own directory naming (issue #11), so a later `/clone` into this same directory needs no rename. Always quote the resolved value in the final command (`--dirname="<value>"`) — the same defense-in-depth `clone` applies against an operator-corrected value carrying a shell metacharacter.
- **`--directory`.** Default: omit (mkwp's own default — the current directory). Recommend an explicit path only when context names one (e.g. the operator mentions a projects folder to create it under).
- **`--title`.** Default: omit (mkwp's own default — `NAME`). Recommend a nicer title only when context supplies one distinct from the technical `NAME` (a company or project name).
- **`--email` / `--user`.** Default: omit both (mkwp's own defaults — current OS username @ hostname, then that email's local part). Recommend the operator's own known email address when the session context supplies one (present the pair together, since `--user` follows from `--email` unless context names a distinct username).
- **`--language`.** Default: omit (mkwp's own default — `en_US`). Recommend a locale only when context indicates one (e.g. a Swedish site or operator → `sv_SE`).
- **`--php`.** Default: omit (mkwp's own default — currently 8.5). Recommend a specific version only when context calls for matching a known target.
- **`--wp`.** Default: omit (mkwp's own default — latest). Recommend a specific version only when context calls for pinning to a known target.
- **`--themes`.** Default: omit (mkwp's own default theme). Recommend only when context names one.
- **`--plugins`.** Default: **Novamira** — `https://github.com/use-novamira/novamira` — recommended every run, because the site needs it the moment it becomes a production site `clone`/`pull` reach ([ADR-0001](../../docs/adr/0001-novamira-mcp-sole-control-channel.md)); append any plugin context names after it, comma-separated. **Forward-pointer:** once the parked companion-plugin epic ([issue #24](https://github.com/Kntnt/kntnt-wp-skills/issues/24)) replaces the control channel, this recommendation switches to the companion plugin instead — do not keep recommending Novamira past that point.
- **`--mu-plugins`.** Default: omit (mkwp's own default — none). Recommend only when context names one.

**Never gather a password.** No `--password` flag is ever offered or passed at any gate — `mkwp`'s own random 16-character generation is always what creates the first user, and the generated value is never captured into this skill's context; only `mkwp`'s own on-screen output shows it, which the operator reads directly.

## 4. Build and run

Assemble the resolved flags into one `mkwp` invocation — `mkwp <name> [--dirname="<value>"] [--directory="<value>"] [--title="<value>"] [--email="<value>"] [--user="<value>"] [--language="<value>"] [--php="<value>"] [--wp="<value>"] [--themes="<value>"] --plugins="<value>" [--mu-plugins="<value>"]` — omitting every flag whose resolved value is mkwp's own default, so the command never carries a redundant flag. Quote every value. Run it from the operator's current directory (or the resolved `--directory`).

`mkwp` performs its own `ddev config`, first `ddev start`, WordPress install, plugin/theme installation, and `ddev launch` — there is nothing downstream in this skill that needs to correct or restart the engine the way `clone`'s bookend does, because there is no production database version to pin against.

## 5. Report

Report the full decided-and-done record: every resolved flag and where it came from (context-derived, gate-accepted, or left at mkwp's own default), the site's local URL (`<name>.ddev.site`), and the directory it landed in. Remind the operator that the first user's password was generated by `mkwp` itself and shown only in `mkwp`'s own on-screen output — this skill never captured or repeats it. If Novamira was installed, remind the operator it still needs to be **activated and connected** as an MCP server in Claude Code before a later `/clone` or `/pull` can reach it ([ADR-0001](../../docs/adr/0001-novamira-mcp-sole-control-channel.md)).

## Testing note

The version guard's pass/fail logic is unit-tested at its own seam (`scripts/mkwp_guard.py`), and the docs-consistency test binds this manual page's flags to the plugin's flag registry. The orchestration prose itself — driving `mkwp` and reading its own report back — is a **human-verified residual** ([spec](../../docs/spec.md) *Testing Decisions*), the same posture `clone` and `pull` take for their own real-tool interactions. Nothing in this file reaches a live `mkwp` invocation during the automated suite.
