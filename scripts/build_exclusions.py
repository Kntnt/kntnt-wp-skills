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
  configuration file, the WordPress drop-ins, the debug log, the cache dir, and
  the upgrade dirs), the single source of truth every prose reference points at.
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

# The configuration file, at the install root — production's belongs to
# production's server, and the local copy carries its own.
_CONFIGURATION_FILE: tuple[str, ...] = ("wp-config.php",)

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

# The debug log, and the regenerable-locally cache and upgrade directories — all
# production runtime detritus, never content: the log is production's, the cache
# is rebuilt on demand, and the upgrade dirs are transient unpack scratch space
# WordPress' own updater owns.
_LOGS: tuple[str, ...] = ("wp-content/debug.log",)
_CACHES: tuple[str, ...] = ("wp-content/cache",)
_UPGRADE_DIRS: tuple[str, ...] = (
    "wp-content/upgrade",
    "wp-content/upgrade-temp-backup",
)

# The canonical always-excluded set: the single source of truth for the paths
# excluded on every run regardless of any decision. Extended by the two child
# issues this one unblocks — the credential-bearing pattern family (#36) and the
# WordPress core tree (#37) — each adding its own group above, never a second
# copy of this list elsewhere.
ALWAYS_EXCLUDED: tuple[str, ...] = (
    *_CONFIGURATION_FILE,
    *_DROP_INS,
    *_LOGS,
    *_CACHES,
    *_UPGRADE_DIRS,
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
