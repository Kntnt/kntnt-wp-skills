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
    "user_submissions",
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
    "directory_name",
    "db_table_structure",
    "db_table_content",
    "user_submissions",
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
    resolved: dict[str, Any],
    saved_plan: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the helper's ``save`` operation over a resolved plan and return the
    persisted saved-plan document — the decisions-only round-trip subject. The
    optional ``saved_plan`` is the committed plan being overwritten, so a key a
    prior run settled for a decision this skill does not walk (a clone-derived
    ``target`` on a pull re-save) is carried forward rather than dropped. The
    optional ``source`` is the run's source record (MCP server and live URL) the
    runtime supplies, which the committed plan must carry as part of the
    reproducible per-site record (docs/spec.md, Persistent config)."""

    payload: dict[str, Any] = {
        "operation": "save", "resolved": resolved, "saved_plan": saved_plan,
    }
    if source is not None:
        payload["source"] = source
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


# --- User-submission tables: their own carry/empty gate, default empty -------
#
# Unlike the four operational categories (silently folded into the
# db_table_content recommendation), form/entry-submission tables are neither
# regenerable nor operational — the most privacy-sensitive data the transfer
# handles — so they get a standalone gate the operator walks or overrides,
# default empty for privacy minimisation (ADR-0014).


def test_user_submissions_defaults_to_empty_for_privacy_minimisation() -> None:
    # Arrange & Act: a plain run, no saved plan, no answer, no flag.
    plan = resolve(envelope())

    # Act.
    submissions = decision(plan, "user_submissions")

    # Assert: the built-in default is empty, sourced from the built-in layer.
    assert submissions["value"] == "empty"
    assert submissions["source"] == "built_in"


def test_a_saved_carry_choice_for_user_submissions_is_honoured_on_replay() -> None:
    # Arrange: a prior run's saved plan settled on carrying real form entries
    # (e.g. to debug a form flow locally) — the gate's way back from the privacy
    # default.
    plan = resolve(envelope(saved_plan={"user_submissions": "carry"}))

    # Act.
    submissions = decision(plan, "user_submissions")

    # Assert: the saved choice overrides the built-in empty default.
    assert submissions["value"] == "carry"
    assert submissions["source"] == "saved"


def test_a_this_run_answer_overrides_the_user_submissions_default() -> None:
    # Arrange & Act: no saved plan, this run answers carry.
    plan = resolve(envelope(answers={"user_submissions": "carry"}))

    # Act.
    submissions = decision(plan, "user_submissions")

    # Assert.
    assert submissions["value"] == "carry"
    assert submissions["source"] == "answer"


def test_user_submissions_is_walked_in_the_fresh_interactive_gate_list() -> None:
    # Arrange & Act: a fresh interactive run with no saved plan.
    plan = resolve(envelope())

    # Assert: the gate is surfaced like any other decision, not silently skipped.
    assert "user_submissions" in plan["gates"]


def test_the_saved_plan_persists_and_replays_a_carry_choice_for_user_submissions() -> None:
    # Arrange: an operator overrides the privacy default to carry for this site.
    fresh = resolve(envelope(answers={"user_submissions": "carry"}))
    written = save(fresh)

    # Act: the choice is persisted, then a later run replays the saved plan.
    assert written["user_submissions"] == "carry"
    replayed = resolve(envelope(saved_plan=written))

    # Assert: the replay honours the persisted carry choice from the saved layer.
    submissions = decision(replayed, "user_submissions")
    assert submissions["value"] == "carry"
    assert submissions["source"] == "saved"


def test_the_saved_plan_persists_the_empty_default_when_never_overridden() -> None:
    # Arrange & Act: an accepted fresh plan with no override.
    written = save(resolve(envelope()))

    # Assert: the privacy default is explicitly persisted, not merely implied by
    # absence — so a later run replays "empty" from the saved layer rather than
    # re-deriving the built-in default.
    assert written["user_submissions"] == "empty"


# --- The user_submissions gate's resolved choice folds into db_table_content --
#
# A resolved 'carry' must change what the dump actually carries, not merely add
# a value to the plan JSON: classify.py already puts every user-submission table
# in the empty (schema-only) split, and nothing downstream re-derives the fold on
# its own, so the resolved plan itself is where a carry has to take effect
# (ADR-0014).


def test_a_carry_answer_moves_user_submission_tables_from_empty_into_the_content_split() -> None:
    # Arrange: a site with Gravity Forms entry tables, this run answers carry.
    plan = resolve(
        envelope("form-submissions-site.json", answers={"user_submissions": "carry"})
    )

    # Act.
    tables = decision(plan, "db_table_content")["value"]

    # Assert: the form-submission tables moved into the full-data list and no
    # longer appear in the empty one — the resolved value is what the pack
    # script's content/empty table lists and the dump-sanity check both read.
    assert "wp_gf_entry" in tables["full"]
    assert "wp_gf_entry_meta" in tables["full"]
    empty_names = {entry["name"] for entry in tables["empty"]}
    assert "wp_gf_entry" not in empty_names
    assert "wp_gf_entry_meta" not in empty_names


def test_the_empty_default_leaves_user_submission_tables_in_the_empty_split() -> None:
    # Arrange & Act: no override, so user_submissions keeps its privacy default.
    plan = resolve(envelope("form-submissions-site.json"))

    # Assert: the form-submission tables stay schema-only, unaffected by the fold.
    tables = decision(plan, "db_table_content")["value"]
    empty_names = {entry["name"] for entry in tables["empty"]}
    assert {"wp_gf_entry", "wp_gf_entry_meta"} <= empty_names
    assert "wp_gf_entry" not in tables["full"]


def test_a_saved_carry_choice_folds_into_the_db_table_content_recommendation_too() -> None:
    # Arrange: a prior run's saved plan already settled on carry for this site —
    # the fold must reach the gate's recommendation, not only the resolved value,
    # so the db_table_content gate the operator sees does not contradict the
    # choice already on record.
    plan = resolve(
        envelope("form-submissions-site.json", saved_plan={"user_submissions": "carry"})
    )

    # Act.
    tables = decision(plan, "db_table_content")

    # Assert: both fields show the folded split.
    assert "wp_gf_entry" in tables["value"]["full"]
    assert "wp_gf_entry" in tables["recommendation"]["full"]


def test_a_this_run_carry_answer_does_not_retroactively_fold_the_recommendation() -> None:
    # Arrange: the saved plan settled on empty; this run answers carry. The
    # db_table_content recommendation mirrors the recommendation layer (built-in
    # < live < saved), never the this-run answer — the same "recommendation
    # predates the answer" contract every other decision honours (see
    # test_this_run_answer_overrides_saved_config).
    plan = resolve(
        envelope(
            "form-submissions-site.json",
            saved_plan={"user_submissions": "empty"},
            answers={"user_submissions": "carry"},
        )
    )

    # Act.
    tables = decision(plan, "db_table_content")

    # Assert: the resolved value is folded, the recommendation is not.
    assert "wp_gf_entry" in tables["value"]["full"]
    empty_recommendation_names = {entry["name"] for entry in tables["recommendation"]["empty"]}
    assert "wp_gf_entry" in empty_recommendation_names


# --- Live-derived and skill-specific decisions --------------------------------


def test_live_derived_decisions_carry_production_values_at_the_live_layer() -> None:
    # Arrange & Act.
    plan = resolve(envelope("monolingual-site.json"))

    # Assert: the table prefix is adopted from production at the live layer.
    prefix = decision(plan, "table_prefix")
    assert prefix["value"] == "blog_"
    assert prefix["source"] == "live"


def test_engine_pin_truncates_the_database_version_to_major_minor() -> None:
    """Issue #14: the ``db_engine_php`` pin is interpolated verbatim into
    ``ddev config --database=<flavour>:<version>``, and DDEV accepts only
    ``major.minor`` there — the same granularity already enforced for PHP.
    Discovery reports the full patch-level server version (``10.11.6-MariaDB``);
    the resolved value must already be truncated, not passed through raw."""

    # Arrange & Act.
    plan = resolve(envelope("mariadb-site.json"))

    # Assert: both the database and the PHP version are major.minor, never the
    # patch-level string discovery reported.
    engine = decision(plan, "db_engine_php")
    assert engine["value"] == {"flavour": "mariadb", "version": "10.11", "php_major_minor": "8.3"}
    assert engine["source"] == "live"


def test_clone_walks_the_project_name_bookend_and_omits_pull_only_decisions() -> None:
    # Arrange & Act.
    plan = resolve(envelope(skill="clone"))

    # Assert: clone opens with the project-name and directory-name bookends and
    # carries no preserved inactive set, object-cache derivation, or deletion
    # mirroring.
    ids = [entry["id"] for entry in plan["decisions"]]
    assert ids == CLONE_DECISIONS
    assert decision(plan, "project_name")["value"] == "example"
    assert decision(plan, "directory_name")["value"] == "www.example.com"


def test_directory_name_is_a_decision_the_operator_corrects_independently_of_project_name() -> None:
    # Arrange & Act: this run answers only the directory-name gate, declining
    # the derived project name's sibling gate — the machinery the name-
    # derivation gate relies on to let the operator correct either name on its
    # own (issue #11).
    plan = resolve(
        envelope(skill="clone", answers={"directory_name": "my-custom-dir"})
    )

    # Assert: the directory-name answer lands as its own decision's resolved
    # value, and the project-name decision it did not touch keeps its own live
    # recommendation untouched.
    assert decision(plan, "directory_name")["value"] == "my-custom-dir"
    assert decision(plan, "directory_name")["source"] == "answer"
    assert decision(plan, "project_name")["value"] == "example"
    assert decision(plan, "project_name")["source"] == "live"


def test_pull_carries_the_pull_only_decisions_and_no_project_name() -> None:
    # Arrange & Act: directory_name is a clone-only bookend, like project_name.
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
    # Arrange: a clone opens with the project-name and directory-name bookends,
    # which persist under the saved-plan 'target' and 'directory' keys — a path
    # the pull round-trip never exercises.
    fresh = resolve(envelope(skill="clone"))
    written = save(fresh)

    # Act: read the saved plan back, re-resolve, and persist again.
    replayed = resolve(envelope(skill="clone", saved_plan=written))
    rewritten = save(replayed)

    # Assert: the clone-derived names are stored under 'target' and 'directory'
    # and the decisions-only round-trip is an identity, resolving both from the
    # saved layer — so the operator's correction to either survives a replay.
    assert written["target"] == "example"
    assert written["directory"] == "www.example.com"
    assert rewritten == written
    assert decision(replayed, "project_name")["value"] == "example"
    assert decision(replayed, "project_name")["source"] == "saved"
    assert decision(replayed, "directory_name")["value"] == "www.example.com"
    assert decision(replayed, "directory_name")["source"] == "saved"


def test_a_pull_resave_preserves_the_clone_saved_target() -> None:
    # Arrange: a clone settles the plan and commits it, recording the DDEV project
    # under 'target' and the clone directory under 'directory' — fields
    # docs/spec.md requires the committed saved plan to carry. The operator later
    # runs a pull, which reads that same committed plan.
    clone_written = save(resolve(envelope(skill="clone")))
    assert clone_written["target"] == "example"
    assert clone_written["directory"] == "www.example.com"

    # Act: the pull re-resolves against the committed plan and persists the
    # accepted result back over the same file (SKILL step 3 writes it verbatim).
    pull_replay = resolve(envelope(skill="pull", saved_plan=clone_written))
    pull_written = save(pull_replay, saved_plan=clone_written)

    # Assert: the pull re-save carries the clone-derived target and directory
    # forward instead of dropping them — a refresh must not silently strip the
    # committed DDEV project or clone directory that clone (the only skill that
    # walks project_name and directory_name) recorded, while the pull-only
    # decisions it does walk are still persisted.
    assert pull_written["target"] == "example"
    assert pull_written["directory"] == "www.example.com"
    assert pull_written["deletion_mirroring"] == "off"


# --- The saved plan records the run's source and never strips it on re-save ----


def test_the_save_records_the_source_supplied_for_the_run() -> None:
    # Arrange: the runtime supplies the run's source — the MCP server and the live
    # URL — which docs/spec.md's persistent config requires the committed plan to
    # record, so the copy is a fully reproducible per-site record.
    source = {"mcp_server": "novamira-example", "live_url": "https://www.example.com"}

    # Act.
    written = save(resolve(envelope(skill="clone")), source=source)

    # Assert: the source is persisted alongside the decisions.
    assert written["source"] == source


def test_a_resave_preserves_the_committed_source_record() -> None:
    # Arrange: a committed plan already records the source an earlier run wrote.
    # A pull re-save writes the whole file from the helper's output, so the
    # decisions-only carry-forward allowlist must carry the documented source
    # forward rather than strip it (docs/spec.md, Persistent config).
    committed = {
        "target": "example",
        "source": {"mcp_server": "novamira-example", "live_url": "https://www.example.com"},
        "media": "include",
    }

    # Act: the pull re-resolves against the committed plan and persists back over
    # the same file, supplying no fresh source this run.
    written = save(
        resolve(envelope(skill="pull", saved_plan=committed)), saved_plan=committed
    )

    # Assert: the source survives the re-save intact.
    assert written["source"] == {
        "mcp_server": "novamira-example",
        "live_url": "https://www.example.com",
    }


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


# --- docs/spec.md's Persistent config prose matches SAVED_KEYS -------------


def test_spec_persistent_config_enumerates_the_user_submissions_answer() -> None:
    """AC: docs/spec.md's "Persistent config" section enumerates the saved
    plan's persisted decisions; the user-submissions carry/empty answer is one
    of them (SAVED_KEYS["user_submissions"], ADR-0014) and must not be missing
    from the prose alongside its siblings (the plugin-preservation choice, the
    cron choice, the deletion-mirroring answer)."""

    spec_path = Path(__file__).resolve().parent.parent / "docs" / "spec.md"
    text = spec_path.read_text(encoding="utf-8")
    sentence = next(
        line for line in text.splitlines() if line.startswith("- `.kntnt-wp-skills.json`")
    )
    assert "user-submissions" in sentence or "user_submissions" in sentence, (
        f"spec.md's Persistent config sentence omits the user-submissions "
        f"answer: {sentence!r}"
    )


def test_invalid_json_input_fails_loudly() -> None:
    # Arrange & Act: raw bytes that are not JSON at all reach the parser first.
    result = subprocess.run(
        [sys.executable, str(RESOLVE)], input=b"this is not json", capture_output=True
    )

    # Assert: the parser reports the malformed payload rather than crashing.
    assert result.returncode != 0
    assert b"json" in result.stderr.lower()
    assert result.stdout == b""
