# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Consistency test — the main extraction owns the file-part budget it packages
at, and only the main extraction (issue #77).

Extractor 0.7.0 accepts an optional ``chunk_size`` on ``POST /extractions``. A
client that sends nothing packages at whatever the host resolves for itself
through a constant-then-filter config seam no endpoint reports — a number that
decided whether the only completed production clone completed, and that lives
somewhere as invisible as an mu-plugin materialised from a code-snippet
collection. The client therefore sends the member, resolved through the ordinary
decision backbone and reported afterwards.

Nothing in ``skills/clone/scripts/`` builds any of the three ``POST
/extractions`` payloads — they are prose in the SKILLs and the role files — so
this suite is where the payload contract is enforced: the main extraction's
create carries the member, the preflight's and the bootstrap's do not (neither
packages a file part, so there is no file-part budget for them to carry), the
``honours`` list rides through the run the way ``api_version`` does, and the
member is sent whether or not that list names it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]

CLONE: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
PULL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"
EXTRACT_SUBMIT: Path = REPO_ROOT / "skills" / "clone" / "roles" / "extract-submit.md"
EXTRACT_SUBMIT_AGENT: Path = REPO_ROOT / "agents" / "extract-submit.md"
DISCOVERY_CLASSIFY: Path = (
    REPO_ROOT / "skills" / "clone" / "roles" / "discovery-classify.md"
)
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
IMPLEMENTATION_NOTES: Path = REPO_ROOT / "docs" / "implementation-notes.md"
CONTEXT: Path = REPO_ROOT / "CONTEXT.md"

SKILLS: tuple[tuple[str, Path], ...] = (("clone", CLONE), ("pull", PULL))

# Every surface that describes the main extraction's create payload.
SUBMIT_SURFACES: tuple[Path, ...] = (
    EXTRACT_SUBMIT,
    CLONE,
    PULL,
    SPEC,
    IMPLEMENTATION_NOTES,
)


def read(path: Path) -> str:
    """Read a documentation surface off disk — the docs are the contract here,
    since no helper builds these payloads."""

    return path.read_text(encoding="utf-8")


def preflight_step(path: Path) -> str:
    """The health check's download-preflight step, as prose. It submits exactly
    two structure-only tables and no files, so it packages no file part and has
    no file-part budget to name."""

    text = read(path)
    start = text.index("Preflight the download path")
    return text[start : text.index("\n", start)]


# --- The main extraction carries the member ----------------------------------


@pytest.mark.parametrize(
    "path", SUBMIT_SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_every_submit_surface_sends_the_file_part_budget(path: Path) -> None:
    """AC: the main extraction's payload carries ``chunk_size``. A surface that
    describes the create and omits the member describes a run packaged at
    whatever the host was quietly configured for."""

    assert "chunk_size" in read(path), (
        f"{path.relative_to(REPO_ROOT)} never tells the caller to submit a "
        "chunk_size — the run would package at the host's own invisible budget"
    )


def test_extract_submit_posts_the_member_on_the_wire() -> None:
    """The role whose steps actually POST carries the JSON member, not just
    prose — a SKILL that mentions the budget in prose alone changes no wire."""

    assert '"chunk_size": chunk_size' in read(EXTRACT_SUBMIT), (
        'the extract-submit role must put "chunk_size" on the POST body'
    )


def test_extract_submit_takes_the_budget_as_an_input() -> None:
    """The value is the orchestrator's resolved decision, handed to the role in
    its task envelope — never derived, guessed, or defaulted inside the role."""

    text = read(EXTRACT_SUBMIT)
    inputs = text[text.index("## Inputs") : text.index("## What to do")]
    assert "chunk_size" in inputs, (
        "extract-submit.md's Inputs must name chunk_size, so the value comes "
        "from the resolved plan rather than from inside the role"
    )


def test_the_agent_wrapper_names_the_budget_it_is_given() -> None:
    """The subagent definition's envelope description stays in step with the
    role's Inputs — a wrapper that names only the selection and the public key
    invites a caller to omit the budget."""

    assert "chunk_size" in read(EXTRACT_SUBMIT_AGENT)


def test_the_local_refusal_is_named_where_the_payload_is_built() -> None:
    """AC: a bad value is a local refusal, not a 422 from production. The
    resolver enforces it; the submit surface says so, so nobody reintroduces a
    hand-assembled value."""

    text = read(EXTRACT_SUBMIT)
    assert re.search(r"integer of at least 1", text), (
        "extract-submit.md must state the budget's range, so an out-of-range "
        "value is refused before production is asked to reject it"
    )


# --- The preflight and the bootstrap carry nothing ---------------------------


@pytest.mark.parametrize("skill, path", SKILLS)
def test_the_preflight_probe_names_no_file_part_budget(skill: str, path: Path) -> None:
    """AC: the preflight's payload is unchanged. It submits two structure-only
    tables and no files, so it packages no file part — the member would be
    meaningless there, not merely omitted."""

    assert "chunk_size" not in preflight_step(path), (
        f"the {skill} preflight step must not carry a file-part budget — it "
        "submits no files"
    )


def test_the_spec_preflight_step_names_no_file_part_budget() -> None:
    """The spec's own statement of the preflight stays a no-files probe."""

    assert "chunk_size" not in preflight_step(SPEC)


def test_the_bootstrap_payload_literal_carries_no_file_part_budget() -> None:
    """AC: the bootstrap's payload is unchanged. Its create names ``"files":
    []`` outright, so it packages no file part either."""

    text = read(DISCOVERY_CLASSIFY)
    assert '"files": [], "public_key": public_key }' in text, (
        "the bootstrap create literal moved; re-pin this test against it"
    )
    assert "chunk_size" not in text, (
        "the discovery-classify role must not carry a file-part budget — its "
        "bootstrap extraction submits no files"
    )


# --- The honours list rides through, and never gates the send ----------------


@pytest.mark.parametrize("skill, path", SKILLS)
def test_the_skills_carry_the_honours_list_through_the_run(
    skill: str, path: Path
) -> None:
    """AC: the ``honours`` list from the authenticated ``GET /status`` is carried
    through the run the same way ``api_version`` is — passed through from the
    health check, never re-fetched. Same plumbing, different call: the
    unauthenticated handshake reports only the version."""

    text = read(path)
    assert "honours" in text
    envelope = next(
        line for line in text.splitlines() if '"api_version": <the health check' in line
    )
    assert '"honours"' in envelope, (
        f"the {skill} discovery envelope must carry honours beside api_version"
    )
    health_check = text[
        text.index("## 1. Health check") : text.index("## 2. Discovery")
    ]
    assert "authenticated" in health_check


def test_the_discovery_role_takes_honours_as_a_pass_through_input() -> None:
    """The role assembles the envelope, so the list has to reach it as an input
    it passes through verbatim — never a second ``GET /status`` of its own."""

    text = read(DISCOVERY_CLASSIFY)
    inputs = text[text.index("## Inputs") : text.index("## What to do")]
    assert "honours" in inputs
    assert "never re-fetch" in text or "never re-fetched" in text


@pytest.mark.parametrize("skill, path", SKILLS)
def test_the_member_is_sent_whether_or_not_honours_names_it(
    skill: str, path: Path
) -> None:
    """AC: the member is sent whether or not it appears in ``honours``. The same
    discipline the ``state=all`` sweep already follows — the member is additive,
    and an Extractor that does not know it ignores it, so reading the list first
    would only invent a way to send nothing."""

    text = read(path)
    assert re.search(
        r"whether or not[^.]*honours|never[^.]*conditional on[^.]*honours",
        text,
    ), (
        f"the {skill} SKILL must state that chunk_size is sent unconditionally, "
        "never gated on the honours list"
    )


# --- The report tells the truth afterwards -----------------------------------


@pytest.mark.parametrize("skill, path", SKILLS)
def test_the_degraded_report_gains_the_ignored_member_bullet(
    skill: str, path: Path
) -> None:
    """AC: when ``honours`` does not name ``chunk_size``, the degraded-behaviours
    report gains a bullet stating that the member was sent and ignored, that the
    run was packaged at whatever the host is configured for, and that the remedy
    is upgrading production's Extractor — never a client-side workaround."""

    text = read(path)
    bullet = next(
        (line for line in text.splitlines() if line.startswith("- **`honours`")),
        None,
    )
    assert bullet is not None, (
        f"the {skill} degraded-behaviours list has no honours-keyed bullet"
    )
    assert "chunk_size" in bullet
    assert "ignored" in bullet
    assert "configured for" in bullet or "configured" in bullet


@pytest.mark.parametrize("skill, path", SKILLS)
def test_the_degraded_lead_in_does_not_suppress_the_new_bullet(
    skill: str, path: Path
) -> None:
    """The section's lead-in used to open "when it is below this client's
    ceiling", which suppressed the whole list on a host *at* the ceiling — which
    is exactly where the honours bullet fires. The lead-in has to key each
    bullet on its own condition instead."""

    text = read(path)
    lead_in = next(
        line
        for line in text.splitlines()
        if line.startswith("Report the Extractor API version")
    )
    suppressing = "when it is below this client's ceiling — name each behaviour"
    assert suppressing not in lead_in, (
        f"the {skill} degraded-behaviours lead-in still gates the whole list on "
        "the API version, suppressing the honours-keyed bullet on a host at the "
        "ceiling"
    )
    assert "there are four" in lead_in, (
        f"the {skill} lead-in still counts the old three degraded behaviours"
    )


@pytest.mark.parametrize("skill, path", SKILLS)
def test_the_report_names_the_budget_and_the_layer_it_came_from(
    skill: str, path: Path
) -> None:
    """AC: the run's report names the file-part budget the run asked for and the
    layer it came from, so the number is recoverable from the record afterwards
    rather than being a server-side mystery."""

    text = read(path)
    report = text[text.index("## 11. Cleanup and report") :]
    assert "file-part budget" in report, (
        f"the {skill} report never names the file-part budget the run asked for"
    )
    sentence = next(
        line
        for line in report.splitlines()
        if "file-part budget" in line and "layer" in line
    )
    assert "chunk_size" in sentence


# --- The budget is a saved-plan key and an ordinary gate ----------------------


def test_the_spec_decision_table_carries_the_budget_row() -> None:
    """The gate joins the ordered decision list like every other one (ADR-0005),
    so the spec's table of decisions and their recommended defaults names it,
    with the measured-good default spelled out."""

    text = read(SPEC)
    table = text[text.index("### The decisions and their recommended defaults") :]
    table = table[: table.index("### Thumbnails and regeneration")]
    row = next(
        (line for line in table.splitlines() if "file-part budget" in line.lower()),
        None,
    )
    assert row is not None, "spec.md's decision table has no file-part budget row"
    assert "262144" in row or "256 KB" in row


def test_the_spec_persistent_config_enumerates_the_budget() -> None:
    """The saved plan is where a deliberately tuned site records its number —
    the whole point of the change — so the persistent-config prose names it."""

    sentence = next(
        line
        for line in read(SPEC).splitlines()
        if line.startswith("- `.kntnt-wp-skills.json`")
    )
    assert "file-part budget" in sentence


def test_the_illustrative_saved_plan_shows_the_budget() -> None:
    """``docs/implementation-notes.md``'s illustrative shape is the JSON copy of
    the saved-plan key list; a key missing there is a key nobody discovers."""

    text = read(IMPLEMENTATION_NOTES)
    block = text[text.index("## Saved plan — illustrative shape") :]
    block = block[: block.index("```", block.index("```jsonc") + 8)]
    assert '"chunk_size"' in block


def test_the_glossary_defines_the_file_part_budget() -> None:
    """CONTEXT.md is the project glossary and its terms are used verbatim in code
    and prose, so a new term lands there rather than being coined per surface."""

    text = read(CONTEXT)
    assert "**File-part budget**" in text
    assert "chunk_size" in text
