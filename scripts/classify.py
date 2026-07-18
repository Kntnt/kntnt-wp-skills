# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Turn the canonical discovery document into recommendation inputs.

This helper is the deterministic classifier seam of the transfer engine: it
reads the canonical discovery document (``scripts/discovery.py``'s output) as one
JSON object on stdin and writes the classifications the recommendations derive
from as one JSON object on stdout. It computes:

- ``defines`` — production's wp-config defines split into the auto-excluded
  credential / salt-nonce / domain-path / infrastructure classes and the
  remaining portable plugin/behaviour class offered at the gate. Auto-excluded
  values are dropped, never echoed, so a secret (a DB password, a salt) cannot
  ride back into model context.
- ``tables`` — each of production's tables split into full-data and empty
  (schema-only) by matching the operational-table patterns after the site's
  prefix; every table's structure is carried regardless, so this is a
  content-only verdict.
- ``blobs`` — the heavy-outlier upload subdirectories flagged for the exclusion
  gate by a deterministic size heuristic (same document in, same flags out).
- ``thumbnails`` — the exclude-set of DB-known generated sizes, with a registered
  original always kept even when its name collides with a derivative and
  side-loaded files never excluded (ADR-0011).
- ``project_name`` — the local DDEV project name derived from the production URL.

The classifier never decides: it produces the recommendation inputs the model
puts behind accept-or-override gates. Malformed input fails loudly — a non-zero
exit and a ``classify:`` diagnostic on stderr, never a half-built document on
stdout.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import PurePosixPath
from typing import Any

# The database-connection constants: production's belong to production's server,
# and the local DDEV site carries its own, so porting these would mis-key it.
CREDENTIAL_DEFINES = frozenset(
    {"DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "DB_CHARSET", "DB_COLLATE"}
)

# The eight WordPress auth keys, salts, and nonces; production secrets that never
# come down. Custom variants are caught by the *_SALT / NONCE_* patterns below.
SALT_NONCE_DEFINES = frozenset(
    {
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

# Domain and path constants describe production's layout, not the local copy's.
DOMAIN_PATH_DEFINES = frozenset(
    {"WP_HOME", "WP_SITEURL", "WP_CONTENT_DIR", "WP_CONTENT_URL", "ABSPATH"}
)

# Infrastructure constants: cache toggles and cron disabling by exact name, plus
# the cache-server host families by prefix (a local copy points at neither
# production's Redis nor its Memcached).
INFRASTRUCTURE_DEFINES = frozenset({"WP_CACHE", "DISABLE_WP_CRON"})
INFRASTRUCTURE_PREFIXES = ("WP_REDIS_", "WP_MEMCACHED_", "MEMCACHED_", "REDIS_")

# The operational-table families whose content is regenerated locally rather than
# carried: analytics, cookie-consent, email-log, and search-index. Each pattern
# is matched against a table name *after* the site's prefix is stripped, so a
# non-default prefix never hides an operational table. Ordered, first match wins.
OPERATIONAL_TABLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "analytics": ("independent_analytics", "statistics", "matomo", "koko_analytics"),
    "cookie_consent": ("rcb_consent", "borlabs_cookie", "cmplz", "cookie_consent"),
    "email_log": ("fsmpt_email_logs", "email_log", "mail_log", "wpmailsmtp"),
    "search_index": ("relevanssi", "searchwp"),
}

# A subdirectory is a heavy blob only when it clears an absolute floor *and*
# stands out from its peers — both together, so a uniformly large library is not
# flagged and a merely-ratio outlier below the floor is not worth a gate.
BLOB_ABSOLUTE_FLOOR_BYTES = 1 << 30  # 1 GiB.
BLOB_OUTLIER_MEDIAN_FACTOR = 3

# The DDEV hostname a derived project name is reachable at, appended to the name.
DDEV_TLD = "ddev.site"

# The fallback project name when a production host sanitises to nothing (an
# all-symbol label); the confirm gate lets the operator correct it.
FALLBACK_PROJECT_NAME = "site"


class ClassifyError(Exception):
    """Raised when the input is malformed — not an object, or a field that must
    be a list or object is neither. The CLI turns this into a loud non-zero exit
    rather than emitting a partial document."""


def _object(value: Any, context: str) -> dict[str, Any]:
    """Assert a value is a JSON object, raising :class:`ClassifyError` otherwise.
    This is the boundary check that makes a malformed section fail loud instead of
    crashing on an attribute the value does not have."""

    if not isinstance(value, dict):
        raise ClassifyError(f"{context}: expected an object, got {type(value).__name__}")
    return value


def _list(mapping: dict[str, Any], key: str, context: str) -> list[Any]:
    """Fetch an optional list, defaulting to empty when absent and raising
    :class:`ClassifyError` when present but not a list. A section a site genuinely
    lacks (no blobs, no attachments) is absent, never malformed."""

    value = mapping.get(key, [])
    if not isinstance(value, list):
        raise ClassifyError(
            f"{context}: field {key!r} must be a list, got {type(value).__name__}"
        )
    return value


def _record(value: Any, context: str) -> dict[str, Any]:
    """Assert a list element is a JSON object, raising :class:`ClassifyError`
    otherwise. This is the per-element guard that turns a malformed inner record —
    a non-object where a define, table, or attachment is expected — into a loud
    ``classify:`` diagnostic rather than an uncaught traceback, because the raw
    discovery seam passes these list elements through without validating each one.
    """

    if not isinstance(value, dict):
        raise ClassifyError(f"{context}: expected an object, got {type(value).__name__}")
    return value


def _field(record: dict[str, Any], key: str, expected: type, context: str) -> Any:
    """Fetch a required field from an inner record, asserting its type and raising
    :class:`ClassifyError` when it is absent or mistyped — so a record missing the
    very key the classifier reads (a define's or table's ``name``, an attachment's
    ``file``) fails loudly instead of crashing on a ``KeyError`` or an
    ``AttributeError`` deeper in."""

    if key not in record:
        raise ClassifyError(f"{context}: missing required field {key!r}")
    value = record[key]
    if not isinstance(value, expected):
        raise ClassifyError(
            f"{context}: field {key!r} must be {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    return value


def define_class(name: str) -> str | None:
    """Classify one define name into its auto-excluded class, or ``None`` when it
    is a portable plugin/behaviour define offered at the gate.

    The order resolves the rare overlaps deterministically: a credential, a
    domain/path, or an infrastructure constant is claimed by its own class before
    the broad salt/nonce pattern can reach it.
    """

    if name in CREDENTIAL_DEFINES:
        return "credentials"
    if name in DOMAIN_PATH_DEFINES:
        return "domain_paths"
    if name in INFRASTRUCTURE_DEFINES or name.startswith(INFRASTRUCTURE_PREFIXES):
        return "infrastructure"
    if name in SALT_NONCE_DEFINES or name.endswith("_SALT") or name.startswith("NONCE_"):
        return "salts_nonces"
    return None


def classify_defines(defines: list[Any]) -> dict[str, list[dict[str, Any]]]:
    """Split production's defines into the portable set offered at the gate and
    the auto-excluded set.

    A portable define carries its value, because it is written verbatim into the
    marked block; an auto-excluded define carries only its name and class — its
    value is deliberately dropped, since it is never written and some (a DB
    password, a salt) are secrets that must not enter model context.
    """

    portable: list[dict[str, Any]] = []
    auto_excluded: list[dict[str, Any]] = []
    for index, entry in enumerate(defines):
        context = f"defines[{index}]"
        record = _record(entry, context)
        name = _field(record, "name", str, context)
        classification = define_class(name)
        if classification is None:
            portable.append({"name": name, "value": record.get("value")})
        else:
            auto_excluded.append({"name": name, "class": classification})

    return {"portable": portable, "auto_excluded": auto_excluded}


def table_category(prefix: str, name: str) -> str | None:
    """Return the operational category a table belongs to, or ``None`` when its
    content is carried in full. The match is on the name after the prefix, so a
    non-default prefix never hides an operational table."""

    stem = name[len(prefix):] if prefix and name.startswith(prefix) else name
    for category, patterns in OPERATIONAL_TABLE_PATTERNS.items():
        if any(stem == pattern or stem.startswith(pattern) for pattern in patterns):
            return category
    return None


def classify_tables(prefix: str, tables: list[Any]) -> dict[str, list[Any]]:
    """Split the tables into full-data and empty (schema-only) by category.

    This is a content-only verdict: every table's structure is carried always, so
    an empty-classified table is created locally and left with zero rows.
    """

    full: list[str] = []
    empty: list[dict[str, str]] = []
    for index, table in enumerate(tables):
        context = f"top_tables[{index}]"
        record = _record(table, context)
        name = _field(record, "name", str, context)
        category = table_category(prefix, name)
        if category is None:
            full.append(name)
        else:
            empty.append({"name": name, "category": category})

    return {"full": full, "empty": empty}


def flag_blobs(subdirectories: list[Any]) -> dict[str, list[dict[str, Any]]]:
    """Flag the heavy-outlier upload subdirectories for the exclusion gate.

    A subdirectory is flagged only when it clears the absolute floor *and* is at
    least the outlier factor above the median subdirectory size. Both conditions
    are pure functions of the sizes, so the same document always yields the same
    flags — the determinism the gate relies on.
    """

    sizes = [int(subdir["size_bytes"]) for subdir in subdirectories]
    if not sizes:
        return {"flagged": []}

    # A blob must clear the absolute floor and stand out from the median together.
    median = statistics.median(sizes)
    outlier_threshold = median * BLOB_OUTLIER_MEDIAN_FACTOR
    flagged = [
        {
            "path": subdir["path"],
            "size_bytes": size,
            "reason": (
                f"{size} bytes: at or above the {BLOB_ABSOLUTE_FLOOR_BYTES}-byte "
                f"floor and at least {BLOB_OUTLIER_MEDIAN_FACTOR}x the "
                f"{int(median)}-byte median subdirectory"
            ),
        }
        for subdir in subdirectories
        if (size := int(subdir["size_bytes"])) >= BLOB_ABSOLUTE_FLOOR_BYTES
        and size >= outlier_threshold
    ]

    return {"flagged": flagged}


def thumbnail_exclude_set(attachments: list[Any]) -> list[str]:
    """Compute the exclude-set of DB-known generated sizes from attachment
    metadata.

    Each attachment's registered sizes are generated derivatives beside its
    original, and only DB-registered attachments can be regenerated locally — so
    the exclude-set is exactly those derivatives, minus any path that is itself
    some attachment's original. That subtraction is what keeps a same-named
    original (a ``photo-300x200.jpg`` uploaded in its own right) from being
    dropped as another attachment's look-alike derivative, and it is why
    side-loaded files — never in the metadata — are never excluded (ADR-0011).
    """

    originals: set[str] = set()
    derivatives: set[str] = set()
    for index, attachment in enumerate(attachments):
        context = f"attachments[{index}]"
        record = _record(attachment, context)
        original = _field(record, "file", str, context)
        originals.add(original)
        directory = PurePosixPath(original).parent
        for size_file in record.get("sizes", []):
            derivatives.add(str(directory / size_file))

    return sorted(derivatives - originals)


def derive_project_name(home_url: str) -> str:
    """Derive a local project name from the production URL: strip the scheme and a
    leading ``www.``, take the main label, and sanitise to the scaffolder's
    lowercase-alphanumeric-and-hyphen charset.

    There is no public-suffix-list dependency — the main label is simply the first
    host label, which the confirm gate lets the operator correct for an oddball
    domain (a subdomain, a multi-part TLD).
    """

    # Reduce the URL to its host: drop the scheme, then the path, any userinfo,
    # and any port.
    without_scheme = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", home_url.strip())
    host = without_scheme.split("/", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0]

    # Strip a leading www. label, then take the main (first) label.
    if host.lower().startswith("www."):
        host = host[len("www."):]
    label = host.split(".", 1)[0]

    # Sanitise to the scaffolder's charset, collapsing runs of invalid characters
    # to a single hyphen and trimming the edges; fall back when nothing survives.
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug or FALLBACK_PROJECT_NAME


def build_project_name(home_url: str) -> dict[str, str]:
    """Assemble the project-name recommendation: the derived name, its DDEV
    hostname, and the source URL it came from (so the confirm gate can show its
    provenance)."""

    name = derive_project_name(home_url)
    return {
        "name": name,
        "ddev_url": f"{name}.{DDEV_TLD}",
        "source_url": home_url,
    }


def classify(document: Any) -> dict[str, Any]:
    """Assemble every classification from the canonical discovery document.

    Each section the classifier reads is optional at this boundary — a site may
    genuinely lack blobs, attachments, or portable defines — but a section that is
    present must be well-shaped, or the input is malformed.
    """

    document = _object(document, "input")
    site = _object(document.get("site", {}), "site")
    database = _object(document.get("database", {}), "database")
    uploads = _object(document.get("uploads", {}), "uploads")

    return {
        "defines": classify_defines(_list(document, "defines", "input")),
        "tables": classify_tables(
            database.get("table_prefix", ""), _list(database, "top_tables", "database")
        ),
        "blobs": flag_blobs(_list(uploads, "subdirectories", "uploads")),
        "thumbnails": {
            "exclude": thumbnail_exclude_set(_list(document, "attachments", "input"))
        },
        "project_name": build_project_name(site.get("home_url", "")),
    }


def main() -> int:
    """Read the canonical document on stdin, emit the classifications on stdout,
    and fail loudly on malformed input with a non-zero exit and a stderr
    diagnostic."""

    raw_text = sys.stdin.read()

    # Parse the input, reporting a malformed payload rather than crashing.
    try:
        document = json.loads(raw_text)
    except json.JSONDecodeError as error:
        print(f"classify: input is not valid JSON: {error}", file=sys.stderr)
        return 1

    # Classify, turning any contract violation into a loud exit.
    try:
        classifications = classify(document)
    except ClassifyError as error:
        print(f"classify: {error}", file=sys.stderr)
        return 1

    json.dump(classifications, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
