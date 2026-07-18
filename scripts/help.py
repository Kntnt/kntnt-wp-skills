# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Echo the manual-page ``/help`` output for the kntnt-wp-skills plugin.

The plugin's own files are the single source of truth:
``.claude-plugin/plugin.json`` supplies the header and blurb, and each
``docs/man/<skill>.md`` is a full manual page. This script does not render or
re-align anything — Claude Code renders GitHub-flavoured Markdown in the
terminal, so the manual pages are emitted verbatim. With no argument it prints
the overview (the plugin blurb and every skill's NAME line); with a skill name
it echoes that skill's manual page; with anything else it prints the
unknown-skill line.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Manual-page stems that document a command rather than a skill: echo-able by
# name (so ``help help`` works) but never listed under the overview's Skills.
COMMAND_PAGES = frozenset({"help"})


def plugin_root() -> Path:
    """Resolve the plugin root, preferring the env var Claude Code injects and
    falling back to the script's own location."""

    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    return Path(env) if env else Path(__file__).resolve().parent.parent


def man_dir(root: Path) -> Path:
    """Return the directory holding the per-skill manual pages."""

    return root / "docs" / "man"


def man_names(root: Path) -> list[str]:
    """List every manual-page stem, alphabetically — skills and commands alike."""

    pages = man_dir(root)
    if not pages.is_dir():
        return []
    return sorted(p.stem for p in pages.glob("*.md"))


def skill_names(root: Path) -> list[str]:
    """List the skills that have a manual page — the command pages excluded."""

    return [name for name in man_names(root) if name not in COMMAND_PAGES]


def name_line(root: Path, skill: str) -> str:
    """Extract a manual page's NAME line: the first non-empty line after the
    ``## NAME`` heading. Returns an empty string when the page has none."""

    lines = (man_dir(root) / f"{skill}.md").read_text(encoding="utf-8").splitlines()

    # Find the NAME heading, then the first non-empty line beneath it.
    start = next(
        (i for i in range(len(lines)) if lines[i].strip().lower() == "## name"), None
    )
    if start is None:
        return ""
    for line in lines[start + 1 :]:
        if line.strip():
            return line.strip()
    return ""


def render_overview(root: Path, names: list[str]) -> str:
    """Assemble the overview: the plugin header and blurb, then one bullet per
    skill carrying its NAME line."""

    manifest = json.loads(
        (root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )

    out = [
        f"**{manifest['name']} {manifest['version']}** · {manifest['repository']}",
        "",
        manifest["description"],
        "",
        "## Skills",
        "",
    ]
    out += [f"- {name_line(root, name)}" for name in names]
    out += [
        "",
        f"For a skill's full manual page: `/{manifest['name']}:help <skill>`",
    ]
    return "\n".join(out)


def render_detail(root: Path, skill: str) -> str:
    """Echo a skill's manual page verbatim."""

    return (man_dir(root) / f"{skill}.md").read_text(encoding="utf-8").rstrip("\n")


def render_unknown(arg: str, names: list[str]) -> str:
    """Render the one-line error naming the unrecognised skill and the known
    ones."""

    return f"**Unknown skill:** `{arg}`. Known skills: {', '.join(names)}."


def main() -> None:
    """Dispatch on the optional skill argument: empty → overview, known →
    manual page, otherwise → unknown."""

    root = plugin_root()
    skills = skill_names(root)
    pages = man_names(root)
    arg = sys.argv[1].strip() if len(sys.argv) > 1 else ""

    if not arg:
        print(render_overview(root, skills))
    elif arg in pages:
        print(render_detail(root, arg))
    else:
        print(render_unknown(arg, skills))


if __name__ == "__main__":
    main()
