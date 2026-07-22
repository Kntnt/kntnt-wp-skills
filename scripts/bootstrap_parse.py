# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Parse the reassembled bootstrap extraction into the row-derived discovery signals.

This helper is the client-side seam that replaces the retired ``discovery.php``
row-level scan (ADR-0016, ADR-0017). Two-phase discovery downloads a cheap
bootstrap extraction — ``wp_posts``, ``wp_postmeta``, ``wp_users``, the active
recognised-mailer tables, and Action Scheduler — which ``unseal.py`` reassembles
into one importable ``.sql``. That dump holds the three signals the main
extraction's classification needs but which live only in rows, not in the
``environment``/``tables``/``files`` REST surface:

- ``attachments`` — each attachment's original file and its registered generated
  sizes, the input ``classify.py`` derives the thumbnail exclude-set from.
- ``entity_counts`` — the published-post, published-page, live-attachment, and
  user counts the verify phase's expectations object sources.
- ``mass_send`` — the per-engine poised-campaign scan and the unrecognised-mailer
  fallback signal, the facts ``discovery.py``'s ``build_mass_send`` turns into the
  mail flip.

The output is the exact ``{attachments, entity_counts, mass_send}`` shape the old
server-side scan produced, so ``discovery.py`` consumes it unchanged. Malformed
input fails loudly — a non-zero exit and a ``bootstrap_parse:`` diagnostic on
stderr, never a half-built signals document on stdout.

## Dump format (from Kntnt Extractor ``Table_Dumper``)

Each table is a verbatim ``SHOW CREATE TABLE`` structure block (``DROP TABLE`` +
``CREATE TABLE``) followed by column-**less** extended ``INSERT`` statements
(``INSERT INTO `t` VALUES (…),(…);``). Column order therefore follows the
``CREATE TABLE`` definition, and every value is emitted as either ``NULL`` or a
single-quoted string literal escaping ``\\``, ``'``, NUL, newline, CR, and Ctrl-Z.
Real newlines in data are escaped, so every ``INSERT`` is one physical line and
the dump can be walked line by line.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# The recognised on-site bulk-mail engines whose campaign tables the bootstrap
# carries, each with the table (after the site prefix) and the columns the poised
# scan reads. The cloud senders (Mailchimp for WP, Brevo) never blast from the
# local copy, so they have no on-site campaign table and are never poised here.
MAILER_ENGINES: dict[str, dict[str, Any]] = {
    "fluentcrm": {
        "table": "fc_campaigns",
        "poised_statuses": {"scheduled", "working"},
        "campaign_column": "title",
        "count_column": "recipients_count",
    },
    "mailpoet": {
        "table": "mailpoet_newsletters",
        "poised_statuses": {"scheduled"},
        "campaign_column": "subject",
        # MailPoet sizes its list only at send time, so no countable column here.
        "count_column": None,
    },
    "newsletter": {
        "table": "newsletter_emails",
        "poised_statuses": {"sending"},
        "campaign_column": "subject",
        "count_column": "total",
    },
}

# Action Scheduler's table (after the prefix) and the hook-name pattern that
# marks a send-shaped pending action — the unrecognised-mailer generic signal.
ACTIONSCHEDULER_TABLE = "actionscheduler_actions"
SENDING_HOOK_PATTERN = re.compile(r"send|mail|newsletter|campaign|queue", re.IGNORECASE)

# The unescaping map inverting ``Table_Dumper::literal``'s ``strtr``: each escape
# sequence back to the byte it stood for. Any other ``\x`` collapses to ``x``.
UNESCAPE = {"\\": "\\", "'": "'", "0": "\0", "n": "\n", "r": "\r", "Z": "\x1a"}


class BootstrapError(Exception):
    """Raised when the dump is malformed or missing a table the bootstrap always
    carries. The CLI turns this into a loud non-zero exit rather than emitting a
    partial signals document."""


class Table:
    """One parsed table: its ordered column names and its rows as name→value
    mappings, so the domain scans below read by column name rather than by a
    brittle positional index."""

    def __init__(self, columns: list[str]) -> None:
        self.columns = columns
        self.rows: list[dict[str, str | None]] = []

    def add_tuple(self, values: list[str | None]) -> None:
        """Map one column-less ``INSERT`` tuple onto the column names. A tuple
        whose arity does not match the definition is a malformed dump."""

        if len(values) != len(self.columns):
            raise BootstrapError(
                f"a row has {len(values)} values but the table has "
                f"{len(self.columns)} columns"
            )
        self.rows.append(dict(zip(self.columns, values)))


# --- SQL parsing ------------------------------------------------------------


def _parse_string_literal(text: str, start: int) -> tuple[str, int]:
    """Read a single-quoted, backslash-escaped string literal beginning at the
    opening quote ``text[start]``; return the unescaped value and the index just
    past the closing quote. A literal that never closes is a malformed dump."""

    chars: list[str] = []
    index = start + 1
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            if index + 1 >= length:
                break
            chars.append(UNESCAPE.get(text[index + 1], text[index + 1]))
            index += 2
            continue
        if char == "'":
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    raise BootstrapError("an INSERT value has an unterminated string literal")


def _parse_values(text: str) -> list[list[str | None]]:
    """Parse the ``VALUES`` clause — ``(v,…),(v,…);`` — into a list of tuples,
    each a list of strings and ``None``s. Every value is either ``NULL`` or a
    quoted string literal, so a value that is neither is a malformed dump."""

    tuples: list[list[str | None]] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in " \t\r\n,":
            index += 1
            continue
        if char == ";":
            break
        if char != "(":
            raise BootstrapError("expected a value tuple in an INSERT statement")

        # Read one parenthesised tuple of NULL / quoted-string values.
        row: list[str | None] = []
        index += 1
        while index < length:
            inner = text[index]
            if inner in " \t\r\n,":
                index += 1
                continue
            if inner == ")":
                index += 1
                break
            if inner == "'":
                value, index = _parse_string_literal(text, index)
                row.append(value)
            elif text.startswith("NULL", index):
                row.append(None)
                index += 4
            else:
                raise BootstrapError("an INSERT value is neither NULL nor a string")
        tuples.append(row)
    return tuples


def _column_name(line: str) -> str | None:
    """Return the column name a ``CREATE TABLE`` body line defines, or ``None``
    for a key/constraint line. A column line opens (once trimmed) with a
    back-ticked identifier; a ``PRIMARY KEY`` / ``KEY`` / ``UNIQUE`` line opens
    with its keyword, so only a leading back-tick marks a column."""

    stripped = line.strip()
    if not stripped.startswith("`"):
        return None
    match = re.match(r"`([^`]+)`", stripped)
    return match.group(1) if match else None


def parse_dump(sql: str) -> dict[str, Table]:
    """Parse the reassembled dump into a table name → :class:`Table` mapping.

    The dump is walked line by line: a ``CREATE TABLE`` opens a multi-line
    structure block whose column lines give the table's column order, and each
    ``INSERT INTO`` is a single physical line whose tuples are mapped onto those
    columns. Real newlines in data are escaped by the dumper, so no data value
    ever spans a physical line.
    """

    tables: dict[str, Table] = {}
    lines = sql.split("\n")
    index = 0
    total = len(lines)
    while index < total:
        line = lines[index]
        stripped = line.strip()

        # A CREATE TABLE opens a structure block; collect its column lines until
        # the closing `) ENGINE=…` line.
        create = re.match(r"CREATE TABLE `([^`]+)` \(", stripped)
        if create:
            name = create.group(1)
            columns: list[str] = []
            index += 1
            while index < total and not lines[index].strip().startswith(")"):
                column = _column_name(lines[index])
                if column is not None:
                    columns.append(column)
                index += 1
            tables[name] = Table(columns)
            index += 1
            continue

        # An INSERT is one complete line; map each tuple onto the table's columns.
        insert = re.match(r"INSERT INTO `([^`]+)` VALUES ", stripped)
        if insert:
            name = insert.group(1)
            table = tables.get(name)
            if table is None:
                raise BootstrapError(f"INSERT into unknown table {name!r}")
            clause = stripped[insert.end() :]
            for values in _parse_values(clause):
                table.add_tuple(values)

        index += 1
    return tables


# --- PHP unserialize (only enough for _wp_attachment_metadata) --------------


def _unserialize(data: str, offset: int) -> tuple[Any, int]:
    """Parse one PHP-serialized value at ``offset``; return it and the new
    offset. Only the node types ``_wp_attachment_metadata`` uses are handled —
    arrays, strings, integers, doubles, booleans, and null — which is all the
    ``sizes[*].file`` walk needs. Anything else is a metadata shape this scan
    does not read, so it fails loud rather than guessing."""

    marker = data[offset : offset + 2]
    if marker == "a:":
        end = data.index(":", offset + 2)
        count = int(data[offset + 2 : end])
        offset = end + 2  # past ':{'
        result: dict[Any, Any] = {}
        for _ in range(count):
            key, offset = _unserialize(data, offset)
            value, offset = _unserialize(data, offset)
            result[key] = value
        return result, offset + 1  # past '}'
    if marker == "s:":
        end = data.index(":", offset + 2)
        byte_length = int(data[offset + 2 : end])
        # The declared length is in bytes; slice the UTF-8 encoding so a
        # multi-byte character in a filename is measured exactly as PHP measured
        # it, then advance the character offset past the content and its '";'.
        content_start = end + 2  # past ':"'
        raw = data[content_start:].encode("utf-8")
        text = raw[:byte_length].decode("utf-8")
        return text, content_start + len(text) + 2
    if marker == "i:":
        end = data.index(";", offset + 2)
        return int(data[offset + 2 : end]), end + 1
    if marker == "d:":
        end = data.index(";", offset + 2)
        return float(data[offset + 2 : end]), end + 1
    if marker == "b:":
        return data[offset + 2] == "1", offset + 4
    if data[offset : offset + 2] == "N;":
        return None, offset + 2
    raise BootstrapError("unreadable PHP-serialized attachment metadata")


def _sizes_from_metadata(serialized: str) -> list[str]:
    """Pull the generated-size filenames from a serialized
    ``_wp_attachment_metadata`` blob: the ``file`` of each entry under its
    ``sizes`` map. A blob this scan cannot read fails loud."""

    metadata, _ = _unserialize(serialized, 0)
    if not isinstance(metadata, dict):
        return []
    sizes = metadata.get("sizes")
    if not isinstance(sizes, dict):
        return []
    files: list[str] = []
    for entry in sizes.values():
        if isinstance(entry, dict):
            file = entry.get("file")
            if isinstance(file, str) and file:
                files.append(file)
    return files


# --- string-length parser for i-column comparisons --------------------------


def _to_int(value: str | None) -> int:
    """Coerce a dumped string value to an integer, treating a non-numeric or
    ``None`` value as zero — the same tolerance the old server-side scan's
    ``(int)`` casts gave a stray or absent count."""

    if value is None:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


# --- signal extraction ------------------------------------------------------


def extract_attachments(tables: dict[str, Table], prefix: str) -> list[dict[str, Any]]:
    """Build the attachment metadata: each ``post_type='attachment'`` post that
    carries an ``_wp_attached_file``, with the generated sizes parsed from its
    ``_wp_attachment_metadata`` (the inner/left-join shape the old scan used)."""

    posts = _require_table(tables, prefix, "posts")
    postmeta = _require_table(tables, prefix, "postmeta")

    # Index the postmeta by post so each attachment's file and metadata are one
    # lookup rather than a scan per attachment.
    attached_file: dict[str, str] = {}
    metadata_blob: dict[str, str] = {}
    for row in postmeta.rows:
        post_id = row.get("post_id")
        if post_id is None:
            continue
        if row.get("meta_key") == "_wp_attached_file" and row.get("meta_value"):
            attached_file[post_id] = row["meta_value"]  # type: ignore[assignment]
        elif row.get("meta_key") == "_wp_attachment_metadata" and row.get("meta_value"):
            metadata_blob[post_id] = row["meta_value"]  # type: ignore[assignment]

    attachments: list[dict[str, Any]] = []
    for row in posts.rows:
        if row.get("post_type") != "attachment":
            continue
        post_id = row.get("ID")
        if post_id is None or post_id not in attached_file:
            continue
        sizes = (
            _sizes_from_metadata(metadata_blob[post_id]) if post_id in metadata_blob else []
        )
        attachments.append(
            {"id": _to_int(post_id), "file": attached_file[post_id], "sizes": sizes}
        )
    return attachments


def extract_entity_counts(tables: dict[str, Table], prefix: str) -> dict[str, int]:
    """Count the verify-phase populations, each scoped exactly as the verifying
    ``wp`` subcommand counts it: published posts and pages, attachments excluding
    trash and auto-draft, and users. The users count is omitted — never
    zero-filled — when the bootstrap lacks ``wp_users``, so a downstream reader's
    presence check decides whether it was collected."""

    posts = _require_table(tables, prefix, "posts")
    counts: dict[str, int] = {
        "published_posts": sum(
            1
            for row in posts.rows
            if row.get("post_type") == "post" and row.get("post_status") == "publish"
        ),
        "published_pages": sum(
            1
            for row in posts.rows
            if row.get("post_type") == "page" and row.get("post_status") == "publish"
        ),
        "attachments": sum(
            1
            for row in posts.rows
            if row.get("post_type") == "attachment"
            and row.get("post_status") not in ("trash", "auto-draft")
        ),
    }

    users = tables.get(f"{prefix}users")
    if users is not None:
        counts["users"] = len(users.rows)
    return counts


def extract_mass_send(tables: dict[str, Table], prefix: str) -> dict[str, Any]:
    """Scan for a poised mass-send: one engine record per recognised on-site
    engine whose campaign table is present, plus the unrecognised-mailer
    fallback signal from Action Scheduler. Only the facts are reported here — the
    flip decision stays in ``discovery.py``'s ``build_mass_send``."""

    engines: list[dict[str, Any]] = []
    for engine, spec in MAILER_ENGINES.items():
        table = tables.get(f"{prefix}{spec['table']}")
        if table is None:
            continue
        engines.append(_scan_engine(engine, spec, table))

    scheduler = tables.get(f"{prefix}{ACTIONSCHEDULER_TABLE}")
    unrecognised = _scan_actionscheduler(scheduler)
    return {"engines": engines, "unrecognised": unrecognised}


def _scan_engine(engine: str, spec: dict[str, Any], table: Table) -> dict[str, Any]:
    """Report the latest poised campaign for one present engine — the last row,
    by ``id``, in a poised status — or a present-but-not-poised record when none
    is poised, mirroring the old server-side scan's per-engine result."""

    poised = [
        row for row in table.rows if row.get("status") in spec["poised_statuses"]
    ]
    if not poised:
        return {
            "engine": engine,
            "present": True,
            "queued_or_scheduled": False,
            "campaign": None,
            "recipient_count": 0,
        }

    # The most recent poised campaign is the one with the greatest id (the old
    # scan's ORDER BY id DESC LIMIT 1).
    latest = max(poised, key=lambda row: _to_int(row.get("id")))
    count_column = spec["count_column"]
    return {
        "engine": engine,
        "present": True,
        "queued_or_scheduled": True,
        "campaign": latest.get(spec["campaign_column"]),
        "recipient_count": _to_int(latest.get(count_column)) if count_column else 0,
    }


def _scan_actionscheduler(table: Table | None) -> dict[str, Any]:
    """Size the pending Action Scheduler queue and flag whether any pending
    action's hook is send-shaped — the generic signal the unrecognised-mailer
    fallback surfaces without flipping."""

    if table is None:
        return {"sending_cron_scheduled": False, "pending_queue_size": 0}

    pending = [row for row in table.rows if row.get("status") == "pending"]
    sending = any(
        row.get("hook") and SENDING_HOOK_PATTERN.search(row["hook"] or "")
        for row in pending
    )
    return {"sending_cron_scheduled": sending, "pending_queue_size": len(pending)}


def _require_table(tables: dict[str, Table], prefix: str, base: str) -> Table:
    """Fetch a table the bootstrap always carries, failing loud when it is
    absent — a malformed bootstrap, never an empty site (a missing anchor table
    would otherwise emit zero counts a stale document cannot be told apart
    from a genuinely empty one)."""

    table = tables.get(f"{prefix}{base}")
    if table is None:
        raise BootstrapError(
            f"the bootstrap extraction is missing the {prefix}{base} table"
        )
    return table


def build_signals(config: dict[str, Any]) -> dict[str, Any]:
    """Parse the reassembled bootstrap dump and assemble the three row-derived
    signals ``discovery.py`` consumes."""

    sql_path = Path(config["sql_path"])
    prefix = config.get("table_prefix", "")
    if not isinstance(prefix, str):
        raise BootstrapError("table_prefix must be a string")

    try:
        sql = sql_path.read_text(encoding="utf-8")
    except OSError as error:
        raise BootstrapError(f"cannot read the bootstrap dump: {error}") from error

    tables = parse_dump(sql)
    return {
        "attachments": extract_attachments(tables, prefix),
        "entity_counts": extract_entity_counts(tables, prefix),
        "mass_send": extract_mass_send(tables, prefix),
    }


def main() -> int:
    """Read the config JSON on stdin, emit the signals on stdout, and fail
    loudly on malformed input with a non-zero exit and a stderr diagnostic."""

    try:
        config = json.loads(sys.stdin.read())
    except json.JSONDecodeError as error:
        sys.stderr.write(f"bootstrap_parse: invalid JSON on stdin: {error}\n")
        return 1

    try:
        signals = build_signals(config)
    except (BootstrapError, KeyError) as error:
        sys.stderr.write(f"bootstrap_parse: {error}\n")
        return 1

    json.dump(signals, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
