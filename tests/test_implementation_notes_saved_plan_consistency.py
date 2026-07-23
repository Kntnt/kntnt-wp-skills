# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Consistency test — bind the "Saved plan — illustrative shape" example in
``docs/implementation-notes.md`` to ``scripts/resolve_plan.py``'s real
persistence contract (issue #45).

The example is documentation, not code, so nothing enforces it stays in step
with ``resolve_plan.py``'s ``SAVED_KEYS`` / ``PERSISTED_METADATA_KEYS`` once the
resolver's saved-plan shape changes (a key renamed, added, or removed). This
test reads the example straight off disk and holds it to the resolver's own
contract, so a future drift — a stale key surviving a resolver rename, or a
resolver key never reflected in the example — fails loudly here instead of
silently misleading the next reader.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import resolve_plan

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
IMPLEMENTATION_NOTES: Path = REPO_ROOT / "docs" / "implementation-notes.md"

# The keys a saved plan may legitimately carry: the resolver's own persistable
# decisions plus the persisted per-site metadata — the single source of truth
# this test holds the doc example to (never a hand-copied list, so a resolver
# rename is caught here automatically).
KNOWN_KEYS: frozenset[str] = (
    frozenset(resolve_plan.SAVED_KEYS.values()) | resolve_plan.PERSISTED_METADATA_KEYS
)


def _saved_plan_example() -> dict[str, Any]:
    """Extract and parse the fenced ``jsonc`` code block under the "Saved plan —
    illustrative shape" heading, stripping ``//`` end-of-line comments (JSON
    proper has none) before parsing."""

    text = IMPLEMENTATION_NOTES.read_text(encoding="utf-8")
    heading = "## Saved plan — illustrative shape"
    start = text.index(heading)
    fence_start = text.index("```jsonc", start) + len("```jsonc")
    fence_end = text.index("```", fence_start)
    raw = text[fence_start:fence_end]

    # Strip trailing `//` comments line by line — a minimal jsonc-to-json pass.
    # Only a `//` preceded by whitespace counts as a comment marker, so a `//`
    # inside a URL value (e.g. `https://...`) is left untouched.
    stripped_lines = [re.sub(r"(?<=\s)//.*$", "", line) for line in raw.splitlines()]
    return json.loads("\n".join(stripped_lines))


def test_example_endpoint_is_the_real_namespace() -> None:
    """The example's endpoint targets the real ``v1`` REST namespace — the
    ``2`` in ``api_version`` is a response-body field, never the namespace, so
    an operator copying the example must not get a 404."""

    example = _saved_plan_example()
    endpoint = example["source"]["extractor_endpoint"]
    assert "/wp-json/kntnt-extractor/v1" in endpoint
    assert "/wp-json/kntnt-extractor/v2" not in endpoint


def test_example_keys_are_all_known_to_the_resolver() -> None:
    """Every top-level key the example shows is one the resolver actually
    persists — no stale or invented key survives."""

    example = _saved_plan_example()
    unknown = set(example) - KNOWN_KEYS
    assert not unknown, (
        f"example carries keys resolve_plan.py never persists: {sorted(unknown)}"
    )


def test_example_round_trips_through_build_saved_plan_unchanged() -> None:
    """Feeding the example back in as the prior saved plan, with no decisions
    resolved this run, reproduces it byte-for-byte — the identity
    ``build_saved_plan`` promises for every key it recognises (docstring of
    ``resolve_plan.build_saved_plan``)."""

    example = _saved_plan_example()
    round_tripped = resolve_plan.build_saved_plan(
        resolved={"decisions": []}, prior=example
    )
    assert round_tripped == example
