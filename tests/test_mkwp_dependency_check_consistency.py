"""mkwp dependency-check consistency test — bind `mkwp`'s §1 to the LOCAL
portion of `clone`/`pull`'s own dependency step (issue #23 x #22 union review
finding).

Issue #23's own body promised "`/mkwp` runs the local portion of this check
before scaffolding", but `skills/mkwp/SKILL.md` shipped a "Known gap"
paragraph instead of actually running it — the version guard alone proves
`mkwp` itself is present and new enough, but never checks `ddev` on `PATH`,
whether its container backend actually responds, or the other required CLI
tools, even though the scaffold step (§4) drives `mkwp`'s own `ddev config`
and first `ddev start` and would otherwise fail silently deep inside them
against a stopped backend.

This suite holds `skills/mkwp/SKILL.md`'s §1 to actually running that local
check — never merely describing it as a known gap — using the same
formulations (`ddev version`, the Docker/Colima liveness probe, the required
CLI tool roster) `clone`'s own dependency step already uses, so the two never
silently drift into two different definitions of "the local portion."
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
MKWP_SKILL: Path = REPO_ROOT / "skills" / "mkwp" / "SKILL.md"
CLONE_SKILL: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"

# The required CLI tool roster clone's own dependency step names — mkwp's own
# local check must name the same set, never a divergent one.
REQUIRED_TOOLS: tuple[str, ...] = ("uv", "jq", "curl", "sha256sum", "openssl")


def _section(text: str, heading: str) -> str:
    """Return the body of the first ``## <heading>`` section in ``text``, up
    to (not including) the next ``## `` heading."""

    start = text.index(heading)
    rest = text[start + len(heading) :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def test_mkwp_skill_no_longer_ships_the_known_gap_paragraph() -> None:
    """The "Known gap" paragraph — a description of the missing check rather
    than the check itself — must be gone; issue #23's own body promised the
    local portion actually runs before scaffolding."""

    text = MKWP_SKILL.read_text(encoding="utf-8")

    assert "Known gap" not in text
    assert "known scope gap" not in text.lower()


def test_mkwp_section_1_checks_ddev_and_its_container_backend() -> None:
    """mkwp's §1 must itself verify `ddev` is on PATH and its container
    backend actually responds — the same `ddev version` plus Docker/Colima
    liveness probe formulation clone's own dependency step uses (its §1) —
    not merely describe the omission."""

    text = MKWP_SKILL.read_text(encoding="utf-8")
    section = _section(text, "## 1.")

    assert "ddev version" in section
    assert "docker info" in section.lower()
    assert "colima" in section.lower()


def test_mkwp_section_1_checks_the_same_required_cli_tools_clone_checks() -> None:
    """mkwp's §1 must name the same required-CLI-tool roster clone's own
    dependency step checks, so the two never silently define "local
    dependencies" differently."""

    mkwp_section = _section(MKWP_SKILL.read_text(encoding="utf-8"), "## 1.")
    clone_section = _section(CLONE_SKILL.read_text(encoding="utf-8"), "## 1.")

    for tool in REQUIRED_TOOLS:
        assert f"`{tool}`" in mkwp_section, f"mkwp §1 never names the required tool {tool!r}"
        assert f"`{tool}`" in clone_section, f"clone §1 never names the required tool {tool!r} (test's own roster is stale)"


def test_mkwp_section_1_still_runs_the_existing_mkwp_version_guard() -> None:
    """The pre-existing `mkwp`-itself version guard (`scripts/mkwp_guard.py`)
    must survive the rewrite — the new local-dependency checks are additive,
    never a replacement for the guard `clone`'s own dependency step also
    reads."""

    section = _section(MKWP_SKILL.read_text(encoding="utf-8"), "## 1.")

    assert "mkwp_guard.py" in section
    assert "--dirname" in section or "helpOutput" in section


def test_mkwp_section_1_never_claims_a_production_side_check() -> None:
    """Production-side checks (the Novamira ability inventory, the
    liveness/exec probes) do not apply to `mkwp` — it never touches
    production — so §1 must not claim to run them."""

    section = _section(MKWP_SKILL.read_text(encoding="utf-8"), "## 1.")

    assert "discover-abilities" not in section
    assert "execute-php" not in section
