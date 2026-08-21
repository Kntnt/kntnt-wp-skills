---
name: extract-submit
description: >
  Submits the main extraction to the Kntnt Extractor plugin and writes the job
  it created to the run's scratchpad, for the kntnt-wp-skills transfer engine.
  It never waits for the job — the orchestrating skill owns that poll. Invoked
  only by the `clone` and `pull` skills' own orchestration via the Task tool —
  never autonomously. Give it the resolved selection and the run's ephemeral
  public key; it returns the job id, the job record's scratchpad path, and its
  evidence block.
model: sonnet
effort: low
---

# extract-submit

Read `${CLAUDE_PLUGIN_ROOT}/skills/clone/roles/extract-submit.md` and follow it exactly. That file is the whole of your instructions — the task envelope it expects, the steps in order, the evidence block you return, and the rules you may not break — and every relative path it names is resolved against `${CLAUDE_PLUGIN_ROOT}/skills/clone/`.

It lives there rather than here because a harness with no subagents must be able to work through the very same procedure inline, and one procedure can only stay one procedure while it exists in a single file. So nothing of it is restated in this definition: a second copy would be a second thing to keep current, and the stale copy is always the one somebody is reading.
