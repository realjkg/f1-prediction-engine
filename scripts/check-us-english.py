#!/usr/bin/env python3
"""Fail on a bounded list of UK-specific spellings in authored Markdown.

Only documentation is scanned. Source code, protocols, dependencies, official
names, and quoted third-party materials may require exact original spelling.
Add a scoped exception when the exceptional content is substantively necessary;
never perform blind source-wide substitutions.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDS = {
    "tyre": "tire", "tyres": "tires",
    "colour": "color", "colours": "colors", "coloured": "colored",
    "behaviour": "behavior", "behaviours": "behaviors",
    "optimise": "optimize", "optimised": "optimized",
    "optimisation": "optimization",
    "analyse": "analyze", "analysed": "analyzed",
    "organise": "organize", "organised": "organized",
    "organisation": "organization",
    "authorise": "authorize", "authorisation": "authorization",
    "centre": "center", "centres": "centers",
    "licence": "license", "favourite": "favorite",
    "neighbour": "neighbor", "neighbours": "neighbors",
    "grey": "gray", "cancelled": "canceled",
    "modelled": "modeled", "modelling": "modeling",
    "metre": "meter", "metres": "meters",
    "litre": "liter", "litres": "liters",
}
FIND = re.compile(r"\\b(" + "|".join(map(re.escape, sorted(WORDS, key=len, reverse=True))) + r")\\b", re.IGNORECASE)


def main() -> int:
    files = sorted(ROOT.glob("*.md")) + sorted((ROOT / "docs").rglob("*.md"))
    problems = []
    for path in files:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in FIND.finditer(line):
                problems.append(
                    f"{path.relative_to(ROOT)}:{line_number}: "
                    f"{match.group()} -> {WORDS[match.group().lower()]}"
                )
    if problems:
        print("U.S. English style check failed:\\n" + "\\n".join(problems), file=sys.stderr)
        return 1
    print(f"U.S. English style check passed ({len(files)} Markdown files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
