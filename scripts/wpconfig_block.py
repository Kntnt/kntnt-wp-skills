# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Write the skills' marked block into ``wp-config.php``, computing collisions dynamically.

This helper is the deterministic seam that replaces the hand-surgery §9.4 once
prescribed. It takes the local ``wp-config.php`` text, the resolved portable
defines, production's table prefix, and the cron decision, and returns the new
full text with a single marked block written and every scaffold collision it
supersedes removed.

The block is delimited by the exact lines ``// BEGIN kntnt-wp-skills`` /
``// END kntnt-wp-skills``. When both markers are present the content between
them is replaced (idempotent re-run); when neither is present the whole block is
inserted immediately above the ``/* That's all, stop editing!`` line — its
absence is a contract violation, since there is nowhere safe to write.

The collision set is *computed*, never a hard-coded name list: before writing,
every ``define()`` line *outside* the block for a name in {the input defines} ∪
{``DISABLE_WP_CRON``}, and every ``$table_prefix`` assignment outside the block,
is removed — the portable set intersected with whatever the scaffold actually
shipped. The smoke test's scaffold carried five such collisions where the SKILL's
prose named two; a fixed list would leave three duplicate ``define()``s, and a
repeated ``define()`` on the same constant fatals (issue #42). Only the removals
and the block differ from the input; everything else is preserved verbatim.

Malformed input fails loudly — a non-zero exit and a ``wpconfig_block:``
diagnostic on stderr, never a half-written config.
"""

from __future__ import annotations

import json
import math
import re
import sys
from typing import Any

# The exact marker lines that delimit the block the skills own, and the anchor
# the block is inserted above when the markers are absent.
BEGIN_MARKER = "// BEGIN kntnt-wp-skills"
END_MARKER = "// END kntnt-wp-skills"
STOP_EDITING_ANCHOR = "That's all, stop editing"

# DISABLE_WP_CRON is always a collision candidate: on ``run`` the scaffold's copy
# must go so cron follows WordPress's default; on ``disabled`` the block writes
# its own. Either way any copy outside the block is removed.
CRON_DEFINE = "DISABLE_WP_CRON"

# A ``$table_prefix`` assignment anywhere outside the block, whatever its value.
TABLE_PREFIX_PATTERN = re.compile(r"^\s*\$table_prefix\s*=")

# A PHP constant identifier: letter/underscore/high-byte start, then letters,
# digits, underscores, high bytes. A name outside this shape — crossing the
# remote-to-local trust boundary from production's wp-config — is rejected, since
# interpolating a quote-bearing name into ``define('NAME', …)`` would inject
# syntactically valid PHP that ``php -l`` cannot catch (issue #42).
DEFINE_NAME_PATTERN = re.compile(r"^[A-Za-z_\x80-\xff][A-Za-z0-9_\x80-\xff]*$")


class WpConfigBlockError(Exception):
    """Raised when the input is malformed or the config has no place to write the
    block. The CLI turns this into a loud non-zero exit rather than emitting a
    half-written config."""


def _define_pattern(name: str) -> re.Pattern[str]:
    """A pattern matching a ``define('NAME', …`` line for ``name`` under either
    quote style — the shape a scaffold collision takes."""

    return re.compile(rf"^\s*define\s*\(\s*['\"]{re.escape(name)}['\"]")


def _php_literal(value: Any) -> str:
    """Render a JSON scalar as its PHP literal: bool and null as bare keywords,
    int and float bare, string single-quoted with backslash and quote escaped.
    A non-scalar (object or array) is a contract violation.

    ``bool`` is checked before ``int`` because ``isinstance(True, int)`` is true
    in Python; rendering ``True`` as ``1`` would silently change the value."""

    if isinstance(value, bool):
        return "true" if value else "false"

    if value is None:
        return "null"

    if isinstance(value, (int, float)):

        # NaN/Infinity survive json.loads and render via str() as bare
        # nan/inf/-inf — valid PHP (an undefined-constant fetch) that php -l
        # passes but PHP 8 fatals on at runtime, the exact issue #42 failure.
        if isinstance(value, float) and not math.isfinite(value):
            raise WpConfigBlockError(
                f"define value must be a finite number, got {value}"
            )

        return str(value)

    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

    raise WpConfigBlockError(
        f"define value must be a JSON scalar, got {type(value).__name__}"
    )


def _defines(value: Any) -> list[tuple[str, Any]]:
    """Read the ordered ``{name, value}`` define records, failing loud on a record
    that is not an object, lacks a string ``name``, carries a name outside the PHP
    constant-identifier shape, duplicates an earlier name, or is ``DISABLE_WP_CRON``
    — whose handling is exclusively the ``cron`` field's job. A duplicate or a
    stray ``DISABLE_WP_CRON`` would emit two ``define()``s on one constant, a PHP
    runtime fatal ``php -l`` cannot catch (issue #42)."""

    if not isinstance(value, list):
        raise WpConfigBlockError(
            f"defines must be a list, got {type(value).__name__}"
        )
    records: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(value):
        context = f"defines[{index}]"

        # Validate the record's shape and its name at the trust boundary.
        if not isinstance(record, dict):
            raise WpConfigBlockError(
                f"{context} must be an object, got {type(record).__name__}"
            )
        name = record.get("name")
        if not isinstance(name, str):
            raise WpConfigBlockError(f"{context}: missing a string 'name'")
        if not DEFINE_NAME_PATTERN.match(name):
            raise WpConfigBlockError(
                f"{context}: '{name}' is not a valid PHP constant name"
            )

        # Reject the two duplicate-define() paths php -l cannot catch: a name
        # repeated in the input, and DISABLE_WP_CRON smuggled in alongside its own
        # dedicated cron field.
        if name == CRON_DEFINE:
            raise WpConfigBlockError(
                f"{context}: {CRON_DEFINE} must not appear in defines; "
                "it is written solely from the 'cron' field"
            )
        if name in seen:
            raise WpConfigBlockError(f"{context}: duplicate define name '{name}'")
        seen.add(name)

        records.append((name, record.get("value")))
    return records


def _build_block(
    defines: list[tuple[str, Any]], table_prefix: str, cron: str
) -> list[str]:
    """Assemble the marked block's lines: one ``define()`` per input define in
    order, ``DISABLE_WP_CRON`` appended iff cron is disabled, the prefix last,
    bracketed by the markers."""

    lines = [BEGIN_MARKER]
    lines += [f"define('{name}', {_php_literal(value)});" for name, value in defines]
    if cron == "disabled":
        lines.append(f"define('{CRON_DEFINE}', true);")
    lines.append(f"$table_prefix = {_php_literal(table_prefix)};")
    lines.append(END_MARKER)
    return lines


def _block_span(lines: list[str]) -> tuple[int, int] | None:
    """Locate the existing marked block as an inclusive ``(begin, end)`` index
    pair, or ``None`` when neither marker is present. A lone marker — one without
    its partner — is a contract violation."""

    begin = next((i for i, line in enumerate(lines) if line.strip() == BEGIN_MARKER), None)
    end = next((i for i, line in enumerate(lines) if line.strip() == END_MARKER), None)

    if begin is None and end is None:
        return None
    if begin is None or end is None or begin > end:
        raise WpConfigBlockError(
            "wp-config has a mismatched marked block: exactly one of the "
            "BEGIN/END markers is present, or they are out of order"
        )
    return begin, end


def _collision_names(defines: list[tuple[str, Any]]) -> list[str]:
    """The computed collision set: the input define names plus ``DISABLE_WP_CRON``.
    The boundary already rejected duplicate names and a ``DISABLE_WP_CRON`` in the
    input, so this list is collision-free by construction."""

    return [name for name, _ in defines] + [CRON_DEFINE]


def _is_collision(line: str, patterns: list[tuple[str, re.Pattern[str]]]) -> str | None:
    """The name of the colliding define this line defines, or ``None`` — the
    first pattern that matches wins."""

    return next((name for name, pattern in patterns if pattern.match(line)), None)


def write_block(payload: Any) -> dict[str, Any]:
    """Write the marked block into ``wp-config.php`` and remove the scaffold
    collisions it supersedes, returning the new full text, the removed define
    names, and the block text."""

    if not isinstance(payload, dict):
        raise WpConfigBlockError(f"input must be an object, got {type(payload).__name__}")

    # Read and validate the envelope's four inputs at the boundary.
    wp_config = payload.get("wp_config")
    if not isinstance(wp_config, str):
        raise WpConfigBlockError("wp_config must be a string")
    table_prefix = payload.get("table_prefix")
    if not isinstance(table_prefix, str):
        raise WpConfigBlockError("table_prefix must be a string")
    cron = payload.get("cron")
    if cron not in ("run", "disabled"):
        raise WpConfigBlockError("cron must be 'run' or 'disabled'")
    defines = _defines(payload.get("defines", []))

    # Assemble the block up front so a bad literal fails before any line is touched.
    block_lines = _build_block(defines, table_prefix, cron)

    # Compute the collision set from the plan, never a hard-coded name list.
    collision_patterns = [(name, _define_pattern(name)) for name in _collision_names(defines)]

    lines = wp_config.split("\n")
    span = _block_span(lines)

    # Partition the config into the region inside the block (untouched by removal)
    # and everything outside it, so a define the block itself writes is never
    # mistaken for a scaffold collision.
    if span is None:
        inside_range: range = range(0, 0)
    else:
        begin, end = span
        inside_range = range(begin, end + 1)

    # Walk the config, dropping every colliding define and stray table_prefix
    # assignment outside the block, and splicing the fresh block in place of the
    # old one (markers present) or above the stop-editing anchor (markers absent).
    output: list[str] = []
    removed: list[str] = []
    block_written = False
    inserted_anchor = span is not None
    for index, line in enumerate(lines):

        # Replace the existing block wholesale at its first line; skip the rest of
        # its span so the old content is dropped.
        if span is not None and index in inside_range:
            if index == span[0]:
                output.extend(block_lines)
                block_written = True
            continue

        # Insert the block above the stop-editing anchor when there was no block.
        if not inserted_anchor and STOP_EDITING_ANCHOR in line:
            output.extend(block_lines)
            block_written = True
            inserted_anchor = True
            output.append(line)
            continue

        # Drop a colliding define or a stray table_prefix outside the block,
        # recording the removed define name once.
        collision = _is_collision(line, collision_patterns)
        if collision is not None:
            if collision not in removed:
                removed.append(collision)
            continue
        if TABLE_PREFIX_PATTERN.match(line):
            continue

        output.append(line)

    # A config with no block and no anchor has nowhere safe to write.
    if not block_written:
        raise WpConfigBlockError(
            "wp-config has no marked block and no '/* That's all, stop editing!' "
            "line to insert the block above"
        )

    return {
        "wp_config": "\n".join(output),
        "removed": removed,
        "block": "\n".join(block_lines),
    }


def main() -> int:
    """Read the envelope on stdin, emit the result on stdout, and fail loudly on
    malformed input with a non-zero exit and a stderr diagnostic."""

    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as error:
        print(f"wpconfig_block: input is not valid JSON: {error}", file=sys.stderr)
        return 1

    try:
        result = write_block(payload)
    except WpConfigBlockError as error:
        print(f"wpconfig_block: {error}", file=sys.stderr)
        return 1

    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
