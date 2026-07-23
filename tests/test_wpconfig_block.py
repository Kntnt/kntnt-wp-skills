# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Behavioural tests for the wp-config marked-block writer CLI.

The writer is the deterministic seam that replaces the hand-surgery §9.4 once
prescribed: it takes the local ``wp-config.php`` text, the resolved portable
defines, the production table prefix, and the cron decision, and returns the new
full text with the skills' marked block written and every scaffold collision it
supersedes removed. The collision set is *computed* — the portable defines plus
``DISABLE_WP_CRON`` intersected with whatever the scaffold actually shipped —
never a hard-coded name list, because the smoke test's scaffold carried five
collisions where the SKILL's prose named two (issue #42). Every test drives the
real command: the envelope in as JSON, the new text out as JSON, malformed input
loud on stderr.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "wpconfig_block.py"

BEGIN = "// BEGIN kntnt-wp-skills"
END = "// END kntnt-wp-skills"
STOP_EDITING = "/* That's all, stop editing! Happy publishing. */"


def run_block(payload: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    """Run the writer with ``payload`` as JSON on stdin and capture its result."""

    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload).encode(),
        capture_output=True,
    )


def write(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the writer and return the parsed result, asserting it succeeded."""

    result = run_block(payload)
    assert result.returncode == 0, result.stderr.decode()
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def scaffold_without_markers() -> str:
    """The mkwp scaffold shape observed in smoke-test run 2: a plain comment-bracketed
    block of defines and a ``$table_prefix`` assignment, with no machine-readable
    marked block and five defines the resolved plan also sets."""

    return "\n".join(
        [
            "<?php",
            "define('DB_NAME', 'db');",
            "define('DB_USER', 'user');",
            "",
            "/* mkwp scaffold */",
            "define('DISABLE_WP_CRON', true);",
            "define('EMPTY_TRASH_DAYS', 7);",
            "define('WP_DEBUG', false);",
            "define('WP_DEBUG_LOG', false);",
            "define('WP_DEBUG_DISPLAY', false);",
            "",
            "$table_prefix = 'scaffold_';",
            "",
            STOP_EDITING,
            "require_once ABSPATH . 'wp-settings.php';",
            "",
        ]
    )


def run2_payload(wp_config: str) -> dict[str, Any]:
    """The run-2 envelope: the four portable debug defines the plan carries, cron
    left running, and production's prefix."""

    return {
        "wp_config": wp_config,
        "defines": [
            {"name": "EMPTY_TRASH_DAYS", "value": 30},
            {"name": "WP_DEBUG", "value": True},
            {"name": "WP_DEBUG_LOG", "value": True},
            {"name": "WP_DEBUG_DISPLAY", "value": True},
        ],
        "table_prefix": "wp_",
        "cron": "run",
    }


def test_run2_scaffold_removes_all_five_collisions_and_block_values_win() -> None:
    # Arrange — the observed run-2 scaffold with five colliding defines.
    payload = run2_payload(scaffold_without_markers())

    # Act.
    result = write(payload)
    text = result["wp_config"]

    # Assert — every collision (the four portable defines plus DISABLE_WP_CRON)
    # is reported removed, computed from the scaffold, not a fixed list of two.
    assert set(result["removed"]) == {
        "DISABLE_WP_CRON",
        "EMPTY_TRASH_DAYS",
        "WP_DEBUG",
        "WP_DEBUG_LOG",
        "WP_DEBUG_DISPLAY",
    }

    # Assert — the scaffold's own colliding lines are gone; only the block's
    # values survive, and the block's values win.
    assert "define('EMPTY_TRASH_DAYS', 7);" not in text
    assert "define('WP_DEBUG', false);" not in text
    assert "$table_prefix = 'scaffold_';" not in text
    assert "define('EMPTY_TRASH_DAYS', 30);" in text
    assert "define('WP_DEBUG', true);" in text
    assert "$table_prefix = 'wp_';" in text

    # Assert — cron left running: no DISABLE_WP_CRON define anywhere.
    assert "DISABLE_WP_CRON" not in text

    # Assert — the non-colliding defines are untouched.
    assert "define('DB_NAME', 'db');" in text
    assert "define('DB_USER', 'user');" in text


def test_block_is_inserted_above_the_stop_editing_line() -> None:
    # Arrange.
    payload = run2_payload(scaffold_without_markers())

    # Act.
    text = write(payload)["wp_config"]
    lines = text.split("\n")

    # Assert — a real marked block now exists and sits above the stop line.
    assert BEGIN in lines
    assert END in lines
    assert lines.index(END) < lines.index(STOP_EDITING)


def test_block_content_order_defines_then_prefix_last() -> None:
    # Arrange.
    payload = run2_payload(scaffold_without_markers())

    # Act.
    block = write(payload)["block"]
    block_lines = block.split("\n")

    # Assert — markers bracket the content, defines in input order, prefix last.
    assert block_lines[0] == BEGIN
    assert block_lines[-1] == END
    assert block_lines[1] == "define('EMPTY_TRASH_DAYS', 30);"
    assert block_lines[2] == "define('WP_DEBUG', true);"
    assert block_lines[-2] == "$table_prefix = 'wp_';"


def test_cron_disabled_appends_disable_wp_cron_define() -> None:
    # Arrange — same envelope but cron disabled.
    payload = run2_payload(scaffold_without_markers())
    payload["cron"] = "disabled"

    # Act.
    result = write(payload)
    block_lines = result["block"].split("\n")

    # Assert — DISABLE_WP_CRON appended after the portable defines, before the
    # prefix, set true.
    assert "define('DISABLE_WP_CRON', true);" in block_lines
    assert block_lines.index("define('DISABLE_WP_CRON', true);") < block_lines.index(
        "$table_prefix = 'wp_';"
    )


def test_cron_run_omits_disable_wp_cron_define() -> None:
    # Arrange.
    payload = run2_payload(scaffold_without_markers())

    # Act.
    text = write(payload)["wp_config"]

    # Assert.
    assert "DISABLE_WP_CRON" not in text


def test_running_twice_equals_once_idempotent() -> None:
    # Arrange.
    payload = run2_payload(scaffold_without_markers())

    # Act — feed the first run's output back through the writer.
    first = write(payload)
    second_payload = run2_payload(first["wp_config"])
    second = write(second_payload)

    # Assert — the text is stable and the second run finds nothing left to remove.
    assert second["wp_config"] == first["wp_config"]
    assert second["removed"] == []


def test_existing_markers_are_replaced_not_duplicated() -> None:
    # Arrange — a wp-config that already carries a stale marked block.
    text = "\n".join(
        [
            "<?php",
            BEGIN,
            "define('WP_DEBUG', false);",
            "$table_prefix = 'old_';",
            END,
            "",
            STOP_EDITING,
            "",
        ]
    )
    payload = {
        "wp_config": text,
        "defines": [{"name": "WP_DEBUG", "value": True}],
        "table_prefix": "wp_",
        "cron": "run",
    }

    # Act.
    result = write(payload)
    out = result["wp_config"]

    # Assert — exactly one marked block, refreshed with the new values.
    assert out.count(BEGIN) == 1
    assert out.count(END) == 1
    assert "define('WP_DEBUG', true);" in out
    assert "$table_prefix = 'wp_';" in out
    assert "'old_'" not in out
    assert "define('WP_DEBUG', false);" not in out


def test_defines_inside_the_block_are_not_treated_as_collisions() -> None:
    # Arrange — a re-run where the only WP_DEBUG lives inside the block.
    text = "\n".join(
        [
            "<?php",
            BEGIN,
            "define('WP_DEBUG', true);",
            "$table_prefix = 'wp_';",
            END,
            "",
            STOP_EDITING,
            "",
        ]
    )
    payload = {
        "wp_config": text,
        "defines": [{"name": "WP_DEBUG", "value": True}],
        "table_prefix": "wp_",
        "cron": "run",
    }

    # Act.
    result = write(payload)

    # Assert — nothing outside the block collided, so nothing was removed.
    assert result["removed"] == []


def test_missing_stop_editing_line_fails_loud() -> None:
    # Arrange — no marked block and no stop-editing anchor to insert above.
    text = "\n".join(["<?php", "define('DB_NAME', 'db');", ""])
    payload = {
        "wp_config": text,
        "defines": [{"name": "WP_DEBUG", "value": True}],
        "table_prefix": "wp_",
        "cron": "run",
    }

    # Act.
    result = run_block(payload)

    # Assert — a non-zero exit and a branded diagnostic, no half-written file.
    assert result.returncode != 0
    assert b"wpconfig_block:" in result.stderr


def test_string_literal_escapes_backslash_and_single_quote() -> None:
    # Arrange — a define whose value carries both a backslash and a single quote.
    payload = {
        "wp_config": scaffold_without_markers(),
        "defines": [{"name": "WP_CONTENT_DIR", "value": r"C:\it's\here"}],
        "table_prefix": "wp_",
        "cron": "run",
    }

    # Act.
    block = write(payload)["block"]

    # Assert — single-quoted PHP literal with backslash and quote escaped.
    assert r"define('WP_CONTENT_DIR', 'C:\\it\'s\\here');" in block


def test_scalar_literals_render_bare() -> None:
    # Arrange — the four JSON scalar shapes render as bare PHP literals.
    payload = {
        "wp_config": scaffold_without_markers(),
        "defines": [
            {"name": "A_INT", "value": 42},
            {"name": "A_FLOAT", "value": 1.5},
            {"name": "A_TRUE", "value": True},
            {"name": "A_FALSE", "value": False},
            {"name": "A_NULL", "value": None},
        ],
        "table_prefix": "wp_",
        "cron": "run",
    }

    # Act.
    block = write(payload)["block"]

    # Assert.
    assert "define('A_INT', 42);" in block
    assert "define('A_FLOAT', 1.5);" in block
    assert "define('A_TRUE', true);" in block
    assert "define('A_FALSE', false);" in block
    assert "define('A_NULL', null);" in block


def test_object_value_fails_loud() -> None:
    # Arrange — a non-scalar define value is a contract violation.
    payload = {
        "wp_config": scaffold_without_markers(),
        "defines": [{"name": "BAD", "value": {"nested": 1}}],
        "table_prefix": "wp_",
        "cron": "run",
    }

    # Act.
    result = run_block(payload)

    # Assert.
    assert result.returncode != 0
    assert b"wpconfig_block:" in result.stderr


def test_only_removals_and_the_block_differ_untouched_invariant() -> None:
    # Arrange — a config with one collision and several inert lines.
    payload = run2_payload(scaffold_without_markers())

    # Act.
    text = write(payload)["wp_config"]
    lines = set(text.split("\n"))

    # Assert — every inert line the scaffold shipped is preserved verbatim.
    for inert in [
        "<?php",
        "define('DB_NAME', 'db');",
        "define('DB_USER', 'user');",
        "/* mkwp scaffold */",
        STOP_EDITING,
        "require_once ABSPATH . 'wp-settings.php';",
    ]:
        assert inert in lines


def test_invalid_cron_value_fails_loud() -> None:
    # Arrange — cron must be exactly "run" or "disabled".
    payload = run2_payload(scaffold_without_markers())
    payload["cron"] = "maybe"

    # Act.
    result = run_block(payload)

    # Assert.
    assert result.returncode != 0
    assert b"wpconfig_block:" in result.stderr


def test_non_json_input_fails_loud() -> None:
    # Act.
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], input=b"not json", capture_output=True
    )

    # Assert.
    assert result.returncode != 0
    assert b"wpconfig_block:" in result.stderr
