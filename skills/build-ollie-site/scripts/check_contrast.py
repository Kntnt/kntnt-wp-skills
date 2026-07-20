#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Check colour-pair contrast against WCAG 2.1 AA — the deterministic half of the
foundation gate.

The design system pairs each background with a text colour; those pairings are
promises the tokens must keep. Eyeballing whether `#C49A58` on `#101018` clears
AA is exactly the check a machine should own. Feed it ground truth (the resolved
palette) and the pairings you intend to use; it computes the contrast ratio and
flags anything below 4.5:1 (normal text) or 3:1 (large text / UI).

Usage:
    # Check explicit pairs (bg:text slug pairs) against ground truth's palette:
    uv run check_contrast.py --ground-truth gt.json primary:base tertiary:main main:base

    # Or check raw hex directly, no ground truth needed:
    uv run check_contrast.py "#181838:#ffffff" "#C49A58:#101018"

Exit status is non-zero if any pair fails the active AA threshold (4.5:1 for
normal text, 3:1 with `--large`) or cannot be resolved.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def to_rgb(hex_str: str) -> tuple[float, float, float]:
    m = HEX.match(hex_str.strip())
    if not m:
        raise ValueError(f"not a hex colour: {hex_str}")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la = relative_luminance(to_rgb(hex_a))
    lb = relative_luminance(to_rgb(hex_b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def resolve(token_or_hex: str, palette: dict[str, str] | None) -> tuple[str, str]:
    """Return (label, hex) for a palette slug or a raw hex."""
    if HEX.match(token_or_hex):
        return token_or_hex, token_or_hex
    if palette and token_or_hex in palette:
        return token_or_hex, palette[token_or_hex]
    raise ValueError(f"'{token_or_hex}' is neither a hex colour nor a known palette slug "
                     f"(load ground truth with --ground-truth, or pass hex).")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pairs", nargs="+", help='bg:text pairs — slugs (primary:base) or hex (#181838:#ffffff)')
    ap.add_argument("--ground-truth", type=Path, default=None)
    ap.add_argument("--large", action="store_true", help="apply the 3:1 large-text threshold instead of 4.5:1")
    args = ap.parse_args(argv)

    palette: dict[str, str] | None = None
    if args.ground_truth and args.ground_truth.exists():
        gt = json.loads(args.ground_truth.read_text())
        palette = gt.get("tokens", {}).get("color", {})

    threshold = 3.0 if args.large else 4.5
    kind = "large/UI (3:1)" if args.large else "normal (4.5:1)"
    print(f"WCAG 2.1 AA — {kind}\n")

    failures = 0
    for pair in args.pairs:
        if ":" not in pair:
            print(f"  skip  {pair}: expected bg:text", file=sys.stderr)
            continue
        bg, text = pair.split(":", 1)
        try:
            bg_label, bg_hex = resolve(bg, palette)
            text_label, text_hex = resolve(text, palette)
        except ValueError as e:
            print(f"  ERROR {pair}: {e}", file=sys.stderr)
            failures += 1
            continue
        ratio = contrast_ratio(bg_hex, text_hex)
        ok = ratio >= threshold
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"  {mark}  {bg_label} ({bg_hex}) + {text_label} ({text_hex}) = {ratio:.2f}:1")

    print(f"\n{failures} pair(s) below AA.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
