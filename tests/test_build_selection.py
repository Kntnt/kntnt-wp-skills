# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Behavioural tests for the extraction-selection builder CLI.

The builder is the deterministic seam that turns the resolved plan's table-content
split and the resolved file set into the ``POST /extractions`` selection (ADR-0017):
content tables into ``tables`` (full data), empty-classified tables into
``tables_structure_only`` (DROP/CREATE DDL, no rows), and the resolved paths into
``files``. Its whole job is to build a selection the plugin will accept — never
overlapping (the plugin's 422), never wholly empty (the plugin's other 422) —
from the discovered enumerations, so a malformed selection is caught here rather
than on the round trip. Every test drives the real command: the split and file
set in as JSON, the selection out as JSON, malformed input loud on stderr.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_selection.py"


def run_build(payload: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    """Run the builder with ``payload`` as JSON on stdin and capture its result."""

    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload).encode(),
        capture_output=True,
    )


def build(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the builder and return the parsed selection, asserting it succeeded."""

    result = run_build(payload)
    assert result.returncode == 0, result.stderr.decode()
    selection: dict[str, Any] = json.loads(result.stdout)
    return selection


def test_the_split_maps_full_to_tables_and_empty_to_structure_only() -> None:
    # Arrange — a resolved table-content split: content tables carried full,
    # operational tables created empty (schema-only).
    payload = {
        "table_content": {
            "full": ["wp_posts", "wp_options", "wp_users"],
            "empty": [
                {"name": "wp_statistics", "category": "analytics"},
                {"name": "wp_relevanssi", "category": "search_index"},
            ],
        },
        "files": ["wp-content/uploads/2024/05/banner.jpg"],
    }

    # Act.
    selection = build(payload)

    # Assert — full data into tables, empty-classified into structure-only, the
    # resolved paths into files, no table in both lists.
    assert selection["tables"] == ["wp_posts", "wp_options", "wp_users"]
    assert selection["tables_structure_only"] == ["wp_statistics", "wp_relevanssi"]
    assert selection["files"] == ["wp-content/uploads/2024/05/banner.jpg"]


def test_a_pull_with_no_changed_files_still_builds_a_valid_selection() -> None:
    # Arrange — a pull whose baseline diff found no new/changed files: the empty
    # file set is legitimate, and the table selection alone is a valid extraction.
    payload = {
        "table_content": {
            "full": ["wp_posts"],
            "empty": [{"name": "wp_statistics", "category": "analytics"}],
        },
        "files": [],
    }

    # Act.
    selection = build(payload)

    # Assert.
    assert selection["files"] == []
    assert selection["tables"] == ["wp_posts"]
    assert selection["tables_structure_only"] == ["wp_statistics"]


def test_a_table_in_both_lists_fails_loudly() -> None:
    # Arrange — a split that names one table both full and empty would be rejected
    # by the plugin (422 overlapping_selection); the builder must refuse it here,
    # from the discovered enumerations, rather than on the round trip.
    payload = {
        "table_content": {
            "full": ["wp_posts", "wp_options"],
            "empty": [{"name": "wp_options", "category": "analytics"}],
        },
        "files": [],
    }

    # Act.
    result = run_build(payload)

    # Assert — a loud, branded diagnostic naming the overlap, never a selection.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"build_selection:")
    assert b"wp_options" in result.stderr


def test_a_wholly_empty_selection_fails_loudly() -> None:
    # Arrange — no tables and no files at all: the plugin rejects an empty
    # selection (422), so the builder refuses to submit one.
    payload = {"table_content": {"full": [], "empty": []}, "files": []}

    # Act.
    result = run_build(payload)

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"build_selection:")


def test_duplicate_paths_and_names_are_de_duplicated() -> None:
    # Arrange — a resolved set that happens to repeat a path or a table name must
    # not carry the duplicate into the selection (a repeated name is a needless
    # 404/again hazard and inflates the poll totals).
    payload = {
        "table_content": {
            "full": ["wp_posts", "wp_posts"],
            "empty": [
                {"name": "wp_statistics", "category": "analytics"},
                {"name": "wp_statistics", "category": "analytics"},
            ],
        },
        "files": ["a.jpg", "a.jpg", "b.jpg"],
    }

    # Act.
    selection = build(payload)

    # Assert — first occurrence order preserved, duplicates dropped.
    assert selection["tables"] == ["wp_posts"]
    assert selection["tables_structure_only"] == ["wp_statistics"]
    assert selection["files"] == ["a.jpg", "b.jpg"]


def test_a_malformed_empty_entry_fails_loudly() -> None:
    # Arrange — an empty-split entry lacking its 'name' must fail loud rather than
    # crash on a KeyError or ride a nameless table into the selection.
    payload = {
        "table_content": {"full": ["wp_posts"], "empty": [{"category": "analytics"}]},
        "files": [],
    }

    # Act.
    result = run_build(payload)

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"build_selection:")
    assert b"name" in result.stderr


def test_a_non_string_file_fails_loudly() -> None:
    # Arrange — a non-string file path is malformed and must not ride into the
    # selection.
    payload = {
        "table_content": {"full": ["wp_posts"], "empty": []},
        "files": ["ok.jpg", 42],
    }

    # Act.
    result = run_build(payload)

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"build_selection:")
    assert b"files" in result.stderr


def test_malformed_json_input_fails_loudly() -> None:
    # Arrange & Act.
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], input=b"not json", capture_output=True
    )

    # Assert.
    assert result.returncode != 0
    assert b"JSON" in result.stderr
    assert result.stdout == b""
