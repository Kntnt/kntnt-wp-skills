# The orchestrator owns the main extraction's poll

The main extraction is the one wait in this engine with no overall wall-clock budget: it runs for hours and the stall window is the only thing that stops it ([ADR-0018](./0018-poll-discipline-and-two-chunk-preflight.md)). Until now a single subagent, `extract-transfer`, owned the whole span — submit, poll, download, unseal, consume — and its definition told it, in as many words, to wait inside one blocking `poll_extraction.py` invocation and return exactly once with a verdict.

On **both** production runs of this engine it returned without one. On 2026-08-19 it returned with the words *"I'll pause here and wait for the background task notification when the poll reaches a terminal verdict"* — no evidence block, no `DONE`/`FAILED` — and it had already written a launcher script and started the poll **detached** before returning. When the subagent's process tree was reaped the poll went with it: the redirect target was 0 bytes, no exit-code line was ever written, and the job on production carried on to 13,459 files with nobody watching. The written close-out for a verdict-less return is `DELETE`. The run survived only because the orchestrator, contrary to its own instructions, queried `GET /extractions/{id}` by hand, saw `state: running` with `chunks_done` climbing, killed the orphan, and restarted the poll under its own tracked background job. That run then completed: 48,578 files in 3 h 28 m.

The instruction was not the problem. Nothing structurally prevented the agent from backgrounding a long wait and returning, and an agent that does so is behaving reasonably by its own lights — a multi-hour blocking wait is exactly the shape a model is inclined to escape. Asking more firmly had already failed twice, under two different wordings.

## Decision

**The main extraction's poll belongs to the orchestrating skill, not to any role.** The phase is split at the poll boundary into three owners:

1. **Submit** — the `extract-submit` role. One `POST /extractions`, the one corrected resubmission a restricted-path refusal allows ([ADR-0024](./0024-a-restricted-path-refusal-drops-the-named-paths-and-resubmits-once.md)), and the accepted job written to `<scratchpad>/extract-job.json`: the job id, the selection exactly as submitted, and any `skipped_files`. Short, bounded, verdict-shaped. It never waits for the job.
2. **Poll** — `skills/clone/SKILL.md` §5 and `skills/pull/SKILL.md` §5, running `poll_extraction.py` as the orchestrator's own tracked background job. Nothing is delegated across the multi-hour boundary, so nothing can be orphaned by a return.
3. **Download, unseal, consume** — the `extract-transfer` role, entered on a job already `ready`. It reads the submitted selection back from the job record, confirms the state in one `GET /extractions/{id}`, and never starts a wait of its own.

**The job id reaches disk before the poll begins.** That single line is what makes a lost poller a re-poll rather than a lost run: polling is read-only, so re-attaching to a job whose id you have costs nothing, and the orchestrator can always run the identical command again.

**A poll's output and its exit code are captured to files.** Stdout is redirected to `<scratchpad>/extract-poll.json` and the helper's exit status written to `<scratchpad>/extract-poll.exit`, beside the progress log `--log` already produced. The helper prints its verdict only at the end, so the JSON file is zero bytes for the whole run and proves nothing by itself; the exit-code file is the discriminator, and its absence means the poll died rather than answered — which says nothing whatever about the job, and is recovered by re-attaching rather than by closing anything out.

**`scripts/poll_extraction.py` is unchanged.** What moved is who invokes it. Its constants, its stall window and its cadence are a separate question with its own evidence, and none of it was touched here.

## Rejected alternatives

- **State the rule more firmly in the agent definition.** This is the third wording, and the second two both failed in production. A boundary a model can cross cheaply will eventually be crossed; the generalisable fix is to move the boundary, not to reinforce the prose in front of it.
- **Let the subagent detach the poll deliberately, and have the orchestrator adopt it.** The orchestrator has no channel to a process it did not start, which is exactly how the 2026-08-19 poll reached a verdict that reached nobody. Adoption would need a supervisor this engine does not have.
- **Keep one role and give the poll a wall-clock budget short enough to fit inside a subagent's life.** A constant cannot be right here: a 3600 s cap had already expired on a healthy, visibly-advancing job at less than a quarter of the file phase, which is why the main extraction has no overall budget at all.
- **Have the orchestrator poll one tool call at a time.** The failure this replaces is the mirror image of the one `discovery-classify` hit — hours of round trips through the context that can least afford them. The helper exists precisely so a long wait costs one call.

## What this does not fix

- **It does not make the extraction itself more reliable.** The server was fine on both occasions; this is entirely about who watches it.
- **It does not remove the need for the close-out's state precedence** ([ADR-0022](./0022-close-the-exposure-window-on-every-failure-path.md)). A role can still return without a verdict for other reasons, and the orchestrator still needs a rule for what to believe. The two are complementary: that one is the guard, this one removes the situation it guards against.
- **It does not address `thumbnail-smoke-test` returning `FAILED` on findings that are not failures** — a related but separate confusion of "the command exited non-zero" with "the clone is wrong".
- **It does not touch the poll discipline's constants.** In particular, the 10-minute stall window is close to the measured watchdog cadence of the one production host there are numbers for, so the helper can report a `stall` on a job that is measurably advancing. Whether that window should move is a question to answer from measurement, not by picking a new number.

## Consequences

- The plugin ships five subagents rather than four, and both `SKILL.md` files carry a literal poll command where they previously described one. The phase costs one extra delegation round trip per run — seconds against hours.
- The selection no longer lives in the memory of the role that unseals it. `extract-submit` records it as submitted, `extract-transfer` reads it back, and the two are reconciled through a file with a SHA256 rather than through an agent's recollection — which also keeps tens of thousands of paths off every agent boundary.
- A harness with no background jobs runs the identical command in the foreground and blocks on it. What may never happen is that the process waiting on the job belongs to something that can be reaped out from under it.
- `tests/test_orchestrator_owns_the_long_poll.py` binds the split structurally: a role file may invoke the poll helper only with an overall budget on its argv — the helper's optional third positional, which the main extraction is the sole caller to omit — so the budget-less multi-hour wait cannot be written back into a role without reddening the suite.
