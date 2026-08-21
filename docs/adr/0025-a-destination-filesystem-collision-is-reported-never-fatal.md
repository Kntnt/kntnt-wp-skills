# A destination-filesystem collision is reported, never fatal

Linux stores a filename's bytes verbatim, so `å` written as one code point (NFC) and `å` written as `a` plus a combining ring (NFD) are two different files there. APFS normalises, so on the operator's Mac they are one. Production runs Linux; the copy lands on macOS. Writing both spellings into the same local directory therefore leaves a single file holding whichever bytes were written last, and the other variant is gone.

The 2026-08-19 production clone did exactly that and said nothing. `unseal.py` reported `files_written: 48578` while **48,552 distinct files landed**: twenty-six pairs collided, eight of them byte-identical and harmless, **eighteen with genuinely different sizes**. The run reported a complete, successful transfer.

**The defect was the count, not the loss.** The helper counted the entities it wrote — one per name in the container's index — and never the paths that actually landed, so it was structurally incapable of noticing a collision it had caused itself. Any run could report a clean transfer while quietly holding fewer files than it transferred, and no step downstream would contradict it.

## Decision

The unseal helper reports what landed beside what it wrote, and names what merged.

Before writing anything, it groups the file list by `unicodedata.normalize("NFC", path)` and keeps every group with more than one member as `normalisation_collisions`, each group naming every spelling in it. That detection is a pure function of the container's own file list: no filesystem access, one pass, and it says which paths *would* merge on a normalising destination rather than which did.

After writing, it counts what actually exists — the distinct `(device, inode)` pairs the destinations resolve to — and reports that as `files_landed` beside `files_written`. The identity is the filesystem's own, not the path string, because that is the only thing that can tell a merge from a pair of files. A reader can now see that 48,578 entities produced 48,552 files, which the old output could not express at all.

**A collision never aborts the run.** The container is correct and the destination cannot represent it; a transfer that stopped here would refuse a copy that is 99.95 % correct over derivatives the next step rebuilds anyway. It travels in the `extract-transfer` role's evidence block and is named in the run report, with both spellings, what macOS did to them, and the fact that one variant's bytes are what survived.

## Rejected alternatives

- **Abort the unseal on a collision.** It converts a bounded, reportable imperfection into a failed multi-hour transfer, and it offers the operator no recovery: the two names exist on production and no client-side retry changes that. Reporting is what a person can act on; refusing is not.
- **Rename around it — write the second variant under a suffixed name.** It breaks WordPress's own references. The database points at `_wp_attached_file` and at names embedded in post content; a file under a name nothing references is worse than a merged file, because APFS lookup is normalisation-insensitive and resolves either spelling to the one file that is there. This is also the one thing the plan behind this decision named as an outright STOP.
- **Diff the selection against the destination tree byte for byte.** The first diagnosis attempt did this and reported seventy-two missing files on a copy that was missing twenty-six — every non-NFC path counted as absent, with the real collisions buried in the noise. Grouping on the NFC form is the comparison that isolates the defect.
- **Derive the landed count arithmetically from the collision groups.** `files_written` minus the surplus members of each group is cheaper and needs no `stat`, and it carries no information the groups do not already carry. The defect was precisely that the helper counted its own intentions; a fix that counts them again, more carefully, repeats it. The disk is the authority, and asking it also makes the count truthful about merges this decision does not detect — a case-folding destination among them.
- **Normalise the stored baseline the same way.** `.kntnt-wp-skills/last-sync.json` records what *production* holds, and production is Linux, where both spellings genuinely exist. Normalising it would make the next `pull`'s deletion set claim a file had vanished when it never did.

## Consequences

- **The observed impact was bounded, and this decision does not overstate it.** APFS lookup is normalisation-insensitive, so WordPress resolves either spelling and nothing 404s; the real risk is serving one variant's bytes under the other's name. All twenty-six pairs were in `uploads/`, mostly `.webp` derivatives and thumbnails that the regeneration step rebuilds locally. A different site could collide on something that matters — and, before this, would have been told nothing.
- **The 2026-08-19 copy is not repaired by this**, and nothing here prevents a collision. Two Linux files that differ only by normalisation cannot both exist on APFS, and the client does not try to make them.
- **What to *do* about a detected collision is deliberately left to a person.** A merged derivative is ordinarily harmless; a merged original is not, and no signal available to the run distinguishes them.
- **The same class reappears for case.** Two Linux files differing only in case merge identically on a default macOS volume, and the NFC grouping does not detect it. The disk-measured count does notice the shortfall — `files_landed` falls below `files_written` — but nothing names the pair, which is issue #61's to close.
