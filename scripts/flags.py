# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""The canonical flag registry — single source of truth for which flags each
skill accepts.

The flag surface is deliberately minimal per skill (ADR-0013): a small set of
coarse scope- and behaviour-tuning switches that let an unattended run deviate
from its defaults, plus the three spellings of the help gate — and nothing
else. ``clone`` and ``pull`` are the shared transfer engine and accept exactly
the same surface by design. ``mkwp`` scaffolds a brand-new site — it is not
part of that engine, has no production discovery to override, and its flags
map onto `mkwp`'s own site-identity and content options instead, so its
surface is unrelated and kept in its own registry entry rather than folded
into the same flat set.

This registry is the authority that binds the documentation to the
implementation: the help/docs consistency test asserts every flag a manual
page documents is in that skill's own ``SKILL_FLAGS`` entry, and every flag in
a skill's entry is documented in its own manual page — a per-skill binding,
never a blanket cross-check against every other skill's flags. Later issues'
argument-parsing helpers read the same registry; running this module directly
emits it as JSON for any non-Python consumer.
"""

from __future__ import annotations

import json

# clone and pull's shared operational flags: coarse scope- and
# behaviour-tuning switches for an unattended (`--yes`) run to override the
# discovery-derived defaults. Ordered as the manual pages present them in
# their SYNOPSIS.
CLONE_PULL_OPERATIONAL_FLAGS: tuple[str, ...] = (
    "--yes",
    "--include-media",
    "--exclude-media",
    "--include-blobs",
    "--live-mail",
    "--capture-mail",
    "--no-cron",
    "--regenerate-all",
)

# mkwp's own operational flags: `--yes` plus the site-identity and content
# options it derives from context or gates, mapped 1:1 onto mkwp's own
# long-form flags (skills/mkwp/SKILL.md §3). Ordered as its manual page
# presents them in its SYNOPSIS.
MKWP_OPERATIONAL_FLAGS: tuple[str, ...] = (
    "--yes",
    "--dirname",
    "--directory",
    "--title",
    "--email",
    "--user",
    "--language",
    "--php",
    "--wp",
    "--themes",
    "--plugins",
    "--mu-plugins",
)

# The help gate's three accepted spellings: any one prints a skill's manual
# page and stops. Shared by every skill.
HELP_FORMS: tuple[str, ...] = ("help", "--help", "-h")

# Per-skill registries — the binding the docs-consistency test enforces: skill
# X's manual page documents exactly SKILL_FLAGS[X], no more, no less. clone and
# pull share one entry by construction (ADR-0013); mkwp's is independent.
SKILL_FLAGS: dict[str, frozenset[str]] = {
    "clone": frozenset(CLONE_PULL_OPERATIONAL_FLAGS + HELP_FORMS),
    "pull": frozenset(CLONE_PULL_OPERATIONAL_FLAGS + HELP_FORMS),
    "mkwp": frozenset(MKWP_OPERATIONAL_FLAGS + HELP_FORMS),
}

# Every token any skill accepts, flattened — for a consumer that genuinely
# wants the whole surface regardless of skill (e.g. a global usage grep).
# Never used for the per-skill documentation binding — see SKILL_FLAGS.
ALL_FLAGS: frozenset[str] = frozenset().union(*SKILL_FLAGS.values())


def main() -> None:
    """Emit the registry as JSON on stdout — the helper-seam contract for any
    non-Python consumer."""

    print(
        json.dumps(
            {skill: sorted(tokens) for skill, tokens in SKILL_FLAGS.items()},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
