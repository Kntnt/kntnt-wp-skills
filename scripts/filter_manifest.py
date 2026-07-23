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
every consumer of the exclusion set shares. A top-level directory prefix with
no ``/`` of its own, such as the core directories ``wp-admin`` and
``wp-includes`` (issue #37), still matches this way — itself or any
descendant — rather than through the root-anchored file-pattern path below.
The credential-bearing pattern family (issue #36) and the root-level core PHP
files (issue #37) are install-root-relative and matched case-insensitively
instead: a ``**/``-prefixed entry matches the path's final segment at any
depth (``.env`` anywhere in the tree), any other *file* entry with no ``/`` of
its own — literal or glob alike — matches only a path that also sits at the
install root (the whole ``wp-config.php`` family, root SQL dumps, root key
material, root core PHP files) — with ``wp-config-sample.php`` carved back out
of the broad ``wp-config-*.php`` variant glob, since it is WordPress' own
bundled template and never carries a real secret.

Malformed input fails loudly: a non-zero exit and a diagnostic on stderr,
never a half-built document on stdout. The same holds for two shapes that are
well-formed JSON but not trustworthy input: a manifest reporting any
``unreadable`` directory (``templates/manifest.php`` could not descend into
it, so the tree it echoes is silently incomplete and would misclassify that
subtree's files as production-deleted) and an explicitly empty
``exclusions`` list (a real resolved exclusion set is never empty — the
canonical always-excluded set, ``scripts/build_exclusions.py``'s
``ALWAYS_EXCLUDED`` constant, is present on every run — so an empty list
signals an unresolved plan, not a legitimate everything-in-scope run). Both
abort here, this helper's single surviving scope-enforcement point.

The resolved ``exclusions`` list is not assembled at the call site: it is the
output of ``scripts/build_exclusions.py``, the single deterministic assembler
that unions the ``ALWAYS_EXCLUDED`` constant with the decision-gated thumbnail,
blob, and media exclusions (issue #35), so both this baseline consumer and the
extraction-selection consumer are fed a byte-identical set.
"""

from __future__ import annotations

import fnmatch
import json
import sys
from typing import Any


class FilterError(Exception):
    """Raised when the input is malformed: not an object, a required field
    missing, or a field of the wrong type. The CLI turns this into a loud
    non-zero exit rather than emitting a partial document."""


# WordPress' own bundled sample config — placeholder values only, never a real
# secret — the one name the broad "wp-config-*.php" credential-variant glob
# (``build_exclusions.py``'s ``ALWAYS_EXCLUDED``) must not swallow (issue #36).
_ALWAYS_ALLOWED = frozenset({"wp-config-sample.php"})

# Marks a pattern that matches its remainder as a basename at any depth in the
# tree (``.env``, ``.env.*``), rather than anchored at the install root.
_ANYWHERE_PREFIX = "**/"


def _matches_anywhere(path: str, pattern: str) -> bool:
    """Match a ``**/``-prefixed pattern against ``path``'s final segment at any
    depth, case-insensitively — ``.env`` files are not only ever at the install
    root, since a bundled toolchain under a plugin or theme can carry its own
    (issue #36)."""

    basename = path.rsplit("/", 1)[-1]
    return fnmatch.fnmatchcase(basename.lower(), pattern[len(_ANYWHERE_PREFIX):].lower())


def _matches_at_root(path: str, pattern: str) -> bool:
    """Match a root-anchored pattern — literal or glob alike — against
    ``path``, case-insensitively, matching only a path with no ``/`` of its
    own. Covers the whole configuration-file family (``wp-config.php`` and its
    backup/swap/variant siblings), root-level SQL dumps, root-level key
    material (issue #36's "install-root-relative and case-insensitive"
    credential-bearing pattern family), and the root-level core PHP files
    (issue #37) — a same-named file nested deeper in the tree is ordinary
    content, not the configuration file, a leaked secret, or core."""

    return "/" not in path and fnmatch.fnmatchcase(path.lower(), pattern.lower())


def is_excluded(path: str, exclusions: tuple[str, ...]) -> bool:
    """Report whether a path falls under any anchored exclusion prefix: an
    exact match or descendant of an excluded directory (including a top-level
    core directory such as ``wp-admin`` or ``wp-includes``, issue #37), a
    root-anchored credential-bearing or core-file pattern, or a ``.env``-style
    pattern matched anywhere in the tree (issue #36) — except
    ``wp-config-sample.php``, which the broad ``wp-config-*.php`` variant
    pattern must not swallow. Mirrors ``scripts/baseline_diff.py``'s
    ``is_excluded`` exactly, so a path this helper drops here is a path the
    diff would have dropped too."""

    if path.lower() in _ALWAYS_ALLOWED:
        return False
    for prefix in exclusions:
        if prefix.startswith(_ANYWHERE_PREFIX):
            if _matches_anywhere(path, prefix):
                return True
        elif path == prefix or path.startswith(f"{prefix}/"):
            return True
        elif "/" not in prefix and _matches_at_root(path, prefix):
            return True
    return False


def _exclusions(raw: dict[str, Any]) -> tuple[str, ...]:
    """Parse the resolved exclusion prefixes, requiring the field to be
    present. This helper is the single surviving scope-enforcement point after
    issues #17 and #18 (see the module docstring): the raw, unfiltered
    ``templates/manifest.php`` output is exactly ``{"entries": [...]}``, with no
    ``exclusions`` key at all, so a caller that pipes that raw response through
    without first merging in the resolved exclusion set must fail loudly rather
    than have the omission silently read as "nothing excluded". An *explicit*
    empty list is likewise rejected: per the specification, a real resolved
    exclusion set is never empty (``scripts/build_exclusions.py``'s
    ``ALWAYS_EXCLUDED`` constant is present on every run), so `[]` here signals a
    plan resolved without its exclusions merged in, not a legitimate
    everything-in-scope run. A trailing slash is normalised away so a prefix
    matches the same paths however the caller spelled it, and a non-string
    entry fails loudly rather than crashing the later prefix check."""

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
    if not value:
        raise FilterError(
            "input: field 'exclusions' is empty — a real resolved exclusion "
            "set is never empty (build_exclusions.py's ALWAYS_EXCLUDED constant "
            "is present on every run); an empty list signals an unresolved plan, "
            "not an everything-in-scope run"
        )
    return tuple(prefix.rstrip("/") for prefix in value)


def _unreadable(raw: dict[str, Any]) -> list[str]:
    """Fetch the manifest's reported unreadable directories — the subtrees
    ``templates/manifest.php``'s walk could not descend into (issue #18: a
    permission-denied directory no longer silently vanishes behind
    ``CATCH_GET_CHILD``). Absent or empty means the walk was clean; each
    element must be a string, and any non-string entry fails loudly rather
    than crashing the join below."""

    value = raw.get("unreadable", [])
    if not isinstance(value, list):
        raise FilterError(
            f"input: field 'unreadable' must be list, got {type(value).__name__}"
        )
    for index, path in enumerate(value):
        if not isinstance(path, str):
            raise FilterError(
                f"input: field 'unreadable'[{index}] must be str, "
                f"got {type(path).__name__}"
            )
    return value


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

    unreadable = _unreadable(raw)
    if unreadable:
        raise FilterError(
            f"input: production reported {len(unreadable)} unreadable "
            f"director{'y' if len(unreadable) == 1 else 'ies'} it could not "
            f"descend into ({', '.join(unreadable)}); the deletion gate cannot "
            "trust a manifest with a silently-incomplete subtree — abort and "
            "investigate before retrying"
        )

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
