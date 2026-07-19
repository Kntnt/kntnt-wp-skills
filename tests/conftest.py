"""Shared test fixtures for the pack-pipeline helpers.

The single automated seam for this plugin is the deterministic helper CLI, so
these fixtures never reach a live site, a real DDEV instance, or the Novamira
MCP. The sandbox executes the *generated* pack script against stub binaries that
stand in for the database, encryption, archive, and checksum tools — proving the
script's runtime contract without ever running a real dump. Stubs tag the
plaintext they emit with a sentinel so any leak into the simulated docroot is
detectable, and encryption strips it; a recursive scan for the sentinel is the
security-critical no-plaintext assertion.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# Make the standalone helper scripts importable without packaging them.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

# Distinctive marker the plaintext-producing stubs emit; the encryption stub
# never reproduces it, so its presence anywhere under the docroot is a leak.
PLAINTEXT_SENTINEL = "KNTNT_PLAINTEXT_SENTINEL_DO_NOT_LEAK"

# The three artifacts a successful pack publishes, plus the success marker.
EXPECTED_DOWNLOAD_ENTRIES = {"db.enc", "files.enc", "SHA256", "DONE"}


# Stub binaries placed ahead of the real tools on PATH. Each honours
# ``KNTNT_STUB_FAIL=<name>`` to induce a mid-script failure on demand.
_STUB_MYSQLDUMP = f"""#!/usr/bin/env bash
if [ "${{KNTNT_STUB_FAIL:-}}" = "mysqldump" ]; then
    echo "stub mysqldump: induced failure" >&2
    exit 1
fi
printf '{PLAINTEXT_SENTINEL}\\n-- stub mysqldump output\\n'
"""

_STUB_GZIP = """#!/usr/bin/env bash
if [ "${KNTNT_STUB_FAIL:-}" = "gzip" ]; then
    echo "stub gzip: induced failure" >&2
    exit 1
fi
exec cat
"""

_STUB_TAR = f"""#!/usr/bin/env bash
if [ "${{KNTNT_STUB_FAIL:-}}" = "tar" ]; then
    echo "stub tar: induced failure" >&2
    exit 1
fi
printf '{PLAINTEXT_SENTINEL}\\n-- stub tar archive\\n'
"""

# Consumes stdin (so upstream never SIGPIPEs) and writes only an encrypted
# marker to ``-out`` — deliberately never echoing the plaintext sentinel.
_STUB_OPENSSL = """#!/usr/bin/env python3
import os
import sys

if os.environ.get("KNTNT_STUB_FAIL") == "openssl":
    sys.stderr.write("stub openssl: induced failure\\n")
    sys.exit(1)

args = sys.argv[1:]
out = None
for i, arg in enumerate(args):
    if arg == "-out":
        out = args[i + 1]

data = sys.stdin.buffer.read()
payload = b"KNTNT_ENCRYPTED\\n" + f"bytes={len(data)}\\n".encode()
if out is None:
    sys.stdout.buffer.write(payload)
else:
    with open(out, "wb") as handle:
        handle.write(payload)
"""

# Real SHA-256 semantics via hashlib, so "checksums verify" is a genuine check
# and the harness stays hermetic on any host.
_STUB_SHA256SUM = """#!/usr/bin/env python3
import hashlib
import os
import sys


def digest(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


if os.environ.get("KNTNT_STUB_FAIL") == "sha256sum":
    sys.stderr.write("stub sha256sum: induced failure\\n")
    sys.exit(1)

args = sys.argv[1:]
if args and args[0] == "-c":
    ok = True
    with open(args[1]) as handle:
        for line in handle:
            line = line.rstrip("\\n")
            if not line:
                continue
            want, name = line.split("  ", 1)
            try:
                got = digest(name)
            except FileNotFoundError:
                ok = False
                print(f"{name}: FAILED open or read")
                continue
            if got == want:
                print(f"{name}: OK")
            else:
                ok = False
                print(f"{name}: FAILED")
    sys.exit(0 if ok else 1)

for name in args:
    print(f"{digest(name)}  {name}")
"""

# Records the delay it was asked to wait (so self-destruct arming is observable
# without waiting the delay out) then hands off to the real sleep, shortened in
# tests via KNTNT_SLEEP_SECONDS. Never recurses into this stub.
_STUB_SLEEP = """#!/usr/bin/env bash
if [ -n "${KNTNT_SLEEP_SENTINEL:-}" ]; then
    echo "$1" >> "$KNTNT_SLEEP_SENTINEL"
fi
real="${KNTNT_SLEEP_SECONDS:-$1}"
for cand in /bin/sleep /usr/bin/sleep; do
    if [ -x "$cand" ]; then
        exec "$cand" "$real"
    fi
done
exit 0
"""

_STUBS: dict[str, str] = {
    "mysqldump": _STUB_MYSQLDUMP,
    "gzip": _STUB_GZIP,
    "tar": _STUB_TAR,
    "openssl": _STUB_OPENSSL,
    "sha256sum": _STUB_SHA256SUM,
    "sleep": _STUB_SLEEP,
}


@dataclass
class Sandbox:
    """A throwaway filesystem laid out like production for one pack run.

    ``docroot`` is the simulated web root (ABSPATH); ``working_dir`` sits outside
    it (never web-readable); ``download_dir`` is the random-named docroot dir the
    finished artifacts are published into.
    """

    root: Path
    docroot: Path
    working_dir: Path
    download_dir: Path
    bin_dir: Path
    sleep_sentinel: Path
    _pgids: list[int] = field(default_factory=list)

    @property
    def source_root(self) -> Path:
        """The tree tar runs relative to — the docroot in this layout."""

        return self.docroot

    @property
    def pack_script(self) -> Path:
        """Where the generated ``pack.sh`` is written."""

        return self.working_dir / "pack.sh"

    @property
    def log(self) -> Path:
        """The pack log, kept in the working dir, never in the docroot."""

        return self.working_dir / "pack.log"

    def config(self, **overrides: object) -> dict[str, object]:
        """Build a resolved-inputs mapping wired to this sandbox's paths."""

        base: dict[str, object] = {
            "workingDir": str(self.working_dir),
            "downloadDir": str(self.download_dir),
            "database": "prod_db",
            "sourceRoot": str(self.source_root),
            "archivePaths": ["wp-content"],
            "excludePaths": [
                "wp-content/object-cache.php",
                "wp-content/uploads/2023/07/pic-150x150.jpg",
            ],
            "contentTables": ["wp_posts", "wp_options", "wp_users"],
            "emptyTables": ["wp_independent_analytics_pages"],
            "consistentSnapshot": True,
            "selfDestructDelaySeconds": 3600,
            "logTailLines": 40,
        }
        base.update(overrides)
        return base

    def install_script(self, script: str) -> None:
        """Write the generated pack script and seed the working-dir secrets the
        orchestration would place there before launch."""

        self.pack_script.write_text(script, encoding="utf-8")
        pass_key = self.working_dir / "pass.key"
        pass_key.write_text("00" * 32, encoding="utf-8")
        pass_key.chmod(0o600)
        mycnf = self.working_dir / ".my.cnf"
        mycnf.write_text(
            "[client]\nuser=stub\npassword=stub\nhost=127.0.0.1\n", encoding="utf-8"
        )
        mycnf.chmod(0o600)

    def run(
        self,
        *,
        fail_tool: str | None = None,
        sleep_seconds: str = "60",
        timeout: float = 30.0,
    ) -> int:
        """Run the generated pack script exactly as the launcher would — under
        ``bash`` with stdout and stderr appended to the log — and return its exit
        code. The self-destruct subshell it spawns is reaped at teardown.
        """

        env = dict(os.environ)
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env['PATH']}"
        env["KNTNT_SLEEP_SENTINEL"] = str(self.sleep_sentinel)
        env["KNTNT_SLEEP_SECONDS"] = sleep_seconds
        if fail_tool is not None:
            env["KNTNT_STUB_FAIL"] = fail_tool

        with self.log.open("ab") as log:
            process = subprocess.Popen(
                ["bash", str(self.pack_script)],
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=str(self.root),
                env=env,
                start_new_session=True,
            )
        self._pgids.append(process.pid)
        return process.wait(timeout=timeout)

    def download_entries(self) -> set[str]:
        """Names currently present in the download dir."""

        if not self.download_dir.is_dir():
            return set()
        return {entry.name for entry in self.download_dir.iterdir()}

    def plaintext_leaks(self) -> list[Path]:
        """Every file under the docroot whose bytes carry the plaintext
        sentinel — the security-critical no-plaintext check."""

        needle = PLAINTEXT_SENTINEL.encode()
        leaks: list[Path] = []
        for path in self.docroot.rglob("*"):
            if path.is_file() and needle in path.read_bytes():
                leaks.append(path)
        return leaks

    def _terminate(self) -> None:
        """Kill each run's process group, reaping any lingering self-destruct
        subshell so the machine is left state-neutral."""

        for pgid in self._pgids:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    """Provision a fresh sandbox: docroot with ordinary content, an
    outside-docroot working dir, a docroot download dir, and stub binaries."""

    docroot = tmp_path / "docroot"
    uploads = docroot / "wp-content" / "uploads" / "2023" / "07"
    plugins = docroot / "wp-content" / "plugins" / "sample"
    uploads.mkdir(parents=True)
    plugins.mkdir(parents=True)
    (uploads / "pic.jpg").write_bytes(b"ordinary jpeg bytes\n")
    (plugins / "sample.php").write_text("<?php echo 'ordinary';\n", encoding="utf-8")
    (docroot / "wp-content" / "object-cache.php").write_text(
        "<?php // drop-in\n", encoding="utf-8"
    )

    working_dir = tmp_path / "outside" / "kntnt-wp-skills-work"
    working_dir.mkdir(parents=True)

    download_dir = docroot / "kntnt-wp-skills-dl"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in _STUBS.items():
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)

    box = Sandbox(
        root=tmp_path,
        docroot=docroot,
        working_dir=working_dir,
        download_dir=download_dir,
        bin_dir=bin_dir,
        sleep_sentinel=tmp_path / "sleep.calls",
    )
    yield box
    box._terminate()
