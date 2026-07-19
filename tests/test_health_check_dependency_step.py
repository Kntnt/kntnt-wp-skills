"""Dependency-check consistency test — issue #23.

The shared health check used to start with "locate the connected Novamira
server" and left every local dependency (``ddev``, `mkwp`, the required CLI
tools) and the production ability inventory (`discover-abilities`) entirely
unchecked; `clone` additionally carried its own ad hoc `mkwp` version check as
a *separate*, late step (its old step 7) instead of sharing the one guard the
`mkwp` skill already reads (`scripts/mkwp_guard.py`).

This suite is the anti-drift binding for the fix: both `SKILL.md` files and
`docs/spec.md` must prescribe a **dependency step that runs first** — local
checks before any production call, then the target server plus its ability
inventory — carrying the remediation contract (stop at the first missing
dependency, name what to install and the re-run command, never install
anything itself). `clone`'s local checks alone fold in the shared `mkwp`
guard; `pull` never mentions `mkwp` at all, since it never scaffolds.

Anchors are the literal step prose, never a snippet of this suite's own text,
matching the convention set by `test_health_check_sweep_order.py` and the
other orchestration-consistency suites.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

CLONE_SKILL: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
PULL_SKILL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"
MKWP_SKILL: Path = REPO_ROOT / "skills" / "mkwp" / "SKILL.md"
MKWP_GUARD: Path = REPO_ROOT / "scripts" / "mkwp_guard.py"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"

SKILL_FILES: dict[str, Path] = {"clone": CLONE_SKILL, "pull": PULL_SKILL}

# The anchor marking the start of the new dependency step in each document —
# the two SKILL.md files spell it out as a bold list-item heading, the spec
# uses shorter narrative prose for the same step.
DEPENDENCY_ANCHOR: dict[str, str] = {
    "clone SKILL.md": r"\*\*Verify dependencies\.\*\*",
    "pull SKILL.md": r"\*\*Verify dependencies\.\*\*",
    "spec.md": r"Verify every local and production dependency",
}

# "Prove the channel is live" is the literal phrase every one of these three
# documents already uses for what was step 1 (clone/pull SKILL.md) or step 2
# (spec.md) — the first item downstream of the new dependency step, so its
# position is the ordering anchor.
LIVE_ANCHOR = r"Prove the channel is live"

DOCS_UNDER_TEST: tuple[tuple[str, Path], ...] = (
    ("clone SKILL.md", CLONE_SKILL),
    ("pull SKILL.md", PULL_SKILL),
    ("spec.md", SPEC),
)

# Local dependency terms every document's dependency step must name — the
# tools this run needs on ``PATH`` regardless of which skill is running.
REQUIRED_LOCAL_TOOL_TERMS: tuple[str, ...] = (
    "ddev",
    "uv",
    "jq",
    "curl",
    "shasum",
    "sha256sum",
    "openssl",
)

# The five Novamira abilities the production side must inventory via
# discover-abilities, plus the call itself.
REQUIRED_ABILITY_TERMS: tuple[str, ...] = (
    "discover-abilities",
    "execute-php",
    "run-wp-cli",
    "read-file",
    "write-file",
    "list-directory",
)


def _pos(text: str, pattern: str, label: str, doc_name: str, start: int = 0) -> int:
    """First match position of a case-insensitive ``pattern`` in ``text`` at
    or after ``start``, failing loudly with the missing anchor when it is
    absent."""

    match = re.search(pattern, text[start:], re.IGNORECASE)
    assert match is not None, f"{doc_name} is missing the {label} anchor /{pattern}/"
    return start + match.start()


def _dependency_window(doc_name: str, path: Path) -> str:
    """The text window starting at the dependency step's own anchor and
    ending exactly at the next step's anchor ("Prove the channel is live"),
    so the window can never bleed into that step's own content — an edit
    that dropped a term from the dependency step could otherwise keep this
    suite green only because the term still appears further down the page."""

    text = path.read_text(encoding="utf-8")
    start = _pos(text, DEPENDENCY_ANCHOR[doc_name], "dependency step", doc_name)
    end = _pos(text, LIVE_ANCHOR, "prove-channel-is-live", doc_name, start=start)
    return text[start:end]


@pytest.mark.parametrize("doc_name, path", DOCS_UNDER_TEST)
def test_dependency_step_precedes_prove_channel_is_live(
    doc_name: str, path: Path
) -> None:
    """The dependency step is the first item in the health check — it
    precedes what used to be the very first step, proving the channel is
    live — in every document that states the health-check order."""

    text = path.read_text(encoding="utf-8")
    dependency_pos = _pos(
        text, DEPENDENCY_ANCHOR[doc_name], "dependency step", doc_name
    )
    live_pos = _pos(text, LIVE_ANCHOR, "prove-channel-is-live", doc_name)
    assert dependency_pos < live_pos, (
        f"{doc_name} does not order the dependency step before proving the "
        "channel is live — it must run first, before any production call"
    )


@pytest.mark.parametrize("doc_name, path", DOCS_UNDER_TEST)
def test_dependency_step_locates_the_target_server_within_itself(
    doc_name: str, path: Path
) -> None:
    """Locating the connected Novamira server for the target production URL
    is folded into the dependency step itself, not left behind as a separate,
    disconnected step — the ability inventory below needs to know which
    server to call ``discover-abilities`` against."""

    window = _dependency_window(doc_name, path)
    assert re.search(r"novamira-\*|several.*novamira", window, re.IGNORECASE), (
        f"{doc_name}'s dependency step never mentions locating the target "
        "site's connected server among several possible `novamira-*` ones"
    )


@pytest.mark.parametrize("doc_name, path", DOCS_UNDER_TEST)
def test_dependency_step_lists_required_local_tools(doc_name: str, path: Path) -> None:
    """Every required local CLI tool is named inside the dependency step's own
    text — not merely somewhere in the document — so the step's own prose is
    the complete, authoritative checklist."""

    window = _dependency_window(doc_name, path).lower()
    for term in REQUIRED_LOCAL_TOOL_TERMS:
        assert term in window, (
            f"{doc_name}'s dependency step never names the required local tool {term!r}"
        )


@pytest.mark.parametrize("doc_name, path", DOCS_UNDER_TEST)
def test_dependency_step_lists_required_production_abilities(
    doc_name: str, path: Path
) -> None:
    """Every one of the five required Novamira abilities, plus the
    `discover-abilities` call that inventories them, is named inside the
    dependency step's own text."""

    window = _dependency_window(doc_name, path).lower()
    for term in REQUIRED_ABILITY_TERMS:
        assert term in window, (
            f"{doc_name}'s dependency step never names the required "
            f"production ability term {term!r}"
        )


@pytest.mark.parametrize("doc_name, path", DOCS_UNDER_TEST)
def test_dependency_step_states_the_remediation_contract(
    doc_name: str, path: Path
) -> None:
    """On a missing dependency the step stops early, names a concrete
    per-dependency fix and re-run command, and states the agent never
    installs system software itself — the remediation contract issue #23
    demands, not merely a bare "abort" with no guidance."""

    window = _dependency_window(doc_name, path).lower()
    assert re.search(r"never install", window), (
        f"{doc_name}'s dependency step never states that the agent itself "
        "never installs system software"
    )
    assert "re-run" in window, (
        f"{doc_name}'s dependency step never names the re-run command as "
        "part of its remediation message"
    )
    assert re.search(r"gate", window), (
        f"{doc_name}'s dependency step never offers a safely agent-runnable "
        "fix behind its own accept-or-override gate"
    )


@pytest.mark.parametrize("doc_name, path", DOCS_UNDER_TEST)
def test_dependency_step_never_auto_accepts_the_fix_gate_under_yes(
    doc_name: str, path: Path
) -> None:
    """The agent-runnable-fix gate is an ordinary accept-or-override gate,
    and `--yes` accepts every ordinary gate unattended — but installing
    system software with no operator present is exactly the consent this
    step's own "rather than assuming consent" clause forbids. The dependency
    step must pin this explicitly: under `--yes` the fix gate is never
    auto-accepted, and the run aborts with the remediation message instead of
    running the fix."""

    window = _dependency_window(doc_name, path).lower()
    assert "--yes" in window, (
        f"{doc_name}'s dependency step never mentions `--yes` when pinning "
        "the agent-runnable-fix gate's behaviour"
    )
    assert re.search(r"never (run|install|auto-accept)|not auto-accepted", window), (
        f"{doc_name}'s dependency step never states that `--yes` must not "
        "silently run the agent-runnable fix"
    )


def test_clone_dependency_step_checks_mkwp_via_the_shared_guard() -> None:
    """`clone` alone needs `mkwp` (it scaffolds); its dependency step checks
    it via the shared, single-source-of-truth guard script rather than
    re-deriving the `--dirname` check ad hoc."""

    window = _dependency_window("clone SKILL.md", CLONE_SKILL).lower()
    assert "mkwp_guard.py" in window, (
        "clone SKILL.md's dependency step never reads the shared "
        "scripts/mkwp_guard.py guard"
    )
    assert "1.5.0" in window, (
        "clone SKILL.md's dependency step never states the mkwp floor version"
    )


def test_pull_dependency_step_never_mentions_mkwp() -> None:
    """`pull` never scaffolds, so its dependency step must never check
    `mkwp` — a copy-pasted clone-only check here would be a false
    dependency that could block a pull for no reason."""

    window = _dependency_window("pull SKILL.md", PULL_SKILL).lower()
    assert "mkwp" not in window, (
        "pull SKILL.md's dependency step mentions mkwp, which pull never uses"
    )


def test_clone_health_check_no_longer_carries_a_separate_mkwp_step() -> None:
    """The old ad hoc step-7 mkwp check is folded into the dependency step,
    not left behind as a second, duplicate mkwp check further down the same
    health check."""

    text = CLONE_SKILL.read_text(encoding="utf-8")
    health_check_start = text.index("## 1. Health check")
    health_check_end = text.index("\n## 2. Discovery")
    section = text[health_check_start:health_check_end]

    assert "Verify the mkwp capability" not in section, (
        "clone SKILL.md's health check still carries the old ad hoc "
        "'Verify the mkwp capability' step alongside the new dependency step"
    )
    assert section.lower().count("mkwp_guard.py") == 1, (
        "clone SKILL.md's health check references scripts/mkwp_guard.py "
        f"{section.lower().count('mkwp_guard.py')} times — it must be read "
        "exactly once, from the dependency step, never duplicated"
    )


def test_old_locate_the_server_heading_is_not_left_as_its_own_step() -> None:
    """`clone` and `pull` both used to carry a standalone `**Locate the
    server.**` step; it is folded into the new dependency step's own
    production sub-bullet, not merely relabelled and left as a second,
    now-redundant step alongside it."""

    for name, path in SKILL_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\d+\.\s+\*\*Locate the server\.\*\*", text), (
            f"{name} SKILL.md still carries a standalone 'Locate the server' "
            "step distinct from the new dependency step"
        )


def test_mkwp_skill_cross_references_the_landed_shared_health_check() -> None:
    """The `mkwp` skill's own version-guard prose no longer hedges that the
    shared dependency health check "has not landed yet" (issue #23) — it has
    — and points at the health check's actual dependency step, not the stale
    `§1.7` step number the fold-in removed."""

    text = MKWP_SKILL.read_text(encoding="utf-8")
    assert "once it lands" not in text.lower(), (
        "skills/mkwp/SKILL.md still hedges that the shared dependency health "
        "check has not landed"
    )
    assert "§1.7" not in text, (
        "skills/mkwp/SKILL.md still cites the old, now-folded §1.7 mkwp step"
    )
    assert re.search(r"clone.{0,80}health check", text, re.IGNORECASE), (
        "skills/mkwp/SKILL.md no longer cross-references clone's own health "
        "check for the shared mkwp guard"
    )


def test_spec_clone_bookends_no_longer_duplicates_the_mkwp_version_check() -> None:
    """`docs/spec.md`'s *Clone bookends* section used to carry its own full
    description of the mkwp version check; now that the health check's
    dependency step owns it, *Clone bookends* only cross-references it,
    rather than maintaining two descriptions of the same guard."""

    text = SPEC.read_text(encoding="utf-8")
    bookends_start = text.index("### Clone bookends")
    bookends_end = text.index("### Pull bookends")
    section = text[bookends_start:bookends_end]

    assert "supports `--dirname`" not in section, (
        "docs/spec.md's Clone bookends section still carries its own full "
        "mkwp version-check description instead of cross-referencing the "
        "health check's dependency step"
    )
    assert re.search(r"health check", section, re.IGNORECASE), (
        "docs/spec.md's Clone bookends section never cross-references the "
        "health check for the mkwp version guard"
    )


def test_mkwp_guard_module_no_longer_hedges_that_the_health_check_has_not_landed() -> None:
    """Cross-issue #22 x #23: `scripts/mkwp_guard.py`'s own module docstring
    described `clone`'s dependency health-check step as a caller that would
    read this guard "once it lands" — issue #23 has since landed that step,
    and its commit e1d9def fixed the identical hedge in `skills/mkwp/
    SKILL.md`, but left this one behind in the shared guard both callers
    (`clone` SKILL.md §1 and `mkwp` SKILL.md §1) now point operators at as
    the single source of truth for the guard."""

    text = MKWP_GUARD.read_text(encoding="utf-8")
    assert "once it lands" not in text.lower(), (
        "scripts/mkwp_guard.py still hedges that the shared dependency "
        "health check has not landed"
    )
    assert re.search(r"clone.{0,80}health.check", text, re.IGNORECASE), (
        "scripts/mkwp_guard.py no longer cross-references clone's own "
        "dependency health-check step as a caller"
    )
