"""Docroot-IO consistency test — bind the docroot-only limits of `read-file`/
`write-file` and the `execute-php` prescription to their documentation (issue
#16).

Both smoke-test runs discovered mid-flight that Novamira's `read-file` and
`write-file` abilities are restricted to the docroot, while the working
directory — and `pass.key`, per ADR-0008 — deliberately live outside it. The
clone run improvised by briefly copying `pass.key` into the docroot to read it,
contrary to the spirit of ADR-0008 even with immediate cleanup; the pull run
found the right pattern: `execute-php` with `file_get_contents` /
`file_put_contents` over the same authenticated channel.

This suite is the anti-drift binding for that lesson: it holds the
control-channel section of both `SKILL.md` files and `docs/spec.md` to the
docroot-only statement, the `execute-php` prescription, and the explicit
prohibition on copying `pass.key` into the docroot — plus ADR-0008, which
records the same as an appended, operator-authorised note rather than a rewrite
of the original decision.

It also guards the specific regression the smoke tests hit: the pack step's
instruction to *write* `pass.key` into the working dir, and the download step's
instruction to *fetch* it back, must each name `execute-php` as the channel —
never the docroot-only `write-file` / `read-file` — or the new docroot-only
statement would directly contradict the very next section of the same file.

Anchors are stable domain terms — ability names, function names, and the
`pass.key` filename — never a snippet of this suite's own prose, matching the
convention set by the sibling orchestration-consistency suites.
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
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
ADR_0008: Path = REPO_ROOT / "docs" / "adr" / "0008-encrypted-artifacts-outside-docroot.md"
IMPLEMENTATION_NOTES: Path = REPO_ROOT / "docs" / "implementation-notes.md"
PACK_TRANSFER_AGENT: Path = REPO_ROOT / "agents" / "pack-transfer.md"

# The docroot-only statement: read-file and write-file named together with
# "docroot-only" close enough to bind the claim to those two abilities, not to
# an incidental, unrelated use of the word elsewhere in the file.
DOCROOT_ONLY_PATTERN: re.Pattern[str] = re.compile(
    r"`read-file`[^.\n]*`write-file`[^.\n]*docroot-only", re.IGNORECASE
)

# The prohibition: pass.key and "never...copied...docroot" in the same sentence.
PASS_KEY_PROHIBITION_PATTERN: re.Pattern[str] = re.compile(
    r"pass\.key[^.\n]*never[^.\n]*(?:copied|copy)[^.\n]*docroot", re.IGNORECASE
)

# The superseded last-resort fallback: a docroot working dir "mitigated by
# immediate cleanup" — the exact prose the abort rule replaces. Its survival
# anywhere in the docs directly contradicts the pass.key-never-in-docroot
# prohibition, since pass.key is written into that same working dir.
LAST_RESORT_FALLBACK_PATTERN: re.Pattern[str] = re.compile(
    r"last resort[^.\n]*docroot", re.IGNORECASE
)

# The abort rule that replaces the fallback: the working dir preference order
# ends in an abort, not a docroot fallback, when neither the system temp dir
# nor a directory above ABSPATH is writable.
WORKING_DIR_ABORT_PATTERN: re.Pattern[str] = re.compile(
    r"abort[^.\n]*(?:working dir|fall back)[^.\n]*docroot"
    r"|docroot[^.\n]*(?:working dir|fall back)[^.\n]*abort",
    re.IGNORECASE,
)

# The docroot-only read channel named as the retrieval mechanism — whether by
# its ability name (`read-file`) or by a paraphrase of it ("the authenticated
# file-read ability"). Both name the same docroot-only ability the execute-php
# prescription supersedes for outside-docroot IO, so a negative assertion must
# catch either spelling, not just the backticked one.
READ_FILE_CHANNEL_PATTERN: re.Pattern[str] = re.compile(
    r"(?:over|through)\s+(?:the\s+\S+\s+)*"
    r"(?:`read-file`|(?:authenticated\s+)?file-read ability)",
    re.IGNORECASE,
)


def _text(path: Path) -> str:
    """Read a documentation file as UTF-8 text."""

    return path.read_text(encoding="utf-8")


def _sentence_containing(text: str, anchor: str) -> str | None:
    """Return the single sentence in ``text`` that contains ``anchor``, or
    ``None`` when no sentence matches.

    A sentence boundary is a period followed by whitespace (or the end of the
    text) — never a bare period — so an inline-code period with no trailing
    space (`` `.my.cnf` ``, ``pass.key`) never truncates the match early.
    Bounds the search to one full sentence so a downstream assertion checks
    what *that* instruction names as its channel, not merely what the file
    mentions somewhere else entirely, and so a negative assertion scans the
    whole sentence rather than a prematurely truncated prefix of it.
    """

    for sentence in re.split(r"(?<=\.)\s+", text):
        if anchor.lower() in sentence.lower():
            return sentence
    return None


def test_sentence_containing_does_not_truncate_at_inline_code_periods() -> None:
    """`_sentence_containing` must capture the whole sentence even when an
    inline-code period with no trailing whitespace (a dotfile name, a
    `<local pass.key>` literal) sits between the anchor and the real
    sentence-ending period — the exact shape that let the pack- and
    download-step assertions above pass against a truncated capture rather
    than the real sentence, narrowing the window a negative assertion
    actually scans."""

    text = (
        "Before. Write `pass.key` and the `.my.cnf` file into the working "
        "dir, using execute-php. After."
    )
    sentence = _sentence_containing(text, "Write `pass.key`")
    assert sentence == (
        "Write `pass.key` and the `.my.cnf` file into the working dir, "
        "using execute-php."
    )


@pytest.mark.parametrize("skill", sorted(SKILL_FILES))
def test_skill_states_read_write_file_are_docroot_only(skill: str) -> None:
    """AC: each SKILL.md's control-channel section states that `read-file` and
    `write-file` reach only the docroot."""

    text = _text(SKILL_FILES[skill])
    assert DOCROOT_ONLY_PATTERN.search(text), (
        f"{skill}/SKILL.md does not state read-file/write-file are docroot-only"
    )


@pytest.mark.parametrize("skill", sorted(SKILL_FILES))
def test_skill_prescribes_execute_php_for_outside_docroot_io(skill: str) -> None:
    """AC: each SKILL.md prescribes `execute-php` with `file_get_contents` /
    `file_put_contents` for all outside-docroot IO."""

    text = _text(SKILL_FILES[skill])
    assert "execute-php" in text
    assert "file_get_contents" in text, f"{skill}/SKILL.md never mentions file_get_contents"
    assert "file_put_contents" in text, f"{skill}/SKILL.md never mentions file_put_contents"


@pytest.mark.parametrize("skill", sorted(SKILL_FILES))
def test_skill_forbids_copying_pass_key_into_the_docroot(skill: str) -> None:
    """AC: each SKILL.md explicitly forbids copying `pass.key` into the docroot,
    not even transiently."""

    text = _text(SKILL_FILES[skill])
    assert PASS_KEY_PROHIBITION_PATTERN.search(text), (
        f"{skill}/SKILL.md does not forbid copying pass.key into the docroot"
    )


@pytest.mark.parametrize("skill", sorted(SKILL_FILES))
def test_skill_pack_step_writes_pass_key_over_execute_php(skill: str) -> None:
    """The pack step's instruction to write `pass.key` into the working dir
    names `execute-php`, never the docroot-only `write-file` — the exact
    contradiction the smoke tests hit when the clone run improvised a docroot
    copy to work around `write-file`'s reach."""

    text = _text(SKILL_FILES[skill])
    sentence = _sentence_containing(text, "the passphrase file `pass.key`")
    assert sentence, f"{skill}/SKILL.md dropped the pass.key write instruction"
    assert "execute-php" in sentence, (
        f"{skill}/SKILL.md's pass.key write step does not name execute-php: {sentence!r}"
    )


@pytest.mark.parametrize("skill", sorted(SKILL_FILES))
def test_skill_download_step_fetches_pass_key_over_execute_php(skill: str) -> None:
    """The download step's instruction to fetch `pass.key` back names
    `execute-php`, never the docroot-only `read-file` — the exact workaround the
    clone run improvised (a transient docroot copy) that this issue forbids."""

    text = _text(SKILL_FILES[skill])
    sentence = _sentence_containing(text, "fetch `pass.key`")
    assert sentence, f"{skill}/SKILL.md dropped the pass.key fetch instruction"
    assert "execute-php" in sentence, (
        f"{skill}/SKILL.md's pass.key fetch step does not name execute-php: {sentence!r}"
    )
    # A clause explaining *why* read-file cannot be used is fine; naming it as
    # the channel actually taken — "over" immediately followed by `read-file`
    # — is the regression the smoke tests hit.
    assert not READ_FILE_CHANNEL_PATTERN.search(sentence), (
        f"{skill}/SKILL.md still routes the pass.key fetch over the docroot-only read channel: {sentence!r}"
    )


def test_pack_transfer_agent_write_step_uses_execute_php() -> None:
    """The delegated pack phase (`agents/pack-transfer.md` step 2) writes
    `pass.key`, `.my.cnf`, and `pack.sh` into the outside-docroot working dir —
    it must name `execute-php` (`file_put_contents`) as the channel, matching
    both `SKILL.md` files' own description of the same write, or the delegated
    path silently regresses to an ambiguous "over the control channel" that a
    future agent could satisfy with the docroot-only `write-file`."""

    text = _text(PACK_TRANSFER_AGENT)
    sentence = _sentence_containing(text, "write the working dir's `pass.key`")
    assert sentence, "agents/pack-transfer.md dropped the pass.key write instruction"
    assert "execute-php" in sentence, (
        f"agents/pack-transfer.md's pass.key write step does not name execute-php: {sentence!r}"
    )


def test_pack_transfer_agent_fetch_step_uses_execute_php_never_read_file() -> None:
    """The delegated pack phase's fetch-back of `pass.key` (step 5) must go
    over `execute-php`, never the docroot-only `read-file` ability — the exact
    #16 regression: `read-file` cannot reach outside the docroot at all, and
    `pass.key` must never be copied into the docroot, not even transiently
    (ADR-0008 amendment)."""

    text = _text(PACK_TRANSFER_AGENT)
    sentence = _sentence_containing(text, "Fetch `pass.key`")
    assert sentence, "agents/pack-transfer.md dropped the pass.key fetch instruction"
    assert "execute-php" in sentence, (
        f"agents/pack-transfer.md's pass.key fetch step does not name execute-php: {sentence!r}"
    )
    assert not READ_FILE_CHANNEL_PATTERN.search(sentence), (
        f"agents/pack-transfer.md still routes the pass.key fetch over the docroot-only read channel: {sentence!r}"
    )


def test_pack_transfer_agent_forbids_copying_pass_key_into_the_docroot() -> None:
    """AC: `agents/pack-transfer.md` explicitly forbids copying `pass.key` into
    the docroot, not even transiently — the same prohibition both `SKILL.md`
    files already state."""

    text = _text(PACK_TRANSFER_AGENT)
    assert PASS_KEY_PROHIBITION_PATTERN.search(text), (
        "agents/pack-transfer.md does not forbid copying pass.key into the docroot"
    )


def test_spec_states_docroot_only_limit_and_execute_php_prescription() -> None:
    """AC: the spec's control-channel section (Implementation Decisions, ~line
    99) states the docroot-only limit, prescribes execute-php with
    file_get_contents/file_put_contents, and forbids copying pass.key into the
    docroot."""

    text = _text(SPEC)
    assert DOCROOT_ONLY_PATTERN.search(text), (
        "spec.md does not state read-file/write-file are docroot-only"
    )
    assert "file_get_contents" in text, "spec.md never mentions file_get_contents"
    assert "file_put_contents" in text, "spec.md never mentions file_put_contents"
    assert PASS_KEY_PROHIBITION_PATTERN.search(text), (
        "spec.md does not forbid copying pass.key into the docroot"
    )


def test_spec_passphrase_fetch_over_execute_php() -> None:
    """AC: the spec's pack-on-production section (~line 181) must describe the
    passphrase fetch-back over `execute-php`, matching spec.md:104 and both
    SKILL.md files/implementation-notes.md — never over the docroot-only
    read channel, whether named `read-file` or paraphrased as "the
    authenticated file-read ability"."""

    text = _text(SPEC)
    sentence = _sentence_containing(text, "fetched locally")
    assert sentence, "spec.md dropped the passphrase fetched-locally sentence"
    assert "execute-php" in sentence, (
        f"spec.md's passphrase fetch step does not name execute-php: {sentence!r}"
    )
    assert not READ_FILE_CHANNEL_PATTERN.search(sentence), (
        f"spec.md still routes the passphrase fetch over the docroot-only read channel: {sentence!r}"
    )


def test_spec_working_dir_aborts_rather_than_falls_back_to_docroot() -> None:
    """AC: `docs/spec.md`'s pack section must state the abort rule the branch's
    SKILL.md files and ADR-0008 amendment establish — no writable dir above
    ABSPATH means abort, never a last-resort docroot working dir — because
    pass.key is written into that same working dir and must never enter the
    docroot, not even transiently."""

    text = _text(SPEC)
    assert not LAST_RESORT_FALLBACK_PATTERN.search(text), (
        "spec.md still describes the superseded last-resort docroot fallback"
    )
    assert WORKING_DIR_ABORT_PATTERN.search(text), (
        "spec.md does not state that the working dir aborts rather than falls back to the docroot"
    )


def test_implementation_notes_working_dir_aborts_rather_than_falls_back_to_docroot() -> None:
    """AC: `docs/implementation-notes.md`'s working-dir preference order must
    match the abort rule, not the superseded last-resort docroot fallback —
    the SKILL.md files it sits alongside already state the abort."""

    text = _text(IMPLEMENTATION_NOTES)
    assert not LAST_RESORT_FALLBACK_PATTERN.search(text), (
        "implementation-notes.md still describes the superseded last-resort docroot fallback"
    )
    assert WORKING_DIR_ABORT_PATTERN.search(text), (
        "implementation-notes.md does not state that the working dir aborts rather than "
        "falls back to the docroot"
    )


def test_adr_0008_carries_a_note_on_execute_php_retrieval_and_the_prohibition() -> None:
    """AC: ADR-0008 carries an appended note recording execute-php as the
    retrieval mechanism for outside-docroot files and the prohibition on
    transient docroot copies of pass.key (operator ADR authority, 2026-07-19).
    The original decision text is untouched — only a note is appended."""

    text = _text(ADR_0008)
    assert "execute-php" in text, "ADR-0008 does not record execute-php as the retrieval mechanism"
    assert PASS_KEY_PROHIBITION_PATTERN.search(text), (
        "ADR-0008 does not record the prohibition on copying pass.key into the docroot"
    )


def test_implementation_notes_download_step_fetches_pass_key_over_execute_php() -> None:
    """`docs/implementation-notes.md` is read alongside the SKILL.md files as the
    invocation-level literals reference (per both skills' own instructions), so
    its download-step literal must name `execute-php` too — leaving it stale
    would contradict the SKILL.md text a reader is told to read right next to
    it. The historic security-review reconciliation appendix is a separate,
    explicitly-labelled record and is not held to this."""

    text = _text(IMPLEMENTATION_NOTES)
    sentence = _sentence_containing(text, "Fetch `pass.key`")
    assert sentence, "implementation-notes.md dropped the pass.key fetch literal"
    assert "execute-php" in sentence, (
        f"implementation-notes.md's pass.key fetch step does not name execute-php: {sentence!r}"
    )
    assert not READ_FILE_CHANNEL_PATTERN.search(sentence), (
        f"implementation-notes.md still routes the pass.key fetch over the docroot-only read channel: {sentence!r}"
    )
