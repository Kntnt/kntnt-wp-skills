"""Tests for the `mkwp` version guard — the single source of truth for whether
a local `mkwp` on `PATH` meets the floor the scaffold step needs.

The floor is 1.8.1 ([Kntnt/mkwp#3](https://github.com/Kntnt/mkwp/issues/3)):
`--dirname` itself has shipped since 1.5.0, but every `mkwp` <= 1.8.0 whose
`--dirname` diverges from `NAME` still dies with a database-connection error,
because `ddev config` omitted `--project-name` while wp-config hardcoded the
database host to `ddev-<NAME>-db`. The flag's mere presence in `mkwp --help`
can no longer distinguish a working `mkwp` from a broken one, so the guard
instead parses the version `mkwp` itself prints in its own `--help` banner
(present since 1.7.0: `mkwp <version> - make wordpress`) and compares it
against the floor.
"""

from __future__ import annotations

import mkwp_guard

# Real-shaped `mkwp --help` NAME sections, one per release actually observed
# on the `Kntnt/mkwp` release train — proving the guard matches real output,
# not a bare substring rigged to pass.

# mkwp 1.8.1: fixes Kntnt/mkwp#3, at the floor exactly.
HELP_1_8_1 = """NAME
\tmkwp 1.8.1 - make wordpress

SYNOPSIS
\tmkwp [OPTION]... NAME
\tmkwp --destroy NAME

OPTIONS
\t-D <dirname>
\t--dirname=<dirname>
\t\tThe name of the directory the site is created in, underneath the
\t\thome directory. If omitted, [NAME] will be used.
"""

# mkwp 1.8.0: has --dirname (as -D) and the version banner, but predates the
# --project-name fix — still broken, one patch release short of the floor.
HELP_1_8_0 = """NAME
\tmkwp 1.8.0 - make wordpress

SYNOPSIS
\tmkwp [OPTION]... NAME
\tmkwp --destroy NAME

OPTIONS
\t-D <dirname>
\t--dirname=<dirname>
\t\tThe name of the directory the site is created in, underneath the
\t\thome directory. If omitted, [NAME] will be used.
"""

# mkwp 1.7.0: has --dirname and the version banner, but is two releases
# short of the fix.
HELP_1_7_0 = """NAME
\tmkwp 1.7.0 - make wordpress

SYNOPSIS
\tmkwp [OPTION]... NAME
\tmkwp --destroy NAME

OPTIONS
\t-n <dirname>
\t--dirname=<dirname>
\t\tThe name of the directory the site is created in, underneath the
\t\thome directory. If omitted, [NAME] will be used.
"""

# mkwp 1.6.0 and earlier: has --dirname (added in 1.5.0) but predates the
# version banner entirely — the NAME section is the bare, unversioned line
# every release before 1.7.0 prints.
HELP_1_6_0_NO_VERSION_BANNER = """NAME
\tmkwp - make wordpress

SYNOPSIS
\tmkwp [OPTION]... NAME
\tmkwp --destroy NAME

OPTIONS
\t-n <dirname>
\t--dirname=<dirname>
\t\tThe name of the directory the site is created in, underneath the
\t\thome directory. If omitted, [NAME] will be used.
"""


def test_check_passes_at_exactly_the_floor_version() -> None:
    """`mkwp --help` reporting exactly 1.8.1 — the release that fixes
    Kntnt/mkwp#3 — clears the guard."""

    verdict = mkwp_guard.check(HELP_1_8_1)

    assert verdict == {"ok": True}


def test_check_fails_one_patch_release_below_the_floor() -> None:
    """1.8.0 has `--dirname` and even prints a version banner, but predates
    the `--project-name` fix — the guard must still reject it by version,
    not merely by flag presence."""

    verdict = mkwp_guard.check(HELP_1_8_0)

    assert verdict["ok"] is False
    assert "1.8.0" in verdict["reason"]
    assert mkwp_guard.FLOOR_VERSION in verdict["remediation"]


def test_check_fails_further_below_the_floor() -> None:
    """1.7.0 — the version the upstream defect was first live-verified
    against — fails the guard the same way."""

    verdict = mkwp_guard.check(HELP_1_7_0)

    assert verdict["ok"] is False
    assert "1.7.0" in verdict["reason"]


def test_check_fails_when_help_output_predates_the_version_banner() -> None:
    """`mkwp` releases before 1.7.0 never print a version at all in
    `--help` — that missing banner is itself below the floor, not a parse
    error to shrug off as a pass."""

    verdict = mkwp_guard.check(HELP_1_6_0_NO_VERSION_BANNER)

    assert verdict["ok"] is False
    assert mkwp_guard.FLOOR_VERSION in verdict["remediation"]


def test_check_fails_when_mkwp_is_not_on_path() -> None:
    """`None` help output — `mkwp` itself could not be run — fails the guard
    with a distinct reason naming the actual failure mode."""

    verdict = mkwp_guard.check(None)

    assert verdict["ok"] is False
    assert "not on PATH" in verdict["reason"]


def test_check_fails_on_empty_help_output() -> None:
    """Empty output (a broken or truncated `mkwp --help`) is treated as
    below the floor, not silently accepted."""

    verdict = mkwp_guard.check("")

    assert verdict["ok"] is False


def test_main_emits_the_verdict_as_json(monkeypatch, capsys) -> None:
    """The CLI entry point reads `{"helpOutput": ...}` from stdin and prints
    the verdict JSON on stdout — the helper-seam contract every other script
    in `scripts/` follows."""

    import io
    import json

    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"helpOutput": HELP_1_8_1}))
    )

    mkwp_guard.main()

    assert json.loads(capsys.readouterr().out) == {"ok": True}
