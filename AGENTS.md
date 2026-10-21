# kntnt-wp-skills — agent guide

## Ground rules (authoritative)

Precedence over any conflicting skill, README, or other doc unless the user overrides
in the moment.

- Authoritative: only this file, the files it references, and the actual code/state.
  Ignore `README*` and other narrative docs unless referenced here or pointed to.

## Non-obvious

- A change of substance costs a documentation round (the queue's **R3**): `CHANGELOG.md`, `GLOSSARY.md`, an ADR, and on the skills side `docs/spec.md` and every `SKILL.md` it touches. An item not worth paying that for is not worth doing — say so and strike it rather than carrying it.
- A test-only change is not a change of substance and carries no `CHANGELOG.md` entry (issue #76). A coherence check reading that gap as a defect is reading this rule's absence, not a defect; do not close it by writing an entry.

## References

- `docs/spec.md` — read before implementing: the specification, the single source of truth for the build.
- `docs/adr/` — read when a choice looks open: the settled decisions with their rationale, never to be re-opened as an oversight.
- `GLOSSARY.md` — the project glossary; use its terms in code, docs, and dialogue.
- `agents.d/coding-standard/general.md` — read before writing or changing any code
- `agents.d/coding-standard/python.md` — read before writing or changing Python
