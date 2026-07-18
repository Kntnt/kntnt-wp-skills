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


def test_connection_host_with_a_socket_path_is_split() -> None:
    # Arrange — a DB_HOST that carries a unix socket path after the single colon.
    payload = load_fixture("mariadb-site.json")
    connection_in = payload["discovery"]["database"]["connection"]
    connection_in["DB_HOST"] = "localhost:/var/run/mysqld/mysqld.sock"

    # Act.
    result = run_on(payload)
    assert result.returncode == 0, result.stderr.decode()
    connection = json.loads(result.stdout)["database"]["connection"]

    # Assert — the socket travels apart from the host, with no spurious port, as
    # the client credentials file needs.
    assert connection["host"] == "localhost"
    assert connection["port"] is None
    assert connection["socket"] == "/var/run/mysqld/mysqld.sock"


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
    # document even before the classifier drops the whole auto-excluded value.
    by_name = {entry["name"]: entry["value"] for entry in defines}
    assert by_name["WP_MEMORY_LIMIT"] == "256M"
    assert by_name["DB_PASSWORD"] is None
    assert by_name["AUTH_SALT"] is None


def test_a_malformed_define_record_fails_loudly() -> None:
    # Arrange — a define entry lacking its 'name' must fail loud rather than ride
    # into the document half-built or crash on a KeyError.
    payload = load_fixture("representative-site.json")
    payload["discovery"]["defines"] = [{"value": "orphan"}]

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


def test_missing_discovery_section_fails_loudly() -> None:
    # Arrange & Act — a well-formed object lacking the required section.
    result = run_discovery(b'{"liveness": {}}')

    # Assert.
    assert result.returncode != 0
    assert b"missing" in result.stderr
    assert result.stdout == b""


def test_a_required_field_of_the_wrong_type_fails_loudly() -> None:
    # Arrange — home_url is required and typed; a number is malformed.
    payload = load_fixture("representative-site.json")
    payload["discovery"]["home_url"] = 12345

    # Act.
    result = run_on(payload)

    # Assert — a loud exit that names the offending field, never a document.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"discovery:")
    assert b"home_url" in result.stderr


def test_a_malformed_structural_field_fails_loudly() -> None:
    # Arrange — top_tables must be a list; a string is malformed and must not
    # ride through into the document (AC1: never a half-built document on stdout).
    payload = load_fixture("representative-site.json")
    payload["discovery"]["database"]["top_tables"] = "oops"

    # Act.
    result = run_on(payload)

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"discovery:")
    assert b"top_tables" in result.stderr


def test_a_non_string_active_plugin_fails_loudly() -> None:
    # Arrange — a non-string element in active_plugins would otherwise crash the
    # multilingual scan with an uncaught traceback rather than a diagnostic.
    payload = load_fixture("representative-site.json")
    payload["discovery"]["active_plugins"] = ["polylang/polylang.php", 42]

    # Act.
    result = run_on(payload)

    # Assert — the precise `discovery: ...` diagnostic, not a stack trace, and no
    # partial document (user story #8: a remediation message, not a traceback).
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"discovery:")
    assert b"active_plugins" in result.stderr
