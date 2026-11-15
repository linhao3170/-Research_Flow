# WP-03 验收记录（2026-11-14）

> 结论：`T-WP-03-001` 由 `IN_REVIEW` 转 `DONE`。
> 依据：真实实现 + 2026-11-14 复测；不改变 2026-11-12 的历史结论，也不改写 full-access/workspace-write 的区分。

## 1. 复测证据

| 项 | 结果 | 日志 |
|---|---|---|
| 定向用例（10 个文件） | **87 passed**，exit 0，9.97s | [pytest_targeted_2026-11-14.log](pytest_targeted_2026-11-14.log) |
| 全量用例 | **217 passed**，exit 0，16.17s | [pytest_full_2026-11-14.log](pytest_full_2026-11-14.log) |
| 解释器 | `.venv/Scripts/python.exe`，3.11.16，64bit | 日志尾行已记录 |
| 权限与会话 | `danger-full-access`（审批不再询问） | 日志尾行已记录 |

## 2. 验收标准逐条核对

| 验收标准 | 核对结果 |
|---|---|
| 7 表 DDL 与已批准偏离 | 通过；0001 未改动，后续 WP 以 0002/0003 只向前扩展 |
| 迁移可重复、checksum fail-closed、失败全回滚 | 通过（`tests/test_persistence_migrations.py`） |
| `StateMachine.transition()` 唯一状态写入口、`create_initial()` 唯一创建入口 | 通过（`tests/test_state_machine.py`、`test_direct_write_guard.py`） |
| 成功同事务 `OK` 审计；失败独立事务 `DENIED`；二次失败 stderr 降级 | 通过（`tests/test_audit_dual_transaction.py`） |
| 直接 SQL 状态写入被触发器拒绝 | 通过（断言触发器名与目标行状态不变） |
| `INVALIDATED → READY` 三条件守卫 | 通过（`tests/test_invalidated_guard.py`；本 Goal 又在 `tests/t0/test_wp_recovery.py` 对三条守卫做端到端复验） |
| JCS 向量、幂等 201/409、未带 key 创建 | 通过 |
| API 201/409/422/404、GET 重启后读取、`/recover` 404 | 通过 |
| 不修改冻结件、不把 P9/P10 当输入、未 commit | 保持 |
| `BLK-003` | 仍 `OPEN`；本次结果不写成 workspace-write 通过 |

## 3. 与后续工作包的衔接

- WP-04 起在同一 SQLite 上新增 `graph_versions/reports/certificates/ingestion_log`（迁移 0002）并扩展审计动作（0003）；0001 的语句与 checksum 均未修改。
- WP-03 的 `Ports` 测试替身只用于 WP-03 单元测试；T0 闭环出口使用 `researchflow/orchestration/sqlite_ports.py` 的生产端口（真实 DB / attempt 目录 / 密钥库）。
- 本次转 DONE 只代表 WP-03 合同范围，并**不**代表 G1/G2/G3 或 T0 全部出口自动通过。