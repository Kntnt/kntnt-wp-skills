"""Two-chunk preflight-probe consistency test — issue #34 (ADR-0018).

The health-check download preflight used to submit a single tiny
structure-only table. A one-chunk job completes on the Extractor's
create-time kick alone, so the preflight passed on a host whose
*continuation* loopback was dead — and the fault only surfaced mid-run, on
the heavy extraction, as an apparent hang. The fix (ADR-0018) makes the
probe exactly two structure-only tables — ``{table_prefix}options`` and
``{table_prefix}users`` — so the second packaging chunk exercises the
continuation path, and times the probe from create to ready: ≤ 90 s passes
silently, a slower-but-completing probe warns loudly and gates on the
operator, and a probe that misses the preflight budget aborts.

This suite is the anti-drift binding: every surface that describes the
preflight describes the two-table probe and its timing verdict, and the
retired one-table wording cannot reappear anywhere live. The sweep-order
suite (``test_health_check_sweep_order.py``) separately pins the
"Preflight the download path" phrasing these surfaces keep.
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
IMPLEMENTATION_NOTES: Path = REPO_ROOT / "docs" / "implementation-notes.md"

# The surfaces that describe the preflight probe. Each must carry the
# two-table selection and the 90 s silent-pass threshold.
PREFLIGHT_DOCS: tuple[tuple[str, Path], ...] = (
    ("clone SKILL.md", CLONE_SKILL),
    ("pull SKILL.md", PULL_SKILL),
    ("spec.md", SPEC),
    ("implementation notes", IMPLEMENTATION_NOTES),
)

# The probe's pinned elements: the exact two-table selection, the explicit
# two-ness (the whole point — the second chunk rides the continuation path),
# and the timing verdict's silent-pass threshold.
PROBE_ANCHORS: tuple[tuple[str, str], ...] = (
    ("options probe table", r"\{table_prefix\}options"),
    ("users probe table", r"\{table_prefix\}users"),
    ("exactly-two wording", r"exactly two"),
    ("90 s silent-pass threshold", r"90 s"),
)

# The two skills own the operator-facing slow-verdict warning; its
# distinctive phrase is what a rewrite must preserve.
WARNING_DOCS: tuple[tuple[str, Path], ...] = (
    ("clone SKILL.md", CLONE_SKILL),
    ("pull SKILL.md", PULL_SKILL),
)

# The live surfaces the retired one-table wording must not reappear in — the
# skills, the subagent definitions, the spec, the notes, and the manpages.
LIVE_SURFACES: tuple[Path, ...] = (
    *sorted((REPO_ROOT / "skills").glob("*/SKILL.md")),
    *sorted((REPO_ROOT / "agents").glob("*.md")),
    *sorted((REPO_ROOT / "docs" / "man").glob("*.md")),
    SPEC,
    IMPLEMENTATION_NOTES,
)


@pytest.mark.parametrize("doc_name, path", PREFLIGHT_DOCS)
@pytest.mark.parametrize("anchor_name, pattern", PROBE_ANCHORS)
def test_preflight_is_the_two_table_timed_probe(
    doc_name: str, path: Path, anchor_name: str, pattern: str
) -> None:
    """Every surface that describes the download preflight describes the
    two-table probe — both table names, the explicit two-ness, and the 90 s
    timing threshold — so no surface can quietly revert to a probe the
    continuation path never touches."""

    text = path.read_text(encoding="utf-8")
    assert re.search(pattern, text), (
        f"{doc_name} is missing the preflight probe's {anchor_name} "
        f"/{pattern}/ (issue #34, ADR-0018)"
    )


@pytest.mark.parametrize("doc_name, path", WARNING_DOCS)
def test_slow_probe_warning_names_backstop_cadence(
    doc_name: str, path: Path
) -> None:
    """Both skills carry the slow-verdict warning's distinctive diagnosis —
    the host advances extraction jobs at backstop cadence — so the operator
    gate explains *why* the heavy extraction would crawl, not just that the
    probe was slow."""

    text = path.read_text(encoding="utf-8")
    assert re.search(r"backstop cadence", text), (
        f"{doc_name} is missing the slow-probe warning's 'backstop cadence' "
        "diagnosis (issue #34, ADR-0018)"
    )


@pytest.mark.parametrize(
    "path", LIVE_SURFACES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_one_table_preflight_wording_is_gone(path: Path) -> None:
    """The retired one-table probe wording never reappears in a live
    surface — a single-chunk preflight completes on the create-time kick
    alone and proves nothing about the continuation path."""

    text = path.read_text(encoding="utf-8")
    assert "a single tiny structure-only table" not in text, (
        f"{path.relative_to(REPO_ROOT)} still describes the preflight as "
        "'a single tiny structure-only table' — the probe is exactly two "
        "structure-only tables (issue #34, ADR-0018)"
    )
