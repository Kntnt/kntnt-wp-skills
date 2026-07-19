"""Consistency check for the read-only discovery payload template.

The discovery template is sent over the control channel and echoes the single
JSON object the pipeline parses. It is INERT in this build (never run against a
live site here), so this is a content check (no PHP runtime), guarding two
cross-issue invariants:

- the payload must enumerate *every* table for the classifier and the dump —
  the "all tables, always" cornerstone (spec user story 16) — not only the
  heaviest-N subset it also reports for the operator's overview;
- the payload must collect production's wp-config defines under a 'defines'
  key, or the downstream classifier, the ported-defines gate, and pull's drift
  detection all have nothing to work from (issue #19: Discovery: collect
  wp-config defines).
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


def test_template_collects_wp_config_defines_for_the_gate() -> None:
    """The payload must parse production's wp-config for its defines and echo
    them under a 'defines' key — the raw material scripts/discovery.py's
    build_defines() and scripts/classify.py's classify_defines() already know
    how to consume, but with nothing to consume until this template supplies it
    (issue #19: the ported-defines gate always resolves to "none" and pull's
    drift detection has nothing to compare against)."""

    source = _TEMPLATE.read_text(encoding="utf-8")

    # wp-config.php is located and read, and its declared constant names are
    # extracted from the source — not merely every constant live in the request,
    # which would sweep in plugin-defined constants wp-config never declared.
    assert "wp-config.php" in source
    assert "file_get_contents(" in source
    assert "preg_match_all(" in source

    # Each define's value is resolved live via defined()/constant() rather than
    # the raw, unevaluated source expression — the same live-value strategy the
    # connection block already uses for DB_HOST and friends above, so a computed
    # or conditionally overridden value is captured as it actually resolves.
    assert "defined( $" in source
    assert "constant( $" in source

    # The collected defines are echoed under their own top-level key, the exact
    # shape scripts/discovery.py's build_defines() consumes: a list of objects
    # each carrying 'name' and 'value'.
    assert "'defines'" in source
    assert "'name'  => $" in source or "'name' => $" in source
    assert "'value' => " in source

    # The collection must run before the echo, not be dead code after it.
    assert source.index("wp-config.php") < source.index("echo json_encode(")
