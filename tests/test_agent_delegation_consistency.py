"""Subagent-delegation consistency test — bind the plugin's pinned subagents to
the ``clone``/``pull`` orchestration (issue #13).

A full clone run pushed the orchestrating agent's own context past ~300k
tokens, almost entirely transport noise (MCP round-trips, curl/checksum
output, thumbnail-regeneration warning spam) rather than decisions. The fix
ships four pinned subagents under ``agents/`` — one per heavy phase — and has
both ``SKILL.md`` files delegate to them explicitly, each with a structured
**evidence block** (exit codes, artifact paths + SHA256, row/file counts,
``DONE``/``FAILED`` markers) the orchestrator validates deterministically
rather than trusting a second LLM's prose.

This is the same kind of anti-drift binding as
``test_help_docs_consistency.py`` and the orchestration-consistency suites: it
holds the shipped agent definitions and the two ``SKILL.md`` files to the
architecture the issue describes, so a rewrite that drops the pin, forgets a
phase's evidence-block contract, or lets a subagent's own instructions permit
it to ask the operator something reddens here rather than drifting silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
AGENTS_DIR: Path = REPO_ROOT / "agents"
SKILLS: dict[str, Path] = {
    "clone": REPO_ROOT / "skills" / "clone" / "SKILL.md",
    "pull": REPO_ROOT / "skills" / "pull" / "SKILL.md",
}

# Issue #13's phase table: subagent name -> its pinned model/effort and which
# skills delegate a phase to it. Both skills delegate every phase — clone's
# "manifest + baseline diff" phase runs the same subagent in manifest-only
# mode (it has no baseline to diff against), and its "thumbnail regen + smoke
# test" phase is delegated twice (regeneration, then the verify step) to the
# same definition.
ROSTER: dict[str, dict[str, object]] = {
    "discovery-classify": {
        "model": "sonnet",
        "effort": "low",
        "skills": ("clone", "pull"),
    },
    "pack-transfer": {
        "model": "sonnet",
        "effort": "medium",
        "skills": ("clone", "pull"),
    },
    "manifest-baseline-diff": {
        "model": "haiku",
        "effort": "low",
        "skills": ("clone", "pull"),
    },
    "thumbnail-smoke-test": {
        "model": "haiku",
        "effort": "low",
        "skills": ("clone", "pull"),
    },
}


def _frontmatter(path: Path) -> dict[str, str]:
    """Parse a ``---``-delimited frontmatter block into a flat key/value map.

    Deliberately hand-rolled rather than a YAML library: the plugin's helper
    scripts declare zero third-party dependencies (PEP 723 metadata), and
    every value here is a flat scalar — no lists, no nesting — so a small
    line-oriented parser is the honest, dependency-free tool for the job (the
    same choice ``test_help_docs_consistency.py`` makes for Markdown).
    """

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0].strip() == "---", f"{path.name} has no frontmatter block"
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    assert end is not None, f"{path.name}'s frontmatter block is never closed"

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        # Skip blank lines and continuation lines (folded/quoted scalars) —
        # only top-level ``key: value`` pairs matter for this registry.
        if not line.strip() or line[:1] in (" ", "\t", ">", "|"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        fields[key.strip()] = value.strip()
    return fields


def _body(path: Path) -> str:
    """Everything after the closing frontmatter delimiter — the subagent's own
    instructions."""

    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    assert len(parts) == 3, f"{path.name} has no frontmatter block"
    return parts[2]


def _delegate_anchor(name: str) -> str:
    """The literal handoff sentence a ``SKILL.md`` must carry to delegate a
    phase to the named subagent."""

    return f"Delegate this phase to `{name}`"


@pytest.mark.parametrize("name", sorted(ROSTER))
def test_every_rostered_agent_has_a_definition_file(name: str) -> None:
    """Every phase issue #13's table names ships a real agent definition under
    ``agents/``."""

    assert (AGENTS_DIR / f"{name}.md").is_file(), f"agents/{name}.md is missing"


def test_agents_directory_carries_no_stray_definitions() -> None:
    """The roster above is the complete set — an orphaned or extra definition
    file would drift the plugin's shipped agent surface away from the
    documented table without anything else catching it."""

    assert AGENTS_DIR.is_dir(), "agents/ directory does not exist"
    present = {p.stem for p in AGENTS_DIR.glob("*.md")}
    assert present == set(ROSTER), f"agents/ carries an unexpected set: {present}"


@pytest.mark.parametrize("name,expected", sorted(ROSTER.items()))
def test_agent_frontmatter_pins_its_name_model_and_effort(
    name: str, expected: dict[str, object]
) -> None:
    """Each subagent's own frontmatter pins its name, a real model alias, and a
    reasoning effort — the "model and reasoning effort pinned in frontmatter"
    acceptance criterion — so the orchestrator's context budget is a property
    of the shipped definition, never a runtime guess."""

    path = AGENTS_DIR / f"{name}.md"
    fields = _frontmatter(path)

    assert fields.get("name") == name, (
        f"{name}.md frontmatter name {fields.get('name')!r} mismatches its filename"
    )
    assert fields.get("model") == expected["model"], (
        f"{name}.md pins model {fields.get('model')!r}, expected {expected['model']!r}"
    )
    assert fields.get("effort") == expected["effort"], (
        f"{name}.md pins effort {fields.get('effort')!r}, expected {expected['effort']!r}"
    )
    assert fields.get("description"), f"{name}.md has no description"


@pytest.mark.parametrize("name", sorted(ROSTER))
def test_agent_body_states_the_evidence_block_and_never_ask_rule(name: str) -> None:
    """Every subagent's own instructions carry the evidence-block contract
    (checksums, exit-code-shaped fields, DONE/FAILED markers, a scratchpad
    routing rule) and the rule that it can never ask the operator anything —
    subagents run once against a task envelope and return, they do not gate."""

    body = _body(AGENTS_DIR / f"{name}.md").lower()
    for term in ("evidence block", "scratchpad", "sha256", "done", "failed"):
        assert term in body, f"{name}.md body omits {term!r}"
    assert re.search(r"never ask the operator", body), (
        f"{name}.md does not state the never-ask-the-operator rule"
    )


@pytest.mark.parametrize(
    "skill,name",
    [(skill, name) for name, info in ROSTER.items() for skill in info["skills"]],
)
def test_skill_delegates_the_phase_with_its_evidence_block_contract(
    skill: str, name: str
) -> None:
    """AC #1 and #2: each SKILL.md names the subagent it delegates a phase to,
    right where that phase already lives, and states the evidence-block
    fields the orchestrator checks there — never a bare mention floating apart
    from the step it belongs to."""

    text = SKILLS[skill].read_text(encoding="utf-8")
    anchor = _delegate_anchor(name)
    pos = text.find(anchor)
    assert pos != -1, f"{skill} SKILL.md never delegates to `{name}`"

    # The evidence-block contract must be stated close to the handoff, not
    # merely somewhere in the file — a nearby window catches a delegation
    # sentence that names the subagent but never specifies what it must prove.
    window = text[pos : pos + 1200].lower()
    assert "evidence block" in window, (
        f"{skill} SKILL.md delegates to `{name}` without stating its evidence block"
    )
    assert "done" in window and "failed" in window, (
        f"{skill} SKILL.md's `{name}` delegation omits the DONE/FAILED markers"
    )


def _delegation_windows(text: str, anchor: str, size: int = 1200) -> list[str]:
    """Every text window following an occurrence of ``anchor`` in ``text``.

    A subagent may be delegated to more than once per ``SKILL.md``
    (``thumbnail-smoke-test``'s regeneration and verify calls delegate to the
    same subagent from two different steps), and each call carries its own
    evidence-block prose — the union of these windows is what a reader
    actually sees documented for that subagent, not just the first call.
    """

    windows: list[str] = []
    start = 0
    while True:
        pos = text.find(anchor, start)
        if pos == -1:
            break
        windows.append(text[pos : pos + size])
        start = pos + 1
    return windows


# Field-shaped evidence terms specific to each phase's delegation prose — SHA256
# checksums, exit codes, and row/file counts — distinct from the generic
# "evidence block" / "done" / "failed" markers ``test_skill_delegates_the_phase_
# with_its_evidence_block_contract`` above already binds. Grounded in the
# committed SKILL.md prose so the assertions are never vacuous.
EVIDENCE_FIELD_TERMS: dict[str, tuple[str, ...]] = {
    "discovery-classify": ("sha256", "exit code", "counts"),
    "pack-transfer": ("sha256", "byte size"),
    "manifest-baseline-diff": ("sha256", "exit code", "row count"),
    "thumbnail-smoke-test": ("exit code", "count"),
}


@pytest.mark.parametrize(
    "skill,name",
    [(skill, name) for name, info in ROSTER.items() for skill in info["skills"]],
)
def test_skill_delegation_names_its_specific_evidence_fields(
    skill: str, name: str
) -> None:
    """AC #2's field-level half: beyond the generic "evidence block" mention,
    each phase's delegation prose must itself name the field-shaped facts the
    issue demands (exit codes, SHA256 checksums, row/file counts) — so a
    rewrite that keeps the anchor sentence and the DONE/FAILED markers but
    quietly drops the actual field prose reddens here rather than passing the
    looser generic check above."""

    text = SKILLS[skill].read_text(encoding="utf-8").lower()
    anchor = _delegate_anchor(name).lower()
    windows = _delegation_windows(text, anchor)
    assert windows, f"{skill} SKILL.md never delegates to `{name}`"

    joined = " ".join(windows)
    for term in EVIDENCE_FIELD_TERMS[name]:
        assert term in joined, (
            f"{skill} SKILL.md's `{name}` delegation never names the evidence "
            f"field {term!r}"
        )


# The orchestrator's own deterministic re-check per (skill, phase) pair — the
# second half of the issue's rule ("re-runs 1-2 cheap deterministic spot
# checks itself") beyond simply trusting a subagent's self-reported evidence
# block. Not every pair carries one: clone's manifest-only write (no baseline
# to diff against yet) has nothing to re-check against, so it is deliberately
# absent here rather than padded with a check that would not exist.
RECHECK_PATTERN: dict[tuple[str, str], str] = {
    ("clone", "discovery-classify"): r"re-read the written discovery document yourself",
    ("pull", "discovery-classify"): r"re-read the written discovery document yourself",
    (
        "pull",
        "manifest-baseline-diff",
    ): r"confirm the manifest's row count structurally",
    ("clone", "pack-transfer"): r"re-run `sha256sum -c`",
    ("pull", "pack-transfer"): r"re-run `sha256sum -c`",
    ("clone", "thumbnail-smoke-test"): r"re-run `wp db check`",
    ("pull", "thumbnail-smoke-test"): r"re-run `wp db check`",
}


@pytest.mark.parametrize("skill,name", sorted(RECHECK_PATTERN))
def test_skill_states_the_orchestrator_side_deterministic_recheck(
    skill: str, name: str
) -> None:
    """AC #2's other half: the issue's rule that the orchestrator "re-runs 1-2
    cheap deterministic spot checks itself" — never trusting a subagent's
    evidence block on its word alone — must survive as a literal sentence per
    phase. Without this, deleting the "Re-run `sha256sum -c` ... yourself" or
    "Re-run `wp db check` ... yourself" sentences (or their discovery/manifest
    equivalents) would leave every other test in this module green."""

    text = SKILLS[skill].read_text(encoding="utf-8")
    assert re.search(RECHECK_PATTERN[(skill, name)], text, re.IGNORECASE), (
        f"{skill} SKILL.md drops the orchestrator's own deterministic "
        f"re-check for `{name}`"
    )


def test_skill_states_the_delegation_architecture_and_the_fail_closed_rule() -> None:
    """AC #2: both SKILL.md files state the general delegation architecture
    once — subagents can never ask the operator anything, a result missing
    its evidence block is treated as failed regardless of its prose, and
    large payloads are routed to the scratchpad rather than crossing the
    agent boundary inline."""

    for skill, path in SKILLS.items():
        text = path.read_text(encoding="utf-8")
        assert re.search(r"never ask the operator", text, re.IGNORECASE), (
            f"{skill} SKILL.md does not state subagents can never ask the operator anything"
        )
        assert re.search(
            r"(?:missing|without) its evidence block[^.\n]*failed",
            text,
            re.IGNORECASE,
        ), f"{skill} SKILL.md does not state the missing-evidence-block-is-failed rule"
        assert re.search(r"scratchpad", text, re.IGNORECASE), (
            f"{skill} SKILL.md does not route large subagent payloads to the scratchpad"
        )


def test_spec_notes_the_delegation_architecture() -> None:
    """AC #3: docs/spec.md notes the delegation architecture briefly, naming
    every subagent in the roster."""

    spec = (REPO_ROOT / "docs" / "spec.md").read_text(encoding="utf-8")
    assert re.search(r"subagent", spec, re.IGNORECASE), (
        "spec.md never mentions the subagent-delegation architecture"
    )
    for name in ROSTER:
        assert name in spec, f"spec.md does not name the `{name}` subagent"
