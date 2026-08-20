# A define's disclosure is read from the protocol member, never from its value

[ADR-0020](./0020-withheld-define-values-are-never-ported.md) settled that a define whose value `GET /environment` returned as `null` is never ported, and built that on the only signal available at the time: the value itself. The Extractor has since shipped a per-record discriminator that says outright why a value is what it is — `docs/define-disclosure.md` in `kntnt-extractor`, the protocol behind its API version 7 — and that document is normative about how a reader must use it: *"A reader MUST NOT infer a define's disclosure state from `value` alone; `disclosure` is the only reliable signal."* This client was still inferring, and paid for it twice.

First, it stated something false about a live production site. A define on the server's allow-list whose real value is `null` — a legitimate `define('X', null)`, or an allow-listed name not currently defined on that install — was reported to the operator as one *"the Extractor did not disclose"*. Second, it gave one remedy for two different problems. A `secret` withholding and a `not_allow_listed` one are not the same situation: the first is a name shaped like a credential, which generally *should* stay withheld, while the second is a name the site operator can opt in explicitly through the Extractor's own `KNTNT_EXTRACTOR_DISCLOSABLE_DEFINES` constant. "Configure it locally if the plugin needs it" is the right advice for exactly one of them.

This ADR refines ADR-0020. It does not supersede it: the conclusion that a `null` is never written into the local `wp-config.php` survives intact, and the reasoning below is why.

## Decision

A define's disclosure state is read from the `disclosure` member. `skills/clone/scripts/discovery.py` carries the member into the canonical document when the server sent one and **omits the key entirely** when it did not; `skills/mkwp/scripts/classify.py`'s `classify_defines()` asks the name-based classes first, then the discriminator, and only then falls back to the value.

The value-based rule of ADR-0020 survives as that fallback, and only as that fallback. This client pins Extractor to API version ≥ 2, the protocol arrived at version 7, and the protocol's own present-on-every-record rule makes an absent `disclosure` mean "this server predates the protocol" rather than "this record is disclosed". Against such a server a `null` value is the only signal a withholding ever had, so the old rule is exactly right there — and it is dead code the day the floor rises above 6.

**The enum is closed.** `included` is the one verdict that is not a withholding. Every other string — `secret`, `not_allow_listed`, and any fourth value a future Extractor introduces that this client has never heard of — is treated as a withholding, *including when the record carries a present value*. The protocol requires this, and the reason is worth restating: a reader that optimistically read an unknown verdict as a disclosure would port a value the server had declined to disclose, which is the precise failure the whole protocol exists to prevent. A non-string `disclosure` is malformed rather than unknown, and drops to the pre-protocol path.

Every auto-excluded record in the `withheld` class now carries a `reason`: the server's own discriminator verbatim, or one of this client's two — `disclosed_null` and `value_withheld_pre_protocol`. The run report branches on it, because the remedy branches on it. A name-classified record (a credential, a salt, a domain/path constant, an infrastructure constant) carries no `reason` at all; its class is the whole of the explanation, and the name-based verdict still wins before the discriminator is consulted, so a `DB_PASSWORD` some future server policy marks `included` is still `credentials` and still never ported.

## Why a disclosed `null` is still not ported

This is the part that could reasonably go the other way, and it is stated in full so a future reader does not mistake it for a forced conclusion.

The harm ADR-0020 identified does not depend on where the `null` came from. Writing `define('NAME', null);` into the local `wp-config.php` makes `defined('NAME')` report `true`, which suppresses whatever fallback the owning plugin runs for "not configured" — and it does so identically whether the `null` was the Extractor's mask or production's own live value. `php -l` passes either way; the smoke test catches neither. So the `disclosed_null` case is auto-excluded under the same `withheld` class as the two real withholdings, and never written.

The counter-argument is real. A faithful copy of a site that genuinely defines `null` would reproduce production's own behaviour, suppressed fallback included, and there is a coherent position that a clone's job is to be faithful rather than to be helpful. This client chose not to take it, for one reason: the operator is told the define's name and its reason, and can define it locally in one line if the copy needs it — whereas an unexplained suppressed fallback on a local copy is a debugging cost with no signal attached to it at all. The asymmetry is between a cost that announces itself and a cost that does not.

Were that judgement reversed, the change is small and local: the third branch of `classify_defines()`'s decision, and the `disclosed_null` bullet in both run reports. It would, however, change ADR-0020's conclusion, and belongs in its own ADR rather than in a refactor.

## What this does not claim

- **No define becomes portable that was not portable before.** The `withheld` class is decided per record instead of by value alone, and gains a `reason`; nothing moves from `auto_excluded` to `portable`. The framing that consuming `disclosure` "recovers the legitimately-null case" is not what happened. What was recovered is the *truth told to the operator* about which case they are in.
- **This client does not verify the server's policy.** The protocol is explicit: *"A reader MUST NOT hard-code the current allow-list's membership … The same holds for the heuristic that produces `secret`."* Which names the server allow-lists, and which substrings its heuristic matches, may change between Extractor releases without an `api_version` bump. No test in this repository asserts either; the tests bind the client's handling of the three enum values and nothing beyond them.
- **`is_secret_define()` is not touched.** `skills/clone/scripts/discovery.py`'s own redaction at the trust boundary (safety rail 8) stays exactly as it is. It answers a different question from the server's policy — what this client refuses to carry, not what the server refuses to disclose — and binding the two lists together would couple this repository to policy that lives in another one. Binding the *protocol* rather than the membership is what this ADR does, and it is the whole of what it does.

## Consequences

- The auto-excluded shape contract gains an optional third key. `reason` is present on a `withheld` record and absent on a name-classified one; the `value` key remains absent from every auto-excluded record, secrets included. `resolve_plan.py`'s gate reads `portable` and is unaffected.
- `wpconfig_block.py`'s refusal of a `None` define value stays unreachable defence in depth. No path routes a null-valued define to `portable`, on either the protocol or the fallback branch.
- Both run reports now give four distinguishable remedies where they gave one, and an unrecognised discriminator is reported as unrecognised rather than silently mapped onto a remedy that may not fit it.
- The pre-protocol fallback, the `value_withheld_pre_protocol` reason, and its report branch are a matched set. If the API-version floor is ever raised above 6, all three are dead and should be deleted together.
