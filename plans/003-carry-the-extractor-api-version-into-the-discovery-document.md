# Plan 003: Carry the Extractor's API version into the discovery document and report what it degrades

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 947e28b..HEAD -- scripts/discovery.py skills/clone/SKILL.md skills/pull/SKILL.md agents/discovery-classify.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (independent of plans 001 and 002)
- **Category**: bug
- **Planned at**: commit `947e28b`, 2026-08-16

## Why this matters

The client's protection against version skew is asymmetric. Against an
Extractor **newer** than this client, the verified ceiling stops the run
outright — a deliberate, well-bound mechanism with its own consistency suite.
Against an Extractor **older** than this client, there are three ad-hoc
handlings, each decided separately, and no mechanism at all:

- below API version 4, the identity report is absent → a documented
  discriminating-test fallback, correctly implemented;
- below API version 6, `progress.chunks_done` is absent → a documented
  widening of the stall window that was **never implemented** (plan 002);
- below the version that added it, `strict: false` is silently ignored → a
  deliberate degradation to the old hard-fail behaviour, recorded in
  `CHANGELOG.md`, safe but **never reported to the operator**.

Production runs API version 5, so two of the three are live on every run
against it today. The operator is told none of it.

The root cause is one line of plumbing that does not exist: **the API version
is observed once in the health check and then discarded.** No artifact carries
it, so no later step can gate on it, report it, or even mention it. Confirm it
yourself before starting:

```
grep -rn "api_version" scripts/
```

returns nothing. Not one helper script has ever seen the number.

This plan does the plumbing and the reporting. It deliberately does **not**
raise the floor — see "Out of scope".

## Current state

### The version is read here, and goes nowhere

`skills/clone/SKILL.md:63` and `skills/pull/SKILL.md:64`, in the health
check's **Production** dependency bullet, are where `GET /status` is called
and its `api_version` is compared:

> `GET /status` on the configured Kntnt Extractor endpoint for the target
> production URL, proving it is reachable and reports **Extractor API version
> ≥ 2** ... The floor is only half the check: the skills are also **verified
> against Extractor API version ≤ 6**, and a `GET /status` reporting a higher
> version stops for the operator.

Both bounds are prose, enforced by the orchestrating model reading this
paragraph. `tests/test_api_version_ceiling_consistency.py` binds them, but read
that suite before assuming it does more than it does: every assertion in it is
a regex over a Markdown file, checking that the strings `≥ 2` and `≤ 6` appear
on the surfaces that state the pin. It is a documentation-consistency suite.
No test, and no code, ever compares a number that came off the wire.

After the comparison, the number is dropped. Nothing downstream receives it.

### The document that should carry it

`scripts/discovery.py:495-508`, the head of `build_document`:

```python
def build_document(raw: Any) -> dict[str, Any]:
    """Assemble the canonical discovery document from the four REST-derived
    sections.
    ...
    """

    environment = _require(raw, "environment", dict, "input")
    tables_source = _optional(raw, "tables", dict, {}, "input")
    files = _optional(raw, "files", list, [], "input")
```

The envelope has four sections — `environment`, `tables`, `files`,
`bootstrap` — assembled by the `discovery-classify` subagent and specified in
`skills/clone/SKILL.md:82` and `skills/pull/SKILL.md:83`. `GET /status` is not
among them, because the health check makes that call before the subagent is
ever dispatched.

The canonical discovery document is the right home: it is the one artifact
every later phase reads, it is already the place where "what production is"
is recorded, and it is re-read by the orchestrator after the subagent returns.

`scripts/discovery.py:536-582` shows the document's top-level shape — an
`environment` sub-object plus sibling keys (`dropins`, `themes`, `mass_send`,
`defines`, …). The version is a fact about the *control channel*, not about
the WordPress environment, so it belongs as its own top-level key, not inside
`environment`.

### Repo conventions you must match

- `scripts/discovery.py` is a `uv` inline-metadata script with no
  dependencies. Malformed input raises `DiscoveryError`, which `main()` turns
  into a non-zero exit and a `discovery: <message>` line on stderr — never a
  half-built document on stdout. Use `_require` / `_optional`
  (`scripts/discovery.py:109-148`) at the boundary; do not hand-roll a check.
- **Comment style** (`agents.d/coding-standard/general.md`): paragraphs with a
  `#` comment above each stating that block's purpose.
- Docstrings on every function, saying why.
- British English in prose; Markdown prose on one physical line per paragraph.
- Terminology is binding (`CONTEXT.md`).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full test suite | `uvx pytest -q` | exit 0, `942 passed` before your change; more after |
| Discovery tests | `uvx pytest -q tests/test_discovery.py` | exit 0 |
| Lint (touched files only) | `uvx ruff check scripts/discovery.py tests/test_discovery.py` | exit 0 |

Run from `/Users/thomas/Projects/kntnt-wp-skills`. **Do not run
`uvx ruff check .`.**

## Scope

**In scope**:

- `scripts/discovery.py` (modify)
- `tests/test_discovery.py` (modify — add cases)
- `tests/test_clone_orchestration.py`, `tests/test_pull_orchestration.py`
  (modify **only** if they construct a discovery envelope that now needs the
  new key; `grep -n '"environment":' tests/*.py` finds every construction —
  there were two at the time of writing)
- `skills/clone/SKILL.md`, `skills/pull/SKILL.md` (modify — the envelope
  contract in §2 and the report in §11)
- `agents/discovery-classify.md` (modify — the task envelope it receives)
- `docs/spec.md`, `CHANGELOG.md` (modify)
- `docs/adr/0020-…` — **do not create one here**; see step 5.

**Out of scope** (do NOT touch, even though they look related):

- **Raising the floor.** The floor is `≥ 2` while the client assumes features
  from 4, 5 and 6. Raising it is the obviously-implied next move and this plan
  deliberately does not make it, because raising the floor to 6 would *refuse
  production* (`safeteam.se`, Extractor 0.4.0, API version 5) until a
  coordinated release and a manual wp-admin install have happened. That is an
  operational decision belonging to the repository owner and the Extractor
  side's own planning, not something to land as a side effect of plumbing. If
  you find yourself editing the `≥ 2` literal, stop.
- `tests/test_api_version_ceiling_consistency.py` and its `VERIFIED_CEILING` /
  `FLOOR` literals. Same reason.
- `scripts/poll_extraction.py`. The stall-window widening is plan 002's, and
  it gates on the *observed absence* of `chunks_done`, not on a version
  number. Do not make it read the version — an observation beats a version
  comparison and needs no plumbing to be correct.
- Any Extractor-side change.
- `classify.py`, `resolve_plan.py`, `build_selection.py` — this plan adds a
  fact to the document; it changes no decision.

## Git workflow

- Trunk-based: commit straight to `main`. No branch, no PR.
- Message style: one imperative sentence, no prefix. Example from this repo:
  `Make the poll discipline canonical in one document, enforced from there`.
- Do NOT push and do NOT tag.

## Steps

### Step 1: Accept and record the version in the discovery document

In `scripts/discovery.py`, add a top-level `api_version` to the envelope
`build_document` reads, and to the document it emits.

Make it **required** (`_require(raw, "api_version", int, "input")`), not
optional. An optional field that can be silently absent reproduces the exact
defect this plan exists to close: something that is supposed to be known,
isn't, and nothing says so. There were two envelope constructions in the test
suite at the time of writing, so the cost of requiring it is small; find them
with `grep -n '"environment":' tests/*.py`.

Emit it as a sibling of `environment` in the returned document — a fact about
the control channel, not about the WordPress install:

```python
        "api_version": api_version,
```

Add a comment paragraph in the file's own register explaining why the document
carries it: the health check observes it once and every later phase needs it
to know which of its behaviours are degraded on this host, and a fact that
lives only in the orchestrator's transcript cannot be reported, tested, or
reasoned about after the fact.

Update `build_document`'s docstring, and the module docstring's description of
the envelope (`scripts/discovery.py:1-40`), to state the new member.

**Verify**: `uvx pytest -q tests/test_discovery.py` → expect failures in the
existing tests whose fixtures now lack the required key. That is expected;
step 2 fixes them.

### Step 2: Update the fixtures and add the tests

Fix every envelope fixture that now fails, adding a realistic `api_version`
(use `6` for the general fixtures — the current ceiling, and what a
released-and-installed pair will report).

Then add cases to `tests/test_discovery.py`, modelled on its existing
boundary-validation tests:

1. A well-formed envelope carrying `"api_version": 6` produces a document
   whose top-level `api_version` is `6`.
2. An envelope **missing** `api_version` fails loud: `DiscoveryError` raised,
   its message naming the field.
3. An envelope whose `api_version` is a string (`"6"`) or a float fails loud —
   the version is compared numerically downstream and a string would compare
   wrong rather than fail.
4. `api_version` is a **sibling** of `environment`, not a member of it — pin
   the placement, because a later reader will look for it in exactly one of
   those two places.

**Verify**: `uvx pytest -q` → exit 0, count at least 4 higher than 942.

### Step 3: Make the subagent carry the number

The `discovery-classify` subagent assembles the envelope, so it must be given
the version the health check already observed.

In `agents/discovery-classify.md`, add `api_version` to the task envelope the
subagent receives — the number the orchestrator's `GET /status` reported —
and state that the subagent puts it into the envelope it pipes to
`scripts/discovery.py` verbatim, never re-fetching it. Re-fetching would mean
a second `GET /status` that could, on a host being upgraded mid-run, disagree
with the one the health check gated on.

In `skills/clone/SKILL.md:82` and `skills/pull/SKILL.md:83`, where the
four-section envelope is specified as
`{ "environment": …, "tables": …, "files": …, "bootstrap": … }`, add the
`api_version` member and one clause saying it is the version the health check
already observed, passed through rather than re-fetched.

`tests/test_agent_delegation_consistency.py` binds the SKILLs and the agent
definitions together; a green suite after this step is the check that the two
sides still agree.

**Verify**: `uvx pytest -q` → exit 0.

### Step 4: Report the degradations to the operator

This is the half that turns plumbing into a fix. In **both** SKILLs' §11
("Cleanup and report"), require the run report to state the Extractor API
version production reported, and — when it is below this client's ceiling —
name each behaviour that is consequently degraded on this host, in one bullet
each. At the time of writing there are exactly three, and the report must be
written so a fourth is easy to add:

- **below 4** — `GET /status` carries no `authenticated_as` or `capabilities`,
  so identity was proven by the deliberate wrong-password discriminating test
  rather than read directly.
- **below 6** — `progress.chunks_done` is absent, so stall detection ran on
  the coarse counters and under the widened stall window (see plan 002); a
  genuine hang therefore took longer to notice.
- **below the version that added `strict`** — the `strict: false` member is
  ignored, so a file that vanished between the `GET /files` walk and the
  `POST` would have failed the whole submission rather than being skipped and
  reported. This one is a *deliberate* degradation to the previous behaviour,
  recorded in `CHANGELOG.md`; the report says so plainly rather than framing
  it as a fault.

State in the same paragraph that this list is the client's own knowledge of
what it assumes, and that the remedy for all of it is upgrading production's
Extractor — never a client-side workaround.

For the third bullet you need the version at which `strict` was introduced.
**Do not guess it.** At the time of writing it had been implemented in the
Extractor's working tree with `API_VERSION` deliberately left at 6
(`~/Projects/kntnt-extractor/classes/Rest/Extractions_Controller.php:772`,
`~/Projects/kntnt-extractor/classes/Rest/Status_Controller.php:87`), which
means **no version number distinguishes an Extractor that honours `strict`
from one that ignores it.** If that is still true when you run this plan,
write the bullet as a plain statement of the current facts — that the member
is additive and silently ignored by any Extractor that predates it, that no
version reports whether it is honoured, and that the degradation is therefore
reported unconditionally against any Extractor whose release version is below
the one that shipped it. Do not invent a version threshold that does not
exist, and do not add a probe to discover one.

**Verify**: `uvx pytest -q` → exit 0.

### Step 5: Pay the documentation round

1. **`docs/spec.md`** — the discovery section (`docs/spec.md:150`) enumerates
   what discovery supplies. Add that the canonical document also records the
   Extractor API version the health check observed, and one sentence on why:
   so a later phase can state what it degraded rather than degrading silently.
2. **`CHANGELOG.md`** — an entry under `## [Unreleased]`. This is an addition
   plus a reporting fix; `### Added` is the honest heading. Match the register
   of the entries already there.
3. **No new ADR.** This plan implements no new decision — it makes an existing
   one (the version pin, ADR-adjacent and already documented on four surfaces)
   observable. Adding an ADR for plumbing would dilute the directory. If the
   floor is later raised, *that* is the ADR, and it is not this plan's.

**Verify**: `uvx pytest -q` → exit 0, and
`uvx ruff check scripts/discovery.py tests/test_discovery.py` → exit 0.

## Test plan

Four new cases in `tests/test_discovery.py`, specified in step 2, plus fixture
updates. Model them on the file's existing boundary-validation tests — the
ones that assert `DiscoveryError` is raised with a message naming the offending
field.

The case that matters most is **3** (a string version fails loud). A version
that arrives as `"6"` and is compared with `<` against an int either raises at
a distance or, worse, is compared lexically somewhere and silently reads wrong
— which is the same class of silent-wrongness this whole plan is about.

Verification: `uvx pytest -q` → exit 0, count ≥ 946.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `uvx pytest -q` exits 0 and reports at least 946 passed
- [ ] `uvx ruff check scripts/discovery.py tests/test_discovery.py` exits 0
- [ ] `grep -rn "api_version" scripts/` returns at least 2 matches in `scripts/discovery.py` (it returned none before this plan)
- [ ] `grep -l 'api_version' skills/clone/SKILL.md skills/pull/SKILL.md agents/discovery-classify.md docs/spec.md` lists all four files
- [ ] `git diff -- tests/test_api_version_ceiling_consistency.py` is empty (the floor and ceiling literals were not touched)
- [ ] `git diff -- scripts/poll_extraction.py` is empty (the poller still gates on observed absence, not on a version)
- [ ] `grep -n '≥ 2' skills/clone/SKILL.md skills/pull/SKILL.md docs/spec.md docs/implementation-notes.md` still returns a match in each (the floor is unchanged)
- [ ] `git status --short` lists only files from the "In scope" list
- [ ] `plans/README.md` status row for 003 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows `scripts/discovery.py` changed since `947e28b` and the
  excerpts above no longer match.
- More than four test fixtures need an `api_version` added. The blast radius
  was two envelope constructions when this plan was written; a much larger
  number means the envelope is constructed somewhere this plan did not
  account for, and the required-versus-optional decision should be re-taken
  rather than pushed through.
- You conclude the version must be required by `classify.py`,
  `resolve_plan.py`, or any other helper to be useful. It must not — this plan
  records a fact and reports it; it changes no decision. A helper that wants
  to *branch* on the version is a different plan with different risk.
- You find that the Extractor does, after all, bump `API_VERSION` for
  `strict`. Step 4's third bullet then has a real threshold and should state
  it — report the number you found rather than writing the unconditional
  wording.
- You find yourself about to change the `≥ 2` floor, `VERIFIED_CEILING`, or
  `FLOOR`.

## Maintenance notes

- **What a reviewer must scrutinise**: that no decision anywhere branches on
  the new field. The value of this change is that the version becomes
  *reportable*; the moment a helper starts branching on it, the client grows a
  compatibility matrix, and that needs its own decision.
- **What this unblocks**: any future floor raise. Once the version is in the
  document and the degradations are enumerated in the report, raising the
  floor becomes a one-literal change with a written list of what each version
  buys — instead of an archaeology exercise across four Markdown surfaces.
- **The open question this plan deliberately leaves for the repository owner**:
  should the floor move from 2 to something that reflects what the client
  actually assumes? Doing so refuses production until the pending coordinated
  release is installed, which is precisely why it is a decision and not a
  cleanup. The degradation report this plan adds is what makes that decision
  informed — after one run against production, the operator sees the list of
  what is degraded rather than inferring it.
- **Related but out of reach from this repository**: the third degradation
  exists only because `strict` shipped without an `api_version` bump. Nothing
  client-side can detect it. If that is judged unacceptable, the fix is a
  version bump on the Extractor side, not a probe here.
