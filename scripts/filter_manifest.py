# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Filter production's unfiltered manifest walk to the resolved scope, locally.

This helper is the local-filtering seam issue #18 introduces: production's
manifest walk (``templates/manifest.php``) takes no exclusion payload and
echoes every file under the content tree, so the exclusion set — thousands of
entries on a real site — never travels to production as part of a manifest
request. This helper applies that exclusion set locally instead, turning the
raw walk into the exact shape ``scripts/baseline_diff.py`` has always consumed
as one side of its diff — ``{"scope": {"exclusions": [...]}, "entries": [...]}``
— restricted to the in-scope entries. ``scripts/baseline_diff.py`` itself is
unchanged: it still consumes an already-filtered manifest, exactly as before
issue #18, only now the filtering happened here rather than on production.

Scope semantics are unchanged from the former production-side filter: a path
is excluded when it equals an exclusion prefix or sits under it as a
descendant, matching is path-segment aware (excluding
``wp-content/uploads/gallery`` never swallows a sibling
``wp-content/uploads/gallery-archive``), and every path is anchored at the
WordPress root (the recent anchoring fix, commit de908bd) — the one spelling
every consumer of the exclusion set shares.

Malformed input fails loudly: a non-zero exit and a diagnostic on stderr,
never a half-built document on stdout.
"""

from __future__ import annotations

import json
import sys
from typing import Any


class FilterError(Exception):
    """Raised when the input is malformed: not an object, a required field
    missing, or a field of the wrong type. The CLI turns this into a loud
    non-zero exit rather than emitting a partial document."""


def is_excluded(path: str, exclusions: tuple[str, ...]) -> bool:
    """Report whether a path falls under any anchored exclusion prefix — an
    exact match or a descendant of an excluded directory. Mirrors
    ``scripts/baseline_diff.py``'s ``is_excluded`` exactly, so a path this
    helper drops here is a path the diff would have dropped too."""

    return any(
        path == prefix or path.startswith(f"{prefix}/") for prefix in exclusions
    )


def _exclusions(raw: dict[str, Any]) -> tuple[str, ...]:
    """Parse the resolved exclusion prefixes, requiring the field to be
    present. This helper is the single surviving scope-enforcement point after
    issues #17 and #18 (see the module docstring): the raw, unfiltered
    ``templates/manifest.php`` output is exactly ``{"entries": [...]}``, with no
    ``exclusions`` key at all, so a caller that pipes that raw response through
    without first merging in the resolved exclusion set must fail loudly rather
    than have the omission silently read as "nothing excluded". An *explicit*
    empty list, in contrast, is the legitimate "everything in scope" run and is
    accepted. A trailing slash is normalised away so a prefix matches the same
    paths however the caller spelled it, and a non-string entry fails loudly
    rather than crashing the later prefix check."""

    if "exclusions" not in raw:
        raise FilterError("input: missing required field 'exclusions'")
    value = raw["exclusions"]
    if not isinstance(value, list):
        raise FilterError(
            f"input: field 'exclusions' must be list, got {type(value).__name__}"
        )
    for index, prefix in enumerate(value):
        if not isinstance(prefix, str):
            raise FilterError(
                f"input: field 'exclusions'[{index}] must be str, "
                f"got {type(prefix).__name__}"
            )
    return tuple(prefix.rstrip("/") for prefix in value)


def _entries(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch the raw manifest's entry list, requiring each element to at least
    carry the string ``path`` the exclusion test needs. ``size`` and ``mtime``
    ride through unvalidated here — ``scripts/baseline_diff.py`` validates
    them when it parses this helper's output as its ``current`` side, so
    duplicating that check here would just be a second place to keep in
    sync."""

    if "entries" not in raw:
        raise FilterError("input: missing required field 'entries'")
    entries = raw["entries"]
    if not isinstance(entries, list):
        raise FilterError(
            f"input: field 'entries' must be list, got {type(entries).__name__}"
        )
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise FilterError(f"input.entries[{index}]: expected an object")
        if not isinstance(item.get("path"), str):
            raise FilterError(f"input.entries[{index}]: missing required field 'path'")
    return entries


def filter_manifest(raw: Any) -> dict[str, Any]:
    """Restrict the raw, unfiltered manifest's entries to those in scope under
    the resolved exclusion set, and carry that set forward as the output's
    scope — the shape ``scripts/baseline_diff.py`` diffs against."""

    if not isinstance(raw, dict):
        raise FilterError(f"input: expected an object, got {type(raw).__name__}")

    exclusions = _exclusions(raw)
    entries = _entries(raw)
    in_scope = [row for row in entries if not is_excluded(row["path"], exclusions)]

    return {"scope": {"exclusions": list(exclusions)}, "entries": in_scope}


def main() -> int:
    """Read the raw manifest and the resolved exclusion set on stdin, emit the
    locally-filtered manifest on stdout, and fail loudly on malformed input."""

    raw_text = sys.stdin.read()

    # Parse the raw input, reporting a malformed payload rather than crashing.
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as error:
        print(f"filter-manifest: input is not valid JSON: {error}", file=sys.stderr)
        return 1

    # Build the result, turning any contract violation into a loud exit.
    try:
        result = filter_manifest(raw)
    except FilterError as error:
        print(f"filter-manifest: {error}", file=sys.stderr)
        return 1

    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
