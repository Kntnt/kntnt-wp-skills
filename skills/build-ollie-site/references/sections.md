# Section patterns (organisms)

A section pattern is a full-width page band — a hero, a feature grid, a CTA band, an intro. It owns its band (the standard section wrapper in `markup.md`) and **composes** the component patterns it needs by slug reference. Build every section the manifest names, after its components are locked.

## File and headers

One file per section in `patterns/`:

```php
<?php
/**
 * Title: Hero
 * Slug: <theme>/hero
 * Categories: <theme>-sections
 * Inserter: yes
 */
?>
<!-- the band wrapper, containing component references and one-off blocks -->
```

Sections are `Inserter: yes` (the default) under a `<theme>-sections` category, so a page author can drop them onto a page. Add `Viewport Width` for a truer inserter preview, and `Block Types`/`Template Types`/`Post Types` only if a section is meant to seed a specific block or template.

## Compose by reference — the one mechanic that matters

Inside the section's constrained inner group, nest a component with the **pattern reference block**:

```html
<!-- wp:pattern {"slug":"<theme>/card"} /-->
```

This is core's `core/pattern` block, and its behaviour is the reason the whole workflow composes instead of copies:

- **It is a live reference by slug, not a copy.** At render, `render_block_core_pattern()` looks the slug up in `WP_Block_Patterns_Registry` and expands the referenced pattern's blocks with `do_blocks()`. Because the section file stores the *reference*, not the component's markup, **editing the component file changes every section that references it** — the cascade you built components for.
- **It nests recursively.** A section may reference a component that itself references another pattern; each resolves at render. Recursion is guarded by a static `seen_refs` set: a pattern that would include itself is halted (rendering stops for that ref), while the same component used twice in separate places renders both times. So a component may not reference itself or an ancestor, but may be reused freely.
- **Editor caveat.** The reference renders on the front end and in most editor contexts; in some it may not render inside the inserter's Block Preview thumbnail. On WordPress 7.0+, an unsynced pattern inserted from the inserter defaults to `contentOnly` editing. Neither changes the file-level truth: the reference resolves at render, and the cascade holds. Verify by loading the page, not only the inserter preview.

**A repeated component is repeated references.** A grid of four cards is four `wp:pattern` references (or a wrapping columns/grid block holding them), not four pasted copies and not one card with the markup duplicated. If you catch yourself pasting a component's blocks into a section, stop — replace it with a reference.

## One-offs stay raw

Structure that the manifest marked as a genuine one-off — unique to a single section, appearing nowhere else — stays as **raw core blocks inside the section file**. Do not manufacture a component for something used once; that is the over-abstraction the cartography guardrails warn against. Keep one-offs listed in the manifest's `one_offs` so the choice is deliberate and reviewable, not an accident of duplication.

## Chrome is template parts, not sections

A site header and footer are **template parts** (`parts/*.html`), assembled in Phase 5, not page sections — they live around the content, not in its vertical sequence. A band that recurs *within* the content across pages (a breadcrumbs bar, a subscribe CTA) is a genuine section pattern; build it here and reference it from each page. The line is the same as everywhere: if it is a band in the page's scroll sequence, it is a section; if it frames the page, it is a template part.

## Lock

The section layer is locked when every section in the manifest is registered, each is lint-clean, and **every `wp:pattern` reference resolves**. Prove the references with `lint_markup.py --ground-truth ground-truth.json --patterns-dir patterns/` — its `PATTERN-REF` check fails on any slug that is neither registered in ground truth nor present as a local pattern file, catching a dangling reference before a page renders it empty.
