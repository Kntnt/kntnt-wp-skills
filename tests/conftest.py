"""Shared test configuration for the deterministic-helper suite.

The single automated seam for this plugin is the deterministic helper CLI, so
these tests never reach a live site, a real DDEV instance, or the Kntnt
Extractor REST API. This module's only job is to make the standalone helper
scripts under ``scripts/`` importable by the tests that exercise them at that
seam (``import flags``, ``import smoke_test``, ``import classify``, …), without
packaging them.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the standalone helper scripts importable without packaging them.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
