"""Credential-handling consistency test — issue #44.

Two problems, one root: the Application Password's home was a convention
that existed only in the operator's head (macOS Keychain, service
``kntnt-extractor-app-password``, account ``<wp-user>@<host>``), and the
health check presumed "the configured" password simply existed rather than
resolving and verifying it. This suite binds:

- the Keychain convention and its environment-variable fallback, documented
  in ``docs/spec.md``;
- the health check's own resolution of the credential (step 1) and its
  precise remediation when the credential is absent;
- both ``SKILL.md`` files' "How the engine works" section stating the
  resolve-in-a-subshell, never-echoed discipline that keeps the secret out
  of the orchestrator's own context.

Companion to ``test_agent_delegation_consistency.py``'s
``test_agent_input_is_a_credential_reference_not_a_password_value`` and
``test_agent_resolves_the_credential_itself_in_a_subshell``, which bind the
subagent side of the same contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repository layout. This test sits at ``tests/``, one level below the root.
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SPEC: Path = REPO_ROOT / "docs" / "spec.md"
SKILLS: dict[str, Path] = {
    "clone": REPO_ROOT / "skills" / "clone" / "SKILL.md",
    "pull": REPO_ROOT / "skills" / "pull" / "SKILL.md",
}

# The settled convention (issue #44): the canonical Keychain service name and
# the portable environment-variable fallback name. Both are literal strings
# an operator or a fresh session must be able to find verbatim.
KEYCHAIN_SERVICE: str = "kntnt-extractor-app-password"
ENV_VAR_NAME: str = "KNTNT_EXTRACTOR_APP_PASSWORD"


def test_spec_documents_the_keychain_service_and_retrieval_command() -> None:
    """The Keychain convention's service name and the exact retrieval
    invocation must be written down — an agent with no memory of the smoke
    test must be able to find it here, not just in the operator's head."""

    spec = SPEC.read_text(encoding="utf-8")
    assert KEYCHAIN_SERVICE in spec, (
        f"spec.md never names the Keychain service {KEYCHAIN_SERVICE!r}"
    )
    assert "security find-generic-password" in spec, (
        "spec.md never documents the `security find-generic-password` retrieval command"
    )
    assert "<wp-user>@<host>" in spec, (
        "spec.md never documents the Keychain account convention `<wp-user>@<host>`"
    )


def test_spec_documents_the_env_var_fallback_and_precedence() -> None:
    """A non-macOS host has no Keychain, so the convention names a portable
    environment-variable fallback and states which source wins when both
    could apply."""

    spec = SPEC.read_text(encoding="utf-8")
    assert ENV_VAR_NAME in spec, (
        f"spec.md never names the environment-variable fallback {ENV_VAR_NAME!r}"
    )
    assert re.search(r"precedence", spec, re.IGNORECASE), (
        "spec.md never states the precedence between the Keychain and the "
        "environment-variable fallback"
    )


def test_spec_documents_the_subshell_and_never_echoed_discipline() -> None:
    """The retrieval command must be documented as run inside a subshell and
    never echoed or interpolated into logged output — the same discipline
    the subagents themselves must follow."""

    spec = SPEC.read_text(encoding="utf-8")
    assert "subshell" in spec.lower(), (
        "spec.md never states the credential is resolved inside a subshell"
    )
    assert re.search(r"never echoed|never log", spec, re.IGNORECASE), (
        "spec.md never states the resolved credential is never echoed or logged"
    )


@pytest.mark.parametrize("skill,path", sorted(SKILLS.items()))
def test_skill_states_a_credentials_paragraph(skill: str, path: Path) -> None:
    """AC: both SKILL.md files' "How the engine works" section state the
    credential's source as a reference (Keychain service+account, or an
    environment-variable name) — never a bare "the configured" literal."""

    text = path.read_text(encoding="utf-8")
    assert re.search(r"\*\*Credentials\.\*\*", text), (
        f"{skill} SKILL.md has no **Credentials.** paragraph in "
        "'How the engine works'"
    )
    assert KEYCHAIN_SERVICE in text, (
        f"{skill} SKILL.md's Credentials paragraph never names the Keychain "
        f"service {KEYCHAIN_SERVICE!r}"
    )
    assert ENV_VAR_NAME in text, (
        f"{skill} SKILL.md's Credentials paragraph never names the "
        f"environment-variable fallback {ENV_VAR_NAME!r}"
    )


@pytest.mark.parametrize("skill,path", sorted(SKILLS.items()))
def test_skill_health_check_resolves_the_credential_in_step_one(
    skill: str, path: Path
) -> None:
    """AC: the health check (step 1, dependency verification) actually
    resolves the credential from the documented source and fails with the
    exact remediation when it is absent — never presumes "the configured"
    password exists."""

    text = path.read_text(encoding="utf-8")
    step_one = re.search(
        r"1\. \*\*Verify dependencies\.\*\*.*?(?=\n\d\. \*\*)", text, re.DOTALL
    )
    assert step_one is not None, f"{skill} SKILL.md's step 1 is not found"
    step_one_text = step_one.group(0)

    assert re.search(r"resolves? the credential", step_one_text, re.IGNORECASE), (
        f"{skill} SKILL.md's step 1 never states that it resolves the credential"
    )
    assert "create a Keychain item" in step_one_text, (
        f"{skill} SKILL.md's step 1 does not carry the exact remediation "
        "'create a Keychain item: service ..., account ...'"
    )
    assert KEYCHAIN_SERVICE in step_one_text and "account" in step_one_text.lower(), (
        f"{skill} SKILL.md's step 1 remediation omits the exact service/account"
    )


@pytest.mark.parametrize("skill,path", sorted(SKILLS.items()))
def test_skill_no_longer_presumes_a_bare_configured_password(
    skill: str, path: Path
) -> None:
    """The retired wording — "the configured Application Password", stated as
    though it simply exists — must not survive step 2's authorisation proof;
    it now proves the channel with the credential step 1 already resolved."""

    text = path.read_text(encoding="utf-8")
    assert "on the configured Application Password" not in text, (
        f"{skill} SKILL.md still presumes 'the configured Application "
        "Password' rather than the credential resolved in step 1"
    )
