# Ollie errata & live verification

Ollie's own descriptions are **informative, not authoritative.** They are written generically, they lag the theme, and they contradict each other across versions — the same token can be documented one way in one Ollie reference and the opposite way in another. So the rule is absolute: **the install is the authority.** When an Ollie claim and `dump_ground_truth.py` disagree, the dump wins, every time.

This file exists so the known divergences are reconciled once and not rediscovered each session. It records the *kinds* of drift, not fixed values — values are specific to a WordPress + Ollie version and style variation, which is exactly why you dump them rather than memorise them.

## The one command behind ground truth

The resolved token stylesheet is whatever WordPress serves as `<style id="global-styles-inline-css">`, which is exactly:

```sh
wp eval 'echo wp_get_global_stylesheet();'     # ddev wp eval '…' locally
```

`dump_ground_truth.py` runs this (plus the pattern registry and theme queries) and parses it. It is the bytes the browser receives — not a reconstruction. On PHP 8.5 the wp-cli bootstrap may print a leading `Deprecated:` line; the helper strips it.

## Known divergences — verify each against the dump

**Border-radius emits variables (an older Ollie doc says it does not).** One Ollie token reference states that border-radius produces no CSS custom property and is only ever applied as raw values. On current WordPress + Ollie that is **wrong**: `theme.json` declares `settings.border.radiusSizes` and WordPress emits all of them as `--wp--preset--border-radius--<slug>`. Note the `2xl` step is spelled **`2-xl`** in the variable. Both facts hold at once — the presets exist *and* some elements still hard-code a raw radius (see raw-value zones). Confirm the set in the dump; use the presets where a preset value is what you want.

**Every font size is fluid.** With `settings.typography.fluid: true`, every size — named preset or raw — is emitted as a `clamp()`. WordPress computes it as `clamp(MIN, MIN + ((1vw - 0.2rem) * FACTOR), MAX)` where `FACTOR = round((MAX_rem - MIN_rem) / 0.5875, 3)` (the `0.5875` and `0.2rem` come from a 320px–`wideSize` fluid range). A raw size with no declared min gets one derived via `factor = clamp(1 - 0.075*log2(px), 0.25, 0.75)` with a 14px floor. **Do not approximate a clamp with a `vw` middle term** — it matches at the endpoints and drifts up to ~20% mid-range. Set min/max in `theme.json` and copy the resolved string from the dump when you need the literal.

**Not everything is a token — raw-value zones exist.** Ollie's applied element styles reach for raw values where no token fits: a body `font-weight` between two weight tokens (e.g. `430`), a button `border-radius` that is not one of the radius presets (e.g. `10px`), a button `font-size` written raw (then made fluid). So "everything is a token" is true for *what you author* but not for *how Ollie styles its own elements*. When you deliberately match Ollie's element look, expect raw values in exactly these places; everywhere else, author tokens only.

**Font families are width-pinned names.** Where Ollie exposes one variable font at several widths, each width is a distinct `@font-face` family name (`Mona Sans`, `Mona Sans Expanded`, `Mona Sans Condensed`, `Mona Sans Narrow`), each pinned to a `font-stretch`. A family slug resolves to that literal string; the family must exist or the width silently collapses to normal. Monospace may be the bare CSS keyword `monospace` with no webfont behind it. Confirm the family strings in the dump before relying on a width.

**Stock WordPress defaults ride along.** The emitted set includes WordPress core defaults — a dozen stock colours, a set of gradients, several shadows, the aspect-ratio presets — that every theme has and that carry no design intent. `dump_ground_truth.py` shows them all; the design system's own slots are the ones to build with. Prefer them; ignore the core defaults unless a design token genuinely maps to one.

**Values are version-pinned.** A token facit is captured from a specific WordPress + Ollie version with a specific variation active; another install differs in values and sometimes in which presets exist. This is the root reason ground truth is dumped, never remembered. Re-dump whenever the theme or WordPress is updated.

## The closed-namespace rule

Because the `--wp--…` namespace is generated and closed, a name WordPress does not emit is not a token. If the design system needs a value outside the emitted set, name it privately (`settings.custom` → `--wp--custom--…`, or a plain `--ds-…`), never `--wp--preset--…`. A block or pattern that references an invented `--wp--preset--…` name resolves to nothing and fails silently — `lint_markup.py`'s `TOKEN-EXISTS` check catches this before it ships.
