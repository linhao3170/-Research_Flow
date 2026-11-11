# architecture-decisions.md — 稳定架构约束与 ADR 索引

> 更新时间：2026-11-08（阶段 7；阶段 8 复核）
> 核验状态：部分核验。14 条不可协商约束已与用户阶段 4 指令逐条核对；证据等级、Gate 与状态机摘要摘自策划书**内部 v4.3.0**（文件名标签 v4.3.1；`BLK-002` 已关闭）§6.2、§7.1、§7.2 与附录 F。
> 重要边界：G0 规格冻结已由用户 2026-11-10 裁决；契约见 `contracts/` 与 `docs/design/`。本文件记录的是已批准的原则与约束。
> 阶段 7 补充：新增 [`ARCHITECTURE.md`](../ARCHITECTURE.md)、[`SECURITY_POLICY.md`](../SECURITY_POLICY.md) 等知识文档；**无运行时架构变化**，不新增 ADR。

当前状态以 docs/state/project_state.json 为准。

## 1. 不可协商的架构约束

1. `StateMachine` 是 ResearchFlow 运行时状态迁移的唯一入口。
2. Agent/LLM 不得直接写 Task/Node 状态。
3. Agent/LLM 不得直接写 Evidence Store、VerificationReport、CompletionCertificate 或私钥。
4. Executor 只负责执行，不裁决成功。
5. Collector 是 E0/E1/E2 事件的受控记录者；E2 必须来自真实受控执行观测。
6. Verifier 独立执行 L1/L2/L3，产生 E3 并签发报告/凭证。
7. Harness 轨迹默认是 E1，不自动等于 E2。
8. E0/E1 不得单独满足执行类必检项。
9. L3 必须在新目录、独立进程中，从原始数据真实重新训练/推理。
10. 只有报告 `VERIFIED`、必检证据完整、签名/信任锚有效且规定 L3 覆盖满足时，才允许签发 `CompletionCertificate`。
11. `verify_bundle.py` 必须独立于数据库和模型运行。
12. 哈希链只能表述为“可发现篡改”，不得声称绝对不可篡改。
13. k 次 bit-exact 只能作为限定条件下的经验资格，不得宣称数学确定性证明。
14. 无有效 DC 不得 SPA 跳过；随机性或副作用节点不签 DC。

补充边界：

- Executor 与 Verifier 使用分离的工作目录；Verifier 不得复用 Executor 的进程内状态作为独立证据。
- 离线验签必须使用外部可信指纹 / 信任锚，不得只信任证据包自带的公钥。
- 未达到门禁条件时，只能报告缺口、`PARTIAL`、`FAILED` 或 `BLOCKED`，不得用文字描述替代结构化证据。

## 2. 五条架构原则（策划书内部 v4.3.0 §5.1；文件名标签 v4.3.1，`BLK-002` 已关闭）

| 原则 | 设计要求 | 代码保证方向 |
|---|---|---|
| 写入者隔离 | LLM Agent 无状态库、证据目录与私钥写权限 | Agent 只经 Tool Gateway；权限拒绝测试 |
| 状态单入口 | 节点状态只能由 `StateMachine.transition()` 改变 | 无公开 setter；每次迁移写 `audit_log` |
| 执行与判定分离 | Executor 只执行；Collector 只记录；Verifier 才判定 / 签发 | 独立进程、独立工作目录与文件权限 |
| 证据与声明分离 | E0 声明不能推动状态 | Gate 只读取结构化证据和规则 |
| 外部可复核 | 证据包离开数据库和模型仍可验签 | `verify_bundle.py` 离线运行，正负例齐全 |

## 3. 证据等级（E0–E3）

| 等级 | 来源 | 写入者 | 状态作用 |
|---|---|---|---|
| E0 | Agent 声明 | Collector 捕获，标记 `agent_claim` | 永不单独推动状态 |
| E1 | 工具调用、Harness 轨迹、知识检索 | Collector | 辅助证明请求 / 轨迹，不等于真实执行 |
| E2 | 受控 Executor 进程和产物观测 | Collector 监听执行事件 | 可覆盖执行类必检项；依赖信任边界 |
| E3 | Verifier 新目录重算或重执行 | 独立 Verifier | 最高等级；关键指标节点必须满足 L3 |

E2 的典型内容：PID / attempt、退出码、stdout/stderr 摘要、耗时、资源峰值、产物 SHA-256、环境指纹。

## 4. Gate 与凭证规则

- 每个 Domain Pack 声明 `RequiredChecks`；Gate 为每项生成 coverage row，至少包含：`required_check_id`、`evidence_ids`、`level`、`producer`、`hash_status`、`l3_status`、`result`。
- 任何必检项缺失、哈希不一致、规则版本不匹配或冲突未解释，均不能 `VERIFIED`。
- Gate 顺序：Schema / 版本校验 → 事件顺序与哈希链校验 → 产物哈希与生产者校验 → 必检覆盖矩阵 → 未解释冲突拒绝 → 执行类必检项要求 E2/E3 → 指标来源节点要求 L3 / IRC → 全部通过才 PASS，否则输出 GAP。
- `VerificationReport` 四态：`VERIFIED`、`PARTIAL`、`FAILED`、`BLOCKED`。
- `CompletionCertificate` 只允许由 `VERIFIED` 报告生成；`PARTIAL` 映射为节点 `BLOCKED`，不能签发凭证。
- 签名载荷必须包含规则版本、证据根和状态；私钥不得进入 Git、日志、证据包或前端。

## 5. 状态机边界

ResearchFlow 运行时至少包含四类状态：

1. Task 状态机；
2. Node 状态机；
3. VerificationReport 状态机；
4. CompletionCertificate 状态机。

Task / Node 的完整状态词汇、允许迁移与不变量见 [`docs/state/runtime_states.md`](../state/runtime_states.md)。研发看板状态（`BACKLOG`…`DEFERRED`）只用于 `project_state.json`，与运行时状态严格分离，不得合并、改名或替代。

## 6. ADR 索引

ADR 共 7 份（ADR-001–007 + README），见 `docs/ADR/README.md`。

阶段 4 的变更性质：新增项目记忆、研发状态同步脚本与测试；**无 ResearchFlow 运行时架构变化**，因此不新增 ADR。

阶段 7 的变更性质：新增资料接手、来源登记、冲突报告与知识文档；**无 ResearchFlow 运行时架构变化**，不新增 ADR。版本基线冲突（`BLK-002`）已由用户 2026-11-08 决议关闭（内部 v4.3.0 为内容基线，v4.3.1 仅为文件名标签），不属于架构决策。

ADR 规则（G0 后）：

- 命名建议：`ADR-0001-<short-title>.md`。
- 必填内容：背景、决策、备选方案、后果、状态、证据/验证方式、评审人。
- 状态至少区分：`PROPOSED`、`ACCEPTED`、`SUPERSEDED`、`REJECTED`。
- 未记录 ADR 的架构变更视为未批准。
- 已冻结架构不得擅自修改；变更必须先提交方案与 diff 计划。

## 7. G0 前未冻结事项（已由 contracts/ 冻结）

以下为 G0 前未冻结事项的历史记录；相关契约已由 `contracts/` 与 `docs/design/` 冻结。

- Task / Node / Evidence / Report / Certificate 的完整 JSON Schema；
- REST API 路径、请求/响应字段与错误码表；
- 数据库表结构、索引、迁移策略；
- `gates.yaml`、`limits.yaml`、`security.yaml` 等配置的最终字段；
- 规则版本命名与哈希口径；
- 信任锚、密钥轮换与撤销的具体实现。

## 8. 相关文件

- [`AGENTS.md`](../../AGENTS.md)
- [`docs/memory/project-context.md`](project-context.md)
- [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)
- [`docs/SECURITY_POLICY.md`](../SECURITY_POLICY.md)
- [`docs/state/runtime_states.md`](../state/runtime_states.md)
- [`docs/reference/CONFLICT_REPORT.md`](../reference/CONFLICT_REPORT.md)
- [`docs/memory/references.md`](references.md)
