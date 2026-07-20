# Section patterns (organisms)

A section pattern is a full-width page band — a hero, a feature grid, a CTA band, an intro. It owns its band (the standard section wrapper in `markup.md`) and **composes** the component patterns it needs. Build every section the manifest names, after its components are locked.

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
<!-- the band wrapper, containing composed components and one-off blocks -->
```

Sections are `Inserter: yes` (the default) under a `<theme>-sections` category, so a page author can drop them onto a page. Add `Viewport Width` for a truer inserter preview, and `Block Types`/`Template Types`/`Post Types` only if a section is meant to seed a specific block or template.

## The reference block — what it really does

Inside a section's constrained inner group, a component is composed with the **pattern reference block**:

```html
<!-- wp:pattern {"slug":"<theme>/card"} /-->
```

Two truths about this block, and both matter:

- **At front-end render** it is a live reference: `render_block_core_pattern()` looks the slug up in `WP_Block_Patterns_Registry` and expands the referenced pattern's blocks with `do_blocks()`. Recursion is guarded (a pattern may not include itself or an ancestor; the same component used twice in separate places renders both times). An unregistered slug renders as an empty string — silently.
- **In the editor** it does not survive: Gutenberg's pattern block *replaces itself with a clone of the pattern's contents* the moment the document loads (`PatternEdit` calls `replaceBlocks`), and the author's first save persists that expansion. A reference that reaches the editor is therefore just an instance you did not stamp — the "live cascade" it seems to promise dies on first edit.

The consequence is the composition rule of the whole workflow: **references are authoring notation inside pattern files; pages hold stamped instances** produced by `scripts/instantiate_patterns.py` (see `pages.md`). Within theme files the reference keeps one source per structure — editing the component file changes every section that composes it, because the files are the source the instantiation reads.

**A repeated component is repeated references.** A grid of four cards is four `wp:pattern` references (or a wrapping columns/grid block holding them), not four hand-pasted copies. If you catch yourself pasting a component's blocks into a per-page section file, stop — compose a reference instead.

## Fixed or per-page — what the file contains

The manifest classifies every section's content (`cartography.md`), and the classification decides what the section *file* holds:

- **`content: per-page`** — the file is a structure source: component references plus placeholder content in its own raw blocks. Real content never enters this file; it is set on each page's instance in Phase 5.
- **`content: fixed`** — the file carries the **real copy**, verbatim, because the band is identical wherever it appears and `reapply --fixed` must be able to overwrite built instances blindly from it. Where that copy lives inside a composed component (the real button label inside a button-pair), a bare reference cannot hold it — embed a **stamped instance** of the component instead, produced with `instantiate_patterns.py flatten`, and edit the copy into it. The stamp keeps the embed traceable: after a component edit, `instantiate_patterns.py audit --patterns-dir patterns/` lists which fixed sections embed instances that need re-flattening.

## One-offs stay raw

Structure that the manifest marked as a genuine one-off — unique to a single section, appearing nowhere else — stays as **raw core blocks inside the section file**. Do not manufacture a component for something used once; that is the over-abstraction the cartography guardrails warn against. Keep one-offs listed in the manifest's `one_offs` so the choice is deliberate and reviewable, not an accident of duplication.

## Chrome is template parts, not sections

A site header and footer are **template parts** (`parts/*.html`), assembled in Phase 5, not page sections — they live around the content, not in its vertical sequence. A band that recurs *within* the content across pages (a breadcrumbs bar, a subscribe CTA) is a genuine section pattern; build it here and instantiate it on each page. The line is the same as everywhere: if it is a band in the page's scroll sequence, it is a section; if it frames the page, it is a template part.

## Lock

The section layer is locked when every section in the manifest is registered, each is lint-clean, and **every `wp:pattern` reference resolves**. Prove the references with `lint_markup.py --ground-truth ground-truth.json --patterns-dir patterns/` — its `PATTERN-REF` check fails on any slug that is neither registered in ground truth nor present as a local pattern file, catching a dangling reference before it renders empty. Then prove each section actually renders with `instantiate_patterns.py check <slug>` — a live `do_blocks()` render of the registered pattern that must come back non-empty.
