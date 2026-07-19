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

from collections.abc import Sequence
from typing import Any

__all__ = ["check_dump", "main"]


def check_dump(sql: str, prefix: str, empty_tables: Sequence[str]) -> dict[str, Any]:
    """Return a verdict on a dump's soundness against the discovered prefix.

    Not yet implemented — this stub exists so the test suite can bind to the
    seam and be seen failing before the satisfying code exists.
    """

    raise NotImplementedError


def main() -> None:
    """CLI entry point: read ``{"prefix", "emptyTables", "dumpPath"}`` JSON from
    stdin, write the verdict JSON to stdout."""

    raise NotImplementedError


if __name__ == "__main__":
    main()
