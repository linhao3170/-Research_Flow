# M02 · NEGATIVE_TESTS — 负例判据（P2）

> 阶段：P2｜状态：**判据定义，未执行**（本阶段限权：不建环境、不跑测试、不写业务代码）
> 执行阶段：M02 落地（WP-03 之后）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P2 不得写成“已通过”**。
> 数据库：真实 SQLite 文件（WAL）；禁止用 mock、内存库替身或“只断言抛异常”代替拒绝原因。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：错误码 + `reason_code` / `field_path` / 异常类 /
   触发器名 / 审计字段中至少两项与下表一致；只断言“被拒绝”判测试失败。
2. 直接写库负例必须断言：抛出 `sqlite3.IntegrityError`（或 `DirectStateWriteDenied`）、
   消息含指定触发器/能力名、**目标行状态未变**、`audit_log` 行数未新增 OK 记录。
3. 非法迁移负例必须断言：`StateTransitionDenied` 的 `error_code`/`reason`、
   `previous_state`/`next_state`、状态未变、存在一条 `DENIED` 审计。
4. 重启负例必须断言：`RUNNING` 没有被改成 `COMPLETED`/`VERIFIED`；每个分支的
   `reason_code` 与 `BootReport.blockers`/`actions` 一致。
5. 原因不符即失败；不得改期望值、放宽阈值或用“重试通过”覆盖失败记录。
6. 本表每条只计一次；同一用例重复运行不构成独立样本。
7. 正例通过不构成完成证据；本表必须真实执行并逐条留下拒绝原因。

## A. 直接写库 / 仓储边界（8 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M02-01 | 直接 UPDATE Task 状态被拒 | 绕过 StateMachine 执行 `UPDATE tasks SET state='COMPLETED' WHERE task_id=?` | `sqlite3.IntegrityError`，消息含 `STATE_WRITE_WITHOUT_AUDIT: tasks`；`tasks.state` 仍为 `VERIFYING`；无新增 OK 审计 | schema_sql 触发器；I-01 |
| NEG-M02-02 | 直接 UPDATE Node 状态被拒 | 直接 `UPDATE nodes SET state='VERIFIED'` | `sqlite3.IntegrityError`，消息含 `STATE_WRITE_WITHOUT_AUDIT: nodes`；状态不变 | 同上 |
| NEG-M02-03 | 仓储/状态机不得多出写入口 | `hasattr(TaskRepository, "update_state")` / `"set_state"` / `"save"` / `"delete"`；`assert_single_write_entrypoint()`；`dir(StateMachine)` 的公开可调用项 | 前四项全 `False`；`assert_single_write_entrypoint()` 返回 `[]`；`StateMachine` 公开可调用项只有 `transition`；静态扫描无 `UPDATE tasks SET state` 出现在仓储公开方法中 | repositories.py；state_machine.py；05 §10 |
| NEG-M02-04 | 无 capability 不得写状态 | `TaskRepository._apply_transition(..., capability=object())` | `DirectStateWriteDenied`，`.error_code == "STATE_TRANSITION_DENIED"`，`.operation == "_apply_transition"`；行未变 | repositories.py |
| NEG-M02-05 | 错误角色 capability 不得写状态 | NodeRepository `_apply_transition(..., capability=COLLECTOR_APPEND)` | `DirectStateWriteDenied`；不得因为“都是内部对象”放行 | 同上 |
| NEG-M02-06 | 审计/证据无公开追加入口 | `hasattr(AuditRepository, "append")` / `EvidenceMetaRepository.update` | 均为 `False`；`_append` 用 `COLLECTOR_APPEND` 调用 → `DirectStateWriteDenied` | 06 §3；repositories.py |
| NEG-M02-07 | 只追加表禁止 UPDATE/DELETE | 直接 `DELETE FROM audit_log`；`UPDATE evidence SET level='E3'`；`DELETE FROM evidence_invalidations` | 三条均 `sqlite3.IntegrityError`，消息分别含 `APPEND_ONLY_TABLE: audit_log` / `evidence` / `evidence_invalidations`；行数不变 | 06 §1.2 规则 1；schema_sql 触发器 |
| NEG-M02-08 | 创建只能进入初始状态 | `INSERT INTO tasks(... state='COMPLETED')`；`INSERT INTO nodes(... state='VERIFIED')`；同状态 `UPDATE nodes SET attempt_seq=attempt_seq+1` | 分别含 `TASK_MUST_BE_INSERTED_CREATED`、`NODE_MUST_BE_INSERTED_PLANNED`、`NODE_FIELD_CHANGE_WITHOUT_STATE_TRANSITION`；行未插入/未变 | schema_sql 触发器 |

## B. 非法迁移 / 守卫不成立（10 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M02-09 | Task 非法边 | `transition(TASK, task, "RUNNING", ..., ctx.previous_state="CREATED")` | `StateTransitionDenied`，`error_code=STATE_TRANSITION_DENIED`，`reason=ILLEGAL_EDGE`，`previous_state=CREATED`，`next_state=RUNNING`；状态仍 `CREATED`；DENIED 审计存在 | 05 §9.2 |
| NEG-M02-10 | Task 不得跳步完成 | `CREATED → COMPLETED` | `reason=ILLEGAL_EDGE`；不得写 `COMPLETED`；不得签发任何证书 | 05 §9.2；I-07 |
| NEG-M02-11 | Node 不得跳过 INVALIDATED | `VERIFIED → READY` | `reason=ILLEGAL_EDGE`，`details` 含“不得跳过 INVALIDATED”；状态仍 `VERIFIED` | 05 §9.3；ADR-001 |
| NEG-M02-12 | INVALIDATED 只能回 READY | `INVALIDATED → VERIFYING` | `reason=ILLEGAL_EDGE`；状态仍 `INVALIDATED`；DENIED 审计记录计划字段（若有） | 05 §9.3；I-09 |
| NEG-M02-13 | 不得回 PLANNED | `READY → PLANNED`（以及 `RUNNING → PLANNED`） | 两条均 `reason=ILLEGAL_EDGE`；状态不变 | 05 §9.3 |
| NEG-M02-14 | Task 级 T1 撤销未授权 | `COMPLETED → INVALIDATED` / `COMPLETED → READY` | `reason=ILLEGAL_EDGE`，`details` 含 T1 revocation；状态仍 `COMPLETED` | ADR-001；T0 边界 |
| NEG-M02-15 | StateMachine 不写 Evidence | `transition(EVIDENCE, ev_id, "APPENDED", ...)` | `error_code=STATE_TRANSITION_DENIED`，`reason=OBJECT_TYPE_NOT_MANAGED`；`evidence` 行未变；无 E0–E3 审计 | 06 §3；05 §9.4 |
| NEG-M02-16 | DAG 未通过不得 READY | Task `PLANNING→READY`，`graph.dag_valid=False` 或 `graph_version=None` | `reason=DAG_INVALID`；`tasks.state` 仍 `PLANNING`；`graph_version` 仍 NULL；DENIED 审计存在 | 05 §9.2 R03 |
| NEG-M02-17 | 无 READY 节点不得启动 | Task `READY→RUNNING`，0 个节点 READY | `reason=NO_READY_NODE`；Task 仍 `READY` | 05 §9.2 R04 |
| NEG-M02-18 | attempt 未结束不得验证 | Node `RUNNING→VERIFYING`，无 `executor_process_exit`；另一例 `exit_code=1` | 第一例 `reason=ATTEMPT_NOT_ENDED`；第二例 `reason=EXIT_CODE_NONZERO`；状态仍 `RUNNING`，不得进入 VERIFYING | 05 §9.3 R09 |

## C. VERIFIED 越权 / 证书（12 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M02-19 | 无 Gate PASS 不得 VERIFIED | Node `VERIFYING→VERIFIED`，`GateFacts.passed=False` | `reason=GATE_NOT_PASS`；状态仍 `VERIFYING`；无证书行 | 05 §9.3 R10；I-07 |
| NEG-M02-20 | PARTIAL 报告不得 VERIFIED | Gate PASS，但 `ReportFacts.final_state="PARTIAL"` | `reason=REPORT_NOT_VERIFIED`；状态仍 `VERIFYING`；`certificates` 行数为 0 | 05 §9.6；I-07 |
| NEG-M02-21 | 缺凭证不得 VERIFIED | Gate PASS + 报告 VERIFIED，`ctx.cert_id=None` | `reason=MISSING_PARAMETER`，`details` 含 `cert_id`；状态不变；无证书 | 05 §9.3；05 §9.7 |
| NEG-M02-22 | 撤销凭证不得 VERIFIED | `CertificateFacts.revoked=True` | `reason=CERTIFICATE_INVALID`；状态仍 `VERIFYING` | 05 §9.6；I-07 |
| NEG-M02-23 | 无效签名不得 VERIFIED | `cert.signature_valid=False` | `error_code=SIGNATURE_INVALID`，`reason=CERTIFICATE_INVALID`；状态不变 | I-06；05 §1.5 |
| NEG-M02-24 | Merkle 根不一致 | `cert.merkle_root != report.evidence_root` | `reason=CERTIFICATE_INVALID`，`details` 含 `merkle_root`；状态不变 | 05 §13 |
| NEG-M02-25 | tree_size 不一致 | `cert.tree_size != evidence.count(task_id)` | `reason=CERTIFICATE_INVALID`；状态不变；不得“按证书自报数量”放行 | 05 §13 |
| NEG-M02-26 | 规则版本不一致 | `cert.ruleset_hash != report.ruleset_hash` | `error_code=RULESET_VERSION_MISMATCH`；状态不变 | E.3；05 §13 |
| NEG-M02-27 | 环境指纹不一致 | `cert.env_fingerprint != evidence.env_fingerprint(task)` | `error_code=ENV_FINGERPRINT_MISMATCH`；状态不变；证书不得复用 | M03 契约；05 §6 |
| NEG-M02-28 | Task 不得带 PARTIAL 完成 | Task `VERIFYING→COMPLETED`，报告 PARTIAL 且无证书 | `reason=REPORT_NOT_VERIFIED` 或 `TASK_COMPLETION_PREREQUISITES`；Task 仍 `VERIFYING`；无证书 | 05 §9.2 R06；§9.6 |
| NEG-M02-29 | PARTIAL 不得签发凭证 | 直接调用签发入口：`report_final_state="PARTIAL"`，`certificate_requested=True` | `InvariantViolation`，`invariant_id=I-07`，`code=REQUIRED_EVIDENCE_MISSING`；`certificates` 行数 0 | I-07；AGENTS §4.10 |
| NEG-M02-30 | Verifier/Executor/Agent 不得写状态 | 分别以 `ActorRole.VERIFIER`、`EXECUTOR`、`AGENT` 请求 Node `READY→RUNNING` 或 `VERIFYING→VERIFIED` | 均 `reason=ROLE_NOT_ALLOWED`；状态不变；DENIED 审计的 `actor` 记录为 `role:identity` | 04 §4.3；I-01 |

## D. 并发（5 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M02-31 | 同节点两个 READY→RUNNING | 两个线程同时提交，均 `previous_state=READY` | 恰好一个成功；另一个 `reason=STALE_PREVIOUS_STATE`，`error_code=STATE_TRANSITION_DENIED`；`attempt_seq` 只 +1；`audit_log` 恰一条 OK + 一条 DENIED | 05 §9.7；M02 §6 |
| NEG-M02-32 | 同任务两个 READY→RUNNING | 两个线程同时提交 Task 迁移 | 一个成功；另一个 `STALE_PREVIOUS_STATE`；Task 只进入一次 RUNNING | 同上 |
| NEG-M02-33 | 同前态两个不同目标 | Node READY 同时请求 `RUNNING` 与 `BLOCKED` | 先提交者赢；后者 `STALE_PREVIOUS_STATE` 或 `ILLEGAL_EDGE`；状态只变一次，无“最后写入者获胜” | 同上 |
| NEG-M02-34 | 重复提交同一迁移 | 成功后再提交一次相同 `previous_state=READY` 的 RUNNING 请求 | `reason=STALE_PREVIOUS_STATE`；不产生第二条 OK 审计；`attempt_seq` 不再增加 | 05 §9.7 |
| NEG-M02-35 | 写锁超时 | 另一个连接持有写锁超过 `busy_timeout` | `reason=WRITE_LOCK_TIMEOUT`（或 `AUDIT_WRITE_FAILED` + stderr）；状态不变；无半条迁移 | 06 §2；schema_sql busy_timeout |

## E. 重启恢复（9 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M02-36 | RUNNING 但 attempt_seq=0 | 启动时节点 `RUNNING`，`attempt_seq=0` | `BootReport.actions` 含 `decision=NO_ACTIVE_ATTEMPT`、`reason=BOOT_NO_ACTIVE_ATTEMPT`、`to_state=FAILED`；**不得**出现 `COMPLETED`/`VERIFIED` | boot_recovery.py；runtime_states §6 |
| NEG-M02-37 | RUNNING 但无 launch 证据 | `attempt_seq=1`，无 `executor_launch` | `decision=NO_ACTIVE_ATTEMPT`、`to_state=FAILED`；状态更新审计 reason 正确 | 同上 |
| NEG-M02-38 | RUNNING 但 attempt 未结束 | launch 存在、无 `executor_process_exit` | `decision=UNFINISHED_ATTEMPT`、`reason=BOOT_UNFINISHED_ATTEMPT`、`to_state=FAILED`；**不得**补造 exit 事件 | 同上 |
| NEG-M02-39 | 已结束且 exit=0 | launch+exit，`exit_code=0`、payload 可读 | `decision=COMPLETED_ATTEMPT`、`to_state=VERIFYING`；不是 `COMPLETED`/`VERIFIED`；后续由 Gate/Verifier 判定 | 05 §9.3 R09 |
| NEG-M02-40 | exit 非 0 | launch+exit，`exit_code=1` | `decision=FAILED_ATTEMPT`、`reason=BOOT_ATTEMPT_FAILED`、`to_state=FAILED` | 同上 |
| NEG-M02-41 | exit payload 不可读 | launch+exit，`exit_payload_readable=False` | `decision=FAILED_ATTEMPT`、`to_state=FAILED`；**fail-closed**，不得猜成功 | 同上 |
| NEG-M02-42 | 证据链断裂 | 任务内 `prev_hash != 上一条 chain_hash` 或 `event_seq` 缺号 | `schedule_allowed=False`，`blockers` 含 `EVIDENCE_CHAIN_BROKEN`；**不改任何状态**、不处理 attempt；不得修复/重写证据 | 05 §13；runtime_states §6 |
| NEG-M02-43 | DB/schema 不满足 | `PRAGMA integrity_check != ok`；或 `foreign_key_check` 有行；或存在 pending migration | `schedule_allowed=False`；`blockers` 含 `DB_INTEGRITY_FAILED`/`FOREIGN_KEY_VIOLATION`/`SCHEMA_VERSION_MISMATCH`；无状态变化 | 06 §5；boot_recovery.py |
| NEG-M02-44 | 重启不得伪造完成 | Task `RUNNING`，所有节点 `VERIFIED`，无证书 | `BootReport` 无 `Task→COMPLETED` 动作；Task 仍 `RUNNING`；`schedule_allowed` 不得因“看起来都 VERIFIED”而绕过证书 | 05 §9.2 R06；I-07 |

## F. plan_hash 三守卫（7 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M02-45 | 守卫①：文件不存在 | Node `INVALIDATED→READY`，`plan_hash` 对应文件不存在 | `StateTransitionDenied`，`error_code=PLAN_HASH_MISMATCH`，`reason=PLAN_FILE_MISSING`；状态仍 `INVALIDATED`；DENIED 审计含 `plan_id`/`plan_hash` | 05 §9.3；ADR-004 |
| NEG-M02-46 | 守卫②：内容哈希不符 | 文件存在，但写入后改一个字节，`sha256(文件) != plan_hash` | `error_code=PLAN_HASH_MISMATCH`，`reason=PLAN_HASH_MISMATCH`；状态仍 `INVALIDATED`；不得只信任 `nodes.plan_hash` | 同上 |
| NEG-M02-47 | 守卫②：审计冻结记录缺失 | 文件与哈希都正确，但 `audit_log` 无 `RECOVERY_PLAN_FROZEN(result=OK)` | `error_code=PLAN_HASH_MISMATCH`，`reason=PLAN_FREEZE_RECORD_MISSING`；状态不变 | 05 §9.3②；ADR-004 |
| NEG-M02-48 | 守卫②：plan_id 不一致 | 冻结记录的 `plan_id` 与请求不同 | `reason=PLAN_ID_MISMATCH`，`error_code=PLAN_HASH_MISMATCH`；状态不变 | 05 §9.3② |
| NEG-M02-49 | 守卫③：先重跑后冻结 | 冻结事件 `created_at` 晚于本次 `received_at` | `reason=PLAN_FROZEN_AFTER_RERUN`，`error_code=PLAN_HASH_MISMATCH`；状态仍 `INVALIDATED` | 05 §9.3③；决议 5 |
| NEG-M02-50 | 守卫③：同一时刻也拒绝 | 冻结 `created_at == received_at` | 同上；严格 `<` 才放行；不得用 `<=` 放宽 | 05 §9.3③；M02 §10.5 |
| NEG-M02-51 | 计划字段只能在此边出现 | Task `CREATED→PLANNING` 携带 `plan_id/plan_hash` | `reason=PLAN_FIELDS_NOT_ALLOWED`，`error_code=STATE_TRANSITION_DENIED`；状态不变；DENIED 审计含计划字段 | 05 §9.7 |

## G. 幂等（6 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M02-52 | 同键异体 | 同一 `Idempotency-Key`，第二次请求体改 `goal` | HTTP 409，`error_code=IDEMPOTENCY_CONFLICT`；`tasks` 仍只有 1 行；旧 `request_hash` 未被覆盖 | 06 §4.5；附录 E.4 |
| NEG-M02-53 | 同键同体重放 | 同键、同体（仅键顺序不同） | HTTP 201，返回同一 `task_id`；`tasks` 1 行、`idempotency_keys` 1 行；不是 409 | 06 §4.5 |
| NEG-M02-54 | 哈希必须 JCS 而非 sort_keys | 含 astral 字符的两个对象，键序不同但语义相同 | `canonical_request_hash` 相等；实现若用 `json.dumps(sort_keys=True)` 产生不同/错误序 → FAIL | ENCODING_RULES §5 |
| NEG-M02-55 | 任务插入失败不得留孤儿键 | 在 `tasks` 插入后人为触发约束失败，再 `reserve`/提交 | 事务回滚；`idempotency_keys` 无该键；重试可正常创建 | 06 §2 |
| NEG-M02-56 | 非法幂等键 | 空串、含空格、>255 字符、换行 | HTTP 422，`error_code=SCHEMA_INVALID`，`field_path="Idempotency-Key"`；不创建任务、不插键 | 06 §4.4；idempotency.py |
| NEG-M02-57 | 不得用 REPLACE 覆盖 | 静态检查 `idempotency.py` 的 SQL | 不含 `INSERT OR REPLACE` / `ON CONFLICT DO UPDATE`；冲突只回读判定 | 06 §4.5；M02 §8 |

## H. 审计（5 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M02-58 | 成功审计失败 → 状态回滚 | 人为让 `audit_log` 插入失败（如临时 trigger） | 状态事务 `ROLLBACK`；`tasks/nodes.state` 未变；无 OK 审计；随后 DENIED 或 `AuditWriteFailed` | 05 §9.7；ADR-005 |
| NEG-M02-59 | 状态写失败 → DENIED 仍存在 | 审计已插入、UPDATE 因约束失败 | 事务回滚后 OK 审计不存在；独立事务 `DENIED` 存在，含 `previous_state`/`next_state`/`error_code` | I-14；ADR-005 |
| NEG-M02-60 | DENIED 二次失败 → stderr | 人为让 `audit_log` 两次插入都失败 | stderr 恰一行 JSON，`audit_write_failed=true`、`error_code=AUDIT_WRITE_FAILED`、`original_error_code` 正确；抛出 `AuditWriteFailed`；不得静默 | 05 §9.7 第 3–4 条 |
| NEG-M02-61 | 缺字段的 DENIED 审计仍可写 | 请求缺 `correlation_id` / `rule_version` | `StateTransitionDenied`（`MISSING_PARAMETER`）；DENIED 审计使用 `AUDIT_SENTINEL`（`<missing>`）而不是 NULL；审计行存在 | state_machine.py；AUDIT_SENTINEL |
| NEG-M02-62 | 审计只追加 | `UPDATE audit_log SET result='OK'`；`DELETE FROM audit_log` | 两条均触发器 ABORT；`audit_log` 行数/内容不变 | 06 §1.2；schema_sql |

## I. T1 状态 / Evidence / 不变量（4 条）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M02-63 | T0 不得出现 T1 Recovery 状态 | 检查 `TaskState`/`NodeState` 成员；尝试 `INSERT INTO nodes(state='PROPOSED')` | 枚举中无 `PROPOSED`/`APPROVED`/`EXECUTING`/`RECHECKED`/`CLOSED`/`ESCALATED`；INSERT 被 `CHECK (state IN (...10...))` 拒绝 | 05 §9.5；ADR-004；决议 6 |
| NEG-M02-64 | Evidence 表无状态列/不可更新 | `PRAGMA table_info(evidence)`；`UPDATE evidence SET ...` | 无 `state` 列；UPDATE 被 `APPEND_ONLY_TABLE: evidence` 拒绝；`StateMachine.transition(EVIDENCE,...)` 被 `OBJECT_TYPE_NOT_MANAGED` 拒绝 | 06 §1.3/§3；05 §9.4 |
| NEG-M02-65 | E0/E1 不得顶替执行证据 | `assert_i02_e01_not_sufficient(check_id="run_training", check_class=EXECUTION, levels={"E0","E1"})` | `InvariantViolation`，`invariant_id=I-02`，`code=REQUIRED_EVIDENCE_MISSING`；不得返回 PASS | I-02；Gate WP-08 |
| NEG-M02-66 | T0 不得调用 I-05 | `assert_i05_dc_before_spa(dc_valid=False, spa_skipped=True, t0=True)` | 抛 `NotApplicableInT0`；**不得**返回 `RECOVERY_NOT_SAFE`；T0 无 DC/SPA | I-05；决议 6 |

## J. 误拒守卫（6 条：防止收紧过头）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M02-01 | 合法 Task 迁移应成功 | `CREATED→PLANNING`，ORCHESTRATOR，合法 ctx | 返回 `TransitionResult(ok=True)`；状态 `PLANNING`；恰一条 OK 审计 | 05 §9.2 |
| GUARD-M02-02 | 合法 Node 启动应成功 | `READY→RUNNING`，SCHEDULER，资源满足 | 成功；`attempt_seq` 恰好 +1；审计 `attempt_seq` 与状态一致 | 05 §9.3 R08 |
| GUARD-M02-03 | 三守卫全满足应放行 | 计划文件存在、哈希一致、冻结早于重跑 | `INVALIDATED→READY` 成功；`nodes.plan_id/plan_hash` 写入；DENIED 行数为 0 | 05 §9.3；I-12 |
| GUARD-M02-04 | 同键同体重排应重放 | 同一请求体仅对象键顺序不同 | 201 + 同 `task_id`；不得 409；`request_hash` 相同 | ENCODING_RULES §5；06 §4.5 |
| GUARD-M02-05 | 无 RUNNING 时启动不误改 | 空库/全部终态，DB/schema/链均 OK | `schedule_allowed=True`，`actions=()`；不得凭空创建/修改状态 | boot_recovery.py |
| GUARD-M02-06 | 合法拒绝不应二次失败 | 非法边（NEG-M02-09） | `StateTransitionDenied` 正常抛出；DENIED 审计存在；不得把“合法拒绝”误报为 `AUDIT_WRITE_FAILED` | 05 §9.7 |

## K. 执行记录模板（落地阶段填写，P2 留空）

| ID | 命令 | 解释器 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|---|
| NEG-M02-01 | （待执行） | 3.11.16 x64 | — | — | — | 未执行 |
| NEG-M02-31 | （待执行） | 3.11.16 x64 | — | — | — | 未执行 |
| NEG-M02-45 | （待执行） | 3.11.16 x64 | — | — | — | 未执行 |
| NEG-M02-60 | （待执行） | 3.11.16 x64 | — | — | — | 未执行 |

## L. 与正例/其他阶段的边界

- 正例仍以 `contracts/examples/manifest.json` 与 `scripts/validate_contracts.py` 为准；
  P2 不改 72 个用例、不改 expected、不改阈值。
- Gate/Verifier/签名/验签的完整测试属 WP-08/WP-09/WP-11/G6-T0；本表只覆盖 M02 边界。
- 本表 66 条负例 + 6 条误拒守卫；P2 只定义判据，不执行、不写“已通过”。