# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Resolve the engine's ordered decision list over the layered defaults.

This helper is the decision-backbone seam of the transfer engine. The runtime
skill has already gathered the canonical discovery document (``discovery.py``'s
output) and the classifications (``classify.py``'s output); this helper reads
them — together with an optional saved plan, the run's flags, and any this-run
answers — as one JSON envelope on stdin, and writes the resolved plan on stdout:
for every decision, the recommendation its gate presents, the resolved value,
and the source layer it came from, plus the ordered gate list the run walks.

The single rule the whole backbone turns on is layer precedence (ADR-0005):

    built-in default  <  live derivation  <  saved config  <  this-run answer

with a coarse flag pinning its decision above all four (ADR-0013), and ``--yes``
stopping at the saved-config layer — it never consumes a this-run answer. A saved
plan collapses the interactive walk to the single "Replay the saved plan?" gate.

One safety exception overrides that collapse: when a saved concrete ``live`` mail
mode would mask a freshly-poised campaign, the mass-send valve re-surfaces the
mail gate even on an otherwise-silent unattended replay, so a real recipient list
is never blasted without a confirmation (ADR-0009).

Two operations share the seam:

- ``resolve`` (the default) turns the envelope into the resolved plan.
- ``save`` turns an accepted resolved plan back into the saved plan — decisions
  only, never the computed lists (the table split, the flagged blobs, the
  thumbnail exclude-set, the ported defines' live values), so nothing in it goes
  stale as production evolves. Writing an accepted plan out and reading it back
  is an identity.

Malformed input fails loudly — a wrong top-level shape or a malformed upstream
document (a missing nested key, a wrong-typed section) alike: a non-zero exit and
a ``resolve_plan:`` diagnostic on stderr, never a half-built plan on stdout.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# The sentinel a layer returns when it contributes no value, distinct from a
# genuine ``None`` a layer might legitimately resolve to.
MISSING: Any = object()

# The two skills the backbone shapes its decision list for; a clone is a pull
# with no baseline, so they differ only at the bookends.
CLONE = "clone"
PULL = "pull"
BOTH = frozenset({CLONE, PULL})

# Each coarse flag pins one decision to one value, above every layer (ADR-0013).
# ``--yes`` is the run-mode switch, not a pin, so it is deliberately absent here.
FLAG_PINS: dict[str, tuple[str, Any]] = {
    "--include-media": ("media_originals", "include"),
    "--exclude-media": ("media_originals", "exclude"),
    "--include-blobs": ("heavy_blobs", "include"),
    "--live-mail": ("mail", "live"),
    "--capture-mail": ("mail", "capture"),
    "--no-cron": ("cron", "disabled"),
    "--regenerate-all": ("thumbnail_regeneration", "all"),
}

# The saved-plan key each persistable decision is stored under. A decision absent
# here re-derives from live state every run and is never persisted, so the saved
# plan stores decisions, never computed lists.
SAVED_KEYS: dict[str, str] = {
    "project_name": "target",
    "media_originals": "media",
    "heavy_blobs": "blobs",
    "wp_config_defines": "ported_defines",
    "plugins_deactivate": "plugin_preservation",
    "object_cache": "object_cache",
    "mail": "mail",
    "cron": "cron",
    "deletion_mirroring": "deletion_mirroring",
}

# The mail modes that pin the decision at the saved layer; "risk_adaptive" is the
# absence of a pin — it defers to the live mass-send valve every run.
MAIL_RISK_ADAPTIVE = "risk_adaptive"


class ResolveError(Exception):
    """Raised when the envelope is malformed — not an object, missing a required
    section, carrying a field of the wrong type, or an upstream document whose
    inner shape a live derivation cannot read. The CLI turns this into a loud
    non-zero exit rather than emitting a partial plan."""


@dataclass(frozen=True)
class Context:
    """The resolved run state every layer reads from: the two upstream documents,
    the skill shaping the decision list, the saved plan, the this-run answers, the
    flag pins, and whether ``--yes`` suppresses the answer layer."""

    discovery: dict[str, Any]
    classifications: dict[str, Any]
    skill: str
    saved_plan: dict[str, Any] | None
    answers: dict[str, Any]
    pins: dict[str, Any]
    yes_mode: bool


@dataclass(frozen=True)
class Decision:
    """One entry in the ordered decision list. ``built_in`` is the always-present
    default and ``live`` the optional derivation from the upstream documents; both
    take the context so a value can depend on the skill or production state. A
    ``live`` returning :data:`MISSING` means the site gives nothing to derive and
    the decision falls back to its built-in default."""

    id: str
    skills: frozenset[str]
    built_in: Callable[[Context], Any]
    live: Callable[[Context], Any] | None = None


def const(value: Any) -> Callable[[Context], Any]:
    """Wrap a constant as a layer function, for a decision whose default does not
    depend on the run."""

    return lambda _context: value


# --- Live derivations: a decision's value read from the upstream documents -----


def live_project_name(context: Context) -> Any:
    """The local DDEV project name the classifier derived from the production URL
    — the clone bookend put behind the confirm gate."""

    return context.classifications["project_name"]["name"]


def live_table_content(context: Context) -> Any:
    """The full-data / empty (schema-only) table split the classifier computed.
    A live list, re-derived every run, so it is never persisted."""

    return context.classifications["tables"]


def live_table_prefix(context: Context) -> Any:
    """Production's table prefix, adopted locally so WordPress reads the tables it
    actually imported (platform constraint 12)."""

    return context.discovery["database"]["table_prefix"]


def live_engine_php(context: Context) -> Any:
    """The database flavour and version and the PHP major.minor, pinned to
    production's so the import does not crash on collations (platform constraint
    11)."""

    database = context.discovery["database"]
    return {
        "flavour": database["flavour"],
        "version": database["version"],
        "php_major_minor": context.discovery["environment"]["php_major_minor"],
    }


def live_portable_defines(context: Context) -> Any:
    """The names of the portable wp-config defines offered for porting — names
    only, because their values are re-fetched from live state every run rather
    than carried in the saved plan."""

    return [entry["name"] for entry in context.classifications["defines"]["portable"]]


def live_mail(context: Context) -> Any:
    """The mass-send valve: capture only when discovery found a poised campaign,
    otherwise nothing to derive so mail keeps the real mailer (ADR-0009)."""

    return "capture" if context.discovery["mass_send"]["flip"] else MISSING


def built_in_regeneration(context: Context) -> Any:
    """Thumbnail regeneration defaults to the whole library at clone and the
    metadata-driven delta at pull; ``--regenerate-all`` forces the lot either
    way (ADR-0011)."""

    return "all" if context.skill == CLONE else "delta"


# The ordered decision list. Filtering by skill preserves this order, so it is the
# single source of truth for both the clone and the pull walks and their bookends.
DECISIONS: tuple[Decision, ...] = (
    Decision("project_name", frozenset({CLONE}), const(None), live_project_name),
    Decision("db_table_structure", BOTH, const("all_tables_with_schema")),
    Decision("db_table_content", BOTH, const(None), live_table_content),
    Decision("table_prefix", BOTH, const(None), live_table_prefix),
    Decision("db_engine_php", BOTH, const(None), live_engine_php),
    Decision("media_originals", BOTH, const("include")),
    Decision("generated_thumbnails", BOTH, const("exclude")),
    Decision("sideloaded_files", BOTH, const("include")),
    Decision("heavy_blobs", BOTH, const("exclude")),
    Decision("wp_config_defines", BOTH, const([]), live_portable_defines),
    Decision("plugins_deactivate", frozenset({PULL}), const("preserve")),
    Decision("object_cache", frozenset({PULL}), const("derive")),
    Decision("thumbnail_regeneration", BOTH, built_in_regeneration),
    Decision("mail", BOTH, const("live"), live_mail),
    Decision("cron", BOTH, const("run")),
    Decision("deletion_mirroring", frozenset({PULL}), const("off")),
)


def _object(value: Any, context: str) -> dict[str, Any]:
    """Assert a value is a JSON object, raising :class:`ResolveError` otherwise —
    the boundary check that makes a malformed section fail loud instead of
    crashing on a key the value does not carry."""

    if not isinstance(value, dict):
        raise ResolveError(f"{context}: expected an object, got {type(value).__name__}")
    return value


def _section(envelope: dict[str, Any], key: str) -> dict[str, Any]:
    """Fetch a required object section from the envelope, raising
    :class:`ResolveError` when it is absent or not an object."""

    if key not in envelope:
        raise ResolveError(f"missing required section {key!r}")
    return _object(envelope[key], key)


def saved_layer(decision: Decision, context: Context) -> Any:
    """The saved-config value for a decision, or :data:`MISSING` when the saved
    plan has nothing for it. Mail is special: a saved ``risk_adaptive`` mode is
    the absence of a pin, so it defers to the live valve rather than fixing a
    value that would go stale."""

    key = SAVED_KEYS.get(decision.id)
    if key is None or context.saved_plan is None:
        return MISSING

    # A saved risk-adaptive mail mode does not pin — it re-runs the valve.
    raw = context.saved_plan.get(key, MISSING)
    if decision.id == "mail" and raw == MAIL_RISK_ADAPTIVE:
        return MISSING

    return raw


def resolve_layers(
    built_in: Any, live: Any, saved: Any, answer: Any, pin: Any
) -> tuple[Any, str, Any, str]:
    """Apply the precedence rule to one decision's five candidate values.

    The recommendation the gate presents is the top of built-in < live < saved,
    with a pin above; the resolved value adds the this-run answer between saved
    and the pin — so the answer overrides the recommendation without ever leaking
    back into what the gate showed. ``--yes`` is expressed upstream by passing a
    :data:`MISSING` answer, which is how it stops at the saved-config layer.
    """

    # The recommendation the gate presents, before any this-run answer.
    if pin is not MISSING:
        recommendation, recommendation_source = pin, "flag"
    elif saved is not MISSING:
        recommendation, recommendation_source = saved, "saved"
    elif live is not MISSING:
        recommendation, recommendation_source = live, "live"
    else:
        recommendation, recommendation_source = built_in, "built_in"

    # The resolved value, with the this-run answer layered above saved config.
    if pin is not MISSING:
        value, source = pin, "flag"
    elif answer is not MISSING:
        value, source = answer, "answer"
    elif saved is not MISSING:
        value, source = saved, "saved"
    elif live is not MISSING:
        value, source = live, "live"
    else:
        value, source = built_in, "built_in"

    return recommendation, recommendation_source, value, source


def resolve_decision(decision: Decision, context: Context) -> dict[str, Any]:
    """Resolve one decision to its gate recommendation, resolved value, and source
    layer. The mail decision additionally carries the mass-send findings so its
    gate can lead with the loud, specific warning."""

    # Read the two upstream-derived layers, turning a malformed inner shape (a
    # missing nested key or a wrong-typed section that slipped past the top-level
    # object check) into the loud ResolveError the CLI reports — so the fail-loud
    # contract holds for a malformed document, not just a missing section.
    try:
        live = decision.live(context) if decision.live is not None else MISSING
        findings = context.discovery["mass_send"]["findings"] if decision.id == "mail" else MISSING
    except (KeyError, TypeError) as error:
        raise ResolveError(
            f"decision {decision.id!r}: malformed upstream document ({error})"
        ) from error

    built_in = decision.built_in(context)
    saved = saved_layer(decision, context)
    answer = MISSING if context.yes_mode else context.answers.get(decision.id, MISSING)
    pin = context.pins.get(decision.id, MISSING)

    recommendation, recommendation_source, value, source = resolve_layers(
        built_in, live, saved, answer, pin
    )
    entry = {
        "id": decision.id,
        "recommendation": recommendation,
        "recommendation_source": recommendation_source,
        "value": value,
        "source": source,
    }

    # Surface the mass-send findings on the mail decision — the warning the gate
    # leads with when the valve flips, and the informational note otherwise.
    if findings is not MISSING:
        entry["findings"] = findings

    return entry


def active_decisions(skill: str) -> list[Decision]:
    """The ordered decisions this skill walks — the shared list filtered to the
    skill's bookends, order preserved."""

    return [decision for decision in DECISIONS if skill in decision.skills]


def gate_list(
    decisions: list[Decision],
    pins: dict[str, Any],
    replay: bool,
    yes_mode: bool,
    mail_hazard: bool,
) -> list[str]:
    """The gates the run walks. A saved plan collapses the walk to the single
    replay gate; an unattended run walks none; otherwise the operator walks every
    decision except those a flag already pinned.

    One safety exception overrides the replay collapse: when a saved concrete
    ``live`` mail mode would mask a freshly-poised campaign (``mail_hazard``), the
    mail gate is re-surfaced on top of the replay — including the otherwise-silent
    unattended replay — so the mass-send valve is never quietly defeated and a
    real recipient list is never blasted without a confirmation (ADR-0009)."""

    if replay:
        gates = [] if yes_mode else ["replay"]
        if mail_hazard:
            gates.append("mail")
        return gates
    if yes_mode:
        return []
    return [decision.id for decision in decisions if decision.id not in pins]


def mail_valve_defeated(decisions: list[dict[str, Any]], context: Context) -> bool:
    """Whether a saved concrete mail mode is silently overriding the live mass-send
    valve. True only when discovery found a poised campaign (the valve wants
    capture) yet the mail decision resolves to a live-delivering value from the
    saved layer — the one about-to-fire hazard the valve exists to catch. A
    this-run ``--live-mail`` flag resolves from the flag layer, not the saved one,
    so a deliberate present override is intentionally excluded."""

    if not context.discovery["mass_send"]["flip"]:
        return False

    mail = next(entry for entry in decisions if entry["id"] == "mail")
    return mail["source"] == "saved" and mail["value"] != "capture"


def collect_pins(flags: list[str]) -> dict[str, Any]:
    """Reduce the run's flags to the decisions they pin. A later flag wins over an
    earlier one for the same decision, so a caller passing a contradictory pair
    gets the last word deterministically."""

    pins: dict[str, Any] = {}
    for flag in flags:
        if flag in FLAG_PINS:
            decision_id, value = FLAG_PINS[flag]
            pins[decision_id] = value
    return pins


def resolve(envelope: dict[str, Any]) -> dict[str, Any]:
    """Turn a resolve envelope into the resolved plan: the run mode, whether it
    replays a saved plan, the gate list, and every decision resolved over the
    layered defaults."""

    # Validate the untrusted boundary and read the run's knobs.
    skill = envelope.get("skill", PULL)
    if skill not in BOTH:
        raise ResolveError(f"skill must be one of {sorted(BOTH)}, got {skill!r}")
    flags = envelope.get("flags", [])
    if not isinstance(flags, list):
        raise ResolveError(f"flags must be a list, got {type(flags).__name__}")

    # A present, non-empty saved plan is what puts the run into replay.
    saved_plan = envelope.get("saved_plan")
    if saved_plan is not None:
        saved_plan = _object(saved_plan, "saved_plan")
    replay = bool(saved_plan)

    context = Context(
        discovery=_section(envelope, "discovery"),
        classifications=_section(envelope, "classifications"),
        skill=skill,
        saved_plan=saved_plan,
        answers=_object(envelope.get("answers", {}), "answers"),
        pins=collect_pins(flags),
        yes_mode="--yes" in flags,
    )

    decisions = active_decisions(skill)
    resolved = [resolve_decision(decision, context) for decision in decisions]

    # A replay must not silently deliver live mail into a freshly-poised campaign
    # a saved concrete mode masks — re-surface the mail gate on that collision.
    mail_hazard = replay and mail_valve_defeated(resolved, context)

    return {
        "mode": "yes" if context.yes_mode else "interactive",
        "replay": replay,
        "gates": gate_list(decisions, context.pins, replay, context.yes_mode, mail_hazard),
        "decisions": resolved,
    }


def persisted_value(entry: dict[str, Any]) -> Any:
    """The saved-plan value for one resolved decision. Mail persists its mode, not
    the momentary live/capture outcome: accepting the recommendation (built-in or
    the live valve) stores ``risk_adaptive`` so next run re-evaluates the valve,
    while an explicit live/capture choice is stored as chosen."""

    if entry["id"] == "mail" and entry["source"] in {"built_in", "live"}:
        return MAIL_RISK_ADAPTIVE
    return entry["value"]


def build_saved_plan(
    resolved: dict[str, Any], prior: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Reduce an accepted resolved plan to the saved plan — only the persistable
    decisions, each under its saved-plan key, and never a computed list. Reading
    the result back into :func:`resolve` reproduces the same decisions from the
    saved layer, so the round-trip is an identity.

    A key belonging to a decision this skill does not walk cannot appear in
    ``resolved`` — a pull never carries ``project_name``, so it cannot re-emit the
    clone-only ``target``. To keep the committed plan whole across skills, any
    known saved-plan key the ``prior`` committed plan already settled but this run
    does not produce is carried forward, so a pull re-save never silently strips
    the DDEV ``target`` a preceding clone recorded (docs/spec.md: the saved plan
    records the target DDEV project)."""

    decisions = resolved.get("decisions")
    if not isinstance(decisions, list):
        raise ResolveError("resolved plan must carry a 'decisions' list")

    # Carry forward the known saved-plan keys the prior committed plan settled, so
    # a decision this run does not walk survives the re-save; still only recognised
    # keys, so no stale or computed value can ride in behind them.
    known_keys = set(SAVED_KEYS.values())
    saved: dict[str, Any] = {
        key: value for key, value in (prior or {}).items() if key in known_keys
    }

    # Overwrite with the decisions this run resolved, refreshing every walked
    # decision from live state while the carried-forward inactive ones stand.
    for entry in decisions:
        key = SAVED_KEYS.get(entry["id"])
        if key is not None:
            saved[key] = persisted_value(entry)
    return saved


def run(envelope: Any) -> dict[str, Any]:
    """Dispatch the envelope to its operation and return the result document."""

    envelope = _object(envelope, "input")
    operation = envelope.get("operation", "resolve")

    if operation == "resolve":
        return resolve(envelope)
    if operation == "save":
        prior = envelope.get("saved_plan")
        if prior is not None:
            prior = _object(prior, "saved_plan")
        return build_saved_plan(_object(envelope.get("resolved", {}), "resolved"), prior)
    raise ResolveError(f"unknown operation {operation!r}")


def main() -> int:
    """Read the envelope on stdin, emit the result on stdout, and fail loudly on
    malformed input with a non-zero exit and a stderr diagnostic."""

    raw_text = sys.stdin.read()

    # Parse the input, reporting a malformed payload rather than crashing.
    try:
        envelope = json.loads(raw_text)
    except json.JSONDecodeError as error:
        print(f"resolve_plan: input is not valid JSON: {error}", file=sys.stderr)
        return 1

    # Run the requested operation, turning any contract violation into a loud exit.
    try:
        result = run(envelope)
    except ResolveError as error:
        print(f"resolve_plan: {error}", file=sys.stderr)
        return 1

    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
