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
- ``files`` — the resolved, already-scope-filtered install-root-relative paths.

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
    files = _dedupe(_string_list(payload.get("files", []), "files"))

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
