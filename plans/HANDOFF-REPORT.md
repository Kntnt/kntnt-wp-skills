# Handoff report — `/improve` on kntnt-wp-skills, scoped to `clone` and `pull`

**Run date:** 2026-08-16. **Commit audited:** `947e28b` (repo `main`, clean, 8 ahead of `origin/main`). **Scope:** the `clone` and `pull` skills and the helper scripts they drive. Not the other skills in the repo, not the Extractor's server half. **Mode:** read-only on source; the only files written are under `plans/`.

**Gate at time of audit:** `uvx pytest -q` → 942 passed in 11.4 s.

---

## Findings

| # | Finding | Category | Impact | Effort | Risk | Confidence | Evidence |
|---|---|---|---|---|---|---|---|
| F1 | The documented widening of the stall window below API version 6 was never implemented. `STALL_WINDOW_SECONDS = 600` is applied unconditionally, with no argv, no environment override, and no second constant. Against production's API version 5, where `chunks_done` does not exist, a healthy job slicing one large table stands still on the coarse counters and **would be** aborted as a false stall. | bug / doc-drift | Forward-looking: `scripts/poll_extraction.py` is unreleased and absent from the installed 0.6.0, so this defect has never fired. See "Correction" below for what *did* fire. | S | LOW | HIGH | `scripts/poll_extraction.py:52`, `:360-371`; the unimplemented rule at `docs/poll-discipline.md:19` |
| F2 | A define whose value the Extractor withheld (`null` on the wire) is classified **portable**, offered at the `wp_config_defines` gate, and written as `define('NAME', null);`. `php -l` passes, the smoke test is silent, the operator is never told. | bug | `defined('NAME')` returns true, so a plugin's own "not configured" fallback never fires and it runs with a null key | M | LOW | HIGH | `scripts/classify.py:415-432`, `:453`; `scripts/resolve_plan.py:235-240`; `scripts/wpconfig_block.py:97-98`, `:220` |
| F3 | The Extractor's API version is observed once in the health check and then discarded. No artifact carries it — `grep -rn "api_version" scripts/` returns nothing — so no later step can gate on it, report it, or test against it. | bug | Every older-Extractor degradation is silent; the floor cannot be enforced anywhere but in prose | M | LOW | HIGH | `scripts/discovery.py:495-508`, `:536-582`; the prose pin at `skills/clone/SKILL.md:63`, `skills/pull/SKILL.md:64` |
| F4 | `tests/test_api_version_ceiling_consistency.py` is a documentation-consistency suite, not a contract tripwire: every assertion in it is a regex over a Markdown file checking that `≥ 2` and `≤ 6` appear. Nothing binds a behaviour, and no test ever compares a number that came off the wire. | tests | The mechanism that exists to catch version skew cannot catch it in code | — | — | HIGH | `tests/test_api_version_ceiling_consistency.py:67-116` |
| F5 | `docs/poll-discipline.md` binds the stall-window phrase as the hard-coded string `"10-minute stall window"`, while the cadence and timeout phrases beside it are derived from `scripts/poll_extraction.py`'s constants. | tech-debt | A changed constant would not redden the suite that exists to catch exactly that | S | LOW | HIGH | `tests/test_poll_discipline_consistency.py:76-84` |

| F6 | Both subagent definitions hand the orchestrator a responsibility it never discharges: on a `FAILED` return they say the verdict is shaped so "the orchestrator can cancel the still-active job rather than leave one wedged against the plugin's one-active-job rule" — but neither SKILL has any step that cancels or consumes after a `FAILED` return. `DELETE /extractions/{id}` appears in the SKILLs only in §1.3 (the *next* run's sweep) and in §7's prohibition against using it as the happy-path close. | bug | A failed or aborted phase leaves a job, and possibly a sealed artifact, on production until TTL — the exposure window §7 exists to keep "to minutes" is silently unbounded on every unhappy path | S | LOW | HIGH | `agents/extract-transfer.md:39`, `:64`; `agents/discovery-classify.md:45`; the gap at `skills/clone/SKILL.md:69`, `:123` and `skills/pull/SKILL.md:70`, `:121` |

F1's correction, and F6, were both established after the initial audit, in response to follow-up questions from the Extractor-side session. F6 is **not** yet planned — see "Correction and additions" below.

F4 and F5 are reported but not separately planned — F4 is closed in substance by plan 003, F5 is folded into plan 002 step 5. The rationale, and the findings that were considered and rejected, are in [README.md](./README.md).

**No ADR was found to have drifted from the code**, with one exception that is really F1: `docs/poll-discipline.md` — which ADR-0018 designates as the canonical statement, and which declares that "the numeric literals themselves live in `scripts/poll_extraction.py` — that is the binding" — states a rule that has no literal and no implementation. ADR-0016, ADR-0017, ADR-0005, ADR-0006, ADR-0009, ADR-0014, ADR-0015 and ADR-0019 were checked against the code they govern and match.

---

## Question 1 — does anything catch that the server is OLDER than the client?

**Short answer: a floor exists, but there is no mechanism. There are three ad-hoc handlings, decided one at a time, and one of the three was never built.**

### The floor exists, and is enforced only by prose

`skills/clone/SKILL.md:63` and `skills/pull/SKILL.md:64` pin **API version ≥ 2** in the health check's Production bullet. That is a real floor and the orchestrating model does check it. But:

- **No code enforces it.** `grep -rn "api_version" scripts/` returns nothing. Not one of the seventeen helper scripts has ever seen the number. Compare the ceiling, which is equally prose-only in enforcement.
- **The consistency suite that appears to bind it does not.** `tests/test_api_version_ceiling_consistency.py:67-116` — every assertion is a regex over a Markdown file asserting the strings `≥ 2` and `≤ 6` are present. It is an anti-drift binding for documentation. Nothing compares a wire value.
- **The floor is five versions below what the client assumes.** It sits at 2 while the client depends on features introduced at 4, 5 and 6.

### The three older-server degradations, and their actual state

| Degradation | Below | Handled? | Where |
|---|---|---|---|
| No `authenticated_as` / `capabilities` in `GET /status` | API 4 | **Yes** — a documented wrong-password discriminating test | `skills/clone/SKILL.md:67`, `skills/pull/SKILL.md:68` |
| No `progress.chunks_done` | API 6 | **No** — documented, never implemented (F1) | rule at `docs/poll-discipline.md:19`; code at `scripts/poll_extraction.py:52`, `:360-371` |
| `strict: false` silently ignored | the version that added it | **Deliberately degraded**, but not reported | `CHANGELOG.md` `[Unreleased]`; server side at `~/Projects/kntnt-extractor/classes/Rest/Extractions_Controller.php:772` |

The middle row is the one that has actually bitten. Production runs API version 5, so `chunks_done` is absent on every real run. The poller detects that absence correctly (`scripts/poll_extraction.py:464-471`) and logs it — and then does nothing with it, because `STALL_WINDOW_SECONDS = 600` is applied unconditionally at `scripts/poll_extraction.py:362`. On a 186-table site, the coarse counters stand still for minutes on a completely healthy job, and the poller returns verdict `stall` and exits 4.

The third row deserves care, and I want to be explicit that it is **not** a finding. `CHANGELOG.md`'s `[Unreleased]` entry already settled it: "`strict` defaults to today's hard fail on an older Extractor that ignores the member, and the new fields are additive, so the verified API-version ceiling stays ≤ 6." The degradation is safe — it is the previous behaviour, not a new failure mode. What is missing is only that the operator is never told the mitigation is inert on their host. Worth one bullet in a report; not worth a plan.

One fact the Extractor side will want: **no version number distinguishes an Extractor that honours `strict` from one that ignores it.** `strict` is implemented at `~/Projects/kntnt-extractor/classes/Rest/Extractions_Controller.php:772` while `~/Projects/kntnt-extractor/classes/Rest/Status_Controller.php:87` holds `API_VERSION = 6` unchanged. That was a deliberate choice, and its consequence is that no client-side check can ever discover the difference.

### What a real floor costs, and where it belongs

**Where it belongs — the answer in one line:** `scripts/discovery.py:495-508`, `build_document`. The canonical discovery document is the one artifact every later phase reads, and it is where "what production is" is already recorded. The version is a fact about the control channel, so it belongs as a top-level sibling of `environment` (the document's shape is at `scripts/discovery.py:536-582`), not inside it.

**What it costs:** small, and in two separable halves.

1. **The plumbing** — carry `api_version` from the health check's `GET /status` through the `discovery-classify` task envelope into `build_document`, and report the degradations in both SKILLs' §11. Effort M, risk LOW, no coordination with the Extractor, no `api_version` bump. Two envelope constructions in the test suite need the new key (`grep -n '"environment":' tests/*.py`). **This is plan 003**, and it is written to be safe to land today.

2. **Raising the floor itself** — I deliberately did **not** plan this, and plan 003 explicitly forbids its executor from touching the literal. Raising the floor to reflect what the client actually assumes would **refuse production**: `safeteam.se` runs Extractor 0.4.0 at API version 5, and a floor of 6 stops every run against it until the pending coordinated release is cut *and* manually installed through wp-admin. That is an operational decision that belongs to Thomas and to the Extractor side's own queue, not something to land as a side effect of plumbing.

What plan 003 buys is that the decision becomes informed: after one run, the report names the version and lists what it degraded, instead of the operator inferring it from four Markdown surfaces.

**A note on the right signal.** For the stall window specifically, gating on the *observed absence* of `chunks_done` beats gating on a version number — it is correct against any Extractor, needs no plumbing, and cannot disagree with reality. Plan 002 is written that way deliberately, and plan 003 forbids making the poller version-aware. The floor and the plumbing are for reporting and for refusal, not for behaviour switching.

---

## Question 2 — the mirrored secret list

`kntnt-extractor`'s `classes/Rest/Environment_Controller.php:45` says its redaction family "Mirrors kntnt-wp-skills's `is_secret_define()`".

### Where the copy is

**`scripts/discovery.py:193-205`** — `is_secret_define()`, reading the frozenset **`SECRET_DEFINE_NAMES` at `scripts/discovery.py:88-100`** (`DB_PASSWORD` plus the eight auth keys, salts and nonces), plus the two patterns `name.endswith("_SALT")` and `name.startswith("NONCE_")`. Applied at `scripts/discovery.py:225`.

Nothing binds the two repositories. No test, no fixture, no shared file, and no sentence in either repo's documentation that mentions the pair exists — the docblock comment at `Environment_Controller.php:45` is the only record anywhere that there is a mirror to keep in step.

**There is also a second, drifted copy inside this repo**, which matters for anyone planning the allow-list: `scripts/classify.py:64-92` (`CREDENTIAL_DEFINES`, `SALT_NONCE_DEFINES`) and `scripts/classify.py:415-432` (`define_class`) apply the same `_SALT` / `NONCE_` patterns again, over a *different* name set. They are not the same list and are not meant to be — `discovery.py` decides what may enter the document, `classify.py` decides what may be ported — but the overlap is undocumented, so a change to one reads like it should be applied to the other. That is three copies of a rule with nothing holding them together.

### What `clone` / `pull` do with a define whose value is `null`

They port it as PHP `null`. The chain, in order:

1. `scripts/discovery.py:225` — `value = None if is_secret_define(name) else entry.get("value")`. A value that arrived already `null` passes straight through as `None`.
2. `scripts/classify.py:415-432` — `define_class()` decides on the **name alone**. A name matching none of the four auto-excluded families returns `None`.
3. `scripts/classify.py:453` — `portable.append({"name": name, "value": record.get("value")})`. **No value check.** The define is now portable, carrying `None`.
4. `scripts/resolve_plan.py:235-240` — `live_portable_defines()` returns every portable name, so the define is offered at the `wp_config_defines` gate like any other.
5. `scripts/wpconfig_block.py:97-98` — `if value is None: return "null"`, rendered into the block at `scripts/wpconfig_block.py:220`.

Result: `define('SOME_API_KEY', null);` in the local `wp-config.php`. `ddev exec php -l wp-config.php` passes. `scripts/smoke_test.py` checks no define values at all.

**This is worse than the define being absent.** `defined('SOME_API_KEY')` returns `true`, so a plugin's own "not configured" fallback never fires; it runs with a null key and fails somewhere far from the cause.

### Is the operator told which defines were held back?

**No. Nowhere.** Not at the gate — `live_portable_defines` (`scripts/resolve_plan.py:235-240`) returns names only, with nothing marking a name whose value is missing. Not in the report — `clone` §11 and `pull` §11 report the search-index outcome, the rollback backup, the trash path, the object-cache outcome, and (at pull) portable-define *drift*, which is a different thing entirely: drift is *a new portable define appeared on production*, not *this define's value did not come down*.

### Why it is latent today, and why that ends

Every name the Extractor currently masks (`DB_PASSWORD`, the auth keys, the salts, the nonces) is **also** routed to the auto-excluded class by `scripts/classify.py:424-431`. So no masked value has ever reached the writer. That is a coincidence of two independently-maintained lists happening to agree — not a mechanism.

The allow-list ends it. Once the Extractor returns `null` for every non-core define it does not recognise, the withheld set stops being a subset of the client's auto-excluded set, and step 3 above starts firing on real plugin defines. `KNTNT_PAPAPI_KEY` is a live example: it is one of the seven portable defines the settled `safeteam.se` plan accepts, and it matches none of `classify.py`'s four auto-excluded families.

There is one deeper point worth carrying into the Extractor's own planning: **`null` on the wire is overloaded.** `docs/spec.md:118` and `docs/spec.md:339` both define it as the masking value, and the client also reads it as a literal value. Those two meanings have never collided only because of the coincidence above.

### What needs to change

Planned in full as **[plan 001](./001-refuse-to-port-a-withheld-define.md)**. In summary:

- **`scripts/classify.py`** — a define that would be portable but whose value is `None` is classified auto-excluded under a new class `"withheld"`. This removes it from the gate for free, because `resolve_plan.py` reads `portable` and nothing else, and the saved-plan pruning at `scripts/resolve_plan.py:304-309` then drops it from a replayed selection automatically.
- **`scripts/wpconfig_block.py`** — reject a `None` define value loudly at the `_defines` boundary (`scripts/wpconfig_block.py:121-164`), as defence in depth on a fatal-sensitive file. This reverses one existing test, `tests/test_wpconfig_block.py:325-350`, which currently pins `null` rendering as bare `null`; the plan amends it explicitly.
- **Both SKILLs' §11** — report every withheld define by name, kept distinct from the existing define-drift report.
- **The documentation round** — a new ADR-0020, `docs/spec.md`'s auto-excluded families (currently four, becoming five, and the fifth decided by value rather than by name), a `CONTEXT.md` glossary entry for *withheld define*, and `CHANGELOG.md`.

The plan's own test plan flags the one way to get this wrong: writing the check as `if not record.get("value")` instead of `if record.get("value") is None` passes everything else and silently stops porting every define whose value is `false` — a common shape for a WordPress behaviour define.

**Client-side only. No coordination, no `api_version` bump, and it can land before the Extractor's allow-list rather than after** — which is the sequence that matters, since after is one production clone too late.

---

## Plans written

| Plan | Title | Priority | Effort | Answers |
|---|---|---|---|---|
| [001](./001-refuse-to-port-a-withheld-define.md) | Refuse to port a define whose value the Extractor withheld | P1 | M | Question 2 |
| [002](./002-widen-the-stall-window-when-chunks-done-is-absent.md) | Widen the stall window when `chunks_done` is absent | P1 | S | F1, and the live half of Question 1 |
| [003](./003-carry-the-extractor-api-version-into-the-discovery-document.md) | Carry the Extractor's API version into the discovery document and report what it degrades | P2 | M | Question 1's "what does a floor cost, and where does it belong" |
| [004](./004-raise-the-verified-api-version-ceiling-to-7.md) | Raise the verified Extractor API-version ceiling from 6 to 7 | P1 | S+M | the cross-repo release gap (depends on 001) |
| [005](./005-close-the-cleanup-handoff-on-every-failure-path.md) | Close the cleanup handoff on every failure path | P2 | M | F6 |

004 depends on 001; the other four are independent and touch disjoint files. None touch the adaptation family (host-limit raising, budget halving, the attempt counter, the floor), so none are blocked by rule R1. Each plan carries its own documentation round per rule R3. The cross-repo release order is in [README.md](./README.md).

---

## What I deliberately did not do

- **Did not raise the API-version floor.** It refuses production until the pending coordinated release ships and is installed by hand. Thomas's decision, and plan 003 forbids its executor from touching the literal.
- **Did not plan `strict: false` as a defect.** The degradation is deliberate and recorded in `CHANGELOG.md`; treating a settled tradeoff as a finding is exactly what the audit rules forbid. It survives as one reporting bullet inside plan 003.
- **Did not plan anything in the adaptation family** — host-limit raising, budget halving, the attempt counter, the floor, or recovery on top of them. Rule R1 freezes it pending the measurement in queue task 6, and nothing I found argues for reopening that.
- **Did not build the fail-fast packaging probe** (queue task 12) or touch P5, P6, P9. All are parked behind triggers that have not fired; rule R2 keeps them out.
- **Did not plan a cross-repo binding for the mirrored secret list.** A test that pins `scripts/discovery.py`'s list against a checked-in copy of the Extractor's is buildable, but it would bind this repo to a snapshot of the other rather than to the other, and plan 001 makes the client correct *whatever* the Extractor masks — which is the more robust answer. If a binding is still wanted, it belongs on the Extractor side, where the allow-list is the thing being changed.
- **Did not audit the other skills** (`mkwp`, `build-ollie-site`), the Extractor's server half, or `scripts/smoke_test.py` beyond checking whether it verifies define values (it does not). Out of the commissioned scope.
- **Did not run anything against production.** No call was made to `safeteam.se`. The only commands run were `git`, `grep`, and the repository's own read-only test gate.
- **Did not modify any source file.** The only files written this run are the four under `plans/`.

## Correction and additions (2026-08-16, after Extractor-side follow-up)

### Correction: I overstated F1's history, and I am retracting it

My first write-up called the unconditional stall window "the false-stall abort that has been costing you healthy runs at api 5". **That was wrong, and the error is exactly the kind this project's own rules warn about — a confident diagnosis stated ahead of its evidence.** `scripts/poll_extraction.py` was added in `177420d`, is unreleased, and is absent from the installed 0.6.0. It cannot have caused any historical failure. F1 is forward-looking.

What the evidence does support, separated observed from inferred:

**Observed, in code.** The installed 0.6.0 — the client that actually ran — had no `chunks_done` concept at all (`grep -rn "chunks_done"` across the whole installed tree returns nothing). Its poll rule, at `~/.claude/plugins/cache/kntnt-wp-skills/kntnt-wp-skills/0.6.0/skills/clone/SKILL.md:106` and `.../pull/SKILL.md:104`, defines an advance as "its `state` changed or the sum `progress.tables_done + progress.files_done` increased", and terminates on "no advance within the 10-minute stall window, **or exhaustion of the overall budget**", with `poll_max_wait_seconds: 3600` (also `.../agents/extract-transfer.md:27`). So 0.6.0 carried **two** independent client-side abort mechanisms on a healthy job, not one.

**Observed, in the project record.** `~/Projects/kntnt-transfer-engine-open-work.md` task 11 documents that the second of those fired: the last extraction packaged 186 tables in 261 s, settled at ~4.75 files/s putting the file phase near 2.9 hours, "the budget expired at less than a quarter of a healthy, visibly-advancing job, and the run had to be re-polled by hand". The queue is explicit that this was a false abort — "nothing was wrong, the site is simply large". It also records the stall window's symptom being observed and hand-mitigated: `3/186` standing still for minutes on a healthy run, "worked around by widening the stall window to 2400 s".

**What the evidence does not settle.** Whether the *stall window* (as opposed to the budget) ever terminated a run. "Worked around" says it was anticipated and mitigated, not that it killed anything, and I found no CHANGELOG entry, issue, or doc note recording a run lost to it. I have no run logs and did not look for any outside the repository.

**So neither reading (a) nor (b) is right, and the Extractor side should not write this up as a fourth unweighed candidate.** A client-side false abort on a healthy production run is real and documented — but it is the 3600 s wall-clock budget, it is already diagnosed as queue task 11, it is already fixed in the working tree (`e8cbffc`, `180d11a`, unreleased), and the run it hit was recovered by hand rather than lost. It is not a competing explanation for the two failed runs; the queue attributes those elsewhere and I found nothing contradicting that. What *is* newly worth saying is narrower and still useful: **at 0.6.0 the client had two false-abort mechanisms of the same family, one of which is documented to have fired, which is a reason to distrust any historical "the run died" account that did not record which side gave up first.**

### Addition: F6, the unclosed cancel handoff

Established while answering the same follow-up. Both subagent definitions shape their `FAILED` verdict explicitly so the orchestrator can clean up — `agents/extract-transfer.md:39` ("so the orchestrator can cancel the still-active job instead of leaving one wedged against the plugin's one-active-job rule") and `agents/discovery-classify.md:45` ("so the orchestrator can consume or cancel the still-active job"). Neither SKILL discharges it. `DELETE /extractions/{id}` occurs in `skills/clone/SKILL.md` only at `:69` (the next run's sweep) and `:123` (the prohibition), and identically in `skills/pull/SKILL.md` at `:70` and `:121`.

Three concrete leaks follow, all client-side:

- **A failed unseal never consumes.** `agents/extract-transfer.md:64` makes an unseal failure `FAILED`; the artifact stays published on production until TTL.
- **An exhausted stall window never cancels.** The job keeps running against the one-active-job rule, and the next run's §1.3 sweep is the only thing that clears it — which is fine for a *non-terminal* job but, per the Extractor side, `GET /extractions` lists only non-terminal jobs, so a job that has since *failed* is invisible to my sweep too.
- **A failed bootstrap deliberately leaves a cleartext dump on local disk.** `agents/discovery-classify.md:51`: "On a `FAILED` bootstrap, leave the dump in place for diagnosis". That dump holds real user and subscriber rows, and §11's cleanup sweep only runs on a completed run — which by definition this is not. This one is a deliberate decision, not an oversight, but it is undocumented outside the agent file and deserves an explicit expiry or an operator warning.

**F6 is now planned as `plans/005-close-the-cleanup-handoff-on-every-failure-path.md`.** It was held back only until the Extractor side settled plan 013's reclamation semantics; those arrived on 2026-08-16 (consume and cancel take the per-job tick lock; the sweep reclaims an ownerless served artifact; `GET /extractions` gains a `state` parameter admitting terminal jobs). Plan 005 is written so none of that is a prerequisite — it must work against production's current 0.4.0.

One correction to leak 3, from field evidence gathered on Thomas's disk on 2026-08-16: **it did not fire on the paused `safeteam.se` run.** `bootstrap.sql`, `bootstrap.key` and `bootstrap.container` were all absent while `unseal_config.json` still named them — the bootstrap succeeded, so the success path cleaned up as designed. The leak is real in code and unproven in practice. That is not a downgrade: the failure path is the one the redone clone will exercise deliberately.

### Addition: plan 004, the ceiling raise

Also established in cross-repo review. The Extractor's plan 008 bumps `API_VERSION` 6 → 7, which trips this client's verified ceiling — at 7 the client refuses to run at all, correctly and by design. Raising it is a multi-file edit (`tests/test_api_version_ceiling_consistency.py:41` plus the literal `≤ 6` on four pinning surfaces, **twice each** in the two SKILLs) that the suite refuses until every surface follows. None of plans 001–003 does it, deliberately — I kept the version literals out of scope.

It is now `plans/004-raise-the-verified-api-version-ceiling-to-7.md`, and it carries a **hard dependency on 001**: raising the ceiling *is* the declaration that this client is correct against version 7, and that declaration is false until the withheld-define fix has landed. The plan's centre of gravity is its verification step, not its edit — the edit is six literals; the value is in establishing, and recording in the plan file, what actually changed between 6 and 7 and whether any of it touches the artifact contract `scripts/unseal.py` reassembles.

## One thing to keep in mind when reading any of this

The **installed** skills plugin is `0.6.0`, at `~/.claude/plugins/cache/kntnt-wp-skills/kntnt-wp-skills/0.6.0/`. I verified it: **it has no `scripts/poll_extraction.py` at all.** A clone run today therefore writes its poll loop from prose, and plan 002's fix — like everything else closed in 0.7.0 through 0.9.0 — is absent from the client that would actually run it. Every finding above is against the repo at `947e28b`; the gap to what is installed is queue tasks 3 and 4, not mine to close.
