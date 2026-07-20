"""Search-index reindex consistency test — bind the local reindex step
(issue #10) to the orchestration prose that must document and delegate it.

After a clone or pull of a Relevanssi/SearchWP-backed site, the imported
search-index tables are empty until something rebuilds them — the classifier
carries them empty by design (``scripts/classify.py``'s
``OPERATIONAL_TABLE_PATTERNS["search_index"]``), exactly like the thumbnail
sizes it excludes from transfer. Both ``SKILL.md`` files already regenerate
thumbnails after import (ADR-0011); issue #10 adds the analogous local rebuild
for the search index, capability-probed with a report-only fallback, folded
into the existing ``thumbnail-smoke-test`` subagent invocation.

This is the same kind of anti-drift binding as
``test_smoke_test_verify_consistency.py`` and
``test_agent_delegation_consistency.py``: it holds the shipped prose to the
issue's own settled decisions, so a rewrite that drops the probe, a fallback
branch, or the delegation reddens here rather than drifting silently.
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
AGENT_FILE: Path = REPO_ROOT / "agents" / "thumbnail-smoke-test.md"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
ADR_DIR: Path = REPO_ROOT / "docs" / "adr"

# The two vendor doc URLs the issue verified the command facts against —
# pinned here so an ADR that cites a different (or no) URL reddens.
RELEVANSSI_DOC_URL = "https://www.relevanssi.com/user-manual/wp-cli/"
SEARCHWP_DOC_URL = "https://searchwp.com/documentation/wp-cli/"


def _import_and_localise_section(text: str) -> str:
    """The ``## N. Import and localise`` step's own text — from its heading
    to the next level-2 heading — so a match elsewhere in the file never
    counts."""

    match = re.search(r"^## \d+\. Import and localise\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "no '## N. Import and localise' section found"
    return match.group(1)


def _verify_smoke_section(text: str) -> str:
    """The ``## N. Verify (smoke)`` section's own text — from its heading to
    the next level-2 heading — so a match elsewhere in the file never
    counts."""

    match = re.search(r"^## \d+\. Verify \(smoke\)\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "no '## N. Verify (smoke)' section found"
    return match.group(1)


def _reindex_step_text(section: str) -> str:
    """The reindex step's own numbered-list item — from the first line that
    starts a numbered item naming the search index to the next numbered
    item — so assertions about its content never accidentally match the
    surrounding thumbnail/flush steps."""

    match = re.search(r"^\d+\.\s+\*\*Rebuild the search index.*?(?=^\d+\.\s+\*\*|\Z)", section, re.MULTILINE | re.DOTALL)
    assert match, "no 'Rebuild the search index' numbered step found in Import and localise"
    return match.group(0)


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_reindex_step_sits_between_thumbnail_regeneration_and_the_rewrite_flush(skill: str) -> None:
    """AC: the reindex runs immediately after thumbnail regeneration and
    before the plugins-loaded rewrite flush — the same slot ADR-0011's
    regeneration step already occupies relative to the flush."""

    section = _import_and_localise_section(SKILLS[skill].read_text(encoding="utf-8"))
    regenerate_pos = section.lower().find("regenerate thumbnails")
    reindex_pos = section.lower().find("rebuild the search index")
    flush_pos = section.lower().find("flush with plugins loaded")
    assert regenerate_pos != -1, f"{skill} SKILL.md lost its thumbnail-regeneration step"
    assert flush_pos != -1, f"{skill} SKILL.md lost its rewrite-flush step"
    assert reindex_pos != -1, f"{skill} SKILL.md never states a 'Rebuild the search index' step"
    assert regenerate_pos < reindex_pos < flush_pos, (
        f"{skill} SKILL.md's reindex step is not between thumbnail regeneration and the rewrite flush"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_reindex_step_names_both_plugin_families_probe_and_run_commands(skill: str) -> None:
    """AC: both plugin commands are named — the deterministic probe
    (``wp cli has-command``) and the actual rebuild invocation, per the
    issue's own verified command facts."""

    section = _import_and_localise_section(SKILLS[skill].read_text(encoding="utf-8"))
    step = _reindex_step_text(section)

    assert 'wp cli has-command "relevanssi index"' in step, f"{skill} SKILL.md never probes the Relevanssi command"
    assert 'wp cli has-command "searchwp index"' in step, f"{skill} SKILL.md never probes the SearchWP command"
    assert "ddev wp relevanssi index" in step, f"{skill} SKILL.md never runs the Relevanssi reindex"
    assert "ddev wp searchwp index --rebuild" in step, f"{skill} SKILL.md never runs the SearchWP reindex"


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_reindex_step_states_the_report_only_fallback(skill: str) -> None:
    """AC: a probe failure (free Relevanssi, no WP-CLI command) never
    attempts an undocumented workaround — it leaves the index empty and
    surfaces a manual-rebuild instruction."""

    section = _import_and_localise_section(SKILLS[skill].read_text(encoding="utf-8"))
    step = _reindex_step_text(section)

    assert re.search(r"report-only", step, re.IGNORECASE), f"{skill} SKILL.md never states the report-only fallback"
    assert re.search(r"manual(ly)?", step, re.IGNORECASE), f"{skill} SKILL.md never surfaces a manual-rebuild instruction"


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_reindex_step_states_the_no_plugin_clean_no_op(skill: str) -> None:
    """AC: with no active search-index plugin, the step is a clean no-op —
    no probe, no report noise."""

    section = _import_and_localise_section(SKILLS[skill].read_text(encoding="utf-8"))
    step = _reindex_step_text(section)

    assert re.search(r"no[\s-]?op", step, re.IGNORECASE), f"{skill} SKILL.md never states the no-plugin no-op case"


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_reindex_step_folds_into_the_thumbnail_smoke_test_delegation(skill: str) -> None:
    """AC: execution is folded into the existing ``thumbnail-smoke-test``
    subagent invocation, which reports the reindex outcome inside its
    evidence block."""

    section = _import_and_localise_section(SKILLS[skill].read_text(encoding="utf-8"))
    step = _reindex_step_text(section)

    assert "Delegate this phase to `thumbnail-smoke-test`" in step, (
        f"{skill} SKILL.md's reindex step never delegates to thumbnail-smoke-test"
    )
    assert "evidence block" in step.lower()
    for outcome in ("rebuilt", "cli-unavailable", "not-present"):
        assert outcome in step, f"{skill} SKILL.md's reindex step never names the outcome {outcome!r}"


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_reindex_step_runs_with_no_operator_gate(skill: str) -> None:
    """Decision 1 (settled at triage): the reindex is local-only,
    deterministic, and mutates only local index tables, so it runs
    automatically — the same footing as thumbnail regeneration, never
    behind its own gate."""

    section = _import_and_localise_section(SKILLS[skill].read_text(encoding="utf-8"))
    step = _reindex_step_text(section)

    assert re.search(r"no operator gate|automatically|ungated", step, re.IGNORECASE), (
        f"{skill} SKILL.md's reindex step never states it runs without an operator gate"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_cleanup_and_report_states_all_three_reindex_outcomes(skill: str) -> None:
    """Decision 6 / AC: the final run report states one of the three
    outcomes — rebuilt, CLI-unavailable-with-manual-instructions, or no
    search-index plugin present."""

    text = SKILLS[skill].read_text(encoding="utf-8")
    match = re.search(r"^## \d+\. Cleanup and report\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, f"{skill} SKILL.md has no 'Cleanup and report' section"
    section = match.group(1)

    assert re.search(r"search.index", section, re.IGNORECASE), (
        f"{skill} SKILL.md's Cleanup and report section never mentions the search-index outcome"
    )
    assert re.search(r"rebuilt", section, re.IGNORECASE)
    assert re.search(r"cli unavailable|cli-unavailable", section, re.IGNORECASE)
    assert re.search(r"no search.index plugin", section, re.IGNORECASE)


def test_thumbnail_smoke_test_agent_documents_the_reindex_subtask() -> None:
    """The delegated subagent's own instructions actually implement the
    reindex probe/run/report-only contract — otherwise the SKILL.md-level
    delegation prose is a promise the subagent's own body never keeps."""

    body = AGENT_FILE.read_text(encoding="utf-8")
    assert re.search(r"reindex", body, re.IGNORECASE)
    # The agent file templates the probe over its `plugin` input rather than
    # spelling out each family's literal command, so the bound string is the
    # templated form actually shipped, not either literal family command —
    # a bare "has-command" check would pass even if the probe were dropped
    # entirely and only mentioned in passing prose.
    assert 'wp cli has-command "<plugin> index"' in body, (
        'thumbnail-smoke-test.md never documents the has-command probe as "wp cli has-command \\"<plugin> index\\""'
    )
    assert "relevanssi" in body and "searchwp" in body, (
        "thumbnail-smoke-test.md never names both search-index plugin families"
    )
    for outcome in ("rebuilt", "cli-unavailable", "not-present"):
        assert outcome in body, f"thumbnail-smoke-test.md never names the outcome {outcome!r}"


def test_spec_import_and_localise_sequence_includes_the_reindex_step() -> None:
    """AC: the spec's own numbered Import-and-localise sequence gets the
    reindex step between thumbnail regeneration and the rewrite flush."""

    text = SPEC.read_text(encoding="utf-8")
    match = re.search(
        r"^### Import and localise \(local, destructive\)\n(.*?)(?=^### |\Z)", text, re.MULTILINE | re.DOTALL
    )
    assert match, "no '### Import and localise (local, destructive)' section found in docs/spec.md"
    section = match.group(1)

    regenerate_pos = section.lower().find("regenerate thumbnails")
    reindex_pos = section.lower().find("search index")
    flush_pos = section.lower().find("flush rewrite rules")
    assert regenerate_pos != -1
    assert flush_pos != -1
    assert reindex_pos != -1, "docs/spec.md's Import and localise sequence never mentions the search index"
    assert regenerate_pos < reindex_pos < flush_pos


def test_spec_user_story_17_distinguishes_discard_and_rebuild_from_discard_and_forget() -> None:
    """AC: user story 17 must distinguish the discard-and-forget operational
    logs from the search index, which is discarded and rebuilt locally."""

    text = SPEC.read_text(encoding="utf-8")
    match = re.search(r"^17\. As an operator.*$", text, re.MULTILINE)
    assert match, "user story 17 not found in docs/spec.md"
    story = match.group(0)

    assert re.search(r"rebuil[dt]", story, re.IGNORECASE), (
        "user story 17 never mentions the search index being rebuilt"
    )


def test_spec_db_table_content_decision_row_distinguishes_search_index() -> None:
    """AC: the 'DB — table content' decision-table row must distinguish the
    discard-and-forget operational logs from the discard-and-rebuild search
    index."""

    text = SPEC.read_text(encoding="utf-8")
    match = re.search(r"^\| DB — table content \|.*\|$", text, re.MULTILINE)
    assert match, "'DB — table content' decision row not found in docs/spec.md"
    row = match.group(0)

    assert re.search(r"rebuil[dt]", row, re.IGNORECASE), (
        "'DB — table content' decision row never mentions the search index being rebuilt"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_skill_verify_smoke_section_mentions_the_rebuilt_search_index_tables_key(skill: str) -> None:
    """AC: the same fold docs/spec.md's Verify section requires must also
    reach each SKILL.md's own '## N. Verify (smoke)' paragraph — it, not
    spec.md, is the operative orchestration prose the running agent follows.
    Without this clause, the orchestrator assembles `tables.operationalEmpty`
    from the resolved plan's raw empty-table list in full, so a correct
    clone/pull that genuinely rebuilt its search index would assert its own
    freshly-populated table empty and fail its own smoke test."""

    section = _verify_smoke_section(SKILLS[skill].read_text(encoding="utf-8"))
    assert "rebuiltSearchIndexTables" in section, (
        f"{skill} SKILL.md's Verify (smoke) section never names rebuiltSearchIndexTables"
    )


def test_spec_verify_section_mentions_the_rebuilt_search_index_tables_key() -> None:
    """AC: the Verify paragraph's expectations assembly must mention that
    only the main index table of a plugin whose rebuild actually ran is
    folded into ``rebuiltSearchIndexTables``."""

    text = SPEC.read_text(encoding="utf-8")
    match = re.search(r"^### Verify\n(.*?)(?=^### |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "no '### Verify' section found in docs/spec.md"
    section = match.group(1)

    assert "rebuiltSearchIndexTables" in section, (
        "docs/spec.md's Verify section never names rebuiltSearchIndexTables"
    )


def test_adr_0015_exists_and_cross_references_adr_0011_and_the_vendor_docs() -> None:
    """AC: a new ADR (next free number) records the search-index-excluded-
    and-rebuilt-locally decision, cross-referencing ADR-0011 and both
    vendor doc URLs the issue verified the command facts against."""

    matches = sorted(ADR_DIR.glob("0015-*.md"))
    assert matches, "no docs/adr/0015-*.md found"
    text = matches[0].read_text(encoding="utf-8")

    assert "0011" in text, "ADR-0015 never cross-references ADR-0011"
    assert RELEVANSSI_DOC_URL in text, "ADR-0015 never cites the Relevanssi WP-CLI manual URL"
    assert SEARCHWP_DOC_URL in text, "ADR-0015 never cites the SearchWP WP-CLI docs URL"


def test_adr_directory_has_no_gap_before_0015() -> None:
    """The 'next free number' contract: 0015 must not skip past an unused
    number — every ADR from 0001 through 0015 exists. This checks only that
    prefix, never the directory's exact upper bound, so a later issue's own
    ADR-0016+ is expected and must never redden this test."""

    numbers = {int(path.name[:4]) for path in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")}
    missing = set(range(1, 16)) - numbers
    assert not missing, f"docs/adr/ has a gap before 0015: missing {sorted(missing)}"
