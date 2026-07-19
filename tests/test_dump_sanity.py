"""Tests for the prefix-aware dump sanity checks.

The checks accept a well-formed dump and reject the two failure modes that would
otherwise surface only after a destructive import: a dump taken under the wrong
table prefix (WordPress would find no tables) and an empty-classified table that
came down carrying rows.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import dump_sanity

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

_EMPTY_TABLES = ["wp_independent_analytics_pages", "wp_relevanssi"]


def _wellformed_dump(prefix: str = "wp_") -> str:
    """A dump where the content tables carry rows and the empty-classified
    tables are created but hold none."""

    return (
        f"CREATE TABLE `{prefix}posts` (`ID` bigint);\n"
        f"INSERT INTO `{prefix}posts` VALUES (1),(2);\n"
        f"CREATE TABLE `{prefix}options` (`option_id` bigint);\n"
        f"INSERT INTO `{prefix}options` VALUES (1);\n"
        f"CREATE TABLE `{prefix}independent_analytics_pages` (`id` bigint);\n"
        f"CREATE TABLE `{prefix}relevanssi` (`doc` bigint);\n"
    )


def test_wellformed_dump_passes() -> None:
    """A sound dump under the discovered prefix passes every check."""

    verdict = dump_sanity.check_dump(_wellformed_dump(), "wp_", _EMPTY_TABLES)

    assert verdict["ok"] is True
    assert verdict["failures"] == []


def test_wrong_prefix_dump_is_rejected() -> None:
    """A dump whose tables use a different prefix than discovered is rejected —
    the imported tables would exist but WordPress could not see them."""

    dump = _wellformed_dump(prefix="old_")

    verdict = dump_sanity.check_dump(dump, "wp_", _EMPTY_TABLES)

    assert verdict["ok"] is False
    assert verdict["failures"]


def test_nonempty_empty_classified_table_is_rejected() -> None:
    """An empty-classified table that came down with rows is rejected."""

    dump = _wellformed_dump() + "INSERT INTO `wp_relevanssi` VALUES (1);\n"

    verdict = dump_sanity.check_dump(dump, "wp_", _EMPTY_TABLES)

    assert verdict["ok"] is False
    assert verdict["failures"]


def test_missing_content_inserts_is_rejected() -> None:
    """A dump with the content table created but empty is rejected — the data
    did not make it in."""

    dump = (
        "CREATE TABLE `wp_posts` (`ID` bigint);\n"
        "CREATE TABLE `wp_independent_analytics_pages` (`id` bigint);\n"
        "CREATE TABLE `wp_relevanssi` (`doc` bigint);\n"
    )

    verdict = dump_sanity.check_dump(dump, "wp_", _EMPTY_TABLES)

    assert verdict["ok"] is False
    assert verdict["failures"]


def test_cli_reads_config_and_dump_file(tmp_path: Path) -> None:
    """The helper is a CLI: a JSON config naming the dump path on stdin, a
    verdict JSON on stdout."""

    dump_file = tmp_path / "dump.sql"
    dump_file.write_text(_wellformed_dump(), encoding="utf-8")
    config = {
        "prefix": "wp_",
        "emptyTables": _EMPTY_TABLES,
        "dumpPath": str(dump_file),
    }

    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "dump_sanity.py")],
        input=json.dumps(config),
        capture_output=True,
        text=True,
        check=True,
    )

    verdict = json.loads(result.stdout)
    assert verdict["ok"] is True
