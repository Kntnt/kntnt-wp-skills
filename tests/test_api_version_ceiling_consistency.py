# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""API-version pin consistency test — the cross-repo tripwire.

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

Floor and ceiling are now the same number (ADR-0037). ``api_version`` moves only
when the container shape moves, which is exactly when this client must stop and
be re-verified, so accepting one version is the honest statement of what has
been checked rather than a brittle pin. It also means a version-conditioned
back-compat path below the ceiling is unreachable, and that no version number
answers a *behaviour*-level question at all: the Extractor ships caller-visible
behaviour additively, on its ``honours`` list, without moving ``api_version``
(Extractor ADR-0017).

This suite is the anti-drift binding. Every surface that states the floor must
state the ceiling, at the same number, no surface may revert to a floor-only
pin, and no surface may keep a floor this suite has moved past. Moving either
bound is therefore a deliberate edit here plus a matching edit in every surface
— which is the point: it makes verifying against a new Extractor release a
conscious act rather than an omission.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

# The highest Extractor API version this client is verified against. Raise it
# only after checking a release's artifact shape against ``scripts/unseal.py``
# and the container-format contract in ``docs/implementation-notes.md``. The
# 6 -> 7 raise found the bump itself (Extractor plan 008, ADR-0018) to be a
# deliberate compatibility interlock rather than a shape claim -- read the
# ADR before assuming "api_version moved" implies "the artifact moved"; check
# the Extractor's own ``docs/container-format.md`` (its ``FORMAT_VERSION``)
# for the artifact question directly.
VERIFIED_CEILING: int = 7

# The floor: the version production actually runs, raised from 2 to meet the
# ceiling (ADR-0037). Below it the client refuses, so every version-conditioned
# back-compat path under the ceiling is unreachable and none may be re-added.
# The floor is not a behaviour guarantee — a build at this version may still
# not honour any given ``honours`` name — only a statement about the container
# contract this client has been verified against.
FLOOR: int = 7

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
    *sorted((REPO_ROOT / "skills" / "clone" / "roles").glob("*.md")),
    *sorted((REPO_ROOT / "agents").glob("*.md")),
    *sorted((REPO_ROOT / "docs" / "man").glob("*.md")),
    REPO_ROOT / "docs" / "spec.md",
    REPO_ROOT / "docs" / "implementation-notes.md",
)

# Every surface a reader could take the floor from — the live ones an agent
# loads, plus the two front doors an operator reads before ever running the
# skill. A stale floor left standing on any of them is a compatibility promise
# nothing behind it keeps.
FLOOR_STATING_SURFACES: tuple[Path, ...] = tuple(
    dict.fromkeys(
        (
            *LIVE_SURFACES,
            *PINNING_SURFACES,
            REPO_ROOT / "CONTEXT.md",
            REPO_ROOT / "README.md",
        )
    )
)

# Every way a surface writes the floor in prose: "API version ≥ N", "API ≥ N".
# The ADRs and CHANGELOG.md are deliberately outside the scan — both are dated
# records of what was true when they were written, not live statements of the
# pin, and rewriting history to match a raise is the opposite of the point.
FLOOR_PATTERN: re.Pattern[str] = re.compile(r"API(?: version)? ≥ (\d+)")


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
    assert f"pin Extractor to API version ≥ {FLOOR}**" not in text, (
        f"{path.relative_to(REPO_ROOT)} carries the floor-only pin sentence — "
        "the pin is a range, and the ceiling is the half that catches an "
        "artifact contract this client has not been verified against"
    )


@pytest.mark.parametrize(
    "path", FLOOR_STATING_SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_no_surface_states_a_stale_floor(path: Path) -> None:
    """No surface still tells a reader the client accepts a version it now
    refuses. A stale floor is worse than a missing one: it promises support for
    hosts nothing behind it has been checked against, and it authorises
    back-compat prose for Extractors no run can reach."""

    text = path.read_text(encoding="utf-8")
    stale = sorted({int(m.group(1)) for m in FLOOR_PATTERN.finditer(text)} - {FLOOR})
    assert not stale, (
        f"{path.relative_to(REPO_ROOT)} states an API-version floor of "
        f"{stale} where the floor is {FLOOR}"
    )


def test_the_ceiling_is_not_below_the_floor() -> None:
    """A guard on this suite's own literals: a ceiling under the floor would
    refuse every install there is, and both numbers live here."""

    assert VERIFIED_CEILING >= FLOOR
