# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Behavioural tests for the discovery assembler CLI.

The helper is the assembler seam of two-phase discovery: the four Extractor REST
sources — the ``environment`` response, the ``tables`` response, the flattened
``files`` manifest, and the client-parsed ``bootstrap`` signals — go in as one
JSON object on stdin, the canonical discovery document comes out on stdout, and
malformed input fails loudly with a non-zero exit. Every test exercises that seam
through the real command — fixtures in, observable output out — and never reaches
into the helper's internals. The fixtures under ``fixtures/`` are what the two-
phase discovery would assemble for a given site; no test touches a real site.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "discovery.py"


def run_discovery(raw: bytes) -> subprocess.CompletedProcess[bytes]:
    """Run the helper with ``raw`` on stdin and capture its result."""

    return subprocess.run([sys.executable, str(SCRIPT)], input=raw, capture_output=True)


def document_for(fixture: str) -> dict[str, Any]:
    """Run the helper on a named fixture and return the parsed canonical
    document, asserting the run succeeded."""

    result = run_discovery((FIXTURES / fixture).read_bytes())
    assert result.returncode == 0, result.stderr.decode()
    document: dict[str, Any] = json.loads(result.stdout)
    return document


def load_fixture(fixture: str) -> dict[str, Any]:
    """Load a named fixture as a mutable dict, so a test can perturb a single
    field and feed the perturbed payload back through the helper."""

    payload: dict[str, Any] = json.loads((FIXTURES / fixture).read_text())
    return payload


def run_on(payload: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    """Run the helper on an in-memory payload, serialising it to stdin — the same
    seam as a fixture file, but for inputs a test constructs on the fly."""

    return run_discovery(json.dumps(payload).encode())


def test_valid_discovery_output_is_parsed_into_a_canonical_document() -> None:
    # Arrange & Act.
    document = document_for("representative-site.json")

    # Assert — the document carries the sections every later recommendation
    # derives from, keyed under a stable schema version.
    assert document["schema_version"] == 2
    assert document["site"]["home_url"] == "https://www.example.com"
    assert document["site"]["core_version"] == "6.5.2"
    assert document["database"]["total_size_bytes"] == 268435456
    assert {"name": "wp_posts", "size_bytes": 104857600} in document["database"][
        "top_tables"
    ]
    subdirectory_paths = {
        entry["path"] for entry in document["uploads"]["subdirectories"]
    }
    assert {"2024", "2023", "galleries"} <= subdirectory_paths
    assert document["dropins"] == ["object-cache.php", "advanced-cache.php"]
    assert document["themes"] == ["astra", "twentytwentyfour"]


def test_the_canonical_document_carries_the_full_table_enumeration() -> None:
    # Arrange — the tables source enumerates every table with its size. The
    # canonical document must carry the complete enumeration so classification and
    # the dump cover every table (spec: all tables, always), heaviest first.
    payload = load_fixture("representative-site.json")
    payload["tables"]["tables"] = [
        {"name": "wp_posts", "rows": 10, "bytes": 4},
        {"name": "wp_options", "rows": 10, "bytes": 3},
        {"name": "wp_users", "rows": 10, "bytes": 2},
        {"name": "wp_extra_plugin_state", "rows": 10, "bytes": 1},
    ]

    # Act.
    result = run_on(payload)
    assert result.returncode == 0, result.stderr.decode()
    database = json.loads(result.stdout)["database"]

    # Assert — every table survives, ordered heaviest-first, distinct from the
    # capped heaviest-N report the document also carries.
    assert database["tables"] == [
        "wp_posts", "wp_options", "wp_users", "wp_extra_plugin_state",
    ]


def test_the_total_size_is_the_sum_of_every_table() -> None:
    # Arrange — the grand total is derived from the per-table byte sizes, never a
    # separately-reported figure that could drift from the enumeration.
    payload = load_fixture("representative-site.json")
    payload["tables"]["tables"] = [
        {"name": "wp_posts", "rows": 1, "bytes": 100},
        {"name": "wp_options", "rows": 1, "bytes": 25},
    ]

    # Act.
    database = json.loads(run_on(payload).stdout)["database"]

    # Assert.
    assert database["total_size_bytes"] == 125


def test_a_malformed_table_record_fails_loudly() -> None:
    # Arrange — a table record whose name is not a string is malformed and must
    # not ride into the document half-built.
    payload = load_fixture("representative-site.json")
    payload["tables"]["tables"] = [{"name": "wp_posts", "bytes": 1}, {"name": 42, "bytes": 1}]

    # Act.
    result = run_on(payload)

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"discovery:")
    assert b"tables" in result.stderr


def test_uploads_subdirectories_are_summed_from_the_file_manifest() -> None:
    # Arrange — several files under one uploads subdirectory must sum into one
    # subdirectory total (the blob heuristic's input), even when the site uses a
    # non-default content directory.
    payload = load_fixture("representative-site.json")
    payload["environment"]["wordpress"]["content_dir"] = "app"
    payload["environment"]["wordpress"]["uploads_dir"] = "app/uploads"
    payload["files"] = [
        {"path": "app/uploads/2024/a.jpg", "size": 100, "mtime": 1},
        {"path": "app/uploads/2024/b.jpg", "size": 50, "mtime": 1},
        {"path": "app/uploads/gallery/big.zip", "size": 900, "mtime": 1},
        {"path": "app/themes/ollie/style.css", "size": 10, "mtime": 1},
    ]

    # Act.
    document = json.loads(run_on(payload).stdout)

    # Assert — the two 2024 files sum, the gallery stands alone, and the theme is
    # found under the custom content dir.
    subdirectories = {
        entry["path"]: entry["size_bytes"]
        for entry in document["uploads"]["subdirectories"]
    }
    assert subdirectories == {"2024": 150, "gallery": 900}
    assert document["themes"] == ["ollie"]


def test_a_bare_file_directly_under_the_themes_prefix_is_not_reported_as_a_theme() -> None:
    # Arrange — an empty-directory guard file (index.php) sits directly under
    # wp-content/themes/ alongside a real theme directory. The manifest holds
    # files only, so the guard file's path segment ("index.php") looks exactly
    # like a theme's directory name unless directory-ness is judged by whether
    # the path continues past that segment.
    payload = load_fixture("representative-site.json")
    payload["files"] = [
        {"path": "wp-content/themes/index.php", "size": 0, "mtime": 1},
        {"path": "wp-content/themes/ollie/style.css", "size": 10, "mtime": 1},
    ]

    # Act.
    document = json.loads(run_on(payload).stdout)

    # Assert — only the real theme directory is reported; the guard file is not
    # mistaken for a theme.
    assert document["themes"] == ["ollie"]


def test_a_theme_directory_containing_a_single_file_still_counts_as_a_theme() -> None:
    # Arrange — a theme with exactly one file must still be recognised as a
    # directory (its path continues past the theme-name segment), not confused
    # with a bare file sitting directly at the themes prefix.
    payload = load_fixture("representative-site.json")
    payload["files"] = [
        {"path": "wp-content/themes/index.php", "size": 0, "mtime": 1},
        {"path": "wp-content/themes/minimal/style.css", "size": 5, "mtime": 1},
    ]

    # Act.
    document = json.loads(run_on(payload).stdout)

    # Assert.
    assert document["themes"] == ["minimal"]


def test_uploads_subdirectories_still_reports_a_loose_file_directly_in_uploads_root() -> None:
    # Arrange — a loose file sitting directly in uploads/ (not a subdirectory)
    # is deliberately still reported as its own entry, unlike derive_themes: the
    # blob heuristic needs to see a giant loose file too. This pins the existing
    # behaviour so the _relative_children fix for derive_themes does not
    # accidentally change derive_uploads_subdirectories.
    payload = load_fixture("representative-site.json")
    payload["files"] = [
        {"path": "wp-content/uploads/loose-huge-export.zip", "size": 999, "mtime": 1},
        {"path": "wp-content/uploads/2024/a.jpg", "size": 100, "mtime": 1},
    ]

    # Act.
    document = json.loads(run_on(payload).stdout)

    # Assert.
    subdirectories = {
        entry["path"]: entry["size_bytes"]
        for entry in document["uploads"]["subdirectories"]
    }
    assert subdirectories == {"loose-huge-export.zip": 999, "2024": 100}


def test_database_password_never_appears_in_the_canonical_document() -> None:
    # Arrange — the fixture's DB_PASSWORD carries a unique sentinel, standing in
    # for a hypothetically unredacted upstream value; the assembler must redact it
    # defensively even though the environment endpoint already masks it.
    sentinel = "P@ssw0rd-NEVER-LEAK-2b91f"

    # Act — serialise the whole document so the scan cannot miss a nested leak.
    result = run_discovery((FIXTURES / "representative-site.json").read_bytes())
    document = json.loads(result.stdout)

    # Assert — the secret is absent everywhere and its define value is redacted to
    # null (safety rail 8: the DB password never enters model context).
    assert sentinel not in result.stdout.decode()
    by_name = {entry["name"]: entry["value"] for entry in document["defines"]}
    assert by_name["DB_PASSWORD"] is None


def test_mariadb_flavour_is_reported_from_the_environment() -> None:
    # Arrange & Act.
    database = document_for("mariadb-site.json")["database"]

    # Assert — the flavour pins DDEV and avoids the collation import crash; it
    # comes straight from the environment endpoint's database server field.
    assert database["flavour"] == "mariadb"
    assert database["version"] == "10.11.6-MariaDB"


def test_mysql_flavour_is_reported_from_the_environment() -> None:
    # Arrange & Act.
    database = document_for("representative-site.json")["database"]

    # Assert.
    assert database["flavour"] == "mysql"


def test_php_version_is_pinned_to_major_minor() -> None:
    # Arrange & Act.
    environment = document_for("representative-site.json")["environment"]

    # Assert — DDEV pins PHP at major.minor, not the patch release.
    assert environment["php_version"] == "8.2.18"
    assert environment["php_major_minor"] == "8.2"


def test_monolingual_site_reports_no_multilingual_plugin() -> None:
    # Arrange & Act.
    plugins = document_for("monolingual-site.json")["plugins"]

    # Assert — verification stays monolingual-aware.
    assert plugins["multilingual_active"] is False
    assert plugins["multilingual_plugin"] is None


def test_multilingual_plugin_is_detected_among_active_plugins() -> None:
    # Arrange & Act.
    plugins = document_for("representative-site.json")["plugins"]

    # Assert — an active Polylang drives the localised-subpage smoke check.
    assert plugins["multilingual_active"] is True
    assert plugins["multilingual_plugin"] == "polylang/polylang.php"


def test_bogo_is_recognised_as_a_multilingual_plugin() -> None:
    # Arrange — a real bilingual Bogo site: Bogo filters the main query by
    # locale exactly as Polylang does, so it must arm the localised-subpage
    # rewrite-flush canary (issue #33).
    payload = load_fixture("monolingual-site.json")
    payload["environment"]["active_plugins"].append("bogo/bogo.php")

    # Act.
    result = run_on(payload)
    assert result.returncode == 0, result.stderr.decode()
    plugins = json.loads(result.stdout)["plugins"]

    # Assert — Bogo flips the multilingual flag and names its own entry.
    assert plugins["multilingual_active"] is True
    assert plugins["multilingual_plugin"] == "bogo/bogo.php"


def test_a_poised_campaign_flips_the_mail_recommendation() -> None:
    # Arrange & Act — a recognised engine with a queued campaign and a real list.
    mass_send = document_for("poised-campaign-site.json")["mass_send"]

    # Assert — the flip fires and one finding names the engine and the count
    # together, isolated from any unrecognised-fallback finding.
    assert mass_send["flip"] is True
    assert {
        "engine": "fluentcrm",
        "campaign": "Summer Sale 2026",
        "recipient_count": 4820,
    } in mass_send["poised_engines"]
    assert any(
        "fluentcrm" in finding and "4820" in finding
        for finding in mass_send["findings"]
    )


def test_a_poised_campaign_with_no_countable_list_still_flips() -> None:
    # Arrange & Act — a recognised engine (MailPoet) with a scheduled campaign
    # whose recipient list it cannot count, so recipient_count arrives as 0.
    mass_send = document_for("mailpoet-poised-site.json")["mass_send"]

    # Assert — the valve fails toward capture: a named, scheduled engine flips
    # mail even when no recipient count is available (ADR-0009). Requiring a
    # positive count would fail open and let a scheduled MailPoet send fire live.
    assert mass_send["flip"] is True
    assert {
        "engine": "mailpoet",
        "campaign": "Newsletter #9",
        "recipient_count": 0,
    } in mass_send["poised_engines"]
    assert any(
        "mailpoet" in finding and "Newsletter #9" in finding
        for finding in mass_send["findings"]
    )


def test_mere_plugin_presence_does_not_flip_the_mail_recommendation() -> None:
    # Arrange & Act — FluentCRM is present but no campaign is poised.
    mass_send = document_for("representative-site.json")["mass_send"]

    # Assert — presence alone never flips the default.
    assert mass_send["flip"] is False
    assert mass_send["poised_engines"] == []


def test_unrecognised_mailer_signal_surfaces_without_flipping() -> None:
    # Arrange & Act — no recognised engine, but a scheduled sending cron and a
    # large pending queue.
    mass_send = document_for("unrecognised-mailer-site.json")["mass_send"]

    # Assert — the finding surfaces and the run is marked uncertain, but the
    # recommendation does not flip.
    assert mass_send["flip"] is False
    assert mass_send["uncertain"] is True
    assert mass_send["findings"] != []


def test_attachment_metadata_is_carried_for_later_thumbnail_derivation() -> None:
    # Arrange & Act.
    attachments = document_for("representative-site.json")["attachments"]

    # Assert — the raw original path and its registered sizes survive intact, so
    # the thumbnail exclude-set can be derived downstream.
    banner = next(item for item in attachments if item["id"] == 12)
    assert banner["file"] == "2024/05/banner.jpg"
    assert "banner-300x200.jpg" in banner["sizes"]


def test_defines_are_carried_with_secret_values_redacted() -> None:
    # Arrange & Act — the representative site's wp-config defines flow into the
    # document for the downstream classifier to split.
    defines = document_for("representative-site.json")["defines"]

    # Assert — every define's name is carried so the classifier can account for
    # it, a portable define keeps its value, but a secret define's value is
    # redacted to None here at the boundary (safety rail 8), never riding into the
    # document even though the environment endpoint already masked it.
    by_name = {entry["name"]: entry["value"] for entry in defines}
    assert by_name["WP_MEMORY_LIMIT"] == "256M"
    assert by_name["DB_PASSWORD"] is None
    assert by_name["AUTH_SALT"] is None


def test_a_malformed_define_record_fails_loudly() -> None:
    # Arrange — a define entry lacking its 'name' must fail loud rather than ride
    # into the document half-built or crash on a KeyError.
    payload = load_fixture("representative-site.json")
    payload["environment"]["defines"] = [{"value": "orphan"}]

    # Act.
    result = run_on(payload)

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"discovery:")
    assert b"defines" in result.stderr


def test_malformed_json_input_fails_loudly() -> None:
    # Arrange & Act.
    result = run_discovery(b"this is not json")

    # Assert — a non-zero exit and a diagnostic naming the failure, never a
    # half-built document on stdout.
    assert result.returncode != 0
    assert b"not valid JSON" in result.stderr
    assert result.stdout == b""


def test_missing_environment_section_fails_loudly() -> None:
    # Arrange & Act — a well-formed object lacking the required section.
    result = run_discovery(b'{"tables": {}}')

    # Assert.
    assert result.returncode != 0
    assert b"missing" in result.stderr
    assert b"environment" in result.stderr
    assert result.stdout == b""


def test_a_required_field_of_the_wrong_type_fails_loudly() -> None:
    # Arrange — home_url is required and typed; a number is malformed.
    payload = load_fixture("representative-site.json")
    payload["environment"]["wordpress"]["home_url"] = 12345

    # Act.
    result = run_on(payload)

    # Assert — a loud exit that names the offending field, never a document.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"discovery:")
    assert b"home_url" in result.stderr


def test_a_malformed_structural_field_fails_loudly() -> None:
    # Arrange — the tables enumeration must be a list; a string is malformed and
    # must not ride through into the document (AC1: never a half-built document).
    payload = load_fixture("representative-site.json")
    payload["tables"]["tables"] = "oops"

    # Act.
    result = run_on(payload)

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"discovery:")
    assert b"tables" in result.stderr


def test_a_non_string_active_plugin_fails_loudly() -> None:
    # Arrange — a non-string element in active_plugins would otherwise crash the
    # multilingual scan with an uncaught traceback rather than a diagnostic.
    payload = load_fixture("representative-site.json")
    payload["environment"]["active_plugins"] = ["polylang/polylang.php", 42]

    # Act.
    result = run_on(payload)

    # Assert — the precise `discovery: ...` diagnostic, not a stack trace, and no
    # partial document (user story #8: a remediation message, not a traceback).
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"discovery:")
    assert b"active_plugins" in result.stderr


def test_entity_counts_are_carried_from_the_bootstrap_parse() -> None:
    # Arrange — the bootstrap parse's entity_counts (the cheap COUNT signals it
    # derives from the bootstrap extraction's rows) flow into the document, so the
    # Verify section's promised counts.* expectations have a live fact to source.
    payload = load_fixture("representative-site.json")
    payload["bootstrap"]["entity_counts"] = {
        "published_posts": 361,
        "published_pages": 62,
        "attachments": 214,
        "users": 7,
    }

    # Act.
    result = run_on(payload)
    document: dict[str, Any] = json.loads(result.stdout)

    # Assert — the four counts survive intact into the canonical document.
    assert result.returncode == 0
    assert document["entity_counts"] == {
        "published_posts": 361,
        "published_pages": 62,
        "attachments": 214,
        "users": 7,
    }


def test_entity_counts_section_is_empty_rather_than_zero_filled_when_the_bootstrap_omits_it() -> None:
    # Arrange & Act — the representative fixture's bootstrap carries no
    # entity_counts, so the document must still build without failing loud on the
    # absent optional section. Critically, it must NOT zero-fill every count: a
    # document built from a bootstrap without them would otherwise hand
    # generate_expectations a false "0 posts, 0 pages, 0 attachments, 0 users"
    # fact, FAILing any non-empty real site.
    document = document_for("representative-site.json")

    # Assert — the section is present (uniform document shape) but empty, so a
    # downstream reader's "is this key present" check — never a "!= 0" check — is
    # what decides whether a count was actually collected.
    assert document["entity_counts"] == {}


def test_entity_counts_omits_only_the_specific_keys_the_bootstrap_leaves_out() -> None:
    # Arrange — a bootstrap that reports some counts but not others (e.g. a
    # selection lacking wp_users) must carry exactly the counts it actually
    # reports, never zero-filling the rest.
    payload = load_fixture("representative-site.json")
    payload["bootstrap"]["entity_counts"] = {"published_posts": 361, "users": 7}

    # Act.
    document = json.loads(run_on(payload).stdout)

    # Assert.
    assert document["entity_counts"] == {"published_posts": 361, "users": 7}
    assert "published_pages" not in document["entity_counts"]
    assert "attachments" not in document["entity_counts"]


def test_a_non_integer_entity_count_fails_loudly() -> None:
    # Arrange — a malformed count must not ride through into the document
    # (AC1: never a half-built document on stdout).
    payload = load_fixture("representative-site.json")
    payload["bootstrap"]["entity_counts"] = {"published_posts": "oops"}

    # Act.
    result = run_on(payload)

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"discovery:")
    assert b"published_posts" in result.stderr


def test_root_subdirectories_are_summed_from_the_file_manifest() -> None:
    # Arrange — the install-root breakdown must sum each top-level directory's
    # files (the wider blob heuristic's input, issue #38), while a loose file
    # sitting directly in the root is not a directory and must not appear.
    payload = load_fixture("representative-site.json")
    payload["files"] = [
        {"path": "2026/big.zip", "size": 8215479066, "mtime": 1},
        {"path": "2026/more.zip", "size": 100, "mtime": 1},
        {"path": "wp-admin/index.php", "size": 500, "mtime": 1},
        {"path": "wp-content/plugins/foo/foo.php", "size": 10, "mtime": 1},
        {"path": "index.php", "size": 405, "mtime": 1},
    ]

    # Act.
    document = json.loads(run_on(payload).stdout)

    # Assert — the two 2026 files sum, wp-admin and wp-content are directories,
    # and the loose root index.php is not counted as a directory.
    root = {
        entry["path"]: entry["size_bytes"]
        for entry in document["root"]["subdirectories"]
    }
    assert root == {"2026": 8215479166, "wp-admin": 500, "wp-content": 10}
    assert "index.php" not in root


def test_content_subdirectories_are_summed_from_the_file_manifest() -> None:
    # Arrange — the content-directory breakdown must sum each of its top-level
    # children (the wider blob heuristic's second input), while a loose file
    # sitting directly under the content dir is not a directory.
    payload = load_fixture("representative-site.json")
    payload["files"] = [
        {"path": "wp-content/ai1wm-backups/x.wpress", "size": 2147483648, "mtime": 1},
        {"path": "wp-content/plugins/foo/foo.php", "size": 10, "mtime": 1},
        {"path": "wp-content/uploads/2024/a.jpg", "size": 100, "mtime": 1},
        {"path": "wp-content/index.php", "size": 28, "mtime": 1},
    ]

    # Act.
    document = json.loads(run_on(payload).stdout)

    # Assert — each content child sums; the loose index.php under the content
    # dir is not counted as a directory.
    content = {
        entry["path"]: entry["size_bytes"]
        for entry in document["content"]["subdirectories"]
    }
    assert content == {"ai1wm-backups": 2147483648, "plugins": 10, "uploads": 100}
    assert "index.php" not in content
