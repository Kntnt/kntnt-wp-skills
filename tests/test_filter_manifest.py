"""Behavioural tests for the local manifest-filtering helper CLI.

Issue #18: ``templates/manifest.php`` no longer takes an exclusion payload — it
walks and echoes production's whole content tree unfiltered, so the (often
thousands-of-entries) exclusion set never travels to production as part of a
manifest request. This helper is the local-filtering seam that replaces the
former production-side pruning: it takes the raw, unfiltered manifest walk and
the resolved exclusion set as one JSON object on stdin, and writes the manifest
restricted to the in-scope entries — the exact shape
``scripts/baseline_diff.py`` has always consumed as one side of its diff —
to stdout.

Every test exercises that seam through the real command — fixtures or
in-memory payloads in, observable output out — and never reaches into the
helper's internals, per the project's testing decisions. Scope semantics
(exact-match-or-descendant, path-segment aware, anchored at the WordPress
root) must be identical to the previous production-side filter — proven here
directly, and end-to-end by feeding this helper's output straight into
``scripts/baseline_diff.py`` unchanged.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "filter_manifest.py"
BASELINE_DIFF = Path(__file__).resolve().parent.parent / "scripts" / "baseline_diff.py"


def run_filter(raw: bytes) -> subprocess.CompletedProcess[bytes]:
    """Run the helper with ``raw`` on stdin and capture its result."""

    return subprocess.run([sys.executable, str(SCRIPT)], input=raw, capture_output=True)


def filter_on(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the helper on an in-memory payload and return the parsed result,
    asserting the run succeeded."""

    result = run_filter(json.dumps(payload).encode())
    assert result.returncode == 0, result.stderr.decode()
    document: dict[str, Any] = json.loads(result.stdout)
    return document


def entry(path: str, size: int = 1, mtime: int = 1) -> dict[str, Any]:
    """Build one raw manifest entry — the row shape the unfiltered walk emits."""

    return {"path": path, "size": size, "mtime": mtime}


def test_an_entry_with_no_matching_exclusion_is_kept() -> None:
    # Arrange & Act — nothing excludes this plugin file.
    result = filter_on({
        "entries": [entry("wp-content/plugins/acme/acme.php")],
        "exclusions": ["wp-content/uploads/gallery"],
    })

    # Assert.
    assert [row["path"] for row in result["entries"]] == ["wp-content/plugins/acme/acme.php"]


def test_an_entry_matching_an_exclusion_prefix_exactly_is_dropped() -> None:
    # Arrange & Act — the excluded path itself, as a file entry.
    result = filter_on({
        "entries": [entry("wp-content/uploads/gallery")],
        "exclusions": ["wp-content/uploads/gallery"],
    })

    # Assert.
    assert result["entries"] == []


def test_a_nested_entry_under_an_excluded_directory_is_dropped() -> None:
    # Arrange & Act — a file deep under the excluded prefix.
    result = filter_on({
        "entries": [entry("wp-content/uploads/gallery/2024/big.jpg")],
        "exclusions": ["wp-content/uploads/gallery"],
    })

    # Assert — matches the production-side filter's prior behaviour exactly.
    assert result["entries"] == []


def test_a_same_named_sibling_of_an_excluded_path_is_kept() -> None:
    # Arrange — "gallery-archive" merely starts with "gallery"; matching must be
    # path-segment aware, not a bare string prefix.
    result = filter_on({
        "entries": [entry("wp-content/uploads/gallery-archive/keep.jpg")],
        "exclusions": ["wp-content/uploads/gallery"],
    })

    # Assert.
    assert [row["path"] for row in result["entries"]] == [
        "wp-content/uploads/gallery-archive/keep.jpg"
    ]


def test_no_exclusions_keeps_every_entry() -> None:
    # Arrange & Act — an empty resolved scope is a legitimate "everything in
    # scope" run, not an error.
    rows = [entry("wp-content/plugins/acme/acme.php"), entry("wp-content/themes/astra/style.css")]
    result = filter_on({"entries": rows, "exclusions": []})

    # Assert.
    assert len(result["entries"]) == 2


def test_missing_exclusions_defaults_to_none_excluded() -> None:
    # Arrange & Act — the field is optional, defaulting the same way
    # ``scripts/baseline_diff.py``'s own scope parsing does.
    result = filter_on({"entries": [entry("wp-content/plugins/acme/acme.php")]})

    # Assert.
    assert len(result["entries"]) == 1


def test_the_output_carries_the_resolved_exclusions_forward_as_scope() -> None:
    # Arrange & Act — the filtered manifest must still report the scope it was
    # taken under, exactly like the former production-side emission did.
    result = filter_on({
        "entries": [],
        "exclusions": ["wp-content/uploads/gallery"],
    })

    # Assert.
    assert result["scope"] == {"exclusions": ["wp-content/uploads/gallery"]}


def test_a_trailing_slash_on_an_exclusion_is_normalised_away() -> None:
    # Arrange & Act — the caller may spell the prefix either way.
    result = filter_on({
        "entries": [entry("wp-content/uploads/gallery/big.jpg")],
        "exclusions": ["wp-content/uploads/gallery/"],
    })

    # Assert — still excluded, and the normalised form is what is carried
    # forward as scope.
    assert result["entries"] == []
    assert result["scope"] == {"exclusions": ["wp-content/uploads/gallery"]}


def test_malformed_json_input_fails_loudly() -> None:
    # Arrange & Act.
    result = run_filter(b"this is not json")

    # Assert — a non-zero exit and a diagnostic naming the failure, never a
    # half-built document on stdout.
    assert result.returncode != 0
    assert b"not valid JSON" in result.stderr
    assert result.stdout == b""


def test_a_missing_entries_field_fails_loudly() -> None:
    # Arrange & Act.
    result = run_filter(b'{"exclusions": []}')

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"filter-manifest:")
    assert b"entries" in result.stderr


def test_an_entry_without_a_path_fails_loudly() -> None:
    # Arrange — an entry missing its path cannot be tested against the
    # exclusion set and would otherwise ride through silently.
    payload = {"entries": [{"size": 1, "mtime": 1}], "exclusions": []}

    # Act.
    result = run_filter(json.dumps(payload).encode())

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"filter-manifest:")
    assert b"path" in result.stderr


def test_a_non_string_exclusion_fails_loudly() -> None:
    # Arrange & Act.
    payload = {"entries": [], "exclusions": [42]}
    result = run_filter(json.dumps(payload).encode())

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"filter-manifest:")
    assert b"exclusions" in result.stderr


def test_the_filtered_output_feeds_baseline_diff_unchanged() -> None:
    # Arrange — the load-bearing end-to-end proof: filter a raw, unfiltered
    # walk that mixes an excluded gallery, an excluded gallery's file, a
    # same-named sibling, and plain in-scope files, then wire the result
    # straight into the real ``baseline_diff.py`` as its "current" side,
    # exactly as the skill orchestration is documented to do.
    raw_walk = {
        "entries": [
            entry("wp-content/uploads/gallery/big.jpg", size=9, mtime=9),
            entry("wp-content/uploads/gallery-archive/keep.jpg", size=7, mtime=7),
            entry("wp-content/plugins/acme/acme.php", size=2000, mtime=1700000000),
        ],
        "exclusions": ["wp-content/uploads/gallery"],
    }
    filtered = filter_on(raw_walk)

    diff_input = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-content/plugins/old/old.php", size=1, mtime=1)],
        },
        "current": filtered,
    }

    # Act.
    diff = subprocess.run(
        [sys.executable, str(BASELINE_DIFF)],
        input=json.dumps(diff_input).encode(),
        capture_output=True,
    )

    # Assert — the diff sees only the locally-filtered entries: the gallery
    # file never appears (filtered out before the diff ever ran), the sibling
    # and the plugin file are diffed normally, and the vanished baseline file
    # is production-deleted because it is in scope this run.
    assert diff.returncode == 0, diff.stderr.decode()
    result = json.loads(diff.stdout)
    assert result["new_or_changed"] == [
        "wp-content/plugins/acme/acme.php",
        "wp-content/uploads/gallery-archive/keep.jpg",
    ]
    assert result["production_deleted"] == ["wp-content/plugins/old/old.php"]
