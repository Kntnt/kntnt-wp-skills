# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Build the ``POST /extractions`` selection from the resolved plan.

This helper is the deterministic seam that turns two resolved inputs — the plan's
table-content split (``resolve_plan.py``'s ``db_table_content`` value, already
folded for the user-submissions gate) and the resolved file set (the baseline
diff's new/changed paths at pull, or the whole in-scope tree at clone) — into the
three lists the extraction submits (ADR-0017):

- ``tables`` — the content/config/users/CRM tables carried in full.
- ``tables_structure_only`` — every empty-classified table, so the table exists
  locally with its schema and zero rows.
- ``files`` — the resolved, already-scope-filtered install-root-relative paths,
  accepted either as a flat list of path strings or as ``filter_manifest.py``'s
  own output shape (``{"entries": [{"path": ..., ...}, ...], "scope": {...}}``)
  piped straight in, with no hand-extraction of the path list at the call site.

Its whole reason to exist is to hand the plugin a selection it will accept. The
plugin rejects a self-overlapping selection (a table in both table lists) and a
wholly empty one, each with a ``422`` (platform constraint 1); the builder catches
both here, from the discovered enumerations, so the failure is loud and local
rather than a wasted round trip. Malformed input fails loudly — a non-zero exit
and a ``build_selection:`` diagnostic on stderr, never a half-built selection.
"""

from __future__ import annotations

import json
import sys
from typing import Any


class SelectionError(Exception):
    """Raised when the input is malformed or the resulting selection is one the
    plugin would reject. The CLI turns this into a loud non-zero exit rather than
    emitting a selection that cannot be submitted."""


def _dedupe(items: list[str]) -> list[str]:
    """Drop duplicates while preserving first-occurrence order — a repeated table
    name or path is a needless existence-check hazard and inflates the poll
    totals, so it never reaches the selection."""

    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _string_list(value: Any, context: str) -> list[str]:
    """Assert a value is a list of strings, raising :class:`SelectionError`
    otherwise — the boundary that keeps a stray non-string out of the selection."""

    if not isinstance(value, list):
        raise SelectionError(f"{context} must be a list, got {type(value).__name__}")
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise SelectionError(
                f"{context}[{index}] must be str, got {type(item).__name__}"
            )
    return value


def _manifest_paths(value: dict[str, Any]) -> list[str]:
    """Extract the path list from ``filter_manifest.py``'s own output shape
    (``{"entries": [{"path": ..., ...}, ...], "scope": {...}}``), so that
    shape can be piped into ``files`` directly with no hand-extraction at the
    call site (issue #48). ``scope`` rides along unused — it is meaningful to
    ``baseline_diff.py``, not here. Fails loud on a malformed ``entries`` list
    or element, mirroring ``_empty_names``'s style, rather than crashing on a
    missing key or riding a pathless entry into the selection."""

    entries = value.get("entries")
    if not isinstance(entries, list):
        raise SelectionError(
            f"files.entries must be a list, got {type(entries).__name__}"
        )
    paths: list[str] = []
    for index, entry in enumerate(entries):
        context = f"files.entries[{index}]"
        if not isinstance(entry, dict):
            raise SelectionError(
                f"{context} must be an object, got {type(entry).__name__}"
            )
        path = entry.get("path")
        if not isinstance(path, str):
            raise SelectionError(f"{context}: missing a string 'path'")
        paths.append(path)
    return paths


def _empty_names(value: Any) -> list[str]:
    """Read the empty split's table names from its ``{name, category}`` records,
    failing loud on a record that is not an object or lacks its ``name`` rather
    than riding a nameless table into the structure-only list."""

    if not isinstance(value, list):
        raise SelectionError(
            f"table_content.empty must be a list, got {type(value).__name__}"
        )
    names: list[str] = []
    for index, record in enumerate(value):
        context = f"table_content.empty[{index}]"
        if not isinstance(record, dict):
            raise SelectionError(
                f"{context} must be an object, got {type(record).__name__}"
            )
        name = record.get("name")
        if not isinstance(name, str):
            raise SelectionError(f"{context}: missing a string 'name'")
        names.append(name)
    return names


def build_selection(payload: Any) -> dict[str, Any]:
    """Assemble the extraction selection from the resolved table split and file
    set, refusing an overlapping or wholly empty selection the plugin would
    reject."""

    if not isinstance(payload, dict):
        raise SelectionError(f"input must be an object, got {type(payload).__name__}")

    table_content = payload.get("table_content", {})
    if not isinstance(table_content, dict):
        raise SelectionError(
            f"table_content must be an object, got {type(table_content).__name__}"
        )

    tables = _dedupe(_string_list(table_content.get("full", []), "table_content.full"))
    structure_only = _dedupe(_empty_names(table_content.get("empty", [])))

    # 'files' accepts either the flat path-string list build_selection has
    # always taken, or filter_manifest.py's own {entries, scope} output shape
    # piped straight in — the composable fix for issue #48, so the SKILL walk
    # never needs a hand-written transform between the two helpers.
    raw_files = payload.get("files", [])
    if isinstance(raw_files, dict):
        files = _dedupe(_manifest_paths(raw_files))
    elif isinstance(raw_files, list):
        files = _dedupe(_string_list(raw_files, "files"))
    else:
        raise SelectionError(
            "files must be a list of path strings or a filter_manifest.py "
            f"output object ({{'entries': [...]}}), got {type(raw_files).__name__}"
        )

    # A table named both full and structure-only is the plugin's overlapping
    # selection (422); refuse it here, naming the offenders.
    overlap = sorted(set(tables) & set(structure_only))
    if overlap:
        raise SelectionError(
            "a table is in both the full and structure-only lists: "
            + ", ".join(overlap)
        )

    # An empty selection is the plugin's other 422; a real run always carries at
    # least the structure-only operational tables, so an all-empty selection is a
    # malformed plan, not a valid no-op.
    if not (tables or structure_only or files):
        raise SelectionError(
            "the selection is empty: no full tables, structure-only tables, or files"
        )

    return {
        "tables": tables,
        "tables_structure_only": structure_only,
        "files": files,
    }


def main() -> int:
    """Read the resolved inputs on stdin, emit the selection on stdout, and fail
    loudly on malformed input with a non-zero exit and a stderr diagnostic."""

    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as error:
        print(f"build_selection: input is not valid JSON: {error}", file=sys.stderr)
        return 1

    try:
        selection = build_selection(payload)
    except SelectionError as error:
        print(f"build_selection: {error}", file=sys.stderr)
        return 1

    json.dump(selection, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
