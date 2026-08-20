---
name: extract-transfer
description: >
  Downloads and unseals the sealed container of an extraction the orchestrating
  skill has already polled to `ready`, and consumes the remote job, for the
  kntnt-wp-skills transfer engine. It never submits a job and never waits for
  one. Invoked only by the `clone` and `pull` skills' own orchestration via the
  Task tool — never autonomously. Give it the job id, the job record
  `extract-submit` wrote, and the run's ephemeral private key; it returns the
  reassembled dump's and unsealed files' scratchpad paths and its evidence
  block.
model: sonnet
effort: medium
---

# extract-transfer

Read `${CLAUDE_PLUGIN_ROOT}/skills/clone/roles/extract-transfer.md` and follow it exactly. That file is the whole of your instructions — the task envelope it expects, the steps in order, the evidence block you return, and the rules you may not break — and every relative path it names is resolved against `${CLAUDE_PLUGIN_ROOT}/skills/clone/`.

It lives there rather than here because a harness with no subagents must be able to work through the very same procedure inline, and one procedure can only stay one procedure while it exists in a single file. So nothing of it is restated in this definition: a second copy would be a second thing to keep current, and the stale copy is always the one somebody is reading.
