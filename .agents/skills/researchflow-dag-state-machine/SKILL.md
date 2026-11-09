---
name: researchflow-dag-state-machine
description: Use when designing or modifying DAG validation, task/node lifecycle, StateMachine transitions, scheduling readiness, dependency invalidation, or recovery state flow.
---

# ResearchFlow DAG and State Machine

## 1. 适用条件 / When to use

在以下情况使用：

- 设计或修改 DAG 校验、任务/节点生命周期、调度就绪判断、依赖失效、恢复流程。
- 需要新增或审查 `StateMachine.transition()`、迁移规则、审计日志。
- 需要判断某个状态变更是否合法、是否应写入 `audit_log`。
- 需要处理重启后未完成 attempt、RUNNING 节点恢复、失败重试。

不用于：直接修改运行时状态、绕过 Gate 或 Verifier、把研发看板状态当运行时状态。

## 2. 输入与前置检查

1. 已读取 `docs/state/runtime_states.md`，确认 Task / Node / Report / Certificate 的状态与迁移。
2. 已确认当前契约版本、规则版本 `rule_version`、DAG 图版本。
3. 已确认调用者 `actor`、原因码 `reason_code`、关联 ID `correlation_id`。
4. 已确认目标状态是否允许从当前状态迁移；不允许时不得“先写再补审计”。
5. 已确认是否存在未完成 attempt、依赖节点、上游输入/参数/代码/环境变化。
6. 已确认这是运行时状态，不是 `project_state.json` 的研发看板状态。

若 `runtime_states.md` 与冻结契约冲突，以冻结契约为准并停止；不得自行选择。

## 3. 执行步骤

1. **建模状态与事件**：列出 Task/Node 状态、事件、守卫条件、副作用。
2. **定义唯一入口**：所有运行时状态变更必须经 `StateMachine.transition()`；其他模块只提交迁移请求。
3. **校验迁移参数**：`previous_state`、`next_state`、`actor`、`reason_code`、`rule_version`、`correlation_id` 缺一不可。
4. **校验前置状态**：从数据库/状态存储读取当前状态，拒绝过期或伪造的 `previous_state`。
5. **校验业务守卫**：依赖是否满足、执行是否结束、证据是否 VERIFIED、证书是否有效。
6. **写审计日志**：成功和失败都写 `audit_log`；记录前后状态、actor、原因码、规则版本、关联 ID、时间、结果。
7. **DAG 校验**：拓扑排序、环检测、孤立节点、依赖引用存在性、图版本、重复边、跨任务引用。
8. **就绪判定**：只有依赖满足、输入可用、资源允许时才进入 READY；不得提前 READY。
9. **失效传播**：上游输入/参数/代码/环境变化时，按规则使下游失效；记录失效原因与范围。
10. **恢复处理**：重启后扫描未完成 attempt；RUNNING 不得默认改 COMPLETED；按规则进入 FAILED/BLOCKED/DIAGNOSING/RECOVERING。
11. **完成判定**：Task COMPLETED 必须有 VERIFIED 报告和有效 CompletionCertificate；缺少则拒绝。
12. **写正反例测试**：非法迁移、直接写状态、依赖未满足、重启恢复、失效传播。

## 4. 不可违反的约束

- `StateMachine.transition()` 是运行时 Task/Node 状态变更的唯一入口。
- 禁止其他模块公开 setter，禁止直接 SQL 更新运行时状态。
- 每次成功或失败迁移都必须写 `audit_log`，不得只记录成功。
- 依赖未满足的节点不得进入 READY。
- 执行未结束不得进入最终验证。
- Task COMPLETED 必须有 VERIFIED 报告和有效 CompletionCertificate。
- 重启后不得把 RUNNING 默认改成 COMPLETED；必须校验 attempt 与证据。
- 不得混淆研发看板状态与运行时状态。
- 不得用自然语言声明替代结构化迁移参数或审计记录。
- 不得为“修复卡住的任务”手工改库；必须通过合法迁移和恢复流程。

## 5. 输出要求

至少交付：

1. **迁移表**：from → to、事件、守卫、副作用、审计字段。
2. **DAG 规则**：拓扑、环、孤立节点、依赖引用、图版本、失效传播。
3. **状态审计说明**：`audit_log` 字段、成功/失败记录、查询方式。
4. **恢复流程**：重启扫描、未完成 attempt、RUNNING 处理、重试/阻塞。
5. **正反例测试**：合法迁移、非法迁移、直接写状态、依赖未满足、重启恢复。
6. **与研发看板的边界说明**：哪些字段属于运行时，哪些属于 `project_state.json`。

## 6. 验收标准

- 非法迁移被拒绝，且失败也写审计。
- 直接写状态（setter/SQL/ORM 更新）被测试阻止或静态检查发现。
- 依赖未满足时节点不会 READY。
- 执行未结束时不会进入最终验证。
- Task COMPLETED 缺少 VERIFIED 报告或证书时被拒绝。
- 重启恢复不会伪造完成，RUNNING 有明确处理结果。
- 上游变化能使下游按规则失效，并有测试。
- 迁移参数缺字段时被拒绝。

## 7. 相关文件 / 参考资料

- `AGENTS.md`
- `docs/state/runtime_states.md`
- `docs/memory/architecture-decisions.md`
- 策划书 v4.3.1 第 5、6 章及附录 F
- `references/state-transition-reference.md`

## 8. 失败与暂停条件

- `runtime_states.md` 与冻结契约冲突。
- 需要新增状态或改变迁移语义但未获批准。
- 数据库现状与状态机不一致，无法判断真实状态。
- 迁移缺少 `rule_version` 或 `correlation_id`。
- 需要绕过 Gate/Verifier 才能继续。
- 重启后发现 RUNNING 节点的证据不完整，无法安全恢复。
- 有人要求直接改库、删审计或伪造 COMPLETED。

暂停时报告：冲突状态、涉及节点、已有证据、可选合法迁移、需要用户决定的问题。
