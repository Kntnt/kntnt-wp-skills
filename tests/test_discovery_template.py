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

import re
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


def test_template_withholds_secret_define_values_at_the_source() -> None:
    """The defines-collection loop must never call constant() on a production
    secret's name — the database password and the auth key / salt / nonce
    family — because scripts/discovery.py's build_defines() redacting the value
    downstream is too late: the plaintext has already crossed the Novamira
    control channel into model context by the time it gets there (spec platform
    constraint 8: the database password never enters model context; issue #19
    review finding)."""

    source = _TEMPLATE.read_text(encoding="utf-8")

    # The template recognises the same secret family scripts/discovery.py's
    # is_secret_define() redacts downstream: the database password by name, and
    # the auth-key / salt / nonce set by name and by the *_SALT / NONCE_*
    # patterns a custom plugin variant may use.
    assert "DB_PASSWORD" in source
    assert "_SALT" in source
    assert "NONCE_" in source

    # The loop that builds each define's value gates its call to constant()
    # behind that recognition — a secret name is never passed to constant() in
    # the first place, not merely redacted from the value constant() already
    # returned.
    loop_start = source.index("foreach ( array_unique( $wp_config_matches[1] )")
    loop_body = source[loop_start:source.index("\n}", loop_start)]
    value_expression = loop_body[loop_body.index("'value' =>"):]
    assert "constant( $define_name )" in value_expression
    assert "secret" in value_expression.lower()


def test_template_collects_cheap_entity_counts_for_the_verify_phase() -> None:
    """The payload must gather production's published-post, published-page,
    attachment, and user counts via cheap COUNT queries, and echo them under
    an 'entity_counts' key — the raw material scripts/discovery.py's
    build_document() and scripts/smoke_test.py's generate_expectations()
    need to assemble the verify phase's counts.* expectations from a live
    fact, not from nothing (docs/spec.md's Verify section already promises
    this; nothing collected it until now)."""

    source = _TEMPLATE.read_text(encoding="utf-8")

    # Each count is a cheap COUNT(*) query, not a full row fetch.
    assert source.count("COUNT(*)") >= 4
    assert "post_type = 'post'" in source
    assert "post_status = 'publish'" in source
    assert "post_type = 'page'" in source
    assert "post_type = 'attachment'" in source
    assert "{$wpdb->users}" in source

    # The attachment count must exclude 'trash' and 'auto-draft' — the exact
    # population `wp post list --post_type=attachment --format=count`
    # counts, since WP-CLI's own default post_status is 'any' (every status
    # except those two), never a bare unfiltered COUNT(*) (which would also
    # sweep in trashed media on a MEDIA_TRASH site, FAILing a correct copy —
    # review finding against the original generator/checker mismatch).
    entity_counts_start = source.index("$entity_counts = [")
    attachment_query_start = source.index("post_type = 'attachment'", entity_counts_start)
    attachment_query = source[attachment_query_start : attachment_query_start + 80]
    assert re.search(r"post_status\s+NOT\s+IN\s*\(\s*'trash'\s*,\s*'auto-draft'\s*\)", attachment_query)

    # The counts are echoed under their own top-level key, in the exact shape
    # scripts/discovery.py's build_entity_counts() consumes.
    assert "'entity_counts'" in source
    assert "'published_posts'" in source
    assert "'published_pages'" in source

    # The collection must run before the echo, not be dead code after it.
    assert source.index("$entity_counts = [") < source.index("echo json_encode(")


def test_wp_config_fallback_respects_the_parent_directory_rule() -> None:
    """The one-directory-above-ABSPATH wp-config.php fallback must not fire when
    the parent is itself a nested WordPress root (has its own wp-settings.php)
    — WordPress's own wp-load.php rule — or a nested-install layout would read
    the outer site's wp-config and report the wrong define set (issue #19
    review finding)."""

    source = _TEMPLATE.read_text(encoding="utf-8")

    # The fallback path is guarded by a check for the parent's own
    # wp-settings.php, evaluated before the fallback is ever selected.
    fallback_index = source.index("dirname( ABSPATH ) . '/wp-config.php'")
    guard_region = source[:fallback_index]
    assert "wp-settings.php" in guard_region
