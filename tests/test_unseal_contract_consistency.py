# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Unseal stdin-contract consistency test — issue #43.

``scripts/unseal.py``'s ``unseal`` mode reads its config from a JSON envelope
on stdin. The smoke test (run 2, findings R2-1/R2-8) discovered this contract
was undocumented anywhere: an implementor had to read the source to learn the
required keys, guessed wrong (``output_dir``), and hit a raw ``unseal.py:
'sql_path'`` failure. The settled fix plan makes ``docs/implementation-notes.md``
the primary, authoritative home for the contract (the health-check preflight
runs ``unseal`` in the orchestrator itself, outside any subagent definition),
and requires this consistency test as the anti-drift binding: the documented
contract text must always name every config key the helper actually reads via
``_required(config, ...)`` / ``config.get(...)``.

This suite does not assert the diagnostic wording for a missing key (``missing
required config key: '<key>'``, raised by ``_required`` since #47) — that is
covered by ``tests/test_unseal.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]

UNSEAL_SCRIPT: Path = REPO_ROOT / "scripts" / "unseal.py"
IMPLEMENTATION_NOTES: Path = REPO_ROOT / "docs" / "implementation-notes.md"

# The config keys `run_unseal` actually reads from its stdin envelope
# (`scripts/unseal.py`, `run_unseal`) — the ground truth this test binds the
# documented contract to, so the two can never silently drift apart.
REQUIRED_UNSEAL_KEYS: tuple[str, ...] = (
    "private_key_path",
    "container_path",
    "sql_path",
    "files_root",
)


def test_required_unseal_keys_are_read_by_the_script() -> None:
    """Sanity check on the ground truth itself: every key this suite binds
    the docs to is one `run_unseal` actually reads via `_required(config,
    ...)` (issue #47's replacement for a bare `config[...]`), so the list
    above cannot silently go stale against the source."""

    text = UNSEAL_SCRIPT.read_text(encoding="utf-8")
    for key in REQUIRED_UNSEAL_KEYS:
        assert f'_required(config, "{key}")' in text, (
            f"scripts/unseal.py no longer reads config[{key!r}] via "
            "_required() — REQUIRED_UNSEAL_KEYS is stale against the "
            "source (issue #43, #47)"
        )


@pytest.mark.parametrize("key", REQUIRED_UNSEAL_KEYS)
def test_implementation_notes_names_every_required_unseal_key(key: str) -> None:
    """`docs/implementation-notes.md` — the primary, authoritative home for
    the `unseal` contract, since the health-check preflight runs it in the
    orchestrator itself with no subagent definition to fall back on — names
    every required config key, so the documented shape can never drift from
    what the helper actually reads (issue #43)."""

    text = IMPLEMENTATION_NOTES.read_text(encoding="utf-8")
    assert key in text, (
        f"docs/implementation-notes.md never names the required unseal "
        f"config key '{key}' — an implementor following the docs alone "
        "cannot assemble a correct stdin envelope (issue #43)"
    )


def test_implementation_notes_pins_the_unseal_stdout_shape() -> None:
    """The reciprocal half of the contract — what `unseal` prints on
    success — is pinned alongside the stdin shape, so the docs describe the
    whole round trip, not just the input."""

    text = IMPLEMENTATION_NOTES.read_text(encoding="utf-8")
    for key in ("tables_written", "structure_only_written", "files_written", "bytes_sql"):
        assert key in text, (
            f"docs/implementation-notes.md never names the unseal stdout "
            f"key '{key}' (issue #43)"
        )


def test_implementation_notes_pins_the_keygen_contract() -> None:
    """The `keygen` contract — stdin `{"private_key_path": ...}`, stdout
    `{"public_key": ...}` — is pinned in implementation-notes too, in the
    Health check section where the preflight first generates a key pair
    (issue #43)."""

    text = IMPLEMENTATION_NOTES.read_text(encoding="utf-8")
    assert "private_key_path" in text
    assert "public_key" in text
