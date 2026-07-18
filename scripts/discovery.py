# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Parse the raw health-check and discovery output into one canonical discovery document.

Stub — not yet implemented. Echoes the raw discovery section so the behavioural
tests fail on their assertions (red) before the real transform exists.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    """Echo the raw ``discovery`` section unchanged (placeholder)."""

    raw = json.load(sys.stdin)
    json.dump(raw.get("discovery", {}), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
