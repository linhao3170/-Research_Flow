# ResearchFlow 3.1 · P0 整改执行计划

> 依据：`reports/remediation/P0_AUDIT_REPORT.md`（2026-11-11）
> 状态：**待用户批准，尚未执行**
> 约束：不改变冻结架构、不改变冻结 API 契约、不提前开发 WP-03、不编造历史决议、不做破坏性 Git 操作。
> 预期最终结果：核心整改完成时为 `PASS WITH WARNINGS`；若关键裁决未获批准，则为 `BLOCKED`；不把 P0 整改 PASS 等同于 G1 PASS。

---

## 1. 执行原则

1. **先备份，后修改。** 修改前记录 HEAD、`git status`、文件清单与 SHA256；把将修改的文件复制到 `reports/remediation/backup_before/`，并保存 `git diff > reports/remediation/backup_before/baseline.patch`。
2. **不覆盖用户未提交修改。** 当前 3 个已修改文件与 7 个未跟踪目录全部保留；每次编辑基于当前内容做精确 `edit`，不做整文件回退。
3. **不做破坏性 Git 操作。** 不执行 `git reset --hard`、`git clean -fd`、`git checkout --` 覆盖；不自动 commit。
4. **冻结件只读。** `contracts/**`、`docs/design/**`、`docs/ADR/**`、`docs/G0/**`、`docs/PRD/**` 不修改；如发现冲突，只登记并请求裁决。
5. **不降标准。** 不删除失败测试、不放宽断言、不改 expected/负例/阈值来获得 PASS。
6. **不把设计写成实现。** 缺失的 P9 伪代码不补写成“已完成”；P10 只登记现状。
7. **每阶段结束输出阶段报告并停止**，不自动进入下一阶段。

---

## 2. 阶段 0：基线冻结与备份（批准后第一步）

### 2.1 记录

```powershell
git status --porcelain=v1            # 保存到 backup_before/git_status_before.txt
git rev-parse HEAD                   # 保存到 backup_before/head_before.txt
git diff > reports/remediation/backup_before/baseline.patch
git diff --stat > reports/remediation/backup_before/baseline_diffstat.txt
```

### 2.2 复制备份

将以下文件复制到 `reports/remediation/backup_before/`（保持相对路径）：

- `researchflow/api/app.py`
- `tests/test_api_422.py`
- `docs/state/project_state.json`
- `design/pseudocode/INDEX.md`
- `design/pseudocode/STAGE_LOG.md`
- `design/pseudocode/OPEN_QUESTIONS.md`
- `design/pseudocode/M01_contracts/MODULE.md`
- `design/pseudocode/M02_state_machine/MODULE.md`
- `design/pseudocode/M03_config_env/MODULE.md`
- `design/pseudocode/M13_scheduler/MODULE.md`
- `design/pseudocode/M14_recovery/MODULE.md`
- `design/pseudocode/M15_dcspa/MODULE.md`
- `design/pseudocode/M16_vas/MODULE.md`
- `design/pseudocode/M17_agents/MODULE.md`
- `design/pseudocode/M18_knowledge/MODULE.md`
- `README.md`
- `docs/DEVELOPMENT_WORKFLOW.md`
- `docs/SESSION_HANDOFF.md`
- `AGENTS.md`
- `docs/PROJECT_OVERVIEW.md`
- `docs/ARCHITECTURE.md`
- `docs/state/G0_DECISION_LIST.md`
- `docs/verification/t0/wp-02/40_wp02_acceptance.md`

### 2.3 基线与回滚

- `baseline.patch` 只覆盖已跟踪文件的未提交修改；未跟踪的 M13–M19 目录用文件副本备份，不压缩、不移动。
- 回滚方式：对单个文件使用备份副本恢复；不使用 `git reset`/`git clean`。
- 任何删除操作前，重新解析绝对路径并确认目标；删除清单写入 `P0_CHANGELOG.md`。

---

## 3. 阶段 2：修复 WP-02 API 幂等（RF-API-01）

### 3.1 修改文件

- `researchflow/api/app.py`
- `tests/test_api_422.py`（或新增 `tests/test_api_idempotency.py`，推荐后者以避免 422 测试文件过长；若新增，需在 WP-02 验收记录中登记）

### 3.2 代码修改设计（不改变冻结契约）

**目标：** 首次创建与同键同体重放返回同一公共响应体；内部记录与公共响应分离。

1. 在 `app.py` 增加公共回执构造函数：

```python
def _public_task_response(task_id: str, state: str, graph_version: int) -> dict[str, Any]:
    return {"task_id": task_id, "state": state, "graph_version": graph_version}
```

2. 修改 `_EphemeralTaskRegistry`：
   - `_tasks` 继续保存内部记录（含 `spec`），仅供 `GET /tasks/{id}` 使用；
   - `_idempotency` 保存 `(request_hash, public_body)`，不再保存内部记录；
   - `idempotent_replay(key)` 只按 key 取 `(hash, public_body)`；
   - `remember(...)` 同时接收 `record` 与 `public_body`；
   - 增加 `threading.Lock`（或等价单进程锁），把“查重放 → 生成 task_id → 写内部记录/幂等记录”放在同一个临界区，保证单进程内重复提交原子；**不在文档中宣称多进程安全**。

3. 修改 `create_task`：
   - 422 校验顺序不变（严格解析 → TaskSpec → 幂等键处理）；
   - 在锁内：
     - 若重放且哈希相同：返回存储的 `public_body`，201；
     - 若重放且哈希不同：409 `IDEMPOTENCY_CONFLICT`，不创建任务；
     - 否则生成 `task_id`，构造 `spec` 与内部 `record`，构造 `public_body`，`remember` 后返回 `public_body`，201；
   - 首次与重放都只返回 06 §4.2 的三个字段；
   - 不新增 `Location`、`Idempotency-Replayed` 等未冻结头（避免扩大契约）。

4. 不在本阶段修改：
   - `GET /tasks/{id}` 的返回结构（RF-API-04 待契约澄清）；
   - 幂等键字符集/长度（RF-API-02 待裁决）；
   - 请求哈希算法（RF-API-03 待裁决）。

### 3.3 新增测试

在 `tests/test_api_422.py` 追加或新建 `tests/test_api_idempotency.py`：

| 测试 | 断言 |
|---|---|
| A `test_first_and_replay_are_identical` | `first.status_code == second.status_code == 201`；`first.json() == second.json()`；`first.content == second.content`；`task_id` 相同；`graph_version` 相同；`state` 相同 |
| B `test_same_key_different_body_conflicts_without_new_task` | 首次 201；异体 409 + `IDEMPOTENCY_CONFLICT`；再次用原体同键 201 且 `task_id` 与首次相同；首次任务 GET 200；冲突响应不含 `spec` |
| C `test_different_keys_same_body_create_distinct_tasks` | 两个不同键、同一请求体均 201；`task_id` 不同；两个 GET 均 200 |
| D `test_create_response_exposes_only_public_fields` | 首次与重放响应键集合严格等于 `{task_id,state,graph_version}`；无 `spec`、无内部字段 |
| E `test_repeated_submissions_do_not_create_new_tasks` | 同一键同体连续 8–10 次，全部 201，`task_id`/响应体完全一致；docstring 明确“仅验证单进程重复提交，不证明多进程/多 worker 安全” |

可选补充：

- `test_idempotency_does_not_leak_spec_on_conflict`
- `test_422_precedes_409_for_invalid_body`（同键 + 非法体应 422 而不是 409；与 M19/P10 顺序一致，但 06 未明确时仅作为现有行为回归）

### 3.4 验证命令与预期

```powershell
& .venv/Scripts/python.exe -m pytest tests/test_api_422.py -q -p no:cacheprovider
& .venv/Scripts/python.exe -m pytest tests/test_contract_models.py tests/test_api_422.py -q -p no:cacheprovider
& .venv/Scripts/python.exe scripts/validate_contracts.py
```

预期：API 测试原 13 项 + 新增 5 项全部通过；模型 89 项通过；契约 72/72 通过；不出现 422 回归。

### 3.5 修复前后对照（写入 P0_CHANGELOG）

| 场景 | 修复前 | 修复后 |
|---|---|---|
| 首次 201 body | 3 字段 | 3 字段 |
| 同键同体重放 201 body | 4 字段（含 `spec`） | 3 字段，与首次逐字节一致 |
| 同键异体 | 409 | 409（不变） |
| 不同键同体 | 两个任务 | 两个任务（不变） |
| 任务查询 | 内部记录含 `spec` | 不改（待契约澄清） |
| 多进程幂等 | 不保证（内存注册表） | 仍不保证；文档明确，WP-03 用 DB 唯一约束解决 |

### 3.6 验收门槛

- R01 通过：首次与重放响应一致；
- R02 通过：原 422/查询/契约测试不回归；
- 不修改 06/contracts；
- 若发现必须改冻结契约，立即停止并报告。

---

## 4. 阶段 3：统一 P1–P10 伪代码状态（RF-STATUS-01/02、RF-PSEUDO-01/02/03、RF-P10-01）

### 4.1 推荐方案 A：在 `project_state.json` 增加 `pseudocode_stages`

**为什么不选方案 B：** 方案 B（新增 10 个任务）沿用 `BACKLOG/READY/IN_PROGRESS/BLOCKED/IN_REVIEW/DONE/DEFERRED`，无法表达用户要求的 `ACCEPTED`，只能做 `ACCEPTED↔DONE` 映射；阶段状态与研发任务混在同一 `tasks` 数组，容易再次产生“伞形任务 + 多阶段”歧义。

**方案 A 的字段设计（建议）：**

```json
"pseudocode_stages": [
  {
    "stage_id": "P1",
    "title": "契约对齐与配置基座",
    "status": "ACCEPTED",
    "modules": ["M01_contracts", "M03_config_env"],
    "deliverables": ["design/pseudocode/M01_contracts", "design/pseudocode/M03_config_env"],
    "evidence_paths": ["design/pseudocode/STAGE_LOG.md", "design/pseudocode/INDEX.md"],
    "acceptance_basis": "INDEX/STAGE_LOG 记录 2026-11-11 用户验收",
    "blocker": null,
    "updated_at": "2026-11-11T..."
  }
]
```

- `status` 只允许 `NOT_STARTED`、`IN_PROGRESS`、`IN_REVIEW`、`BLOCKED`、`ACCEPTED`、`DEFERRED`。
- `stage_id` 唯一，允许 P1–P10；`modules` 必须指向存在的目录；`evidence_paths` 必须指向存在的文件（P9 缺失文件不能写入 `deliverables`）。
- `blocker` 非空时，`status` 必须为 `BLOCKED` 或 `IN_PROGRESS`，并在 `acceptance_basis` 说明缺口。
- 扩展 `scripts/state_sync.py`：
  - `TOP_LEVEL_ALLOWED_FIELDS` 增加 `pseudocode_stages`（建议设为可选，避免破坏现有测试夹具；实际状态文件必须包含）；
  - 增加 `validate_pseudocode_stages()`：唯一性、枚举、路径存在性、ACCEPTED 必须有 evidence、BLOCKED 必须有 blocker；
  - `render` 增加“伪代码阶段”表到 `docs/PROJECT_STATE.md` 与 `docs/IMPLEMENTATION_STATUS.md`；
  - `check` 继续逐字节校验生成文件。
- 扩展 `tests/test_state_sync.py`：新增阶段校验正/负例（重复 stage_id、非法状态、ACCEPTED 无 evidence、BLOCKED 无 blocker、路径不存在）。
- 注意：`tests/test_state_sync.py` 当前在 workspace-write 下因 BLK-003 无法运行；新增测试需在 full-access 批准运行或等环境修复后才能验证。不得因此删除测试。

### 4.2 P1–P10 目标状态（批准后写入）

| 阶段 | 模块 | 目标状态 | 依据/缺口 |
|---|---|---|---|
| P1 | M01、M03 | **ACCEPTED** | 2026-11-11 用户验收；OQ-P1-03/05 待补证，不影响 P1 已验收事实，但需在阶段记录中注明 |
| P2 | M02 | **IN_REVIEW** | 产物齐全；未用户验收；§12-2 等 WP-03 前置问题未决 |
| P3 | M04、M05 | **IN_REVIEW** | 产物齐全；未用户验收；OQ OPEN |
| P4 | M06、M07 | **IN_REVIEW** | 产物齐全；未用户验收；E3 路径未实现 |
| P5 | M08、M09、M10 | **IN_REVIEW** | 产物齐全；未用户验收；OQ OPEN |
| P6 | M11、M12 | **IN_REVIEW** | 产物齐全；未用户验收；签名口径未定 |
| P7 | M13、M14 | **IN_REVIEW** | 产物齐全（11 文件/6,576 行）；无 STAGE_LOG；未验收 |
| P8 | M17、M18 | **IN_REVIEW** | 产物齐全（15 文件/9,361 行）；无 STAGE_LOG；未验收 |
| P9 | M15、M16 | **IN_PROGRESS** | 缺 6 个 `.py`；5 文件/1,404 行；不能验收；blocker 写清缺失清单 |
| P10 | M19 | **IN_PROGRESS** | 仅 5 个 API `.py`；缺 MODULE/NEGATIVE/日志/OQ；未登记 |

**不得**把 P2–P10 任何阶段标为 `ACCEPTED`，除非用户逐阶段正式验收。

### 4.3 需要同步修改的文件

1. `docs/state/project_state.json`
   - 新增 `pseudocode_stages`；
   - `T-PSEUDO-001` 标题改为“P0 伪代码规格阶段（P1–P10）”，状态保持 `IN_REVIEW`（伞形任务不再承担阶段细节）；
   - `T-PSEUDO-001.blocker` 指向 P9 缺口或改为“见 pseudocode_stages.P9”；
   - `updated_at` 更新。
2. `design/pseudocode/INDEX.md`
   - 模块表增加 M13/M14/M17/M18/M19；
   - 文件数改为实际值；
   - P9 的 6/5 改为 2/3，并注明缺失；
   - 状态列引用 `project_state.json`，不再自行维护“已验收/待验收”口径。
3. `design/pseudocode/STAGE_LOG.md`
   - 补 P7、P8 条目（实际文件/行数、静态自检、未验收）；
   - P9 条目加“2026-11-11 复核修正”：原 11/7,427 为计划口径，实际 5/1,404，缺 6 文件；阶段状态 IN_PROGRESS；
   - P10 条目登记部分产物/缺失文档；
   - 保留原文，追加修正，不删除历史。
4. `design/pseudocode/OPEN_QUESTIONS.md`
   - P1-03/05：按用户指示标 `NEEDS_CONFIRMATION`（若批准；见 §6.1）；
   - P9 条目落点加“文件缺失”备注；
   - 表头行数记录追加 P10/本次复核变化；
   - 不擅自关闭任何 OPEN。
5. `design/pseudocode/M13/M14/M15/M16/M17/M18/.../MODULE.md`
   - 前置条件改为事实性描述：“P2–P4 设计产物存在；验收状态见 `project_state.json`”等；
   - P9 不修改设计内容，只加缺失清单/状态指针。
6. `docs/SESSION_HANDOFF.md`
   - 新增置顶交接，列出 P1–P10 状态、WP-02 修复、BLK-003、下一步与禁止事项；
   - 旧条目保留，标注“历史”。
7. `docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`
   - 只通过 `state_sync.py render` 重新生成，禁止手改。

### 4.4 状态检查

```powershell
& .venv/Scripts/python.exe scripts/state_sync.py validate
& .venv/Scripts/python.exe scripts/state_sync.py render
& .venv/Scripts/python.exe scripts/state_sync.py check
```

三条均需 exit 0；`check` 逐字节一致。

---

## 5. 阶段 4：修复 README 与工程文档

### 5.1 `README.md`

需要改写的段落：

- 顶部状态引用（L5–L7）：改为 G0 PASS、WP-01/WP-02 DONE、P1 ACCEPTED/P2–P8 IN_REVIEW/P9 IN_PROGRESS/P10 IN_PROGRESS、BLK-003 OPEN、下一步 WP-03 前置整改。
- 目录表（L13、L14、L21–L23）：`contracts/` 已有 5 份 schema + 72 例；`researchflow/` 已有模型/API；`docs/PRD`、`docs/design`、`docs/ADR` 已建立。
- 环境节（L57）：`.venv` 已创建（3.11.16/64bit，58 包锁），不再写“未创建/未安装”。
- 当前阶段节（L77–L81）：删除“阶段 7”“未 commit”“未建 .venv”“G0 3 项待裁决”；写入真实状态、WP-02 缺陷与整改、P9 缺口、BLK-003。
- 增加“当前不能做什么”：不得宣称 G1–G7 PASS；不得宣称 WP-03 已实现；不得把伪代码当实现；不得在 workspace-write 未通过时宣称全量测试通过。
- 保留策划书版本决议、DOCX 禁止复制规则、Python 基线。

### 5.2 `docs/DEVELOPMENT_WORKFLOW.md`

- §1 来源优先级：删除“G0 仍有 3 项待裁决”；改为 G0 已于 2026-11-10 PASS，2–4 项已裁决，历史见 `G0_DECISION_LIST`。
- §5.2 “现状”：改为 G0 PASS、G1–G7 NOT_STARTED；不得写“全部 NOT_STARTED”。
- §8 第 6 条：删除“G0 冻结前…不宣布 G0 通过”；改为“G0 已 PASS；后续变更仍需 ADR/审批”。
- §9 Git：删除“last_verified_commit=null；0 commit”；写入 7 commits、HEAD、当前 `last_verified_commit` 与不一致原因；保留“不自动 commit”规则。
- §11：从“阶段 7 执行约束”改为“当前 T0 整改约束”，保留历史阶段 7 约束在单独的“历史”小节；加入 WP-03 入口条件（见 §6.4）。
- 新增/更新“G0/门禁现状表”，只引用 `project_state.json`，不复制独立状态。
- 不修改 §4 的 T0 开发顺序、§6 测试规则、§10 状态词汇（除非状态模型批准后补充 `pseudocode_stages` 说明）。

### 5.3 `docs/SESSION_HANDOFF.md`

新增置顶条目，至少包含：

- 当前阶段/里程碑：T0 / M0_GOVERNANCE_BASELINE；G0 PASS；G1–G7 NOT_STARTED。
- 已完成：WP-01、WP-02（含整改）、P1 验收、P2–P8 设计产物、P9 部分、P10 部分。
- 未完成：P2 用户验收；P9 缺 6 文件；P10 缺模块文档；WP-03 未启动；BLK-003 OPEN。
- 已知风险：API 幂等缺陷已修/待验证；GET spec 契约未澄清；幂等键字符集/JCS 未决；P7/P8 无阶段日志。
- 下一步：修复后测试 → 用户验收 P2/阶段状态 → 裁决 WP-03 前置问题 → 才可 WP-03。
- 禁止：不提前 WP-03、不改冻结契约、不删除未跟踪文件、不自动 commit。
- 权威文件：`AGENTS.md`、`project_state.json`、`06_DATA_AND_API.md`、`07_T0_PLAN_AND_GATES.md`、`P0_*` 报告。
- 旧条目保留，标注历史。

### 5.4 `AGENTS.md`

只改元数据/指针，不改规则：

- L5 版本行：改为“阶段 5 基线（2026-11-08），2026-11-11 P0 治理修订”；如有更准确日期，以 CHANGELOG 为准。
- §10 增加：T0 WP-01/WP-02 证据、`reports/remediation/`、P1–P10 状态注册表（若批准）。
- 不引入第二套状态体系；阶段状态仍以 `project_state.json` 为准。
- 不修改 §6 研发状态词汇（除非用户批准状态模型扩展，并在 §6.1 补一句 `pseudocode_stages` 的独立状态）。

### 5.5 非冻结知识文档

- `docs/PROJECT_OVERVIEW.md` L120、L154–L164：改为当前状态指针；标注“阶段 7 快照”历史。
- `docs/ARCHITECTURE.md` L1–L3、L516–L529：改为“G0 已 PASS；本文件是架构基线，不是门禁证据；当前实现状态见 JSON”；实现状态表改为真实值（模型/API 已有，StateMachine/DB 等未实现）。
- `docs/state/G0_DECISION_LIST.md`：页首加历史横幅；不改表。
- **不修改** `docs/G0/01`、`docs/PRD/02`、`03`、`docs/design/04`–`07` 的冻结状态段；在 README 中说明“冻结件文末状态为冻结时点快照”。

---

## 6. 阶段 5：补齐设计决议

### 6.1 P1 决议追溯（OQ-P1-03/05）

- 已执行的搜索：工作区全文、Git 全历史 `-S`、删除文件历史、当前 ZIP、邻近目录/Downloads；均无原始问题与裁决正文。
- 处理：
  - 若用户提供正文/来源：把正文、依据、影响范围、证据来源写入 `M01_contracts/MODULE.md §8`（或对应节）与 `OPEN_QUESTIONS.md`，保留 OQ 编号。
  - 若无法提供：经用户批准，把两行从 `DECIDED` 改为 `NEEDS_CONFIRMATION`，并在 `M01/M03` 写明“原问题与裁决正文缺失；已搜索范围；不得作为先例”。
  - 不编造问题内容，不把“已由用户处理”改写成具体决定。
- 若 `PHASE_RULES §8` 只允许 OPEN/DEFERRED/DECIDED，则需要用户同时批准一个“证据状态”扩展（例如新增 `NEEDS_CONFIRMATION` 到 OQ 表，但不改变 OQ 的 OPEN/DEFERRED 语义）；否则用“DECIDED（证据不足，待补）”的兼容写法，并在表头说明。

### 6.2 P2 前置决议（A/B/C/D）

| 项 | 分类 | 建议方案（待批准，不自行生效） |
|---|---|---|
| §12-2 创建入口 | A+C | `StateMachine.create_initial()` 统一写 Task/Node 初始行 + 初始审计；API/Service 只调用该入口，不直接 INSERT；若用户坚持 TaskCreationPort 直接写，则必须定义写权限、审计和非法绕过防护 |
| §12-6 BLOCKED 终态 | A+C | T0 视为终态；解除阻塞需新 ADR，不在 M02 私自加边 |
| §12-7 幂等键 task_id | A+C | `NOT NULL` + FK + 与任务同事务；不支持“先占键后建任务”；若必须支持，改为可空/延迟 FK 并记录 |
| §12-8 幂等键字符集 | A+C | 1–255 个可见 ASCII（`0x21–0x7E`），无空白；空键 422 `SCHEMA_INVALID`；与 M02/M19 提案一致 |
| §12-5 时钟/审计序 | A+D | 先 fail-closed；若实验表明 `created_at` 不足，再评估 `audit_seq`（schema 变更，需 ADR） |
| §12-1 Evidence 状态 | B | WP-07 前 ADR；M02 不加列 |
| §12-3 失败审计 | B | WP-08 前确认；M02 记录实际状态，声称值进 reason/details |
| §12-4 audit/invalidation ID | B | 不透明 UUID；如需前缀再改 |
| §12-9 404 映射 | B+C | WP-08/API 错误映射前裁决；当前 GET 404 不改 |
| §12-10 Verifier 边界 | B | 保持 M02：Verifier 只签发报告/证书，不驱动状态 |
| OQ-DB-2 保留期 | B | WP-03 建表保留字段；清理策略后置 |

**写入位置：** `M02_state_machine/MODULE.md` 的 `DECISIONS` 段（新增）+ `OPEN_QUESTIONS.md` 对应行；涉及冻结 DDL 偏离的 §12-7 必须先经用户批准，不能只写伪代码。

### 6.3 不裁决的事项

- 不把 P2–P8 阶段自动验收。
- 不把 P9 缺失文件补写成“原设计”。
- 不把 §12 的 OPEN 改成 DECIDED 来减少问题数量。
- 不修改 06/05 冻结语义；如需改，先报告并请求批准。

### 6.4 WP-03 进入条件（建议写入 DEVELOPMENT_WORKFLOW/交接）

1. API 幂等修复完成，测试 A–E 通过；
2. P2 由用户正式验收（或书面豁免）；
3. §12-2、§12-6、§12-7、§12-8 已裁决并写入 M02 DECISIONS/ADR；
4. P9 缺口已如实登记，不作为 WP-03 输入；
5. BLK-003 状态如实保留并说明影响；
6. 用户明确下达 WP-03 指令；不得把 P0 整改 PASS 当作 WP-03 开工令。

---

## 7. 阶段 6：BLK-003 测试环境核查

### 7.1 已执行的审计证据

- Python 3.11.16 / 64bit / SQLite 3.53.1 / pytest 9.2.0；
- workspace-write 下：112 passed、23 failed、20 errors；
- 失败全部在 `tests/test_state_sync.py` 的临时目录创建/清理，`PermissionError [WinError 5]`，无断言失败；
- 根因与 `project_state.json` L553–563 描述一致：沙箱授权未向运行期新建子目录传播。

### 7.2 批准后的补充验证

1. 最小写入探针（只读/临时目录，不写项目源码）：
   - `tempfile.mkdtemp()` 后创建子目录并写文件，记录成功/失败路径；
   - 与 2026-11-08 的 `PROBE_WRITE=OK` 对照，说明“能建根目录、不能建子目录”的差异。
2. 指定测试：`pytest tests/test_api_422.py tests/test_contract_models.py tests/test_check_docs_drift.py`（预计 112 passed）。
3. 全量 pytest：workspace-write 下再跑一次，保存 `P0_TEST_REPORT` 日志；预计仍为 23 failed/20 errors。
4. 如用户批准一次性 full-access：在 full-access 下跑全量 pytest，记录结果；**只用于业务回归**，不用于关闭 BLK-003，不用于安全项。
5. 结论：
   - 若 workspace-write 全量通过 → 可按规则评估关闭 BLK-003；
   - 若仍失败 → **保持 OPEN**，在最终报告写“环境阻塞，未达到关闭条件”；
   - 不修改测试来规避 ACL，不手工改 ACL。

---

## 8. 阶段 7：完整回归测试

### 8.1 静态检查

```powershell
# AST 语法检查（全部 researchflow/tests/scripts/design 伪代码）
& .venv/Scripts/python.exe -c "import ast,pathlib; ..."

# 导入检查
& .venv/Scripts/python.exe -c "import researchflow, researchflow.api.app, researchflow.contracts.models, researchflow.contracts.parsing; print('IMPORT_OK')"

# 依赖一致性
uv pip check --python .venv/Scripts/python.exe
```

### 8.2 自动化测试

```powershell
& .venv/Scripts/python.exe scripts/validate_contracts.py --selftest
& .venv/Scripts/python.exe scripts/validate_contracts.py
& .venv/Scripts/python.exe -m pytest tests/test_contract_models.py -q -p no:cacheprovider
& .venv/Scripts/python.exe -m pytest tests/test_api_422.py -q -p no:cacheprovider
& .venv/Scripts/python.exe -m pytest tests/test_check_docs_drift.py -q -p no:cacheprovider
& .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

- 保存每条命令、解释器、退出码、日志、运行时间到 `reports/remediation/P0_TEST_REPORT.md` 与 `reports/remediation/logs/`。
- 不得只报告最后一次成功；必须同时报告全量失败及原因。
- 不得删除失败测试；不得降低断言。

### 8.3 目录清洁

- 检查 `__pycache__`、`.pytest_cache`、`tmp/unittest-temp`、空 `tmple0ojac0`；
- 经批准后删除已确认缓存/测试残留；保留 `tmp/stage6_asar`、`tmp/commitmsg_g0.txt`；
- 记录 `git status --porcelain=v1 --ignored` 前后对比；
- 不删除已跟踪且用途不明的文件。

---

## 9. 阶段 8：更新项目状态与交付

### 9.1 状态更新顺序

1. 修改 `docs/state/project_state.json`：
   - `updated_at`；
   - `pseudocode_stages`（若批准）；
   - `T-PSEUDO-001` 元数据/阻塞；
   - 新增 `T-P0-REMEDIATION-001`（或等价任务），状态 `IN_REVIEW`，记录整改范围、测试命令、证据路径、BLK-003 关联；
   - `T-WP-02-001` 保持 `DONE`，但 `evidence_paths` 增加整改测试报告与验收补记；
   - `BLK-003` 保持 `OPEN`，更新描述/复核证据；
   - `last_verified_commit` 仅在获得提交授权且真实提交后更新。
2. 运行：

```powershell
& .venv/Scripts/python.exe scripts/state_sync.py validate
& .venv/Scripts/python.exe scripts/state_sync.py render
& .venv/Scripts/python.exe scripts/state_sync.py check
```

3. 追加 `docs/CHANGELOG_DEV.md`（追加式，不覆盖）。
4. 更新 `docs/SESSION_HANDOFF.md`（最新置顶）。
5. 更新 WP-02 验收记录：追加“2026-11-11 复议/补测”段，不删除原文；说明原测试只断言 task_id，新增 A–E。
6. 生成六个报告：
   - `P0_AUDIT_REPORT.md`（已有）；
   - `P0_REMEDIATION_PLAN.md`（本文件）；
   - `P0_CHANGELOG.md`（逐文件/逐位置/原因/diff 摘要）；
   - `P0_TEST_REPORT.md`（环境、命令、结果、失败原因）；
   - `P0_FINAL_ACCEPTANCE.md`（R01–R12 判定、PASS/WARNINGS/BLOCKED）；
   - `P0_OPEN_ISSUES.md`（未解决问题、优先级、责任方、下一步）。
7. 输出完整 `git diff`（含未跟踪文件的清单；未跟踪文件用 `git diff --no-index /dev/null` 或文件清单+哈希，不强行 `git add`）。

### 9.2 状态判定边界

- `T-P0-REMEDIATION-001` 建议 `IN_REVIEW`（等待用户最终验收），不自动 `DONE`。
- `T-WP-02-001` 维持 `DONE`，但验收记录追加复议；不得因为整改任务完成就重开/改写历史。
- `T-PSEUDO-001` 仍 `IN_REVIEW`；P2–P8 各阶段仍 `IN_REVIEW`；P9/P10 `IN_PROGRESS`。
- 不把 T0 整体标完成；不把 P0 整改 PASS 等同 G1 PASS；G1–G7 不变。
- `last_verified_commit` 未提交前不推进；若无法提交，最终报告明确 WARNING。

---

## 10. 验收映射（R01–R12）

| 编号 | 验收项 | 本计划如何满足 | 预期 |
|---|---|---|---|
| R01 | API 幂等一致性 | 阶段 2 修复 + 测试 A/E | 通过 |
| R02 | API 回归 | 原 13 项 + 新增 5 项 + 422/查询 | 通过 |
| R03 | P1–P10 状态统一 | 阶段 3 注册表 + 全文件同步 | 通过（需批准方案） |
| R04 | P7/P8/P9 归属 | 阶段 3 矩阵、STAGE_LOG 补登、P9 缺口 | 通过（P9 仍 IN_PROGRESS） |
| R05 | README | 阶段 4 重写现状 | 通过 |
| R06 | DEVELOPMENT_WORKFLOW | 阶段 4 更新现状/G0/commit | 通过 |
| R07 | P1 决议 | 阶段 5 有证据恢复/无证据标 NEEDS_CONFIRMATION | 取决于用户证据；至少不伪造 |
| R08 | P2 前置决议 | 阶段 5 A 类裁决；B 类挂起 | 通过/部分 BLOCKED |
| R09 | BLK-003 | 阶段 6 真实复核；不满足则保留 OPEN | 可能 BLOCKED/WARNING |
| R10 | PROJECT_STATE 与 JSON | `state_sync render/check` | 通过 |
| R11 | 测试环境 | 3.11.16/64bit；全量受 ACL 阻塞时如实报告 | 部分通过 |
| R12 | 修改安全性 | 备份、Diff、保留用户修改 | 通过 |

**最终结果预设：**

- 若 R01–R08、R10、R12 通过，R09/R11 因 workspace-write ACL 保留 → **PASS WITH WARNINGS**；
- 若 §12-2/§12-6/§12-7/§12-8 或 P1 决议未获裁决 → **BLOCKED**；
- 若发现需改冻结契约/架构 → 立即停止，按冲突报告处理。

---

## 11. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 修改 `app.py` 时误改 422 顺序 | 破坏既有 422 测试 | 只改幂等区；先跑原 13 项；diff 逐行复核 |
| 状态模型扩展导致 `state_sync` 校验失败 | 生成文件无法更新 | 先写校验测试；小步改；`validate→render→check` 三步 |
| 覆盖用户未提交的 INDEX/STAGE_LOG/OQ | 丢失并发会话成果 | 先备份；基于当前内容 edit；不整文件重写 |
| 把 P9 缺失写成“已完成” | 虚假完成 | 只登记缺口；不补写 |
| BLK-003 被误关闭 | 验收失真 | 只有 workspace-write 全量通过才可关闭；full-access 结果不用于关闭 |
| 提交/身份问题 | 无法更新 `last_verified_commit` | 不自动 commit；按用户授权；未授权则保留 WARNING |
| 删除缓存误伤证据 | 丢失阶段 6 证据 | 只删明确缓存；保留 `tmp/stage6_asar`；删除前列清单 |

**回滚：**

- 单文件：从 `backup_before/` 恢复；
- 批量：按 `baseline.patch` 反向应用（仅已跟踪文件）；
- 生成文件：`state_sync render` 重新生成；
- 不执行 `git reset --hard`/`git clean -fd`。

---

## 12. 批准清单（请逐项回复）

- [ ] **A. 是否批准阶段 2**：修复 `researchflow/api/app.py` 幂等响应 + 新增测试 A–E，不改冻结契约。
- [ ] **B. 状态模型**：选 A（在 `project_state.json` 增加 `pseudocode_stages`，推荐）或 B（新增 10 个任务，ACCEPTED↔DONE 映射）。
- [ ] **C. OQ-P1-03/05**：提供决议正文/来源；或批准标 `NEEDS_CONFIRMATION`。
- [ ] **D. WP-03 前置裁决**：批准 §6.2 建议（§12-2/§12-6/§12-7/§12-8），或给出替代口径。
- [ ] **E. BLK-003**：批准一次性 full-access 全量测试（不关闭 BLK-003），或仅保留 workspace-write 结果。
- [ ] **F. P9 缺失文件**：是否有副本可恢复；无则批准 P9 标 IN_PROGRESS/BLOCKED 并保留缺口。
- [ ] **G. P10/M19**：确认是否授权在研；建议登记 IN_PROGRESS，不删除。
- [ ] **H. 提交**：整改完成后是否授权 commit 并更新 `last_verified_commit`。
- [ ] **I. 非冻结文档**：是否批准更新 `PROJECT_OVERVIEW`/`ARCHITECTURE` 现状节与 `G0_DECISION_LIST` 历史横幅。
- [ ] **J. 清理**：是否批准清理 `.pytest_cache`、`__pycache__`、`tmp/unittest-temp`、空 `tmple0ojac0`。

> 未获批准前，保持只读；不进入阶段 2。