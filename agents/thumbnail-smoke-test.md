---
name: thumbnail-smoke-test
description: >
  Regenerates thumbnails, rebuilds the local search index, and runs the
  finished copy's deterministic post-clone/pull smoke test for the
  kntnt-wp-skills transfer engine, swallowing the WP-CLI progress and warning
  spam all three produce. Invoked only by the `clone` and `pull` skills' own
  orchestration via the Task tool — never autonomously. Give it the
  regeneration scope, the reindex plugin family (if any), and/or the
  assembled expectations object; it returns only genuine anomalies and its
  evidence block.
model: haiku
effort: low
---

# thumbnail-smoke-test

Read `${CLAUDE_PLUGIN_ROOT}/skills/clone/roles/thumbnail-smoke-test.md` and follow it exactly. That file is the whole of your instructions — the task envelope it expects, the steps in order, the evidence block you return, and the rules you may not break — and every relative path it names is resolved against `${CLAUDE_PLUGIN_ROOT}/skills/clone/`.

It lives there rather than here because a harness with no subagents must be able to work through the very same procedure inline, and one procedure can only stay one procedure while it exists in a single file. So nothing of it is restated in this definition: a second copy would be a second thing to keep current, and the stale copy is always the one somebody is reading.
