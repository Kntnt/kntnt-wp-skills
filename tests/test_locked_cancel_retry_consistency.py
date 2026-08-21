# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Locked-cancel retry consistency test — issue #68.

`tests/test_locked_consume_retry_consistency.py` is this suite's sibling and its
model. The Extractor takes the **same** per-job tick lock in its `DELETE`
handler that it takes in the consume handler, and refuses with the same
**`409 kntnt_extractor_locked`** when it cannot take it, with the same recorded
intent — "the caller simply retries". #54 taught the consume that retry and
deliberately left the cancel out, naming it a follow-up rather than an
oversight. This is that follow-up: the close-out's own case-1 cancel now retries
on the consume's bounded schedule.

The stakes are not the consume's. Case 1 is entered on a job that has *not*
reached `ready`, so a refused cancel leaves that job's tick running — and the
job may go on to complete and publish a sealed artifact on the live client site,
served until its TTL. That is the exposure window ADR-0022 exists to close,
reached through the door the locked-consume amendment left open. No data is lost
on either side of the refusal.

The derivation is copied onto a route whose premise is weaker, and the surfaces
have to say so rather than borrow the consume's confidence: the consume only
ever reaches a job already gone `ready`, which races a tick in a narrow window,
while the cancel reaches `queued` and `running` jobs whose ticks keep retaking
the lock. Six bounded attempts are a bound on the attempt, never a guarantee of
the cancel.

Like its sibling, every assertion here is a regex over Markdown. It binds the
*prose* both orchestrators read, never a behaviour, so a faithful rewrite stays
green while a regression — the retry dropped, the bound unstated or picked
rather than derived, an exhausted window turned back into a run-ending failure,
the two SKILLs drifting apart — reddens.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

CLONE_SKILL: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
PULL_SKILL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
CONTEXT: Path = REPO_ROOT / "CONTEXT.md"
ADR: Path = (
    REPO_ROOT
    / "docs"
    / "adr"
    / "0022-close-the-exposure-window-on-every-failure-path.md"
)

# The refusal's own name on the wire, shared with the consume. Pinned as a
# literal because it is what an agent matches on: a paraphrase ("a 409
# conflict") is not actionable.
REFUSAL_CODE: str = "kntnt_extractor_locked"

# The subsection both SKILLs own the close-out in, and case 1 within it. The
# cancel this suite is about is issued by that one case, so every assertion is
# scoped to it — an anchor satisfied by the consume's own paragraph two sections
# up would otherwise pass a case that says nothing about its refusal.
CLOSE_OUT_HEADING: str = "### Closing out a failed phase"
CASE_ONE_ANCHOR: str = r"1\. \*\*The job never reached `ready`\*\*"
CASE_TWO_ANCHOR: str = r"\n2\. \*\*"

# The two SKILLs that carry case 1. They state it in wording that must stay
# identical — the case names no path and no section number, so there is nothing
# legitimate to differ about between them.
CASE_SKILLS: tuple[tuple[str, Path], ...] = (
    ("clone SKILL.md", CLONE_SKILL),
    ("pull SKILL.md", PULL_SKILL),
)

# The bound's pinned elements. They are the consume's own numbers, deliberately:
# one schedule stated twice is a schedule, two schedules are a coin toss. The
# third anchor is the derivation rule R4 asks for — the Extractor-side constant
# the number is read off, so a later reader can check the arithmetic instead of
# trusting a number somebody liked.
BOUND_ANCHORS: tuple[tuple[str, str], ...] = (
    ("the retry count", r"five times"),
    ("the retry interval", r"10 seconds apart"),
    ("the Extractor-side constant it is derived from", r"`tick_budget`"),
)

# What an exhausted window must say. It is a report, never a run-ending failure:
# the close-out is best-effort and a cleanup failure never becomes the headline.
# The sweep's clause is qualified because case 1 is also entered on a `failed`
# job, which is terminal — and §1.3's sweep lists only non-terminal jobs, so for
# that sub-case the TTL is the only reclaimer.
EXHAUSTED_CLAUSES: tuple[tuple[str, str], ...] = (
    ("that the job is still standing", r"still standing"),
    ("the TTL as the reclaimer", r"TTL"),
    (
        "the sweep as a reclaimer only where the job is still non-terminal",
        r"sweep where the job is still non-terminal",
    ),
    ("that the run stops on its original cause", r"original cause"),
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _close_out_section(path: Path, doc_name: str) -> str:
    """Return the *Closing out a failed phase* subsection of a SKILL document.

    Fails loudly when the heading is gone rather than returning an empty string:
    a scoped suite whose section silently vanished would pass while enforcing
    nothing.
    """

    _, heading, after = _text(path).partition(CLOSE_OUT_HEADING)
    assert heading, f"{doc_name} no longer carries a '{CLOSE_OUT_HEADING}' section"
    section, _, _ = after.partition("\n## ")
    return section


def _case_one(path: Path, doc_name: str) -> str:
    """Return close-out case 1 — the cancelling case, and the only one that
    issues the `DELETE` this suite is about."""

    section = _close_out_section(path, doc_name)
    match = re.search(CASE_ONE_ANCHOR, section)
    assert match is not None, (
        f"{doc_name}'s close-out no longer carries case 1 — the cancelling case "
        "this suite is scoped to"
    )
    rest = section[match.start() :]
    end = re.search(CASE_TWO_ANCHOR, rest)
    return rest[: end.start()] if end else rest


@pytest.mark.parametrize("doc_name,path", CASE_SKILLS)
def test_case_one_names_the_refusal_code(doc_name: str, path: Path) -> None:
    """Case 1 names `409 kntnt_extractor_locked` literally. Without it a reader
    of that case has no way to tell a lock contention from a real error, and
    reports a cancel that was merely refused as a failed one."""

    assert REFUSAL_CODE in _case_one(path, doc_name), (
        f"{doc_name}'s close-out case 1 never names the {REFUSAL_CODE!r} "
        "refusal its own `DELETE` can answer"
    )


@pytest.mark.parametrize("anchor,pattern", BOUND_ANCHORS)
@pytest.mark.parametrize("doc_name,path", CASE_SKILLS)
def test_case_one_states_the_bound_and_where_it_comes_from(
    doc_name: str, path: Path, anchor: str, pattern: str
) -> None:
    """The retry is bounded, the bound is written in the file rather than left
    to the agent, and the file says what the number is derived from.

    Both halves matter. Without the numbers an executor invents its own schedule
    against a live client site; without the derivation the numbers are a
    preference, which rule R4 exists to stop."""

    assert re.search(pattern, _case_one(path, doc_name)), (
        f"{doc_name}'s close-out case 1 does not state {anchor} of the "
        "locked-cancel retry"
    )


@pytest.mark.parametrize("doc_name,path", CASE_SKILLS)
def test_case_one_says_the_first_refusal_is_retried_not_failed(
    doc_name: str, path: Path
) -> None:
    """What matters is the exhausted window, never the first refusal. Pinned
    beside the refusal itself so a rewrite that keeps the code but drops the
    retry reddens here."""

    case = _case_one(path, doc_name).lower()
    assert "retr" in case, (
        f"{doc_name}'s case 1 mentions {REFUSAL_CODE} without saying the cancel "
        "is retried"
    )
    assert "not a failure" in case, (
        f"{doc_name}'s case 1 does not say a single {REFUSAL_CODE} refusal is "
        "not a failure"
    )


@pytest.mark.parametrize("doc_name,path", CASE_SKILLS)
def test_case_one_states_the_derivation_is_weaker_here(
    doc_name: str, path: Path
) -> None:
    """The bound is the consume's, but the premise under it is not. The cancel
    reaches `queued` and `running` jobs whose ticks keep retaking the lock,
    where the consume only ever reaches a job already gone `ready`. A surface
    that copies the schedule without copying that caveat sells an executor a
    guarantee the route cannot give."""

    case = _case_one(path, doc_name)
    assert re.search(r"keep retaking|retaking the lock", case), (
        f"{doc_name}'s case 1 borrows the consume's derivation without saying "
        "the premise is weaker at the cancel"
    )


@pytest.mark.parametrize("clause,pattern", EXHAUSTED_CLAUSES)
@pytest.mark.parametrize("doc_name,path", CASE_SKILLS)
def test_case_one_reports_an_exhausted_window_rather_than_failing_on_it(
    doc_name: str, path: Path, clause: str, pattern: str
) -> None:
    """An exhausted window is reported and the run stops on its original cause.
    The close-out is best-effort: a cleanup failure that becomes the headline
    hides the failure the operator actually has to act on."""

    assert re.search(pattern, _case_one(path, doc_name)), (
        f"{doc_name}'s case 1 does not report {clause} when the cancel's retry "
        "window is exhausted"
    )


@pytest.mark.parametrize("doc_name,path", CASE_SKILLS)
def test_the_cancel_retry_never_widens_to_the_one_active_job_refusal(
    doc_name: str, path: Path
) -> None:
    """`429` is a different code with a different meaning — a job is already
    active — and an existing, deliberate hard stop. It is not retried at the
    consume and it is not retried here."""

    case = _case_one(path, doc_name)
    assert re.search(r"`429` is (?:never|not) retried", case), (
        f"{doc_name}'s case 1 does not exclude `429` from the cancel's retry"
    )


def test_the_two_skills_word_case_one_identically() -> None:
    """`clone` and `pull` state case 1 in the same words. The two documents are
    read alone and maintained together; a divergence here is how one operator
    learns a rule the other never sees."""

    assert _case_one(CLONE_SKILL, "clone SKILL.md") == _case_one(
        PULL_SKILL, "pull SKILL.md"
    ), "the clone and pull SKILLs have drifted apart on close-out case 1"


def test_the_bound_is_the_consumes_bound() -> None:
    """One schedule, stated twice. The cancel's numbers are read off the same
    Extractor-side constant as the consume's, so a future change to one that
    leaves the other behind is drift rather than a decision."""

    consume_paragraph = next(
        line
        for line in _text(CLONE_SKILL).splitlines()
        if REFUSAL_CODE in line and "consume refused" in line
    )
    case = _case_one(CLONE_SKILL, "clone SKILL.md")
    for anchor, pattern in BOUND_ANCHORS:
        assert re.search(pattern, consume_paragraph), (
            f"the consume's own paragraph lost {anchor}; the cancel's bound is "
            "pinned to it and this suite can no longer tell them apart"
        )
        assert re.search(pattern, case), (
            f"the cancel's bound and the consume's disagree on {anchor}"
        )


def test_the_adr_no_longer_excludes_the_close_outs_cancel() -> None:
    """ADR-0022's locked-consume amendment said the retry was deliberately not
    widened to `DELETE /extractions/{id}`. That is the sentence this work makes
    false, and a settled decision contradicting the code it governs is worse
    than no record at all."""

    text = _text(ADR)
    assert not re.search(r"Deliberately not widened to `DELETE", text), (
        "ADR-0022 still states the blanket exclusion of the cancel that the "
        "close-out's case 1 now contradicts"
    )


def test_the_adr_records_the_follow_up_was_taken() -> None:
    """The exclusion is replaced by a record, not deleted: the ADR says the
    follow-up was taken, on what schedule, and why the exhausted window is a
    report rather than a failure."""

    text = _text(ADR)
    assert re.search(r"locked[- ]cancel", text, re.IGNORECASE), (
        "ADR-0022 does not record that the locked cancel is now retried"
    )
    for anchor, pattern in BOUND_ANCHORS:
        assert re.search(pattern, text), (
            f"ADR-0022 does not state {anchor} of the retry it now records"
        )


def test_the_adr_keeps_the_sweeps_cancel_excluded() -> None:
    """§1.3's stranded-job sweep is deliberately untouched: a failed cancel
    there is already reportable rather than run-ending, and changing it changes
    sweep semantics rather than close-out semantics. The narrowed exclusion has
    to survive the widening, or the next reader takes the widening for total."""

    text = _text(ADR)
    assert re.search(r"sweep keeps its cancel unretried", text), (
        "ADR-0022 no longer scopes the exclusion it kept — §1.3's sweep cancel "
        "reads as covered by the widening"
    )


def test_the_adr_extends_the_delete_this_retry_instruction_to_the_cancel() -> None:
    """The locked-consume amendment's standing instruction survives and now
    covers both retries: if the Extractor ever makes the lock wait rather than
    refuse, they are deleted rather than kept as harmless belt-and-braces, since
    silent attempts against a route that no longer refuses hide a real error."""

    text = _text(ADR)
    assert re.search(
        r"both retries should be deleted rather than kept as harmless", text
    ), (
        "ADR-0022's delete-this-retry-if-the-lock-waits instruction no longer "
        "covers the cancel's retry as well as the consume's"
    )


def test_the_spec_states_the_cancel_is_retried() -> None:
    """The specification is the source of truth the build is checked against, so
    the cancel's refusal belongs in it beside the consume's rather than only in
    the two documents that execute it."""

    text = _text(SPEC)
    cancel_lines = [
        line
        for line in text.splitlines()
        if REFUSAL_CODE in line and "DELETE /extractions/{id}" in line
    ]
    assert cancel_lines, (
        "docs/spec.md never says the close-out's cancel can be refused "
        f"{REFUSAL_CODE!r}, so the spec and the SKILLs disagree about it"
    )
    joined = " ".join(cancel_lines)
    assert re.search(r"five times", joined) and re.search(r"10 seconds apart", joined), (
        "docs/spec.md states the cancel's refusal without its bound"
    )


def test_the_glossary_carries_the_locked_cancel_term() -> None:
    """`CONTEXT.md` is the project's ubiquitous language, and it already names
    **Locked consume**. The sibling condition gets a sibling term, so the two
    are told apart in prose instead of both being called "a 409"."""

    text = _text(CONTEXT)
    assert "**Locked cancel**" in text, (
        "CONTEXT.md has no **Locked cancel** term beside **Locked consume**"
    )
    _, _, after = text.partition("**Locked cancel**")
    entry, _, _ = after.partition("\n\n")
    assert REFUSAL_CODE in entry, (
        "CONTEXT.md's **Locked cancel** term does not name the refusal code"
    )
    assert re.search(r"five (?:retries|times)", entry), (
        "CONTEXT.md's **Locked cancel** term does not state the bounded schedule"
    )
