"""Vanished-file submission — the skills send ``strict: false`` and surface skips.

A file manifest is a snapshot and a live site is not. Resubmitting a
hours-old selection used to die as an opaque 404; Extractor now accepts
``strict: false``, skips vanished files, and names every missing table and
every missing file on a remaining 404. This suite binds the caller: the
agent that actually POSTs, both SKILLs, and the spec all send the member,
surface ``skipped_files``, and unseal against the remaining file list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]

EXTRACT_TRANSFER: Path = REPO_ROOT / "agents" / "extract-transfer.md"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
IMPLEMENTATION_NOTES: Path = REPO_ROOT / "docs" / "implementation-notes.md"
CLONE: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
PULL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"

SURFACES: tuple[Path, ...] = (
    EXTRACT_TRANSFER,
    SPEC,
    IMPLEMENTATION_NOTES,
    CLONE,
    PULL,
)


@pytest.mark.parametrize("path", SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_every_submit_surface_sends_strict_false(path: Path) -> None:
    """The main extraction is submitted with strict: false, so a vanished
    file is a reported skip rather than a fatal 404."""

    text = path.read_text(encoding="utf-8")
    assert "`strict: false`" in text or '"strict": false' in text, (
        f"{path.relative_to(REPO_ROOT)} never tells the caller to submit "
        "with strict: false"
    )


def test_extract_transfer_posts_the_member_on_the_wire() -> None:
    """The agent that actually POSTs carries the JSON member, not just prose."""

    text = EXTRACT_TRANSFER.read_text(encoding="utf-8")
    assert '"strict": false' in text, (
        "extract-transfer.md must put \"strict\": false on the POST body — "
        "a SKILL that only mentions the mode in prose will not change the wire"
    )


def test_extract_transfer_surfaces_skipped_files() -> None:
    """Skipped names are operator-visible and recorded in the evidence block."""

    text = EXTRACT_TRANSFER.read_text(encoding="utf-8")
    assert "skipped_files" in text
    assert "`skipped_files`" in text or "skipped_files —" in text


def test_extract_transfer_unseals_the_remaining_file_list() -> None:
    """The container holds what the plugin packaged, so unseal must drop skips."""

    text = EXTRACT_TRANSFER.read_text(encoding="utf-8")
    assert "minus" in text and "skipped_files" in text, (
        "extract-transfer.md must unseal against the submitted files minus "
        "skipped_files — passing the original selection fails the container check"
    )


@pytest.mark.parametrize("path", (CLONE, PULL), ids=("clone", "pull"))
def test_skills_surface_skipped_files(path: Path) -> None:
    """Both SKILLs tell the operator that skipped_files are gone, not an error."""

    text = path.read_text(encoding="utf-8")
    assert "skipped_files" in text
    assert "vanished" in text.lower() or "gone from production" in text
