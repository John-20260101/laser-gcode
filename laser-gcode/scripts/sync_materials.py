#!/usr/bin/env python3
"""Sync references/materials.json into assets/vectorizer.html.

The interactive page is a single offline HTML file, so it cannot fetch the
material database at run time (file:// blocks fetch). Instead the JSON is
embedded between two marker comments; run this script after editing
materials.json so the page never drifts from the CLI's data.

Usage:
    python3 scripts/sync_materials.py            # rewrite the page
    python3 scripts/sync_materials.py --check    # exit 1 when out of date
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MATERIALS = ROOT / "references" / "materials.json"
PAGE = ROOT / "assets" / "vectorizer.html"
BEGIN = "/* MATERIALS:BEGIN */"
END = "/* MATERIALS:END */"


def render_block(data) -> str:
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
    return BEGIN + "\nconst MATERIALS = " + payload + ";\n" + END


def main(argv) -> int:
    check = "--check" in argv
    if not PAGE.exists():
        print("[error] missing %s" % PAGE, file=sys.stderr)
        return 2
    data = json.loads(MATERIALS.read_text(encoding="utf-8"))
    html = PAGE.read_text(encoding="utf-8")
    start = html.find(BEGIN)
    end = html.find(END, start + 1)
    if start < 0 or end < 0:
        print("[error] markers not found in %s" % PAGE, file=sys.stderr)
        return 2
    block = render_block(data)
    updated = html[:start] + block + html[end + len(END):]
    if updated == html:
        print("materials.json and vectorizer.html are in sync")
        return 0
    if check:
        print("[error] vectorizer.html is out of date; run scripts/sync_materials.py", file=sys.stderr)
        return 1
    PAGE.write_text(updated, encoding="utf-8")
    print("synced %d material keys into %s" % (
        sum(1 for k in data if not k.startswith("_")), PAGE.name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
