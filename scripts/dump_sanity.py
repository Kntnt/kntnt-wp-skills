# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Prefix-aware sanity checks over a decrypted database dump.

Runs before the destructive local import: it confirms the dump was taken under
the discovered table prefix (WordPress finds nothing if the prefix is wrong),
that the content tables actually carried their rows, and that every
empty-classified table was created but left empty. Deterministic helper on the
transfer engine's single automated seam — SQL text in, a verdict out. See
``docs/spec.md`` (Import and localise) and ``docs/implementation-notes.md``.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

__all__ = ["check_dump", "main"]

# mysqldump wraps identifiers in backticks; both patterns tolerate the backticks
# being present or absent and stop at the first delimiter.
_CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([A-Za-z0-9_$]+)`?",
    re.IGNORECASE,
)
_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+`?([A-Za-z0-9_$]+)`?",
    re.IGNORECASE,
)


def check_dump(sql: str, prefix: str, empty_tables: Sequence[str]) -> dict[str, Any]:
    """Return a verdict on a dump's soundness against the discovered prefix.

    The verdict is ``{"ok": bool, "checks": {...}, "failures": [...]}``. It fails
    when the content table was not created under the prefix (a wrong-prefix
    dump), when the content table carried no rows, or when any empty-classified
    table came down with rows.

    Args:
        sql: The decrypted, decompressed dump text.
        prefix: The table prefix discovered on production.
        empty_tables: The tables classified empty — created, but expected to
            hold no rows.
    """

    created = {match.group(1) for match in _CREATE_RE.finditer(sql)}
    inserted = {match.group(1) for match in _INSERT_RE.finditer(sql)}

    # The content anchor: the posts table must be created under the discovered
    # prefix and must carry rows, or the import is unusable.
    posts = f"{prefix}posts"
    content_table_created = posts in created
    content_inserts_present = posts in inserted

    # Every empty-classified table must exist yet hold no rows.
    non_empty = [table for table in empty_tables if table in inserted]
    missing_empty = [table for table in empty_tables if table not in created]
    empty_tables_ok = not non_empty and not missing_empty

    # Collect human-readable reasons for each failed check.
    failures: list[str] = []
    if not content_table_created:
        failures.append(
            f"content table `{posts}` was not created under the discovered "
            f"prefix `{prefix}` (wrong-prefix dump)"
        )
    if not content_inserts_present:
        failures.append(f"content table `{posts}` carried no rows")
    for table in missing_empty:
        failures.append(f"empty-classified table `{table}` was not created")
    for table in non_empty:
        failures.append(f"empty-classified table `{table}` came down with rows")

    checks = {
        "contentTableCreated": content_table_created,
        "contentInsertsPresent": content_inserts_present,
        "emptyTablesEmpty": empty_tables_ok,
    }
    return {"ok": not failures, "checks": checks, "failures": failures}


def main() -> None:
    """CLI entry point: read ``{"prefix", "emptyTables", "dumpPath"}`` JSON from
    stdin, write the verdict JSON to stdout."""

    config = json.load(sys.stdin)
    sql = Path(config["dumpPath"]).read_text(encoding="utf-8")
    verdict = check_dump(sql, str(config["prefix"]), config.get("emptyTables", []))
    json.dump(verdict, sys.stdout)


if __name__ == "__main__":
    main()
