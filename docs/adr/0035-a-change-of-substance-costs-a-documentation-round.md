# A change of substance costs a documentation round; a test-only change does not

Two rules governed the work in this repository without being written down in it, and both cost something every time they were needed.

The first is the documentation round, cited in tickets as **R3**. It was defined in `~/Projects/kntnt-transfer-engine-open-work.md` — a file on one machine that no clone of this repository carries. Four tickets in the unattended run of 2026-08-21 charged work against it by name; every readiness check flagged that the citation resolved to nothing in-repo; every builder resolved it from precedent and passed anyway. That worked four times because the precedent was thick and the builders were careful. It is not a rule this repository can enforce, a reader can look up, or a verifier can hold anyone to.

The second is its boundary. Issue [#76](https://github.com/Kntnt/kntnt-wp-skills/issues/76) put a changelog entry in its *Out of scope* list verbatim — *"A CHANGELOG entry. This repository's test-only changes do not carry one."* The builder wrote none and the verifier passed it on exactly that basis. The integrated-branch coherence check, which is deliberately given no ticket text so that its reading of the branch is independent, read the gap as a defect and named it twice. Nothing authoritative stated the rule, so the check was not wrong — it was reading the rule's absence. Two fixer sessions were handed the finding and both declined it as a choice rather than a restatement, which was the right judgement and also not a fix: the finding regenerates on every future wave that merges a test-only ticket.

They are one question asked from both ends — what a change owes the documentation, and where the obligation stops — so they are settled together.

## Decision

**Both rules live in [`AGENTS.md`](../../AGENTS.md), and R3's definition comes into this repository with them.**

- **A change of substance costs a documentation round:** [`CHANGELOG.md`](../../CHANGELOG.md), [`CONTEXT.md`](../../CONTEXT.md), an ADR, and on the skills side [`docs/spec.md`](../spec.md) and every `SKILL.md` it touches. That tax is what lets a cold agent work here at all, and it is real. An item not worth paying it for is not worth doing — say so and strike it rather than carrying it.
- **A test-only change is not a change of substance** and carries no `CHANGELOG.md` entry.

**The boundary is the files touched, not the size of the effect.** A change confined to `tests/` carries no entry. A change that touches a helper, a skill document, an operator-facing document, or the tool configuration carries one however small it is — the entry is what tells a reader of the release that something they run behaved differently, and a test does not qualify no matter how much work it was.

`AGENTS.md` rather than `CONTRIBUTING.md` or `docs/spec.md`, because the readers who keep missing this rule are agents mid-run. `AGENTS.md` is always loaded and is authoritative by its own ground rules; `CONTRIBUTING.md` is a contributor-facing page a human reads once at setup; and the specification's subject is what gets built, not how the work is conducted.

## Rejected alternatives

- **Retire the rule and give #76 a retroactive entry.** The live alternative, and the one the coherence check implicitly proposed. Rejected on both halves: it reverses a ticket's stated scope after the ticket was built and verified against that scope, and it points the changelog in the wrong direction. A changelog carrying "added a test" among the entries a reader scans for what changed for them is a changelog that gets skimmed instead of read.
- **Leave R3 in the external file and keep citing it.** The status quo, measured: four tickets, four readiness flags, four independent resolutions from precedent. The cost is one flag per ticket forever, and the risk is the day a builder resolves it differently from the four before it — with no in-repo text to show which reading was right.
- **Bring the whole external rule set (R1–R5) in.** R1, R2, R4 and R5 govern how that backlog is worked — what may be queued, what must be measured before a constant is chosen, when a schema field is free. R3 is the only one that binds a change made in this repository, and it is the only one tickets here cite. Importing the rest would move a queue's process into a codebase that does not run that queue.
- **Teach the coherence check to read the ticket text.** It would have silenced the finding, and it would have cost the check the property that makes it worth running: it reads the integrated branch with no ticket in hand, which is why it catches what a ticket-scoped verifier is looking away from. The repair is to make the rule readable in the repository, not to make the check less independent.
- **Record the rules in a test rather than in prose.** This repository binds a great deal of prose with consistency suites, so the reflex is defensible. It does not apply: a suite can hold a document to saying something, but the rule's whole purpose is to be read by an agent deciding what a change owes, before any test runs. A test asserting `AGENTS.md` contains a sentence would pin the wording without adding a reader.

## Consequences

- **"R3" resolves inside the repository**, so tickets may keep citing it by name and a readiness check has somewhere to look. The external file remains the queue's own copy; this one governs changes made here.
- **The coherence check has something authoritative to read**, and the #76 finding stops regenerating. A future agent reaching for the changelog entry as a mechanical fix now finds the rule that forbids it.
- **`CONTEXT.md` and `docs/spec.md` are deliberately untouched.** No new glossary term is introduced, and the rule governs how the work is conducted rather than what the transfer engine does — which is what a documentation round asks of a change like this one, not a checklist to satisfy mechanically.
- **This decision is its own first worked example.** The rules land in `AGENTS.md`, the rationale lands here, and `CHANGELOG.md` gets an entry — earned because the change alters how every later change is judged, not by its size. Both halves of the rule are visible in the same commit: the widened type-check guard is named in that entry because it amended [ADR-0032](0032-strict-type-checking-is-enforced-ruff-is-advisory.md) and `pyproject.toml`'s comment, while the `mkwp` floor scan's package-pin discount lives entirely in `tests/` and buys no entry of its own.
