# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Behavioural tests for the bootstrap-extraction parser CLI.

The parser is the client-side seam that replaces the retired ``discovery.php``
row-level scan (ADR-0017): the two-phase discovery's cheap bootstrap extraction
comes down sealed, is reassembled into one importable ``.sql`` by ``unseal.py``,
and this helper parses that dump into the three row-derived signals the main
extraction's classification needs — the attachment metadata (for the thumbnail
exclude-set), the verify-phase entity counts, and the mass-send poised-campaign
scan. Every test drives the real command: a fixture ``.sql`` on disk in, the
signals JSON on stdout out, and malformed input fails loudly. No test touches a
real site; the SQL fixtures are hand-written in the exact ``Table_Dumper``
shape the plugin emits — a verbatim ``CREATE TABLE`` and column-less extended
``INSERT`` statements whose every value is an escaped string literal or ``NULL``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bootstrap_parse.py"


def run_parse(config: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    """Run the parser with ``config`` as JSON on stdin and capture its result."""

    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(config).encode(),
        capture_output=True,
    )


def parse_sql(tmp_path: Path, sql: str, prefix: str = "wp_") -> dict[str, Any]:
    """Write ``sql`` to a temp file, run the parser over it, and return the
    parsed signals, asserting the run succeeded."""

    sql_path = tmp_path / "bootstrap.sql"
    sql_path.write_text(sql, encoding="utf-8")
    result = run_parse({"sql_path": str(sql_path), "table_prefix": prefix})
    assert result.returncode == 0, result.stderr.decode()
    signals: dict[str, Any] = json.loads(result.stdout)
    return signals


# --- SQL fixtures in the exact Table_Dumper shape ---------------------------


def create_table(name: str, columns: list[str]) -> str:
    """Render a ``SHOW CREATE TABLE``-shaped structure block: the mysqldump
    header, a ``DROP TABLE``, and a ``CREATE TABLE`` whose column lines each
    open with a back-ticked identifier, followed by a non-column key line — the
    exact frame the parser must read column order from and the key line it must
    skip."""

    column_lines = ",\n".join(f"  `{column}` text" for column in columns)
    return (
        f"--\n-- Table structure for table `{name}`\n--\n\n"
        f"DROP TABLE IF EXISTS `{name}`;\n"
        f"CREATE TABLE `{name}` (\n"
        f"{column_lines},\n"
        f"  PRIMARY KEY (`{columns[0]}`)\n"
        f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"
    )


def literal(value: str | None) -> str:
    """Render one value as the parser's counterpart escapes it: ``NULL`` or a
    quoted string with backslash, quote, NUL, newline, CR, and Ctrl-Z escaped —
    the exact escaping ``Table_Dumper::literal`` applies."""

    if value is None:
        return "NULL"
    escaped = (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\0", "\\0")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\x1a", "\\Z")
    )
    return f"'{escaped}'"


def insert(name: str, rows: list[list[str | None]]) -> str:
    """Render a data block: the mysqldump header and one column-less extended
    ``INSERT`` carrying every row as a tuple of escaped literals."""

    tuples = ",".join(
        "(" + ",".join(literal(value) for value in row) + ")" for row in rows
    )
    return (
        f"\n--\n-- Dumping data for table `{name}`\n--\n\n"
        f"INSERT INTO `{name}` VALUES {tuples};\n"
    )


def php_metadata(sizes: list[str]) -> str:
    """Render a minimal ``_wp_attachment_metadata`` PHP-serialized blob carrying
    only the ``sizes`` map the exclude-set derivation reads — each size a nested
    array whose ``file`` is the generated filename."""

    entries = "".join(
        f's:{len(str(index))}:"{index}";'
        f'a:1:{{s:4:"file";s:{len(name)}:"{name}";}}'
        for index, name in enumerate(sizes)
    )
    inner = f'a:{len(sizes)}:{{{entries}}}'
    return f's:5:"sizes";{inner}'


def posts_and_meta(
    attachments: list[tuple[int, str, list[str]]],
    published_posts: int = 0,
    published_pages: int = 0,
    trashed_attachments: int = 0,
) -> str:
    """Build a ``wp_posts`` + ``wp_postmeta`` pair: the given attachments (id,
    file, generated sizes), plus filler published posts/pages and trashed
    attachments so the entity counts have a population to scope over."""

    post_rows: list[list[str | None]] = []
    meta_rows: list[list[str | None]] = []
    for post_id, file, sizes in attachments:
        post_rows.append([str(post_id), "attachment", "inherit"])
        meta_rows.append([str(post_id), "_wp_attached_file", file])
        metadata = "a:1:{" + php_metadata(sizes) + "}"
        meta_rows.append([str(post_id), "_wp_attachment_metadata", metadata])
    next_id = 1000
    for _ in range(published_posts):
        post_rows.append([str(next_id), "post", "publish"])
        next_id += 1
    for _ in range(published_pages):
        post_rows.append([str(next_id), "page", "publish"])
        next_id += 1
    for _ in range(trashed_attachments):
        post_rows.append([str(next_id), "attachment", "trash"])
        next_id += 1

    posts = create_table("wp_posts", ["ID", "post_type", "post_status"]) + insert(
        "wp_posts", post_rows
    )
    meta = create_table("wp_postmeta", ["post_id", "meta_key", "meta_value"]) + insert(
        "wp_postmeta", meta_rows
    )
    return posts + meta


def users(count: int) -> str:
    """Build a ``wp_users`` table carrying ``count`` rows."""

    rows: list[list[str | None]] = [[str(index + 1)] for index in range(count)]
    return create_table("wp_users", ["ID"]) + insert("wp_users", rows)


# --- attachments ------------------------------------------------------------


def test_attachment_original_and_generated_sizes_are_extracted(tmp_path: Path) -> None:
    # Arrange — one attachment with a registered original and two generated
    # sizes, exactly the shape the thumbnail exclude-set is later derived from.
    sql = posts_and_meta([(12, "2024/05/banner.jpg", ["banner-300x200.jpg", "banner-150x150.jpg"])])

    # Act.
    signals = parse_sql(tmp_path, sql)

    # Assert — the original path and its sizes survive intact, keyed by id.
    banner = next(item for item in signals["attachments"] if item["id"] == 12)
    assert banner["file"] == "2024/05/banner.jpg"
    assert "banner-300x200.jpg" in banner["sizes"]
    assert "banner-150x150.jpg" in banner["sizes"]


def test_attachment_without_metadata_carries_an_empty_size_list(tmp_path: Path) -> None:
    # Arrange — an attachment with _wp_attached_file but no _wp_attachment_metadata
    # (the LEFT JOIN case): it is still an attachment, just with no generated sizes.
    posts = create_table("wp_posts", ["ID", "post_type", "post_status"]) + insert(
        "wp_posts", [["7", "attachment", "inherit"]]
    )
    meta = create_table("wp_postmeta", ["post_id", "meta_key", "meta_value"]) + insert(
        "wp_postmeta", [["7", "_wp_attached_file", "2024/06/doc.pdf"]]
    )

    # Act.
    signals = parse_sql(tmp_path, posts + meta)

    # Assert.
    doc = next(item for item in signals["attachments"] if item["id"] == 7)
    assert doc["file"] == "2024/06/doc.pdf"
    assert doc["sizes"] == []


def test_a_non_attachment_post_is_not_emitted_as_an_attachment(tmp_path: Path) -> None:
    # Arrange — a published post that happens to carry postmeta must never be
    # mistaken for an attachment (the scan is scoped to post_type='attachment').
    sql = posts_and_meta(
        [(12, "2024/05/banner.jpg", ["banner-300x200.jpg"])], published_posts=3
    )

    # Act.
    signals = parse_sql(tmp_path, sql)

    # Assert — only the one real attachment appears.
    assert [item["id"] for item in signals["attachments"]] == [12]


# --- entity counts ----------------------------------------------------------


def test_entity_counts_scope_each_population_like_the_verifying_subcommand(
    tmp_path: Path,
) -> None:
    # Arrange — published posts and pages, live and trashed attachments, and a
    # user table: the counts must scope exactly as the verify phase's own wp
    # subcommands do (published-only posts/pages; attachments excluding trash).
    sql = posts_and_meta(
        [(12, "a.jpg", ["a-1x1.jpg"]), (13, "b.jpg", [])],
        published_posts=5,
        published_pages=2,
        trashed_attachments=3,
    ) + users(7)

    # Act.
    signals = parse_sql(tmp_path, sql)

    # Assert — 5 posts, 2 pages, 2 live attachments (trash excluded), 7 users.
    assert signals["entity_counts"] == {
        "published_posts": 5,
        "published_pages": 2,
        "attachments": 2,
        "users": 7,
    }


def test_users_count_is_omitted_when_the_bootstrap_lacks_the_users_table(
    tmp_path: Path,
) -> None:
    # Arrange — a bootstrap without wp_users (an older selection): the users
    # count must be omitted, never zero-filled, so a downstream reader's
    # presence check — not a "!= 0" check — decides whether it was collected.
    sql = posts_and_meta([], published_posts=4)

    # Act.
    signals = parse_sql(tmp_path, sql)

    # Assert.
    assert signals["entity_counts"]["published_posts"] == 4
    assert "users" not in signals["entity_counts"]


# --- mass-send scan ---------------------------------------------------------


def fluentcrm(prefix: str, rows: list[list[str | None]]) -> str:
    """Build a FluentCRM ``fc_campaigns`` table with (id, status, title,
    recipients_count) rows."""

    name = f"{prefix}fc_campaigns"
    return create_table(name, ["id", "status", "title", "recipients_count"]) + insert(
        name, rows
    )


def test_a_poised_fluentcrm_campaign_is_reported_with_its_recipient_count(
    tmp_path: Path,
) -> None:
    # Arrange — a scheduled FluentCRM campaign with a real recipient list; the
    # latest scheduled/working campaign is the poised one.
    sql = posts_and_meta([]) + fluentcrm(
        "wp_",
        [
            ["1", "sent", "Old News", "100"],
            ["2", "scheduled", "Summer Sale 2026", "4820"],
        ],
    )

    # Act.
    signals = parse_sql(tmp_path, sql)

    # Assert — the engine record names the campaign and its count, ready for the
    # deterministic flip logic downstream (discovery.py's build_mass_send).
    engine = next(e for e in signals["mass_send"]["engines"] if e["engine"] == "fluentcrm")
    assert engine["present"] is True
    assert engine["queued_or_scheduled"] is True
    assert engine["campaign"] == "Summer Sale 2026"
    assert engine["recipient_count"] == 4820


def test_an_engine_present_but_not_poised_reports_not_queued(tmp_path: Path) -> None:
    # Arrange — FluentCRM present, but every campaign already sent: present, but
    # nothing poised, so the downstream flip must not fire.
    sql = posts_and_meta([]) + fluentcrm("wp_", [["1", "sent", "Old News", "100"]])

    # Act.
    signals = parse_sql(tmp_path, sql)

    # Assert.
    engine = next(e for e in signals["mass_send"]["engines"] if e["engine"] == "fluentcrm")
    assert engine["present"] is True
    assert engine["queued_or_scheduled"] is False
    assert engine["campaign"] is None


def test_a_mailpoet_scheduled_newsletter_flips_without_a_countable_list(
    tmp_path: Path,
) -> None:
    # Arrange — MailPoet reports only a subject for a scheduled newsletter, never
    # a list size, so recipient_count arrives as 0 but the engine is still poised.
    name = "wp_mailpoet_newsletters"
    sql = posts_and_meta([]) + create_table(name, ["id", "status", "subject"]) + insert(
        name, [["9", "scheduled", "Newsletter #9"]]
    )

    # Act.
    signals = parse_sql(tmp_path, sql)

    # Assert — poised with a zero (uncountable) list, so the valve can fail
    # toward capture (ADR-0009).
    engine = next(e for e in signals["mass_send"]["engines"] if e["engine"] == "mailpoet")
    assert engine["queued_or_scheduled"] is True
    assert engine["campaign"] == "Newsletter #9"
    assert engine["recipient_count"] == 0


def test_an_absent_engine_table_yields_no_engine_record(tmp_path: Path) -> None:
    # Arrange — a bootstrap with no recognised-mailer table at all.
    sql = posts_and_meta([(12, "a.jpg", [])])

    # Act.
    signals = parse_sql(tmp_path, sql)

    # Assert — no engines, so nothing can flip on mere absence.
    assert signals["mass_send"]["engines"] == []


def test_the_non_default_table_prefix_locates_the_engine_table(tmp_path: Path) -> None:
    # Arrange — a site whose prefix is not the default; the engine table must be
    # found under that prefix, not the default one.
    sql = posts_and_meta([], published_posts=0).replace("wp_posts", "site_posts").replace(
        "wp_postmeta", "site_postmeta"
    ) + fluentcrm("site_", [["1", "scheduled", "Campaign", "10"]])

    # Act.
    signals = parse_sql(tmp_path, sql, prefix="site_")

    # Assert.
    engine = next(e for e in signals["mass_send"]["engines"] if e["engine"] == "fluentcrm")
    assert engine["queued_or_scheduled"] is True


def test_action_scheduler_pending_queue_feeds_the_unrecognised_fallback(
    tmp_path: Path,
) -> None:
    # Arrange — no recognised engine, but Action Scheduler carries pending
    # send-shaped actions: the generic signal the helper surfaces without
    # flipping.
    name = "wp_actionscheduler_actions"
    rows = [
        ["1", "wp_mail_send_queue", "pending"],
        ["2", "some_other_hook", "pending"],
        ["3", "newsletter_dispatch", "complete"],
    ]
    sql = posts_and_meta([]) + create_table(name, ["action_id", "hook", "status"]) + insert(
        name, rows
    )

    # Act.
    signals = parse_sql(tmp_path, sql)

    # Assert — the pending queue is counted and a send-shaped pending hook marks
    # the sending-cron signal.
    unrecognised = signals["mass_send"]["unrecognised"]
    assert unrecognised["pending_queue_size"] == 2
    assert unrecognised["sending_cron_scheduled"] is True


# --- escaping and robustness ------------------------------------------------


def test_escaped_values_round_trip_through_the_literal_parser(tmp_path: Path) -> None:
    # Arrange — a campaign title carrying every escaped byte the dumper emits: a
    # quote, a backslash, a newline, and a comma (comma is not escaped, so it
    # must be read inside the quotes rather than as a tuple separator).
    tricky = "O'Brien \\ sale,\ntoday"
    sql = posts_and_meta([]) + fluentcrm("wp_", [["1", "scheduled", tricky, "5"]])

    # Act.
    signals = parse_sql(tmp_path, sql)

    # Assert — the title is reassembled byte-for-byte.
    engine = next(e for e in signals["mass_send"]["engines"] if e["engine"] == "fluentcrm")
    assert engine["campaign"] == tricky


def test_a_missing_sql_file_fails_loudly() -> None:
    # Arrange & Act.
    result = run_parse({"sql_path": "/nonexistent/bootstrap.sql", "table_prefix": "wp_"})

    # Assert — a non-zero exit and a branded diagnostic, never a half-built
    # signals document on stdout.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"bootstrap_parse:")


def test_a_bootstrap_missing_the_posts_table_fails_loudly(tmp_path: Path) -> None:
    # Arrange — the bootstrap always carries wp_posts; its absence is a malformed
    # bootstrap, not an empty site, and must fail loud rather than emit empty
    # counts a stale document could not be told apart from a real empty site.
    sql = users(3)

    # Act.
    sql_path = tmp_path / "bootstrap.sql"
    sql_path.write_text(sql, encoding="utf-8")
    result = run_parse({"sql_path": str(sql_path), "table_prefix": "wp_"})

    # Assert.
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr.startswith(b"bootstrap_parse:")
    assert b"posts" in result.stderr


# --- bootstrap artifact cleanup (issue #49) ----------------------------------
#
# The bootstrap dump holds real user and subscriber rows in cleartext. Once
# this helper has parsed it, nothing should keep the unsealed .sql, the sealed
# container it was unsealed from, or the run's ephemeral private key alive on
# disk — the local analogue of Extractor's own POST /consume. These tests bind
# that discipline in code rather than trusting a subagent's prose to remember it.


def test_the_unsealed_sql_dump_is_deleted_after_a_successful_parse(
    tmp_path: Path,
) -> None:
    # Arrange — a well-formed bootstrap dump.
    sql = posts_and_meta([], published_posts=1)
    sql_path = tmp_path / "bootstrap.sql"
    sql_path.write_text(sql, encoding="utf-8")

    # Act.
    result = run_parse({"sql_path": str(sql_path), "table_prefix": "wp_"})

    # Assert — the parse still succeeds, and the cleartext dump is gone.
    assert result.returncode == 0, result.stderr.decode()
    assert not sql_path.exists()


def test_the_sealed_container_and_private_key_are_deleted_when_named(
    tmp_path: Path,
) -> None:
    # Arrange — the caller names the sealed container and the ephemeral
    # private key alongside the unsealed dump, exactly as
    # agents/discovery-classify.md's task envelope will.
    sql = posts_and_meta([], published_posts=1)
    sql_path = tmp_path / "bootstrap.sql"
    sql_path.write_text(sql, encoding="utf-8")
    container_path = tmp_path / "bootstrap.kntntext"
    container_path.write_bytes(b"sealed-container-bytes")
    private_key_path = tmp_path / "bootstrap.key"
    private_key_path.write_bytes(b"private-key-bytes")

    # Act.
    result = run_parse(
        {
            "sql_path": str(sql_path),
            "table_prefix": "wp_",
            "container_path": str(container_path),
            "private_key_path": str(private_key_path),
        }
    )

    # Assert — all three cleartext/key artifacts are gone; the parent no
    # longer holds any of them.
    assert result.returncode == 0, result.stderr.decode()
    assert not sql_path.exists()
    assert not container_path.exists()
    assert not private_key_path.exists()
    assert list(tmp_path.iterdir()) == []


def test_an_already_missing_container_or_key_path_does_not_fail_the_parse(
    tmp_path: Path,
) -> None:
    # Arrange — a caller names cleanup paths that never existed (already swept
    # by a retry, or simply not produced this run): the cleanup must be
    # idempotent, never a crash.
    sql = posts_and_meta([], published_posts=1)
    sql_path = tmp_path / "bootstrap.sql"
    sql_path.write_text(sql, encoding="utf-8")

    # Act.
    result = run_parse(
        {
            "sql_path": str(sql_path),
            "table_prefix": "wp_",
            "container_path": str(tmp_path / "nonexistent.kntntext"),
            "private_key_path": str(tmp_path / "nonexistent.key"),
        }
    )

    # Assert.
    assert result.returncode == 0, result.stderr.decode()
    assert not sql_path.exists()


def test_a_failed_unlink_does_not_prevent_deleting_the_other_artifacts(
    tmp_path: Path,
) -> None:
    # Arrange — the container path is a directory rather than a file, so
    # unlinking it raises IsADirectoryError (an OSError). The dump and the
    # private key are ordinary files that must still be deleted even though
    # the container's unlink fails: a single failure must never abort cleanup
    # of the remaining cleartext/key material.
    sql = posts_and_meta([], published_posts=1)
    sql_path = tmp_path / "bootstrap.sql"
    sql_path.write_text(sql, encoding="utf-8")
    container_path = tmp_path / "bootstrap.kntntext"
    container_path.mkdir()
    private_key_path = tmp_path / "bootstrap.key"
    private_key_path.write_bytes(b"private-key-bytes")

    # Act.
    result = run_parse(
        {
            "sql_path": str(sql_path),
            "table_prefix": "wp_",
            "container_path": str(container_path),
            "private_key_path": str(private_key_path),
        }
    )

    # Assert — the run still fails loudly (the container survives), but the
    # dump and the private key are gone regardless.
    assert result.returncode != 0
    assert not sql_path.exists()
    assert not private_key_path.exists()
    assert container_path.exists()


def test_a_failed_parse_leaves_the_dump_on_disk_for_diagnosis(tmp_path: Path) -> None:
    # Arrange — a malformed bootstrap (missing wp_posts): the parse fails, so
    # the dump must survive on disk rather than vanish along with the
    # diagnostic an operator would need to investigate it.
    sql = users(3)
    sql_path = tmp_path / "bootstrap.sql"
    sql_path.write_text(sql, encoding="utf-8")

    # Act.
    result = run_parse({"sql_path": str(sql_path), "table_prefix": "wp_"})

    # Assert.
    assert result.returncode != 0
    assert sql_path.exists()
