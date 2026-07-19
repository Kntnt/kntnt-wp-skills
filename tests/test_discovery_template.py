"""Consistency check for the read-only discovery payload template.

The discovery template is sent over the control channel and echoes the single
JSON object the pipeline parses. It is INERT in this build (never run against a
live site here), so this is a content check (no PHP runtime), guarding the one
cross-issue invariant the whole dump rests on: the payload must enumerate *every*
table for the classifier and the dump — the "all tables, always" cornerstone
(spec user story 16) — not only the heaviest-N subset it also reports for the
operator's overview.
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "discovery.php"


def test_template_exists() -> None:
    """The plugin ships the read-only discovery payload."""

    assert _TEMPLATE.is_file()


def test_template_enumerates_every_table_not_only_the_report_subset() -> None:
    """The payload must emit the complete table enumeration the dump needs, built
    for every row and independent of the heaviest-N report cap — otherwise tables
    beyond the report subset are silently omitted and the copy hits missing tables
    on import (spec user story 16: all tables, always)."""

    source = _TEMPLATE.read_text(encoding="utf-8")

    # The heaviest-N report subset stays capped for the operator's overview.
    assert "count( $top_tables ) < 20" in source

    # The authoritative enumeration is collected for every table, uncapped, and
    # emitted under its own key for the classifier and the dump.
    assert "$all_tables[] = $row['name'];" in source
    assert "'tables'" in source

    # The full enumeration must not sit behind the heaviest-N report cap.
    loop = source[source.index("foreach ( $table_rows"):]
    assert loop.index("$all_tables[]") < loop.index("count( $top_tables ) < 20")
