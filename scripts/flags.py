# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The canonical flag registry — single source of truth for the flags the skills accept.

STUB: the registry is not yet populated. The help/docs consistency test is
written first and fails against this empty surface; the next commit fills it in.
"""

from __future__ import annotations

import json

# The complete set of tokens the skills accept — deliberately empty until the
# registry is populated.
ALL_FLAGS: frozenset[str] = frozenset()


def main() -> None:
    """Emit the registry as JSON on stdout."""

    print(json.dumps(sorted(ALL_FLAGS), indent=2))


if __name__ == "__main__":
    main()
