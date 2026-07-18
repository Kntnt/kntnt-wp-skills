---
name: probe
disable-model-invocation: true
description: >
  Throwaway skill used only to demonstrate the help/docs consistency test going
  red when a skill ships without a manual page. Removed in the next commit.
---

# probe

Temporary perturbation for the red-first artifact of
`test_every_skill_has_a_manpage`. It has a `SKILL.md` but no `docs/man/probe.md`,
so the consistency test reddens. The next commit deletes this directory.
