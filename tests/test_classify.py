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

The canonical fixtures under ``fixtures/classify-*.json`` are shaped like
``scripts/discovery.py``'s output for the sections each exercises (tables, blobs,
the thumbnail exclude-set, the project name). The headline define classification
and the thumbnail exclude-set are additionally driven end-to-end through the real
``discovery.py`` against the representative raw fixture, so those two are anchored
to the canonical document discovery actually produces — the ``defines`` array
included — rather than a hand-authored stand-in the pipeline never emits. No test
touches a real site.
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
BASELINE_DIFF = Path(__file__).resolve().parent.parent / "scripts" / "baseline_diff.py"


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
    # Arrange & Act — the representative site through the real discovery helper, so
    # the define classification is exercised against the canonical document
    # discovery actually produces.
    excluded = excluded_classes(classify_through_discovery("representative-site.json"))

    # Assert — every database credential is auto-excluded as the credentials
    # class (the local DDEV site has its own, so production's would mis-key it).
    for name in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_CHARSET", "DB_COLLATE"):
        assert excluded.get(name) == "credentials", name


def test_auth_key_salt_and_nonce_defines_are_auto_excluded() -> None:
    # Arrange & Act.
    excluded = excluded_classes(classify_through_discovery("representative-site.json"))

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
    excluded = excluded_classes(classify_through_discovery("representative-site.json"))

    # Assert — domain and path constants belong to production's layout, not the
    # local copy's.
    for name in ("WP_HOME", "WP_SITEURL", "WP_CONTENT_DIR", "WP_CONTENT_URL", "ABSPATH"):
        assert excluded.get(name) == "domain_paths", name


def test_infrastructure_defines_are_auto_excluded() -> None:
    # Arrange & Act.
    excluded = excluded_classes(classify_through_discovery("representative-site.json"))

    # Assert — cache toggles, cache-server hosts, and cron disabling are
    # infrastructure the local copy must not inherit.
    assert excluded.get("WP_CACHE") == "infrastructure"
    assert excluded.get("DISABLE_WP_CRON") == "infrastructure"
    assert excluded.get("WP_REDIS_HOST") == "infrastructure"


def test_plugin_behaviour_defines_are_offered() -> None:
    # Arrange & Act.
    classifications = classify_through_discovery("representative-site.json")

    # Assert — the remaining plugin/behaviour defines are offered at the gate,
    # and none of them leaked into the auto-excluded set.
    offered = portable_names(classifications)
    assert offered == {"WP_MEMORY_LIMIT", "WP_MAX_MEMORY_LIMIT", "WP_DEBUG", "FS_METHOD"}
    for name in offered:
        assert name not in excluded_classes(classifications)


def test_offered_define_carries_its_value_for_the_marked_block() -> None:
    # Arrange & Act — a portable define is written verbatim into the marked block,
    # so its value must survive classification through the real pipeline.
    portable = classify_through_discovery("representative-site.json")["defines"]["portable"]

    # Assert.
    by_name = {entry["name"]: entry.get("value") for entry in portable}
    assert by_name["WP_MEMORY_LIMIT"] == "256M"


def test_every_define_is_classified_exactly_once() -> None:
    # Arrange — the representative site's wp-config carries 26 defines.
    classifications = classify_through_discovery("representative-site.json")

    # Act.
    offered = portable_names(classifications)
    excluded = set(excluded_classes(classifications))

    # Assert — offered and excluded partition the input with no overlap and no
    # loss (a define is either ported or dropped, never both, never neither).
    assert offered.isdisjoint(excluded)
    assert len(offered) + len(excluded) == 26


def test_secret_define_values_never_appear_in_the_output() -> None:
    # Arrange — an auto-excluded define carrying a secret sentinel value, fed
    # straight to the classifier: its own contract is that an auto-excluded define
    # is dropped to name and class, so no secret value may ride into model
    # context even if one reaches it (defence in depth behind discovery's redaction
    # of the same secret at the boundary).
    sentinel = "PW-NEVER-LEAK-4c7a"
    document = {"defines": [
        {"name": "DB_PASSWORD", "value": sentinel},
        {"name": "WP_MEMORY_LIMIT", "value": "256M"},
    ]}

    # Act.
    result = run_classify(json.dumps(document).encode())

    # Assert — the run succeeds, the portable value survives, and the secret is
    # nowhere in the output.
    assert result.returncode == 0, result.stderr.decode()
    assert b"256M" in result.stdout
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


def test_a_form_submission_table_is_classified_under_user_submissions() -> None:
    # Arrange — a discovery document naming a Weforms/WS Form submission table and
    # its meta sibling. Form-entry tables are neither regenerable nor operational
    # (real names, emails, messages) so they earn their own classification family,
    # distinct from the four silently-emptied operational categories (ADR-0014).
    document = {"database": {
        "table_prefix": "wp_",
        "tables": ["wp_posts", "wp_wsf_submit", "wp_wsf_submit_meta"],
    }}

    # Act.
    tables = classify_document(document)["tables"]

    # Assert — tagged under the user_submissions category, not any operational
    # one, while ordinary content stays full.
    by_name = {entry["name"]: entry["category"] for entry in tables["empty"]}
    assert by_name.get("wp_wsf_submit") == "user_submissions"
    assert by_name.get("wp_wsf_submit_meta") == "user_submissions"
    assert "wp_posts" in tables["full"]


def test_every_documented_form_plugin_family_is_classified_under_user_submissions() -> None:
    # Arrange — one representative table per form plugin the issue's initial
    # pattern set names: WS Form, Fluent Forms, Formidable, WPForms, Gravity Forms.
    names = [
        "wp_wsf_submit",
        "wp_wsf_submit_meta",
        "wp_fluentform_submissions",
        "wp_fluentform_submission_meta",
        "wp_fluentform_entry_details",
        "wp_frm_items",
        "wp_frm_item_metas",
        "wp_wpforms_entries",
        "wp_wpforms_entry_meta",
        "wp_wpforms_entry_fields",
        "wp_gf_entry",
        "wp_gf_entry_meta",
        "wp_gf_entry_notes",
    ]
    document = {"database": {"table_prefix": "wp_", "tables": names}}

    # Act.
    tables = classify_document(document)["tables"]

    # Assert — every one of them lands in user_submissions, none in full.
    by_name = {entry["name"]: entry["category"] for entry in tables["empty"]}
    for name in names:
        assert by_name.get(name) == "user_submissions", name
    assert tables["full"] == []


def test_user_submission_classification_respects_a_non_default_prefix() -> None:
    # Arrange — the match is on the name after the prefix, so a non-default
    # prefix must not hide a form-submission table.
    document = {"database": {
        "table_prefix": "site7_",
        "tables": ["site7_wsf_submit", "site7_posts"],
    }}

    # Act.
    tables = classify_document(document)["tables"]

    # Assert.
    assert {"name": "site7_wsf_submit", "category": "user_submissions"} in tables["empty"]
    assert "site7_posts" in tables["full"]


def test_every_table_is_classified_not_only_the_report_subset() -> None:
    # Arrange — a site with more tables than the heaviest-N report subset: the full
    # enumeration 'tables' lists 25, while 'top_tables' (the report artifact the
    # operator's overview reads) carries only the heaviest 20. The classifier must
    # split the whole enumeration, or every table beyond the report subset is
    # silently dropped from the dump — the "all tables, always" cornerstone the
    # copy relies on so nothing ever hits a missing table (spec user story 16).
    all_tables = [f"wp_widget_{index:02d}" for index in range(25)]
    document = {"database": {
        "table_prefix": "wp_",
        "tables": all_tables,
        "top_tables": [{"name": name, "size_bytes": 1_000_000} for name in all_tables[:20]],
    }}

    # Act.
    tables = classify_document(document)["tables"]

    # Assert — the full/empty split together covers every one of the 25 tables,
    # not just the 20 the report subset carries.
    covered = set(tables["full"]) | {entry["name"] for entry in tables["empty"]}
    assert covered == set(all_tables)


# --- Blob heuristic ----------------------------------------------------------


def test_a_heavy_outlier_subdirectory_is_flagged() -> None:
    # Arrange & Act.
    flagged = classify_fixture("classify-full-site.json")["blobs"]["flagged"]

    # Assert — the multi-gigabyte gallery stands out and is offered for exclusion,
    # anchored at the WordPress root so the exclusion actually bites in tar and the
    # baseline diff (which both work in root-relative paths).
    paths = {entry["path"] for entry in flagged}
    assert "wp-content/uploads/galleries" in paths


def test_ordinary_subdirectories_are_not_flagged() -> None:
    # Arrange & Act.
    flagged = classify_fixture("classify-full-site.json")["blobs"]["flagged"]

    # Assert — the year directories are not heavy outliers.
    paths = {entry["path"] for entry in flagged}
    assert "wp-content/uploads/2024" not in paths
    assert "wp-content/uploads/2023" not in paths


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
    # original and anchored at the WordPress root (the exclusion set's one anchor,
    # shared with the pack tar and the baseline manifest).
    assert exclude == {
        "wp-content/uploads/2024/05/banner-150x150.jpg",
        "wp-content/uploads/2024/05/banner-300x200.jpg",
        "wp-content/uploads/2024/05/banner-1024x683.jpg",
        "wp-content/uploads/2024/05/banner-1920x1080-150x150.jpg",
    }


def test_registered_originals_are_kept() -> None:
    # Arrange & Act.
    exclude = set(classify_through_discovery("representative-site.json")["thumbnails"]["exclude"])

    # Assert — an original named like a size (banner-1920x1080.jpg) is kept,
    # because it is _wp_attached_file, not a derivative (ADR-0011).
    assert "wp-content/uploads/2024/05/banner.jpg" not in exclude
    assert "wp-content/uploads/2024/05/banner-1920x1080.jpg" not in exclude


def test_a_same_named_original_is_kept_while_its_derivatives_are_excluded() -> None:
    # Arrange & Act — photo-300x200.jpg is one attachment's registered derivative
    # *and* another attachment's own original in the same directory.
    exclude = set(classify_fixture("classify-thumbnail-collision.json")["thumbnails"]["exclude"])

    # Assert — the original wins the collision and is kept, while every genuine
    # derivative (including the colliding one's own children) is excluded, each
    # anchored at the WordPress root.
    assert "wp-content/uploads/2020/01/photo-300x200.jpg" not in exclude
    assert "wp-content/uploads/2020/01/photo.jpg" not in exclude
    assert exclude == {
        "wp-content/uploads/2020/01/photo-1024x768.jpg",
        "wp-content/uploads/2020/01/photo-300x200-150x150.jpg",
    }


def test_a_side_loaded_thumbnail_named_file_is_never_excluded() -> None:
    # Arrange — a side-loaded file whose name matches the size pattern but that no
    # attachment registers; a filename heuristic would wrongly drop it.
    document = {"attachments": [
        {"id": 7, "file": "2021/03/holiday.jpg", "sizes": ["holiday-150x150.jpg"]},
    ]}

    # Act.
    exclude = set(classify_document(document)["thumbnails"]["exclude"])

    # Assert — only the registered derivative is excluded (root-anchored); the
    # look-alike side-load is carried whole because it cannot be regenerated.
    assert exclude == {"wp-content/uploads/2021/03/holiday-150x150.jpg"}
    assert "wp-content/uploads/2021/03/random-150x150.jpg" not in exclude


# --- Exclusion-path anchoring ------------------------------------------------
#
# The exclusion set (flagged blobs and the thumbnail exclude-set) has exactly one
# consumer-facing anchor: WordPress-root-relative paths (e.g.
# "wp-content/uploads/gallery"). The pack script's `tar --exclude-from --anchored
# -C "$SOURCE_ROOT"` and the baseline manifest's root-relative entries both silently
# no-match anything spelled otherwise, so a producer that emitted uploads-relative
# or bare-basename paths would defeat the blob gate and corrupt the deletion diff
# with no test going red. These tests pin that anchor at the producer.


def test_the_exclusion_anchor_is_derived_from_a_custom_content_directory() -> None:
    # Arrange — a non-standard layout where the uploads directory sits under a
    # custom content directory, not the default wp-content/uploads. The anchor must
    # come from the document's own root_path and uploads_base, never a hard-coded
    # assumption, or the exclusion is mis-anchored on every non-default site.
    document = {
        "site": {
            "home_url": "https://example.test",
            "root_path": "/srv/app/",
            "uploads_base": "/srv/app/content/uploads",
        },
        "uploads": {"subdirectories": [
            {"path": "2023", "size_bytes": 104857600},
            {"path": "2024", "size_bytes": 104857600},
            {"path": "galleries", "size_bytes": 6442450944},
        ]},
        "attachments": [
            {"id": 1, "file": "2024/05/banner.jpg", "sizes": ["banner-150x150.jpg"]},
        ],
    }

    # Act.
    classifications = classify_document(document)

    # Assert — both producers anchor at "content/uploads" (uploads relative to the
    # site root), the exact prefix the derivation yields from the two paths.
    blob_paths = {entry["path"] for entry in classifications["blobs"]["flagged"]}
    assert blob_paths == {"content/uploads/galleries"}
    assert classifications["thumbnails"]["exclude"] == [
        "content/uploads/2024/05/banner-150x150.jpg"
    ]


def test_the_exclusion_anchor_defaults_to_the_standard_layout_when_paths_absent() -> None:
    # Arrange — a minimal or hand-authored document that omits the absolute
    # root_path and uploads_base. The classifier falls back to the standard
    # single-site location wp-content/uploads (the same layout manifest.php assumes),
    # so the anchor is still correct for the overwhelmingly common case.
    document = {
        "uploads": {"subdirectories": [
            {"path": "2023", "size_bytes": 104857600},
            {"path": "2024", "size_bytes": 104857600},
            {"path": "galleries", "size_bytes": 6442450944},
        ]},
        "attachments": [
            {"id": 1, "file": "2024/05/banner.jpg", "sizes": ["banner-150x150.jpg"]},
        ],
    }

    # Act.
    classifications = classify_document(document)

    # Assert.
    blob_paths = {entry["path"] for entry in classifications["blobs"]["flagged"]}
    assert blob_paths == {"wp-content/uploads/galleries"}
    assert classifications["thumbnails"]["exclude"] == [
        "wp-content/uploads/2024/05/banner-150x150.jpg"
    ]


def test_an_uploads_directory_outside_the_root_fails_loudly() -> None:
    # Arrange — an uploads_base that is not under root_path. The anchored-exclude
    # scheme cannot express such a layout as a root-relative prefix, so silently
    # emitting a wrong anchor is exactly the failure mode to avoid; it must fail
    # loudly with a `classify:` diagnostic instead.
    document = {
        "site": {
            "home_url": "https://example.test",
            "root_path": "/var/www/html/",
            "uploads_base": "/mnt/media/uploads",
        },
        "attachments": [
            {"id": 1, "file": "2024/05/banner.jpg", "sizes": ["banner-150x150.jpg"]},
        ],
    }

    # Act.
    result = run_classify(json.dumps(document).encode())

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"classify:")


def test_the_exclusion_set_actually_bites_in_the_baseline_diff() -> None:
    # Arrange — the seam the integration review flagged: classify PRODUCES the
    # exclusion set and baseline_diff CONSUMES it as the run's scope. Wire the real
    # producer output straight into the real consumer, so a future anchor drift on
    # either side reddens here rather than silently defeating the deletion rule.
    document = {
        "uploads": {"subdirectories": [
            {"path": "2023", "size_bytes": 104857600},
            {"path": "2024", "size_bytes": 104857600},
            {"path": "galleries", "size_bytes": 6442450944},
        ]},
        "attachments": [
            {"id": 1, "file": "2024/05/banner.jpg", "sizes": ["banner-150x150.jpg"]},
        ],
    }
    classifications = classify_document(document)
    exclusions = [entry["path"] for entry in classifications["blobs"]["flagged"]]
    exclusions += classifications["thumbnails"]["exclude"]

    # Act — a baseline holding a file inside the excluded gallery, an excluded
    # thumbnail, and a plain in-scope file, all now gone from production; the diff
    # runs under the exclusion set as this run's scope.
    diff_input = {
        "baseline": {"scope": {"exclusions": []}, "entries": [
            {"path": "wp-content/uploads/galleries/huge.jpg", "size": 1, "mtime": 1.0},
            {"path": "wp-content/uploads/2024/05/banner-150x150.jpg", "size": 1, "mtime": 1.0},
            {"path": "wp-content/uploads/2024/05/banner.jpg", "size": 1, "mtime": 1.0},
        ]},
        "current": {"scope": {"exclusions": exclusions}, "entries": []},
    }
    diff = subprocess.run(
        [sys.executable, str(BASELINE_DIFF)],
        input=json.dumps(diff_input).encode(),
        capture_output=True,
    )
    assert diff.returncode == 0, diff.stderr.decode()
    deleted = set(json.loads(diff.stdout)["production_deleted"])

    # Assert — the classifier's anchor matches the manifest's: the gallery file and
    # the excluded thumbnail are out of scope (protected from the deletion diff),
    # while the plain original is in scope and reported deleted.
    assert "wp-content/uploads/galleries/huge.jpg" not in deleted
    assert "wp-content/uploads/2024/05/banner-150x150.jpg" not in deleted
    assert "wp-content/uploads/2024/05/banner.jpg" in deleted


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


# --- Directory-name derivation ------------------------------------------------


def test_directory_name_and_project_name_reproduce_the_issue_example() -> None:
    # Arrange & Act — the issue's worked example (#11): the full host survives
    # for the clone directory, the sanitised main label survives for the DDEV
    # project.
    project = classify_document({"site": {"home_url": "https://www.smoltek.com/"}})[
        "project_name"
    ]

    # Assert — directory_name keeps `www.` and the dot; name is unchanged.
    assert project["directory_name"] == "www.smoltek.com"
    assert project["name"] == "smoltek"


def test_directory_name_keeps_a_plain_host_verbatim() -> None:
    # Arrange & Act — a bare host with no `www.` label and no path.
    project = classify_document({"site": {"home_url": "https://example.com"}})[
        "project_name"
    ]

    # Assert — the host survives unchanged; no sanitisation applies to it.
    assert project["directory_name"] == "example.com"


def test_directory_name_strips_scheme_userinfo_port_and_path_but_keeps_case() -> None:
    # Arrange — userinfo, a non-default port, a path and query, and mixed-case
    # labels: none of these belong in a directory name, but the case is the
    # operator's own, unlike the lowercase-and-sanitise project-name slug.
    cases = {
        "https://user:pass@WWW.Example.COM:8443/some/path?x=1": "WWW.Example.COM",
        "http://example.org:80/": "example.org",
        "www.smoltek.com": "www.smoltek.com",
    }

    # Act & Assert — only the bare host survives, verbatim, in every shape.
    for url, expected in cases.items():
        project = classify_document({"site": {"home_url": url}})["project_name"]
        assert project["directory_name"] == expected, url


def test_directory_name_keeps_an_idn_host_verbatim() -> None:
    # Arrange & Act — an internationalised domain name: unicode labels the
    # project-name sanitiser would mangle, but the directory name never does.
    project = classify_document(
        {"site": {"home_url": "https://www.xn--nxasmq6b.example"}}
    )["project_name"]

    # Assert — the punycode host passes through untouched.
    assert project["directory_name"] == "www.xn--nxasmq6b.example"


def test_directory_name_falls_back_when_no_host_survives() -> None:
    # Arrange & Act — an oddball URL that reduces to no host at all.
    project = classify_document({"site": {"home_url": "https:///no-host-here"}})[
        "project_name"
    ]

    # Assert — the same fallback the project-name slug uses when nothing
    # survives, so the confirm gate always has something to show and correct.
    assert project["directory_name"] == "site"


def test_directory_name_falls_back_on_a_path_traversal_host() -> None:
    # Arrange — URLs that reduce to the traversal-shaped hosts `.` and `..`: a
    # verbatim directory name here would flow unattended into `mkwp
    # --dirname=<...>` under `--yes` and resolve outside the operator's current
    # directory.
    cases = {
        "https://../x": "..",
        "https://./x": ".",
    }

    # Act & Assert — the path-safety floor rejects both, falling back to the
    # same oddball floor `derive_project_name` uses.
    for url, host in cases.items():
        project = classify_document({"site": {"home_url": url}})["project_name"]
        assert project["directory_name"] == "site", f"{url!r} reduced to {host!r}"


# --- Whole-document contract -------------------------------------------------


def test_canonical_document_in_yields_every_classification() -> None:
    # Arrange & Act — the representative site through the real discovery helper.
    classifications = classify_through_discovery("representative-site.json")

    # Assert — one call over the canonical document produces every recommendation
    # input the engine needs.
    assert classifications["project_name"]["name"] == "example"
    assert classifications["project_name"]["directory_name"] == "www.example.com"
    assert {entry["path"] for entry in classifications["blobs"]["flagged"]} == {
        "wp-content/uploads/galleries"
    }
    assert (
        "wp-content/uploads/2024/05/banner-150x150.jpg"
        in classifications["thumbnails"]["exclude"]
    )
    assert "wp_posts" in classifications["tables"]["full"]
    assert classifications["tables"]["empty"] == []
    assert "WP_MEMORY_LIMIT" in portable_names(classifications)
    assert excluded_classes(classifications).get("DB_HOST") == "credentials"


def test_malformed_input_fails_loudly() -> None:
    # Arrange — input that is not JSON at all.
    # Act.
    result = run_classify(b"this is not json")

    # Assert — a non-zero exit and a `classify:` diagnostic, never a half-built
    # document on stdout.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"classify:")


# --- Malformed inner records -------------------------------------------------


def test_a_malformed_define_record_fails_loudly() -> None:
    # Arrange — a define entry lacking its 'name'. It must earn the same loud
    # `classify:` diagnostic as a top-level shape error, not an uncaught KeyError
    # traceback (the classifier's fail-loud contract covers inner records too).
    document = {"defines": [{"value": "orphan"}]}

    # Act.
    result = run_classify(json.dumps(document).encode())

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"classify:")


def test_a_malformed_table_name_fails_loudly() -> None:
    # Arrange — a non-string element in the full table enumeration. It must earn
    # the same loud `classify:` diagnostic as any other malformed record, not an
    # uncaught traceback from the operational-pattern match.
    document = {"database": {"tables": [123]}}

    # Act.
    result = run_classify(json.dumps(document).encode())

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"classify:")


def test_a_malformed_attachment_record_fails_loudly() -> None:
    # Arrange — a non-object attachment element, which the raw discovery seam can
    # pass through unvalidated.
    document = {"attachments": ["not-an-object"]}

    # Act.
    result = run_classify(json.dumps(document).encode())

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"classify:")


def test_a_blob_subdirectory_missing_its_size_fails_loudly() -> None:
    # Arrange — an uploads subdirectory element lacking its 'size_bytes'. The blob
    # heuristic reads that field directly, so without a per-element guard it raises
    # a raw KeyError; the fail-loud contract promises the same branded `classify:`
    # diagnostic here as for defines, tables, and attachments — the #3 -> #4 seam
    # hands these list elements through unvalidated.
    document = {"uploads": {"subdirectories": [{"path": "galleries"}]}}

    # Act.
    result = run_classify(json.dumps(document).encode())

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"classify:")


def test_a_non_object_blob_subdirectory_fails_loudly() -> None:
    # Arrange — a non-object subdirectory element the raw discovery seam can pass
    # through unvalidated; indexing 'size_bytes' into it raises a raw TypeError
    # without the branded per-element guard.
    document = {"uploads": {"subdirectories": ["not-an-object"]}}

    # Act.
    result = run_classify(json.dumps(document).encode())

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"classify:")


def test_a_non_string_thumbnail_size_fails_loudly() -> None:
    # Arrange — an attachment whose 'sizes' holds a non-string element. The
    # exclude-set joins each size onto the original's directory, so a non-string
    # size raises a raw TypeError from the path join without a per-element guard.
    document = {"attachments": [{"file": "2021/03/holiday.jpg", "sizes": [123]}]}

    # Act.
    result = run_classify(json.dumps(document).encode())

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"classify:")
