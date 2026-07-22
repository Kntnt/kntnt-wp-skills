# Local templates

The transfer engine reaches production **only** through the [Kntnt Extractor](https://github.com/Kntnt/kntnt-extractor) plugin's REST API ([ADR-0016](../docs/adr/0016-kntnt-extractor-replaces-novamira-as-control-channel.md), [ADR-0017](../docs/adr/0017-discovery-over-extractor-rest-two-phase.md)). The plugin owns the extraction, the sealing, the one-time download link, and the cleanup, so there are **no production-side PHP payloads to send** — the retired `execute-php` templates (`liveness.php`, `exec-probe.php`, `stranded-sweep.php`, `download-preflight.php`, `discovery.php`, `manifest.php`) are gone, replaced by the REST surface the skills call directly.

One file therefore remains in this directory, and it never travels over the control channel: the local capture mu-plugin.

## The local capture mu-plugin

`kntnt-wp-skills-mailpit.php` is a standalone WordPress mu-plugin — a full plugin header, `declare(strict_types=1)`, and its own `Kntnt\Wp_Skills\Mailpit` namespace — that the engine drops into the **local** copy's `wp-content/mu-plugins/` when the mail decision resolves to capture. It short-circuits `wp_mail` at `PHP_INT_MIN` priority and re-routes every message to DDEV's Mailpit, so a fresh copy can never mail real recipients ([ADR-0009](../docs/adr/0009-live-mail-default-with-mass-send-valve.md)). It catches API mailers that never touch sendmail.

## This mu-plugin is inert here

Nothing in this directory is executed against a live site during the build. Per the specification's Testing Decisions, the sole automated seam is the deterministic helper CLI (`scripts/*.py`, exercised by `tests/`); the mu-plugin's real behaviour is a **human-verified residual**, exercised by the engine's own verify phase on every run and by the manual end-to-end smoke before release. Its structure is bound by `tests/test_mailpit_template.py` as a source file under the project coding standard.
