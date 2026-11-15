# WP-03 Step 1 计划与 diff（待批准）

> 状态：**已批准（2026-11-12）；已按本计划实施；`task_spec_json`=A；未 commit**
> 日期：2026-11-12
> 依据：用户 2026-11-12“按你的建议来吧”；[`00_decisions.md`](00_decisions.md)；`docs/design/05` §9、`docs/design/06` §1–§5、`docs/design/07` §2.3、ADR-001/004/005、`design/pseudocode/M02_state_machine/`。
> 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（3.11.16 / 64bit）。

## 0. 前置条件复核

| # | 条件 | 复核 | 判定 |
|---:|---|---|---|
| 1 | §12-2/§12-6/§12-7/§12-8 已裁决并记录 | [`00_decisions.md`](00_decisions.md) 第 1–5 项 | 满足 |
| 2 | 用户明确下达 WP-03 指令 | 本轮“按你的建议来吧”；仅授权 Step 0/1 | 满足（代码待 Step 1 批准） |
| 3 | P9/P10 已处置且不作为输入 | `00_decisions.md` 第 6 项：保持 BLOCKED，不读 M15/M16/M19 | 满足 |
| 4 | `BLK-003` 仍 OPEN | 未改状态；测试策略见 §10 | 满足（保持 OPEN） |
| 5 | 解释器 3.11.16 / 64bit | 实测 `3.11.16 ... 64bit`，SQLite 3.53.1 | 满足 |
| 6 | 分支/HEAD/未提交变更已确认 | `main`；HEAD `309083e`；49 项未提交（39 M + 10 ??） | 满足 |

## 1. 范围

### 1.1 本轮实现（WP-03）

1. SQLite 连接、迁移、`schema_migrations`。
2. 7 张表：`tasks`、`nodes`、`evidence`、`evidence_invalidations`、`audit_log`、`idempotency_keys`、`schema_migrations`。
3. `StateMachine.transition()` 唯一改变已有状态的公开入口；`StateMachine.create_initial()` 唯一创建入口。
4. 成功迁移：状态 + `audit_log(OK)` 同事务。
5. 失败迁移：状态回滚后，独立事务写 `audit_log(DENIED)`；二次失败写结构化 stderr。
6. 旁路写防护：仓储无公开写方法；DB 触发器拒绝无审计状态更新。
7. `INVALIDATED → READY` 三条件守卫；`VERIFIED → INVALIDATED` 追加失效记录。
8. 幂等创建：同键同体 201 重放、同键异体 409；JCS 请求哈希。
9. API 从 `_EphemeralTaskRegistry` 切换到 SQLite；保留 201/409/422/404。
10. 真实 SQLite 测试与证据日志。

### 1.2 不在本轮

- 不实现 Collector、Verifier、Gate 计算、签名/验签、DAG Builder、调度器、重启恢复。
- 不实现 `POST /recover`（保持 404）。
- 不新增 T1 Recovery 状态、不新增契约字段、不新增第 14 个 API 错误码。
- 不修改 `contracts/**`、`docs/design/**`、`docs/ADR/**`、`docs/PRD/**`、`docs/G0/**`、`design/pseudocode/**`。
- 不读取 P3–P10 实现作为输入；P9/P10 保持 `BLOCKED`。
- 不 commit。

### 1.3 范围代价（需知悉）

为测试 `INVALIDATED → READY`，本轮把 `evidence` 与 `evidence_invalidations` 纳入建表范围，实际是 **7 张表**，不是原计划口径的“五表”。这是 `00_decisions.md` 第 9 项批准的 9A 方案；如果不接受该范围，应改为 9C（拆到后续 WP），本轮验收清单相应标“未实现/未测”。

## 2. 文件清单

### 2.1 新增

| 文件 | 作用 |
|---|---|
| `researchflow/persistence/__init__.py` | 包入口 |
| `researchflow/persistence/db.py` | 连接工厂：WAL、`foreign_keys=ON`、`busy_timeout`、显式事务、UTC 时间辅助 |
| `researchflow/persistence/schema_sql.py` | 7 表 DDL、索引、只追加/状态写触发器 |
| `researchflow/persistence/migrations.py` | 版本清单、`upgrade()`、全有或全无、checksum、只向前 |
| `researchflow/persistence/repositories.py` | Task/Node/Evidence/Audit/Idempotency 仓储；公开只读，写入私有 + capability |
| `researchflow/persistence/idempotency.py` | 幂等键查询/插入/冲突；JCS 哈希调用 |
| `researchflow/orchestration/__init__.py` | 包入口 |
| `researchflow/orchestration/transitions.py` | Task 9 / Node 10 迁移表、角色、守卫、reason code；T1 禁令 |
| `researchflow/orchestration/state_machine.py` | `transition()`、`create_initial()`、事务、审计、降级、守卫 |
| `researchflow/orchestration/ports.py` | 只读事实端口 Protocol 与 dataclass |
| `researchflow/orchestration/plan_store.py` | 内容寻址计划文件读取/路径安全/哈希校验 |
| `researchflow/orchestration/invariants.py` | I-01–I-14 中 WP-03 可调用断言；不做 Gate/验签 |
| `researchflow/contracts/encoding.py` | RFC 8785 JCS `canonical_bytes()` / `hash_payload()` |
| `researchflow/contracts/errors.py` | 13 个冻结 API 错误码 + HTTP 映射；不含内部 domain code |
| `tests/test_jcs.py` | JCS 向量 |
| `tests/test_persistence_migrations.py` | 建库、重复迁移、失败回滚、checksum |
| `tests/test_state_machine.py` | 合法/非法迁移、角色、缺参、端口缺失 |
| `tests/test_audit_dual_transaction.py` | OK 同事务、DENIED 回滚后仍存在、二次失败 stderr |
| `tests/test_direct_write_guard.py` | 直接 SQL 更新/插入/删除被触发器拒绝 |
| `tests/test_invalidated_guard.py` | 三条件各失败一次 + 正例 + `VERIFIED→INVALIDATED` |
| `tests/test_idempotency_sqlite.py` | 同键同体/异体/缺 key/非法 key/无孤儿键 |
| `tests/test_api_sqlite.py` | 201/409/422/404/重启读取 |
| `tests/wp03_support.py` | 测试夹具：真实 SQLite、fake ports、受控种子、证据写入 |

### 2.2 修改

| 文件 | 改动 |
|---|---|
| `researchflow/api/app.py` | 用可注入的 SQLite 服务替换 `_EphemeralTaskRegistry`；lifespan 迁移；保留 201/409/422/404；`/recover` 仍 404 |
| `tests/test_api_422.py` | fixture 改为 `with TestClient(create_app(db_path=tmp_path/...))`；断言不降低 |
| `tests/test_api_idempotency.py` | 同上；补“未带 key 允许创建两次”的显式断言 |
| `docs/CHANGELOG_DEV.md` | 仅真实测试完成后追加 |
| `docs/SESSION_HANDOFF.md` | 仅真实测试完成后更新 |
| `docs/state/project_state.json` | 仅真实测试完成后新增/更新 `T-WP-03-001` |

### 2.3 不改

`contracts/**`、`docs/design/**`、`docs/ADR/**`、`docs/PRD/**`、`docs/G0/**`、`design/pseudocode/**`、`tests/test_contract_models.py`、`scripts/state_sync.py`（收尾仅运行）。

## 3. DDL 与迁移

### 3.1 表集合与偏离

| 表 | 基线 | 偏离/说明 |
|---|---|---|
| `tasks` | 06 §1.3 | **待批准新增 `task_spec_json TEXT NOT NULL`**，用于保留 GET `spec`；其余列同 06 |
| `nodes` | 06 §1.3 | 列同 06；增加状态 CHECK、初态触发器、状态写触发器 |
| `evidence` | 06 §1.3 | 列同 06；只追加；WP-03 无生产写入路径，测试种子用受控 capability |
| `evidence_invalidations` | 06 §1.3 | 列同 06；只追加；FK 指向 `evidence` |
| `audit_log` | 06 §1.3 | 列同 06；`action` CHECK 增加 `TASK_CREATED`、`NODE_PLANNED`（已裁决） |
| `idempotency_keys` | 06 §1.3 | `task_id NOT NULL` + FK（已裁决 §12-7）；只追加 |
| `schema_migrations` | 06 §5 / M02 | `(version, applied_at, checksum)`；只追加 |

**`tasks.task_spec_json` 待批准项**：06 §1.3 没有完整 TaskSpec 列，当前 GET 返回 `spec`。本计划推荐：

- **A（推荐）**：`tasks.task_spec_json TEXT NOT NULL`，存 `TaskSpec.model_dump_json()`；GET 读回 `spec`。这是单列偏离，保留现有 GET 结构。
- **B**：GET 不再返回 `spec`，只返回 `task_id`/`state`/`graph_version`；不改 DDL，但改变现有 GET 结构。
- **C**：TaskSpec 存内容寻址文件；不改 DDL，但增加文件原子性/清理逻辑。

若批准 A，`task_spec_hash = hash_payload(spec.model_dump(mode="json"))`，并加触发器禁止更新 `task_spec_json`/`task_spec_hash`。

### 3.2 触发器

| 触发器 | 作用 |
|---|---|
| `trg_tasks_insert_created` | `tasks` 只能以 `CREATED` 插入 |
| `trg_nodes_insert_planned` | `nodes` 只能以 `PLANNED` 插入 |
| `trg_tasks_state_requires_audit` | `tasks` 更新 `state/graph_version` 必须有同事务 `STATE_TRANSITION/OK` 审计，previous/next 匹配 |
| `trg_nodes_state_requires_audit` | `nodes` 更新 `state/attempt_seq/plan_id/plan_hash` 必须有同事务 OK 审计 |
| `trg_tasks_graph_version_requires_state_change` | 状态不变时不得单独改 `graph_version` |
| `trg_nodes_nonstate_requires_state_change` | 状态不变时不得单独改 `attempt_seq/plan_*` |
| `trg_tasks_immutable_fields` | 禁止改 `task_id/schema_version/domain_pack/goal/task_spec_hash/task_spec_json/created_at` |
| `trg_nodes_immutable_fields` | 禁止改 `task_id/node_id/schema_version/node_type/template_id` |
| `trg_tasks_no_delete` / `trg_nodes_no_delete` | 禁止删除 Task/Node |
| append-only triggers | `evidence`、`evidence_invalidations`、`audit_log`、`schema_migrations`、`idempotency_keys` 禁止 UPDATE/DELETE |

触发器是旁路防护，不是安全边界；测试直接 SQL 必须被拒绝，并断言触发器名/目标行未变。

### 3.3 迁移执行器

- 每连接：`PRAGMA journal_mode=WAL`、`foreign_keys=ON`、`busy_timeout=5000`、`isolation_level=None`。
- `upgrade()`：`BEGIN IMMEDIATE` → 建 `schema_migrations`（IF NOT EXISTS）→ 按版本执行 DDL 语句 → 插入 `(version, applied_at, checksum)` → `COMMIT`。
- **不使用 `executescript()` 在事务内执行**（它会隐式提交）；逐条 `execute`，确保 DDL 参与事务。
- 已应用版本：校验 checksum；不一致 fail-closed；一致则跳过。
- 失败：`ROLLBACK`，不留半张表，`schema_migrations` 不前进。
- 只向前，不提供破坏性 DOWN；迁移前备份 DB（生产路径）。

## 4. 仓储与写入口

- `TaskRepository`/`NodeRepository`：公开 `get_*`/`list_nodes`；写入私有 `_insert_initial`、`_apply_transition`，必须带 capability。
- `AuditRepository`：公开 `get`/`latest_freeze`/`list`；写入私有 `_append`，必须带 capability。
- `EvidenceMetaRepository`：公开 `get`/`count`/`is_invalidated`；写入私有 `_append`（生产不暴露，测试种子用 `COLLECTOR_APPEND`）。
- `IdempotencyRepository`：公开 `lookup`；写入私有 `_insert`，必须带 `IDEMPOTENCY_WRITE`；只允许与任务同事务。
- 仓储不得有公开 `update`/`update_state`/`set_state`/`save`/`delete`。
- `assert_single_write_entrypoint()`：
  - `StateMachine` 公开可调用项只有 `transition`、`create_initial`；
  - 仓储无公开写方法；
  - 测试断言返回空列表。

## 5. 状态机

### 5.1 迁移表

- Task 9 状态 / 13 条边；终态 `COMPLETED`、`FAILED`、`BLOCKED`、`CANCELLED`。
- Node 10 状态 / 17 条边；`BLOCKED` 终态；`VERIFIED→INVALIDATED`、`INVALIDATED→READY` 两条窄边。
- 不出现 T1 Recovery 状态（`PROPOSED`/`APPROVED`/`EXECUTING`/`RECHECKED`/`CLOSED`/`ESCALATED`）。
- `lookup_transition()` 返回 edge 或 `IllegalTransition(reason=ILLEGAL_EDGE)`；`allowed_next_states()` 返回完整出边。

### 5.2 `transition()` 顺序

1. 校验必填参数/类型/actor；缺参 → `MISSING_PARAMETER`（field_path 指向参数）。
2. 读取对象；不存在 → `OBJECT_NOT_FOUND`（API 错误码 `STATE_TRANSITION_DENIED`）。
3. 校验 `previous_state` 与持久化状态；不一致 → `STALE_PREVIOUS_STATE`。
4. 查边；非法边 → `ILLEGAL_EDGE`；`plan_id/plan_hash` 只在 `INVALIDATED→READY` 允许 → 否则 `PLAN_FIELDS_NOT_ALLOWED`。
5. 校验角色；非写者/不在 edge 允许集 → `ROLE_NOT_ALLOWED`。
6. 执行只读守卫；端口缺失 → `PORT_UNAVAILABLE`；守卫失败 → 具体 reason。
7. `BEGIN IMMEDIATE`；事务内重读状态；变化 → `STALE_PREVIOUS_STATE`。
8. 如 `VERIFIED→INVALIDATED`：先插 `evidence_invalidations`。
9. 先插 `audit_log(result=OK)`，`created_at = 新 updated_at`。
10. `UPDATE ... WHERE state=:expected_from`；受影响行数必须为 1。
11. `COMMIT`；返回 `TransitionResult`。
12. 任一步失败：`ROLLBACK` → 新事务写 `DENIED` → 抛 `StateTransitionDenied`。
13. `DENIED` 写入失败：单行 JSON stderr（`audit_write_failed=true`）→ 抛 `AuditWriteFailed`；不静默。

### 5.3 `create_initial()`

- 参数：`obj_type`、`task_id`、`node_id`（可选）、`actor`、`correlation_id`、`rule_version`、对象字段。
- 只允许 `CREATED`（Task）/ `PLANNED`（Node）；其他状态拒绝 `INITIAL_STATE_INVALID`。
- 同一事务：插入初始行 + 初始审计（`TASK_CREATED` / `NODE_PLANNED`，`result=OK`，`previous_state=NULL`）。
- `create_initial` 不算状态迁移；不调用 `transition()`。
- 允许 actor：`api:create`（Task）、`orchestrator:...`（Node 测试/未来图构建）；API 不因此获得 `transition()` 写权限。
- 失败：回滚；不写 DENIED（创建不是迁移）；返回结构化异常；API 映射 409/422。

### 5.4 守卫与端口

| 边/守卫 | 端口 | 失败 reason |
|---|---|---|
| Task `PLANNING→READY` | `GraphFactsPort.dag_valid` | `DAG_INVALID` |
| Task `READY→RUNNING` | `TaskFactsPort.has_ready_node` | `NO_READY_NODE` |
| Task `RUNNING→VERIFYING` | `TaskFactsPort.execution_finished` | `EXECUTION_NOT_FINISHED` |
| Task `VERIFYING→COMPLETED` | Report/Certificate/Node facts | `REPORT_NOT_VERIFIED` / `CERTIFICATE_INVALID` |
| Node `PLANNED→READY` | `NodeFactsPort.dependencies_satisfied` | `DEPENDENCIES_NOT_SATISFIED` |
| Node `READY→RUNNING` | `NodeFactsPort.resources_available` | `RESOURCES_UNAVAILABLE` |
| Node `RUNNING→VERIFYING` | `NodeFactsPort.attempt_end` | `ATTEMPT_NOT_ENDED` / `EXIT_CODE_NONZERO` |
| Node `VERIFYING→VERIFIED` | Gate/Report/Certificate facts | `GATE_NOT_PASS` / `REPORT_NOT_VERIFIED` / `CERTIFICATE_INVALID` |
| Node `VERIFIED→INVALIDATED` | Evidence facts | `CAUSE_INVALID` / `NO_STALE_EVIDENCE` |
| Node `INVALIDATED→READY` | `PlanStorePort` + audit freeze | `PLAN_FILE_MISSING` / `PLAN_HASH_MISMATCH` / `PLAN_FREEZE_RECORD_MISSING` / `PLAN_ID_MISMATCH` / `PLAN_FROZEN_AFTER_RERUN` |

端口缺失时 `PORT_UNAVAILABLE`，fail-closed；不得伪造 PASS。WP-03 实现 `SqliteTaskFacts`、`SqliteNodeFacts`、`SqliteEvidenceFacts`、`FilePlanStore`；Gate/Report/Certificate 生产端口不实现，测试用 fake。

### 5.5 `INVALIDATED` 路径

- `VERIFIED→INVALIDATED`：`cause_type` 四类之一；`evidence_ids` 非空；每条证据存在、属于该节点、未失效；同事务追加 `evidence_invalidations`、OK 审计、节点状态更新；不删除证据。
- `INVALIDATED→READY`：
  1. 计划文件存在、普通文件、可读、路径不逃逸；
  2. `sha256(文件字节)==plan_hash`，且与 `audit_log` 的 `RECOVERY_PLAN_FROZEN(result=OK)` 记录一致（plan_id/plan_hash）；
  3. 冻结 `created_at` 严格早于本次 `received_at`（相等拒绝）。
- 三条件任一失败 → `DENIED`，状态仍 `INVALIDATED`，错误码/原因按下表断言。

## 6. 错误码分层

| 层 | 内容 | 用途 |
|---|---|---|
| API 错误码（13 个） | `SCHEMA_INVALID`、`IDEMPOTENCY_CONFLICT`、`STATE_TRANSITION_DENIED`、…（06 §4.4） | HTTP 响应；不新增第 14 个 |
| 内部 domain code | `PLAN_HASH_MISMATCH`、`ENV_FINGERPRINT_MISMATCH`、`EVIDENCE_CHAIN_BROKEN`、`AUDIT_WRITE_FAILED` | 异常字段/测试断言/stderr；不是 API 错误码 |
| reason code | `ILLEGAL_EDGE`、`STALE_PREVIOUS_STATE`、`ROLE_NOT_ALLOWED`、`MISSING_PARAMETER`、`PLAN_FILE_MISSING`、`PLAN_FROZEN_AFTER_RERUN` 等 | 测试断言“拒绝原因正确” |

`StateTransitionDenied` 同时携带 `api_error_code`（默认 `STATE_TRANSITION_DENIED`）与 `error_code`（domain）。测试至少断言 `api_error_code` + `reason` 两项；计划守卫额外断言 `plan_id/plan_hash` 或 `field_path`。

## 7. 审计与旁路

- 成功：状态更新 + `audit_log(result=OK)` 同事务；任何一步失败全回滚。
- 失败：状态事务回滚 → **新连接/新事务**写 `DENIED`；字段含 `previous_state`（实际持久化状态）、`next_state`、`actor`、`reason_code`、`rule_version`、`correlation_id`、`error_code`、`result=DENIED`。
- 缺 `correlation_id`/`rule_version`：DENIED 使用 `AUDIT_SENTINEL="<missing>"`，仍写行；公开错误仍报 `MISSING_PARAMETER`。
- 二次失败：单行 JSON stderr，含 `audit_write_failed=true`、`error_code=AUDIT_WRITE_FAILED`、`original_error_code`、`correlation_id`；抛 `AuditWriteFailed`；测试捕获 stderr。
- 直接写库：触发器拒绝；测试断言 `sqlite3.IntegrityError`、消息含触发器名、目标行状态未变、无新增 OK 审计。

## 8. 幂等、JCS、API

### 8.1 JCS

- `canonical_bytes(value)`：RFC 8785；对象键按 UTF-16 code unit 排序；数组保序；字符串/数字按 ECMAScript；拒绝 NaN/Infinity；UTF-8。
- `hash_payload(value)` = sha256 hex。
- API 对解析后的请求体做 JCS 哈希；替换现有 `json.dumps(sort_keys=True)`。
- 现有 WP-02 内存幂等键不保留，无历史键迁移。

### 8.2 幂等

- 同键同体：201 重放原 `task_id`；任务/键各 1 行。
- 同键异体：409 `IDEMPOTENCY_CONFLICT`；旧 `request_hash` 不覆盖；不创建新任务。
- 未带 key：允许创建；不写幂等键；同体两次会得到两个任务（显式测试）。
- key 校验：1–255 可见 ASCII（`0x21–0x7E`），无空白；非法 → 422 `SCHEMA_INVALID`，`field_path="Idempotency-Key"`。
- 事务：`BEGIN IMMEDIATE` → 查键 → 插任务（`create_initial`）→ 插键 → `COMMIT`；冲突回滚后回读；任务插入失败不得留孤儿键。
- 重放响应：确定性创建回执 `{"task_id", "state":"CREATED", "graph_version":1}`，不返回当前状态。

### 8.3 API

- `create_app(db_path=None)`：
  - 路径优先级：显式参数 → `RESEARCHFLOW_DB_PATH` → `runtime/researchflow.db`（`/runtime/` 已在 `.gitignore`）。
  - FastAPI `lifespan`：建父目录、执行迁移、设置 `app.state.persistence`；失败拒绝启动。
  - `/healthz` 200；`/readyz` 检查 schema 版本，未就绪 503。
- `POST /api/v1/tasks`：
  - 校验 body（保持现有 422 字段路径/文案）→ 校验 key → JCS 哈希 → 事务创建 → 201。
  - 冲突 409；重放 201；未带 key 201；非法 key 422。
- `GET /api/v1/tasks/{id}`：读 `tasks`；返回 `task_id/state/graph_version/spec`（若批准 `task_spec_json`）；未知 404。
- `POST /api/v1/tasks/{id}/recover`：不注册，404。
- 测试 fixture 使用 `with TestClient(create_app(db_path=tmp_path/"test.db"))`，确保 lifespan/迁移执行。

## 9. 测试矩阵（最低要求）

| 类别 | 用例 | 通过条件 |
|---|---|---|
| JCS | 键序、数组、astral、数字、NaN/Infinity | 固定向量相等/拒绝 |
| 迁移 | 新库 7 表 + 索引；重复 upgrade；失败回滚；checksum 不符 | 表/行/回滚正确 |
| 创建 | Task `CREATED` + `TASK_CREATED` 审计；Node `PLANNED` + `NODE_PLANNED`；非初态拒绝 | 审计行存在；状态正确 |
| 合法迁移 | `CREATED→PLANNING`；Node `PLANNED→READY→RUNNING→VERIFYING→VERIFIED` | 状态 + OK 审计同事务 |
| 非法迁移 | `CREATED→COMPLETED`、`VERIFIED→READY`、Evidence 类型、过期 previous_state、角色拒绝、缺参、 plan 字段错边 | 断言 `api_error_code` + `reason` + 状态未变 + DENIED 存在 |
| 守卫 | DAG、READY 节点、attempt 结束、exit code、Gate、Report、Certificate、stale cause、证据归属 | 断言具体 reason；状态不变 |
| INVALIDATED | 文件缺失、哈希不符、冻结记录缺失/plan_id 不符/冻结晚于或等于重跑、三条件全满足 | 前五者 DENIED + 状态仍 INVALIDATED；正例 READY + plan 字段写入 |
| 审计 | OK 同事务；状态写失败后 DENIED 仍存在；二次失败 stderr | 真实 SQLite；stderr 单行 JSON；`AuditWriteFailed` |
| 旁路 | 直接 UPDATE Task/Node 状态、直接 INSERT 非初态、DELETE 审计、无审计改 attempt_seq | 触发器名正确；状态/行数不变 |
| 幂等 | 同键同体、同键异体、缺 key、非法 key、无孤儿键 | 201/409/422；行数正确 |
| API | 201/201/409/422/404；重启读取；`/recover` 404；`readyz` | 状态码/响应字段不变 |
| 回归 | 现有 `test_api_422.py`、`test_api_idempotency.py`、`test_contract_models.py` | 不降低断言强度 |

每个负例至少断言两项：`api_error_code` + `reason` / `field_path` / 触发器名 / 守卫；不能只断言“被拒绝”。

## 10. 证据与测试环境

- 证据目录：`docs/verification/t0/wp-03/`。
- 运行方式：`docs/verification/t0/wp-03/make_evidence.py` 设置 `RF_WP03_EVIDENCE_DIR`，运行定向 pytest，并写：
  - `transitions.jsonl`、`illegal.log`、`direct_write.log`、`audit_log.jsonl`、`denied_survives_rollback.log`、`audit_degraded_stderr.log`、`invalidated_guard.log`；
  - `pytest_targeted.log`、`pytest_full.log`、`state_sync.log`。
- 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`。
- `BLK-003`：workspace-write 下若 setUp/临时目录失败，如实记录；如需 full-access 补充，单独取得批准，并与 workspace-write 结果分开标注；不写成 workspace-write 通过。

## 11. 回滚

- 不 commit。
- 修改 `researchflow/api/app.py`、`tests/test_api_422.py`、`tests/test_api_idempotency.py` 前，把原文件复制到 `docs/verification/t0/wp-03/rollback/`；新增文件可删除。
- 测试 DB 全部在 `tmp_path`；不创建生产 DB。
- 迁移失败由事务回滚；不提供破坏性 DOWN；生产迁移前备份 DB。
- 若 Step 2 失败：恢复三个修改文件的副本，删除新增模块/测试，重跑现有测试；保留失败日志，不改 expected。

## 12. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 7 表 + fake ports 扩大范围 | 被误认为实现 Gate/Verifier | fake 仅测试；生产端口缺失 fail-closed；报告标明 |
| `tasks.task_spec_json` 偏离 06 | 冻结件一致性争议 | 单列记录；待批准；不改 06 |
| 测试种子用私有 capability | 削弱“旁路写”证明 | 仅测试导入；生产不暴露；负例断言公开路径拒绝 |
| `BLK-003` | workspace-write 测试失败 | 如实记录；full-access 另批；分开标注 |
| Windows SQLite 锁 | 并发用例偶发 `database is locked` | `busy_timeout`、`BEGIN IMMEDIATE`、短事务 |
| 触发器/审计顺序 | 成功写被误拒或回滚不彻底 | 先审计后更新；真实 SQLite 负例 |
| JCS 实现不完整 | 幂等哈希错误 | 固定向量 + astral/数字测试 |
| API 默认 DB 路径/import 副作用 | 测试污染仓库 | lifespan 迁移；测试显式 `tmp_path`；默认 `runtime/` |
| 全量测试耗时/环境 | 无法一次全绿 | 先定向；全量单独记录；BLK-003 如实说明 |

## 13. 批准结果（2026-11-12）

1. **7 表范围 + fake ports + 测试种子**：已批准（`00_decisions.md` 第 9 项）。
2. **`tasks.task_spec_json`**：用户选择 **A**（保留 GET `spec`）。
3. **初始审计动作** `TASK_CREATED`/`NODE_PLANNED` 与 actor `api:create`：已批准。
4. **`idempotency_keys.task_id` NOT NULL + FK**：已批准（§12-7）。
5. **`RESEARCHFLOW_DB_PATH` 默认 `runtime/researchflow.db`**：已批准。
6. **`00_decisions.md` 作为裁决记录**：已批准。
7. **批准 Step 2 实施**：已批准；实现已完成，定向 87 passed / 全量 217 passed（full-access 补充）。
8. **不 commit**：保持；commit 需另行确认 Git 身份与授权。

## 14. 批准后的执行顺序

Phase 1：JCS + errors + 7 表 DDL + 迁移 → 迁移测试。
Phase 2：仓储 + `create_initial()` + 幂等 + API 切换 → 定向 API/幂等测试。
Phase 3：transitions + `transition()` + 守卫 → 状态机/审计测试。
Phase 4：`INVALIDATED` 路径 + 旁路/双事务/降级 → 定向证据。
Phase 5：全量 pytest + `state_sync` + CHANGELOG/交接；不 commit。