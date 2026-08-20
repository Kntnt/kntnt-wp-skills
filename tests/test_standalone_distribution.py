"""Standalone-distribution guards — which skills are portable, which are Claude-only.

A generic skill installer (`npx skills` and the ~75 harnesses it targets) copies
only the `skills/<name>/` directory, so a skill that reaches outside its own
directory cannot work in that channel at all. `build-ollie-site` and `mkwp` are
this plugin's portable skills: every path each one names lives under its own
directory, and their one plugin-only reference — the help stanza's
`../../scripts/help.py` — is guarded by an existence check with a documented
standalone fallback, so the help gate degrades instead of breaking.

`mkwp` earns that by owning the two helpers it drives: `classify.py` and
`mkwp_guard.py` ship inside its own `scripts/` directory (issue #51). The
direction that dependency runs in is the whole design rule. A portable skill may
never depend on a hidden one, because a generic installer never installs a
hidden skill; a hidden skill may freely depend on a portable sibling, because
the plugin channel always installs every skill. So `clone`, `pull`, and the
bundled subagents reach both helpers at their home inside `mkwp`, never the
other way round.

`clone` and `pull` are inseparable from the Claude Code plugin: bundled
subagents under `agents/`, the shared transfer-engine helpers under `scripts/`,
and cross-skill delegation. They can never work as a standalone skill install,
so they carry the `metadata.internal` marker that keeps the generic installer
from offering them, and say so in their own prose for anyone who installs one
anyway. Claude Code ignores the unknown key, so the plugin channel is unaffected.

These tests pin that split where it is decided — in the skills' own frontmatter
and prose, and in where the moved helpers live — so a later edit that reaches
back out of a portable skill's directory, that drops a Claude-only skill's
marker, or that points a plugin-only surface at a helper's old home reddens here
rather than shipping a skill that cannot run in the channel it was offered to
(issues #50 and #51).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SKILLS_DIR: Path = REPO_ROOT / "skills"

# The skills a generic installer may offer: everything each one names ships
# inside its own directory.
PORTABLE_SKILLS: tuple[str, ...] = ("build-ollie-site", "mkwp")

# The skills that are inseparable from the plugin — the transfer engine, with
# its bundled subagents and its shared helper surface.
CLAUDE_ONLY_SKILLS: tuple[str, ...] = ("clone", "pull")

# The helpers `mkwp` owns and ships, so a standalone install of it can still run
# its own version guard and its own directory-name derivation.
MKWP_OWNED_HELPERS: tuple[str, ...] = ("classify.py", "mkwp_guard.py")

# Where those two helpers live now, as a path prefix every reference to them
# must carry.
MKWP_HELPER_HOME: str = "skills/mkwp/scripts/"

# The surfaces that drive `mkwp`'s helpers but ship only inside the plugin, so
# they must reach them at their new home rather than at the repo-root `scripts/`
# directory the move emptied.
PLUGIN_ONLY_SURFACES: tuple[str, ...] = (
    "skills/clone/SKILL.md",
    "skills/pull/SKILL.md",
    *sorted(
        str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "agents").glob("*.md")
    ),
)

# The sentence each Claude-only skill states early in its body, so a reader who
# obtained it outside the plugin learns why it cannot work before running it.
PLUGIN_REQUIREMENT: str = (
    "Requires Claude Code with this plugin installed "
    "(`/plugin install kntnt-wp-skills@kntnt-wp-skills`); this skill does not "
    "work as a standalone skill install."
)

# The portable skills' path preamble: what makes every relative path in the
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

# A path into the skill's own bundled asset namespace, wherever the prose puts
# it — on its own inside backticks, or mid-command as in `uv run
# scripts/classify.py`. The match ends at the file extension, so a token that
# carries arguments (`scripts/instantiate_patterns.py check <slug>`,
# `scripts/lint_markup.py --ground-truth ground-truth.json`) still yields just
# the file. The lookbehind rejects any path this one is only the tail of: a
# `../`-prefixed one (the plugin-only help fallback, checked by its own test
# below) and a sibling skill's (`skills/mkwp/scripts/…` as a plugin-only
# surface writes it) both belong to a different anchor than this skill's own
# directory.
SHIPPED_ASSET: re.Pattern[str] = re.compile(
    r"(?<![\w./-])((?:references|scripts)/[\w./-]*\.[A-Za-z0-9]+)"
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


def _is_shipped_source(path: Path) -> bool:
    """Whether a path under a skill directory is source the skill ships, rather
    than the interpreter's own bytecode cache — generated, gitignored, and not
    decodable as text, so a sweep that read it would die on the first byte."""

    return path.is_file() and "__pycache__" not in path.parts


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


@pytest.mark.parametrize("skill", PORTABLE_SKILLS)
def test_portable_skill_is_offered_to_the_standalone_channel(skill: str) -> None:
    """A portable skill carries neither the marker that hides it from a generic
    installer nor the prose telling a reader it cannot run outside the plugin —
    both would be false of a skill that ships everything it names."""

    assert not INTERNAL_MARKER.search(_frontmatter(SKILLS_DIR / skill)), (
        f"{skill}/SKILL.md is marked `metadata.internal: true`, which hides a "
        "portable skill from the one channel it was made portable for"
    )
    assert PLUGIN_REQUIREMENT not in _body(SKILLS_DIR / skill), (
        f"{skill}/SKILL.md still claims it needs the plugin, which a portable "
        "skill does not"
    )


@pytest.mark.parametrize("skill", PORTABLE_SKILLS)
def test_portable_skill_depends_on_no_hidden_skill(skill: str) -> None:
    """The dependency runs one way only. A generic installer never installs a
    hidden skill, so a portable skill that reached into one would break on first
    use in the very channel the marker was meant to protect."""

    body = _body(SKILLS_DIR / skill)
    offenders = [name for name in CLAUDE_ONLY_SKILLS if f"skills/{name}/" in body]
    assert not offenders, (
        f"{skill}/SKILL.md reaches into the hidden skill(s) {offenders}, which a "
        "standalone install never receives"
    )


@pytest.mark.parametrize("helper", MKWP_OWNED_HELPERS)
def test_the_mkwp_helpers_ship_inside_the_skill_that_owns_them(helper: str) -> None:
    """`classify.py` and `mkwp_guard.py` live under `skills/mkwp/scripts/` and
    nowhere else: a standalone `mkwp` cannot run its version guard or derive a
    directory name without them, and two copies would be two truths."""

    assert (SKILLS_DIR / "mkwp" / "scripts" / helper).is_file(), (
        f"{helper} is not shipped inside the mkwp skill, so a standalone "
        "install cannot run it"
    )
    assert not (REPO_ROOT / "scripts" / helper).exists(), (
        f"scripts/{helper} still exists beside the copy inside the mkwp skill — "
        "the move left a second, drifting copy behind"
    )


@pytest.mark.parametrize("surface", PLUGIN_ONLY_SURFACES)
@pytest.mark.parametrize("helper", MKWP_OWNED_HELPERS)
def test_plugin_only_surface_reaches_the_mkwp_helpers_at_their_new_home(
    surface: str, helper: str
) -> None:
    """A plugin-only surface may depend on a portable sibling — the plugin
    channel always installs every skill — but it has to name where the helper
    actually is, so every `scripts/<helper>` token it carries is anchored at the
    skill that owns it."""

    text = (REPO_ROOT / surface).read_text(encoding="utf-8")
    token = f"scripts/{helper}"
    stale = [
        match.start()
        for match in re.finditer(re.escape(token), text)
        if not text[: match.start()].endswith(MKWP_HELPER_HOME[: -len("scripts/")])
    ]
    assert not stale, (
        f"{surface} names {token} at its old home (offsets {stale}); it now "
        f"lives at {MKWP_HELPER_HOME}{helper}"
    )


@pytest.mark.parametrize("skill", PORTABLE_SKILLS)
def test_the_portable_skill_names_no_plugin_root(skill: str) -> None:
    """Nothing under a portable skill's directory names `CLAUDE_PLUGIN_ROOT` —
    the environment variable exists only inside a Claude Code plugin install, so
    any use of it is a path that cannot resolve in the standalone channel."""

    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted((SKILLS_DIR / skill).rglob("*"))
        if _is_shipped_source(path)
        and "CLAUDE_PLUGIN_ROOT" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "a portable skill names CLAUDE_PLUGIN_ROOT, which resolves only "
        f"inside a plugin install: {offenders}"
    )


@pytest.mark.parametrize("skill", PORTABLE_SKILLS)
def test_every_path_the_portable_skill_names_resolves_standalone(
    skill: str, tmp_path: Path
) -> None:
    """Copied alone into an empty directory — exactly what a generic installer
    does — every path the portable skill's SKILL.md names still resolves."""

    installed = tmp_path / skill
    shutil.copytree(SKILLS_DIR / skill, installed)

    mentioned = _mentioned_paths(installed / "SKILL.md")
    assert mentioned, (
        f"no shipped paths were extracted from {skill}'s SKILL.md; the guard "
        "would be enforcing nothing"
    )

    unresolved = [path for path in mentioned if not (installed / path).exists()]
    assert not unresolved, (
        f"a standalone install of {skill} cannot resolve: {unresolved}"
    )


@pytest.mark.parametrize("skill", PORTABLE_SKILLS)
def test_the_portable_skill_states_its_paths_are_skill_relative(skill: str) -> None:
    """A portable skill fixes the anchor every one of its relative paths is read
    against: its own directory, wherever that was installed."""

    assert PATH_PREAMBLE in _body(SKILLS_DIR / skill), (
        f"{skill}/SKILL.md does not state that its relative paths are resolved "
        "against the skill directory"
    )


@pytest.mark.parametrize("skill", PORTABLE_SKILLS)
def test_the_portable_skill_help_gate_degrades_without_the_plugin(skill: str) -> None:
    """The one thing a portable skill cannot ship — the plugin's manual-page
    renderer — is reached through an existence check with a stated standalone
    fallback, so the help gate degrades rather than breaking."""

    body = _body(SKILLS_DIR / skill)

    # The plugin path is named relative to the skill directory, never through
    # the plugin-root environment variable.
    assert "../../scripts/help.py" in body, (
        f"{skill}'s help gate does not reach the plugin's help renderer by a "
        "skill-relative path"
    )

    # Both branches are stated: the file exists (plugin install), and it does
    # not (standalone install).
    assert "does not exist" in body and "standalone skill install" in body, (
        f"{skill}'s help gate does not state what happens when the plugin's "
        "help renderer is absent"
    )


@pytest.mark.parametrize("skill", PORTABLE_SKILLS)
def test_the_portable_skill_trigger_needs_no_plugin_namespace(skill: str) -> None:
    """A portable skill's trigger description lists the bare `/<skill>`
    invocation as sufficient — a standalone install has no plugin namespace to
    prefix it with — while keeping the explicit-only guard clause."""

    frontmatter = _frontmatter(SKILLS_DIR / skill)
    assert f"`/{skill}`" in frontmatter, (
        f"{skill}'s description does not list the bare invocation, which is the "
        "only form a standalone install has"
    )
    assert "never auto-triggers" in frontmatter, (
        f"{skill}'s description lost its explicit-only guard clause"
    )
