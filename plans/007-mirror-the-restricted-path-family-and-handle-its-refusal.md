# Plan 007: Mirror the Extractor's widened restricted-path family, and handle its refusal instead of crashing on it

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 2734a2c..HEAD -- scripts/build_exclusions.py scripts/filter_manifest.py scripts/baseline_diff.py agents/extract-transfer.md skills/clone/SKILL.md skills/pull/SKILL.md tests/test_build_exclusions.py`
>
> Expected drift: **none**. This plan was written at the tip of `main`. If any
> of those files changed, compare the "Current state" excerpts against the live
> code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none in this repository. **Release-sequenced**: this must land and be installed *before* `~/Projects/kntnt-extractor`'s `plans/016-close-the-restricted-path-gaps.md` reaches production. Landing it early is harmless — every pattern added here is a file this client already had no business transferring.
- **Category**: bug
- **Planned at**: commit `2734a2c`, 2026-08-16

## Why this matters

The Extractor refuses a `POST /extractions` whose selection names a restricted path — `422 kntnt_extractor_restricted_path`, with every offender in `data.paths`, and **the whole create is rejected, not the offending file**. That behaviour exists today (`classes/Rest/Extractions_Controller.php:867` in `~/Projects/kntnt-extractor`) and is correct: the server is the last party that can guarantee a site's secrets stay on the site, and it does not trust the caller to filter.

This client has two problems against that. First, its own pre-filter carries a **stale copy** of the pattern family, so it will hand the server paths the server is about to start refusing. Second — verified, not assumed — `grep -rn "kntnt_extractor_restricted_path"` over this repository's runtime surface returns **nothing**: the client has no handling of that error code anywhere. `agents/extract-transfer.md:41` enumerates the failure codes and describes `422` only as "malformed or overlapping selection".

The concrete break, once the Extractor's widened list ships: a site carries a `wp-config.old` left over from a manual edit, or an `id_ed25519` key at the install root → this client's pre-filter does not recognise the shape and includes it in `files` → the server rejects the entire create → the client hits an error code it has never seen, at the exact step that was supposed to start a multi-hour transfer. **A clone that worked yesterday fails today, on an error nobody wrote a message for.**

Note what this plan is *not*. It does not improve the security guarantee — that guarantee never depended on this client being correct, which is the whole reason it is enforced server-side. What it fixes is availability and diagnosability for the one production consumer of this API.

## Current state

### Where the mirror actually lives — one place, not three

The Extractor's plan 016 describes the client as keeping "three independent copies" of these patterns. That is not quite right, and the correction makes this plan much smaller than it would otherwise be. Verified against the live code:

- **The pattern tuples are single-source**, in `scripts/build_exclusions.py:59-102`. Nothing else defines them.
- **The matching logic is duplicated**, in `scripts/filter_manifest.py:124-148` and `scripts/baseline_diff.py:248-272` — two byte-identical `is_excluded()` implementations, each consuming the resolved exclusion set as *data*. Their duplication is already pinned by `tests/test_exclusion_matching_consistency.py`.

So widening the family is a **one-file change**, and the two matchers need no edit at all.

`scripts/build_exclusions.py:59-102` as it stands:

```python
_CONFIGURATION_FILE: tuple[str, ...] = ("wp-config.php",)

_CONFIGURATION_FILE_VARIANTS: tuple[str, ...] = (
    "wp-config.php.*",
    "wp-config.php~",
    ".wp-config.php.sw?",
    "wp-config-*.php",
)

_ENV_FILES: tuple[str, ...] = (
    "**/.env",
    "**/.env.*",
)

_ROOT_SQL_DUMPS: tuple[str, ...] = (
    "*.sql",
    "*.sql.gz",
    "*.sql.zip",
)

_ROOT_KEY_MATERIAL: tuple[str, ...] = (
    "*.pem",
    "*.key",
    "id_rsa*",
)
```

`scripts/filter_manifest.py:72-74` and `scripts/baseline_diff.py:194-196` each carve `wp-config-sample.php` back out via `_ALWAYS_ALLOWED`, so the broad `wp-config-*.php` catcher does not swallow WordPress' own bundled template. **Do not disturb that carve-out** — every pattern you add must leave `wp-config-sample.php` transferable.

### What the server's list is becoming

From `~/Projects/kntnt-extractor/plans/016-close-the-restricted-path-gaps.md` step 1, which is the authority. The server adds, as PCRE against a *basename*:

```
/^\.wp-config\.php(\..+)?$/i          Vim swap files: .wp-config.php.swp, .swo, .swn, ...
/^#wp-config\.php#$/i                 Emacs auto-save file
/^\.#wp-config\.php$/i                Emacs lock file
/^wp-config\.(?:bak|old|orig|save)(?:\.php)?$/i    reordered backup names
```

and replaces its `id_rsa` root-only pattern with:

```
/^id_(?:rsa|dsa|ecdsa(?:-sk)?|ed25519(?:-sk)?)/i   OpenSSH's default key basenames, prefix match
```

Where this client already stands relative to that: `.wp-config.php.sw?` covers the Vim family already (it is in fact slightly *ahead* of the server's current list). It has nothing for the Emacs shapes, nothing for the reordered backup names, and only `id_rsa*` of the SSH key types.

### The error this client must handle

`422` with `code == "kntnt_extractor_restricted_path"` and `data.paths` naming **every** offending path (not just the first). The code, the status, and the `data.paths` shape are all unchanged by the server's widening — only which selections trigger it widens. This is exactly the shape the client already handles for the `404` case at `agents/extract-transfer.md:41`, where "A `404` now names every missing table in `data.tables` and every missing file in `data.files`".

`agents/extract-transfer.md:41` as it stands:

> A `422` (malformed or overlapping selection), `400` (invalid public key), `404` (unknown *table*, or a file the plugin would not skip — a traversal, or a selection that was only vanished files), `403` (capability), or `429` (a job is already active — the sweep or a bootstrap did not finish) is a hard stop: return `FAILED` with the status and body, never a retry.

### Repo conventions you must match

- `scripts/build_exclusions.py`'s pattern tuples each carry a comment paragraph explaining *what real-world tool produces that shape* and why it is credential-bearing. Match that register — see `:63-72` for the exemplar. A pattern added without that explanation will not survive review.
- Patterns here are **fnmatch-style globs**, not PCRE. Do not transliterate the server's regexes; express the same shapes as globs, and prove they match with tests.
- Markdown paragraphs are never hard-wrapped — one physical line per paragraph.
- Every change of substance pays a documentation round: `CHANGELOG.md`, an ADR where a decision is made, `docs/spec.md` where the normative description moves, and both `SKILL.md` files where behaviour is operator-visible.
- `agents.d/coding-standard/general.md` and `agents.d/coding-standard/python.md` — read before writing code.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Full suite | `uvx pytest -q` | exit 0, 962 passing before your change |
| One file | `uvx pytest -q tests/test_build_exclusions.py` | exit 0 |
| Consistency | `uvx pytest -q tests/test_exclusion_matching_consistency.py` | exit 0 |
| Lint | `uvx ruff check scripts/build_exclusions.py tests/test_build_exclusions.py` | exit 0 |

**Never run `ruff check .`** — it reports pre-existing findings that are not yours.

## Scope

**In scope**:

- `scripts/build_exclusions.py`
- `tests/test_build_exclusions.py`
- `agents/extract-transfer.md`
- `skills/clone/SKILL.md`
- `skills/pull/SKILL.md`
- `docs/spec.md`
- `docs/adr/0024-a-restricted-path-refusal-drops-the-named-paths-and-resubmits-once.md` (create)
- `CHANGELOG.md`

**Out of scope**:

- `scripts/filter_manifest.py` and `scripts/baseline_diff.py` — they consume the pattern family as data. If you find yourself editing either, you have misread the architecture; see STOP conditions.
- `_ALWAYS_ALLOWED` in either matcher — `wp-config-sample.php` must stay transferable.
- Any attempt to mirror the server's PCRE patterns literally, or to assert this client's list equals the server's. The lists serve different questions (what this client declines to *ask for* versus what the server declines to *give*), and one is not required to be the other. Binding them would create a false contract across two independently released repositories.
- The API-version floor and ceiling.

## Git workflow

- Trunk-based: commit straight to `main`. No branch, no PR.
- Do **not** push, tag, or bump a version.

## Steps

### Step 1: Widen the configuration-file variant family

In `scripts/build_exclusions.py`, extend `_CONFIGURATION_FILE_VARIANTS` (`:73-78`) with the shapes this client is missing, and extend the comment above it to name the tools that produce them:

```python
_CONFIGURATION_FILE_VARIANTS: tuple[str, ...] = (
    "wp-config.php.*",
    "wp-config.php~",
    ".wp-config.php.sw?",
    "#wp-config.php#",
    ".#wp-config.php",
    "wp-config.bak",
    "wp-config.bak.php",
    "wp-config.old",
    "wp-config.old.php",
    "wp-config.orig",
    "wp-config.orig.php",
    "wp-config.save",
    "wp-config.save.php",
    "wp-config-*.php",
)
```

The reordered-backup names are listed individually rather than as `wp-config.*` because a bare `wp-config.*` would also swallow `wp-config.php` itself (harmless — it is excluded anyway) *and* anything else beginning `wp-config.`, which is broader than the shape being closed. Prefer the enumeration; it is auditable, and each entry maps to a documented tool convention.

Add to the comment block above the tuple, in the existing register: `#wp-config.php#` is Emacs' auto-save file and `.#wp-config.php` its lock file, both carrying or pointing at the live file's complete secret family; `wp-config.bak` / `.old` / `.orig` / `.save`, with or without a trailing `.php`, are the reordered backup names an operator leaves behind after a manual edit — the existing `wp-config.php.*` catcher only covers the suffix-appended form.

**Verify**: `uvx pytest -q tests/test_build_exclusions.py` → exit 0.

### Step 2: Widen the root key-material family

In `scripts/build_exclusions.py`, replace `id_rsa*` in `_ROOT_KEY_MATERIAL` (`:98-102`) with OpenSSH's full default basename set, keeping the prefix-match style so `.pub` siblings still match:

```python
_ROOT_KEY_MATERIAL: tuple[str, ...] = (
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
)
```

`id_ecdsa*` and `id_ed25519*` cover the `-sk` hardware-token variants through the same prefix. Extend the comment to say that these are OpenSSH's default key basenames and that the prefix match deliberately also catches the `.pub` sibling — a public key is not a secret, but a public key at the install root is a strong signal the private one is beside it, and neither is site content.

**Verify**: `uvx pytest -q tests/test_build_exclusions.py` → exit 0.

### Step 3: Test the new shapes, and the false-positive controls

In `tests/test_build_exclusions.py`, following the file's existing structure:

1. `test_the_emacs_auto_save_and_lock_files_beside_wp_config_are_excluded` — `#wp-config.php#` and `.#wp-config.php` at the install root.
2. `test_the_reordered_wp_config_backup_names_are_excluded` — `wp-config.bak`, `wp-config.bak.php`, `wp-config.old`, `wp-config.old.php`, `wp-config.orig`, `wp-config.save`.
3. `test_every_openssh_default_key_basename_at_the_root_is_excluded` — `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ecdsa-sk`, `id_ed25519`, `id_ed25519-sk`, and the `.pub` sibling of each.
4. **`test_wp_config_sample_survives_the_widened_variant_family`** — the negative control that matters most. `wp-config-sample.php` must still be transferable after this change.
5. `test_ordinary_content_named_like_a_backup_is_not_excluded` — the false-positive controls: a theme file at `wp-content/themes/x/config.old` (not at the root, not `wp-config`), and `wp-content/uploads/id_ed25519-tutorial.png` (a `uploads`-level path, not root-anchored). Both must be **kept**. If either is dropped, your patterns are anchoring wrongly.

Run the consistency suite too — the two matchers must still agree.

**Verify**: `uvx pytest -q tests/test_build_exclusions.py tests/test_exclusion_matching_consistency.py` → exit 0.

### Step 4: Handle `kntnt_extractor_restricted_path` at submission

This is the half that makes an unanticipated restricted path survivable rather than fatal. **The client's pre-filter will never be provably complete** — it is a mirror of a policy that lives in another repository and may change between releases without an `api_version` bump. So the handling below is the real fix; step 1 and 2 only reduce how often it fires.

In `agents/extract-transfer.md`, at step 1 (`:41`), split `kntnt_extractor_restricted_path` out of the blanket `422` hard stop and give it its own behaviour:

> A `422` whose `code` is `kntnt_extractor_restricted_path` is **not** a hard stop on the first occurrence. The body's `data.paths` names every path the server refused; each is a file this client should never have asked for. Report every named path to the operator with the reason (the Extractor refuses to package it, because its name matches a restricted shape — a configuration-file backup, key material, or a database dump at the install root), drop exactly those paths from the selection's `files` list, and resubmit the create **once**. No job was created by the refused request, so resubmitting starts nothing twice. A second `kntnt_extractor_restricted_path` on the resubmission **is** a hard stop: return `FAILED` with both bodies, because a refusal that survives dropping every named path means the client and the server disagree about what was named, and guessing further would loop.

Keep every other `422` — malformed or overlapping selection — a hard stop exactly as it is today. Add `restricted_paths` to the agent's evidence-block contract beside the existing `skipped_files` (`:64`): the paths dropped, or an empty list when none.

Mirror the same behaviour in `skills/clone/SKILL.md` and `skills/pull/SKILL.md` at their submission steps (`clone` §6 / `pull` §5 — the paragraphs that already describe `strict: false` and `skipped_files`), in one sentence each, and add the dropped paths to the run report beside the skipped files. Keep the two files' wording identical.

**Why drop-and-resubmit rather than a clean hard stop**: this repository already made exactly this trade once, for vanished files — `strict: false` converts a fatal whole-selection mismatch into a reported skip, because a manifest is a snapshot and a live site is not. A restricted path is the same shape of problem: a file the client had no business asking for, discovered after the manifest walk, failing an entire multi-hour transfer at submission. The alternative — report clearly and stop — is defensible and cheaper, and it is recorded in ADR-0024 as the rejected option. It was rejected because the operator's only recovery from it is to hand-edit a selection of tens of thousands of paths.

**Verify**: `uvx pytest -q` → exit 0. Several consistency suites in `tests/` pin cross-surface wording between the agent files and the SKILLs; if one fails, the two surfaces have drifted and you must reconcile them, not weaken the test.

### Step 5: Write ADR-0024

Create `docs/adr/0024-a-restricted-path-refusal-drops-the-named-paths-and-resubmits-once.md`. It must record:

- **The decision**: the client drops the server-named paths and resubmits once; a second identical refusal is fatal.
- **Why the bound is one retry** and not a loop: the server names *every* offender in one response, so one corrected resubmission is sufficient by construction. A second refusal means the two sides disagree about the naming, which more retries cannot fix.
- **Why the client's mirror is not, and must not become, a contract.** The Extractor's `docs/define-disclosure.md` sets the precedent for the sibling protocol: server-side policy may change between releases without a version bump, and a reader must not hard-code or assert it. The same holds here. This client's exclusion patterns exist to avoid *asking* for files it does not want; they are not a claim about what the server will refuse, and no test should assert the two lists are equal.
- **The rejected alternative**: report clearly and hard-stop. Name why it was rejected (the operator's only recovery is hand-editing a very large selection) and note that it is the cheaper option if the retry ever proves troublesome.
- **What this does not claim**: it does not strengthen any security guarantee. The guarantee is enforced server-side precisely so that no client's correctness is load-bearing for it.

### Step 6: Pay the rest of the documentation round

1. `docs/spec.md` — the exclusion-set section describing the always-excluded credential-bearing families. Extend it to name the Emacs and reordered-backup shapes and the full OpenSSH basename set, and add one sentence stating that the client's list is a pre-filter, never a mirror the server's list is checked against. Reference ADR-0024.
2. `CHANGELOG.md` — one `### Added` entry for the widened family and one `### Fixed` entry for the previously unhandled refusal. State plainly in the second that the client had **no** handling of `kntnt_extractor_restricted_path` at all, and that the practical effect was an unhandled error at the step meant to begin the transfer.

**Verify**: `uvx pytest -q` → exit 0; `uvx ruff check scripts/build_exclusions.py tests/test_build_exclusions.py` → exit 0.

## Test plan

- New tests: five in `tests/test_build_exclusions.py`, as enumerated in step 3.
- Structural pattern: the existing credential-family tests in the same file.
- The two that guard against over-matching are tests 4 and 5. A change that passes 1–3 and fails either of those has widened the exclusion set into legitimate site content, which silently removes files from a clone — a worse failure than the one this plan fixes, because nothing reports it.
- Verification: `uvx pytest -q` → exit 0, **967 passing** (962 + 5).

## Done criteria

ALL must hold:

- [ ] `uvx pytest -q` exits 0 with 967 passing
- [ ] `uvx ruff check scripts/build_exclusions.py tests/test_build_exclusions.py` exits 0
- [ ] `grep -rn "kntnt_extractor_restricted_path" agents/ skills/` returns matches in `agents/extract-transfer.md`, `skills/clone/SKILL.md`, and `skills/pull/SKILL.md`
- [ ] `git diff --stat` shows `scripts/filter_manifest.py` and `scripts/baseline_diff.py` **unmodified**
- [ ] `git diff --stat` lists only the files in the In-scope list
- [ ] `docs/adr/0024-*.md` exists
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report (do not improvise) if:

- The drift check reports changes to any in-scope file, or the excerpts do not match the live code.
- You find yourself needing to edit `scripts/filter_manifest.py` or `scripts/baseline_diff.py`. The patterns flow to them as data; needing to edit them means the change is in the wrong layer.
- Test 4 (`wp-config-sample.php` survives) or test 5 (the false-positive controls) fails. Do not loosen the test; narrow the pattern.
- `~/Projects/kntnt-extractor/plans/016-close-the-restricted-path-gaps.md` has been executed and its landed patterns differ from those quoted in "What the server's list is becoming". The landed code is the authority; re-derive from `classes/Restricted_Path.php` and report the difference.
- You conclude the client's list should be asserted equal to the server's. It should not — see the Out-of-scope list and ADR-0024. Report the reasoning rather than building the assertion.

## Maintenance notes

- **What a reviewer should scrutinise**: that no new pattern is broader than the shape it names (`wp-config.*` was deliberately not used); that `wp-config-sample.php` is still transferable; that the root-anchored patterns are still root-anchored, so an `uploads/` file with a coincidental name is not dropped; and that the resubmission in step 4 is bounded at exactly one.
- **This plan's pattern list will go stale again**, by design — it mirrors policy that lives in another repository and is allowed to move without a version bump. That is why step 4 exists: the handling, not the mirror, is what makes staleness survivable. Do not respond to the next drift by trying to make the mirror authoritative.
- **Deliberately not built**: any local check that the *resolved* target of a symlink is restricted. The Extractor's plan 016 adds that check server-side, where it belongs — the client walks a manifest the server produced and never resolves anything itself. If a future finding wants it client-side, that is a new decision, not an extension of this one.
- **Interacts with**: `tests/test_exclusion_matching_consistency.py`, which pins the two matchers against each other. Adding a pattern shape neither matcher handles identically will surface there first.
