# Plan 001: Refuse to port a define whose value the Extractor withheld

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 947e28b..HEAD -- scripts/classify.py scripts/wpconfig_block.py scripts/resolve_plan.py scripts/discovery.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `947e28b`, 2026-08-16

## Why this matters

The Extractor masks a production secret by returning its define's value as
`null` on `GET /environment` (`docs/spec.md:118`, `docs/spec.md:339`). The
skills' side reads `null` as "the value is literally null" and ports it: the
define is offered at the `wp_config_defines` gate like any other, and the
writer emits `define('NAME', null);` into the local `wp-config.php`. `php -l`
passes, the smoke test says nothing, and the operator is never told.

That is worse than the define being absent. `defined('NAME')` returns `true`,
so a plugin's "not configured" fallback never fires; instead the plugin runs
with a null key and fails somewhere far from the cause.

Today this is latent rather than live, by coincidence: every name the Extractor
currently masks (`DB_PASSWORD`, the auth keys, the salts, the nonces) is *also*
routed to the auto-excluded class by `scripts/classify.py`, so no masked value
ever reaches the writer. That coincidence is about to end — the Extractor is
replacing its secret **deny**-list with an **allow**-list and will then return
`null` for every non-core define it does not recognise, including plugin
defines like third-party API keys that `classify.py` classifies as *portable*.
When that ships, a clone silently writes `define('SOME_API_KEY', null);`.

After this plan: a define whose value was withheld is never offered at the
gate, never written into the marked block, and is named to the operator in the
run report. `null` on the wire means "withheld", once, in one place.

## Current state

The value travels through four files, in this order. Read all four before
editing.

### 1. `scripts/discovery.py` — carries the value into the canonical document

`scripts/discovery.py:208-228`:

```python
def build_defines(raw_defines: list[Any]) -> list[dict[str, Any]]:
    ...
    defines: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_defines):
        context = f"environment.defines[{index}]"
        name = _require(entry, "name", str, context)
        value = None if is_secret_define(name) else entry.get("value")
        defines.append({"name": name, "value": value})

    return defines
```

This is the second line of defence that redacts the names it knows
(`is_secret_define`, `scripts/discovery.py:193-205`). A value that arrived
already `null` passes straight through as `None`. **Do not change this file.**
It is correct: redacting more is its job, and distinguishing "withheld" from
"null" is the classifier's.

### 2. `scripts/classify.py` — routes the define to portable, value and all

`scripts/classify.py:415-432`:

```python
def define_class(name: str) -> str | None:
    """Classify one define name into its auto-excluded class, or ``None`` when it
    is a portable plugin/behaviour define offered at the gate.
    ...
    """

    if name in CREDENTIAL_DEFINES:
        return "credentials"
    if name in DOMAIN_PATH_DEFINES:
        return "domain_paths"
    if name in INFRASTRUCTURE_DEFINES or name.startswith(INFRASTRUCTURE_PREFIXES):
        return "infrastructure"
    if name in SALT_NONCE_DEFINES or name.endswith("_SALT") or name.startswith("NONCE_"):
        return "salts_nonces"
    return None
```

`scripts/classify.py:435-457`:

```python
def classify_defines(defines: list[Any]) -> dict[str, list[dict[str, Any]]]:
    ...
    portable: list[dict[str, Any]] = []
    auto_excluded: list[dict[str, Any]] = []
    for index, entry in enumerate(defines):
        context = f"defines[{index}]"
        record = _record(entry, context)
        name = _field(record, "name", str, context)
        classification = define_class(name)
        if classification is None:
            portable.append({"name": name, "value": record.get("value")})
        else:
            auto_excluded.append({"name": name, "class": classification})

    return {"portable": portable, "auto_excluded": auto_excluded}
```

Note the shape contract, which this plan must preserve: **a portable record
carries `name` and `value`; an auto-excluded record carries `name` and
`class`, never a value.** That asymmetry is deliberate — an auto-excluded
value is dropped because some of them are secrets.

`define_class` decides on the **name alone**. This is the seam the fix goes
through, and it is why the fix cannot live entirely in `define_class`: the
withheld verdict depends on the *value*, which `define_class` never sees.

### 3. `scripts/resolve_plan.py` — offers every portable name at the gate

`scripts/resolve_plan.py:235-240`:

```python
def live_portable_defines(context: Context) -> Any:
    """The names of the portable wp-config defines offered for porting — names
    only, because their values are re-fetched from live state every run rather
    than carried in the saved plan."""

    return [entry["name"] for entry in context.classifications["defines"]["portable"]]
```

This reads `portable` and nothing else, so routing a withheld define out of
`portable` in step 2 removes it from the gate for free — **no edit is needed
in this file.** The same is true of the saved-plan pruning at
`scripts/resolve_plan.py:304-309`, which already prunes a saved selection down
to the names still portable this run; a define that becomes withheld between
runs is therefore dropped from a replayed selection automatically. Step 4's
tests assert both of these rather than changing them.

### 4. `scripts/wpconfig_block.py` — renders `None` as PHP `null`

`scripts/wpconfig_block.py:86-118`:

```python
def _php_literal(value: Any) -> str:
    """Render a JSON scalar as its PHP literal: bool and null as bare keywords,
    int and float bare, string single-quoted with backslash and quote escaped.
    A non-scalar (object or array) is a contract violation.
    ...
    """

    if isinstance(value, bool):
        return "true" if value else "false"

    if value is None:
        return "null"
    ...
```

`_php_literal` is used for two different things — the define values *and* the
table prefix, at `scripts/wpconfig_block.py:220-223`:

```python
    lines = [BEGIN_MARKER]
    lines += [f"define('{name}', {_php_literal(value)});" for name, value in defines]
    if cron == "disabled":
        lines.append(f"define('{CRON_DEFINE}', true);")
    lines.append(f"$table_prefix = {_php_literal(table_prefix)};")
```

The table prefix is validated as a `str` at `scripts/wpconfig_block.py:273-275`
and can never be `None`, so the rejection this plan adds belongs on the define
path, not inside `_php_literal`. Put it in `_defines`, the boundary that
already rejects every other malformed define record
(`scripts/wpconfig_block.py:121-164`).

### Repo conventions you must match

- Every script is a `uv` inline-metadata script: the `# /// script` header at
  the top of the file, then a module docstring, then `from __future__ import
  annotations`. Do not add dependencies.
- **Comment style** (`agents.d/coding-standard/general.md`): group related
  lines into paragraphs separated by blank lines, with a `//`-equivalent (`#`)
  comment above each paragraph stating that block's *purpose*. Do not explain
  the obvious. End-of-line comments only for a genuine gotcha.
- Docstrings on every function, explaining the *why*, in the voice of the
  surrounding code — see `classify.py:435-443` above for the register.
- Malformed input fails loud: raise the module's own error class, which `main()`
  turns into a non-zero exit and a `<module>: <message>` line on stderr. Never
  emit a half-built document. See `scripts/wpconfig_block.py:355-373`.
- British English in all prose (`docs/spec.md:3`).
- Terminology is binding (`CONTEXT.md`). This plan introduces one new term;
  step 6 adds it to the glossary.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full test suite | `uvx pytest -q` | exit 0, `942 passed` before your change; more after |
| One test file | `uvx pytest -q tests/test_classify.py` | exit 0 |
| Lint (touched files only) | `uvx ruff check <the files you changed>` | exit 0, `All checks passed!` |

Run these from the repository root, `/Users/thomas/Projects/kntnt-wp-skills`.

**Do not run `uvx ruff check .`** — a repo-wide run reports pre-existing
findings that are not yours. Lint only the files you touched.

## Scope

**In scope**:

- `scripts/classify.py` (modify)
- `scripts/wpconfig_block.py` (modify)
- `tests/test_classify.py` (modify — add cases)
- `tests/test_wpconfig_block.py` (modify — add cases, and amend one existing
  case; see step 3)
- `tests/test_resolve_plan.py` (modify — add cases)
- `skills/clone/SKILL.md`, `skills/pull/SKILL.md` (modify — the report step)
- `docs/spec.md`, `CONTEXT.md`, `CHANGELOG.md` (modify)
- `docs/adr/0020-withheld-define-values-are-never-ported.md` (create)

**Out of scope** (do NOT touch, even though they look related):

- `scripts/discovery.py` — its redaction is a deliberate second line of
  defence and is correct as it stands. Widening `is_secret_define` is a
  different question and is not this plan's.
- `scripts/resolve_plan.py` — the gate and the saved-plan pruning both read
  `portable` and need no change once step 1 lands. Editing it would duplicate
  the rule in a second place.
- Anything under `skills/mkwp/`, `skills/build-ollie-site/`, or
  `scripts/smoke_test.py`.
- The Extractor repository at `~/Projects/kntnt-extractor` — it is a separate
  repo with its own release cycle. This plan is client-side only and must work
  against every Extractor from API version 2 upward.
- The `_php_literal` `None` branch itself. Leave it rendering `null`; the
  rejection belongs at the `_defines` boundary (see "Current state", part 4).

## Git workflow

- Trunk-based: commit straight to `main`. No branch, no PR.
- One commit for the whole plan is fine; the code and its documentation round
  belong together.
- Message style (from `git log --oneline`): a single imperative sentence, no
  conventional-commit prefix, no scope. Examples from this repo:
  `Exclude cache-plugin, backup, and Extractor staging trees from every clone`,
  `Start the poll stall clock from loop start when no poll has succeeded`.
- Do NOT push and do NOT tag. A release is the operator's call alone.

## Steps

### Step 1: Route a withheld define out of `portable` in `classify.py`

In `scripts/classify.py`, change `classify_defines` (currently lines 435-457)
so that a define whose value is `None` is classified as auto-excluded under a
new class string `"withheld"`, instead of being appended to `portable`.

Keep `define_class` unchanged — it classifies by name and must keep doing so.
The withheld check is a **value** check and belongs in `classify_defines`,
after `define_class` has returned `None` (i.e. only a define that would
otherwise have been portable can be withheld; a name-classified define is
already excluded and its value is dropped either way).

The target shape:

```python
        classification = define_class(name)
        if classification is None and record.get("value") is None:
            classification = WITHHELD_CLASS
        if classification is None:
            portable.append({"name": name, "value": record.get("value")})
        else:
            auto_excluded.append({"name": name, "class": classification})
```

Add the constant near the other define constants at the top of the file
(beside `INFRASTRUCTURE_PREFIXES`, `scripts/classify.py:92`), with a comment
paragraph in the file's own register explaining *why* — that `null` on the
wire is the Extractor's masking value, so a value that did not come down
cannot be ported, and that porting it would define the constant as PHP `null`
where `defined()` then reports `true` and suppresses a plugin's own fallback:

```python
WITHHELD_CLASS = "withheld"
```

Update `classify_defines`'s docstring to state the third outcome. Keep the
existing sentence about auto-excluded values being dropped — it still holds,
and it is now also what protects a withheld name from carrying a `None` value
downstream.

**Verify**: `uvx pytest -q tests/test_classify.py` → exit 0 (existing tests
still pass; you add the new ones in step 4).

### Step 2: Reject a `None` define value at the writer's boundary

In `scripts/wpconfig_block.py`, inside `_defines` (currently lines 121-164),
add a rejection for a record whose `value` is `None`, alongside the existing
rejections for a bad name, a duplicate name, and a smuggled `DISABLE_WP_CRON`.

Place it after the name validation and before the duplicate check, so the
message can name the define. Raise `WpConfigBlockError` with a message that
says what happened and what it would have caused — match the voice of the
neighbouring messages at `scripts/wpconfig_block.py:154-160`. For example:

```python
        # A withheld value never becomes a define: the Extractor masks a value
        # it will not disclose to null, and writing define('NAME', null) makes
        # defined('NAME') report true, suppressing the plugin's own fallback.
        if record.get("value") is None:
            raise WpConfigBlockError(
                f"{context}: '{name}' has no value (the Extractor withheld it); "
                "a withheld define is never ported"
            )
```

Then update the module docstring (`scripts/wpconfig_block.py:5-41`) to state
this rejection alongside the ones it already documents.

This is defence in depth, not the primary mechanism: after step 1 a withheld
define never reaches this helper through the normal path. It exists because
this file writes a fatal-sensitive config, and because a caller that hand-built
its `defines` list — which the SKILLs forbid but cannot prevent — must fail
loud rather than write `null`.

**Verify**: `uvx pytest -q tests/test_wpconfig_block.py` → this will FAIL on
exactly one test, `test_scalar_literals_render_bare`
(`tests/test_wpconfig_block.py:325-350`), which feeds `{"name": "A_NULL",
"value": None}` and asserts it renders as bare `null`. That failure is
expected and step 3 resolves it. If **any other** test fails, that is a STOP
condition.

### Step 3: Amend the one test that asserted the old behaviour

`tests/test_wpconfig_block.py:325-350`, `test_scalar_literals_render_bare`,
currently pins the behaviour this plan reverses. Read the whole test first.

Amend it so it no longer feeds a `None` value: keep every other scalar case it
covers (bool, int, float, string) exactly as they are, and remove only the
`{"name": "A_NULL", "value": None}` record and its assertion.

Do **not** delete the test, and do not weaken any other assertion in it. The
`None` case moves to its own new test in step 4, asserting the rejection.

**Verify**: `uvx pytest -q tests/test_wpconfig_block.py` → exit 0, all pass.

### Step 4: Add the tests

Model the new tests on the file they go in — same imports, same helper
functions, same naming (`test_<what_is_true>`), same use of a plain dict
payload piped through the module's public function.

**`tests/test_classify.py`** — model on the existing define tests (find them
with `grep -n "define" tests/test_classify.py`). Add:

1. A portable-looking define with a `null` value is classified auto-excluded
   with `class == "withheld"`, and does **not** appear in `portable`.
2. That record carries **no** `value` key — the auto-excluded shape contract.
3. A portable define with a real value (including the falsy-but-present cases
   `false`, `0`, and `""`) is still portable and still carries its value.
   This is the regression that matters most: `value is None` must not be
   confused with a falsy value.
4. A name-classified define with a `null` value keeps its **name-based** class
   (e.g. `DB_PASSWORD` stays `"credentials"`, not `"withheld"`), so the
   existing classes are not eroded by the new one.

**`tests/test_wpconfig_block.py`** — model on
`test_object_value_fails_loud` (`tests/test_wpconfig_block.py:351`). Add:

5. A define record with `"value": None` fails loud: `WpConfigBlockError`
   raised, its message naming the define.
6. A record with `"value": False` and one with `"value": 0` still render as
   `false` and `0` — the falsy-versus-absent regression again, at this
   boundary too.

**`tests/test_resolve_plan.py`** — model on the existing
`wp_config_defines` tests (`grep -n "wp_config_defines" tests/test_resolve_plan.py`).
Add:

7. A withheld define is not among the names the `wp_config_defines` gate
   offers (i.e. `live_portable_defines` does not return it), given
   classifications produced by the amended `classify_defines`.
8. A saved plan naming a define that is withheld this run has that name pruned
   from the replayed selection, and the run does not fail. This asserts the
   existing pruning at `scripts/resolve_plan.py:304-309` composes with the new
   class — it should pass without any change to `resolve_plan.py`. If it does
   not, that is a STOP condition.

**Verify**: `uvx pytest -q` → exit 0, and the reported count is **at least 8
higher** than the 942 you saw before starting.

### Step 5: Surface withheld defines to the operator in both SKILLs

The operator must learn which defines did not come down. Without it, the
failure mode simply moves: instead of a silent `null`, the plugin is silently
unconfigured.

In **`skills/clone/SKILL.md` §11 ("Cleanup and report")** and
**`skills/pull/SKILL.md` §11 ("Cleanup and report")**, add one bullet to the
report requiring that every define in `classifications.defines.auto_excluded`
whose `class` is `withheld` is listed by name, with one sentence saying the
Extractor did not disclose its value, so it was not ported and the local copy
does not define it — configure it locally if the plugin needs it.

`skills/pull/SKILL.md` §11 already reports "any surfaced define drift"; place
the new bullet beside it and keep them distinct — drift is *a new portable
define appeared*, withheld is *a define exists but its value did not come
down*. They are different reports and must not be merged.

Match the surrounding voice: these files are dense, declarative prose in
British English, and each bullet says what to do and why in the same breath.
Keep prose on one physical line per paragraph — the repo never hard-wraps
Markdown prose at a column width.

**Verify**: `uvx pytest -q` → exit 0. Several consistency suites read these
SKILL files (`tests/test_agent_delegation_consistency.py`,
`tests/test_api_version_ceiling_consistency.py`,
`tests/test_poll_discipline_consistency.py`), so a green suite is the check
that your edit did not disturb a pinned phrase.

### Step 6: Pay the documentation round

This repo charges every change of substance a documentation round, and it is
not optional (`AGENTS.md`, and the queue's rule R3). Do all five:

1. **`docs/adr/0020-withheld-define-values-are-never-ported.md`** (create).
   Follow the structure of the existing ADRs — read
   `docs/adr/0019-crm-subscribers-own-gate-default-empty.md` first and match
   its sections and length. The decision: `null` from `GET /environment` means
   *withheld*, never *the value is null*; a withheld define is classified
   auto-excluded under its own class, is never offered at the gate, is never
   written, and is named in the run report. Record the rejected alternatives
   honestly: (a) *port it as PHP `null`* — the status quo, rejected because
   `defined()` then reports `true` and suppresses the plugin's own fallback,
   turning a missing configuration value into a wrong one; (b) *treat it as
   portable but skip it silently at the writer* — rejected because the
   operator would never learn the define exists; (c) *distinguish withheld
   from null with a new wire field* — rejected because it needs an Extractor
   change and an `api_version` bump for a case that a value check settles
   client-side. Record the consequence: the client is now correct against an
   Extractor that widens what it masks, without any coordinated release.

2. **`docs/spec.md`** — the *wp-config defines* section (`docs/spec.md:198-200`)
   describes the auto-excluded class as four families. Add withheld as the
   fifth, and state that it is decided by value, not by name.

3. **`CONTEXT.md`** — add the glossary term. `CONTEXT.md:145` already defines
   the marked block; put **withheld define** near it, defined as: a production
   define whose value `GET /environment` returned as `null` because the
   Extractor would not disclose it — auto-excluded by value rather than by
   name, never ported, always reported.

4. **`CHANGELOG.md`** — add an entry under `## [Unreleased]` → `### Fixed`.
   Match the register of the entries already there: several sentences,
   naming the concrete failure and what changed, with the ADR linked. Do not
   create a new version heading and do not bump any version.

5. **Both SKILL.md files** — already done in step 5.

**Verify**: `uvx pytest -q` → exit 0, and
`uvx ruff check scripts/classify.py scripts/wpconfig_block.py tests/test_classify.py tests/test_wpconfig_block.py tests/test_resolve_plan.py`
→ exit 0.

## Test plan

Eight new cases, listed with their files and their exact assertions in step 4.
The two that carry the most weight, and must not be dropped if you trim
anything:

- **Falsy is not absent** (cases 3 and 6). `False`, `0`, and `""` are real
  values and must still port. A fix written as `if not record.get("value")`
  instead of `if record.get("value") is None` passes every other test in this
  plan and silently stops porting every define whose value is `false` — a
  common shape for a WordPress behaviour define.
- **The saved-plan replay composes** (case 8). It asserts an interaction this
  plan deliberately does not touch, which is exactly why it needs a test.

Structural pattern to follow: `tests/test_wpconfig_block.py:351`
(`test_object_value_fails_loud`) for the loud-failure shape, and the existing
define tests in `tests/test_classify.py` for the classification shape.

Verification: `uvx pytest -q` → exit 0, count ≥ 950.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `uvx pytest -q` exits 0 and reports at least 950 passed
- [ ] `uvx ruff check scripts/classify.py scripts/wpconfig_block.py tests/test_classify.py tests/test_wpconfig_block.py tests/test_resolve_plan.py` exits 0
- [ ] `grep -n 'WITHHELD_CLASS' scripts/classify.py` returns at least two matches (the constant and its use)
- [ ] `grep -n 'withheld' scripts/wpconfig_block.py skills/clone/SKILL.md skills/pull/SKILL.md docs/spec.md CONTEXT.md CHANGELOG.md` returns at least one match in **each** of the six files
- [ ] `test -f docs/adr/0020-withheld-define-values-are-never-ported.md` exits 0
- [ ] `git status --short` lists only files from the "In scope" list
- [ ] `git diff --stat -- scripts/discovery.py scripts/resolve_plan.py` is empty (neither out-of-scope script was touched)
- [ ] `plans/README.md` status row for 001 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The drift check shows any in-scope file changed since `947e28b`, and the
  "Current state" excerpts no longer match the live code.
- `classify_defines` no longer has the `portable` / `auto_excluded` shape shown
  above — the whole fix hangs on that asymmetry.
- Step 2's verification fails a test **other than**
  `test_scalar_literals_render_bare`. Something else depended on `None`
  rendering as `null`, and that dependency needs a decision, not a patch.
- Step 4's case 8 fails — the saved-plan pruning at
  `scripts/resolve_plan.py:304-309` does not compose with the new class. Do
  **not** fix it by editing `resolve_plan.py`; report instead, because the
  pruning rule belongs to issue #42 and changing it has consequences this plan
  has not weighed.
- You find yourself needing to change `scripts/discovery.py` or
  `scripts/resolve_plan.py` to make anything pass.
- You discover that the Extractor distinguishes withheld from null some other
  way (a separate flag, a sentinel string) — the whole premise of this plan is
  that `null` is the only signal there is.

## Maintenance notes

- **The one thing a reviewer must scrutinise**: that the check is
  `is None` and never a truthiness test. Everything else in this plan is
  reversible; that one confusion silently drops every `false`-valued define.
- **What will interact with this**: when the Extractor ships its allow-list,
  the *number* of withheld defines jumps from zero to potentially many. The
  report bullet from step 5 is what keeps that legible; if the list gets long
  enough to be noise, that is the moment to consider grouping it, not to
  quieten it.
- **Deliberately deferred**: nothing here lets the operator supply a value for
  a withheld define at the gate. That would mean prompting for secrets in the
  clone flow, which cuts against the engine's rule that secrets never enter
  model context. If it is ever wanted, it belongs in a separate decision with
  its own ADR — not as an extension of this one.
- **Not addressed by this plan**: the Extractor currently returns every
  non-core define from `wp-config.php` in cleartext, which is how a
  third-party API key came down on a real run. That is a server-side fix in
  `kntnt-extractor`, and this plan is what makes the client correct once it
  lands.
