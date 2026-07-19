"""Generation-level tests for the pack-script helper.

These bind to the script's *content*: every settled literal from the
implementation notes must be baked in, and generation must be deterministic
(resolved inputs in, one script out).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pack_script

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _config(**overrides: object) -> dict[str, object]:
    """A minimal, valid resolved-inputs mapping for generation tests."""

    base: dict[str, object] = {
        "workingDir": "/tmp/outside/kntnt-wp-skills-work",
        "downloadDir": "/var/www/html/kntnt-wp-skills-dl",
        "database": "prod_db",
        "sourceRoot": "/var/www/html",
        "archivePaths": ["wp-content"],
        "excludePaths": [
            "wp-content/object-cache.php",
            "wp-content/uploads/2023/07/pic-150x150.jpg",
        ],
        "contentTables": ["wp_posts", "wp_options"],
        "emptyTables": ["wp_independent_analytics_pages"],
        "consistentSnapshot": True,
        "selfDestructDelaySeconds": 3600,
        "logTailLines": 40,
    }
    base.update(overrides)
    return base


def test_generation_is_deterministic() -> None:
    """The same resolved inputs always yield a byte-identical script."""

    config = _config()

    first = pack_script.generate_pack_script(config)
    second = pack_script.generate_pack_script(config)

    assert first == second


def test_script_runs_under_strict_shell_mode() -> None:
    """Strict error handling with an ERR trap is the robustness contract."""

    script = pack_script.generate_pack_script(_config())

    assert "set -euo pipefail" in script
    assert "trap fail ERR" in script


def test_exclusion_is_anchored_with_wildcards_disabled() -> None:
    """Archive exclusions must be an anchored exclude file with wildcards off —
    command-line or basename patterns overflow the arg limit and mis-match."""

    script = pack_script.generate_pack_script(_config())

    assert "--exclude-from=" in script
    assert "--anchored" in script
    assert "--no-wildcards" in script
    assert "--warning=no-file-changed" in script
    assert "wp-content/object-cache.php" in script
    assert "wp-content/uploads/2023/07/pic-150x150.jpg" in script


def test_two_pass_consistent_dump() -> None:
    """A live-site-safe first pass with full data, then a schema-only pass for
    the empty-classified tables."""

    script = pack_script.generate_pack_script(_config())

    assert "--single-transaction" in script
    assert "--quick" in script
    assert "--skip-lock-tables" in script
    assert "--no-data" in script
    assert "wp_posts" in script
    assert "wp_independent_analytics_pages" in script


def test_myisam_fallback_drops_single_transaction_with_a_caveat() -> None:
    """A non-InnoDB content table falls back off --single-transaction and logs a
    consistency caveat, keeping the other live-safe flags."""

    script = pack_script.generate_pack_script(_config(consistentSnapshot=False))

    assert "--single-transaction" not in script
    assert "--quick" in script
    assert "--skip-lock-tables" in script
    assert "caveat" in script.lower()


def test_artifacts_are_enc_named_from_creation() -> None:
    """Both artifacts are written straight to their final .enc names — never
    created under another name and renamed."""

    script = pack_script.generate_pack_script(_config())

    assert "-out" in script
    assert "db.enc" in script
    assert "files.enc" in script
    # No rename step turning a non-.enc artifact into an .enc one.
    assert "mv db.tar" not in script
    assert "mv db.sql" not in script


def test_secrets_never_reach_the_command_line() -> None:
    """The DB password travels via a defaults file and the passphrase via a file
    reference — neither ever appears as a command-line argument."""

    script = pack_script.generate_pack_script(_config())

    assert "--defaults-extra-file=" in script
    assert "-pass file:" in script
    assert "-pass pass:" not in script


def test_checksums_are_over_the_final_names() -> None:
    """Checksums are computed over the exact published names, so verification
    after download stays honest."""

    script = pack_script.generate_pack_script(_config())

    assert "sha256sum db.enc files.enc > SHA256" in script


def test_done_marker_and_selfdestruct_are_armed() -> None:
    """Success writes DONE; a self-destruct removing both dirs is armed with the
    configured delay baked in."""

    script = pack_script.generate_pack_script(_config(selfDestructDelaySeconds=1234))

    assert "DONE" in script
    assert "rm -rf" in script
    assert 'sleep "$SELF_DESTRUCT_DELAY"' in script
    assert "1234" in script


def test_failed_marker_carries_the_log_tail() -> None:
    """On failure a FAILED marker plus a bounded log tail lands in the download
    dir, the only place the client can read it."""

    script = pack_script.generate_pack_script(_config(logTailLines=25))

    assert "FAILED" in script
    assert "tail -n" in script
    assert "25" in script


def test_cli_reads_json_stdin_and_writes_the_script() -> None:
    """The helper is a CLI: resolved-inputs JSON on stdin, pack script on
    stdout."""

    payload = json.dumps(_config())

    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "pack_script.py")],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.startswith("#!")
    assert "set -euo pipefail" in result.stdout
    assert "sha256sum db.enc files.enc > SHA256" in result.stdout
