# Plan 004: Raise the verified Extractor API-version ceiling from 6 to 7

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **This plan raises a safety limit. Its value is entirely in the verification
> step, not in the edit.** The edit is six literals and takes minutes. If you
> find yourself doing the edit without having completed Step 1, you are
> defeating the mechanism this plan exists to operate.
>
> **Drift check (run first)**:
> `git diff --stat 947e28b..HEAD -- tests/test_api_version_ceiling_consistency.py skills/clone/SKILL.md skills/pull/SKILL.md docs/spec.md docs/implementation-notes.md`

## Status

- **Priority**: P1 (blocks the coordinated release; do not start before its dependency)
- **Effort**: S for the edit, M for the verification that justifies it
- **Risk**: MED — this is the client's only protection against an artifact contract it has not been checked against
- **Depends on**: `plans/001-refuse-to-port-a-withheld-define.md` — **hard dependency, see below**
- **Category**: migration
- **Planned at**: commit `947e28b`, 2026-08-16

## Why this matters

The skills pin the Extractor to API version **≥ 2 and ≤ 6**. The ceiling is
the half that catches a server whose artifact contract has moved: API version
5 turned one sealed segment per table into one *or more*, and a client that had
not been updated kept only the last slice of every table — every table but its
final slice lost, no error raised on either side, both repositories' suites
green throughout.

The Extractor's plan 008 bumps `API_VERSION` 6 → 7. **At 7 this client refuses
to run at all** — correctly, by design: a `GET /status` above the ceiling stops
for the operator rather than risking a silent mis-reassembly. So the ceiling
raise is not optional cleanup; it is a required step of the coordinated
release, and without it the release ships a client that cannot talk to the
server it shipped with.

The raise is deliberately expensive to do by accident. `VERIFIED_CEILING` lives
in a test, and `tests/test_api_version_ceiling_consistency.py` refuses the
change until every pinning surface has followed — which is the point: it makes
verifying against a new Extractor release a conscious act rather than an
omission.

### Why this depends on plan 001

**Do not raise the ceiling until `plans/001-refuse-to-port-a-withheld-define.md` is merged.**

API version 7 is where the Extractor replaces its secret deny-list with an
allow-list, so it is the first version that returns `null` for defines this
client classifies as *portable*. Without 001, a run against a version-7
Extractor writes `define('SOME_API_KEY', null);` into the local
`wp-config.php` — `php -l` passes, the smoke test is silent, and
`defined('SOME_API_KEY')` then returns `true`, suppressing the plugin's own
fallback. Raising the ceiling is precisely the act of declaring "this client is
correct against version 7". That declaration is false until 001 has landed.

Note what this plan does **not** need: 001 makes the client correct against the
allow-list *without* consuming the Extractor's new per-record `disclosure`
member, because it decides on the value (`null`) rather than on the
discriminator. Consuming `disclosure` is a later refinement, not a prerequisite
of this release.

## Current state

### The one authoritative literal

`tests/test_api_version_ceiling_consistency.py:36-45`:

```python
# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]

# The highest Extractor API version this client is verified against. Raise it
# only after checking a release's artifact shape against ``scripts/unseal.py``
# and the container-format contract in ``docs/implementation-notes.md``.
VERIFIED_CEILING: int = 6

# The floor, unchanged since it was set: the version that ships the environment
# endpoint, structure-only extraction, and caller job listing together.
FLOOR: int = 2
```

### The four surfaces the suite holds to it

`tests/test_api_version_ceiling_consistency.py:49-54`:

```python
PINNING_SURFACES: tuple[Path, ...] = (
    REPO_ROOT / "skills" / "clone" / "SKILL.md",
    REPO_ROOT / "skills" / "pull" / "SKILL.md",
    REPO_ROOT / "docs" / "spec.md",
    REPO_ROOT / "docs" / "implementation-notes.md",
)
```

Each is asserted to match `rf"≤ {VERIFIED_CEILING}\b"`
(`tests/test_api_version_ceiling_consistency.py:70-80`) and to still state the
floor `≥ 2` (`:83-94`). A third test (`:97-109`) asserts no *live* surface —
which additionally includes `agents/*.md` and `docs/man/*.md` — carries the
old floor-only pin sentence.

In `skills/clone/SKILL.md` the sentence is at `:26` and `:63`; in
`skills/pull/SKILL.md` at `:26` and `:64`. **There are two occurrences per
SKILL, not one** — the "How the engine works" control-channel paragraph and
the health check's Production bullet. Both must move.

### What the ceiling actually protects

Read `tests/test_api_version_ceiling_consistency.py:5-25` before Step 1 — it is
the rationale in full, and it is what tells you what "verified" has to mean.
The hazard is a version *above* what the client understands, and specifically
a change to the **artifact's shape** that `scripts/unseal.py` would reassemble
wrongly rather than reject.

### Repo conventions

- British English; Markdown prose on one physical line per paragraph, never
  hard-wrapped at a column width.
- The `≥`/`≤` characters are literal Unicode, not `>=`/`<=`. The test's regex
  matches the Unicode form. Match it exactly.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full test suite | `uvx pytest -q` | exit 0 |
| The ceiling suite | `uvx pytest -q tests/test_api_version_ceiling_consistency.py` | exit 0 |
| Lint | `uvx ruff check tests/test_api_version_ceiling_consistency.py` | exit 0 |
| Find every stale literal | `grep -rn "≤ 6" --include=*.md --include=*.py .` | after Step 3, no match outside `CHANGELOG.md` and `docs/adr/` |

Run from `/Users/thomas/Projects/kntnt-wp-skills`. **Do not run `uvx ruff check .`**.

## Scope

**In scope**:

- `tests/test_api_version_ceiling_consistency.py` (modify — the literal)
- `skills/clone/SKILL.md`, `skills/pull/SKILL.md` (modify — two occurrences each)
- `docs/spec.md`, `docs/implementation-notes.md` (modify)
- `agents/*.md`, `docs/man/*.md` (modify **only** where they state the ceiling)
- `docs/adr/0021-verified-against-extractor-api-version-7.md` (create)
- `CHANGELOG.md` (modify)
- `plans/004-…md` itself (record the verification findings — see Step 2)

**Out of scope**:

- **The floor `≥ 2`.** It does not move in this plan. Raising the ceiling never
  refuses an older server, so production at API version 5 keeps working
  throughout. Changing the floor is a separate decision with a separate cost
  (it would refuse production outright).
- `scripts/` — no helper changes. If the verification in Step 1 finds that
  version 7 *does* change the artifact shape, that is a STOP condition and a
  different plan, not an edit here.
- Consuming the Extractor's new per-record `disclosure` member. Plan 001 makes
  the client correct without it.
- Historical mentions of `≤ 6` inside `CHANGELOG.md` entries and `docs/adr/`
  files. Those are records of what was true at the time and must not be
  rewritten.

## Git workflow

- Trunk-based: commit straight to `main`. No branch, no PR.
- Message style: one imperative sentence, no prefix. E.g.
  `Verify the client against Extractor API version 7 and raise the ceiling`.
- Do NOT push and do NOT tag.

## Steps

### Step 1: Verify, before editing anything

**This is the plan. The rest is bookkeeping.** The ceiling asserts "this client
has actually been checked against version N". Raising it without checking makes
the mechanism worse than absent, because it launders an unverified contract
through a test that reads as verification.

Establish, and write down, exactly what changed between API version 6 and 7.
The Extractor repository is at `~/Projects/kntnt-extractor`. Sources, in order
of authority:

1. Its `CHANGELOG.md` entries for the release that carries `API_VERSION = 7`.
2. `~/Projects/kntnt-extractor/classes/Rest/Status_Controller.php` — confirm
   the constant is actually 7 in the build you are verifying against.
3. Its `plans/` directory — at the time of writing, plan 008 (the wp-config
   define allow-list), plan 013 (a `state` query parameter on
   `GET /extractions` admitting terminal jobs), and plan 014 (a `capabilities`
   array on `GET /status`) were the changes expected to ride this bump.
4. Its normative container-format specification (its plan 009), if written by
   then — that document is the authority on the artifact contract.

For **each** change, answer one question and record the answer:

> Does this change the **artifact** — the `KNTNTEXT` container's layout, its
> segment framing, the number of segments per table or file, the sealed index,
> or the reassembly order?

Then confirm the answer against this repository's own reassembly contract:
`scripts/unseal.py`, and the container-format section of
`docs/implementation-notes.md` (its *Download and unseal (local)* contract).

**The expected finding, based on what was known when this plan was written:**
none of the three changes touches the artifact. The define allow-list changes a
`GET /environment` response body; the `state` parameter changes a
`GET /extractions` query; the capabilities array changes a `GET /status`
response body. All three are REST-surface changes. If that holds, the
verification conclusion is that version 7 is artifact-identical to version 6
and `scripts/unseal.py` needs no change.

**Do not assume that expected finding is true.** It is what a reader believed
in advance; Step 1 exists to check it. If a fourth change rode the bump, or if
any of the three grew an artifact component, the conclusion changes.

**Strongest available verification, if you can get it**: unseal a container
actually produced by the version-7 build. A local DDEV site with the new
Extractor installed, exercised through the health check's own two-table
preflight (`skills/clone/SKILL.md:70`), produces a real container cheaply. If a
version-7 Extractor is not reachable, say so explicitly in Step 2's record
rather than implying a round trip happened.

**Never do this against production.** `safeteam.se` is a live client site.

**Verify**: you have a written list of the version-7 changes, each with its
artifact-impact answer and the source you read it from. If you do not, do not
continue.

### Step 2: Record the verification in this plan file

Append a `## Verification record` section to *this file* with:

- the Extractor version and `API_VERSION` value you verified against, and the
  commit or release tag;
- each change, with its artifact-impact answer and the source;
- whether a real version-7 container was unsealed, and if not, why not;
- the conclusion, in one sentence.

This is the durable answer to "was the ceiling raised on evidence?", asked
months later by someone who was not here. A raise whose record says "no
version-7 container was available, verification was by source inspection of
three REST-surface changes" is honest and useful. One with no record is exactly
the omission the ceiling exists to prevent.

**Verify**: the section exists and names a specific Extractor build.

### Step 3: Raise the literal and every surface that states it

1. `tests/test_api_version_ceiling_consistency.py:41` — `VERIFIED_CEILING: int = 6`
   → `7`. Leave `FLOOR` at 2. Update the comment above it if Step 1 found
   anything worth warning the next raiser about.
2. Run `uvx pytest -q tests/test_api_version_ceiling_consistency.py`. It
   **will fail**, naming each surface that still says `≤ 6`. That failure list
   is your worklist — work it rather than guessing at the files.
3. Change `≤ 6` to `≤ 7` on each. Remember: **two occurrences each** in
   `skills/clone/SKILL.md` (`:26`, `:63`) and `skills/pull/SKILL.md`
   (`:26`, `:64`).
4. `grep -rn "≤ 6" --include=*.md --include=*.py .` and change any remaining
   live surface — `agents/*.md`, `docs/man/*.md`. **Leave `CHANGELOG.md`
   entries and `docs/adr/` files alone**; those are historical records.
5. Check for stale *prose* the literal change does not catch: a sentence like
   "verified against version 6" or "this client's ceiling is 6" written out in
   words. `grep -rn "ceiling" --include=*.md .` finds them.

Keep every `≥ 2` intact. The suite asserts it separately, and the floor is not
this plan's.

**Verify**: `uvx pytest -q` → exit 0.

### Step 4: Pay the documentation round

1. **`docs/adr/0021-verified-against-extractor-api-version-7.md`** (create).
   Read `docs/adr/0019-crm-subscribers-own-gate-default-empty.md` first and
   match its structure and length. Record: what version 7 changed; that the
   artifact contract was checked and found unchanged (or whatever Step 1
   actually concluded); that the raise required plan 001 to be merged first,
   and why; and — most valuable to a future reader — that the raise is a
   *declaration of having checked*, so the correct response to an unverifiable
   future version is to leave the ceiling where it is and let the client stop.
2. **`CHANGELOG.md`** — an entry under `## [Unreleased]` → `### Changed`,
   naming the new ceiling and pointing at the ADR. Do not create a version
   heading and do not bump any version.

**Verify**: `uvx pytest -q` → exit 0;
`uvx ruff check tests/test_api_version_ceiling_consistency.py` → exit 0.

## Test plan

No new tests. This plan changes a constant that four existing tests already
enforce across six files, and adding a test asserting the constant equals 7
would only restate the constant.

What must hold instead: `uvx pytest -q` exits 0 with **no** test skipped or
deleted, and in particular
`tests/test_api_version_ceiling_consistency.py::test_the_ceiling_is_not_below_the_floor`
and both `test_every_pinning_surface_*` families still pass, parametrised over
all four surfaces.

If any of those tests is weakened, deleted, or has a surface removed from
`PINNING_SURFACES` in order to make this plan pass, the plan has failed even if
the suite is green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `plans/001-refuse-to-port-a-withheld-define.md` has status DONE in `plans/README.md` **before this plan's edits begin**
- [ ] This file contains a `## Verification record` section naming a specific Extractor build
- [ ] `uvx pytest -q` exits 0, with no fewer tests than before
- [ ] `grep -n 'VERIFIED_CEILING: int = 7' tests/test_api_version_ceiling_consistency.py` matches
- [ ] `grep -n 'FLOOR: int = 2' tests/test_api_version_ceiling_consistency.py` still matches
- [ ] `grep -rn "≤ 6" --include=*.md --include=*.py .` matches nothing outside `CHANGELOG.md`, `docs/adr/`, and `plans/`
- [ ] `grep -c "≤ 7" skills/clone/SKILL.md` and `grep -c "≤ 7" skills/pull/SKILL.md` each return 2
- [ ] `grep -rn "≥ 2" skills/clone/SKILL.md skills/pull/SKILL.md docs/spec.md docs/implementation-notes.md` matches in all four
- [ ] `git diff --stat -- scripts/` is empty
- [ ] `test -f docs/adr/0021-verified-against-extractor-api-version-7.md` exits 0
- [ ] `plans/README.md` status row for 004 updated

## STOP conditions

Stop and report back (do not improvise) if:

- **Plan 001 is not merged.** Raising the ceiling declares the client correct
  against version 7; without 001 that declaration is false and a clone will
  write `define('NAME', null);`.
- **Step 1 finds that version 7 changes the artifact** — segment framing,
  segments per table or file, the sealed index, or reassembly order. Then
  `scripts/unseal.py` needs work first, and that is a different plan with a
  different risk profile. This is the exact hazard the ceiling exists for; do
  not edit past it.
- **You cannot establish what changed between 6 and 7.** Leave the ceiling at
  6 and report. A client that stops for the operator is the designed
  behaviour, not a failure — it is strictly better than one that proceeds on
  an unverified contract.
- The Extractor's shipped `API_VERSION` is not 7 (it stayed 6, or went to 8).
  The number in this plan came from another repository's plan, not from a
  release; verify against the build, and report the discrepancy rather than
  raising to whatever you found.
- Making the suite pass appears to require removing a surface from
  `PINNING_SURFACES`, or relaxing an assertion.
- Any temptation arises to also move the floor.

## Maintenance notes

- **What a reviewer must scrutinise**: the `## Verification record` section,
  and nothing else. The literal change is trivially correct or trivially
  wrong; the record is the only thing that says whether the raise was earned.
- **The mechanism is the point.** This suite exists because API version 5 lost
  every table's non-final slice while both repositories' suites stayed green.
  The cost of raising the ceiling — six literals across six files, refused by a
  test until all follow — is deliberate friction, not an inconvenience to
  streamline. Anyone who proposes deriving these literals from a single source
  to make the raise cheaper is removing the safety mechanism.
- **Interacts with**: plan 003, if executed. Once the API version is carried in
  the discovery document and the degradation list is reported, a future ceiling
  raise gains a second, live check — a run against the new version reports what
  it degraded, instead of the ceiling being the only signal.
- **Deferred deliberately**: consuming the version-7 per-record `disclosure`
  member on `GET /environment` defines. Plan 001 decides on the value, so the
  client is correct without it; consuming the discriminator would additionally
  let a legitimately-null define be ported and let the withheld-reason reach
  the operator's report. Worth doing, not worth blocking the release on.

## Verification record

**Extractor build verified against**: `kntnt-extractor` HEAD at commit
`7dc242047bbb60df8fd5a90f822005b0046c984b` ("Disclose a define's value only
from an allow-list, so an unlisted secret fails closed"), dated 2026-08-16.
`API_VERSION = 7` confirmed by direct read of
`classes/Rest/Status_Controller.php:112` in that build. **No tagged release
carries this commit** — the highest tag is `v0.5.1`, and this work sits in the
`## [Unreleased]` section of that repository's `CHANGELOG.md`.

This plan's own prediction of what rode the bump (its plan 008, 013, 014) was
wrong in two particulars, corrected here from the Extractor repository's own
`plans/README.md`, its ADRs, and its `CHANGELOG.md` rather than from this
plan's advance summary:

1. **Extractor plan 008 — the `GET /environment` define-disclosure
   allow-list — is the change that bumped `API_VERSION` 6 → 7**, and is the
   only one of the three. Source: `docs/adr/0018-a-defines-value-discloses-only-from-an-allow-list-with-a-per-record-discriminator.md`
   and the `## [Unreleased]` → `### Changed` entry in `CHANGELOG.md`
   ("**`api_version` moves from 6 to 7**"). **Artifact impact: none.** ADR-0018
   states explicitly that under ADR-0017's shape rule this change "would
   ordinarily be a `honours` entry instead" — it changes only the `GET
   /environment` response body (a `disclosure` member added to every `defines`
   record) — and bumps the integer anyway as "a deliberate compatibility
   interlock", not a shape claim: an already-shipped, unmodified
   `kntnt-wp-skills` client classifies a `null`-valued define by name alone
   and would port a newly-withheld one into a local `wp-config.php` as
   `define('X', null)`, which plan 001 (merged as `66e42e9`) is what makes
   safe. The container's byte layout, segment framing, segments-per-resource,
   sealed index, and reassembly order are untouched by this change; nothing in
   it touches `classes/Crypto/Sealed_Writer.php` or `Artifact_Builder.php`.
2. **Extractor plan 014 — the `honours` capability list on `GET /status` —
   landed (`f47b42e`, status DONE) but is not what the plan expected.** The
   member is named `honours`, not `capabilities`; `capabilities` already
   named the caller's own WordPress capabilities on that same endpoint and
   was not available to reuse. Source: `docs/adr/0017-api-version-bounds-the-artifact-contract-honours-reports-what-a-build-does.md`,
   which states plainly "`API_VERSION` moves only when the artifact's shape
   moves… Adding a capability to `honours`… never moves `API_VERSION`."
   **Artifact impact: none** — it is an authenticated `GET /status` response
   field, not a change to the sealed container, and by ADR-0017's own rule it
   did not ride this or any version bump. `disclosure` (from plan 008) was
   additionally registered in `HONOURED_BEHAVIOURS`, which is also not an
   artifact change.
3. **Extractor plan 013 — a `state` query parameter on `GET /extractions` —
   has not landed.** Source: `plans/README.md` in the Extractor repository
   lists it `TODO`, depending on plan 014. Its own text (`plans/013-…md`,
   "Out of scope") states the parameter "does not change the container" and
   is "announced through the capability list" rather than a version bump —
   so it will not ride a version bump whenever it does land. **Not yet
   relevant to this ceiling raise; no artifact impact predicted or observed.**

**The normative source, `docs/container-format.md`** (landed via Extractor
plan 009, commit `0b90bde`), was read in full. §8 *Versioning* states
`FORMAT_VERSION` is currently `1` and that `FORMAT_VERSION` moving "is always
also a shape change and therefore always accompanies an `api_version` move;
the reverse is not guaranteed to be true in principle" — i.e. `api_version`
can move (as it just did) without `FORMAT_VERSION` moving, which is exactly
what plan 008/ADR-0018's compatibility-interlock bump is. Nothing in the
document was changed by the version-6-to-7 work; it describes exactly the
same byte layout, segment framing, and reassembly rule this repository's
`scripts/unseal.py` and `docs/implementation-notes.md`'s *Container format*
section already implement (positional name/segment pairing, concatenation of
same-named segments in index order, tolerance for the pre-version-5
one-segment-per-table shape as the one-slice case of the current rule).

**Artifact-writing code history, checked independently of the changelog's own
framing**: `git -C ~/Projects/kntnt-extractor log --oneline v0.5.1..HEAD --
classes/Crypto/ classes/Artifact_Builder.php` names nine commits
(`7dc2420` through `f5a1e0a`). Each was read against its `CHANGELOG.md`
entry:

- `7dc2420` (the version bump itself) does not touch either path — confirmed
  by the command's own output, which does not list it; the define-disclosure
  change lives entirely in `classes/Rest/Environment_Controller.php`.
- `0b90bde` — adds `docs/container-format.md`. Documentation only.
- `e08ea3d` — `Sealed_Writer::resume()` skips a truncation call and an
  `is_file()`/`filesize()` stat pair when they are provably redundant given
  the anchor already checked; validates resume anchors via `fstat()` on an
  already-open handle instead of re-opening. Fewer filesystem round trips per
  chunk; the bytes written to the container are unchanged. Changelog: "No
  REST change."
- `a2d7c01` — `Sealed_Writer::add_segment()` takes plaintext as a `string`
  directly instead of round-tripping it through a `php://temp` stream.
  Changelog states explicitly: "The container's wire format, framing, and
  `api_version` are unchanged — every byte `add_segment()` writes is
  identical to before."
- `481888b` — `Artifact_Builder::read_part()` now throws on a failed or short
  `fread()` instead of silently casting the failure to an empty string and
  sealing it as a legitimate empty segment. This changes error-path
  *behaviour* (fail loudly instead of publishing a truncated artifact) but
  does not add a new artifact shape; the happy-path bytes sealed for a
  successfully-read part are unchanged, and a genuine zero-byte file still
  seals as exactly one empty segment as before.
- `0842a8a` — defers discarding the index sidecar until after the container
  is published rather than before. Working-state (`.names` sidecar, out of
  `docs/container-format.md`'s §9 scope) handling only; the published
  container is unaffected.
- `c39e871` — deletes a failed job's part-built container and sidecar at
  fail-time. Applies only to jobs that never reach `ready`; no published
  artifact is affected.
- `3001817`, `9a13c33` — stall-adaptation and resume-from-persisted-progress
  logic (chunk-size search, re-driving a failed stall). Change when and how
  large a chunk is requested, not the format of what gets sealed.
- `f5a1e0a` — splits the persisted job record (`job.json`/`state.json`); a
  bookkeeping file the Extractor keeps for itself, never part of the sealed
  container.

**Conclusion of this check**: none of the nine commits touching
`classes/Crypto/` or `classes/Artifact_Builder.php` since `v0.5.1` changes a
byte that reaches the container — several change *how* those bytes get
written (fewer round trips, no temp-file spill, deferred sidecar cleanup),
none change *what* gets written. This corroborates `docs/container-format.md`
§8's statement that `FORMAT_VERSION` (still `1`) did not move.

**No version-7 container was unsealed.** Standing up a DDEV site with a
version-7 Extractor build to obtain a real container was considered — the
plan calls it the strongest available verification — and deliberately not
done: it was judged a heavyweight detour that would leave machine state
behind for a check this source inspection already answers with corroborating
evidence from three independent angles (the normative format spec, the
version-bump ADRs' own artifact-impact claims, and the artifact-writing code
history), and the operator will exercise a real round trip at release time.
This verification therefore establishes that **no source available in either
repository claims or shows a change to the artifact's byte layout, segment
framing, segments-per-resource, sealed index, or reassembly order between API
version 6 and 7** — it does not establish that an actual version-7-produced
container unseals correctly with this repository's `scripts/unseal.py`, which
only a real round trip can prove.

**Conclusion**: API version 7 is artifact-identical to API version 6 — the
sole change that moved the integer (plan 008's define-disclosure allow-list,
ADR-0018) is, by its own author's admission, a deliberate compatibility
interlock rather than a shape change, corroborated by an unmoved
`FORMAT_VERSION` and by nine artifact-adjacent commits that touch only how
segments are written, never what they contain; `scripts/unseal.py` needs no
change, and the verified ceiling is raised to 7 on that evidence.
