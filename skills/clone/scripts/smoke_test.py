# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Deterministic post-clone/pull verification against an expectations file.

This helper turns the hand-written baseline document a real-site smoke test
used to require (a Markdown checklist an operator re-typed by eye) into a
mechanical check surface: a clone directory and an **expectations file** go
in, a PASS/FAIL/attention report — one entry per check — comes out, and any
FAIL trips a non-zero exit. It is the transfer engine's own verify phase
(``docs/spec.md``, *Verify*), runnable both as the prescribed final step of
`clone`/`pull`'s orchestration (the `thumbnail-smoke-test` role, whichever
tier executes it) and standalone from a terminal.

Every check is **individually skippable**: its expectations key absent means
the check is skipped, never failed — an expectations file is never
all-or-nothing, and a baseline captured before some fact was known (or one the
operator does not care to pin) never blocks the rest of the report. Three
verdicts exist per check: ``pass``, ``fail``, and the softer ``attention`` —
reserved for the one check (the total table count) where *more* than expected
is not itself a defect (production may have grown a table since the baseline
was captured) while *fewer* is (the "nothing ever hits a missing table"
guarantee, spec.md user story 16). The script reports facts; classifying a
finding as an already-known gap (the search-index-not-reindexed issue #10
territory, an unclassified operational table carried in full) is the
operator's job, not this script's.

Unlike the sibling helpers under this directory, this one is not a pure
JSON-transform: some checks need to observe the finished copy's actual
state — `ddev wp ...` calls and HTTP fetches over `curl` — rather than
being fed pre-gathered facts on stdin. To keep that live-state edge
honestly separate from the check logic it drives, every check that shells
out takes its command runner (and, for the URL checks, its fetcher) as an
injectable dependency; :func:`run_checks` builds the real ones by default,
so unit tests can substitute fakes and never spawn a real DDEV project or
issue a real HTTP request.

Two CLI shapes, because the two modes take fundamentally different inputs:

- **Verify** (default): ``smoke_test.py <clone_dir> <expectations_file>
  [--log <report_path>]`` — positional arguments, since an expectations *file*
  is naturally a path, not a JSON blob worth piping. Emits the JSON report to
  stdout. It exits ``1`` on any FAIL and ``2`` when it could not run at all —
  a missing clone directory, an unreadable or non-object expectations file, a
  malformed invocation, or a probe that raised — because those two say
  opposite things about the copy and only the first may condemn it (issue
  #59, :data:`EXIT_COPY_DEFECTIVE` / :data:`EXIT_COULD_NOT_RUN`). With
  ``--log`` the full report is written to that path instead and stdout carries
  only the verdict, the pass/fail counts, and the ``fail``/``attention``
  findings, so a caller executing this step inline is not handed the whole
  report to read.
- **Generate** (``--generate``): reads an envelope JSON object from stdin —
  production's canonical discovery document (``scripts/discovery.py``'s
  output) plus the few supplementary facts that document does not itself
  carry (the local DDEV URL, live entity counts) — and writes the derived
  expectations JSON to stdout, matching the sibling helpers' stdin/stdout
  convention. See :func:`generate_expectations`.

The sample URLs are the one expectation nobody assembles: the copy under test
is asked for its own front page, post, page and archive (issue #60), because a
caller building those strings is the one input that can plausibly be built
wrongly — and a wrong one reads as a rewrite or flush bug in the copy rather
than as the bad expectation it is. A caller may still override the list, for a
site with a URL it cannot derive; the report then records the list as
``supplied`` rather than ``derived``, so a later reader can always tell the two
apart. Where the source site's own permalink structure and front-page pair are
recorded, they are compared against the copy's and a disagreement is reported
— as ``attention``, since the copy is the subject under test and a source that
has moved on since discovery is not a broken copy.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "CheckResult",
    "DdevConfig",
    "EXIT_COPY_DEFECTIVE",
    "EXIT_COULD_NOT_RUN",
    "EXIT_OK",
    "GenerateError",
    "SampleUrlDerivation",
    "SampleUrlResolution",
    "SmokeTestError",
    "check_active_plugin_count",
    "check_baseline_present",
    "check_content_tables_nonempty",
    "check_core_version",
    "check_db_check_clean",
    "check_ddev_database",
    "check_ddev_php_version",
    "check_entity_counts",
    "check_excluded_dropins_absent",
    "check_local_asset_urls",
    "check_local_urls",
    "check_object_cache_dropin_state",
    "check_operational_tables_empty",
    "check_rollback_backup_present",
    "check_sample_url_source_parity",
    "check_sample_urls",
    "check_saved_plan_present",
    "check_table_prefix",
    "check_total_table_count",
    "default_fetch_url",
    "default_run_command",
    "derive_sample_urls",
    "generate_expectations",
    "main",
    "parse_ddev_config",
    "read_site_shape",
    "resolve_sample_urls",
    "run_checks",
]

Status = Literal["pass", "fail", "attention", "skip"]

# The exit codes verify mode answers with, and the whole of what a caller has
# to know to judge the phase (issue #59). They exist as three rather than "0 or
# non-zero" because the two non-zero meanings have opposite consequences: `1`
# is the only one that says anything about the copy, and it is the only one a
# caller may turn into a `FAILED` verdict. `2` says this script never got as
# far as a check, which is the caller's input or environment and never
# evidence against what landed.
EXIT_OK: int = 0
EXIT_COPY_DEFECTIVE: int = 1
EXIT_COULD_NOT_RUN: int = 2

# The three WordPress fatal-error markers the transfer engine has always
# grepped for (agents/thumbnail-smoke-test.md, both SKILL.md verify sections)
# — kept identical here so a caller migrating from the ad-hoc check list sees
# the same three strings, never a silently different set.
FATAL_ERROR_MARKERS: tuple[str, ...] = (
    "There has been a critical error",
    "Fatal error",
    "Error establishing a database",
)

# Every entity-count sub-check's prefix-relative table and the raw-SQL WHERE
# clause that scopes it, keyed by the expectations sub-key so
# `check_entity_counts` can iterate one table rather than repeating four
# near-identical bodies. The count is issued as raw SQL over `wp db query`,
# never `wp post list` / `wp user list` — those go through WP_Query, which any
# active plugin hooking the main query (Bogo narrows it to one locale, and the
# whole class of membership / geo-restriction / post-visibility plugins does
# the like) silently filters, FAILing a complete copy against an expectation
# the discovery template derived from an unfiltered COUNT(*) (issue #33). Each
# WHERE clause mirrors templates/discovery.php's own entity_counts SQL
# clause-for-clause, so the checker counts the exact population the expectation
# was built from; the clauses are code constants, never operator input.
_COUNT_QUERIES: dict[str, tuple[str, str]] = {
    "publishedPosts": ("posts", "WHERE post_type = 'post' AND post_status = 'publish'"),
    "publishedPages": ("posts", "WHERE post_type = 'page' AND post_status = 'publish'"),
    "attachments": ("posts", "WHERE post_type = 'attachment' AND post_status NOT IN ('trash', 'auto-draft')"),
    "users": ("users", ""),
}

RunCommand = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]
FetchUrl = Callable[[str], tuple[int, str]]


class SmokeTestError(Exception):
    """Raised when the CLI's own inputs are malformed: an unreadable
    expectations file, a missing clone directory, or an expectations file
    that is not a JSON object. Turned into a loud non-zero exit rather than a
    half-run report."""


class GenerateError(Exception):
    """Raised when a ``--generate`` envelope is malformed: not an object, or
    missing its required ``discovery`` section. Turned into a loud non-zero
    exit rather than a half-built expectations document, mirroring every
    sibling helper's fail-loud contract."""


@dataclass(frozen=True)
class CheckResult:
    """One check's verdict: its id, one of the four :data:`Status` values,
    and a human-readable detail — the actual value observed, or the reason a
    command could not even be run."""

    id: str
    status: Status
    detail: str

    def to_dict(self) -> dict[str, str]:
        """Render as the flat JSON object the report's ``checks`` list carries."""

        return {"id": self.id, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class DdevConfig:
    """The two pins :func:`parse_ddev_config` extracts from a DDEV
    ``config.yaml``'s text — the PHP major.minor and the database
    flavour/version ``ddev config --php-version=<..>
    --database=<flavour>:<version>`` writes (spec.md, *Clone bookends*).
    Any field DDEV's config lacks (or the file itself is missing) is
    ``None``, never a crash."""

    php_version: str | None
    db_type: str | None
    db_version: str | None


@dataclass(frozen=True)
class SampleUrlDerivation:
    """What the copy under test answered when asked for its own sample URLs:
    the URLs in shape order, and one ``coverage`` line per shape naming the
    URL that covered it — or, when the site has none of that kind, why none
    did. ``error`` is set only when the site could not be asked at all, which
    is the one derivation failure that leaves nothing to fetch."""

    urls: tuple[str, ...]
    coverage: Mapping[str, str]
    error: str | None = None


@dataclass(frozen=True)
class SampleUrlResolution:
    """Which sample URLs this run will fetch, where they came from, and the
    verdict the resolution itself earned.

    ``origin`` is the fact a later reader needs most: ``derived`` means the
    copy answered for its own URLs, ``supplied`` means a caller's list won and
    the copy was never asked, ``none`` means there is nothing to fetch. It
    reaches the report and its compact summary, so a reader can always tell a
    derived expectation from a supplied one."""

    urls: tuple[str, ...]
    origin: Literal["supplied", "derived", "none"]
    checks: tuple[CheckResult, ...]

    @property
    def expectation(self) -> list[str] | None:
        """The value :func:`check_sample_urls` takes: the URL list, or ``None``
        when there is nothing to fetch — the same "absent means skipped, never
        failed" contract every other expectation follows."""

        return list(self.urls) or None

    def to_dict(self) -> dict[str, Any]:
        """The report's own ``sampleUrls`` section."""

        return {"origin": self.origin, "urls": list(self.urls)}


# --- Small result-shaping helpers ------------------------------------------


def _skip(check_id: str, reason: str = "no expectation given") -> CheckResult:
    """The uniform skip verdict every check returns when its expectations key
    is absent — the "individually skippable" contract in one place."""

    return CheckResult(check_id, "skip", reason)


def _bool_result(check_id: str, ok: bool, detail: str) -> CheckResult:
    """The uniform pass/fail verdict for a check that reduces to one boolean
    comparison — the common case every check but the total-table-count one
    (which has its own softer ``attention`` branch) uses."""

    return CheckResult(check_id, "pass" if ok else "fail", detail)


def _snake(camel: str) -> str:
    """Reduce an expectations sub-key's camelCase spelling (``publishedPosts``)
    to the snake_case a check id reads better in (``published_posts``)."""

    return re.sub(r"(?<!^)(?=[A-Z])", "_", camel).lower()


# --- The shelling-out edges: real implementations ---------------------------


def default_run_command(clone_dir: Path) -> RunCommand:
    """Build the real command runner: every command runs with the clone
    directory as its working directory, exactly as an operator would from a
    terminal open on the site."""

    def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                list(args), cwd=clone_dir, capture_output=True, text=True, timeout=120
            )
        except (OSError, subprocess.SubprocessError) as error:
            # A missing binary or a command that overran its timeout is a check
            # that could not be run, never a crash. This matters more since the
            # sample-URL derivation shells out on every run (issue #60): a
            # machine with no `ddev` on its PATH must still produce a report.
            return subprocess.CompletedProcess(list(args), 127, "", str(error))

    return _run


# The sentinel curl's `-w` format string appends after the response body, so
# the body and the HTTP status code can be told apart in one invocation
# without a second round-trip. Distinctive enough that no real response body
# is expected to collide with it.
_HTTP_STATUS_MARKER = "\n__KNTNT_SMOKE_TEST_HTTP_STATUS__"


def default_fetch_url(run: RunCommand) -> FetchUrl:
    """Build the real URL fetcher over the injected command runner: `curl`,
    per the issue's own instruction to shell out deterministically rather
    than add an HTTP client dependency to an otherwise stdlib-only helper.
    Deliberately not ``-f`` — a fatal-error page is very much still a
    response this helper must read the body of, not treat as a curl failure.
    """

    def _fetch(url: str) -> tuple[int, str]:
        completed = run(
            ["curl", "-sS", "--max-time", "15", "-o", "-", "-w", f"{_HTTP_STATUS_MARKER}%{{http_code}}", url]
        )
        if completed.returncode != 0:
            return -1, (completed.stderr or completed.stdout).strip()
        body, marker_found, status_text = completed.stdout.rpartition(_HTTP_STATUS_MARKER)
        if not marker_found:
            return -1, completed.stdout
        try:
            return int(status_text), body
        except ValueError:
            return -1, completed.stdout

    return _fetch


def _run_ddev_wp(run: RunCommand, *args: str) -> tuple[bool, str]:
    """Run ``ddev wp <args>`` via the injected runner, returning ``(ok,
    output)`` — stripped stdout on success, stripped stderr (falling back to
    stdout) on failure, so a caller never has to branch on which stream
    carried the diagnostic."""

    completed = run(["ddev", "wp", *args])
    if completed.returncode != 0:
        return False, (completed.stderr or completed.stdout).strip()
    return True, completed.stdout.strip()


_SAFE_TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _table_row_count(
    run: RunCommand, table: str, where: str = ""
) -> tuple[bool, int | None, str]:
    """Query one table's row count via `ddev wp db query`, optionally scoped
    by ``where``, returning ``(ok, count, raw_output)``. Backtick-quoted so a
    table name is never mistaken for SQL syntax.

    ``table`` comes from an expectations file the generator built from
    production's own discovery output — a remote system — so it is rejected
    outright unless it stays inside the identifier charset a real MySQL/
    MariaDB table name uses. A backtick inside ``table`` would otherwise
    close the surrounding backtick-quoting early, and `ddev wp db query`
    hands the whole string to a client that executes multiple
    ``;``-separated statements, turning a malicious table name into
    arbitrary SQL against the local clone (including, at pull, against the
    rollback backup's source database).

    ``where`` is only ever one of :data:`_COUNT_QUERIES`'s own code-constant
    clauses (never operator input), so it needs no such sanitising — it scopes
    an entity count to the same population ``templates/discovery.php`` counted.
    """

    if not _SAFE_TABLE_NAME_RE.match(table):
        return False, None, f"table name {table!r} contains characters outside [A-Za-z0-9_] — refusing to query it"

    query = f"SELECT COUNT(*) FROM `{table}`"
    if where:
        query = f"{query} {where}"

    ok, output = _run_ddev_wp(run, "db", "query", query, "--skip-column-names")
    if not ok:
        return False, None, output
    try:
        return True, int(output.strip().splitlines()[-1]), output
    except (ValueError, IndexError):
        return False, None, output


# --- .ddev/config.yaml parsing (pure) ---------------------------------------

_PHP_VERSION_RE = re.compile(r'^php_version:\s*"?([^"\s]+)"?\s*$', re.MULTILINE)
_DATABASE_BLOCK_RE = re.compile(r"^database:\n((?:[ \t]+\S.*\n?)*)", re.MULTILINE)
_DB_TYPE_RE = re.compile(r'^\s*type:\s*"?([^"\s]+)"?\s*$', re.MULTILINE)
_DB_VERSION_RE = re.compile(r'^\s*version:\s*"?([^"\s]+)"?\s*$', re.MULTILINE)


def parse_ddev_config(text: str) -> DdevConfig:
    """Extract the PHP and database pins from a DDEV ``config.yaml``'s raw
    text with a minimal, dependency-free line parser — the whole file is a
    flat and one-level-nested key/value document, and pulling in a YAML
    library would be the one third-party dependency in an otherwise
    stdlib-only helper surface, for two fields. A field the text does not
    carry — an unpinned engine, a config predating the pin — resolves to
    ``None`` rather than raising."""

    php_match = _PHP_VERSION_RE.search(text)
    php_version = php_match.group(1) if php_match else None

    db_type = db_version = None
    db_match = _DATABASE_BLOCK_RE.search(text)
    if db_match:
        block = db_match.group(1)
        type_match = _DB_TYPE_RE.search(block)
        version_match = _DB_VERSION_RE.search(block)
        db_type = type_match.group(1) if type_match else None
        db_version = version_match.group(1) if version_match else None

    return DdevConfig(php_version=php_version, db_type=db_type, db_version=db_version)


def _read_ddev_config(clone_dir: Path) -> DdevConfig:
    """Read and parse ``<clone_dir>/.ddev/config.yaml``, or an all-``None``
    config when the file itself is missing — a pure-file check downstream
    turns that into a clean FAIL rather than an uncaught exception."""

    path = clone_dir / ".ddev" / "config.yaml"
    if not path.is_file():
        return DdevConfig(php_version=None, db_type=None, db_version=None)
    return parse_ddev_config(path.read_text(encoding="utf-8"))


def _major_minor(version: str) -> str:
    """Truncate a full version string to its ``major.minor`` — the
    granularity DDEV's own pins accept, mirroring
    ``scripts/resolve_plan.py``'s ``engine_version_major_minor`` without
    importing across the helper-script boundary (each stays a self-contained
    single-file script, per the project's packaging convention)."""

    parts = version.split(".")
    return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else version


# classify.py's "full" list means only "not silently emptied by this
# transfer" — a table carried in full can still legitimately hold zero rows
# on the production site it came from (wp_links on nearly every modern
# WordPress install, wp_commentmeta with comments disabled). These three are
# the only tables core WordPress itself cannot run without a row in, so
# they are the sole safe basis for a "the transfer dropped data" assertion
# without observing production's own live row counts.
_ALWAYS_POPULATED_CORE_TABLES: frozenset[str] = frozenset({"posts", "options", "users"})


def _table_suffix(prefix: str, name: str) -> str:
    """Strip the site's own table prefix from a table name, mirroring
    ``classify.py``'s ``table_category`` stem derivation — matching against
    :data:`_ALWAYS_POPULATED_CORE_TABLES` must use the same prefix-relative
    name a non-default prefix (or none at all) still resolves correctly."""

    return name[len(prefix):] if prefix and name.startswith(prefix) else name


# --- Individual checks -------------------------------------------------------


def check_core_version(expected: Any, run: RunCommand) -> CheckResult:
    """WordPress core is scaffolded at production's exact version (spec.md,
    *Clone bookends*) — verified here via `ddev wp core version`."""

    if expected is None:
        return _skip("core_version")
    ok, output = _run_ddev_wp(run, "core", "version")
    if not ok:
        return CheckResult("core_version", "fail", f"ddev wp core version failed: {output}")
    return _bool_result("core_version", output == expected, f"expected {expected!r}, got {output!r}")


def check_ddev_php_version(expected: Any, clone_dir: Path) -> CheckResult:
    """DDEV's PHP pin, read straight from ``.ddev/config.yaml`` — a
    pure-file check, no DDEV project need be running."""

    if expected is None:
        return _skip("ddev_php_version")
    actual = _read_ddev_config(clone_dir).php_version
    if actual is None:
        return CheckResult("ddev_php_version", "fail", ".ddev/config.yaml has no php_version pin")
    return _bool_result("ddev_php_version", actual == expected, f"expected {expected!r}, got {actual!r}")


def check_ddev_database(expected: Any, clone_dir: Path) -> CheckResult:
    """DDEV's database engine/version pin, read from ``.ddev/config.yaml``.
    ``expected`` is ``{"type": <flavour>, "version": <major.minor>}``."""

    if expected is None:
        return _skip("ddev_database")
    config = _read_ddev_config(clone_dir)
    actual = {"type": config.db_type, "version": config.db_version}
    ok = actual["type"] == expected.get("type") and actual["version"] == expected.get("version")
    return _bool_result("ddev_database", ok, f"expected {expected!r}, got {actual!r}")


def check_table_prefix(expected: Any, run: RunCommand) -> CheckResult:
    """The adopted-from-production table prefix, written into the marked
    block and verified here via `ddev wp config get table_prefix` — the
    "WordPress finds zero tables" failure mode this guards against
    (platform constraint 12)."""

    if expected is None:
        return _skip("table_prefix")
    ok, output = _run_ddev_wp(run, "config", "get", "table_prefix")
    if not ok:
        return CheckResult("table_prefix", "fail", f"ddev wp config get table_prefix failed: {output}")
    return _bool_result("table_prefix", output == expected, f"expected {expected!r}, got {output!r}")


def check_local_urls(expected: Any, run: RunCommand) -> list[CheckResult]:
    """``home`` and ``siteurl`` equal the local DDEV URL, never production's
    host. Equality against the local URL already implies inequality with
    production's (the two are never the same string), so no separate
    production-host comparison is needed."""

    if expected is None:
        return [_skip("home_url"), _skip("site_url")]
    results: list[CheckResult] = []
    for option, check_id in (("home", "home_url"), ("siteurl", "site_url")):
        ok, output = _run_ddev_wp(run, "option", "get", option)
        if not ok:
            results.append(CheckResult(check_id, "fail", f"ddev wp option get {option} failed: {output}"))
        else:
            results.append(_bool_result(check_id, output == expected, f"expected {expected!r}, got {output!r}"))
    return results


def check_entity_counts(
    expected: Any, run: RunCommand, table_prefix: str
) -> list[CheckResult]:
    """Published posts, pages, attachments, and users — each counted with the
    raw ``ddev wp db query`` SQL :data:`_COUNT_QUERIES` defines (never through
    WP_Query, for the reason documented there — issue #33), against the site's
    real prefixed table (``table_prefix`` + ``posts`` / ``users``, from the
    expectations document's ``tablePrefix``).

    Each count is individually skippable, so an expectations file that only
    pins the counts a baseline actually captured still runs the rest.
    """

    expected = expected or {}
    results: list[CheckResult] = []
    for key, (suffix, where) in _COUNT_QUERIES.items():
        check_id = f"count_{_snake(key)}"
        if key not in expected:
            results.append(_skip(check_id))
            continue
        table = f"{table_prefix}{suffix}"
        ok, count, output = _table_row_count(run, table, where)
        if not ok:
            results.append(CheckResult(check_id, "fail", f"could not query `{table}`: {output}"))
            continue
        results.append(_bool_result(check_id, count == expected[key], f"{table}: expected {expected[key]}, got {count}"))
    return results


def check_total_table_count(expected: Any, run: RunCommand) -> CheckResult:
    """Every table exists locally (spec.md user story 16: "nothing ever hits
    a missing table"). Fewer tables than the baseline is a FAIL — the dump
    enumeration guarantee is broken; more is the softer ATTENTION —
    production may simply have grown a table since the baseline was taken,
    which is not itself a defect."""

    if expected is None:
        return _skip("total_table_count")
    ok, output = _run_ddev_wp(
        run,
        "db",
        "query",
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",
        "--skip-column-names",
    )
    if not ok:
        return CheckResult("total_table_count", "fail", f"table count query failed: {output}")
    try:
        actual = int(output.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return CheckResult("total_table_count", "fail", f"non-numeric table count output: {output!r}")

    if actual < expected:
        return CheckResult(
            "total_table_count",
            "fail",
            f"expected at least {expected} tables, found {actual} — a table may be missing from the dump",
        )
    if actual > expected:
        return CheckResult(
            "total_table_count",
            "attention",
            f"expected {expected} tables, found {actual} — production may have grown new tables since the baseline was captured",
        )
    return CheckResult("total_table_count", "pass", f"{actual} tables, matches the baseline")


def check_operational_tables_empty(expected: Any, run: RunCommand) -> list[CheckResult]:
    """Each named operational table (analytics, cookie-consent, email-log,
    search-index, and — by default — user-submission tables) was created but
    carries no rows, per table."""

    if expected is None:
        return [_skip("operational_tables_empty")]
    results: list[CheckResult] = []
    for table in expected:
        check_id = f"table_empty:{table}"
        ok, count, output = _table_row_count(run, table)
        if not ok:
            results.append(CheckResult(check_id, "fail", f"could not query `{table}`: {output}"))
            continue
        results.append(_bool_result(check_id, count == 0, f"{table}: {count} row(s), expected 0"))
    return results


def check_content_tables_nonempty(expected: Any, run: RunCommand) -> list[CheckResult]:
    """Each named content table actually carries data — the transfer/import
    did not silently drop it, per table."""

    if expected is None:
        return [_skip("content_tables_nonempty")]
    results: list[CheckResult] = []
    for table in expected:
        check_id = f"table_nonempty:{table}"
        ok, count, output = _table_row_count(run, table)
        if not ok:
            results.append(CheckResult(check_id, "fail", f"could not query `{table}`: {output}"))
            continue
        results.append(
            _bool_result(check_id, count is not None and count > 0, f"{table}: {count} row(s), expected > 0")
        )
    return results


def check_excluded_dropins_absent(expected: Any, clone_dir: Path) -> list[CheckResult]:
    """Every excluded drop-in (e.g. ``wp-content/object-cache.php``) is
    absent locally — the pack's exclusion file did its job — per path.
    A pure-file check."""

    if expected is None:
        return [_skip("excluded_dropins_absent")]
    results: list[CheckResult] = []
    for rel_path in expected:
        check_id = f"dropin_absent:{rel_path}"
        present = (clone_dir / rel_path).exists()
        results.append(
            _bool_result(check_id, not present, f"{rel_path} {'present' if present else 'absent'} (expected absent)")
        )
    return results


def check_object_cache_dropin_state(expected: Any, clone_dir: Path) -> CheckResult:
    """The object-cache drop-in's presence matches the resolved ownership
    rule's outcome (spec.md, *Import and localise* step 6 / *Pull
    bookends*) — ``expected`` is whether ``wp-content/object-cache.php``
    should exist after the ownership rule ran. A pure-file check; the actual
    verify-a-real-request-succeeds step already ran during import (step 9 of
    both skills), this only confirms the file-presence outcome that step
    left behind."""

    if expected is None:
        return _skip("object_cache_state")
    present = (clone_dir / "wp-content" / "object-cache.php").is_file()
    return _bool_result(
        "object_cache_state",
        present == bool(expected),
        f"object-cache.php {'present' if present else 'absent'}, expected {'present' if expected else 'absent'}",
    )


def check_sample_urls(expected: Any, fetch: FetchUrl) -> list[CheckResult]:
    """Each sample URL returns HTTP 200 without any WordPress fatal-error
    marker, per URL. The list itself is settled by
    :func:`resolve_sample_urls` — derived from the copy's own database unless
    a caller overrode it — so this function only ever fetches what it is
    handed, and ``None`` still means "nothing to check", never a failure."""

    if expected is None:
        return [_skip("sample_urls")]
    results: list[CheckResult] = []
    for url in expected:
        check_id = f"sample_url:{url}"
        status, body = fetch(url)
        if status != 200:
            results.append(CheckResult(check_id, "fail", f"{url}: HTTP {status}"))
            continue
        markers = [marker for marker in FATAL_ERROR_MARKERS if marker in body]
        if markers:
            results.append(
                CheckResult(check_id, "fail", f"{url}: fatal-error marker(s) present: {', '.join(markers)}")
            )
            continue
        results.append(CheckResult(check_id, "pass", f"{url}: HTTP 200, no fatal-error markers"))
    return results


# The four request shapes a sample-URL run exercises, in the order the report
# reads them. Each is derived independently, so a site that genuinely has none
# of a kind still contributes every other one.
_SAMPLE_URL_SHAPES: tuple[str, ...] = ("front_page", "post", "page", "archive")

# The three WordPress settings that decide what a URL on a site looks like,
# keyed by the expectations sub-key each is compared under and valued by the
# option `wp option get` reads it from. Read off the site under test rather
# than assumed, and — when the source site's own values are recorded — the
# whole of what :func:`check_sample_url_source_parity` compares.
_SITE_SHAPE_OPTIONS: dict[str, str] = {
    "permalinkStructure": "permalink_structure",
    "showOnFront": "show_on_front",
    "pageOnFront": "page_on_front",
}

def _url_key(url: str) -> str:
    """A URL reduced to what makes it the same request: the trailing slash a
    permalink carries and ``wp option get home`` does not is never a different
    page."""

    return url.rstrip("/")


def _sample_url_candidates(run: RunCommand, *args: str) -> tuple[list[str], str | None]:
    """Run one WP-CLI listing that emits a URL per line, returning its URLs
    and — when there are none — the reason: the command's own diagnostic, or
    the plain fact that the site has nothing of this kind."""

    ok, output = _run_ddev_wp(run, *args)
    if not ok:
        return [], output or "could not be listed"
    urls = [line.strip() for line in output.splitlines() if line.strip()]
    if not urls:
        return [], "none found"
    return urls, None


def derive_sample_urls(run: RunCommand) -> SampleUrlDerivation:
    """Ask the copy under test for a representative URL of each shape this
    smoke test exercises — its front page, a published post, a page that is
    not the front page, and an archive — rather than having a caller assemble
    strings only the site itself can get right (issue #60).

    A caller building those strings is the one input that can plausibly be
    built wrongly, and a wrong one reads as a rewrite or flush bug in the copy
    rather than as the bad expectation it is. The site knows its own
    permalinks, so it is asked.

    Every shape but the front page is independent and optional: a site with no
    published post, or no non-empty category, simply contributes none — a fact
    about the site, never a failure to produce an expectation. The front page
    is the one load-bearing answer, since a site that will not answer for
    ``home`` cannot be asked for anything else either; the reason then comes
    back in ``error`` and no URL list is guessed at.
    """

    # The front page, and the only answer whose absence ends the derivation:
    # every other candidate is judged distinct-or-not against it.
    ok, home = _run_ddev_wp(run, "option", "get", "home")
    if not ok or not home:
        reason = home or "the site reported no home URL"
        return SampleUrlDerivation((), {shape: reason for shape in _SAMPLE_URL_SHAPES}, reason)

    resolved: dict[str, str] = {"front_page": home}
    coverage: dict[str, str] = {"front_page": home}

    # The three remaining shapes, one WP-CLI listing each. The page listing
    # asks for two candidates so a site whose front page is a page still
    # yields a real subpage; a candidate the front page already covers is
    # dropped everywhere, since fetching one URL twice tests one request twice.
    listings: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "post",
            ("post", "list", "--post_type=post", "--post_status=publish", "--posts_per_page=1", "--field=url"),
        ),
        (
            "page",
            ("post", "list", "--post_type=page", "--post_status=publish", "--posts_per_page=2", "--field=url"),
        ),
        ("archive", ("term", "list", "category", "--field=url", "--number=1", "--hide_empty=1")),
    )
    for shape, args in listings:
        candidates, sampling_reason = _sample_url_candidates(run, *args)
        distinct = [url for url in candidates if _url_key(url) != _url_key(home)]
        if distinct:
            resolved[shape] = coverage[shape] = distinct[0]
            continue
        # No reason means the site did answer — with nothing but the front
        # page, which the front-page shape already covers.
        coverage[shape] = sampling_reason or "only the front page"

    # Shape order, de-duplicated: the report reads front page first, and no
    # URL earns two fetches however many shapes it happens to cover.
    urls: list[str] = []
    for shape in _SAMPLE_URL_SHAPES:
        url = resolved.get(shape)
        if url and url not in urls:
            urls.append(url)

    return SampleUrlDerivation(tuple(urls), coverage)


def resolve_sample_urls(expected: Any, run: RunCommand) -> SampleUrlResolution:
    """Settle which sample URLs this run fetches, and record where they came
    from.

    Absent is the ordinary case and the whole point of issue #60: the copy is
    asked for its own URLs, so a caller can no longer hand the test a wrong
    expectation that reads as a defect in the copy. A caller-supplied list
    still wins — a genuinely odd site (a multilingual install's localised home
    and subpage, the canary for the rewrite-flush bug) would otherwise be
    untestable — but the override is *recorded* rather than silently obeyed,
    since an unmarked override reproduces this very defect one step further
    from the reader.

    A site that cannot be asked earns ``attention``, never ``fail``: an input
    that could not be gathered is a bad input, not a bad copy, and every other
    check against a site that will not answer is already failing loudly.
    """

    if expected is None:
        derivation = derive_sample_urls(run)
        if derivation.error is not None:
            return SampleUrlResolution(
                (),
                "derived",
                (
                    CheckResult(
                        "sample_urls_source",
                        "attention",
                        f"could not derive sample URLs from the copy: {derivation.error}",
                    ),
                ),
            )
        coverage = ", ".join(
            f"{shape}: {derivation.coverage.get(shape, 'unknown')}" for shape in _SAMPLE_URL_SHAPES
        )
        return SampleUrlResolution(
            derivation.urls,
            "derived",
            (
                CheckResult(
                    "sample_urls_source",
                    "pass",
                    f"{len(derivation.urls)} URL(s) derived from the copy — {coverage}",
                ),
            ),
        )

    # The expectations file is operator-editable input, so a `sampleUrls` that
    # is not a list fails this one check loudly rather than being iterated
    # character by character into a report full of nonsense URLs.
    if not isinstance(expected, list):
        return SampleUrlResolution(
            (),
            "none",
            (
                CheckResult(
                    "sample_urls_source",
                    "fail",
                    f"sampleUrls must be a list of URLs, got {type(expected).__name__}",
                ),
            ),
        )

    if not expected:
        return SampleUrlResolution(
            (), "none", (_skip("sample_urls_source", "the expectations document pins an empty URL list"),)
        )

    return SampleUrlResolution(
        tuple(str(url) for url in expected),
        "supplied",
        (
            _skip(
                "sample_urls_source",
                f"{len(expected)} URL(s) supplied by the caller — the copy was not asked for its own",
            ),
        ),
    )


def read_site_shape(run: RunCommand) -> dict[str, str]:
    """The three URL-deciding settings (:data:`_SITE_SHAPE_OPTIONS`), read off
    the site the runner points at. A setting the site will not answer for is
    omitted rather than guessed, so the parity check below reports it as
    unreadable instead of inventing a disagreement."""

    shape: dict[str, str] = {}
    for key, option in _SITE_SHAPE_OPTIONS.items():
        ok, output = _run_ddev_wp(run, "option", "get", option)
        if ok:
            shape[key] = output
    return shape


def check_sample_url_source_parity(source_shape: Any, clone_shape: Mapping[str, Any]) -> CheckResult:
    """The three settings that decide what a URL looks like — the permalink
    structure and the front-page pair — compared between the source site as
    discovery recorded it and the copy under test.

    A disagreement here may be the most useful thing this test can report: a
    permalink structure or front-page setting that did not survive the
    transfer is exactly the class of defect a fidelity check exists to catch.
    It is still only ``attention``. The copy is the subject under test, and a
    source that has legitimately moved on since discovery took its snapshot is
    not a broken copy — so this names both values for a human and never fails
    the run on its own.

    Both sides are compared as text: the copy's values come back from ``wp
    option get`` as strings, and a recorded ``12`` must never disagree with a
    read-back ``"12"``.
    """

    if source_shape is None:
        return _skip("sample_url_source_parity", "the source site's own URL-deciding settings are not recorded")
    if not isinstance(source_shape, dict):
        return CheckResult(
            "sample_url_source_parity", "fail", "sourceSiteShape expectation must be an object"
        )
    if not source_shape:
        return _skip("sample_url_source_parity", "the source site's own URL-deciding settings are not recorded")

    disagreements = []
    for key in _SITE_SHAPE_OPTIONS:
        if key not in source_shape:
            continue
        source_value = str(source_shape[key])
        if key not in clone_shape:
            disagreements.append(f"{key}: source {source_value!r}, copy unreadable")
            continue
        clone_value = str(clone_shape[key])
        if clone_value != source_value:
            disagreements.append(f"{key}: source {source_value!r}, copy {clone_value!r}")

    if disagreements:
        return CheckResult("sample_url_source_parity", "attention", "; ".join(disagreements))
    return CheckResult(
        "sample_url_source_parity", "pass", "the copy's URL-deciding settings match the source's"
    )


def _bare_host(production_host: str) -> str:
    """Normalise an expectations-file ``productionHost`` — given with or
    without a leading ``www.`` — to its bare root, so callers never have to
    special-case which form the operator happened to record."""

    return production_host.removeprefix("www.")


def _url_shaped_production_host_forms(production_host: str) -> list[str]:
    """The 18 URL-shaped forms a leaked *production_host* reference can take
    on a rendered page — the exact source-form family
    ``docs/implementation-notes.md``'s localisation search-replace passes
    rewrite: 3 scheme prefixes (``https:``, ``http:``, and the empty prefix
    for a protocol-relative URL) x 3 slash-escaping levels (none, the
    JSON-escaped ``\\/``, and the JSON-in-JSON double-escaped ``\\\\/``) x 2
    domain variants (bare host, ``www.``-prefixed). Reusing this exact
    family — rather than a bare-substring needle — is what lets the check
    tell a leaked URL apart from legitimate domain-valued data (a
    cookie-domain string, an e-mail address) that merely contains the host.
    """

    bare_host = _bare_host(production_host)
    domains = (bare_host, f"www.{bare_host}")
    slash_forms = ("//", "\\/\\/", "\\\\/\\\\/")
    scheme_prefixes = ("https:", "http:", "")
    return [f"{scheme}{slashes}{domain}" for scheme in scheme_prefixes for slashes in slash_forms for domain in domains]


def check_local_asset_urls(expected: Any, fetch: FetchUrl) -> CheckResult:
    """The rendered front page carries no lingering **URL-shaped** reference
    to the production host — no bare, protocol-relative, or escaped/
    double-escaped JSON form of it (:func:`_url_shaped_production_host_forms`,
    the same 18-form family the localisation search-replace passes rewrite).
    A bare occurrence of the host *outside* any of those forms — a
    cookie-consent plugin's leading-dot domain value (``"host":".<host>"``)
    or an e-mail address's domain (``info@<host>``) — is legitimate
    domain-valued data, not a search-replace miss; it earns the softer
    ``attention`` verdict (visible in the report, never a FAIL), since
    bare-domain search-replace is itself forbidden by design (it would
    corrupt those very values). ``expected`` is ``{"url": <local front
    page>, "productionHost": <production host, with or without a leading
    "www.">}``."""

    if expected is None:
        return _skip("local_asset_urls")

    # Guard the expectations file's own shape — it is operator-editable
    # input, so a missing key must fail this one check loudly rather than
    # crash the whole report with an uncaught KeyError.
    url = expected.get("url")
    production_host = expected.get("productionHost")
    if not url or not production_host:
        return CheckResult(
            "local_asset_urls",
            "fail",
            "localAssetCheck expectation must carry both 'url' and 'productionHost'",
        )

    status, body = fetch(url)
    if status != 200:
        return CheckResult("local_asset_urls", "fail", f"{url}: HTTP {status}")

    leaks = sorted(needle for needle in _url_shaped_production_host_forms(production_host) if needle in body)
    if leaks:
        return CheckResult(
            "local_asset_urls",
            "fail",
            f"{url}: production host still present in URL form ({', '.join(leaks)}) — search-replace miss",
        )

    # The host string appears, but never inside a URL shape — a cookie
    # banner's domain value or an e-mail address, not a leaked asset URL.
    # Bare-domain search-replace is forbidden by design, so this is never
    # fixable and never a FAIL; it is only worth a human's glance.
    bare_host = _bare_host(production_host)
    if bare_host in body:
        return CheckResult(
            "local_asset_urls",
            "attention",
            f"{url}: '{bare_host}' present outside any URL form (e.g. an e-mail address or a cookie-domain "
            "value) — not a search-replace miss, worth a look",
        )

    return CheckResult(
        "local_asset_urls", "pass", f"{url}: no production-host references, including escaped-slash JSON forms"
    )


def check_db_check_clean(expected: Any, run: RunCommand) -> CheckResult:
    """``wp db check`` exits clean."""

    if expected is None:
        return _skip("db_check")
    completed = run(["ddev", "wp", "db", "check"])
    ok = completed.returncode == 0
    detail = (completed.stdout + completed.stderr).strip() or ("clean" if ok else "wp db check failed")
    return _bool_result("db_check", ok, detail)


def check_active_plugin_count(expected: Any, run: RunCommand) -> CheckResult:
    """The active-plugin count matches the resolved plan's expectation (the
    preserved-inactive-set outcome at pull, or the discovered count at
    clone)."""

    if expected is None:
        return _skip("active_plugin_count")
    ok, output = _run_ddev_wp(run, "plugin", "list", "--status=active", "--format=count")
    if not ok:
        return CheckResult("active_plugin_count", "fail", f"ddev wp plugin list failed: {output}")
    try:
        actual = int(output)
    except ValueError:
        return CheckResult("active_plugin_count", "fail", f"non-numeric plugin count: {output!r}")
    return _bool_result("active_plugin_count", actual == expected, f"expected {expected}, got {actual}")


def check_saved_plan_present(expected: Any, clone_dir: Path) -> CheckResult:
    """The saved plan ``.kntnt-wp-skills.json`` exists — a pure-file check."""

    if expected is None:
        return _skip("saved_plan_present")
    present = (clone_dir / ".kntnt-wp-skills.json").is_file()
    return _bool_result(
        "saved_plan_present", present == bool(expected), f".kntnt-wp-skills.json {'present' if present else 'absent'}"
    )


def check_baseline_present(expected: Any, clone_dir: Path) -> CheckResult:
    """The baseline manifest ``.kntnt-wp-skills/last-sync.json`` exists — a
    pure-file check."""

    if expected is None:
        return _skip("baseline_present")
    present = (clone_dir / ".kntnt-wp-skills" / "last-sync.json").is_file()
    return _bool_result(
        "baseline_present",
        present == bool(expected),
        f".kntnt-wp-skills/last-sync.json {'present' if present else 'absent'}",
    )


def check_rollback_backup_present(expected: Any, clone_dir: Path) -> CheckResult:
    """On pull, a rollback backup exists under ``.kntnt-wp-skills/backups/``
    — a pure-file check; a present-but-empty directory does not count, since
    that is indistinguishable from the backup step never having run."""

    if expected is None:
        return _skip("rollback_backup_present")
    backups_dir = clone_dir / ".kntnt-wp-skills" / "backups"
    present = backups_dir.is_dir() and any(backups_dir.iterdir())
    return _bool_result(
        "rollback_backup_present", present == bool(expected), f"backups dir {'has entries' if present else 'missing or empty'}"
    )


# --- Orchestration: run every check over one expectations document ---------


def run_checks(
    clone_dir: Path,
    expectations: Mapping[str, Any],
    *,
    run_command: RunCommand | None = None,
    fetch_url: FetchUrl | None = None,
) -> dict[str, Any]:
    """Run every check the expectations document activates, and return the
    coherent report: ``ok`` (no FAIL among the checks — ``attention`` and
    ``skip`` never affect it), a ``summary`` of pass/fail/attention/skip
    counts, a ``sampleUrls`` section saying which URLs were fetched and
    whether they were derived from the copy or supplied by the caller, and the
    flat ``checks`` list.

    ``run_command`` and ``fetch_url`` default to the real DDEV/curl-shelling
    implementations bound to ``clone_dir``; a caller — chiefly the test
    suite — may inject fakes for either independently.
    """

    run = run_command or default_run_command(clone_dir)
    fetch = fetch_url or default_fetch_url(run)

    results: list[CheckResult] = []

    results.append(check_core_version(expectations.get("coreVersion"), run))

    ddev = expectations.get("ddev") or {}
    results.append(check_ddev_php_version(ddev.get("phpVersion"), clone_dir))
    results.append(check_ddev_database(ddev.get("database"), clone_dir))

    results.append(check_table_prefix(expectations.get("tablePrefix"), run))
    results.extend(check_local_urls(expectations.get("localUrl"), run))

    results.extend(check_entity_counts(expectations.get("counts"), run, expectations.get("tablePrefix") or ""))

    tables = expectations.get("tables") or {}
    results.append(check_total_table_count(tables.get("total"), run))
    results.extend(check_operational_tables_empty(tables.get("operationalEmpty"), run))
    results.extend(check_content_tables_nonempty(tables.get("contentNonEmpty"), run))

    results.extend(check_excluded_dropins_absent(expectations.get("excludedDropins"), clone_dir))
    results.append(check_object_cache_dropin_state(expectations.get("objectCacheDropinPresent"), clone_dir))
    # Sample URLs come from the copy under test unless the expectations
    # document overrides them (issue #60); the source/clone parity check only
    # asks the copy for its URL-deciding settings when a recorded source value
    # exists to compare them against.
    sample_urls = resolve_sample_urls(expectations.get("sampleUrls"), run)
    results.extend(sample_urls.checks)
    results.extend(check_sample_urls(sample_urls.expectation, fetch))
    source_shape = expectations.get("sourceSiteShape")
    results.append(
        check_sample_url_source_parity(source_shape, read_site_shape(run) if source_shape else {})
    )

    results.append(check_local_asset_urls(expectations.get("localAssetCheck"), fetch))
    results.append(check_db_check_clean(expectations.get("dbCheck"), run))
    results.append(check_active_plugin_count(expectations.get("activePluginCount"), run))
    results.append(check_saved_plan_present(expectations.get("savedPlan"), clone_dir))
    results.append(check_baseline_present(expectations.get("baseline"), clone_dir))
    results.append(check_rollback_backup_present(expectations.get("rollbackBackup"), clone_dir))

    summary = {"pass": 0, "fail": 0, "attention": 0, "skip": 0}
    for result in results:
        summary[result.status] += 1

    return {
        "ok": summary["fail"] == 0,
        "summary": summary,
        "sampleUrls": sample_urls.to_dict(),
        "checks": [result.to_dict() for result in results],
    }


# --- Expectations-file generator (--generate) -------------------------------


def _require_dict(value: Any, context: str) -> dict[str, Any]:
    """Assert a value is a JSON object, raising :class:`GenerateError`
    otherwise — the boundary check that keeps a malformed envelope section
    from crashing the derivation with a raw ``AttributeError``."""

    if not isinstance(value, dict):
        raise GenerateError(f"{context}: expected an object, got {type(value).__name__}")
    return value


def generate_expectations(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Snapshot an expectations document from production's canonical
    discovery document (``scripts/discovery.py``'s output) plus the few
    supplementary, optional facts that document does not itself carry, so
    the operator never hand-writes a baseline (issue #25).

    ``envelope`` shape:

    - ``discovery`` (required) — the canonical discovery document.
    - ``classifications`` (optional) — ``skills/mkwp/scripts/classify.py``'s output; its
      table split derives ``tables.operationalEmpty`` in full, and
      ``tables.contentNonEmpty`` restricted to the always-populated core
      tables in :data:`_ALWAYS_POPULATED_CORE_TABLES` — never the whole
      full-carry list, since "carried in full" only means the transfer did
      not silently empty a table, not that production actually put rows
      in it. Superseded by ``resolvedTableContent`` when both are given.
    - ``resolvedTableContent`` (optional) — the resolved plan's
      ``db_table_content`` decision value (``resolve_plan.py``), the same
      ``{"full", "empty"}`` shape ``classifications.tables`` uses. Takes
      precedence over ``classifications`` for the table split. An operator
      who accepted CARRY at the user_submissions gate (ADR-0014) has
      ``resolve_plan.py`` fold those tables out of the empty list into the
      full-data one; ``classifications.tables.empty`` alone never reflects
      that fold (it is ``classify.py``'s raw, un-folded split), so deriving
      ``tables.operationalEmpty`` from it would FAIL a correct copy that
      genuinely carries the accepted tables.
    - ``localUrl`` (optional) — the local DDEV URL; not derivable from
      discovery alone (that is ``classify.py``'s ``project_name.ddev_url``).
    ``counts`` is primarily sourced from ``discovery.entity_counts`` —
    ``templates/discovery.php``'s cheap ``COUNT(*)`` queries for published
    posts, published pages, attachments, and users, threaded through by
    ``scripts/discovery.py``. Both sides now count the same raw-SQL way:
    :func:`check_entity_counts` issues the same unfiltered ``COUNT(*)`` over
    ``wp db query`` that the template ran, clause-for-clause (issue #33), so
    the expectation and the verifying count share one population by
    construction — no longer by ``wp post list``'s WP_Query count happening to
    match, which any active main-query-filtering plugin (Bogo and its class)
    would break. ``attachments`` in particular is **never** derived from
    discovery's raw attachment list — that list exists to derive the thumbnail
    exclude-set's metadata (``templates/discovery.php``'s query is an INNER
    JOIN on ``_wp_attached_file`` with no post_status filter), a different
    population from the ``post_type = 'attachment' AND post_status NOT IN
    ('trash', 'auto-draft')`` count both the template and the checker run.
    That ``trash``/``auto-draft`` exclusion is what keeps a ``MEDIA_TRASH``
    site from sweeping in trashed media (which would FAIL a correct copy), and
    counting rows rather than list length is what keeps a broken attachment
    row missing ``_wp_attached_file`` from throwing the count off.

    - ``entityCounts`` (optional) — ``{"publishedPosts", "publishedPages",
      "attachments", "users"}``; a per-key override the caller may supply
      directly (e.g. a hand-edited re-verification), taking precedence over
      whatever ``discovery.entity_counts`` reports.
    - ``sampleUrls`` (optional) — an **override** for the smoke-test URL
      list. Omitting it is the intended default: ``run_checks`` then derives
      the URLs from the copy under test, which knows its own permalinks
      better than any caller assembling strings (issue #60). Supply it only
      for a URL the copy cannot derive — a multilingual install's localised
      home and subpage, the canary for the rewrite-flush bug — knowing that a
      supplied list replaces the derived set entirely and is recorded as
      ``supplied`` in the run's report.
    - ``sourceSiteShape`` (optional) — the *source* site's permalink
      structure and front-page pair, for the source/clone parity check.
      Sourced from ``discovery.site``'s ``permalink_structure`` /
      ``show_on_front`` / ``page_on_front`` when the document carries them,
      with a per-key envelope override — the same precedence ``entityCounts``
      follows. Today's discovery document carries none of the three, so the
      parity check stays dormant unless a caller supplies the section; it
      starts reporting of its own accord the moment discovery grows them.
    - ``productionHost`` (optional) — paired with ``localUrl`` into the
      ``localAssetCheck`` expectation.
    - ``objectCacheDropinPresent`` (optional) — the object-cache ownership
      rule's resolved outcome (spec.md, pull §9.6). When ``true``, the
      object-cache drop-in is subtracted from ``excludedDropins`` — a
      correct pull may legitimately leave it PRESENT, and asserting it both
      absent (``excludedDropins``) and present (below) at once is
      self-contradictory. Never supplied at clone, where the ownership rule
      never runs and every discovered drop-in stays excluded.
    - ``preservedInactivePlugins`` (optional) — pull step 9.9's
      preserved-inactive plugin set: plugins ``discovery.plugins.active``
      reports active on production that the local copy deliberately keeps
      deactivated. Subtracted from ``activePluginCount``, which otherwise
      unconditionally takes ``len(discovery.plugins.active)`` and would FAIL
      a correct pull that genuinely leaves fewer plugins active locally.
      Never supplied at clone, where no preserved-inactive bookend runs.
    - ``rebuiltSearchIndexTables`` (optional) — the search-index plugin's main
      table name(s) whose rebuild command actually ran (issue #10: the reindex
      step folded into the thumbnail-regeneration delegation, run when
      discovery's active-plugin list carries a Relevanssi/SearchWP-family
      plugin and its WP-CLI reindex command probes available). Each named
      table is subtracted from ``tables.operationalEmpty`` and added to
      ``tables.contentNonEmpty`` — a rebuilt index is no longer empty, so
      asserting it so would FAIL a correct copy. A name not present in
      ``operationalEmpty`` is still added to ``contentNonEmpty`` rather than
      raising. Omitted (no plugin present, or its CLI command unavailable —
      the report-only fallback) leaves the table split exactly as the raw
      classifier/resolved-plan split derived it.
    - ``mode`` (optional, ``"clone"`` or ``"pull"``, default ``"clone"``) —
      only ``"pull"`` adds the ``rollbackBackup`` expectation, since a
      rollback backup is a pull-only artifact.

    Every derived field mirrors one :func:`run_checks` expectation key
    exactly. A field the envelope gives nothing to derive is simply
    **omitted**, which is what makes the corresponding ``run_checks`` check
    skip rather than fail — the same "individually skippable when absent"
    contract on both sides of this seam.
    """

    envelope = _require_dict(envelope, "input")
    if "discovery" not in envelope:
        raise GenerateError("input: missing required section 'discovery'")
    discovery = _require_dict(envelope["discovery"], "discovery")

    site = _require_dict(discovery.get("site", {}), "discovery.site")
    environment = _require_dict(discovery.get("environment", {}), "discovery.environment")
    database = _require_dict(discovery.get("database", {}), "discovery.database")
    plugins = _require_dict(discovery.get("plugins", {}), "discovery.plugins")
    dropins = discovery.get("dropins") or []

    expectations: dict[str, Any] = {}

    # Versions and the table prefix — straight off the discovery document.
    if site.get("core_version"):
        expectations["coreVersion"] = site["core_version"]

    ddev: dict[str, Any] = {}
    if environment.get("php_major_minor"):
        ddev["phpVersion"] = environment["php_major_minor"]
    if database.get("flavour") and database.get("version"):
        ddev["database"] = {"type": database["flavour"], "version": _major_minor(database["version"])}
    if ddev:
        expectations["ddev"] = ddev

    if database.get("table_prefix"):
        expectations["tablePrefix"] = database["table_prefix"]

    # The local DDEV URL — supplementary, since discovery has no notion of
    # the local site's own URL.
    local_url = envelope.get("localUrl")
    if local_url:
        expectations["localUrl"] = local_url

    # Entity counts: sourced from the discovery document's own entity_counts
    # section (templates/discovery.php's cheap COUNT queries) — including
    # attachments, which is deliberately never derived from discovery's raw
    # attachment list (a differently-scoped, differently-populated query —
    # see the docstring above). The optional entityCounts envelope override
    # still wins per key, the same "this-run answer overrides the default"
    # precedence every other override in this function follows.
    counts: dict[str, Any] = {}
    discovery_entity_counts = discovery.get("entity_counts")
    if isinstance(discovery_entity_counts, dict):
        for snake_key, camel_key in (
            ("published_posts", "publishedPosts"),
            ("published_pages", "publishedPages"),
            ("attachments", "attachments"),
            ("users", "users"),
        ):
            if snake_key in discovery_entity_counts:
                counts[camel_key] = discovery_entity_counts[snake_key]
    entity_counts_override = envelope.get("entityCounts") or {}
    for key in ("publishedPosts", "publishedPages", "attachments", "users"):
        if key in entity_counts_override:
            counts[key] = entity_counts_override[key]
    if counts:
        expectations["counts"] = counts

    # The table split: the total count is discovery's own enumeration; the
    # empty/non-empty name lists need either the resolved plan's own
    # db_table_content decision (preferred — it already reflects a resolved
    # user_submissions CARRY, ADR-0014) or, absent that, the optional raw
    # classifications section. The full-carry list is never taken whole into
    # contentNonEmpty — it only means "not silently emptied by this
    # transfer", not "known to hold rows in production" — see
    # _ALWAYS_POPULATED_CORE_TABLES above.
    tables: dict[str, Any] = {}
    all_tables = database.get("tables")
    if isinstance(all_tables, list) and all_tables:
        tables["total"] = len(all_tables)
    resolved_table_content = envelope.get("resolvedTableContent")
    classifications = envelope.get("classifications")
    table_split = (
        resolved_table_content
        if isinstance(resolved_table_content, dict)
        else classifications.get("tables") if isinstance(classifications, dict) else None
    )
    if isinstance(table_split, dict):
        prefix = database.get("table_prefix", "")
        empty = table_split.get("empty")
        if isinstance(empty, list):
            tables["operationalEmpty"] = sorted(
                entry["name"] for entry in empty if isinstance(entry, dict) and "name" in entry
            )
        full = table_split.get("full")
        if isinstance(full, list) and full:
            non_empty = sorted(
                str(name)
                for name in full
                if isinstance(name, str)
                and _table_suffix(prefix, name) in _ALWAYS_POPULATED_CORE_TABLES
            )
            if non_empty:
                tables["contentNonEmpty"] = non_empty

    # Search-index rebuild (issue #10): the reindex step fills a search-index
    # plugin's main table after import, so a table the classifier's split
    # otherwise expects empty must instead be expected non-empty. Orchestration
    # passes only the table(s) whose rebuild command actually ran; a name
    # absent from operationalEmpty (a stale override, a plugin the classifier
    # never tagged) is still folded into contentNonEmpty rather than raising —
    # a caller-supplied override must never crash the derivation. Non-string
    # entries are dropped rather than raising — an unhashable one (a dict)
    # would break the `set()` below, and a hashable-but-wrong-type one (an
    # int) would break `sorted()` once mixed with the existing `str` table
    # names — the same defensive filter the `full` list above already
    # applies to its own entries. When the filtered set is empty, or every
    # named table was the whole of operationalEmpty, the key is dropped
    # entirely rather than left as an empty list, matching every other
    # "nothing left to derive" field.
    rebuilt_search_index_tables = envelope.get("rebuiltSearchIndexTables")
    if isinstance(rebuilt_search_index_tables, list) and rebuilt_search_index_tables:
        rebuilt = {name for name in rebuilt_search_index_tables if isinstance(name, str)}
        if rebuilt:
            remaining_empty = set(tables.get("operationalEmpty", [])) - rebuilt
            if remaining_empty:
                tables["operationalEmpty"] = sorted(remaining_empty)
            else:
                tables.pop("operationalEmpty", None)
            tables["contentNonEmpty"] = sorted(set(tables.get("contentNonEmpty", [])) | rebuilt)

    if tables:
        expectations["tables"] = tables

    # Excluded drop-ins: production's own drop-in list, anchored under
    # wp-content — every one of them belongs to the pack's exclusion set,
    # except the object-cache drop-in when the ownership rule (spec.md, pull
    # §9.6) resolved to keep it present locally. A drop-in can never be
    # expected both absent (here) and present (objectCacheDropinPresent,
    # below) at once — check_object_cache_dropin_state exists precisely to
    # assert that presence, so folding it into the excluded set unconditionally
    # would self-contradict a correct pull's own expectations document.
    object_cache_present = envelope.get("objectCacheDropinPresent")
    if isinstance(dropins, list) and dropins:
        excluded = sorted(
            f"wp-content/{name}"
            for name in dropins
            if not (name == "object-cache.php" and object_cache_present)
        )
        if excluded:
            expectations["excludedDropins"] = excluded

    if object_cache_present is not None:
        expectations["objectCacheDropinPresent"] = bool(object_cache_present)

    # Sample URLs and the local-asset check: the URL list is an override
    # only — omitted, the checker derives it from the copy itself — while
    # localAssetCheck needs a local URL to make sense, so it only appears when
    # both halves are present.
    sample_urls = envelope.get("sampleUrls")
    if isinstance(sample_urls, list) and sample_urls:
        expectations["sampleUrls"] = list(sample_urls)

    # The source site's own URL-deciding settings, for the parity check.
    # Normalised to strings, since the copy's side of that comparison comes
    # back from `wp option get` as text and a recorded 12 must never disagree
    # with a read-back "12".
    source_shape: dict[str, str] = {}
    source_shape_override = envelope.get("sourceSiteShape") or {}
    for camel_key, option in _SITE_SHAPE_OPTIONS.items():
        if option in site:
            source_shape[camel_key] = str(site[option])
        if camel_key in source_shape_override:
            source_shape[camel_key] = str(source_shape_override[camel_key])
    if source_shape:
        expectations["sourceSiteShape"] = source_shape

    production_host = envelope.get("productionHost")
    if local_url and production_host:
        expectations["localAssetCheck"] = {"url": local_url, "productionHost": production_host}

    # Always-on expectations for a completed run: a clean database, the
    # active-plugin count discovery already reports minus pull's
    # preserved-inactive set (the plugins production shows active that the
    # local copy deliberately leaves deactivated — step 9.9), and the two
    # persistent files every accepted plan writes.
    expectations["dbCheck"] = True

    active = plugins.get("active")
    if isinstance(active, list):
        preserved_inactive = envelope.get("preservedInactivePlugins")
        held_back = (
            len(set(active) & set(preserved_inactive))
            if isinstance(preserved_inactive, list)
            else 0
        )
        expectations["activePluginCount"] = len(active) - held_back

    expectations["savedPlan"] = True
    expectations["baseline"] = True

    if envelope.get("mode") == "pull":
        expectations["rollbackBackup"] = True

    return expectations


# --- CLI ----------------------------------------------------------------


def _usage() -> str:
    return (
        "usage: smoke_test.py <clone_dir> <expectations_file> [--log <report_path>]\n"
        "       smoke_test.py --generate   (envelope JSON on stdin, expectations JSON on stdout)"
    )


def _quiet_summary(report: Mapping[str, Any], report_path: Path) -> dict[str, Any]:
    """Reduce a full report to what a caller has to act on.

    Every routine ``pass`` and ``skip`` stays in the written report; what comes
    back is the verdict, the counts, where the sample URLs came from, where the
    report is, and each ``fail`` or ``attention`` finding — the same reduction
    the delegated path used to get from a subagent's own context, now available
    to a caller that has none. The sample-URL origin rides along because a
    caller with no context to spare is exactly the reader who could not
    otherwise tell a derived expectation from a supplied one.
    """

    anomalies = [
        {"id": check["id"], "status": check["status"], "detail": check["detail"]}
        for check in report["checks"]
        if check["status"] in ("fail", "attention")
    ]
    return {
        "ok": report["ok"],
        "summary": report["summary"],
        "sample_urls": report.get("sampleUrls", {"origin": "none", "urls": []}),
        "report_path": str(report_path),
        "anomalies": anomalies,
    }


def _main_verify(args: list[str]) -> int:
    """Verify mode: run every check the given expectations file activates
    against the given clone directory, print the JSON report, and answer with
    the exit code that classifies what happened.

    :data:`EXIT_COPY_DEFECTIVE` is reserved for the one outcome that is
    evidence against the copy — the checks ran and the report carries a
    ``fail``. Everything that stops this script before it can judge anything
    answers :data:`EXIT_COULD_NOT_RUN`, so a caller reading the exit code can
    never mistake a step that did not run for a copy that is wrong (issue
    #59).

    With ``--log <path>`` the full report is written there and stdout carries
    only the compact summary — the quiet shape an agent running this step
    inline can afford to read.
    """

    report_path: Path | None = None
    if "--log" in args:
        index = args.index("--log")
        if index + 1 >= len(args):
            print(f"smoke_test: {_usage()}", file=sys.stderr)
            return EXIT_COULD_NOT_RUN
        report_path = Path(args[index + 1])
        args = args[:index] + args[index + 2 :]

    if len(args) != 2:
        print(f"smoke_test: {_usage()}", file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    clone_dir = Path(args[0])
    expectations_path = Path(args[1])

    if not clone_dir.is_dir():
        print(f"smoke_test: clone directory not found: {clone_dir}", file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    try:
        raw_text = expectations_path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"smoke_test: cannot read expectations file: {error}", file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    try:
        expectations = json.loads(raw_text)
    except json.JSONDecodeError as error:
        print(f"smoke_test: expectations file is not valid JSON: {error}", file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    if not isinstance(expectations, dict):
        print("smoke_test: expectations file must contain a JSON object", file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    # The checks observe live state over DDEV and curl, both under a timeout,
    # so a probe can raise instead of returning — and a traceback carries no
    # verdict about the copy at all. Broad on purpose: what makes an exception
    # here could-not-run is that no report exists, never which exception it
    # was, and narrowing the catch would let an unanticipated one exit as
    # though the copy were defective.
    try:
        report = run_checks(clone_dir, expectations)
    except Exception as error:
        print(f"smoke_test: the checks could not be run: {error!r}", file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    # Quiet mode routes the whole report to disk; the default keeps the
    # long-standing contract of emitting it on stdout. Emitting it is guarded
    # for the same reason running the checks is: a report that cannot be
    # written says nothing about the copy, and the realistic cause is ENOSPC —
    # the engine has just written a multi-gigabyte unsealed tree into this same
    # scratchpad — or a --log path the caller cannot write to. Left unguarded,
    # either would raise past `main()` and exit 1, which is the one code this
    # script reserves for a defective copy and the one the phase turns into a
    # destructive close-out, so a healthy clone would be condemned by a full
    # disk (issue #59).
    try:
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            json.dump(_quiet_summary(report, report_path), sys.stdout, sort_keys=True)
        else:
            json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    except Exception as error:
        print(f"smoke_test: the report could not be emitted: {error!r}", file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    return EXIT_OK if report["ok"] else EXIT_COPY_DEFECTIVE


def _main_generate() -> int:
    """Generate mode: read an envelope JSON object on stdin, write the
    derived expectations JSON to stdout.

    A malformed envelope answers :data:`EXIT_COULD_NOT_RUN`: this mode
    inspects no copy, so nothing it does can ever be evidence that one is
    defective.
    """

    raw_text = sys.stdin.read()
    try:
        envelope = json.loads(raw_text)
    except json.JSONDecodeError as error:
        print(f"smoke_test: input is not valid JSON: {error}", file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    try:
        expectations = generate_expectations(envelope)
    except GenerateError as error:
        print(f"smoke_test: {error}", file=sys.stderr)
        return EXIT_COULD_NOT_RUN

    json.dump(expectations, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return EXIT_OK


def main() -> int:
    """Dispatch on ``--generate``; everything else is verify mode."""

    args = sys.argv[1:]
    if args and args[0] == "--generate":
        return _main_generate()
    return _main_verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
