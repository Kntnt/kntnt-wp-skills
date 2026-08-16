# Plan 006: Decide a define's disclosure from the `disclosure` member, never from its value

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 2734a2c..HEAD -- scripts/discovery.py scripts/classify.py scripts/wpconfig_block.py tests/test_discovery.py tests/test_classify.py skills/clone/SKILL.md skills/pull/SKILL.md docs/spec.md`
>
> Expected drift: **none**. This plan was written at the tip of `main`. If any
> of those files changed, compare the "Current state" excerpts against the live
> code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: `plans/001-refuse-to-port-a-withheld-define.md` (DONE) — this plan replaces the mechanism 001 built, and must not be executed against a tree where 001 has not landed.
- **Category**: bug
- **Planned at**: commit `2734a2c`, 2026-08-16
- **Sequenced**: the operator has placed this *after* the coordinated release and the production install. Nothing in the plan requires that ordering — every assertion here is fixture-driven — but a real API-version-7 server is available afterwards, and is worth one manual confirmation (see "Maintenance notes").

## Why this matters

The Extractor now states, per define record, *why* a value is what it is. `docs/define-disclosure.md` in `~/Projects/kntnt-extractor` is normative about how a reader must use it, and this client currently violates two of its rules: it infers a define's disclosure state from `value` alone, which the protocol says a reader MUST NOT do, and it has no notion of the protocol being absent versus present.

Two concrete consequences today. First, a define that is on the server's allow-list and whose real value is `null` is reported to the operator as *"the Extractor did not disclose its value"* — a false statement about a live production site. Second, every withheld define gets the same one-line message regardless of *why* it was withheld, even though the remedy differs sharply: a `not_allow_listed` define can be opted in by the site operator through the Extractor's own `KNTNT_EXTRACTOR_DISCLOSABLE_DEFINES` constant, while a `secret` one is withheld because the name is shaped like a credential and generally *should* stay withheld. The operator is told to "configure it locally if the plugin needs it" in both cases, which is the right advice for only one of them.

What this plan does **not** do is make any define portable that is not portable today. See "What this deliberately does not change" — the framing that consuming `disclosure` "recovers the legitimately-null case" does not survive contact with `ADR-0020`'s own argument, and this plan says so rather than quietly shipping the weaker claim.

## Current state

### The files

- `scripts/discovery.py` — builds the canonical discovery document. `build_defines()` (`:212-232`) carries each define into the document and drops the `disclosure` member on the floor.
- `scripts/classify.py` — `define_class()` (`:425-442`) classifies by name; `classify_defines()` (`:445-475`) splits into `portable` / `auto_excluded` and decides "withheld" **by value**.
- `scripts/wpconfig_block.py` — `:160-166` refuses to write a define whose value is `None`, with a message that asserts the Extractor withheld it. Unreachable today (classify never routes such a define to `portable`); it is defence in depth, and this plan must keep it that way.
- `skills/clone/SKILL.md:191` and `skills/pull/SKILL.md:193` — the run report's withheld-define paragraph.
- `docs/spec.md:200` — the normative description of the auto-excluded families.
- `docs/adr/0020-withheld-define-values-are-never-ported.md` — the decision this plan refines rather than reopens.

### The code as it stands

`scripts/discovery.py:225-232` — the `disclosure` member is not carried:

```python
    defines: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_defines):
        context = f"environment.defines[{index}]"
        name = _require(entry, "name", str, context)
        value = None if is_secret_define(name) else entry.get("value")
        defines.append({"name": name, "value": value})

    return defines
```

`scripts/classify.py:461-475` — the value-based decision this plan replaces:

```python
    portable: list[dict[str, Any]] = []
    auto_excluded: list[dict[str, Any]] = []
    for index, entry in enumerate(defines):
        context = f"defines[{index}]"
        record = _record(entry, context)
        name = _field(record, "name", str, context)
        classification = define_class(name)
        if classification is None and record.get("value") is None:
            classification = WITHHELD_CLASS
        if classification is None:
            portable.append({"name": name, "value": record.get("value")})
        else:
            auto_excluded.append({"name": name, "class": classification})

    return {"portable": portable, "auto_excluded": auto_excluded}
```

`scripts/classify.py:102` — the class constant:

```python
WITHHELD_CLASS = "withheld"
```

### The protocol you are implementing

Quoted from `~/Projects/kntnt-extractor/docs/define-disclosure.md`, because you have not read it and it is in the other repository:

- The member is `disclosure`, and it MUST be one of exactly three values: `included`, `secret`, `not_allow_listed`.
- `included` — "The value is disclosed and, when present, is the define's real, live value. `value` may still be `null` here … and that is a fact about the define, not a withholding."
- `secret` — withheld because the name matched the server's heuristic credential-shaped-name pattern. `value` is always `null`.
- `not_allow_listed` — withheld because the name is not on the server's allow-list. `value` is always `null`.
- "A reader MUST NOT infer a define's disclosure state from `value` alone; `disclosure` is the only reliable signal."
- "The set is closed. A reader MUST treat any `disclosure` value it does not recognise … as withheld."
- "**`disclosure` MUST be present on every record, including one whose value is disclosed (`included`).**" — and, critically: "A reader that finds a `defines` record without a `disclosure` member MUST treat that record as talking to a server that does not implement this protocol at all, and MUST NOT assume anything about `value` on that record beyond what it could already assume before this protocol existed."
- "A reader MUST NOT hard-code the current allow-list's membership … The same holds for the heuristic that produces `secret`."

That last rule is binding on your tests too: **do not** write a test that asserts which names the server allow-lists, or which substrings its heuristic matches. Test the client's handling of the three enum values, not the server's policy.

The absent-member rule is why this client keeps its existing value-based rule as a fallback: production still runs API version 5 in the field, this client's floor is `≥ 2` (`docs/spec.md:117`), and a pre-protocol server sends no `disclosure` at all.

### Repo conventions you must match

- Python, `uv`-run helpers, stdin JSON → stdout JSON. Docstrings are full sentences explaining *why*, not restatements of the code — see `classify.py:445-459` for the exact register expected.
- `agents.d/coding-standard/general.md` and `agents.d/coding-standard/python.md` — read both before writing code.
- Tests are named as full sentences: `test_a_withheld_define_is_auto_excluded_and_not_offered` (`tests/test_classify.py:204`). Follow that. Arrange/Act/Assert comments are used — match the surrounding file.
- Every change of substance pays a documentation round: `CHANGELOG.md`, an ADR, `docs/spec.md`, and both `SKILL.md` files where the behaviour is operator-visible. This is not optional here.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `uvx pytest -q` | exit 0, 962 passing before your change |
| One file | `uvx pytest -q tests/test_classify.py` | exit 0 |
| Lint | `uvx ruff check scripts/discovery.py scripts/classify.py tests/test_discovery.py tests/test_classify.py` | exit 0 |

**Never run `ruff check .`** — it reports pre-existing findings that are not yours. Lint only the files you touched.

## Scope

**In scope** (the only files you should modify):

- `scripts/discovery.py`
- `scripts/classify.py`
- `tests/test_discovery.py`
- `tests/test_classify.py`
- `skills/clone/SKILL.md`
- `skills/pull/SKILL.md`
- `docs/spec.md`
- `docs/adr/0023-a-defines-disclosure-is-read-from-the-protocol-member.md` (create)
- `CHANGELOG.md`

**Out of scope** (do NOT touch, even though they look related):

- `scripts/wpconfig_block.py` — its `None` refusal at `:160-166` is defence in depth and must stay unreachable. If your change makes it reachable, you have made a mistake; see STOP conditions.
- `scripts/resolve_plan.py` — the gate consumes `classifications.defines.portable` and `auto_excluded` unchanged. This plan adds a member to the `auto_excluded` records and changes nothing about their shape otherwise.
- The API-version floor and ceiling in `docs/spec.md:117`. A separate, operator-owned decision.
- `scripts/discovery.py`'s `is_secret_define()` / `SECRET_DEFINE_NAMES` — the client's own second-line redaction. It stays exactly as it is; it is not a mirror of the server's policy and must not be made one.

## Git workflow

- Trunk-based: commit straight to `main`. No branch, no PR.
- One commit for the whole plan is fine; the message is a full sentence in the imperative naming what changed and why, matching `git log --oneline -5`.
- Do **not** push, tag, or bump a version.

## Steps

### Step 1: Carry `disclosure` into the canonical document

In `scripts/discovery.py`'s `build_defines()` (`:212-232`), carry the member through when the server sent one, and omit the key entirely when it did not. Omission is meaningful — it is how the downstream classifier distinguishes a pre-protocol server from one that sent a value — so do **not** default it to a string.

Target shape:

```python
    defines: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_defines):
        context = f"environment.defines[{index}]"
        name = _require(entry, "name", str, context)
        value = None if is_secret_define(name) else entry.get("value")
        record: dict[str, Any] = {"name": name, "value": value}
        disclosure = entry.get("disclosure")
        if isinstance(disclosure, str):
            record["disclosure"] = disclosure
        defines.append(record)

    return defines
```

Note the `isinstance` guard rather than a membership test against the three known values: an unrecognised *string* must reach the classifier so the classifier can apply the protocol's "treat as withheld" rule. A non-string is malformed and is dropped to the pre-protocol path.

Extend the docstring to say why the key is omitted rather than defaulted, and update the module docstring's define paragraph (`:20-21`) to mention that the disclosure discriminator rides along.

**Verify**: `uvx pytest -q tests/test_discovery.py` → exit 0.

### Step 2: Classify from `disclosure`, with the pre-protocol fallback

In `scripts/classify.py`:

1. Replace the single `WITHHELD_CLASS` constant block (`:94-102`) with the class constant **plus** the protocol's enum, and keep the comment's explanation of the `defined()` harm — it is still the reason, and it is load-bearing:

```python
# The three values the Extractor's define-disclosure protocol defines. The set
# is closed: any other value — including one a future Extractor introduces —
# is treated as a withholding, because a reader that guessed at an unknown
# state could port a value the server declined to disclose.
DISCLOSURE_INCLUDED = "included"
DISCLOSURE_WITHHELD = frozenset({"secret", "not_allow_listed"})
```

2. Add a helper beside `define_class()` that answers the protocol question and nothing else:

```python
def disclosure_class(record: dict[str, Any]) -> str | None:
    """Classify one define by the Extractor's disclosure discriminator, or
    ``None`` when the record carries no verdict this helper can act on.

    Three outcomes, in the protocol's own terms. A record with no
    ``disclosure`` member at all comes from an Extractor that predates the
    protocol; the caller falls back to the pre-protocol rule for it, which is
    the only thing that can be assumed about such a record. A recognised
    withholding, or any value this client does not recognise, is a
    withholding — the enum is closed, so an unknown fourth value is treated
    exactly as ``secret`` is rather than optimistically read as a disclosure.
    ``included`` is the one verdict that is not a withholding, and it is
    reported as such even when the value is ``null``: on this protocol that
    is a fact about the define, not a masking.
    """

    disclosure = record.get("disclosure")
    if not isinstance(disclosure, str):
        return None
    if disclosure == DISCLOSURE_INCLUDED:
        return DISCLOSURE_INCLUDED
    return WITHHELD_CLASS
```

3. Rewrite `classify_defines()`'s loop body so the name-based classes still win first, then the protocol decides, then the pre-protocol fallback applies only when the protocol said nothing. Carry the raw discriminator as a `reason` on the auto-excluded record so the report can state *why*:

```python
    portable: list[dict[str, Any]] = []
    auto_excluded: list[dict[str, Any]] = []
    for index, entry in enumerate(defines):
        context = f"defines[{index}]"
        record = _record(entry, context)
        name = _field(record, "name", str, context)
        classification = define_class(name)
        reason: str | None = None
        if classification is None:
            verdict = disclosure_class(record)
            if verdict == WITHHELD_CLASS:
                classification = WITHHELD_CLASS
                reason = record.get("disclosure")
            elif verdict is None and record.get("value") is None:
                # No protocol verdict: a pre-protocol Extractor, where a null
                # value is the only signal a withholding ever had.
                classification = WITHHELD_CLASS
                reason = "value_withheld_pre_protocol"
            elif record.get("value") is None:
                # Disclosed, and the disclosed value is null. Not a
                # withholding — but still never written; see ADR-0023.
                classification = WITHHELD_CLASS
                reason = "disclosed_null"
        if classification is None:
            portable.append({"name": name, "value": record.get("value")})
        else:
            excluded: dict[str, Any] = {"name": name, "class": classification}
            if reason is not None:
                excluded["reason"] = reason
            auto_excluded.append(excluded)

    return {"portable": portable, "auto_excluded": auto_excluded}
```

Read the third branch carefully before writing it: **a disclosed `null` is still not ported.** That is deliberate and is the subject of ADR-0023 in step 4. Writing `define('NAME', null);` makes `defined('NAME')` return `true` and suppresses the owning plugin's not-configured fallback — and that harm is identical whether the `null` was the server's mask or production's real value. What changes is only that the operator is now told the truth about which one it was.

Update `classify_defines()`'s docstring to describe the three-way decision and to state that `reason` is present on a withheld record and absent on a name-classified one.

**Verify**: `uvx pytest -q tests/test_classify.py` → exit 0 (existing tests still pass; the value-based tests at `:204-258` all exercise records with no `disclosure` member, so they exercise the fallback path unchanged).

### Step 3: Add the tests

In `tests/test_classify.py`, beside the existing withheld tests at `:204-258`, add:

1. `test_a_secret_disclosure_is_withheld_with_its_reason` — a portable-by-name define with `{"value": None, "disclosure": "secret"}` lands in `auto_excluded` with `class == "withheld"` and `reason == "secret"`.
2. `test_a_not_allow_listed_disclosure_is_withheld_with_its_reason` — the same with `"not_allow_listed"`.
3. `test_an_unrecognised_disclosure_is_treated_as_withheld` — `{"value": "something", "disclosure": "some_future_value"}` is withheld **even though a value is present**. This is the protocol's closed-set rule and is the single most important new test in this plan.
4. `test_a_disclosed_value_is_portable` — `{"value": "/var/www", "disclosure": "included"}` is portable and carries its value.
5. `test_a_disclosed_null_is_withheld_but_not_reported_as_a_withholding` — `{"value": None, "disclosure": "included"}` lands in `auto_excluded` with `reason == "disclosed_null"`, distinguishing it from `"secret"`.
6. `test_a_pre_protocol_null_keeps_the_value_based_verdict` — no `disclosure` member, `value` is `None` → withheld with `reason == "value_withheld_pre_protocol"`.
7. `test_a_name_classified_define_ignores_its_disclosure` — a `CREDENTIAL_DEFINES` member with `"disclosure": "included"` keeps `class == "credentials"` and carries **no** `reason`. Mirrors the existing `test_a_name_classified_define_keeps_its_own_class_when_withheld` (`:250`).

In `tests/test_discovery.py`, add:

8. `test_a_defines_disclosure_rides_into_the_document` — an `environment.defines` entry carrying `"disclosure": "not_allow_listed"` appears in the built document with that member intact.
9. `test_a_define_without_a_disclosure_carries_no_disclosure_key` — assert the key is **absent**, not `None`. Use `assert "disclosure" not in record`.

Model all of them on the surrounding tests' Arrange/Act/Assert comment style.

**Verify**: `uvx pytest -q` → exit 0, **971 passing** (962 + 9). If the count differs, read why before continuing — a parametrised fixture may have absorbed one; that is fine, an unexplained difference is not.

### Step 4: Write ADR-0023

Create `docs/adr/0023-a-defines-disclosure-is-read-from-the-protocol-member.md`, matching the structure of `docs/adr/0020-withheld-define-values-are-never-ported.md` (read it first — this ADR refines 0020 and must reference it by name, not supersede it).

It must record, at minimum:

- **The decision**: a define's disclosure state is read from the `disclosure` member; the value-based rule survives only as the fallback for a pre-protocol Extractor, which this client still supports because its floor is `≥ 2`.
- **The closed-set rule** and why an unrecognised value is treated as a withholding even when a value is present.
- **Why a disclosed `null` is still not ported.** State the argument in full: the `defined()` harm ADR-0020 identified does not depend on where the `null` came from. Then state the counter-argument honestly — a faithful copy of a site that genuinely defines `null` would reproduce production's own behaviour, including its suppressed fallback — and record that this client chose not to, because the operator is told the name and can define it locally, whereas an unexplained suppressed fallback on a local copy is a debugging cost with no signal attached. **Name this as a decision that could reasonably go the other way**, so a future reader does not mistake it for a forced conclusion.
- **What this does not claim**: it does not make any define portable that was not portable before, and it does not verify the server's allow-list or heuristic — this client is forbidden from asserting either (quote the protocol's rule).

### Step 5: Report the reason to the operator

`skills/clone/SKILL.md:191` and `skills/pull/SKILL.md:193` currently say, in both files:

> List every define in `classifications.defines.auto_excluded` whose `class` is `withheld` by name, stating that the Extractor did not disclose its value, so it was not ported and the local `wp-config.php` does not define it — configure it locally if the plugin needs it

Replace that clause in **both** files with wording that branches on `reason`, because the remedy differs:

- `reason: "secret"` — the Extractor withheld the value because the name is shaped like a credential. Not ported. Configure it locally if the plugin needs it; do not ask for it to be disclosed unless it is genuinely not a secret.
- `reason: "not_allow_listed"` — the Extractor withheld the value because the name is not on that site's disclosure allow-list. Not ported. If the value is genuinely needed and is not a secret, the **site operator** can opt this specific name in on production through the Extractor's `KNTNT_EXTRACTOR_DISCLOSABLE_DEFINES` constant or its `kntnt_extractor_config_disclosable_defines` filter; otherwise configure it locally.
- `reason: "disclosed_null"` — production defines this name with the value `null`, and the Extractor disclosed that. It was **not** ported: writing `define('NAME', null);` locally would make `defined('NAME')` true and suppress the owning plugin's not-configured fallback (ADR-0023). Define it locally yourself if the local copy needs it.
- `reason: "value_withheld_pre_protocol"`, or the member absent — this Extractor predates the disclosure protocol, so the reason is not knowable; the value did not come down and was not ported.

Keep the existing surrounding sentences in `pull`'s paragraph (the define-drift distinction) intact — it is `pull`-specific and unaffected.

Keep the two files' wording **identical** for the shared part. `tests/test_agent_delegation_consistency.py` and the other consistency suites in `tests/` pin cross-surface wording; run the full suite after editing.

**Verify**: `uvx pytest -q` → exit 0.

### Step 6: Pay the rest of the documentation round

1. `docs/spec.md:200` — the sentence describing the fifth, by-value family. Rewrite it: the family is decided by the Extractor's `disclosure` discriminator, with the by-value rule surviving as the pre-protocol fallback, and reference ADR-0023 alongside the existing ADR-0020 link. Keep the paragraph on one physical line — this repository's Markdown is never hard-wrapped.
2. `CHANGELOG.md` — a `### Fixed` entry under `[Unreleased]`. State what was wrong (the client inferred disclosure state from the value, which the protocol forbids, and told the operator a define had been withheld when the server had in fact disclosed it as `null`), what changed, and what it does **not** change (no define becomes portable that was not portable before). Match the existing entries' length and register — they are long and explanatory, not one-liners.

**Verify**: `uvx pytest -q` → exit 0; `uvx ruff check scripts/discovery.py scripts/classify.py tests/test_discovery.py tests/test_classify.py` → exit 0.

## Test plan

- New tests: seven in `tests/test_classify.py`, two in `tests/test_discovery.py`, as enumerated in step 3.
- Structural pattern: `tests/test_classify.py:204-258` — the existing withheld cluster.
- The regression this plan fixes is test 5 (`disclosed_null` is no longer reported as a withholding) and test 3 (an unrecognised discriminator is not read optimistically).
- Do **not** add a test asserting which names the server allow-lists or which substrings its heuristic matches; the protocol forbids the client from binding either.
- Verification: `uvx pytest -q` → exit 0, 971 passing.

## Done criteria

ALL must hold:

- [ ] `uvx pytest -q` exits 0 with 971 passing
- [ ] `uvx ruff check scripts/discovery.py scripts/classify.py tests/test_discovery.py tests/test_classify.py` exits 0
- [ ] `grep -n 'record.get("value") is None' scripts/classify.py` shows the value test only inside the fallback branches, never as the first question asked
- [ ] `git diff --stat` lists only the files in the In-scope list
- [ ] `docs/adr/0023-a-defines-disclosure-is-read-from-the-protocol-member.md` exists and names ADR-0020
- [ ] `CHANGELOG.md` `[Unreleased]` carries the entry
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report (do not improvise) if:

- The drift check reports changes to any in-scope file, or the "Current state" excerpts do not match the live code.
- **Any define reaches `scripts/wpconfig_block.py`'s `None` refusal at `:160-166`.** That guard must remain unreachable. If a test exercises it, your `classify_defines()` is routing a null-valued define to `portable`, which this plan explicitly does not do.
- The full suite's count moves by anything other than +9 without an explanation you can state in one sentence.
- You conclude that a disclosed `null` should be ported after all. That is a defensible position, but it is a decision for the repository owner and it changes ADR-0020's conclusion — stop and report it rather than shipping it.
- `~/Projects/kntnt-extractor/docs/define-disclosure.md` no longer says what the "The protocol you are implementing" section quotes. The protocol document is the authority; this plan is a reader of it.

## Maintenance notes

- **What a reviewer should scrutinise**: that `define_class()`'s name-based verdict still wins before the discriminator is consulted (a `DB_PASSWORD` marked `included` by some future server policy must still be `credentials`, never portable); that the unrecognised-value branch treats a *present* value as withheld anyway; and that the `disclosure` key is genuinely absent — not `None` — on a pre-protocol record, since the fallback branch distinguishes the two.
- **Worth one manual confirmation against a real server** once production runs API version 7: fetch `GET /environment` and check that every `defines` record carries a `disclosure` member. The protocol's present-on-every-record rule is the one thing this client cannot verify from fixtures, and the whole fallback path is predicated on absence meaning "pre-protocol server" rather than "server bug".
- **Deliberately deferred**: nothing here binds the client's own `is_secret_define()` redaction (`scripts/discovery.py:197-209`) to the server's policy, and it should not be. The two lists answer different questions, and the agreed fix for their coupling is to bind the *protocol*, not the membership — which is what this plan does.
- **If the floor is ever raised above 6**, the pre-protocol fallback in `classify_defines()` becomes dead code and should be deleted in the same change, along with the `"value_withheld_pre_protocol"` reason and its report branch.
