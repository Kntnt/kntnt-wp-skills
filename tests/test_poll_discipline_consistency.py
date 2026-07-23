"""Poll-discipline consistency test — issue #34 (ADR-0018), refined by #41.

The first live smoke of the Extractor cutover read two zero-byte status-poll
responses as ``FAILED`` while the job completed fine and was downloadable
minutes later — one transport timeout was enough to abort the run. The fix
(ADR-0018) pins one canonical poll discipline across every poll loop: a steady
15 s cadence, a generous 120 s per-request timeout, retry with backoff on a
transport failure, stall detection by ``progress`` rather than by a single
timeout, and an explicit overall wall-clock budget per loop.

The second live smoke (2026-07-23) then proved the original 404-is-terminal
rule wrong in the field: ``GET /extractions/{id}`` returned a spurious `404`
twice mid-job while the job was alive and progressing (kntnt-extractor#20,
a server-side non-atomic ``job.json`` rewrite race). Issue #41 refines the
discipline: a `404` is terminal only when *confirmed vanished* — re-polled
after a short backoff and cross-checked against the `GET /extractions`
listing — never on a single 404.

This suite is the anti-drift binding. It holds the three surfaces that spell
the discipline out in full — ``skills/clone/SKILL.md`` §5,
``skills/pull/SKILL.md`` §5, and ``agents/extract-transfer.md`` — to the same
pinned literals and the same confirmed-vanished wording; holds
``agents/discovery-classify.md`` to the bootstrap loop's 15-minute budget and
its compact confirmed-vanished reference; and asserts no live surface reverts
to the bare "up to an explicit maximum wait" poll sentence, nor to an
unqualified "a vanished job (`404`)" that treats a single 404 as terminal.
The anchors are the literal prose values, never a snippet of this suite's own
text, so a faithful rewrite stays green while a regression (a drifted
literal, or the retry-within-budget rule dropped) reddens.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

CLONE_SKILL: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
PULL_SKILL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"
EXTRACT_TRANSFER: Path = REPO_ROOT / "agents" / "extract-transfer.md"
DISCOVERY_CLASSIFY: Path = REPO_ROOT / "agents" / "discovery-classify.md"

# The three surfaces that state the main-extraction poll discipline in full.
# Each must carry every pinned literal, so a subagent (or the orchestrator)
# loading any one of them alone still gets the whole rule set.
FULL_DISCIPLINE_DOCS: tuple[tuple[str, Path], ...] = (
    ("clone SKILL.md", CLONE_SKILL),
    ("pull SKILL.md", PULL_SKILL),
    ("extract-transfer agent", EXTRACT_TRANSFER),
)

# The pinned literals of the discipline, as they appear in prose. The cadence
# and timeout anchor on their exact phrasing; the stall window and the main
# budget anchor on the values themselves.
PINNED_LITERALS: tuple[tuple[str, str], ...] = (
    ("15 s poll cadence", r"every 15 s"),
    ("120 s per-request timeout", r"120 s per-request timeout"),
    ("10-minute stall window", r"10-minute stall window"),
    ("3600 s main budget", r"\b3600\b"),
)

# The live surfaces an agent actually loads or is pointed at — the skills,
# the subagent definitions, the spec, the notes, and the manpages. The ADRs
# are historical records and legitimately describe the old
# one-timeout-is-failure behaviour, so they are out of scope here.
LIVE_SURFACES: tuple[Path, ...] = (
    *sorted((REPO_ROOT / "skills").glob("*/SKILL.md")),
    *sorted((REPO_ROOT / "agents").glob("*.md")),
    *sorted((REPO_ROOT / "docs" / "man").glob("*.md")),
    REPO_ROOT / "docs" / "spec.md",
    REPO_ROOT / "docs" / "implementation-notes.md",
)

# The confirmed-vanished rule (issue #41), stated identically in full in every
# surface that spells the main-extraction poll discipline out in full. A `404`
# alone is a transport-class blip, never terminal on its own.
CONFIRMED_VANISHED_FULL: str = (
    "a confirmed-vanished job (a `404` that, after a ~5 s backoff, is "
    "re-polled and also `404`s and the id is absent from `GET /extractions` "
    "— a single `404` is logged and polling continues within budget)"
)

# The compact form of the same rule, carried by the bootstrap loop's
# reference in ``agents/discovery-classify.md`` alongside its own budget.
CONFIRMED_VANISHED_COMPACT: str = (
    "a confirmed-vanished job (`404`, re-confirmed via `GET /extractions` "
    "and a second poll)"
)


@pytest.mark.parametrize("doc_name, path", FULL_DISCIPLINE_DOCS)
@pytest.mark.parametrize("literal_name, pattern", PINNED_LITERALS)
def test_poll_discipline_literals_are_pinned(
    doc_name: str, path: Path, literal_name: str, pattern: str
) -> None:
    """Every surface that spells out the main-extraction poll discipline
    carries the same pinned literals, so the three poll sites can never
    drift apart on cadence, timeout, stall window, or budget."""

    text = path.read_text(encoding="utf-8")
    assert re.search(pattern, text), (
        f"{doc_name} is missing the {literal_name} literal /{pattern}/ — "
        "the poll discipline's pinned values must appear in every surface "
        "that states the loop (issue #34, ADR-0018)"
    )


def test_bootstrap_poll_carries_its_fifteen_minute_budget() -> None:
    """The discovery-classify agent states the bootstrap poll's own overall
    budget — 15 minutes — alongside its compact reference to the standard
    discipline, so the subagent that runs the bootstrap loop knows its
    wall-clock bound without loading any other file."""

    text = DISCOVERY_CLASSIFY.read_text(encoding="utf-8")
    assert re.search(r"15-minute", text), (
        "discovery-classify agent is missing the bootstrap poll's 15-minute "
        "overall budget (issue #34, ADR-0018)"
    )


@pytest.mark.parametrize("doc_name, path", FULL_DISCIPLINE_DOCS)
def test_confirmed_vanished_rule_is_pinned_in_full(
    doc_name: str, path: Path
) -> None:
    """Every surface that spells out the main-extraction poll discipline in
    full carries the identical confirmed-vanished wording — a `404` is
    terminal only after a re-poll and a `GET /extractions` cross-check both
    confirm the job is gone, never on a single 404 (issue #41, ADR-0018)."""

    text = path.read_text(encoding="utf-8")
    assert CONFIRMED_VANISHED_FULL in text, (
        f"{doc_name} is missing the confirmed-vanished rule in its pinned "
        "full form — a single 404 must never be read as terminal "
        "(issue #41, ADR-0018)"
    )


def test_bootstrap_poll_carries_the_confirmed_vanished_rule() -> None:
    """The discovery-classify agent's compact poll-discipline reference
    carries the confirmed-vanished rule too, in both places it restates the
    bootstrap loop's failure conditions (issue #41, ADR-0018)."""

    text = DISCOVERY_CLASSIFY.read_text(encoding="utf-8")
    assert text.count(CONFIRMED_VANISHED_COMPACT) >= 2, (
        "discovery-classify agent is missing the compact confirmed-vanished "
        "rule in both of its failure-condition statements (issue #41, "
        "ADR-0018)"
    )


@pytest.mark.parametrize(
    "path", LIVE_SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_no_unqualified_vanished_job_sentence_survives(path: Path) -> None:
    """No live surface still carries the bare, unqualified "a vanished job
    (`404`)" sentence — the pre-#41 wording under which a single spurious
    404 was read as terminal. The confirmed-vanished rule that replaced it
    requires a re-poll and a listing cross-check before a 404 is terminal."""

    text = path.read_text(encoding="utf-8")
    assert "a vanished job (`404`)" not in text, (
        f"{path.relative_to(REPO_ROOT)} still carries the bare, unqualified "
        "'a vanished job (`404`)' sentence — replaced by the "
        "confirmed-vanished rule (issue #41, ADR-0018)"
    )


@pytest.mark.parametrize(
    "path", LIVE_SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_no_bare_maximum_wait_poll_sentence_survives(path: Path) -> None:
    """No live surface still carries the bare "up to an explicit maximum
    wait" poll sentence — the pre-#34 wording under which a single transport
    timeout was read as failure. The discipline that replaced it retries
    within budget and fails only on a terminal state or a no-progress
    stall."""

    text = path.read_text(encoding="utf-8")
    assert "up to an explicit maximum wait" not in text, (
        f"{path.relative_to(REPO_ROOT)} still carries the bare "
        "'up to an explicit maximum wait' poll sentence — replaced by the "
        "retry-within-budget discipline (issue #34, ADR-0018)"
    )
