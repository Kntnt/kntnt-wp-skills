# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Assemble the canonical discovery document from the Extractor REST sources.

This helper is the assembler seam of two-phase discovery (ADR-0016, ADR-0017).
Discovery no longer rides on a single server-side payload; it is reconstructed
client-side from three sources, and this helper normalises them into the one
canonical document every later recommendation derives from. It takes a single
JSON object on stdin with four sections:

- ``environment`` — the ``GET /environment`` response: the runtime/config scalars
  (PHP version, server software, WordPress core version, home/site URL, table
  prefix, content/uploads dirs, database server flavour/version/collation), the
  active plugins, the drop-ins present, and the resolved ``wp-config`` defines
  with the secret family already redacted to ``null`` server-side.
- ``tables`` — the ``GET /tables`` response: every table with its row-count and
  byte size, from which the total size, the authoritative table enumeration, and
  the heaviest-N report artifact are derived.
- ``files`` — the flattened ``GET /files`` manifest (each entry ``path``/``size``/
  ``mtime``, install-root-relative): the per-top-level-subdirectory uploads size
  breakdown and the installed theme directories are derived from it.
- ``bootstrap`` — the client-side parse of the cheap bootstrap extraction
  (``bootstrap_parse.py``'s output): the attachment metadata, the entity counts,
  and the mass-send poised-campaign scan, the three signals that live only in
  rows.

Two contracts matter above the rest:

- No production secret enters the document. The ``environment`` endpoint masks the
  secret define family server-side, and there are no database-connection
  constants to carry at all now (the import runs inside DDEV against the
  reassembled dump, never a client-side connection to production). Each secret
  define value is nonetheless redacted again here at the boundary — a second,
  independent line of defence (safety rail 8).
- Malformed input fails loudly: a non-zero exit and a ``discovery:`` diagnostic on
  stderr, never a half-built document on stdout.

The document computes only the normalisations the whole engine agrees on — the
PHP major.minor pin, the multilingual-plugin flag, the mass-send flip, the table
enumeration, and the uploads/theme breakdowns. Classification of tables, defines,
blobs, and the thumbnail exclude-set is deliberately left downstream.
"""

from __future__ import annotations

import json
import sys
from typing import Any

# The document's shape version, bumped when a later reader would need to adapt.
# Version 2 dropped the production-DB connection block, the binary probe, and the
# InnoDB/disk/writability fields the old single-call discovery carried, none of
# which the Extractor REST surface exposes or the plugin-owned dump needs.
SCHEMA_VERSION = 2

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
        "bogo",
    }
)

# Minimum pending-queue size before an unrecognised mailer's generic signal —
# a scheduled sending cron plus a backlog — is worth surfacing to the operator.
UNRECOGNISED_QUEUE_THRESHOLD = 50

# How many of the heaviest tables the report artifact carries alongside the full
# enumeration — the operator's overview, capped so a wide schema is not dumped whole.
TOP_TABLES_LIMIT = 20

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


def is_secret_define(name: str) -> bool:
    """Report whether a define carries a production secret whose value must be
    redacted before it enters the document — the database password and the auth
    key / salt / nonce family, including the custom plugin variants a downstream
    classifier also treats as secrets (safety rail 8; the secrets that never come
    down). The ``environment`` endpoint already masks these server-side; redacting
    again here is the second, independent line of defence."""

    return (
        name in SECRET_DEFINE_NAMES
        or name.endswith("_SALT")
        or name.startswith("NONCE_")
    )


def build_defines(raw_defines: list[Any]) -> list[dict[str, Any]]:
    """Carry the ``environment`` endpoint's resolved defines into the document for
    the downstream classifier, redacting every secret value at this trust boundary.

    Classification into the portable and auto-excluded classes is left downstream,
    but the split needs every define's name — so the name is always carried, while
    a secret's value (the DB password, an auth key, a salt, a nonce) is dropped to
    ``None`` here even though the endpoint already masked it, before it can reach
    model context and independently of the classifier later dropping the whole
    auto-excluded value (safety rail 8). A malformed entry — a non-object, or one
    missing its ``name`` — fails loudly rather than riding in half-built.
    """

    defines: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_defines):
        context = f"environment.defines[{index}]"
        name = _require(entry, "name", str, context)
        value = None if is_secret_define(name) else entry.get("value")
        defines.append({"name": name, "value": value})

    return defines


def build_tables(tables_source: dict[str, Any]) -> dict[str, Any]:
    """Turn the ``GET /tables`` response into the document's table facts: the
    grand total size, the authoritative table enumeration (every table name, so
    the classifier and the dump cover every table — user story 16), and the
    heaviest-N report artifact for the operator's overview.

    Each record is validated before it is read, so a malformed table entry — a
    non-object, or one missing its ``name`` — fails loudly rather than riding a
    half-built enumeration into the document. The enumeration and the report are
    both ordered heaviest-first, the order the old single-call discovery used.
    """

    records = _optional(tables_source, "tables", list, [], "tables")
    parsed: list[tuple[str, int]] = []
    for index, record in enumerate(records):
        context = f"tables.tables[{index}]"
        name = _require(record, "name", str, context)
        size = _optional(record, "bytes", int, 0, context)
        parsed.append((name, size))

    parsed.sort(key=lambda item: item[1], reverse=True)
    return {
        "total_size_bytes": sum(size for _, size in parsed),
        "tables": [name for name, _ in parsed],
        "top_tables": [
            {"name": name, "size_bytes": size}
            for name, size in parsed[:TOP_TABLES_LIMIT]
        ],
    }


def _relative_children(
    files: list[Any], prefix: str
) -> list[tuple[str, int, bool]]:
    """Yield the ``(top-level-child, size, is_directory)`` triples of every
    manifest entry whose path sits under ``prefix``, skipping anything that does
    not. An empty ``prefix`` means the install root itself, so every entry's
    first path segment is a top-level child. A malformed entry — a non-object, a
    non-string path, a non-integer size — is skipped rather than aborting the
    whole document over one stray record in a manifest that can hold hundreds of
    thousands of files.

    The manifest holds files only, never directory entries, so directory-ness of
    a child is inferred rather than read off the entry: a segment is a directory
    exactly when the path continues past it — the remainder after ``prefix``
    contains a further ``/`` — and a bare file (e.g. an empty-directory guard
    ``index.php`` sitting directly under the prefix) is not.
    """

    normalised = prefix.rstrip("/") + "/" if prefix else ""
    children: list[tuple[str, int, bool]] = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.startswith(normalised):
            continue
        remainder = path[len(normalised) :]
        if not remainder:
            continue
        segment = remainder.split("/", 1)[0]
        size = entry.get("size")
        children.append(
            (segment, size if isinstance(size, int) else 0, "/" in remainder)
        )
    return children


def derive_uploads_subdirectories(
    files: list[Any], uploads_dir: str
) -> list[dict[str, Any]]:
    """Break the uploads tree down by top-level subdirectory, summing each one's
    files, so a heavy gallery stands out for the blob heuristic. Paths are
    install-root-relative and the uploads dir is too, so a subdirectory is the
    first path segment under the uploads dir; the result is ordered by name for a
    deterministic document.

    Unlike ``derive_themes``, a bare file sitting directly in the uploads root
    still contributes its own entry — deliberate: the blob heuristic needs to see
    a giant loose file too, not just files grouped under real subdirectories.
    """

    if not uploads_dir:
        return []
    sizes: dict[str, int] = {}
    for segment, size, _is_directory in _relative_children(files, uploads_dir):
        sizes[segment] = sizes.get(segment, 0) + size
    return [
        {"path": segment, "size_bytes": total}
        for segment, total in sorted(sizes.items())
    ]


def _summed_subdirectories(files: list[Any], prefix: str) -> list[dict[str, Any]]:
    """Sum the directory children under ``prefix`` into ``{path, size_bytes}``
    records ordered by name — the shared shape the install-root and content
    breakdowns give the blob heuristic, counting only genuine subdirectories: a
    loose top-level file (an ``index.php`` guard) is not a directory the heuristic
    should weigh, so it is excluded via the ``is_directory`` flag."""

    sizes: dict[str, int] = {}
    for segment, size, is_directory in _relative_children(files, prefix):
        if not is_directory:
            continue
        sizes[segment] = sizes.get(segment, 0) + size
    return [
        {"path": segment, "size_bytes": total}
        for segment, total in sorted(sizes.items())
    ]


def derive_root_subdirectories(files: list[Any]) -> list[dict[str, Any]]:
    """Break the install root down by top-level directory, summing each one's
    files, so a heavy stray directory outside uploads — the 7.6 GB ``2026/`` that
    transferred silently (issue #38) — becomes visible to the blob heuristic. Only
    directories count; a loose root file (``index.php``) is not a subdirectory."""

    return _summed_subdirectories(files, "")


def derive_content_subdirectories(
    files: list[Any], content_dir: str
) -> list[dict[str, Any]]:
    """Break the content directory down by top-level child, summing each one's
    files, so a heavy non-standard content child (a migration-plugin backup store)
    becomes visible to the blob heuristic alongside the install-root breakdown.
    An absent content dir yields nothing, mirroring the uploads breakdown."""

    if not content_dir:
        return []
    return _summed_subdirectories(files, content_dir)


def derive_themes(files: list[Any], content_dir: str) -> list[str]:
    """Enumerate the installed theme directories — the first path segment under
    ``<content_dir>/themes`` — for drift detection, ordered for determinism.

    Only directory segments count: a bare file directly under the themes prefix
    (an empty-directory guard ``index.php``, for instance) is not a theme.
    """

    if not content_dir:
        return []
    themes = {
        segment
        for segment, _size, is_directory in _relative_children(
            files, f"{content_dir.rstrip('/')}/themes"
        )
        if is_directory
    }
    return sorted(themes)


def build_entity_counts(raw: dict[str, Any]) -> dict[str, int]:
    """Carry the bootstrap parse's cheap entity counts — published posts,
    published pages, live attachments, and users — into the canonical document, so
    ``scripts/smoke_test.py``'s ``generate_expectations`` has a live fact to source
    ``counts.*`` from.

    A count the bootstrap parse omits — the whole section absent, or just one key
    within it (an older bootstrap selection lacking ``wp_users``, a hand-trimmed
    re-verification payload) — is **left out of the returned mapping entirely,
    never defaulted to zero**. Zero-filling would hand ``generate_expectations`` a
    false "0" fact it cannot tell apart from a genuinely empty site, FAILing any
    non-empty real site verified against a stale document. A present-but-malformed
    count still fails loud, the same "optionality is about presence, never about
    shape" contract every other optional field follows.
    """

    counts: dict[str, int] = {}
    for key in ("published_posts", "published_pages", "attachments", "users"):
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, int):
            raise DiscoveryError(
                f"entity_counts: field {key!r} must be int, got {type(value).__name__}"
            )
        counts[key] = value
    return counts


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
    """Turn the bootstrap parse's mass-send scan into the mail verdict.

    A *poised* campaign — a recognised engine that is present and has a queued or
    scheduled campaign — is what flips the mail recommendation from live to
    capture; mere plugin presence never does. The recipient count is reported in
    the warning but is **not** a gate: a named engine that cannot size its list
    (MailPoet queries only the subject, so it reports 0) must still flip, so the
    valve fails toward capture rather than open on an uncountable list (ADR-0009,
    the mass-send safety rail). An unrecognised mailer only ever falls back to a
    generic signal (a sending Action Scheduler event plus a large pending queue):
    it surfaces a finding and marks the run uncertain, but never flips on its own.
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
    """Assemble the canonical discovery document from the four REST-derived
    sections.

    The ``environment`` section is required — it anchors the site, the runtime,
    and the database facts; ``tables``, ``files``, and ``bootstrap`` are optional
    at this boundary and enrich the document when present. The document is built
    by explicit construction from allowlisted fields — never a blanket copy — so
    no secret rides along by accident.
    """

    environment = _require(raw, "environment", dict, "input")
    tables_source = _optional(raw, "tables", dict, {}, "input")
    files = _optional(raw, "files", list, [], "input")
    bootstrap = _optional(raw, "bootstrap", dict, {}, "input")

    wordpress = _require(environment, "wordpress", dict, "environment")
    database = _require(environment, "database", dict, "environment")

    php_version = _require(environment, "php_version", str, "environment")
    active_plugins = _string_list(environment, "active_plugins", "environment")
    multilingual_active, multilingual_plugin = detect_multilingual(active_plugins)

    content_dir = _optional(wordpress, "content_dir", str, "", "environment.wordpress")
    uploads_dir = _optional(wordpress, "uploads_dir", str, "", "environment.wordpress")
    table_facts = build_tables(tables_source)

    return {
        "schema_version": SCHEMA_VERSION,
        "site": {
            "home_url": _require(wordpress, "home_url", str, "environment.wordpress"),
            "site_url": _optional(wordpress, "site_url", str, "", "environment.wordpress"),
            # Paths are already install-root-relative, so there is no absolute
            # root to carry; the empty root keeps the field's shape stable.
            "root_path": "",
            "content_path": content_dir,
            "uploads_base": uploads_dir,
            "core_version": _optional(
                wordpress, "core_version", str, "", "environment.wordpress"
            ),
        },
        "environment": {
            "php_version": php_version,
            "php_major_minor": major_minor(php_version),
            "server_software": _optional(
                environment, "server_software", str, "", "environment"
            ),
        },
        "database": {
            "flavour": _optional(database, "server", str, "", "environment.database"),
            "version": _require(database, "version", str, "environment.database"),
            "default_collation": _optional(
                database, "collation", str, "", "environment.database"
            ),
            "table_prefix": _require(
                wordpress, "table_prefix", str, "environment.wordpress"
            ),
            "total_size_bytes": table_facts["total_size_bytes"],
            "tables": table_facts["tables"],
            "top_tables": table_facts["top_tables"],
        },
        "uploads": {
            "subdirectories": derive_uploads_subdirectories(files, uploads_dir),
        },
        "root": {
            "subdirectories": derive_root_subdirectories(files),
        },
        "content": {
            "subdirectories": derive_content_subdirectories(files, content_dir),
        },
        "plugins": {
            "active": active_plugins,
            "multilingual_active": multilingual_active,
            "multilingual_plugin": multilingual_plugin,
        },
        "dropins": _string_list(environment, "dropins", "environment"),
        "themes": derive_themes(files, content_dir),
        "mass_send": build_mass_send(
            _optional(bootstrap, "mass_send", dict, {}, "bootstrap")
        ),
        "attachments": _optional(bootstrap, "attachments", list, [], "bootstrap"),
        "entity_counts": build_entity_counts(
            _optional(bootstrap, "entity_counts", dict, {}, "bootstrap")
        ),
        "defines": build_defines(
            _optional(environment, "defines", list, [], "environment")
        ),
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
