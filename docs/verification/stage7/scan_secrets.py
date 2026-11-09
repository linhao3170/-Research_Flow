#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 7: secret-pattern scan for newly written documentation.

Read-only. Reports counts only; never prints matched secret values.
"""

from __future__ import annotations

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "13_secret_scan.log")

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
    "docs/memory/references.md",
    "docs/memory/project-context.md",
    "docs/memory/architecture-decisions.md",
    "docs/memory/feedback-and-lessons.md",
    "docs/memory/environment.md",
    "docs/state/runtime_states.md",
    "docs/state/project_state.json",
    "docs/CHANGELOG_DEV.md",
    "docs/SESSION_HANDOFF.md",
    "README.md",
]

PATTERNS = {
    "openai_like_key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "password_assignment": re.compile(r"(?i)\bpassword\s*[:=]\s*['\"]?[^\s'\"<>]{6,}"),
    "token_assignment": re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|secret[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "cn_mobile": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "cn_id": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
}


def main() -> int:
    lines = [
        "STAGE7 SECRET-PATTERN SCAN (read-only; counts only)",
        f"ROOT={ROOT}",
        f"FILES={len(FILES)}",
        "",
    ]
    total = 0
    missing = 0
    for rel in FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            lines.append(f"MISSING\t{rel}")
            missing += 1
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        hits = []
        for name, pattern in PATTERNS.items():
            count = len(pattern.findall(text))
            if count:
                hits.append(f"{name}={count}")
                total += count
        lines.append(f"{'HIT' if hits else 'OK'}\t{rel}\t" + (", ".join(hits) if hits else "0"))
    lines.append("")
    lines.append(f"TOTAL_HITS={total}")
    lines.append(f"MISSING_FILES={missing}")
    lines.append(f"RESULT={'PASS' if total == 0 and missing == 0 else 'REVIEW'}")
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"SECRET_SCAN={'PASS' if total == 0 and missing == 0 else 'REVIEW'}")
    print(f"FILES={len(FILES)} HITS={total} MISSING={missing}")
    print(f"OUT={OUT}")
    return 0 if total == 0 and missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
