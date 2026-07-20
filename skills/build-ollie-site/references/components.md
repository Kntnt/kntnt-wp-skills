# Component patterns (molecules)

A component pattern is a small reusable unit that lives inside sections — a card, a stat, a button pair, an icon-feature, a quote. It is built once and referenced everywhere it recurs, so editing it cascades. Build every component the manifest names before building any section, because a section cannot reference a component that is not yet registered.

## File and headers

One file per component in the child theme's `patterns/` directory. WordPress registers it automatically from the header; no PHP call needed.

```php
<?php
/**
 * Title: Card
 * Slug: <theme>/card
 * Categories: <theme>-components
 * Inserter: no
 */
?>
<!-- block markup -->
```

- **Slug** is `<theme>/<name>`, namespaced to the child theme (its text domain). This is the slug sections reference.
- **`Inserter: no`** is what makes it a component. It keeps the pattern **registered and referenceable by slug** while hiding it from the inserter, so components never clutter the author's insert menu — they are building blocks, not things a page author drops in directly. (`register_block_pattern()`'s `inserter: false` is the programmatic equivalent.)
- **Categories** groups it; register the category in `functions.php` with `register_block_pattern_category('<theme>-components', ['label' => '…'])` so the group has a label.

## Rules for the markup

- **No band chrome.** A component never sets `align:full`, never sets a section background, never writes the standard section wrapper. It is placed inside a section's constrained group and inherits the band. `lint_markup.py`'s `COMPONENT-BAND` check flags a component that claims the full band.
- **Core blocks only, every value a token.** The same on-system rules as everywhere (`markup.md`). Lint each file with `lint_markup.py --ground-truth ground-truth.json`.
- **Inherit colour where the component is placed on varying grounds.** A card reused on both a white band and a dark band should not hard-set a text colour that only works on one; let it inherit, or build the two grounds as an explicit variation only if the manifest calls for it.
- **Keep the optional slots the manifest identified.** If cartography found a component with an optional slot (a card with an optional link row), build the slot and leave it empty where a section does not fill it — do not fork it into two components.

## Placeholder content

Fill text and images with representative placeholder content, not lorem ipsum that hides structure and not the mockup's exact copy (which is content, not structure). The component's job is the *shape*; page authors replace the words later. Keep placeholders short enough that the structure reads at a glance.

## Lock

A component layer is locked when every component in the manifest is registered, each is lint-clean against ground truth, and each has been confirmed to render once (insert it on a scratch page, or preview it, and see the shape). Only then do sections start referencing them.
