# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Back-compat paths are anchored where their discriminator actually lives — #79.

The API-version floor rose to meet the ceiling (ADR-0037), and the tempting
conclusion — "the floor rose, therefore every back-compat path below it is
dead" — is true of exactly one of them. `api_version` bounds the artifact's byte
layout and nothing else (Extractor ADR-0017): caller-visible *behaviour* ships
additively, named on the authenticated `GET /status`'s ``honours`` list, without
moving the number. So a build reporting `api_version: 7` may still not honour
``strict``, ``chunks_done``, or ``disclosure``, and a guard that reads the
version number to answer a behaviour question was never right — the floor raise
does not make it right, and does not make its fallback dead.

This suite binds the split:

- The identity report (`authenticated_as` / `capabilities`) is *not* an honours
  name. The version number is its real discriminator, and at the floor the
  condition is unreachable — so the bullet, and the wrong-password fallback that
  stood in for it, are gone from every live surface.
- ``chunks_done``, ``strict``, ``chunk_size``, and ``packaging_skips`` all are
  honours names. Their bullets fire on the list, never on a version comparison
  and never unconditionally, and their fallbacks stay reachable.
- The define-disclosure by-value fallback is guarded by member *presence*. No
  surface may credit the floor for it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

# The two orchestrations whose §11 carries the degraded-behaviour section.
SKILLS: tuple[tuple[str, Path], ...] = (
    ("clone", REPO_ROOT / "skills" / "clone" / "SKILL.md"),
    ("pull", REPO_ROOT / "skills" / "pull" / "SKILL.md"),
)

# Every surface an agent loads or is pointed at, plus the two documentation
# surfaces that state the same rules for a human reader.
LIVE_SURFACES: tuple[Path, ...] = (
    *sorted((REPO_ROOT / "skills").glob("*/SKILL.md")),
    *sorted((REPO_ROOT / "skills" / "clone" / "roles").glob("*.md")),
    *sorted((REPO_ROOT / "agents").glob("*.md")),
    REPO_ROOT / "docs" / "spec.md",
    REPO_ROOT / "docs" / "implementation-notes.md",
    REPO_ROOT / "docs" / "poll-discipline.md",
)

# The honours names whose degraded-behaviour bullet must fire on the list.
HONOURS_KEYED_BULLETS: tuple[str, ...] = (
    "chunks_done",
    "strict",
    "chunk_size",
    "packaging_skips",
)

# A bullet conditioned on the version number rather than on a behaviour name.
VERSION_KEYED_BULLET: re.Pattern[str] = re.compile(r"^- \*\*Below API version \d+\*\*")


def read(path: Path) -> str:
    """The surface's text, or a clear failure naming the file that is missing."""

    assert path.is_file(), f"{path} does not exist"
    return path.read_text(encoding="utf-8")


def degraded_bullets(text: str) -> list[str]:
    """Every bullet of the run report's degraded-behaviour list."""

    return [line for line in text.splitlines() if line.startswith("- **")]


# --- What the raised floor genuinely killed ----------------------------------


@pytest.mark.parametrize("skill, path", SKILLS)
def test_no_degraded_bullet_fires_on_a_version_number(skill: str, path: Path) -> None:
    """At the floor, "below API version N" cannot be met for any N under the
    ceiling. A bullet that still says so describes a host no run can reach."""

    offenders = [
        bullet
        for bullet in degraded_bullets(read(path))
        if VERSION_KEYED_BULLET.match(bullet)
    ]
    assert not offenders, (
        f"the {skill} degraded-behaviours list still keys a bullet on the API "
        f"version, whose condition the raised floor makes unreachable: {offenders}"
    )


@pytest.mark.parametrize("path", LIVE_SURFACES, ids=lambda p: p.name)
def test_no_live_surface_describes_an_extractor_without_the_identity_report(
    path: Path,
) -> None:
    """`authenticated_as` and `capabilities` have been on `GET /status` since
    API version 4 and are not honours names, so at the floor every install has
    them. The wrong-password discriminating test survives as the diagnosis for
    an apparently-anonymous refusal — it is no longer a *fallback* for an
    Extractor too old to report identity, because there is no such Extractor."""

    text = read(path)
    stale = re.findall(r"API version < \d+|[Ff]allback for an older Extractor", text)
    assert not stale, (
        f"{path.relative_to(REPO_ROOT)} still describes an Extractor below the "
        f"API-version floor: {stale}"
    )


# --- What the raised floor did not touch -------------------------------------


@pytest.mark.parametrize("skill, path", SKILLS)
@pytest.mark.parametrize("member", HONOURS_KEYED_BULLETS)
def test_every_behaviour_bullet_fires_on_the_honours_list(
    member: str, skill: str, path: Path
) -> None:
    """A behaviour-level degradation is discoverable only from ``honours``. Each
    of these fires on the list — at the ceiling as readily as below it — never on
    a version comparison and never unconditionally."""

    bullets = [
        bullet
        for bullet in degraded_bullets(read(path))
        if bullet.startswith("- **`honours`") and f"`{member}`" in bullet
    ]
    assert len(bullets) == 1, (
        f"the {skill} degraded-behaviours list has no single honours-keyed "
        f"bullet for {member!r}"
    )


@pytest.mark.parametrize("skill, path", SKILLS)
def test_the_strict_bullet_is_no_longer_reported_unconditionally(
    skill: str, path: Path
) -> None:
    """The `strict` bullet used to fire against every host, on the stated
    grounds that no version number distinguishes a build that honours the member
    from one that ignores it. That was true of the version number and false of
    ``honours``, which names ``strict`` for exactly this reason."""

    text = read(path)
    assert "no version number distinguishes an Extractor that honours" not in text, (
        f"the {skill} SKILL still says nothing distinguishes a host that "
        "honours strict — the honours list does, and names it"
    )


@pytest.mark.parametrize("skill, path", SKILLS)
def test_the_remedy_for_a_degraded_behaviour_is_still_an_upgrade(
    skill: str, path: Path
) -> None:
    """Re-anchoring the guard must not turn a degradation into something the
    client is expected to work around: the remedy is production's Extractor."""

    text = read(path)
    assert "the remedy for all of it is upgrading production's Extractor" in text, (
        f"the {skill} degraded-behaviours lead-in no longer names upgrading "
        "production's Extractor as the remedy"
    )


def test_the_widened_stall_window_is_guarded_on_presence_not_on_a_version() -> None:
    """The poll widens its stall window when ``chunks_done`` is *observed*
    absent from the body. That guard is correct at any floor and must not be
    re-expressed as a version comparison, which would silently stop firing
    against a build at the floor that does not honour the member."""

    source = read(REPO_ROOT / "skills" / "clone" / "scripts" / "poll_extraction.py")
    assert "chunks_done_absent" in source
    assert not re.search(r"api_version|API version \d", source), (
        "poll_extraction.py reads an API version — the widened stall window is "
        "guarded on the member's observed absence, never on the version number"
    )


def test_the_disclosure_fallback_is_guarded_on_presence_not_on_a_version() -> None:
    """`discovery.py` omits the ``disclosure`` key when the server sent none, and
    that omission is the whole signal. ``disclosure`` is an honours name, so a
    build at the floor may still not send it: the fallback stays reachable."""

    source = read(REPO_ROOT / "skills" / "clone" / "scripts" / "discovery.py")
    assert 'record["disclosure"] = disclosure' in source
    assert "The omission is the payload" in source, (
        "discovery.py no longer states that omitting the key is how the "
        "classifier tells a disclosure-capable server from one without it"
    )


@pytest.mark.parametrize(
    "path",
    (
        REPO_ROOT / "docs" / "spec.md",
        REPO_ROOT / "docs" / "adr" / "0023-a-defines-disclosure-is-read-from-the-protocol-member.md",
        REPO_ROOT / "GLOSSARY.md",
    ),
    ids=lambda p: p.name,
)
def test_no_surface_credits_the_floor_for_the_disclosure_fallback(path: Path) -> None:
    """The by-value fallback's guard is member presence, never the floor. A
    surface that credits the floor invites deleting a live defence the next time
    the floor moves — which is exactly what nearly happened at this raise."""

    text = read(path)
    offenders = re.findall(
        r"because its API-version floor is \d"
        r"|API-version floor is ever raised"
        r"|dead code the day the floor rises",
        text,
    )
    assert not offenders, (
        f"{path.relative_to(REPO_ROOT)} credits the API-version floor for the "
        f"define-disclosure fallback: {offenders}"
    )
    assert re.search(r"`disclosure`[^.]{0,120}`honours`|omission is the payload", text), (
        f"{path.relative_to(REPO_ROOT)} states the by-value fallback without "
        "naming what actually guards it — the absent member, whose name is on "
        "the honours list and so is not promised by any API version"
    )
