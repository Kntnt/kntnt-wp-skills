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
  (schema-only) by matching the operational-table patterns and the
  user-submission patterns after the site's prefix; every table's structure is
  carried regardless, so this is a content-only verdict. A user-submission table
  is tagged with its own ``user_submissions`` category, distinct from the four
  operational ones, because it earns a standalone gate rather than being
  silently emptied (ADR-0014).
- ``blobs`` — the heavy-outlier upload subdirectories flagged for the exclusion
  gate by a deterministic size heuristic (same document in, same flags out).
- ``thumbnails`` — the exclude-set of DB-known generated sizes, with a registered
  original always kept even when its name collides with a derivative and
  side-loaded files never excluded (ADR-0011).
- ``project_name`` — the name-derivation recommendation: the local DDEV project
  name (a sanitised, hostname-safe slug) and the clone's directory name (the
  production host verbatim), both derived from the production URL.

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

# The user-submission table family: form/entry data from WS Form, Fluent Forms,
# Formidable, WPForms, and Gravity Forms — real names, emails, and messages, the
# most privacy-sensitive content the transfer handles. Matched the same way as
# the operational patterns (after prefix-stripping), but kept as its own family
# rather than folded into OPERATIONAL_TABLE_PATTERNS: unlike those four, which
# are silently emptied, this one earns a standalone carry/empty gate, default
# empty for privacy minimisation (ADR-0014).
USER_SUBMISSION_TABLE_PATTERNS: tuple[str, ...] = (
    "wsf_submit",
    "wsf_submit_meta",
    "fluentform_submissions",
    "fluentform_submission_meta",
    "fluentform_entry_details",
    "frm_items",
    "frm_item_metas",
    "wpforms_entries",
    "wpforms_entry_meta",
    "wpforms_entry_fields",
    "gf_entry",
    "gf_entry_meta",
    "gf_entry_notes",
)

# A subdirectory is a heavy blob only when it clears an absolute floor *and*
# stands out from its peers — both together, so a uniformly large library is not
# flagged and a merely-ratio outlier below the floor is not worth a gate.
BLOB_ABSOLUTE_FLOOR_BYTES = 1 << 30  # 1 GiB.
BLOB_OUTLIER_MEDIAN_FACTOR = 3

# The standard WordPress single-site uploads location relative to the site root.
# The exclusion set has one consumer-facing anchor — WordPress-root-relative paths
# (the pack tar's `--anchored -C "$SOURCE_ROOT"` and the baseline manifest's
# root-relative entries both silently no-match anything else) — and this is the
# fallback when a document omits the absolute paths to derive it from. It is the
# same layout templates/manifest.php assumes.
DEFAULT_UPLOADS_ROOT_RELATIVE = "wp-content/uploads"

# The DDEV hostname a derived project name is reachable at, appended to the name.
DDEV_TLD = "ddev.site"

# The fallback the project name and the directory name share when a production
# host yields nothing to work with — sanitises to an all-symbol label for the
# slug, or strips away to no host at all for the directory; the confirm gate
# lets the operator correct either.
FALLBACK_NAME = "site"

# The traversal-shaped hosts a pathological home_url (e.g. "https://../x") can
# reduce to. Unlike the project-name slug, the directory name is carried
# verbatim into "mkwp --dirname=<...>" under --yes, so these two literal names
# are floored to FALLBACK_NAME rather than allowed to resolve outside the
# operator's current directory.
PATH_UNSAFE_DIRECTORY_NAMES = frozenset({".", ".."})


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
    ``file``, a subdirectory's ``size_bytes``) fails loudly instead of crashing on
    a ``KeyError`` or a ``TypeError`` deeper in."""

    if key not in record:
        raise ClassifyError(f"{context}: missing required field {key!r}")
    value = record[key]
    if not isinstance(value, expected):
        raise ClassifyError(
            f"{context}: field {key!r} must be {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    return value


def _string_list(record: dict[str, Any], key: str, context: str) -> list[str]:
    """Fetch an optional list-of-strings field from an inner record: default empty
    when absent, and raise :class:`ClassifyError` when it is not a list or holds a
    non-string element. This is the per-element guard the thumbnail exclude-set
    needs so a stray non-string size never reaches the path join as a raw
    ``TypeError`` — the same branded fail-loud story :func:`_record` and
    :func:`_field` give defines and attachments, and the inline check in
    :func:`classify_tables` gives the table enumeration."""

    values = _list(record, key, context)
    for index, value in enumerate(values):
        if not isinstance(value, str):
            raise ClassifyError(
                f"{context}: field {key!r}[{index}] must be str, "
                f"got {type(value).__name__}"
            )
    return values


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
    """Return the category a table belongs to — one of the four operational
    families or ``user_submissions`` — or ``None`` when its content is carried in
    full. The match is on the name after the prefix, so a non-default prefix
    never hides an operational or user-submission table.

    ``user_submissions`` is checked first: it is disjoint from the operational
    patterns, but keeping it first documents that it is a distinct family with
    its own gate (ADR-0014), not a fifth operational category folded into the
    silently-emptied set.
    """

    stem = name[len(prefix):] if prefix and name.startswith(prefix) else name
    if any(stem == pattern or stem.startswith(pattern) for pattern in USER_SUBMISSION_TABLE_PATTERNS):
        return "user_submissions"
    for category, patterns in OPERATIONAL_TABLE_PATTERNS.items():
        if any(stem == pattern or stem.startswith(pattern) for pattern in patterns):
            return category
    return None


def classify_tables(prefix: str, tables: list[Any]) -> dict[str, list[Any]]:
    """Split every one of production's tables into full-data and empty
    (schema-only) by category.

    The input is the complete table enumeration (``database.tables``) — every
    table name, never the heaviest-N report artifact (``top_tables``) — so the two
    lists together cover every table: the "all tables, always" cornerstone the
    dump relies on so the local copy never hits a missing table (user story 16).
    This is a content-only verdict: every table's structure is carried regardless,
    so an empty-classified table is created locally and left with zero rows. A
    non-string entry earns the branded ``classify:`` fail-loud diagnostic rather
    than an uncaught traceback from the pattern match, since the raw discovery seam
    passes these list elements through without validating each one.
    """

    full: list[str] = []
    empty: list[dict[str, str]] = []
    for index, name in enumerate(tables):
        context = f"tables[{index}]"
        if not isinstance(name, str):
            raise ClassifyError(f"{context}: expected str, got {type(name).__name__}")
        category = table_category(prefix, name)
        if category is None:
            full.append(name)
        else:
            empty.append({"name": name, "category": category})

    return {"full": full, "empty": empty}


def uploads_root_relative(site: dict[str, Any]) -> PurePosixPath:
    """Return the uploads directory as a path relative to the WordPress root — the
    single anchor every exclusion consumer requires.

    The flagged blobs and thumbnail exclude-set are matched by the pack tar
    (``--exclude-from --anchored -C "$SOURCE_ROOT"``) and the baseline manifest,
    both of which spell paths relative to the site root (``wp-content/uploads/...``);
    an exclusion anchored any other way silently no-matches. The prefix is derived
    from the document's own absolute ``root_path`` and ``uploads_base`` when both
    are present — so a non-default content directory is honoured — and falls back to
    the standard single-site location otherwise. An uploads directory outside the
    root cannot be expressed as a root-relative prefix, so it fails loudly rather
    than emitting a wrong anchor.
    """

    root = site.get("root_path", "")
    uploads = site.get("uploads_base", "")
    if not (isinstance(root, str) and root and isinstance(uploads, str) and uploads):
        return PurePosixPath(DEFAULT_UPLOADS_ROOT_RELATIVE)

    try:
        return PurePosixPath(uploads).relative_to(PurePosixPath(root))
    except ValueError:
        raise ClassifyError(
            f"uploads_base {uploads!r} is not under root_path {root!r}: "
            "the exclusion set cannot be anchored at the WordPress root"
        )


def flag_blobs(
    uploads_prefix: PurePosixPath, subdirectories: list[Any]
) -> dict[str, list[dict[str, Any]]]:
    """Flag the heavy-outlier upload subdirectories for the exclusion gate.

    A subdirectory is flagged only when it clears the absolute floor *and* is at
    least the outlier factor above the median subdirectory size. Both conditions
    are pure functions of the sizes, so the same document always yields the same
    flags — the determinism the gate relies on. Each flagged path is anchored at
    the WordPress root (``uploads_prefix`` joined onto the subdirectory name), the
    one spelling the pack tar and the baseline manifest match against.
    """

    # Validate each subdirectory element and read its path and size once, so a
    # malformed blob record earns the branded `classify:` diagnostic rather than a
    # raw KeyError/TypeError from the size read — the raw discovery seam passes
    # these list elements through without validating each one.
    blobs: list[tuple[str, int]] = []
    for index, subdir in enumerate(subdirectories):
        context = f"uploads.subdirectories[{index}]"
        record = _record(subdir, context)
        path = _field(record, "path", str, context)
        size = _field(record, "size_bytes", int, context)
        blobs.append((path, size))

    sizes = [size for _, size in blobs]
    if not sizes:
        return {"flagged": []}

    # A blob must clear the absolute floor and stand out from the median together.
    median = statistics.median(sizes)
    outlier_threshold = median * BLOB_OUTLIER_MEDIAN_FACTOR
    flagged = [
        {
            "path": str(uploads_prefix / path),
            "size_bytes": size,
            "reason": (
                f"{size} bytes: at or above the {BLOB_ABSOLUTE_FLOOR_BYTES}-byte "
                f"floor and at least {BLOB_OUTLIER_MEDIAN_FACTOR}x the "
                f"{int(median)}-byte median subdirectory"
            ),
        }
        for path, size in blobs
        if size >= BLOB_ABSOLUTE_FLOOR_BYTES and size >= outlier_threshold
    ]

    return {"flagged": flagged}


def thumbnail_exclude_set(
    uploads_prefix: PurePosixPath, attachments: list[Any]
) -> list[str]:
    """Compute the exclude-set of DB-known generated sizes from attachment
    metadata.

    Each attachment's registered sizes are generated derivatives beside its
    original, and only DB-registered attachments can be regenerated locally — so
    the exclude-set is exactly those derivatives, minus any path that is itself
    some attachment's original. That subtraction is what keeps a same-named
    original (a ``photo-300x200.jpg`` uploaded in its own right) from being
    dropped as another attachment's look-alike derivative, and it is why
    side-loaded files — never in the metadata — are never excluded (ADR-0011).

    The attachment ``file`` and its ``sizes`` are uploads-relative (WordPress'
    ``_wp_attached_file``), so the resolved exclusions are re-anchored at the
    WordPress root via ``uploads_prefix`` — the one spelling the pack tar and the
    baseline manifest match against. The subtraction runs before the re-anchoring,
    in the uploads-relative space both sets share, so the original-wins-collision
    rule is unaffected.
    """

    originals: set[str] = set()
    derivatives: set[str] = set()
    for index, attachment in enumerate(attachments):
        context = f"attachments[{index}]"
        record = _record(attachment, context)
        original = _field(record, "file", str, context)
        originals.add(original)
        directory = PurePosixPath(original).parent
        for size_file in _string_list(record, "sizes", context):
            derivatives.add(str(directory / size_file))

    return sorted(str(uploads_prefix / path) for path in derivatives - originals)


def _extract_host(home_url: str) -> str:
    """Reduce a production URL to its bare host: drop the scheme, then the path,
    any userinfo, and any port. This is the shared first step both the DDEV
    project-name slug and the clone directory name derive from — the two then
    diverge on what they do with the host."""

    without_scheme = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", home_url.strip())
    return without_scheme.split("/", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0]


def derive_project_name(home_url: str) -> str:
    """Derive the local DDEV project name from the production URL: strip the
    scheme and a leading ``www.``, take the main label, and sanitise to the
    scaffolder's lowercase-alphanumeric-and-hyphen charset — a valid hostname
    label, since it also names the DDEV domain.

    There is no public-suffix-list dependency — the main label is simply the first
    host label, which the confirm gate lets the operator correct for an oddball
    domain (a subdomain, a multi-part TLD).
    """

    # Reduce to the bare host, strip a leading www. label, then take the main
    # (first) label.
    host = _extract_host(home_url)
    if host.lower().startswith("www."):
        host = host[len("www."):]
    label = host.split(".", 1)[0]

    # Sanitise to the scaffolder's charset, collapsing runs of invalid characters
    # to a single hyphen and trimming the edges; fall back when nothing survives.
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug or FALLBACK_NAME


def derive_directory_name(home_url: str) -> str:
    """Derive the clone's directory name from the production URL: the host
    verbatim, once the scheme, any userinfo, any port, and the path are
    stripped — keeping ``www.`` and every dot, and preserving case, so the
    directory mirrors the operator's full original host rather than the
    sanitised, hostname-safe DDEV project name.

    Falls back to :data:`FALLBACK_NAME` when stripping leaves no host at all (an
    empty or host-less URL), the same oddball floor :func:`derive_project_name`
    uses, so the confirm gate always has a name to present and correct — and
    likewise when the extracted host is itself traversal-shaped (``.`` or
    ``..``), the path-safety floor :data:`PATH_UNSAFE_DIRECTORY_NAMES` closes,
    since this value is carried verbatim into ``mkwp --dirname=<...>``.
    """

    host = _extract_host(home_url)
    if host in PATH_UNSAFE_DIRECTORY_NAMES:
        return FALLBACK_NAME
    return host or FALLBACK_NAME


def build_project_name(home_url: str) -> dict[str, str]:
    """Assemble the name-derivation recommendation: the DDEV project slug and its
    DDEV hostname, the clone's directory name, and the source URL both came from
    (so the confirm gate can show its provenance and let the operator correct
    either name independently)."""

    name = derive_project_name(home_url)
    return {
        "name": name,
        "directory_name": derive_directory_name(home_url),
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

    # Anchor the exclusion set at the WordPress root once, so the flagged blobs and
    # the thumbnail exclude-set share the one spelling their consumers match against.
    uploads_prefix = uploads_root_relative(site)

    return {
        "defines": classify_defines(_list(document, "defines", "input")),
        "tables": classify_tables(
            database.get("table_prefix", ""), _list(database, "tables", "database")
        ),
        "blobs": flag_blobs(
            uploads_prefix, _list(uploads, "subdirectories", "uploads")
        ),
        "thumbnails": {
            "exclude": thumbnail_exclude_set(
                uploads_prefix, _list(document, "attachments", "input")
            )
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
