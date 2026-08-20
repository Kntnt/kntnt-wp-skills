"""Restricted-path refusal — the client drops the named paths and resubmits once.

The Extractor refuses the *whole* create when a selection names a path its own
policy restricts: ``422`` with ``code == "kntnt_extractor_restricted_path"`` and
every offender in ``data.paths``. This client's exclusion patterns are a
pre-filter against that, never a mirror of it — the server's policy lives in
another repository and may widen between releases without an ``api_version``
bump (ADR-0024) — so the refusal has to be survivable rather than merely rare.

This suite binds the caller. The role whose steps actually POST, both SKILLs,
and the spec all name the code, drop exactly the paths the server named, and
resubmit exactly once; a second refusal is fatal. Before it existed the code
appeared nowhere in this repository at all, so an operator met an unrecognised
error at the step meant to begin a multi-hour transfer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]

EXTRACT_SUBMIT: Path = REPO_ROOT / "skills" / "clone" / "roles" / "extract-submit.md"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
CLONE: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
PULL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"

ERROR_CODE = "kntnt_extractor_restricted_path"

SURFACES: tuple[Path, ...] = (EXTRACT_SUBMIT, SPEC, CLONE, PULL)


@pytest.mark.parametrize("path", SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_submit_surface_names_the_refusal_code(path: Path) -> None:
    """An operator meeting the refusal finds it described where they are reading."""

    text = path.read_text(encoding="utf-8")
    assert ERROR_CODE in text, (
        f"{path.relative_to(REPO_ROOT)} never names {ERROR_CODE}, so the refusal "
        "reaches its reader as an unrecognised error code"
    )


@pytest.mark.parametrize("path", SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_submit_surface_names_the_paths_the_server_refused(path: Path) -> None:
    """The refusal names every offender at once, which is what makes one
    corrected resubmission sufficient by construction."""

    text = path.read_text(encoding="utf-8")
    assert "data.paths" in text, (
        f"{path.relative_to(REPO_ROOT)} does not say the refused paths arrive in "
        "data.paths, so a reader cannot know what to drop"
    )


def test_extract_submit_drops_the_named_paths_and_resubmits_once() -> None:
    """The role that POSTs recovers, and the recovery is bounded at one attempt."""

    text = EXTRACT_SUBMIT.read_text(encoding="utf-8")
    assert "drop exactly those paths" in text, (
        "the role must drop exactly the paths the server named — dropping more is "
        "a silent hole in the copy, dropping fewer loops"
    )
    assert "resubmit the create **once**" in text, (
        "the resubmission must be bounded at exactly one; an unbounded retry on a "
        "refusal the two sides disagree about is a loop"
    )


def test_a_second_restricted_path_refusal_is_a_hard_stop() -> None:
    """A refusal that survives dropping every named path cannot be guessed past."""

    text = EXTRACT_SUBMIT.read_text(encoding="utf-8")
    assert "A second `kntnt_extractor_restricted_path`" in text
    assert "hard stop" in text


def test_other_422s_stay_a_hard_stop() -> None:
    """Only the restricted-path code is split out; a malformed or overlapping
    selection is still fatal on the first occurrence."""

    text = EXTRACT_SUBMIT.read_text(encoding="utf-8")
    assert "malformed or overlapping selection" in text
    assert "hard stop" in text


def test_extract_submit_reports_the_dropped_paths_in_its_evidence_block() -> None:
    """The dropped paths ride the evidence block beside the vanished ones, so the
    orchestrator's report can name what the copy does not contain."""

    text = EXTRACT_SUBMIT.read_text(encoding="utf-8")
    assert "`restricted_paths`" in text, (
        "the evidence-block contract must carry restricted_paths beside "
        "skipped_files, or the dropped paths reach no report"
    )
    assert "empty list when none" in text


@pytest.mark.parametrize("path", (CLONE, PULL), ids=("clone", "pull"))
def test_both_skills_report_the_dropped_paths_to_the_operator(path: Path) -> None:
    """The operator is told which paths were refused and why, not left to read an
    error code the run report does not explain."""

    text = path.read_text(encoding="utf-8")
    assert "restricted" in text.lower()
    assert "resubmit" in text.lower()


def test_the_two_skills_word_the_refusal_identically() -> None:
    """clone and pull describe one behaviour, so their sentences are one sentence;
    two spellings of the same rule are two things to keep current."""

    sentences = []
    for path in (CLONE, PULL):
        text = path.read_text(encoding="utf-8")
        matching = [
            line.strip()
            for line in text.splitlines()
            if ERROR_CODE in line
        ]
        assert matching, f"{path.relative_to(REPO_ROOT)} carries no {ERROR_CODE} line"
        sentences.append(matching)

    assert sentences[0] == sentences[1], (
        "clone and pull have drifted in how they describe the restricted-path "
        "refusal; the two files must carry identical wording"
    )
