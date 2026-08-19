# Plan 011: Detect the files macOS silently merges, instead of counting the ones we wrote

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report. When done, update the status row in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat <the SHA in "Planned at">..HEAD -- scripts/unseal.py tests/test_unseal.py`

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b79c98b`, 2026-08-19
- **Evidence**: the successful production clone of 2026-08-19

## Why this matters

Linux keeps `å` written as one code point (NFC) and `å` written as `a` plus a combining ring (NFD) as **two distinct files**. APFS normalises, so writing both into the same directory on macOS means the second overwrites the first. Production runs Linux; the copy lands on macOS.

On the 2026-08-19 clone, `scripts/unseal.py` reported `files_written: 48578` while **48,552 distinct files landed**. Twenty-six pairs collided. Eight were byte-identical and harmless; **eighteen had genuinely different sizes, so one variant of each is gone.** A typical pair — both already mojibake for `kameraövervakning` from some historic bad import on production:

```
kamerai\xcc\x82vervakning.png     (NFD)
kamera\xc3\xaevervakning.png      (NFC)
```

**The defect is the silent count, not the loss.** `unseal.py` counts the entities it wrote, never the distinct paths that landed, so it structurally cannot notice a collision it caused. A run reports complete success while quietly holding fewer files than it transferred.

The impact this time was bounded, and the plan should not overstate it: APFS lookup is normalisation-insensitive, so WordPress resolves either spelling and nothing 404s. The real risk is serving one variant's bytes under the other's name. All twenty-six were in `uploads/`, mostly `.webp` derivatives and thumbnails that the regeneration step rebuilds anyway. **A different site could collide on something that matters, and would be told nothing.**

## What this does not fix

- It does not prevent the collision. Two Linux files that differ only by normalisation cannot both exist on APFS, and this plan does not try to rename around it.
- It does not repair the 2026-08-19 copy.
- It does not decide what to *do* about a detected collision. Reporting it to the operator is the whole deliverable; choosing a variant is a judgement this plan deliberately leaves to a person.

## Current state

- `scripts/unseal.py` — reassembles the container and writes each file segment to a staging tree by its install-root-relative path. It reports `files_written`, derived from segments processed.
- The three lists it is given must equal what the plugin packaged; `files` comes from the submitted selection minus any `skipped_files`.

Find the counter before changing it:

```
grep -n "files_written\|def unseal\|write" scripts/unseal.py
```

## The wrong turn, recorded so it is not repeated

The first diagnosis attempt compared selection paths against `find` output **byte for byte**. That reports every non-NFC path as a missing file — 72 of them on this copy — and hides the 26 real collisions in the noise. **Do not diff raw path bytes.** Group by `unicodedata.normalize("NFC", path)` and look for groups larger than one; that is the comparison that isolates the actual defect.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Suite | `uvx pytest -q` | exit 0, 962 passing |
| One file | `uvx pytest -q tests/test_unseal.py` | exit 0 |
| Lint | `uvx ruff check scripts/unseal.py tests/test_unseal.py` | exit 0 |

## Scope

**In scope**: `scripts/unseal.py`, `tests/test_unseal.py`, `skills/clone/SKILL.md`, `skills/pull/SKILL.md`, `docs/implementation-notes.md`, `CHANGELOG.md`.

**Out of scope**:

- Renaming, re-encoding or otherwise "fixing" a colliding path. That changes what the copy contains and would break WordPress's own references.
- The exclusion set and the manifest. The collision is a property of the destination filesystem, not of the selection.
- `scripts/filter_manifest.py` and `scripts/baseline_diff.py`. A baseline written from the *production* manifest is correct as it stands; making it normalise would make the diff lie about what production holds.

## Git workflow

Trunk-based, straight to `main`. No push, no tag, no bump.

## Steps

### Step 1: Detect the collision before writing

In `scripts/unseal.py`, before the write loop, group the file list by `unicodedata.normalize("NFC", path)` and collect every group with more than one member. This is a pure function of the input list — it needs no filesystem access and costs one pass.

Carry the groups into the output as a new member (`normalisation_collisions` or similar), each entry naming the colliding paths. Absent or empty when there are none, so the common case is unchanged.

Do **not** make it fatal. The transfer is not wrong; the destination cannot represent it. A run that stops here would refuse a copy that is 99.95 % correct over derivatives the next step rebuilds.

### Step 2: Make the count mean what it says

Report the distinct destination paths alongside the entities written, so the two can be compared. Whether that is a second member or a corrected `files_written` is your call — but the output must let a reader see that 48,578 segments produced 48,552 files, which today it cannot.

Only guard the guard: if the collision detection itself is what miscounts, the fix is worse than the defect.

### Step 3: Test it

In `tests/test_unseal.py`:

1. Two paths differing only by NFC/NFD normalisation are reported as one collision group.
2. Paths that differ by more than normalisation are **not** grouped — the false-positive control.
3. A selection with no non-ASCII names reports no collisions and the member is absent or empty.
4. The distinct-path count differs from the segment count exactly when a collision exists.

Test 2 is the one that matters most: a detector that groups too eagerly would flag ordinary files on every run and be switched off.

**Verify**: `uvx pytest -q` → exit 0, four new tests passing.

### Step 4: Surface it, and pay the round

Both SKILLs' run reports must name any collision group: the paths, that macOS merged them, that one variant's bytes are what landed, and that a regenerated derivative is likely harmless while an original may not be. Keep the two files identical.

`docs/implementation-notes.md` gets the new output member in the unseal contract. `CHANGELOG.md` gets an entry stating the observed case — 26 pairs, 18 with differing sizes, reported as complete success — and what this does not fix.

## Done criteria

- [ ] `uvx pytest -q` exits 0 with four new tests
- [ ] `uvx ruff check scripts/unseal.py tests/test_unseal.py` exits 0
- [ ] `grep -n "normalize" scripts/unseal.py` shows NFC grouping, not a byte-for-byte path diff
- [ ] The output distinguishes segments written from distinct paths landed
- [ ] Both SKILLs report collisions identically; `CHANGELOG.md` entry present; `plans/README.md` row updated

## STOP conditions

- The detector flags paths that differ by more than normalisation (test 2 fails). Narrow it; do not relax the test.
- You conclude a collision should abort the unseal. That is a behaviour change with a real cost and it is the repository owner's call.
- You find yourself renaming a destination path to avoid a collision. Out of scope — it breaks WordPress's own references to the file.

## Maintenance notes

- **What a reviewer should scrutinise**: that detection is a pure function of the input list; that nothing became fatal; and that the false-positive control genuinely exercises a non-normalisation difference.
- **Why the baseline is deliberately untouched**: `.kntnt-wp-skills/last-sync.json` records what *production* holds, and production is Linux, where both spellings exist. Normalising it would make the next `pull`'s deletion set claim a file vanished when it never did.
- **The general shape**: this is a destination-filesystem property, not a transfer defect, and the same class will appear again for case-insensitivity — two Linux files differing only in case collide on a default macOS volume in exactly the same way, and nothing here detects that. Worth its own pass if it ever bites.
