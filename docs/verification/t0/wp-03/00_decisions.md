# WP-03 前置裁决记录

> 裁决日期：2026-11-12
> 裁决人：用户
> 来源：用户 2026-11-12 对话“按你的建议来吧”，对应上一轮列出的 16 项问题及建议口径
> 适用范围：T0 WP-03（SQLite 迁移、StateMachine、审计、幂等、API 持久化）
> 性质：本文件是用户书面裁决，用于满足 `DEVELOPMENT_WORKFLOW.md` §11.3 第 3 条；不修改 `design/pseudocode/**`、`docs/design/**`、`docs/ADR/**`。

## 1. 裁决总表

| # | 事项 | 裁决 |
|---:|---|---|
| 1 | §12-2 创建入口 | 采用 `StateMachine.create_initial()` 作为 Task/Node 初始行与初始审计的唯一创建入口；只允许 `CREATED` / `PLANNED`；API/Service 只调用它，不得直接 `INSERT`。M02 设计件没有该函数，本裁决批准其为 WP-03 新增创建入口；它不算状态迁移。 |
| 2 | 创建时初始审计 | 新增 `TASK_CREATED`、`NODE_PLANNED` 审计动作；这两个动作允许 `previous_state` 为空。创建审计 actor 使用 `api:create`，`rule_version=1.0`，`correlation_id` 由 API 生成。该扩展属于实现层审计动作集合，不改变 06 §1.3 的列定义。 |
| 3 | §12-6 `BLOCKED` 终态 | T0 中 Task/Node 的 `BLOCKED` 均为终态，无出边；解除阻塞必须新 ADR，WP-03 不得私自加边。 |
| 4 | §12-7 `idempotency_keys.task_id` | 采用 `NOT NULL` + `REFERENCES tasks(task_id)` + 与 `tasks` 插入同事务；不支持“先占键后建任务”。这是对 06 §1.3 中 `task_id TEXT` 可空、无外键形态的已批准收紧；除该列外，五表其余列/约束仍以 06 §1.3 为基线。不修改 06 冻结件。 |
| 5 | §12-8 幂等键字符集 | `Idempotency-Key` 取 1–255 个可见 ASCII（`0x21–0x7E`），不得含空白。空串、含空白、超长、换行等返回 HTTP 422 `SCHEMA_INVALID`，`field_path="Idempotency-Key"`，不创建任务、不写幂等键。完全未带 `Idempotency-Key` 时允许创建任务，但不保证幂等，也不写幂等键。 |
| 6 | P9/P10 处置 | P9/P10 保持 `BLOCKED`；不验收、不运行、不导入、不复制、不引用；WP-03 不读取 `design/pseudocode/M15_dcspa/**`、`M16_vas/**`、`M19_api/**` 的实现内容。本处置不关闭 P9/P10，不构成验收。 |
| 7 | 裁决记录载体 | 本文件即裁决记录；不要求写入 M02 `DECISIONS` 或 ADR。后续如需正式 ADR，另立任务，不在 WP-03 内做。 |
| 8 | 写入口措辞 | `StateMachine.transition()` 是唯一改变已有状态的公开入口；`StateMachine.create_initial()` 是唯一创建入口。两者职责分开；验收按此措辞检查，不把“创建”当作状态迁移。 |
| 9 | `INVALIDATED` 守卫范围 | 纳入 WP-03；采用 7 张表（`tasks`、`nodes`、`evidence`、`evidence_invalidations`、`audit_log`、`idempotency_keys`、`schema_migrations`）+ 最小测试事实端口，走合法状态机路径 `VERIFYING → VERIFIED → INVALIDATED → READY`。测试事实端口只用于构造前置事实，不用于证明 SQLite/审计/事务；测试报告必须标明。证据与冻结审计的测试种子通过受控的私有 capability 写入，不暴露为生产公开入口。 |
| 10 | `AUDIT_WRITE_FAILED` | 只作为 DENIED 审计二次失败时结构化 stderr 的内部标记，不是 HTTP API 错误码；API 仍只使用 06 §4.4 的 13 个冻结错误码，不新增第 14 码。 |
| 11 | 测试环境口径 | workspace-write 为主；若因 `BLK-003` 在 setUp/临时目录阶段失败，先如实记录；如需 full-access 补充，必须单独取得用户批准，并与 workspace-write 结果分开标注。不得把 full-access 结果写成 workspace-write 通过。 |
| 12 | JCS | 本轮切换为 RFC 8785 JCS；`canonical_bytes()` / `hash_payload()` 用于请求哈希；现有 WP-02 内存幂等键不保留，无历史键迁移负担。 |
| 13 | 运行时 DB 路径 | 允许环境变量 `RESEARCHFLOW_DB_PATH` 注入；默认 `runtime/researchflow.db`（`/runtime/` 已在 `.gitignore`）；测试使用 `tmp_path`；不新增契约字段，不在代码中写死用户目录。 |
| 14 | 触发器/额外 CHECK | 允许作为实现层旁路防护：只追加触发器、状态更新必须带同事务 OK 审计的触发器、额外状态/哈希/UTC 形态 CHECK。列定义以 06 §1.3 为基线；触发器与额外 CHECK 在 Step 1 计划中单列，不视为修改冻结件。 |
| 15 | `schema_migrations` 基线 | 按 06 §5 与 M02 的 `(version, applied_at, checksum)` 设计；不强行归入 06 §1.3 五表。 |
| 16 | P3–P10 阅读边界 | WP-03 只读 M02（P2）+ 05/06/07/ADR + 现有代码/测试；不读取 P3–P10 的实现文件作为输入。 |

## 2. 对前置条件的影响

- §11.3 第 3 条：由本文件第 1–5 项裁决满足（用户书面裁决载体）。
- §11.3 第 4 条：由第 6 项满足（P9/P10 保持 `BLOCKED`，不作为 WP-03 输入）。
- §11.3 第 6 条：用户已下达 WP-03 指令；本文件只授权 Step 0 复核与 Step 1 计划/diff，代码实施仍需 Step 1 书面批准。
- `BLK-003` 仍 `OPEN`，本文件不改变其状态。
- 本文件不修改 `project_state.json`；状态更新只能在真实测试完成后进行。

## 3. Step 1 计划新增事项（已于 2026-11-12 批准）

以下事项由用户在 Step 1 批准（2026-11-12）：

1. **`GET /api/v1/tasks/{id}` 的 `spec` 字段存储方式**：用户选择 **A**——在 `tasks` 增加 `task_spec_json TEXT NOT NULL`，保留现有 GET `spec` 结构；这是对 06 §1.3 的单列偏离。
2. **测试种子路径**：`evidence` / `evidence_invalidations` / `RECOVERY_PLAN_FROZEN` 审计的测试前置数据使用受控私有 capability 写入；该路径不暴露为生产公开入口。
3. **`RESEARCHFLOW_DB_PATH` 的默认值与启动迁移**：已按 app lifespan 执行迁移、失败拒绝启动/`readyz` 503 实施；默认 `runtime/researchflow.db`。
4. **full-access 补充测试**：已按 11B 在 workspace-write 受阻后执行一次受控 full-access 补充；结果与 workspace-write 分开记录。

## 4. 补充口径：错误码分层

- API 仍只使用 06 §4.4 的 **13 个冻结错误码**，不新增第 14 个。
- `PLAN_HASH_MISMATCH`、`ENV_FINGERPRINT_MISMATCH`、`EVIDENCE_CHAIN_BROKEN`、`AUDIT_WRITE_FAILED` 作为**内部 domain code**，可出现在 `StateTransitionDenied.error_code`、测试断言或结构化 stderr 中；不是 HTTP API 错误码。
- HTTP 层（如果将来暴露迁移端点）对内部 domain code 统一映射为 409 `STATE_TRANSITION_DENIED`；`SIGNATURE_INVALID` 等已在 13 码内的按 06 映射。
- 负例测试至少断言 `api_error_code` + `reason`；计划守卫额外断言 `plan_id`/`plan_hash` 或 `field_path`。

## 5. Step 1 批准与实施记录

- 2026-11-12：用户选择 `tasks.task_spec_json` **方案 A**（保留现有 GET `spec`），并批准 [`01_step1_plan.md`](01_step1_plan.md) 进入 Phase 1–4。
- 实施结果：定向 `87 passed`；全量 `217 passed`（`danger-full-access` 补充运行；workspace-write 因 `BLK-003` 在 `tmp_path` setup 阶段失败，未写成通过）。
- `T-WP-03-001` 已登记为 `IN_REVIEW`，等待用户验收；未 commit。

## 6. 范围代价确认

- `00_decisions.md` 第 9 项（9A）把 `evidence` 与 `evidence_invalidations` 纳入 WP-03，实际建 **7 张表**，不是原计划的“五表”。
- 该扩表只用于 `VERIFIED → INVALIDATED → READY` 的合法路径与 FK 完整性；WP-03 不实现 Collector/Verifier/Gate 的生产写入逻辑。
- 若在 Step 1 批准时决定控制范围，可改为 9C：拆到后续 WP，WP-03 验收清单相应标“未实现/未测”。