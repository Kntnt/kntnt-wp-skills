# Pattern cartography

The mockups are the user's own design, not yet marked up as WordPress patterns. Before anything is built, you **derive** the pattern taxonomy from them. This is the map the whole build follows; get it wrong and every later layer inherits the mistake.

The one rule that makes it tractable: **read structure, not content.** Content — the words, the images, the colours, the number of items in a row — varies by design and tells you nothing about what is reusable. Structure — the arrangement of containers and the roles of the slots inside them — is what recurs, and recurring structure is what becomes a pattern. Two regions that look different because their content differs may be the *same pattern*; two that look similar because their content rhymes may be *different patterns*. Only the structure decides.

## The same-structure test

Reduce each region to its **structural signature** and compare signatures, not appearances. Build the signature by normalising away everything that is content:

1. **Erase text, images, icons, and colours.** Keep that a slot *exists* and its **role** (heading, body text, eyebrow/label, button, link, image, icon, stat-number, input, quote); discard what fills it.
2. **Collapse repeated siblings to one.** A row of three cards and a row of four cards have the same signature: `grid[ card* ]`. **Item count is a parameter, never a distinction.**
3. **Unwrap styling-only containers.** A `div` that only adds padding or a background is not structure; lift its children into its parent so decoration never splits one pattern into two.
4. **Keep the nesting.** What contains what *is* the structure: `band[ heading, text, buttons[ btn, btn ] ]`.

Two regions are **the same pattern** if their signatures are equal. They are **different patterns** if the signatures differ — *unless* the only difference is a slot that is present in one and absent in the other and is plausibly optional, in which case they are one pattern with an **optional slot** (see below). That exception is the only judgment the test leaves you; everything else is mechanical.

`scripts/mine_structures.py` computes these signatures for you and groups the mockups' bands by them — the deterministic first pass. It is a starting map to curate, not the answer: it reliably groups full bands and detects components pulled in as explicit design-system imports, but repeated *raw* sub-structures inside a single band (a card repeated in a grid) collapse into the band's signature rather than being named. You surface those by eye. Never take its grouping as final; run it, then apply the rest of this file.

## What the miner needs

The miner reads **HTML mockups**, and its component detection keys on corpus conventions: `<x-import component-from-global-scope="NS.Name">` imports, `data-component` attributes, and `M<n>` module-tag comments. A plain-HTML corpus without those still gets its bands grouped, but the candidate-component list comes back empty — components are then found entirely by eye. Mockups that are not HTML at all (Figma frames, images) cannot be mined: say so, skip the script, and do the cartography of this file wholly by eye. The same-structure test works on anything you can see; only the deterministic first pass is lost.

## Optional slots — one pattern, or two?

When two signatures differ only by a present/absent slot, decide by **role continuity**: if both are unmistakably the same organism doing the same job and the extra slot is a variation of emphasis (a disclaimer line under an intro, a CTA some heroes have and some don't), it is **one pattern with an optional slot** — build it once, leave the slot empty where unused. If the extra slot changes what the section *is* (a plain intro versus an intro that also contains a filter bar and a result list), they are **two patterns**. Ask: would a designer call these the same thing with a tweak, or two different things? Same thing → one pattern; different things → two.

## Component or section?

Every recurring structure is one of three things. Classify by what the structure *is*, not by size:

- **Atom** — a single core block used directly: a heading, a paragraph, a button, an image. Not a pattern. It carries no internal structure worth naming.
- **Component pattern (molecule)** — a small, reusable unit that lives **inside** sections: a card, a stat, a button pair, an icon-feature, a quote. It does **not** set full-width band chrome (no `align:full`, no section background, no band padding); it is placed *within* a band. It earns its own pattern because it **recurs**.
- **Section pattern (organism)** — a full-width page **band**: it spans the viewport (`align:full`), sets its own background and vertical rhythm (the standard section wrapper in `markup.md`), and occupies one slot in a page's vertical sequence. It is the unit of page composition.

The boundary is sharp and worth stating as a rule: **a section owns the band; a component never does.** If a structure sets the full-width background and padding of a page zone, it is a section. If it is placed inside such a zone and reused, it is a component. This is also what `lint_markup.py`'s `COMPONENT-BAND` check enforces.

## Guardrails

The classification fails in two opposite directions. Hold both lines.

**Against over-abstraction (fragmenting).** Do not promote structure to a component just because you *can*. A structure earns component status only when it **recurs**: it appears inside **≥2 distinct section types**, or as **≥3 instances** overall (including as the repeated item of a grid). A cluster of blocks that appears once is not a component — it is just blocks inside its section. A component must also be worth naming: **≥2 blocks in a stable relationship**. Never split a heading-and-button into two patterns. The test: if extracting it removes no duplication, do not extract it.

**Against under-abstraction (duplicating).** The opposite failure is worse, because it is the one this whole workflow exists to prevent. If a **band** signature appears in **≥2 places**, it **must** become one section pattern — never a hand-written copy. Two sections that differ only by content are one section pattern. A card that appears in three sections is one component pattern composed three times. Sub-band structure is governed by the component thresholds above, and the two rules do not conflict: a cluster recurring twice inside a *single* section type stays raw in that one section file, which is still a single source — composition, not duplication. The line you must never cross is hand-writing structure that already has a pattern source somewhere else.

## Harvest the author's own tags first

Mockups often already carry the author's module tags — a comment like `<!-- M3 · filter bar -->` or `<!-- 6 · INVESTMENT CASE -->` above a band, with the same tag reused across pages. These are the author telling you what *they* consider one reusable unit. Harvest them as **hypotheses**: a repeated tag is strong evidence of one pattern, and `mine_structures.py` surfaces them. But validate each against the signature test — tags are applied by hand and drift (the same tag may sit above two genuinely different structures, or two tags may sit above one). Structure is the arbiter; the tags just tell you where to look first. When a mockup carries no tags, derive the taxonomy purely from signatures.

## The pattern manifest

The output of this phase, and the input to every later one. Settle it with the user before building. It has four parts:

```
components:            # molecules, Inserter: no
  - slug: <theme>/card
    role: "image + heading + body + link; the repeated item of card grids"
    slots: [image, heading, body, link?]     # ? marks an optional slot
    seen_in: [feature-grid, quick-links]

sections:              # organisms, full-width bands
  - slug: <theme>/hero
    role: "statement opener: bg image, heading, sub, CTA pair"
    content: per-page                         # its copy differs on every page
    grounds: [main]                           # background tokens the mockups show it on
    composes: [<theme>/button-pair]           # components nested by slug
    one_offs: []                              # unique raw-block structure, if any
  - slug: <theme>/feature-grid
    role: "3–4 up grid of feature cards over an intro"
    content: per-page
    grounds: [base]
    composes: [<theme>/card]
  - slug: <theme>/subscribe-cta
    role: "newsletter signup band, identical wherever it appears"
    content: fixed                            # the pattern file carries the real copy
    grounds: [tertiary]
    composes: [<theme>/button-pair]

pages:                 # section patterns in sequence
  - title: "Home"
    sections: [<theme>/hero, <theme>/feature-grid, <theme>/cta-band]
  - title: "Board"
    sections: [<theme>/breadcrumbs, <theme>/intro, <theme>/person-grid, <theme>/crosslinks]

coverage:              # every mockup band accounted for
  - "Home#0 → hero; Home#1 → instrument-panel; …; Board#3 → crosslinks"

one_off_styles:        # sanctioned literals no token covers (each carries a lint:allow pragma)
  - "hero: border-radius 100px bottom-right on the media frame"
```

Three fields deserve their own words:

- **`content:`** classifies where a section's final copy lives. **`fixed`** means the same content everywhere it appears: the pattern file carries the real copy, and a later structure fix may overwrite built instances blindly (`instantiate_patterns.py reapply --fixed`). **`per-page`** means the file carries placeholders; content is set on each page's instance at Phase 5, and built instances are never overwritten automatically. When in doubt, `per-page` — it is the safe default, because it never destroys content.
- **`grounds:`** records the background tokens the mockups show the section on. The signature test erases colour, so two bands that differ only by ground are **one** section — the ground is set per instance at build time, always as a background/text token pair that passed AA in Phase 2. Without this field the manifest could not even say that a hero appears on both dark and light ground.
- **`one_off_styles`** lists the sanctioned literals — values the design system genuinely has no token for. Each corresponds to exactly one `lint:allow` pragma in the markup (`markup.md`), so every exception is deliberate, reviewable, and counted.

The **coverage** section is the completion check: every band of every mockup maps to exactly one section pattern (or is named as a sanctioned one-off). A band with no home means the map is incomplete — resolve it before locking.

## Worked example (from the sample IR mockups)

Running `mine_structures.py` over the sample mockups produced 49 bands across 22 files, grouping to 27 distinct signatures. Curating that first pass:

- A **breadcrumbs bar** signature recurred 10× across every subpage → one section pattern (chrome), referenced, never copied.
- An **intro/ingress** signature recurred 5×, and a near-identical one 4× differing only by a trailing disclaimer line — the author tagged both `M11`. Role continuity says *same thing with a tweak* → **one** `intro` section pattern with an **optional disclaimer slot**, not two.
- A **crosslinks** band recurred 3×, a **quick-links card grid** 3×, a **subscribe CTA** 2× (tagged `M9`/`M12`) → three more section patterns.
- The design-system components the bands imported — a filter bar, a segmented control, pagination, tags, an empty state — are the **molecules**; the ones used across ≥2 section structures (e.g. the empty state) are clearly component patterns, the rest confirmed by checking whether they recur.
- The remaining once-seen bands (hero, instrument panel, investment-case bento) are **page-unique sections** — real sections, built once, instantiated by the one page that uses them; their signature seen once is the signal to confirm they are genuinely one-offs, not a missed duplicate.
- Classifying content: the subscribe CTA is `content: fixed` — the same invitation wherever it appears, so its file carries the real copy. The breadcrumbs bar, the intro, and every content band are `content: per-page`: one pattern each, but a breadcrumb trail or an intro differs on every page even though the structure never does.

That curated result — components, sections, per-section composition, per-page sequence, full coverage — is the manifest the build then follows.
