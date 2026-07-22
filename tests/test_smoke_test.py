"""Tests for the deterministic post-clone/pull smoke test (issue #25).

The smoke test's job is to turn the hand-written baseline document a real-site
run used to require into a mechanical, deterministic check surface: a clone
directory and an expectations file go in, a PASS/FAIL/attention report per
check comes out, and any FAIL trips a non-zero exit. Every check is
individually skippable when its expectation key is absent — an expectations
file is never all-or-nothing.

Two edges are exercised separately, per the project's testing decisions:

- **Pure comparison logic** — the fixture-in/verdict-out functions — is tested
  directly with fabricated facts, no filesystem or subprocess involved.
- **The shelling-out edges** (``ddev wp ...``, ``curl``) are exercised through
  ``run_checks`` with an injected fake command runner and fetcher, so the
  suite never spawns a real DDEV project or issues a real HTTP request.
- **Pure-filesystem checks** (drop-in absence, saved-plan/baseline presence,
  the ``.ddev/config.yaml`` pins) are exercised against a real ``tmp_path``
  fixture site, since they need no injection to stay hermetic.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import classify
import smoke_test

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


# --- Fakes for the shelling-out edges -------------------------------------


class FakeCompleted:
    """A duck-typed stand-in for ``subprocess.CompletedProcess`` — only the
    three attributes the helper reads."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def fake_run_command(responses: dict[tuple[str, ...], FakeCompleted]):
    """Build a ``run_command`` fake keyed by the exact argv tuple, so each
    test wires only the commands its scenario actually needs — an argv this
    fixture was never told about is a test bug, not a silently-passing gap."""

    def _run(args):
        key = tuple(args)
        if key not in responses:
            raise AssertionError(f"unexpected command: {list(args)}")
        return responses[key]

    return _run


def fake_fetch_url(responses: dict[str, tuple[int, str]]):
    """Build a ``fetch_url`` fake keyed by URL."""

    def _fetch(url: str):
        if url not in responses:
            raise AssertionError(f"unexpected fetch: {url}")
        return responses[url]

    return _fetch


# --- Pure comparison logic --------------------------------------------------


def test_check_core_version_passes_on_match():
    run = fake_run_command({("ddev", "wp", "core", "version"): FakeCompleted(stdout="7.0.2\n")})

    result = smoke_test.check_core_version("7.0.2", run)

    assert result.status == "pass"


def test_check_core_version_fails_on_mismatch():
    run = fake_run_command({("ddev", "wp", "core", "version"): FakeCompleted(stdout="6.8.2\n")})

    result = smoke_test.check_core_version("7.0.2", run)

    assert result.status == "fail"
    assert "6.8.2" in result.detail


def test_check_core_version_skips_when_expectation_absent():
    run = fake_run_command({})

    result = smoke_test.check_core_version(None, run)

    assert result.status == "skip"


def test_check_core_version_fails_loud_on_command_error():
    run = fake_run_command(
        {("ddev", "wp", "core", "version"): FakeCompleted(returncode=1, stderr="no such site")}
    )

    result = smoke_test.check_core_version("7.0.2", run)

    assert result.status == "fail"
    assert "no such site" in result.detail


def test_check_total_table_count_passes_on_exact_match():
    run = fake_run_command(
        {
            (
                "ddev",
                "wp",
                "db",
                "query",
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",
                "--skip-column-names",
            ): FakeCompleted(stdout="120\n")
        }
    )

    result = smoke_test.check_total_table_count(120, run)

    assert result.status == "pass"


def test_check_total_table_count_fails_when_short():
    run = fake_run_command(
        {
            (
                "ddev",
                "wp",
                "db",
                "query",
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",
                "--skip-column-names",
            ): FakeCompleted(stdout="118\n")
        }
    )

    result = smoke_test.check_total_table_count(120, run)

    assert result.status == "fail"


def test_check_total_table_count_is_attention_when_surplus():
    """More tables than the baseline recorded is not itself a defect —
    production may have grown a new table since the baseline was captured —
    so it earns the softer ``attention`` verdict, never a hard ``fail``."""

    run = fake_run_command(
        {
            (
                "ddev",
                "wp",
                "db",
                "query",
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()",
                "--skip-column-names",
            ): FakeCompleted(stdout="121\n")
        }
    )

    result = smoke_test.check_total_table_count(120, run)

    assert result.status == "attention"


def test_check_operational_tables_empty_reports_each_table():
    run = fake_run_command(
        {
            (
                "ddev",
                "wp",
                "db",
                "query",
                "SELECT COUNT(*) FROM `wp_relevanssi`",
                "--skip-column-names",
            ): FakeCompleted(stdout="0\n"),
            (
                "ddev",
                "wp",
                "db",
                "query",
                "SELECT COUNT(*) FROM `wp_fsmpt_email_logs`",
                "--skip-column-names",
            ): FakeCompleted(stdout="3\n"),
        }
    )

    results = smoke_test.check_operational_tables_empty(
        ["wp_relevanssi", "wp_fsmpt_email_logs"], run
    )

    by_id = {r.id: r for r in results}
    assert by_id["table_empty:wp_relevanssi"].status == "pass"
    assert by_id["table_empty:wp_fsmpt_email_logs"].status == "fail"


def test_check_content_tables_nonempty_reports_each_table():
    run = fake_run_command(
        {
            (
                "ddev",
                "wp",
                "db",
                "query",
                "SELECT COUNT(*) FROM `wp_posts`",
                "--skip-column-names",
            ): FakeCompleted(stdout="423\n"),
            (
                "ddev",
                "wp",
                "db",
                "query",
                "SELECT COUNT(*) FROM `wp_users`",
                "--skip-column-names",
            ): FakeCompleted(stdout="0\n"),
        }
    )

    results = smoke_test.check_content_tables_nonempty(["wp_posts", "wp_users"], run)

    by_id = {r.id: r for r in results}
    assert by_id["table_nonempty:wp_posts"].status == "pass"
    assert by_id["table_nonempty:wp_users"].status == "fail"


def test_check_content_tables_nonempty_rejects_a_table_name_outside_the_identifier_charset():
    """A table name is expectations-file input ultimately sourced from
    production's own discovery output — a remote system. A name carrying a
    backtick or a statement separator must fail that one table's check
    without ever reaching the shell, rather than break out of the
    surrounding backtick-quoting and execute as SQL."""

    run = fake_run_command({})  # any shelled-out command here is the defect itself

    results = smoke_test.check_content_tables_nonempty(["wp_posts`; DROP TABLE wp_users; --"], run)

    assert results[0].status == "fail"
    assert "outside [A-Za-z0-9_]" in results[0].detail


def test_check_operational_tables_empty_rejects_a_table_name_outside_the_identifier_charset():
    run = fake_run_command({})  # any shelled-out command here is the defect itself

    results = smoke_test.check_operational_tables_empty(["wp_relevanssi`x"], run)

    assert results[0].status == "fail"
    assert "outside [A-Za-z0-9_]" in results[0].detail


def test_check_entity_counts_are_individually_skippable():
    run = fake_run_command(
        {
            (
                "ddev",
                "wp",
                "db",
                "query",
                "SELECT COUNT(*) FROM `wp_posts` WHERE post_type = 'post' AND post_status = 'publish'",
                "--skip-column-names",
            ): FakeCompleted(stdout="361\n"),
        }
    )

    results = smoke_test.check_entity_counts({"publishedPosts": 361}, run, "wp_")

    by_id = {r.id: r for r in results}
    assert by_id["count_published_posts"].status == "pass"
    assert by_id["count_published_pages"].status == "skip"
    assert by_id["count_attachments"].status == "skip"
    assert by_id["count_users"].status == "skip"


def test_check_entity_counts_use_raw_sql_so_a_query_filtering_plugin_cannot_false_fail():
    """Regression for the Bogo false-positive (issue #33). Bogo hooks the
    main query and narrows WP_Query to one locale, so
    ``wp post list --format=count`` returns roughly half the true row count
    (live-verified: 46 of 92 published pages) — while the discovery template
    derived the expectation from an unfiltered raw ``COUNT(*)`` (92). Counting
    the same raw-SQL way over ``wp db query`` — never through WP_Query — the
    check sees the full 92 and PASSes a complete copy the old WP_Query count
    would have FAILed."""

    # The WP_Query-based count Bogo would have filtered down to — wired to
    # document what the old check saw and prove the fixed check never consumes
    # it (it asserts the raw 92, not the filtered 46).
    filtered_wp_query_count = (
        "ddev", "wp", "post", "list", "--post_type=page", "--post_status=publish", "--format=count",
    )
    raw_sql_count = (
        "ddev",
        "wp",
        "db",
        "query",
        "SELECT COUNT(*) FROM `wp_posts` WHERE post_type = 'page' AND post_status = 'publish'",
        "--skip-column-names",
    )
    run = fake_run_command(
        {
            filtered_wp_query_count: FakeCompleted(stdout="46\n"),
            raw_sql_count: FakeCompleted(stdout="92\n"),
        }
    )

    results = smoke_test.check_entity_counts({"publishedPages": 92}, run, "wp_")

    by_id = {r.id: r for r in results}
    assert by_id["count_published_pages"].status == "pass"
    assert "92" in by_id["count_published_pages"].detail


def test_check_entity_counts_use_the_sites_real_table_prefix():
    """The raw-SQL count must target the site's real prefixed tables (a
    non-default prefix leaves WordPress finding zero rows in ``wp_posts``);
    the prefix threads in from the expectations document's ``tablePrefix``."""

    run = fake_run_command(
        {
            (
                "ddev",
                "wp",
                "db",
                "query",
                "SELECT COUNT(*) FROM `smt_users`",
                "--skip-column-names",
            ): FakeCompleted(stdout="7\n"),
        }
    )

    results = smoke_test.check_entity_counts({"users": 7}, run, "smt_")

    assert results[0].id == "count_published_posts" and results[0].status == "skip"
    by_id = {r.id: r for r in results}
    assert by_id["count_users"].status == "pass"


def test_check_sample_urls_fails_on_fatal_error_marker():
    fetch = fake_fetch_url(
        {
            "https://smoltek.ddev.site/technology/": (200, "<html>ok</html>"),
            "https://smoltek.ddev.site/news/": (
                200,
                "<html>There has been a critical error on this website.</html>",
            ),
        }
    )

    results = smoke_test.check_sample_urls(
        ["https://smoltek.ddev.site/technology/", "https://smoltek.ddev.site/news/"], fetch
    )

    by_id = {r.id: r for r in results}
    assert by_id["sample_url:https://smoltek.ddev.site/technology/"].status == "pass"
    assert by_id["sample_url:https://smoltek.ddev.site/news/"].status == "fail"


def test_check_sample_urls_fails_on_non_200():
    fetch = fake_fetch_url({"https://smoltek.ddev.site/gone/": (404, "not found")})

    results = smoke_test.check_sample_urls(["https://smoltek.ddev.site/gone/"], fetch)

    assert results[0].status == "fail"
    assert "404" in results[0].detail


def test_check_local_asset_urls_catches_escaped_slash_production_host():
    fetch = fake_fetch_url(
        {
            "https://smoltek.ddev.site/": (
                200,
                '{"url":"https:\\/\\/www.smoltek.com\\/wp-content\\/theme.css"}',
            )
        }
    )

    result = smoke_test.check_local_asset_urls(
        {"url": "https://smoltek.ddev.site/", "productionHost": "www.smoltek.com"}, fetch
    )

    assert result.status == "fail"


def test_check_local_asset_urls_catches_double_escaped_slash_production_host():
    """JSON-within-JSON storage (e.g. a cookie-banner config nested inside
    another plugin's JSON option) doubles the escaping to ``\\\\/\\\\/`` —
    the bare-host needle still catches it as a substring, since backslash
    escaping never touches the host segment itself."""

    fetch = fake_fetch_url(
        {
            "https://smoltek.ddev.site/": (
                200,
                '{"config":"{\\"cookieUrl\\":\\"https:\\\\/\\\\/www.smoltek.com\\\\/\\"}"}',
            )
        }
    )

    result = smoke_test.check_local_asset_urls(
        {"url": "https://smoltek.ddev.site/", "productionHost": "www.smoltek.com"}, fetch
    )

    assert result.status == "fail"


def test_check_local_asset_urls_passes_when_clean():
    fetch = fake_fetch_url(
        {"https://smoltek.ddev.site/": (200, '{"url":"https:\\/\\/smoltek.ddev.site\\/theme.css"}')}
    )

    result = smoke_test.check_local_asset_urls(
        {"url": "https://smoltek.ddev.site/", "productionHost": "www.smoltek.com"}, fetch
    )

    assert result.status == "pass"


# The 18 URL-shaped forms of a leaked production host that
# docs/implementation-notes.md's localisation search-replace passes rewrite:
# 3 scheme prefixes (``https:``, ``http:``, and the empty prefix for a
# protocol-relative URL) x 3 slash-escaping levels (none, the JSON-escaped
# ``\/``, and the JSON-in-JSON double-escaped ``\\/``) x 2 domain variants
# (bare host, ``www.``-prefixed). Written out literally rather than
# generated, so a regression in the check's own form-generation logic cannot
# quietly shrink the family this test locks in place.
_EIGHTEEN_URL_SHAPED_PRODUCTION_HOST_FORMS = [
    "https://smoltek.com",
    "https://www.smoltek.com",
    "http://smoltek.com",
    "http://www.smoltek.com",
    "//smoltek.com",
    "//www.smoltek.com",
    "https:\\/\\/smoltek.com",
    "https:\\/\\/www.smoltek.com",
    "http:\\/\\/smoltek.com",
    "http:\\/\\/www.smoltek.com",
    "\\/\\/smoltek.com",
    "\\/\\/www.smoltek.com",
    "https:\\\\/\\\\/smoltek.com",
    "https:\\\\/\\\\/www.smoltek.com",
    "http:\\\\/\\\\/smoltek.com",
    "http:\\\\/\\\\/www.smoltek.com",
    "\\\\/\\\\/smoltek.com",
    "\\\\/\\\\/www.smoltek.com",
]


@pytest.mark.parametrize("leaked_form", _EIGHTEEN_URL_SHAPED_PRODUCTION_HOST_FORMS)
def test_check_local_asset_urls_fails_on_each_url_shaped_production_host_form(leaked_form):
    """Every one of the 18 URL-shaped forms a leaked production reference can
    take still fails the check — this is the actual search-replace-miss
    signal the check exists to catch (issue #31)."""

    fetch = fake_fetch_url({"https://smoltek.ddev.site/": (200, f'{{"asset":"{leaked_form}/theme.css"}}')})

    result = smoke_test.check_local_asset_urls(
        {"url": "https://smoltek.ddev.site/", "productionHost": "smoltek.com"}, fetch
    )

    assert result.status == "fail"


def test_check_local_asset_urls_catches_bare_leak_when_production_host_has_www():
    """productionHost may be given with a leading 'www.' (the canonical
    form); a leaked bare-domain URL (no 'www.') must still fail — both
    domain variants belong to the same production site."""

    fetch = fake_fetch_url({"https://smoltek.ddev.site/": (200, '{"asset":"https://smoltek.com/theme.css"}')})

    result = smoke_test.check_local_asset_urls(
        {"url": "https://smoltek.ddev.site/", "productionHost": "www.smoltek.com"}, fetch
    )

    assert result.status == "fail"


def test_check_local_asset_urls_flags_email_and_cookie_domain_as_attention_not_fail():
    """A cookie-consent plugin's leading-dot domain value
    (``"host":".<host>"``) and an e-mail address's domain (``info@<host>``)
    are legitimate domain-valued data, not a URL-shaped leak — the check
    must not FAIL a correct clone over either (issue #31). It is still
    worth a human's glance, hence the softer ``attention`` verdict rather
    than a silent PASS."""

    fetch = fake_fetch_url(
        {
            "https://smoltek.ddev.site/": (
                200,
                '{"contact":"info@smoltek.com","cookieDomain":{"host":".smoltek.com"}}',
            )
        }
    )

    result = smoke_test.check_local_asset_urls(
        {"url": "https://smoltek.ddev.site/", "productionHost": "smoltek.com"}, fetch
    )

    assert result.status == "attention"


def test_check_local_asset_urls_fails_loud_when_url_is_missing():
    """The expectations file's ``localAssetCheck`` object is operator-editable
    input; a missing 'url' key must fail this one check with a diagnostic
    rather than crash the whole report with an uncaught KeyError. The empty
    fetch fake also proves the guard short-circuits before ever fetching."""

    fetch = fake_fetch_url({})

    result = smoke_test.check_local_asset_urls({"productionHost": "www.smoltek.com"}, fetch)

    assert result.status == "fail"
    assert "url" in result.detail


def test_check_local_asset_urls_fails_loud_when_production_host_is_missing():
    fetch = fake_fetch_url({})

    result = smoke_test.check_local_asset_urls({"url": "https://smoltek.ddev.site/"}, fetch)

    assert result.status == "fail"
    assert "productionHost" in result.detail


def test_check_db_check_clean_reads_exit_code():
    run = fake_run_command({("ddev", "wp", "db", "check"): FakeCompleted(returncode=0, stdout="Success")})

    result = smoke_test.check_db_check_clean(True, run)

    assert result.status == "pass"


def test_check_db_check_clean_fails_on_nonzero_exit():
    run = fake_run_command(
        {("ddev", "wp", "db", "check"): FakeCompleted(returncode=1, stderr="Table wp_posts is corrupt")}
    )

    result = smoke_test.check_db_check_clean(True, run)

    assert result.status == "fail"


def test_check_active_plugin_count():
    run = fake_run_command(
        {
            ("ddev", "wp", "plugin", "list", "--status=active", "--format=count"): FakeCompleted(
                stdout="34\n"
            )
        }
    )

    assert smoke_test.check_active_plugin_count(34, run).status == "pass"
    assert smoke_test.check_active_plugin_count(33, run).status == "fail"


def test_check_table_prefix_passes_on_match():
    run = fake_run_command(
        {("ddev", "wp", "config", "get", "table_prefix"): FakeCompleted(stdout="wp_\n")}
    )

    assert smoke_test.check_table_prefix("wp_", run).status == "pass"


def test_check_table_prefix_fails_on_mismatch():
    run = fake_run_command(
        {("ddev", "wp", "config", "get", "table_prefix"): FakeCompleted(stdout="wp_\n")}
    )

    result = smoke_test.check_table_prefix("smt_", run)

    assert result.status == "fail"
    assert "wp_" in result.detail


def test_check_table_prefix_skips_when_expectation_absent():
    run = fake_run_command({})

    assert smoke_test.check_table_prefix(None, run).status == "skip"


def test_check_table_prefix_fails_loud_on_command_error():
    run = fake_run_command(
        {("ddev", "wp", "config", "get", "table_prefix"): FakeCompleted(returncode=1, stderr="no such site")}
    )

    result = smoke_test.check_table_prefix("wp_", run)

    assert result.status == "fail"
    assert "no such site" in result.detail


def test_check_local_urls_passes_when_home_and_siteurl_equal_the_local_ddev_url():
    """The issue's own bullet: home/siteurl must equal the local DDEV URL,
    never production's host."""

    run = fake_run_command(
        {
            ("ddev", "wp", "option", "get", "home"): FakeCompleted(stdout="https://smoltek.ddev.site\n"),
            ("ddev", "wp", "option", "get", "siteurl"): FakeCompleted(stdout="https://smoltek.ddev.site\n"),
        }
    )

    results = smoke_test.check_local_urls("https://smoltek.ddev.site", run)

    by_id = {r.id: r for r in results}
    assert by_id["home_url"].status == "pass"
    assert by_id["site_url"].status == "pass"


def test_check_local_urls_fails_when_a_url_still_points_at_the_production_host():
    run = fake_run_command(
        {
            ("ddev", "wp", "option", "get", "home"): FakeCompleted(stdout="https://www.smoltek.com\n"),
            ("ddev", "wp", "option", "get", "siteurl"): FakeCompleted(stdout="https://smoltek.ddev.site\n"),
        }
    )

    results = smoke_test.check_local_urls("https://smoltek.ddev.site", run)

    by_id = {r.id: r for r in results}
    assert by_id["home_url"].status == "fail"
    assert "www.smoltek.com" in by_id["home_url"].detail
    assert by_id["site_url"].status == "pass"


def test_check_local_urls_skips_both_when_expectation_absent():
    run = fake_run_command({})

    results = smoke_test.check_local_urls(None, run)

    assert {r.id for r in results} == {"home_url", "site_url"}
    assert all(r.status == "skip" for r in results)


def test_check_local_urls_fails_loud_on_command_error():
    run = fake_run_command(
        {
            ("ddev", "wp", "option", "get", "home"): FakeCompleted(returncode=1, stderr="no such site"),
            ("ddev", "wp", "option", "get", "siteurl"): FakeCompleted(stdout="https://smoltek.ddev.site\n"),
        }
    )

    results = smoke_test.check_local_urls("https://smoltek.ddev.site", run)

    by_id = {r.id: r for r in results}
    assert by_id["home_url"].status == "fail"
    assert "no such site" in by_id["home_url"].detail


# --- Pure-filesystem checks (fabricated site dirs) --------------------------


@pytest.fixture
def clone_dir(tmp_path: Path) -> Path:
    """A fabricated clone directory shaped like a real one: the DDEV config,
    the saved plan, and the derived state directory."""

    root = tmp_path / "site"
    (root / ".ddev").mkdir(parents=True)
    (root / ".ddev" / "config.yaml").write_text(
        'php_version: "8.4"\n'
        "database:\n"
        "  type: mariadb\n"
        '  version: "11.4"\n',
        encoding="utf-8",
    )
    (root / ".kntnt-wp-skills.json").write_text("{}", encoding="utf-8")
    (root / ".kntnt-wp-skills").mkdir(exist_ok=True)
    (root / ".kntnt-wp-skills" / "last-sync.json").write_text("{}", encoding="utf-8")
    (root / "wp-content").mkdir(parents=True)
    return root


def test_check_ddev_php_version_reads_config_yaml(clone_dir: Path):
    result = smoke_test.check_ddev_php_version("8.4", clone_dir)

    assert result.status == "pass"


def test_check_ddev_php_version_fails_on_mismatch(clone_dir: Path):
    result = smoke_test.check_ddev_php_version("8.3", clone_dir)

    assert result.status == "fail"


def test_check_ddev_database_reads_type_and_version(clone_dir: Path):
    result = smoke_test.check_ddev_database({"type": "mariadb", "version": "11.4"}, clone_dir)

    assert result.status == "pass"


def test_check_ddev_database_fails_on_wrong_flavour(clone_dir: Path):
    result = smoke_test.check_ddev_database({"type": "mysql", "version": "11.4"}, clone_dir)

    assert result.status == "fail"


def test_check_ddev_config_missing_file_fails_rather_than_crashes(tmp_path: Path):
    empty_dir = tmp_path / "no-ddev-here"
    empty_dir.mkdir()

    result = smoke_test.check_ddev_php_version("8.4", empty_dir)

    assert result.status == "fail"


def test_check_excluded_dropins_absent_passes_when_absent(clone_dir: Path):
    results = smoke_test.check_excluded_dropins_absent(
        ["wp-content/object-cache.php"], clone_dir
    )

    assert results[0].status == "pass"


def test_check_excluded_dropins_absent_fails_when_present(clone_dir: Path):
    (clone_dir / "wp-content" / "object-cache.php").write_text("<?php\n", encoding="utf-8")

    results = smoke_test.check_excluded_dropins_absent(
        ["wp-content/object-cache.php"], clone_dir
    )

    assert results[0].status == "fail"


def test_check_object_cache_dropin_state_matches_expectation(clone_dir: Path):
    absent = smoke_test.check_object_cache_dropin_state(False, clone_dir)
    assert absent.status == "pass"

    (clone_dir / "wp-content" / "object-cache.php").write_text("<?php\n", encoding="utf-8")
    now_present = smoke_test.check_object_cache_dropin_state(True, clone_dir)
    assert now_present.status == "pass"
    mismatched = smoke_test.check_object_cache_dropin_state(False, clone_dir)
    assert mismatched.status == "fail"


def test_check_saved_plan_present(clone_dir: Path):
    assert smoke_test.check_saved_plan_present(True, clone_dir).status == "pass"

    (clone_dir / ".kntnt-wp-skills.json").unlink()
    assert smoke_test.check_saved_plan_present(True, clone_dir).status == "fail"


def test_check_baseline_present(clone_dir: Path):
    assert smoke_test.check_baseline_present(True, clone_dir).status == "pass"


def test_check_rollback_backup_present_requires_a_nonempty_backups_dir(clone_dir: Path):
    absent = smoke_test.check_rollback_backup_present(True, clone_dir)
    assert absent.status == "fail"

    backups = clone_dir / ".kntnt-wp-skills" / "backups"
    backups.mkdir()
    (backups / "local-pre-import-20260719.sql.gz").write_bytes(b"stub")
    present = smoke_test.check_rollback_backup_present(True, clone_dir)
    assert present.status == "pass"


def test_check_rollback_backup_skipped_when_expectation_absent(clone_dir: Path):
    assert smoke_test.check_rollback_backup_present(None, clone_dir).status == "skip"


# --- The parser for .ddev/config.yaml (pure, no filesystem) ----------------


def test_parse_ddev_config_extracts_php_and_database():
    text = 'php_version: "8.3"\ndatabase:\n  type: mariadb\n  version: "11.4"\n'

    config = smoke_test.parse_ddev_config(text)

    assert config.php_version == "8.3"
    assert config.db_type == "mariadb"
    assert config.db_version == "11.4"


def test_parse_ddev_config_tolerates_missing_database_block():
    text = 'php_version: "8.3"\n'

    config = smoke_test.parse_ddev_config(text)

    assert config.php_version == "8.3"
    assert config.db_type is None
    assert config.db_version is None


# --- run_checks end-to-end (injected fakes; no real shelling out) ----------


def test_run_checks_reports_ok_true_when_everything_passes(clone_dir: Path):
    run = fake_run_command(
        {
            ("ddev", "wp", "core", "version"): FakeCompleted(stdout="7.0.2\n"),
        }
    )

    report = smoke_test.run_checks(clone_dir, {"coreVersion": "7.0.2"}, run_command=run)

    assert report["ok"] is True
    assert report["summary"]["fail"] == 0
    ids = {c["id"] for c in report["checks"]}
    assert "core_version" in ids


def test_run_checks_reports_ok_false_on_any_fail(clone_dir: Path):
    run = fake_run_command(
        {
            ("ddev", "wp", "core", "version"): FakeCompleted(stdout="6.8.2\n"),
        }
    )

    report = smoke_test.run_checks(clone_dir, {"coreVersion": "7.0.2"}, run_command=run)

    assert report["ok"] is False
    assert report["summary"]["fail"] == 1


def test_run_checks_skips_every_check_with_no_expectation(clone_dir: Path):
    run = fake_run_command({})

    report = smoke_test.run_checks(clone_dir, {}, run_command=run)

    assert report["ok"] is True
    assert report["summary"]["pass"] == 0
    assert report["summary"]["fail"] == 0
    assert report["summary"]["skip"] > 0


def test_run_checks_covers_pure_filesystem_expectations_without_shelling_out(clone_dir: Path):
    """An expectations file limited to the pure-file checks never has to call
    the injected runner at all — an empty fake proves nothing unexpected was
    shelled out."""

    run = fake_run_command({})

    report = smoke_test.run_checks(
        clone_dir,
        {
            "ddev": {"phpVersion": "8.4", "database": {"type": "mariadb", "version": "11.4"}},
            "excludedDropins": ["wp-content/object-cache.php"],
            "savedPlan": True,
            "baseline": True,
        },
        run_command=run,
    )

    assert report["ok"] is True


def test_run_checks_wires_table_prefix_and_local_urls_end_to_end(clone_dir: Path):
    """The issue's own explicit bullets — home/siteurl equal the local DDEV
    URL, never production's host, and the table prefix — reach
    ``run_checks`` from the expectations document, not just their standalone
    check functions."""

    run = fake_run_command(
        {
            ("ddev", "wp", "config", "get", "table_prefix"): FakeCompleted(stdout="wp_\n"),
            ("ddev", "wp", "option", "get", "home"): FakeCompleted(stdout="https://smoltek.ddev.site\n"),
            ("ddev", "wp", "option", "get", "siteurl"): FakeCompleted(stdout="https://smoltek.ddev.site\n"),
        }
    )

    report = smoke_test.run_checks(
        clone_dir,
        {"tablePrefix": "wp_", "localUrl": "https://smoltek.ddev.site"},
        run_command=run,
    )

    ids = {c["id"]: c["status"] for c in report["checks"]}
    assert ids["table_prefix"] == "pass"
    assert ids["home_url"] == "pass"
    assert ids["site_url"] == "pass"
    assert report["ok"] is True


def test_run_checks_fails_when_local_url_still_points_at_production(clone_dir: Path):
    run = fake_run_command(
        {
            ("ddev", "wp", "option", "get", "home"): FakeCompleted(stdout="https://www.smoltek.com\n"),
            ("ddev", "wp", "option", "get", "siteurl"): FakeCompleted(stdout="https://smoltek.ddev.site\n"),
        }
    )

    report = smoke_test.run_checks(
        clone_dir, {"localUrl": "https://smoltek.ddev.site"}, run_command=run
    )

    assert report["ok"] is False
    ids = {c["id"]: c["status"] for c in report["checks"]}
    assert ids["home_url"] == "fail"


# --- The CLI: verify mode ---------------------------------------------------


def test_cli_verify_mode_exits_nonzero_on_fail(clone_dir: Path, tmp_path: Path):
    expectations_path = tmp_path / "expectations.json"
    expectations_path.write_text(
        json.dumps({"savedPlan": True, "baseline": True}), encoding="utf-8"
    )
    (clone_dir / ".kntnt-wp-skills.json").unlink()

    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "smoke_test.py"), str(clone_dir), str(expectations_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["ok"] is False


def test_cli_verify_mode_exits_zero_on_pass(clone_dir: Path, tmp_path: Path):
    expectations_path = tmp_path / "expectations.json"
    expectations_path.write_text(
        json.dumps(
            {
                "ddev": {"phpVersion": "8.4", "database": {"type": "mariadb", "version": "11.4"}},
                "savedPlan": True,
                "baseline": True,
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "smoke_test.py"), str(clone_dir), str(expectations_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["ok"] is True


def test_cli_verify_mode_fails_loud_on_missing_clone_dir(tmp_path: Path):
    expectations_path = tmp_path / "expectations.json"
    expectations_path.write_text("{}", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS_DIR / "smoke_test.py"),
            str(tmp_path / "does-not-exist"),
            str(expectations_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stderr.strip()


def test_cli_verify_mode_fails_loud_on_malformed_expectations_json(clone_dir: Path, tmp_path: Path):
    expectations_path = tmp_path / "expectations.json"
    expectations_path.write_text("{not json", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "smoke_test.py"), str(clone_dir), str(expectations_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stderr.strip()


# --- Generator mode ----------------------------------------------------------


def test_generate_expectations_derives_versions_and_prefix_from_discovery():
    envelope = {
        "discovery": {
            "site": {"core_version": "7.0.2"},
            "environment": {"php_major_minor": "8.4"},
            "database": {
                "flavour": "mariadb",
                "version": "11.4.12-MariaDB",
                "table_prefix": "wp_",
                "tables": ["wp_posts", "wp_options"],
            },
            "plugins": {"active": ["a/a.php", "b/b.php"]},
            "dropins": ["object-cache.php"],
            "attachments": [{"file": "2026/07/a.jpg", "sizes": []}],
        }
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["coreVersion"] == "7.0.2"
    assert expectations["ddev"]["phpVersion"] == "8.4"
    assert expectations["ddev"]["database"] == {"type": "mariadb", "version": "11.4"}
    assert expectations["tablePrefix"] == "wp_"
    assert expectations["tables"]["total"] == 2
    assert expectations["activePluginCount"] == 2
    assert expectations["excludedDropins"] == ["wp-content/object-cache.php"]
    assert expectations["savedPlan"] is True
    assert expectations["baseline"] is True
    assert "rollbackBackup" not in expectations


def test_generate_expectations_subtracts_pulls_preserved_inactive_plugins_from_the_active_count():
    """Same defect class as the object-cache drop-in fix (commit d5a1210):
    pull's step 9.9 re-applies the preserved-inactive plugin set — plugins
    discovery found active on production that the operator's local copy
    deliberately keeps deactivated (spec.md pull step 9). Deriving
    ``activePluginCount`` from ``len(discovery.plugins.active)`` alone
    ignores that outcome and FAILs a correct pull, which genuinely leaves
    fewer plugins active locally than production reports. When
    ``preservedInactivePlugins`` names a subset of the active list, those
    plugins are subtracted from the count."""

    envelope = {
        "discovery": {"plugins": {"active": ["a/a.php", "b/b.php", "c/c.php"]}},
        "preservedInactivePlugins": ["b/b.php"],
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["activePluginCount"] == 2


def test_generate_expectations_keeps_the_raw_active_count_when_nothing_is_preserved_inactive():
    """Clone never walks the preserved-inactive-set bookend (spec.md, Clone
    bookends: "no preserved inactive set"), so an envelope that never
    supplies ``preservedInactivePlugins`` leaves the count exactly as
    discovery reports it."""

    envelope = {"discovery": {"plugins": {"active": ["a/a.php", "b/b.php"]}}}

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["activePluginCount"] == 2


def test_generate_expectations_marks_pull_mode_with_rollback_backup():
    envelope = {"discovery": {}, "mode": "pull"}

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["rollbackBackup"] is True


def test_generate_expectations_never_derives_attachment_count_from_discoverys_attachment_list():
    """Issue #25 x #19 union: discovery's raw attachment list exists to
    derive the thumbnail exclude-set's metadata (``templates/discovery.php``
    is an INNER JOIN on ``_wp_attached_file`` with no post_status filter),
    not to count attachments — a different population from the verifying
    check's raw-SQL ``COUNT(*) ... WHERE post_type = 'attachment' AND
    post_status NOT IN ('trash', 'auto-draft')`` (issue #33). On a real site
    with trashed media (MEDIA_TRASH) or a broken attachment row missing
    ``_wp_attached_file``, the two totals diverge, so deriving the count from
    the list length would FAIL a correct copy. The list's length must never
    feed ``counts.attachments``."""

    envelope = {
        "discovery": {
            "attachments": [
                {"file": "2026/07/a.jpg", "sizes": []},
                {"file": "2026/07/b.jpg", "sizes": []},
            ],
        },
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert "attachments" not in expectations.get("counts", {})


def test_check_entity_count_queries_carry_the_expected_table_and_where_clauses():
    """The checker counts with raw SQL over ``wp db query`` — never through
    ``wp post list`` / ``wp user list``, which any active main-query-filtering
    plugin (Bogo and its whole class) silently narrows (issue #33). After the
    Extractor cutover the ``entity_counts`` these are compared against at run
    time are produced by ``scripts/bootstrap_parse.py`` from the bootstrap
    extraction's parsed rows (the retired ``templates/discovery.php`` SQL scan
    is gone), so this test pins only the checker's own per-entity table +
    WHERE-clause contract, the half that lives in ``smoke_test._COUNT_QUERIES``.

    - ``publishedPosts``/``publishedPages`` — post_type + ``post_status =
      'publish'``, counted over the prefixed ``posts`` table.
    - ``attachments`` — post_type ``attachment`` with ``trash`` and
      ``auto-draft`` excluded, matching the population WP-CLI's own default
      ``post_status`` of ``any`` would have counted, so a MEDIA_TRASH site
      never diverges.
    - ``users`` — an unfiltered ``COUNT(*)`` over the prefixed ``users``
      table, no WHERE clause at all.
    """

    posts_suffix, posts_where = smoke_test._COUNT_QUERIES["publishedPosts"]
    assert posts_suffix == "posts"
    assert posts_where == "WHERE post_type = 'post' AND post_status = 'publish'"

    pages_suffix, pages_where = smoke_test._COUNT_QUERIES["publishedPages"]
    assert pages_suffix == "posts"
    assert pages_where == "WHERE post_type = 'page' AND post_status = 'publish'"

    attach_suffix, attach_where = smoke_test._COUNT_QUERIES["attachments"]
    assert attach_suffix == "posts"
    assert attach_where == "WHERE post_type = 'attachment' AND post_status NOT IN ('trash', 'auto-draft')"

    users_suffix, users_where = smoke_test._COUNT_QUERIES["users"]
    assert users_suffix == "users"
    assert users_where == ""


def test_generate_expectations_takes_the_attachment_count_as_a_supplementary_live_fact():
    """The attachment count is supplied like every other entity count —
    a live-state fact the caller observes directly (matching the population
    the verifying check itself queries), decoupled from discovery's
    differently-scoped attachment list."""

    envelope = {
        "discovery": {
            "attachments": [{"file": "2026/07/a.jpg", "sizes": []}],
        },
        "entityCounts": {"attachments": 42},
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["counts"]["attachments"] == 42


def test_generate_expectations_keeps_object_cache_present_out_of_excluded_dropins_when_ownership_keeps_it():
    """Issue #25 x pull §9.6 union: when the object-cache ownership rule
    resolves to keep the drop-in present (spec.md, pull §9.6 — "a different
    owner than production → keep local"; "the same owner → take
    production's"), the generated expectations must not also expect
    ``wp-content/object-cache.php`` absent — that self-contradicts
    ``check_object_cache_dropin_state``'s own presence assertion and FAILs a
    correct pull."""

    envelope = {
        "discovery": {"dropins": ["object-cache.php", "advanced-cache.php"]},
        "mode": "pull",
        "objectCacheDropinPresent": True,
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["excludedDropins"] == ["wp-content/advanced-cache.php"]
    assert expectations["objectCacheDropinPresent"] is True


def test_generate_expectations_still_excludes_object_cache_when_ownership_removes_it():
    """The opposite ownership outcome (no local drop-in ever existed, or the
    rule's own verify-and-auto-remove fallback tripped) leaves
    ``object-cache.php`` genuinely absent — the drop-in stays in the
    excluded-and-expected-absent set."""

    envelope = {
        "discovery": {"dropins": ["object-cache.php"]},
        "mode": "pull",
        "objectCacheDropinPresent": False,
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["excludedDropins"] == ["wp-content/object-cache.php"]
    assert expectations["objectCacheDropinPresent"] is False


def test_generate_expectations_omits_object_cache_presence_key_when_not_supplied():
    """At clone, the ownership rule never runs (spec.md, Clone bookends:
    "no object-cache derivation — nothing local pre-exists"), so an envelope
    that never supplies ``objectCacheDropinPresent`` must leave the key out
    entirely — the same "individually skippable when absent" contract every
    other expectation follows — and every discovered drop-in, including
    object-cache.php, stays in the excluded set."""

    envelope = {"discovery": {"dropins": ["object-cache.php"]}}

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["excludedDropins"] == ["wp-content/object-cache.php"]
    assert "objectCacheDropinPresent" not in expectations


def test_generated_pull_expectations_do_not_self_contradict_when_object_cache_is_kept(clone_dir: Path):
    """End-to-end proof for the union fix: feed a generated pull-mode
    expectations document (object-cache ownership resolved to "present")
    into the actual checks against a clone directory that genuinely kept the
    drop-in — the drop-in-absent check must never fail it, and the presence
    check must pass, so a correct copy never trips a FAIL."""

    (clone_dir / "wp-content" / "object-cache.php").write_text("<?php\n", encoding="utf-8")

    expectations = smoke_test.generate_expectations(
        {
            "discovery": {"dropins": ["object-cache.php"]},
            "mode": "pull",
            "objectCacheDropinPresent": True,
        }
    )

    dropin_results = smoke_test.check_excluded_dropins_absent(expectations.get("excludedDropins"), clone_dir)
    presence_result = smoke_test.check_object_cache_dropin_state(
        expectations.get("objectCacheDropinPresent"), clone_dir
    )

    assert all(result.status != "fail" for result in dropin_results)
    assert presence_result.status == "pass"


def test_generate_expectations_carries_supplementary_facts_the_discovery_document_lacks():
    envelope = {
        "discovery": {},
        "localUrl": "https://smoltek.ddev.site",
        "entityCounts": {"publishedPosts": 361, "publishedPages": 62, "users": 7},
        "sampleUrls": ["https://smoltek.ddev.site/technology/"],
        "productionHost": "www.smoltek.com",
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["localUrl"] == "https://smoltek.ddev.site"
    assert expectations["counts"]["publishedPosts"] == 361
    assert expectations["counts"]["publishedPages"] == 62
    assert expectations["counts"]["users"] == 7
    assert expectations["sampleUrls"] == ["https://smoltek.ddev.site/technology/"]
    assert expectations["localAssetCheck"] == {
        "url": "https://smoltek.ddev.site",
        "productionHost": "www.smoltek.com",
    }


def test_generate_expectations_sources_entity_counts_from_the_discovery_document():
    """docs/spec.md's Verify section promises entity counts assembled "from
    what this run already knows" — now that ``templates/discovery.php``
    collects them (review finding: nothing did before), the canonical
    discovery document's own ``entity_counts`` section is a live fact
    ``generate_expectations`` sources directly, without the caller having to
    separately supply an ``entityCounts`` envelope key from nowhere."""

    envelope = {
        "discovery": {
            "entity_counts": {
                "published_posts": 361,
                "published_pages": 62,
                "attachments": 214,
                "users": 7,
            },
        },
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["counts"] == {
        "publishedPosts": 361,
        "publishedPages": 62,
        "attachments": 214,
        "users": 7,
    }


def test_generate_expectations_emits_no_false_zero_counts_from_a_stale_document():
    """Verification review advisory: a discovery document built before
    ``entity_counts`` existed (or by an older ``scripts/discovery.py``) has
    no ``entity_counts`` section at all. ``generate_expectations`` must never
    treat that absence as "0 posts, 0 pages, 0 attachments, 0 users" — a
    zero-filled ``counts`` object would FAIL any non-empty real site verified
    against it. An entirely absent section omits ``counts`` altogether; a
    present-but-empty section (``scripts/discovery.py``'s own contract when
    the raw scan omits the whole section) does the same."""

    assert "counts" not in smoke_test.generate_expectations({"discovery": {}})
    assert "counts" not in smoke_test.generate_expectations(
        {"discovery": {"entity_counts": {}}}
    )


def test_generate_expectations_sources_only_the_entity_counts_the_document_actually_reports():
    """A partially-upgraded discovery document — some counts collected, some
    not (``scripts/discovery.py``'s own per-key omission contract) — must
    source exactly the counts it reports, never zero-filling the rest."""

    # scripts/discovery.py's own build_entity_counts emits snake_case keys;
    # generate_expectations reads those, not camelCase, from the document.
    envelope = {"discovery": {"entity_counts": {"published_posts": 361, "users": 7}}}

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["counts"] == {"publishedPosts": 361, "users": 7}
    assert "publishedPages" not in expectations["counts"]
    assert "attachments" not in expectations["counts"]


def test_generate_expectations_lets_the_entity_counts_override_take_precedence():
    """The explicit ``entityCounts`` envelope override (e.g. a hand-supplied
    re-verification) still wins over the discovery-sourced counts — the same
    "this-run answer overrides the default" precedence every other override
    in this module follows."""

    envelope = {
        "discovery": {"entity_counts": {"published_posts": 361, "users": 7}},
        "entityCounts": {"publishedPosts": 999},
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["counts"]["publishedPosts"] == 999
    assert expectations["counts"]["users"] == 7


def test_generate_expectations_derives_table_split_from_classifications():
    """Pins the classifications shape this derivation is sensitive to:
    ``empty`` is a list of ``{"name", "category"}`` dicts, ``full`` is a
    list of bare table-name strings (both isinstance-guarded, so a future
    classify.py shape change would otherwise silently derive nothing rather
    than reddening here). Also pins the fix for issue #25's review finding:
    ``contentNonEmpty`` must be restricted to the always-populated core
    tables, never the whole full-carry list — ``wp_links`` and
    ``wp_commentmeta`` are full-carried here yet must NOT be asserted
    non-empty, since both are legitimately empty on many real sites."""

    envelope = {
        "discovery": {"database": {"table_prefix": "wp_"}},
        "classifications": {
            "tables": {
                "empty": [
                    {"name": "wp_relevanssi", "category": "search_index"},
                    {"name": "wp_fsmpt_email_logs", "category": "email_log"},
                ],
                "full": ["wp_posts", "wp_options", "wp_users", "wp_links", "wp_commentmeta"],
            }
        },
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["tables"]["operationalEmpty"] == ["wp_fsmpt_email_logs", "wp_relevanssi"]
    assert expectations["tables"]["contentNonEmpty"] == ["wp_options", "wp_posts", "wp_users"]
    assert "wp_links" not in expectations["tables"]["contentNonEmpty"]
    assert "wp_commentmeta" not in expectations["tables"]["contentNonEmpty"]


def test_generate_expectations_omits_content_nonempty_when_no_core_table_survives():
    envelope = {
        "discovery": {"database": {"table_prefix": "wp_"}},
        "classifications": {"tables": {"empty": [], "full": ["wp_links", "wp_commentmeta"]}},
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert "contentNonEmpty" not in expectations.get("tables", {})


def test_generate_expectations_table_split_matches_classify_pys_real_output():
    """Cross-module contract test: feed ``classify.classify_tables``'s
    actual output (not a hand-shaped fixture) straight into
    ``generate_expectations``, so a real classify.py shape drift reddens
    here rather than only in a fixture nobody keeps in sync."""

    all_tables = ["wp_posts", "wp_options", "wp_users", "wp_links", "wp_relevanssi"]
    table_split = classify.classify_tables("wp_", all_tables)

    envelope = {
        "discovery": {"database": {"table_prefix": "wp_"}},
        "classifications": {"tables": table_split},
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["tables"]["operationalEmpty"] == ["wp_relevanssi"]
    assert expectations["tables"]["contentNonEmpty"] == ["wp_options", "wp_posts", "wp_users"]


def test_generate_expectations_prefers_the_resolved_table_content_over_raw_classifications():
    """Same defect class as the object-cache drop-in fix (commit d5a1210): a
    correct copy where the operator accepted CARRY at the user-submissions
    gate (issue #12, ADR-0014) has ``resolve_plan.py`` fold the tagged tables
    out of ``db_table_content``'s empty list into its full-data one — but
    ``classifications.tables.empty`` (``classify.py``'s raw, un-folded split)
    still lists them empty. Deriving ``tables.operationalEmpty`` from the raw
    split ignores the resolved plan's actual outcome and FAILs a correct
    carry: the copy genuinely holds rows in a table the expectations document
    still asserts empty. When ``resolvedTableContent`` is supplied — the
    resolved plan's ``db_table_content`` decision value, the same
    ``{"full", "empty"}`` shape ``classifications.tables`` uses — it takes
    precedence over ``classifications`` for the table split."""

    envelope = {
        "discovery": {"database": {"table_prefix": "wp_"}},
        "classifications": {
            "tables": {
                "empty": [
                    {"name": "wp_relevanssi", "category": "search_index"},
                    {"name": "wp_gf_entry", "category": "user_submissions"},
                ],
                "full": ["wp_posts", "wp_options", "wp_users"],
            }
        },
        "resolvedTableContent": {
            "empty": [
                {"name": "wp_relevanssi", "category": "search_index"},
            ],
            "full": ["wp_posts", "wp_options", "wp_users", "wp_gf_entry"],
        },
    }

    expectations = smoke_test.generate_expectations(envelope)

    # The carried table must not be expected empty — a correct copy that
    # genuinely holds its rows must never FAIL dropin/table checks.
    assert expectations["tables"]["operationalEmpty"] == ["wp_relevanssi"]
    assert "wp_gf_entry" not in expectations["tables"]["operationalEmpty"]


def test_generate_expectations_falls_back_to_classifications_when_no_resolved_table_content():
    """Without ``resolvedTableContent`` (e.g. clone/pull assembling from a
    site that never walked the user_submissions gate), the raw
    ``classifications`` split is still honoured exactly as before."""

    envelope = {
        "discovery": {"database": {"table_prefix": "wp_"}},
        "classifications": {
            "tables": {
                "empty": [{"name": "wp_relevanssi", "category": "search_index"}],
                "full": ["wp_posts"],
            }
        },
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["tables"]["operationalEmpty"] == ["wp_relevanssi"]


def test_generate_expectations_moves_rebuilt_search_index_tables_from_empty_to_nonempty():
    """Issue #10: the reindex step fills a search-index plugin's main table
    after import, so a table the classifier's split would otherwise expect
    empty must instead be expected non-empty. ``rebuiltSearchIndexTables``
    names the table(s) whose rebuild command actually ran; each one is
    subtracted from ``tables.operationalEmpty`` and added to
    ``tables.contentNonEmpty``, mirroring the existing
    ``objectCacheDropinPresent`` / ``preservedInactivePlugins`` override
    pattern."""

    envelope = {
        "discovery": {"database": {"table_prefix": "wp_"}},
        "classifications": {
            "tables": {
                "empty": [
                    {"name": "wp_relevanssi", "category": "search_index"},
                    {"name": "wp_fsmpt_email_logs", "category": "email_log"},
                ],
                "full": ["wp_posts", "wp_options", "wp_users"],
            }
        },
        "rebuiltSearchIndexTables": ["wp_relevanssi"],
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["tables"]["operationalEmpty"] == ["wp_fsmpt_email_logs"]
    assert "wp_relevanssi" not in expectations["tables"]["operationalEmpty"]
    assert expectations["tables"]["contentNonEmpty"] == ["wp_options", "wp_posts", "wp_relevanssi", "wp_users"]


def test_generate_expectations_drops_operational_empty_key_when_every_table_was_rebuilt():
    """When every operationally-empty table named by the split was also
    rebuilt, ``operationalEmpty`` has nothing left to assert and must be
    omitted entirely — an empty list would make ``check_operational_tables_
    empty`` iterate zero tables, which is a different (if harmless) shape
    than the key being genuinely absent, and this derivation always prefers
    the latter, matching every other "nothing to derive" field."""

    envelope = {
        "discovery": {"database": {"table_prefix": "wp_"}},
        "classifications": {
            "tables": {
                "empty": [{"name": "wp_relevanssi", "category": "search_index"}],
                "full": ["wp_posts"],
            }
        },
        "rebuiltSearchIndexTables": ["wp_relevanssi"],
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert "operationalEmpty" not in expectations["tables"]
    assert expectations["tables"]["contentNonEmpty"] == ["wp_posts", "wp_relevanssi"]


def test_generate_expectations_ignores_non_string_entries_in_rebuilt_search_index_tables():
    """The fold's own contract (stated in the comment above it) is that a
    caller-supplied override must never crash the derivation. An unhashable
    entry (a dict) would raise ``TypeError`` at ``set(rebuilt_search_index_
    tables)``, and a hashable-but-wrong-type entry (an int) would raise
    ``TypeError`` from ``sorted()`` once mixed with the existing ``str``
    table names — both must instead be silently dropped, the same
    defensive filter the ``full`` list above already applies to its own
    entries."""

    envelope = {
        "discovery": {"database": {"table_prefix": "wp_"}},
        "classifications": {
            "tables": {
                "empty": [{"name": "wp_relevanssi", "category": "search_index"}],
                "full": ["wp_posts"],
            }
        },
        "rebuiltSearchIndexTables": ["wp_relevanssi", {"name": "wp_relevanssi"}, 42],
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert "operationalEmpty" not in expectations["tables"]
    assert expectations["tables"]["contentNonEmpty"] == ["wp_posts", "wp_relevanssi"]


def test_generate_expectations_treats_an_all_malformed_rebuilt_search_index_tables_as_key_omitted():
    """When every entry in ``rebuiltSearchIndexTables`` is malformed, the
    filtered set is empty and the fold must behave exactly as if the key
    had never been supplied — never raise, and never touch the table
    split derived from the classifier/resolved-plan split."""

    envelope = {
        "discovery": {"database": {"table_prefix": "wp_"}},
        "classifications": {
            "tables": {
                "empty": [{"name": "wp_relevanssi", "category": "search_index"}],
                "full": ["wp_posts"],
            }
        },
        "rebuiltSearchIndexTables": [{"name": "wp_relevanssi"}, 42],
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["tables"]["operationalEmpty"] == ["wp_relevanssi"]
    assert expectations["tables"]["contentNonEmpty"] == ["wp_posts"]


def test_generate_expectations_handles_a_rebuilt_table_absent_from_the_empty_list_without_crashing():
    """A name ``rebuiltSearchIndexTables`` supplies that never appears in the
    derived ``operationalEmpty`` list (a stale override, a typo, a plugin the
    classifier did not tag) must not raise — it is still folded into
    ``contentNonEmpty``, and the rest of the table split is left untouched."""

    envelope = {
        "discovery": {"database": {"table_prefix": "wp_"}},
        "classifications": {
            "tables": {
                "empty": [{"name": "wp_fsmpt_email_logs", "category": "email_log"}],
                "full": ["wp_posts"],
            }
        },
        "rebuiltSearchIndexTables": ["wp_not_actually_empty"],
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["tables"]["operationalEmpty"] == ["wp_fsmpt_email_logs"]
    assert expectations["tables"]["contentNonEmpty"] == ["wp_not_actually_empty", "wp_posts"]


def test_generate_expectations_omitting_rebuilt_search_index_tables_matches_todays_output():
    """The omitted-key contract every override in this function follows:
    an envelope that never supplies ``rebuiltSearchIndexTables`` must derive
    an output bit-identical to one that never knew the key existed —
    verified against a fixed, hand-computed snapshot rather than a second
    call, so a future change to the surrounding derivation cannot
    accidentally make both sides of a self-comparison drift together."""

    envelope = {
        "discovery": {"database": {"table_prefix": "wp_"}},
        "classifications": {
            "tables": {
                "empty": [{"name": "wp_relevanssi", "category": "search_index"}],
                "full": ["wp_posts", "wp_options", "wp_users"],
            }
        },
    }

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["tables"] == {
        "operationalEmpty": ["wp_relevanssi"],
        "contentNonEmpty": ["wp_options", "wp_posts", "wp_users"],
    }


def test_generate_expectations_omits_fields_it_has_nothing_to_derive():
    expectations = smoke_test.generate_expectations({"discovery": {}})

    assert "coreVersion" not in expectations
    assert "ddev" not in expectations
    assert "tablePrefix" not in expectations
    assert "counts" not in expectations
    assert "localUrl" not in expectations


def test_generate_expectations_rejects_missing_discovery_section():
    with pytest.raises(smoke_test.GenerateError):
        smoke_test.generate_expectations({})


def test_generate_expectations_rejects_non_object_input():
    with pytest.raises(smoke_test.GenerateError):
        smoke_test.generate_expectations([])


def test_cli_generate_mode_reads_stdin_writes_stdout():
    envelope = {
        "discovery": {
            "site": {"core_version": "7.0.2"},
            "database": {"table_prefix": "wp_"},
        }
    }

    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "smoke_test.py"), "--generate"],
        input=json.dumps(envelope),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    expectations = json.loads(result.stdout)
    assert expectations["coreVersion"] == "7.0.2"
    assert expectations["tablePrefix"] == "wp_"


def test_cli_generate_mode_fails_loud_on_missing_discovery():
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "smoke_test.py"), "--generate"],
        input="{}",
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stderr.strip()
