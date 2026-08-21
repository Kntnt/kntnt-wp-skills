"""Type-checking guards — the standard states what the project actually runs.

The Python module of the coding standard used to require "strict mode on new
code" while the repository carried no type-checker configuration at all, so
nothing enforced it and nothing could: two strict-mode regressions landed
unnoticed, three separate verifiers ran a checker of their own accord, and
every ticket in the queue had to argue in its own status row which findings
were pre-existing (issues #71, #74).

Strict type checking is now a verification step the project runs, on the same
"one command, provisioned through ``uv``" shape as the test suite, reproducing
from the repository's own ``[tool.mypy]`` configuration rather than from flags
a caller has to remember. These tests pin the three halves that can drift apart
from one another:

- **What is checked.** The configuration's ``files`` list is the scope decision
  and is permanent, so it is bound here to the same three helper homes
  ``pytest.ini`` puts on the import path and ``docs/spec.md`` calls the
  deterministic helper seam. ``skills/build-ollie-site/scripts/`` is outside it
  deliberately ([ADR-0032](../docs/adr/0032-strict-type-checking-is-enforced-ruff-is-advisory.md)),
  and the configuration has to say so in its own text rather than leave a
  reader to notice an omission.
- **What the command provisions.** ``mypy`` cannot read a PEP 723 header, so
  the one third-party dependency any checked helper declares has to be named a
  second time in the documented command. A second copy of a pinned version is
  a drift hazard, so the helper's own header is the source of truth and every
  document that quotes the command is checked against it.
- **What the standard claims.** Strict type checking is enforced; ruff is the
  chosen linter but is unconfigured and advisory until a ruleset is pinned, so
  the result of a bare ruff run is not a verdict on a change. The standard has
  to say both, so no executor has to re-derive it.

Prose assertions here are regexes over documents, exactly as the other
consistency suites in this directory are, and they bind wording rather than
behaviour on purpose: the wording *is* the deliverable for the half of this
that instructs a human or an agent.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
PYPROJECT: Path = REPO_ROOT / "pyproject.toml"
PYTEST_INI: Path = REPO_ROOT / "pytest.ini"

# The deterministic helper seam (`docs/spec.md`, § *The deterministic helper
# seam*): the three homes that hold every helper the transfer engine drives,
# and exactly what the enforced check covers.
HELPER_HOMES: tuple[str, ...] = ("scripts", "skills/clone/scripts", "skills/mkwp/scripts")

# The helper home deliberately outside the check: `build-ollie-site` shares
# none of the transfer engine's machinery and its helpers are written against
# an older floor with no dependency metadata at all.
EXCLUDED_HELPER_HOME: str = "skills/build-ollie-site/scripts"

# The Python floor every checked helper declares, and the one third-party
# dependency any of them needs.
PYTHON_FLOOR: str = ">=3.12"
DEPENDENT_HELPER: str = "skills/clone/scripts/unseal.py"

# Every document that quotes a verification command, and so has to quote the
# type-check one at the pin the dependent helper's own header declares.
COMMAND_SURFACES: tuple[str, ...] = (
    "CONTRIBUTING.md",
    "agents.d/coding-standard/python.md",
    "plans/README.md",
)

# The suppressions that predate the enforced check, by the file that carries
# them. Pinned as counts rather than lines so an edit above them does not
# redden this, and pinned at all so a *new* suppression does: clearing a strict
# finding by silencing it is the one repair the enforced check exists to refuse.
PRE_EXISTING_SUPPRESSIONS: dict[str, int] = {"skills/clone/scripts/bootstrap_parse.py": 2}


def checked_helpers() -> list[Path]:
    """Every helper the configured check covers, in a stable order."""

    return sorted(
        path
        for home in HELPER_HOMES
        for path in (REPO_ROOT / home).glob("*.py")
    )


def pep723_metadata(script: Path) -> dict[str, object]:
    """Parse a standalone script's PEP 723 inline metadata block.

    Raises rather than returning empty when the block is missing: a helper with
    no inline metadata is a defect this suite exists to catch, not a case to
    skip past silently.
    """

    block = re.search(
        r"^# /// script\n(?P<body>(?:^#(?: .*)?\n)*?)^# ///$",
        script.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if block is None:
        raise AssertionError(f"{script.relative_to(REPO_ROOT)} carries no PEP 723 metadata block")

    return tomllib.loads(
        "\n".join(line[2:] if line.startswith("# ") else line[1:] for line in block["body"].splitlines())
    )


def mypy_config() -> dict[str, object]:
    """The repository's own type-checker configuration."""

    assert PYPROJECT.is_file(), (
        "the repository must carry a pyproject.toml holding the type-checker "
        "configuration, so the check reproduces without ad-hoc flags"
    )
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    tools = config.get("tool", {})
    assert isinstance(tools, dict) and "mypy" in tools, "pyproject.toml declares no [tool.mypy] section"
    section = tools["mypy"]
    assert isinstance(section, dict)
    return section


def documented_command() -> str:
    """The type-check command, built from the pin its dependent helper declares.

    Every document quoting the command is held to this string, so the second
    copy of the version can never drift away from the PEP 723 header that owns
    it — the header wins, and this suite is how it wins.
    """

    dependencies = pep723_metadata(REPO_ROOT / DEPENDENT_HELPER)["dependencies"]
    assert isinstance(dependencies, list) and len(dependencies) == 1
    return f"uv run --with mypy --with {dependencies[0]} mypy"


def test_the_repository_configures_strict_type_checking() -> None:
    """Strict mode is declared in the repository, so the documented command
    needs no flag a caller could forget."""

    assert mypy_config().get("strict") is True, (
        "[tool.mypy] must set strict = true, so the documented command needs no "
        "--strict flag to reproduce the check"
    )


def test_the_checked_tree_is_the_deterministic_helper_seam() -> None:
    """The configuration's ``files`` list is the permanent scope decision, and
    it names the three helper homes ADR-0032 settled on."""

    assert mypy_config().get("files") == list(HELPER_HOMES), (
        "[tool.mypy]'s files list is the scope decision (ADR-0032); it must name "
        "the three helper homes and no others"
    )


def test_the_checked_tree_is_the_tree_the_test_suite_imports_from() -> None:
    """The checked tree and the imported tree are one tree: a helper home added
    to `pytest.ini` alone would be tested but never type-checked."""

    pythonpath = re.search(r"^pythonpath = (.+)$", PYTEST_INI.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert pythonpath is not None
    assert sorted(pythonpath.group(1).split()) == sorted(HELPER_HOMES), (
        "the checked tree and the imported tree are the same tree; a new helper "
        "home has to be added to both pytest.ini and [tool.mypy]"
    )


def test_the_configuration_states_what_it_leaves_out_and_that_the_list_must_grow() -> None:
    """A deliberate exclusion reads as an oversight unless the file says
    otherwise, and a directory list cannot notice a home nobody added to it."""

    text = PYPROJECT.read_text(encoding="utf-8")
    assert EXCLUDED_HELPER_HOME in text, (
        f"{EXCLUDED_HELPER_HOME} is excluded deliberately, and the configuration must "
        "say so rather than leave the exclusion as an omission a reader has to notice"
    )
    assert re.search(r"new (helper home|skill)", text), (
        "the configuration must state that a new helper home has to be added to the "
        "list, since a directory list cannot notice one on its own"
    )


def test_the_configuration_declares_no_distribution() -> None:
    """The helpers are standalone PEP 723 scripts; the configuration file must
    not quietly turn the repository into an installable package."""

    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert "project" not in config and "build-system" not in config, (
        "the helpers are standalone PEP 723 scripts, not a package; pyproject.toml "
        "holds tool configuration only and must not make the repository installable"
    )


@pytest.mark.parametrize("helper", checked_helpers(), ids=lambda path: path.name)
def test_every_checked_helper_keeps_its_declared_python_floor(helper: Path) -> None:
    """No type-level repair may raise a helper's runtime floor."""

    assert pep723_metadata(helper)["requires-python"] == PYTHON_FLOOR


@pytest.mark.parametrize("helper", checked_helpers(), ids=lambda path: path.name)
def test_only_the_unseal_helper_declares_a_dependency(helper: Path) -> None:
    """No type-level repair may add a runtime dependency, and the one that
    exists stays exactly where and what it was."""

    expected = ["pynacl==1.5.0"] if helper == REPO_ROOT / DEPENDENT_HELPER else []
    assert pep723_metadata(helper)["dependencies"] == expected


@pytest.mark.parametrize("surface", COMMAND_SURFACES)
def test_every_verification_surface_names_the_type_check_command(surface: str) -> None:
    """A verification step four documents describe differently is one nobody
    runs the same way twice."""

    command = documented_command()
    assert command in (REPO_ROOT / surface).read_text(encoding="utf-8"), (
        f"{surface} must quote the type-check command verbatim as `{command}` — the "
        "dependency is resolved so the checker can see it, never ignored"
    )


def test_no_surface_tells_a_reader_to_ignore_missing_imports() -> None:
    """Suppressing the missing import manufactures a finding that does not
    exist and blinds the check where a real one could hide."""

    for surface in (*COMMAND_SURFACES, "pyproject.toml"):
        text = (REPO_ROOT / surface).read_text(encoding="utf-8")
        assert "ignore_missing_imports" not in text and "--ignore-missing-imports" not in text, (
            f"{surface} must not suppress missing imports: doing so manufactures a "
            "phantom finding in the unseal helper and blinds the check at the only "
            "boundary a real one could hide behind"
        )


def test_the_python_standard_states_that_type_checking_is_enforced() -> None:
    """The standard states what is enforced, not what is intended — the gap
    between the two is what let two regressions land."""

    text = (REPO_ROOT / "agents.d" / "coding-standard" / "python.md").read_text(encoding="utf-8")
    assert "Strict mode on new code." not in text, (
        "the standard must stop stating a requirement as an intention; it now names "
        "the command that enforces it"
    )
    assert re.search(r"\benforced\b", text), "the standard must say strict type checking is enforced"


def test_the_python_standard_states_that_ruff_is_advisory() -> None:
    """Ruff's finding count here is a property of the invocation, not of the
    code, so the standard must stop implying a linter runs."""

    ruff_line = next(
        line
        for line in (REPO_ROOT / "agents.d" / "coding-standard" / "python.md")
        .read_text(encoding="utf-8")
        .splitlines()
        if "**ruff**" in line
    )
    assert "unconfigured" in ruff_line and "advisory" in ruff_line, (
        "the standard must stop implying a linter runs: ruff is chosen but "
        "unconfigured and advisory until a ruleset is pinned"
    )


def test_no_new_suppression_hides_a_strict_finding() -> None:
    """A strict finding is repaired by making the types honest; only the
    suppressions that predate the enforced check are permitted."""

    found = {
        str(helper.relative_to(REPO_ROOT)): len(
            re.findall(r"#\s*type:\s*ignore", helper.read_text(encoding="utf-8"))
        )
        for helper in checked_helpers()
    }
    assert {path: count for path, count in found.items() if count} == PRE_EXISTING_SUPPRESSIONS, (
        "a strict finding is repaired by making the types honest, never by silencing "
        "it; only the suppressions that predate the enforced check are permitted"
    )
