---
name: manifest-baseline-diff
description: >
  Fetches production's unfiltered file manifest over `GET /files`,
  scope-filters it locally, and diffs it against a stored baseline — or, with
  no baseline, simply writes it — for the kntnt-wp-skills transfer engine.
  Invoked only by the `clone` and `pull` skills' own orchestration via the Task
  tool — never autonomously. Give it the current baseline (or none) and the
  resolved scope; it returns the emitted manifest's and (when diffing) the diff
  output's scratchpad paths, the diff summary, and its evidence block.
model: haiku
effort: low
---

# manifest-baseline-diff

Read `${CLAUDE_PLUGIN_ROOT}/skills/clone/roles/manifest-baseline-diff.md` and follow it exactly. That file is the whole of your instructions — the task envelope it expects, the steps in order, the evidence block you return, and the rules you may not break — and every relative path it names is resolved against `${CLAUDE_PLUGIN_ROOT}/skills/clone/`.

It lives there rather than here because a harness with no subagents must be able to work through the very same procedure inline, and one procedure can only stay one procedure while it exists in a single file. So nothing of it is restated in this definition: a second copy would be a second thing to keep current, and the stale copy is always the one somebody is reading.
