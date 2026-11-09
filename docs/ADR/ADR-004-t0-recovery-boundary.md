# ADR-004：T0 恢复边界（内部不可变计划 + 控制事件不入 E0–E3 + 不复用 Recovery 状态机）

| 字段 | 内容 |
|---|---|
| 编号 | `ADR-004` |
| 状态 | **ACCEPTED**（用户 2026-11-09，决议 3/4/5/6） |
| 日期 | 2026-11-09 |
| 决策者 | 用户（书面决议 3、4、5、6） |
| 影响版本 | 状态机 `1.0`；`evidence_invalidations`、`audit_log`、`nodes` 表 |
| 取代 | 无（原 v0.1 的 ADR-003 候选编号已顺延） |

## 1. 背景

`FR-010` 是 P0，但 T0 不接 LLM、不做六角色、没有人工审批界面。策划书 TABLE 26 的 Recovery 状态机（`PROPOSED → VALIDATED → APPROVED → EXECUTING → RECHECKED → CLOSED`）隐含“Recovery Agent 提案 + 人工批准”。若 T0 直接复用：

- 会引入 T0 不具备的 Agent 与审批语义，形成“文档里有、实现里没有”的空壳状态；
- 计划可能在执行中被改写，破坏“执行前冻结”；
- 失效事件若计入 E0–E3，会让控制面污染证据面，Gate 的等级判定失效。

## 2. 决策

1. **`RecoveryPlan` 是 T0 内部不可变产物**：不签名、不进七契约、不对外。
2. 计划存为**内容寻址文件**（文件名 = SHA-256，即 `plan_hash`），**不入库**；DB 只存 `nodes.plan_id`/`nodes.plan_hash` 与 `audit_log` 的冻结记录。
3. 冻结时把 `plan_hash` 写入 `audit_log`；`INVALIDATED → READY` 守卫必须同时校验：
   - 计划文件存在于内容寻址路径；
   - `sha256(文件字节) == plan_hash`，且与 `audit_log` 冻结记录一致；
   - 冻结事件早于本次重跑。
   任一不满足即拒绝迁移并写 `DENIED` 审计。
4. **失效/恢复控制事件只写 `audit_log` + `evidence_invalidations`**（追加写、引用 stale `evidence_id` 与变更原因），**不占用 E0–E3**。Gate 读 `evidence_invalidations` 拒绝 stale 证据；即使 stale 证据仍在证据包内，也不得满足必检项。
5. **T0 不复用完整 Recovery 状态机**：无 `PROPOSED`/`APPROVED`、无 Agent 提案、无人工审批；T0 恢复路径必须确定性、可重放（同输入 ⇒ 同 `plan_hash`）。完整状态机与 G4 留 T1。

## 3. 后果

- ⑥ 删除 `recovery_plans` 表；`nodes` 增 `plan_id`/`plan_hash`（成对约束）；`audit_log` 增 `plan_id`/`plan_hash`/`error_code`。
- 计划正文不得含时间戳/随机序；`frozen_at` 只写 `audit_log`。
- `WP-08` 的 stale 判定以失效表为准，不以“证据是否还在包里”为准。
- `WP-R` 必须证明：同一输入两次生成同一 `plan_hash`；三条守卫负例各返回 `DENIED`。

## 4. 备选（未选）

| 方案 | 未选原因 |
|---|---|
| T0 复用完整 Recovery 状态机 | 需要 Agent 提案与审批，T0 不具备；会产生无法实现的状态 |
| 计划存 DB 表 | 可被 `UPDATE`，违背“不可变”；且与 `plan_hash` 的内容寻址语义重复 |
| 失效事件记 E1/E2 | 控制面污染证据面，E2 变成“系统自己声明自己失效”，Gate 无法独立核验 |
| 失效时删除 stale 证据 | 破坏只追加与可追溯，无法解释“为什么曾经 PASS” |

## 5. 验证

- `tests/t0/test_fr_010_minimal*`：确定性复算、计划存在/hash 一致/先冻结三条守卫负例。
- `tests/t0/test_fr_006*`、`tests/t0/test_fr_003*`：stale 拒绝与 `INVALIDATED` 两条边。
- 文档：⑤ §9.3/§9.5、⑥ §1.3/§2、⑦ `WP-R`/`WP-08`。