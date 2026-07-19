"""Project- and directory-name wording consistency (doc-drift residual from
the integration review).

``scripts/classify.py`` derives two names from production's URL — `name`
(the DDEV project slug) and `directory_name` (the clone's directory name,
issue #11) — but two prose spots lagged behind the two-name reality:
``skills/pull/SKILL.md``'s helper-seam bullet still named only "the derived
project name", where ``skills/clone/SKILL.md``'s equivalent bullet already
says "project and directory names"; and ``docs/spec.md``'s helper-surface
bullet still listed "the project-name derivation", where the same document's
own Testing Decisions section already says "project- and directory-name
derivation". This suite pins both spots to the two-name wording so a future
edit reddens here rather than silently drifting again.
"""

from __future__ import annotations

from pathlib import Path

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
PULL_SKILL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"


def _text(path: Path) -> str:
    """Read a documentation file as UTF-8 text."""

    return path.read_text(encoding="utf-8")


def _seam_bullet_line(text: str, prefix: str) -> str:
    """Return the single line in ``text`` starting with ``prefix`` — the
    specific bullet a wording check targets, not the whole file (a one-line
    summary elsewhere may legitimately use shorthand)."""

    return next(line for line in text.splitlines() if line.startswith(prefix))


def test_pull_skill_helper_seam_bullet_names_both_derived_names() -> None:
    """AC: ``skills/pull/SKILL.md``'s `scripts/classify.py` helper-seam bullet
    names both derived names, matching ``skills/clone/SKILL.md``'s equivalent
    bullet — not only the stale "the derived project name"."""

    text = _text(PULL_SKILL)
    bullet = _seam_bullet_line(text, "- `scripts/classify.py`")
    assert "the derived project and directory names" in bullet, (
        f"pull/SKILL.md's classify.py bullet still names only the project name: {bullet!r}"
    )
    combine_paragraph = _seam_bullet_line(text, "Combine the discovery output")
    assert "the derived project and directory names" in combine_paragraph, (
        "pull/SKILL.md's 'Combine the discovery output' paragraph still names "
        f"only the project name: {combine_paragraph!r}"
    )


def test_spec_helper_surface_bullet_names_both_derived_names() -> None:
    """AC: ``docs/spec.md``'s helper-surface bullet (Architecture section)
    names the project- and directory-name derivation, matching the wording its
    own Testing Decisions section already uses — not the stale
    "the project-name derivation"."""

    text = _text(SPEC)
    assert "the project- and directory-name derivation" in text, (
        "spec.md's helper-surface bullet does not name both derivations"
    )
    assert "owns" in text
    helper_surface_bullet = next(
        line for line in text.splitlines() if line.startswith("- The helper surface owns:")
    )
    assert "the project-name derivation" not in helper_surface_bullet, (
        "spec.md's helper-surface bullet still has the stale one-name wording"
    )
