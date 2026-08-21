"""Role-delegation consistency test — bind the transfer engine's role files to
the ``clone``/``pull`` orchestration (issues #13 and #52).

A full clone run pushed the orchestrating agent's own context past ~300k
tokens, almost entirely transport noise (REST round-trips, curl/download
output, thumbnail-regeneration warning spam) rather than decisions. The fix
gives each heavy phase its own **role** — instructions any competent agent can
execute — and has both ``SKILL.md`` files hand that phase off to it, with a
structured **evidence block** (exit codes, artifact paths + SHA256, row/file
counts, ``DONE``/``FAILED`` markers) the orchestrator validates
deterministically rather than trusting a second LLM's prose.

Since issue #52 each role is written once, at ``skills/clone/roles/<name>.md``,
so a harness with no subagents can execute it inline. The definitions under
``agents/`` remain — Claude Code loads its subagents from there and nowhere
else — but carry only their pinned frontmatter and a pointer to the role file:
a subagent and an inline executor must follow the same procedure, which they
can only be relied on to do while that procedure exists in exactly one place.

This is the same kind of anti-drift binding as
``test_help_docs_consistency.py`` and the orchestration-consistency suites: it
holds the role files, the wrapper definitions, and the two ``SKILL.md`` files
to the architecture the issues describe, so a rewrite that drops the pin,
forgets a phase's evidence-block contract, lets a role's instructions permit it
to ask the operator something, or copies procedure back into a wrapper reddens
here rather than drifting silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
AGENTS_DIR: Path = REPO_ROOT / "agents"
ROLES_DIR: Path = REPO_ROOT / "skills" / "clone" / "roles"
SKILLS: dict[str, Path] = {
    "clone": REPO_ROOT / "skills" / "clone" / "SKILL.md",
    "pull": REPO_ROOT / "skills" / "pull" / "SKILL.md",
}

# Issue #13's phase table: subagent name -> its pinned model/effort and which
# skills delegate a phase to it. Both skills delegate every phase — clone's
# "manifest + baseline diff" phase runs the same subagent in manifest-only
# mode (it has no baseline to diff against), and its "thumbnail regen + smoke
# test" phase is delegated twice (regeneration, then the verify step) to the
# same definition. Issue #58 split the old ``extract-transfer`` phase in two:
# the multi-hour poll between the halves is the orchestrator's own background
# job, because a subagent's process tree does not outlive its return and twice
# took a live poll down with it.
ROSTER: dict[str, dict[str, object]] = {
    "discovery-classify": {
        "model": "sonnet",
        "effort": "low",
        "skills": ("clone", "pull"),
    },
    "extract-submit": {
        "model": "sonnet",
        "effort": "low",
        "skills": ("clone", "pull"),
    },
    "extract-transfer": {
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


def _role_text(name: str) -> str:
    """A role file's whole text. Role files carry no frontmatter: they are
    instructions, not a harness's agent definition, and every harness that runs
    one reads it as plain Markdown."""

    return (ROLES_DIR / f"{name}.md").read_text(encoding="utf-8")


def _role_anchor(name: str) -> str:
    """The literal handoff sentence a ``SKILL.md`` must carry to hand a phase
    to the named role — whichever of the three execution tiers actually runs
    it."""

    return f"Run the `{name}` role"


@pytest.mark.parametrize("name", sorted(ROSTER))
def test_every_rostered_agent_has_a_definition_file(name: str) -> None:
    """Every phase issue #13's table names ships a real agent definition under
    ``agents/``."""

    assert (AGENTS_DIR / f"{name}.md").is_file(), f"agents/{name}.md is missing"


@pytest.mark.parametrize("name", sorted(ROSTER))
def test_every_rostered_agent_has_a_role_file(name: str) -> None:
    """Every phase also ships the role itself — the harness-independent
    instructions a spawned subagent or an inline executor follows (issue
    #52)."""

    assert (ROLES_DIR / f"{name}.md").is_file(), (
        f"skills/clone/roles/{name}.md is missing, so only a Claude Code "
        "subagent could run this phase"
    )


def test_roles_directory_carries_no_stray_files() -> None:
    """The roster is the complete set of roles too: an orphaned role file would
    be procedure nothing executes and nothing keeps current."""

    assert ROLES_DIR.is_dir(), "skills/clone/roles/ directory does not exist"
    present = {path.stem for path in ROLES_DIR.glob("*.md")}
    assert present == set(ROSTER), f"roles/ carries an unexpected set: {present}"


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
def test_role_states_the_evidence_block_and_never_ask_rule(name: str) -> None:
    """Every role's instructions carry the evidence-block contract (checksums,
    exit-code-shaped fields, DONE/FAILED markers, a scratchpad routing rule)
    and the rule that whoever runs it can never ask the operator anything — a
    role runs once against a task envelope and returns, it does not gate."""

    body = _role_text(name).lower()
    for term in ("evidence block", "scratchpad", "sha256", "done", "failed"):
        assert term in body, f"roles/{name}.md omits {term!r}"
    assert re.search(r"never ask the operator", body), (
        f"roles/{name}.md does not state the never-ask-the-operator rule"
    )


@pytest.mark.parametrize("name", sorted(ROSTER))
def test_wrapper_agent_points_at_its_role_file(name: str) -> None:
    """Claude Code loads a subagent from ``agents/`` and nowhere else, so the
    definition stays — but as a pointer: it names the role file by a path that
    resolves inside a plugin install, and says to follow it."""

    body = _body(AGENTS_DIR / f"{name}.md")
    assert f"${{CLAUDE_PLUGIN_ROOT}}/skills/clone/roles/{name}.md" in body, (
        f"agents/{name}.md does not name its role file at a path that resolves "
        "inside a plugin install"
    )
    assert re.search(r"read .*follow|follow .*exactly", body, re.IGNORECASE), (
        f"agents/{name}.md does not tell the subagent to follow the role file"
    )


@pytest.mark.parametrize("name", sorted(ROSTER))
def test_wrapper_agent_duplicates_no_procedure(name: str) -> None:
    """The procedure exists in exactly one place. A wrapper that grew its own
    copy of a step would let the subagent path and the inline path drift apart
    silently — which is the whole failure mode the single-sourcing prevents."""

    wrapper = _body(AGENTS_DIR / f"{name}.md")
    assert len(wrapper.strip()) < 1200, (
        f"agents/{name}.md's body is {len(wrapper.strip())} characters — long "
        "enough to be carrying procedure that belongs in the role file"
    )

    # Shingled overlap, not an eyeball: any 80-character run of the role's own
    # prose reappearing in the wrapper is duplication whatever it is called.
    role = " ".join(_role_text(name).split())
    flat = " ".join(wrapper.split())
    duplicated = [
        role[index : index + 80]
        for index in range(0, len(role) - 80, 40)
        if role[index : index + 80] in flat
    ]
    assert not duplicated, (
        f"agents/{name}.md repeats role prose verbatim: {duplicated[:2]}"
    )


@pytest.mark.parametrize(
    "skill,name",
    [(skill, name) for name, info in ROSTER.items() for skill in info["skills"]],
)
def test_skill_delegates_the_phase_with_its_evidence_block_contract(
    skill: str, name: str
) -> None:
    """AC #1 and #2: each SKILL.md names the role it hands a phase to, right
    where that phase already lives, and states the evidence-block fields the
    orchestrator checks there — never a bare mention floating apart from the
    step it belongs to."""

    text = SKILLS[skill].read_text(encoding="utf-8")
    anchor = _role_anchor(name)
    pos = text.find(anchor)
    assert pos != -1, f"{skill} SKILL.md never hands a phase to the `{name}` role"

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

    A role may be run more than once per ``SKILL.md``
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
    "extract-submit": ("sha256", "counts"),
    "extract-transfer": ("sha256", "byte size"),
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
    anchor = _role_anchor(name).lower()
    windows = _delegation_windows(text, anchor)
    assert windows, f"{skill} SKILL.md never hands a phase to the `{name}` role"

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
    ("clone", "extract-submit"): r"re-read the written job record yourself",
    ("pull", "extract-submit"): r"re-read the written job record yourself",
    ("clone", "extract-transfer"): r"re-run `scripts/dump_sanity\.py`",
    ("pull", "extract-transfer"): r"re-run `\.\./clone/scripts/dump_sanity\.py`",
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


def test_manifest_baseline_diff_role_forwards_the_unreadable_field() -> None:
    """The delegated path must not be a hole in issue #18's fail-loud guard:
    the ``manifest-baseline-diff`` role's step 2 constructs the
    ``scripts/filter_manifest.py`` payload itself (the orchestrator never sees
    it), so if that construction omits ``"unreadable"``, the helper's
    absent-field-means-clean-walk default lets a permission-denied production
    subtree sail through undetected in every delegated run — even though both
    ``SKILL.md`` files' own (non-delegated) payload descriptions already
    include it. This binds the agent definition to the same payload shape."""

    body = _role_text("manifest-baseline-diff")
    assert '"unreadable"' in body, (
        "the manifest-baseline-diff role's filter_manifest.py payload does "
        "not forward the manifest's \"unreadable\" field"
    )


def test_discovery_classify_role_deletes_the_unsealed_bootstrap_dump() -> None:
    """Issue #49: the bootstrap dump holds real user and subscriber rows in
    cleartext, so ``discovery-classify``'s own contract must state — not just
    imply via the generic ``consume`` sentence — that the unsealed dump, its
    sealed container, and the bootstrap's ephemeral private key are deleted
    from the scratchpad immediately once ``bootstrap_parse.py`` has consumed
    them, and that the evidence block proves it via
    ``bootstrap_artifacts_deleted`` rather than trusting prose alone."""

    body = _role_text("discovery-classify")

    assert re.search(r"bootstrap_parse\.py.{0,400}delete", body, re.DOTALL) or re.search(
        r"delete.{0,400}bootstrap_parse\.py", body, re.DOTALL
    ), "the discovery-classify role never ties bootstrap_parse.py to deleting its artifacts"
    assert "sealed container" in body, (
        "the discovery-classify role's cleanup step omits the sealed container"
    )
    assert "private key" in body, (
        "the discovery-classify role's cleanup step omits the ephemeral private key"
    )
    assert "bootstrap_artifacts_deleted" in body, (
        "the discovery-classify role's evidence block omits bootstrap_artifacts_deleted"
    )
    assert re.search(r"never leave.{0,200}bootstrap", body, re.IGNORECASE | re.DOTALL), (
        "the discovery-classify role's hard rules never state the bootstrap-cleanup rule"
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


# Issue #44: the three agent definitions whose task envelope carries the
# Extractor credential — the ones the issue names as taking
# ``application_password`` by literal value.
CREDENTIAL_BEARING_AGENTS: tuple[str, ...] = (
    "discovery-classify",
    "extract-submit",
    "extract-transfer",
    "manifest-baseline-diff",
)


@pytest.mark.parametrize("name", CREDENTIAL_BEARING_AGENTS)
def test_agent_input_is_a_credential_reference_not_a_password_value(
    name: str,
) -> None:
    """Issue #44: the orchestrator must never read the Application Password's
    value into its own context to build a task envelope. Each credential-
    bearing agent's ``## Inputs`` section names a ``credential`` reference
    (Keychain service+account, or an env-var name) — never a literal
    ``application_password`` field carrying the secret itself."""

    body = _role_text(name)
    assert "`credential`" in body, (
        f"roles/{name}.md's Inputs section does not name a `credential` reference"
    )
    assert "application_password" not in body, (
        f"roles/{name}.md still takes `application_password` as a literal input "
        "— the secret's value must never transit the orchestrator's context"
    )


@pytest.mark.parametrize("name", CREDENTIAL_BEARING_AGENTS)
def test_agent_resolves_the_credential_itself_in_a_subshell(name: str) -> None:
    """Issue #44: resolution discipline. Each credential-bearing agent
    resolves its own ``credential`` reference, inside the authenticated
    call's own subshell, and never prints or logs the resolved secret."""

    body = _role_text(name).lower()
    assert "subshell" in body, (
        f"roles/{name}.md does not state that the credential is resolved inside "
        "a subshell"
    )
    assert re.search(r"never print|never log", body), (
        f"roles/{name}.md does not state the never-print/never-log rule for the "
        "resolved secret"
    )


def test_no_agent_definition_carries_a_literal_application_password_input() -> None:
    """Belt-and-braces sweep: no shipped agent definition or role file —
    rostered or not — still takes the Application Password by value."""

    for path in (*AGENTS_DIR.glob("*.md"), *ROLES_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        assert "application_password" not in text, (
            f"{path.name} still carries a literal `application_password` input"
        )


# Issue #52's three execution tiers, in the order a document must offer them:
# the Claude Code subagent, any other harness's spawned task, and — when the
# harness has neither — the orchestrator running the role file itself. Keyed by
# the phrase each tier must be recognisable by in both SKILL.md files.
EXECUTION_TIERS: tuple[tuple[str, str], ...] = (
    ("claude code subagent", r"task tool"),
    ("spawned task in another harness", r"spawn"),
    ("inline execution", r"execute (?:each|the) role file'?s? instructions yourself"),
)


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_skill_offers_all_three_execution_tiers(skill: str) -> None:
    """Issue #52: neither skill may be wired to one harness. Each states the
    same three-tier rule — delegate to the pinned subagent under Claude Code,
    else spawn one per role, else run the role file inline — so a harness
    without subagents degrades to slower rather than to broken."""

    text = SKILLS[skill].read_text(encoding="utf-8").lower()
    for tier, pattern in EXECUTION_TIERS:
        assert re.search(pattern, text), (
            f"{skill} SKILL.md never offers the {tier} tier"
        )
    assert "kntnt-wp-skills:" in text, (
        f"{skill} SKILL.md's first tier does not name the plugin-namespaced "
        "subagents Claude Code loads"
    )


# Where each skill reaches the role files from: `clone` owns them, `pull`
# reaches its sibling's copy, which is what keeps the procedure single-sourced
# across the two skills as well as across the tiers.
ROLE_PATH_PREFIX: dict[str, str] = {"clone": "roles/", "pull": "../clone/roles/"}


@pytest.mark.parametrize("skill,name", sorted((s, n) for s in SKILLS for n in ROSTER))
def test_skill_names_the_role_file_it_hands_the_phase_to(skill: str, name: str) -> None:
    """The tier-2 and tier-3 executors need the file, not just the phase name:
    each handoff names the role file at a path that resolves from the skill
    directory it is read in."""

    text = SKILLS[skill].read_text(encoding="utf-8")
    expected = f"{ROLE_PATH_PREFIX[skill]}{name}.md"
    assert expected in text, (
        f"{skill} SKILL.md hands a phase to `{name}` without naming {expected}"
    )
