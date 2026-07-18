# Decision backbone: every decision is a recommendation behind an accept/override gate

Every decision the skill makes is presented as a **recommendation with an accept/override gate** — *"Recommended: exclude the 3.1 GB gallery. Accept? [Y/n]"*. This single shape drives all run modes; even multi-valued decisions (e.g. object-cache: keep / take-prod / none) are expressed as a yes/no gate on their recommendation, where `n` reveals the alternatives. Three speeds run over one ordered decision list — interactive (walk each gate), `--yes` (accept every recommendation, print a full record), and replay (a saved plan collapses interactive to a single "Replay the saved plan? [Y/n]" gate) — rather than three separate mode implementations.

Defaults layer without precedence ceremony: `built-in default < live derivation < saved config < this run's answer` (`--yes` stops at the saved-config layer). The saved config stores **decisions, not computed lists** — the inactive-plugin set and blob list re-derive from live state each run, so nothing goes stale; the config exists mainly to make replay a one-liner.

## Consequences

- Adding a new decision means adding one gate to the ordered list; all three run modes get it for free.
- The AI writes recommendations (e.g. from the blob heuristic) but never decides freely — the gate is the authority.
