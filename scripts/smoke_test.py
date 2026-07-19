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
`clone`/`pull`'s orchestration (delegated to the `thumbnail-smoke-test`
subagent, ``agents/thumbnail-smoke-test.md``) and standalone from a terminal.

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

- **Verify** (default): ``smoke_test.py <clone_dir> <expectations_file>`` —
  positional arguments, since an expectations *file* is naturally a path, not
  a JSON blob worth piping. Emits the JSON report to stdout; exits non-zero
  on any FAIL.
- **Generate** (``--generate``): reads an envelope JSON object from stdin —
  production's canonical discovery document (``scripts/discovery.py``'s
  output) plus the few supplementary facts that document does not itself
  carry (the local DDEV URL, live entity counts, the mapped sample URLs) —
  and writes the derived expectations JSON to stdout, matching the sibling
  helpers' stdin/stdout convention. See :func:`generate_expectations`.
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
    "GenerateError",
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
    "check_saved_plan_present",
    "check_sample_urls",
    "check_table_prefix",
    "check_total_table_count",
    "default_fetch_url",
    "default_run_command",
    "generate_expectations",
    "main",
    "parse_ddev_config",
    "run_checks",
]

Status = Literal["pass", "fail", "attention", "skip"]

# The three WordPress fatal-error markers the transfer engine has always
# grepped for (agents/thumbnail-smoke-test.md, both SKILL.md verify sections)
# — kept identical here so a caller migrating from the ad-hoc check list sees
# the same three strings, never a silently different set.
FATAL_ERROR_MARKERS: tuple[str, ...] = (
    "There has been a critical error",
    "Fatal error",
    "Error establishing a database",
)

# Every entity-count sub-check's id and the `ddev wp` argv that answers it,
# keyed by the expectations sub-key so `check_entity_counts` can iterate one
# table rather than repeating four near-identical bodies.
_COUNT_COMMANDS: dict[str, tuple[str, ...]] = {
    "publishedPosts": ("post", "list", "--post_type=post", "--post_status=publish", "--format=count"),
    "publishedPages": ("post", "list", "--post_type=page", "--post_status=publish", "--format=count"),
    "attachments": ("post", "list", "--post_type=attachment", "--format=count"),
    "users": ("user", "list", "--format=count"),
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
        return subprocess.run(
            list(args), cwd=clone_dir, capture_output=True, text=True, timeout=120
        )

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


def _table_row_count(run: RunCommand, table: str) -> tuple[bool, int | None, str]:
    """Query one table's row count via `ddev wp db query`, returning ``(ok,
    count, raw_output)``. Backtick-quoted so a table name is never mistaken
    for SQL syntax.

    ``table`` comes from an expectations file the generator built from
    production's own discovery output — a remote system — so it is rejected
    outright unless it stays inside the identifier charset a real MySQL/
    MariaDB table name uses. A backtick inside ``table`` would otherwise
    close the surrounding backtick-quoting early, and `ddev wp db query`
    hands the whole string to a client that executes multiple
    ``;``-separated statements, turning a malicious table name into
    arbitrary SQL against the local clone (including, at pull, against the
    rollback backup's source database).
    """

    if not _SAFE_TABLE_NAME_RE.match(table):
        return False, None, f"table name {table!r} contains characters outside [A-Za-z0-9_] — refusing to query it"

    ok, output = _run_ddev_wp(
        run, "db", "query", f"SELECT COUNT(*) FROM `{table}`", "--skip-column-names"
    )
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


def check_entity_counts(expected: Any, run: RunCommand) -> list[CheckResult]:
    """Published posts, pages, attachments, and users — each individually
    skippable, so an expectations file that only pins the counts a baseline
    actually captured still runs the rest."""

    expected = expected or {}
    results: list[CheckResult] = []
    for key, args in _COUNT_COMMANDS.items():
        check_id = f"count_{_snake(key)}"
        if key not in expected:
            results.append(_skip(check_id))
            continue
        ok, output = _run_ddev_wp(run, *args)
        if not ok:
            results.append(CheckResult(check_id, "fail", f"ddev wp {' '.join(args)} failed: {output}"))
            continue
        try:
            actual = int(output)
        except ValueError:
            results.append(CheckResult(check_id, "fail", f"non-numeric count output: {output!r}"))
            continue
        results.append(_bool_result(check_id, actual == expected[key], f"expected {expected[key]}, got {actual}"))
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
    """Each sample URL — drawn from the copy's own database — returns HTTP
    200 without any WordPress fatal-error marker, per URL."""

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


def check_local_asset_urls(expected: Any, fetch: FetchUrl) -> CheckResult:
    """The rendered front page references only local asset URLs — no
    lingering production host, including the escaped-slash JSON forms
    page builders store (``https:\\/\\/<host>``) that a plain search-replace
    pass can miss. ``expected`` is ``{"url": <local front page>,
    "productionHost": <bare production host>}``."""

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

    needles = {
        production_host,
        f"https:\\/\\/{production_host}",
        f"http:\\/\\/{production_host}",
    }
    leaks = sorted(needle for needle in needles if needle in body)
    if leaks:
        return CheckResult(
            "local_asset_urls",
            "fail",
            f"{url}: production host still present ({', '.join(leaks)}) — search-replace miss",
        )
    return CheckResult("local_asset_urls", "pass", f"{url}: no production-host references, including escaped-slash JSON forms")


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
    counts, and the flat ``checks`` list.

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

    results.extend(check_entity_counts(expectations.get("counts"), run))

    tables = expectations.get("tables") or {}
    results.append(check_total_table_count(tables.get("total"), run))
    results.extend(check_operational_tables_empty(tables.get("operationalEmpty"), run))
    results.extend(check_content_tables_nonempty(tables.get("contentNonEmpty"), run))

    results.extend(check_excluded_dropins_absent(expectations.get("excludedDropins"), clone_dir))
    results.append(check_object_cache_dropin_state(expectations.get("objectCacheDropinPresent"), clone_dir))
    results.extend(check_sample_urls(expectations.get("sampleUrls"), fetch))
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
    - ``classifications`` (optional) — ``scripts/classify.py``'s output; its
      table split derives ``tables.operationalEmpty`` in full, and
      ``tables.contentNonEmpty`` restricted to the always-populated core
      tables in :data:`_ALWAYS_POPULATED_CORE_TABLES` — never the whole
      full-carry list, since "carried in full" only means the transfer did
      not silently empty a table, not that production actually put rows
      in it.
    - ``localUrl`` (optional) — the local DDEV URL; not derivable from
      discovery alone (that is ``classify.py``'s ``project_name.ddev_url``).
    - ``entityCounts`` (optional) — ``{"publishedPosts", "publishedPages",
      "users"}``; discovery carries only the raw attachment list, not
      post/page/user counts.
    - ``sampleUrls`` (optional) — the local-URL-mapped smoke-test URL list;
      discovery carries no sample URLs of its own.
    - ``productionHost`` (optional) — paired with ``localUrl`` into the
      ``localAssetCheck`` expectation.
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
    attachments = discovery.get("attachments") or []

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

    # Entity counts: the attachment count is derivable from discovery's raw
    # attachment list; the rest are supplementary live-state facts.
    counts: dict[str, Any] = {}
    entity_counts = envelope.get("entityCounts") or {}
    for key in ("publishedPosts", "publishedPages", "users"):
        if key in entity_counts:
            counts[key] = entity_counts[key]
    if isinstance(attachments, list) and attachments:
        counts["attachments"] = len(attachments)
    if counts:
        expectations["counts"] = counts

    # The table split: the total count is discovery's own enumeration; the
    # empty/non-empty name lists need the optional classifications section.
    # The full-carry list is never taken whole into contentNonEmpty — it
    # only means "not silently emptied by this transfer", not "known to
    # hold rows in production" — see _ALWAYS_POPULATED_CORE_TABLES above.
    tables: dict[str, Any] = {}
    all_tables = database.get("tables")
    if isinstance(all_tables, list) and all_tables:
        tables["total"] = len(all_tables)
    classifications = envelope.get("classifications")
    if isinstance(classifications, dict):
        table_split = classifications.get("tables")
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
    if tables:
        expectations["tables"] = tables

    # Excluded drop-ins: production's own drop-in list, anchored under
    # wp-content — every one of them belongs to the pack's exclusion set.
    if isinstance(dropins, list) and dropins:
        expectations["excludedDropins"] = sorted(f"wp-content/{name}" for name in dropins)

    # Sample URLs and the local-asset check: both need a local URL to make
    # sense, so localAssetCheck only appears when both halves are present.
    sample_urls = envelope.get("sampleUrls")
    if isinstance(sample_urls, list) and sample_urls:
        expectations["sampleUrls"] = list(sample_urls)

    production_host = envelope.get("productionHost")
    if local_url and production_host:
        expectations["localAssetCheck"] = {"url": local_url, "productionHost": production_host}

    # Always-on expectations for a completed run: a clean database, the
    # active-plugin count discovery already reports, and the two persistent
    # files every accepted plan writes.
    expectations["dbCheck"] = True

    active = plugins.get("active")
    if isinstance(active, list):
        expectations["activePluginCount"] = len(active)

    expectations["savedPlan"] = True
    expectations["baseline"] = True

    if envelope.get("mode") == "pull":
        expectations["rollbackBackup"] = True

    return expectations


# --- CLI ----------------------------------------------------------------


def _usage() -> str:
    return (
        "usage: smoke_test.py <clone_dir> <expectations_file>\n"
        "       smoke_test.py --generate   (envelope JSON on stdin, expectations JSON on stdout)"
    )


def _main_verify(args: list[str]) -> int:
    """Verify mode: run every check the given expectations file activates
    against the given clone directory, print the JSON report, and exit
    non-zero on any FAIL."""

    if len(args) != 2:
        print(f"smoke_test: {_usage()}", file=sys.stderr)
        return 2

    clone_dir = Path(args[0])
    expectations_path = Path(args[1])

    if not clone_dir.is_dir():
        print(f"smoke_test: clone directory not found: {clone_dir}", file=sys.stderr)
        return 1

    try:
        raw_text = expectations_path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"smoke_test: cannot read expectations file: {error}", file=sys.stderr)
        return 1

    try:
        expectations = json.loads(raw_text)
    except json.JSONDecodeError as error:
        print(f"smoke_test: expectations file is not valid JSON: {error}", file=sys.stderr)
        return 1

    if not isinstance(expectations, dict):
        print("smoke_test: expectations file must contain a JSON object", file=sys.stderr)
        return 1

    report = run_checks(clone_dir, expectations)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["ok"] else 1


def _main_generate() -> int:
    """Generate mode: read an envelope JSON object on stdin, write the
    derived expectations JSON to stdout."""

    raw_text = sys.stdin.read()
    try:
        envelope = json.loads(raw_text)
    except json.JSONDecodeError as error:
        print(f"smoke_test: input is not valid JSON: {error}", file=sys.stderr)
        return 1

    try:
        expectations = generate_expectations(envelope)
    except GenerateError as error:
        print(f"smoke_test: {error}", file=sys.stderr)
        return 1

    json.dump(expectations, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def main() -> int:
    """Dispatch on ``--generate``; everything else is verify mode."""

    args = sys.argv[1:]
    if args and args[0] == "--generate":
        return _main_generate()
    return _main_verify(args)


if __name__ == "__main__":
    raise SystemExit(main())
