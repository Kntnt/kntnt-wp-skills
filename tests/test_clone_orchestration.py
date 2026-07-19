"""Clone-orchestration consistency test — bind the clone SKILL to the engine.

Issue #8 replaces the ``clone`` stub with the real orchestration prose that
*drives* the deterministic helper CLIs (``scripts/*.py``) and the production-side
templates (``templates/*``). Per the specification's Testing Decisions the
orchestration prose itself is a human-verified residual — the real Novamira and
DDEV interaction is exercised at run time, never in CI — so this suite does not
re-simulate the transfer. It is instead the anti-drift binding, the exact kind of
"documentation cannot silently diverge from implementation" guard the help/docs
consistency test already establishes: it holds ``skills/clone/SKILL.md`` to the
acceptance criteria and the safety rails that converge in the clone flow.

Anchors are stable domain terms (``CONTEXT.md``), real helper/template paths, and
the exact ``ddev`` invocation literals pinned in ``docs/implementation-notes.md``
— never a snippet of this suite's own prose — so a faithful rewrite stays green
while a regression (a returned stub, unwired hand-computation, a re-ordered
localise tail, a dropped safety rail) reddens.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import flags

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
CLONE_SKILL: Path = REPO_ROOT / "skills" / "clone" / "SKILL.md"
SKILL_TEXT: str = CLONE_SKILL.read_text(encoding="utf-8")

# The deterministic helpers the clone flow must drive rather than compute by hand
# (spec "The deterministic helper seam"). ``baseline_diff.py`` is deliberately
# absent — a clone has no baseline to diff, it only *writes* the first one.
REQUIRED_HELPERS: tuple[str, ...] = (
    "scripts/discovery.py",
    "scripts/classify.py",
    "scripts/resolve_plan.py",
    "scripts/pack_script.py",
    "scripts/dump_sanity.py",
)

# The production-side templates the clone flow sends over the control channel.
REQUIRED_TEMPLATES: tuple[str, ...] = (
    "templates/liveness.php",
    "templates/exec-probe.php",
    "templates/download-preflight.php",
    "templates/stranded-sweep.php",
    "templates/discovery.php",
    "templates/manifest.php",
)

# Phrases that mark the file as still (or again) a stub — the notice AC #1 says
# must be gone.
STUB_MARKERS: tuple[str, ...] = (
    "not yet implemented",
    "no-op stub",
    "is a stub",
    "planned behaviour (not active)",
)

# Every ``scripts/<x>`` or ``templates/<x>`` path token, however it is embedded
# (a bare mention, a backticked path, or inside a ``${CLAUDE_PLUGIN_ROOT}/...``
# command), so a reference to a helper or template that does not exist is caught.
_PATH_TOKEN = re.compile(r"(?:scripts|templates)/[A-Za-z0-9_.\-]+\.[A-Za-z0-9]+")


def _pos(pattern: str) -> int:
    """First match position of a case-insensitive ``pattern`` in the clone SKILL,
    failing loudly with the missing anchor when it is absent — so an ordering
    assertion never silently passes on a ``-1`` from an anchor that is not there."""

    match = re.search(pattern, SKILL_TEXT, re.IGNORECASE)
    assert match is not None, f"clone SKILL.md is missing an anchor for /{pattern}/"
    return match.start()


def _referenced_paths() -> set[str]:
    """Every distinct ``scripts/`` or ``templates/`` path the clone SKILL cites."""

    return set(_PATH_TOKEN.findall(SKILL_TEXT))


def test_stub_notice_is_gone() -> None:
    """AC #1: the stub notice is gone — no marker of an unimplemented no-op skill
    survives anywhere in the file, frontmatter included."""

    lowered = SKILL_TEXT.lower()
    present = [marker for marker in STUB_MARKERS if marker in lowered]
    assert not present, f"clone SKILL.md still carries stub markers: {present}"


def test_help_gate_short_circuits_before_the_health_check() -> None:
    """AC #1: the help-gate still short-circuits — every help form is honoured by
    echoing the manual page via ``help.py`` as the skill's first step, ahead of
    the first health-check action."""

    assert "scripts/help.py" in SKILL_TEXT, "help-gate must echo via scripts/help.py"
    for form in flags.HELP_FORMS:
        assert f"`{form}`" in SKILL_TEXT, f"help-gate omits the {form!r} form"

    # The help-gate precedes the first production-touching step (the liveness
    # probe), so ``help`` never reaches the control channel.
    assert _pos(r"scripts/help\.py") < _pos(r"templates/liveness\.php")


@pytest.mark.parametrize("helper", REQUIRED_HELPERS)
def test_drives_every_deterministic_helper(helper: str) -> None:
    """The orchestration never computes a classification, a plan, a pack script,
    or a dump verdict by hand — it drives the helper CLI for each (AC #2 and the
    "never computes ... by hand" invariant)."""

    assert helper in SKILL_TEXT, f"clone SKILL.md does not drive {helper}"


@pytest.mark.parametrize("template", REQUIRED_TEMPLATES)
def test_sends_every_production_side_template(template: str) -> None:
    """Each health-check and discovery step is driven by its production-side
    template over the control channel, not improvised PHP."""

    assert template in SKILL_TEXT, f"clone SKILL.md does not send {template}"


def test_no_referenced_helper_or_template_path_dangles() -> None:
    """Every ``scripts/`` or ``templates/`` path the orchestration cites resolves
    to a real file — the wiring cannot drift onto a helper or template that does
    not exist."""

    dangling = sorted(
        path for path in _referenced_paths() if not (REPO_ROOT / path).is_file()
    )
    assert not dangling, f"clone SKILL.md references non-existent paths: {dangling}"


def test_every_decision_is_a_gate_from_the_resolved_plan() -> None:
    """AC #2: every decision reaches the operator as a gate whose recommendation
    comes from the helper's resolved plan, with the saved-plan replay collapse."""

    for term in ("gate", "recommendation", "replay"):
        assert re.search(term, SKILL_TEXT, re.IGNORECASE), f"missing decision term {term!r}"
    assert "scripts/resolve_plan.py" in SKILL_TEXT
    assert _pos(r"scripts/resolve_plan\.py") < _pos(r"\bgate")


def test_yes_mode_is_unattended_and_prints_the_full_record() -> None:
    """AC #2: ``--yes`` runs unattended — never pausing — and prints the full
    record of what was decided and done."""

    assert "--yes" in SKILL_TEXT
    assert re.search(r"record", SKILL_TEXT, re.IGNORECASE), "no decided-and-done record"


def test_nothing_heavy_runs_before_the_health_check() -> None:
    """AC #3: nothing heavy runs before the health check — discovery parsing and
    the pack-script generation both follow it."""

    health = _pos(r"health check")
    assert health < _pos(r"scripts/discovery\.py")
    assert health < _pos(r"scripts/pack_script\.py")


def test_exposure_window_closes_immediately_after_verification() -> None:
    """AC #3: the artifacts and the remote workspace are deleted immediately after
    checksum verification — the exposure window closes before the destructive
    local import ever begins."""

    assert re.search(r"exposure window", SKILL_TEXT, re.IGNORECASE)
    close = _pos(r"close the exposure window")
    assert _pos(r"checksum") < close, "the window must close only after verification"
    assert close < _pos(r"ddev import-db"), "the window must close before local import"


def test_import_and_localise_follow_the_spec_order() -> None:
    """AC #4: import and localisation follow the specification's order — dump
    sanity check, import, URL-scoped search-replace, then the localise tail."""

    order = (
        r"scripts/dump_sanity\.py",
        r"ddev import-db",
        r"ddev wp search-replace",
        r"ddev wp rewrite flush",
        r"ddev restart",
        r"last-sync\.json",
    )
    positions = [_pos(step) for step in order]
    assert positions == sorted(positions), (
        f"localise steps are out of spec order: {list(zip(order, positions))}"
    )


def test_final_flush_loads_plugins_before_the_restart_and_baseline() -> None:
    """AC #4: the run ends with the plugins-loaded rewrite flush, the DDEV
    restart, and the baseline write — the flush that skips plugins 404s localised
    subpages (platform constraint 14)."""

    assert re.search(r"plugins loaded", SKILL_TEXT, re.IGNORECASE)
    plugins_loaded = _pos(r"plugins loaded")
    assert _pos(r"ddev wp search-replace") < plugins_loaded < _pos(r"ddev restart")
    assert _pos(r"ddev restart") < _pos(r"last-sync\.json")


def test_verify_phase_uses_live_state_and_documents_the_operator_residual() -> None:
    """AC #5: the in-run verify phase smoke-tests from live state (URLs, error
    greps, a database check) after the baseline write, and the real-site smoke is
    documented as the operator's residual."""

    assert _pos(r"last-sync\.json") < _pos(r"ddev wp db check")
    assert re.search(r"critical error", SKILL_TEXT, re.IGNORECASE)
    assert re.search(r"residual|manual .*smoke", SKILL_TEXT, re.IGNORECASE)


# The safety rails the plan flags as converging in the clone flow — each stated
# as a regex the faithful prose must satisfy.
SAFETY_RAILS: dict[str, str] = {
    "verify-targets-prod": r"targets production",
    "db-password-never-in-context": r"password[^.\n]*(?:never|not).*context|never[^.\n]*password",
    "passphrase-authenticated-not-http": r"passphrase",
    "encrypted-outside-docroot": r"outside the docroot",
    "escaped-json-search-replace": r"\\/\\/",
    "guid-column-skipped": r"guid",
    "risk-warning-always": r"risk warning",
    "bare-domain-never": r"bare domain",
}


@pytest.mark.parametrize("rail,pattern", list(SAFETY_RAILS.items()))
def test_safety_rails_are_stated(rail: str, pattern: str) -> None:
    """Each safety rail that converges in the clone flow is stated in the
    orchestration — the risk warning, the outside-docroot packing, the secret
    handling, and the URL-scoped search-replace including the escaped-JSON forms."""

    assert re.search(pattern, SKILL_TEXT, re.IGNORECASE), f"safety rail {rail!r} not stated"
