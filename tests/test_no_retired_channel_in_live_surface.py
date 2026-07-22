"""Regression guard: the retired Novamira/execute-php control channel and the
retired client-side pack machinery must never reappear in the executable surface.

The control channel was cut over from the Novamira MCP `execute-php` channel to
the Kntnt Extractor REST API (ADR-0016), and the client-side pack machinery was
retired in favour of the plugin's own background extraction (ADR-0017). This
suite pins that cutover where it matters most — the surface an agent actually
runs: the helper scripts, the subagent definitions, and the two skills'
orchestration prose. A future edit that reintroduces a retired-channel verb
(`execute-php`, `run-wp-cli`, a Novamira ability inventory) or a retired
pack-mechanism token (`pack.sh`, `pass.key`) reddens here rather than silently
resurrecting a channel the plugin no longer speaks.

The narrative docs (`docs/implementation-notes.md`, `templates/README.md`, the
ADRs) legitimately *describe* the retired mechanism as history, so they are out
of scope here; this guard is only the live, executed surface. The word
"Novamira" itself survives solely inside the ADR-0016 filename that these files
link to (`0016-kntnt-extractor-replaces-novamira-as-control-channel.md`), so the
bare-reference check discounts that link before asserting.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]

# The executable surface: the helper scripts an agent runs, the subagent
# definitions it delegates to, and the two skills' orchestration prose. The
# narrative/historical docs are deliberately excluded.
EXECUTABLE_SURFACE: list[Path] = [
    *sorted((REPO_ROOT / "scripts").glob("*.py")),
    *sorted((REPO_ROOT / "agents").glob("*.md")),
    REPO_ROOT / "skills" / "clone" / "SKILL.md",
    REPO_ROOT / "skills" / "pull" / "SKILL.md",
    REPO_ROOT / "skills" / "mkwp" / "SKILL.md",
]

# Retired control-channel verbs and pack-mechanism tokens with no legitimate use
# in the new REST model — the plugin owns the extraction, the sealing, the
# one-time link, and the cleanup, so none of these ever runs from here again.
RETIRED_TOKENS: tuple[str, ...] = (
    "execute-php",
    "run-wp-cli",
    "discover-abilities",
    "create-upload-link",
    "pack.sh",
    "pass.key",
)

# ADR filenames legitimately carry "novamira" (the cutover is literally named
# after what it replaced); a link to one is not a live-channel reference.
ADR_FILENAME_WITH_NOVAMIRA = re.compile(r"\d{4}-[a-z0-9-]*novamira[a-z0-9-]*\.md")


def test_no_retired_channel_tokens_in_the_executable_surface() -> None:
    """No helper script, subagent definition, or skill prose names a retired
    control-channel verb or pack-mechanism token."""

    offenders: list[str] = []
    for path in EXECUTABLE_SURFACE:
        text = path.read_text(encoding="utf-8")
        for token in RETIRED_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {token!r}")

    assert not offenders, (
        "retired control-channel/pack tokens reappeared in the executable "
        "surface (the plugin owns extraction now — ADR-0016/0017):\n"
        + "\n".join(offenders)
    )


def test_no_bare_novamira_reference_in_the_executable_surface() -> None:
    """No helper script, subagent definition, or skill prose names Novamira as a
    live channel — the only surviving occurrence is the ADR-0016 filename these
    files link to, which is discounted before the check."""

    offenders: list[str] = []
    for path in EXECUTABLE_SURFACE:
        text = path.read_text(encoding="utf-8")
        # Strip the legitimate ADR-filename link occurrences, then any residual
        # "novamira" is a live-channel reference that should not be there.
        without_adr_links = ADR_FILENAME_WITH_NOVAMIRA.sub("", text)
        if "novamira" in without_adr_links.lower():
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "a bare Novamira reference (not an ADR-filename link) reappeared in the "
        "executable surface:\n" + "\n".join(offenders)
    )
