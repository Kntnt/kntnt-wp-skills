# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Parse the raw health-check and discovery output into one canonical discovery document.

This helper is the sole automated seam of the transfer engine's health-check and
discovery step. The runtime skill collects raw output over the Novamira control
channel — an optional liveness probe, an optional exec probe, and the single
read-only discovery call — and pipes it here as one JSON object on stdin. The
helper validates it and writes the canonical discovery document to stdout: the
single, structured input every later recommendation derives from.

Two contracts matter above the rest:

- The database password is never carried into the document, whatever the raw
  input holds — the connection is rebuilt from an allowlist, so the one secret
  that unlocks everything cannot enter model context (safety rail / platform
  constraint 8).
- Malformed input fails loudly: a non-zero exit and a diagnostic on stderr,
  never a half-built document on stdout.

The document computes only normalisations the whole engine agrees on — the
database flavour, the PHP major.minor pin, the connection host/port split, the
multilingual-plugin flag, and the mass-send flip. Classification of tables,
defines, blobs, and the thumbnail exclude-set is deliberately left downstream;
this document carries the raw attachment metadata that derivation consumes.
"""

from __future__ import annotations

import json
import sys
from typing import Any

# The document's shape version, bumped when a later reader would need to adapt.
SCHEMA_VERSION = 1

# Plugin directory slugs whose active presence makes a site multilingual — the
# flag that adds a localised home and subpage to the smoke test (the canary for
# the rewrite-flush bug). Matched against the directory part of each active
# plugin entry ("polylang/polylang.php" -> "polylang").
MULTILINGUAL_PLUGIN_SLUGS = frozenset(
    {
        "polylang",
        "polylang-pro",
        "sitepress-multilingual-cms",
        "translatepress-multilingual",
        "weglot",
        "multilingualpress",
        "qtranslate-xt",
    }
)

# Minimum pending-queue size before an unrecognised mailer's generic signal —
# a scheduled sending cron plus a backlog — is worth surfacing to the operator.
UNRECOGNISED_QUEUE_THRESHOLD = 50


class DiscoveryError(Exception):
    """Raised when the raw input is malformed: not an object, missing a required
    section, or carrying a field of the wrong type. The CLI turns this into a
    loud non-zero exit rather than emitting a partial document."""


def _require(mapping: Any, key: str, expected: type, context: str) -> Any:
    """Fetch ``mapping[key]``, asserting the mapping is an object and the value
    has the expected type; raise :class:`DiscoveryError` with a precise message
    otherwise. This is the boundary check that makes malformed input fail loud."""

    if not isinstance(mapping, dict):
        raise DiscoveryError(
            f"{context}: expected an object, got {type(mapping).__name__}"
        )
    if key not in mapping:
        raise DiscoveryError(f"{context}: missing required field {key!r}")
    value = mapping[key]
    if not isinstance(value, expected):
        raise DiscoveryError(
            f"{context}: field {key!r} must be {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    return value


def split_host_and_port(db_host: str) -> tuple[str, int | None, str | None]:
    """Split a WordPress ``DB_HOST`` into host, port, and socket.

    ``DB_HOST`` may embed a port (``127.0.0.1:3306``) or a socket path
    (``localhost:/var/run/mysqld/mysqld.sock``) after a single colon — the
    database-client credentials file needs them apart (platform constraint 6). A
    bare host, or an IPv6 literal carrying several colons, is returned unsplit.
    """

    if db_host.count(":") != 1:
        return db_host, None, None

    host, _, suffix = db_host.partition(":")
    if suffix.isdigit():
        return host, int(suffix), None
    if suffix.startswith("/"):
        return host, None, suffix
    return db_host, None, None


def detect_flavour(version: str, version_comment: str) -> str:
    """Classify the database server as MariaDB or MySQL from its version string
    and comment — the pin that keeps a MySQL 8 dump from crashing a MariaDB
    import on modern collations (platform constraint 11)."""

    haystack = f"{version} {version_comment}".lower()
    return "mariadb" if "mariadb" in haystack else "mysql"


def major_minor(version: str) -> str:
    """Reduce a full PHP version to its ``major.minor`` pin (``8.2.18`` ->
    ``8.2``); DDEV is pinned at this granularity, never the patch release."""

    parts = version.split(".")
    if len(parts) < 2:
        raise DiscoveryError(f"php_version {version!r} is not in major.minor form")
    return f"{parts[0]}.{parts[1]}"


def detect_multilingual(active_plugins: list[str]) -> tuple[bool, str | None]:
    """Report whether an active plugin is one of the recognised multilingual
    plugins, and which entry matched, driving the localisation-aware smoke test."""

    for plugin in active_plugins:
        slug = plugin.split("/", 1)[0]
        if slug in MULTILINGUAL_PLUGIN_SLUGS:
            return True, plugin
    return False, None


def build_connection(raw: dict[str, Any]) -> dict[str, Any]:
    """Build the database connection from an allowlist of non-secret constants.

    ``DB_PASSWORD`` is deliberately never read, so the one secret that unlocks
    everything cannot enter the document (safety rail 8). ``DB_HOST`` is split
    into host, port, and socket for the client credentials file.
    """

    db_host = _require(raw, "DB_HOST", str, "database.connection")
    host, port, socket = split_host_and_port(db_host)
    return {
        "host": host,
        "port": port,
        "socket": socket,
        "name": raw.get("DB_NAME", ""),
        "user": raw.get("DB_USER", ""),
        "charset": raw.get("DB_CHARSET", ""),
        "collate": raw.get("DB_COLLATE", ""),
    }


def build_mass_send(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract the mass-send verdict from the raw scan.

    A *poised* campaign — a recognised engine that is present, has a queued or
    scheduled campaign, and holds a real recipient list — is what flips the mail
    recommendation from live to capture; mere plugin presence never does. An
    unrecognised mailer only ever falls back to a generic signal (a scheduled
    sending cron plus a large pending queue): it surfaces a finding and marks the
    run uncertain, but it never flips the recommendation on its own.
    """

    engines = raw.get("engines", [])
    unrecognised = raw.get("unrecognised", {})

    # Keep only the genuinely poised engines; presence alone is not enough.
    poised_engines = [
        {
            "engine": engine.get("engine"),
            "campaign": engine.get("campaign"),
            "recipient_count": engine.get("recipient_count", 0),
        }
        for engine in engines
        if engine.get("present")
        and engine.get("queued_or_scheduled")
        and engine.get("recipient_count", 0) > 0
    ]

    # Lead every poised engine with a loud, specific finding for the warning.
    findings = [
        f"{engine['engine']}: campaign {engine['campaign']!r} is poised against "
        f"{engine['recipient_count']} recipients — mail flips to capture"
        for engine in poised_engines
    ]

    # Surface an unrecognised mailer's generic signal without flipping.
    uncertain = bool(
        unrecognised.get("sending_cron_scheduled")
        and unrecognised.get("pending_queue_size", 0) >= UNRECOGNISED_QUEUE_THRESHOLD
    )
    if uncertain:
        findings.append(
            "an unrecognised mailer has a scheduled sending cron and a pending "
            f"queue of {unrecognised['pending_queue_size']} — review before "
            "trusting live mail"
        )

    return {
        "flip": bool(poised_engines),
        "poised_engines": poised_engines,
        "uncertain": uncertain,
        "findings": findings,
    }


def build_document(raw: Any) -> dict[str, Any]:
    """Assemble the canonical discovery document from the raw combined input.

    The ``discovery`` section is required; the ``liveness`` and ``exec`` probe
    sections are optional and enrich the environment when present. The document
    is built by explicit construction from allowlisted fields — never a blanket
    copy — so no secret rides along by accident.
    """

    discovery = _require(raw, "discovery", dict, "input")
    liveness = raw.get("liveness", {}) if isinstance(raw, dict) else {}
    exec_probe = raw.get("exec", {}) if isinstance(raw, dict) else {}

    # Resolve the environment, preferring the liveness probe for the fields it
    # and discovery both report.
    php_version = liveness.get("php_version") or _require(
        discovery, "php_version", str, "discovery"
    )
    server_software = liveness.get("server_software") or discovery.get(
        "server_software", ""
    )

    database = _require(discovery, "database", dict, "discovery")
    connection = build_connection(_require(database, "connection", dict, "database"))
    active_plugins = discovery.get("active_plugins", [])
    multilingual_active, multilingual_plugin = detect_multilingual(active_plugins)

    return {
        "schema_version": SCHEMA_VERSION,
        "site": {
            "home_url": _require(discovery, "home_url", str, "discovery"),
            "site_url": discovery.get("site_url", ""),
            "root_path": discovery.get("root_path", ""),
            "content_path": discovery.get("content_path", ""),
            "uploads_base": discovery.get("uploads_base", ""),
            "core_version": discovery.get("core_version", ""),
        },
        "environment": {
            "php_version": php_version,
            "php_major_minor": major_minor(php_version),
            "server_software": server_software,
            "exec_available": bool(exec_probe.get("exec_available", False)),
            "disk_free_bytes": discovery.get("disk_free_bytes", 0),
            "root_writable": bool(discovery.get("root_writable", False)),
        },
        "database": {
            "flavour": detect_flavour(
                _require(database, "version", str, "database"),
                database.get("version_comment", ""),
            ),
            "version": database["version"],
            "default_collation": database.get("default_collation", ""),
            "table_prefix": _require(discovery, "table_prefix", str, "discovery"),
            "total_size_bytes": database.get("total_size_bytes", 0),
            "top_tables": database.get("top_tables", []),
            "content_tables_innodb": bool(database.get("content_tables_innodb", False)),
            "connection": connection,
        },
        "uploads": {
            "subdirectories": discovery.get("uploads_subdirectories", []),
        },
        "plugins": {
            "active": active_plugins,
            "multilingual_active": multilingual_active,
            "multilingual_plugin": multilingual_plugin,
        },
        "dropins": discovery.get("dropins", []),
        "themes": discovery.get("themes", []),
        "mass_send": build_mass_send(discovery.get("mass_send", {})),
        "attachments": discovery.get("attachments", []),
        "binaries": discovery.get("binaries", {}),
    }


def main() -> int:
    """Read raw JSON on stdin, emit the canonical document on stdout, and fail
    loudly on malformed input with a non-zero exit and a stderr diagnostic."""

    raw_text = sys.stdin.read()

    # Parse the raw input, reporting a malformed payload rather than crashing.
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as error:
        print(f"discovery: input is not valid JSON: {error}", file=sys.stderr)
        return 1

    # Build the document, turning any contract violation into a loud exit.
    try:
        document = build_document(raw)
    except DiscoveryError as error:
        print(f"discovery: {error}", file=sys.stderr)
        return 1

    json.dump(document, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
