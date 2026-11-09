# 26 策划书版本冲突与用户决议

## 1. 用户决议（2026-11-08）

> 结论：策划书内容基线 = v4.3.0；文件名中的 v4.3.1 只是标签，不是另一个版本。

处理：

1. `BLK-002` 关闭；`resolution` 记录用户确认内容；`severity` 保留 `HIGH` 作为历史属性。
2. `CONFLICT_REPORT` 的 `C-001` 标为 `RESOLVED（用户决议）`，保留全部原始证据行。
3. 不修改 DOCX、不改文件名、不移动文件；`SOURCE_REGISTER` 的“禁止再产生第二份策划书副本”继续有效。
4. 阶段 9 的 G0 裁决清单中，版本一项标“已决”，其余 3 项保留。
5. `T-DOCS-001` 由 `IN_REVIEW` 转 `DONE`。

## 2. 文档事实未变

| 项 | 值 |
|---|---|
| DOCX 大小 | 111,209 字节 |
| SHA256 | `9E54168FB1B553294ECB88E2E3F5C8CE878EE699FCF07E37D531A68C195CCB3A` |
| 文档内 `v4.3.1` 计数 | 0 |
| 文档内 `v4.3.0` 计数 | 6（document.xml）+ 1（header）+ 1（core） |
| 文件名 | 未改；`v4.3.1` 仅标签 |
| 副本数 | 全项目仅 1 份 DOCX；inbox 仅 `.gitkeep` |

## 3. 状态映射说明

`project_state.json` 的 blocker 状态枚举只有 `OPEN` / `RESOLVED` / `WAIVED`，没有 `CLOSED`。为通过 `state_sync.py validate`，状态使用 `RESOLVED` 表示“已关闭”，并在 `resolution` 中写明“用户决议关闭（等价 CLOSED）”。这是 schema 映射，不是把用户决议改成“未关闭”。

## 4. 判定

PASS：版本冲突已登记、用户已确认基线、DOCX 未变、C-001 已解决、T-DOCS-001 可转 DONE。
