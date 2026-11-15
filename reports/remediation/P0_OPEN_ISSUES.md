# ResearchFlow 3.1 · P0 遗留问题与待裁决事项（P0_OPEN_ISSUES）

> 日期：2026-11-11（Asia/Shanghai）
> 状态：**未完成 / 等待用户裁决**；不得把本文件当作批准记录。
> 关联：`P0_CHANGELOG.md`、`P0_TEST_REPORT.md`、`P0_FINAL_ACCEPTANCE.md`、`P0_STATE_CONSISTENCY_REPORT.md`。

## 1. 结论摘要

| 类别 | 当前状态 | 是否可关闭 |
|---|---|---|
| A API 幂等 | 已修复，A–E 通过 | 可进入复核，但 GET `spec`/键字符集/JCS 仍未决 |
| B 阶段注册表 | 已建立，validate/render/check 通过 | P1–P10 状态可复核；P2–P10 未验收 |
| C P1 OQ | 已标 `NEEDS_CONFIRMATION` | 需用户补证或确认无法恢复 |
| D WP-03 前置 | 仅方案，未裁决 | **否** |
| E full-access 测试 | `140 passed` | 结果有效；**BLK-003 仍 OPEN** |
| F P9 | 6 个 `.py` 为并发重写，非原始恢复 | **否**，P9 `BLOCKED` |
| G P10/M19 | 仅登记现状 | **否**，P10 `BLOCKED` |
| H commit | 未授权 | **否**，未 commit |
| I 非冻结文档 | 已更新现状说明 | 可复核；冻结件未改 |
| J 清理 | 未授权 | 未清理 |

## 2. D · WP-03 前置裁决（未生效）

> 本节只提交方案，不写入 `M02 DECISIONS`、ADR 或冻结契约。用户单独批准后才可落盘。

### 2.0 核对结论（先于方案）

| 核对项 | 事实 | 结论 |
|---|---|---|
| 当前契约 | 06 §3 写者矩阵把 `tasks`/`nodes` 的唯一写者列为 `StateMachine`；`audit_log` 也是 StateMachine 写 | 创建入口应归 StateMachine，才与写者矩阵一致 |
| P2 伪代码 | `StateMachine` 只有 `transition()` 一个公开写入口：`PUBLIC_WRITE_ENTRYPOINTS = ("transition",)`；`assert_single_write_entrypoint()` 只允许 `transition` | **当前没有 `create_initial()`**；用户原则批准的接口尚不存在 |
| Task 创建职责 | `TaskRepository._insert_created()` 需要 `TASK_CREATE` capability，只允许 `state='CREATED'`；未暴露给 API | 创建能力存在，但没有统一事务/入口 |
| Node 创建职责 | `NodeRepository._insert_planned()` 需要 `DAG_REGISTER` capability，只允许 `state='PLANNED'`；DAG Builder 是候选调用方 | Node 是批量注册，和 Task 创建的事务边界不同 |
| 幂等创建 | `IdempotencyStore.reserve()` 文档要求：`BEGIN IMMEDIATE` → `INSERT tasks(state='CREATED')` → `reserve` → COMMIT/ROLLBACK | 事务必须覆盖 task + idempotency；若 `create_initial()` 自行提交，API 无法把幂等行放进同一事务 |
| 初始审计 | 05 §9.2 只在 `CREATED→PLANNING` 等迁移行写“写审计”；SQLite 触发器只强制 `UPDATE OF state` 的同事务审计，不强制 INSERT | 初始 INSERT 目前没有契约要求的审计动作；若要创建审计，需先定义 action/字段，属契约扩展 |
| 事务边界 | `transition()` 使用 `BEGIN IMMEDIATE`；`Repositories.transaction()` 也是 `BEGIN IMMEDIATE` | 创建入口必须明确“自己开事务”还是“加入调用方事务”，不能两者都做 |

**核对结论：** 原则上可以采用 `StateMachine.create_initial()`，但不能直接加一个只做 INSERT 的方法；必须同时解决三件事：

1. Task 创建与 `idempotency_keys` 同事务；
2. Node 批量注册的独立事务/调用方；
3. 初始 INSERT 是否写审计（当前契约不要求，写了反而要新增 action 约定）。

### 2.1 §12-2 · Task/Node 创建 INSERT 路径归谁

#### 原问题完整上下文

- M02 §12-2 原文：`tasks/nodes` 的创建 INSERT 路径未分配；M02 把“创建”与“状态迁移”分开，INSERT 只能进入初始状态 `CREATED`/`PLANNED`，之后只能 transition；死线为 **WP-03 开工前**。
- 06 §3 写者矩阵：`tasks`/`nodes` 唯一写者 = `StateMachine`；`idempotency_keys` 写者 = API 任务创建路径；`graph_versions` = DAG Builder（经 StateMachine 登记）。
- 06 §1.3：`tasks`、`nodes`、`idempotency_keys` 的 DDL 已冻结；`idempotency_keys.task_id` 当前为可空 `TEXT`（见 §2.3）。
- 06 §3 事务：幂等创建 = `idempotency_keys` INSERT + `tasks` INSERT 同事务；冲突回滚，不留孤儿键。
- P2 代码：`StateMachine` 只有 `transition()`；`TaskRepository._insert_created()`/`NodeRepository._insert_planned()` 是受 capability 保护的写方法；`IdempotencyStore.reserve()` 要求 `INSERT tasks` 先于 `reserve`，同事务。
- 05 §9.2：`CREATED → PLANNING/CANCELLED` 写审计；初始 `CREATED` 插入本身没有“创建审计”条目。
- 05 §9.3：Node `PLANNED` 的下一状态是 `READY/BLOCKED`；初始 `PLANNED` 插入也没有创建审计条目。

#### A / B 方案

**方案 A（推荐方向）：`StateMachine.create_initial()` 统一创建 + 统一事务**

- 新增 `StateMachine.create_initial(obj_type, rows, actor, ctx, idempotency=None)`：
  - `obj_type=task`：写一条 `tasks(state='CREATED')`；可选地在同一 `BEGIN IMMEDIATE` 内调用 `IdempotencyStore.reserve()`；
  - `obj_type=nodes`：批量写 `nodes(state='PLANNED')`，由 DAG Builder 调用；
  - 只允许初始状态；其他状态直接拒绝；
  - `TaskRepository._insert_created` / `NodeRepository._insert_planned` 保持私有，仅由 `StateMachine` 传入 capability；
  - `PUBLIC_WRITE_ENTRYPOINTS` 改为 `("transition", "create_initial")`，同步 `assert_single_write_entrypoint()` 与负例 `NEG-M02-03`；
  - API 不再直接 INSERT；DAG Builder 不再直接持有 Node 写能力。
- 初始审计：
  - **默认不写**创建审计，理由是 05 只要求迁移审计，06 触发器也只强制 UPDATE 审计；
  - 若用户要求“创建也审计”，必须先定义 `action`（例如 `TASK_CREATED`/`NODES_REGISTERED`）与字段，再在同一事务写入；这是契约/审计扩展，需单独批准，不能在本轮偷偷加。
- 事务边界：
  - `create_initial` 自己开 `BEGIN IMMEDIATE`；若调用方已有事务，则拒绝（不能用嵌套事务假装原子）；
  - Task 创建 + 幂等 reserve 必须在同一事务；Node 批量注册单独事务；
  - 回滚时 task/idempotency/node 全部回滚，不留孤儿。

**方案 B：独立 `TaskCreationPort` / `DagRegistrationPort`**

- StateMachine 只保留 `transition()`；创建由 API/DAG Builder 通过端口写仓储。
- 优点：创建与迁移事务解耦，端口可替换；
- 缺点：与 06 §3“tasks/nodes 唯一写者 = StateMachine”冲突；需要在 ADR 中明确“创建是例外”，并防止绕过端口直接 INSERT；审计边界也要另定。
- 若选 B，至少需要：端口 capability、禁止裸 SQL、创建审计策略、API/DAG 的调用契约、负例（直接 INSERT 被拒）。

#### 对 T0 / WP-03 / Recovery 的影响

| 维度 | 方案 A | 方案 B |
|---|---|---|
| T0 | 创建入口与写者矩阵一致；WP-03 工作量增加（一个入口 + 事务测试） | 需要 ADR/写者矩阵例外；T0 实现更分散 |
| WP-03 | `create_initial` 必须与 `IdempotencyStore` 同事务；必须处理 replay/conflict | API 直接编排事务；StateMachine 不拥有创建，容易漏审计/绕过 |
| Recovery | 不受影响：Recovery 只走 `transition()`，不创建 Task/Node | 同样不受影响，但创建端口可能被复用，边界更模糊 |
| 迁移风险 | 低：不改表结构，只加入口与 capability | 中：需要改写者矩阵/ADR，后续更难收回 |

#### 对现有契约和测试的影响

- 不需要改 05/06 的字段或状态枚举；方案 A 与 06 §3 写者矩阵一致。
- 需要改 P2 伪代码与测试：`PUBLIC_WRITE_ENTRYPOINTS`、`assert_single_write_entrypoint`、`NEG-M02-03`、`NEG-M02-08`、创建/回滚/幂等负例。
- 需要新增测试：同键同体 replay、同键异体 conflict、任务插入失败回滚、幂等行失败回滚、直接 INSERT 被拒、Node 批量注册部分失败全回滚、非法初始状态拒绝。
- 若加创建审计：需要新增 action 约定与正/负例，属额外范围。

#### 推荐

**推荐 A，但拆成两个方法/一个入口类的两条路径：**

- `create_initial_task(..., idempotency=...)`：Task + 幂等同事务；
- `create_initial_nodes(...)`：Node 批量注册独立事务；
- 对外可保留 `create_initial(obj_type=...)` 分派，避免两个公开类；
- 默认不写创建审计；若要写，先批准 action 约定；
- 在 WP-03 编码前把该方案写入 M02 `DECISIONS` 或 ADR，并补上述测试。

### 2.2 §12-6 · Task/Node 的 `BLOCKED` 是否为终态

#### 原问题完整上下文

- 05 §9.2 Task：`BLOCKED` 在“其余”行，未给任何出边；M02 明确 T0 视为终态。
- 05 §9.3 Node：`BLOCKED` 同样无出边；M02 T0 视为终态。
- 现状：`BLOCKED` 只能由 `PLANNING/READY/RUNNING/VERIFYING`（Task）或 `PLANNED/READY/VERIFYING/FAILED/DIAGNOSING/RECOVERING`（Node）进入；进入后无迁移。
- 影响：T0 的“解除阻塞”没有状态路径；只能新任务/人工处置；T1 Recovery 若需要从 `BLOCKED` 恢复，必须新增边。

#### A / B 方案

- **A：T0 保持终态。** 不新增出边；解除阻塞走新任务/人工操作；T1 需要时另立 ADR。
- **B：T0 增加解除阻塞边。** 例如 Task `BLOCKED→READY`、Node `BLOCKED→READY/DIAGNOSING`；需要定义守卫、审计、重试次数、资源/权限条件。

#### 影响

| 维度 | A | B |
|---|---|---|
| T0 | 简单、与 05 一致；无法原地解除阻塞 | 需要新迁移、守卫、审计与测试 |
| WP-03 | 不需要新增边/守卫 | 迁移表、守卫、审计、负例扩大 |
| Recovery | T1 才能解除；T0 只报告 `BLOCKED` | 可在 T0 原地恢复，但风险与范围扩大 |

#### 契约/测试影响

- A：不改契约；补“BLOCKED 无出边”负例。
- B：改 05 状态表、M02 迁移表、审计 action/守卫、负例；属状态机变更，需 ADR。

#### 推荐

**A：T0 保持终态。** T1 若需要“解除阻塞”，单独立 ADR，不在 WP-03 私自加边。

### 2.3 §12-7 · `idempotency_keys.task_id` 是否可空

#### 原问题完整上下文

- 06 §1.3 冻结 DDL：`task_id TEXT`（可空、无 FK）；`idem_key TEXT PRIMARY KEY`。
- M02 §12-7 / D-3 提议收紧为 `NOT NULL` + `REFERENCES tasks(task_id)`，要求任务与幂等键同事务。
- `IdempotencyStore.reserve()` 当前顺序：`BEGIN IMMEDIATE` → `INSERT tasks` → `reserve` → COMMIT；冲突回滚。
- 当前 API 是内存注册表，不涉及 SQLite；WP-03 才落地。

#### A / B 方案

- **A：保持冻结 DDL 可空，应用层强制非空 + 同事务 + task 存在。** 不改 06；用触发器或应用校验防止孤儿键；测试覆盖空 task_id、孤儿 task_id、回滚。
- **B：改 DDL 为 `NOT NULL` + FK。** 需要 ADR/MINOR 迁移；数据库层更强，但偏离 06 冻结件。

#### 影响

| 维度 | A | B |
|---|---|---|
| T0/WP-03 | 不改契约；应用层约束需测试；裸 SQL 仍可能绕过 | DB 层强约束；需要迁移/契约变更 |
| Recovery | 不受影响 | 不受影响 |
| 兼容性 | 与 06 DDL 一致 | 旧库迁移、回滚、外键顺序需处理 |

#### 契约/测试影响

- A：不改 06；新增“空/孤儿 task_id 拒绝”的负例（应用层/触发器）。
- B：改 06 DDL、迁移脚本、回滚说明、FK 测试；需用户批准。

#### 推荐

**A（本轮）：** 不改冻结 DDL；WP-03 以应用层/触发器保证 `task_id` 非空且任务存在。若 WP-03 需要 DB 级 `NOT NULL + FK`，另提 ADR/MINOR，不在本轮直接改。

### 2.4 §12-8 · 幂等键字符集

#### 原问题完整上下文

- 06 §4.5 只要求“`idempotency_key` + 规范化请求哈希”，未定义字符集/长度/空键语义。
- M02 §12-8 提议：可见 ASCII `0x21–0x7E`，长度 1–255，无空白。
- 当前 API：任意 header 值都接受（包括空串、空白、超长、Unicode）；无 422。
- 当前 A 项明确“不改变现有 422 顺序”，因此本轮**没有**加入键校验。

#### A / B 方案

- **A：采用 M02 提议。** `^[\x21-\x7E]{1,255}$`；空键/空白/超长/控制字符返回 422 `SCHEMA_INVALID`。
- **B：保持 opaque。** 由 HTTP 层限制长度，业务不解析字符集；只要求非空（或允许空键表示“无幂等”）。

#### 影响

| 维度 | A | B |
|---|---|---|
| API 行为 | 新增 422 分支；客户端需换键 | 兼容当前行为；DB/日志可能收到奇怪字符 |
| WP-03 | DB 约束/索引更可控 | 需处理任意字符的存储/比较 |
| 测试 | 需新增 422 键负例 | 需明确空键语义 |

#### 契约/测试影响

- A：不改 06 路径/响应形状，但新增 422 语义；需在 06 §4.5 或 ADR 记录；测试空、空白、256 字符、Unicode、控制字符。
- B：不新增 422；需明确空键是否等价于无键。

#### 推荐

**A，作为 WP-03 前的建议口径；但本轮不实现。** 若批准，应在 API 校验顺序中放在“请求体校验之后、幂等查重之前”，并保持现有 422 结构；错误字段路径需先定义（header 无 body 字段，建议 `field_path` 为空或 `Idempotency-Key`，需用户确认）。

## 3. F · P9 六个并发重写文件逐项登记

> 这不是“恢复原始正文”。2026-11-11 22:53:44 基线时 P9 只有 5 文件 / 1,404 行；22:53:54–55 出现 6 个 `.py`、4 份模块文档与 3 份阶段索引文档（INDEX/STAGE_LOG/OPEN_QUESTIONS）变更。以下为当前落盘事实，不是验收证据。

| 文件 | 原 MODULE 声明 | 当前行数 | SHA256 | 创建/修改时间 | 当前判定 |
|---|---:|---:|---|---|---|
| `M15_dcspa/orchestration/determinism/dc_eligibility.py` | 1,317 | 1,173 | `dac738298af46a874fc04517fd334c01f08ebc5e6ad227454145800abb497502` | 2026-11-11T22:53:54.9738305+08:00 | 并发重写；未测试 |
| `M15_dcspa/orchestration/determinism/dc_issuer.py` | 973 | 1,035 | `53524c900025e76ea0c6741c58ba53a6bc5d01ee2a38dcc22ebf4785556f70aa` | 2026-11-11T22:53:54.9768236+08:00 | 并发重写；未测试 |
| `M15_dcspa/orchestration/determinism/spa_judge.py` | 1,327 | 1,227 | `3e8cfebfcd43ce930377ad2f2619d0cfcc9cc9ca29dcf6b275a617e3973cb527` | 2026-11-11T22:53:54.9798241+08:00 | 并发重写；未测试 |
| `M15_dcspa/orchestration/determinism/prr_ledger.py` | 842 | 830 | `81153260611eb00e8897b8ebb05b110eb6c7acb5832c01e8fb9316b1e974d69c` | 2026-11-11T22:53:54.9833320+08:00 | 并发重写；未测试 |
| `M16_vas/orchestration/vas/risk_features.py` | 749 | 614 | `1656953478c95bcec6d1014ba0aadcfb5f41198091dd08498a25db828910d274` | 2026-11-11T22:53:54.9898614+08:00 | 并发重写；未测试 |
| `M16_vas/orchestration/vas/knapsack.py` | 815 | 747 | `a1cd72cc71ea63b7ef22889f520c8fa263836edcde8293bc3bda79c21c4ffb64` | 2026-11-11T22:53:54.9863370+08:00 | 并发重写；未测试 |

补充事实：

- 六个文件均无 Git 对象；`git rev-list --all --objects` 未命中。
- 六个文件 `ast.parse` 均通过（6/6）；顶层符号数量分别 32/33/45/21/25/23；但**未做**完整接口语义比对、未导入、未运行 pytest。
- 当前 P9 共 11 文件 / 7,122 行（M15 6/4,772；M16 5/2,350；含复核横幅 +4 行），与 `INDEX.md` 一致；`OPEN_QUESTIONS.md` 的 7,030 已修正为 7,122。
- 原 `MODULE.md` 的行数/函数索引是“原声明”，不是当前文件的证据；当前 `MODULE.md` 已加并发重写横幅，文件状态改为“存在（并发重写，未测试）”。
- 未找到其他可恢复副本：工作区、Git 全历史、`D:\ResearchFlow-project.zip`、`Downloads` 均无原始六文件；ZIP 内 M15 2 文件、M16 3 文件。

### 恢复建议（待用户选择）

1. **接受为新的设计稿**：P9 从 `BLOCKED` 改为 `IN_REVIEW`，但必须重新做接口/函数索引核对、负例对照、至少 AST/导入/静态检查；不得称“原文恢复”。
2. **要求重新补齐**：保持 `BLOCKED`；由用户指定原始来源或授权重写；重写后重新登记哈希与行数。
3. **不再补齐**：保持 `BLOCKED`，P9 不作为 WP-03 输入；后续 T2 重新设计。

本报告推荐 **2 或 1 的前置审查**，不推荐 3 的直接删除；无论哪种，都不得标 `ACCEPTED`。

## 4. G · P10/M19 现状（仅登记，不扩大）

| 文件 | 行数 | SHA256 | 修改时间 |
|---|---:|---|---|
| `M19_api/api/error_map.py` | 282 | `38a52ac7d0c9ac65d78779c53abf33a4a751f226b9d36ca69a9b4c8f27de79f3` | 2026-11-11T22:22:43+08:00 |
| `M19_api/api/middleware_idempotency.py` | 568 | `fb090eb1a3c08bd57d806ad97063df890c8f37cf030824f14e69b16d8e3621b6` | 2026-11-11T22:25:42+08:00 |
| `M19_api/api/routes_evidence.py` | 369 | `019400da7af66f613d83f1feb79a177378610123f2289ea46b094aa305019014` | 2026-11-11T22:24:48+08:00 |
| `M19_api/api/routes_tasks.py` | 431 | `6b8d87d1d21da8c29b24b043bb7749dbe94cfe8f2bab49d5eebdad1689e54a56` | 2026-11-11T22:24:15+08:00 |
| `M19_api/api/routes_verify_report.py` | 488 | `064bcde11f019a1d2fe2f1703f6d68e71f2035131bcda55035a5dc04ea795973` | 2026-11-11T22:25:42+08:00 |

- 合计 5 文件 / 2,138 行；无 `MODULE.md`、`NEGATIVE_TESTS.md`、阶段日志、OQ。
- Git：`?? design/pseudocode/M19_api/`；无 Git 对象。
- 依赖：`researchflow.contracts.parsing`；同目录 `error_map`、`middleware_idempotency`、`routes_tasks`。
- 未删除、未移动、未标 `ACCEPTED`；P10 状态 `BLOCKED`，原因“用户尚未确认 M19 是否为授权产物”。

## 5. 其他未解决问题

| 编号 | 问题 | 影响 | 当前处理 |
|---|---|---|---|
| BLK-003 | workspace-write 下测试临时目录 ACL 阻塞 | 全量测试在受限策略下仍不可复现；不能宣称环境通过 | 保持 `OPEN`；full-access 140 passed 仅作业务回归 |
| RF-API-02 | 幂等键字符集/长度未校验（§12-8） | 空键/超长/Unicode 可进入内存注册表 | 未改；等待 D 裁决 |
| RF-API-03 | 请求哈希用 `json.dumps(sort_keys=True)`，M02 提议 JCS | WP-03 可能产生不同同键判定 | 未改；等待 WP-03 前裁决 |
| RF-API-04 | `GET /tasks/{id}` 返回内部 `spec`，06 未定义字段 | 可能泄漏内部记录/契约未澄清 | 未改 GET；等待契约澄清 |
| OQ-P1-03/05 | 原问题与裁决正文不可恢复 | P1 追溯链缺口 | 已标 `NEEDS_CONFIRMATION`；等待用户补证 |
| P2 验收 | P2 仍 `IN_REVIEW` | WP-03 不得启动 | 等待用户逐阶段验收 |
| P7/P8 | 设计件存在但无用户验收；STAGE_LOG 为补登 | 不能宣称 P7/P8 完成 | 保持 `IN_REVIEW` |
| P9 | 六文件并发重写，未测试 | 不能作为 WP-03 输入 | 保持 `BLOCKED` |
| P10 | M19 未获开发授权 | 不能扩大范围 | 保持 `BLOCKED` |
| H | 未 commit；`last_verified_commit` 与 HEAD 不一致 | 无法宣称 HEAD 已验证 | 等待用户单独批准 |
| J | 缓存/临时目录未清理 | 工作区有既有缓存 | 只记录，不删除 |
| 并发写入 | 22:53:54–55 出现重写；截至 23:03 的只读复核未见新增；此后仅有本轮自身编辑 | 仍不能证明没有第二个写者 | 后续每次修改前复核时间戳/进程；发现新写入立即停止 |

## 6. 建议的最小决策顺序

1. **D-1**：批准/修改 §12-2 方案（是否采用 `StateMachine.create_initial()`；是否写创建审计；Task/Node 是否两个方法）。
2. **D-2**：§12-6 `BLOCKED` 是否 T0 终态。
3. **D-3**：§12-7 保持 06 可空 DDL + 应用层约束，还是走 ADR 收紧。
4. **D-4**：§12-8 是否采用可见 ASCII 1–255；若采用，定义 header 422 的 `field_path`。
5. **P9**：选择“接受为设计稿并复审 / 重新补齐 / 保持阻塞”。
6. **P10**：确认 M19 是否授权；未确认前不扩大。
7. **P2/P7/P8**：逐阶段验收或书面豁免；否则 WP-03 不启动。
8. **H/J**：单独批准 commit 与清理；本轮不自动执行。

> 在上述决策完成前，`P0_FINAL_ACCEPTANCE.md` 只能给出 `BLOCKED` 或 `PASS WITH WARNINGS` 的分项结论，不能写“项目完成”。