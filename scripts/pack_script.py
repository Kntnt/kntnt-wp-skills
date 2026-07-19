# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Generate the production-side pack script from resolved inputs.

Deterministic helper on the transfer engine's single automated seam: resolved
inputs (table classification, exclusion paths, archive/transfer set, working and
download dirs) go in as JSON, the ``pack.sh`` the background job runs comes out.
The model never assembles this shell by hand — it is generated here and unit
tested, then executed in a sandbox with stub binaries to prove its runtime
contract. See ``docs/spec.md`` (The deterministic helper seam) and
``docs/implementation-notes.md`` (Pack).
"""

from __future__ import annotations

from typing import Any

__all__ = ["generate_pack_script", "main"]


def generate_pack_script(config: dict[str, Any]) -> str:
    """Render the pack script text from a resolved-inputs mapping.

    Not yet implemented — this stub exists so the test suite can bind to the
    seam and be seen failing before the satisfying code exists.
    """

    raise NotImplementedError


def main() -> None:
    """CLI entry point: read a resolved-inputs JSON object from stdin, write the
    generated pack script to stdout."""

    raise NotImplementedError


if __name__ == "__main__":
    main()
