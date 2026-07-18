# Decoupled from mkwp — scaffold only; import and localisation live in the skill engine

The skills ride `mkwp` exactly as it is today (scaffold only). Import and localisation live in the skill engine, because `pull` needs them against an already-existing site and `mkwp` is a create-a-new-project tool. `mkwp`'s optional template-seeder capability is a separate, non-blocking track — filed as [Kntnt/mkwp#1](https://github.com/Kntnt/mkwp/issues/1). It is justified on its own merits and is **not** a dependency of these skills.
