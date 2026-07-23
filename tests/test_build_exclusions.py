# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Behavioural tests for the exclusion-set assembler CLI.

The assembler (``scripts/build_exclusions.py``) is the deterministic seam issue
#35 introduces: the one place the resolved exclusion set is built, so the
extraction selection (clone §5) and the baseline manifest (clone §9.12, pull's
diff) can never assemble it even slightly differently and poison the deletion
diff. It reads the classifications (``classify.py``'s ``thumbnails.exclude``,
``blobs.flagged``, and ``uploads_prefix``) and the resolved plan
(``resolve_plan.py``'s decisions) as one JSON object on stdin, and writes the
complete, anchored, deduped exclusion prefix list on stdout as
``{"exclusions": [...]}`` — exactly the shape ``filter_manifest.py`` consumes.

The canonical always-excluded set lives once, as the module constant
:data:`build_exclusions.ALWAYS_EXCLUDED`; these tests pin its contents so no
prose reference can drift from it, and pin the assembler's output for a
representative classification-plus-plan input so the two consumers provably
agree.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import build_exclusions

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_exclusions.py"


def run_build(payload: Any) -> subprocess.CompletedProcess[bytes]:
    """Run the assembler with ``payload`` as JSON on stdin and capture its result."""

    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload).encode(),
        capture_output=True,
    )


def build(payload: Any) -> list[str]:
    """Run the assembler and return the parsed exclusion list, asserting success."""

    result = run_build(payload)
    assert result.returncode == 0, result.stderr.decode()
    document: dict[str, Any] = json.loads(result.stdout)
    return document["exclusions"]


def make_payload(
    *,
    thumbnails: list[str] | None = None,
    flagged: list[dict[str, Any]] | None = None,
    uploads_prefix: str = "wp-content/uploads",
    decisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Assemble a representative ``{classifications, plan}`` envelope, defaulting
    every decision to its recommended value (thumbnails and blobs excluded, media
    included) so a test only states the knob it varies."""

    resolved = {
        "generated_thumbnails": "exclude",
        "heavy_blobs": "exclude",
        "media_originals": "include",
        **(decisions or {}),
    }
    return {
        "classifications": {
            "thumbnails": {
                "exclude": thumbnails
                if thumbnails is not None
                else ["wp-content/uploads/2024/05/banner-300x200.jpg"]
            },
            "blobs": {
                "flagged": flagged
                if flagged is not None
                else [{"path": "wp-content/uploads/galleries", "size_bytes": 1}]
            },
            "uploads_prefix": uploads_prefix,
        },
        "plan": {
            "decisions": [
                {"id": key, "value": value} for key, value in resolved.items()
            ]
        },
    }


# --- The canonical constant ----------------------------------------------------


def test_always_excluded_covers_the_documented_categories() -> None:
    # Arrange / Act — the single source of truth for the always-excluded paths.
    always = set(build_exclusions.ALWAYS_EXCLUDED)

    # Assert — the configuration file, the drop-ins under wp-content/, the debug
    # log, the cache dir, and the upgrade dirs the §5 prose enumerates, each
    # anchored at the WordPress root.
    assert "wp-config.php" in always
    assert "wp-content/object-cache.php" in always
    assert "wp-content/advanced-cache.php" in always
    assert "wp-content/db.php" in always
    assert "wp-content/maintenance.php" in always
    assert "wp-content/debug.log" in always
    assert "wp-content/cache" in always
    assert "wp-content/upgrade" in always
    assert "wp-content/upgrade-temp-backup" in always


def test_always_excluded_pins_its_exact_contents() -> None:
    # Assert — the exact always-excluded set, so a stray, typo'd, or dropped entry
    # reddens here rather than silently changing what every run excludes. When
    # #36 (credential patterns) or #37 (core) extend the constant, this literal is
    # updated in lockstep — the single place the set's contents are pinned.
    assert set(build_exclusions.ALWAYS_EXCLUDED) == {
        "wp-config.php",
        "wp-content/advanced-cache.php",
        "wp-content/object-cache.php",
        "wp-content/db.php",
        "wp-content/db-error.php",
        "wp-content/install.php",
        "wp-content/maintenance.php",
        "wp-content/php-error.php",
        "wp-content/fatal-error-handler.php",
        "wp-content/sunrise.php",
        "wp-content/blog-deleted.php",
        "wp-content/blog-inactive.php",
        "wp-content/blog-suspended.php",
        "wp-content/debug.log",
        "wp-content/cache",
        "wp-content/upgrade",
        "wp-content/upgrade-temp-backup",
    }
    # No duplicate entries hide behind the set comparison above.
    assert len(build_exclusions.ALWAYS_EXCLUDED) == len(set(build_exclusions.ALWAYS_EXCLUDED))


def test_always_excluded_is_anchored_and_normalised() -> None:
    # Assert — every always-excluded entry is a relative, root-anchored prefix
    # with no leading or trailing slash, the one spelling every consumer matches.
    for prefix in build_exclusions.ALWAYS_EXCLUDED:
        assert not prefix.startswith("/"), prefix
        assert not prefix.endswith("/"), prefix


# --- The assembled set ---------------------------------------------------------


def test_the_default_plan_excludes_thumbnails_and_blobs_but_not_media() -> None:
    # Act — the recommended defaults: thumbnails and heavy blobs excluded, media
    # originals included.
    exclusions = set(build(make_payload()))

    # Assert — the always-excluded constant, plus the DB-known thumbnails and the
    # flagged heavy blobs; the uploads tree itself is not excluded.
    assert set(build_exclusions.ALWAYS_EXCLUDED) <= exclusions
    assert "wp-content/uploads/2024/05/banner-300x200.jpg" in exclusions
    assert "wp-content/uploads/galleries" in exclusions
    assert "wp-content/uploads" not in exclusions


def test_excluding_media_adds_the_uploads_prefix() -> None:
    # Act — --exclude-media pins media_originals to exclude.
    exclusions = set(build(make_payload(decisions={"media_originals": "exclude"})))

    # Assert — the whole uploads tree is anchored into the set.
    assert "wp-content/uploads" in exclusions


def test_including_blobs_omits_the_flagged_blobs() -> None:
    # Act — --include-blobs pins heavy_blobs to include.
    exclusions = set(build(make_payload(decisions={"heavy_blobs": "include"})))

    # Assert — the flagged blob path is not excluded, but the always-excluded set
    # still is.
    assert "wp-content/uploads/galleries" not in exclusions
    assert set(build_exclusions.ALWAYS_EXCLUDED) <= exclusions


def test_including_thumbnails_omits_the_exclude_set() -> None:
    # Act — a plan that resolves generated_thumbnails to include.
    exclusions = set(
        build(make_payload(decisions={"generated_thumbnails": "include"}))
    )

    # Assert — the DB-known thumbnail derivative is carried, not excluded.
    assert "wp-content/uploads/2024/05/banner-300x200.jpg" not in exclusions


def test_the_set_is_sorted_deduped_and_trailing_slash_normalised() -> None:
    # Arrange — a classification that repeats a path and spells one with a
    # trailing slash, the two shapes a hand-assembler would let diverge.
    payload = make_payload(
        thumbnails=[
            "wp-content/uploads/a-150x150.jpg",
            "wp-content/uploads/a-150x150.jpg",
        ],
        flagged=[{"path": "wp-content/uploads/galleries/", "size_bytes": 1}],
    )

    # Act.
    exclusions = build(payload)

    # Assert — sorted, no duplicates, no trailing slash.
    assert exclusions == sorted(exclusions)
    assert len(exclusions) == len(set(exclusions))
    assert "wp-content/uploads/galleries" in exclusions
    assert "wp-content/uploads/galleries/" not in exclusions


def test_the_set_is_never_empty() -> None:
    # Arrange — everything the operator could include is included, and the site
    # has no thumbnails or blobs at all.
    payload = make_payload(
        thumbnails=[],
        flagged=[],
        decisions={
            "generated_thumbnails": "include",
            "heavy_blobs": "include",
            "media_originals": "include",
        },
    )

    # Act.
    exclusions = build(payload)

    # Assert — the always-excluded constant guarantees a non-empty set, so
    # filter_manifest.py's "a real resolved exclusion set is never empty" contract
    # holds without the assembler ever emitting an unresolved-looking [].
    assert exclusions == sorted(build_exclusions.ALWAYS_EXCLUDED)
    assert exclusions


def test_selection_and_baseline_share_one_byte_identical_set() -> None:
    # Arrange — the same classifications and plan the clone §5 selection and the
    # §9.12 baseline (and pull's diff) each feed the assembler.
    payload = make_payload()

    # Act — two independent runs, standing in for the two consumers.
    first = run_build(payload)
    second = run_build(payload)

    # Assert — byte-identical output, the AC that the deletion diff is never
    # poisoned by a divergently-assembled set.
    assert first.returncode == 0
    assert first.stdout == second.stdout


# --- Fail-loud contract --------------------------------------------------------


def test_a_non_object_payload_fails_loud() -> None:
    result = run_build(["not", "an", "object"])
    assert result.returncode == 1
    assert b"build_exclusions:" in result.stderr


def test_invalid_json_fails_loud() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], input=b"{not json", capture_output=True
    )
    assert result.returncode == 1
    assert b"build_exclusions:" in result.stderr


def test_excluding_media_without_an_uploads_prefix_fails_loud() -> None:
    # Arrange — a plan that excludes media, but classifications missing the
    # uploads_prefix the exclusion must be anchored on.
    payload = make_payload(decisions={"media_originals": "exclude"})
    del payload["classifications"]["uploads_prefix"]

    # Act.
    result = run_build(payload)

    # Assert — a loud abort rather than a mis-anchored or dropped media exclusion.
    assert result.returncode == 1
    assert b"uploads_prefix" in result.stderr


def test_a_missing_decision_fails_loud() -> None:
    # Arrange — a plan whose decisions omit generated_thumbnails, one of the three
    # gates the set turns on.
    payload = make_payload()
    payload["plan"]["decisions"] = [
        entry
        for entry in payload["plan"]["decisions"]
        if entry["id"] != "generated_thumbnails"
    ]

    # Act.
    result = run_build(payload)

    # Assert — an unresolved plan is malformed input, not a silent default.
    assert result.returncode == 1
    assert b"generated_thumbnails" in result.stderr
