#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Instantiate patterns onto pages — the deterministic half of page assembly.

Pages never hold `wp:pattern` references: the editor expands such a reference
into a copy the first time an author opens and saves the page, so a reference
in page content is a time bomb, not a cascade. Instead, this helper expands
patterns into **stamped instances** at build time: every `wp:pattern` reference
is resolved recursively against the pattern files, and each instantiated
pattern's root block is stamped with `metadata.patternSlug` so the instance
stays traceable to its source. References remain the composition notation
*inside* pattern files; pages (and `content: fixed` section files) hold
instances this helper produced.

Modes:
  * flatten  — expand one or more slugs (or pattern files) to stamped block
    markup on stdout. The agent fills in per-page content afterwards and
    creates the page with the result.
  * audit    — scan the install's pages (and/or a patterns directory) and list
    every top-level band with its provenance stamp, or UNSTAMPED. The Phase 5
    completion check: every band is a stamped instance or a sanctioned one-off.
  * reapply  — after a pattern-file edit, find that pattern's stamped
    instances on built pages. Bands whose slug is listed via --fixed are
    replaced wholesale from the file (their file carries the real copy, so a
    blind overwrite is safe); all other stamped bands are only reported for
    manual attention. Reports by default; only --write mutates the install.
  * check    — render each slug through `wp eval 'do_blocks(…)'` on the live
    install and fail on empty output. The scriptable "does it render" gate for
    Phase 3/4 locks, which works for `Inserter: no` patterns the editor's
    inserter cannot show.

Usage:
    uv run instantiate_patterns.py flatten <slug|file>... --patterns-dir patterns/
    uv run instantiate_patterns.py audit [--patterns-dir patterns/] [--runner "ddev wp"]
    uv run instantiate_patterns.py reapply <slug>... --patterns-dir patterns/ \\
        --fixed <slug>... [--write] [--runner "ddev wp"]
    uv run instantiate_patterns.py check <slug>... [--runner "ddev wp"]
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# One regex tokenizes all four block-comment delimiter forms: opener, closer,
# self-closing, each with optional attrs JSON. The lazy attrs match extends
# until the first `}` that is directly followed by the comment close, which is
# sufficient for serialized block attrs (they never contain `} -->` inside).
BLOCK_COMMENT = re.compile(
    r"<!--\s*(?P<close>/)?wp:(?P<name>[a-z][a-z0-9_-]*(?:/[a-z][a-z0-9_-]*)?)"
    r"(?:\s+(?P<attrs>\{.*?\}))?\s*(?P<self>/)?-->",
    re.S,
)

SLUG_HEADER = re.compile(r"^\s*\*?\s*Slug:\s*(\S+)", re.M)
PATTERN_REF = re.compile(
    r"<!--\s*wp:pattern\s+(\{.*?\"slug\"\s*:\s*\"(?P<slug>[^\"]+)\".*?\})\s*/-->", re.S
)

# WordPress' wp-cli bootstrap can emit deprecation noise before the payload on
# newer PHP; strip any such leading lines before parsing command output.
NOISE_PREFIX = re.compile(r"^(Deprecated|Notice|Warning|Strict Standards):.*$", re.M)


@dataclass
class Band:
    """One top-level block span in a document: its delimiters-inclusive text
    range, block name, and the pattern slug it was stamped with, if any."""

    start: int
    end: int
    name: str
    pattern_slug: str | None


def detect_runner(explicit: str | None) -> list[str]:
    """Resolve the WP-CLI runner: an explicit --runner wins; otherwise `ddev wp`
    when a DDEV project is found upward from the cwd, else plain `wp`."""
    if explicit:
        return shlex.split(explicit)

    # Walk up looking for a DDEV project; DDEV is this toolchain's local default.
    here = Path.cwd()
    for d in [here, *here.parents]:
        if (d / ".ddev").is_dir():
            return ["ddev", "wp"]

    return ["wp"]


def run(runner: list[str], wp_args: list[str], stdin: str | None = None) -> str:
    """Run one WP-CLI command and return stdout, raising on failure."""
    proc = subprocess.run(runner + wp_args, capture_output=True, text=True, input=stdin)
    if proc.returncode != 0:
        raise RuntimeError(
            f"`{' '.join(runner + wp_args)}` failed (exit {proc.returncode}):\n{proc.stderr.strip()}"
        )
    return proc.stdout


def strip_noise(s: str) -> str:
    return NOISE_PREFIX.sub("", s).strip()


def load_patterns(patterns_dir: Path) -> dict[str, str]:
    """Map each pattern file's Slug header to its block-markup body (the text
    after the PHP header), across the directory recursively."""
    out: dict[str, str] = {}
    for f in sorted(patterns_dir.rglob("*.php")):

        # A file without a Slug header is not a registrable pattern; skip it.
        text = f.read_text(encoding="utf-8", errors="replace")
        m = SLUG_HEADER.search(text)
        if not m:
            continue

        # The markup body starts after the closing `?>` of the header block.
        hdr = re.search(r"\?>\s*\n?", text)
        out[m.group(1)] = text[hdr.end():].strip() if hdr else text.strip()

    return out


def top_level_bands(markup: str) -> list[Band]:
    """Split a document into its top-level block spans by tracking delimiter
    depth. Text between top-level blocks is left unclaimed and untouched."""
    bands: list[Band] = []
    depth = 0
    open_start = 0
    open_name = ""
    open_attrs: str | None = None

    for m in BLOCK_COMMENT.finditer(markup):

        # A self-closing block at depth 0 is a complete band of its own.
        if m.group("self") and depth == 0:
            bands.append(Band(m.start(), m.end(), m.group("name"), _stamp_of(m.group("attrs"))))
            continue
        if m.group("self"):
            continue

        # Openers descend; the depth-0 opener anchors the next band.
        if not m.group("close"):
            if depth == 0:
                open_start, open_name, open_attrs = m.start(), m.group("name"), m.group("attrs")
            depth += 1
            continue

        # Closers ascend; returning to depth 0 completes the anchored band.
        depth -= 1
        if depth == 0:
            bands.append(Band(open_start, m.end(), open_name, _stamp_of(open_attrs)))

    return bands


def _stamp_of(attrs_json: str | None) -> str | None:
    if not attrs_json:
        return None
    try:
        return json.loads(attrs_json).get("metadata", {}).get("patternSlug")
    except json.JSONDecodeError:
        return None


def stamp(markup: str, slug: str) -> str:
    """Stamp the markup's first top-level block with metadata.patternSlug.
    The metadata attribute has no HTML face, so only the comment changes."""
    bands = top_level_bands(markup)
    if not bands:
        return markup
    if len(bands) > 1:
        print(f"warning: pattern {slug} has {len(bands)} root blocks; stamping the first.", file=sys.stderr)

    # Merge the stamp into the opener's attrs JSON, preserving existing keys.
    m = BLOCK_COMMENT.match(markup, bands[0].start)
    attrs = json.loads(m.group("attrs")) if m.group("attrs") else {}
    attrs.setdefault("metadata", {})["patternSlug"] = slug
    attrs_out = json.dumps(attrs, separators=(",", ":"), ensure_ascii=False)
    closer = " /" if m.group("self") else " "
    opener = f"<!-- wp:{m.group('name')} {attrs_out}{closer}-->"
    return markup[:bands[0].start] + opener + markup[m.end():]


def flatten(slug: str, patterns: dict[str, str], seen: tuple[str, ...] = ()) -> str:
    """Expand a pattern to stamped markup, recursively resolving every
    `wp:pattern` reference against the pattern files. Mirrors core's render-time
    recursion guard: a slug may not include itself or an ancestor."""
    if slug in seen:
        raise ValueError(f"pattern recursion: {' → '.join([*seen, slug])}")
    if slug not in patterns:
        raise KeyError(f"slug {slug!r} not found in the patterns directory.")

    # Resolve nested references depth-first, then stamp this expansion's root.
    def expand_ref(m: re.Match[str]) -> str:
        return flatten(m.group("slug"), patterns, (*seen, slug))

    body = PATTERN_REF.sub(expand_ref, patterns[slug])
    return stamp(body, slug)


def cmd_flatten(args: argparse.Namespace) -> int:
    patterns = load_patterns(args.patterns_dir)

    # Accept file paths as well as slugs, so a not-yet-registered file can be
    # instantiated directly during authoring.
    chunks: list[str] = []
    for target in args.targets:
        path = Path(target)
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            m = SLUG_HEADER.search(text)
            if not m:
                print(f"error: {path} has no Slug header.", file=sys.stderr)
                return 1
            target = m.group(1)
        chunks.append(flatten(target, patterns))

    print("\n\n".join(chunks))
    return 0


def list_pages(runner: list[str]) -> list[dict]:
    raw = strip_noise(run(runner, [
        "post", "list", "--post_type=page", "--post_status=publish,draft,pending,private",
        "--format=json", "--fields=ID,post_title",
    ]))
    return json.loads(raw or "[]")


def page_content(runner: list[str], page_id: int) -> str:
    return run(runner, ["post", "get", str(page_id), "--field=post_content"])


def audit_document(label: str, markup: str) -> None:
    """Print one document's top-level bands with their provenance stamps."""
    bands = top_level_bands(markup)
    print(f"{label}: {len(bands)} band(s)")
    for i, b in enumerate(bands):
        mark = b.pattern_slug or "UNSTAMPED"
        print(f"  #{i} {b.name:24} {mark}")


def cmd_audit(args: argparse.Namespace) -> int:

    # Pattern files first: fixed sections legitimately embed stamped component
    # instances, and this lists where they live for re-flattening after edits.
    if args.patterns_dir:
        patterns = load_patterns(args.patterns_dir)
        for slug, body in patterns.items():
            inner = sum(1 for m in BLOCK_COMMENT.finditer(body) if _stamp_of(m.group("attrs")))
            if inner:
                print(f"file {slug}: {inner} embedded stamped instance(s)")
        print()

    # Then the install's pages — the Phase 5 audit proper.
    runner = detect_runner(args.runner)
    for page in list_pages(runner):
        audit_document(f"page {page['ID']} ({page['post_title']})", page_content(runner, page["ID"]))

    return 0


def cmd_reapply(args: argparse.Namespace) -> int:
    patterns = load_patterns(args.patterns_dir)
    runner = detect_runner(args.runner)
    targets = set(args.targets)
    fixed = set(args.fixed or [])
    manual: list[str] = []
    replaced = 0

    for page in list_pages(runner):

        # Rebuild the page bottom-up: replace matching fixed bands from their
        # files, collect per-page bands for the manual-attention report.
        content = page_content(runner, page["ID"])
        out: list[str] = []
        cursor = 0
        changed = False
        for band in top_level_bands(content):
            if band.pattern_slug in targets & fixed:
                out.append(content[cursor:band.start])
                out.append(flatten(band.pattern_slug, patterns))
                cursor = band.end
                changed = True
                replaced += 1
            elif band.pattern_slug in targets:
                manual.append(f"page {page['ID']} ({page['post_title']}): {band.pattern_slug}")
        out.append(content[cursor:])

        # Only --write touches the install; the default run is a report.
        if changed and args.write:
            run(runner, ["post", "update", str(page["ID"]), "-"], stdin="".join(out))
            print(f"page {page['ID']} ({page['post_title']}): updated")
        elif changed:
            print(f"page {page['ID']} ({page['post_title']}): would update (use --write)")

    print(f"\n{replaced} fixed band(s) {'replaced' if args.write else 'replaceable'}.")
    if manual:
        print("Per-page instances needing manual structural attention:")
        for line in manual:
            print(f"  {line}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    runner = detect_runner(args.runner)
    failures = 0

    for slug in args.targets:

        # Render the reference exactly as the front end would; empty output
        # means the slug is unregistered or its markup collapses to nothing.
        php = f"echo do_blocks('<!-- wp:pattern {{\"slug\":\"{slug}\"}} /-->');"
        rendered = strip_noise(run(runner, ["eval", php]))
        if rendered:
            print(f"  PASS  {slug} renders ({len(rendered)} bytes)")
        else:
            print(f"  FAIL  {slug} renders empty")
            failures += 1

    print(f"\n{failures} pattern(s) render empty.")
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("flatten", help="expand slugs/files to stamped markup on stdout")
    p.add_argument("targets", nargs="+")
    p.add_argument("--patterns-dir", type=Path, required=True)
    p.set_defaults(fn=cmd_flatten)

    p = sub.add_parser("audit", help="list every band's provenance stamp")
    p.add_argument("--patterns-dir", type=Path, default=None)
    p.add_argument("--runner", default=None)
    p.set_defaults(fn=cmd_audit)

    p = sub.add_parser("reapply", help="update built pages after a pattern-file edit")
    p.add_argument("targets", nargs="+", help="edited pattern slugs to reapply")
    p.add_argument("--patterns-dir", type=Path, required=True)
    p.add_argument("--fixed", nargs="*", default=None, help="slugs safe to overwrite blindly (content: fixed)")
    p.add_argument("--write", action="store_true", help="apply changes; default is a report")
    p.add_argument("--runner", default=None)
    p.set_defaults(fn=cmd_reapply)

    p = sub.add_parser("check", help="verify each slug renders non-empty via do_blocks")
    p.add_argument("targets", nargs="+")
    p.add_argument("--runner", default=None)
    p.set_defaults(fn=cmd_check)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (RuntimeError, KeyError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
