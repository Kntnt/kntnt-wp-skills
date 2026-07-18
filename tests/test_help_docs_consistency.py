"""Help/docs consistency test — bind the plugin's documentation to its implementation.

The manual pages under ``docs/man/`` are the single source of usage truth, and
``scripts/flags.py`` is the single source of truth for which flags the skills
accept (ADR-0013). These tests fail the moment the two drift apart, so the
documentation can never silently diverge from the flag surface — the maintainer
guarantee of spec.md user story 57.

Each test asserts one binding: every skill has a manual page; every flag a
manual page documents is in the registry, and every registry flag is documented
for both skills; the ``help`` overview carries each manual page's NAME line; and
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
REPO_ROOT = Path(__file__).resolve().parents[1]
MAN_DIR = REPO_ROOT / "docs" / "man"
SKILLS_DIR = REPO_ROOT / "skills"
README = REPO_ROOT / "README.md"


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


# Values fixed at collection time so each skill and link reports as its own case.
SKILLS = _skill_names()
README_MANPAGE_LINKS = _readme_manpage_links()


@pytest.mark.parametrize("skill", SKILLS)
def test_every_skill_has_a_manpage(skill: str) -> None:
    """Every skill directory is matched by a manual page under ``docs/man/``."""

    assert (MAN_DIR / f"{skill}.md").is_file(), f"skill {skill!r} has no manual page"


@pytest.mark.parametrize("skill", SKILLS)
def test_documented_flags_are_all_in_the_registry(skill: str) -> None:
    """No manual page documents a flag the registry does not accept."""

    documented = _options_flags(MAN_DIR / f"{skill}.md")
    undocumented = documented - flags.ALL_FLAGS
    assert not undocumented, (
        f"{skill}.md documents flags absent from the registry: {sorted(undocumented)}"
    )


@pytest.mark.parametrize("skill", SKILLS)
def test_every_registry_flag_is_documented(skill: str) -> None:
    """Every registry flag is documented in every skill's OPTIONS table."""

    documented = _options_flags(MAN_DIR / f"{skill}.md")
    missing = flags.ALL_FLAGS - documented
    assert not missing, f"{skill}.md omits registry flags: {sorted(missing)}"


@pytest.mark.parametrize("skill", SKILLS)
def test_help_overview_carries_each_manpage_name_line(skill: str) -> None:
    """The overview the ``help`` command renders carries each skill's NAME line."""

    name_line = help_module.name_line(REPO_ROOT, skill)
    overview = help_module.render_overview(REPO_ROOT, help_module.skill_names(REPO_ROOT))
    assert name_line, f"{skill}.md has no NAME line"
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
