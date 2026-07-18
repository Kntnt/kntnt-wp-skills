# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Diff the current production manifest against the stored last-sync baseline.

This helper is the deterministic seam of the transfer engine's file-sync
arithmetic (ADR-0006). The runtime skill emits a manifest of production's
in-scope tree — path, size, and mtime for every included file, together with the
scope (the anchored exclusion prefixes) it was taken under — and reads back the
stored last-sync baseline of the same shape. It pipes both here as one JSON
object on stdin, and the helper writes the two decision sets to stdout: the
``new_or_changed`` set to pack and pull, and the ``production_deleted`` set the
deletion gate draws from.

Three contracts matter above the rest:

- The diff is always production-now against the stored baseline, never against
  the local filesystem — local mtimes are unreliable through the archive-and-sync
  chain, whereas both sides of a baseline diff are production mtimes (platform
  constraint 19).
- Deletion obeys the scope-intersection rule: a path is production-deleted only
  when it is in the baseline, gone from the current manifest, and still in scope
  this run. A subtree excluded this run but present in the baseline (finally
  excluding the gallery) is out of scope for the deletion diff, so its
  still-present files are never mis-classified as deleted (ADR-0006).
- Malformed input fails loudly: a non-zero exit and a diagnostic on stderr, never
  a half-built document on stdout.

Detection is size + mtime, mirroring rsync's default quick-check: a size-only
change and an mtime-only change both count as changed. An empty baseline is the
clone case — everything is new, and nothing can be deleted.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any


class DiffError(Exception):
    """Raised when the input is malformed: not an object, missing a required
    section, or carrying a field of the wrong type. The CLI turns this into a
    loud non-zero exit rather than emitting a partial document."""


@dataclass(frozen=True)
class Entry:
    """One manifest row's comparable state: the size and mtime the size+mtime
    quick-check tests. The path is the dict key that carries it, so it is not
    repeated here."""

    size: int
    mtime: float


@dataclass(frozen=True)
class Manifest:
    """A production-tree manifest with the scope it was taken under: the in-scope
    entries keyed by their production-relative path, and the anchored exclusion
    prefixes that scope applied. The stored baseline and the current run share
    this one shape, so a run's current manifest becomes the next run's baseline
    unchanged."""

    exclusions: tuple[str, ...]
    entries: dict[str, Entry]


def _require(mapping: Any, key: str, expected: type, context: str) -> Any:
    """Fetch ``mapping[key]``, asserting the mapping is an object and the value
    has the expected type; raise :class:`DiffError` with a precise message
    otherwise. This is the boundary check that makes malformed input fail loud."""

    if not isinstance(mapping, dict):
        raise DiffError(f"{context}: expected an object, got {type(mapping).__name__}")
    if key not in mapping:
        raise DiffError(f"{context}: missing required field {key!r}")
    value = mapping[key]
    if not isinstance(value, expected):
        raise DiffError(
            f"{context}: field {key!r} must be {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    return value


def _optional(
    mapping: dict[str, Any], key: str, expected: type, default: Any, context: str
) -> Any:
    """Fetch an optional ``mapping[key]``: the value when present and well-typed,
    the ``default`` when absent, and a :class:`DiffError` when present but of the
    wrong type — optionality is about presence, never about shape."""

    if key not in mapping:
        return default
    value = mapping[key]
    if not isinstance(value, expected):
        raise DiffError(
            f"{context}: field {key!r} must be {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    return value


def _number(mapping: dict[str, Any], key: str, context: str) -> float:
    """Fetch a required numeric ``mapping[key]`` as a float, accepting an integer
    or fractional mtime alike and rejecting anything else loudly. mtime is the
    half of the quick-check that a string or object would silently poison, so it
    is validated at the boundary rather than trusted."""

    if key not in mapping:
        raise DiffError(f"{context}: missing required field {key!r}")
    value = mapping[key]
    if not isinstance(value, (int, float)):
        raise DiffError(
            f"{context}: field {key!r} must be a number, got {type(value).__name__}"
        )
    return float(value)


def _exclusions(side: dict[str, Any], context: str) -> tuple[str, ...]:
    """Parse the scope's anchored exclusion prefixes, defaulting to none when the
    scope or its exclusions are absent. A trailing slash is normalised away so a
    prefix matches the same paths however the emitter spelled it, and a
    non-string entry fails loudly rather than crashing the later prefix check."""

    scope = _optional(side, "scope", dict, {}, context)
    raw_exclusions = _optional(scope, "exclusions", list, [], f"{context}.scope")
    for index, prefix in enumerate(raw_exclusions):
        if not isinstance(prefix, str):
            raise DiffError(
                f"{context}.scope: field 'exclusions'[{index}] must be str, "
                f"got {type(prefix).__name__}"
            )
    return tuple(prefix.rstrip("/") for prefix in raw_exclusions)


def _entries(side: dict[str, Any], context: str) -> dict[str, Entry]:
    """Parse the manifest's entries into a path-keyed map of comparable state.

    Every entry must carry a string path and a numeric size and mtime; a missing
    or mistyped field fails loudly, because an entry that rode in half-formed
    would corrupt both decision sets in silence. Entries default to empty, so an
    absent baseline manifest reads as the clone case rather than an error.
    """

    raw_entries = _optional(side, "entries", list, [], context)
    entries: dict[str, Entry] = {}
    for index, raw_entry in enumerate(raw_entries):
        item_context = f"{context}.entries[{index}]"
        path = _require(raw_entry, "path", str, item_context)
        entries[path] = Entry(
            size=_require(raw_entry, "size", int, item_context),
            mtime=_number(raw_entry, "mtime", item_context),
        )
    return entries


def parse_manifest(raw: Any, key: str) -> Manifest:
    """Parse one required top-level manifest section — ``baseline`` or
    ``current`` — into a :class:`Manifest`, validating its scope and entries."""

    side = _require(raw, key, dict, "input")
    return Manifest(exclusions=_exclusions(side, key), entries=_entries(side, key))


def is_excluded(path: str, exclusions: tuple[str, ...]) -> bool:
    """Report whether a path falls under any anchored exclusion prefix — an exact
    match or a descendant of an excluded directory. Matching is path-segment
    aware, so excluding ``uploads/gallery`` never swallows a sibling
    ``uploads/gallery-archive``."""

    return any(
        path == prefix or path.startswith(f"{prefix}/") for prefix in exclusions
    )


def diff(baseline: Manifest, current: Manifest) -> dict[str, list[str]]:
    """Compute the new/changed and production-deleted sets from the two manifests.

    ``new_or_changed`` is every current path that is absent from the baseline or
    whose size or mtime moved — the set to pack and pull. ``production_deleted``
    is every baseline path now gone from the current manifest, restricted to
    those still in scope under this run's exclusions: the scope-intersection rule
    that keeps a scope change from mis-classifying still-present files as deleted
    (ADR-0006). Baseline membership already guarantees a path was in scope when
    the baseline was taken, so only this run's scope needs re-testing. Both sets
    are sorted, so the run's record reads the same every time.
    """

    # The pull set: paths new to production, or changed under the size+mtime
    # quick-check since the baseline was taken.
    new_or_changed = sorted(
        path
        for path, entry in current.entries.items()
        if path not in baseline.entries
        or baseline.entries[path].size != entry.size
        or baseline.entries[path].mtime != entry.mtime
    )

    # The deletion candidates: baseline paths gone from the current manifest and
    # still in scope this run — an out-of-scope subtree is protected, not deleted.
    production_deleted = sorted(
        path
        for path in baseline.entries
        if path not in current.entries and not is_excluded(path, current.exclusions)
    )

    return {"new_or_changed": new_or_changed, "production_deleted": production_deleted}


def build_result(raw: Any) -> dict[str, list[str]]:
    """Assemble the diff result from the raw combined input: parse the required
    ``baseline`` and ``current`` manifests, then diff them."""

    baseline = parse_manifest(raw, "baseline")
    current = parse_manifest(raw, "current")
    return diff(baseline, current)


def main() -> int:
    """Read the combined JSON on stdin, emit the two decision sets on stdout, and
    fail loudly on malformed input with a non-zero exit and a stderr diagnostic."""

    raw_text = sys.stdin.read()

    # Parse the raw input, reporting a malformed payload rather than crashing.
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as error:
        print(f"baseline-diff: input is not valid JSON: {error}", file=sys.stderr)
        return 1

    # Build the result, turning any contract violation into a loud exit.
    try:
        result = build_result(raw)
    except DiffError as error:
        print(f"baseline-diff: {error}", file=sys.stderr)
        return 1

    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
