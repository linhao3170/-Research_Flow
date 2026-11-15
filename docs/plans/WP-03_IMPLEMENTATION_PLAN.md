# WP-03 实施方案与测试/证据计划（草案 v0.1）

> 状态：**PROPOSED（未获实施批准）**｜日期：2026-11-12｜阶段：T0
> 依据：用户 2026-11-12 指令“按 C→B 顺序推进”；P1–P8 设计件已验收；`docs/design/05_CONTRACTS_AND_STATES.md` §9、`docs/design/06_DATA_AND_API.md` §1–§5、`docs/design/07_T0_PLAN_AND_GATES.md` §2.3、`ADR-005`、`design/pseudocode/M02_state_machine/`。
> 边界：本文件是**计划**，不是实现，不是 WP-03 开工授权。未满足 §11.3 第 3/4/6 条前，不得创建 WP-03 代码、数据库或迁移。

## 1. 目标与出口

### 1.1 目标

把“状态只能由 StateMachine 改变”落成可运行、可测试、可审计的 T0 最小持久层：

1. SQLite 迁移脚本与 `schema_migrations`；
2. `StateMachine.transition()` 唯一写入口；
3. 成功迁移同事务写 `audit_log(result=OK)`；
4. 失败迁移回滚后，独立事务写 `audit_log(result=DENIED)`；
5. 直接写库/旁路写状态被拒绝；
6. `INVALIDATED → READY` 三条件守卫；
7. 幂等创建：同键同体返回原任务，同键异体 409；
8. API 从 `_EphemeralTaskRegistry` 切换到 SQLite 持久层，保持既有 201/409/422/404 契约。

### 1.2 出口（对照 ⑦ §2.3）

- 合法迁移成功并写 `OK` 审计；
- 非法迁移/旁路写库被拒；
- 失败迁移回滚后 `DENIED` 记录仍存在（真实 SQLite，不用 mock/内存库替身）；
- 审计二次失败降级结构化 stderr，且测试捕获；
- `INVALIDATED` 两条边按守卫执行；
- `pytest` 全量通过，日志、退出码、解释器路径齐全。

## 2. 前置条件与待裁决项

### 2.1 硬前置

| # | 条件 | 当前状态 |
|---:|---|---|
| 1 | P2 设计件验收 | 已完成（2026-11-12，设计件） |
| 2 | §12-2/§12-6/§12-7/§12-8 裁决并写入 M02 `DECISIONS`/ADR | **未完成** |
| 3 | P9 并发重写产物处置，不作为 WP-03 输入 | **未完成**（P9 `BLOCKED`） |
| 4 | 用户明确下达 WP-03 指令 | **未下达** |
| 5 | `BLK-003` 状态保留并说明测试环境限制 | 已保留；workspace-write 下测试可能受 ACL 影响 |

### 2.2 建议裁决口径（来自 `reports/remediation/P0_REMEDIATION_PLAN.md` §6.2，待用户批准）

| 项 | 建议 |
|---|---|
| §12-2 创建入口 | `StateMachine.create_initial()` 统一写 Task/Node 初始行 + 初始审计；API/Service 只调用该入口，不直接 `INSERT`。 |
| §12-6 `BLOCKED` 终态 | T0 视为终态；解除阻塞需新 ADR，不在 M02 私自加边。 |
| §12-7 `idempotency_keys.task_id` | `NOT NULL` + FK + 与任务同事务；不支持“先占键后建任务”。 |
| §12-8 幂等键字符集 | 1–255 个可见 ASCII（`0x21–0x7E`），无空白；空键 422 `SCHEMA_INVALID`。 |
| JCS 请求哈希 | 采用 RFC 8785 JCS；WP-02 的内存存根不保留历史键，切换无迁移负担。 |
| DB 路径 | WP-03 由调用方注入（测试用 `tmp_path`，运行用环境/配置注入）；不新增未冻结配置键，也不在代码里写死用户目录。 |
| Evidence 状态列 | 维持 `OQ §12-1`：WP-03 不加列；WP-07 前另行裁决。 |
| 404 映射 | 维持 `§12-9` 待裁决；WP-03 不改变现有 GET 404 结构。 |

## 3. 范围与文件清单

### 3.1 新增文件（建议）

| 文件 | 作用 |
|---|---|
| `researchflow/persistence/__init__.py` | 包入口 |
| `researchflow/persistence/db.py` | 连接工厂：WAL、`foreign_keys=ON`、`busy_timeout`、显式事务；不接受全局连接 |
| `researchflow/persistence/schema_sql.py` | WP-03 最小 DDL：`tasks`、`nodes`、`audit_log`、`idempotency_keys`、`schema_migrations`；只追加表触发器 |
| `researchflow/persistence/migrations.py` | 版本清单、`MigrationRunner.upgrade()`、全有或全无、只向前 |
| `researchflow/persistence/repositories.py` | Task/Node/Audit 仓储；公开只读查询，写方法私有 + capability |
| `researchflow/persistence/idempotency.py` | 幂等键查询/预留/冲突；JCS 请求哈希 |
| `researchflow/orchestration/__init__.py` | 包入口 |
| `researchflow/orchestration/transitions.py` | Task 9 / Node 10 迁移表、角色、守卫、失败码；T1 Recovery 禁令 |
| `researchflow/orchestration/state_machine.py` | `transition()` 唯一写入口；校验顺序、守卫、事务、审计、降级 |
| `researchflow/orchestration/invariants.py` | I-01–I-08 可调用断言；I-09–I-14 落点登记 |
| `researchflow/orchestration/boot_recovery.py` | 最小重启恢复：RUNNING 无活动 attempt → FAILED；**建议作为 WP-03b，是否纳入本轮由用户裁决** |
| `researchflow/contracts/encoding.py` | RFC 8785 JCS 规范化；`canonical_bytes()` / `hash_payload()` |
| `researchflow/contracts/errors.py` | 13 个冻结错误码常量与 HTTP 映射（不新增第 14 码） |

### 3.2 修改文件

| 文件 | 改动 |
|---|---|
| `researchflow/api/app.py` | 以可注入的持久层服务替换 `_EphemeralTaskRegistry`；保留 201 三字段、409、422、GET 结构、`/healthz`、`/readyz`、`POST /recover` 404。 |
| `tests/test_api_422.py` / `tests/test_api_idempotency.py` | 仅做必要的适配；不得降低断言强度。 |
| `tests/test_contract_models.py` | 不变；WP-03 不改契约模型。 |

### 3.3 新增测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_persistence_migrations.py` | 建库、重复迁移、失败回滚、`schema_migrations` |
| `tests/test_state_machine.py` | 合法迁移、非法边、过期 `previous_state`、角色拒绝、缺参数 |
| `tests/test_audit_dual_transaction.py` | OK 同事务、DENIED 回滚后仍存在、二次失败 stderr |
| `tests/test_direct_write_guard.py` | 直接 SQL 更新状态被触发器/仓储拒绝 |
| `tests/test_invalidated_guard.py` | 计划缺失、哈希不符、冻结晚于重跑三条负例 |
| `tests/test_idempotency_sqlite.py` | 同键同体、同键异体、并发顺序 |
| `tests/test_jcs.py` | 键序、astral 字符、数组不排序、NEG-M02-54 |
| `tests/test_api_sqlite.py` | 创建/重放/409/422/GET/重启后读取 |

### 3.4 禁止修改

- `contracts/**`、`docs/design/**`、`docs/ADR/**`、`docs/PRD/**`、`docs/G0/**`：冻结件。
- `docs/state/project_state.json` 的运行时状态语义；不得把研发看板状态写入运行时 DB。
- `design/pseudocode/**`：设计件只读；实现不得反向改设计来“对齐代码”。

## 4. 分阶段实施

### Phase 0：裁决与计划批准（不写代码）

1. 用户批准 §12-2/§12-6/§12-7/§12-8（或给出替代口径），并记录到 M02 `DECISIONS`/ADR。
2. 用户处置 P9/P10，明确不作为 WP-03 输入。
3. 用户明确下达 WP-03 指令。
4. 本计划与 diff 清单获批准。

**停止点：以上任一未满足，停止，不创建文件。**

### Phase 1：JCS + 错误码 + 最小 DDL/迁移

- 实现 `researchflow/contracts/encoding.py`：RFC 8785 JCS 最小完整子集；用固定向量测试对象键序（UTF-16 码元）、数组保序、astral 字符。
- 实现 `researchflow/contracts/errors.py`：13 个冻结码 + HTTP 映射；不新增码。
- 实现 `schema_sql.py`：WP-03 最小五表 + 索引 + 只追加触发器；DDL 与 06 §1.3 逐列对应。
- 实现 `migrations.py`：`schema_migrations(version, applied_at, checksum)`；`upgrade()` 只向前、全有或全无。
- 测试：新库迁移、空库重复迁移、失败迁移回滚。

**检查点：DDL 与 06 逐列 diff；JCS 向量通过；不碰 StateMachine。**

### Phase 2：仓储 + `create_initial` + 幂等

- 实现 `repositories.py`：Task/Node/Audit 只读查询；写方法私有 + capability；禁止公开 setter。
- 实现 `create_initial()`：Task/Node 初始行 + 初始审计同事务；只允许 `CREATED` / `PLANNED`；重复创建冲突。
- 实现 `idempotency.py`：`idempotency_keys` 插入 + `tasks` 插入同事务；同键同体返回原任务；同键异体 409；不覆盖旧 `request_hash`。
- 改 `researchflow/api/app.py`：使用持久层服务；保留 201/409/422/404。
- 测试：幂等 A–E、API 回归、JCS 键序。

**检查点：API 全量回归；`_EphemeralTaskRegistry` 删除或仅测试替身。**

### Phase 3：迁移表 + `transition()`

- 实现 `transitions.py`：Task 9 / Node 10 完整迁移表；角色允许集；守卫 ID；失败码；T1 Recovery 禁令。
- 实现 `state_machine.py`：
  1. 校验参数/角色/边/`previous_state`（只读）；
  2. 校验守卫（只读；含 plan_hash 三条件）；
  3. `BEGIN IMMEDIATE`；
  4. 事务内重读状态，防 TOCTOU；
  5. 如 `VERIFIED→INVALIDATED`：先追加 `evidence_invalidations`；
  6. 先插入 `audit_log(result=OK)`；
  7. `UPDATE ... WHERE state = :expected_from`；受影响行数必须为 1；
  8. `COMMIT`。
- WP-03 只实现不依赖后续 WP 端口的迁移；依赖 Gate/Report/Certificate/Evidence 端口的迁移，端口缺失时 fail-closed 拒绝，不得伪造 PASS。
- 测试：合法迁移、非法边、过期状态、角色拒绝、缺参数、端口缺失拒绝。

**检查点：每条拒绝断言错误码/reason；不得只断言“抛异常”。**

### Phase 4：双事务审计 + 旁路防护

- 成功：状态更新 + `OK` 审计同事务；任何一步失败全回滚。
- 失败：状态事务回滚 → **新事务**写 `DENIED`；字段含 `previous_state`、`next_state`、`actor`、`reason_code`、`rule_version`、`correlation_id`、`error_code`。
- 二次失败：单行结构化 stderr（含 `audit_write_failed=true`），抛 `AuditWriteFailed`；不得静默吞掉。
- 旁路防护：仓储无公开写方法；DB 触发器要求状态更新必须带同事务 `OK` 审计；测试直接 SQL `UPDATE` 必须被拒。
- 测试：`DENIED` 回滚后仍存在；二次失败 stderr；直接写库被拒。

**检查点：真实 SQLite 文件、WAL；不用 mock 证明事务。**

### Phase 5：`INVALIDATED` 守卫 + 重启恢复（可选）

- 三条守卫：计划文件存在、`sha256(文件字节)==plan_hash` 且与 `audit_log` 冻结记录一致、冻结早于重跑。
- WP-03 用临时内容寻址目录测试；WP-R 接入真实 PlanStore。
- `boot_recovery` 最小实现：`RUNNING` 无活动 attempt → `FAILED`；绝不默认 `COMPLETED`；**是否纳入 WP-03 由用户裁决**，否则标 WP-03b。
- 测试：三条守卫各失败一次；重启不伪造完成。

### Phase 6：回归、证据、状态

- 运行全量 pytest（workspace-write 若受 `BLK-003` 影响，按项目规则记录，不改用 full-access 冒充通过）。
- 保存日志到 `docs/verification/t0/wp-03/`。
- 更新 `project_state.json`：新增 `T-WP-03-001`，状态按真实结果；未完成项不得标 `DONE`。
- 追加 `CHANGELOG_DEV.md`、更新 `SESSION_HANDOFF.md`；不自动 commit。

## 5. 测试矩阵（最低要求）

| 类别 | 用例 | 通过条件 |
|---|---|---|
| 迁移 | 新库建表 | 五表 + 索引存在；`schema_migrations` 有 1 条 |
| 迁移 | 重复 `upgrade()` | 幂等，无重复行 |
| 迁移 | 注入失败 DDL | 全回滚；无半张表；`schema_migrations` 不前进 |
| 迁移 | `DOWN`/降级 | 不提供破坏性降级；只向前 |
| 状态机 | Task `CREATED→PLANNING` | 成功；`audit_log(result=OK)` 同事务 |
| 状态机 | 非法边（如 `CREATED→COMPLETED`） | `STATE_TRANSITION_DENIED`，reason 正确 |
| 状态机 | 过期 `previous_state` | 拒绝；事务内重读 |
| 状态机 | 缺 `rule_version`/`correlation_id` | 拒绝；字段路径/原因正确 |
| 状态机 | 非写者角色 | 拒绝；角色原因正确 |
| 审计 | 失败迁移 | 状态回滚；`DENIED` 仍在 |
| 审计 | 二次审计失败 | stderr 单行 JSON；`audit_write_failed=true` |
| 旁路 | 直接 SQL 更新状态 | 触发器/仓储拒绝；无审计则不改 |
| 守卫 | `INVALIDATED→READY` 三条件 | 三条各失败一次，均拒绝 |
| 幂等 | 同键同体 | 201 + 同 `task_id`；无第二条任务 |
| 幂等 | 同键异体 | 409 `IDEMPOTENCY_CONFLICT`；旧哈希不被覆盖 |
| JCS | 键序/astral/数组 | `canonical_hash` 相等/不等符合预期 |
| API | 创建/重放/GET/422 | 201/201/200/422；响应字段不变 |
| API | 重启后读取 | 同一 SQLite 文件重启后任务仍在 |
| 恢复 | RUNNING 无 attempt | 明确 `FAILED`，绝不 `COMPLETED` |

每个负例必须断言**拒绝原因**（错误码、reason、field_path 或具体守卫），不能只断言“被拒绝”。

## 6. 证据要求

- 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（3.11.16 / 64bit）。
- 建议命令（按实际文件名调整）：
  - `& .venv/Scripts/python.exe -m pytest tests/test_persistence_migrations.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -m pytest tests/test_state_machine.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -m pytest tests/test_audit_dual_transaction.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider`
- 日志路径：`docs/verification/t0/wp-03/`，至少包含 `transitions.jsonl`、`illegal.log`、`direct_write.log`、`audit_log.jsonl`、`denied_survives_rollback.log`、`audit_degraded_stderr.log`、`invalidated_guard.log`。
- 证据必须包含命令、解释器、退出码、测试数、失败数、运行时间；不得只保存摘要。

## 7. 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| JCS 实现不完整 | 幂等哈希错误；同键同体误判 409 | 固定向量 + NEG-M02-54；不引入未批准依赖 |
| SQLite 事务/WAL 在 Windows 的锁行为 | 并发创建偶发 `database is locked` | `busy_timeout`、`BEGIN IMMEDIATE`、短事务；测试并发顺序 |
| 双事务审计写错 | 失败无审计 | ADR-005 口径；真实 SQLite 负例 |
| 直接写库绕过 | 状态不可信 | 仓储私有写 + 触发器 + 测试 |
| `BLK-003` workspace-write ACL | 测试无法在受限沙箱运行 | 保留状态；不把 full-access 结果写成 workspace-write 通过 |
| API 存根切换 | 201/409/422 回归 | 保留现有测试并加强断言 |
| 范围蔓延 | 把 WP-04/06/07 的逻辑提前实现 | 只做 WP-03；端口缺失 fail-closed |

## 8. 停止条件

出现以下任一情况，停止并报告，不自行扩大范围：

- §12-2/§12-6/§12-7/§12-8 未裁决，或用户未下达 WP-03 指令；
- 需要修改冻结契约、05/06/ADR、PRD/G0；
- 需要新增依赖、联网、改系统配置或读取凭据；
- 测试失败原因未定位，或需要修改 expected/阈值才能通过；
- 发现 P9/P10 产物被当作 WP-03 输入；
- 发现直接写库无法被阻止，或审计二次失败被静默吞掉；
- `BLK-003` 被误写成已关闭。

## 9. Diff 计划（待批准）

```text
新增：
  researchflow/persistence/{__init__,db,schema_sql,migrations,repositories,idempotency}.py
  researchflow/orchestration/{__init__,transitions,state_machine,invariants,boot_recovery}.py
  researchflow/contracts/{encoding,errors}.py
  tests/test_{persistence_migrations,state_machine,audit_dual_transaction,direct_write_guard,invalidated_guard,idempotency_sqlite,jcs,api_sqlite}.py
  docs/verification/t0/wp-03/...

修改：
  researchflow/api/app.py（替换临时注册表，保留契约）
  tests/test_api_422.py、tests/test_api_idempotency.py（仅必要适配）
  docs/state/project_state.json（新增 T-WP-03-001，按真实证据）

不改：
  contracts/**、docs/design/**、docs/ADR/**、docs/PRD/**、docs/G0/**
  design/pseudocode/**（只读）
```