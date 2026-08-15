# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest==8.3.4"]
# ///
"""Consistency tests: the two exclusion matchers stay one implementation.

``scripts/filter_manifest.py`` reduces production's manifest to the in-scope
tree, and ``scripts/baseline_diff.py`` restricts the deletion set to the paths
still in scope this run. They are separate standalone CLIs — the repository
packages no shared module for them to import — so each carries its own copy of
the matcher, and each docstring claims it mirrors the other exactly. The claim
is load-bearing: if the two ever disagree about a single path, the selection
drops a tree the diff still considers in scope, and the next pull reports it as
production-deleted. That is the deletion-diff poisoning issue #35 closed at the
assembly end, reappearing at the matching end.

These tests pin the claim rather than trusting it. They compare the matcher
functions structurally, with docstrings discounted, so the two copies may
describe themselves as mirrors of each other but may not behave differently.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any

import baseline_diff
import build_exclusions
import filter_manifest
import pytest

# The matching seam: the entry point and every helper it dispatches through.
MATCHER_FUNCTIONS = (
    "is_excluded",
    "_matches_anywhere",
    "_matches_at_root",
    "_has_glob",
    "_matches_glob_prefix",
)


def structure_of(function: Any) -> str:
    """Return a function's source with its docstring discounted, so two copies
    that differ only in which sibling module they name as their mirror compare
    equal while any difference in behaviour does not."""

    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    definition = tree.body[0]
    first = definition.body[0] if definition.body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        definition.body.pop(0)
    return ast.unparse(definition)


@pytest.mark.parametrize("name", MATCHER_FUNCTIONS)
def test_the_two_matchers_are_the_same_implementation(name: str) -> None:
    # Assert — same code, whatever the surrounding prose says.
    assert structure_of(getattr(filter_manifest, name)) == structure_of(
        getattr(baseline_diff, name)
    ), f"{name}() has drifted between filter_manifest.py and baseline_diff.py"


def test_the_two_matchers_share_their_matching_constants() -> None:
    # Assert — the allow-list carve-out and the match-anywhere marker are part of
    # the matcher's behaviour, so they drift the same way the code would.
    assert filter_manifest._ALWAYS_ALLOWED == baseline_diff._ALWAYS_ALLOWED
    assert filter_manifest._ANYWHERE_PREFIX == baseline_diff._ANYWHERE_PREFIX


@pytest.mark.parametrize(
    ("path", "excluded"),
    [
        ("wp-content/w3tc-cache/object/a", True),
        ("wp-content/w3tcache/keep.php", False),
        ("wp-content/uploads/backwpup-abc/restore.log", True),
        ("wp-content/uploads/kntnt-extractor/1a2b/x.sealed.building", True),
        ("wp-content/uploads/kntnt-extractor-something-else/keep.jpg", False),
        ("wp-config-sample.php", False),
        ("wp-content/plugins/acme/.env", True),
        ("wp-content/plugins/acme/acme.php", False),
    ],
)
def test_both_matchers_agree_on_the_always_excluded_set(path: str, excluded: bool) -> None:
    # Arrange — the real resolved set's static half, matched by both helpers.
    exclusions = tuple(build_exclusions.ALWAYS_EXCLUDED)

    # Assert — one verdict, reached twice.
    assert filter_manifest.is_excluded(path, exclusions) is excluded
    assert baseline_diff.is_excluded(path, exclusions) is excluded
