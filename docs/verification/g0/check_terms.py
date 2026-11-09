#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_terms.py — G0 四词一致性与自动断言（只读，只输出到 stdout）。

检查范围：②③④⑤⑥⑦（文档 05-07 与 02-04）。
四个词：schema_version / INVALIDATED / plan_hash / dataset_ref。

自动断言（只覆盖能机器判定的部分，语义一致性仍需人工复核）：
  A1 不得出现字符串形态的 dataset_ref（`"dataset_ref": "..."`）。
  A2 出现 plan_hash 的文件必须同时出现 plan_id（决议 5 要求成对存储）。
  A3 出现 schema_version 的文件必须出现 1.0（本版 const 值）。

用法：
    $py docs/verification/g0/check_terms.py
退出码：0 断言全过；1 存在断言失败。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FILES = [
    "docs/PRD/02_REQUIREMENT_TRACEABILITY.md",
    "docs/PRD/03_PRD_T0.md",
    "docs/design/04_ARCHITECTURE.md",
    "docs/design/05_CONTRACTS_AND_STATES.md",
    "docs/design/06_DATA_AND_API.md",
    "docs/design/07_T0_PLAN_AND_GATES.md",
]
TERMS = ["schema_version", "INVALIDATED", "plan_hash", "dataset_ref"]


def main() -> int:
    texts = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in FILES}
    lines = {rel: text.splitlines() for rel, text in texts.items()}

    print("G0 TERM CONSISTENCY CHECK (read-only)")
    print(f"ROOT={ROOT}")
    print("FILES=" + ",".join(FILES))
    print()

    header = "file".ljust(44) + "".join(term.ljust(18) for term in TERMS)
    print(header)
    print("-" * len(header))
    counts: dict[str, dict[str, int]] = {}
    for rel in FILES:
        counts[rel] = {}
        row = rel.ljust(44)
        for term in TERMS:
            hit_lines = [i for i, line in enumerate(lines[rel], start=1) if term in line]
            counts[rel][term] = len(hit_lines)
            row += str(len(hit_lines)).ljust(18)
        print(row)
    print()

    print("OCCURRENCES")
    for rel in FILES:
        for term in TERMS:
            hits = [(i, line.strip()) for i, line in enumerate(lines[rel], start=1) if term in line]
            if not hits:
                continue
            print(f"\n[{rel}] {term} = {len(hits)}")
            for number, text in hits:
                if len(text) > 220:
                    text = text[:220] + "…"
                print(f"  L{number}: {text}")
    print()

    failures: list[str] = []
    for rel, text in texts.items():
        if re.search(r'"dataset_ref"\s*:\s*"', text):
            failures.append(f"A1 {rel}: 发现字符串形态 dataset_ref")
        if counts[rel]["plan_hash"] and "plan_id" not in text:
            failures.append(f"A2 {rel}: 有 plan_hash 但无 plan_id")
        if counts[rel]["schema_version"] and "1.0" not in text:
            failures.append(f"A3 {rel}: 有 schema_version 但无 1.0")

    print("ASSERTIONS")
    print("A1 no-string-dataset_ref: " + ("PASS" if not any(f.startswith("A1") for f in failures) else "FAIL"))
    print("A2 plan_hash-with-plan_id: " + ("PASS" if not any(f.startswith("A2") for f in failures) else "FAIL"))
    print("A3 schema_version-1.0: " + ("PASS" if not any(f.startswith("A3") for f in failures) else "FAIL"))
    for failure in failures:
        print("  FAIL " + failure)
    print()
    print("TERMS_RESULT=" + ("PASS" if not failures else "FAIL"))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())