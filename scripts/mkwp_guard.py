# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The `mkwp` version guard — the single source of truth for whether a local
`mkwp` on `PATH` meets the floor the scaffold step needs.

`mkwp` >= 1.5.0 is the floor because that release added the `--dirname` flag
([Kntnt/mkwp#2](https://github.com/Kntnt/mkwp/issues/2)), which lets a site's
directory name diverge from its DDEV project name — the convention issue #11
settled for a clone landing under its production host's full name. Rather than
parse `mkwp`'s own version banner (a string with no stability contract across
releases), the guard checks for the flag's own presence in `mkwp --help`'s
output — the artefact whose absence is the actual failure mode `clone`'s
health check (spec.md, Clone bookends) and this plugin's `mkwp` skill both
guard against.

This module is the ONE place the guard's pass/fail verdict and remediation
message are computed, so every caller — the `mkwp` skill's own preflight today,
and the shared dependency health check (issue #23) once it lands — reads the
same verdict instead of maintaining separate copies of the same check and
message.
"""

from __future__ import annotations

import json
import sys
from typing import Any

__all__ = ["FLOOR_VERSION", "REQUIRED_FLAG", "check", "main"]

# The floor version and the flag whose presence in `mkwp --help` proves it —
# kept together so a future floor bump touches one place.
FLOOR_VERSION = "1.5.0"
REQUIRED_FLAG = "--dirname"

# The install-guidance line every failed guard prints verbatim — never
# reworded independently by the model at run time.
REMEDIATION = (
    f"Install or upgrade mkwp to >= {FLOOR_VERSION}: "
    "https://github.com/Kntnt/mkwp — the --dirname flag "
    "(https://github.com/Kntnt/mkwp/issues/2) is the floor this plugin's "
    "scaffold step relies on."
)


def check(help_output: str | None) -> dict[str, Any]:
    """Verdict the guard: does `mkwp --help`'s output list `--dirname`?

    Args:
        help_output: The captured stdout of `mkwp --help`, or ``None`` when
            `mkwp` itself is missing from `PATH` (the caller could not run it
            at all — a "command not found" is not help output).

    Returns:
        ``{"ok": True}`` on success, or ``{"ok": False, "reason": <str>,
        "remediation": REMEDIATION}`` on failure — the same shape whichever
        of the two failure modes triggered it, so a caller can print
        ``remediation`` verbatim without branching on the reason.
    """

    if help_output is None:
        return {
            "ok": False,
            "reason": "mkwp is not on PATH",
            "remediation": REMEDIATION,
        }
    if REQUIRED_FLAG not in help_output:
        return {
            "ok": False,
            "reason": f"mkwp on PATH does not support {REQUIRED_FLAG} (< {FLOOR_VERSION})",
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
