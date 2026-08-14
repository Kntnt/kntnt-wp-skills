# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""API-version ceiling consistency test — the cross-repo tripwire.

The Extractor's API version governs the *artifact's* shape, not only its REST
surface. Version 5 changed a table from exactly one sealed segment into one or
more, and a client that had not been updated kept only the last segment it saw
for each name — every table but its final slice lost, with no error raised on
either side. Both repositories' own suites were green throughout: nothing tested
the contract between them, and a floor-only version check (`>= 2`) accepted the
new artifact without knowing anything had changed.

A floor cannot catch that, because the hazard is a version *above* what the
client understands. So the skills also carry a verified ceiling: the highest
Extractor API version this client has actually been checked against. A
`GET /status` reporting more than that stops for the operator rather than
proceeding on an unverified artifact contract.

This suite is the anti-drift binding. Every surface that states the floor must
state the ceiling, at the same number, and no surface may revert to a
floor-only pin. Raising the ceiling is therefore a deliberate edit here plus a
matching edit in every surface — which is the point: it makes verifying against
a new Extractor release a conscious act rather than an omission.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

# The highest Extractor API version this client is verified against. Raise it
# only after checking a release's artifact shape against ``scripts/unseal.py``
# and the container-format contract in ``docs/implementation-notes.md``.
VERIFIED_CEILING: int = 6

# The floor, unchanged since it was set: the version that ships the environment
# endpoint, structure-only extraction, and caller job listing together.
FLOOR: int = 2

# Every surface that states the version pin. Each must carry both bounds, so a
# reader who loads only one of them still learns the whole rule.
PINNING_SURFACES: tuple[Path, ...] = (
    REPO_ROOT / "skills" / "clone" / "SKILL.md",
    REPO_ROOT / "skills" / "pull" / "SKILL.md",
    REPO_ROOT / "docs" / "spec.md",
    REPO_ROOT / "docs" / "implementation-notes.md",
)

# The live surfaces an agent actually loads or is pointed at. A floor-only pin
# surviving on any of them is the regression this suite exists to catch.
LIVE_SURFACES: tuple[Path, ...] = (
    *sorted((REPO_ROOT / "skills").glob("*/SKILL.md")),
    *sorted((REPO_ROOT / "agents").glob("*.md")),
    *sorted((REPO_ROOT / "docs" / "man").glob("*.md")),
    REPO_ROOT / "docs" / "spec.md",
    REPO_ROOT / "docs" / "implementation-notes.md",
)


@pytest.mark.parametrize(
    "path", PINNING_SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_every_pinning_surface_states_the_ceiling(path: Path) -> None:
    """Each surface that pins the API version names the verified ceiling, so no
    single file states a floor the reader would take for the whole rule."""

    text = path.read_text(encoding="utf-8")
    assert re.search(rf"≤ {VERIFIED_CEILING}\b", text), (
        f"{path.relative_to(REPO_ROOT)} does not state the verified API-version "
        f"ceiling (≤ {VERIFIED_CEILING}) — a floor-only pin accepts an "
        "Extractor whose artifact shape this client has never been checked "
        "against, which is how API version 5 lost every table's non-final slice"
    )


@pytest.mark.parametrize(
    "path", PINNING_SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_every_pinning_surface_still_states_the_floor(path: Path) -> None:
    """The ceiling supplements the floor, never replaces it: an Extractor below
    the floor lacks endpoints the run depends on and is still refused."""

    text = path.read_text(encoding="utf-8")
    assert re.search(rf"≥ {FLOOR}\b", text), (
        f"{path.relative_to(REPO_ROOT)} no longer states the API-version floor "
        f"(≥ {FLOOR})"
    )


@pytest.mark.parametrize(
    "path", LIVE_SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_no_live_surface_carries_a_floor_only_pin(path: Path) -> None:
    """No live surface still says the skills pin the Extractor to a floor alone.
    That sentence is what let an unverified artifact shape through unremarked."""

    text = path.read_text(encoding="utf-8")
    assert "pin Extractor to API version ≥ 2**" not in text, (
        f"{path.relative_to(REPO_ROOT)} carries the floor-only pin sentence — "
        "the pin is a range, and the ceiling is the half that catches an "
        "artifact contract this client has not been verified against"
    )


def test_the_ceiling_is_not_below_the_floor() -> None:
    """A guard on this suite's own literals: a ceiling under the floor would
    refuse every install there is, and both numbers live here."""

    assert VERIFIED_CEILING >= FLOOR
