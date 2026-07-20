# Foundation — the design system in theme.json

The foundation is the whole point: every block, component, and section above it gets its appearance from these tokens and adds almost nothing of its own. Build it once, verify it resolves, and never revisit it after a pattern starts referencing it.

## The child theme

Create (or locate) an Ollie child theme; it is the home for the foundation and everything above it (`SKILL.md` says why). Minimum:

- `style.css` with a theme header whose `Template: ollie` line makes it Ollie's child.
- `theme.json` — the token overrides. A child's `theme.json` **deep-merges over the parent's**, so you declare only what the design system changes; everything you omit inherits from Ollie.
- `functions.php` — only if you register pattern categories (Phase 3/4) or enqueue web fonts.

Activate it, then confirm with `dump_ground_truth.py`: `active_theme.parent_is_ollie` must be true.

## Names are closed; only values are yours

WordPress generates the `--wp--…` custom properties from `theme.json` deterministically, and the set is **closed** — you cannot invent a `--wp--preset--color--brand`. Presets become `--wp--preset--<category>--<slug>`; `settings.custom` entries become `--wp--custom--<key>--<slug>`, splitting camelCase to kebab-case (`custom.lineHeight.tight` → `--wp--custom--line-height--tight`).

So the mapping is: **take the slug names from ground truth, give them the design system's values.** A well-made design system already names its tokens after these variables (the sample one does); your job is to write those values into `theme.json` under the matching preset. Ollie's 11-slot palette, its font-size / spacing / radius scales, and its font-weight / line-height customs are the slots you fill — read them from `dump_ground_truth.py`, not from memory.

If the design system needs a value WordPress will not emit a preset for — an extra hue, a marker-highlight colour — give it a **private** name: `settings.custom` (→ `--wp--custom--…`) if you want it in the generated stylesheet, or a plain `--ds-…` in your own CSS. **Never** name it `--wp--preset--…`; WordPress will not emit it and every reference resolves to nothing. (This is the single most common corruption of a generated system — see `ollie-errata.md`.)

## The fluid-type trap

Ollie sets `settings.typography.fluid: true`, so **every font size becomes a `clamp()`** that WordPress computes from the size's `min`/`max` and the layout width. Do not write the `clamp()` yourself. Declare each size as:

```json
{ "slug": "large", "size": "2.75rem", "fluid": { "min": "1.85rem", "max": "2.75rem" } }
```

and let WordPress generate the curve. A hand-written `clamp(min, Nvw, max)` approximation matches at the viewport endpoints and is wrong by up to ~20% across the middle — where most reading happens. The exact algorithm, if you ever need to predict the output, is in `ollie-errata.md`; the rule here is simpler: **set min/max, never the clamp**, then verify the resolved string with `dump_ground_truth.py`.

## The font-width trap

If the design system uses one variable font at several widths (Ollie ships Mona Sans as `primary`/`expanded`/`condensed`/`narrow`, all one file pinned to different `font-stretch`), each width must be a **distinct `@font-face` family name** registered in `settings.typography.fontFamilies` (with `fontFace` entries), because a slug like `narrow` resolves to the literal string `Mona Sans Narrow, sans-serif` — a family name that must exist. Aliasing all widths to one stack renders headings and buttons at normal width, visibly wrong. Register the family names as the parent does, or the widths silently collapse.

## Identity: theme.json or a style variation

For a single-identity site, put the design system directly in the child's `theme.json` — it is the site's one look. Use a **style variation** (`styles/*.json`) only if the site genuinely switches identities. Either way the source of truth is a **file**, not the Site Editor: user global styles are stored in the database and **override theme.json**, so a value changed in the Site Editor can mask what your file says. Keep identity in the file; if the dump disagrees with your file, suspect a DB override and clear it (`wp option delete` the user global-styles post, or reset customisations) rather than editing the file to match.

## Verify and lock

The foundation is locked only when the install proves it:

1. Re-run `dump_ground_truth.py --json ground-truth.json`. Every token the design system defines resolves, with the intended value and — for fluid sizes — the intended `clamp()` string.
2. Run `check_contrast.py --ground-truth ground-truth.json <bg:text pairs>` for every background/text pairing the design system promises. All clear AA (4.5:1 normal, 3:1 large/UI). A pairing scoped to large text only (a bright accent behind big numerals) is checked with `--large`.

When both hold, the foundation is ground truth for every layer above. `ground-truth.json` is now the reference `lint_markup.py` checks against.
