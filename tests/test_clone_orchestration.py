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
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
SPEC_TEXT: str = SPEC.read_text(encoding="utf-8")

# The deterministic helpers the clone flow must drive rather than compute by hand
# (spec "The deterministic helper seam"). ``baseline_diff.py`` is deliberately
# absent — a clone has no baseline to diff, it only *writes* the first one.
REQUIRED_HELPERS: tuple[str, ...] = (
    "scripts/discovery.py",
    "scripts/classify.py",
    "scripts/resolve_plan.py",
    "scripts/filter_manifest.py",
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


def _pos_after(pattern: str, start: int) -> int:
    """First match position of ``pattern`` at or after ``start`` — the scoped
    variant of :func:`_pos` for asserting order within one step rather than
    across the whole file, where an earlier bullet-list mention of the same
    helper would otherwise make a naive first-match comparison meaningless."""

    match = re.search(pattern, SKILL_TEXT[start:], re.IGNORECASE)
    assert match is not None, f"clone SKILL.md is missing an anchor for /{pattern}/ after {start}"
    return start + match.start()


def _spec_pos(pattern: str) -> int:
    """First match position of a case-insensitive ``pattern`` in the specification's
    clone bookends, failing loudly with the missing anchor when it is absent — the
    ``docs/spec.md`` counterpart to ``_pos``."""

    match = re.search(pattern, SPEC_TEXT, re.IGNORECASE)
    assert match is not None, f"docs/spec.md is missing an anchor for /{pattern}/"
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


def test_manifest_transport_carries_no_exclusion_payload() -> None:
    """Issue #18: the manifest request must not embed an exclusion payload —
    ``manifest.php`` is sent unfiltered and ``scripts/filter_manifest.py`` filters
    the result locally before it is stored as the baseline."""

    assert "scripts/filter_manifest.py" in SKILL_TEXT, (
        "the baseline write must filter production's manifest locally"
    )
    assert "resolved exclusion scope injected" not in SKILL_TEXT, (
        "the manifest request must not describe injecting an exclusion payload"
    )

    # Scoped to the baseline-write step itself — not the earlier helper-seam
    # bullet list — so the check proves the step's own narrative.
    manifest_pos = _pos(r"templates/manifest\.php")
    filter_pos = _pos_after(r"scripts/filter_manifest\.py", manifest_pos)
    assert manifest_pos < filter_pos, (
        "the manifest is filtered locally after the unfiltered walk, not before"
    )


def test_every_decision_is_a_gate_from_the_resolved_plan() -> None:
    """AC #2: every decision reaches the operator as a gate whose recommendation
    comes from the helper's resolved plan, with the saved-plan replay collapse."""

    for term in ("gate", "recommendation", "replay"):
        assert re.search(term, SKILL_TEXT, re.IGNORECASE), f"missing decision term {term!r}"
    assert "scripts/resolve_plan.py" in SKILL_TEXT, "recommendations must come from resolve_plan.py"


def test_yes_mode_is_unattended_and_prints_the_full_record() -> None:
    """AC #2: ``--yes`` runs unattended — never pausing — and prints the full
    record of what was decided and done."""

    assert "--yes" in SKILL_TEXT
    assert re.search(r"record", SKILL_TEXT, re.IGNORECASE), "no decided-and-done record"


def test_engine_correction_follows_scaffold_and_precedes_the_restart() -> None:
    """Issue #14: `mkwp` has no `--db=` flag, so its scaffold necessarily runs its
    own first `ddev start` on DDEV's default engine — the ordering the clone
    bookends can actually deliver is scaffold, then discard that throwaway
    database, then the discovered engine/version pin in ``.ddev/config.yaml``,
    then the restart onto the corrected engine — never an import or transfer
    step ahead of that restart. A smoke test once let `mkwp` settle on DDEV's
    default MariaDB (11.8) against a production 11.4 all the way to import,
    costing a ``ddev delete -O`` plus reconfigure-and-restart cycle deep inside
    an already-populated site to undo; this ordering runs that same cycle
    deliberately, immediately after scaffold, instead."""

    # Anchor the restart position on the actual **Restart on the corrected
    # engine.** step, not the summary intro sentence that also mentions
    # restarting — otherwise a regression that reordered the real steps while
    # leaving the intro intact would slip through (the same pitfall the
    # health-check ordering test above documents).
    scaffold = _pos(r"mkwp <name>")
    discard = _pos(r"ddev delete -O")
    pin = _pos(r"ddev config --database=")
    restart = _pos(r"\*\*Restart on the corrected engine\.\*\*")
    assert scaffold < discard < pin < restart, (
        "clone SKILL.md must order the mkwp scaffold, then discarding the "
        "throwaway default-engine database, then the `ddev config --database=` "
        "engine pin, then the restart-on-the-corrected-engine step"
    )


def test_spec_clone_bookends_order_scaffold_discard_pin_then_restart() -> None:
    """Issue #14: the specification's clone bookends carry the same explicit,
    achievable ordering as the SKILL, so the two documents cannot silently
    diverge on how the engine actually gets corrected."""

    # The restart anchor is the specific "restart with `ddev start`" phrasing of
    # the terminal step, not a bare "ddev start" search — the latter would also
    # match the intro sentence's mention of mkwp's own unavoidable first start,
    # which precedes the scaffold anchor and would make the assertion pass
    # regardless of where the real restart step sits.
    scaffold = _spec_pos(r"scaffold with `mkwp`")
    discard = _spec_pos(r"ddev delete -O")
    pin = _spec_pos(r"ddev config --database=")
    restart = _spec_pos(r"restart with `ddev start`")
    assert scaffold < discard < pin < restart, (
        "docs/spec.md must order the mkwp scaffold, then discarding the "
        "throwaway default-engine database, then the `ddev config --database=` "
        "engine pin, then the restart onto the corrected engine"
    )


def test_nothing_heavy_runs_before_the_health_check() -> None:
    """AC #3: nothing heavy runs before the health check — discovery parsing and
    the pack-script generation both follow it."""

    # Anchor on the health-check *step*, not the intro sentence "Every run
    # begins with a health check" — otherwise a regression that reordered the
    # steps while leaving the intro intact would slip through. The discovery and
    # pack anchors likewise target the actual `uv run` driving invocations in
    # steps 2 and 5, not the earlier seam-list descriptions that precede the
    # health-check step.
    health = _pos(r"## 1\. Health check")
    assert health < _pos(r"uv run scripts/discovery\.py"), (
        "discovery parsing must be driven after the health-check step"
    )
    assert health < _pos(r"uv run scripts/pack_script\.py"), (
        "pack-script generation must be driven after the health-check step"
    )


def test_exposure_window_closes_immediately_after_verification() -> None:
    """AC #3: the artifacts and the remote workspace are deleted immediately after
    checksum verification — the exposure window closes before the destructive
    local import ever begins."""

    assert re.search(r"exposure window", SKILL_TEXT, re.IGNORECASE)
    close = _pos(r"close the exposure window")
    # Anchor on the download-side verification (`sha256sum -c SHA256` in step 6),
    # not the first "checksum" mention, which is the pack step's SHA256 creation
    # in step 5 — closure must follow the download verify, not merely the pack.
    assert _pos(r"sha256sum -c SHA256") < close, (
        "the window must close only after the download checksum verification"
    )
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
    "double-escaped-json-search-replace": r"\\\\/\\\\/",
    "escaped-protocol-relative-www-search-replace": r"`\\/\\/www",
    "escaped-protocol-relative-bare-search-replace": r"`\\/\\/<domain>",
    "double-escaped-protocol-relative-www-search-replace": r"`\\\\/\\\\/www",
    "double-escaped-protocol-relative-bare-search-replace": r"`\\\\/\\\\/<domain>",
    "guid-column-skipped": r"guid",
    "risk-warning-always": r"risk warning",
    "bare-domain-never": r"bare domain",
    "form-to-service-integration-bullet": r"form-to-service",
}


@pytest.mark.parametrize("rail,pattern", list(SAFETY_RAILS.items()))
def test_safety_rails_are_stated(rail: str, pattern: str) -> None:
    """Each safety rail that converges in the clone flow is stated in the
    orchestration — the risk warning, the outside-docroot packing, the secret
    handling, and the URL-scoped search-replace including the escaped-JSON,
    double-escaped-JSON, and their protocol-relative counterparts — a stored
    protocol-relative URL has no scheme to anchor a scheme-ful pass, so it needs
    its own escaped and double-escaped entries in the list."""

    assert re.search(pattern, SKILL_TEXT, re.IGNORECASE), f"safety rail {rail!r} not stated"
