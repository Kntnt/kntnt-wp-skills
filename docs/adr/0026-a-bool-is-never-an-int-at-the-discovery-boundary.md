# A `bool` is never an `int` at the discovery boundary

`bool` subclasses `int` in Python, so `isinstance(True, int)` is true. The discovery assembler's boundary check — `_require(mapping, key, expected, context)` and its optional sibling — was a bare `isinstance`, so every integer field in the module accepted a boolean: an `api_version` of `true` passed the check that exists to reject exactly that, and would have been carried into the canonical document and compared numerically downstream as a 1.

Two things kept it small. The exposure is close to nil — the values come from an Extractor this client authenticates against, over the site owner's own credential — and it was the module's convention from the start, not a regression a change introduced. What made it worth closing is the other half: the convention is shared, so tightening it is a one-place change. The question had also been asked before in this repository and answered locally, in `wpconfig_block.py`, whose define writer already orders its `bool` check ahead of its `int` check for this precise reason; discovery's own boundary never learned it.

## Decision

One predicate decides what a type check means for the whole module: `_has_type(value, expected)` is `isinstance` with a single narrowing — a field declared `int` refuses `True` and `False`, and every other declared type keeps plain `isinstance` semantics.

Both boundary helpers go through it, and so do the module's two hand-rolled integer checks: the entity counts' own check and the file manifest's tolerant size read. No call site changes, the refusal keeps the same shape every other type mismatch produces, and the message names the type that arrived (`must be int, got bool`), so a future occurrence is diagnosable from the diagnostic alone.

A field declared `bool` is deliberately unaffected. The narrowing is *an `int` field rejects a `bool`*, never *a boolean is not a valid value*; the module declares no boolean field today, and the guard on that half exists so that the first one is not broken by this decision.

## Rejected alternatives

- **Leave the convention and record why not.** Defensible on exposure alone, and rejected on cost: it buys a note the next reader has to re-derive, against a predicate that is one function and one line at each of four sites. The question had already been reached twice — once in `wpconfig_block.py`, once here — and the point of settling it is that there is no third time.
- **Narrow at the call site that matters.** Spelling `isinstance(value, int) and not isinstance(value, bool)` for `api_version` alone answers the reported symptom and leaves every other integer field loose, and the next integer field added would start loose again. The knowledge belongs where the type check is decided, not where a field is declared.
- **Adopt a schema validator (`pydantic`) for the input document.** It would restate the whole document's shape to buy one narrowing, and it puts a dependency into a helper whose PEP 723 dependency list is deliberately empty — the assembler runs anywhere `uv` can start a bare interpreter.
- **Tighten every accidental coercion at once** — a float for an `int`, a numeric string, `None` as an absent value. Each is a separate judgement about what the wire is allowed to say, and folding them into a bool narrowing would hide those judgements inside a change nobody reviewed for them.

## Consequences

- Every integer field in the assembler tightens together: the required fields, the optional ones, the entity counts, and the manifest's size. A boolean `size` in a manifest entry now weighs nothing in a subdirectory total instead of the one byte int-ness lent it, which is the tolerant path's documented intent — a non-integer size counts as zero — rather than a new behaviour.
- The narrowing is invisible to any well-formed input. No document that an Extractor produces changes shape, and no run behaves differently; what changes is which malformed inputs are refused.
- **The sibling helpers are deliberately untouched.** `baseline_diff.py` and `classify.py` carry the same bare-`isinstance` convention for their own integer fields, and `poll_extraction.py` reads its progress counters the same way. They are a separate module boundary with their own inputs, and this decision does not silently reach into them; if the same narrowing is wanted there, it is its own change with its own tests.
