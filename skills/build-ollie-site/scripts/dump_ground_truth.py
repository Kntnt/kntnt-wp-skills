#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Dump the ground truth of a live WordPress install — the tokens WordPress
*actually resolves* and the patterns it *actually has registered* — so the build
references reality, not the Ollie skill's prose.

The Ollie skill's token tables are generic and version-dependent; a specific
site runs a specific style variation on a specific Ollie/WordPress version, and
the two diverge (see `references/ollie-errata.md`). This helper closes that gap
in one shot by asking the install itself:

  * the resolved custom properties WordPress emits (the bytes the browser gets),
    from `wp_get_global_stylesheet()` — every `--wp--preset--*` and
    `--wp--custom--*` name and its exact value, grouped by category;
  * every registered block pattern (slug, title, categories, inserter, source),
    so you can see what already exists before you register anything and never
    collide with a core/remote pattern; and
  * the active theme and its parent, to confirm Ollie is the foundation.

Usage:
    uv run dump_ground_truth.py [--runner "ddev wp"] [--json out.json]

Runner defaults to `ddev wp` when a `.ddev/` directory is found nearby,
otherwise `wp`. Override for any environment (`--runner "wp --path=/var/www"`).
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

# WordPress' wp-cli bootstrap can emit a `Deprecated:`/`Notice:`/`Warning:` line
# on PHP 8.5 before the real payload; strip any such leading noise before parsing.
NOISE_PREFIX = re.compile(r"^(Deprecated|Notice|Warning|Strict Standards):.*$", re.M)

ROOT_BLOCK = re.compile(r":root\s*\{(.*?)\}", re.S)
DECL = re.compile(r"(--wp--[a-z0-9-]+)\s*:\s*([^;]+);")


def detect_runner(explicit: str | None) -> list[str]:
    if explicit:
        return shlex.split(explicit)
    # Walk up looking for a DDEV project; DDEV is this toolchain's local default.
    here = Path.cwd()
    for d in [here, *here.parents]:
        if (d / ".ddev").is_dir():
            return ["ddev", "wp"]
    return ["wp"]


def run(runner: list[str], wp_args: list[str]) -> str:
    proc = subprocess.run(runner + wp_args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"`{' '.join(runner + wp_args)}` failed (exit {proc.returncode}):\n{proc.stderr.strip()}"
        )
    return proc.stdout


def strip_noise(s: str) -> str:
    return NOISE_PREFIX.sub("", s).strip()


def category_of(name: str) -> str:
    # --wp--preset--color--primary → "color"; --wp--custom--font-weight--bold → "custom:font-weight"
    m = re.match(r"--wp--preset--([a-z0-9-]+?)--", name)
    if m:
        return m.group(1)
    m = re.match(r"--wp--custom--([a-z0-9-]+?)--", name)
    if m:
        return f"custom:{m.group(1)}"
    return "other"


def parse_root_css(css: str) -> dict[str, dict[str, str]]:
    """Parse a `:root { --wp--…: …; }` block into {category: {slug: value}}.

    Slug is the trailing segment after the category (e.g. `primary`,
    `x-large`), which is how you reference it: `var:preset|color|primary`."""
    out: dict[str, dict[str, str]] = {}
    block = ROOT_BLOCK.search(css)
    body = block.group(1) if block else css
    for name, value in DECL.findall(body):
        cat = category_of(name)
        # Slug = everything after the category prefix.
        prefix = re.match(r"(--wp--(?:preset|custom)--[a-z0-9-]+?--)", name)
        slug = name[len(prefix.group(1)):] if prefix else name
        out.setdefault(cat, {})[slug] = value.strip()
    return out


PATTERN_PHP = (
    "$r = WP_Block_Patterns_Registry::get_instance()->get_all_registered();"
    "$o = array_map(function($p){return ['slug'=>$p['name'],'title'=>$p['title']??null,"
    "'categories'=>$p['categories']??[],'inserter'=>$p['inserter']??true,"
    "'source'=>$p['source']??null];}, $r);"
    "echo json_encode(array_values($o));"
)


def dump_patterns(runner: list[str]) -> list[dict]:
    raw = strip_noise(run(runner, ["eval", PATTERN_PHP]))
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Some installs print the JSON after a stray notice the regex missed.
        m = re.search(r"\[.*\]", raw, re.S)
        return json.loads(m.group(0)) if m else []


def active_theme(runner: list[str]) -> dict:
    stylesheet = strip_noise(run(runner, ["option", "get", "stylesheet"]))
    template = strip_noise(run(runner, ["option", "get", "template"]))
    version = ""
    try:
        version = strip_noise(run(runner, ["theme", "get", stylesheet, "--field=version"]))
    except RuntimeError:
        pass
    return {"stylesheet": stylesheet, "template": template, "version": version,
            "is_child": stylesheet != template, "parent_is_ollie": template.lower() == "ollie"}


def build(runner: list[str]) -> dict:
    theme = active_theme(runner)
    css = strip_noise(run(runner, ["eval", "echo wp_get_global_stylesheet();"]))
    tokens = parse_root_css(css)
    patterns = dump_patterns(runner)
    theme_patterns = [p for p in patterns if p.get("source") in ("theme", "plugin")]
    return {
        "runner": " ".join(runner),
        "active_theme": theme,
        "token_categories": {k: len(v) for k, v in sorted(tokens.items())},
        "token_total": sum(len(v) for v in tokens.values()),
        "tokens": tokens,
        "pattern_total": len(patterns),
        "your_patterns": theme_patterns,
        "all_patterns": patterns,
    }


def print_summary(g: dict) -> None:
    t = g["active_theme"]
    ok = "✓" if t["parent_is_ollie"] else "✗"
    print(f"Active theme: {t['stylesheet']} (parent: {t['template']}, v{t['version']}) "
          f"— Ollie foundation {ok}")
    if not t["parent_is_ollie"]:
        print("  WARNING: parent theme is not Ollie. The token foundation this skill "
              "assumes is not in place.")
    print(f"\nResolved tokens: {g['token_total']} custom properties")
    for cat, n in g["token_categories"].items():
        print(f"  {cat:22} {n}")
    print(f"\nRegistered patterns: {g['pattern_total']} total, "
          f"{len(g['your_patterns'])} from a theme/plugin (yours)")
    for p in g["your_patterns"]:
        ins = "" if p.get("inserter", True) else "  [Inserter:no]"
        print(f"  {p['slug']}{ins}")
    print()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runner", default=None, help='WP-CLI runner, e.g. "ddev wp" or "wp"')
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--parse-css", type=Path, default=None,
                    help="Offline: parse a CSS file's :root block instead of calling WP (for testing).")
    args = ap.parse_args(argv)

    if args.parse_css:
        tokens = parse_root_css(args.parse_css.read_text())
        out = {"tokens": tokens, "token_total": sum(len(v) for v in tokens.values()),
               "token_categories": {k: len(v) for k, v in sorted(tokens.items())}}
        print(json.dumps(out["token_categories"], indent=2))
        if args.json:
            args.json.write_text(json.dumps(out, indent=2))
        return 0

    runner = detect_runner(args.runner)
    try:
        g = build(runner)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        print(f"(runner was `{' '.join(runner)}` — override with --runner)", file=sys.stderr)
        return 1
    print_summary(g)
    if args.json:
        args.json.write_text(json.dumps(g, indent=2))
        print(f"Wrote ground truth → {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
