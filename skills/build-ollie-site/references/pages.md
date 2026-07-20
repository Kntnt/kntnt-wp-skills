# Pages & templates

The top of the stack, and the thinnest layer — by design. A page is a sequence of **stamped section instances**: expanded copies produced by `scripts/instantiate_patterns.py`, each traceable to its source pattern through `metadata.patternSlug` on its root block. Pages never hold `wp:pattern` references — a reference renders the file's content identically everywhere (no per-page content), and the editor expands it into an unstamped copy on the author's first save anyway (`sections.md`). If a page needs much more than its manifest sequence, the map below it is incomplete; go back down, do not improvise upward.

## Instantiate, fill, create

For each page in the manifest:

1. **Instantiate the structure.** `uv run instantiate_patterns.py flatten <theme>/hero <theme>/feature-grid <theme>/cta-band --patterns-dir patterns/` emits the page's bands as stamped markup, in order, with every nested component reference resolved.
2. **Fill the content.** Replace the instance's placeholders with the page's content, by strict priority: **(1)** copy the user actually supplied for this page — use it verbatim, never invent or "improve" it; **(2)** otherwise the mockup's own text and images — they are the best available content until real copy exists; **(3)** only when even the mockup is silent may the pattern's placeholders stand, and then say so to the user instead of hiding it. Set each band's ground to what the mockup shows, from the manifest's `grounds` — always a background/text token pair that passed AA in Phase 2.
3. **Import media.** `ddev wp media import <file> --porcelain` returns the attachment id; wire the attachment's URL and id into the image blocks. Never hot-link mockup asset paths — they will not exist on the install.
4. **Create the page.** `ddev wp post create - --post_type=page --post_title="Home" --post_status=publish` with the filled markup on stdin (WP-CLI reads post content from stdin when the content argument is `-`). The Ollie Abilities `manage-posts` is a fine alternative hand for this — but never its pattern tool, which serves the forbidden cloud library.

Set the page template to a full-width, title-less template where the design calls for it (Ollie ships one); a section-composed page usually owns its own opening, so a template that adds a page title on top fights the hero.

A page may also place a **loose component** (a single CTA panel between two sections) — instantiate it the same way, via `flatten` — and may hold a **raw one-off** the manifest sanctioned. Both are the exception; the rule is section instances in sequence.

## Structure fixes after pages exist — reapply

When a pattern file changes after pages are built, the built instances do not update by themselves — the helper updates them:

```sh
uv run instantiate_patterns.py reapply <theme>/subscribe-cta --patterns-dir patterns/ \
    --fixed <theme>/subscribe-cta            # report first; add --write to apply
```

`content: fixed` bands are replaced wholesale from their file — safe, because the file carries their real copy. `content: per-page` instances are only **reported**: their content belongs to the page, so the structural fix is walked into each by hand (or the page is re-instantiated and re-filled). The default run is a report; only `--write` touches the install.

## Verify and finish

The build is done when the install shows it:

1. `instantiate_patterns.py audit` lists every top-level band of every page with its provenance stamp. Every band is a stamped instance or a manifest-sanctioned one-off; an `UNSTAMPED` band that is not a sanctioned one-off is duplication that should have been an instance.
2. Every manifest page renders — load each, confirm its sections appear in order with the page's content.
3. The rendered structure matches the mockups, with the design system's tokens throughout — spot-check that a colour, a size, and a spacing on a live page trace back to a ground-truth token, not a literal.

## Templates and parts

Site-wide chrome is **templates and template parts**, not page content:

- **Template parts** (`parts/*.html`) — the header and footer, built from the same tokens and, where they contain reusable structure, the same composition rules as sections. Assemble them once here.
- **Templates** (`templates/*.html`) — the page/archive/single wrappers that place the content between header and footer. A child theme's templates override Ollie's; add only the ones the design changes.

Edit templates and parts as child-theme files, or through the Ollie `manage-templates` ability against the DB — the file is the reproducible source of truth, so prefer the file and treat a DB edit as a preview. Note that editing a part in the Site Editor creates a DB copy that shadows the file, exactly like user global styles shadow `theme.json`.

## Out of scope — dynamic content

Navigation menus (`core/navigation`), query loops and archives, search, forms, and computed per-page chrome are functionality, not pattern structure; this workflow does not build them. The line for breadcrumbs: the breadcrumbs *band* is a section pattern, and each page's instance carries that page's static trail — a trail that must compute itself needs a plugin or block logic outside this skill. State the boundary to the user rather than half-building across it.
