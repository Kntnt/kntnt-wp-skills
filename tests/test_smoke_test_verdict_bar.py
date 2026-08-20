"""Verdict-bar consistency test — bind the `thumbnail-smoke-test` phase's
`FAILED` bar to the copy, never to a process's exit status (issue #59).

The role returned `FAILED` when **a command exited non-zero** rather than when
**the clone was wrong**, and fired twice on a single production clone on
findings that were not failures. That bar is not merely noisy: the close-out
for a failed phase is destructive, and an operator who learns to discount a
verdict stops reading it, at which point the verdict has negative value.

The fix is a classification rather than a softer rule. `smoke_test.py` now
answers with three exit codes instead of "zero or not" — :data:`EXIT_OK`,
:data:`EXIT_COPY_DEFECTIVE`, :data:`EXIT_COULD_NOT_RUN` — so the one exit that
is evidence against the copy is distinguishable from every exit that says
nothing about it, and the role file carries a table placing every non-zero
exit its three steps can provoke in one bucket or the other with a stated
reason.

This suite is the anti-drift binding for that table and the rule it feeds: the
prose surfaces must keep stating the bar, the table must stay complete and
two-bucketed, and its exit codes must stay the numbers the script actually
uses. Without it, the code half could stand while the prose an agent actually
executes quietly drifted back to "non-zero means failed".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import smoke_test

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
ROLE_FILE: Path = REPO_ROOT / "skills" / "clone" / "roles" / "thumbnail-smoke-test.md"
SKILLS: dict[str, Path] = {
    "clone": REPO_ROOT / "skills" / "clone" / "SKILL.md",
    "pull": REPO_ROOT / "skills" / "pull" / "SKILL.md",
}
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
ADR: Path = REPO_ROOT / "docs" / "adr" / "0026-a-phase-fails-on-a-defective-copy-never-on-a-non-zero-exit.md"
IMPLEMENTATION_NOTES: Path = REPO_ROOT / "docs" / "implementation-notes.md"

# The heading the classification lives under, and the only three values its
# Verdict column may carry. Two of them are the buckets the issue names; the
# third is the reindex probe's pre-existing `cli-unavailable` outcome
# (ADR-0015), which is neither a failure nor something that went wrong.
CLASSIFICATION_HEADING: str = "## What a non-zero exit means"
VERDICT_VALUES: frozenset[str] = frozenset({"**FAILED**", "anomaly", "neither"})


def _role_text() -> str:
    return ROLE_FILE.read_text(encoding="utf-8")


def _classification_rows() -> list[list[str]]:
    """The classification table's data rows, each split into its cells.

    Parsed rather than string-matched so the assertions below can hold every
    row to the same shape — a row added without a bucket, or with a bucket
    this vocabulary does not have, is exactly the drift this suite exists to
    catch.
    """

    text = _role_text()
    start = text.find(CLASSIFICATION_HEADING)
    assert start != -1, f"the role file has no {CLASSIFICATION_HEADING!r} section"
    section = text[start:]
    end = section.find("\n## ", 1)
    if end != -1:
        section = section[:end]

    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.splitlines()
        if line.strip().startswith("|")
    ]
    assert len(rows) >= 3, "no classification table under the heading"

    # Drop the header row and the `|---|` separator beneath it.
    return [row for row in rows[2:] if row]


def _verify_section(text: str) -> str:
    """A SKILL.md's own Verify (smoke) section — heading to next level-2
    heading — so a match elsewhere in the file never counts."""

    match = re.search(r"^## \d+\. Verify \(smoke\)\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "no '## N. Verify (smoke)' section found"
    return match.group(1)


# --- The classification table -----------------------------------------------


def test_every_classified_exit_carries_a_bucket_and_a_reason() -> None:
    """AC: the non-zero exits the phase's steps can provoke are enumerated,
    each classified with a stated reason, in a form a reader can check. A row
    without a reason is an assertion, not a classification."""

    rows = _classification_rows()
    assert len(rows) >= 6, f"only {len(rows)} exits classified — the enumeration is not credible"

    for row in rows:
        assert len(row) == 4, f"row {row!r} is not (step, exit, verdict, why)"
        step, exit_condition, verdict, why = row
        assert step, f"row {row!r} names no step"
        assert exit_condition, f"row {row!r} names no exit condition"
        assert verdict in VERDICT_VALUES, f"row {row!r} carries an unknown verdict {verdict!r}"
        assert len(why) > 20, f"row {row!r} states no reason for its bucket"


def test_exactly_one_classified_exit_is_a_failure() -> None:
    """The whole of the fix: one condition may condemn a run, and it is the
    smoke test's own report finding the copy defective. A second `FAILED` row
    would mean the bar had been widened again."""

    failing = [row for row in _classification_rows() if row[2] == "**FAILED**"]
    assert len(failing) == 1, f"{len(failing)} exits are classified as FAILED, expected exactly 1"
    assert re.search(r"smoke.test", failing[0][0], re.IGNORECASE), (
        "the one failing row is not the smoke test's own verdict"
    )
    assert "fail" in failing[0][3].lower(), (
        "the failing row never says it rests on a `fail` finding in the report"
    )


def test_all_three_steps_are_represented_in_the_classification() -> None:
    """The phase runs three steps and all three can exit non-zero; a table
    covering only the loud one would leave the other two to be judged from
    prose, which is how this bug arrived."""

    steps = " ".join(row[0].lower() for row in _classification_rows())
    for expected in ("regenerat", "index", "smoke test"):
        assert expected in steps, f"no classified exit names the {expected!r} step"


def test_an_unclassifiable_exit_falls_to_anomaly() -> None:
    """AC: an unclassifiable non-zero exit is reported as an anomaly, not a
    failure. Defaulting an unknown to `FAILED` is what produced this bug, so
    the catch-all is part of the table rather than left to judgement."""

    catch_all = [
        row
        for row in _classification_rows()
        if re.search(r"any other|not (?:listed|classified)|anything else", row[1], re.IGNORECASE)
    ]
    assert catch_all, "the table has no catch-all row for an exit it does not classify"
    for row in catch_all:
        assert row[2] == "anomaly", f"the catch-all row {row!r} does not fall to `anomaly`"


def test_the_classification_names_the_exit_codes_the_script_actually_uses() -> None:
    """The role reads the verdict off `smoke_test.py`'s exit code, so the two
    numbers it names must be the two the script returns — a constant changed
    on one side without the other would leave the role condemning the wrong
    runs."""

    section = _role_text()
    assert f"exits `{smoke_test.EXIT_COPY_DEFECTIVE}`" in section, (
        "the role never names the exit code that means the copy is defective"
    )
    assert f"exits `{smoke_test.EXIT_COULD_NOT_RUN}`" in section, (
        "the role never names the exit code that means the smoke test could not run"
    )


# --- The verdict the table feeds --------------------------------------------


def test_the_role_binds_failed_to_the_copy_not_to_an_exit_status() -> None:
    """The bar itself: `FAILED` iff the smoke test ran and its report carries
    a `fail`. Stated as an `iff` so neither half can be read loosely."""

    text = _role_text()
    assert re.search(
        r"`status` is `FAILED` \*\*iff `scripts/smoke_test\.py` exits `1`\*\*", text
    ), "the role no longer states the verdict bar as an iff on the one defect-implying exit"


def test_the_role_denies_the_old_bar_in_as_many_words() -> None:
    """The rule that was wrong is worth naming, not merely superseding: a
    reader who arrives with the old bar in mind must meet it being refused."""

    text = _role_text()
    assert re.search(
        r"never (?:because|that) a command exited non-zero|a command exited non-zero is never",
        text,
        re.IGNORECASE,
    ), "the role never refuses the old 'a command exited non-zero' bar outright"


def test_the_role_keeps_a_step_level_anomaly_as_visible_as_a_failure_was() -> None:
    """AC: an anomaly must be as visible as a failure was — the point is not a
    quieter agent but one that stops lying about what it found. The evidence
    block's `anomalies` list is where a non-zero regeneration or reindex exit,
    and a smoke test that could not run, have to land."""

    text = _role_text()
    for field in ("regenerate_exit", "reindex_exit", "smoke_test_could_not_run"):
        assert f"`{field}`" in text, f"the evidence block never carries the {field!r} anomaly"


def test_the_role_hard_rules_forbid_condemning_a_run_on_a_neutral_exit() -> None:
    """The hard rules are what an agent re-reads under pressure; the bar has
    to be one of them, on both sides — never condemn on a neutral exit, and
    never quietly drop the anomaly that exit deserves."""

    match = re.search(r"^## Hard rules\n(.*?)(?=^## |\Z)", _role_text(), re.MULTILINE | re.DOTALL)
    assert match, "the role file has no Hard rules section"
    rules = match.group(1)
    assert re.search(r"never return `FAILED`", rules, re.IGNORECASE), (
        "no hard rule forbids returning FAILED on an exit that is not a defective copy"
    )
    assert re.search(r"never (?:drop|swallow|omit)[^.\n]*anomal", rules, re.IGNORECASE), (
        "no hard rule forbids dropping an anomaly because it is not a failure"
    )


# --- The surfaces that must agree with it -----------------------------------


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_skill_verify_section_states_the_bar(skill: str) -> None:
    """Both SKILL.md files describe this verdict where they consume it, so an
    orchestrator reading only its own skill still applies the same bar the
    role does."""

    section = _verify_section(SKILLS[skill].read_text(encoding="utf-8"))
    assert re.search(r"`FAILED` only", section), (
        f"{skill} SKILL.md's Verify section never restricts `FAILED` to the defect case"
    )
    assert re.search(r"anomal", section, re.IGNORECASE), (
        f"{skill} SKILL.md's Verify section never names the anomaly the other exits become"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_skill_regeneration_step_states_a_non_zero_exit_is_not_a_failure(skill: str) -> None:
    """The regeneration step is the one an operator watches spew warnings, and
    the first place the old bar fired. Its own prose must say what a non-zero
    exit there means, rather than leaving the reader to infer it."""

    text = SKILLS[skill].read_text(encoding="utf-8")
    match = re.search(r"\*\*Regenerate thumbnails.*?(?=\n\d+\. \*\*|\n## )", text, re.DOTALL)
    assert match, f"{skill} SKILL.md has no thumbnail-regeneration step"
    step = match.group(0)
    assert re.search(r"non-zero exit[^.]*anomal", step, re.IGNORECASE), (
        f"{skill} SKILL.md's regeneration step never says a non-zero exit is an anomaly"
    )
    assert "never a `FAILED`" in step, (
        f"{skill} SKILL.md's regeneration step never says such an exit is not a `FAILED`"
    )


def test_spec_verify_section_states_the_bar() -> None:
    """`docs/spec.md` is the declared single source of truth; a bar it does
    not carry is a bar the next rewrite is free to lose."""

    text = SPEC.read_text(encoding="utf-8")
    match = re.search(r"^### Verify\n(.*?)(?=^### |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "no '### Verify' section found in docs/spec.md"
    section = match.group(1)
    assert re.search(r"anomal", section, re.IGNORECASE), (
        "docs/spec.md's Verify section never names the anomaly bucket"
    )
    assert re.search(r"defective|the copy is wrong", section, re.IGNORECASE), (
        "docs/spec.md's Verify section never states what a failed verify means"
    )


def test_the_adr_records_the_decision_and_its_two_buckets() -> None:
    """The bar is a settled decision with a rejected alternative behind it
    (keep condemning on any non-zero exit), so it belongs in `docs/adr/`
    beside the rest — an ADR is where a later reader is told this was decided
    rather than overlooked."""

    assert ADR.is_file(), f"{ADR.name} is missing"
    text = ADR.read_text(encoding="utf-8")
    assert "#59" in text, "the ADR never cites the issue it settles"
    for term in ("anomaly", "FAILED", "smoke_test.py"):
        assert term in text, f"the ADR never mentions {term!r}"


def test_the_implementation_notes_carry_the_exit_code_contract() -> None:
    """The notes are where a maintainer looks for what a helper's output
    means; the three exit codes are now the whole of the verify phase's
    verdict, so they belong there in the same checkable form."""

    text = IMPLEMENTATION_NOTES.read_text(encoding="utf-8")
    match = re.search(r"^## Verify \(smoke\)\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "no '## Verify (smoke)' section found in docs/implementation-notes.md"
    section = match.group(1)
    for code in (smoke_test.EXIT_OK, smoke_test.EXIT_COPY_DEFECTIVE, smoke_test.EXIT_COULD_NOT_RUN):
        assert f"`{code}`" in section, f"the notes never state what exit code {code} means"
