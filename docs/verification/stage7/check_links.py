#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 7: check relative Markdown links in new/updated docs.

Read-only. External URLs, anchors, and code spans are ignored.
"""

from __future__ import annotations

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "14_link_check.log")

FILES = [
    "docs/reference/SOURCE_REGISTER.md",
    "docs/reference/CONFLICT_REPORT.md",
    "docs/PROJECT_OVERVIEW.md",
    "docs/ARCHITECTURE.md",
    "docs/GLOSSARY.md",
    "docs/DEVELOPMENT_WORKFLOW.md",
    "docs/MEMORY_GUIDE.md",
    "docs/MCP_CATALOG.md",
    "docs/SECURITY_POLICY.md",
    "docs/SKILL_CATALOG.md",
    "docs/verification/stage7/STAGE7_REPORT.md",
    "docs/verification/stage7/06_page_map_attempt.md",
    "docs/memory/references.md",
    "docs/memory/project-context.md",
    "docs/memory/architecture-decisions.md",
    "docs/memory/feedback-and-lessons.md",
    "docs/memory/environment.md",
    "docs/memory/Memory.md",
    "docs/state/runtime_states.md",
    "README.md",
]

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def main() -> int:
    lines = ["STAGE7 RELATIVE MARKDOWN LINK CHECK", f"ROOT={ROOT}", ""]
    total = 0
    broken = 0
    for rel in FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            lines.append(f"MISSING_FILE\t{rel}")
            broken += 1
            continue
        text = open(path, encoding="utf-8").read()
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        text = re.sub(r"`[^`]*`", "", text)
        base = os.path.dirname(path)
        for target in LINK_RE.findall(text):
            target = target.strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_path = target.split("#", 1)[0]
            if not target_path:
                continue
            total += 1
            resolved = os.path.normpath(os.path.join(base, target_path))
            if not os.path.exists(resolved):
                broken += 1
                lines.append(f"BROKEN\t{rel}\t{target}\t-> {resolved}")
    lines.append("")
    lines.append(f"LINKS_CHECKED={total}")
    lines.append(f"BROKEN={broken}")
    lines.append(f"RESULT={'PASS' if broken == 0 else 'FAIL'}")
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"LINK_CHECK={'PASS' if broken == 0 else 'FAIL'}")
    print(f"LINKS={total} BROKEN={broken}")
    print(f"OUT={OUT}")
    return 0 if broken == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
