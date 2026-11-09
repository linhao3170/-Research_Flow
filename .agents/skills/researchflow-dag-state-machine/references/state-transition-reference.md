# 状态迁移参考

> 规范性来源：`docs/state/runtime_states.md` 与冻结后的契约。本文件只提供检查清单，不新增状态或迁移。
> 禁止把本文件中的示例当成已冻结迁移表。

## 1. 状态词汇

### Task

`CREATED`、`PLANNING`、`READY`、`RUNNING`、`VERIFYING`、`COMPLETED`、`FAILED`、`BLOCKED`、`CANCELLED`。

### Node

`PLANNED`、`READY`、`RUNNING`、`VERIFYING`、`VERIFIED`、`FAILED`、`BLOCKED`、`DIAGNOSING`、`RECOVERING`。

### 研发看板（禁止混用）

`BACKLOG`、`READY`、`IN_PROGRESS`、`BLOCKED`、`IN_REVIEW`、`DONE`、`DEFERRED`。

## 2. 迁移请求必填

| 字段 | 说明 |
|---|---|
| `previous_state` | 调用者认为的当前状态；必须与存储一致 |
| `next_state` | 目标状态 |
| `actor` | 发起者身份/组件 |
| `reason_code` | 稳定原因码 |
| `rule_version` | 规则版本 |
| `correlation_id` | 关联任务/节点/attempt/事件 |

可选但建议：`task_id`、`node_id`、`attempt_id`、`evidence_ids`、`message`、`occurred_at`。

## 3. 审计日志字段

| 字段 | 要求 |
|---|---|
| `audit_id` | 唯一 |
| `entity_type` / `entity_id` | Task/Node 等 |
| `previous_state` / `next_state` | 实际值 |
| `actor` | 谁发起 |
| `reason_code` | 为什么 |
| `rule_version` | 哪版规则 |
| `correlation_id` | 关联链 |
| `result` | `ACCEPTED` / `REJECTED` |
| `error_code` | 拒绝原因（如适用） |
| `occurred_at` | 带时区时间 |

成功和失败都必须写；失败不得只写应用日志。

## 4. 守卫检查

- [ ] 当前状态与 `previous_state` 一致
- [ ] `previous_state → next_state` 在允许迁移内
- [ ] 依赖节点满足
- [ ] 执行已结束（进入最终验证前）
- [ ] 必检证据/报告状态满足
- [ ] Task COMPLETED 有 VERIFIED 报告 + 有效证书
- [ ] `rule_version` 匹配
- [ ] 调用者有权发起该迁移
- [ ] 无并发竞态（版本号/事务）

## 5. DAG 检查

- 拓扑排序成功；无环。
- 所有依赖引用存在；无自依赖。
- 无孤立节点（除明确允许的根/叶）。
- 图版本与节点版本一致。
- 重复边、跨任务引用、已删除节点有处理。
- 上游输入/参数/代码/环境变化时，下游按规则失效。

## 6. 重启恢复

1. 扫描未完成 attempt。
2. 不把 `RUNNING` 默认改 `COMPLETED`。
3. 校验 PID/进程、工作目录、产物、退出码、证据。
4. 可恢复 → `RECOVERING`/重试；不可恢复 → `FAILED`/`BLOCKED`。
5. 记录恢复决策与审计。
6. 未完成 attempt 不得复用为成功证据。

## 7. 负例清单

- 伪造 `previous_state`。
- 跳过中间状态。
- 依赖未满足直接 READY。
- 执行未结束进入 VERIFYING/COMPLETED。
- 无 VERIFIED 报告/证书标 COMPLETED。
- 直接 SQL/ORM 更新状态。
- 重启把 RUNNING 改 COMPLETED。
- 缺 `rule_version`/`correlation_id`。
- 失败迁移不写审计。
