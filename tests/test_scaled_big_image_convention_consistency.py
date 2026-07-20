"""The -scaled big-image convention consistency test — issue #30.

#26 narrowed the transfer exclusion and the pull-side regeneration delta to
sizes whose name ``wp media regenerate`` would itself derive from the
attachment's *current* attached file (``<stem>-<W>x<H><ext>``). That
derivation never matches a big-image attachment's genuinely regenerable
sizes: WordPress's big-image-size-threshold feature writes the current
attached file as ``<stem>-scaled<ext>``, but generates every registered
sub-size from the *pre-scaled* original, so its filename never carries the
``-scaled`` token. #30 extends the rule additively: a size derived from the
stem with that exact, case-sensitive terminal token stripped is also
accepted.

This is the same kind of anti-drift binding as
``test_mkwp_floor_version_consistency.py`` and
``test_search_index_reindex_consistency.py``: the exclusion rule
(``scripts/classify.py``) and the pull-side delta rule
(``skills/pull/SKILL.md``) must state the same convention, grounded to the
single source of truth (``classify.SCALED_BIG_IMAGE_SUFFIX``) rather than a
hand-typed literal repeated in each test, so a rewrite that drops the
extension from one side but not the other reddens here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
ADR_0011: Path = REPO_ROOT / "docs" / "adr" / "0011-metadata-driven-thumbnail-regeneration.md"
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
PULL_SKILL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"

import classify  # noqa: E402 — pytest.ini puts scripts/ on pythonpath.

# The single source of truth every document below is bound to, rather than a
# literal "-scaled" repeated across this file.
TOKEN = classify.SCALED_BIG_IMAGE_SUFFIX


def _import_and_localise_section(text: str) -> str:
    """The ``## N. Import and localise`` step's own text — from its heading
    to the next level-2 heading — so a match elsewhere in the file never
    counts (mirrors ``test_search_index_reindex_consistency.py``)."""

    match = re.search(r"^## \d+\. Import and localise\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "no '## N. Import and localise' section found"
    return match.group(1)


def _regenerate_thumbnails_step(section: str) -> str:
    """The pull-delta regeneration step's own numbered-list item — from its
    heading to the next numbered item — so assertions never accidentally
    match the surrounding search-index/flush steps."""

    match = re.search(
        r"^\d+\.\s+\*\*Regenerate thumbnails.*?(?=^\d+\.\s+\*\*|\Z)", section, re.MULTILINE | re.DOTALL
    )
    assert match, "no 'Regenerate thumbnails' numbered step found in Import and localise"
    return match.group(0)


def test_classify_scaled_suffix_constant_is_the_exact_terminal_token() -> None:
    """The single source of truth every document is bound to below."""

    assert TOKEN == "-scaled"


def test_thumbnail_exclude_set_accepts_the_pre_scaled_stem_additively() -> None:
    """Behavioural anchor: a big-image attachment's regenerable size is
    excluded, its non-matching sibling is kept, and the unstripped-stem match
    still fires too — the additive contract every doc below describes."""

    exclude = set(
        classify.thumbnail_exclude_set(
            classify.PurePosixPath("wp-content/uploads"),
            [
                {
                    "file": "2024/05/photo-scaled.jpg",
                    "sizes": ["photo-300x200.jpg", "photo-drifted.webp", "photo-scaled-150x150.jpg"],
                },
            ],
        )
    )
    assert exclude == {
        "wp-content/uploads/2024/05/photo-300x200.jpg",
        "wp-content/uploads/2024/05/photo-scaled-150x150.jpg",
    }


def test_adr_0011_states_the_scaled_convention_and_cross_references_30() -> None:
    """ADR-0011 records the extension as an amendment, cites the exact
    token, and traces its authority back to issue #30."""

    text = ADR_0011.read_text(encoding="utf-8")
    assert TOKEN in text, "ADR-0011 never states the -scaled terminal token"
    assert "#30" in text, "ADR-0011 never cross-references issue #30"
    assert re.search(r"pre-scaled", text, re.IGNORECASE), (
        "ADR-0011 never explains the pre-scaled-original derivation"
    )


def test_pull_skill_regeneration_step_states_the_scaled_convention() -> None:
    """AC: pull's delta-detector prose stays symmetric with the exclusion
    rule — the -scaled convention is stated right where the regenerable-name
    rule already lives, not merely floating elsewhere in the file."""

    section = _import_and_localise_section(PULL_SKILL.read_text(encoding="utf-8"))
    step = _regenerate_thumbnails_step(section)

    assert TOKEN in step, "pull SKILL.md's regeneration step never states the -scaled terminal token"
    assert re.search(r"pre-scaled", step, re.IGNORECASE), (
        "pull SKILL.md's regeneration step never explains the pre-scaled-original derivation"
    )
    assert re.search(r"#30", step), "pull SKILL.md's regeneration step never cross-references issue #30"


def test_spec_thumbnails_section_states_the_scaled_convention() -> None:
    """docs/spec.md's Thumbnails and regeneration section states the same
    convention as the exclusion rule and the pull-delta prose."""

    text = SPEC.read_text(encoding="utf-8")
    match = re.search(r"^### Thumbnails and regeneration\n(.*?)(?=^### |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "no '### Thumbnails and regeneration' section found in docs/spec.md"
    section = match.group(1)

    assert TOKEN in section, "docs/spec.md's Thumbnails section never states the -scaled terminal token"
    assert re.search(r"pre-scaled", section, re.IGNORECASE), (
        "docs/spec.md's Thumbnails section never explains the pre-scaled-original derivation"
    )


def test_spec_known_limitation_21_states_the_scaled_convention() -> None:
    """docs/spec.md's numbered "known limitations" item on thumbnail
    regeneration must not still describe only the unstripped-stem formula —
    that would misstate the rule #30 extended."""

    text = SPEC.read_text(encoding="utf-8")
    match = re.search(r"^21\. Thumbnail regeneration is DB-only.*$", text, re.MULTILINE)
    assert match, "docs/spec.md's thumbnail-regeneration limitation (item 21) not found"
    item = match.group(0)

    assert TOKEN in item, "docs/spec.md's item 21 never states the -scaled terminal token"


@pytest.mark.parametrize(
    "doc_name, text_getter",
    [
        ("skills/pull/SKILL.md", lambda: _regenerate_thumbnails_step(
            _import_and_localise_section(PULL_SKILL.read_text(encoding="utf-8"))
        )),
        ("docs/adr/0011", lambda: ADR_0011.read_text(encoding="utf-8")),
    ],
)
def test_the_match_is_documented_as_exact_and_case_sensitive_with_no_fuzzy_strip(
    doc_name: str, text_getter
) -> None:
    """AC: "keep it conservative — only the exact terminal token, no fuzzy
    matching" must survive as stated prose, not just as an implementation
    detail invisible to a reader of the orchestration docs."""

    text = text_getter()
    assert re.search(r"exact.{0,40}terminal|terminal.{0,40}exact", text, re.IGNORECASE | re.DOTALL), (
        f"{doc_name} never states the exact-terminal-token requirement"
    )
    assert re.search(r"case.sensitive", text, re.IGNORECASE), (
        f"{doc_name} never states the case-sensitivity requirement"
    )
