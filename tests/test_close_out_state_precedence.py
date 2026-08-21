"""Close-out state-precedence consistency test — issue #53, plan 010.

Two defensible rules combined into a destructive one. The `extract-transfer`
role says a result without an evidence block is `FAILED`; both SKILLs' close-out
maps a `FAILED` whose stall window was exhausted to `DELETE /extractions/{id}`.
Together they let a subagent that returned **nothing at all** — no verdict, no
evidence, no claim about the job — route the orchestrator onto the branch that
cancels a healthy extraction. An absent verdict is the least informative return
possible, and the close-out read it as the most specific case.

It happened on both production runs. On 2026-08-19 the subagent returned with
no evidence block after two and a half hours while the job was `running` with
`chunks_done` climbing, and it went on to complete all 48,578 files. The only
thing between that run and a `DELETE` was the orchestrator querying the job by
hand, on its own initiative, contrary to the written close-out.

The fix is one sentence of ordering, so this suite is its anti-drift binding: on
any `FAILED` **or absent or malformed** verdict, one `GET /extractions/{id}`
comes before the case selection, and a job whose own state says it is advancing
selects no case at all. Like the sibling consistency suites, every assertion
here is a regex over Markdown — it binds the *prose* both orchestrators read,
never a behaviour, and the anchors are the literal rule text rather than a
snippet of this suite's own wording, so a faithful rewrite stays green while a
regression (the ordering inverted, the absent case dropped, the two SKILLs
drifting apart) reddens.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

CLONE_SKILL: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
PULL_SKILL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"
EXTRACT_TRANSFER_ROLE: Path = (
    REPO_ROOT / "skills" / "clone" / "roles" / "extract-transfer.md"
)
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
ADR: Path = (
    REPO_ROOT
    / "docs"
    / "adr"
    / "0022-close-the-exposure-window-on-every-failure-path.md"
)

# The subsection both SKILLs own the close-out in, and the level-2 heading that
# ends it. The rule under test is an ordering *within* this section, so every
# positional assertion below is made against the section rather than the whole
# document — an anchor that matched somewhere else entirely would otherwise
# satisfy an ordering the close-out itself does not carry.
CLOSE_OUT_HEADING: str = "### Closing out a failed phase"

# The two SKILLs that carry the close-out. They state it in wording that must
# stay identical — the section names no path and no section number, so there is
# nothing legitimate to differ about between them.
CLOSE_OUT_SKILLS: tuple[tuple[str, Path], ...] = (
    ("clone SKILL.md", CLONE_SKILL),
    ("pull SKILL.md", PULL_SKILL),
)

# The re-query rule's own lead-in, and the first close-out case. The rule binds
# only if it precedes the case selection: read afterwards it is a footnote to a
# `DELETE` that has already gone out.
RE_QUERY_ANCHOR: str = r"\*\*Re-query the job before choosing a case\.\*\*"
FIRST_CASE_ANCHOR: str = r"\*\*The job never reached `ready`\*\*"

# The clauses the rule is worthless without. The absent-verdict clause is the
# one that bit twice: a `FAILED`-only rule leaves silence routed exactly where
# it was. The stall-window clause names the false inference itself, and the
# no-case clause is the consequence — an advancing job is not cancelled.
REQUIRED_CLAUSES: tuple[tuple[str, str], ...] = (
    ("the absent-verdict clause", r"absent or malformed verdict"),
    ("the outranking clause", r"outranks the subagent's claim"),
    ("the advancing-job clause", r"select no close-out case"),
    (
        "the not-a-stall-window clause",
        r"is \*\*not\*\* evidence of an exhausted stall window",
    ),
)


def _close_out_section(path: Path, doc_name: str) -> str:
    """Return the *Closing out a failed phase* subsection of a SKILL document.

    Fails loudly when the heading is gone rather than returning an empty string:
    a positional suite whose section silently vanished would pass while
    enforcing nothing, which is the one failure mode this indirection could
    introduce.
    """

    text = path.read_text(encoding="utf-8")
    _, heading, after = text.partition(CLOSE_OUT_HEADING)
    assert heading, f"{doc_name} no longer carries a '{CLOSE_OUT_HEADING}' section"
    section, _, _ = after.partition("\n## ")
    return section


def _pos(text: str, pattern: str, label: str, doc_name: str) -> int:
    """First match position of ``pattern`` in ``text``, failing loudly with the
    missing anchor when it is absent — so an ordering assertion never silently
    passes on a ``-1`` from an anchor that moved."""

    match = re.search(pattern, text)
    assert match is not None, f"{doc_name} is missing the {label} anchor /{pattern}/"
    return match.start()


def _re_query_paragraph(path: Path, doc_name: str) -> str:
    """Return the single paragraph stating the re-query rule, so the two SKILLs
    can be compared on the rule itself rather than on the whole section."""

    section = _close_out_section(path, doc_name)
    start = _pos(section, RE_QUERY_ANCHOR, "re-query rule", doc_name)
    paragraph, _, _ = section[start:].partition("\n\n")
    return paragraph


@pytest.mark.parametrize("doc_name, path", CLOSE_OUT_SKILLS)
def test_re_query_precedes_the_close_out_cases(doc_name: str, path: Path) -> None:
    """The re-query of `GET /extractions/{id}` is stated ahead of the numbered
    close-out cases, so the job's own state is known before any case — the
    cancelling one above all — is chosen."""

    section = _close_out_section(path, doc_name)
    re_query_pos = _pos(section, RE_QUERY_ANCHOR, "re-query rule", doc_name)
    first_case_pos = _pos(section, FIRST_CASE_ANCHOR, "first close-out case", doc_name)
    assert re_query_pos < first_case_pos, (
        f"{doc_name} states the re-query after the close-out cases — it has to "
        "come first, or the job is cancelled before anyone asks the server "
        "whether it is still advancing"
    )


@pytest.mark.parametrize("doc_name, path", CLOSE_OUT_SKILLS)
def test_the_re_query_rule_names_the_endpoint_it_queries(
    doc_name: str, path: Path
) -> None:
    """The rule names `GET /extractions/{id}` itself. "Check the job's state" is
    guidance; the endpoint is an instruction."""

    paragraph = _re_query_paragraph(path, doc_name)
    assert "GET /extractions/{id}" in paragraph, (
        f"{doc_name}'s re-query rule never names GET /extractions/{{id}} — the "
        "call it requires has to be the call it names"
    )


@pytest.mark.parametrize("clause_name, pattern", REQUIRED_CLAUSES)
@pytest.mark.parametrize("doc_name, path", CLOSE_OUT_SKILLS)
def test_the_re_query_rule_carries_every_required_clause(
    doc_name: str, path: Path, clause_name: str, pattern: str
) -> None:
    """The rule covers an absent verdict, not only a `FAILED` one; it says the
    job's state outranks the subagent's claim; it stops an advancing job being
    routed onto any case at all; and it names the false inference — silence is
    not an exhausted stall window — that put a healthy run one instruction away
    from a `DELETE`, twice."""

    paragraph = _re_query_paragraph(path, doc_name)
    assert re.search(pattern, paragraph), (
        f"{doc_name}'s re-query rule is missing {clause_name} (/{pattern}/)"
    )


def test_both_skills_state_the_rule_identically() -> None:
    """`clone` and `pull` carry the rule word for word. The paragraph names no
    path and no section number, so any difference between them is drift — and a
    rule stated two ways is two rules, which is how the poll discipline came to
    need a canonical document of its own."""

    clone_paragraph = _re_query_paragraph(CLONE_SKILL, "clone SKILL.md")
    pull_paragraph = _re_query_paragraph(PULL_SKILL, "pull SKILL.md")
    assert clone_paragraph == pull_paragraph, (
        "clone and pull state the close-out re-query rule differently; they must "
        "be identical, since the paragraph carries nothing that legitimately "
        "differs between the two skills"
    )


@pytest.mark.parametrize("doc_name, path", CLOSE_OUT_SKILLS)
def test_the_re_query_never_delays_the_case_two_consume(
    doc_name: str, path: Path
) -> None:
    """Case 2 — a complete download whose unseal failed — still consumes, and
    the rule says outright that the re-query does not hold it up. The download
    already succeeded there, the local copy is complete, and delaying the
    consume would widen the exposure window on a live client site that
    ADR-0022 exists to close."""

    section = _close_out_section(path, doc_name)
    assert "POST /extractions/{id}/consume" in section, (
        f"{doc_name}'s close-out no longer consumes a downloaded-but-unsealable job"
    )
    assert re.search(r"never postpones case 2's `consume`", section), (
        f"{doc_name}'s re-query rule does not say it leaves case 2's consume "
        "alone — without that, the guard against a cancel reads as a delay "
        "before every close-out"
    )


def test_the_role_binds_its_verdict_to_its_own_work() -> None:
    """`extract-transfer` says a verdictless return is read as `FAILED`. Beside
    that, the role now states what the verdict is *about*: the subagent's own
    work, never the job's state, which the orchestrator settles by asking the
    server. Without it the two documents read as contradicting each other and a
    future reader picks one."""

    body = EXTRACT_TRANSFER_ROLE.read_text(encoding="utf-8")
    assert re.search(r"binds your own work, never the job's state", body), (
        "the extract-transfer role does not scope its verdict to its own work — "
        "the close-out's re-query and the role's verdictless-return rule then "
        "read as a contradiction"
    )


def test_the_spec_states_the_precedence() -> None:
    """The specification carries the general shape once, rather than leaving it
    to be re-derived per phase: where a local claim and the remote authority
    disagree about remote state, the remote authority wins."""

    text = SPEC.read_text(encoding="utf-8")
    assert re.search(r"the remote authority wins", text), (
        "docs/spec.md does not state the local-claim-versus-remote-authority "
        "precedence the close-out's re-query is one instance of"
    )
    assert re.search(r"absent verdict", text), (
        "docs/spec.md's close-out paragraph does not cover an absent verdict, "
        "only a reported failure"
    )


def test_the_adr_records_the_ordering() -> None:
    """ADR-0022 owns the close-out decision, so the ordering that now guards it
    is recorded there rather than only in the SKILLs it constrains."""

    text = ADR.read_text(encoding="utf-8")
    assert re.search(r"absent verdict", text), (
        "ADR-0022 does not record that an absent verdict is re-queried before "
        "any cancelling action — the decision record and the rule have drifted"
    )


# ---------------------------------------------------------------------------
# Issue #65 — the case is derived, never read off a reported phase.
#
# The ordering above stopped silence being read as case 1. It left a hole one
# step further in: cases 2, 3 and 4 are all `ready` jobs, and the only thing
# telling them apart was a `failure_phase` that exactly one of the three roles
# entering this close-out ever sends. An absent verdict carries none by
# definition — that is what makes it absent — and a well-formed `FAILED` from
# `discovery-classify` or `extract-submit` carries none either, because neither
# evidence block has the field at all. Three routes therefore reached a state
# the close-out had no instruction for, on a job that may hold hours of
# extraction.
#
# The fix is that the close-out establishes the state itself, from the job's own
# state and this machine's own state, and demotes the reported phase to a hint.
# These assertions are the anti-drift binding for that derivation: the two
# authorities, the fixed paths the probe reads, and — the criterion the whole
# thing exists to satisfy — that every combination has a stated outcome rather
# than one a reader is left to infer.
# ---------------------------------------------------------------------------

# The derivation's own lead-ins and the clauses that make it a derivation rather
# than a second field to trust.
DERIVATION_CLAUSES: tuple[tuple[str, str], ...] = (
    ("the derivation's lead-in", r"\*\*Derive the case; never read it off a reported phase\.\*\*"),
    ("the demotion of the reported phase", r"hint, never the selector"),
    ("the tie-break between hint and derivation", r"the derived state wins"),
    ("the local-state authority", r"this machine's own state"),
    ("the three-role scope", r"`discovery-classify` and `extract-submit` have no such field"),
)

# The probe's fixed targets. A probe asking *was a sealed container downloaded?*
# needs a name as well as a directory, and the answer is only trustworthy if a
# half-downloaded container cannot answer to the same name as a whole one.
PROBE_ANCHORS: tuple[tuple[str, str], ...] = (
    ("the main container's fixed path", r"`<scratchpad>/extract\.container`"),
    ("the in-flight download's own name", r"`<scratchpad>/extract\.container\.part`"),
    ("the completed-download rename", r"renamed to `<scratchpad>/extract\.container`"),
    ("the reassembled dump's fixed path", r"`<scratchpad>/extract\.sql`"),
    ("the unsealed files tree's fixed path", r"`<scratchpad>/extract-files/`"),
    (
        "the bootstrap job's globbed layout",
        r"`<scratchpad>/discovery-classify-\*/bootstrap\.container`",
    ),
)

# Every value the job's own state can take when the close-out asks, plus the two
# answers that are not a state at all. The completeness criterion is that each
# one has a stated outcome in the section.
JOB_STATE_ROWS: tuple[tuple[str, str], ...] = (
    ("a queued job", r"`queued`"),
    ("a running job", r"`running`"),
    ("a ready job", r"`ready`"),
    ("a failed job", r"`failed`"),
    ("an already-consumed job", r"`consumed`"),
    ("a confirmed-vanished job", r"confirmed-vanished job"),
    ("a re-query that could not be answered", r"could not be answered"),
)

# The three outcomes that are not one of the four cases. Each is named in full,
# because "no case" without a reason reads as an omission rather than a
# decision — and one of them, the advancing job, is #53's whole point.
NO_CASE_OUTCOMES: tuple[tuple[str, str], ...] = (
    ("the advancing job", r"\*\*No case — resume polling\.\*\*"),
    ("the already-consumed job", r"\*\*No case — the job is already accounted for\.\*\*"),
    ("the unanswerable re-query", r"\*\*No case — the job's state is unknown\.\*\*"),
)


@pytest.mark.parametrize("clause_name, pattern", DERIVATION_CLAUSES)
@pytest.mark.parametrize("doc_name, path", CLOSE_OUT_SKILLS)
def test_the_close_out_derives_its_case(
    doc_name: str, path: Path, clause_name: str, pattern: str
) -> None:
    """The close-out establishes the failed job's phase for itself rather than
    selecting a case from a field the reporting role may never have sent."""

    section = _close_out_section(path, doc_name)
    assert re.search(pattern, section), (
        f"{doc_name}'s close-out is missing {clause_name} (/{pattern}/)"
    )


@pytest.mark.parametrize("anchor_name, pattern", PROBE_ANCHORS)
@pytest.mark.parametrize("doc_name, path", CLOSE_OUT_SKILLS)
def test_the_probe_has_a_defined_place_to_look(
    doc_name: str, path: Path, anchor_name: str, pattern: str
) -> None:
    """A derivation from local state is only as good as the paths it reads. Each
    artifact has one fixed name, and an incomplete download answers to a
    different one — otherwise a truncated container would select the consume
    that destroys the only whole copy."""

    section = _close_out_section(path, doc_name)
    assert re.search(pattern, section), (
        f"{doc_name}'s close-out probe is missing {anchor_name} (/{pattern}/)"
    )


@pytest.mark.parametrize("row_name, pattern", JOB_STATE_ROWS)
@pytest.mark.parametrize("doc_name, path", CLOSE_OUT_SKILLS)
def test_every_job_state_has_a_stated_outcome(
    doc_name: str, path: Path, row_name: str, pattern: str
) -> None:
    """The completeness criterion, checked the only way prose can be: every
    answer the re-query can give is named in the section that has to act on
    it."""

    section = _close_out_section(path, doc_name)
    assert re.search(pattern, section), (
        f"{doc_name}'s close-out never says what happens for {row_name} "
        f"(/{pattern}/) — an unnamed state is an undefined one"
    )


@pytest.mark.parametrize("outcome_name, pattern", NO_CASE_OUTCOMES)
@pytest.mark.parametrize("doc_name, path", CLOSE_OUT_SKILLS)
def test_the_no_case_outcomes_are_stated_as_decisions(
    doc_name: str, path: Path, outcome_name: str, pattern: str
) -> None:
    """Selecting no case is an outcome, not a gap. Each of the three says so in
    words, so a reader can tell a decision from an omission."""

    section = _close_out_section(path, doc_name)
    assert re.search(pattern, section), (
        f"{doc_name}'s close-out does not state {outcome_name} as an explicit "
        f"no-case outcome (/{pattern}/)"
    )


@pytest.mark.parametrize("doc_name, path", CLOSE_OUT_SKILLS)
def test_case_four_is_an_outcome_of_the_consume_not_a_precondition(
    doc_name: str, path: Path
) -> None:
    """A `ready` job that was downloaded and unsealed presents identically on
    disk whether the consume was never attempted (case 2) or attempted and
    refused six times (case 4). No probe separates them, so the close-out does
    not try: it attempts the consume, and the refusal *is* case 4."""

    section = _close_out_section(path, doc_name)
    assert re.search(r"that refusal is \*\*case 4\*\*", section), (
        f"{doc_name}'s close-out still presents case 4 as a state to detect "
        "rather than as the outcome of attempting case 2's consume"
    )


def test_both_skills_state_the_whole_subsection_identically() -> None:
    """The re-query paragraph was pinned for identity; the derivation makes the
    whole subsection worth pinning. It names no path and no section number that
    legitimately differs between the two skills, so any difference is drift —
    and the criterion the ticket states is about the subsection, not one
    paragraph of it."""

    clone_section = _close_out_section(CLONE_SKILL, "clone SKILL.md")
    pull_section = _close_out_section(PULL_SKILL, "pull SKILL.md")
    assert clone_section == pull_section, (
        "clone and pull have drifted apart on the *Closing out a failed phase* "
        "subsection; it carries nothing that legitimately differs between them"
    )


def test_the_role_fixes_the_container_filename() -> None:
    """`extract-transfer` downloads to a name the probe can ask about, and only
    a whole container ever reaches it. Before this, step 3 said only "into
    `<scratchpad_dir>`" — no target, no convention — so *was a sealed container
    downloaded?* had no filename to ask about."""

    body = EXTRACT_TRANSFER_ROLE.read_text(encoding="utf-8")
    assert "<scratchpad_dir>/extract.container.part" in body, (
        "the extract-transfer role does not download to its own in-flight name"
    )
    assert re.search(
        r"rename it to `<scratchpad_dir>/extract\.container`", body
    ), (
        "the extract-transfer role does not rename the finished download to the "
        "fixed name the close-out probes for — a partial container answering to "
        "the whole one's name would select the consume"
    )
    assert "<scratchpad_dir>/extract.sql" in body, (
        "the extract-transfer role does not write the reassembled dump to the "
        "fixed path the close-out probes for"
    )


def test_the_role_demotes_its_failure_phase_to_a_hint() -> None:
    """The vocabulary stays — it is useful corroboration and it belongs in the
    run record — but the role says outright that it is no longer what the
    close-out selects on, so the two documents cannot read as rivals."""

    body = EXTRACT_TRANSFER_ROLE.read_text(encoding="utf-8")
    assert re.search(r"a \*\*hint\*\*", body), (
        "the extract-transfer role still presents `failure_phase` as the field "
        "the close-out picks its case from"
    )


def test_the_bootstrap_container_has_one_layout_across_every_surface() -> None:
    """Three surfaces claimed two layouts for the bootstrap container: both
    SKILLs' §3 put it directly under the scratchpad, the role put it in a
    randomly named working directory beneath it. A probe cannot read two
    layouts, so the SKILLs now name the one the role actually uses."""

    role = (
        REPO_ROOT / "skills" / "clone" / "roles" / "discovery-classify.md"
    ).read_text(encoding="utf-8")
    assert "<work_dir>/bootstrap.container" in role, (
        "the discovery-classify role no longer names its bootstrap container"
    )
    for doc_name, path in CLOSE_OUT_SKILLS:
        text = path.read_text(encoding="utf-8")
        assert "<scratchpad>/discovery-classify-<stamp>/bootstrap.container" in text, (
            f"{doc_name} still puts the bootstrap container directly under the "
            "scratchpad, where the discovery-classify role never writes it"
        )


def test_the_spec_states_the_derivation() -> None:
    """`AGENTS.md` calls the spec the single source of truth for the build, and
    it states all four close-out cases. A derivation recorded only in the two
    SKILLs would leave the source of truth describing the selector it
    replaced."""

    text = SPEC.read_text(encoding="utf-8")
    assert re.search(r"hint, never the selector", text), (
        "docs/spec.md still presents the reported `failure_phase` as what the "
        "close-out selects its case from"
    )
    assert "extract.container" in text, (
        "docs/spec.md does not name the fixed container path the close-out's "
        "local probe reads"
    )


def test_the_adr_records_the_derivation() -> None:
    """ADR-0022 owns the close-out decision, so the derivation that now selects
    among its four cases is recorded there beside the ordering that guards
    them."""

    text = ADR.read_text(encoding="utf-8")
    assert re.search(r"Amendment \(2026-08-21\)", text), (
        "ADR-0022 carries no amendment for the derivation — the decision record "
        "and the rule have drifted"
    )
    assert re.search(r"hint, never the selector", text), (
        "ADR-0022's amendment does not record that a reported `failure_phase` "
        "is demoted to a hint"
    )
