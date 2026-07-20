"""Pack-transport and scaffold-define consistency test — bind the plugin's
documentation to issue #32's two lessons from the 2026-07-20 E2E run.

**Transport.** Transcribing the ~220 KB generated ``pack.sh`` inline through
``execute-php`` + ``file_put_contents`` corrupted the payload once, caught only
by falling back, ad hoc, to Novamira's ``create-upload-link`` ability: a
gzipped upload into the random-named docroot download dir, a server-side move
outside the docroot into the working dir, a hash-verify against the locally
computed checksum, and immediate deletion of the docroot copy. This suite
binds both ``SKILL.md`` files and ``agents/pack-transfer.md`` to a stated size
threshold above which the upload-link path is blessed, with a mandatory
server-side SHA256 gate that applies to *both* transports (the inline write
too — it is exactly what would have caught the corruption before ``bash`` ever
ran the script), and the standing prohibition that ``pass.key`` never takes
this path, whatever its own size.

**Scaffold-define conflict.** ``mkwp``'s own scaffold block ships
``DISABLE_WP_CRON`` as ``true`` plus duplicates of common portable defines; the
clone flow's marked-block write must remove or supersede the conflicting
scaffold defines so the resolved cron/define decisions actually take effect,
rather than silently losing to whichever block PHP evaluates first.

Anchors are stable domain terms — ability names, function names, the literal
threshold, and defines — never a snippet of this suite's own prose, matching
the convention set by the sibling orchestration-consistency suites
(``test_docroot_io_consistency.py``, ``test_agent_delegation_consistency.py``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SKILL_FILES: dict[str, Path] = {
    "clone": REPO_ROOT / "skills" / "clone" / "SKILL.md",
    "pull": REPO_ROOT / "skills" / "pull" / "SKILL.md",
}
PACK_TRANSFER_AGENT: Path = REPO_ROOT / "agents" / "pack-transfer.md"

# The three pack-transport docs the transport half of this issue binds
# together: both skills' own orchestration prose, and the delegated subagent
# that actually performs the write.
PACK_TRANSPORT_DOCS: dict[str, Path] = {
    "clone": SKILL_FILES["clone"],
    "pull": SKILL_FILES["pull"],
    "pack-transfer agent": PACK_TRANSFER_AGENT,
}

# The stated small/large boundary literal, expected verbatim (bold Markdown)
# in every pack-transport doc — the exact string this suite holds identical
# across all three so the threshold can never quietly diverge between them.
THRESHOLD_LOWER_PATTERN: re.Pattern[str] = re.compile(
    r"at or under \*\*(\d+\s?KB)\*\*", re.IGNORECASE
)
THRESHOLD_UPPER_PATTERN: re.Pattern[str] = re.compile(
    r"above \*\*(\d+\s?KB)\*\*", re.IGNORECASE
)

# The blessed large-payload transport's ability name.
UPLOAD_LINK_PATTERN: re.Pattern[str] = re.compile(r"create-upload-link")

# The pass.key exclusion from the upload-link path — independent of (and
# additional to) the pre-existing "never...copied...docroot" prohibition the
# docroot-IO suite already binds; this one names the upload-link path itself.
PASS_KEY_EXCLUDED_FROM_UPLOAD_PATTERN: re.Pattern[str] = re.compile(
    r"pass\.key[^.\n]*never[^.\n]*(?:this path|upload-link)", re.IGNORECASE
)

# The mandatory-for-both-transports statement on the server-side SHA256 gate.
SHA256_GATE_BOTH_TRANSPORTS_PATTERN: re.Pattern[str] = re.compile(
    r"(?:mandatory[^.\n]*(?:both transports|gate)|gate[^.\n]*mandatory)"
    r"[^.\n]*(?:both transports|SHA256)",
    re.IGNORECASE,
)

# Scaffold-define conflict resolution (clone only).
CLONE_SKILL: Path = SKILL_FILES["clone"]
DISABLE_WP_CRON_CONFLICT_PATTERN: re.Pattern[str] = re.compile(
    r"scaffold[^.\n]*DISABLE_WP_CRON[^.\n]*true"
    r"|DISABLE_WP_CRON[^.\n]*true[^.\n]*scaffold",
    re.IGNORECASE,
)
SCAFFOLD_DUPLICATE_DEFINES_PATTERN: re.Pattern[str] = re.compile(
    r"scaffold[^.\n]*duplicat", re.IGNORECASE
)
SCAFFOLD_REMOVE_OR_SUPERSEDE_PATTERN: re.Pattern[str] = re.compile(
    r"(?:remove|supersede)[^.\n]*scaffold[^.\n]*define"
    r"|scaffold[^.\n]*define[^.\n]*(?:remove|supersede)",
    re.IGNORECASE,
)


def _text(path: Path) -> str:
    """Read a documentation file as UTF-8 text."""

    return path.read_text(encoding="utf-8")


def _window_after(text: str, anchor_pattern: re.Pattern[str], size: int = 900) -> str:
    """The text window starting at the first match of ``anchor_pattern`` — the
    scope a sequence-order assertion checks, rather than the whole file, so a
    coincidental later mention elsewhere can never satisfy the assertion."""

    match = anchor_pattern.search(text)
    assert match, f"anchor {anchor_pattern.pattern!r} never appears"
    return text[match.start() : match.start() + size]


def _sentence_containing(text: str, anchor: str) -> str | None:
    """Return the single sentence in ``text`` that contains ``anchor``, or
    ``None`` when no sentence matches.

    A sentence boundary is a period followed by whitespace (or the end of the
    text) — never a bare period — so an inline-code period with no trailing
    space never truncates the match early, matching the convention set by
    ``test_docroot_io_consistency.py``'s helper of the same name.
    """

    for sentence in re.split(r"(?<=\.)\s+", text):
        if anchor.lower() in sentence.lower():
            return sentence
    return None


@pytest.mark.parametrize("doc", sorted(PACK_TRANSPORT_DOCS))
def test_pack_doc_states_the_lower_threshold(doc: str) -> None:
    """AC: every pack-transport doc states the small-payload boundary as a
    literal ``at or under **N KB**`` value."""

    text = _text(PACK_TRANSPORT_DOCS[doc])
    assert THRESHOLD_LOWER_PATTERN.search(text), (
        f"{doc} does not state the 'at or under' size threshold"
    )


@pytest.mark.parametrize("doc", sorted(PACK_TRANSPORT_DOCS))
def test_pack_doc_states_the_upper_threshold(doc: str) -> None:
    """AC: every pack-transport doc states the large-payload boundary as a
    literal ``above **N KB**`` value — the trigger for the blessed upload-link
    path."""

    text = _text(PACK_TRANSPORT_DOCS[doc])
    assert THRESHOLD_UPPER_PATTERN.search(text), (
        f"{doc} does not state the 'above' size threshold"
    )


def test_threshold_is_the_same_stated_value_across_every_pack_doc() -> None:
    """AC: the threshold is one stated value, consistent across both SKILL.md
    files and the delegated pack-transfer agent — never silently drifting
    between them."""

    lower_values = {
        doc: THRESHOLD_LOWER_PATTERN.search(_text(path)).group(1).replace(" ", "").upper()
        for doc, path in PACK_TRANSPORT_DOCS.items()
    }
    upper_values = {
        doc: THRESHOLD_UPPER_PATTERN.search(_text(path)).group(1).replace(" ", "").upper()
        for doc, path in PACK_TRANSPORT_DOCS.items()
    }
    assert len(set(lower_values.values())) == 1, f"lower thresholds diverge: {lower_values}"
    assert len(set(upper_values.values())) == 1, f"upper thresholds diverge: {upper_values}"
    assert set(lower_values.values()) == set(upper_values.values()), (
        f"lower and upper thresholds are not the same boundary value: "
        f"{lower_values} vs {upper_values}"
    )


@pytest.mark.parametrize("doc", sorted(PACK_TRANSPORT_DOCS))
def test_pack_doc_names_create_upload_link_for_large_payloads(doc: str) -> None:
    """AC: every pack-transport doc names Novamira's ``create-upload-link``
    ability as the blessed transport for payloads above the threshold."""

    text = _text(PACK_TRANSPORT_DOCS[doc])
    assert UPLOAD_LINK_PATTERN.search(text), (
        f"{doc} never names create-upload-link"
    )


@pytest.mark.parametrize("doc", sorted(PACK_TRANSPORT_DOCS))
def test_pack_doc_states_the_upload_link_sequence_in_order(doc: str) -> None:
    """AC: the upload-link path is documented as a strict sequence — gzipped
    upload into the docroot download dir, a server-side move outside the
    docroot, the SHA256 verify, then immediate deletion of the docroot copy —
    each step's anchor appearing after the previous one's, not merely present
    anywhere in the file."""

    text = _text(PACK_TRANSPORT_DOCS[doc])
    window = _window_after(text, UPLOAD_LINK_PATTERN, size=1200)
    lower = window.lower()

    positions = {
        "gzip": lower.find("gzip"),
        "docroot": lower.find("docroot"),
        "move": lower.find("move"),
        "sha256": lower.find("sha256"),
        "delete": lower.find("delete"),
    }
    for step, pos in positions.items():
        assert pos != -1, f"{doc}'s upload-link sequence never mentions {step!r}"

    ordered = ["gzip", "docroot", "move", "sha256", "delete"]
    for earlier, later in zip(ordered, ordered[1:]):
        assert positions[earlier] < positions[later], (
            f"{doc}'s upload-link sequence is out of order: "
            f"{earlier!r} ({positions[earlier]}) should precede {later!r} ({positions[later]})"
        )


@pytest.mark.parametrize("doc", sorted(PACK_TRANSPORT_DOCS))
def test_pack_doc_excludes_pass_key_from_the_upload_link_path(doc: str) -> None:
    """AC: the existing prohibition stays absolute and explicit — pass.key
    never takes the upload-link path, whatever its own size; only the
    non-secret pack.sh does."""

    text = _text(PACK_TRANSPORT_DOCS[doc])
    assert PASS_KEY_EXCLUDED_FROM_UPLOAD_PATTERN.search(text), (
        f"{doc} does not explicitly exclude pass.key from the upload-link path"
    )


@pytest.mark.parametrize("doc", sorted(PACK_TRANSPORT_DOCS))
def test_pack_doc_states_the_sha256_gate_is_mandatory_for_both_transports(doc: str) -> None:
    """AC: keep the mandatory server-side SHA256 gate for both transports —
    the inline execute-php write and the upload-link path alike."""

    text = _text(PACK_TRANSPORT_DOCS[doc])
    assert SHA256_GATE_BOTH_TRANSPORTS_PATTERN.search(text), (
        f"{doc} does not state the SHA256 gate is mandatory for both transports"
    )


def test_clone_skill_documents_the_scaffold_disable_wp_cron_conflict() -> None:
    """AC: the clone flow's marked-block write step documents that mkwp's own
    scaffold block already ships DISABLE_WP_CRON as true."""

    text = _text(CLONE_SKILL)
    assert DISABLE_WP_CRON_CONFLICT_PATTERN.search(text), (
        "clone/SKILL.md does not document the scaffold's own DISABLE_WP_CRON true"
    )


def test_clone_skill_documents_scaffold_define_duplicates() -> None:
    """AC: the clone flow documents that mkwp's scaffold block also duplicates
    common portable defines, not only DISABLE_WP_CRON."""

    text = _text(CLONE_SKILL)
    assert SCAFFOLD_DUPLICATE_DEFINES_PATTERN.search(text), (
        "clone/SKILL.md does not document the scaffold's duplicate portable defines"
    )


def test_clone_skill_marked_block_write_removes_or_supersedes_scaffold_defines() -> None:
    """AC: the marked-block write must remove or supersede conflicting
    scaffold defines so the resolved cron/define decisions actually take
    effect — not merely note the conflict without resolving it."""

    text = _text(CLONE_SKILL)
    assert SCAFFOLD_REMOVE_OR_SUPERSEDE_PATTERN.search(text), (
        "clone/SKILL.md does not state that the marked-block write removes or "
        "supersedes conflicting scaffold defines"
    )


def test_clone_skill_cron_step_confirms_scaffold_define_was_already_cleared() -> None:
    """The cron bullet's 'otherwise leave it running' is only true once the
    marked-block write has already removed the scaffold's own DISABLE_WP_CRON
    — this binds that the *same sentence* says so, rather than silently
    relying on an untouched scaffold define that would leave cron disabled by
    default even when the resolved decision is to leave it running."""

    text = _text(CLONE_SKILL)
    sentence = _sentence_containing(text, "otherwise leave it running")
    assert sentence, "clone/SKILL.md dropped the cron 'otherwise leave it running' clause"
    assert re.search(r"scaffold[^.\n]*DISABLE_WP_CRON|DISABLE_WP_CRON[^.\n]*scaffold", sentence), (
        f"clone/SKILL.md's cron step does not confirm the scaffold define was "
        f"already cleared in the same sentence: {sentence!r}"
    )
