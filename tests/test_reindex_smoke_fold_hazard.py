"""Cross-issue integration hotfix — bind two seams the #10 reindex step
opened against pre-existing prose it never touched.

1. **The false-smoke-verdict hazard.** §10 Verify's delegation sentence has
   always said the ``thumbnail-smoke-test`` call "can combine this with the
   preceding thumbnail-regeneration call in one invocation" — true before
   issue #10, when nothing between regeneration and smoke produced a result
   the expectations object needed. Issue #10 inserted the reindex step into
   that same preceding invocation and made ``rebuiltSearchIndexTables``
   (assembled *before* the smoke delegation) depend on the reindex's own
   outcome (``rebuilt`` / ``cli-unavailable`` / ``not-present``), which only
   exists once that invocation's evidence block returns. Folding smoke into
   the same call as an active-plugin reindex therefore forces
   ``rebuiltSearchIndexTables`` to be guessed before the reindex has run —
   risking a false FAIL either way the guess lands. The fix: the Verify
   section must state that the smoke delegation is a **separate** call that
   runs only after the reindex outcome is known, with the fold remaining
   safe only when no active search-index plugin makes the reindex a
   guaranteed no-op.

2. **The pull substep-numbering drift.** Issue #10's own §10 Verify prose
   correctly cites "step 9.13", "step 9.6", "step 9.1" — pull's
   section.substep convention — but the Cleanup and report line it also
   touched still says the bare "step 13", which belongs to clone's different
   (bare-substep) convention. Purely cosmetic; no behavioural effect, but it
   breaks pull's own internal consistency.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SKILLS: dict[str, Path] = {
    "clone": REPO_ROOT / "skills" / "clone" / "SKILL.md",
    "pull": REPO_ROOT / "skills" / "pull" / "SKILL.md",
}


def _verify_smoke_section(text: str) -> str:
    """The ``## N. Verify (smoke)`` section's own text — from its heading to
    the next level-2 heading — so a match elsewhere in the file never
    counts."""

    match = re.search(r"^## \d+\. Verify \(smoke\)\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "no '## N. Verify (smoke)' section found"
    return match.group(1)


def _smoke_delegation_sentence(section: str) -> str:
    """The Verify section's own delegation paragraph — the one that
    delegates to ``thumbnail-smoke-test``, distinct from the expectations-
    assembly paragraph above it — so assertions about the fold guidance
    never accidentally match unrelated prose."""

    match = re.search(r"\*\*Delegate this phase to `thumbnail-smoke-test`\*\*.*", section)
    assert match, "no smoke-test delegation sentence found in the Verify (smoke) section"
    return match.group(0)


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_smoke_delegation_states_it_must_run_separately_from_an_active_reindex(skill: str) -> None:
    """AC: the smoke delegation must warn that it cannot share one
    invocation with an active-plugin reindex — the reindex's outcome decides
    ``rebuiltSearchIndexTables``, and that outcome is unknown until the
    reindex call returns."""

    section = _verify_smoke_section(SKILLS[skill].read_text(encoding="utf-8"))
    sentence = _smoke_delegation_sentence(section)

    assert re.search(r"\bseparat", sentence, re.IGNORECASE), (
        f"{skill} SKILL.md's smoke delegation never states it must run separately from the reindex call"
    )
    assert re.search(r"reindex", sentence, re.IGNORECASE), (
        f"{skill} SKILL.md's smoke delegation never names the reindex as the reason for the separation"
    )
    assert re.search(r"rebuiltSearchIndexTables", sentence), (
        f"{skill} SKILL.md's smoke delegation never ties the separation to rebuiltSearchIndexTables"
    )
    assert re.search(r"outcome", sentence, re.IGNORECASE), (
        f"{skill} SKILL.md's smoke delegation never mentions the reindex outcome by name"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_smoke_delegation_still_permits_the_fold_when_no_search_index_plugin_is_active(skill: str) -> None:
    """AC: the fold-in-one-invocation guidance survives for the case that was
    always safe — no active search-index plugin means the reindex is a
    guaranteed no-op, so there is no outcome to wait for."""

    section = _verify_smoke_section(SKILLS[skill].read_text(encoding="utf-8"))
    sentence = _smoke_delegation_sentence(section)

    assert re.search(r"no active search-index plugin", sentence, re.IGNORECASE), (
        f"{skill} SKILL.md's smoke delegation never states the no-active-plugin exception that keeps the fold safe"
    )
    assert re.search(r"combine|fold", sentence, re.IGNORECASE), (
        f"{skill} SKILL.md's smoke delegation dropped the one-invocation option entirely instead of conditioning it"
    )


def test_pull_cleanup_and_report_references_the_reindex_step_using_the_dotted_substep_convention() -> None:
    """Cosmetic: pull's own §10 Verify prose already cites 'step 9.13',
    'step 9.6', and 'step 9.1' — the dotted section.substep convention pull
    uses throughout. The Cleanup and report line issue #10 also touched must
    match, not the bare 'step 13' that belongs to clone's different
    (bare-substep) convention."""

    text = SKILLS["pull"].read_text(encoding="utf-8")
    match = re.search(r"^## \d+\. Cleanup and report\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "pull SKILL.md has no 'Cleanup and report' section"
    section = match.group(1)

    assert "step 9.13" in section, "pull SKILL.md's Cleanup and report line never references 'step 9.13'"
    assert not re.search(r"\bstep 13\b", section), (
        "pull SKILL.md's Cleanup and report line still uses the bare 'step 13' reference"
    )


def test_clone_cleanup_and_report_keeps_its_own_bare_substep_convention() -> None:
    """Guard rail: clone uses the bare-substep convention ('step 9', 'step
    6') throughout and must stay that way — this hotfix touches only pull's
    drifted reference, never clone's already-consistent one."""

    text = SKILLS["clone"].read_text(encoding="utf-8")
    match = re.search(r"^## \d+\. Cleanup and report\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "clone SKILL.md has no 'Cleanup and report' section"
    section = match.group(1)

    assert re.search(r"\bstep 9\b", section), "clone SKILL.md's Cleanup and report line no longer references 'step 9'"
    assert "9.9" not in section, "clone SKILL.md's Cleanup and report line must not switch to pull's dotted convention"
