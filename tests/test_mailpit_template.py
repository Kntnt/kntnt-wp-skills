"""Consistency check for the shipped Mailpit capture mu-plugin template.

The capture branch installs this mu-plugin to short-circuit ``wp_mail`` at top
priority and deliver to DDEV's Mailpit — catching API mailers that never touch
sendmail. This is a content check (no PHP runtime), guarding the settled
literals: the ``pre_wp_mail`` hook, top priority, and the Mailpit port.
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "templates"
    / "kntnt-wp-skills-mailpit.php"
)


def test_template_exists() -> None:
    """The plugin ships the capture mu-plugin template."""

    assert _TEMPLATE.is_file()


def test_template_captures_wp_mail_to_mailpit_at_top_priority() -> None:
    """It intercepts wp_mail before any mailer runs and points at Mailpit."""

    source = _TEMPLATE.read_text(encoding="utf-8")

    assert "declare(strict_types=1)" in source
    assert "pre_wp_mail" in source
    assert "PHP_INT_MIN" in source
    assert "1025" in source
    assert "127.0.0.1" in source or "localhost" in source
