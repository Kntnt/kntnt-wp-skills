# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Locked-consume retry consistency test — issue #54, plan 008.

The Extractor makes `POST /extractions/{id}/consume` take the same per-job tick
lock a live tick holds, and answers **`409 kntnt_extractor_locked`** when it
cannot take it, with "the caller simply retries" as the intended handling. This
client had no handling for that code at all, and its own rule that a job never
consumed on the happy path is always `FAILED` turned a narrow lock contention
into a failed verdict on a finished multi-hour extraction. Observed live during
this project's production runs, not hypothesised.

The data was never at risk — the download and the unseal both precede the
consume, so a complete local copy already exists by the time the refusal lands.
What was lost was the run's verdict.

This suite is the anti-drift binding for the fix, in the same spirit as
``test_preflight_probe_consistency.py``:

1. Every surface that describes the consume names the refusal code and states
   the **bounded** retry, with the bound written down rather than left to the
   agent — an unbounded "retry until it works" against a live client site is
   exactly the nondeterminism ``scripts/poll_extraction.py`` exists to remove.
2. The bound is *derived*, not picked (rule R4): the surfaces name the
   Extractor's own ``tick_budget`` as what it is read off.
3. The exhausted case is reportable and reported as complete-but-unconsumed —
   the ``unsealed_consume_locked`` failure phase — so a close-out never tells
   the operator a finished transfer failed.
4. The retry never widens to `429`, a different code with a different meaning
   and a deliberate hard stop, and never leaks into the poll helper, whose
   `GET /extractions/{id}` cannot answer `409` at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

ROLE: Path = REPO_ROOT / "skills" / "clone" / "roles" / "extract-transfer.md"
CLONE_SKILL: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
PULL_SKILL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"

# The refusal's own name on the wire. Pinned as a literal because it is what an
# agent matches on: a paraphrase ("a 409 conflict") is not actionable.
REFUSAL_CODE: str = "kntnt_extractor_locked"

# The failure phase the exhausted retry window reports — the only phase whose
# local copy is complete and usable.
EXHAUSTED_PHASE: str = "unsealed_consume_locked"

# Every surface that describes the consume and must therefore describe its
# refusal. The role is what actually issues the call; the two SKILLs are what an
# operator reads; the spec is the source of truth the build is checked against.
CONSUME_SURFACES: tuple[tuple[str, Path], ...] = (
    ("extract-transfer role", ROLE),
    ("clone SKILL.md", CLONE_SKILL),
    ("pull SKILL.md", PULL_SKILL),
    ("spec.md", SPEC),
)

# The surfaces that must carry the bound itself, in numbers. The spec states the
# behaviour; these three state the schedule an executor follows.
BOUND_SURFACES: tuple[tuple[str, Path], ...] = (
    ("extract-transfer role", ROLE),
    ("clone SKILL.md", CLONE_SKILL),
    ("pull SKILL.md", PULL_SKILL),
)

# The bound's pinned elements: how many retries, how far apart, and the
# Extractor-side constant the number is read off — the derivation rule R4 asks
# for, so a later reader can check the arithmetic instead of trusting a
# number somebody liked.
BOUND_ANCHORS: tuple[tuple[str, str], ...] = (
    ("the retry count", r"five times"),
    ("the retry interval", r"10 seconds apart"),
    ("the Extractor-side constant it is derived from", r"`tick_budget`"),
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _locked_lines(path: Path) -> list[str]:
    """Every line of a surface that mentions the refusal code, whitespace-
    normalised — the prose a reader of that surface actually gets about it."""

    return [
        " ".join(line.split())
        for line in _text(path).splitlines()
        if REFUSAL_CODE in line
    ]


@pytest.mark.parametrize("label,path", CONSUME_SURFACES)
def test_surface_names_the_refusal_code(label: str, path: Path) -> None:
    """Each surface names `409 kntnt_extractor_locked` literally. The refusal is
    loud, named and detectable; a surface that does not name it leaves whoever
    reads it with the old rule — an unconsumed job is always `FAILED` — and no
    way to tell a lock contention from a real error."""

    assert REFUSAL_CODE in _text(path), (
        f"{label} never names the {REFUSAL_CODE!r} refusal, so a reader of it "
        "still treats a locked consume as a failed run"
    )


@pytest.mark.parametrize("label,path", BOUND_SURFACES)
@pytest.mark.parametrize("anchor,pattern", BOUND_ANCHORS)
def test_surface_states_the_bound_and_where_it_comes_from(
    label: str, path: Path, anchor: str, pattern: str
) -> None:
    """The retry is bounded, the bound is written in the file rather than left
    to the agent, and the file says what the number is derived from.

    Both halves matter. Without the numbers an executor invents its own
    schedule against a live client site; without the derivation the numbers are
    a preference, which rule R4 exists to stop."""

    assert re.search(pattern, _text(path)), (
        f"{label} does not state {anchor} of the locked-consume retry"
    )


@pytest.mark.parametrize("label,path", BOUND_SURFACES)
def test_surface_states_the_first_refusal_is_not_the_failure(
    label: str, path: Path
) -> None:
    """What fails is the exhausted window, never the first refusal — the whole
    point of the fix. Pinned near the refusal itself so a rewrite that keeps the
    code but drops the retry reddens here."""

    joined = " ".join(_locked_lines(path)).lower()
    assert "retr" in joined, (
        f"{label} mentions {REFUSAL_CODE} without saying the call is retried"
    )
    assert "not a failure" in joined or "is not a failure" in joined, (
        f"{label} does not say a single {REFUSAL_CODE} refusal is not a failure"
    )


@pytest.mark.parametrize("label,path", CONSUME_SURFACES)
def test_surface_states_the_local_copy_survives_an_exhausted_window(
    label: str, path: Path
) -> None:
    """The bound this fix accepts has a cost, and every surface must state what
    it is: an exhausted window loses the verdict, never the data. The download
    and the unseal both precede the consume, so the local copy is complete."""

    joined = " ".join(_locked_lines(path)).lower()
    assert re.search(r"local copy|already exists|complete", joined), (
        f"{label} never says the local copy is complete when the retry window "
        "is exhausted — the one fact that keeps a close-out from reporting a "
        "finished transfer as a failed one"
    )


def test_the_role_reports_the_exhausted_window_as_its_own_failure_phase() -> None:
    """The exhausted case is reportable: a fourth `failure_phase` beside the
    three the close-out already switches on, so the orchestrator picks the
    matching case directly instead of re-deriving it from `job_state` and
    `consumed`."""

    body = _text(ROLE)
    assert EXHAUSTED_PHASE in body, (
        f"the extract-transfer role never reports {EXHAUSTED_PHASE!r}, so an "
        "exhausted retry window maps to no close-out case at all"
    )

    phase_line = next(
        (line for line in body.splitlines() if "`failure_phase`" in line), None
    )
    assert phase_line is not None, "the role's evidence block lost `failure_phase`"
    for phase in (
        "never_ready",
        "downloaded_unseal_failed",
        "ready_download_failed",
        EXHAUSTED_PHASE,
    ):
        assert phase in phase_line, (
            f"the role's `failure_phase` enumeration omits {phase!r}"
        )

    assert "`consumed`" in body, (
        "the role's evidence block lost `consumed` — the phase and the flag "
        "carry different facts and both are wanted"
    )


@pytest.mark.parametrize("label,path", (("clone", CLONE_SKILL), ("pull", PULL_SKILL)))
def test_skill_close_out_carries_the_locked_case(label: str, path: Path) -> None:
    """Each SKILL's *Closing out a failed phase* subsection has a case for the
    new phase. A four-valued field switched on by a three-case list is a hole:
    the orchestrator would fall through to the cancel or the consume case, on a
    job whose container is already unsealed on this machine."""

    text = _text(path)
    _, sep, close_out = text.partition("### Closing out a failed phase")
    assert sep, f"{label} SKILL.md has no *Closing out a failed phase* subsection"
    assert EXHAUSTED_PHASE in close_out, (
        f"{label} SKILL.md's close-out has no case for {EXHAUSTED_PHASE!r}"
    )


def test_the_two_skills_word_the_locked_consume_identically() -> None:
    """`clone` and `pull` state this in the same words. The two documents are
    read alone and maintained together; a divergence here is how one operator
    learns a rule the other never sees."""

    assert _locked_lines(CLONE_SKILL) == _locked_lines(PULL_SKILL), (
        "the clone and pull SKILLs have drifted apart on the locked consume"
    )


def test_the_retry_never_widens_to_the_one_active_job_refusal() -> None:
    """`429` is a different code with a different meaning — a job is already
    active — and an existing, deliberate hard stop. The retry must not reach it,
    and the hard stop must survive this change."""

    body = _text(ROLE)
    assert re.search(r"`429`[^.]*hard stop", body), (
        "the extract-transfer role no longer hard-stops on `429`"
    )
    for line in _locked_lines(ROLE):
        assert "429" not in line or "never retried" in line or "hard stop" in line, (
            f"the role's locked-consume prose drags `429` into the retry: {line!r}"
        )


def test_the_poll_helper_stays_out_of_it() -> None:
    """`scripts/poll_extraction.py` polls `GET /extractions/{id}`, which does not
    take the lock and cannot answer `409`. Retry logic there would be dead code
    guarding a route that never refuses — and a second, competing retry regime
    in the one place the discipline's literals are supposed to live."""

    helper = REPO_ROOT / "skills" / "clone" / "scripts" / "poll_extraction.py"
    assert helper.is_file(), "the poll helper moved; this guard needs its new path"
    assert REFUSAL_CODE not in helper.read_text(encoding="utf-8"), (
        "scripts/poll_extraction.py grew handling for a refusal its own route "
        "cannot return"
    )
