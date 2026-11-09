# ADR-001：Node 增加 `INVALIDATED` 状态（FR-010 T0 最小切片）

| 字段 | 内容 |
|---|---|
| 编号 | `ADR-001` |
| 状态 | **ACCEPTED**（用户 2026-11-08） |
| 日期 | 2026-11-08（决策）；2026-11-09（正式文件落地） |
| 决策者 | 用户（书面决议 B1） |
| 影响版本 | 契约/状态机 `1.0`；G0 文档 ⑤⑥⑦ |
| 取代 | 无 |

## 1. 背景

`FR-010` 为 P0；用户决议 B1 要求 T0 完成“失效传播 + 执行前冻结恢复计划 + 受影响后代保守重跑”。策划书附录 F 的 Node 迁移表没有 `VERIFIED` 的出边，已 `VERIFIED` 的节点无法表达“原证据失效”，存在继续复用 stale 证据的风险。

## 2. 决策

1. Node 新增 `INVALIDATED` 状态，Node 状态由 9 个变为 10 个。
2. 只授权两条边：`VERIFIED → INVALIDATED` 与 `INVALIDATED → READY`；其他边未授权，需新 ADR。
3. `INVALIDATED` 的语义是“曾 `VERIFIED`，但上游输入/前驱/图版本/规则版本变化，原证据 stale”；不等于 `FAILED`，也不等于 `BLOCKED`。
4. Gate 必须拒绝 stale 证据；证据不删除，追加失效记录。
5. Task 级 `COMPLETED` 之后的失效留 T1 / revocation，T0 不实现。

## 3. 后果

- 状态机、DB、API、测试、文档同步；`evidence_invalidations` 为追加表。
- `INVALIDATED → READY` 需要计划引用与守卫，后续由 `ADR-004`（计划形态）与决议 5 补齐。
- 未授权迁移由 StateMachine 拒绝并写审计。

## 4. 备选（未选）

| 方案 | 未选原因 |
|---|---|
| `VERIFIED` + `stale` 布尔字段 | 改动小，但语义不显式，Gate 与 UI 都容易漏判 |
| 复用 `BLOCKED` | 与缺口/权限/资源/冲突混淆，无法区分“证据过期”与“执行受阻” |
| 只靠 revocation event | 无法表达节点级重跑生命周期，且 revocation 属 T1/Task 级 |

## 5. 验证

- `VERIFIED` 节点上游变化 → 后代 `INVALIDATED`；stale 证据不能过 Gate。
- `INVALIDATED → READY` 后重跑产生新证据；非法迁移拒绝。
- 测试位置：`tests/t0/test_fr_003*`、`tests/t0/test_fr_010_minimal*`；文档见 ⑤ §9.3、⑦ `WP-R`。

## 6. 关联

- 用户决议 B1（2026-11-08）。
- `ADR-004`（T0 恢复边界）、`ADR-005`（失败迁移审计）。
- ⑧ §2 `OQ-001/002/013/015` 的关闭背景。