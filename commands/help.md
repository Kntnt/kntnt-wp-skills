---
description: Manual-page help for the kntnt-wp-skills plugin — list skills or show one skill's manpage
argument-hint: [skill-name]
allowed-tools: Bash(uv:*)
disable-model-invocation: true
model: haiku
---

The user invoked `/kntnt-wp-skills:help`. Argument: `$ARGUMENTS`

`scripts/help.py` reads the plugin's own files — `.claude-plugin/plugin.json` and `docs/man/*.md` — and echoes the help as Markdown. With no argument it prints the overview (the plugin blurb and each skill's NAME line); with a skill name it echoes that skill's full manual page verbatim; with anything else it prints the unknown-skill line.

Rendered help:

!`uv run "${CLAUDE_PLUGIN_ROOT}/scripts/help.py" "$ARGUMENTS"`

Emit the output above **verbatim as Markdown** — it is already GitHub-flavoured Markdown (headings, a fenced SYNOPSIS block, an OPTIONS table) that the terminal renders. Do not wrap it in an outer code fence, and add no preamble, commentary, or summary.
