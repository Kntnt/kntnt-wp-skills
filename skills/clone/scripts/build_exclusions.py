# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Assemble the resolved exclusion set — the single place it is built.

This helper is the deterministic assembler issue #35 introduces. Two consumers
depend on the resolved exclusion set: the extraction file selection (clone §5)
and the baseline manifest (clone §9.12, pull's diff). Before this helper each
consumer hand-assembled the set from the same ingredients, and any drift between
the two spellings poisoned the pull deletion diff — a file excluded on one side
but not the other surfaced as a spurious add or delete. This helper is the one
seam that produces the set, so both consumers pipe it the same two upstream
documents and get a byte-identical list back.

It reads one JSON object on stdin — ``{"classifications": <classify.py output>,
"plan": <resolve_plan.py output>}`` — and writes ``{"exclusions": [...]}`` on
stdout: the complete, anchored, deduped, sorted exclusion prefix list, exactly
the shape ``scripts/filter_manifest.py`` consumes as its ``exclusions`` field.
Nothing is hand-assembled at the call site; the helper does all extraction.

The set is the union of:

- :data:`ALWAYS_EXCLUDED` — the canonical, static always-excluded paths (the
  configuration file and its credential-bearing backup/swap/variant siblings,
  ``.env`` files anywhere in the tree, root-level SQL dumps and key material,
  the WordPress drop-ins, the debug log, the known cache-plugin and backup-tool
  trees, the plugin's own transfer-staging directories, the upgrade dirs, and
  the whole WordPress core tree — ``wp-admin/``, ``wp-includes/``, and the
  root-level core PHP files), the single source of truth every prose reference
  points at. Its uploads-level members are spelled at the standard uploads
  location and re-anchored on ``classifications.uploads_prefix`` when the site
  has moved it.
- The DB-known generated thumbnails (``classifications.thumbnails.exclude``),
  when the plan resolves ``generated_thumbnails`` to ``exclude``.
- The flagged heavy blobs (``classifications.blobs.flagged[*].path``), when the
  plan resolves ``heavy_blobs`` to ``exclude``.
- The whole uploads tree (``classifications.uploads_prefix``), when the plan
  resolves ``media_originals`` to ``exclude`` (``--exclude-media``).

Every path is anchored at the WordPress root — the one spelling the pack tar and
the baseline manifest match against; classify.py already anchors its thumbnail
and blob paths there, so the assembler adds only the
always-excluded constant and the uploads prefix, both already root-anchored. The always-excluded constant
guarantees the set is never empty, so ``filter_manifest.py`` keeps requiring a
non-empty list (an empty one signals an unresolved plan) without the assembler
ever emitting one.

Malformed input fails loudly — a non-zero exit and a ``build_exclusions:``
diagnostic on stderr, never a half-built set on stdout.
"""

from __future__ import annotations

import json
import sys
from typing import Any

# The configuration file, anywhere in the tree — production's belongs to
# production's server, and the local copy carries its own. A file named
# "wp-config.php" is a copy of the configuration file wherever it sits: a backup
# tool's staging copy, a duplicated install under a subdirectory, a developer's
# snapshot. None of them is content, and each carries the complete secret family
# in clear text, so none is ever asked for (issue #75, ADR-0031).
_CONFIGURATION_FILE: tuple[str, ...] = ("**/wp-config.php",)

# The credential-bearing siblings an operator can leave beside wp-config.php
# whose names admit no other reading: a dated or suffixed backup
# (".bak-20260717-212309", ".save", ".orig", ".old", ...) and an editor's tilde
# backup or swap file. Each carries the complete secret family in clear text
# exactly like the live file, so each is excluded on every run precisely as the
# configuration file itself is (issue #36). The differently-named variants
# ("wp-config-backup.php" and its kind) are the separate catcher below, because
# that shape alone can name something other than a configuration copy.
# Emacs leaves two more shapes no other entry here catches: "#wp-config.php#"
# is its auto-save file, holding that same secret family verbatim, and
# ".#wp-config.php" its lock file, naming the account and host editing it.
# The dot-prefixed configuration file is covered whole — ".wp-config.php"
# itself and whatever suffix follows it — rather than only vim's swap family
# (".wp-config.php.swp", ".wp-config.php.swo"), which is all the retired
# ".wp-config.php.sw?" entry ever reached: a ".bak", ".save", ".orig" or bare
# ".1" sits beside the config just as readily and holds the same secrets. It
# is two entries rather than one ".wp-config.php*" glob so the shape is
# exactly the Extractor's own /^\.wp-config\.php(\..+)?$/i and no wider,
# following the enumerate-rather-than-broaden reasoning below (issue #67).
# "wp-config.bak" / ".old" / ".orig" / ".save", with or without a trailing
# ".php", are the reordered backup names a manual edit leaves behind — the
# marker sits ahead of the extension rather than appended to it, so the
# "wp-config.php.*" catcher above never sees them. They are enumerated one by
# one rather than caught with a bare "wp-config.*", which would reach every
# name beginning "wp-config." and is broader than the shape being closed
# (issue #55).
# Every one of these basenames can *only* ever name a copy of the configuration
# file, so each is matched anywhere in the tree with the "**/" marker, exactly
# as the configuration file itself is and exactly as the Extractor matches the
# whole family against basename() at any depth (issue #75, ADR-0031).
_CONFIGURATION_FILE_VARIANTS: tuple[str, ...] = (
    "**/wp-config.php.*",
    "**/wp-config.php~",
    "**/.wp-config.php",
    "**/.wp-config.php.*",
    "**/#wp-config.php#",
    "**/.#wp-config.php",
    "**/wp-config.bak",
    "**/wp-config.bak.php",
    "**/wp-config.old",
    "**/wp-config.old.php",
    "**/wp-config.orig",
    "**/wp-config.orig.php",
    "**/wp-config.save",
    "**/wp-config.save.php",
)

# The one entry of the family that stays anchored at the install root. Unlike
# every shape above, "wp-config-<something>.php" is a basename an ordinary file
# can legitimately carry without being a copy of the configuration file at all —
# a plugin's "wp-config-loader.php", a theme's "wp-config-local.php" — so a
# nested one is read as content and kept, and the resulting divergence from the
# Extractor (which matches this entry by basename too) is accepted: it costs a
# resubmission under ADR-0024, where widening it would cost a legitimate file.
# It is also the only entry the "wp-config-sample.php" exception has to defend
# against, and leaving it root-anchored is what keeps that exception correct as
# an exact whole-path comparison: WordPress' own bundled template — placeholder
# values only, never a real secret — is sent at the install root because
# ``is_excluded`` in ``filter_manifest.py`` and ``baseline_diff.py`` carves it
# back out there, and anywhere else because no pattern in the family reaches it
# (issue #36, ADR-0031).
_CONFIGURATION_FILE_VARIANT_CATCHER: tuple[str, ...] = ("wp-config-*.php",)

# Environment-variable files, wherever they sit in the tree — never only at
# the install root, since a bundled toolchain (a Composer package, a Node
# build step under a theme) can carry its own alongside the WordPress one.
_ENV_FILES: tuple[str, ...] = (
    "**/.env",
    "**/.env.*",
)

# Root-level database dumps an operator left beside the install after a manual
# export — the whole database's secrets in clear text, sitting in the docroot.
_ROOT_SQL_DUMPS: tuple[str, ...] = (
    "*.sql",
    "*.sql.gz",
    "*.sql.zip",
)

# Root-level key material an operator dropped beside the install and forgot —
# a private key or certificate, never content. The "id_*" entries are OpenSSH's
# default key basenames in full, matched as prefixes so the "-sk" hardware-token
# variants ("id_ecdsa-sk", "id_ed25519-sk") come along with them (issue #55).
# The prefix deliberately catches the ".pub" sibling too: a public key is not a
# secret, but a public key at the install root is a strong signal the private
# one is lying beside it, and neither is site content.
_ROOT_KEY_MATERIAL: tuple[str, ...] = (
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
)

# The WordPress drop-ins, under wp-content/. Every core-recognised single-site
# and multisite drop-in name (WordPress' ``_get_dropins()``): each reconfigures
# the local install for production's infrastructure — an object cache pointed at
# a Redis the copy cannot reach, a maintenance page, a custom database class —
# so none is ever transferred. A drop-in a site does not have is simply a path
# the manifest never contains, so listing all of them is a harmless superset.
_DROP_INS: tuple[str, ...] = (
    "wp-content/advanced-cache.php",
    "wp-content/object-cache.php",
    "wp-content/db.php",
    "wp-content/db-error.php",
    "wp-content/install.php",
    "wp-content/maintenance.php",
    "wp-content/php-error.php",
    "wp-content/fatal-error-handler.php",
    "wp-content/sunrise.php",
    "wp-content/blog-deleted.php",
    "wp-content/blog-inactive.php",
    "wp-content/blog-suspended.php",
)

# The debug log, and the regenerable-locally cache and upgrade directories —
# all production runtime detritus, never content: the log is production's, a
# cache is rebuilt on demand, and the upgrade dirs are transient unpack space
# WordPress' own updater owns. ``_CACHES`` is the known cache-plugin trees, not
# just ``wp-content/cache``: a clone that carries LiteSpeed's hashed CSS or a
# W3 Total Cache object store is worse than useless.
_LOGS: tuple[str, ...] = ("wp-content/debug.log",)
_CACHES: tuple[str, ...] = (
    "wp-content/cache",
    "wp-content/litespeed",
    "wp-content/et-cache",
    "wp-content/w3tc-*",
)
_UPGRADE_DIRS: tuple[str, ...] = (
    "wp-content/upgrade",
    "wp-content/upgrade-temp-backup",
)

# The detritus that lives *inside* the uploads directory, named relative to it
# because the uploads directory is not always ``wp-content/uploads``: a site
# that moves it (a non-default ``WP_CONTENT_DIR``, an ``UPLOADS`` define) would
# otherwise carry every one of these, which is the failure this set exists to
# close. The resolved location is re-anchored on the classifications'
# ``uploads_prefix`` by :func:`uploads_level_exclusions`; the standard location
# below is the fallback spelling the static constant is built from, never a
# second source of truth about where uploads live.
#
# The backup tool's working directories are that tool's own scratch —
# yesterday's BackWPup restore log is never content. The Extractor's own three
# directories are a self-reference rather than a cache: the moment
# ``POST /extractions`` is accepted the plugin may create a new job directory
# and reclaim an old one, so a path in the selection can vanish because of the
# very run that selected it. They are listed by full name because a prefix of
# ``kntnt-extractor`` must not swallow a coincidental
# ``kntnt-extractor-something-else`` the site actually owns.
_UPLOADS_LEVEL: tuple[str, ...] = (
    "backwpup*",
    "kntnt-extractor",
    "kntnt-extractor-audit",
    "kntnt-extractor-downloads",
)

# The standard WordPress single-site uploads location relative to the site root,
# the fallback the static constant is spelled at.
_DEFAULT_UPLOADS_PREFIX = "wp-content/uploads"


def uploads_level_exclusions(uploads_prefix: str) -> tuple[str, ...]:
    """Anchor the uploads-level names on a resolved uploads location, so a site
    that moved its uploads directory excludes the same detritus the standard
    layout does — the plugin's own transfer staging above all, which a clone must
    never select."""

    prefix = uploads_prefix.rstrip("/")
    return tuple(f"{prefix}/{name}" for name in _UPLOADS_LEVEL)

# The whole WordPress core admin and includes trees, at the install root. Clone
# §4 scaffolds the exact core version with ``mkwp`` before extraction ever
# runs, so production's copy is always byte-identical to the scaffold's — never
# content, and never worth the network, disk, and merge cost of transferring
# (issue #37). ``GET /files``' manifest is install-root-wide, not scoped to
# content, so nothing on the server keeps these out; this exclusion is the only
# thing that does.
_CORE_DIRECTORIES: tuple[str, ...] = (
    "wp-admin",
    "wp-includes",
)

# The root-level core PHP files WordPress ships with every release — the same
# rationale as the core directories above. "wp-config-sample.php" is deliberately
# absent: it belongs to the configuration family's carve-out (issue #36's
# ``_ALWAYS_ALLOWED`` in ``filter_manifest.py``/``baseline_diff.py``), which this
# issue leaves untouched.
_CORE_ROOT_FILES: tuple[str, ...] = (
    "index.php",
    "license.txt",
    "readme.html",
    "wp-activate.php",
    "wp-blog-header.php",
    "wp-comments-post.php",
    "wp-cron.php",
    "wp-links-opml.php",
    "wp-load.php",
    "wp-login.php",
    "wp-mail.php",
    "wp-settings.php",
    "wp-signup.php",
    "wp-trackback.php",
    "xmlrpc.php",
)

# The canonical always-excluded set: the single source of truth for the paths
# excluded on every run regardless of any decision. Extended by the credential-
# bearing pattern family (#36) and the WordPress core tree (#37) above, never a
# second copy of this list elsewhere.
ALWAYS_EXCLUDED: tuple[str, ...] = (
    *_CONFIGURATION_FILE,
    *_CONFIGURATION_FILE_VARIANTS,
    *_CONFIGURATION_FILE_VARIANT_CATCHER,
    *_ENV_FILES,
    *_ROOT_SQL_DUMPS,
    *_ROOT_KEY_MATERIAL,
    *_DROP_INS,
    *_LOGS,
    *_CACHES,
    *uploads_level_exclusions(_DEFAULT_UPLOADS_PREFIX),
    *_UPGRADE_DIRS,
    *_CORE_DIRECTORIES,
    *_CORE_ROOT_FILES,
)

# The decisions whose resolved value gates a category into or out of the set, and
# the value at which the category is excluded.
_THUMBNAILS_DECISION = "generated_thumbnails"
_BLOBS_DECISION = "heavy_blobs"
_MEDIA_DECISION = "media_originals"
_EXCLUDE = "exclude"


class ExclusionError(Exception):
    """Raised when the input is malformed — a wrong top-level shape, a section of
    the wrong type, a plan missing a gating decision, or a media exclusion with no
    uploads prefix to anchor it on. The CLI turns this into a loud non-zero exit
    rather than emitting a partial set."""


def _object(value: Any, context: str) -> dict[str, Any]:
    """Assert a value is a JSON object, raising :class:`ExclusionError` otherwise —
    the boundary check that fails a malformed section loud instead of crashing on
    a key the value does not carry."""

    if not isinstance(value, dict):
        raise ExclusionError(f"{context}: expected an object, got {type(value).__name__}")
    return value


def _string_list(container: dict[str, Any], key: str, context: str) -> list[str]:
    """Read an optional list-of-strings field, defaulting to empty when absent and
    failing loud when present but not a list of strings — so a stray non-string
    never rides into the anchored set as a raw ``TypeError`` downstream."""

    value = container.get(key, [])
    if not isinstance(value, list):
        raise ExclusionError(
            f"{context}.{key} must be a list, got {type(value).__name__}"
        )
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ExclusionError(
                f"{context}.{key}[{index}] must be str, got {type(item).__name__}"
            )
    return value


def _flagged_paths(blobs: dict[str, Any]) -> list[str]:
    """Read the flagged heavy blobs' anchored paths from their ``{path, ...}``
    records, failing loud on a record that is not an object or lacks its string
    ``path`` rather than riding a pathless blob into the set."""

    flagged = blobs.get("flagged", [])
    if not isinstance(flagged, list):
        raise ExclusionError(
            f"classifications.blobs.flagged must be a list, got {type(flagged).__name__}"
        )
    paths: list[str] = []
    for index, record in enumerate(flagged):
        context = f"classifications.blobs.flagged[{index}]"
        if not isinstance(record, dict):
            raise ExclusionError(f"{context} must be an object, got {type(record).__name__}")
        path = record.get("path")
        if not isinstance(path, str):
            raise ExclusionError(f"{context}: missing a string 'path'")
        paths.append(path)
    return paths


def _decisions(plan: dict[str, Any]) -> dict[str, Any]:
    """Reduce the resolved plan's ordered decision list to an ``id -> value`` map.
    The gating decisions are all in both skills' lists, so a resolved plan always
    carries them; a decision list that is not a list of ``{id, value}`` records is
    malformed input."""

    decisions = plan.get("decisions")
    if not isinstance(decisions, list):
        raise ExclusionError(
            f"plan.decisions must be a list, got {type(decisions).__name__}"
        )
    resolved: dict[str, Any] = {}
    for index, entry in enumerate(decisions):
        context = f"plan.decisions[{index}]"
        if not isinstance(entry, dict):
            raise ExclusionError(f"{context} must be an object, got {type(entry).__name__}")
        decision_id = entry.get("id")
        if not isinstance(decision_id, str):
            raise ExclusionError(f"{context}: missing a string 'id'")
        if "value" not in entry:
            raise ExclusionError(f"{context}: missing required field 'value'")
        resolved[decision_id] = entry["value"]
    return resolved


def _required_decision(decisions: dict[str, Any], decision_id: str) -> Any:
    """Fetch a gating decision's resolved value, failing loud when the plan does
    not carry it — an unresolved plan is malformed input, never a silent default
    that could quietly change what is excluded."""

    if decision_id not in decisions:
        raise ExclusionError(f"plan.decisions is missing required decision {decision_id!r}")
    return decisions[decision_id]


def build_exclusions(payload: Any) -> dict[str, Any]:
    """Assemble the resolved exclusion set from the classifications and the
    resolved plan, gating the thumbnails, heavy blobs, and media categories by
    their resolved decisions and always including :data:`ALWAYS_EXCLUDED`."""

    # Reject a non-object payload at the untrusted stdin boundary before reading
    # any field off it.
    if not isinstance(payload, dict):
        raise ExclusionError(f"input: expected an object, got {type(payload).__name__}")

    # Read the two upstream documents the set is derived from: the classifications
    # supply the concrete paths, the plan supplies the gating decisions.
    classifications = _object(payload.get("classifications", {}), "classifications")
    decisions = _decisions(_object(payload.get("plan", {}), "plan"))

    # The canonical always-excluded paths — every run, regardless of any decision.
    prefixes: set[str] = set(ALWAYS_EXCLUDED)

    # Re-anchor the uploads-level names on this site's own uploads location, so a
    # moved uploads directory still drops the backup-tool scratch and the
    # Extractor's own staging. The constant already carries the standard spelling,
    # so a default layout adds nothing; a classifications document too old to
    # carry the prefix keeps exactly that standard spelling rather than failing —
    # only the media gate below needs the prefix badly enough to demand it.
    resolved_uploads = classifications.get("uploads_prefix")
    if isinstance(resolved_uploads, str) and resolved_uploads:
        prefixes.update(uploads_level_exclusions(resolved_uploads))

    # The DB-known generated thumbnails, when the plan resolves to excluding them
    # (the default — they are regenerated locally after import).
    if _required_decision(decisions, _THUMBNAILS_DECISION) == _EXCLUDE:
        thumbnails = _object(classifications.get("thumbnails", {}), "classifications.thumbnails")
        prefixes.update(_string_list(thumbnails, "exclude", "classifications.thumbnails"))

    # The flagged heavy blobs, when the gate resolves to excluding them.
    if _required_decision(decisions, _BLOBS_DECISION) == _EXCLUDE:
        blobs = _object(classifications.get("blobs", {}), "classifications.blobs")
        prefixes.update(_flagged_paths(blobs))

    # The whole uploads tree, when media originals are excluded (--exclude-media);
    # its prefix subsumes the thumbnail and blob paths already added, harmlessly.
    if _required_decision(decisions, _MEDIA_DECISION) == _EXCLUDE:
        uploads_prefix = classifications.get("uploads_prefix")
        if not isinstance(uploads_prefix, str) or not uploads_prefix:
            raise ExclusionError(
                "media originals are excluded but classifications carries no string "
                "'uploads_prefix' to anchor the exclusion on"
            )
        prefixes.add(uploads_prefix)

    # Normalise a trailing slash away so a prefix matches the same paths however it
    # was spelled, then present the set sorted and deduped.
    return {"exclusions": sorted({prefix.rstrip("/") for prefix in prefixes})}


def main() -> int:
    """Read the classifications and resolved plan on stdin, emit the resolved
    exclusion set on stdout, and fail loudly on malformed input with a non-zero
    exit and a stderr diagnostic."""

    # Parse the input, reporting a malformed payload rather than crashing.
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as error:
        print(f"build_exclusions: input is not valid JSON: {error}", file=sys.stderr)
        return 1

    # Assemble the set, turning any contract violation into a loud exit.
    try:
        result = build_exclusions(payload)
    except ExclusionError as error:
        print(f"build_exclusions: {error}", file=sys.stderr)
        return 1

    # Emit the resolved exclusion set, stably ordered so the output is reproducible.
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
