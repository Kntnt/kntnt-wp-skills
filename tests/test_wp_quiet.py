"""Tests for the quiet WP-CLI step runner (issue #52).

Thumbnail regeneration and a search-index rebuild are the two noisiest local
steps of a clone or a pull: WP-CLI emits one progress line per image and a
deprecation notice per plugin load, tens of thousands of lines that carry no
decision the operator or the agent has to make. That noise used to be
swallowed by a Claude Code subagent's separate context, which meant the two
steps were only quiet in one harness; this helper makes them quiet in every
harness by construction — the whole output goes to a log file under the run's
scratchpad, and one compact JSON summary comes back.

The shelling-out edge is injected exactly as ``smoke_test.py``'s is, so the
suite never spawns a real DDEV project; one end-to-end test drives the real
subprocess seam against a fake ``wp`` so the argv assembly is covered too.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import wp_quiet

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "clone" / "scripts"


class FakeCompleted:
    """A duck-typed stand-in for ``subprocess.CompletedProcess`` — only the
    three attributes the helper reads."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def fake_runner(responses: dict[tuple[str, ...], FakeCompleted]):
    """Build a command runner keyed by the exact argv tuple, recording the
    calls — an argv the scenario never wired is a test bug, never a silent
    pass."""

    calls: list[tuple[str, ...]] = []

    def _run(args):
        key = tuple(args)
        calls.append(key)
        if key not in responses:
            raise AssertionError(f"unexpected command: {list(args)}")
        return responses[key]

    _run.calls = calls  # type: ignore[attr-defined]
    return _run


REGENERATE_SPAM = "\n".join(
    [
        "Found 3 images to regenerate.",
        "1/3 Regenerated thumbnails for 'alpha' (ID 1).",
        "2/3 Regenerated thumbnails for 'beta' (ID 2).",
        "3/3 Regenerated thumbnails for 'gamma' (ID 3).",
        "Success: Regenerated 3 of 3 images.",
    ]
)


# --- Thumbnail regeneration -------------------------------------------------


def test_regenerate_writes_the_whole_output_to_the_log(tmp_path: Path) -> None:
    """Nothing is discarded: the log holds every line the command produced, so
    a diagnosis after the fact never needs the step re-run."""

    log = tmp_path / "regenerate.log"
    run = fake_runner(
        {("ddev", "wp", "media", "regenerate", "--yes"): FakeCompleted(stdout=REGENERATE_SPAM)}
    )

    wp_quiet.regenerate(log_path=log, ids=None, run_command=run)

    written = log.read_text(encoding="utf-8")
    assert "Regenerated thumbnails for 'beta'" in written
    assert "Success: Regenerated 3 of 3 images." in written


def test_regenerate_summary_carries_the_count_not_the_spam(tmp_path: Path) -> None:
    """What comes back is decision-relevant only: the count, the exit code, the
    log's path and size — never the per-image lines."""

    log = tmp_path / "regenerate.log"
    run = fake_runner(
        {("ddev", "wp", "media", "regenerate", "--yes"): FakeCompleted(stdout=REGENERATE_SPAM)}
    )

    summary = wp_quiet.regenerate(log_path=log, ids=None, run_command=run)

    assert summary["step"] == "regenerate"
    assert summary["exit_code"] == 0
    assert summary["regenerated"] == 3
    assert summary["log_path"] == str(log)
    # Six, not five: the log heads each step with the command that produced it,
    # so a log holding two steps still says which output belongs to which.
    assert summary["log_lines"] == 6
    assert summary["anomalies"] == []
    assert "Regenerated thumbnails for" not in json.dumps(summary)


def test_regenerate_scopes_to_the_given_attachment_ids(tmp_path: Path) -> None:
    """The pull path regenerates a metadata-driven delta, so the ids ride into
    the command rather than the whole library being rebuilt."""

    log = tmp_path / "regenerate.log"
    run = fake_runner(
        {
            ("ddev", "wp", "media", "regenerate", "7", "9", "--yes"): FakeCompleted(
                stdout="Success: Regenerated 2 of 2 images."
            )
        }
    )

    summary = wp_quiet.regenerate(log_path=log, ids=[7, 9], run_command=run)

    assert run.calls == [("ddev", "wp", "media", "regenerate", "7", "9", "--yes")]
    assert summary["regenerated"] == 2


def test_regenerate_surfaces_genuine_errors_as_anomalies(tmp_path: Path) -> None:
    """Swallowing the routine noise must never swallow a real failure: an
    ``Error:`` line comes back in the summary, not only in the log."""

    log = tmp_path / "regenerate.log"
    noisy = "\n".join(
        [
            "1/2 Regenerated thumbnails for 'alpha' (ID 1).",
            "Warning: No metadata for attachment 2.",
            "Error: Could not regenerate attachment 2.",
            "Success: Regenerated 1 of 2 images.",
        ]
    )
    run = fake_runner(
        {
            ("ddev", "wp", "media", "regenerate", "--yes"): FakeCompleted(
                returncode=1, stdout=noisy
            )
        }
    )

    summary = wp_quiet.regenerate(log_path=log, ids=None, run_command=run)

    assert summary["exit_code"] == 1
    assert summary["anomalies"] == ["Error: Could not regenerate attachment 2."]
    # The cosmetic warning is routine noise, and stays in the log only.
    assert "Warning: No metadata" not in json.dumps(summary)


def test_regenerate_reports_an_unparseable_count_as_unknown(tmp_path: Path) -> None:
    """A WP-CLI whose success line changes shape must not make the helper
    invent a number — an absent count is reported as absent."""

    log = tmp_path / "regenerate.log"
    run = fake_runner(
        {("ddev", "wp", "media", "regenerate", "--yes"): FakeCompleted(stdout="all done\n")}
    )

    summary = wp_quiet.regenerate(log_path=log, ids=None, run_command=run)

    assert summary["regenerated"] is None


# --- Search-index rebuild ---------------------------------------------------


def test_reindex_probes_before_running_and_reports_rebuilt(tmp_path: Path) -> None:
    """The documented probe-then-run pair (ADR-0015), with the family's own
    rebuild command and the ``rebuilt`` outcome."""

    log = tmp_path / "reindex.log"
    run = fake_runner(
        {
            ("ddev", "wp", "cli", "has-command", "relevanssi index"): FakeCompleted(),
            ("ddev", "wp", "relevanssi", "index"): FakeCompleted(
                stdout="Indexing complete. 412 posts indexed."
            ),
        }
    )

    summary = wp_quiet.reindex(log_path=log, plugin="relevanssi", run_command=run)

    assert run.calls == [
        ("ddev", "wp", "cli", "has-command", "relevanssi index"),
        ("ddev", "wp", "relevanssi", "index"),
    ]
    assert summary["outcome"] == "rebuilt"
    assert summary["exit_code"] == 0
    assert "Indexing complete" in log.read_text(encoding="utf-8")


def test_reindex_searchwp_uses_its_own_rebuild_command(tmp_path: Path) -> None:
    """The two families' rebuild commands differ; the helper owns the mapping so
    no caller has to remember it."""

    log = tmp_path / "reindex.log"
    run = fake_runner(
        {
            ("ddev", "wp", "cli", "has-command", "searchwp index"): FakeCompleted(),
            ("ddev", "wp", "searchwp", "index", "--rebuild"): FakeCompleted(),
        }
    )

    summary = wp_quiet.reindex(log_path=log, plugin="searchwp", run_command=run)

    assert ("ddev", "wp", "searchwp", "index", "--rebuild") in run.calls
    assert summary["outcome"] == "rebuilt"


def test_reindex_probe_failure_is_the_report_only_fallback(tmp_path: Path) -> None:
    """Free Relevanssi ships no WP-CLI command at all: the probe fails, nothing
    is run, and the outcome says so — never an error, never a ``wp eval``
    workaround (ADR-0015)."""

    log = tmp_path / "reindex.log"
    run = fake_runner(
        {
            ("ddev", "wp", "cli", "has-command", "relevanssi index"): FakeCompleted(
                returncode=1, stderr="Error: 'relevanssi index' is not a registered command."
            )
        }
    )

    summary = wp_quiet.reindex(log_path=log, plugin="relevanssi", run_command=run)

    assert run.calls == [("ddev", "wp", "cli", "has-command", "relevanssi index")]
    assert summary["outcome"] == "cli-unavailable"
    assert summary["exit_code"] is None


def test_reindex_without_a_plugin_runs_nothing(tmp_path: Path) -> None:
    """No active search-index plugin is a clean no-op: no probe, no command, and
    the ``not-present`` outcome the report reads."""

    log = tmp_path / "reindex.log"
    run = fake_runner({})

    summary = wp_quiet.reindex(log_path=log, plugin=None, run_command=run)

    assert run.calls == []
    assert summary["outcome"] == "not-present"
    assert summary["exit_code"] is None


# --- The CLI ---------------------------------------------------------------


def _fake_wp(tmp_path: Path, body: str) -> str:
    """Write a stand-in for ``ddev wp`` and return it as a runner prefix."""

    script = tmp_path / "fake_wp.py"
    script.write_text(body, encoding="utf-8")
    return f"{sys.executable} {script}"


def test_cli_regenerate_prints_only_the_summary(tmp_path: Path) -> None:
    """End to end through the real subprocess seam: stdout is one compact JSON
    object, and the thousands of lines the command produced are in the log."""

    runner = _fake_wp(
        tmp_path,
        "import sys\n"
        "for i in range(1, 2001):\n"
        "    print(f\"{i}/2000 Regenerated thumbnails for 'x' (ID {i}).\")\n"
        'print("Success: Regenerated 2000 of 2000 images.")\n',
    )
    log = tmp_path / "logs" / "regenerate.log"

    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS_DIR / "wp_quiet.py"),
            "regenerate",
            "--log",
            str(log),
            "--runner",
            runner,
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["regenerated"] == 2000
    assert summary["log_lines"] == 2002
    assert len(result.stdout) < 500
    assert log.read_text(encoding="utf-8").count("Regenerated thumbnails") == 2000


def test_cli_exits_nonzero_when_the_command_failed(tmp_path: Path) -> None:
    """A swallowed exit code would be a silent failure: the helper's own exit
    status follows the command's."""

    runner = _fake_wp(
        tmp_path,
        'import sys\nprint("Error: no such attachment")\nsys.exit(1)\n',
    )
    log = tmp_path / "regenerate.log"

    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS_DIR / "wp_quiet.py"),
            "regenerate",
            "--log",
            str(log),
            "--runner",
            runner,
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    summary = json.loads(result.stdout)
    assert summary["exit_code"] == 1
    assert summary["anomalies"] == ["Error: no such attachment"]


def test_cli_runs_the_step_in_the_given_directory(tmp_path: Path) -> None:
    """``ddev wp`` only works inside the project directory, so the caller can
    name it rather than having to change directory around the invocation."""

    site = tmp_path / "site"
    site.mkdir()
    runner = _fake_wp(
        tmp_path,
        'import os\nprint(f"cwd={os.getcwd()}")\nprint("Success: Regenerated 0 of 0 images.")\n',
    )
    log = tmp_path / "regenerate.log"

    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS_DIR / "wp_quiet.py"),
            "regenerate",
            "--log",
            str(log),
            "--runner",
            runner,
            "--dir",
            str(site),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert f"cwd={site.resolve()}" in log.read_text(encoding="utf-8")


def test_cli_rejects_an_unknown_search_index_family(tmp_path: Path) -> None:
    """The two recognised families are the whole contract; anything else is a
    caller mistake, refused loudly rather than probed for."""

    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS_DIR / "wp_quiet.py"),
            "reindex",
            "--log",
            str(tmp_path / "reindex.log"),
            "--plugin",
            "elasticpress",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "elasticpress" in result.stderr
