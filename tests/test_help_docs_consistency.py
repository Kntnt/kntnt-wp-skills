"""Help/docs consistency test — bind the plugin's documentation to its implementation.

The manual pages under ``docs/man/`` are the single source of usage truth, and
``scripts/flags.py`` is the single source of truth for which flags each skill
accepts (ADR-0013). These tests fail the moment the two drift apart, so the
documentation can never silently diverge from the flag surface — the maintainer
guarantee of spec.md user story 57.

Each test asserts one binding: every skill has a manual page; every flag a
manual page documents is in that skill's own registry entry, and every flag in
a skill's registry entry is documented in its own manual page (``clone`` and
``pull`` share one surface by design, ADR-0013; ``mkwp`` — a standalone
scaffold skill, not part of the shared transfer engine — has an unrelated one,
so the binding is per skill, never a blanket cross-check against every other
skill's flags); the ``help`` overview carries each manual page's NAME line; and
every README link into ``docs/man/`` resolves to a real file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import flags
import help as help_module

# Repository layout. This test file sits at ``tests/``, one level below the
# repository root, from which every other path is resolved.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
MAN_DIR: Path = REPO_ROOT / "docs" / "man"
SKILLS_DIR: Path = REPO_ROOT / "skills"
README: Path = REPO_ROOT / "README.md"

# The shape a manual page's NAME line must take: the skill's own name in
# backticks, a spaced em dash, then a non-empty summary — e.g.
# ``\`clone\` — create a fresh local DDEV copy``. The capture group is the
# backticked name, checked against the skill it belongs to. Holding the line to
# this shape is what lets the NAME-line test reject a blank or corrupted NAME
# section instead of silently accepting whatever the parser fell through to.
NAME_LINE_SHAPE: re.Pattern[str] = re.compile(r"^`([^`]+)` — \S")


def _skill_names() -> list[str]:
    """List the plugin's skills: every subdirectory of ``skills/`` that carries
    a ``SKILL.md``. This is the authoritative roster the manual pages must cover."""

    return sorted(d.name for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").is_file())


def _options_flags(manpage: Path) -> set[str]:
    """Extract every backtick-quoted token from a manual page's OPTIONS table.

    Reads the ``## OPTIONS`` section up to the next level-2 heading, and from
    each table data row collects the backtick-delimited tokens in the first
    (Option) column — so the combined ``help``, ``--help``, ``-h`` row yields all
    three. The header row and the ``|---|`` rule are skipped.
    """

    lines = manpage.read_text(encoding="utf-8").splitlines()

    # Slice out the OPTIONS section: from its heading to the next level-2 heading.
    start = next(i for i, line in enumerate(lines) if line.strip() == "## OPTIONS")
    rest = lines[start + 1 :]
    end = next((i for i, line in enumerate(rest) if line.startswith("## ")), len(rest))
    section = rest[:end]

    # From each table data row, collect the Option column's backtick tokens,
    # skipping the header row and the separator rule.
    tokens: set[str] = set()
    for line in section:
        if not line.lstrip().startswith("|"):
            continue
        first_cell = line.strip().strip("|").split("|")[0].strip()
        if first_cell.lower() == "option" or set(first_cell) <= {"-", ":", " "}:
            continue
        tokens.update(re.findall(r"`([^`]+)`", first_cell))
    return tokens


def _readme_manpage_links() -> list[str]:
    """List every Markdown link target in the README that points into
    ``docs/man/`` — the links whose resolution the README promises."""

    targets = re.findall(r"\]\(([^)]+)\)", README.read_text(encoding="utf-8"))
    return [target for target in targets if "docs/man/" in target]


def _name_line(manpage: Path) -> str:
    """Read a manual page's NAME line straight from disk, independently of the
    ``help`` module under test.

    Deliberately does *not* call ``help.name_line``: the overview is built with
    that same function, so checking the overview against it is tautological — the
    only way to fail is an empty return, never a NAME section that is blank or
    corrupted (``help.name_line`` then falls through to the next ``## `` heading
    and the overview embeds it verbatim, undetected). Parsing here yields an
    independent witness whose shape the test can then hold to account.

    Returns the first non-empty line after the ``## NAME`` heading, stripped, or
    an empty string when the page has no NAME heading or nothing follows it.
    """

    lines = manpage.read_text(encoding="utf-8").splitlines()

    # Find the NAME heading, then the first non-empty line beneath it — which for
    # a blank NAME section is the next heading, caught by the shape check below.
    start = next(
        (i for i, line in enumerate(lines) if line.strip().lower() == "## name"), None
    )
    if start is None:
        return ""
    for line in lines[start + 1 :]:
        if line.strip():
            return line.strip()
    return ""


# Values fixed at collection time so each skill and link reports as its own case.
SKILLS: list[str] = _skill_names()
README_MANPAGE_LINKS: list[str] = _readme_manpage_links()


@pytest.mark.parametrize("skill", SKILLS)
def test_every_skill_has_a_manpage(skill: str) -> None:
    """Every skill directory is matched by a manual page under ``docs/man/``."""

    assert (MAN_DIR / f"{skill}.md").is_file(), f"skill {skill!r} has no manual page"


def test_registry_covers_every_skill() -> None:
    """``flags.SKILL_FLAGS`` carries an entry for every skill directory — a
    skill with no registry entry would otherwise ``KeyError`` inside the
    per-skill tests below instead of failing with a clear message."""

    missing = set(SKILLS) - set(flags.SKILL_FLAGS)
    assert not missing, f"flags.SKILL_FLAGS has no entry for: {sorted(missing)}"


def test_clone_and_pull_share_one_flag_surface() -> None:
    """``clone`` and ``pull`` accept exactly the same flags (ADR-0013) — a
    drift between the two would silently break the "one shared transfer
    engine" guarantee that both skills present identically."""

    assert flags.SKILL_FLAGS["clone"] == flags.SKILL_FLAGS["pull"]


@pytest.mark.parametrize("skill", SKILLS)
def test_documented_flags_are_all_in_the_registry(skill: str) -> None:
    """No manual page documents a flag that skill's own registry entry does
    not accept — checked against ``flags.SKILL_FLAGS[skill]``, never the
    flattened ``flags.ALL_FLAGS``, so ``mkwp``'s unrelated surface is never
    cross-checked against ``clone``/``pull``'s and vice versa."""

    documented = _options_flags(MAN_DIR / f"{skill}.md")
    undocumented = documented - flags.SKILL_FLAGS[skill]
    assert not undocumented, (
        f"{skill}.md documents flags absent from its registry entry: {sorted(undocumented)}"
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_every_registry_flag_is_documented(skill: str) -> None:
    """Every flag in a skill's own registry entry is documented in its
    OPTIONS table."""

    documented = _options_flags(MAN_DIR / f"{skill}.md")
    missing = flags.SKILL_FLAGS[skill] - documented
    assert not missing, f"{skill}.md omits registry flags: {sorted(missing)}"


@pytest.mark.parametrize("skill", SKILLS)
def test_help_overview_carries_each_manpage_name_line(skill: str) -> None:
    """The ``help`` overview carries each skill's NAME line, and that line is a
    genuine summary — not a blank or corrupted NAME section the parser fell
    through to.

    The NAME line is parsed independently of ``help.name_line`` (see
    ``_name_line``) and then held to its shape, so the assertion reddens when a
    manual page ships an empty or malformed NAME section — the very drift the
    overview would otherwise carry unnoticed.
    """

    name_line = _name_line(MAN_DIR / f"{skill}.md")

    # Reject a blank or removed NAME section: the parser then falls through to
    # the next ``## `` heading (or returns nothing at all).
    assert name_line and not name_line.startswith("## "), (
        f"{skill}.md has no NAME-line body"
    )

    # Hold the NAME line to its shape — the backticked skill name and an em dash
    # — so a corrupted summary is caught too, not merely an absent one.
    shape = NAME_LINE_SHAPE.match(name_line)
    assert shape and shape.group(1) == skill, (
        f"{skill}.md NAME line is malformed: {name_line!r}"
    )

    # The binding AC #3 actually promises: the rendered overview carries this
    # NAME line verbatim.
    overview = help_module.render_overview(
        REPO_ROOT, help_module.skill_names(REPO_ROOT)
    )
    assert name_line in overview, f"overview omits the NAME line of {skill!r}"


def test_every_readme_manpage_link_resolves() -> None:
    """Every README link into ``docs/man/`` points at a file that exists."""

    assert README_MANPAGE_LINKS, "README references no manual pages"
    unresolved = [
        link
        for link in README_MANPAGE_LINKS
        if not (REPO_ROOT / link.split("#", 1)[0]).is_file()
    ]
    assert not unresolved, f"README manpage links do not resolve: {unresolved}"
