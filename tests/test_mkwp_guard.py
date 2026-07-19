"""Tests for the `mkwp` version guard — the single source of truth for whether
a local `mkwp` on `PATH` meets the floor the scaffold step needs.

The guard's only job is verdicting `mkwp --help`'s captured output for the
`--dirname` flag (the artefact whose presence proves `mkwp` >= 1.5.0,
[Kntnt/mkwp#2](https://github.com/Kntnt/mkwp/issues/2)) — never a version
string, which carries no stability contract across releases.
"""

from __future__ import annotations

import mkwp_guard

# A representative slice of a `mkwp` >= 1.5.0 `--help` OPTIONS section —
# enough to prove the guard matches on real-shaped output, not merely a bare
# substring rigged to pass.
HELP_WITH_DIRNAME = """
OPTIONS
\t-t <title>
\t--title=<title>
\t\tThe title of the WordPress site. If omitted, [NAME] will be used.

\t-n <dirname>
\t--dirname=<dirname>
\t\tThe name of the directory the site is created in, underneath the
\t\thome directory. If omitted, [NAME] will be used.
"""

# The pre-1.5.0 shape: every other flag present, `--dirname` genuinely absent.
HELP_WITHOUT_DIRNAME = """
OPTIONS
\t-t <title>
\t--title=<title>
\t\tThe title of the WordPress site. If omitted, [NAME] will be used.

\t-m <email>
\t--email=<email>
\t\tThe email address of the first user created in WordPress.
"""


def test_check_passes_when_help_output_lists_dirname() -> None:
    """`mkwp --help` output that lists `--dirname` clears the guard."""

    verdict = mkwp_guard.check(HELP_WITH_DIRNAME)

    assert verdict == {"ok": True}


def test_check_fails_when_help_output_omits_dirname() -> None:
    """`mkwp --help` output without `--dirname` (an older `mkwp`) fails the
    guard with the floor-version remediation."""

    verdict = mkwp_guard.check(HELP_WITHOUT_DIRNAME)

    assert verdict["ok"] is False
    assert "1.5.0" in verdict["reason"]
    assert mkwp_guard.FLOOR_VERSION in verdict["remediation"]


def test_check_fails_when_mkwp_is_not_on_path() -> None:
    """`None` help output — `mkwp` itself could not be run — fails the guard
    with a distinct reason naming the actual failure mode."""

    verdict = mkwp_guard.check(None)

    assert verdict["ok"] is False
    assert "not on PATH" in verdict["reason"]


def test_check_fails_on_empty_help_output() -> None:
    """Empty output (a broken or truncated `mkwp --help`) is treated as
    missing the flag, not silently accepted."""

    verdict = mkwp_guard.check("")

    assert verdict["ok"] is False


def test_main_emits_the_verdict_as_json(monkeypatch, capsys) -> None:
    """The CLI entry point reads `{"helpOutput": ...}` from stdin and prints
    the verdict JSON on stdout — the helper-seam contract every other script
    in `scripts/` follows."""

    import io
    import json

    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"helpOutput": HELP_WITH_DIRNAME}))
    )

    mkwp_guard.main()

    assert json.loads(capsys.readouterr().out) == {"ok": True}
