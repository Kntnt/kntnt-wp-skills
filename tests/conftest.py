"""Shared test configuration for the deterministic-helper suite.

The single automated seam for this plugin is the deterministic helper CLI, so
these tests never reach a live site, a real DDEV instance, or the Kntnt
Extractor REST API. This module's only job is to make the standalone helper
scripts importable by the tests that exercise them at that seam (``import
flags``, ``import smoke_test``, ``import classify``, …), without packaging
them. They live in two places: the shared transfer-engine helpers under
``scripts/``, and the two the portable ``mkwp`` skill owns and ships inside its
own directory (``skills/mkwp/scripts/``, issue #51).

It also parses the canonical poll-discipline document, so the suites that
enforce that discipline read their pinned phrases from the document rather
than restating them in Python — the document is the source of truth for a
product decision, and a test is a poor place to keep one.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Make the standalone helper scripts importable without packaging them, from
# each directory that holds one.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "clone" / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "mkwp" / "scripts"))

# The canonical statement of the poll discipline. Its pinned-phrase sections are
# what ``test_poll_discipline_consistency.py`` and
# ``test_poll_agent_single_verdict_consistency.py`` hold every surface to.
POLL_DISCIPLINE_DOC: Path = REPO_ROOT / "docs" / "poll-discipline.md"


def pinned_phrases(section_prefix: str) -> dict[str, str]:
    """Read the pinned phrases out of one ``## Pinned phrases…`` section of the
    canonical poll-discipline document.

    A phrase is an ``### <name>`` heading followed, anywhere before the next
    heading of the same or higher level, by a fenced ``text`` block holding the
    exact wording every surface must carry. Returning them keyed by name lets a
    suite parametrise over them and name the offender in its failure message.

    Raises rather than returning empty when the section is missing: a data-driven
    suite whose data silently vanished would pass while enforcing nothing, which
    is the one failure mode this indirection could otherwise introduce.
    """

    text = POLL_DISCIPLINE_DOC.read_text(encoding="utf-8")
    sections = [
        block
        for block in re.split(r"^## ", text, flags=re.MULTILINE)
        if block.startswith(section_prefix)
    ]
    if len(sections) != 1:
        raise AssertionError(
            f"{POLL_DISCIPLINE_DOC.name} must hold exactly one '## {section_prefix}…' "
            f"section; found {len(sections)}"
        )

    phrases: dict[str, str] = {}
    for name, fenced in re.findall(
        r"^### (.+?)\n(.*?)(?=^#{1,3} |\Z)", sections[0], flags=re.MULTILINE | re.DOTALL
    ):
        block = re.search(r"```text\n(.*?)\n```", fenced, flags=re.DOTALL)
        if block is not None:
            phrases[name.strip()] = block.group(1).strip()
    if not phrases:
        raise AssertionError(
            f"{POLL_DISCIPLINE_DOC.name}'s '## {section_prefix}…' section defines no "
            "pinned phrases; the suites reading it would enforce nothing"
        )

    return phrases
