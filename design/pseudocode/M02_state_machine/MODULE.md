# M02 · 持久层与状态机（P2）

> 阶段：P2「持久层与状态机」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：SQLite 表结构、四类仓储、迁移、幂等、四张迁移表、唯一写入口、I-01–I-08、重启恢复
> 不覆盖：Gate 结果计算、签名/验签、任务派发、模板执行、Evidence 正文写入
> 阶段约束：S0 规则仍生效——只读 P1 基线，不改契约/看板，不建环境，不跑测试，不写业务代码。

## 1. 目标

把“状态只能由 StateMachine 改变”从一句架构口号落成四件可检查的东西：

1. **表结构**：`tasks` / `nodes` / `evidence`(元数据) / `evidence_invalidations` /
   `audit_log` / `idempotency_keys` / `schema_migrations` 的列、约束、索引、写者；
2. **迁移表**：Task 9 状态、Node 10 状态、Evidence 5 状态、T0 恢复两条路径；
   每个状态的允许下一状态逐条列全，终态写空元组；
3. **唯一入口**：`StateMachine.transition()` 是唯一公开写入口；仓储无裸 update；
   DB 触发器要求状态更新必须带同事务 OK 审计；
4. **失败与恢复**：失败也写 `DENIED` 审计（独立事务）；重启先校验 DB/证据链/attempt，
   发现 RUNNING 但无活动 attempt 时明确走 `RUNNING→FAILED`，绝不默认 `COMPLETED`。

## 2. 文件

| 文件 | 内容 | 状态 |
|---|---|---|
| `persistence/schema_sql.py` | 7 张表的列级规格、CHECK、索引、只追加/状态触发器、写者矩阵 | 完成 |
| `persistence/repositories.py` | Task/Node/EvidenceMeta/Audit 四类仓储；查询公开、写入私有 + capability | 完成 |
| `persistence/migrations.py` | `schema_migrations`、版本清单、升级骨架、全有或全无回滚 | 完成 |
| `persistence/idempotency.py` | 幂等键校验、JCS 请求哈希、同键同体/异体、并发顺序 | 完成 |
| `orchestration/transitions.py` | 四张迁移表、角色、守卫、失败码、T1 状态禁令 | 完成 |
| `orchestration/state_machine.py` | `transition()` 唯一写入口、守卫、事务、审计、降级 | 完成 |
| `orchestration/invariants.py` | I-01–I-08 可调用断言；I-09–I-14 落点登记 | 完成 |
| `orchestration/boot_recovery.py` | 六阶段恢复顺序、RUNNING 四分支、调度门 | 完成 |
| `MODULE.md`、`NEGATIVE_TESTS.md` | 模块说明与 66 条负例 + 6 条误拒守卫判据（P2 不执行） | 完成 |

## 2.1 文件导航（>800 行文件必填）

> 依据 PHASE_RULES §5 第 2 档（800–1500 行）：登记完整函数索引，不拆分、不改文件内容。行号为读文件后得到的真实起始行（`ast` 解析）；每个文件的函数数 = 顶层函数 + 类内函数（含 Protocol 方法），与该文件实际数量一致。

### `orchestration/state_machine.py`（1336 行 / 51 个函数）

| 行号 | 类/函数 | 职责（一句话） | 依据章节 |
|---:|---|---|---|
| 118 | `format_utc` | 把带时区 datetime 归一为 27 字符 UTC 文本（微秒 + Z） | 06 §1.1；ENCODING_RULES §3 |
| 125 | `parse_utc` | 解析 27 字符 UTC 文本，非法即 `ValueError`（用于冻结时间比较） | 06 §1.1；05 §9.3 |
| 133 | `SystemClock.now` | 生产时钟，提供审计与迁移的 `created_at` 时间源 | 06 §1.1、§1.3 |
| 138 | `_ClockLike.now` | 时钟协议，便于测试注入固定时间 | 06 §1.1 |
| 152 | `Actor.__post_init__` | 校验角色枚举与 identity 形态（1–64 位，不含冒号） | 05 §9.7；06 §1.3 |
| 159 | `Actor.audit_value` | 生成审计用 `role:identity` 字符串 | 05 §9.7；06 §1.3 |
| 225 | `StateTransitionDenied.__init__` | 公开拒绝异常，绑定错误码、原因、前后态与 HTTP 映射 | 06 §4.4；05 §9.7 |
| 263 | `AuditWriteFailed.__init__` | DENIED 审计二次失败异常，携带原始错误码并标记已降级 | 05 §9.7（决议 7） |
| 289 | `_Denial.__init__` | 内部拒绝信号，承载 reason/error_code/前后态 | 05 §9.7 |
| 307 | `_ConcurrentModification.__init__` | 并发改状态信号，携带事务内重读的实际状态 | 06 §2；05 §9.3 |
| 359 | `GraphFactsPort.dag_valid` | 查询 DAG 静态校验与图版本是否有效 | 05 §9.2 R03 |
| 362 | `GraphFactsPort.blocking_gap` | 查询是否存在可引用的阻塞缺口 | 05 §9.2 R03 |
| 367 | `TaskFactsPort.has_ready_node` | 查询任务是否至少有一个 `READY` 节点 | 05 §9.2 R04 |
| 370 | `TaskFactsPort.execution_finished` | 查询执行是否已结束（执行类节点均有结束事件） | 05 §9.2 R05 |
| 373 | `TaskFactsPort.all_required_nodes_verified` | 查询非跳过节点是否全部 `VERIFIED` | 05 §9.2 R06；I-07 |
| 378 | `NodeFactsPort.dependencies_satisfied` | 查询节点依赖是否全部满足 | 05 §9.3 R07 |
| 381 | `NodeFactsPort.resources_available` | 查询资源/权限/并发槽是否可用 | 05 §9.3 R08 |
| 384 | `NodeFactsPort.attempt_end` | 读取 attempt 结束事实（结束标志 / exit_code / 证据链） | 05 §9.3 R09 |
| 387 | `NodeFactsPort.recovery_budget_available` | 查询恢复预算是否未耗尽 | 05 §9.3 R11 |
| 392 | `NodeFactsPort.diagnosis_valid` | 查询诊断/恢复计划是否有效 | 05 §9.3 R12 |
| 395 | `NodeFactsPort.recovery_rechecked` | 查询恢复执行后的复核是否通过 | 05 §9.3 R13 |
| 400 | `GateFactsPort.get` | 读取已持久化的 Gate 结果（PASS / 缺口 / 规则集） | 05 §9.3 R10；I-02/I-04 |
| 405 | `ReportFactsPort.get` | 读取 VerificationReport 事实（最终态 / 规则集 / 签名有效性） | 05 §9.6 |
| 410 | `CertificateFactsPort.get` | 读取 CompletionCertificate 事实（绑定报告 / 环境 / 签名） | 05 §9.6 |
| 415 | `EvidenceFactsPort.verify_chain` | 读取证据链校验报告（不修复链） | 05 §13；06 §1.3 |
| 419 | `EvidenceFactsPort.count` | 统计任务证据条数（与证书 `tree_size` 对照） | 06 §1.3；05 §9.6 |
| 422 | `EvidenceFactsPort.get` | 读取单条证据元数据（stale 归属判定） | 06 §1.3 |
| 425 | `EvidenceFactsPort.is_invalidated` | 查询证据是否已有失效记录 | 05 §9.3；ADR-001 |
| 428 | `EvidenceFactsPort.env_fingerprint` | 读取任务 E2 的环境指纹（证书一致性） | 05 §6 |
| 433 | `PlanStorePort.resolve` | 解析内容寻址计划路径并拒绝 `../`、绝对路径与符号链接逃逸 | 05 §9.3；ADR-004 |
| 437 | `PlanStorePort.read_bytes` | 读取计划文件字节（用于 sha256 校验） | 05 §9.3；ADR-004 |
| 459 | `StateMachine.__init__` | 注入仓储、只读事实端口与时钟 | 05 §9.7 |
| 471 | `StateMachine.transition` | 唯一公开写入口：校验 → 守卫 → 事务写状态 + 审计 → 返回结果 | 05 §9.7；06 §2 |
| 547 | `StateMachine._validate_request` | 校验必填参数/对象类型/非写者角色，并组装请求 | 05 §9.7；06 §4.4 |
| 614 | `StateMachine._load_object` | 从仓储读取 Task/Node 当前行；不存在即拒绝 | 06 §1.3 |
| 631 | `StateMachine._select_transition` | 校验 `previous_state` 并查允许边 | 05 §9.7；05 §9.2/§9.3 |
| 650 | `StateMachine._check_context_requirements` | 校验边的 `requires` 与 `plan_id`/`plan_hash` 仅限 `INVALIDATED→READY` | 05 §9.7 |
| 674 | `StateMachine._check_role` | 校验 actor 角色在该边允许集合内 | 05 §9.2/§9.3；06 §3 |
| 684 | `StateMachine._evaluate_guard` | 按 `guard_id` 分派到只读守卫；未知守卫拒绝 | 05 §9.2/§9.3 |
| 771 | `StateMachine._guard_attempt_ended` | 要求 attempt 已结束、证据链完整且 `exit_code=0` | 05 §9.3 R09 |
| 791 | `StateMachine._guard_task_completion` | 任务完成：报告 `VERIFIED` + 节点全 `VERIFIED` + `tree_size` 对齐 | 05 §9.2 R06、§9.6；I-07 |
| 809 | `StateMachine._guard_verified_prerequisites` | 节点 `VERIFIED`：报告 `VERIFIED` + `tree_size` 对齐 | 05 §9.3 R10、§9.6 |
| 822 | `StateMachine._verified_bundle` | 交叉校验 Gate/Report/Certificate/证据链三条件（不计算 Gate、不验签） | 05 §9.6、§13；I-02/I-04/I-07 |
| 906 | `StateMachine._guard_stale_cause` | 校验失效原因为四类之一、证据非空且属于该节点 | 05 §9.3；ADR-001 |
| 933 | `StateMachine._guard_plan_three` | 三条 plan 守卫：文件存在 / 哈希与冻结记录一致 / 冻结早于重跑 | 05 §9.3；ADR-004；决议 5 |
| 1027 | `StateMachine._apply_success` | 单事务内重读、追加失效、写 OK 审计、更新状态；失败回滚 | 06 §2；05 §9.7 |
| 1165 | `StateMachine._deny` | 回滚后独立事务写 DENIED 审计；二次失败降级 stderr 并抛 `AuditWriteFailed` | 05 §9.7（决议 7）；ADR-005 |
| 1223 | `StateMachine._audit_row` | 组装 `audit_log` 行，补齐必填字段与 plan 字段成对约束 | 05 §9.7；06 §1.3 |
| 1272 | `StateMachine._degrade_audit` | 向 stderr 写单行结构化 JSON（不含堆栈/SQL/路径/密钥） | 05 §9.7（决议 7） |
| 1297 | `StateMachine._read_state` | 在事务内重读 Task/Node 当前状态（防 TOCTOU） | 06 §2 |
| 1320 | `assert_single_write_entrypoint` | 自检：只允许 `transition` 为公开写入口，仓储无裸写方法 | 05 §9.1；06 §3 |

### `orchestration/transitions.py`（926 行 / 8 个函数）

| 行号 | 类/函数 | 职责（一句话） | 依据章节 |
|---:|---|---|---|
| 262 | `_t` | 构造一条迁移边（前后态、角色、守卫、失败码、副作用、依据） | 05 §9.2–§9.4 |
| 591 | `_build_allowed_next` | 由边表生成每个状态的完整出边（终态为空元组） | 05 §9.2–§9.4 |
| 759 | `assert_no_t1_recovery_state` | 禁止 T1 Recovery 状态进入 T0 的 Task/Node | 05 §9.5；决议 6 |
| 778 | `IllegalTransition.__init__` | 非法边异常，携带对象 / 前后态 / 原因 / 依据 | 05 §9.3 |
| 798 | `_states_for` | 返回对象类型的完整状态元组 | 05 §9.2–§9.4 |
| 808 | `allowed_next_states` | 查询某状态的全部允许下一状态 | 05 §9.2–§9.4 |
| 815 | `lookup_transition` | 查允许边；禁止边与未列出边给具体原因 | 05 §9.3 |
| 852 | `assert_transition_contract` | 自检状态数/边数/终态/窄边/T1 禁令 | 05 §9.2–§9.5 |

### `persistence/schema_sql.py`（835 行 / 12 个函数）

| 行号 | 类/函数 | 职责（一句话） | 依据章节 |
|---:|---|---|---|
| 134 | `IndexSpec.sql` | 生成 `CREATE INDEX` 语句 | 06 §1.3 |
| 150 | `_in` | 把枚举元组渲染为 SQL `IN` 列表 | 06 §1.3 |
| 154 | `_hash_check` | 生成 64 位小写十六进制哈希 CHECK | 06 §1.3；05 §13 |
| 160 | `_utc_check` | 生成 27 字符 UTC 时间 CHECK | 06 §1.1 |
| 168 | `_task_id_check` | 生成 `task_` UUID 形态 CHECK | 05 §1.4；06 §1.3 |
| 176 | `_evidence_id_check` | 生成 `ev_` UUID 形态 CHECK | 05 §1.4；06 §1.3 |
| 184 | `_node_id_check` | 生成 `node_id` 字符集/长度 CHECK | 06 §1.3 |
| 192 | `_attempt_id_check` | 生成 `attempt_NN` 形态 CHECK | 05 §1.4；06 §1.3 |
| 531 | `_render_create_table` | 把 `TableSpec` 渲染为 `CREATE TABLE` 文本 | 06 §1.3 |
| 611 | `_build_column_index_map` | 生成「表.列 → 索引名」映射 | 06 §1.3 |
| 768 | `ddl` | 返回完整 DDL 文本（可含触发器；P2 不执行） | 06 §1.3、§5 |
| 779 | `assert_schema_contract` | 自检状态集/写者矩阵/只追加表/T1 禁令/主键 | 06 §1.3、§3；05 §9 |

## 3. 架构原则与写者边界

| 对象 | 唯一写者 | M02 的位置 |
|---|---|---|
| Task/Node 状态 | `StateMachine.transition()` | `tasks.state` / `nodes.state` 只由 `_apply_transition` 更新 |
| `audit_log` | StateMachine | 成功同事务；失败独立事务；只追加 |
| `evidence` E0–E2 | Collector | 只追加；M02 只定义元数据表与读接口 |
| `evidence` E3 | Verifier | 只追加；M02 不写 |
| `evidence_invalidations` | StateMachine（仅 `VERIFIED→INVALIDATED`） | 同事务追加；不删除证据 |
| `idempotency_keys` | API 任务创建路径 | 与 `tasks` 同事务 INSERT；不 UPDATE |
| `schema_migrations` | 迁移执行器 | 只 INSERT；已应用迁移不得改写 |

四条不可协商：

1. 仓储不提供 `update` / `update_state` / `set_state` / `save` / `delete`；
   状态写入只有 `_apply_transition`，带 `WHERE state = :expected_from` + capability。
2. `tasks`/`nodes` 的 INSERT 只能进入初始状态（`CREATED`/`PLANNED`）；
   写入其他初始状态由触发器拒绝。
3. `tasks`/`nodes` 的 `UPDATE OF state/attempt_seq/graph_version/plan_*` 必须有同事务
   `audit_log(action='STATE_TRANSITION', result='OK', previous_state=OLD.state,
   next_state=NEW.state, created_at=NEW.updated_at)`，否则触发器
   `STATE_WRITE_WITHOUT_AUDIT` 拒绝。触发器不是安全边界，但能抓住直接 SQL 旁路。
4. Evidence 的 `RECEIVED/VALIDATED/APPENDED` 是 Collector 摄入流水线状态；
   06 §1.3 的 `evidence` 表没有 `state` 列且只追加。M02 **不擅自加列**：
   `APPENDED` 以行存在表示，`INVALID/CONFLICT` 在写入前拒绝，不落 evidence 表。
   若 WP-07 需要持久化摄入状态，必须先补 ADR + MINOR 迁移。

列的二级索引见 `schema_sql.COLUMN_INDEX_MAP`（列 → 索引名）；主键/唯一键/外键在列约束
或表约束中声明；未列入 map 的列没有二级索引。

不在 M02 建表范围（由其他 WP 负责，M02 只读）：`graph_versions`（WP-04）、
`reports` / `certificates`（WP-11）、`ingestion_log`（WP-07）。M02 的
`GuardPorts` 只读取报告/凭证事实，不写这些表；`audit_log` 也不替它们保存正文。

## 4. 四张迁移表

### 4.1 Task（9 状态 / 13 条边 / 4 个终态）

| 当前 | 允许下一状态（逐条） |
|---|---|
| `CREATED` | `PLANNING`、`CANCELLED` |
| `PLANNING` | `READY`、`BLOCKED`、`FAILED` |
| `READY` | `RUNNING`、`CANCELLED` |
| `RUNNING` | `VERIFYING`、`FAILED`、`BLOCKED` |
| `VERIFYING` | `COMPLETED`、`FAILED`、`BLOCKED` |
| `COMPLETED` | （无；T0 终态，撤销属 T1） |
| `FAILED` | （无；T0 终态） |
| `BLOCKED` | （无；T0 终态） |
| `CANCELLED` | （无；T0 终态） |

关键守卫：`PLANNING→READY` 需 DAG 校验 + `graph_version`；`READY→RUNNING` 至少一个节点
`READY`；`RUNNING→VERIFYING` 执行必须结束；`VERIFYING→COMPLETED` 需报告 `VERIFIED` +
有效证书 + 所有非跳过节点 `VERIFIED`（T0 `skipped_nodes` 恒空）。

### 4.2 Node（10 状态 / 17 条边 / 1 个终态）

| 当前 | 允许下一状态（逐条） |
|---|---|
| `PLANNED` | `READY`、`BLOCKED` |
| `READY` | `RUNNING`、`BLOCKED` |
| `RUNNING` | `VERIFYING`、`FAILED` |
| `VERIFYING` | `VERIFIED`、`FAILED`、`BLOCKED` |
| `VERIFIED` | `INVALIDATED` |
| `INVALIDATED` | `READY` |
| `FAILED` | `DIAGNOSING`、`BLOCKED` |
| `DIAGNOSING` | `RECOVERING`、`BLOCKED` |
| `RECOVERING` | `READY`、`BLOCKED` |
| `BLOCKED` | （无；T0 终态） |

关键守卫：依赖未满足不能 `READY`；`RUNNING→VERIFYING` 必须有 attempt 结束事件且
`exit_code=0`；`VERIFYING→VERIFIED` 需 Gate PASS + 报告 `VERIFIED` + 有效凭证；
`VERIFIED→INVALIDATED` 只追加失效，不删除证据；`INVALIDATED→READY` 走三条 plan 守卫。

### 4.3 Evidence（5 状态 / 4 条边 / 3 个终态）

| 当前 | 允许下一状态 |
|---|---|
| `RECEIVED` | `VALIDATED`、`INVALID` |
| `VALIDATED` | `APPENDED`、`CONFLICT` |
| `APPENDED` | （无；终态） |
| `INVALID` | （无；终态，保留） |
| `CONFLICT` | （无；终态，保留） |

写者是 Collector（E0–E2）/ Verifier（E3），**不是 StateMachine**；`transition()` 对
`obj_type=evidence` 一律 `OBJECT_TYPE_NOT_MANAGED`。

### 4.4 T0 恢复（`VERIFIED → INVALIDATED → READY`）

| 路径 | 守卫 |
|---|---|
| `VERIFIED→INVALIDATED` | 变更原因属于四类；stale `evidence_ids` 非空；只追加失效，不删证据 |
| `INVALIDATED→READY` | ① 计划文件存在/可读/不逃逸 ② `sha256(文件)==plan_hash` 且与 `audit_log` 冻结记录一致 ③ 冻结事件严格早于本次重跑 |

`plan_id`/`plan_hash` **只允许**在 `INVALIDATED→READY` 携带；其余迁移携带即
`PLAN_FIELDS_NOT_ALLOWED`（05 §9.7）。T1 Recovery 状态 `PROPOSED`/`APPROVED`/
`EXECUTING`/`RECHECKED`/`CLOSED`/`ESCALATED` 不得出现在 T0 代码或 DB 枚举中。

## 5. 事务与审计

| 场景 | 事务 | 结果 |
|---|---|---|
| 成功迁移 | 一个 `BEGIN IMMEDIATE`：审计 INSERT → 状态 UPDATE → COMMIT | 原子；无半条迁移 |
| 失败迁移 | 状态事务 ROLLBACK；**新事务**写 `DENIED` | `DENIED` 在回滚后仍存在（I-14） |
| DENIED 二次失败 | 无事务；stderr 单行 JSON | `audit_write_failed=true`；测试计缺口 |
| 证据追加 | 证据 INSERT + `event_seq` 分配 + 审计同事务 | 失败回滚，不占 `event_seq` |
| 证据失效 | `evidence_invalidations` + 审计同事务 | 不删除/不改写 evidence |
| 幂等创建 | `tasks` INSERT + `idempotency_keys` INSERT 同事务 | 冲突回滚，不留孤儿键 |

成功审计的必填字段：`audit_id`、`task_id`/`node_id`（适用时）、`actor`、`action`、
`previous_state`、`next_state`、`reason_code`、`rule_version`、`correlation_id`、
`result=OK`、`created_at`；`plan_id`/`plan_hash` 仅在计划相关迁移出现。
失败审计额外必填 `error_code`，且 `result=DENIED`。

## 6. 并发

同一节点两个迁移请求：

1. 两者都读到 `READY`，都通过只读守卫；
2. 两者竞争 `BEGIN IMMEDIATE`；SQLite 单写者，先提交者赢；
3. 后者在事务内重读发现状态已变，或 `UPDATE ... WHERE state='READY'` 受影响行数为 0；
4. 后者状态事务回滚，`_deny` 在独立事务写 `DENIED`，`reason_code=STALE_PREVIOUS_STATE`，
   `error_code=STATE_TRANSITION_DENIED`，HTTP 409；审计的 `previous_state` 记录**实际
   持久化状态**（例如 `RUNNING`），不是调用方声称的旧值；
5. 状态只变一次，`attempt_seq` 只加一次；没有“最后写入者获胜”。

## 7. 重启恢复

顺序固定：`LOCK → DB_INTEGRITY → SCHEMA_VERSION → EVIDENCE_CHAIN →
UNFINISHED_ATTEMPTS → SCHEDULER_GATE`。

- DB `integrity_check != ok` 或 `foreign_key_check` 有行 → 只报告，不改状态、不调度；
- schema 有 pending / checksum 不符 / 降级请求 → 拒绝恢复；
- 任一任务证据链断裂 → 不修复、不重写、不处理 attempt、不调度；
- `RUNNING` 节点四分支：
  - 无 attempt 或无 launch → `NO_ACTIVE_ATTEMPT` → **FAILED**；
  - 有 launch、无 exit → `UNFINISHED_ATTEMPT` → **FAILED**；
  - launch+exit 且 `exit_code=0` 且 payload 可读 → `COMPLETED_ATTEMPT` → **VERIFYING**；
  - exit 非 0 / payload 不可读 / 读取异常 → `FAILED_ATTEMPT` → **FAILED**；
- Task 状态在启动阶段**不**自动推进到 `COMPLETED`；本模块没有该分支；
- 仍有 RUNNING 或任何阻断 → `schedule_allowed=False`，调度器不得启动。

## 8. 幂等

- `request_hash = sha256(JCS(原始请求体))`，不是 `json.dumps(sort_keys=True)`；
- 同键同体 → 201 重放原 `task_id`；同键异体 → 409 `IDEMPOTENCY_CONFLICT`；
- 幂等行与任务行同事务；冲突时必须回滚刚插入的任务行；
- 并发同键同体：一个赢，另一个回滚并回读 → 重放同一任务；
- 并发同键异体：一个 201，另一个 409；不得覆盖旧哈希；
- 保留期 `OQ-DB-2` 未决；T0 保留至任务终态后归档。

## 9. 对外接口

| 接口 | 语义 |
|---|---|
| `StateMachine.transition(...)` | 唯一公开写入口；只接受 Task/Node |
| `transitions.lookup_transition()` / `allowed_next_states()` | 查询允许边/出边；非法边给具体 reason |
| `transitions.T0_RECOVERY_PATHS` | T0 两条恢复路径与三条 plan 守卫 |
| `repositories.*` | 公开查询；写方法以下划线开头 + capability |
| `migrations.MigrationRunner.upgrade()` | 全有或全无迁移；只向前 |
| `idempotency.IdempotencyStore.lookup/reserve` | 重放/冲突/预留 |
| `invariants.assert_i01…i08` | 可调用断言；不计算 Gate/不验签 |
| `boot_recovery.BootRecovery.run()` | 返回 `BootReport`；`schedule_allowed` 门控 |

## 10. 验收（P2）

- `transitions.py` 四张表与 05 §9 逐条对齐：Task 9/13、Node 10/17、Evidence 5/4、
  T0 恢复 2/3；无多余状态；无 T1 Recovery 状态。
- `state_machine.py` 只有一个公开写入口 `transition`；仓储无裸 update；
  DB 触发器拒绝无审计的状态更新。
- `boot_recovery.py` 有“RUNNING 但无活动 attempt”的明确分支
  （`BOOT_NO_ACTIVE_ATTEMPT → FAILED`），且不存在 `RUNNING→COMPLETED`。
- `NEGATIVE_TESTS.md` 覆盖：直接写库、非法迁移、VERIFIED 越权、重启误判、
  plan_hash 三守卫各失败一次；每条断言拒绝原因。
- 失败审计字段齐全：`previous_state`、`next_state`、`actor`、`reason_code`、
  `rule_version`、`correlation_id`、`error_code`。

## 11. 本阶段不做

- 不计算 Gate 结果、不判断 L1/L2/L3、不签名、不验签、不派发任务、不执行模板。
- 不实现 SQLite 连接、迁移执行、仓储 SQL、StateMachine 运行时代码。
- 不建 `.venv`、不安装依赖、不跑测试、不改 `project_state.json`、不写 CHANGELOG。
- 不新增契约字段、不新增状态、不为 T0 引入 `PROPOSED`/`APPROVED`。
- 不建 `recovery_plans` 表，不把计划正文写入 `audit_log`。
- 不删除/覆盖 `evidence`、`evidence_invalidations`、`audit_log`。

## 12. 已知缺口与开放问题

1. **Evidence 状态持久化**：05 §9.4 有 `RECEIVED/VALIDATED/APPENDED`，06 §1.3 的
   `evidence` 表无 `state` 列。M02 选择不擅自加列；若 WP-07 需要持久化，需 ADR + MINOR。
2. **任务/节点创建写者**：06 §3 写“tasks/nodes W=StateMachine”，但创建 INSERT 路径
   未分配。M02 把“创建”与“状态迁移”分开：INSERT 只能进入初始状态，之后只能 transition。
   待 WP-03 确认创建入口归属。
3. **失败审计的 claimed previous_state**：`audit_log` 只有一个 `previous_state` 列；
   M02 记录**实际持久化状态**，调用方声称的旧值只进 `reason_code/details`，
   不新增 `detail_json` 列（避免 schema 变更）。
4. **`audit_id` / `invalidation_id` 形态未冻结**：06 DDL 只写 `TEXT PRIMARY KEY`；
   M02 用不透明 UUID，不新造 `aud_` / `inv_` 前缀。
5. **冻结事件先后的时钟**：`INVALIDATED→READY` 用 `created_at` 严格小于 `received_at`；
   时钟回拨会 fail-closed（拒绝），不会误放行。若需强单调序，需增加 `audit_seq`（schema 变更）。
6. **`BLOCKED` 终态**：05 §9.2/§9.3 未给 Task/Node `BLOCKED` 出边；T0 视为终态。
   若 T0 需要“解除阻塞”，必须新 ADR，不得在 M02 私自加边。
7. **`idempotency_keys.task_id` 可空性**：06 DDL 为 `TEXT`；M02 收紧为 `NOT NULL` +
   FK，要求与任务同事务。若保留“先占键后建任务”，需改为可空或延迟 FK。
8. **幂等键字符集**：06 §4.5 未冻结；M02 取可见 ASCII 1–255、无空白，待确认。
9. **`STATE_TRANSITION_DENIED` 与 404**：对象不存在时 M02 用
   `STATE_TRANSITION_DENIED/OBJECT_NOT_FOUND`；API 是否映射 404 未在 06 定义。
10. **Verifier 不能写 Node 状态**：M02 只允许 Orchestrator 在 VERIFYING→VERIFIED
    请求迁移，Verifier 只签发报告/证书；若要求 Verifier 直接驱动状态，需改角色表。

## 12.1 需特别裁决的偏离

> 本节把 §12 中三条对 G0 冻结件的实质偏离单独定级：**待确认（T0 实现选择）**，不是既成裁决。
> 三条均**不得**写入 `contracts/**` 或 `06_DATA_AND_API.md`，只能留在 `design/pseudocode/` 与将来的 ADR。

### D-1 `evidence` 表无 `state` 列

- **① 偏离的冻结原文**：`06 §1.3` 的 `CREATE TABLE evidence (...)` 列清单从 `evidence_id` 到 `chain_hash`，**没有 `state` 列**；`06 §1.2` 把 `evidence` 列为只追加表（禁止 `UPDATE`/`DELETE`）。而 `05 §9.4` 定义了 `RECEIVED/VALIDATED/APPENDED/INVALID/CONFLICT` 五个摄入状态。原话：06 §1.2「`evidence` … 只追加表 … 禁止 `UPDATE`/`DELETE`」。
- **② 现状**：M02 不擅自加列；`APPENDED` 以行存在表示，`INVALID`/`CONFLICT` 在写入前拒绝、不落 `evidence` 表（`schema_sql.EVIDENCE_STATE_NOTE`、§3 第 4 条、§4.3）。
- **③ 处置**：待确认（T0 实现选择）。
- **④ 升级条件**：WP-07 需要持久化摄入状态，或 Gate 需要断言非法状态转换。
- **⑤ 死线**：WP-07 开工前必须关闭。

### D-2 `audit_log` 只有一列 `previous_state`

- **① 偏离的冻结原文**：`05 §9.7`「失败迁移的审计语义（决议 7）」第 1 条原话：「含 `error_code`、尝试的 `previous_state`/`next_state`、`correlation_id`…」；`06 §1.3` 的 `audit_log` 只有一列 `previous_state`，无法同时保存「声称旧值」与「实际旧值」。
- **② 现状**：M02 只记录**实际持久化状态**；调用方声称的旧值只进 `reason_code/details`，不新增 `detail_json` 列（§12-3、§6）。
- **③ 处置**：待确认（T0 实现选择）。
- **④ 升级条件**：需要区分「声称旧值 / 实际旧值」，或需要结构化统计 409 原因。
- **⑤ 死线**：WP-08 开工前必须关闭。

### D-3 `idempotency_keys.task_id` 收紧为 `NOT NULL` + FK

- **① 偏离的冻结原文**：`06 §1.3` 的 `CREATE TABLE idempotency_keys (...)` 中 `task_id           TEXT,`，即可空、无外键。
- **② 现状**：M02 收紧为 `NOT NULL` + `REFERENCES tasks(task_id)`，要求与任务同事务（§3 写者矩阵、§8）。
- **③ 处置**：待确认（T0 实现选择）。
- **④ 升级条件**：需要「先占键后建任务」或延迟 FK。
- **⑤ 死线**：WP-13 开工前必须关闭。