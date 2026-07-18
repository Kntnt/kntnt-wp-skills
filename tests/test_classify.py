# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Behavioural tests for the classifiers-and-derivations helper CLI.

The helper is the deterministic seam that turns the canonical discovery document
into recommendation inputs: the wp-config define classification, the table
full/empty classification, the deterministic blob heuristic, the thumbnail
exclude-set, and the local project-name derivation. Every test exercises that
seam through the real command — a canonical discovery document in as JSON on
stdin, the classifications out as JSON on stdout — and never reaches into the
helper's internals.

The canonical fixtures under ``fixtures/classify-*.json`` are shaped exactly like
``scripts/discovery.py``'s output, and the representative site is additionally
piped through the real ``discovery.py`` so the classifier is anchored to the
document it actually consumes rather than a hand-authored guess. No test touches
a real site.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "classify.py"
DISCOVERY = Path(__file__).resolve().parent.parent / "scripts" / "discovery.py"


def run_classify(raw: bytes) -> subprocess.CompletedProcess[bytes]:
    """Run the classifier with ``raw`` on stdin and capture its result."""

    return subprocess.run([sys.executable, str(SCRIPT)], input=raw, capture_output=True)


def classify_document(document: dict[str, Any]) -> dict[str, Any]:
    """Serialise an in-memory canonical document through the classifier and
    return the parsed classifications, asserting the run succeeded."""

    result = run_classify(json.dumps(document).encode())
    assert result.returncode == 0, result.stderr.decode()
    classifications: dict[str, Any] = json.loads(result.stdout)
    return classifications


def classify_fixture(fixture: str) -> dict[str, Any]:
    """Run the classifier on a named canonical-document fixture and return the
    parsed classifications."""

    result = run_classify((FIXTURES / fixture).read_bytes())
    assert result.returncode == 0, result.stderr.decode()
    classifications: dict[str, Any] = json.loads(result.stdout)
    return classifications


def classify_through_discovery(raw_fixture: str) -> dict[str, Any]:
    """Pipe a raw discovery fixture through the real ``discovery.py`` and then the
    classifier, so the classifier is exercised against the canonical document the
    engine actually produces — not a hand-authored stand-in."""

    document = subprocess.run(
        [sys.executable, str(DISCOVERY)],
        input=(FIXTURES / raw_fixture).read_bytes(),
        capture_output=True,
    )
    assert document.returncode == 0, document.stderr.decode()
    result = run_classify(document.stdout)
    assert result.returncode == 0, result.stderr.decode()
    classifications: dict[str, Any] = json.loads(result.stdout)
    return classifications


def excluded_classes(classifications: dict[str, Any]) -> dict[str, str]:
    """Reduce the auto-excluded defines to a name -> class map, the shape the
    define-classification assertions read."""

    return {
        entry["name"]: entry["class"]
        for entry in classifications["defines"]["auto_excluded"]
    }


def portable_names(classifications: dict[str, Any]) -> set[str]:
    """Reduce the offered defines to the set of their names."""

    return {entry["name"] for entry in classifications["defines"]["portable"]}


# --- Define classifier -------------------------------------------------------


def test_credential_defines_are_auto_excluded() -> None:
    # Arrange & Act.
    excluded = excluded_classes(classify_fixture("classify-full-site.json"))

    # Assert — every database credential is auto-excluded as the credentials
    # class (the local DDEV site has its own, so production's would mis-key it).
    for name in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_CHARSET", "DB_COLLATE"):
        assert excluded.get(name) == "credentials", name


def test_auth_key_salt_and_nonce_defines_are_auto_excluded() -> None:
    # Arrange & Act.
    excluded = excluded_classes(classify_fixture("classify-full-site.json"))

    # Assert — production auth keys, salts, and nonces never come down.
    for name in (
        "AUTH_KEY",
        "SECURE_AUTH_KEY",
        "LOGGED_IN_KEY",
        "NONCE_KEY",
        "AUTH_SALT",
        "SECURE_AUTH_SALT",
        "LOGGED_IN_SALT",
        "NONCE_SALT",
    ):
        assert excluded.get(name) == "salts_nonces", name


def test_a_custom_salt_or_nonce_define_is_auto_excluded_by_pattern() -> None:
    # Arrange — a plugin-defined salt and nonce that are not the eight WordPress
    # constants must still be caught by the *_SALT / NONCE_* pattern.
    document = {"defines": [
        {"name": "MY_PLUGIN_SALT", "value": "x"},
        {"name": "NONCE_CUSTOM", "value": "y"},
    ]}

    # Act.
    excluded = excluded_classes(classify_document(document))

    # Assert.
    assert excluded.get("MY_PLUGIN_SALT") == "salts_nonces"
    assert excluded.get("NONCE_CUSTOM") == "salts_nonces"


def test_domain_and_path_defines_are_auto_excluded() -> None:
    # Arrange & Act.
    excluded = excluded_classes(classify_fixture("classify-full-site.json"))

    # Assert — domain and path constants belong to production's layout, not the
    # local copy's.
    for name in ("WP_HOME", "WP_SITEURL", "WP_CONTENT_DIR", "WP_CONTENT_URL", "ABSPATH"):
        assert excluded.get(name) == "domain_paths", name


def test_infrastructure_defines_are_auto_excluded() -> None:
    # Arrange & Act.
    excluded = excluded_classes(classify_fixture("classify-full-site.json"))

    # Assert — cache toggles, cache-server hosts, and cron disabling are
    # infrastructure the local copy must not inherit.
    assert excluded.get("WP_CACHE") == "infrastructure"
    assert excluded.get("DISABLE_WP_CRON") == "infrastructure"
    assert excluded.get("WP_REDIS_HOST") == "infrastructure"


def test_plugin_behaviour_defines_are_offered() -> None:
    # Arrange & Act.
    classifications = classify_fixture("classify-full-site.json")

    # Assert — the remaining plugin/behaviour defines are offered at the gate,
    # and none of them leaked into the auto-excluded set.
    offered = portable_names(classifications)
    assert offered == {"WP_MEMORY_LIMIT", "WP_MAX_MEMORY_LIMIT", "WP_DEBUG", "FS_METHOD"}
    for name in offered:
        assert name not in excluded_classes(classifications)


def test_offered_define_carries_its_value_for_the_marked_block() -> None:
    # Arrange & Act — a portable define is written verbatim into the marked block,
    # so its value must survive classification.
    portable = classify_fixture("classify-full-site.json")["defines"]["portable"]

    # Assert.
    by_name = {entry["name"]: entry.get("value") for entry in portable}
    assert by_name["WP_MEMORY_LIMIT"] == "256M"


def test_every_define_is_classified_exactly_once() -> None:
    # Arrange — the fixture carries 26 defines.
    classifications = classify_fixture("classify-full-site.json")

    # Act.
    offered = portable_names(classifications)
    excluded = set(excluded_classes(classifications))

    # Assert — offered and excluded partition the input with no overlap and no
    # loss (a define is either ported or dropped, never both, never neither).
    assert offered.isdisjoint(excluded)
    assert len(offered) + len(excluded) == 26


def test_secret_define_values_never_appear_in_the_output() -> None:
    # Arrange — DB_PASSWORD carries a unique sentinel; auto-excluded defines are
    # dropped, never written, so no secret value may ride into model context.
    sentinel = "PW-NEVER-LEAK-4c7a"

    # Act.
    result = run_classify((FIXTURES / "classify-full-site.json").read_bytes())

    # Assert.
    assert result.returncode == 0, result.stderr.decode()
    assert sentinel.encode() not in result.stdout


# --- Table classifier --------------------------------------------------------


def test_operational_tables_are_classified_empty_with_their_category() -> None:
    # Arrange & Act.
    empty = classify_fixture("classify-full-site.json")["tables"]["empty"]

    # Assert — each operational table is carried empty and tagged with the
    # category that earned it the recommendation.
    by_name = {entry["name"]: entry["category"] for entry in empty}
    assert by_name.get("wp_independent_analytics_pages") == "analytics"
    assert by_name.get("wp_rcb_consent") == "cookie_consent"
    assert by_name.get("wp_fsmpt_email_logs") == "email_log"
    assert by_name.get("wp_relevanssi") == "search_index"


def test_content_tables_are_classified_full() -> None:
    # Arrange & Act.
    full = classify_fixture("classify-full-site.json")["tables"]["full"]

    # Assert — content, config, and user tables keep their data.
    for name in ("wp_posts", "wp_postmeta", "wp_options", "wp_users"):
        assert name in full


def test_table_classification_respects_a_non_default_prefix() -> None:
    # Arrange & Act — the operational match is on the name *after* the prefix, so
    # a non-default prefix must not hide an operational table nor empty a content
    # one.
    tables = classify_fixture("classify-custom-prefix.json")["tables"]

    # Assert.
    assert {"name": "site7_relevanssi", "category": "search_index"} in tables["empty"]
    assert "site7_posts" in tables["full"]
    assert "site7_options" in tables["full"]


# --- Blob heuristic ----------------------------------------------------------


def test_a_heavy_outlier_subdirectory_is_flagged() -> None:
    # Arrange & Act.
    flagged = classify_fixture("classify-full-site.json")["blobs"]["flagged"]

    # Assert — the multi-gigabyte gallery stands out and is offered for exclusion.
    paths = {entry["path"] for entry in flagged}
    assert "galleries" in paths


def test_ordinary_subdirectories_are_not_flagged() -> None:
    # Arrange & Act.
    flagged = classify_fixture("classify-full-site.json")["blobs"]["flagged"]

    # Assert — the year directories are not heavy outliers.
    paths = {entry["path"] for entry in flagged}
    assert "2024" not in paths
    assert "2023" not in paths


def test_the_blob_heuristic_is_deterministic() -> None:
    # Arrange — the same fixture, classified twice.
    first = classify_fixture("classify-full-site.json")["blobs"]
    second = classify_fixture("classify-full-site.json")["blobs"]

    # Assert — identical flags out; nothing sampled or randomised.
    assert first == second


def test_a_large_subdirectory_below_the_floor_is_not_flagged() -> None:
    # Arrange — one subdirectory dwarfs the others by ratio but sits below the
    # absolute floor, so it is not worth a gate.
    document = {"uploads": {"subdirectories": [
        {"path": "2024", "size_bytes": 209715200},
        {"path": "2023", "size_bytes": 104857600},
        {"path": "2022", "size_bytes": 943718400},
    ]}}

    # Act.
    flagged = classify_document(document)["blobs"]["flagged"]

    # Assert — the absolute floor keeps a sub-gigabyte outlier off the list.
    assert flagged == []


# --- Thumbnail exclude-set ---------------------------------------------------


def test_registered_derivatives_are_excluded() -> None:
    # Arrange & Act — the representative site through the real discovery helper.
    exclude = set(classify_through_discovery("representative-site.json")["thumbnails"]["exclude"])

    # Assert — exactly the DB-known generated sizes, resolved beside their
    # original.
    assert exclude == {
        "2024/05/banner-150x150.jpg",
        "2024/05/banner-300x200.jpg",
        "2024/05/banner-1024x683.jpg",
        "2024/05/banner-1920x1080-150x150.jpg",
    }


def test_registered_originals_are_kept() -> None:
    # Arrange & Act.
    exclude = set(classify_through_discovery("representative-site.json")["thumbnails"]["exclude"])

    # Assert — an original named like a size (banner-1920x1080.jpg) is kept,
    # because it is _wp_attached_file, not a derivative (ADR-0011).
    assert "2024/05/banner.jpg" not in exclude
    assert "2024/05/banner-1920x1080.jpg" not in exclude


def test_a_same_named_original_is_kept_while_its_derivatives_are_excluded() -> None:
    # Arrange & Act — photo-300x200.jpg is one attachment's registered derivative
    # *and* another attachment's own original in the same directory.
    exclude = set(classify_fixture("classify-thumbnail-collision.json")["thumbnails"]["exclude"])

    # Assert — the original wins the collision and is kept, while every genuine
    # derivative (including the colliding one's own children) is excluded.
    assert "2020/01/photo-300x200.jpg" not in exclude
    assert "2020/01/photo.jpg" not in exclude
    assert exclude == {
        "2020/01/photo-1024x768.jpg",
        "2020/01/photo-300x200-150x150.jpg",
    }


def test_a_side_loaded_thumbnail_named_file_is_never_excluded() -> None:
    # Arrange — a side-loaded file whose name matches the size pattern but that no
    # attachment registers; a filename heuristic would wrongly drop it.
    document = {"attachments": [
        {"id": 7, "file": "2021/03/holiday.jpg", "sizes": ["holiday-150x150.jpg"]},
    ]}

    # Act.
    exclude = set(classify_document(document)["thumbnails"]["exclude"])

    # Assert — only the registered derivative is excluded; the look-alike
    # side-load is carried whole because it cannot be regenerated.
    assert exclude == {"2021/03/holiday-150x150.jpg"}
    assert "2021/03/random-150x150.jpg" not in exclude


# --- Project-name derivation -------------------------------------------------


def test_project_name_reproduces_the_specification_example() -> None:
    # Arrange & Act — the specification's worked example.
    project = classify_fixture("classify-full-site.json")["project_name"]

    # Assert — scheme and www stripped, main label taken, DDEV hostname formed.
    assert project["name"] == "elfsborgsmarschen"
    assert project["ddev_url"] == "elfsborgsmarschen.ddev.site"


def test_project_name_sanitises_an_oddball_domain() -> None:
    # Arrange — an oddball production URL: uppercase scheme-relative host, an
    # underscore, and a trailing slash.
    cases = {
        "https://WWW.Example.COM/": "example",
        "http://Foo_Bar.io": "foo-bar",
        "https://my_site.example.org": "my-site",
        "https://-weird-.test": "weird",
    }

    # Act & Assert — every oddity sanitises to the scaffolder's charset.
    for url, expected in cases.items():
        project = classify_document({"site": {"home_url": url}})["project_name"]
        assert project["name"] == expected, url


# --- Whole-document contract -------------------------------------------------


def test_canonical_document_in_yields_every_classification() -> None:
    # Arrange & Act — the representative site through the real discovery helper.
    classifications = classify_through_discovery("representative-site.json")

    # Assert — one call over the canonical document produces every recommendation
    # input the engine needs.
    assert classifications["project_name"]["name"] == "example"
    assert {entry["path"] for entry in classifications["blobs"]["flagged"]} == {"galleries"}
    assert "2024/05/banner-150x150.jpg" in classifications["thumbnails"]["exclude"]
    assert "wp_posts" in classifications["tables"]["full"]
    assert classifications["tables"]["empty"] == []


def test_malformed_input_fails_loudly() -> None:
    # Arrange — input that is not JSON at all.
    # Act.
    result = run_classify(b"this is not json")

    # Assert — a non-zero exit and a `classify:` diagnostic, never a half-built
    # document on stdout.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"classify:")
