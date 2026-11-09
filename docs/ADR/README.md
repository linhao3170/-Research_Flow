# ADR 索引

> 架构决策记录（ADR）。每条决策独立成文件，编号不复用；`ACCEPTED` 才具有约束力，`PROPOSED` 不构成实现授权。
> 与 ⑧ 的关系：`docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md` §4 是登记表，本目录是正式文件；两者冲突时以用户书面决议为准并立即报告。

| 编号 | 标题 | 状态 | 文件 |
|---|---|---|---|
| `ADR-001` | Node 增加 `INVALIDATED` 状态（FR-010 T0 最小切片） | ACCEPTED（2026-11-08） | [ADR-001-invalidated-node-state.md](ADR-001-invalidated-node-state.md) |
| `ADR-002` | `dataset_ref` 统一为对象形态（偏离附录 E.1 字符串样例） | ACCEPTED（2026-11-09） | [ADR-002-dataset-ref-object.md](ADR-002-dataset-ref-object.md) |
| `ADR-003` | 为三个契约补 `schema_version`、为证书补 `issued_at` | ACCEPTED（2026-11-09） | [ADR-003-schema-version-and-issued-at.md](ADR-003-schema-version-and-issued-at.md) |
| `ADR-004` | T0 恢复边界：内部不可变计划 + 控制事件不入 E0–E3 + 不复用 Recovery 状态机 | ACCEPTED（2026-11-09） | [ADR-004-t0-recovery-boundary.md](ADR-004-t0-recovery-boundary.md) |
| `ADR-005` | 失败迁移的审计写入语义 | ACCEPTED（2026-11-09） | [ADR-005-failed-transition-audit.md](ADR-005-failed-transition-audit.md) |
| `ADR-006` | T0 API 面与回环免认证 + 启动守卫 | ACCEPTED（2026-11-09） | [ADR-006-t0-api-and-loopback-auth.md](ADR-006-t0-api-and-loopback-auth.md) |
| `ADR-007` | T0 最小工作台范围锁定为四视图 | **PROPOSED（WP-13 前裁决）** | [ADR-007-t0-workbench-scope.md](ADR-007-t0-workbench-scope.md) |

## 规则

1. 编号按用户指定：`ADR-002` 固定为 `dataset_ref` 对象化；其余按决议顺序顺延，不复用空号。
2. `ACCEPTED` 的决策内容不得静默修改；要改就新开 ADR 并在「取代」字段指向旧编号。
3. 每条 ADR 至少包含：背景、决策、后果、备选（未选）、验证、关联。
4. 正式 ADR 不是 G0 通过的替代品；G0 仍需用户书面批准（见 ⑧ §7）。
5. 本目录文件与 ⑧ §4 登记表必须一致；新增或改状态时两边同步。