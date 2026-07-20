# Design rationale

Why the `build-ollie-site` skill is shaped the way it is: the architecture decisions, and how the conflicts between the source skills were resolved. Read this once to understand the whys; the skill itself (`skills/build-ollie-site/`) is the how.

## The problem

Building a WordPress site on Ollie from a design system and mockups usually degrades into generating one-off block markup per page — every page a fresh pile of blocks with per-instance styling, no shared vocabulary, no cascade. The result drifts from the design system immediately and cannot be maintained. This skill exists to force the opposite: build **bottom-up by Atomic Design**, so the design system's tokens are the foundation, recurring structure becomes shared patterns, and pages are thin compositions of those patterns.

## Architecture: one gated skill, references, and deterministic helpers

**One user-invoked skill, not several.** The workflow is a single ordered sequence — cartography → foundation → components → sections → pages — with hard gates between layers. That is one procedure with one entry point, so it is one skill. Splitting a phase into its own model-invoked skill would buy independent reach nothing else needs, at the cost of an always-loaded description. The phases are gated *inside* the one skill instead.

**Explicit-only invocation.** The skill writes a theme and content into a WordPress install — a consequential act — and the Kntnt ecosystem already settles this class of skill as user-invoked ([ADR-0002](../../docs/adr/0002-skills-user-invoked-only.md) makes it a rule for anything that executes against a site). So `build-ollie-site` sets `disable-model-invocation: true`; it fires on `/build-ollie-site`, never on its own. The description is human-facing and costs no context load.

**A lean spine over disclosed references.** `SKILL.md` carries only the phased, gated procedure and the four load-bearing ideas (ground truth, pattern cartography, compose-don't-duplicate, Ollie-is-tokens-only). Everything a phase needs in depth is a reference file reached by a pointer, loaded only when that phase runs. The novel methodology (cartography) and the divergence catalogue (errata) get their own files because they are the parts with no shortcut.

**Deterministic helpers where prose would be vague.** Four Python helpers own the computations that must not be done by hand: `dump_ground_truth.py` (the resolved tokens and registered patterns from the live install), `mine_structures.py` (the cartography first pass), `lint_markup.py` (the on-system gate), and `check_contrast.py` (the AA gate). Each was validated against the real sample inputs before shipping — the mining helper recovers the sample mockups' reuse structure, the token parser recovers all 108 properties from a real resolved stylesheet, the linter catches every planted violation, and the contrast checker flags the sample's one sub-AA pairing.

## Where the patterns live: an Ollie child theme

**Decision: the child theme, not the `kntnt-` plugin namespace.** The whole atomic stack — the token foundation in `theme.json`, the component and section patterns in `patterns/`, the templates in `templates/` — lives in one Ollie child theme.

**Why.** The foundation is theme-scoped by nature: `theme.json` and global styles are a theme concern, and **a plugin cannot ship a `theme.json`.** If patterns lived in a plugin and tokens in the theme, the two halves of the design system would be split across two artifacts with different lifecycles. Co-locating tokens, patterns, and templates in one child theme makes the design system a single versioned, update-safe unit — which is exactly the coherence the workflow produces. It also keeps everything file-based and reproducible, fitting the DDEV-copy world the Kntnt WordPress tooling already lives in, rather than trapping the design in the database.

**Rejected: a plugin.** A `kntnt-` plugin *can* register patterns (via `register_block_pattern()` on `init`), so patterns alone could live there. But it cannot hold the foundation, so it cannot be the home of a *design system*. The plugin namespace is for functional plugins; a site's look belongs to its theme layer. If patterns are ever needed independently of the theme, a companion MU-plugin can register the same files — but the default and recommended home is the child theme.

## Conflicts between the source skills, resolved

Three source skill sets were studied. None could be adopted wholesale; each conflicts with the constraints in a specific way, resolved explicitly below.

**Ollie's own skill — pattern-first, cloud library.** Ollie's skill defaults to finding and delivering pre-made patterns from its bundled and cloud pattern library, treating from-scratch work as a fallback. That is the direct opposite of the constraint that the site's patterns are the **user's own**. **Resolution:** Ollie is used for *tokens and global styles only*. Its pattern tools (including the `manage-patterns` cloud search) are out of scope; the skill even tells the agent not to call them. What Ollie's skill genuinely contributes — the token vocabulary, the section-wrapper shape, the on-system discipline — is reconstructed in this skill's own words (Ollie's skill is commercial; its files are not copied), and every token value is taken from the live install, not Ollie's prose.

**Ollie's prose diverges from reality.** Ollie's token descriptions are generic and version-dependent, and the two token references in the sample even contradict each other (one claims border-radius emits no CSS variable; the live install emits all seven). **Resolution:** the errata reference records the *kinds* of divergence once, and `dump_ground_truth.py` hands the agent the install's actual resolved tokens — ground truth outranks every remembered value.

**Automattic wp-site-creator — duplicate the expanded markup.** This is the sharpest conflict. wp-site-creator's philosophy is to paste full expanded block markup into each page and to *avoid* patterns/inner-blocks for speed ("NEVER use patterns for the index.html template"; "output the full expanded markup inside each block"). That is the exact opposite of **compose, don't duplicate**. **Resolution:** rejected outright as a philosophy. This skill composes by `wp:pattern` slug reference so a change to a component cascades; duplication is the failure mode the cartography guardrails and the linter's `PATTERN-REF` check exist to prevent. What wp-site-creator *does* contribute is reused: its `theme.json` v3 preset conventions, its WCAG-AA contrast gate (reimplemented in `check_contrast.py`), and its core-block-only discipline.

**Automattic agent-skills (`wp-block-themes`) — a thin routing layer.** This pack is MIT-licensed but deliberately thin: its patterns reference is ~19 lines and defers the mechanics upstream. It documents nothing about `Inserter: no`, the `wp:pattern` reference block, `Block Types`, or `settings.custom`. **Resolution:** its folder conventions and the style-hierarchy override gotcha (user DB global styles override `theme.json`) are adopted; the pattern-composition mechanics — which none of the three sources covers — were sourced directly from WordPress core (`register_block_pattern()` properties, the pattern header fields, and `render_block_core_pattern()`'s render-time expansion and `seen_refs` recursion guard) and written into `references/sections.md`.

## The novel part: pattern cartography

The mission's centrepiece — deriving the pattern taxonomy from mockups by structure — exists in **none** of the source skills (the closest, wp-site-creator's `site-specification`, produces a flat list of section names, not a reuse graph). It was authored from scratch: a content-blind structural-signature test, a component-vs-section classification with a sharp band-ownership boundary, numeric guardrails against over- and under-abstraction, a rule for harvesting the author's own module tags as hypotheses, and a manifest schema whose coverage section is the phase's completion check. `mine_structures.py` makes the first pass deterministic; `references/cartography.md` is the judgment layer the agent applies on top.

## Licensing posture

- **Ollie skill** — commercial; not copied. Mechanics reconstructed independently; the errata reference is this project's own synthesis plus the user's own live-extracted facit.
- **Automattic wp-site-creator** — no license declared (all-rights-reserved); treated as inspiration only, reimplemented.
- **Automattic agent-skills** — MIT; conventions adopted, nothing copied verbatim.
- **WordPress core & developer docs** — the authoritative source for the pattern and theme.json mechanics, cited in the references.
- **The sample design system and mockups** — the user's own example inputs, used to validate the methodology and helpers. The shipped skill is general; the worked example in `cartography.md` is drawn from them but the skill hard-codes nothing site-specific.
