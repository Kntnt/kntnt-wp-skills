#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Mine mockups for repeated structure — the deterministic first pass of pattern cartography.

Reads a set of mockup HTML files and groups their page *bands* (full-width
sections) by a normalised **structural signature** that ignores content: text,
images, colours, and the *count* of repeated siblings are all erased, so a
three-card grid and a four-card grid reduce to the same signature. Bands that
share a signature across the corpus are candidate **section patterns**;
sub-structures reused across bands — including any design-system components the
mockup pulls in — are candidate **component patterns**.

This never decides the taxonomy. It hands the agent a defensible starting map to
curate against `references/cartography.md`, so "read every mockup and find the
repetition" stops being fuzzy recall and becomes a checkable diff.

Usage:
    uv run mine_structures.py <file-or-dir> [<file-or-dir> ...] [--json out.json]

Emits a human-readable report to stdout; with --json also writes the full
machine-readable manifest-candidate to the given path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

# Tags that carry no structural meaning for cartography — unwrapped, their
# children are lifted into the parent so styling-only wrappers never split a
# pattern in two.
TRANSPARENT = {"span", "b", "i", "em", "strong", "small", "u", "br", "wbr", "cite"}

# Void/among-leaf tags we keep as typed leaf roles.
VOID = {"img", "input", "hr", "source", "path", "polyline", "circle", "use"}

# Map a raw tag to its structural role. Headings collapse to one role; anchors,
# buttons, media and icons become typed leaf slots. Everything else keeps its tag.
ROLE = {
    "h1": "h", "h2": "h", "h3": "h", "h4": "h", "h5": "h", "h6": "h",
    "p": "text", "a": "link", "button": "btn", "img": "img", "svg": "icon",
    "blockquote": "quote", "input": "field", "form": "form", "ul": "list",
    "ol": "list", "li": "item", "table": "table", "figure": "figure",
}

COMMENT_TAG_RE = re.compile(r"\bM\s?\d+\b", re.I)


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    comment_before: str | None = None


class DOM(HTMLParser):
    """A forgiving DOM builder that also records the last comment seen before
    each element open, so author module tags (`<!-- 3 · FILTER BAR -->`,
    `<!-- M3 ... -->`) attach to the band they annotate."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.stack = [self.root]
        self._pending_comment: str | None = None

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, comment_before=self._pending_comment)
        self._pending_comment = None
        self.stack[-1].children.append(node)
        if tag not in VOID and tag != "x-import":
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, comment_before=self._pending_comment)
        self._pending_comment = None
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_comment(self, data):
        self._pending_comment = data.strip()


def component_name(node: Node) -> str | None:
    """The design-system component a node pulls in, if any — from an <x-import
    component-from-global-scope="NS.Name"> (the mockups' convention) or from a
    data-component / is="..." hint."""
    if node.tag == "x-import":
        ref = node.attrs.get("component-from-global-scope", "")
        if "." in ref:
            return ref.rsplit(".", 1)[1]
        return ref or None
    return node.attrs.get("data-component") or None


def signature(node: Node, depth: int = 0, max_depth: int = 6) -> str:
    """Content-blind structural signature. Repeated adjacent siblings collapse to
    one `role*`, so item count never changes the signature. Depth is capped so a
    deep leaf's internals don't over-specify the pattern."""
    comp = component_name(node)
    if comp:
        return f"C:{comp}"
    role = ROLE.get(node.tag, node.tag)
    if node.tag in VOID or depth >= max_depth:
        return role
    child_sigs = [signature(c, depth + 1, max_depth) for c in node.children if _keep(c)]
    child_sigs = _collapse_repeats(child_sigs)
    if not child_sigs:
        return role
    return f"{role}[{','.join(child_sigs)}]"


def _keep(node: Node) -> bool:
    if node.tag in TRANSPARENT:
        return False
    if node.tag in ("script", "style", "link", "meta", "helmet", "polyline", "path"):
        return False
    return True


def _collapse_repeats(sigs: list[str]) -> list[str]:
    out: list[str] = []
    for s in sigs:
        base = s[:-1] if s.endswith("*") else s
        if out and (out[-1] == s or out[-1] == base + "*"):
            out[-1] = base + "*"
        else:
            out.append(s)
    return out


def flatten_transparent(node: Node) -> Node:
    new_children: list[Node] = []
    for c in node.children:
        c = flatten_transparent(c)
        if c.tag in TRANSPARENT:
            new_children.extend(c.children)
        else:
            new_children.append(c)
    node.children = new_children
    return node


def find_main(root: Node) -> Node:
    stack = [root]
    while stack:
        n = stack.pop()
        if n.tag == "main":
            return n
        stack.extend(n.children)
    body = _first(root, "body")
    return body or root


def _first(node: Node, tag: str) -> Node | None:
    stack = [node]
    while stack:
        n = stack.pop(0)
        if n.tag == tag:
            return n
        stack.extend(n.children)
    return None


def collect_components(node: Node, acc: set[str]) -> None:
    c = component_name(node)
    if c:
        acc.add(c)
    for ch in node.children:
        collect_components(ch, acc)


def band_label(node: Node) -> str | None:
    c = (node.comment_before or "").strip()
    if not c:
        return None
    c = re.sub(r"\s+", " ", c)
    return c[:80]


def sig_hash(sig: str) -> str:
    return hashlib.sha1(sig.encode()).hexdigest()[:8]


def process_file(path: Path) -> dict:
    dom = DOM()
    dom.feed(path.read_text(encoding="utf-8", errors="replace"))
    flatten_transparent(dom.root)
    main = find_main(dom.root)

    # Bands = the top-level <x-import> chrome that sits around <main> (site
    # header/footer show up as shared structure this way), plus the direct
    # children of <main> that are sectioning/container elements.
    bands: list[dict] = []
    candidates: list[Node] = []
    for c in _walk_top_chrome(dom.root):
        candidates.append(c)
    for c in main.children:
        if c.tag in ("section", "div", "article", "header", "footer", "aside") or component_name(c):
            candidates.append(c)

    for idx, node in enumerate(candidates):
        comps: set[str] = set()
        collect_components(node, comps)
        sig = signature(node)
        bands.append({
            "index": idx,
            "tag": node.tag,
            "label": band_label(node) or (component_name(node) and f"[component:{component_name(node)}]") or None,
            "module_tag": _module_tag(band_label(node)),
            "signature": sig,
            "sig_hash": sig_hash(sig),
            "components": sorted(comps),
        })
    return {"file": path.name, "bands": bands}


def _walk_top_chrome(root: Node) -> list[Node]:
    body = _first(root, "body") or root
    out = []
    for c in body.children:
        if component_name(c):
            out.append(c)
    return out


def _module_tag(label: str | None) -> str | None:
    if not label:
        return None
    m = COMMENT_TAG_RE.search(label)
    return m.group(0).replace(" ", "").upper() if m else None


def gather(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.glob("*.html")))
        elif p.suffix in (".html", ".htm"):
            files.append(p)
    # The mockup corpus often ships tiny "- Mockup" thumbnails beside the real
    # page; keep both — duplicates only strengthen a signature's evidence.
    return files


def build_report(files: list[Path]) -> dict:
    per_file = [process_file(f) for f in files]

    # Group bands by exact signature → candidate section patterns.
    by_sig: dict[str, dict] = {}
    comp_usage: dict[str, set[str]] = {}
    for pf in per_file:
        for b in pf["bands"]:
            entry = by_sig.setdefault(b["sig_hash"], {
                "sig_hash": b["sig_hash"],
                "signature": b["signature"],
                "occurrences": [],
                "module_tags": set(),
                "components": set(),
            })
            entry["occurrences"].append({"file": pf["file"], "index": b["index"], "label": b["label"]})
            if b["module_tag"]:
                entry["module_tags"].add(b["module_tag"])
            for c in b["components"]:
                entry["components"].add(c)
                comp_usage.setdefault(c, set()).add(b["sig_hash"])

    sections = []
    for e in by_sig.values():
        sections.append({
            "sig_hash": e["sig_hash"],
            "count": len(e["occurrences"]),
            "reused": len(e["occurrences"]) > 1,
            "module_tags": sorted(e["module_tags"]),
            "components": sorted(e["components"]),
            "occurrences": e["occurrences"],
            "signature": e["signature"],
        })
    sections.sort(key=lambda s: (-s["count"], s["sig_hash"]))

    components = []
    for name, sigs in sorted(comp_usage.items()):
        components.append({
            "name": name,
            "used_in_section_signatures": sorted(sigs),
            "section_count": len(sigs),
            "reused": len(sigs) > 1,
        })
    components.sort(key=lambda c: (-c["section_count"], c["name"]))

    return {
        "files": [pf["file"] for pf in per_file],
        "band_total": sum(len(pf["bands"]) for pf in per_file),
        "distinct_band_signatures": len(by_sig),
        "candidate_section_patterns": sections,
        "candidate_component_patterns": components,
        "per_file": per_file,
    }


def print_report(rep: dict) -> None:
    print(f"Scanned {len(rep['files'])} file(s): {', '.join(rep['files'])}")
    print(f"{rep['band_total']} bands → {rep['distinct_band_signatures']} distinct structural signatures\n")

    print("== CANDIDATE SECTION PATTERNS (bands grouped by structure) ==")
    print("   A signature seen ≥2× is reused structure → one section pattern, referenced everywhere.")
    print("   A signature seen once is a page-unique band → confirm it is genuinely one-off.\n")
    for s in rep["candidate_section_patterns"]:
        tag = f"  tags={','.join(s['module_tags'])}" if s["module_tags"] else ""
        comps = f"  uses={','.join(s['components'])}" if s["components"] else ""
        flag = "REUSED" if s["reused"] else "once"
        where = "; ".join(f"{o['file'].split('.')[0]}#{o['index']}" for o in s["occurrences"][:6])
        print(f"  [{s['sig_hash']}] ×{s['count']} ({flag}){tag}{comps}")
        labels = [o["label"] for o in s["occurrences"] if o["label"]]
        if labels:
            print(f"      label: {labels[0]}")
        print(f"      in: {where}")
    print()

    print("== CANDIDATE COMPONENT PATTERNS (sub-structures reused across sections) ==")
    print("   Used across ≥2 distinct section structures → a molecule worth registering (Inserter: no).")
    print("   Used in only one → fold it into that section unless it clearly recurs.\n")
    for c in rep["candidate_component_patterns"]:
        flag = "REUSED" if c["reused"] else "one section"
        print(f"  {c['name']:22} in {c['section_count']} section-structure(s)  ({flag})")
    print()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    files = gather(args.paths)
    if not files:
        print("No HTML files found.", file=sys.stderr)
        return 2
    rep = build_report(files)
    print_report(rep)
    if args.json:
        args.json.write_text(json.dumps(rep, indent=2))
        print(f"Wrote machine-readable candidate manifest → {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
