# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Behavioural tests for the baseline-diff helper CLI.

The helper is the deterministic seam of the file-sync arithmetic (ADR-0006):
the stored last-sync baseline and the current production manifest go in as one
JSON object on stdin, and the two decision sets come out as JSON on stdout — the
``new_or_changed`` set to pull and the ``production_deleted`` set for the
deletion gate. Malformed input fails loudly with a non-zero exit and an empty
stdout, never a half-built document.

Every test exercises that seam through the real command — fixtures or in-memory
payloads in, observable output out — and never reaches into the helper's
internals. No test touches a real site or the local filesystem tree: the
manifests are exactly what the production-side emission would report, supplied as
data. The load-bearing case is the scope-intersection rule — a directory
excluded this run but still present on production must never look deleted — so it
is proven by a dedicated fixture.

Since issue #18, the ``current`` side supplied here is exactly what it always
was — an in-scope manifest with the scope it was taken under — but it now
arrives pre-filtered by ``scripts/filter_manifest.py`` locally rather than by a
production-side walk that took an exclusion payload. This helper's contract is
unchanged; see ``tests/test_filter_manifest.py`` for the filtering seam and its
end-to-end proof that a locally-filtered manifest diffs identically here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "baseline_diff.py"


def run_diff(raw: bytes) -> subprocess.CompletedProcess[bytes]:
    """Run the helper with ``raw`` on stdin and capture its result."""

    return subprocess.run([sys.executable, str(SCRIPT)], input=raw, capture_output=True)


def diff_for(fixture: str) -> dict[str, Any]:
    """Run the helper on a named fixture and return the parsed result, asserting
    the run succeeded."""

    result = run_diff((FIXTURES / fixture).read_bytes())
    assert result.returncode == 0, result.stderr.decode()
    document: dict[str, Any] = json.loads(result.stdout)
    return document


def run_on(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the helper on an in-memory payload and return the parsed result — the
    same seam as a fixture file, but for inputs a test constructs on the fly."""

    result = run_diff(json.dumps(payload).encode())
    assert result.returncode == 0, result.stderr.decode()
    document: dict[str, Any] = json.loads(result.stdout)
    return document


def entry(path: str, size: int, mtime: int) -> dict[str, Any]:
    """Build one manifest entry — path, size, and mtime — the row shape both
    manifests are lists of."""

    return {"path": path, "size": size, "mtime": mtime}


def test_empty_baseline_makes_everything_new_and_deletes_nothing() -> None:
    # Arrange & Act — the clone case: no baseline, so the diff has nothing to
    # compare against.
    result = diff_for("baseline-diff-clone.json")

    # Assert — every current file is new to pull, and nothing can be
    # production-deleted because there was no prior manifest.
    assert result["new_or_changed"] == [
        "wp-content/plugins/acme/acme.php",
        "wp-content/themes/astra/style.css",
    ]
    assert result["production_deleted"] == []


def test_a_directory_excluded_this_run_is_never_production_deleted() -> None:
    # Arrange & Act — the baseline was taken with the gallery included; this run
    # excludes it, so the gallery files are absent from the current manifest yet
    # still present on production.
    result = diff_for("baseline-diff-scope-change.json")

    # Assert — the load-bearing scope-intersection rule (ADR-0006): a subtree
    # excluded this run is out of scope for the deletion diff, so its still-present
    # files never appear as production-deleted.
    assert "wp-content/uploads/gallery/big-1.jpg" not in result["production_deleted"]
    assert "wp-content/uploads/gallery/big-2.jpg" not in result["production_deleted"]


def test_a_file_gone_from_production_while_in_scope_is_deleted() -> None:
    # Arrange & Act — the same run also has a plugin file present in the baseline,
    # in scope both runs, and gone from production now.
    result = diff_for("baseline-diff-scope-change.json")

    # Assert — the scope rule protects excluded subtrees without blinding the diff
    # to a genuine deletion: an in-scope file gone from production is the only
    # member of the deletion set.
    assert result["production_deleted"] == ["wp-content/plugins/old/old.php"]


def test_new_or_changed_carries_new_and_changed_files_only() -> None:
    # Arrange & Act.
    result = diff_for("baseline-diff-scope-change.json")

    # Assert — a brand-new file, a size-changed file, and an mtime-changed file
    # are all to pull; the byte-identical, same-mtime file is not.
    assert result["new_or_changed"] == [
        "wp-content/plugins/acme/acme.php",
        "wp-content/plugins/new/new.php",
        "wp-content/themes/astra/style.css",
    ]


def test_a_size_only_change_counts_as_changed() -> None:
    # Arrange — one file whose mtime is identical across runs but whose size grew.
    payload = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-content/plugins/acme/acme.php", 2000, 1700000000)],
        },
        "current": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-content/plugins/acme/acme.php", 2500, 1700000000)],
        },
    }

    # Act.
    result = run_on(payload)

    # Assert — size is half of the size+mtime quick-check, so a size-only change
    # is enough to mark the file for transfer.
    assert result["new_or_changed"] == ["wp-content/plugins/acme/acme.php"]
    assert result["production_deleted"] == []


def test_an_mtime_only_change_counts_as_changed() -> None:
    # Arrange — one file whose size is identical across runs but whose mtime moved.
    payload = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-content/themes/astra/style.css", 400, 1700000010)],
        },
        "current": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-content/themes/astra/style.css", 400, 1700000600)],
        },
    }

    # Act.
    result = run_on(payload)

    # Assert — mtime is the other half of the quick-check, so an mtime-only change
    # is enough on its own.
    assert result["new_or_changed"] == ["wp-content/themes/astra/style.css"]
    assert result["production_deleted"] == []


def test_a_byte_identical_file_is_in_neither_set() -> None:
    # Arrange — a file whose path, size, and mtime are all unchanged.
    row = entry("wp-content/plugins/acme/acme.php", 2000, 1700000000)
    payload = {
        "baseline": {"scope": {"exclusions": []}, "entries": [row]},
        "current": {"scope": {"exclusions": []}, "entries": [dict(row)]},
    }

    # Act.
    result = run_on(payload)

    # Assert — the negative control that gives the size- and mtime-change tests
    # their meaning: an unchanged file is neither pulled nor deleted.
    assert result["new_or_changed"] == []
    assert result["production_deleted"] == []


def test_a_file_under_a_nested_excluded_path_is_not_deleted() -> None:
    # Arrange — the baseline holds a file deep under a directory this run excludes;
    # exclusion is by anchored prefix, so the whole subtree is out of scope.
    payload = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-content/uploads/gallery/2024/big.jpg", 9000, 1700000000)],
        },
        "current": {
            "scope": {"exclusions": ["wp-content/uploads/gallery"]},
            "entries": [],
        },
    }

    # Act.
    result = run_on(payload)

    # Assert — a nested file under an excluded directory is protected too, not just
    # a file sitting directly in it.
    assert result["production_deleted"] == []


def test_a_same_named_sibling_of_an_excluded_path_is_still_diffed() -> None:
    # Arrange — an exclusion of "…/gallery" must not swallow a sibling directory
    # whose name merely starts with the same string ("…/gallery-archive").
    payload = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-content/uploads/gallery-archive/keep.jpg", 700, 1700000000)],
        },
        "current": {
            "scope": {"exclusions": ["wp-content/uploads/gallery"]},
            "entries": [],
        },
    }

    # Act.
    result = run_on(payload)

    # Assert — prefix matching is path-segment aware, so "gallery-archive" is in
    # scope and its vanished file is a real deletion, not a false exclusion.
    assert result["production_deleted"] == ["wp-content/uploads/gallery-archive/keep.jpg"]


# --- Credential-bearing glob patterns (issue #36) ------------------------------


def test_a_vanished_wp_config_backup_is_not_production_deleted() -> None:
    # Arrange — a wp-config backup somehow rode into a baseline before this
    # exclusion existed; this run's scope now carries the glob, so its
    # disappearance from production is out-of-scope, not a real deletion.
    payload = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-config.php.bak-20260717-212309", 4096, 1700000000)],
        },
        "current": {
            "scope": {"exclusions": ["wp-config.php.*"]},
            "entries": [],
        },
    }

    # Act.
    result = run_on(payload)

    # Assert.
    assert result["production_deleted"] == []


def test_a_vanished_env_file_is_not_production_deleted() -> None:
    payload = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-content/plugins/acme/.env", 200, 1700000000)],
        },
        "current": {
            "scope": {"exclusions": ["**/.env"]},
            "entries": [],
        },
    }
    result = run_on(payload)
    assert result["production_deleted"] == []


def test_a_vanished_root_sql_dump_is_not_production_deleted() -> None:
    payload = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("dump.sql", 5000, 1700000000)],
        },
        "current": {
            "scope": {"exclusions": ["*.sql"]},
            "entries": [],
        },
    }
    result = run_on(payload)
    assert result["production_deleted"] == []


def test_a_vanished_root_key_file_is_not_production_deleted() -> None:
    payload = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("id_rsa", 1200, 1700000000)],
        },
        "current": {
            "scope": {"exclusions": ["id_rsa*"]},
            "entries": [],
        },
    }
    result = run_on(payload)
    assert result["production_deleted"] == []


def test_a_vanished_wp_config_sample_file_is_still_production_deleted() -> None:
    # Arrange — the sample file is carved back out of the broad
    # "wp-config-*.php" variant glob, so it stays in scope and a real
    # disappearance is a genuine deletion.
    payload = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-config-sample.php", 3000, 1700000000)],
        },
        "current": {
            "scope": {"exclusions": ["wp-config-*.php"]},
            "entries": [],
        },
    }

    # Act.
    result = run_on(payload)

    # Assert.
    assert result["production_deleted"] == ["wp-config-sample.php"]


# --- WordPress core tree (issue #37) --------------------------------------------


def test_a_vanished_core_directory_file_is_not_production_deleted() -> None:
    # Arrange — a core file that was in a stale baseline (taken before this
    # exclusion existed) but is out of scope this run: its absence from the
    # current, in-scope manifest is not a real deletion.
    payload = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-admin/index.php", 4096, 1700000000)],
        },
        "current": {
            "scope": {"exclusions": ["wp-admin"]},
            "entries": [],
        },
    }
    result = run_on(payload)
    assert result["production_deleted"] == []


def test_a_vanished_root_core_php_file_is_not_production_deleted() -> None:
    payload = {
        "baseline": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-login.php", 2000, 1700000000)],
        },
        "current": {
            "scope": {"exclusions": ["wp-login.php"]},
            "entries": [],
        },
    }
    result = run_on(payload)
    assert result["production_deleted"] == []


def test_outputs_are_sorted_for_deterministic_reports() -> None:
    # Arrange — current entries deliberately out of lexical order.
    payload = {
        "baseline": {"scope": {"exclusions": []}, "entries": []},
        "current": {
            "scope": {"exclusions": []},
            "entries": [
                entry("wp-content/plugins/zeta/z.php", 1, 1),
                entry("wp-content/plugins/alpha/a.php", 1, 1),
            ],
        },
    }

    # Act.
    result = run_on(payload)

    # Assert — the helper sorts its sets, so the record reads the same every run.
    assert result["new_or_changed"] == sorted(result["new_or_changed"])


def test_malformed_json_input_fails_loudly() -> None:
    # Arrange & Act.
    result = run_diff(b"this is not json")

    # Assert — a non-zero exit and a diagnostic naming the failure, never a
    # half-built document on stdout.
    assert result.returncode != 0
    assert b"not valid JSON" in result.stderr
    assert result.stdout == b""


def test_a_missing_baseline_section_fails_loudly() -> None:
    # Arrange & Act — a well-formed object lacking the required baseline section.
    result = run_diff(b'{"current": {"entries": []}}')

    # Assert — a loud exit naming the missing section, not a partial document.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"baseline-diff:")
    assert b"baseline" in result.stderr


def test_a_missing_current_section_fails_loudly() -> None:
    # Arrange & Act — the mirror case: the current manifest is required too.
    result = run_diff(b'{"baseline": {"entries": []}}')

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"baseline-diff:")
    assert b"current" in result.stderr


def test_a_manifest_entry_without_a_path_fails_loudly() -> None:
    # Arrange — an entry missing its path would otherwise ride into the diff as a
    # keyless row and corrupt both sets silently.
    payload = {
        "baseline": {"scope": {"exclusions": []}, "entries": []},
        "current": {
            "scope": {"exclusions": []},
            "entries": [{"size": 1000, "mtime": 1700000000}],
        },
    }

    # Act.
    result = run_diff(json.dumps(payload).encode())

    # Assert — the precise diagnostic, not a stack trace, and no partial document.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"baseline-diff:")
    assert b"path" in result.stderr


def test_a_manifest_entry_with_a_wrongly_typed_size_fails_loudly() -> None:
    # Arrange — size drives the change detection; a string would compare unequal
    # to every baseline size and mark unchanged files for transfer.
    payload = {
        "baseline": {"scope": {"exclusions": []}, "entries": []},
        "current": {
            "scope": {"exclusions": []},
            "entries": [{"path": "a.php", "size": "big", "mtime": 1700000000}],
        },
    }

    # Act.
    result = run_diff(json.dumps(payload).encode())

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"baseline-diff:")
    assert b"size" in result.stderr


def test_a_non_string_scope_exclusion_fails_loudly() -> None:
    # Arrange — the exclusions gate the deletion set; a non-string entry would
    # crash the prefix check with an uncaught traceback rather than a diagnostic.
    payload = {
        "baseline": {"scope": {"exclusions": []}, "entries": []},
        "current": {"scope": {"exclusions": [42]}, "entries": []},
    }

    # Act.
    result = run_diff(json.dumps(payload).encode())

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"baseline-diff:")
    assert b"exclusions" in result.stderr


def test_a_current_section_missing_scope_fails_loudly() -> None:
    # Arrange — issue #27: a raw, unfiltered walk from templates/manifest.php
    # never carries a "scope" key, unlike scripts/filter_manifest.py's output.
    # Feeding that raw walk straight in as "current" (skipping the local filter
    # helper) must not be silently read as an empty exclusion set — it must
    # fail loudly, since that is the only mechanical proof the filter ran.
    payload = {
        "baseline": {"scope": {"exclusions": []}, "entries": []},
        "current": {"entries": [entry("wp-content/plugins/acme/acme.php", 2000, 1700000000)]},
    }

    # Act.
    result = run_diff(json.dumps(payload).encode())

    # Assert — a loud exit naming the missing scope, not a silent empty-scope
    # default and not a partial document.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"baseline-diff:")
    assert b"scope" in result.stderr


def test_a_current_section_with_an_explicit_empty_scope_behaves_as_today() -> None:
    # Arrange — the current side legitimately carries "scope": {"exclusions": []}
    # when nothing is excluded this run; presence of the key is what matters,
    # not whether the exclusion list inside it happens to be empty.
    payload = {
        "baseline": {"scope": {"exclusions": []}, "entries": []},
        "current": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-content/plugins/acme/acme.php", 2000, 1700000000)],
        },
    }

    # Act.
    result = run_on(payload)

    # Assert — an explicit empty scope is accepted and diffs exactly as before.
    assert result["new_or_changed"] == ["wp-content/plugins/acme/acme.php"]
    assert result["production_deleted"] == []


def test_a_baseline_section_missing_scope_still_defaults_to_empty() -> None:
    # Arrange — the clone case: no prior baseline exists, so a stored baseline
    # document without a "scope" key is legitimate and must keep defaulting to
    # an empty exclusion set, unlike the current side.
    payload = {
        "baseline": {"entries": []},
        "current": {
            "scope": {"exclusions": []},
            "entries": [entry("wp-content/plugins/acme/acme.php", 2000, 1700000000)],
        },
    }

    # Act.
    result = run_on(payload)

    # Assert — the run succeeds, treating the baseline as empty rather than
    # rejecting it for the missing key.
    assert result["new_or_changed"] == ["wp-content/plugins/acme/acme.php"]
    assert result["production_deleted"] == []
