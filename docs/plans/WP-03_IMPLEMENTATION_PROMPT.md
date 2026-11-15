# WP-03 实施提示词（v0.1，待前置裁决后使用）

> 使用方式：把下面整段交给执行 Agent。**前置条件未满足时，执行 Agent 必须停止，不得先写代码。**
> 配套方案：`docs/plans/WP-03_IMPLEMENTATION_PLAN.md`
> 设计验收：`reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`

---

## 任务提示词

【背景】

项目：ResearchFlow 3.1（T0 阶段，Windows 11 单机，CPU-only）。
当前事实：
- G0 已于 2026-11-10 由用户宣布 PASS；`T-WP-01-001`、`T-WP-02-001` 为 DONE。
- P1–P8 伪代码设计件已于 2026-11-12 验收（`ACCEPTED`，仅设计件）；P9/P10 仍 `BLOCKED`。
- P2 设计件已验收，但 P2 的 `§12-2`、`§12-6`、`§12-7`、`§12-8` 仍 OPEN；WP-03 不得以 P2 已验收为由启动。
- 当前业务代码只有 `researchflow/contracts/` 与 `researchflow/api/`；`researchflow/api/app.py` 的 `_EphemeralTaskRegistry` 是 WP-02 存根，不是状态机。
- 工作区有大量未提交变更；不得自动 commit。
- WP-03 只依赖 P2 设计件；P3–P8 的设计验收不等于实现授权，P7/P8 属 T1、P9/P10 属 T2/未授权，均不得作为 WP-03 输入。

【目标】

实现 T0 WP-03：SQLite 迁移、`StateMachine.transition()` 唯一写入口、成功同事务 `OK` 审计、失败独立事务 `DENIED` 审计、旁路写拒绝、`INVALIDATED → READY` 三条件守卫、幂等创建，并把 API 从临时内存注册表切换到 SQLite 持久层；用真实测试与日志证明。

【事实来源（必须读取，按顺序）】

1. `AGENTS.md` §0–§9。
2. `docs/state/project_state.json`（当前阶段、P2–P8 状态、P9/P10 阻塞、`last_verified_commit`）。
3. `docs/SESSION_HANDOFF.md` 最新条目。
4. `docs/DEVELOPMENT_WORKFLOW.md` §11.3（WP-03 进入条件）。
5. `docs/design/05_CONTRACTS_AND_STATES.md` §9（Task/Node 迁移、I-01–I-14、§9.7 参数与失败审计）。
6. `docs/design/06_DATA_AND_API.md` §1–§5（DDL、事务边界、写权限、错误码、幂等、启动守卫）。
7. `docs/design/07_T0_PLAN_AND_GATES.md` §2.3（WP-03 目标/出口/证据）。
8. `docs/ADR/ADR-005-failed-transition-audit.md`、`docs/ADR/ADR-001-invalidated-node-state.md`、`docs/ADR/ADR-004-t0-recovery-boundary.md`。
9. `design/pseudocode/M02_state_machine/MODULE.md`、`NEGATIVE_TESTS.md`（设计参考，**不是可运行代码**）。
10. `docs/plans/WP-03_IMPLEMENTATION_PLAN.md`。
11. `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`。

【前置条件（逐条核对；任一未满足，停止并报告）】

1. `§12-2`、`§12-6`、`§12-7`、`§12-8` 已在 M02 `DECISIONS`/ADR 或用户书面裁决中明确；若仍是 OPEN，停止，不写代码。
2. 用户已明确下达 WP-03 指令；仅有“可以开始吗”或“出方案”不构成开工令。
3. P9/P10 已由用户处置，且明确不作为 WP-03 输入；P9 仍是 `BLOCKED` 时，不得读取其 `.py` 作为实现来源。
4. `BLK-003` 仍为 OPEN；不得把 full-access 测试结果写成 workspace-write 通过。
5. 已确认解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（3.11.16 / 64bit）；不得用 PATH 上的 `python` 或 `py -3.11`。
6. 已确认当前分支、HEAD、未提交变更；未获用户批准不得 commit。

【允许修改】

- `researchflow/persistence/**`（新增）
- `researchflow/orchestration/**`（新增）
- `researchflow/contracts/encoding.py`、`researchflow/contracts/errors.py`（新增）
- `researchflow/api/app.py`（替换临时注册表，保留现有 HTTP 契约）
- `tests/test_persistence_migrations.py`、`tests/test_state_machine.py`、`tests/test_audit_dual_transaction.py`、`tests/test_direct_write_guard.py`、`tests/test_invalidated_guard.py`、`tests/test_idempotency_sqlite.py`、`tests/test_jcs.py`、`tests/test_api_sqlite.py`（新增）
- `tests/test_api_422.py`、`tests/test_api_idempotency.py`（仅必要适配，不得降低断言强度）
- `docs/verification/t0/wp-03/**`（证据日志）
- `docs/state/project_state.json`（仅在真实测试完成后新增/更新 `T-WP-03-001`）
- `docs/CHANGELOG_DEV.md`、`docs/SESSION_HANDOFF.md`（收尾）

【禁止修改 / 禁止动作】

- 禁止修改 `contracts/**`、`docs/design/**`、`docs/ADR/**`、`docs/PRD/**`、`docs/G0/**`；冻结件只读。
- 禁止修改 `design/pseudocode/**` 来迁就实现；伪代码只作设计参考。
- 禁止把 P9/P10 产物作为 WP-03 输入；禁止把 P9 并发重写文件当原始设计。
- 禁止把研发看板状态（`IN_REVIEW`/`DONE` 等）写入运行时数据库。
- 禁止 Agent/API 直接写 Task/Node 状态；必须经 `StateMachine.transition()`。
- 禁止为通过测试修改 expected result、负例样本、阈值或日志。
- 禁止新增依赖、联网、改系统配置、读取密钥/`.credentials.yaml`、commit。
- 禁止用 mock、内存库替身或“只断言抛异常”证明事务/审计/直接写库拒绝。
- 禁止把 `DENIED` 审计写进已回滚的事务；禁止静默吞掉审计二次失败。

【执行步骤】

Step 0：只读核对
- 逐条核对前置条件；输出“满足/不满足”表。
- 只读探索现有 `researchflow/contracts/`、`researchflow/api/app.py`、`tests/`、`conftest.py`。
- 复核 `05`、`06`、`07`、`ADR-005`、M02 设计；列出与现有代码的差异。
- 若发现前置条件不满足、冻结件冲突或需要新增状态，停止并报告。

Step 1：输出计划与 diff 计划（不写代码）
- 文件清单（新增/修改/不改）、接口、数据流、迁移、错误处理、测试、回滚。
- 明确 WP-03 最小切片：哪些迁移/守卫在 WP-03 实现，哪些依赖后续 WP（端口缺失 fail-closed）。
- 明确 JCS 请求哈希与现有 `json.dumps(sort_keys=True)` 的差异及切换方式。
- 明确 API 如何注入 SQLite 服务、如何保留 201/409/422/404。
- 等待用户批准；未批准不得进入 Step 2。

Step 2：按 Phase 1–4 实施（最小变更）
- Phase 1：JCS + 错误码 + 五表 DDL + 迁移；先跑迁移测试。
- Phase 2：仓储 + `create_initial()` + 幂等；切换 API；跑 API 回归。
- Phase 3：迁移表 + `transition()`；每条拒绝断言错误码/reason。
- Phase 4：双事务审计 + 旁路防护 + 降级；真实 SQLite 负例。
- Phase 5（可选，需批准）：`INVALIDATED` 守卫、最小重启恢复。
- 每 Phase 结束运行定向测试；失败先定位，不调整 expected。

Step 3：全量验证
- 运行定向测试与全量 `pytest`；记录解释器、命令、退出码、测试数、日志路径。
- 若 workspace-write 下受 `BLK-003` 影响，如实记录；不得用 full-access 结果冒充通过。
- 生成 `docs/verification/t0/wp-03/` 证据。

Step 4：收尾
- 仅按真实结果更新 `project_state.json`（新增 `T-WP-03-001`，状态按证据；未完成项标 `IN_REVIEW`/`BLOCKED`）。
- 运行 `state_sync.py validate|render|check`（使用 `.venv` 解释器）。
- 追加 `CHANGELOG_DEV.md`、更新 `SESSION_HANDOFF.md`；不 commit。

【测试与证据】

解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（3.11.16 / 64bit）。

建议命令（按实际文件调整）：
```powershell
& .venv/Scripts/python.exe -m pytest tests/test_persistence_migrations.py -q -p no:cacheprovider
& .venv/Scripts/python.exe -m pytest tests/test_state_machine.py -q -p no:cacheprovider
& .venv/Scripts/python.exe -m pytest tests/test_audit_dual_transaction.py -q -p no:cacheprovider
& .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider
& .venv/Scripts/python.exe scripts/state_sync.py validate
& .venv/Scripts/python.exe scripts/state_sync.py render
& .venv/Scripts/python.exe scripts/state_sync.py check
```

证据至少包含：
- `docs/verification/t0/wp-03/transitions.jsonl`
- `docs/verification/t0/wp-03/illegal.log`
- `docs/verification/t0/wp-03/direct_write.log`
- `docs/verification/t0/wp-03/audit_log.jsonl`
- `docs/verification/t0/wp-03/denied_survives_rollback.log`
- `docs/verification/t0/wp-03/audit_degraded_stderr.log`
- `docs/verification/t0/wp-03/invalidated_guard.log`
- 全量 pytest 日志

【交付格式】

1. 前置条件核对表（满足/不满足）。
2. 实施计划与 diff 清单（Step 1 先交）。
3. 文件变更清单（新增/修改/未改）。
4. 测试命令、解释器、退出码、测试数、失败数、日志路径。
5. 证据路径与关键输出摘要。
6. 风险与未完成项（明确标“未实现/未测/待核实”）。
7. 状态变更说明（`T-WP-03-001`、`last_verified_commit` 是否变化）。
8. commit 状态：明确“未 commit”。

【停止条件】

- §12-2/§12-6/§12-7/§12-8 未裁决，或用户未下达 WP-03 指令。
- 需要修改冻结契约/05/06/ADR/PRD/G0，或需要新增状态/错误码。
- 需要新增依赖、联网、改系统配置、读取凭据。
- 测试失败原因未定位，或需要改 expected/阈值才能通过。
- 发现直接写库无法阻止，或 `DENIED` 审计二次失败被静默吞掉。
- 发现 P9/P10 产物被当作 WP-03 输入。
- `BLK-003` 被误写成已关闭。

【验收清单（逐项打勾）】

- [ ] 五表 DDL 与 06 §1.3 逐列一致；迁移可重复、失败全回滚。
- [ ] `transition()` 是唯一公开写入口；仓储无裸 update。
- [ ] 合法迁移成功且同事务写 `audit_log(OK)`。
- [ ] 非法迁移/旁路写库被拒，且拒绝原因正确。
- [ ] 失败迁移回滚后 `DENIED` 仍存在（真实 SQLite）。
- [ ] 审计二次失败写结构化 stderr，测试捕获。
- [ ] `INVALIDATED → READY` 三条件守卫各失败一次。
- [ ] 同键同体 201、同键异体 409；无重复任务。
- [ ] JCS 键序/astral 字符测试通过。
- [ ] API 201/409/422/404 回归通过。
- [ ] 全量 pytest 通过，日志与证据齐全。
- [ ] 未改冻结件、未 commit、未把 P9/P10 当输入。