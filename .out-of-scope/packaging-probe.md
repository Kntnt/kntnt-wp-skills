# Packaging probe — measuring a host's file-part budget from the client

This client does not ship a tool that measures a host's file-part budget. The budget is a settled per-site number, resolved through the ordinary decision backbone (built-in `262144`, overridden by the saved plan's `chunk_size` key), and an operator who needs a different one measures it by hand and writes it down.

## Why this is out of scope

The idea was to package a real file at one or more candidate sizes before or after discovery, so that a host whose packaging ceiling differs from the measured one surfaces in minutes rather than hours into a run. It was sketched during chunking work and parked twice, each time with a written trigger. Both triggers have since fired and the idea got *smaller* each time, not larger. That is the tell.

**The hazard it was built to catch no longer exists.** Its force came from one specific failure: a production run died at 97.8 % after six hours because the host packaged at a budget nobody had chosen, and no endpoint reported what that budget was. Three changes closed that off:

- The built-in default is now `262144` — the one value measured to complete a real clone end to end.
- The client sends `chunk_size` on the main extraction's create, whether or not the host's `honours` list names it. The run no longer inherits whatever production happens to be configured for; the client took that decision back.
- The Extractor's stall adaptation halves *downward from the caller's number*. An oversized request calibrates itself at the cost of attempt windows rather than the run, so overshooting is recoverable — which is precisely the outcome a probe existed to prevent.

What is left is fine-tuning for a host whose ceiling differs from the measured one. That is a real thing, and it is not worth what it costs.

**The cost is a full documentation round.** A new helper is a change of substance under `AGENTS.md`'s R3: `CHANGELOG.md`, a `CONTEXT.md` glossary term, `docs/spec.md`, and an ADR. The ADR is not optional here, because the probe brushes two settled decisions and must record why it leaves them standing:

- [ADR-0018](../docs/adr/0018-poll-discipline-and-two-chunk-preflight.md) Decision 2 pins the download preflight to *exactly* two structure-only tables and **no files**, specifically so that size is irrelevant to it. `tests/test_preflight_probe_consistency.py` binds that wording across four surfaces. Packaging a real file in the preflight supersedes that decision rather than extending it.
- [ADR-0013](../docs/adr/0013-minimal-flag-surface.md) cut the fine-grained flag surface and recorded the cut so it would not be "helpfully" re-proposed. That rules out a flag as the delivery vehicle.

There is also a sequencing defect in the idea as originally filed: it placed the probe in the preflight, measuring "the largest file in the resolved selection". The preflight is health-check step 4; the resolved selection does not exist until after discovery. The input is not available at the point of use, so the probe would have to move out of the preflight anyway — at which point it is a `scripts/` helper an operator runs deliberately.

**The value does not cover that.** The manual method already works and costs about two minutes per point now that `chunk_size` is accepted on the create payload: submit a single-file extraction at a candidate size and read the resulting **part count** to confirm the size was in force. In both the manual and the automated case the output is a number the operator types into `.kntnt-wp-skills.json` by hand. Automating the measurement does not automate the decision, and the decision is the part that needs a person.

And the measurement was never where the run's time went. The production run's dominant cost was roughly 229 ms per ordinary small file, which no value of this setting touches.

## What must not be lost

Two pieces of framing outlive the rejection and belong to whatever touches this area next.

**A fast probe is not a promise.** The download preflight passed in 0–9 seconds against a host that then failed the main extraction twice. That is why the preflight carries a warning paragraph at all. Anything that reports quickly about packaging reports about one file at one size — the existing "a fast preflight is not a promise" language stays regardless.

**Every figure in this area comes from one host and one file, with nothing below 256 KB tested.** Per-part cost grew about twice as fast as the part up to 2 MiB and then jumped roughly 26× between 2 and 4 MiB: 256 KB packaged a 36 MB file in 85 s; 4 MiB did not finish it in twelve minutes. The record is `docs/measurements/2026-08-19-chunk-size-curve.md` in the Extractor repository — read its "What this does not establish" section before quoting any of those numbers.

**Nothing server-side bounds `chunk_size` from above.** `POST /extractions` accepts an integer of at least 1, unbounded, derived from `Artifact_Builder::configured()`'s own `max( 1, … )`. A per-job value beats both the site constant and its filter. The client is therefore the only thing that can keep a request sane — but since the adaptation halves down from it, the cost of a bad request is attempt windows, not the run.

## What would reopen this

Not a new opinion about tuning — a change in the population. If this client acquires hosts whose packaging ceilings genuinely differ from each other, so that "measure this host" becomes a recurring operation rather than a one-off, the arithmetic changes and the helper starts paying for its documentation round. Until then, measuring by hand is the right instrument.

## Prior requests

- #63 — "A packaging probe for tuning a host's file-part budget — re-scoped out of the preflight"
