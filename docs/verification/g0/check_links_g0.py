#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_links_g0.py — 只读检查 G0 文档与 contracts/ 的相对 Markdown 链接。

与 docs/verification/stage7/check_links.py 的区别：
- 只读，**不写任何证据文件**（stage7 版本按设计覆盖自身日志，不得再用于本轮）。
- 文件清单由调用方给出，便于只检查本轮改动的文档。
- 输出到 stdout，由调用方重定向到本轮日志。

用法：
    $py docs/verification/g0/check_links_g0.py docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md ...
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def check(rel_paths: list[str]) -> int:
    total = 0
    broken = 0
    for rel in rel_paths:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            print(f"MISSING_FILE\t{rel}")
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
                print(f"BROKEN\t{rel}\t{target}\t-> {resolved}")
    print(f"FILES={len(rel_paths)} LINKS_CHECKED={total} BROKEN={broken}")
    print(f"RESULT={'PASS' if broken == 0 else 'FAIL'}")
    return 0 if broken == 0 else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("usage: check_links_g0.py <repo-relative markdown> [...]")
        raise SystemExit(2)
    print(f"G0 LINK CHECK (read-only) ROOT={ROOT}")
    raise SystemExit(check(args))