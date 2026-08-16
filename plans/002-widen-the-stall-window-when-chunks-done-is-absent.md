# Plan 002: Widen the stall window when `chunks_done` is absent

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 947e28b..HEAD -- scripts/poll_extraction.py docs/poll-discipline.md skills/clone/SKILL.md skills/pull/SKILL.md agents/extract-transfer.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `947e28b`, 2026-08-16

## Why this matters

The canonical poll discipline states, at `docs/poll-discipline.md:19`:

> Against an Extractor below API version 6 the field is absent — fall back to
> the coarse counters, **widen the stall window**, and say so in the run's
> output rather than reading an absent field as a stall.

The fallback and the saying-so are implemented. **The widening is not.**
`scripts/poll_extraction.py` has exactly one stall window,
`STALL_WINDOW_SECONDS = 600`, applied unconditionally, with no way for a
caller to change it — no argv, no environment, no second constant.

**This defect has not fired yet, and that is the only reason it is cheap.**
`scripts/poll_extraction.py` is unreleased and absent from the installed
0.6.0 plugin, so no run has ever executed this code. It would first bite on
the next run made with an installed build of this client against an Extractor
below API version 6 — which is exactly the configuration production is in
today.

The mechanism is not hypothetical, though. Production (`safeteam.se`) runs
Extractor 0.4.0, API version 5, where `progress.chunks_done` does not exist.
The remaining counters, `tables_done` and `files_done`, move only when a
*whole* table or a *whole* file finishes. On a 186-table site working through
one large table, they stand still for minutes at a time on a completely
healthy job — this was observed on a real run as `3/186` not moving, and the
recorded field response was to widen the window to 2400 s **by hand**, because
the code offers no other way. With a 600 s window and no `chunks_done`, the
poller returns verdict `stall` and exits 4 on a job that is fine.

So the one poll-discipline rule that exists specifically to protect against an
Extractor *older* than this client is the one rule that was never built. After
this plan, a run against an Extractor below API version 6 detects the absence
of `chunks_done` on its first poll carrying progress and widens its own stall
window from that moment on, saying so once — exactly what the canonical
document already promises.

## Current state

### The single window, and the two places it is used

`scripts/poll_extraction.py:45-54` — the pinned discipline literals:

```python
# The seven pinned poll-discipline literals (ADR-0018). Move them; do not
# invent new ones. Preflight and bootstrap pass their budget as argv; the
# main extraction omits it.
POLL_CADENCE_SECONDS = 15
PER_REQUEST_TIMEOUT_SECONDS = 120
BACKOFF_FIRST_SECONDS = 30
BACKOFF_SECOND_SECONDS = 60
STALL_WINDOW_SECONDS = 600
PREFLIGHT_BUDGET_SECONDS = 600
BOOTSTRAP_BUDGET_SECONDS = 900
```

`scripts/poll_extraction.py:360-371` — the stall check, inside the `while True`
loop in `poll()`:

```python
        # Stop when nothing has advanced inside the stall window.
        last_at = loop.advance.at if loop.advance.at is not None else started
        if clock.now() - last_at >= STALL_WINDOW_SECONDS:
            return give_up(
                "stall",
                STALL_WINDOW_SECONDS // 60,
                {
                    "job_id": job_id,
                    "job_state": loop.advance.state,
                    "progress": loop.advance.progress,
                },
            )
```

Note that `give_up`'s second argument is the minutes reported in the log line
`gave up after N minutes` and in the result's
`inferred.gave_up_after_minutes`. It is derived from the window, so widening
the window must widen that number too — the log line must not claim 10
minutes after waiting 40.

### The absence is already detected — this plan only acts on it

`scripts/poll_extraction.py:464-471`, immediately after a successful poll:

```python
        state, chunks, coarse, saw_progress = _progress_signature(payload)
        if saw_progress and chunks is None:
            if not loop.advance.chunks_done_absent:
                _log(
                    stream,
                    "chunks_done absent; stall detection falls back to coarse counters",
                )
            loop.advance.chunks_done_absent = True
```

`loop.advance.chunks_done_absent` is a `bool` on the `_Advance` dataclass
(`scripts/poll_extraction.py:135-145`) that already survives every reassignment
of `loop.advance` (it is threaded through explicitly at
`scripts/poll_extraction.py:481`). It is already reported in every result via
`_result(..., chunks_done_absent=...)` (`scripts/poll_extraction.py:265-283`).

**This is the signal to gate on — not the API version number.** Observed
absence of the field is strictly better than a version comparison: it is
correct against any Extractor, needs no new plumbing, and cannot disagree with
reality. This plan therefore adds no version awareness at all.

`_progress_signature` (`scripts/poll_extraction.py:213-233`) is what produces
`chunks` and `saw_progress`; read it, but do not change it.

### Where the number 2400 comes from

Not invented here. `~/Projects/kntnt-transfer-engine-open-work.md` records it
as the value a live production run was manually widened to, against exactly
this Extractor version and exactly this symptom, and the run then completed.
The repo's own rule is to measure before picking a constant; this is the
measurement there is. Both SKILL files already narrate the incident — see
`skills/clone/SKILL.md:115` and `skills/pull/SKILL.md:113`: *"observed as
`3/186` standing still for minutes on a healthy run, and worked around by
widening the stall window to 2400 s"*.

### The consistency binding you must extend

`docs/poll-discipline.md` is the canonical statement, and
`tests/test_poll_discipline_consistency.py` reads its pinned phrases and
asserts they match the script's constants. Three surfaces must carry every
pinned phrase verbatim: `skills/clone/SKILL.md` §5, `skills/pull/SKILL.md` §5,
and `agents/extract-transfer.md`.

`tests/test_poll_discipline_consistency.py:76-84`:

```python
SCRIPT_BOUND_PHRASES: tuple[tuple[str, str], ...] = (
    ("poll cadence", f"every {pe.POLL_CADENCE_SECONDS} s"),
    (
        "per-request timeout",
        f"{pe.PER_REQUEST_TIMEOUT_SECONDS} s per-request timeout",
    ),
    ("stall window", "10-minute stall window"),
)
```

Two of the three phrases are derived from the script's constants; the stall
window's is a hard-coded string that merely happens to agree with
`STALL_WINDOW_SECONDS`. Step 5 fixes that while adding the second phrase.

### Repo conventions you must match

- `scripts/poll_extraction.py` is a `uv` inline-metadata script with no
  dependencies. Keep it that way.
- **Comment style** (`agents.d/coding-standard/general.md`): paragraphs of
  related lines, a `#` comment above each stating that block's *purpose*.
  See the existing comments inside `poll()` for the register.
- Docstrings on every function, saying why.
- The loop is tested with an injected `Clock` and an injected `fetch` — never
  real time, never real network. See `tests/test_poll_extraction.py`.
- British English in prose. Markdown prose stays on one physical line per
  paragraph; never hard-wrap at a column width.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full test suite | `uvx pytest -q` | exit 0, `942 passed` before your change; more after |
| The poll tests | `uvx pytest -q tests/test_poll_extraction.py tests/test_poll_discipline_consistency.py` | exit 0 |
| Lint (touched files only) | `uvx ruff check scripts/poll_extraction.py tests/test_poll_extraction.py tests/test_poll_discipline_consistency.py` | exit 0 |

Run these from the repository root, `/Users/thomas/Projects/kntnt-wp-skills`.
**Do not run `uvx ruff check .`** — it reports pre-existing findings that are
not yours.

## Scope

**In scope**:

- `scripts/poll_extraction.py` (modify)
- `tests/test_poll_extraction.py` (modify — add cases)
- `tests/test_poll_discipline_consistency.py` (modify — extend the binding)
- `docs/poll-discipline.md` (modify — the rule and a new pinned phrase)
- `skills/clone/SKILL.md`, `skills/pull/SKILL.md`, `agents/extract-transfer.md`
  (modify — carry the new pinned phrase)
- `docs/adr/0018-poll-discipline-and-two-chunk-preflight.md` (modify — record
  the second window under its consequences)
- `CHANGELOG.md` (modify)

**Out of scope** (do NOT touch, even though they look related):

- Anything to do with budgets, halving, the attempt counter, or a floor on
  chunk sizes. That family is frozen pending a measurement that has not been
  taken; adding to it is explicitly forbidden by the work queue's rule R1.
  This plan touches only the *client's* stall detection, which is not in that
  family.
- `PREFLIGHT_BUDGET_SECONDS` and `BOOTSTRAP_BUDGET_SECONDS`. Those loops pass
  an overall budget as argv and stop on it; widening a stall window inside a
  bounded loop cannot extend it past its own budget, and neither number
  changes.
- `_progress_signature` and `_has_advanced`. The detection they perform is
  correct; this plan acts on the result, it does not change the detection.
- Adding an `--stall-window` CLI flag. The discipline's whole point is that
  the literals live in the script so an agent cannot re-derive them per run
  (`docs/poll-discipline.md`, *How the loop is executed*). A flag would hand
  the number back to the agent. Do not add one.
- Any Extractor-side change, and any use of `api_version`.

## Git workflow

- Trunk-based: commit straight to `main`. No branch, no PR.
- Message style (from `git log --oneline`): one imperative sentence, no
  prefix. Example from this repo:
  `Start the poll stall clock from loop start when no poll has succeeded`.
- Do NOT push and do NOT tag.

## Steps

### Step 1: Add the second window constant

In `scripts/poll_extraction.py`, add a constant beside the existing pinned
literals (the block at lines 45-54):

```python
COARSE_STALL_WINDOW_SECONDS = 2400
```

The literal block's own comment says "The seven pinned poll-discipline
literals ... Move them; do not invent new ones." Update that comment to say
eight, and extend the paragraph to explain the new one's purpose in the file's
own register: the wider window that applies once `chunks_done` is observed
absent, because the coarse counters move only when a whole table or file
finishes and therefore stand still for minutes on a healthy job; and that 2400
is the value a live production run against an API-version-5 Extractor was
manually widened to before it completed, not a guess.

**Verify**: `uvx pytest -q` → exit 0 (nothing consumes the constant yet).

### Step 2: Apply the window the loop is actually under

In `poll()`, add a small helper *inside* the function, next to the existing
`wall()` and `remaining()` closures (`scripts/poll_extraction.py:327-333`),
that returns the window in force:

```python
    def stall_window() -> int:
        """The stall window this loop is under: widened once ``chunks_done`` is
        observed absent, because the coarse counters alone stand still for
        minutes on a healthy job slicing one large table."""

        if loop.advance.chunks_done_absent:
            return COARSE_STALL_WINDOW_SECONDS
        return STALL_WINDOW_SECONDS
```

Then change the stall check (`scripts/poll_extraction.py:360-371`) to call it
**once per iteration** and use that one value for both the comparison and the
reported minutes:

```python
        # Stop when nothing has advanced inside the stall window — widened once
        # chunks_done is known absent, so a coarse-counter job is not read as
        # stalled while it is slicing one large table.
        window = stall_window()
        last_at = loop.advance.at if loop.advance.at is not None else started
        if clock.now() - last_at >= window:
            return give_up(
                "stall",
                window // 60,
                {
                    "job_id": job_id,
                    "job_state": loop.advance.state,
                    "progress": loop.advance.progress,
                },
            )
```

Read the value into `window` once rather than calling `stall_window()` twice —
the comparison and the reported minutes must never come from different values.

**Verify**: `uvx pytest -q tests/test_poll_extraction.py` → exit 0. The
existing tests all exercise the `chunks_done`-present path or short windows,
so none of them should change behaviour. If any existing test fails, that is
a STOP condition.

### Step 3: Extend the log line so the widening is visible

The rule says "say so in the run's output". Today the log says only that the
fallback happened. Amend the existing message at
`scripts/poll_extraction.py:466-471` so it also names the new window — the
operator watching stderr must be able to tell a 40-minute wait from a hang.

Target shape (keep the existing leading clause verbatim, since it is the
sentence operators and the agent definitions already recognise):

```python
                    "chunks_done absent; stall detection falls back to coarse "
                    f"counters and the stall window widens to "
                    f"{COARSE_STALL_WINDOW_SECONDS // 60} minutes",
```

It is still logged exactly once, on the first poll that observes the absence —
do not move it out of the `if not loop.advance.chunks_done_absent:` guard.

**Verify**: `uvx pytest -q tests/test_poll_extraction.py` → exit 0.

### Step 4: Add the tests

Model them on the existing loop tests in `tests/test_poll_extraction.py` —
read that file first and reuse its fake clock and fake `fetch`, its naming,
and its assertion style. Do not introduce a new test harness.

Add four cases:

1. **A job with `chunks_done` present and no advance for just over 600 s
   returns verdict `stall`.** The unchanged path, pinned so this plan cannot
   silently widen the normal window.
2. **A job whose polls carry `progress` without `chunks_done`, and no advance
   for 700 s, is still polling — not `stall`.** This is the regression the
   plan exists for: under the old code it aborted here.
3. **The same job, with no advance for just over 2400 s, returns verdict
   `stall`, and the result's `inferred.gave_up_after_minutes` is 40** (not
   10). This is what step 2's single-`window` read protects.
4. **The result's `inferred.chunks_done_absent` is `True` in case 3 and
   `False` in case 1.** The evidence block must let a reader tell which window
   was in force after the fact.

One ordering subtlety to get right in cases 2 and 3: the absence is only
observed on a poll that *carries* `progress`. A job still `queued` carries no
counters (`_progress_signature` returns `saw_progress=False`), so the narrow
window is correctly in force until the first progress-bearing poll. Build the
fixtures so at least one progress-bearing poll happens before the clock is
advanced, and assert nothing about the pre-progress phase.

**Verify**: `uvx pytest -q tests/test_poll_extraction.py` → exit 0, four more
tests than before.

### Step 5: Extend the canonical document and its binding

**`docs/poll-discipline.md`:**

- In *The discipline* → *What counts as an advance*
  (`docs/poll-discipline.md:19`), replace the unquantified "widen the stall
  window" with the actual number and its provenance: the window widens to 40
  minutes once `chunks_done` is observed absent, because the coarse counters
  stand still for minutes on a healthy job, and 40 minutes is the value a live
  production run against an API-version-5 Extractor was widened to before it
  completed.
- In *Terminal conditions* (`docs/poll-discipline.md:21`), state both windows
  rather than only the 10-minute one.
- Under *Pinned phrases — every surface stating the discipline in full*, add a
  new subsection beside the existing `### stall window`, following its exact
  format (a `###` heading, then a fenced `text` block containing only the
  phrase):

```
### coarse stall window

```text
40-minute stall window
```
```

**`tests/test_poll_discipline_consistency.py`:** extend `SCRIPT_BOUND_PHRASES`
(lines 76-84) with the new phrase, and — while you are there — derive **both**
window phrases from the script's constants instead of hard-coding the
10-minute string:

```python
SCRIPT_BOUND_PHRASES: tuple[tuple[str, str], ...] = (
    ("poll cadence", f"every {pe.POLL_CADENCE_SECONDS} s"),
    (
        "per-request timeout",
        f"{pe.PER_REQUEST_TIMEOUT_SECONDS} s per-request timeout",
    ),
    ("stall window", f"{pe.STALL_WINDOW_SECONDS // 60}-minute stall window"),
    (
        "coarse stall window",
        f"{pe.COARSE_STALL_WINDOW_SECONDS // 60}-minute stall window",
    ),
)
```

**Verify**: `uvx pytest -q tests/test_poll_discipline_consistency.py` → this
will FAIL, reporting that the three full-discipline surfaces do not carry the
new pinned phrase. That failure is expected; step 6 resolves it. If it fails
for any *other* reason, that is a STOP condition.

### Step 6: Carry the new rule into the three full-discipline surfaces

`skills/clone/SKILL.md` §5, `skills/pull/SKILL.md` §5, and
`agents/extract-transfer.md` each restate the discipline in full, because a
surface loaded on its own must carry the whole rule set. All three already
contain a sentence about falling back to the coarse counters below API version
6 — in the SKILLs it is in the long `**Poll**` paragraph (`skills/clone/SKILL.md:115`,
`skills/pull/SKILL.md:113`), ending *"fall back to the two coarse counters and
widen the stall window instead, and say in the run's output that you did."*

Amend that sentence in each of the three files so it names the widened window
and carries the pinned phrase `40-minute stall window` verbatim. The narrative
around the phrase is each surface's own voice — a SKILL explaining the rule to
an orchestrator and an agent definition instructing a subagent legitimately
read differently — but the phrase itself must appear exactly.

Keep every other pinned phrase in those paragraphs untouched, including
`10-minute stall window`, which still states the normal window and is still
asserted.

**Verify**: `uvx pytest -q` → exit 0, and the count is 4 higher than the 942
you started from.

### Step 7: Pay the documentation round

1. **`docs/adr/0018-poll-discipline-and-two-chunk-preflight.md`** — add the
   second window to its consequences. Read the ADR fully first and match its
   voice. Say what it is, why it is gated on the *observed* absence of the
   field rather than on the API version (the observation is correct against
   any Extractor and needs no new plumbing), and that 40 minutes is a measured
   field value, not a chosen one. Do not rewrite the ADR's decision — the
   discipline it settled is unchanged; this is the missing half of a rule it
   already implies.
2. **`CHANGELOG.md`** — an entry under `## [Unreleased]` → `### Fixed`,
   matching the register of the entries already there: name the concrete
   failure (a healthy job against an API-version-5 Extractor aborted as a
   false stall because the coarse counters stand still while one large table
   is sliced), what changed, and the ADR link. Do not create a version heading
   and do not bump any version.

There is no `docs/spec.md` or `CONTEXT.md` change here — the discipline's home
is `docs/poll-discipline.md` and the spec defers to it.

**Verify**: `uvx pytest -q` → exit 0, and
`uvx ruff check scripts/poll_extraction.py tests/test_poll_extraction.py tests/test_poll_discipline_consistency.py`
→ exit 0.

## Test plan

Four new cases, specified in step 4 with their exact assertions. The two that
carry the most weight:

- **Case 2** (no `chunks_done`, 700 s of no advance, still polling) is the
  regression this whole plan exists to prevent. If only one test survives, it
  is this one.
- **Case 3's `gave_up_after_minutes == 40`** catches the subtle half of the
  bug: an implementation that widens the comparison but leaves
  `STALL_WINDOW_SECONDS // 60` in the `give_up` call waits 40 minutes and then
  reports having waited 10, which is worse than either behaviour alone,
  because the operator's log then contradicts the clock.

Structural pattern to follow: the existing loop tests in
`tests/test_poll_extraction.py`, with their injected clock and injected
`fetch`. No test may sleep or touch the network.

Verification: `uvx pytest -q` → exit 0, count ≥ 946.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `uvx pytest -q` exits 0 and reports at least 946 passed
- [ ] `uvx ruff check scripts/poll_extraction.py tests/test_poll_extraction.py tests/test_poll_discipline_consistency.py` exits 0
- [ ] `grep -c 'COARSE_STALL_WINDOW_SECONDS' scripts/poll_extraction.py` returns at least 3
- [ ] `grep -l '40-minute stall window' skills/clone/SKILL.md skills/pull/SKILL.md agents/extract-transfer.md docs/poll-discipline.md` lists all four files
- [ ] `grep -c '10-minute stall window' docs/poll-discipline.md` is still at least 1 (the normal window's phrase was not replaced)
- [ ] `grep -n 'STALL_WINDOW_SECONDS //' scripts/poll_extraction.py` returns no match inside the `give_up` call for the stall verdict — the reported minutes come from `window`
- [ ] `git status --short` lists only files from the "In scope" list
- [ ] `plans/README.md` status row for 002 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows `scripts/poll_extraction.py` changed since `947e28b`
  and the excerpts above no longer match.
- Any **existing** test in `tests/test_poll_extraction.py` fails after step 2
  or step 3. Something depended on the single unconditional window, and that
  dependency needs a decision.
- `tests/test_poll_discipline_consistency.py` fails after step 5 for a reason
  other than the three surfaces missing the new phrase.
- You find that `loop.advance.chunks_done_absent` does **not** survive the
  reassignment of `loop.advance` at `scripts/poll_extraction.py:474-483` — the
  whole design assumes it is sticky once set.
- You conclude the fix needs the Extractor's `api_version`. It does not; if
  the observed-absence signal seems insufficient, report why rather than
  reaching for version plumbing (that question is plan 003's).

## Maintenance notes

- **What a reviewer must scrutinise**: that the comparison and the reported
  minutes come from the *same* read of `stall_window()`, and that the
  10-minute path is genuinely unchanged when `chunks_done` is present.
- **What will interact with this**: the moment production is upgraded to an
  Extractor at API version 6 or above, this widening stops engaging entirely
  and the run reverts to the 10-minute window. That is correct and intended —
  but it means the widened path will be exercised rarely once the pending
  coordinated release lands, so its tests are the only thing keeping it
  honest. Do not delete them as dead weight.
- **Deliberately not done here**: no CLI flag, no environment override, and no
  version-derived window. The number stays in the script, which is the whole
  reason `scripts/poll_extraction.py` exists.
- **Related but separate**: the widened window makes a genuine hang take up to
  40 minutes to notice on an older Extractor. That is the honest cost of not
  having `chunks_done`, and it is strictly better than aborting healthy runs;
  the real fix is production running an Extractor at API version 6, which is
  a release-and-install matter, not a code one.
