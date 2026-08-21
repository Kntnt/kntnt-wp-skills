"""Documentation-link guards — every link this repository writes down resolves.

Until issue #76 nothing checked that a Markdown link goes anywhere. Two defects
in two days were found by a person reading rather than by the suite: the
glossary's three ADR citations, dead since the day they were written because
`CONTEXT.md` sits at the repository root and reached them as `./adr/…` (#73);
and a `../../docs/adr/…` citation inside a shipped skill document, which
resolves in a clone and dangles for every reader who installed that skill on
its own (#69).

The two are not the same defect, and no single check catches both. This module
owns the two invariants that are repository-wide; the third — that a shipped
skill document's links survive standalone installation — belongs to
``test_standalone_distribution.py``, which already installs a skill into a temp
directory and resolves what it names there, and whose blind spot was the
*document set* rather than the mechanism.

- **Own-directory resolution.** For every tracked Markdown file, every relative
  link target resolves against the directory containing that file. This is the
  check that catches #73's class, and it deliberately passes #69's — a
  `../../docs/adr/…` from under `skills/` does resolve in a clone.
- **Absolute repository URLs.** The house convention for a portable skill
  citing a repository document is an absolute URL into this repository's own
  tree at `https://github.com/Kntnt/kntnt-wp-skills/blob/main/`, which no
  relative check can follow. Every such URL's path component names a file that
  exists in the working tree, so a renamed ADR reddens here instead of leaving a
  link that looks canonical and silently 404s for a standalone reader with no
  repository to fall back on.

Two scope decisions the ticket left to be made, recorded where the code makes
them. **The absolute-URL sweep reads every tracked file, not only the Markdown
ones**: the criterion is written repository-wide over *URLs into this
repository* with no file-set restriction, and #69's own fix converted a Python
module docstring's citation to exactly this form, so restricting the sweep to
`.md` would leave the one non-Markdown member of the population unguarded. The
neighbouring exclusion of *relative* links in non-Markdown files is untouched —
that population is zero, and the bare `ADR-NNNN` mention is the deliberate
house style in Python. **Nothing here reaches the network.** A URL's path
component is checked against the working tree as a string and a filesystem
lookup; whether the URL is reachable, whether an external host is up, and
whether a `#anchor` names a real heading are all somebody else's problem and no
test's.

Each sweep asserts that the set it examined is non-empty before checking it —
the pattern ``test_help_docs_consistency.py`` established with its README
manpage links — so a regex that stops matching reddens instead of quietly
enforcing nothing.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]

# A Markdown link target — the same shape ``test_standalone_distribution.py``
# extracts, so the two suites read a link the same way.
MARKDOWN_LINK: re.Pattern[str] = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# An absolute link into this repository's own tree at its default branch, with
# the repository-relative path captured. The terminator class ends the match at
# whatever delimits the URL in prose — a Markdown link's `)`, a backtick, a
# quote, or whitespace — so a citation carrying a trailing anchor or punctuation
# still yields the path itself.
REPOSITORY_BLOB_URL: re.Pattern[str] = re.compile(
    r"https://github\.com/Kntnt/kntnt-wp-skills/blob/main/([^\s)\]\"'`>]+)"
)


def _tracked(pattern: str) -> list[str]:
    """List the repository-relative paths of the tracked files matching a
    pathspec.

    Asking git is what "tracked" means, and the alternative — walking the tree
    and guessing which dot-directories are not part of the repository — would
    make the guard's own corpus a heuristic. A working tree always has git; a
    missing or broken one raises here rather than yielding a short corpus that
    still passes.
    """

    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", pattern],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return sorted(name for name in completed.stdout.split("\0") if name)


def _linked_paths(text: str) -> list[str]:
    """Extract the path references from a document's Markdown links.

    A link target is a path reference only when it addresses a file: an absolute
    URL is somebody else's tree, a pure `#anchor` addresses a heading in this
    same document, and a `mailto:` addresses a person. What survives is returned
    with any trailing `#anchor` stripped, because a `path#anchor` target is a
    real path reference whose anchor no offline check can verify.
    """

    return [
        target.split("#", 1)[0]
        for target in MARKDOWN_LINK.findall(text)
        if "://" not in target and not target.startswith(("#", "mailto:"))
    ]


def _repository_blob_paths(text: str) -> list[str]:
    """Extract the repository-relative paths named by a document's absolute
    links into this repository, the trailing `#anchor` of each stripped for the
    same reason ``_linked_paths`` strips it."""

    return [url.split("#", 1)[0] for url in REPOSITORY_BLOB_URL.findall(text)]


def _text(path: str) -> str:
    """Read a tracked file for pattern matching.

    Undecodable bytes are dropped rather than raising: this sweep reads every
    tracked file, an ASCII URL cannot hide inside a byte sequence that is not
    UTF-8, and a binary asset committed some day should not turn a link guard
    into a decode error.
    """

    return (REPO_ROOT / path).read_text(encoding="utf-8", errors="ignore")


# Values fixed at collection time so each document reports as its own case. The
# absolute-URL corpus is keyed by file so a failure names the file that carries
# the dead citation, and only the files that carry one become cases.
TRACKED_MARKDOWN: list[str] = _tracked("*.md")
REPOSITORY_BLOB_PATHS: dict[str, list[str]] = {
    path: paths
    for path in _tracked("*")
    if (paths := _repository_blob_paths(_text(path)))
}


@pytest.mark.parametrize("document", TRACKED_MARKDOWN)
def test_every_relative_markdown_link_resolves_from_its_own_directory(
    document: str,
) -> None:
    """Every relative link a tracked Markdown document writes down points at
    something that is there, read — as every Markdown renderer reads it —
    against the directory the document itself sits in."""

    directory = (REPO_ROOT / document).parent
    unresolved = sorted(
        {
            target
            for target in _linked_paths(_text(document))
            if not (directory / target).exists()
        }
    )
    assert not unresolved, f"{document} links to nothing at: {unresolved}"


def test_the_relative_link_sweep_examines_a_non_empty_set() -> None:
    """The sweep above enforces something: there are tracked Markdown documents,
    and they do carry relative links. A link pattern that stopped matching would
    otherwise leave every one of those cases passing vacuously."""

    assert TRACKED_MARKDOWN, "git reports no tracked Markdown files"
    targets = [
        target
        for document in TRACKED_MARKDOWN
        for target in _linked_paths(_text(document))
    ]
    assert targets, (
        "no relative Markdown link targets were extracted from any tracked "
        "document; the resolution guard would be enforcing nothing"
    )


def test_anchors_and_mailto_targets_are_not_read_as_paths() -> None:
    """The extraction predicate keeps the two skip rules the tree itself cannot
    exercise — it carries no pure-anchor and no `mailto:` link today — and keeps
    a `path#anchor` target as the path it is."""

    text = (
        "[same document](#a-heading) and [a person](mailto:thomas@kntnt.com) and "
        "[elsewhere](https://example.com/page) are not paths, while "
        "[a section of a file](./docs/spec.md#troubleshooting) and "
        "[a file](README.md) are."
    )

    assert _linked_paths(text) == ["./docs/spec.md", "README.md"]


@pytest.mark.parametrize("source", sorted(REPOSITORY_BLOB_PATHS))
def test_every_absolute_repository_url_names_a_path_that_exists(source: str) -> None:
    """Every `blob/main` URL into this repository names a file that is actually
    in the working tree.

    This is a string-and-filesystem check and never a request: the URL's own
    reachability, and whether GitHub would serve it, are not this suite's to
    know. What it does catch is the one failure a relative check cannot see — a
    renamed or deleted document leaving a citation that looks canonical and
    404s for the standalone reader who has no repository to fall back on.
    """

    unresolved = sorted(
        {
            path
            for path in REPOSITORY_BLOB_PATHS[source]
            if not (REPO_ROOT / path).exists()
        }
    )
    assert not unresolved, (
        f"{source} cites this repository at paths that do not exist: {unresolved}"
    )


def test_the_absolute_repository_url_sweep_examines_a_non_empty_set() -> None:
    """The sweep above enforces something: the tree does carry `blob/main`
    citations, and the pattern does find them. A URL pattern that stopped
    matching would otherwise leave no cases at all — and no cases is a suite
    that cannot go red."""

    assert REPOSITORY_BLOB_PATHS, (
        "no blob/main URLs into this repository were extracted from any tracked "
        "file; the citation guard would be enforcing nothing"
    )
