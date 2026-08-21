# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run one noisy local WP-CLI step, log all of it, report a compact summary.

Thumbnail regeneration and a search-index rebuild are the two loudest steps of
a clone or a pull — one progress line per image, a deprecation notice per
plugin load, tens of thousands of lines carrying no decision anybody has to
make. That noise used to be absorbed by a Claude Code subagent's separate
context, which made the steps quiet in exactly one harness. This helper makes
them quiet in every harness instead: the command's whole output goes to a log
file under the run's scratchpad, and what comes back on stdout is the count,
the exit code, the log's path, and any line that looks like a genuine failure.

The two steps live here together because they are one shape — run a WP-CLI
command through DDEV, keep everything, report almost nothing — and because the
reindex probe-then-run pair ([ADR-0015](https://github.com/Kntnt/kntnt-wp-skills/blob/main/docs/adr/0015-search-index-excluded-and-rebuilt-locally.md))
is a decision an agent should never have to re-derive from prose. The command
runner is injectable, so the suite exercises the argv assembly and the
summarising without a DDEV project anywhere near it.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

__all__ = ["main", "regenerate", "reindex"]

# The default way this engine reaches WP-CLI: inside the local DDEV project.
DEFAULT_RUNNER: str = "ddev wp"

# The two recognised search-index families, each mapped to the command that
# proves its WP-CLI support is installed and the command that rebuilds it.
# Free Relevanssi ships no WP-CLI command at all (Premium-only, from 1.15.1),
# which is why the probe exists and why its failure is a documented outcome
# rather than an error.
SEARCH_INDEX_FAMILIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "relevanssi": ("relevanssi index", ("relevanssi", "index")),
    "searchwp": ("searchwp index", ("searchwp", "index", "--rebuild")),
}

# WP-CLI's own success line for a regeneration run. The count is reported as
# absent rather than guessed when this does not match.
_REGENERATED_RE = re.compile(r"Regenerated (\d+) of (\d+) images", re.IGNORECASE)

# What survives the swallowing. WP-CLI's `Warning:` lines are the routine noise
# of a regeneration pass (an attachment without metadata, a missing source
# file); an `Error:` line, or a PHP fatal, is the operator's business.
_ANOMALY_RE = re.compile(r"^\s*Error:|Fatal error|PHP Fatal", re.MULTILINE)

# An anomaly list is a summary, not a second log: past this many lines the log
# file is the place to read.
_MAX_ANOMALIES = 20


class Completed(Protocol):
    """The three attributes this helper reads off a finished command — the
    subset of ``subprocess.CompletedProcess`` the injected fake also has."""

    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str]], Completed]


def _real_runner(cwd: Path | None) -> CommandRunner:
    """Build the real command runner: capture both streams, never raise on a
    non-zero exit — the exit code is a result this helper reports, not an
    exception it hides."""

    def run(args: Sequence[str]) -> Completed:
        return subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            cwd=cwd,
            check=False,  # a non-zero exit is a result this helper reports, not an error it raises
        )

    return run


def _append_log(log_path: Path, args: Sequence[str], result: Completed) -> None:
    """Append a command's whole output to the log, headed by the command itself
    so a log holding two steps still says which produced what."""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"$ {shlex.join(args)}\n")
        log.write(result.stdout)
        if result.stdout and not result.stdout.endswith("\n"):
            log.write("\n")
        log.write(result.stderr)
        if result.stderr and not result.stderr.endswith("\n"):
            log.write("\n")


def _log_lines(log_path: Path) -> int:
    """Count the log's lines — the one number that says how much was swallowed."""

    if not log_path.is_file():
        return 0
    return len(log_path.read_text(encoding="utf-8").splitlines())


def _anomalies(result: Completed) -> list[str]:
    """Pick the genuine failures out of a command's output.

    Everything else is the routine progress and deprecation noise this helper
    exists to absorb; a swallowed ``Error:`` line would make it a liability
    rather than a convenience, so those come back.
    """

    text = f"{result.stdout}\n{result.stderr}"
    found = [
        line.strip()
        for line in text.splitlines()
        if _ANOMALY_RE.match(line) or _ANOMALY_RE.search(line)
    ]
    return found[:_MAX_ANOMALIES]


def regenerate(
    *,
    log_path: Path,
    ids: Sequence[int] | None,
    run_command: CommandRunner | None = None,
) -> dict[str, Any]:
    """Regenerate thumbnails and return the compact summary.

    Args:
        log_path: Where the command's whole output is kept.
        ids: The attachment ids to regenerate — the metadata-driven delta a
            pull computes. ``None`` regenerates the whole library, which is
            what a clone does.
        run_command: Injected command runner; the real one by default.
    """

    run = run_command if run_command is not None else _real_runner(None)
    args = [
        *shlex.split(DEFAULT_RUNNER),
        "media",
        "regenerate",
        *(str(attachment_id) for attachment_id in ids or ()),
        "--yes",
    ]

    result = run(args)
    _append_log(log_path, args, result)

    # WP-CLI's own tally is the count; a shape this does not recognise is
    # reported as unknown rather than inferred from the progress lines.
    match = _REGENERATED_RE.search(f"{result.stdout}\n{result.stderr}")

    return {
        "step": "regenerate",
        "exit_code": result.returncode,
        "regenerated": int(match.group(1)) if match else None,
        "attempted": int(match.group(2)) if match else None,
        "log_path": str(log_path),
        "log_lines": _log_lines(log_path),
        "anomalies": _anomalies(result),
    }


def reindex(
    *,
    log_path: Path,
    plugin: str | None,
    run_command: CommandRunner | None = None,
) -> dict[str, Any]:
    """Rebuild the local search index and return the compact summary.

    The outcome is one of three, and only one of them runs anything:
    ``rebuilt`` (the probe passed and the family's rebuild command ran),
    ``cli-unavailable`` (the plugin is active but ships no WP-CLI command — the
    documented report-only fallback, never a ``wp eval`` workaround), and
    ``not-present`` (no active search-index plugin, so nothing to probe).

    Args:
        log_path: Where the commands' whole output is kept.
        plugin: The recognised family, or ``None`` when discovery found none.
        run_command: Injected command runner; the real one by default.
    """

    if plugin is None:
        return {
            "step": "reindex",
            "outcome": "not-present",
            "exit_code": None,
            "log_path": str(log_path),
            "log_lines": _log_lines(log_path),
            "anomalies": [],
        }

    run = run_command if run_command is not None else _real_runner(None)
    probe_command, rebuild_args = SEARCH_INDEX_FAMILIES[plugin]

    probe_args = [*shlex.split(DEFAULT_RUNNER), "cli", "has-command", probe_command]
    probe = run(probe_args)
    _append_log(log_path, probe_args, probe)

    # A failed probe is the settled fallback, not an error: the index is left
    # empty and the report tells the operator to rebuild it from wp-admin.
    if probe.returncode != 0:
        return {
            "step": "reindex",
            "outcome": "cli-unavailable",
            "exit_code": None,
            "probe_exit_code": probe.returncode,
            "log_path": str(log_path),
            "log_lines": _log_lines(log_path),
            "anomalies": [],
        }

    rebuild = [*shlex.split(DEFAULT_RUNNER), *rebuild_args]
    result = run(rebuild)
    _append_log(log_path, rebuild, result)

    return {
        "step": "reindex",
        "outcome": "rebuilt",
        "exit_code": result.returncode,
        "probe_exit_code": probe.returncode,
        "command": shlex.join(rebuild),
        "log_path": str(log_path),
        "log_lines": _log_lines(log_path),
        "anomalies": _anomalies(result),
    }


def _build_parser() -> argparse.ArgumentParser:
    """The CLI: one subcommand per noisy step, each taking the log it fills.

    The options every step shares are declared on a parent parser rather than
    on the top level, so they may follow the subcommand — ``wp_quiet.py
    regenerate --log …`` is how a caller naturally writes it.
    """

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--runner",
        default=DEFAULT_RUNNER,
        help=f"How to reach WP-CLI (default: {DEFAULT_RUNNER!r})",
    )
    common.add_argument("--dir", type=Path, default=None, help="Directory to run the step in")
    common.add_argument("--log", type=Path, required=True, help="Where the full output is kept")

    parser = argparse.ArgumentParser(
        description="Run a noisy local WP-CLI step quietly: full output to a log, summary to stdout."
    )
    steps = parser.add_subparsers(dest="step", required=True)

    regenerate_step = steps.add_parser(
        "regenerate", parents=[common], help="Regenerate thumbnails"
    )
    regenerate_step.add_argument(
        "--ids",
        default="",
        help="Comma-separated attachment ids; omit for the whole library",
    )

    reindex_step = steps.add_parser(
        "reindex", parents=[common], help="Rebuild the local search index"
    )
    reindex_step.add_argument(
        "--plugin",
        choices=sorted(SEARCH_INDEX_FAMILIES),
        default=None,
        help="The active search-index family; omit when there is none",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry: run the named step, print its summary, exit on its outcome.

    The exit status follows the command's own — a swallowed non-zero exit would
    turn quiet into silent, which is the one thing this helper must not be. It
    reports what the command did and never judges the copy: both steps rebuild
    local artifacts that were deliberately never transferred, so the phase
    driving this wrapper classifies a non-zero exit here as an anomaly, never a
    failure (issue #59, ADR-0028).
    """

    parser = _build_parser()
    args = parser.parse_args(argv)

    runner_prefix = shlex.split(args.runner)
    run_command = _wrapped_runner(runner_prefix, args.dir)

    if args.step == "regenerate":
        ids = [int(part) for part in args.ids.split(",") if part.strip()]
        summary = regenerate(log_path=args.log, ids=ids or None, run_command=run_command)
    else:
        summary = reindex(log_path=args.log, plugin=args.plugin, run_command=run_command)

    json.dump(summary, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 1 if summary.get("exit_code") else 0


def _wrapped_runner(runner_prefix: Sequence[str], cwd: Path | None) -> CommandRunner:
    """Swap the default ``ddev wp`` prefix for whatever the caller named, then
    run in the given directory — ``ddev wp`` only works inside the project, and
    a caller should not have to change directory around the invocation."""

    default_prefix = shlex.split(DEFAULT_RUNNER)
    real = _real_runner(cwd)

    def run(args: Sequence[str]) -> Completed:
        rest = list(args)[len(default_prefix) :]
        return real([*runner_prefix, *rest])

    return run


if __name__ == "__main__":
    raise SystemExit(main())
