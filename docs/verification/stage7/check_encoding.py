#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 7: verify UTF-8 no-BOM / LF / trailing newline for deliverables."""

from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "17_encoding_check.log")

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
    "docs/state/project_state.json",
    "docs/CHANGELOG_DEV.md",
    "docs/SESSION_HANDOFF.md",
    "README.md",
]


def main() -> int:
    lines = ["STAGE7 ENCODING CHECK (UTF-8 no BOM / LF / trailing newline)", ""]
    bad = 0
    for rel in FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            lines.append(f"MISSING\t{rel}")
            bad += 1
            continue
        raw = open(path, "rb").read()
        bom = raw.startswith(b"\xef\xbb\xbf")
        cr = raw.count(b"\r")
        lf = raw.count(b"\n")
        trailing = raw.endswith(b"\n")
        try:
            raw.decode("utf-8")
            utf8 = True
        except UnicodeDecodeError:
            utf8 = False
        ok = utf8 and not bom and cr == 0 and trailing
        if not ok:
            bad += 1
        lines.append(
            f"{'OK' if ok else 'BAD'}\t{rel}\tutf8={utf8}\tbom={bom}\tCR={cr}\tLF={lf}\ttrailing_lf={trailing}"
        )
    lines.append("")
    lines.append(f"FILES={len(FILES)} BAD={bad}")
    lines.append(f"RESULT={'PASS' if bad == 0 else 'FAIL'}")
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"ENCODING={'PASS' if bad == 0 else 'FAIL'}")
    print(f"FILES={len(FILES)} BAD={bad}")
    print(f"OUT={OUT}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
