# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The `mkwp` version guard — the single source of truth for whether a local
`mkwp` on `PATH` meets the floor the scaffold step needs.

`mkwp` >= 1.8.1 is the floor because that release fixed
[Kntnt/mkwp#3](https://github.com/Kntnt/mkwp/issues/3): every `mkwp` <= 1.8.0
whose `--dirname` diverges from `NAME` dies with a database-connection error
before `wp-config.php` is ever written, since its `ddev config` call omitted
`--project-name` while wp-config hardcoded the database host to
`ddev-<NAME>-db`. `--dirname` itself has been present since 1.5.0
([Kntnt/mkwp#2](https://github.com/Kntnt/mkwp/issues/2)), so the flag's mere
presence in `mkwp --help` no longer distinguishes a working `mkwp` from a
broken one — 1.7.0 and 1.8.0 both have it and both still break. The guard
instead parses the version `mkwp` itself prints in its `--help` banner (the
`NAME` section's `mkwp <version> - make wordpress` line, present since 1.7.0)
and compares it against the floor; a banner with no version at all (`mkwp` <
1.7.0, printed as bare `mkwp - make wordpress`) is older than the floor by
construction and fails the same way.

This module is the ONE place the guard's pass/fail verdict and remediation
message are computed, so every caller — the `mkwp` skill's own preflight (its
§1) and `clone`'s own dependency health-check step (its §1, issue #23) — reads
the same verdict instead of maintaining separate copies of the same check and
message.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

__all__ = ["FLOOR_VERSION", "check", "main"]

# The floor version, and the pattern that extracts the version mkwp itself
# reports in its `--help` banner's NAME section — kept together so a future
# floor bump touches one place.
FLOOR_VERSION = "1.8.1"
_FLOOR_VERSION_TUPLE = tuple(int(part) for part in FLOOR_VERSION.split("."))
_VERSION_PATTERN = re.compile(r"mkwp\s+(\d+)\.(\d+)\.(\d+)\s*-\s*make wordpress")

# The install-guidance line every failed guard prints verbatim — never
# reworded independently by the model at run time.
REMEDIATION = (
    f"Install or upgrade mkwp to >= {FLOOR_VERSION}: "
    "https://github.com/Kntnt/mkwp — v1.8.1 fixes the --dirname/NAME "
    "database-connection defect "
    "(https://github.com/Kntnt/mkwp/issues/3) this plugin's scaffold step "
    "relies on being fixed."
)


def _parsed_version(help_output: str) -> tuple[int, int, int] | None:
    """Extract the `(major, minor, patch)` version from `mkwp --help`'s own
    `NAME` section, or ``None`` when the banner carries no version at all —
    the shape every `mkwp` < 1.7.0 prints."""

    match = _VERSION_PATTERN.search(help_output)
    if match is None:
        return None
    return int(match[1]), int(match[2]), int(match[3])


def check(help_output: str | None) -> dict[str, Any]:
    """Verdict the guard: does `mkwp --help`'s own version banner meet the
    floor?

    Args:
        help_output: The captured stdout of `mkwp --help`, or ``None`` when
            `mkwp` itself is missing from `PATH` (the caller could not run it
            at all — a "command not found" is not help output).

    Returns:
        ``{"ok": True}`` on success, or ``{"ok": False, "reason": <str>,
        "remediation": REMEDIATION}`` on failure — the same shape whichever
        of the three failure modes triggered it, so a caller can print
        ``remediation`` verbatim without branching on the reason.
    """

    if help_output is None:
        return {
            "ok": False,
            "reason": "mkwp is not on PATH",
            "remediation": REMEDIATION,
        }
    version = _parsed_version(help_output)
    if version is None:
        return {
            "ok": False,
            "reason": f"mkwp on PATH reports no version in --help (< {FLOOR_VERSION})",
            "remediation": REMEDIATION,
        }
    if version < _FLOOR_VERSION_TUPLE:
        found = ".".join(str(part) for part in version)
        return {
            "ok": False,
            "reason": f"mkwp on PATH is version {found}, below the floor {FLOOR_VERSION}",
            "remediation": REMEDIATION,
        }
    return {"ok": True}


def main() -> None:
    """CLI entry point: read ``{"helpOutput": <str or null>}`` JSON from
    stdin, write the verdict JSON to stdout."""

    config = json.load(sys.stdin)
    verdict = check(config.get("helpOutput"))
    json.dump(verdict, sys.stdout)


if __name__ == "__main__":
    main()
