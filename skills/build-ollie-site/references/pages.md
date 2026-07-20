# Pages & templates

The top of the stack, and the thinnest layer — by design. A page is **mainly a sequence of section patterns**, the occasional loose component, and raw blocks only for a sanctioned one-off. If a page needs much more than that, the map below it is incomplete; go back down, do not improvise upward.

## A page is section references in order

For each page in the manifest, create the content as the page's section sequence, each section a reference:

```html
<!-- wp:pattern {"slug":"<theme>/hero"} /-->
<!-- wp:pattern {"slug":"<theme>/feature-grid"} /-->
<!-- wp:pattern {"slug":"<theme>/cta-band"} /-->
```

The same reference mechanic as sections (`sections.md`): the page stores references, so a change to a section cascades to every page that uses it. Two hands create the page:

- **WP-CLI** — `wp post create --post_type=page --post_title="Home" --post_status=publish --post_content='<!-- wp:pattern … -->…'`. File-driven and reproducible; prefer it.
- **Ollie Abilities / MCP** — `manage-posts` to create the page and set its content. A convenient hand for content, and fine here — but not its pattern tool, which serves the forbidden cloud library.

Set the page template to a full-width, title-less template where the design calls for it (Ollie ships one); a section-composed page usually owns its own opening, so a template that adds a page title on top fights the hero.

## Loose components and one-offs

A page may place a **loose component** directly (a single CTA panel between two sections) — reference it the same way, `<!-- wp:pattern {"slug":"<theme>/…"} /-->`. And a page may hold a **raw one-off** the manifest sanctioned. Both are the exception; the rule is section patterns in sequence. Every raw block on a page that is not a sanctioned one-off is duplication that should have been a reference — the last place the compose-don't-duplicate discipline is checked.

## Templates and parts

Site-wide chrome is **templates and template parts**, not page content:

- **Template parts** (`parts/*.html`) — the header and footer, built from the same tokens and, where they contain reusable structure, the same component references. Assemble them once here.
- **Templates** (`templates/*.html`) — the page/archive/single wrappers that place the content between header and footer. A child theme's templates override Ollie's; add only the ones the design changes.

Edit templates and parts as child-theme files, or through the Ollie `manage-templates` ability against the DB — the file is the reproducible source of truth, so prefer the file and treat a DB edit as a preview.

## Verify and finish

The build is done when the install shows it:

1. Every manifest page exists and renders — load each, confirm its sections appear in order and resolve (not empty).
2. The rendered structure matches the mockups, with the design system's tokens throughout — spot-check that a colour, a size, and a spacing on a live page trace back to a ground-truth token, not a literal.
3. No page carries duplicated section markup it should have referenced.

At that point the site is what the workflow promised: one child theme holding tokens, components, sections, and templates; pages composed from them; every value resolving to an Ollie token; and a change at any layer cascading upward through the references instead of being re-pasted.
