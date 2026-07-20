# Block-markup mechanics

Shared by every layer that writes blocks — components, sections, pages. Three things must always be true; the rest is composition.

## Every value is a token

Colours, font sizes, spacing, radius, and shadows reference a design token, never a literal. Two reference forms:

- **Named attribute** (the common form): `"backgroundColor":"primary"`, `"textColor":"main"`, `"fontSize":"medium"`, `"fontFamily":"narrow"`, `"gradient":"black"`. The slug must exist in ground truth.
- **`var:` form** inside a `style` object: `"style":{"spacing":{"padding":{"top":"var:preset|spacing|large"}}}`, `"style":{"typography":{"fontWeight":"var:custom|fontWeight|bold"}}`. These become `var(--wp--preset--spacing--large)` / `var(--wp--custom--font-weight--bold)` at render.

No hex, `rgb()`, `hsl()`, or raw `px`/`rem`/`em` in block attributes. No `core/html` block. No inline `<style>`. `lint_markup.py` enforces all of this against ground truth; run it on every file.

**The sanctioned exception.** Occasionally the design genuinely needs a value no token covers — a 100px corner radius on one media frame, say. That is allowed, but only deliberately: list it in the manifest's `one_off_styles`, and mark the line with a pragma so the linter downgrades the finding to a visible note instead of failing:

```html
<!-- lint:allow NO-HARDCODE -->
<!-- wp:group {"style":{"border":{"radius":{"bottomRight":"100px"}}}} -->
```

One pragma per deliberate exception, on the same or the preceding line — never a blanket waiver. An exception that is not in `one_off_styles` is not sanctioned; a first instinct to reach for a literal should instead trigger the foundation amendment procedure (`foundation.md`) — most "missing" values deserve a token.

## The provenance stamp

An instantiated pattern carries its origin in the root block's `metadata` attribute — `instantiate_patterns.py` writes it, `audit` reads it:

```html
<!-- wp:group {"tagName":"section","align":"full","metadata":{"patternSlug":"<theme>/hero"}} -->
```

`metadata` has no HTML face — no class, no rendered output — so the stamp changes nothing visually and nothing in the comment↔HTML sync rule below. Leave stamps alone when editing content on an instance; they are how the Phase 5 audit tells an instance from hand-written duplication, and how `reapply` finds what to update.

## The comment and the HTML must agree

A block is a comment carrying the attributes plus the HTML they render to, and the two are one source with two faces:

```html
<!-- wp:group {"backgroundColor":"tertiary","textColor":"main"} -->
<div class="wp-block-group has-tertiary-background-color has-main-color has-background">…</div>
<!-- /wp:group -->
```

Whatever you set in the comment JSON must be reflected in the HTML — the colour classes (`has-<slug>-background-color`, `has-<slug>-color`, `has-background`), a `className` (`is-style-…`), an `align` (`alignfull`), spacing style attributes. Set it in only one place and the block is invalid or the editor shows the wrong state: the comment is what the editor reads for the sidebar; the HTML is what the front end renders. When in doubt, author the comment and let a `wp eval` round-trip (parse → re-serialize) normalise the HTML — WordPress's own parser fills in the canonical classes.

## The standard section wrapper

Every section pattern is a full-width band wrapping a constrained inner group. This is the one shape all sections share:

```html
<!-- wp:group {"tagName":"section","align":"full","backgroundColor":"base","style":{"spacing":{"padding":{"top":"var:preset|spacing|x-large","bottom":"var:preset|spacing|x-large","left":"var:preset|spacing|medium","right":"var:preset|spacing|medium"}}}} -->
<section class="wp-block-group alignfull has-base-background-color has-background" style="padding-top:var(--wp--preset--spacing--x-large);padding-bottom:var(--wp--preset--spacing--x-large);padding-left:var(--wp--preset--spacing--medium);padding-right:var(--wp--preset--spacing--medium)">

  <!-- wp:group {"layout":{"type":"constrained"}} -->
  <div class="wp-block-group">

    <!-- content, or wp:pattern references to components, go here -->

  </div>
  <!-- /wp:group -->

</section>
<!-- /wp:group -->
```

The outer group owns the band: `align:full`, a background token, vertical padding. The inner constrained group holds the content at the theme's content/wide width. A **component** never writes this wrapper — it is placed *inside* the inner group and inherits the band. Only sections set `align:full`.

## Backgrounds pair with text

Whenever you set a background colour, set a text colour that pairs with it and clears AA (verify pairings with `check_contrast.py`). A dark band (`main` background) takes `base` or the light accent for text; a tint band (`tertiary`) takes `main`. Never set a background without its paired foreground — unpaired, the text inherits whatever the parent had and can vanish against the new ground.
