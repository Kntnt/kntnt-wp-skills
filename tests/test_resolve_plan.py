# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Behavioural tests for the decision-backbone helper CLI.

The helper is the deterministic seam that resolves the engine's ordered decision
list over the layered defaults — built-in default < live derivation < saved
config < this run's answer — and produces, for each decision, the recommendation
its gate presents, the resolved value, and the source layer, plus the gate list
the run walks. Every test exercises that seam through the real command: a JSON
envelope in on stdin (the canonical discovery document, the classifications, an
optional saved plan, the run's flags and this-run answers), the resolved plan out
as JSON on stdout — and never reaches into the helper's internals.

The discovery documents and classifications are produced by piping the shared raw
fixtures through the real ``discovery.py`` and ``classify.py``, so the backbone is
anchored to the shapes the engine actually emits rather than a hand-authored
stand-in. No test touches a real site.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
RESOLVE = SCRIPTS / "resolve_plan.py"
DISCOVERY = SCRIPTS / "discovery.py"
CLASSIFY = SCRIPTS / "classify.py"

# The ordered decision lists each skill walks — the behavioural contract the gate
# list and the skill-specific bookends are asserted against.
PULL_DECISIONS = [
    "db_table_structure",
    "db_table_content",
    "table_prefix",
    "db_engine_php",
    "media_originals",
    "generated_thumbnails",
    "sideloaded_files",
    "heavy_blobs",
    "wp_config_defines",
    "plugins_deactivate",
    "object_cache",
    "thumbnail_regeneration",
    "mail",
    "cron",
    "deletion_mirroring",
]
CLONE_DECISIONS = [
    "project_name",
    "db_table_structure",
    "db_table_content",
    "table_prefix",
    "db_engine_php",
    "media_originals",
    "generated_thumbnails",
    "sideloaded_files",
    "heavy_blobs",
    "wp_config_defines",
    "thumbnail_regeneration",
    "mail",
    "cron",
]


def _pipe(script: Path, payload: bytes) -> bytes:
    """Run a helper script with ``payload`` on stdin and return its stdout,
    asserting a clean exit — the plumbing that anchors the backbone's inputs to
    the real discovery and classify seams."""

    result = subprocess.run([sys.executable, str(script)], input=payload, capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    return result.stdout


def canonical_inputs(raw_fixture: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Produce the canonical discovery document and classifications for a raw
    site fixture by piping it through the real ``discovery.py`` and
    ``classify.py`` — the exact inputs the backbone consumes at run time."""

    document_bytes = _pipe(DISCOVERY, (FIXTURES / raw_fixture).read_bytes())
    classifications_bytes = _pipe(CLASSIFY, document_bytes)
    return json.loads(document_bytes), json.loads(classifications_bytes)


def envelope(
    raw_fixture: str = "representative-site.json",
    *,
    skill: str = "pull",
    flags: list[str] | None = None,
    answers: dict[str, Any] | None = None,
    saved_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a ``resolve`` envelope from a raw site fixture and the run's
    knobs — the single input shape the backbone reads on stdin."""

    document, classifications = canonical_inputs(raw_fixture)
    return {
        "operation": "resolve",
        "skill": skill,
        "flags": flags or [],
        "answers": answers or {},
        "discovery": document,
        "classifications": classifications,
        "saved_plan": saved_plan,
    }


def run_resolve(payload: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    """Run the backbone helper with ``payload`` on stdin and capture its result."""

    return subprocess.run(
        [sys.executable, str(RESOLVE)], input=json.dumps(payload).encode(), capture_output=True
    )


def resolve(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the backbone helper, assert a clean exit, and return the parsed plan."""

    result = run_resolve(payload)
    assert result.returncode == 0, result.stderr.decode()
    plan: dict[str, Any] = json.loads(result.stdout)
    return plan


def save(
    resolved: dict[str, Any], saved_plan: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Run the helper's ``save`` operation over a resolved plan and return the
    persisted saved-plan document — the decisions-only round-trip subject. The
    optional ``saved_plan`` is the committed plan being overwritten, so a key a
    prior run settled for a decision this skill does not walk (a clone-derived
    ``target`` on a pull re-save) is carried forward rather than dropped."""

    payload = {"operation": "save", "resolved": resolved, "saved_plan": saved_plan}
    result = run_resolve(payload)
    assert result.returncode == 0, result.stderr.decode()
    saved: dict[str, Any] = json.loads(result.stdout)
    return saved


def decision(plan: dict[str, Any], decision_id: str) -> dict[str, Any]:
    """Return the single resolved decision with the given id."""

    matches = [entry for entry in plan["decisions"] if entry["id"] == decision_id]
    assert len(matches) == 1, f"expected exactly one {decision_id!r}, got {len(matches)}"
    return matches[0]


# --- Layer precedence: each layer overrides the one below it, nothing above ---


def test_built_in_default_wins_when_no_higher_layer_applies() -> None:
    # Arrange: a plain pull with no saved plan, no answer, no flag.
    plan = resolve(envelope())

    # Act: read the media-originals decision, which has only a built-in default.
    media = decision(plan, "media_originals")

    # Assert: the built-in "include" default is the resolved value and source.
    assert media["value"] == "include"
    assert media["source"] == "built_in"


def test_live_derivation_overrides_the_built_in_default() -> None:
    # Arrange: a site with a poised campaign, so the live mass-send valve derives
    # a value that departs from the built-in "live" mail default.
    plan = resolve(envelope("poised-campaign-site.json"))

    # Act.
    mail = decision(plan, "mail")

    # Assert: the live derivation (capture) overrides the built-in default (live).
    assert mail["value"] == "capture"
    assert mail["source"] == "live"


def test_saved_config_overrides_the_live_derivation() -> None:
    # Arrange: a poised campaign (live derivation flips to capture) but the saved
    # plan pins mail to live.
    plan = resolve(envelope("poised-campaign-site.json", saved_plan={"mail": "live"}))

    # Act.
    mail = decision(plan, "mail")

    # Assert: the saved pin overrides the live valve.
    assert mail["value"] == "live"
    assert mail["source"] == "saved"


def test_this_run_answer_overrides_saved_config() -> None:
    # Arrange: the saved plan excludes media, but this run answers include.
    plan = resolve(
        envelope(saved_plan={"media": "exclude"}, answers={"media_originals": "include"})
    )

    # Act.
    media = decision(plan, "media_originals")

    # Assert: the this-run answer is the resolved value and source; the gate's
    # recommendation still shows the saved value it presented before the answer.
    assert media["value"] == "include"
    assert media["source"] == "answer"
    assert media["recommendation"] == "exclude"
    assert media["recommendation_source"] == "saved"


def test_a_lower_layer_never_overrides_a_higher_one() -> None:
    # Arrange: built-in, live-adjacent, and saved all present for media (via a
    # saved value) with no answer — the saved value must stand.
    plan = resolve(envelope(saved_plan={"media": "exclude"}))

    # Act.
    media = decision(plan, "media_originals")

    # Assert: the saved value wins; the built-in default beneath it is not applied.
    assert media["value"] == "exclude"
    assert media["source"] == "saved"


# --- Flag pinning: a coarse flag pins its decision above every layer ----------


def test_a_coarse_flag_pins_its_decision_above_saved_and_answer() -> None:
    # Arrange: saved includes media, this run answers include, but --exclude-media
    # pins the opposite.
    plan = resolve(
        envelope(
            flags=["--exclude-media"],
            saved_plan={"media": "include"},
            answers={"media_originals": "include"},
        )
    )

    # Act.
    media = decision(plan, "media_originals")

    # Assert: the flag pins the value above every layer.
    assert media["value"] == "exclude"
    assert media["source"] == "flag"


def test_include_blobs_flag_pins_the_blob_decision_to_include() -> None:
    # Arrange & Act: blobs default to exclude; the flag pins include.
    default_blobs = decision(resolve(envelope()), "heavy_blobs")
    pinned_blobs = decision(resolve(envelope(flags=["--include-blobs"])), "heavy_blobs")

    # Assert.
    assert default_blobs["value"] == "exclude"
    assert default_blobs["source"] == "built_in"
    assert pinned_blobs["value"] == "include"
    assert pinned_blobs["source"] == "flag"


def test_no_cron_flag_pins_cron_to_disabled() -> None:
    # Arrange & Act.
    default_cron = decision(resolve(envelope()), "cron")
    pinned_cron = decision(resolve(envelope(flags=["--no-cron"])), "cron")

    # Assert: cron runs by default and the flag pins it disabled.
    assert default_cron["value"] == "run"
    assert pinned_cron["value"] == "disabled"
    assert pinned_cron["source"] == "flag"


def test_regenerate_all_flag_pins_thumbnail_regeneration() -> None:
    # Arrange & Act: a pull defaults to the metadata-driven delta; the flag forces
    # the whole library.
    default_regen = decision(resolve(envelope()), "thumbnail_regeneration")
    forced_regen = decision(resolve(envelope(flags=["--regenerate-all"])), "thumbnail_regeneration")

    # Assert.
    assert default_regen["value"] == "delta"
    assert forced_regen["value"] == "all"
    assert forced_regen["source"] == "flag"


# --- --yes semantics: stop at the saved-config layer, never consume an answer -


def test_yes_run_never_consumes_a_this_run_answer() -> None:
    # Arrange: a saved plan excludes media and this run answers include, but --yes
    # must stop at the saved-config layer and ignore the answer.
    plan = resolve(
        envelope(
            flags=["--yes"],
            saved_plan={"media": "exclude"},
            answers={"media_originals": "include"},
        )
    )

    # Act.
    media = decision(plan, "media_originals")

    # Assert: the answer is not consumed; the saved value stands.
    assert media["value"] == "exclude"
    assert media["source"] == "saved"


def test_yes_run_falls_to_built_in_when_only_an_answer_would_override() -> None:
    # Arrange: no saved plan; only a this-run answer would raise media above its
    # built-in default, but --yes drops the answer layer entirely.
    plan = resolve(envelope(flags=["--yes"], answers={"media_originals": "exclude"}))

    # Act.
    media = decision(plan, "media_originals")

    # Assert: the built-in default wins because --yes never consumes the answer.
    assert media["value"] == "include"
    assert media["source"] == "built_in"


def test_yes_run_still_honours_a_flag_pin() -> None:
    # Arrange: --yes plus a coarse pin — the flag is not a this-run answer, so it
    # still pins.
    plan = resolve(envelope(flags=["--yes", "--exclude-media"]))

    # Act.
    media = decision(plan, "media_originals")

    # Assert.
    assert media["value"] == "exclude"
    assert media["source"] == "flag"


def test_yes_run_reports_yes_mode_and_no_interactive_gates() -> None:
    # Arrange & Act.
    plan = resolve(envelope(flags=["--yes"]))

    # Assert: an unattended run walks no gates.
    assert plan["mode"] == "yes"
    assert plan["gates"] == []


# --- The mass-send valve flips mail only on a poised campaign -----------------


def test_mail_stays_live_without_a_poised_campaign() -> None:
    # Arrange & Act: a representative site with no poised campaign.
    mail = decision(resolve(envelope()), "mail")

    # Assert: mail keeps the real mailer by default.
    assert mail["value"] == "live"
    assert mail["source"] == "built_in"


def test_mail_flips_to_capture_on_a_poised_campaign_and_surfaces_the_finding() -> None:
    # Arrange & Act.
    mail = decision(resolve(envelope("poised-campaign-site.json")), "mail")

    # Assert: the valve flips mail to capture and leads with the loud finding.
    assert mail["value"] == "capture"
    assert mail["source"] == "live"
    assert any("Summer Sale 2026" in finding for finding in mail["findings"])


def test_an_uncertain_unrecognised_mailer_does_not_flip_mail() -> None:
    # Arrange & Act: an unrecognised mailer with a generic signal is surfaced but
    # never flips the recommendation on its own.
    mail = decision(resolve(envelope("unrecognised-mailer-site.json")), "mail")

    # Assert.
    assert mail["value"] == "live"
    assert mail["source"] == "built_in"


def test_live_mail_flag_pins_live_past_a_detected_campaign() -> None:
    # Arrange & Act: a poised campaign that would flip to capture, overridden.
    mail = decision(
        resolve(envelope("poised-campaign-site.json", flags=["--live-mail"])), "mail"
    )

    # Assert: the flag forces the real mailer even past the valve.
    assert mail["value"] == "live"
    assert mail["source"] == "flag"


def test_capture_mail_flag_pins_capture_without_a_campaign() -> None:
    # Arrange & Act: a quiet site the valve would leave live, forced to capture.
    mail = decision(resolve(envelope(flags=["--capture-mail"])), "mail")

    # Assert.
    assert mail["value"] == "capture"
    assert mail["source"] == "flag"


# --- Live-derived and skill-specific decisions --------------------------------


def test_live_derived_decisions_carry_production_values_at_the_live_layer() -> None:
    # Arrange & Act.
    plan = resolve(envelope("monolingual-site.json"))

    # Assert: the table prefix is adopted from production at the live layer.
    prefix = decision(plan, "table_prefix")
    assert prefix["value"] == "blog_"
    assert prefix["source"] == "live"


def test_clone_walks_the_project_name_bookend_and_omits_pull_only_decisions() -> None:
    # Arrange & Act.
    plan = resolve(envelope(skill="clone"))

    # Assert: clone opens with the project-name bookend and carries no preserved
    # inactive set, object-cache derivation, or deletion mirroring.
    ids = [entry["id"] for entry in plan["decisions"]]
    assert ids == CLONE_DECISIONS
    assert decision(plan, "project_name")["value"] == "example"


def test_pull_carries_the_pull_only_decisions_and_no_project_name() -> None:
    # Arrange & Act.
    plan = resolve(envelope(skill="pull"))

    # Assert.
    ids = [entry["id"] for entry in plan["decisions"]]
    assert ids == PULL_DECISIONS


# --- Gate list: the walk, the flag-pinned skip, and the replay collapse -------


def test_fresh_interactive_run_walks_the_full_ordered_decision_list() -> None:
    # Arrange & Act: no saved plan, interactive.
    plan = resolve(envelope(skill="pull"))

    # Assert.
    assert plan["mode"] == "interactive"
    assert plan["replay"] is False
    assert plan["gates"] == PULL_DECISIONS


def test_a_flag_pinned_decision_is_dropped_from_the_interactive_walk() -> None:
    # Arrange & Act: --no-cron pins cron, so the operator need not be asked.
    plan = resolve(envelope(skill="pull", flags=["--no-cron"]))

    # Assert.
    assert "cron" not in plan["gates"]
    assert plan["gates"] == [d for d in PULL_DECISIONS if d != "cron"]


def test_a_saved_plan_collapses_the_walk_to_the_single_replay_gate() -> None:
    # Arrange & Act: a saved plan present, interactive.
    plan = resolve(envelope(saved_plan={"media": "exclude", "cron": "run"}))

    # Assert: the whole walk collapses to one replay gate.
    assert plan["replay"] is True
    assert plan["gates"] == ["replay"]


def test_replay_under_yes_runs_the_saved_plan_with_no_gate() -> None:
    # Arrange & Act: a saved plan under --yes replays silently.
    plan = resolve(envelope(flags=["--yes"], saved_plan={"media": "exclude"}))

    # Assert.
    assert plan["replay"] is True
    assert plan["gates"] == []


# --- Saved-plan round-trip: decisions, never computed lists -------------------


def test_an_accepted_plan_round_trips_to_an_identical_saved_plan() -> None:
    # Arrange: resolve a fresh pull and persist the accepted decisions.
    fresh = resolve(envelope(skill="pull"))
    written = save(fresh)

    # Act: read the saved plan back, re-resolve, and persist again.
    replayed = resolve(envelope(skill="pull", saved_plan=written))
    rewritten = save(replayed)

    # Assert: the plan written out equals the plan read back and written again,
    # and the persisted decisions now resolve from the saved layer.
    assert rewritten == written
    assert decision(replayed, "media_originals")["source"] == "saved"
    assert decision(replayed, "cron")["source"] == "saved"


def test_a_clone_plan_round_trips_including_the_project_name_target() -> None:
    # Arrange: a clone opens with the project-name bookend, which persists under
    # the saved-plan 'target' key — a path the pull round-trip never exercises.
    fresh = resolve(envelope(skill="clone"))
    written = save(fresh)

    # Act: read the saved plan back, re-resolve, and persist again.
    replayed = resolve(envelope(skill="clone", saved_plan=written))
    rewritten = save(replayed)

    # Assert: the clone-derived project name is stored under 'target' and the
    # decisions-only round-trip is an identity, resolving from the saved layer.
    assert written["target"] == "example"
    assert rewritten == written
    assert decision(replayed, "project_name")["value"] == "example"
    assert decision(replayed, "project_name")["source"] == "saved"


def test_a_pull_resave_preserves_the_clone_saved_target() -> None:
    # Arrange: a clone settles the plan and commits it, recording the DDEV project
    # under 'target' — the field docs/spec.md requires the committed saved plan to
    # carry. The operator later runs a pull, which reads that same committed plan.
    clone_written = save(resolve(envelope(skill="clone")))
    assert clone_written["target"] == "example"

    # Act: the pull re-resolves against the committed plan and persists the
    # accepted result back over the same file (SKILL step 3 writes it verbatim).
    pull_replay = resolve(envelope(skill="pull", saved_plan=clone_written))
    pull_written = save(pull_replay, saved_plan=clone_written)

    # Assert: the pull re-save carries the clone-derived target forward instead of
    # dropping it — a refresh must not silently strip the committed DDEV project
    # that clone (the only skill that derives project_name) recorded, while the
    # pull-only decisions it does walk are still persisted.
    assert pull_written["target"] == "example"
    assert pull_written["deletion_mirroring"] == "off"


# --- The mass-send valve is never silently defeated on replay -----------------


def test_a_saved_live_mail_masking_a_fresh_campaign_regates_mail_on_interactive_replay() -> None:
    # Arrange & Act: a prior run saved mail=live; on replay the site now carries a
    # freshly-poised campaign the saved concrete value would blast past.
    plan = resolve(envelope("poised-campaign-site.json", saved_plan={"mail": "live"}))

    # Assert: the replay walk re-surfaces the mail gate alongside the replay gate,
    # while the saved value it recommends stands and still leads with the finding.
    assert plan["replay"] is True
    assert plan["gates"] == ["replay", "mail"]
    mail = decision(plan, "mail")
    assert mail["value"] == "live"
    assert mail["source"] == "saved"
    assert any("Summer Sale 2026" in finding for finding in mail["findings"])


def test_a_saved_live_mail_masking_a_fresh_campaign_regates_mail_under_yes_replay() -> None:
    # Arrange & Act: the same collision under --yes, where the walk is otherwise
    # silent — the one about-to-fire hazard the valve exists to catch (ADR-0009).
    plan = resolve(
        envelope("poised-campaign-site.json", flags=["--yes"], saved_plan={"mail": "live"})
    )

    # Assert: the otherwise-empty unattended replay still stops on the mail gate,
    # so a real recipient list is never blasted without a confirmation.
    assert plan["replay"] is True
    assert plan["gates"] == ["mail"]
    assert any("Summer Sale 2026" in finding for finding in decision(plan, "mail")["findings"])


def test_a_this_run_live_mail_flag_is_not_regated_on_replay() -> None:
    # Arrange & Act: --live-mail on this run is a deliberate, present override of
    # the valve (ADR-0009), not a stale saved value, so it must not re-gate.
    plan = resolve(
        envelope(
            "poised-campaign-site.json",
            flags=["--yes", "--live-mail"],
            saved_plan={"mail": "live"},
        )
    )

    # Assert: the deliberate flag override leaves the unattended replay silent.
    assert decision(plan, "mail")["source"] == "flag"
    assert plan["gates"] == []


def test_an_unattended_replay_without_a_campaign_stays_silent() -> None:
    # Arrange & Act: a saved mail=live but no poised campaign — no about-to-fire
    # hazard, so the valve does not re-gate and the replay stays silent.
    plan = resolve(envelope(flags=["--yes"], saved_plan={"mail": "live"}))

    # Assert.
    assert plan["replay"] is True
    assert plan["gates"] == []


def test_the_saved_plan_stores_decisions_and_never_computed_lists() -> None:
    # Arrange & Act.
    written = save(resolve(envelope(skill="pull")))

    # Assert: the coarse per-site decisions are stored.
    assert written["media"] == "include"
    assert written["cron"] == "run"
    assert written["mail"] == "risk_adaptive"
    assert written["deletion_mirroring"] == "off"

    # Assert: no computed list ever rides into the saved plan — no table
    # full/empty split, no flagged-blob list, no thumbnail exclude-set, and the
    # ported defines are names only, never their live-fetched values.
    blob = json.dumps(written)
    assert "wp_posts" not in blob
    assert "galleries" not in blob
    assert "full" not in written
    assert "empty" not in written
    for name in written.get("ported_defines", []):
        assert isinstance(name, str)


# --- Contract: malformed input fails loudly -----------------------------------


def test_missing_discovery_document_fails_loudly() -> None:
    # Arrange: an envelope with no discovery section.
    payload = {"operation": "resolve", "skill": "pull", "flags": [], "classifications": {}}

    # Act.
    result = run_resolve(payload)

    # Assert: a non-zero exit and a resolve_plan diagnostic naming the missing
    # section, never a half-built plan on stdout.
    assert result.returncode != 0
    assert b"discovery" in result.stderr.lower()
    assert result.stdout == b""


def test_a_present_but_malformed_discovery_document_fails_loudly() -> None:
    # Arrange: a discovery section that is an object — so it passes the top-level
    # shape check — but lacks the nested keys the live derivations read.
    payload = envelope()
    payload["discovery"] = {}

    # Act.
    result = run_resolve(payload)

    # Assert: the fail-loud contract holds for a malformed inner shape too — the
    # resolve_plan diagnostic rather than a raw traceback, a non-zero exit, and no
    # half-built plan on stdout.
    assert result.returncode != 0
    assert b"resolve_plan:" in result.stderr
    assert b"Traceback" not in result.stderr
    assert result.stdout == b""


def test_a_present_but_malformed_classifications_document_fails_loudly() -> None:
    # Arrange: a classifications section that is an object but lacks the nested
    # keys the live derivations read.
    payload = envelope()
    payload["classifications"] = {}

    # Act.
    result = run_resolve(payload)

    # Assert.
    assert result.returncode != 0
    assert b"resolve_plan:" in result.stderr
    assert b"Traceback" not in result.stderr
    assert result.stdout == b""


def test_an_unknown_operation_fails_loudly() -> None:
    # Arrange & Act: an envelope naming an operation the seam does not implement.
    result = run_resolve({"operation": "frobnicate"})

    # Assert: the unknown operation is a loud contract violation, not a partial
    # plan on stdout.
    assert result.returncode != 0
    assert b"unknown operation" in result.stderr.lower()
    assert result.stdout == b""


def test_invalid_json_input_fails_loudly() -> None:
    # Arrange & Act: raw bytes that are not JSON at all reach the parser first.
    result = subprocess.run(
        [sys.executable, str(RESOLVE)], input=b"this is not json", capture_output=True
    )

    # Assert: the parser reports the malformed payload rather than crashing.
    assert result.returncode != 0
    assert b"json" in result.stderr.lower()
    assert result.stdout == b""
