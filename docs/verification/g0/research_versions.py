#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""research_versions.py — 依赖版本矩阵**只读**调研（不安装、不建 venv、不写 lock）。

对每个包：
  1. 取 `https://pypi.org/pypi/<pkg>/json` 的 releases 文件表（含每个版本的
     `requires_python` 与 wheel 文件名），据此筛出“允许 Python 3.11 且存在
     win_amd64 兼容 wheel”的最近稳定版本；
  2. 只对该版本再取一次 `<pkg>/<ver>/json`，读取 `requires_dist` 判断传递依赖；
  3. 输出最新版、选定版、wheel 文件名、被跳过的版本与原因。

只发 GET 请求，不下载包体、不调用 pip、不修改环境。
用法：$py -u docs/verification/g0/research_versions.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request

TARGET = (3, 11, 16)
PACKAGES = [
    "fastapi",
    "pydantic",
    "networkx",
    "pandas",
    "scikit-learn",
    "cryptography",
    "streamlit",
    "pytest",
    "uv",
    # 关键传递依赖（决定是否真的无需编译）
    "numpy",
    "scipy",
    "pydantic-core",
    "cffi",
    "starlette",
    "pyarrow",
    "pillow",
    "protobuf",
]

VERSION_RE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$")


def vparts(text: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(text or "")
    if not match:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2) or 0), int(match.group(3) or 0))


def is_stable(text: str) -> bool:
    match = VERSION_RE.match(text or "")
    if not match:
        return False
    tail = (match.group(4) or "").lower()
    return not tail or tail.startswith(".post")


def allows(spec: str | None) -> bool:
    if not spec:
        return True
    for raw in spec.split(","):
        clause = raw.strip()
        match = re.match(r"(>=|<=|==|!=|>|<)\s*([0-9][0-9A-Za-z.*]*)", clause)
        if not match:
            continue
        op, value = match.group(1), match.group(2)
        if value.endswith(".*"):
            prefix = value[:-2].split(".")
            actual = ".".join(str(item) for item in TARGET[: len(prefix)])
            if op in ("==", "!="):
                equal = actual == ".".join(prefix)
                if (op == "==" and not equal) or (op == "!=" and equal):
                    return False
            continue
        left, right = TARGET, vparts(value)
        checks = {
            ">=": left >= right,
            ">": left > right,
            "<=": left <= right,
            "<": left < right,
            "==": left == right,
            "!=": left != right,
        }
        if not checks[op]:
            return False
    return True


def wheel_for_windows(files: list[dict]) -> tuple[str | None, int | None]:
    for item in files:
        name = item.get("filename", "")
        if not name.endswith(".whl"):
            continue
        parts = name[:-4].split("-")
        if len(parts) < 5:
            continue
        py_tag, abi_tag, platform_tag = parts[-3], parts[-2], parts[-1]
        if platform_tag == "any":
            if py_tag in ("py3", "py2.py3"):
                return name, item.get("size")
            continue
        if platform_tag != "win_amd64":
            continue
        if any(token in name.lower() for token in ("musllinux", "manylinux", "macosx", "win32", "arm64")):
            continue
        if py_tag.startswith("cp311") or py_tag in ("py3", "py2.py3") or abi_tag == "abi3":
            return name, item.get("size")
    return None, None


def fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "researchflow-g0-research/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def pick(package: str) -> dict:
    data = fetch(f"https://pypi.org/pypi/{package}/json")
    releases = data.get("releases", {})
    versions = sorted((v for v in releases if is_stable(v)), key=vparts, reverse=True)
    result = {
        "package": package,
        "latest": data["info"]["version"],
        "latest_requires_python": data["info"].get("requires_python"),
        "chosen": None,
        "requires_python": None,
        "wheel": None,
        "requires_dist": [],
        "skipped": [],
    }
    for version in versions[:10]:
        files = releases.get(version) or []
        if not files:
            result["skipped"].append((version, "该版本无文件记录"))
            continue
        spec = next((f.get("requires_python") for f in files if f.get("requires_python")), None)
        wheel, wheel_size = wheel_for_windows(files)
        reasons = []
        if not allows(spec):
            reasons.append(f"requires_python {spec!r} 不允许 3.11")
        if wheel is None:
            reasons.append("无 win_amd64 兼容 wheel")
        if reasons:
            result["skipped"].append((version, "; ".join(reasons)))
            continue
        result.update(
            {
                "chosen": version,
                "requires_python": spec,
                "wheel": wheel,
                "wheel_size": wheel_size,
            }
        )
        detail = fetch(f"https://pypi.org/pypi/{package}/{version}/json")
        result["requires_dist"] = detail["info"].get("requires_dist") or []
        break
    return result


def main() -> int:
    print("DEPENDENCY RESEARCH (read-only; no install, no venv, no lock)")
    print(f"TARGET_PYTHON={TARGET[0]}.{TARGET[1]}.{TARGET[2]}  PLATFORM=win_amd64")
    print()
    for package in PACKAGES:
        print(f"##### {package}", flush=True)
        try:
            item = pick(package)
        except Exception as exc:
            print(f"ERROR {type(exc).__name__}: {exc}", flush=True)
            continue
        print(f"latest={item['latest']} latest_requires_python={item['latest_requires_python']!r}")
        print(f"chosen={item['chosen']} requires_python={item['requires_python']!r}")
        print(f"wheel={item['wheel']}")
        size = item.get("wheel_size")
        print(f"wheel_size_mb={round(size / 1048576, 2) if size else 'n/a'}")
        for version, reason in item["skipped"]:
            print(f"skipped={version} reason={reason}")
        for dep in item["requires_dist"]:
            if "extra ==" in dep:
                continue
            print(f"dep={dep}")
        print(flush=True)
    print("RESULT=OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())