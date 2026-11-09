#!/usr/bin/env python3
"""校验项目级 Skill Bundle 的结构、frontmatter 与引用。

只使用 Python 标准库；不解析完整 YAML，只校验本项目要求的字段与章节。
真正的 frontmatter 解析与 catalog 注册由 DSH 的 skills provider 负责。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

REQUIRED_SKILLS = (
    "researchflow-onboarding",
    "researchflow-spec-driven-development",
    "researchflow-prompt-workflow",
    "researchflow-contracts-api",
    "researchflow-python-backend",
    "researchflow-dag-state-machine",
    "researchflow-evidence-security",
    "researchflow-testing-benchmark",
    "researchflow-memory-handoff",
)

REQUIRED_SECTIONS = (
    "适用条件",
    "输入与前置检查",
    "执行步骤",
    "不可违反的约束",
    "输出要求",
    "验收标准",
    "相关文件",
    "失败与暂停条件",
)

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REF_RE = re.compile(r"references/[a-z0-9-]+\.md")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """返回 (frontmatter, body)；格式不合法时返回 None。"""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields, text[end + 5 :]


def validate(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    rows: list[str] = []

    if not root.is_dir():
        return [f"Skill 根目录不存在：{root}"], rows

    found = sorted(path.name for path in root.iterdir() if path.is_dir())
    if found != sorted(REQUIRED_SKILLS):
        errors.append(f"Skill 目录集合不匹配：找到 {found}")

    for name in REQUIRED_SKILLS:
        skill_dir = root / name
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"{name}: 缺少 SKILL.md")
            continue

        raw = skill_file.read_bytes()
        text = raw.decode("utf-8")
        parsed = parse_frontmatter(text)
        if parsed is None:
            errors.append(f"{name}: frontmatter 格式不合法")
            continue
        fields, body = parsed

        if fields.get("name") != name:
            errors.append(f"{name}: frontmatter name={fields.get('name')!r}")
        if not NAME_RE.fullmatch(fields.get("name", "")):
            errors.append(f"{name}: name 不是 kebab-case")
        description = fields.get("description", "")
        if len(description) < 40:
            errors.append(f"{name}: description 缺失或过短")

        missing = [section for section in REQUIRED_SECTIONS if section not in body]
        if missing:
            errors.append(f"{name}: 缺少章节 {missing}")
        numbers = re.findall(r"^##\s+([1-8])\.", body, re.MULTILINE)
        expected_numbers = [str(index) for index in range(1, 9)]
        if numbers != expected_numbers:
            errors.append(f"{name}: 章节编号为 {numbers}，应为 {expected_numbers}")

        for reference in sorted(set(REF_RE.findall(body))):
            if not (skill_dir / reference).is_file():
                errors.append(f"{name}: 引用资源不存在 {reference}")

        digest = hashlib.sha256(raw).hexdigest().upper()
        rows.append(
            f"PASS {name}: bytes={len(raw)} lines={text.count(chr(10)) + 1} "
            f"sha256={digest}"
        )

    nested = [
        str(path.relative_to(root))
        for path in root.rglob("SKILL.md")
        if len(path.relative_to(root).parts) != 2
    ]
    if nested:
        errors.append(f"存在多层嵌套 SKILL.md：{nested}")

    return errors, rows


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 ResearchFlow 项目级 Skills")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".agents" / "skills",
        help="Skill 根目录（默认：项目 .agents/skills）",
    )
    args = parser.parse_args()

    errors, rows = validate(args.root)
    print(f"Skill root: {args.root}")
    for row in rows:
        print(row)
    if errors:
        print("\nFAIL:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"\nOK: {len(REQUIRED_SKILLS)} 个 Skill 结构校验通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
