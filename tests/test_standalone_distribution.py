"""Standalone-distribution guards — one skill is portable, three are Claude-only.

A generic skill installer (`npx skills` and the ~75 harnesses it targets) copies
only the `skills/<name>/` directory, so a skill that reaches outside its own
directory cannot work in that channel at all. `build-ollie-site` is this
plugin's one portable skill: every path it names lives under its own directory,
and its single plugin-only reference — the help stanza's `../../scripts/help.py`
— is guarded by an existence check with a documented standalone fallback, so the
help gate degrades instead of breaking.

`clone`, `pull`, and `mkwp` are inseparable from the Claude Code plugin: bundled
subagents under `agents/`, the shared transfer-engine helpers under `scripts/`,
and cross-skill delegation. They can never work as a standalone skill install,
so they carry the `metadata.internal` marker that keeps the generic installer
from offering them, and say so in their own prose for anyone who installs one
anyway. Claude Code ignores the unknown key, so the plugin channel is unaffected.

These tests pin that split where it is decided — in the skills' own frontmatter
and prose — so a later edit that reaches back out of the portable skill's
directory, or that drops a Claude-only skill's marker, reddens here rather than
shipping a skill that cannot run in the channel it was offered to (issue #50).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SKILLS_DIR: Path = REPO_ROOT / "skills"
PORTABLE_SKILL: Path = SKILLS_DIR / "build-ollie-site"

# The skills that are inseparable from the plugin — the transfer engine and the
# standalone scaffold skill that delegates into the same helper surface.
CLAUDE_ONLY_SKILLS: tuple[str, ...] = ("clone", "pull", "mkwp")

# The sentence each Claude-only skill states early in its body, so a reader who
# obtained it outside the plugin learns why it cannot work before running it.
PLUGIN_REQUIREMENT: str = (
    "Requires Claude Code with this plugin installed "
    "(`/plugin install kntnt-wp-skills@kntnt-wp-skills`); this skill does not "
    "work as a standalone skill install."
)

# The portable skill's path preamble: what makes every relative path in the
# document resolvable wherever the skill directory was copied to.
PATH_PREAMBLE: str = (
    "All relative paths in this document are relative to the directory "
    "containing this SKILL.md (the skill directory), regardless of where the "
    "skill is installed."
)

# `metadata.internal: true` in YAML frontmatter: a top-level `metadata:` mapping
# whose indented block carries `internal: true`. Matched with a regex rather
# than a YAML parser so the suite keeps running on the standard library alone.
INTERNAL_MARKER: re.Pattern[str] = re.compile(
    r"^metadata:[ \t]*$\n(?:^[ \t]+.*$\n)*?^[ \t]+internal:[ \t]*true[ \t]*$",
    re.MULTILINE,
)

# A path into the skill's own bundled asset namespace, as the prose backticks
# it. The path ends at the closing backtick or at the first space, so a token
# that carries arguments (`scripts/instantiate_patterns.py check <slug>`,
# `scripts/lint_markup.py --ground-truth ground-truth.json`) still yields just
# the file. A `../`-prefixed path cannot match — the plugin-only help fallback
# is deliberately out of scope here and is checked by its own test below.
SHIPPED_ASSET: re.Pattern[str] = re.compile(
    r"`((?:references|scripts)/[\w./-]+)(?=[`\s])"
)

# A Markdown link target, from which the relative ones are kept.
MARKDOWN_LINK: re.Pattern[str] = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _frontmatter(skill: Path) -> str:
    """Return a SKILL.md's YAML frontmatter block, without its `---` fences."""

    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    assert match is not None, f"{skill.name}/SKILL.md has no YAML frontmatter"
    return match.group(1)


def _body(skill: Path) -> str:
    """Return a SKILL.md's body — everything after the frontmatter block."""

    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    return re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)


def _intro(skill: Path) -> str:
    """Return a SKILL.md's introduction: the body up to its first section
    heading. What a reader meets before any procedure starts — which is what
    "early in the body" has to mean for a warning to do its job."""

    return re.split(r"^## ", _body(skill), maxsplit=1, flags=re.MULTILINE)[0]


def _mentioned_paths(skill_md: Path) -> list[str]:
    """List every path a SKILL.md names that the skill directory itself ships:
    the backticked `references/…` and `scripts/…` assets, plus the relative
    targets of its Markdown links."""

    text = skill_md.read_text(encoding="utf-8")
    paths = set(SHIPPED_ASSET.findall(text))
    paths.update(
        target
        for target in MARKDOWN_LINK.findall(text)
        if "://" not in target and not target.startswith(("#", "mailto:"))
    )
    return sorted(paths)


@pytest.mark.parametrize("skill", CLAUDE_ONLY_SKILLS)
def test_claude_only_skill_carries_the_internal_marker(skill: str) -> None:
    """Each plugin-bound skill is marked `metadata.internal: true`, so a generic
    installer leaves it out of the standalone channel it cannot work in."""

    frontmatter = _frontmatter(SKILLS_DIR / skill)
    assert INTERNAL_MARKER.search(frontmatter), (
        f"{skill}/SKILL.md frontmatter lacks `metadata.internal: true`; a "
        "generic skill installer would offer a skill that cannot run"
    )


@pytest.mark.parametrize("skill", CLAUDE_ONLY_SKILLS)
def test_claude_only_skill_states_the_plugin_requirement(skill: str) -> None:
    """Each plugin-bound skill says so in its introduction, before any
    procedure — the marker hides it from the installer, this tells the reader
    who obtained it some other way."""

    assert PLUGIN_REQUIREMENT in _intro(SKILLS_DIR / skill), (
        f"{skill}/SKILL.md does not state the plugin requirement in its introduction"
    )


def test_the_portable_skill_names_no_plugin_root() -> None:
    """Nothing under the portable skill's directory names
    `CLAUDE_PLUGIN_ROOT` — the environment variable exists only inside a Claude
    Code plugin install, so any use of it is a path that cannot resolve in the
    standalone channel."""

    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted(PORTABLE_SKILL.rglob("*"))
        if path.is_file() and "CLAUDE_PLUGIN_ROOT" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "the portable skill names CLAUDE_PLUGIN_ROOT, which resolves only "
        f"inside a plugin install: {offenders}"
    )


def test_every_path_the_portable_skill_names_resolves_standalone(
    tmp_path: Path,
) -> None:
    """Copied alone into an empty directory — exactly what a generic installer
    does — every path the portable skill's SKILL.md names still resolves."""

    installed = tmp_path / PORTABLE_SKILL.name
    shutil.copytree(PORTABLE_SKILL, installed)

    mentioned = _mentioned_paths(installed / "SKILL.md")
    assert mentioned, (
        "no shipped paths were extracted from the portable skill's SKILL.md; "
        "the guard would be enforcing nothing"
    )

    unresolved = [path for path in mentioned if not (installed / path).exists()]
    assert not unresolved, (
        f"a standalone install of {PORTABLE_SKILL.name} cannot resolve: {unresolved}"
    )


def test_the_portable_skill_states_its_paths_are_skill_relative() -> None:
    """The portable skill fixes the anchor every one of its relative paths is
    read against: its own directory, wherever that was installed."""

    assert PATH_PREAMBLE in _body(PORTABLE_SKILL), (
        "build-ollie-site/SKILL.md does not state that its relative paths are "
        "resolved against the skill directory"
    )


def test_the_portable_skill_help_gate_degrades_without_the_plugin() -> None:
    """The one thing the portable skill cannot ship — the plugin's manual-page
    renderer — is reached through an existence check with a stated standalone
    fallback, so the help gate degrades rather than breaking."""

    body = _body(PORTABLE_SKILL)

    # The plugin path is named relative to the skill directory, never through
    # the plugin-root environment variable.
    assert "../../scripts/help.py" in body, (
        "the help gate does not reach the plugin's help renderer by a "
        "skill-relative path"
    )

    # Both branches are stated: the file exists (plugin install), and it does
    # not (standalone install).
    assert "does not exist" in body and "standalone skill install" in body, (
        "the help gate does not state what happens when the plugin's help "
        "renderer is absent"
    )


def test_the_portable_skill_trigger_needs_no_plugin_namespace() -> None:
    """The portable skill's trigger description lists the bare `/build-ollie-site`
    invocation as sufficient — a standalone install has no plugin namespace to
    prefix it with — while keeping the explicit-only guard clause."""

    frontmatter = _frontmatter(PORTABLE_SKILL)
    assert "`/build-ollie-site`" in frontmatter, (
        "the description does not list the bare invocation, which is the only "
        "form a standalone install has"
    )
    assert "never auto-triggers" in frontmatter, (
        "the description lost its explicit-only guard clause"
    )
