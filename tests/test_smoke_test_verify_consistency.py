"""Verify-phase consistency test — bind the deterministic smoke test
(``scripts/smoke_test.py``, issue #25) to the orchestration prose that must
delegate to it.

Issue #25 replaces the ad-hoc check list in both ``SKILL.md``'s Verify (smoke)
section with the deterministic script, wires the delegated
``thumbnail-smoke-test`` subagent to run it, and documents standalone usage in
both manual pages. This is the same kind of anti-drift binding as
``test_help_docs_consistency.py`` and ``test_agent_delegation_consistency.py``:
it holds the shipped prose to the architecture the issue describes, so a
rewrite that quietly drops the delegation or the standalone-usage note
reddens here rather than drifting silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import smoke_test

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SKILLS: dict[str, Path] = {
    "clone": REPO_ROOT / "skills" / "clone" / "SKILL.md",
    "pull": REPO_ROOT / "skills" / "pull" / "SKILL.md",
}
MANPAGES: dict[str, Path] = {
    "clone": REPO_ROOT / "docs" / "man" / "clone.md",
    "pull": REPO_ROOT / "docs" / "man" / "pull.md",
}
AGENT_FILE: Path = REPO_ROOT / "agents" / "thumbnail-smoke-test.md"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"


def _verify_section(text: str) -> str:
    """The Verify (smoke) step's own text: from its heading to the next
    level-2 heading, so a match elsewhere in the file (the changelog, an
    unrelated step) never counts."""

    match = re.search(r"^## \d+\. Verify \(smoke\)\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "no '## N. Verify (smoke)' section found"
    return match.group(1)


def _spec_verify_section(text: str) -> str:
    """``docs/spec.md``'s own ``### Verify`` section — from its heading to
    the next level-3 heading — so a match in an unrelated section (Testing
    Decisions, a changelog-shaped aside) never counts."""

    match = re.search(r"^### Verify\n(.*?)(?=^### |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "no '### Verify' section found in docs/spec.md"
    return match.group(1)


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_verify_step_delegates_to_the_smoke_test_script(skill: str) -> None:
    """Each skill's Verify (smoke) step names ``scripts/smoke_test.py`` as the
    check surface — the "prescribed final step" the issue requires, replacing
    the ad-hoc check list that used to live only in prose."""

    section = _verify_section(SKILLS[skill].read_text(encoding="utf-8"))
    assert "scripts/smoke_test.py" in section, (
        f"{skill} SKILL.md's Verify (smoke) step never names scripts/smoke_test.py"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_verify_step_still_delegates_to_the_subagent_with_its_evidence_block(skill: str) -> None:
    """The rewrite must not drop the existing subagent delegation (issue
    #13) while wiring in the script — both architectures coexist."""

    section = _verify_section(SKILLS[skill].read_text(encoding="utf-8"))
    assert "Delegate this phase to `thumbnail-smoke-test`" in section
    assert "evidence block" in section.lower()
    assert "done" in section.lower() and "failed" in section.lower()


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_verify_step_still_states_the_orchestrator_deterministic_recheck(skill: str) -> None:
    """The orchestrator's own cheap spot-check on top of the subagent's
    report — an existing hard requirement (test_agent_delegation_consistency
    binds it too) — must survive the rewrite verbatim."""

    section = _verify_section(SKILLS[skill].read_text(encoding="utf-8"))
    assert re.search(r"re-run `wp db check`", section, re.IGNORECASE)


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_verify_step_mentions_the_expectations_file(skill: str) -> None:
    """The prose names the expectations-file concept the script consumes,
    not just the script's bare filename — a reader must be able to tell what
    goes in, not only what runs."""

    section = _verify_section(SKILLS[skill].read_text(encoding="utf-8"))
    assert "expectations" in section.lower()


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_verify_step_restricts_content_nonempty_to_the_always_populated_core_set(skill: str) -> None:
    """"Carried in full" only means the transfer did not silently empty a
    table — it says nothing about whether production actually put rows in
    it (``wp_links``/``wp_commentmeta`` are full-carried yet legitimately
    empty on many real sites). The prose must instruct the orchestrator to
    restrict ``tables.contentNonEmpty`` to the always-populated core tables
    (mirroring ``smoke_test._ALWAYS_POPULATED_CORE_TABLES``), never assemble
    it from the whole content-table list — otherwise a correct copy of a
    site with a legitimately-empty full-carried table FAILs its own verify
    phase."""

    section = _verify_section(SKILLS[skill].read_text(encoding="utf-8"))
    for table in sorted(smoke_test._ALWAYS_POPULATED_CORE_TABLES):
        assert f"`{table}`" in section, f"{skill} SKILL.md never names the core table {table!r}"
    assert "never" in section, f"{skill} SKILL.md never states the exclusion this check pins"


def test_thumbnail_smoke_test_agent_runs_the_smoke_test_script() -> None:
    """The delegated subagent's own instructions actually invoke the script
    — otherwise the SKILL.md-level delegation prose is a promise the
    subagent's own body never keeps."""

    body = AGENT_FILE.read_text(encoding="utf-8")
    assert "scripts/smoke_test.py" in body
    assert "expectations" in body.lower()


def test_thumbnail_smoke_test_agent_still_states_the_never_ask_rule() -> None:
    """The rewrite must not drop the existing hard rule that a subagent can
    never ask the operator anything (issue #13's contract, re-bound here
    since this file is exactly what's being rewritten for issue #25)."""

    body = AGENT_FILE.read_text(encoding="utf-8")
    assert re.search(r"never ask the operator", body, re.IGNORECASE)


@pytest.mark.parametrize("skill", sorted(MANPAGES))
def test_manpage_documents_standalone_smoke_test_usage(skill: str) -> None:
    """Each manual page documents that ``scripts/smoke_test.py`` can be run
    standalone from a terminal, per the issue's own instruction — the single
    source-of-usage-truth manpages are where an operator would look."""

    text = MANPAGES[skill].read_text(encoding="utf-8")
    assert "scripts/smoke_test.py" in text
    assert re.search(r"uv run.*smoke_test\.py", text), (
        f"{skill}.md never shows the `uv run ... smoke_test.py` invocation form"
    )


def test_fatal_error_markers_are_identical_between_the_script_and_the_skill_prose() -> None:
    """The three WordPress fatal-error markers the script greps for
    (``smoke_test.FATAL_ERROR_MARKERS``) are the same three strings the
    orchestration prose has always named — a rewrite of one side without the
    other would silently desynchronise what "success" means."""

    for path in SKILLS.values():
        text = path.read_text(encoding="utf-8")
        for marker in smoke_test.FATAL_ERROR_MARKERS:
            assert f"`{marker}`" in text, f"{path.name} never states the marker {marker!r}"


def test_smoke_test_script_is_a_pep723_standalone_script() -> None:
    """``scripts/smoke_test.py`` follows the project's standalone-script
    packaging convention (agents.d/coding-standard/python.md): inline PEP 723
    metadata pinning the Python floor, no third-party dependencies."""

    text = (REPO_ROOT / "scripts" / "smoke_test.py").read_text(encoding="utf-8")
    assert text.startswith("# /// script\n")
    assert "requires-python" in text.splitlines()[1]


def test_spec_verify_section_delegates_to_the_smoke_test_script() -> None:
    """``docs/spec.md`` — the declared single source of truth — must
    describe the same deterministic-expectations architecture issue #25
    shipped in both ``SKILL.md`` files, never the ad-hoc, hand-checked list
    it prescribed before the rewrite. Nothing else in this suite binds
    ``spec.md`` to the verify-phase rewrite, so a future change that only
    touches the ``SKILL.md`` prose would otherwise leave the spec silently
    contradicting the shipped architecture."""

    section = _spec_verify_section(SPEC.read_text(encoding="utf-8"))
    assert "scripts/smoke_test.py" in section, (
        "docs/spec.md's Verify section never names scripts/smoke_test.py"
    )
    assert "expectations" in section.lower(), (
        "docs/spec.md's Verify section never mentions the expectations object"
    )
    assert re.search(r"ad[\s-]?hoc", section, re.IGNORECASE), (
        "docs/spec.md's Verify section no longer states that the expectations "
        "object replaces an ad-hoc, hand-checked list"
    )


def test_spec_testing_decisions_residual_paragraph_mentions_the_smoke_test_script() -> None:
    """The Testing Decisions residual paragraph must also name the
    deterministic script as the in-run verification the manual smoke sits
    on top of, not the hand-wavy description of the verify phase it carried
    before issue #25."""

    text = SPEC.read_text(encoding="utf-8")
    match = re.search(r"- \*\*Stated residual.*?(?=\n\n|\Z)", text, re.DOTALL)
    assert match, "no 'Stated residual' bullet found in docs/spec.md's Testing Decisions"
    assert "scripts/smoke_test.py" in match.group(0), (
        "docs/spec.md's 'Stated residual' paragraph never names scripts/smoke_test.py"
    )
