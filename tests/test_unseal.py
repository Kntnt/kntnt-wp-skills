# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Behavioural tests for the sealed-container unseal helper CLI.

The helper is the deterministic seam that opens a Kntnt Extractor ``KNTNTEXT``
container (ADR-0017): it generates the run's ephemeral X25519 key pair, unseals
each segment's key, decrypts each segment, and reassembles the container — table
dumps concatenated into one importable ``.sql`` with a connection-safe preamble,
file parts written to disk by their installation-root-relative path.

Every test exercises the real command at its CLI seam, driving both the sealing
(a development/test mode standing in for the plugin's PHP ``Sealed_Writer``) and
the unsealing through ``uv run`` so ``pynacl`` is provisioned from the script's
own inline metadata — the pytest interpreter never needs the dependency. The
sealing mode mirrors the plugin's documented wire format byte for byte, so a
round-trip proves the reader against that format; the live end-to-end smoke is
the ultimate cross-check against the real plugin.
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "unseal.py"

# The connection-safe preamble the helper prepends to the reassembled dump; the
# plugin's per-table DDL carries no global preamble of its own (ADR-0017).
PREAMBLE_MARKER = "SET NAMES utf8mb4"
TRAILER_MARKER = "SET FOREIGN_KEY_CHECKS=@KNTNT_OLD_FOREIGN_KEY_CHECKS"


def _run(mode: str, config: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    """Run the helper's ``mode`` with ``config`` as JSON on stdin, via ``uv``."""

    return subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), mode],
        input=json.dumps(config).encode(),
        capture_output=True,
    )


def _keygen(tmp_path: Path) -> tuple[str, Path]:
    """Generate a run key pair; return the base64 public key and private-key path."""

    private_key_path = tmp_path / "run.key"
    result = _run("keygen", {"private_key_path": str(private_key_path)})
    assert result.returncode == 0, result.stderr.decode()
    public_key = json.loads(result.stdout)["public_key"]
    return public_key, private_key_path


def _seal(container: Path, public_key: str, segments: list[dict[str, str]]) -> None:
    """Seal ``segments`` into ``container`` for ``public_key`` (dev/test mode)."""

    result = _run(
        "seal",
        {
            "container_path": str(container),
            "public_key": public_key,
            "segments": segments,
        },
    )
    assert result.returncode == 0, result.stderr.decode()


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def test_keygen_emits_valid_public_key_and_private_file(tmp_path: Path) -> None:
    """keygen writes a 32-byte private key and prints its base64 public key."""

    public_key, private_key_path = _keygen(tmp_path)

    assert len(base64.b64decode(public_key)) == 32
    assert private_key_path.is_file()
    assert len(private_key_path.read_bytes()) == 32
    # The private key stays on disk, never emitted into stdout/model context.
    assert public_key not in private_key_path.read_text(errors="ignore")


def test_keygen_with_empty_stdin_exits_nonzero_naming_private_key_path() -> None:
    """keygen fed no stdin exits non-zero with a self-documenting diagnostic
    naming the required ``private_key_path`` envelope, not a raw JSON-parse
    error — so a caller who forgets the envelope learns the fix from stderr."""

    result = subprocess.run(
        ["uv", "run", "--script", str(SCRIPT), "keygen"],
        input=b"",
        capture_output=True,
    )

    assert result.returncode != 0
    stderr = result.stderr.decode()
    assert "private_key_path" in stderr
    assert stderr.startswith("unseal.py: keygen requires JSON on stdin:")


def test_round_trip_reassembles_sql_and_files(tmp_path: Path) -> None:
    """A sealed container of tables, structure-only tables, and a multi-part file
    unseals to a preamble-wrapped dump and the file written whole."""

    public_key, private_key_path = _keygen(tmp_path)
    container = tmp_path / "artifact.kntntext"

    # Order mirrors the plugin: full-data tables, then structure-only DDL, then
    # file parts under one relative path (a large file split across segments).
    _seal(
        container,
        public_key,
        [
            {"name": "wp_posts", "data": _b64("-- wp_posts dump\nINSERT INTO wp_posts VALUES (1);\n")},
            {"name": "wp_options", "data": _b64("-- wp_options dump\nINSERT INTO wp_options VALUES (2);\n")},
            {"name": "wp_actionscheduler_logs", "data": _b64("-- DDL only\nCREATE TABLE wp_actionscheduler_logs (id INT);\n")},
            {"name": "wp-content/uploads/2024/big.bin", "data": _b64("PART-ONE-")},
            {"name": "wp-content/uploads/2024/big.bin", "data": _b64("PART-TWO")},
        ],
    )

    sql_path = tmp_path / "out" / "dump.sql"
    files_root = tmp_path / "out" / "files"
    result = _run(
        "unseal",
        {
            "container_path": str(container),
            "private_key_path": str(private_key_path),
            "sql_path": str(sql_path),
            "files_root": str(files_root),
            "tables": ["wp_posts", "wp_options"],
            "structure_only": ["wp_actionscheduler_logs"],
            "files": ["wp-content/uploads/2024/big.bin"],
        },
    )

    assert result.returncode == 0, result.stderr.decode()
    report = json.loads(result.stdout)
    assert report["tables_written"] == 2
    assert report["structure_only_written"] == 1
    assert report["files_written"] == 1

    sql = sql_path.read_text()
    assert PREAMBLE_MARKER in sql
    assert TRAILER_MARKER in sql
    # Tables come before structure-only DDL, and both are present in full.
    assert sql.index("INSERT INTO wp_posts") < sql.index("INSERT INTO wp_options")
    assert sql.index("INSERT INTO wp_options") < sql.index("CREATE TABLE wp_actionscheduler_logs")

    # The multi-part file is concatenated in order and written at its path.
    written = (files_root / "wp-content/uploads/2024/big.bin").read_text()
    assert written == "PART-ONE-PART-TWO"


def test_tampered_ciphertext_fails_closed(tmp_path: Path) -> None:
    """Flipping a byte inside the container fails the authenticated open with a
    non-zero exit and no reassembled dump left behind."""

    public_key, private_key_path = _keygen(tmp_path)
    container = tmp_path / "artifact.kntntext"
    _seal(container, public_key, [{"name": "wp_posts", "data": _b64("INSERT INTO wp_posts VALUES (1);\n")}])

    # Corrupt a byte near the end of the ciphertext region (before the trailer).
    raw = bytearray(container.read_bytes())
    raw[-20] ^= 0xFF
    container.write_bytes(raw)

    sql_path = tmp_path / "dump.sql"
    result = _run(
        "unseal",
        {
            "container_path": str(container),
            "private_key_path": str(private_key_path),
            "sql_path": str(sql_path),
            "files_root": str(tmp_path / "files"),
            "tables": ["wp_posts"],
            "structure_only": [],
            "files": [],
        },
    )

    assert result.returncode != 0
    assert not sql_path.exists()


def test_truncated_container_fails_closed(tmp_path: Path) -> None:
    """A truncated download cannot be reassembled — it fails rather than emit a
    short dump."""

    public_key, private_key_path = _keygen(tmp_path)
    container = tmp_path / "artifact.kntntext"
    _seal(container, public_key, [{"name": "wp_posts", "data": _b64("INSERT INTO wp_posts VALUES (1);\n")}])

    raw = container.read_bytes()
    container.write_bytes(raw[: len(raw) // 2])

    result = _run(
        "unseal",
        {
            "container_path": str(container),
            "private_key_path": str(private_key_path),
            "sql_path": str(tmp_path / "dump.sql"),
            "files_root": str(tmp_path / "files"),
            "tables": ["wp_posts"],
            "structure_only": [],
            "files": [],
        },
    )

    assert result.returncode != 0


def test_path_traversal_segment_rejected(tmp_path: Path) -> None:
    """A file segment whose name escapes the files root is refused, so a hostile
    or buggy container can never write outside the copy."""

    public_key, private_key_path = _keygen(tmp_path)
    container = tmp_path / "artifact.kntntext"
    _seal(container, public_key, [{"name": "../escape.txt", "data": _b64("owned")}])

    result = _run(
        "unseal",
        {
            "container_path": str(container),
            "private_key_path": str(private_key_path),
            "sql_path": str(tmp_path / "dump.sql"),
            "files_root": str(tmp_path / "files"),
            "tables": [],
            "structure_only": [],
            "files": ["../escape.txt"],
        },
    )

    assert result.returncode != 0
    assert not (tmp_path / "escape.txt").exists()


def test_unseal_missing_required_key_reports_clear_diagnostic(tmp_path: Path) -> None:
    """A config missing a required key (e.g. ``sql_path``) exits non-zero with a
    clear diagnostic naming the missing key — not the raw quoted ``KeyError`` —
    and writes no ``.sql`` file."""

    public_key, private_key_path = _keygen(tmp_path)
    container = tmp_path / "artifact.kntntext"
    _seal(container, public_key, [{"name": "wp_posts", "data": _b64("INSERT INTO wp_posts VALUES (1);\n")}])

    sql_path = tmp_path / "dump.sql"
    result = _run(
        "unseal",
        {
            "container_path": str(container),
            "private_key_path": str(private_key_path),
            # "sql_path" deliberately omitted — the required key under test.
            "files_root": str(tmp_path / "files"),
            "tables": ["wp_posts"],
            "structure_only": [],
            "files": [],
        },
    )

    assert result.returncode != 0
    assert "missing required config key: 'sql_path'" in result.stderr.decode()
    assert not sql_path.exists()


def test_seal_malformed_segment_reports_clear_diagnostic(tmp_path: Path) -> None:
    """A seal segment missing a required per-segment key (``name`` / ``data``)
    exits non-zero with the same clear ``missing required config key`` diagnostic
    the config-level checks give — not an uncaught ``KeyError`` traceback — so the
    fail-loud convention is uniform across every dict access in the helper."""

    public_key, _ = _keygen(tmp_path)
    container = tmp_path / "artifact.kntntext"

    result = _run(
        "seal",
        {
            "container_path": str(container),
            "public_key": public_key,
            # The segment omits "name" — the required per-segment key under test.
            "segments": [{"data": _b64("INSERT INTO wp_posts VALUES (1);\n")}],
        },
    )

    assert result.returncode != 0
    stderr = result.stderr.decode()
    assert "missing required config key: 'name'" in stderr
    assert "Traceback" not in stderr
    assert not container.exists()


def test_selection_mismatch_fails_closed(tmp_path: Path) -> None:
    """When the container's sealed index does not match the expected selection,
    the helper refuses rather than silently reassemble the wrong thing."""

    public_key, private_key_path = _keygen(tmp_path)
    container = tmp_path / "artifact.kntntext"
    _seal(container, public_key, [{"name": "wp_posts", "data": _b64("INSERT INTO wp_posts VALUES (1);\n")}])

    result = _run(
        "unseal",
        {
            "container_path": str(container),
            "private_key_path": str(private_key_path),
            "sql_path": str(tmp_path / "dump.sql"),
            "files_root": str(tmp_path / "files"),
            "tables": ["wp_comments"],
            "structure_only": [],
            "files": [],
        },
    )

    assert result.returncode != 0
