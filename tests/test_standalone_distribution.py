"""Standalone-distribution guards — every skill portable, the plugin a superset.

A generic skill installer (`npx skills` and the ~75 harnesses it targets) copies
only the `skills/<name>/` directory, so a skill that reaches outside the set of
skill directories cannot work in that channel at all. All four skills are now
portable: everything each one names lives under its own directory or a sibling
skill's, and their one plugin-only reference — the help stanza's
`../../scripts/help.py` — is guarded by an existence check with a documented
standalone fallback, so the help gate degrades instead of breaking.

`mkwp` earned that first, by owning the two helpers it drives (issue #51);
`clone` earns it the same way, by owning the transfer engine's own helpers,
its role files, and the local-capture mu-plugin template (issue #52). The
direction a dependency runs in is the whole design rule. A portable skill may
never depend on a hidden one, because a generic installer never installs a
hidden skill; between portable siblings the dependency is free, because the
installer can carry both. So `pull` reaches into `../clone/` and both reach
`../mkwp/scripts/classify.py`, while nothing under `skills/` reaches back out
to the plugin root except through a checked, degrading fallback.

These tests pin that where it is decided — in the skills' own frontmatter and
prose, in where the moved helpers live, and in what a copied directory can
still resolve — so a later edit that reaches out of the skill tree, that
re-hides a skill from the channel it was made portable for, or that points a
plugin-only surface at a helper's old home reddens here rather than shipping a
skill that cannot run in the channel it was offered to (issues #50, #51, #52).

What a copied directory can resolve is read from **every** Markdown document
the skill ships, not merely the ones a run executes: narrowing that set to
SKILL.md and the role files was how a design rationale's `../../docs/adr/…`
citation reached out of the skill tree unseen (issues #69, #76). The two
repository-wide link invariants that sit beside this one — that a relative link
resolves from its own file's directory, and that a `blob/main` URL into this
repository names a path that exists — live in
``test_documentation_links.py``.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SKILLS_DIR: Path = REPO_ROOT / "skills"

# Every skill a generic installer may offer — which, since issue #52, is all of
# them. Everything each one names ships inside the skill tree.
PORTABLE_SKILLS: tuple[str, ...] = ("build-ollie-site", "clone", "mkwp", "pull")

# The transfer-engine helpers `clone` owns and ships, so a standalone install
# of the engine can run every deterministic step it prescribes.
CLONE_OWNED_HELPERS: tuple[str, ...] = (
    "baseline_diff.py",
    "bootstrap_parse.py",
    "build_exclusions.py",
    "build_selection.py",
    "discovery.py",
    "dump_sanity.py",
    "filter_manifest.py",
    "flags.py",
    "poll_extraction.py",
    "resolve_plan.py",
    "smoke_test.py",
    "unseal.py",
    "wp_quiet.py",
    "wpconfig_block.py",
)

# The helpers `mkwp` owns and ships, so a standalone install of it can still run
# its own version guard and its own directory-name derivation.
MKWP_OWNED_HELPERS: tuple[str, ...] = ("classify.py", "mkwp_guard.py")

# Where each skill's own helpers live now, as the path prefix every reference
# from outside the skill tree must carry.
HELPER_HOME: dict[str, str] = {
    "clone": "skills/clone/scripts/",
    "mkwp": "skills/mkwp/scripts/",
}

# The one helper that stays at the plugin root: the manual-page renderer, which
# reads `docs/man/` and `.claude-plugin/plugin.json` and so is meaningless
# outside a plugin install. Every skill reaches it through a checked fallback.
PLUGIN_ONLY_HELPER: str = "help.py"

# The surfaces that drive the skills' helpers but ship only inside the plugin,
# so they must reach them at their home inside the owning skill rather than at
# the repo-root `scripts/` directory the moves emptied.
PLUGIN_ONLY_SURFACES: tuple[str, ...] = tuple(
    sorted(
        str(path.relative_to(REPO_ROOT))
        for directory in ("agents", "commands", "docs/man")
        for path in (REPO_ROOT / directory).glob("*.md")
    )
)

# The sentence the Claude-only skills used to carry. No skill may claim it now.
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

# A path into the skill tree's own bundled asset namespace, wherever the prose
# puts it — on its own inside backticks, or mid-command as in `uv run
# scripts/classify.py`. The optional leading `../<skill>/` is a sibling
# reference (`../clone/scripts/unseal.py`), which resolves against the
# directory the installer copied the skills into rather than against one skill
# directory. The match ends at the file extension, so a token that carries
# arguments (`scripts/unseal.py keygen`) still yields just the file. The
# lookbehind rejects any path this one is only the tail of — notably the
# plugin-only `../../scripts/help.py`, checked by its own test below.
SHIPPED_ASSET: re.Pattern[str] = re.compile(
    r"(?<![\w./-])((?:\.\./(?:" + "|".join(PORTABLE_SKILLS) + r")/)?"
    r"(?:references|roles|scripts|templates)/[\w./-]*\.[A-Za-z0-9]+)"
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


def _is_shipped_source(path: Path) -> bool:
    """Whether a path under a skill directory is source the skill ships, rather
    than the interpreter's own bytecode cache — generated, gitignored, and not
    decodable as text, so a sweep that read it would die on the first byte."""

    return path.is_file() and "__pycache__" not in path.parts


def _documents(skill_dir: Path) -> list[Path]:
    """Every Markdown document a skill ships — its SKILL.md, its role files, its
    reference documents, its design rationale, the README beside its templates.

    The set used to be SKILL.md plus the role files, on the reasoning that those
    are the instructions an executor follows step by step. The mechanism was
    right and the document set was the blind spot: a design rationale a SKILL.md
    sends readers to by name is read by whoever installed the skill alone, and
    the path it cites has to resolve there too. Narrowing to the documents that
    drive a run let exactly that link dangle unseen (issues #69, #76), so the
    set is now every Markdown file under the skill directory — the interpreter's
    bytecode cache excluded for the reason `_is_shipped_source` gives.
    """

    return [path for path in sorted(skill_dir.rglob("*.md")) if _is_shipped_source(path)]


def _mentioned_paths(document: Path) -> list[str]:
    """List every path a shipped document names that the skill tree itself
    ships: the backticked `references/…`, `roles/…`, `scripts/…`, and
    `templates/…` assets — own-relative or sibling-relative — plus the relative
    targets of its Markdown links."""

    text = document.read_text(encoding="utf-8")
    paths = set(SHIPPED_ASSET.findall(text))
    paths.update(
        target
        for target in MARKDOWN_LINK.findall(text)
        if "://" not in target and not target.startswith(("#", "mailto:"))
    )
    return sorted(paths)


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


def test_no_skill_is_hidden_from_the_standalone_channel() -> None:
    """The roster above is every skill there is: a fifth one added later without
    a portability pass would otherwise slip past the parametrised guards."""

    present = {path.parent.name for path in SKILLS_DIR.glob("*/SKILL.md")}
    assert present == set(PORTABLE_SKILLS), (
        f"skills/ carries an unexpected set: {sorted(present)}"
    )


@pytest.mark.parametrize("helper", CLONE_OWNED_HELPERS)
def test_the_engine_helpers_ship_inside_the_clone_skill(helper: str) -> None:
    """The transfer engine's helpers live under `skills/clone/scripts/` and
    nowhere else: a standalone `clone` (or the `pull` that reaches into it)
    cannot run a single deterministic step without them, and two copies would
    be two truths."""

    assert (SKILLS_DIR / "clone" / "scripts" / helper).is_file(), (
        f"{helper} is not shipped inside the clone skill, so a standalone "
        "install cannot run it"
    )
    assert not (REPO_ROOT / "scripts" / helper).exists(), (
        f"scripts/{helper} still exists beside the copy inside the clone skill "
        "— the move left a second, drifting copy behind"
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


def test_the_plugin_root_keeps_only_the_manual_page_renderer() -> None:
    """What is left at the repo root is exactly the one helper no skill
    directory could carry: the renderer that reads the plugin's own manual
    pages and manifest. Anything else there is a helper a skill should own."""

    present = {path.name for path in (REPO_ROOT / "scripts").glob("*.py")}
    assert present == {PLUGIN_ONLY_HELPER}, (
        f"the plugin-root scripts/ directory carries {sorted(present)}; only "
        f"{PLUGIN_ONLY_HELPER} belongs to the plugin rather than to a skill"
    )


@pytest.mark.parametrize("surface", PLUGIN_ONLY_SURFACES)
def test_plugin_only_surface_reaches_the_helpers_at_their_new_home(
    surface: str,
) -> None:
    """A plugin-only surface may depend on any skill — the plugin channel always
    installs every one — but it has to name where the helper actually is, so
    every `scripts/<helper>` token it carries is anchored at the skill that owns
    it."""

    text = (REPO_ROOT / surface).read_text(encoding="utf-8")
    owners = {helper: "clone" for helper in CLONE_OWNED_HELPERS}
    owners.update({helper: "mkwp" for helper in MKWP_OWNED_HELPERS})

    stale: list[str] = []
    for helper, owner in owners.items():
        token = f"scripts/{helper}"
        prefix = HELPER_HOME[owner][: -len("scripts/")]
        stale.extend(
            f"{token}@{match.start()}"
            for match in re.finditer(re.escape(token), text)
            if not text[: match.start()].endswith(prefix)
        )
    assert not stale, (
        f"{surface} names a helper at its old home ({stale}); the engine's "
        "helpers now live under skills/clone/scripts/ and mkwp's under "
        "skills/mkwp/scripts/"
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


# The documents that ship inside a skill but drive no step of a run, and were
# therefore never read by the standalone check until issue #76 widened it. Named
# one by one rather than derived, so re-narrowing the document set reddens here
# with the documents it dropped instead of silently checking fewer of them.
DOCUMENTS_BEYOND_THE_SKILL_AND_ITS_ROLES: dict[str, tuple[str, ...]] = {
    "build-ollie-site": (
        "DESIGN-RATIONALE.md",
        "references/cartography.md",
        "references/components.md",
        "references/foundation.md",
        "references/markup.md",
        "references/ollie-errata.md",
        "references/pages.md",
        "references/sections.md",
    ),
    "clone": ("templates/README.md",),
}


@pytest.mark.parametrize("skill", sorted(DOCUMENTS_BEYOND_THE_SKILL_AND_ITS_ROLES))
def test_the_standalone_check_reads_every_document_the_skill_ships(skill: str) -> None:
    """The standalone reach is checked over every Markdown document a skill
    ships, not merely the ones a run executes: a reference file, an errata
    catalogue, a design rationale and a templates README are read by whoever
    installed the skill on its own, and a path any of them names has to resolve
    there."""

    directory = SKILLS_DIR / skill
    read = {path.relative_to(directory).as_posix() for path in _documents(directory)}
    missing = set(DOCUMENTS_BEYOND_THE_SKILL_AND_ITS_ROLES[skill]) - read
    assert not missing, (
        f"the standalone check never reads {skill}'s {sorted(missing)}, so a "
        "path they name could dangle for a standalone reader unseen"
    )


@pytest.mark.parametrize("skill", PORTABLE_SKILLS)
def test_every_path_the_portable_skill_names_resolves_standalone(
    skill: str, tmp_path: Path
) -> None:
    """Copied into an empty directory — exactly what a generic installer does —
    every path the skill's SKILL.md and role files name still resolves, whether
    it points inside the skill's own directory or at a portable sibling's."""

    for name in PORTABLE_SKILLS:
        shutil.copytree(SKILLS_DIR / name, tmp_path / name)

    installed = tmp_path / skill
    mentioned = {
        path for document in _documents(installed) for path in _mentioned_paths(document)
    }
    assert mentioned, (
        f"no shipped paths were extracted from {skill}'s documents; the guard "
        "would be enforcing nothing"
    )

    # A sibling reference is read against the directory the skills were
    # installed into; everything else against the skill's own directory — the
    # anchor the path preamble fixes.
    unresolved = [
        path
        for path in sorted(mentioned)
        if not (tmp_path / path[len("../") :] if path.startswith("../") else installed / path).exists()
    ]
    assert not unresolved, f"a standalone install of {skill} cannot resolve: {unresolved}"


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


# The sibling dependencies the engine is allowed to have, and the preflight
# check each one is guarded by: a standalone install that received only one of
# the pair fails with a precise remediation rather than mid-run on a missing
# file (issue #52).
SIBLING_PREFLIGHT: dict[str, tuple[str, ...]] = {
    "clone": ("../mkwp/scripts/classify.py",),
    "pull": ("../clone/roles/thumbnail-smoke-test.md", "../mkwp/scripts/classify.py"),
}


@pytest.mark.parametrize("skill", sorted(SIBLING_PREFLIGHT))
def test_the_engine_skill_preflights_its_sibling_dependencies(skill: str) -> None:
    """A portable skill that depends on a portable sibling says so where the run
    can still stop cheaply: the health check names the sibling files it needs
    and what to do when they are absent."""

    body = _body(SKILLS_DIR / skill)
    for path in SIBLING_PREFLIGHT[skill]:
        assert path in body, (
            f"{skill}/SKILL.md never preflights the sibling path {path} it "
            "depends on"
        )
    assert re.search(r"install (?:the )?[`/]", body), (
        f"{skill}/SKILL.md's sibling preflight states no remediation for a "
        "missing sibling skill"
    )
