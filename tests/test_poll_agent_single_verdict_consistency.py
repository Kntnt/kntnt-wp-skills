# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Poll-agent single-verdict consistency test — the anti-drift binding for the
two rules that stopped `discovery-classify` hanging.

A `clone` run against `safeteam.se` lost roughly 165k tokens to one subagent
that could not sit still. `discovery-classify` had already made every call its
phase needs — `/environment`, `/tables`, sixty-one pages of `/files`, and the
bootstrap submit — and then returned **three times** saying it was still
waiting for the bootstrap job, ~55k tokens each and no evidence block. The
skill's own rule (a result without an evidence block is `FAILED`) worked and
was applied; the agent was the problem. Its contract gave it no way to wait
out a job taking minutes and no way to resume polling after a return, so
yielding was the only move it had, and yielding accomplished nothing.

Two rules fixed it. Their canonical wording lives in ``docs/poll-discipline.md``
and this suite reads it from there — the rule belongs in the document, and a
test is a poor place to keep a product decision:

1. **Wait inside one blocking shell loop**, never one tool call per poll, and
   let the loop terminate itself and print its own verdict.
2. **Return exactly once, with a verdict.** There is no "still waiting"
   return; an exhausted budget is a `FAILED` carrying the job id, so the
   orchestrator can consume or cancel a job that is still active against the
   plugin's one-active-job rule.

Prose rules drift, and these two already had: the first version of this suite
reddened immediately because the two agents stated the same ban in different
words. Both now carry the canonical phrasing verbatim, and this suite holds
them to it in the same spirit as ``test_poll_discipline_consistency.py`` binds
the discipline's numeric literals — a faithful rewrite of the surrounding
narrative stays green, a rewrite that quietly drops "return exactly once"
reddens.

It also binds `discovery-classify`'s own-working-directory rule. In that same
run the agent reported artifacts the **orchestrator** had produced, with
matching SHA256s, while its own `consume` returned `404` because the
orchestrator had already consumed the job — an evidence block is only evidence
when nothing else could have written the files it names.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import pinned_phrases

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
ROLES_DIR: Path = REPO_ROOT / "skills" / "clone" / "roles"

# The two subagents that own a poll loop. Every other phase is synchronous and
# has nothing to wait on, so the rules below do not apply to them.
POLLING_AGENTS: tuple[str, ...] = ("discovery-classify", "extract-transfer")

# Every phrase both poll-owning agents must carry, read from the canonical
# document rather than restated here. The names are pinned separately below, so a
# phrase quietly disappearing from the document reddens instead of silently
# turning this suite into a no-op.
AGENT_PHRASES: dict[str, str] = pinned_phrases("Pinned phrases — the poll-owning subagents")

# The names the canonical document is expected to define for these two agents.
# This is the guard on the indirection itself: data-driven enforcement that loses
# its data enforces nothing, and would do so while passing.
EXPECTED_PHRASE_NAMES: frozenset[str] = frozenset({
    "the wait-in-one-loop heading",
    "the give-up line the loop must print",
    "the return-exactly-once heading",
    "the still-active-job consequence",
    "the hard rule forbidding a verdictless return",
    "the hard rule forbidding a per-poll tool call",
})

# The two hard rules are carried in the *Hard rules* section specifically, where
# an agent's refusals live — a rule stated only in narrative prose is guidance.
HARD_RULE_NAMES: frozenset[str] = frozenset({
    "the hard rule forbidding a verdictless return",
    "the hard rule forbidding a per-poll tool call",
})


def _body(path: Path) -> str:
    """Return a role file's text. Role files carry no frontmatter — they are
    instructions any harness can execute, not one harness's agent definition —
    so there is nothing to strip and no description a body assertion could be
    satisfied by."""

    return path.read_text(encoding="utf-8")


def test_the_canonical_document_defines_every_expected_phrase() -> None:
    """The guard on the indirection: the canonical document must still define
    each phrase this suite enforces. Without it, deleting a phrase from the
    document would disable its enforcement everywhere and turn this file green
    while the rule it protects vanished."""

    assert set(AGENT_PHRASES) == EXPECTED_PHRASE_NAMES, (
        "docs/poll-discipline.md's poll-owning-subagents section no longer "
        "defines exactly the phrases this suite enforces; added or removed: "
        f"{set(AGENT_PHRASES) ^ EXPECTED_PHRASE_NAMES}"
    )


@pytest.mark.parametrize("name", POLLING_AGENTS)
@pytest.mark.parametrize("phrase_name", sorted(EXPECTED_PHRASE_NAMES))
def test_polling_agent_carries_the_canonical_phrase(
    name: str, phrase_name: str
) -> None:
    """Each poll-owning subagent carries every pinned phrase verbatim: wait in
    one blocking loop, terminate it yourself, return exactly once with a
    verdict, and leave no job wedged when a budget runs out.

    Verbatim, not merely equivalent — the two agents had already come to state
    the same ban in different words, which is how a rule stops being one rule."""

    body = _body(ROLES_DIR / f"{name}.md")
    assert AGENT_PHRASES[phrase_name] in body, (
        f"roles/{name}.md is missing {phrase_name} as canonically worded "
        f"({AGENT_PHRASES[phrase_name]!r}) — the wording lives in "
        "docs/poll-discipline.md and every poll-owning role must carry it"
    )


@pytest.mark.parametrize("name", POLLING_AGENTS)
@pytest.mark.parametrize("phrase_name", sorted(HARD_RULE_NAMES))
def test_polling_agent_carries_the_hard_rule_where_refusals_live(
    name: str, phrase_name: str
) -> None:
    """The two bans appear under *Hard rules* specifically. A rule stated only
    in narrative prose is guidance; the Hard rules section is where an agent's
    refusals live, and that is where a ban has to be to bind."""

    body = _body(ROLES_DIR / f"{name}.md")
    sections = body.split("## Hard rules", 1)
    assert len(sections) == 2, f"roles/{name}.md has no Hard rules section"
    assert AGENT_PHRASES[phrase_name] in sections[1], (
        f"{name}.md states {phrase_name} outside its Hard rules section, where "
        "it reads as advice rather than a refusal"
    )


def test_discovery_classify_owns_its_working_directory() -> None:
    """`discovery-classify` creates its own working directory under the shared
    scratchpad and may name only artifacts it wrote there. The shared directory
    is where the orchestrator writes too, and an evidence block that can
    describe someone else's files proves nothing about this agent's run."""

    body = _body(ROLES_DIR / "discovery-classify.md")
    assert "Create your own working directory under the scratchpad" in body, (
        "the discovery-classify role no longer tells the agent to create its own "
        "working directory — without it, a checksum in the evidence block can "
        "describe an artifact the orchestrator produced"
    )
    assert "<work_dir>/" in body, (
        "the discovery-classify role no longer routes its artifacts through "
        "<work_dir>, so they land in the shared scratchpad again"
    )
    hard_rules = body.split("## Hard rules", 1)
    assert len(hard_rules) == 2, "the discovery-classify role has no Hard rules section"
    assert "Never name an artifact in your evidence block" in hard_rules[1], (
        "the discovery-classify role's Hard rules do not forbid claiming an artifact "
        "it did not write itself"
    )


@pytest.mark.parametrize("name", POLLING_AGENTS)
def test_polling_agent_invokes_the_poll_helper(name: str) -> None:
    """Each poll-owning subagent names ``scripts/poll_extraction.py`` as the
    loop it runs, so it cannot fall back to writing a fresh shell loop."""

    body = _body(ROLES_DIR / f"{name}.md")
    assert "scripts/poll_extraction.py" in body, (
        f"{name}.md never names scripts/poll_extraction.py — the poll loop "
        "lives in that helper, not in a loop the agent writes"
    )
    assert "KNTNT_EXTRACTOR_APP_PASSWORD" in body, (
        f"{name}.md never names KNTNT_EXTRACTOR_APP_PASSWORD — the secret "
        "must be documented as environment-only for the helper"
    )
