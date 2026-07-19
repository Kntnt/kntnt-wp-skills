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
                "post",
                "list",
                "--post_type=post",
                "--post_status=publish",
                "--format=count",
            ): FakeCompleted(stdout="361\n"),
        }
    )

    results = smoke_test.check_entity_counts({"publishedPosts": 361}, run)

    by_id = {r.id: r for r in results}
    assert by_id["count_published_posts"].status == "pass"
    assert by_id["count_published_pages"].status == "skip"
    assert by_id["count_attachments"].status == "skip"
    assert by_id["count_users"].status == "skip"


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


def test_check_local_asset_urls_passes_when_clean():
    fetch = fake_fetch_url(
        {"https://smoltek.ddev.site/": (200, '{"url":"https:\\/\\/smoltek.ddev.site\\/theme.css"}')}
    )

    result = smoke_test.check_local_asset_urls(
        {"url": "https://smoltek.ddev.site/", "productionHost": "www.smoltek.com"}, fetch
    )

    assert result.status == "pass"


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
    assert expectations["counts"]["attachments"] == 1
    assert expectations["activePluginCount"] == 2
    assert expectations["excludedDropins"] == ["wp-content/object-cache.php"]
    assert expectations["savedPlan"] is True
    assert expectations["baseline"] is True
    assert "rollbackBackup" not in expectations


def test_generate_expectations_marks_pull_mode_with_rollback_backup():
    envelope = {"discovery": {}, "mode": "pull"}

    expectations = smoke_test.generate_expectations(envelope)

    assert expectations["rollbackBackup"] is True


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
