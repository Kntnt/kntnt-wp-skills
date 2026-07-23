"""Pull-orchestration consistency test — bind the pull SKILL to the engine.

Issue #9 replaces the ``pull`` stub with the real orchestration prose that
*drives* the deterministic helper CLIs (``scripts/*.py``) and the production-side
templates (``templates/*``) — the same engine choreography as ``clone`` plus the
pull bookends. Per the specification's Testing Decisions the orchestration prose
itself is a human-verified residual — the real Novamira and DDEV interaction is
exercised at run time, never in CI — so this suite does not re-simulate the
transfer. It is instead the anti-drift binding (the sibling of
``test_clone_orchestration.py``): it holds ``skills/pull/SKILL.md`` to issue #9's
acceptance criteria and the pull bookends the spec converges into the pull flow.

Anchors are stable domain terms (``CONTEXT.md``), real helper/template paths, and
the exact ``ddev`` / ``wp`` invocation literals pinned in
``docs/implementation-notes.md`` — never a snippet of this suite's own prose — so
a faithful rewrite stays green while a regression (a returned stub, an unwired
hand-computation, a dropped rollback backup, a prefix check that no longer
precedes the import, deletion mirroring that hard-removes, a re-ordered localise
tail) reddens.

One reconciliation is recorded here and honoured by the anchors: the spec's
numbered *Import and localise* list places the pull prefix-assertion at step 7
(after the import), but acceptance criterion #4 and the pull manual page both
require a prefix mismatch to abort *before* the import. The AC and the manual
page are the contract, so the binding is prefix-verify-before-import.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import flags

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
PULL_SKILL: Path = REPO_ROOT / "skills" / "pull" / "SKILL.md"
SKILL_TEXT: str = PULL_SKILL.read_text(encoding="utf-8")
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
SPEC_TEXT: str = SPEC.read_text(encoding="utf-8")

# The deterministic helpers the pull flow must drive rather than compute by hand
# (spec "The deterministic helper seam"). Unlike ``clone``, pull additionally
# drives ``baseline_diff.py`` — it has a stored baseline to diff production
# against, so only the new/changed set moves.
REQUIRED_HELPERS: tuple[str, ...] = (
    "scripts/discovery.py",
    "scripts/bootstrap_parse.py",
    "scripts/classify.py",
    "scripts/resolve_plan.py",
    "scripts/build_exclusions.py",
    "scripts/filter_manifest.py",
    "scripts/baseline_diff.py",
    "scripts/build_selection.py",
    "scripts/unseal.py",
    "scripts/dump_sanity.py",
)

# The only production-side template that survives the Extractor cutover: the
# local capture mu-plugin, dropped into the *local* copy (never a channel
# payload). Every retired ``execute-php`` payload is gone.
REQUIRED_TEMPLATES: tuple[str, ...] = ("templates/kntnt-wp-skills-mailpit.php",)

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
    """First match position of a case-insensitive ``pattern`` in the pull SKILL,
    failing loudly with the missing anchor when it is absent — so an ordering
    assertion never silently passes on a ``-1`` from an anchor that is not there."""

    match = re.search(pattern, SKILL_TEXT, re.IGNORECASE)
    assert match is not None, f"pull SKILL.md is missing an anchor for /{pattern}/"
    return match.start()


def _pos_after(pattern: str, start: int) -> int:
    """First match position of ``pattern`` at or after ``start`` — the scoped
    variant of :func:`_pos` for asserting order within one step rather than
    across the whole file, where an earlier bullet-list mention of the same
    helper would otherwise make a naive first-match comparison meaningless."""

    match = re.search(pattern, SKILL_TEXT[start:], re.IGNORECASE)
    assert match is not None, f"pull SKILL.md is missing an anchor for /{pattern}/ after {start}"
    return start + match.start()


def _referenced_paths() -> set[str]:
    """Every distinct ``scripts/`` or ``templates/`` path the pull SKILL cites."""

    return set(_PATH_TOKEN.findall(SKILL_TEXT))


def test_stub_notice_is_gone() -> None:
    """AC #1: the stub notice is gone — no marker of an unimplemented no-op skill
    survives anywhere in the file, frontmatter included."""

    lowered = SKILL_TEXT.lower()
    present = [marker for marker in STUB_MARKERS if marker in lowered]
    assert not present, f"pull SKILL.md still carries stub markers: {present}"


def test_help_gate_short_circuits_before_the_health_check() -> None:
    """AC #1: the help-gate still short-circuits — every help form is honoured by
    echoing the manual page via ``help.py`` as the skill's first step, ahead of
    the first health-check action."""

    assert "scripts/help.py" in SKILL_TEXT, "help-gate must echo via scripts/help.py"
    for form in flags.HELP_FORMS:
        assert f"`{form}`" in SKILL_TEXT, f"help-gate omits the {form!r} form"

    # The help-gate precedes the first production-touching step (the ``GET
    # /status`` handshake), so ``help`` never reaches the control channel.
    assert _pos(r"scripts/help\.py") < _pos(r"GET /status")


@pytest.mark.parametrize("helper", REQUIRED_HELPERS)
def test_drives_every_deterministic_helper(helper: str) -> None:
    """The orchestration never computes a diff, a classification, a plan, a pack
    script, or a dump verdict by hand — it drives the helper CLI for each (AC #2
    and the "never computes ... by hand" invariant). ``baseline_diff.py`` is the
    pull-specific one: a pull has a baseline, so it diffs rather than only
    writing the first one."""

    assert helper in SKILL_TEXT, f"pull SKILL.md does not drive {helper}"


@pytest.mark.parametrize("template", REQUIRED_TEMPLATES)
def test_references_the_local_capture_template(template: str) -> None:
    """The one surviving template — the local capture mu-plugin — is still
    referenced where the mail decision resolves to capture; the retired
    ``execute-php`` payloads are gone with the Novamira channel."""

    assert template in SKILL_TEXT, f"pull SKILL.md does not reference {template}"


def test_no_referenced_helper_or_template_path_dangles() -> None:
    """Every ``scripts/`` or ``templates/`` path the orchestration cites resolves
    to a real file — the wiring cannot drift onto a helper or template that does
    not exist."""

    dangling = sorted(
        path for path in _referenced_paths() if not (REPO_ROOT / path).is_file()
    )
    assert not dangling, f"pull SKILL.md references non-existent paths: {dangling}"


def test_manifest_transport_carries_no_exclusion_payload() -> None:
    """Issue #18: the manifest request must not embed an exclusion payload — the
    whole content tree is fetched unfiltered over ``GET /files`` and
    ``scripts/filter_manifest.py`` filters the result locally before it is diffed
    and stored as the new baseline."""

    assert "scripts/filter_manifest.py" in SKILL_TEXT, (
        "the baseline diff must filter production's manifest locally"
    )
    assert "resolved exclusion scope injected" not in SKILL_TEXT, (
        "the manifest request must not describe injecting an exclusion payload"
    )

    # Scoped to the diff step itself — the ``GET /files`` fetch precedes the local
    # filter, which precedes the diff, within that step's own narrative.
    diff_start = _pos(r"\*\*Diff the baseline\.\*\*")
    files_pos = _pos_after(r"GET /files", diff_start)
    filter_pos = _pos_after(r"scripts/filter_manifest\.py", files_pos)
    diff_pos = _pos_after(r"scripts/baseline_diff\.py", filter_pos)
    assert files_pos < filter_pos < diff_pos, (
        "the manifest must be fetched unfiltered over GET /files, then locally "
        "filtered, then diffed"
    )


def test_every_decision_is_a_gate_from_the_resolved_plan() -> None:
    """AC #2: every decision reaches the operator as a gate whose recommendation
    comes from the helper's resolved plan."""

    for term in ("gate", "recommendation"):
        assert re.search(term, SKILL_TEXT, re.IGNORECASE), f"missing decision term {term!r}"
    assert "scripts/resolve_plan.py" in SKILL_TEXT, "recommendations must come from resolve_plan.py"


def test_replay_collapses_to_the_single_replay_gate() -> None:
    """AC #5: a saved plan collapses the whole walk to the single replay gate."""

    assert re.search(r"replay", SKILL_TEXT, re.IGNORECASE), "replay collapse not stated"
    assert re.search(r"replay the saved plan", SKILL_TEXT, re.IGNORECASE), (
        "the single replay gate is not named"
    )


def test_yes_mode_is_unattended_and_prints_the_full_record() -> None:
    """AC #5: ``--yes`` runs unattended — never pausing — and prints the full
    record of what was decided and done."""

    assert "--yes" in SKILL_TEXT
    assert re.search(r"record", SKILL_TEXT, re.IGNORECASE), "no decided-and-done record"


def test_nothing_heavy_runs_before_the_health_check() -> None:
    """AC: nothing heavy runs before the health check — discovery parsing and the
    pack-script generation both follow the health-check step."""

    health = _pos(r"## 1\. Health check")
    assert health < _pos(r"uv run scripts/discovery\.py"), (
        "discovery parsing must be driven after the health-check step"
    )
    assert health < _pos(r"uv run scripts/build_selection\.py"), (
        "extraction-selection building must be driven after the health-check step"
    )


def test_incremental_transfer_diffs_the_stored_baseline() -> None:
    """AC #2: a pull transfers only the new/changed set — diffed by
    ``baseline_diff.py`` against the stored ``last-sync.json`` baseline, never the
    local filesystem — and always dumps the database in full."""

    # The diff is driven by the helper against the stored baseline manifest, and
    # its two decision sets are named by the helper's own output keys.
    assert "scripts/baseline_diff.py" in SKILL_TEXT
    assert "last-sync.json" in SKILL_TEXT, "the diff must read the stored baseline"
    assert "new_or_changed" in SKILL_TEXT, "the new/changed set is not the pack input"
    assert "production_deleted" in SKILL_TEXT, "the deletion set is not drawn from the diff"

    # Only the new/changed set is packed, but the database is always dumped whole.
    assert re.search(r"in full", SKILL_TEXT, re.IGNORECASE), (
        "the database-always-in-full invariant (AC #2) is not stated"
    )

    # The diff is production-now against the stored baseline, not local mtimes.
    assert re.search(r"baseline", SKILL_TEXT, re.IGNORECASE)


def test_rollback_backup_precedes_every_destructive_local_step() -> None:
    """AC #3: the pre-import rollback backup is taken before anything destructive,
    written to the durable gitignored backups location, and its path is reported."""

    # The backup is a real ``ddev export-db`` into the durable backups dir.
    assert re.search(r"ddev export-db", SKILL_TEXT), "no ddev export-db rollback backup"
    assert ".kntnt-wp-skills/backups" in SKILL_TEXT, "backup not written to the durable dir"

    # The backup precedes the first destructive local step — the import.
    assert _pos(r"ddev export-db") < _pos(r"ddev import-db"), (
        "the rollback backup must precede the destructive import"
    )

    # Its path is surfaced in the report (AC #3, spec Cleanup).
    assert re.search(r"backup", SKILL_TEXT, re.IGNORECASE)
    report = _pos(r"## 11\. Cleanup and report")
    assert re.search(r"backup", SKILL_TEXT[report:], re.IGNORECASE), (
        "the report does not surface the rollback backup path"
    )


def test_prefix_mismatch_aborts_before_import() -> None:
    """AC #4: a prefix mismatch aborts before the import — WordPress would find
    zero tables under a mismatched prefix (platform constraint 12)."""

    assert re.search(r"prefix", SKILL_TEXT, re.IGNORECASE), "no table-prefix verification"
    assert re.search(r"mismatch", SKILL_TEXT, re.IGNORECASE), "no mismatch abort"
    assert re.search(r"abort", SKILL_TEXT, re.IGNORECASE), "the mismatch does not abort"

    # The mismatch abort comes before the import ever runs.
    assert _pos(r"mismatch") < _pos(r"ddev import-db"), (
        "the prefix mismatch must abort before the import (AC #4, pull manpage)"
    )


def test_deletion_mirroring_is_off_by_default_and_reversible() -> None:
    """AC #4: deletion mirroring stays off by default, never removes anything under
    ``--yes`` without a saved Yes, and confirmed deletions land in the reversible
    trash rather than a hard removal (ADR-0010)."""

    assert re.search(r"off by default", SKILL_TEXT, re.IGNORECASE), (
        "deletion mirroring is not off by default"
    )

    # Confirmed deletions go to the timestamped local trash, never a hard rm.
    assert ".kntnt-wp-skills/trash" in SKILL_TEXT, "deletions do not land in the trash"
    assert re.search(r"never[^.\n]*(?:hard|rm|remove)|reversible", SKILL_TEXT, re.IGNORECASE), (
        "the trash is not described as reversible / never a hard removal"
    )

    # Under --yes, nothing is removed without a previously saved Yes.
    assert re.search(r"without a saved", SKILL_TEXT, re.IGNORECASE), (
        "the --yes-needs-a-saved-Yes safety is not stated"
    )


def test_exposure_window_closes_immediately_after_verification() -> None:
    """AC: the extraction job is consumed immediately after the download unseals
    — the exposure window closes before the destructive local import ever begins.
    After the Extractor cutover the happy-path close is
    ``POST /extractions/{id}/consume`` and integrity is the sealed container's own
    authentication, so the closure follows the unseal, never a `sha256sum -c`."""

    assert re.search(r"exposure window", SKILL_TEXT, re.IGNORECASE)
    close = _pos(r"close the exposure window")
    assert _pos(r"scripts/unseal\.py unseal") < close, (
        "the window must close only after the download unseals"
    )
    assert re.search(r"consume", SKILL_TEXT[close:], re.IGNORECASE), (
        "the happy-path close must consume the job (POST /extractions/{id}/consume)"
    )
    assert close < _pos(r"ddev import-db"), "the window must close before local import"


def test_import_and_localise_follow_the_spec_order() -> None:
    """AC #4: import and localisation follow the specification's order — rollback
    backup, dump sanity check, import, URL-scoped search-replace, the
    plugins-loaded flush, the restart, then the new baseline write."""

    # The baseline write is anchored on its step-15-only heading, not on
    # ``last-sync.json``: pull *reads* the stored ``last-sync.json`` in the step-4
    # diff (and names it in the config overview) before *writing* it here, so a
    # first-occurrence anchor on the filename would point at the read, not the
    # write. Clone has no such earlier mention; pull always does.
    # ``dump_sanity`` is anchored on its ``uv run`` drive site in step 9.2, not the
    # bare path token that the seam-list description in "How the engine works"
    # carries first (the same distinction the health-check ordering test draws).
    order = (
        r"ddev export-db",
        r"uv run scripts/dump_sanity\.py",
        r"ddev import-db",
        r"ddev wp search-replace",
        r"ddev wp rewrite flush",
        r"ddev restart",
        r"Write the new baseline",
    )
    positions = [_pos(step) for step in order]
    assert positions == sorted(positions), (
        f"localise steps are out of spec order: {list(zip(order, positions))}"
    )


def test_preserved_inactive_set_reapplied_with_code_skipped() -> None:
    """AC / pull bookend: the preserved inactive set is re-applied after import,
    with plugin and theme code skipped during deactivation so an object-cache
    plugin cannot re-drop its drop-in mid-step (spec step 9)."""

    assert re.search(r"preserved inactive|inactive (?:plugin )?set", SKILL_TEXT, re.IGNORECASE), (
        "the preserved inactive set is not re-applied"
    )

    # The deactivation call carries --skip-plugins --skip-themes so no plugin or
    # theme code loads while it runs.
    assert re.search(
        r"deactivate.{0,80}--skip-plugins --skip-themes",
        SKILL_TEXT,
        re.IGNORECASE | re.DOTALL,
    ), "the deactivation does not skip plugin/theme code"

    # It runs after the import and before the final search-replace (spec order).
    assert _pos(r"ddev import-db") < _pos(r"plugin deactivate") < _pos(r"ddev wp search-replace")


def test_object_cache_ownership_rule_is_verified_and_removed() -> None:
    """AC / pull bookend: the object-cache drop-in is resolved by the ownership
    rule, then verified with a real request and auto-removed on failure — a
    production drop-in pointing at a loopback cache host is fatal locally
    (platform constraint 16)."""

    assert re.search(r"ownership rule", SKILL_TEXT, re.IGNORECASE), "no object-cache ownership rule"
    assert re.search(r"object[- ]cache", SKILL_TEXT, re.IGNORECASE)

    # A real request verifies the drop-in, and it is auto-removed when the request
    # cannot be served.
    assert re.search(r"request", SKILL_TEXT, re.IGNORECASE), "no request verification"
    assert re.search(r"auto-remove|remove the drop-in", SKILL_TEXT, re.IGNORECASE), (
        "the drop-in is not auto-removed on a failed request"
    )

    # It runs after the import (spec step 6), never against nothing local.
    assert _pos(r"ddev import-db") < _pos(r"ownership rule")


def test_thumbnail_regeneration_is_the_metadata_driven_delta() -> None:
    """AC / pull bookend: thumbnails regenerate as the metadata-driven delta at
    pull — newly registered sizes appear without regenerating the whole library —
    with ``--regenerate-all`` as the escape hatch (ADR-0011)."""

    assert re.search(r"metadata-driven", SKILL_TEXT, re.IGNORECASE), "not a metadata-driven delta"
    assert re.search(r"delta", SKILL_TEXT, re.IGNORECASE)
    assert "--regenerate-all" in SKILL_TEXT, "the --regenerate-all escape hatch is missing"
    assert re.search(r"ddev wp media regenerate", SKILL_TEXT), "no media regenerate invocation"


def test_configuration_define_drift_is_surfaced() -> None:
    """Pull bookend: a new production define of the portable class is surfaced in
    the report — configuration drift brought to attention, not silently ignored
    (spec user story 25)."""

    assert re.search(r"define", SKILL_TEXT, re.IGNORECASE)
    assert re.search(
        r"surface[sd]?[^.\n]*define|define[^.\n]*surface|new[^.\n]*define",
        SKILL_TEXT,
        re.IGNORECASE,
    ), "a new portable define (define drift) is not surfaced"


def test_new_baseline_is_written_with_its_scope() -> None:
    """Pull bookend: the new baseline manifest is written with the scope it was
    taken under, after the restart, so the next pull's diff and its
    scope-intersection deletion rule stay honest (ADR-0006)."""

    assert "GET /files" in SKILL_TEXT, "the baseline is not emitted by the GET /files walk"
    assert "last-sync.json" in SKILL_TEXT, "the baseline is not stored as last-sync.json"
    assert re.search(r"scope", SKILL_TEXT, re.IGNORECASE), "the baseline scope is not stored"

    # Anchored on the step-15 write heading — see the ordering test for why the
    # ``last-sync.json`` filename is not a safe write anchor at pull.
    assert _pos(r"ddev restart") < _pos(r"Write the new baseline"), (
        "the baseline write must be the last localise step"
    )


def test_final_flush_loads_plugins_before_the_restart_and_baseline() -> None:
    """AC #4: the run ends with the plugins-loaded rewrite flush, the DDEV restart,
    and the baseline write — a flush that skips plugins 404s localised subpages
    (platform constraint 14)."""

    assert re.search(r"plugins loaded", SKILL_TEXT, re.IGNORECASE)
    plugins_loaded = _pos(r"plugins loaded")
    assert _pos(r"ddev wp search-replace") < plugins_loaded < _pos(r"ddev restart")
    assert _pos(r"ddev restart") < _pos(r"Write the new baseline")


def test_verify_phase_uses_live_state_and_documents_the_operator_residual() -> None:
    """AC #5: the in-run verify phase smoke-tests from live state (URLs, error
    greps, a database check) after the baseline write, and the real-site smoke is
    documented as the operator's residual."""

    assert _pos(r"Write the new baseline") < _pos(r"ddev wp db check")
    assert re.search(r"critical error", SKILL_TEXT, re.IGNORECASE)
    assert re.search(r"residual|manual .*smoke", SKILL_TEXT, re.IGNORECASE)


# The safety rails the shared transfer engine carries into every run — each stated
# as a regex the faithful prose must satisfy. Dropping one in the pull rewrite
# reddens here even though the pull bookends have their own dedicated tests above.
SAFETY_RAILS: dict[str, str] = {
    "verify-targets-prod": r"targets production",
    "db-password-never-in-context": r"password[^.\n]*(?:never|not).*context|never[^.\n]*password",
    "sealed-to-ephemeral-key": r"ephemeral",
    "extraction-outside-docroot": r"outside the docroot",
    "authenticated-unseal-catches-corruption": r"authenticat",
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
def test_shared_engine_safety_rails_are_stated(rail: str, pattern: str) -> None:
    """Each safety rail the shared engine carries is stated in the pull
    orchestration — the risk warning, the outside-docroot packing, the secret
    handling, and the URL-scoped search-replace including the escaped-JSON,
    double-escaped-JSON, and their protocol-relative counterparts — a stored
    protocol-relative URL has no scheme to anchor a scheme-ful pass, so it needs
    its own escaped and double-escaped entries in the list."""

    assert re.search(pattern, SKILL_TEXT, re.IGNORECASE), f"safety rail {rail!r} not stated"
