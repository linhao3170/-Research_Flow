#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 7: verify task evidence paths and referenced scripts exist."""

from __future__ import annotations

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
STATE = os.path.join(ROOT, "docs", "state", "project_state.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "15_task_evidence_check.log")


def main() -> int:
    data = json.load(open(STATE, encoding="utf-8"))
    lines = ["STAGE7 TASK EVIDENCE CHECK", f"STATE={STATE}", ""]
    missing = 0
    checked = 0
    for task in data["tasks"]:
        lines.append(f"[{task['task_id']}] status={task['status']}")
        for rel in task["evidence_paths"]:
            checked += 1
            path = os.path.join(ROOT, rel)
            if os.path.exists(path):
                lines.append(f"  OK   {rel}")
            else:
                missing += 1
                lines.append(f"  MISS {rel}")
        for cmd in task["test_commands"]:
            m = re.search(r"(docs/[^\s]+\.py)", cmd)
            if m:
                checked += 1
                path = os.path.join(ROOT, m.group(1))
                if os.path.exists(path):
                    lines.append(f"  OK   {m.group(1)}")
                else:
                    missing += 1
                    lines.append(f"  MISS {m.group(1)}")
        lines.append("")
    lines.append(f"CHECKED={checked}")
    lines.append(f"MISSING={missing}")
    lines.append(f"RESULT={'PASS' if missing == 0 else 'FAIL'}")
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"TASK_EVIDENCE={'PASS' if missing == 0 else 'FAIL'}")
    print(f"CHECKED={checked} MISSING={missing}")
    print(f"OUT={OUT}")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
