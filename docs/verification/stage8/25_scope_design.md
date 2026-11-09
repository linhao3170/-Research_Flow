# 25 第一版范围与并发声明

## 1. 设计基线（未变）

- `AGENTS.md` §5：Windows 11 单机；16GB 内存；CPU-only；并发上限 2（必须实测后才能宣称达成）。
- `docs/memory/project-context.md`：
  - 第 32 行：`Windows 11 单机；16GB 内存；CPU-only`
  - 第 33 行：`并发 | 上限 2；必须实测后才能宣称达成`
  - 第 122 行：`16GB 内存与“并发 2”是设计约束；并发能力尚未实测，不得宣称已达成。`

## 2. 是否出现“已验证”措辞

- 全项目 Markdown 搜索“并发 + 已验证/已实测/实测通过”：**0 命中**。
- 未发现把设计目标写成实测能力的表述。

## 3. 判定

- 范围设计仍为 16GB、CPU-only、并发目标 2：**PASS**。
- 并发能力：**NOT VERIFIED**（未做并发压力实测；不得写成已验证）。

证据：`25_scope_design.log`、`AGENTS.md` §5、`docs/memory/project-context.md`。
