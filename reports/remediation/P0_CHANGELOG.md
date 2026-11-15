# ResearchFlow 3.1 · P0 整改变更记录（P0_CHANGELOG）

> 日期：2026-11-11（Asia/Shanghai）
> 工作区：`D:\ResearchFlow-project`
> 基线：`main` / HEAD `309083e715cb59a1f0c181d95df44e1946ffbaa5` / 7 commits
> 状态：**整改执行完成待复核；未 commit；未清理临时文件；D/G/H 未获最终授权**
> 依据：用户 2026-11-11 P0 整改授权 A–J；执行顺序 A → E → B → C/F/I → D/G 记录 → 报告。

## 1. 执行边界

- 未修改 `contracts/**`、`docs/design/**`、`docs/G0/**`、`docs/PRD/**`、`docs/ADR/**` 的冻结内容。
- 未进入 WP-03；未创建 SQLite 数据库、迁移或 StateMachine 运行时代码。
- 未安装/升级依赖；未执行 `git add`、`git commit`、`git reset`、`git clean`。
- 未删除任何缓存、临时目录或未跟踪文件。
- `last_verified_commit` 保持 `1c9a10461c50c02058ce28be8b4b09c0c8870e80`，未擅自推进。

## 2. A · API 幂等响应修复

### 2.1 问题

`POST /api/v1/tasks` 首次创建返回 06 §4.2 的三字段公共响应：
`{task_id, state, graph_version}`；同键同体重放却返回内部记录（额外含 `spec`）。
同一请求的首次与重放响应体不一致，违反 06 §4.5“同键同体返回原任务”的语义。

### 2.2 修改

文件：`researchflow/api/app.py`

- 新增冻结的 `_TaskRecord` 内部记录类型，仅用于 `GET /api/v1/tasks/{id}`。
- 新增 `_TaskRecord.public_creation_receipt()`，统一生成三字段 201 回执。
- `_EphemeralTaskRegistry` 分离 `_tasks`（内部记录）与 `_idempotency`（请求哈希 + 公共回执）。
- 新增 `threading.Lock` 与 `register()`：把“查重放 → 写内部记录/幂等记录”放入同一临界区；只在单进程内保证原子，不宣称多进程安全。
- `create_task` 保持原 422 顺序：严格 JSON 解析 → `TaskSpecCreate` 校验 → 幂等处理。
- `GET /api/v1/tasks/{id}` 结构未改：仍返回 `task_id/state/graph_version/spec`。
- 未新增 `Location`、`Idempotency-Replayed` 等未冻结头。

### 2.3 新增测试 A–E

文件：`tests/test_api_idempotency.py`

| 测试 | 断言 |
|---|---|
| A | 首次/重放 201；`first.content == second.content`；`first.json() == second.json()`；`task_id/graph_version/state` 各自相等 |
| B | 同键异体 409 `IDEMPOTENCY_CONFLICT`；响应无 `spec`；原体再次提交仍 201 且返回首次任务；首次任务 GET 200 |
| C | 不同键同体创建两个不同 `task_id`；两个 GET 均 200 |
| D | 首次/重放键集合严格等于 `{task_id,state,graph_version}`；无 `spec`；内容逐字节一致 |
| E | 同键同体连续 10 次全部 201；`task_id` 唯一；响应体逐次完全一致；docstring 明确只验证单进程 |

### 2.4 验证结果

| 命令 | 结果 | 日志 |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest tests/test_api_422.py tests/test_api_idempotency.py -q -p no:cacheprovider` | `18 passed`，exit 0 | `reports/remediation/logs/10_api_pytest_before_fullaccess.log` |
| `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`（受控 full-access） | `140 passed`，exit 0 | `reports/remediation/logs/21_full_pytest_fullaccess.log` |

## 3. E · 受控 full-access 全量测试

- 命令：`& .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
- 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（3.11.16 / 64bit / SQLite 3.53.1 / pytest 9.2.0）
- 时间：2026-11-11 22:54:54–22:55:00（约 6.73 s）
- 退出码：0；结果：`140 passed`
- 前后 Git 状态一致；项目内未新增临时目录；`.pytest_cache`、`__pycache__`、`tmp/unittest-temp` 文件数/字节数未变。
- `BLK-003` **仍为 OPEN**：full-access 成功不代表 workspace-write 阻塞关闭；未修改 `project_state.json` 的 blocker 状态。
- 未安装/升级依赖；测试未触发项目源码或契约修改。

## 4. B · P1–P10 独立阶段注册表

- `docs/state/project_state.json` 新增 `pseudocode_stages`，与 `tasks`、`stage_gates` 分离。
- 状态枚举严格为：`NOT_STARTED`、`IN_PROGRESS`、`IN_REVIEW`、`BLOCKED`、`ACCEPTED`、`DEFERRED`。
- 当前：P1 `ACCEPTED`；P2–P8 `IN_REVIEW`；P9/P10 `BLOCKED`。
- `scripts/state_sync.py` 新增：
  - `PSEUDOCODE_STAGE_STATUSES` / `PSEUDOCODE_STAGE_IDS`；
  - 结构、枚举、P1–P10 完整性、重复 ID、模块目录存在性、交付物/证据路径存在性校验；
  - `ACCEPTED` 必须有证据路径与验收依据；`BLOCKED` 必须有阻塞原因；
  - `PROJECT_STATE.md` 与 `IMPLEMENTATION_STATUS.md` 渲染“伪代码阶段”段。
- `tests/test_state_sync.py` 新增 8 个阶段校验/渲染测试；`31 passed`，exit 0。
- B 完成后 API 422 + A–E + state_sync 定向回归：`49 passed`，exit 0；未再跑第二次全量（用户只批准一次 full-access 全量）。
- `T-PSEUDO-001` 标题改为 P1–P10，状态保持 `IN_REVIEW`；阶段细节由注册表承载。

## 5. C · P1 历史决议缺口

- `OQ-P1-03`、`OQ-P1-05` 从 `DECIDED` 改为 `NEEDS_CONFIRMATION`。
- 未编造原问题、未推测用户曾批准的内容、未保留“已决议”表述。
- 同步修改：
  - `design/pseudocode/00_BASELINE/PHASE_RULES.md` §8：新增 `NEEDS_CONFIRMATION` 定义；
  - `design/pseudocode/OPEN_QUESTIONS.md` 表头与两行；
  - `design/pseudocode/M01_contracts/MODULE.md` §8；
  - `design/pseudocode/M03_config_env/MODULE.md` §8；
  - `design/pseudocode/STAGE_LOG.md` P1 条目。
- `PHASE_RULES` 的 `NEEDS_CONFIRMATION` 只表示“曾声称已裁决但证据不可恢复”，不等于 `OPEN`，不得作为先例。

## 6. F · P9 缺口与并发重写产物

- 基线（22:53:44）时 P9 仅有 5 文件 / 1,404 行；M15 缺 4 个 `.py`，M16 缺 2 个 `.py`。
- 22:53:54–55 发现并发进程重写并落盘 6 个 `.py`、4 份模块文档与 3 份阶段索引文档；**不是原始正文恢复**。
- 未删除、未覆盖、未把重写产物标为 `ACCEPTED`；P9 在状态源中标 `BLOCKED`。
- 逐项时间、SHA256、行数、原声明行数与当前行数对比见 `P0_OPEN_ISSUES.md`。
- `INDEX.md` 修正 P9 文件数/行数与模块表；`STAGE_LOG.md` 追加 P9 复核修正、P7/P8 补登、P10 登记。
- `M15/M16 MODULE.md` 加并发重写横幅，并把“完成（伪代码）”改为“存在（并发重写，未测试）”。
- `M04–M11` 等模块前置条件中的“P2/P3/P4/P5 已验收”改为“设计产物存在；验收状态以 `project_state.json` 为准”。

## 7. G · P10/M19 现状登记

- 现有 5 个 `.py` / 2,138 行；无 `MODULE.md`、`NEGATIVE_TESTS.md`、阶段日志或 OQ。
- 未跟踪目录 `design/pseudocode/M19_api/`；无 Git 对象。
- 依赖：`researchflow.contracts.parsing`，以及同目录 `error_map`、`middleware_idempotency`、`routes_tasks`。
- P10 在注册表标 `BLOCKED`，原因：“用户尚未确认 M19 是否为授权产物；暂缓扩大 P10 开发范围”。
- 未删除、未移动、未标 `ACCEPTED`。

## 8. I · 非冻结文档现状修正

| 文件 | 变更 |
|---|---|
| `README.md` | 当前阶段改为 T0；G0 PASS、G1–G7 NOT_STARTED；目录/环境/当前不能做什么 |
| `docs/DEVELOPMENT_WORKFLOW.md` | G0/commit/WP-03 入口/状态词汇更新；阶段 7/8 约束标为历史 |
| `docs/SESSION_HANDOFF.md` | 置顶新增本轮交接；旧条目保留 |
| `AGENTS.md` | 仅版本元数据；未改规则正文 |
| `docs/PROJECT_OVERVIEW.md` | G0 现状、实现状态表、P9/P10 说明 |
| `docs/ARCHITECTURE.md` | G0 PASS、依赖已锁定、实现状态表；G0 缺口标历史 |
| `docs/state/G0_DECISION_LIST.md` | 顶部历史横幅；原表与历史规则保留 |

未改写冻结架构、未改写历史决议正文、未把未验收功能写成已实现。

## 9. D · 未决裁决

本轮只形成方案，未写入正式决议。详见 `P0_OPEN_ISSUES.md` §2：

- §12-2：核对后确认 P2 当前**没有** `StateMachine.create_initial()`；`PUBLIC_WRITE_ENTRYPOINTS` 只有 `transition`，`TaskRepository._insert_created` / `NodeRepository._insert_planned` 由 capability 保护。方案 A（StateMachine 统一创建 + 单事务）与方案 B（独立 CreationPort）均已列出，未生效。
- §12-6、§12-7、§12-8：仅列 A/B、影响与建议，等待用户单独批准。

## 10. H / J · 未执行事项

- **H 未执行**：未 commit；未修改 `last_verified_commit`。
- **J 未执行**：未删除 `.pytest_cache`、`__pycache__`、`tmp/unittest-temp` 或其他临时目录。
- 本轮只记录，不清理。

## 11. 文件级变更清单

### 已跟踪文件（会出现在 `git diff`）

- `researchflow/api/app.py`
- `tests/test_state_sync.py`
- `scripts/state_sync.py`
- `docs/state/project_state.json`
- `docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`（生成）
- `design/pseudocode/INDEX.md`、`STAGE_LOG.md`、`OPEN_QUESTIONS.md`
- `design/pseudocode/00_BASELINE/PHASE_RULES.md`
- `design/pseudocode/M01_contracts/MODULE.md`、`M03_config_env/MODULE.md`
- `design/pseudocode/M04_dag/MODULE.md`、`M05_executor/MODULE.md`、`M06_templates/MODULE.md`、`M07_evidence/MODULE.md`、`M08_gate/MODULE.md`、`M09_verifier_l12/MODULE.md`、`M10_verifier_l3/MODULE.md`、`M11_signing/MODULE.md`
- `README.md`、`AGENTS.md`、`docs/DEVELOPMENT_WORKFLOW.md`、`docs/SESSION_HANDOFF.md`
- `docs/PROJECT_OVERVIEW.md`、`docs/ARCHITECTURE.md`、`docs/state/G0_DECISION_LIST.md`
- `docs/CHANGELOG_DEV.md`

### 未跟踪文件（不 `git add`）

- `design/pseudocode/M13_scheduler/`、`M14_recovery/`、`M15_dcspa/`、`M16_vas/`、`M17_agents/`、`M18_knowledge/`、`M19_api/`
- `reports/remediation/`（本轮报告、日志、Diff、备份）
- `tests/test_api_idempotency.py`（新文件，未 `git add`）

## 12. 架构变化

**无架构变化。** 本轮是 API 实现修正、状态注册表、状态/文档一致性与测试证据；未修改冻结契约定义的 API 形状、状态迁移规则、证据/验证/签名边界。P9 的并发重写产物未获验收，不构成实现完成声明。

## 13. 遗留风险（摘要）

1. P9 并发重写产物来源/版本未确认，P9 仍 `BLOCKED`。
2. P10/M19 未获开发授权，P10 仍 `BLOCKED`。
3. §12-2/§12-6/§12-7/§12-8 未裁决，WP-03 不得启动。
4. `BLK-003` 仍 `OPEN`；full-access 测试不能关闭 workspace-write 阻塞。
5. `last_verified_commit` 与 HEAD 不一致；未 commit。
6. GET `/tasks/{id}` 的 `spec` 契约未澄清；幂等键字符集/JCS 未裁决。
7. `OQ-P1-03/05` 仍需用户补证或确认无法恢复。