"""Health-check step-order consistency test — issue #15.

The smoke test against a real site exposed a batching hazard: the health check
ordered the download preflight (step 5) before the stranded-workspace sweep
(step 6), so a batched pair of calls let the sweep delete the preflight's own
throwaway probe directory before the local ``curl`` fetched it, forcing a redo.

The fix is a step swap, not new behaviour, so this suite is the anti-drift
binding: it holds ``skills/clone/SKILL.md``, ``skills/pull/SKILL.md``,
``docs/spec.md``, and both manual pages to the new order — sweep first, then
preflight — and to the one-line note that the two must never run concurrently.
Anchors are the literal step prose, never a snippet of this suite's own text,
so a faithful rewrite stays green while a regression (the old order restored
anywhere, or the concurrency note dropped) reddens.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

CLONE_SKILL: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
PULL_SKILL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
CLONE_MANPAGE: Path = REPO_ROOT / "docs" / "man" / "clone.md"
PULL_MANPAGE: Path = REPO_ROOT / "docs" / "man" / "pull.md"

# The documents whose health-check prose must agree on the new order. Each
# entry pairs the file with the pattern that anchors its "sweep" step and its
# "preflight" step — the two skills spell the sweep step out in full sentences,
# the spec and the manpages use shorter prose, so the anchors differ per file
# while the invariant (sweep precedes preflight) is identical.
ORDERED_DOCS: tuple[tuple[str, Path, str, str], ...] = (
    (
        "clone SKILL.md",
        CLONE_SKILL,
        r"Sweep stranded workspaces",
        r"Preflight the download path",
    ),
    (
        "pull SKILL.md",
        PULL_SKILL,
        r"Sweep stranded workspaces",
        r"Preflight the download path",
    ),
    (
        "spec.md",
        SPEC,
        r"Sweep production's temp and download bases",
        r"Preflight the download path",
    ),
    (
        "clone manual page",
        CLONE_MANPAGE,
        r"sweeps stranded workspaces",
        r"preflights the download path",
    ),
    (
        "pull manual page",
        PULL_MANPAGE,
        r"sweeps stranded workspaces",
        r"preflights the download path",
    ),
)

# The three documents that own the actual health-check step list (the skills
# and the spec) must each carry a one-line note that the sweep must never run
# concurrently with an in-flight preflight — the exact hazard the smoke test
# hit. The manual pages are prose summaries, not the step list, so they are not
# held to this note.
CONCURRENCY_NOTE_DOCS: tuple[tuple[str, Path], ...] = (
    ("clone SKILL.md", CLONE_SKILL),
    ("pull SKILL.md", PULL_SKILL),
    ("spec.md", SPEC),
)


def _pos(text: str, pattern: str, label: str, doc_name: str) -> int:
    """First match position of a case-insensitive ``pattern`` in ``text``,
    failing loudly with the missing anchor when it is absent — so an ordering
    assertion never silently passes on a ``-1`` from an anchor that moved."""

    match = re.search(pattern, text, re.IGNORECASE)
    assert match is not None, f"{doc_name} is missing the {label} anchor /{pattern}/"
    return match.start()


@pytest.mark.parametrize(
    "doc_name, path, sweep_pattern, preflight_pattern", ORDERED_DOCS
)
def test_sweep_precedes_preflight(
    doc_name: str, path: Path, sweep_pattern: str, preflight_pattern: str
) -> None:
    """The stranded-workspace sweep runs before the download preflight in every
    document that states the health-check order, so a batched pair of calls can
    never let the sweep delete the preflight's own probe directory."""

    text = path.read_text(encoding="utf-8")
    sweep_pos = _pos(text, sweep_pattern, "sweep", doc_name)
    preflight_pos = _pos(text, preflight_pattern, "preflight", doc_name)
    assert sweep_pos < preflight_pos, (
        f"{doc_name} orders the download preflight before the stranded-workspace "
        "sweep — the sweep must run first so a batched pair of calls can never "
        "delete the preflight's own probe directory before it is fetched"
    )


@pytest.mark.parametrize("doc_name, path", CONCURRENCY_NOTE_DOCS)
def test_sweep_never_runs_concurrently_with_preflight_is_noted(
    doc_name: str, path: Path
) -> None:
    """Each document owning the health-check step list carries a one-line note
    that the sweep must never run concurrently with an in-flight preflight —
    the exact batching hazard the smoke test hit, called out so a future
    re-ordering or re-batching cannot reintroduce it silently."""

    text = path.read_text(encoding="utf-8")
    assert re.search(r"never run", text, re.IGNORECASE), (
        f"{doc_name} is missing the sweep/preflight concurrency note"
    )
    assert re.search(r"concurrently", text, re.IGNORECASE), (
        f"{doc_name} is missing the sweep/preflight concurrency note"
    )
    assert re.search(r"in-flight preflight", text, re.IGNORECASE), (
        f"{doc_name} is missing the sweep/preflight concurrency note"
    )
