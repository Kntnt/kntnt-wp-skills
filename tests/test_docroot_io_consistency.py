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


def _text(path: Path) -> str:
    """Read a documentation file as UTF-8 text."""

    return path.read_text(encoding="utf-8")


def _sentence_containing(text: str, anchor: str) -> str | None:
    """Return the single period-delimited sentence in ``text`` that contains
    ``anchor``, or ``None`` when no sentence matches.

    Bounds the search to one sentence so a downstream assertion checks what
    *that* instruction names as its channel, not merely what the file mentions
    somewhere else entirely.
    """

    pattern = re.compile(rf"[^.\n]*{re.escape(anchor)}[^.\n]*\.", re.IGNORECASE)
    match = pattern.search(text)
    return match.group(0) if match else None


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
    assert "read-file" not in sentence, (
        f"{skill}/SKILL.md still routes the pass.key fetch over read-file: {sentence!r}"
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
