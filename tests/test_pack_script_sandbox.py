"""Sandbox execution tests for the generated pack script.

The generated script is run against stub binaries in a throwaway directory —
never a real dump, never a live site. These assert the runtime contract:
success yields DONE, three artifacts, and verifying checksums with no plaintext
in the docroot; an induced failure yields FAILED plus a log tail; and the
self-destruct actually removes both directories.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from pathlib import Path

import pack_script
from conftest import EXPECTED_DOWNLOAD_ENTRIES, Sandbox


def _generate_into(sandbox: Sandbox, **overrides: object) -> None:
    """Generate the pack script for this sandbox and install it."""

    script = pack_script.generate_pack_script(sandbox.config(**overrides))
    sandbox.install_script(script)


def _wait_gone(paths: list[Path], deadline_seconds: float) -> bool:
    """Poll until none of the paths exist, or the deadline passes."""

    end = time.monotonic() + deadline_seconds
    while time.monotonic() < end:
        if not any(path.exists() for path in paths):
            return True
        time.sleep(0.1)
    return not any(path.exists() for path in paths)


def test_success_path_yields_done_and_three_artifacts(sandbox: Sandbox) -> None:
    """A clean run publishes exactly the three artifacts plus DONE."""

    _generate_into(sandbox)

    code = sandbox.run()

    assert code == 0
    assert (sandbox.download_dir / "DONE").is_file()
    assert sandbox.download_entries() == EXPECTED_DOWNLOAD_ENTRIES


def test_success_path_with_no_exclude_list_yields_done_and_three_artifacts(
    sandbox: Sandbox,
) -> None:
    """The explicit-include (pull delta) path — an empty exclude list, so the
    generated script carries no exclusion heredoc or exclude-file reference —
    still runs to a clean DONE with all three artifacts."""

    _generate_into(sandbox, excludePaths=[])

    code = sandbox.run()

    assert code == 0
    assert (sandbox.download_dir / "DONE").is_file()
    assert sandbox.download_entries() == EXPECTED_DOWNLOAD_ENTRIES


def test_success_path_checksums_verify(sandbox: Sandbox) -> None:
    """The published SHA256 file lists the artifacts under their final names and
    the recorded digests match the bytes on disk."""

    _generate_into(sandbox)

    sandbox.run()

    lines = (sandbox.download_dir / "SHA256").read_text(encoding="utf-8").splitlines()
    recorded = {}
    for line in lines:
        if line.strip():
            digest, name = line.split("  ", 1)
            recorded[name] = digest
    assert set(recorded) == {"db.enc", "files.enc"}
    for name, digest in recorded.items():
        actual = hashlib.sha256((sandbox.download_dir / name).read_bytes()).hexdigest()
        assert actual == digest


def test_success_path_leaves_no_plaintext_in_the_docroot(sandbox: Sandbox) -> None:
    """The security-critical assertion: no plaintext ever lands in the docroot;
    only encrypted artifacts are published there."""

    _generate_into(sandbox)

    sandbox.run()

    assert sandbox.plaintext_leaks() == []


def test_selfdestruct_arming_is_observable_without_waiting(sandbox: Sandbox) -> None:
    """The self-destruct is armed with the configured delay — observable via the
    recorded sleep request, without waiting the delay out."""

    _generate_into(sandbox, selfDestructDelaySeconds=3600)

    sandbox.run()

    assert "3600" in sandbox.sleep_sentinel.read_text(encoding="utf-8").split()


def test_induced_failure_yields_failed_marker_with_log_tail(sandbox: Sandbox) -> None:
    """A mid-script failure writes FAILED, carrying the log tail, into the
    download dir — and never DONE or any artifact."""

    _generate_into(sandbox)

    code = sandbox.run(fail_tool="mysqldump")

    assert code != 0
    failed = sandbox.download_dir / "FAILED"
    assert failed.is_file()
    content = failed.read_text(encoding="utf-8")
    assert content.startswith("FAILED")
    assert "induced failure" in content
    assert not (sandbox.download_dir / "DONE").exists()
    assert "db.enc" not in sandbox.download_entries()
    assert "files.enc" not in sandbox.download_entries()


def test_induced_failure_leaves_no_plaintext_in_the_docroot(sandbox: Sandbox) -> None:
    """Even an aborted run must not strand plaintext in the docroot."""

    _generate_into(sandbox)

    sandbox.run(fail_tool="mysqldump")

    assert sandbox.plaintext_leaks() == []


def test_selfdestruct_removes_both_directories(sandbox: Sandbox) -> None:
    """When the timer fires it removes both the working dir and the download dir,
    so the passphrase and artifacts vanish even if the client never returns."""

    _generate_into(sandbox, selfDestructDelaySeconds=3600)

    sandbox.run(sleep_seconds="1")

    removed = _wait_gone([sandbox.working_dir, sandbox.download_dir], 10.0)
    assert removed
    assert not sandbox.working_dir.exists()
    assert not sandbox.download_dir.exists()
    assert "3600" in sandbox.sleep_sentinel.read_text(encoding="utf-8").split()


def test_cli_generates_a_runnable_script(sandbox: Sandbox) -> None:
    """The script produced through the CLI (JSON stdin) runs to a clean DONE,
    proving the CLI output is the same runnable artifact."""

    import json

    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    payload = json.dumps(sandbox.config())
    generated = subprocess.run(
        [sys.executable, str(scripts_dir / "pack_script.py")],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )
    sandbox.install_script(generated.stdout)

    code = sandbox.run()

    assert code == 0
    assert (sandbox.download_dir / "DONE").is_file()
