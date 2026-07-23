# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Integration tests spanning the resolve_plan -> classify -> wpconfig_block seam.

The §9.4 pipeline the clone/pull SKILLs prescribe runs three deterministic
helpers back to back: ``classify.py`` splits production's defines into the
portable ``[{name, value}]`` records offered at the gate; ``resolve_plan.py``
resolves the ``wp_config_defines`` decision to the *names* the operator kept
(names only — their values are re-fetched from live state every run); and
``wpconfig_block.py`` writes the marked block. Nothing in the per-helper suites
crossed this seam, so a contract mismatch (the resolver emits names, the writer
wants ``{name, value}`` objects) passed every per-issue gate yet made the
combined pipeline impossible to execute deterministically.

These tests drive the real helpers end to end: they feed a discovery document
through ``classify.py`` and ``resolve_plan.py``, then hand the writer the
classifier's portable records as the value source and the resolver's resolved
name list as the gate selection, and assert the block that lands honours the
gate — every kept define written with its live value, every deselected define
absent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
CLASSIFY = SCRIPTS / "classify.py"
RESOLVE = SCRIPTS / "resolve_plan.py"
WPCONFIG_BLOCK = SCRIPTS / "wpconfig_block.py"

BEGIN = "// BEGIN kntnt-wp-skills"
END = "// END kntnt-wp-skills"
STOP_EDITING = "/* That's all, stop editing! Happy publishing. */"


def run_helper(script: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Run a deterministic helper with ``payload`` as JSON on stdin, asserting it
    succeeded and returning its parsed JSON result."""

    result = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload).encode(),
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()
    return json.loads(result.stdout)


def discovery_document() -> dict[str, Any]:
    """A minimal discovery document carrying three portable defines alongside a
    credential and a salt (both auto-excluded by the classifier), so the portable
    set the writer must honour is a real subset of production's defines."""

    return {
        "site": {"home_url": "https://example.com"},
        "database": {
            "table_prefix": "wp_",
            "flavour": "mariadb",
            "version": "10.11.6-MariaDB",
            "tables": ["wp_posts", "wp_options"],
        },
        "environment": {"php_major_minor": "8.3"},
        "mass_send": {"flip": False, "findings": []},
        "defines": [
            {"name": "DB_PASSWORD", "value": "secret"},
            {"name": "AUTH_SALT", "value": "salt"},
            {"name": "EMPTY_TRASH_DAYS", "value": 30},
            {"name": "WP_DEBUG", "value": True},
            {"name": "WP_POST_REVISIONS", "value": 5},
        ],
    }


def drifted_discovery_document() -> dict[str, Any]:
    """The same production, one drift later: ``WP_POST_REVISIONS`` has been removed
    from wp-config since the plan was saved, so the classifier no longer offers it
    in the portable set. Everything else is identical to ``discovery_document``."""

    document = discovery_document()
    document["defines"] = [
        entry for entry in document["defines"] if entry["name"] != "WP_POST_REVISIONS"
    ]
    return document


def scaffold() -> str:
    """A minimal mkwp scaffold with a stop-editing anchor and no marked block."""

    return "\n".join(["<?php", "", STOP_EDITING, ""])


def block_defines(block: str) -> list[str]:
    """The ``define()`` lines inside a returned marked block."""

    return [line for line in block.split("\n") if line.startswith("define(")]


def test_classifier_portable_records_are_the_writer_value_source() -> None:
    # Arrange — classify production's defines, then resolve the plan with no
    # answers so wp_config_defines resolves to every portable name (the live layer).
    classifications = run_helper(CLASSIFY, discovery_document())
    resolved = run_helper(
        RESOLVE,
        {
            "operation": "resolve",
            "skill": "clone",
            "flags": [],
            "discovery": discovery_document(),
            "classifications": classifications,
        },
    )
    wp_config_defines = next(
        entry for entry in resolved["decisions"] if entry["id"] == "wp_config_defines"
    )

    # The resolver emits names only; the classifier carries the {name, value}
    # records. The writer joins them: portable records as the value source,
    # resolved names as the gate selection.
    result = run_helper(
        WPCONFIG_BLOCK,
        {
            "wp_config": scaffold(),
            "defines": classifications["defines"]["portable"],
            "select": wp_config_defines["value"],
            "table_prefix": "wp_",
            "cron": "run",
        },
    )

    # Assert — every portable define is written with the value the classifier
    # carried, and the auto-excluded credential/salt never appear.
    defines = block_defines(result["block"])
    assert "define('EMPTY_TRASH_DAYS', 30);" in defines
    assert "define('WP_DEBUG', true);" in defines
    assert "define('WP_POST_REVISIONS', 5);" in defines
    assert not any("DB_PASSWORD" in line for line in defines)
    assert not any("AUTH_SALT" in line for line in defines)


def test_deselected_define_at_the_gate_is_never_written() -> None:
    # Arrange — the operator deselects WP_DEBUG at the wp_config_defines gate, so
    # the resolved answer keeps only two of the three portable names.
    classifications = run_helper(CLASSIFY, discovery_document())
    resolved = run_helper(
        RESOLVE,
        {
            "operation": "resolve",
            "skill": "clone",
            "flags": [],
            "discovery": discovery_document(),
            "classifications": classifications,
            "answers": {"wp_config_defines": ["EMPTY_TRASH_DAYS", "WP_POST_REVISIONS"]},
        },
    )
    wp_config_defines = next(
        entry for entry in resolved["decisions"] if entry["id"] == "wp_config_defines"
    )
    assert wp_config_defines["value"] == ["EMPTY_TRASH_DAYS", "WP_POST_REVISIONS"]

    # Act — the writer is handed the full portable record set as the value source
    # but only the two kept names as the selection.
    result = run_helper(
        WPCONFIG_BLOCK,
        {
            "wp_config": scaffold(),
            "defines": classifications["defines"]["portable"],
            "select": wp_config_defines["value"],
            "table_prefix": "wp_",
            "cron": "run",
        },
    )

    # Assert — the deselected define is honoured: it is never written, exactly the
    # gate decision that a wholesale pipe of classifications.defines.portable would
    # silently defeat.
    defines = block_defines(result["block"])
    assert "define('EMPTY_TRASH_DAYS', 30);" in defines
    assert "define('WP_POST_REVISIONS', 5);" in defines
    assert not any("WP_DEBUG" in line for line in defines)


def test_replayed_saved_plan_prunes_a_vanished_ported_define() -> None:
    # Arrange — a saved plan carries two ported defines from an earlier run, but
    # production has since dropped WP_POST_REVISIONS, so this run's classifier only
    # offers EMPTY_TRASH_DAYS. This is the --yes replay path the clone/pull SKILLs
    # walk at §9.4, where the writer runs after the destructive dump import.
    classifications = run_helper(CLASSIFY, drifted_discovery_document())
    portable_names = [entry["name"] for entry in classifications["defines"]["portable"]]
    assert "WP_POST_REVISIONS" not in portable_names

    # Act — resolve the replay with the stale saved selection. The saved layer
    # outranks live, but a saved name production no longer offers must be pruned so
    # the resolved value can never be a superset of what the writer is handed.
    resolved = run_helper(
        RESOLVE,
        {
            "operation": "resolve",
            "skill": "pull",
            "flags": ["--yes"],
            "discovery": drifted_discovery_document(),
            "classifications": classifications,
            "saved_plan": {"ported_defines": ["EMPTY_TRASH_DAYS", "WP_POST_REVISIONS"]},
        },
    )
    wp_config_defines = next(
        entry for entry in resolved["decisions"] if entry["id"] == "wp_config_defines"
    )

    # Assert the resolver pruned the vanished define while still honouring the saved
    # layer for the one that survived — the selection stays a subset of the offered
    # records, sourced from the saved plan.
    assert wp_config_defines["value"] == ["EMPTY_TRASH_DAYS"]
    assert wp_config_defines["source"] == "saved"

    # Act — pipe the resolved selection into the writer exactly as the SKILLs do,
    # with the classifier's current portable records as the value source.
    result = run_helper(
        WPCONFIG_BLOCK,
        {
            "wp_config": scaffold(),
            "defines": classifications["defines"]["portable"],
            "select": wp_config_defines["value"],
            "table_prefix": "wp_",
            "cron": "run",
        },
    )

    # Assert — the writer succeeds and writes only the surviving define, rather than
    # aborting mid-localise on the vanished one.
    defines = block_defines(result["block"])
    assert "define('EMPTY_TRASH_DAYS', 30);" in defines
    assert not any("WP_POST_REVISIONS" in line for line in defines)


def test_selecting_a_name_absent_from_the_records_fails_loud() -> None:
    # Arrange — a selection naming a define the classifier never offered is a
    # corrupt join: the writer must fail loud rather than silently drop it.
    result = subprocess.run(
        [sys.executable, str(WPCONFIG_BLOCK)],
        input=json.dumps(
            {
                "wp_config": scaffold(),
                "defines": [{"name": "WP_DEBUG", "value": True}],
                "select": ["WP_DEBUG", "NOT_OFFERED"],
                "table_prefix": "wp_",
                "cron": "run",
            }
        ).encode(),
        capture_output=True,
    )

    # Assert — a non-zero exit and a branded diagnostic, no half-written config.
    assert result.returncode != 0
    assert b"wpconfig_block:" in result.stderr
