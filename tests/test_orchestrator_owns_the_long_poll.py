"""Long-poll ownership consistency test — issue #58, plan 009.

The main extraction's poll is the one wait in this engine with no overall
budget: hours, bounded only by the stall window. It used to belong to the
`extract-transfer` subagent, which was instructed to sit inside the one
blocking `poll_extraction.py` invocation and return exactly once with a
verdict. On **both** production runs it returned without one, and the second
time it had detached the poll before returning — so when its process tree was
reaped the poll died with it: the redirect target was 0 bytes, no exit code was
ever written, and the job on production carried on to 13,459 files with nobody
watching. The written close-out for a verdict-less return is `DELETE`; only a
manual state check stopped a healthy job being cancelled.

Instructing the agent harder had already been tried, twice, under two different
wordings. This suite binds the structural fix instead: the poll is nobody's to
delegate. `skills/clone/SKILL.md` and `skills/pull/SKILL.md` run it themselves
as their own tracked background job; the phase either side of it is delegated
in two short, bounded halves — `extract-submit` (one `POST /extractions`, the
job id to disk, return) and `extract-transfer` (download, unseal, consume) —
and neither half spans the wait.

Every assertion here would have failed before the split, and each names the
property rather than the prose: a role file may invoke the poll helper only
with an overall budget on its argv (the helper's third positional, which the
main extraction is the sole caller to omit); the budget-less invocation appears
only in the two orchestration surfaces; its verdict and its exit code are
captured to files that survive it; and the job id reaches disk before the poll
begins, which is what makes a lost poller a re-poll rather than a lost run.

Like its sibling suites, the pinned wording lives in ``docs/poll-discipline.md``
and is read from there — the rule belongs in the document, and a test is a poor
place to keep a product decision.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import pinned_phrases

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
ROLES_DIR: Path = REPO_ROOT / "skills" / "clone" / "roles"
SKILLS: dict[str, Path] = {
    "clone": REPO_ROOT / "skills" / "clone" / "SKILL.md",
    "pull": REPO_ROOT / "skills" / "pull" / "SKILL.md",
}

SUBMIT_ROLE: Path = ROLES_DIR / "extract-submit.md"
TRANSFER_ROLE: Path = ROLES_DIR / "extract-transfer.md"

# The ownership rule's canonical wording, read from the document that owns it.
OWNERSHIP_PHRASES: dict[str, str] = pinned_phrases(
    "Pinned phrases — who owns the main extraction's poll"
)

# The names the canonical document is expected to define. Data-driven
# enforcement that loses its data enforces nothing — and would do so while
# passing — so the indirection is guarded before it is used.
EXPECTED_PHRASE_NAMES: frozenset[str] = frozenset({
    "the ownership heading",
    "the never-delegate rule",
    "the job record written before the poll starts",
    "the file the poll's verdict is captured in",
    "the file the poll's exit code is captured in",
    "the re-attach rule",
})

# One actual invocation of the poll helper: the helper's name followed by its
# quoted positional arguments. A bare mention in prose (```scripts/poll_
# extraction.py``` inside a sentence) carries no quoted argv and is skipped,
# which is what keeps this a check on commands rather than on narrative.
INVOCATION: re.Pattern[str] = re.compile(r'poll_extraction\.py((?:\s+"[^"]+")+)')
QUOTED_ARGUMENT: re.Pattern[str] = re.compile(r'"([^"]+)"')

# The helper's argv contract (``skills/clone/scripts/poll_extraction.py``):
# endpoint, job id, and an optional overall wall-clock budget. The main
# extraction is the only caller that omits the budget, so the count of
# positionals is exactly the "is this the unbounded wait?" test.
BOUNDED_POSITIONALS: int = 3
UNBOUNDED_POSITIONALS: int = 2


def _invocations(path: Path) -> list[list[str]]:
    """Every poll-helper invocation in a document, as its positional argv."""

    text = path.read_text(encoding="utf-8")
    return [
        QUOTED_ARGUMENT.findall(match.group(1)) for match in INVOCATION.finditer(text)
    ]


def test_the_canonical_document_defines_every_expected_phrase() -> None:
    """The guard on the indirection: deleting a phrase from the document must
    redden here rather than quietly disabling its enforcement everywhere."""

    assert set(OWNERSHIP_PHRASES) == EXPECTED_PHRASE_NAMES, (
        "docs/poll-discipline.md's poll-ownership section no longer defines "
        "exactly the phrases this suite enforces; added or removed: "
        f"{set(OWNERSHIP_PHRASES) ^ EXPECTED_PHRASE_NAMES}"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
@pytest.mark.parametrize("phrase_name", sorted(EXPECTED_PHRASE_NAMES))
def test_orchestration_surface_carries_the_ownership_phrase(
    skill: str, phrase_name: str
) -> None:
    """Both orchestration surfaces state who owns the wait, in the canonical
    wording: a rule stated two ways is two rules."""

    text = SKILLS[skill].read_text(encoding="utf-8")
    assert OWNERSHIP_PHRASES[phrase_name] in text, (
        f"{skill} SKILL.md is missing {phrase_name} as canonically worded "
        f"({OWNERSHIP_PHRASES[phrase_name]!r}) — the wording lives in "
        "docs/poll-discipline.md"
    )


@pytest.mark.parametrize(
    "role", sorted(ROLES_DIR.glob("*.md")), ids=lambda p: p.stem
)
def test_no_role_file_owns_an_unbounded_poll(role: Path) -> None:
    """A role runs inside something that can be reaped, so it may own only a
    wait that is bounded by its own overall budget. Every poll-helper
    invocation in a role file therefore passes the budget argv; the one wait
    that omits it — the main extraction's — is not a role's to own.

    This is the assertion the old shape fails: `extract-transfer` invoked the
    helper with two positionals and no budget, and waited hours on it."""

    for argv in _invocations(role):
        assert len(argv) == BOUNDED_POSITIONALS, (
            f"roles/{role.name} invokes the poll helper with {len(argv)} "
            f"positional arguments ({argv}) — a role may only own a poll that "
            "carries an overall wall-clock budget as its third argument. The "
            "budget-less invocation is the multi-hour main-extraction wait, "
            "and it belongs to the orchestrator"
        )


@pytest.mark.parametrize("role", sorted((SUBMIT_ROLE, TRANSFER_ROLE)), ids=lambda p: p.stem)
def test_the_split_halves_never_mention_the_poll_helper(role: Path) -> None:
    """Neither half of the split phase names the poll helper at all. The submit
    returns before the wait and the transfer starts after it, so a mention
    could only be an invitation to re-merge them."""

    text = role.read_text(encoding="utf-8")
    assert "poll_extraction.py" not in text, (
        f"roles/{role.name} still names the poll helper — the main extraction's "
        "poll is run by the orchestration surface, not by either half of the "
        "phase around it"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_the_orchestration_surface_runs_the_unbounded_poll_itself(skill: str) -> None:
    """The budget-less invocation exists, once, in each SKILL.md — as a literal
    command, not as a description of one somebody else runs."""

    argvs = _invocations(SKILLS[skill])
    unbounded = [argv for argv in argvs if len(argv) == UNBOUNDED_POSITIONALS]
    assert len(unbounded) == 1, (
        f"{skill} SKILL.md carries {len(unbounded)} budget-less poll-helper "
        f"invocations ({argvs}); it must carry exactly one — the main "
        "extraction's poll, run by the orchestrator itself"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_the_poll_command_captures_its_verdict_and_its_exit_code(skill: str) -> None:
    """AC: a poll's output and exit code are recoverable after the fact. The
    command redirects stdout to the verdict file and writes the helper's exit
    status beside it, so a poll that ended can always be read back — and one
    that never ended is distinguishable from one that returned nothing, which
    a 0-byte redirect target on its own is not."""

    text = SKILLS[skill].read_text(encoding="utf-8")
    match = INVOCATION.search(text)
    assert match is not None, f"{skill} SKILL.md never invokes the poll helper"

    # The command runs to the end of its backticked span; that is the unit the
    # redirections have to appear in, not merely somewhere in the document.
    command = text[match.start() : text.find("`", match.end())]
    verdict_file = OWNERSHIP_PHRASES["the file the poll's verdict is captured in"]
    exit_file = OWNERSHIP_PHRASES["the file the poll's exit code is captured in"]

    assert f"> \"<scratchpad>/{verdict_file}\"" in command, (
        f"{skill} SKILL.md's poll command does not redirect stdout to "
        f"{verdict_file} — the verdict would live only in a context that can "
        "be lost"
    )
    assert exit_file in command and "$?" in command, (
        f"{skill} SKILL.md's poll command does not write the helper's exit "
        f"status to {exit_file} — an unfinished poll and a finished one then "
        "look identical from disk"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_the_job_id_reaches_disk_before_the_poll_begins(skill: str) -> None:
    """A poller that is lost is a re-poll rather than a lost run only while the
    job id is on disk. The record is therefore written by the submit, and the
    document says so before it says how to poll."""

    text = SKILLS[skill].read_text(encoding="utf-8")
    record = OWNERSHIP_PHRASES["the job record written before the poll starts"]
    record_pos = text.find(record)
    assert record_pos != -1, (
        f"{skill} SKILL.md never names {record}, so nothing puts the job id on "
        "disk before the wait that can lose it"
    )

    match = INVOCATION.search(text)
    assert match is not None, f"{skill} SKILL.md never invokes the poll helper"
    assert record_pos < match.start(), (
        f"{skill} SKILL.md writes {record} after the poll command — the id has "
        "to be on disk before the poll starts, or a lost poller is a lost run"
    )


def test_the_submit_role_hands_back_a_job_it_never_waits_for() -> None:
    """`extract-submit` is short, bounded and verdict-shaped: it creates the
    job, records it, and returns. Its refusal to wait is a hard rule, because
    the refusal is the whole point of it existing separately."""

    text = SUBMIT_ROLE.read_text(encoding="utf-8")
    assert "POST /extractions" in text, (
        "the extract-submit role does not submit the extraction"
    )
    assert OWNERSHIP_PHRASES["the job record written before the poll starts"] in text, (
        "the extract-submit role does not write the job record the orchestrator "
        "polls from"
    )

    hard_rules = text.split("## Hard rules", 1)
    assert len(hard_rules) == 2, "the extract-submit role has no Hard rules section"
    assert re.search(r"never wait for the job", hard_rules[1], re.IGNORECASE), (
        "the extract-submit role's Hard rules do not forbid waiting for the job "
        "it submitted — which is the one thing the split exists to prevent"
    )


def test_the_transfer_role_starts_from_an_already_ready_job() -> None:
    """`extract-transfer` no longer creates the job it transfers. It is handed
    a job id the orchestrator has already polled to `ready`, and it downloads,
    unseals, and consumes — all bounded, none of it a wait."""

    text = TRANSFER_ROLE.read_text(encoding="utf-8")
    assert "unseal.py unseal" in text, (
        "the extract-transfer role no longer unseals the container"
    )
    assert "POST /extractions/{id}/consume" in text, (
        "the extract-transfer role no longer consumes the job"
    )
    assert not re.search(r"`POST /extractions`", text), (
        "the extract-transfer role still submits an extraction — the submit and "
        "the transfer are separated precisely so that no single role spans the "
        "multi-hour wait between them"
    )


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_the_surface_forbids_backgrounding_the_poll_out_of_reach(skill: str) -> None:
    """The second production run did not merely delegate the poll — it detached
    it. A background job the orchestrator itself tracks is the fix; a `nohup`
    that outlives the session's own bookkeeping is the defect wearing the same
    clothes, so the document names it."""

    text = SKILLS[skill].read_text(encoding="utf-8")
    assert "nohup" in text, (
        f"{skill} SKILL.md never names the detached-process shape the poll must "
        "not take, so 'run it in the background' reads as licence for it"
    )
