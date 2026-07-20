#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Lint block markup against ground truth — the offline gate that keeps every
pattern on-system before it ever reaches WordPress.

Ollie's own linter runs server-side; this runs on the files, so a component or
section pattern is checked the moment it is written. It enforces the rules that
break silently: a token slug that does not exist resolves to nothing, a
hardcoded colour dodges the whole design system, and a `wp:pattern` reference to
a slug you never registered renders empty.

Checks (error unless noted):
  * TOKEN-EXISTS  — every `var:preset|cat|slug`, `var:custom|key|slug`,
    `var(--wp--…)`, and named-attribute slug (`"backgroundColor":"primary"`)
    resolves to a property present in ground truth. Catches invented names like
    `--wp--preset--color--sage`.
  * NO-HARDCODE   — no hex/rgb/hsl colour, and no raw px/rem font-size or
    spacing, in block attributes or style values. (rem inside a clamp() token
    value you copied verbatim is fine — those live in theme.json, not here.)
  * NO-RAW-HTML   — no `core/html` block and no inline `<style>`.
  * PATTERN-REF   — every `<!-- wp:pattern {"slug":"ns/name"} /-->` resolves to
    a registered pattern (ground truth) or a local pattern file (--patterns-dir).
  * COMPONENT-BAND (warn) — a file under a components/ path should not set
    `align:"full"`; that is section-band chrome, not a molecule.

Usage:
    uv run lint_markup.py <pattern.php|.html> [more…] \\
        [--ground-truth gt.json] [--patterns-dir path/to/patterns]

Exit status is non-zero if any error-level finding is reported.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RGB_HSL = re.compile(r"\b(?:rgba?|hsla?)\s*\(")
PRESET_REF = re.compile(r"var:preset\|([a-z0-9-]+)\|([a-zA-Z0-9-]+)")
CUSTOM_REF = re.compile(r"var:custom\|([a-zA-Z0-9-]+)\|([a-zA-Z0-9-]+)")
CSSVAR_REF = re.compile(r"var\(\s*(--wp--[a-z0-9-]+)\s*\)")
PATTERN_REF = re.compile(r"wp:pattern\s+\{[^}]*?\"slug\"\s*:\s*\"([^\"]+)\"")
SLUG_HEADER = re.compile(r"^\s*\*?\s*Slug:\s*(\S+)", re.M)
# Named-slug attribute references — the everyday Ollie form, e.g.
# "backgroundColor":"primary", "fontSize":"medium". Each maps to a token category.
NAMED_ATTR = {
    "backgroundColor": "color", "textColor": "color", "borderColor": "color",
    "overlayColor": "color", "gradient": "gradient",
    "fontSize": "font-size", "fontFamily": "font-family",
}
NAMED_ATTR_RE = re.compile(
    r"\"(" + "|".join(NAMED_ATTR) + r")\"\s*:\s*\"([a-z0-9-]+)\""
)
# A raw size in a typography/spacing style value, e.g. "fontSize":"42px" or
# padding "3rem" written directly (not as a var:preset token).
RAW_SIZE = re.compile(r"\"(?:fontSize|top|bottom|left|right|blockGap|padding|margin)\"\s*:\s*\"(\d[\d.]*(?:px|rem|em))\"")


def camel_to_kebab(s: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", s).lower()


class Finding:
    def __init__(self, level: str, code: str, line: int, msg: str):
        self.level, self.code, self.line, self.msg = level, code, line, msg

    def __str__(self) -> str:
        return f"  {self.level.upper():5} {self.code:14} line {self.line}: {self.msg}"


def known_property_set(gt: dict | None) -> set[str] | None:
    if not gt:
        return None
    names: set[str] = set()
    for cat, slugs in gt.get("tokens", {}).items():
        if cat.startswith("custom:"):
            key = cat.split(":", 1)[1]
            for slug in slugs:
                names.add(f"--wp--custom--{key}--{slug}")
        else:
            for slug in slugs:
                names.add(f"--wp--preset--{cat}--{slug}")
    return names


def token_slug_map(gt: dict | None) -> dict[str, set[str]] | None:
    if not gt:
        return None
    return {cat: set(slugs) for cat, slugs in gt.get("tokens", {}).items()}


def known_slugs(gt: dict | None, patterns_dir: Path | None) -> set[str] | None:
    slugs: set[str] = set()
    have = False
    if gt:
        have = True
        for p in gt.get("all_patterns", []):
            if p.get("slug"):
                slugs.add(p["slug"])
    if patterns_dir and patterns_dir.is_dir():
        have = True
        for f in patterns_dir.rglob("*.php"):
            m = SLUG_HEADER.search(f.read_text(encoding="utf-8", errors="replace"))
            if m:
                slugs.add(m.group(1))
    return slugs if have else None


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def lint(path: Path, props: set[str] | None, slugs: set[str] | None,
         cat_slugs: dict[str, set[str]] | None = None) -> list[Finding]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[Finding] = []

    # Only look at the block-markup region (after the PHP header, if any).
    body_start = 0
    hdr = re.search(r"\?>\s*\n", text)
    if hdr:
        body_start = hdr.end()
    body = text[body_start:]

    def off(pos: int) -> int:
        return line_of(text, body_start + pos)

    # NO-RAW-HTML
    for m in re.finditer(r"<!--\s*wp:html\b", body):
        out.append(Finding("error", "NO-RAW-HTML", off(m.start()), "core/html block is not allowed; use core blocks."))
    for m in re.finditer(r"<style[\s>]", body):
        out.append(Finding("error", "NO-RAW-HTML", off(m.start()), "inline <style> is not allowed."))

    # NO-HARDCODE — colours
    for m in HEX.finditer(body):
        out.append(Finding("error", "NO-HARDCODE", off(m.start()), f"hardcoded colour {m.group(0)}; reference a token slug."))
    for m in RGB_HSL.finditer(body):
        out.append(Finding("error", "NO-HARDCODE", off(m.start()), f"hardcoded colour function {m.group(0)}…; reference a token slug."))
    # NO-HARDCODE — raw sizes written into style values
    for m in RAW_SIZE.finditer(body):
        out.append(Finding("error", "NO-HARDCODE", off(m.start()), f"raw size {m.group(1)}; use var:preset|font-size|… or var:preset|spacing|…."))

    # TOKEN-EXISTS
    if props is not None:
        for m in PRESET_REF.finditer(body):
            name = f"--wp--preset--{m.group(1)}--{m.group(2)}"
            if name not in props:
                out.append(Finding("error", "TOKEN-EXISTS", off(m.start()), f"unknown preset token {name} (ref var:preset|{m.group(1)}|{m.group(2)})."))
        for m in CUSTOM_REF.finditer(body):
            name = f"--wp--custom--{camel_to_kebab(m.group(1))}--{m.group(2)}"
            if name not in props:
                out.append(Finding("error", "TOKEN-EXISTS", off(m.start()), f"unknown custom token {name} (ref var:custom|{m.group(1)}|{m.group(2)})."))
        for m in CSSVAR_REF.finditer(body):
            if m.group(1) not in props:
                out.append(Finding("error", "TOKEN-EXISTS", off(m.start()), f"unknown CSS variable {m.group(1)}."))
    if cat_slugs is not None:
        for m in NAMED_ATTR_RE.finditer(body):
            attr, slug = m.group(1), m.group(2)
            if slug[0].isdigit():  # a raw size, not a slug — NO-HARDCODE owns it
                continue
            cat = NAMED_ATTR[attr]
            if slug not in cat_slugs.get(cat, set()):
                out.append(Finding("error", "TOKEN-EXISTS", off(m.start()), f"\"{attr}\":\"{slug}\" is not a registered {cat} slug."))

    # PATTERN-REF
    if slugs is not None:
        for m in PATTERN_REF.finditer(body):
            if m.group(1) not in slugs:
                out.append(Finding("error", "PATTERN-REF", off(m.start()), f"wp:pattern references unregistered slug \"{m.group(1)}\"."))

    # COMPONENT-BAND (warn) — a molecule should not claim the full-width band.
    if "components" in str(path).lower().replace("\\", "/").split("/"):
        for m in re.finditer(r"\"align\"\s*:\s*\"full\"", body):
            out.append(Finding("warn", "COMPONENT-BAND", off(m.start()), "component pattern sets align:full; band chrome belongs to section patterns."))

    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--ground-truth", type=Path, default=None)
    ap.add_argument("--patterns-dir", type=Path, default=None)
    args = ap.parse_args(argv)

    gt = json.loads(args.ground_truth.read_text()) if args.ground_truth and args.ground_truth.exists() else None
    props = known_property_set(gt)
    cat_slugs = token_slug_map(gt)
    slugs = known_slugs(gt, args.patterns_dir)

    if props is None:
        print("note: no --ground-truth given; skipping TOKEN-EXISTS. Run dump_ground_truth.py first for full coverage.\n")

    errors = 0
    for f in args.files:
        if not f.exists():
            print(f"{f}: not found", file=sys.stderr)
            errors += 1
            continue
        findings = lint(f, props, slugs, cat_slugs)
        if findings:
            print(f"{f}:")
            for fd in findings:
                print(fd)
                if fd.level == "error":
                    errors += 1
            print()
        else:
            print(f"{f}: clean")
    print(f"\n{errors} error(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
