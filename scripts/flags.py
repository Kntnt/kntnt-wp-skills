# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The canonical flag registry — single source of truth for the flags the skills accept.

The flag surface is deliberately minimal (ADR-0013): a small set of coarse
scope- and behaviour-tuning switches that let an unattended run deviate from the
discovery-derived defaults, plus the three spellings of the help gate — and
nothing else. Both skills, ``clone`` and ``pull``, accept exactly this surface.

This registry is the authority that binds the documentation to the
implementation: the help/docs consistency test asserts every flag a manual page
documents is in ``ALL_FLAGS`` and every flag in ``ALL_FLAGS`` is documented for
both skills, so neither can drift from the other. Later issues' argument-parsing
helpers read the same registry; running this module directly emits it as JSON
for any non-Python consumer.
"""

from __future__ import annotations

import json

# The operational flags: coarse scope- and behaviour-tuning switches for an
# unattended (`--yes`) run to override the discovery-derived defaults. Ordered as
# the manual pages present them in their SYNOPSIS.
OPERATIONAL_FLAGS: tuple[str, ...] = (
    "--yes",
    "--include-media",
    "--exclude-media",
    "--include-blobs",
    "--live-mail",
    "--capture-mail",
    "--no-cron",
    "--regenerate-all",
)

# The help gate's three accepted spellings: any one prints the skill's manual
# page and stops.
HELP_FORMS: tuple[str, ...] = ("help", "--help", "-h")

# Every token the skills accept, flattened — the set the consistency test and
# the argument parsers check against.
ALL_FLAGS: frozenset[str] = frozenset(OPERATIONAL_FLAGS + HELP_FORMS)


def main() -> None:
    """Emit the registry as JSON on stdout — the helper-seam contract for any
    non-Python consumer."""

    print(
        json.dumps(
            {"operational": list(OPERATIONAL_FLAGS), "help_forms": list(HELP_FORMS)},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
