# A withheld define value is never ported

`GET /environment` masks a subset of production's wp-config defines by returning their value as `null` — the secret family today (`DB_PASSWORD`, the four auth keys, the salts, the nonces), and, once the Extractor replaces that deny-list with an allow-list, every non-core define it does not recognise, including ordinary plugin defines such as a third-party API key. `scripts/discovery.py`'s canonical document carries that `null` straight through: it is a second, independent line of defence that redacts the names it already knows, and a value that arrived already masked passes through unchanged as `None`. Distinguishing "the Extractor withheld this" from "the value is genuinely null" is not discovery's job.

Until now nothing downstream made that distinction either. `skills/mkwp/scripts/classify.py`'s `define_class()` classifies a define by name alone; a name it does not recognise is portable, value and all, and the value travels unexamined into the marked block `scripts/wpconfig_block.py` writes. Today that is harmless by coincidence — every name the Extractor currently masks is also routed to an auto-excluded class by name — but the coincidence ends with the allow-list change: a masked plugin API key is not in any name-based auto-excluded family, so it would be offered at the `wp_config_defines` gate and written as `define('SOME_API_KEY', null);` into the local `wp-config.php`. `php -l` passes; the smoke test says nothing; the operator is never told. `defined('SOME_API_KEY')` then reports `true`, so the plugin's "not configured" fallback never fires and it runs with a null key instead, failing somewhere far from the cause — worse than the define being absent altogether.

## Decision

`null` on the wire from `GET /environment` means **withheld**, never "the value is null". `skills/mkwp/scripts/classify.py`'s `classify_defines()` now checks the value, not just the name: a define that `define_class()` would otherwise leave portable, but whose value is `None`, is instead classified auto-excluded under a new class, `withheld`. A name-classified define (a credential, a salt, a domain/path constant, an infrastructure constant) keeps its own class regardless of its value — the value check runs only after the name-based classes have had their turn, so the existing four families are not eroded by the new one.

A withheld define is therefore never offered at the `wp_config_defines` gate — `scripts/resolve_plan.py`'s `live_portable_defines()` reads only the `portable` list, so routing it out in the classifier removes it from the gate for free — and never written: `scripts/wpconfig_block.py`'s `_defines()` boundary additionally rejects any define record whose value is `None`, as defence in depth for a caller that hand-built its `defines` list outside the normal classifier-to-writer path. Every withheld define is named to the operator in the run report, so the failure mode does not simply move from a silent `null` to a silently unconfigured plugin.

The check is `value is None`, deliberately never a truthiness test. `false`, `0`, and `""` are real, present values — a common shape for a WordPress behaviour define — and must still port; `if not value` would silently stop porting every one of them.

## Rejected alternatives

- **Port it as PHP `null` (the status quo).** Rejected: `defined('NAME')` reports `true` regardless of the value written, so this turns a missing configuration value into a wrong one, and does so silently.
- **Treat it as portable but skip it silently at the writer.** Rejected: the operator would never learn the define exists, let alone that its value did not come down — the same silent failure moved one file downstream.
- **Distinguish withheld from null with a new wire field.** Rejected: it needs an Extractor change and an `api_version` bump for a case a value check settles entirely client-side, against every Extractor from API version 2 upward.

## Consequences

- `classify.py`'s auto-excluded shape contract — a record carries `name` and `class`, never a `value` — extends to the new class without amendment; `withheld` is just a fifth member of a set the writer already treats as "dropped, never written".
- The client is now correct against an Extractor that widens what it masks, without any coordinated release: the allow-list change can ship on its own schedule and the withheld class already covers whatever it starts returning `null` for.
- Nothing here lets the operator supply a value for a withheld define at the gate; that would mean prompting for secrets in the clone flow, which cuts against the rule that secrets never enter model context. If ever wanted, it is a separate decision with its own ADR.
- The Extractor currently returns every non-core define in cleartext, which is how a real third-party API key came down uninspected on a live run — a server-side gap this plan does not close. This ADR is what makes the client correct once the allow-list change lands; the allow-list itself belongs to `kntnt-extractor`.
