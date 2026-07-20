# build-ollie-site

## NAME

`build-ollie-site` — build a site on the Ollie block theme, bottom-up by Atomic Design

## SYNOPSIS

```
/kntnt-wp-skills:build-ollie-site
/kntnt-wp-skills:build-ollie-site (help | --help | -h)
```

## DESCRIPTION

`build-ollie-site` builds a coherent, token-correct WordPress site on the **Ollie** block theme from a design system and a set of mockups. Unlike `clone`, `pull`, and `mkwp`, it is **not** part of the transfer engine and shares none of its machinery — no production, no Novamira, no health check, no recommendation-gate backbone. It works **bottom-up by Atomic Design**, and the whole atomic stack it produces — tokens, component patterns, section patterns, templates — lives in one Ollie child theme, because a plugin cannot ship a `theme.json`.

The build proceeds through gated phases, and a later layer is never built before the one below it is locked and verified: **ground truth** (dump the tokens the install actually resolves and the patterns it already has registered), **pattern cartography** (derive the pattern taxonomy from the mockups' *structure*, not their content), **foundation** (map the design system into the child theme's `theme.json` and verify it resolves), **component patterns** (molecules, registered `Inserter: no`), **section patterns** (organisms, composing components by `wp:pattern` slug reference inside the pattern files), and **pages** (stamped, expanded instances of the section patterns in sequence, each filled with that page's content — supplied copy first, else the mockup's, since a slug reference can neither carry per-page content nor survive the editor).

Its distinctive first phase is **pattern cartography**. The mockups' patterns are the operator's own and are not yet marked up, so the skill derives them: two regions are the same pattern when they share a structural signature, regardless of content. This is a judgment task, so it is human-in-the-loop — the skill proposes the taxonomy and composition as a **pattern manifest** and settles it with the operator before building anything.

**Ollie is used for its tokens and global styles only** — never its bundled or cloud pattern library; the site's patterns are the operator's own. Everything resolves to one design system's tokens, verified against what the install actually emits rather than against Ollie's prose, which is known to drift (see `references/ollie-errata.md` in the skill).

Because it is gate-driven and human-in-the-loop with no autonomous mode, `build-ollie-site` takes no operational flags — you point it at the design system and mockups and walk its phase gates. It requires an Ollie-parented WordPress install and WP-CLI (`ddev wp` locally); `uv` for its helper scripts (`dump_ground_truth.py`, `mine_structures.py`, `lint_markup.py`, `check_contrast.py`, `instantiate_patterns.py`); and, optionally, the Ollie Abilities / MCP as a convenience hand for content operations. It needs neither Novamira nor `mkwp`. Its full design, and the conflicts it resolves between the source skills it distils, are recorded in [`skills/build-ollie-site/DESIGN-RATIONALE.md`](../../skills/build-ollie-site/DESIGN-RATIONALE.md).

`build-ollie-site` is user-invoked only: it never runs on its own, because it writes a theme and content into a WordPress install ([ADR-0002](../../docs/adr/0002-skills-user-invoked-only.md)).

## OPTIONS

| Option | Description |
|---|---|
| `help`, `--help`, `-h` | Print this manual page and stop. |

## EXAMPLES

Build a site on Ollie, walking the phase gates and confirming the pattern manifest before the build proceeds:

```
/kntnt-wp-skills:build-ollie-site
```

Show this manual page:

```
/kntnt-wp-skills:build-ollie-site --help
```

## FILES

`build-ollie-site` writes the site's design system into an Ollie **child theme** under the WordPress install's `themes/` directory: the token foundation in its `theme.json` (or a style variation), the component and section patterns in its `patterns/` directory, and templates in `templates/`. Pages are created as content in the install — stamped, expanded instances of the registered section patterns, each traceable to its source pattern via `metadata.patternSlug` and filled with that page's content. It writes none of the transfer engine's files — no `.kntnt-wp-skills.json`, no `.kntnt-wp-skills/`.
