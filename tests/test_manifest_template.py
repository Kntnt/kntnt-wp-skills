"""Consistency check for the production-side baseline manifest payload template.

The manifest template is sent over the control channel and echoes the single
JSON object ``scripts/filter_manifest.py`` reads as its raw, unfiltered input.
It is INERT in this build (never run against a live site here), so this is a
content check (no PHP runtime), guarding the one cross-issue invariant issue
#18 introduces: the exclusion set — thousands of entries on a real site — must
never travel to production as part of a manifest request. The template takes
no exclusion payload and walks the whole content tree; scope filtering happens
locally afterwards (``scripts/filter_manifest.py``, ADR-0006 addendum).
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "manifest.php"


def test_template_exists() -> None:
    """The plugin ships the manifest-walk payload."""

    assert _TEMPLATE.is_file()


def test_template_carries_no_exclusion_payload() -> None:
    """The payload must not declare, accept, or apply an exclusion set — the
    injection point a runtime skill could substitute a resolved exclusion list
    into. A production request built from this template can therefore never
    embed the exclusion set, however large it grows on a real site (the smoke
    test measured 6,135 entries / ~436KB for one site)."""

    source = _TEMPLATE.read_text(encoding="utf-8")

    assert "$exclusions" not in source
    assert "exclusion" not in source.lower()


def test_template_applies_no_scope_filtering_while_walking() -> None:
    """The walk must not prune any subtree — no callback filter, no per-file
    exclusion test — so the echoed tree is the full content tree, not a
    server-side-filtered one. Local filtering is the prescribed path now."""

    source = _TEMPLATE.read_text(encoding="utf-8")

    assert "RecursiveCallbackFilterIterator" not in source
    assert "is_excluded" not in source


def test_template_walks_the_full_content_tree_anchored_at_the_wordpress_root() -> None:
    """The walk still anchors every emitted path at the WordPress root — the
    one spelling ``scripts/filter_manifest.py`` and ``scripts/baseline_diff.py``
    match exclusion prefixes against (the anchoring fix, commit de908bd)."""

    source = _TEMPLATE.read_text(encoding="utf-8")

    assert "ABSPATH" in source
    assert "RecursiveDirectoryIterator" in source
    assert "RecursiveIteratorIterator" in source


def test_template_emits_only_entries_no_scope_key() -> None:
    """The echoed object carries only the raw entries — no ``scope`` key, since
    production no longer knows the exclusion set and has nothing to report it
    took a walk "under". ``scripts/filter_manifest.py`` is what attaches the
    resolved scope to its output."""

    source = _TEMPLATE.read_text(encoding="utf-8")

    assert "'entries'" in source or '"entries"' in source
    assert "'scope'" not in source and '"scope"' not in source


def test_template_records_path_size_and_mtime_per_entry() -> None:
    """Every entry still carries the size+mtime quick-check pair the diff
    compares, keyed by its WordPress-root-relative path."""

    source = _TEMPLATE.read_text(encoding="utf-8")

    assert "'path'" in source
    assert "'size'" in source
    assert "'mtime'" in source
