# Contributing to kntnt-wp-skills

Thanks for considering a contribution. kntnt-wp-skills is open source, so anyone is free to fork it and adapt it for their own purposes. This document describes the *project norm* — what kinds of contribution are likely to be welcomed into the upstream repository at [Kntnt/kntnt-wp-skills](https://github.com/Kntnt/kntnt-wp-skills). It is editorial guidance on what is likely to be merged, not a legal restriction on what you may do with the code.

## Contribution scope

| Category | Examples | Reception |
|---|---|---|
| Welcomed without question | Bug reports; bug fixes against existing behaviour; corrections to broken examples; typo and grammar fixes in prose; clarifications that do not change behaviour. | Open a PR. If the change is small and self-evidently correct, it is usually merged quickly. |
| Accepted but discussed first | New features; changes to existing behaviour, scope, or a public interface; new dependencies. | Open an issue first to align on intent before writing code. A PR without prior discussion may still land, but expect feedback rounds. |
| Unlikely to be merged but free to fork | Changes that alter the project's direction or restructure its architecture in a way that conflicts with its goals. | The licence makes forking explicit and lawful. If you want a different direction, build it in your fork. |

## Inbound licensing

By submitting a contribution, you agree it is licensed under the Apache License 2.0 by virtue of its §5 *Submission of Contributions* — any contribution intentionally submitted for inclusion is under the terms of that licence unless you state otherwise. No separate contributor licence agreement is required.

## Behaviour

Be respectful and constructive in issues, pull requests, and discussions. Assume good faith, keep criticism about the work rather than the person, and help keep this a project people want to contribute to.

## How to contribute

1. **Open an issue first** for anything in the *discussed* row above. For *welcomed* items, you can open a PR directly. Use the issue tracker at <https://github.com/Kntnt/kntnt-wp-skills/issues>.
2. **One concern per PR.** Smaller PRs land faster.
3. **Follow the project's coding standard.** It is materialised under [`agents.d/coding-standard/`](agents.d/coding-standard/) — read `general.md` plus the module(s) for the language or framework you touch before changing code.
4. **Run the tests.** The Python helpers under `scripts/` are covered by a pytest suite under `tests/`. One command runs it, provisioning pytest through `uv`:

   ```
   uv run --with pytest pytest
   ```

5. **Run the type check.** The helpers are checked in mypy's strict mode, and a type error is a change that does not land. One command runs it, in the same shape, from the repository root:

   ```
   uv run --with mypy --with pynacl==1.5.0 mypy
   ```

   Strict mode and the checked directories come from `pyproject.toml`, so the command carries no flags of its own. The `pynacl` pin is the one `skills/clone/scripts/unseal.py` declares in its own inline metadata: mypy cannot read a PEP 723 header, so the dependency is provisioned here instead of being ignored — ignoring it would invent a finding that is not there. A lint run is a different matter: ruff is the project's chosen linter but nothing pins a ruleset yet, so what it reports is advice rather than a verdict on your change.

## Questions

Open an issue or start a discussion. Conversation happens in the open.
