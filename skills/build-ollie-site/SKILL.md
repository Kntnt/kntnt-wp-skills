---
name: build-ollie-site
disable-model-invocation: true
description: >
  Build a coherent, token-correct WordPress site on the Ollie block theme from a
  design system and a set of mockups, bottom-up by Atomic Design: foundation →
  component patterns → section patterns → pages. Explicit-only. Trigger on
  `/build-ollie-site`, `/kntnt-wp-skills:build-ollie-site`, or an unmistakable
  request to build an Ollie site this way. Because it writes a theme and content
  into a WordPress install, it never auto-triggers; when in doubt, ask first.
---

# build-ollie-site

Build a WordPress site on **Ollie** the way a design system is meant to be built: **bottom-up**, by **Atomic Design**. The foundation is the theme's design tokens; everything above references them and adds nothing the layer below cannot express.

```
tokens (theme.json / global styles)   ← the foundation everything references
   └─ core blocks                     ← atoms, styled entirely by the tokens
        └─ component patterns          ← molecules  (card, stat, button row, icon-feature)
             └─ section patterns       ← organisms  (hero, feature grid, CTA band)
                  └─ pages             ← section patterns in sequence
```

You build in that order and no other. **A later layer is never built before the one below it is locked and verified** — a section cannot compose a component that is not yet registered, and no pattern can reference a token that is not yet resolving. Each phase ends on a **lock** you can check.

Four ideas run through every phase; treat each as load-bearing.

- **Ground truth.** Ollie's descriptions drift from what a given install actually resolves (its own docs even disagree with each other — see `references/ollie-errata.md`). Never build against remembered token values. Ask the install what it resolves and register, with `scripts/dump_ground_truth.py`, and build against that.
- **Pattern cartography.** The mockups' patterns are the user's own and are not yet marked up. Phase 1 *derives* the taxonomy from them by reading **structure, not content**. This is the centerpiece and has no shortcut — `references/cartography.md`.
- **Compose, don't duplicate.** Structure that recurs becomes one pattern, referenced by slug — never a pasted copy. Section patterns nest component patterns with `<!-- wp:pattern {"slug":"…"} /-->`; editing the component then cascades everywhere it is used.
- **Ollie is tokens and global styles only.** Its bundled and cloud pattern libraries are out of scope — the site's patterns are the user's own. One design system; every value resolves to an Ollie token.

## Where everything lives — an Ollie child theme

The whole atomic stack lives in **one Ollie child theme**: the token foundation in its `theme.json` (or a style variation), the component and section patterns in its `patterns/` directory, the templates in `templates/`. One versioned, update-safe artifact holds tokens, patterns, and templates together — which is exactly the coherence this workflow exists to produce. A plugin cannot ship `theme.json`, so it cannot be the foundation's home; that is why the child theme wins over the `kntnt-` plugin namespace here ([DESIGN-RATIONALE](DESIGN-RATIONALE.md)). Pages are content: created in the install, referencing the registered section patterns by slug.

Your hands on the install are **WP-CLI** (`ddev wp` locally) for files and verification, and optionally the **Ollie Abilities / MCP** for content operations (creating pages, quick block edits, reading global styles). Do not use the Ollie Abilities' pattern tool — it serves the forbidden cloud library.

## Help gate

If the arguments are `help`, `--help`, or `-h`, run `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/help.py" build-ollie-site`, emit its output verbatim as Markdown, and stop. Do nothing else.

## Procedure

Read the reference named in each phase before doing it. Do not start a phase until the phase before it is **locked**.

### Phase 0 — Ground truth

Establish reality before building on it. Confirm Ollie is the active theme's parent and set up (or locate) the child theme. Run `scripts/dump_ground_truth.py --json ground-truth.json` to capture the resolved token set (every `--wp--…` name and value) and the already-registered patterns. Read `references/ollie-errata.md` and reconcile any Ollie claim you were about to rely on against the dump.

**Lock:** you hold `ground-truth.json`; Ollie is confirmed as the parent theme; the child theme exists and is active.

### Phase 1 — Pattern cartography → the manifest

Derive the pattern taxonomy from the mockups by structure. Run `scripts/mine_structures.py <mockups> --json candidates.json` for the deterministic first pass, then curate it against `references/cartography.md`: apply the same-structure test, classify each recurring structure as a **component** or **section** pattern, and map how each section composes from components and how each page sequences its sections. Produce the **pattern manifest**.

This is a judgment task, so it is **human-in-the-loop**: present the manifest — component list, section list, per-section composition, per-page sequence — and settle it with the user before building anything.

**Lock:** a manifest the user has confirmed, in which every band of every mockup is accounted for (mapped to a section pattern, or explicitly a one-off).

### Phase 2 — Foundation (tokens)

Map the design system onto the child theme's `theme.json`, following `references/foundation.md`. Names come from the closed WordPress preset set (ground truth); only the values are the design system's. Re-run `dump_ground_truth.py` and confirm the tokens you intended now resolve exactly. Gate every background/text pairing through `scripts/check_contrast.py` for AA.

**Lock:** the dump shows the intended tokens resolving with the intended values; every pairing passes AA. This is the foundation — do not revisit it once a pattern references it.

### Phase 3 — Component patterns (molecules)

Build each component from the manifest as a `patterns/*.php` file, per `references/components.md`: `Inserter: no`, slug-namespaced to the child theme, core blocks only, every value a token. Lint each with `scripts/lint_markup.py --ground-truth ground-truth.json` and confirm it renders once in the editor.

**Lock:** every manifest component is registered, lint-clean, and confirmed once.

### Phase 4 — Section patterns (organisms)

Build each section from the manifest as a full-width band that composes its components by slug reference, per `references/sections.md`. Genuinely unique one-offs stay as raw core blocks inside the section file. Lint with `lint_markup.py --ground-truth ground-truth.json --patterns-dir <patterns>` so every `wp:pattern` reference is proven to resolve.

**Lock:** every manifest section is registered, lint-clean, and every nested reference resolves.

### Phase 5 — Pages

Assemble each page from its section sequence in the manifest, per `references/pages.md` — mainly section patterns, the occasional loose component, raw blocks only for a sanctioned one-off. Verify each page renders and that no section duplicated markup it should have referenced.

**Lock:** every manifest page exists and renders; the site matches the mockups' structure with the design system's tokens throughout.

## References

- `references/cartography.md` — the same-structure test, component-vs-section classification, the guardrails against over- and under-abstraction, and the manifest schema.
- `references/foundation.md` — mapping a design system into `theme.json`; the fluid-type trap; verifying resolved tokens.
- `references/ollie-errata.md` — how Ollie's prose diverges from installs, and how to verify live.
- `references/components.md` — component-pattern file conventions.
- `references/sections.md` — section-pattern composition and the `wp:pattern` reference mechanics.
- `references/pages.md` — page and template assembly.
- `references/markup.md` — block-markup mechanics shared by every layer (the section wrapper, the comment↔HTML sync rule, token reference forms).
