"""mkwp version-floor consistency — issue #28.

`Kntnt/mkwp` v1.8.1 fixes [Kntnt/mkwp#3](https://github.com/Kntnt/mkwp/issues/3)
(`ddev config` omitting `--project-name`, so any `--dirname` diverging from
`NAME` broke the scaffold outright with a database-connection error) — the
defect `scripts/mkwp_guard.py` and this plugin's own docs used to warn about
at the pre-fix floor, 1.5.0 (the release that merely added the `--dirname`
flag itself, [Kntnt/mkwp#2](https://github.com/Kntnt/mkwp/issues/2)). Every
document that states the floor must now read 1.8.1, and none may still tell
an operator that 1.5.0 or `mkwp` <= 1.7.0 is sufficient — that would
recommend installing a version the guard itself rejects.

This suite binds every prose floor reference across the plugin to the single
source of truth, `scripts.mkwp_guard.FLOOR_VERSION`, and holds the `mkwp`
skill to having dropped the failure-diagnosis-and-cleanup workaround the
pre-fix floor used to require — dead machinery once the dependency check
already rejects every version the workaround existed for.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import mkwp_guard  # noqa: E402

README: Path = REPO_ROOT / "README.md"
CHANGELOG: Path = REPO_ROOT / "CHANGELOG.md"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
MKWP_MAN: Path = REPO_ROOT / "docs" / "man" / "mkwp.md"
CLONE_MAN: Path = REPO_ROOT / "docs" / "man" / "clone.md"
CLONE_SKILL: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
MKWP_SKILL: Path = REPO_ROOT / "skills" / "mkwp" / "SKILL.md"

# Every document that states the mkwp version floor in operator-facing prose.
FLOOR_DOCUMENTS: tuple[tuple[str, Path], ...] = (
    ("README.md", README),
    ("CHANGELOG.md", CHANGELOG),
    ("docs/spec.md", SPEC),
    ("docs/man/mkwp.md", MKWP_MAN),
    ("docs/man/clone.md", CLONE_MAN),
    ("skills/clone/SKILL.md", CLONE_SKILL),
    ("skills/mkwp/SKILL.md", MKWP_SKILL),
)

# Stale floor/version references that must no longer appear anywhere in these
# documents — 1.5.0 was the pre-fix floor (merely proved --dirname existed),
# and "<= 1.7.0" / "≤ 1.7.0" is the still-broken-version phrasing the pre-fix
# docs used for the known-defect warning.
STALE_FLOOR_REFERENCES: tuple[str, ...] = ("1.5.0", "≤ 1.7.0", "<= 1.7.0")


def test_floor_version_constant_is_1_8_1() -> None:
    """The guard's own floor constant is the single source of truth every
    document below must match."""

    assert mkwp_guard.FLOOR_VERSION == "1.8.1"


@pytest.mark.parametrize("doc_name, path", FLOOR_DOCUMENTS)
def test_document_states_the_raised_floor(doc_name: str, path: Path) -> None:
    """Every document that states the mkwp version floor names 1.8.1, the
    release that fixes Kntnt/mkwp#3."""

    text = path.read_text(encoding="utf-8")
    assert mkwp_guard.FLOOR_VERSION in text, (
        f"{doc_name} never states the raised mkwp floor "
        f"({mkwp_guard.FLOOR_VERSION})"
    )


@pytest.mark.parametrize("doc_name, path", FLOOR_DOCUMENTS)
def test_document_drops_the_stale_pre_fix_floor(doc_name: str, path: Path) -> None:
    """No document still tells an operator the pre-fix floor (1.5.0) or a
    still-broken version (<= 1.7.0) is the requirement — that would recommend
    installing a version the guard itself now rejects."""

    text = path.read_text(encoding="utf-8")
    for stale in STALE_FLOOR_REFERENCES:
        assert stale not in text, (
            f"{doc_name} still references the stale floor {stale!r}"
        )


def test_mkwp_skill_no_longer_prescribes_the_failure_diagnosis_workaround() -> None:
    """The `mkwp` skill's `--dirname` bullet used to warn that a diverging
    value is "known to fail" and prescribe a failure-signature diagnosis
    (grepping the log for the exact database-connection error); the raised
    floor (1.8.1) guarantees the fix before the scaffold ever runs, so that
    prescriptive workaround — dead machinery for a version the dependency
    check already rejects — must be gone."""

    text = MKWP_SKILL.read_text(encoding="utf-8")
    assert "known to fail" not in text.lower()
    assert "known `mkwp` defect" not in text.lower()
    assert "getaddrinfo" not in text.lower()


def test_mkwp_skill_dirname_bullet_is_an_ordinary_recommendation() -> None:
    """With the fix guaranteed by the floor, `--dirname` diverging from
    `NAME` is no longer a warned-against, declined-by-default alternative —
    it is an ordinary recommendation like every other flag's."""

    text = MKWP_SKILL.read_text(encoding="utf-8")
    assert "declined-alternative" not in text.lower()


def test_spec_known_upstream_caveat_states_the_defect_is_fixed() -> None:
    """`docs/spec.md`'s "Known upstream caveat" paragraph reflects the fix:
    the defect existed <= 1.8.0 and is fixed in 1.8.1, guaranteed by the
    raised floor, not merely flagged as an open follow-up issue."""

    text = SPEC.read_text(encoding="utf-8")
    caveat_start = text.index("Known upstream caveat")
    caveat = text[caveat_start : caveat_start + 1500]
    assert "1.8.1" in caveat
    assert re.search(r"fixed|guarantee", caveat, re.IGNORECASE)
