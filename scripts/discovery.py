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
this document carries the raw attachment metadata and the wp-config defines that
derivation consumes. The defines are the one place a secret could ride in beside
the connection, so each secret value (the DB password, an auth key, a salt, a
nonce) is redacted here at the boundary — the name is kept for the classifier,
the value dropped (safety rail 8).
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

# Define names whose *value* is a production secret that must never enter the
# canonical document: the database password (safety rail 8, the one secret that
# unlocks everything) and the eight WordPress auth keys, salts, and nonces that
# never come down. Custom plugin variants are caught by the *_SALT / NONCE_*
# patterns in is_secret_define below.
SECRET_DEFINE_NAMES = frozenset(
    {
        "DB_PASSWORD",
        "AUTH_KEY",
        "SECURE_AUTH_KEY",
        "LOGGED_IN_KEY",
        "NONCE_KEY",
        "AUTH_SALT",
        "SECURE_AUTH_SALT",
        "LOGGED_IN_SALT",
        "NONCE_SALT",
    }
)


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


def _optional(
    mapping: dict[str, Any], key: str, expected: type, default: Any, context: str
) -> Any:
    """Fetch an optional ``mapping[key]``: return the value when present and of
    the expected type, the ``default`` when the key is absent, and raise
    :class:`DiscoveryError` when the key is present but of the wrong type.

    Optionality is about presence, never about shape — a field the scan does emit
    must still be well-typed, so a malformed value fails loudly rather than riding
    into the document (AC1: never a half-built document on stdout)."""

    if key not in mapping:
        return default
    value = mapping[key]
    if not isinstance(value, expected):
        raise DiscoveryError(
            f"{context}: field {key!r} must be {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    return value


def _string_list(mapping: dict[str, Any], key: str, context: str) -> list[str]:
    """Fetch an optional list of strings, defaulting to empty when absent and
    raising :class:`DiscoveryError` when the value is not a list or holds a
    non-string element. This is the boundary that lets downstream string handling
    — plugin slugs, theme and drop-in names — trust its input instead of crashing
    on a stray non-string with an uncaught traceback."""

    value = mapping.get(key, [])
    if not isinstance(value, list):
        raise DiscoveryError(
            f"{context}: field {key!r} must be list, got {type(value).__name__}"
        )
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise DiscoveryError(
                f"{context}: field {key!r}[{index}] must be str, "
                f"got {type(item).__name__}"
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
        "name": _optional(raw, "DB_NAME", str, "", "database.connection"),
        "user": _optional(raw, "DB_USER", str, "", "database.connection"),
        "charset": _optional(raw, "DB_CHARSET", str, "", "database.connection"),
        "collate": _optional(raw, "DB_COLLATE", str, "", "database.connection"),
    }


def is_secret_define(name: str) -> bool:
    """Report whether a define carries a production secret whose value must be
    redacted before it enters the document — the database password and the auth
    key / salt / nonce family, including the custom plugin variants a downstream
    classifier also treats as secrets (safety rail 8; the secrets that never come
    down)."""

    return (
        name in SECRET_DEFINE_NAMES
        or name.endswith("_SALT")
        or name.startswith("NONCE_")
    )


def build_defines(raw_defines: list[Any]) -> list[dict[str, Any]]:
    """Carry production's wp-config defines into the document for the downstream
    classifier, redacting every secret value at this trust boundary.

    Classification into the portable and auto-excluded classes is left downstream,
    but the split needs every define's name — so the name is always carried, while
    a secret's value (the DB password, an auth key, a salt, a nonce) is dropped to
    ``None`` here, before it can reach model context and independently of the
    classifier later dropping the whole auto-excluded value (safety rail 8). A
    malformed entry — a non-object, or one missing its ``name`` — fails loudly
    rather than riding in half-built.
    """

    defines: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_defines):
        context = f"discovery.defines[{index}]"
        name = _require(entry, "name", str, context)
        value = None if is_secret_define(name) else entry.get("value")
        defines.append({"name": name, "value": value})

    return defines


def _poised_finding(engine: dict[str, Any]) -> str:
    """Compose the loud, specific warning for one poised engine. A positive
    recipient count is named; a zero count means the engine could not size the
    list (MailPoet reports only the subject), so the warning says so plainly
    rather than claiming a campaign 'against 0 recipients'."""

    count = engine["recipient_count"]
    target = (
        f"against {count} recipients"
        if count > 0
        else "against its recipient list (size unavailable)"
    )
    return (
        f"{engine['engine']}: campaign {engine['campaign']!r} is poised "
        f"{target} — mail flips to capture"
    )


def build_mass_send(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract the mass-send verdict from the raw scan.

    A *poised* campaign — a recognised engine that is present and has a queued or
    scheduled campaign — is what flips the mail recommendation from live to
    capture; mere plugin presence never does. The recipient count is reported in
    the warning but is **not** a gate: a named engine that cannot size its list
    (MailPoet queries only the subject, so it reports 0) must still flip, so the
    valve fails toward capture rather than open on an uncountable list (ADR-0009,
    the mass-send safety rail). An unrecognised mailer only ever falls back to a
    generic signal (a scheduled sending cron plus a large pending queue): it
    surfaces a finding and marks the run uncertain, but never flips on its own.
    """

    engines = _optional(raw, "engines", list, [], "mass_send")
    unrecognised = _optional(raw, "unrecognised", dict, {}, "mass_send")

    # Validate each engine record before reading it, so a malformed scan fails
    # loud rather than crashing on a non-object or a non-numeric recipient count.
    for index, engine in enumerate(engines):
        if not isinstance(engine, dict):
            raise DiscoveryError(
                f"mass_send.engines[{index}]: expected an object, "
                f"got {type(engine).__name__}"
            )
        _optional(engine, "recipient_count", int, 0, f"mass_send.engines[{index}]")

    # Keep only the genuinely poised engines: present and queued or scheduled.
    # Presence alone never flips, and an uncountable list never un-flips.
    poised_engines = [
        {
            "engine": engine.get("engine"),
            "campaign": engine.get("campaign"),
            "recipient_count": engine.get("recipient_count", 0),
        }
        for engine in engines
        if engine.get("present") and engine.get("queued_or_scheduled")
    ]

    # Lead every poised engine with a loud, specific finding for the warning.
    findings = [_poised_finding(engine) for engine in poised_engines]

    # Surface an unrecognised mailer's generic signal without flipping.
    pending_queue_size = _optional(
        unrecognised, "pending_queue_size", int, 0, "mass_send.unrecognised"
    )
    uncertain = bool(
        unrecognised.get("sending_cron_scheduled")
        and pending_queue_size >= UNRECOGNISED_QUEUE_THRESHOLD
    )
    if uncertain:
        findings.append(
            "an unrecognised mailer has a scheduled sending cron and a pending "
            f"queue of {pending_queue_size} — review before trusting live mail"
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
    liveness = _optional(raw, "liveness", dict, {}, "input")
    exec_probe = _optional(raw, "exec", dict, {}, "input")

    # Resolve the environment, preferring the liveness probe for the fields it
    # and discovery both report; both sources are typed so a stray number never
    # reaches major_minor's string split.
    php_version = _optional(liveness, "php_version", str, "", "liveness") or _require(
        discovery, "php_version", str, "discovery"
    )
    server_software = _optional(
        liveness, "server_software", str, "", "liveness"
    ) or _optional(discovery, "server_software", str, "", "discovery")

    database = _require(discovery, "database", dict, "discovery")
    connection = build_connection(_require(database, "connection", dict, "database"))
    active_plugins = _string_list(discovery, "active_plugins", "discovery")
    multilingual_active, multilingual_plugin = detect_multilingual(active_plugins)

    return {
        "schema_version": SCHEMA_VERSION,
        "site": {
            "home_url": _require(discovery, "home_url", str, "discovery"),
            "site_url": _optional(discovery, "site_url", str, "", "discovery"),
            "root_path": _optional(discovery, "root_path", str, "", "discovery"),
            "content_path": _optional(discovery, "content_path", str, "", "discovery"),
            "uploads_base": _optional(discovery, "uploads_base", str, "", "discovery"),
            "core_version": _optional(discovery, "core_version", str, "", "discovery"),
        },
        "environment": {
            "php_version": php_version,
            "php_major_minor": major_minor(php_version),
            "server_software": server_software,
            "exec_available": _optional(
                exec_probe, "exec_available", bool, False, "exec"
            ),
            "disk_free_bytes": _optional(
                discovery, "disk_free_bytes", int, 0, "discovery"
            ),
            "root_writable": _optional(
                discovery, "root_writable", bool, False, "discovery"
            ),
        },
        "database": {
            "flavour": detect_flavour(
                _require(database, "version", str, "database"),
                _optional(database, "version_comment", str, "", "database"),
            ),
            "version": database["version"],
            "default_collation": _optional(
                database, "default_collation", str, "", "database"
            ),
            "table_prefix": _require(discovery, "table_prefix", str, "discovery"),
            "total_size_bytes": _optional(
                database, "total_size_bytes", int, 0, "database"
            ),
            "top_tables": _optional(database, "top_tables", list, [], "database"),
            "content_tables_innodb": _optional(
                database, "content_tables_innodb", bool, False, "database"
            ),
            "connection": connection,
        },
        "uploads": {
            "subdirectories": _optional(
                discovery, "uploads_subdirectories", list, [], "discovery"
            ),
        },
        "plugins": {
            "active": active_plugins,
            "multilingual_active": multilingual_active,
            "multilingual_plugin": multilingual_plugin,
        },
        "dropins": _string_list(discovery, "dropins", "discovery"),
        "themes": _string_list(discovery, "themes", "discovery"),
        "mass_send": build_mass_send(
            _optional(discovery, "mass_send", dict, {}, "discovery")
        ),
        "attachments": _optional(discovery, "attachments", list, [], "discovery"),
        "defines": build_defines(
            _optional(discovery, "defines", list, [], "discovery")
        ),
        "binaries": _optional(discovery, "binaries", dict, {}, "discovery"),
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
