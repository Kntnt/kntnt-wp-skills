---
name: discovery-classify
description: >
  Runs the read-only, two-phase production discovery reconstruction and the
  deterministic classification pass for the kntnt-wp-skills transfer engine.
  Invoked only by the `clone` and `pull` skills' own orchestration via the Task
  tool — never autonomously, and never mid-run by anything else. Give it the
  target Extractor endpoint and a reference to the Application Password; it
  returns the canonical discovery document's and classifications' scratchpad
  paths, a one-line summary, and its evidence block.
model: sonnet
effort: low
---

# discovery-classify

Read `${CLAUDE_PLUGIN_ROOT}/skills/clone/roles/discovery-classify.md` and follow it exactly. That file is the whole of your instructions — the task envelope it expects, the steps in order, the evidence block you return, and the rules you may not break — and every relative path it names is resolved against `${CLAUDE_PLUGIN_ROOT}/skills/clone/`.

It lives there rather than here because a harness with no subagents must be able to work through the very same procedure inline, and one procedure can only stay one procedure while it exists in a single file. So nothing of it is restated in this definition: a second copy would be a second thing to keep current, and the stale copy is always the one somebody is reading.
