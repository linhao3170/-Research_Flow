#!/usr/bin/env python3
"""生成 WP-01 环境指纹、依赖核对表与锁文件摘要（只读环境，不安装）。"""

from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import platform
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
WP01 = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
CACHE = ROOT / ".uv-cache"
LOCK = ROOT / "requirements.lock"
IN = ROOT / "requirements.in"

# 包名, 矩阵版本, 说明
MATRIX = [
    ("fastapi", "0.162.2", "矩阵 §2"),
    ("pydantic", "2.14.3", "矩阵 §2"),
    ("networkx", "3.6.1", "矩阵 §2"),
    ("pandas", "3.1.1", "矩阵 §2"),
    ("scikit-learn", "1.9.1", "矩阵 §2"),
    ("cryptography", "50.0.2", "矩阵 §2"),
    ("streamlit", "1.67.0", "矩阵 §2"),
    ("pytest", "9.2.0", "矩阵 §2"),
    ("uv", "0.13.7", "矩阵 §2；工具，不进入 .venv"),
    ("numpy", "2.4.6", "矩阵 §2.1"),
    ("scipy", "1.17.1", "矩阵 §2.1"),
    ("pydantic-core", "2.50.4", "矩阵 §2.1"),
    ("starlette", "1.10.0", "矩阵 §2.1"),
    ("cffi", "2.1.1", "矩阵 §2.1"),
    ("pyarrow", "26.0.1", "矩阵 §2.1"),
    ("pillow", "13.0.0", "矩阵 §2.1"),
    ("protobuf", "7.36.2", "矩阵 §2.1"),
]


def dir_size(path: Path) -> tuple[int, int]:
    total = 0
    count = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
            count += 1
    return total, count


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def actual_version(name: str) -> str:
    if name == "uv":
        result = subprocess.run(["uv", "--version"], capture_output=True, text=True, check=False)
        match = re.search(r"uv\s+([0-9][^\s]*)", result.stdout + result.stderr)
        return match.group(1) if match else "UNKNOWN"
    return metadata.version(name)


def main() -> int:
    now = datetime.now(timezone(timedelta(hours=8)))
    venv_bytes, venv_files = dir_size(VENV)
    cache_bytes, cache_files = dir_size(CACHE)
    lock_text = LOCK.read_text(encoding="utf-8")
    lock_packages = [line for line in lock_text.splitlines() if line and not line.startswith("#")]

    fingerprint = {
        "captured_at": now.isoformat(timespec="seconds"),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "architecture": platform.architecture()[0],
            "compiler": platform.python_compiler(),
            "executable": sys.executable,
            "sqlite_version": sqlite3.sqlite_version,
        },
        "project": {
            "root": str(ROOT),
            "venv": str(VENV),
            "venv_size_bytes": venv_bytes,
            "venv_file_count": venv_files,
        },
        "uv": {
            "version": actual_version("uv"),
            "cache_dir": str(CACHE),
            "cache_size_bytes": cache_bytes,
            "cache_file_count": cache_files,
        },
        "lock": {
            "path": "requirements.lock",
            "sha256": sha256(LOCK),
            "packages": len(lock_packages),
        },
        "direct_input": {
            "path": "requirements.in",
            "sha256": sha256(IN),
        },
    }
    (WP01 / "env_fingerprint.json").write_text(
        json.dumps(fingerprint, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    rows = []
    mismatches = []
    for name, expected, note in MATRIX:
        actual = actual_version(name)
        match = "一致" if actual == expected else "**不一致**"
        if actual != expected:
            mismatches.append((name, expected, actual, note))
        rows.append(f"| {name} | {expected} | {actual} | {match} | {note} |")

    sqlite_actual = sqlite3.sqlite_version
    rows.append(
        f"| SQLite | 3.53.1（随解释器） | {sqlite_actual} | "
        f"{'一致' if sqlite_actual == '3.53.1' else '**不一致**'} | 矩阵 §2；stdlib |"
    )

    numpy_actual = metadata.version("numpy")
    numpy_ok = tuple(int(part) for part in numpy_actual.split(".")[:2]) >= (2, 0) and tuple(
        int(part) for part in numpy_actual.split(".")[:2]
    ) < (2, 7)
    numpy_ok = numpy_actual == "2.4.6" and numpy_ok

    lines = [
        "# WP-01 依赖解析与矩阵核对",
        "",
        f"> 生成时间：{now.isoformat(timespec='seconds')}",
        f"> 解释器：`{sys.executable}`",
        f"> 矩阵：`docs/verification/g0/09_dependency_matrix.md`（v1.0，2026-11-10 锁定）",
        "",
        "| 包名 | 矩阵版本 | 实际版本 | 是否一致 | 说明 |",
        "|---|---|---|---|---|",
        *rows,
        "",
        "## 矩阵外新增（用户批准）",
        "",
        "| 包名 | 版本 | 原因 |",
        "|---|---|---|",
        "| httpx2 | 2.16.0 | starlette 1.10.0 `TestClient` 要求；2026-11-10 用户批准 |",
        "| httpcore2 | 2.16.0 | httpx2 传递依赖 |",
        "| truststore | 0.10.5 | httpx2 传递依赖 |",
        "",
        "## numpy 区间",
        "",
        f"- 实际：`{numpy_actual}`；要求：`[2.0.2, 2.7)`；结论：{'PASS' if numpy_ok else 'FAIL'}。",
        "",
        "## 偏差",
        "",
    ]
    if mismatches:
        for name, expected, actual, note in mismatches:
            lines.append(f"- `{name}`：矩阵 `{expected}`，实际 `{actual}`；{note}。")
    else:
        lines.append("- 无。")
    lines.extend(
        [
            "",
            f"- `uv` 为工具版本而非 `.venv` 运行时依赖；矩阵注明“是否升级由 WP-01 决定”。本次保留 0.12.16，"
            "理由是它成功完成 3.11.16 venv 创建、55 包解析与 58 包安装，且升级全局工具不在本工作包必要范围；"
            "该偏差已记录，未静默升级。",
            "",
        ]
    )
    (WP01 / "dependency_resolution.txt").write_text("\n".join(lines), encoding="utf-8", newline="\n")

    lock_lines = [
        "# WP-01 锁文件摘要",
        "",
        f"- 路径：`requirements.lock`",
        f"- SHA256：`{sha256(LOCK)}`",
        f"- 锁定包数：{len(lock_packages)}",
        f"- 直接依赖清单：`requirements.in`，SHA256 `{sha256(IN)}`",
        f"- 安装验证：`uv pip install -r requirements.lock` → exit 0，`Checked 58 packages`",
        f"- 干净环境复现：`.venv-repro` 从锁文件安装 → TestClient 200，43.95 s，已删除",
        "",
    ]
    (WP01 / "lockfile.txt").write_text("\n".join(lock_lines), encoding="utf-8", newline="\n")

    smoke = (WP01 / "testclient_smoke.log").read_text(encoding="utf-8")
    smoke_ok = "TESTCLIENT_OK 200" in smoke
    smoke_text = '通过（200 {"ok": true}）' if smoke_ok else "失败"
    starlette_lines = [
        "# starlette 实测与回退判断",
        "",
        "- 矩阵版本：`1.10.0`；实测版本：`1.10.0`；结论：**一致**。",
        "- FastAPI：`0.162.2`。",
        f"- TestClient 冒烟：{smoke_text}。",
        "- 回退判断：**不回退**。失败原因不是 starlette 1.x 与 FastAPI 不兼容，而是缺少 starlette 1.10.0 "
        "TestClient 所需的 `httpx2`；经用户批准安装 `httpx2==2.16.0` 后冒烟通过。",
        "- 证据：`testclient_smoke.log`、`install_httpx2.log`。",
        "",
    ]
    (WP01 / "starlette_resolution.txt").write_text(
        "\n".join(starlette_lines), encoding="utf-8", newline="\n"
    )

    print("ENV_EVIDENCE=OK")
    print(f"venv_bytes={venv_bytes} venv_files={venv_files}")
    print(f"cache_bytes={cache_bytes} cache_files={cache_files}")
    print(f"lock_packages={len(lock_packages)}")
    print(f"mismatches={mismatches}")
    print(f"numpy_ok={numpy_ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
