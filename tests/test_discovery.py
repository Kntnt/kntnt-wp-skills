# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Behavioural tests for the discovery helper CLI.

The helper is the sole automated seam of the health-check/discovery step: raw
probe and discovery output goes in as JSON on stdin, the validated canonical
discovery document comes out as JSON on stdout, and malformed input fails loudly
with a non-zero exit. Every test exercises that seam through the real command —
fixtures in, observable output out — and never reaches into the helper's
internals. The fixtures under ``fixtures/`` are what the production-side
discovery template would emit for a given site; no test touches a real site.
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


def test_valid_discovery_output_is_parsed_into_a_canonical_document() -> None:
    # Arrange & Act.
    document = document_for("representative-site.json")

    # Assert — the document carries the sections every later recommendation
    # derives from, keyed under a stable schema version.
    assert document["schema_version"] == 1
    assert document["site"]["home_url"] == "https://www.example.com"
    assert document["site"]["core_version"] == "6.5.2"
    assert document["database"]["total_size_bytes"] == 268435456
    assert {"name": "wp_posts", "size_bytes": 104857600} in document["database"][
        "top_tables"
    ]
    assert document["uploads"]["subdirectories"][0]["path"] == "2024"
    assert document["binaries"]["mysqldump"] is True
    assert document["dropins"] == ["object-cache.php", "advanced-cache.php"]
    assert document["themes"] == ["astra", "twentytwentyfour"]


def test_database_password_never_appears_in_the_canonical_document() -> None:
    # Arrange — the fixture's DB_PASSWORD carries a unique sentinel.
    sentinel = "P@ssw0rd-NEVER-LEAK-2b91f"

    # Act — serialise the whole document so the scan cannot miss a nested leak.
    result = run_discovery((FIXTURES / "representative-site.json").read_bytes())
    document = json.loads(result.stdout)

    # Assert — the secret is absent everywhere and the connection has no
    # password-bearing key at all (safety rail: the DB password never enters
    # model context).
    assert sentinel not in result.stdout.decode()
    connection = document["database"]["connection"]
    assert "password" not in {key.lower() for key in connection}


def test_connection_host_with_embedded_port_is_split() -> None:
    # Arrange & Act — the representative site's DB_HOST is "127.0.0.1:3306".
    connection = document_for("representative-site.json")["database"]["connection"]

    # Assert — host and port travel apart, as the client credentials file needs.
    assert connection["host"] == "127.0.0.1"
    assert connection["port"] == 3306
    assert connection["socket"] is None


def test_connection_host_without_a_port_leaves_the_port_null() -> None:
    # Arrange & Act — the MariaDB fixture's DB_HOST is a bare "localhost".
    connection = document_for("mariadb-site.json")["database"]["connection"]

    # Assert.
    assert connection["host"] == "localhost"
    assert connection["port"] is None


def test_mariadb_flavour_is_detected_from_the_version() -> None:
    # Arrange & Act.
    database = document_for("mariadb-site.json")["database"]

    # Assert — the flavour pins DDEV and avoids the collation import crash.
    assert database["flavour"] == "mariadb"


def test_mysql_flavour_is_detected_from_the_version() -> None:
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


def test_a_poised_campaign_flips_the_mail_recommendation() -> None:
    # Arrange & Act — a recognised engine with a queued campaign and a real list.
    mass_send = document_for("poised-campaign-site.json")["mass_send"]

    # Assert — the flip fires and the finding names the engine and the count.
    assert mass_send["flip"] is True
    assert {
        "engine": "fluentcrm",
        "campaign": "Summer Sale 2026",
        "recipient_count": 4820,
    } in mass_send["poised_engines"]
    assert any("4820" in finding for finding in mass_send["findings"])


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


def test_malformed_json_input_fails_loudly() -> None:
    # Arrange & Act.
    result = run_discovery(b"this is not json")

    # Assert — a non-zero exit and a diagnostic naming the failure, never a
    # half-built document on stdout.
    assert result.returncode != 0
    assert b"not valid JSON" in result.stderr
    assert result.stdout == b""


def test_missing_discovery_section_fails_loudly() -> None:
    # Arrange & Act — a well-formed object lacking the required section.
    result = run_discovery(b'{"liveness": {}}')

    # Assert.
    assert result.returncode != 0
    assert b"missing" in result.stderr
    assert result.stdout == b""
