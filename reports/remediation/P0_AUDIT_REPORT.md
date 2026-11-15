# ResearchFlow 3.1 · P0 整改前审计报告

> 审计日期：2026-11-11（Asia/Shanghai）
> 工作区：`D:\ResearchFlow-project`
> 分支 / HEAD：`main` / `309083e715cb59a1f0c181d95df44e1946ffbaa5`
> 审计性质：只读审计。除本报告与 `P0_REMEDIATION_PLAN.md` 外，未修改任何既有项目文件。
> 结论先行：**不具备直接进入 WP-03 的条件**。存在 1 个已复现的 API 契约缺陷、1 个 P9 产物缺失且阶段状态失实、1 套 P1–P10 状态源冲突、1 个 WP-03 前置设计问题未决，以及 1 个已复现的测试环境阻塞。G0 PASS、WP-01/WP-02 DONE 的事实成立，但 WP-02 的幂等验收测试不充分，需补测并追加验收记录。

---

## 1. 审计范围、事实来源与工作区基线

### 1.1 实际读取/核对的权威文件

| 类别 | 文件 |
|---|---|
| 项目规则 | `AGENTS.md`、`docs/memory/Memory.md` |
| 机器状态 | `docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md` |
| 交接与日志 | `docs/SESSION_HANDOFF.md`、`docs/CHANGELOG_DEV.md`、`docs/state/G0_DECISION_LIST.md` |
| 工作流/总览 | `README.md`、`docs/DEVELOPMENT_WORKFLOW.md`、`docs/PROJECT_OVERVIEW.md`、`docs/ARCHITECTURE.md` |
| 冻结/上游设计 | `docs/design/06_DATA_AND_API.md`、`docs/design/07_T0_PLAN_AND_GATES.md`、`docs/G0/01_BASELINE_AND_TERMS.md`、`docs/verification/t0/wp-02/*` |
| 伪代码 | `design/pseudocode/INDEX.md`、`STAGE_LOG.md`、`OPEN_QUESTIONS.md`、`00_BASELINE/PHASE_RULES.md`、M01–M19 全部 `MODULE.md` / `NEGATIVE_TESTS.md` / `*.py` |
| 业务代码 | `researchflow/api/app.py`、`researchflow/contracts/*` |
| 测试 | `tests/test_api_422.py`、`tests/test_contract_models.py`、`tests/test_state_sync.py`、`tests/test_check_docs_drift.py`、`conftest.py` |
| 工程脚本 | `scripts/state_sync.py`、`scripts/check_docs_drift.py`、`scripts/validate_contracts.py` |

### 1.2 Git 事实（审计开始时）

```text
branch: main
HEAD:   309083e715cb59a1f0c181d95df44e1946ffbaa5
commits: 7
tracked: 427 files
```

未提交修改（必须保留，未做任何覆盖）：

```text
 M design/pseudocode/INDEX.md
 M design/pseudocode/OPEN_QUESTIONS.md
 M design/pseudocode/STAGE_LOG.md
?? design/pseudocode/M13_scheduler/
?? design/pseudocode/M14_recovery/
?? design/pseudocode/M15_dcspa/
?? design/pseudocode/M16_vas/
?? design/pseudocode/M17_agents/
?? design/pseudocode/M18_knowledge/
?? design/pseudocode/M19_api/
```

现有 7 个提交：

```text
309083e chore(state): 修正 last_verified_commit、登记伪代码阶段、补 STAGE_LOG 与 INDEX
1c9a104 docs(p0): P1-P6 伪代码基线（M01-M12，83 文件）
29902ef feat(wp-02): 落地五份冻结契约模型与 API 绑定
678d2e8 docs(t0): 记录 WP-01 验收通过并更新已验证提交
19c337f feat(wp-01): 锁定 T0 依赖环境
6c1783c chore(g0): 宣布 G0 PASS 并补测 Git 回滚
91bde66 chore(g0): 建立 G0 规格基线
```

`last_verified_commit` 当前为 `1c9a104`，与 HEAD `309083e` 不一致；`scripts/check_docs_drift.py` 报 1 条 WARNING（exit 0）。该字段在未提交整改完成前**不得**擅自推进。

### 1.3 环境基线

```text
解释器：D:\ResearchFlow-project\.venv\Scripts\python.exe
版本：3.11.16 (main, Sep 1 2026) [MSC v.1944 64 bit (AMD64)]
架构：64bit
SQLite：3.53.1
pytest：9.2.0
```

符合 `AGENTS.md` §3 的项目 Python 基线；未使用 PATH 上的 3.12、`py -3.11`（32 位）或任何 3.13 结果。

### 1.4 审计执行的真实命令

| 命令 | 结果 |
|---|---|
| `git status --porcelain=v1` | 3 个已修改、7 个未跟踪目录 |
| `git rev-parse HEAD` / `git rev-list --count --all` | `309083e…` / `7` |
| `& .venv/Scripts/python.exe -c "import sys,platform,sqlite3;..."` | 3.11.16 / 64bit / SQLite 3.53.1 |
| `& .venv/Scripts/python.exe -m pytest tests/test_api_422.py tests/test_contract_models.py tests/test_check_docs_drift.py -q -p no:cacheprovider` | **112 passed**，exit 0 |
| `& .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` | **112 passed, 23 failed, 20 errors**，exit 1（全部失败为 `test_state_sync.py` 临时目录 WinError 5） |
| `& .venv/Scripts/python.exe scripts/validate_contracts.py` | `contracts=5 cases=72 pass=72 fail=0`，exit 0 |
| `& .venv/Scripts/python.exe scripts/state_sync.py validate` | OK，exit 0 |
| `& .venv/Scripts/python.exe scripts/state_sync.py check` | 2 个生成文件逐字节一致，exit 0 |
| `& .venv/Scripts/python.exe scripts/check_docs_drift.py` | ERROR=0，WARNING=1（`last_verified_commit` 与 HEAD 不一致），exit 0 |
| 全部 `design/pseudocode/**/*.py` 的 `ast.parse` | 79 个文件，0 个语法错误 |
| `researchflow` 包导入检查 | `IMPORT_OK`，exit 0 |

### 1.5 上一版 ZIP 的核对

`D:\ResearchFlow-project.zip`（3,357,597 字节，2026-11-11 22:22:40）已只读比对：

- 其 `OPEN_QUESTIONS.md`、`M01_contracts/MODULE.md`、`M15_dcspa/MODULE.md`、`M16_vas/MODULE.md`、`project_state.json` 与当前工作区**逐字节相同**；
- ZIP 内 M15 也只有 2 个文件、M16 只有 3 个文件，**没有**缺失的 6 个 `.py`；
- ZIP 内没有 M19_api；
- ZIP 不能作为 P9 缺失文件的恢复来源。

---

## 2. 审计结论摘要

### 2.1 总体判定

| 维度 | 审计结果 |
|---|---|
| G0 规格冻结 | **PASS**（2026-11-10，用户宣布；`project_state.json` 有证据路径） |
| WP-01 环境锁定 | **DONE**（可复现的 3.11.16 / 64bit 环境与依赖锁存在） |
| WP-02 核心契约 | **DONE，但存在需整改的幂等响应缺陷**；原验收测试只断言 `task_id` 相同，未断言响应体一致 |
| P1 伪代码 | **ACCEPTED**（INDEX/STAGE_LOG 记录 2026-11-11） |
| P2–P8 伪代码 | **IN_REVIEW**（产物大部分齐全，但无逐阶段用户验收；P7/P8 未登记阶段日志） |
| P9 伪代码 | **不成立为 IN_REVIEW**：声明 11 文件 / 7,427 行，实际仅 5 文件 / 1,404 行，缺失 6 个 `.py` |
| P10 伪代码 | **未登记**：仅有 5 个 API `.py`，缺 `MODULE.md`、`NEGATIVE_TESTS.md`、阶段日志、OQ 与状态登记 |
| 全量 pytest | **当前 workspace-write 下不可通过**：112 passed / 23 failed / 20 errors，全部为环境 ACL，不是断言失败 |
| 冻结架构/API 契约 | 审计未发现需要修改冻结架构或公共 API 契约的证据；API 缺陷可通过实现修正回到 06 §4.2 冻结响应 |

### 2.2 不能进入 WP-03 的直接原因

1. `researchflow/api/app.py` 的幂等重放返回内部记录（含 `spec`），首次创建返回公共三字段；同一键同体两次 201 的响应体不一致，违反 06 §4.2 的 201 响应形状与 06 §4.5 的“返回原任务”语义。
2. P2 仍为 `IN_REVIEW`，且 `M02 §12-2`（Task/Node 创建 INSERT 路径归属）明确以 **WP-03 开工前**为死线，当前仍 OPEN。
3. P1–P10 没有统一的机器可读阶段状态；`INDEX.md`、`STAGE_LOG.md`、`OPEN_QUESTIONS.md`、`SESSION_HANDOFF.md` 与 `project_state.json` 互相冲突，WP-03 的前置阶段是否“已验收”无法从单一事实源判定。
4. P9 产物缺失且阶段状态失实；若继续以“P2–P9 已完成设计”为前提启动 WP-03，会把缺失的设计当作已冻结输入。
5. `BLK-003` 在 workspace-write 下已复现；全量 pytest 未通过，不能宣称当前测试环境满足验收。
6. `OQ-P1-03`、`OQ-P1-05` 标记 DECIDED 但无决议正文、无历史证据；不能把“已由用户处理”当成可追溯决议。

---

## 3. 问题清单

> 编号规则：`RF-<类别>-<序号>`。严重程度：P0 = 阻断正确性或验收；P1 = 会造成状态/文档/交接错误；P2 = 追溯性、清洁度或非阻断风险。
> “是否允许修改”：指本轮整改是否可以修改该对象；`否` 表示需要用户先裁决、属于冻结件、或不得凭空补造。

### 3.1 已确认缺陷（代码/产物/可复现事实）

| 编号 | 问题名称 | 严重程度 | 文件路径 | 代码位置 | 当前事实 | 预期状态 | 影响范围 | 修复建议 | 是否确认 | 是否允许修改 |
|---|---|---|---|---|---|---|---|---|---|---|
| RF-API-01 | 幂等重放响应体与首次创建不一致 | P0 | `researchflow/api/app.py` | L45–60、L150–183；首次响应 L179–183；重放 L153–157 | 首次 201 返回 `{task_id,state,graph_version}`；同键同体重放 201 返回内部记录 `{task_id,state,graph_version,spec}`；`first.json() != second.json()` 已复现 | 同键同体在相同业务条件下返回相同状态码、相同响应体结构、相同 `task_id`、一致 `graph_version`，不重复创建任务 | 违反 06 §4.2 冻结的 201 响应形状与 06 §4.5 幂等语义；客户端无法依赖重放响应；泄漏内部 `spec`；WP-03 接管时可能继承错误契约 | 将“内部任务记录”与“对外创建回执”分离；首次与重放共用同一公共响应体；补测试 A–E；不修改冻结契约 | 已确认（真实复现） | 是 |
| RF-PSEUDO-01 | P9 声明产物缺失且阶段记录失实 | P0 | `design/pseudocode/M15_dcspa/`、`M16_vas/`、`STAGE_LOG.md`、`INDEX.md` | M15 `MODULE.md` L26–29；M16 `MODULE.md` L26–28；`STAGE_LOG.md` L58–66（L61 为 11 文件/7,427 行）；`INDEX.md` L21–22（6/5 文件） | M15 仅有 `MODULE.md`、`NEGATIVE_TESTS.md`；M16 仅有 `MODULE.md`、`NEGATIVE_TESTS.md`、`strategies.py`；实际 5 文件 / 1,404 行；缺失 `dc_eligibility.py`、`dc_issuer.py`、`spa_judge.py`、`prr_ledger.py`、`risk_features.py`、`knapsack.py`；阶段仍标“待验收（IN_REVIEW）” | P9 状态应为 `IN_PROGRESS` 或 `BLOCKED`，缺失文件逐项登记；未补齐前不得标“待验收” | P9 验收结论不可信；OQ-P9 多条落点指向不存在的代码；后续 T2 设计可能以“已完成”为前提返工 | 修正阶段状态与文件计数；列出缺失文件；不凭空补写；由用户决定是否恢复/补齐；不删除现有文档 | 已确认（文件系统与 ZIP 双重核对） | 部分：状态与文档可改；缺失代码不得凭空补造 |
| RF-STATUS-01 | P1–P10 阶段状态无单一事实源，且各文件互相冲突 | P0 | `docs/state/project_state.json`、`design/pseudocode/INDEX.md`、`STAGE_LOG.md`、`OPEN_QUESTIONS.md`、`docs/SESSION_HANDOFF.md`、`docs/PROJECT_STATE.md` | `project_state.json` L394–416（`T-PSEUDO-001`，标题“当前至 P6”，`IN_REVIEW`，`blocker=null`）；`INDEX.md` L3–5、L21–22；`STAGE_LOG.md` L6–66；`OPEN_QUESTIONS.md` L7–13、L21–23、L29–39；`SESSION_HANDOFF.md` L19–36 | `project_state` 只有一个伞形任务；INDEX 说 12 模块/P1–P6 但表中有 14 行；STAGE_LOG 有 P1–P6、P9，无 P7/P8；OQ 有 P7/P8/P9 条目；SESSION 说 P7–P10 未开始；P9 又标待验收 | 每个 P1–P10 都有唯一状态、状态依据、验收证据与未完成项；`project_state.json` 为唯一机器可读事实源，其余文档只引用不另建状态 | R03/R10 无法通过；WP-03 无法确认 P2 是否已验收；新会话会得到互相矛盾的上下文 | 建立 P1–P10 阶段注册表（建议放在 `project_state.json` 的新段，状态严格使用 NOT_STARTED/IN_PROGRESS/IN_REVIEW/BLOCKED/ACCEPTED/DEFERRED）；同步所有状态文档；P9 标 IN_PROGRESS，P10 标 IN_PROGRESS；P1 ACCEPTED，P2–P8 IN_REVIEW | 已确认（逐文件对照） | 是（需先批准状态模型） |
| RF-STATUS-02 | P7/P8/P9 模块头声称前置阶段“已验收” | P1 | `design/pseudocode/M13_scheduler/MODULE.md`、`M14_recovery/MODULE.md`、`M15_dcspa/MODULE.md`、`M16_vas/MODULE.md`、`M17_agents/MODULE.md`、`M18_knowledge/MODULE.md` | M13 L6（“P2–P4 已验收”）；M14 L7（“P3 已验收、P2 已验收”）；M15 L7、M16 L8（“P5/P6/P7 已验收”）；M17/M18 L6（“P1–P7 已验收”） | 实际只有 P1 被记录为已验收；P2–P8 均为 IN_REVIEW，P9 产物缺失；这些“已验收”没有用户验收记录或证据路径 | 前置条件应写“设计产物存在；验收状态以 `project_state.json` 为准”，不得声称已验收 | 评审者会把未验收设计当成冻结输入；与状态文件冲突 | 改为事实性前置描述；保留“设计产物存在”的信息；不改变模块设计内容 | 已确认 | 是 |
| RF-WP03-01 | `M02 §12-2` 在 WP-03 开工前仍开放 | P0（WP-03 就绪性） | `design/pseudocode/M02_state_machine/MODULE.md`、`OPEN_QUESTIONS.md` | M02 L314–316；OQ `(无编号) §12-2` L31 | Task/Node 创建 INSERT 路径归属未定；M02 把“创建”与“状态迁移”分开，INSERT 只能进入初始状态，但未指定谁写；死线明确为 WP-03 开工前 | 在 WP-03 编码前由用户裁决并写入 ADR/模块决议；建议由 `StateMachine.create_initial()` 统一承担创建+初始审计，或明确 `TaskCreationPort` 的写权限与审计边界 | WP-03 可能绕过唯一状态入口，或创建路径无审计；这是 WP-03 返工风险最高的设计歧义 | 列入 A 类必须裁决；给出两个候选方案与影响；不自行批准 | 已确认（OQ 状态 OPEN） | 否（需用户裁决） |
| RF-BLK-003 | workspace-write 下全量 pytest 被环境 ACL 阻断 | P0（验收环境） | `docs/state/project_state.json`、`tests/test_state_sync.py` | `project_state.json` L553–563；`test_state_sync.py` L134–140、L103–110 | 2026-11-11 实测：112 passed、23 failed、20 errors；23 个失败全部在 `test_state_sync.py` 的 setUp/tearDown，`PermissionError [WinError 5]`，发生在 `C:\Users\...\Temp\dsh-*\rf_state_sync_*\docs` 子目录创建；无断言失败 | 在 workspace-write 下全量 pytest 通过，或按既定规则保持 `BLK-003` OPEN 并明确不能宣称全量通过 | R09/R11 无法通过；WP-02 的“125 passed”记录无法在当前策略下复现；不能把环境失败说成业务失败，也不能把部分通过说成全量通过 | 保留 OPEN；补最小写入探针与精确日志；如获用户批准，可在一次性 full-access 会话中补跑业务测试，但不得据此关闭 workspace-write 阻塞，也不得用于安全项 | 已确认（真实复现） | 否（环境/权限变更需批准；不得改测试规避） |
| RF-P1-OQ | `OQ-P1-03`、`OQ-P1-05` 标 DECIDED 但无决议正文 | P1 | `design/pseudocode/M01_contracts/MODULE.md`、`M03_config_env/MODULE.md`、`OPEN_QUESTIONS.md`、`STAGE_LOG.md` | M01 L81；M03 L112；OQ L21、L23；STAGE_LOG L11 | 两行只写“已由用户处理，本模块不再记录”；无问题原文、无裁决正文、无证据来源；`git log -S` 仅命中两个包含该占位句的提交；ZIP 版本相同；未找到会议记录、阶段报告或历史决议 | 有真实决议正文与证据来源，或明确标记 `NEEDS_CONFIRMATION` 并保留待补状态；不得以 DECIDED 掩盖缺证 | P1 验收追溯链断裂；后续阶段可能把不存在的裁决当先例 | 不编造；在 M01/M03/OQ 标 `NEEDS_CONFIRMATION`（或经用户批准的新证据状态），记录已执行的搜索范围与否定结果；请用户补正文或确认“无法恢复” | 已确认（缺证） | 否（需用户确认） |
| RF-README-01 | README 仍描述 WORKSTATION_SETUP / 无业务代码 / G0 未通过 | P1 | `README.md` | L5、L6、L13、L14、L22、L23、L57、L79、L81 | 声称“当前处于 WORKSTATION_SETUP”“尚未开发业务代码”“G0–G7 均 NOT_STARTED”“G0 仍有 3 项待裁决”“未创建 .venv、未安装依赖”“当前阶段：阶段 7” | 反映 G0 PASS、WP-01/WP-02 DONE、`researchflow/` 已有模型与 API、`.venv` 与依赖已锁定、P1 ACCEPTED/P2–P8 IN_REVIEW/P9 IN_PROGRESS/P10 IN_PROGRESS、BLK-003 OPEN、下一步为 WP-03 前置整改 | 新会话/外部读者得到错误项目阶段；R05 不通过 | 重写状态区、目录表、环境节、当前阶段节；保留策划书版本决议；不把 WP-02 缺陷写成已解决 | 已确认 | 是 |
| RF-WORKFLOW-01 | DEVELOPMENT_WORKFLOW 仍以“G0 未通过、0 commit、阶段 7”约束描述当前 | P1 | `docs/DEVELOPMENT_WORKFLOW.md` | L3、L24、L112、L181、L189–L190、L221–L229 | 称“G0 仍有 3 项待裁决”“G0–G7 全部 NOT_STARTED”“last_verified_commit=null；0 commit”“当前阶段执行约束（阶段 7）：不 commit、不建 .venv……”；实际 G0 PASS、7 commits、`.venv` 存在 | 当前状态段落与 `project_state.json` 一致；历史阶段 7/8 约束保留但明确标“历史”；开发流程、门禁、WP-03 入口条件分开陈述 | R06 不通过；新会话可能继续按阶段 7 禁令执行或误以为不能提交 | 重写 §1、§5.2、§8、§9、§11 的现状部分；保留历史规则并加“历史”标记；新增 WP-03 入口条件 | 已确认 | 是 |
| RF-HANDOFF-01 | SESSION_HANDOFF 最新交接已过期 | P1 | `docs/SESSION_HANDOFF.md` | L19–L36（最新条目）；L26“P7–P10 未开始” | 最新条目仍说 P2–P6 待验收、P7–P10 未开始、M13/M14/M17/M18 未纳入提交；未提 M15/M16/M19；未提 P9 缺失 | 最新条目准确记录当前阶段、P1–P10 状态、WP-02 缺陷、BLK-003、下一步与禁止事项；旧条目保留为历史 | 下一次会话会按错误上下文继续；R03/R10 不通过 | 新增置顶交接；保留旧条目；明确“旧条目中的阶段状态已被本条目取代” | 已确认 | 是 |
| RF-P10-01 | P10/M19 产物未登记、缺模块文档 | P1 | `design/pseudocode/M19_api/` | 目录仅 5 个 `.py`；无 `MODULE.md`、`NEGATIVE_TESTS.md`；`INDEX.md` 无 M19；`STAGE_LOG.md` 无 P10；`OPEN_QUESTIONS.md` 无 P10；`project_state.json` 无 P10 | P10“接入、实验与交付”仅有部分 API 伪代码，未登记状态，无法判断是授权在研还是遗留产物 | 登记为 P10 `IN_PROGRESS`，列出已有/缺失产物；或由用户确认删除/迁移（不得擅删） | 孤儿产物；后续 API 落地可能重复设计；R04 不通过 | 在阶段注册表登记 P10；补充缺失文档或明确挂起；保留现有文件 | 已确认 | 是（登记/文档），否（删除需批准） |
| RF-DOC-01 | PROJECT_OVERVIEW / ARCHITECTURE 的现状节已过期 | P1 | `docs/PROJECT_OVERVIEW.md`、`docs/ARCHITECTURE.md` | OVERVIEW L120、L154–L164；ARCHITECTURE L1–L3、L516–L529 | 两者仍称 T0 未开始、G0–G7 全 NOT_STARTED、`researchflow/` 只有 `.gitkeep`、`contracts/` 为空、G0 尚未冻结/通过 | 现状节指向 `project_state.json`；明确“本文件为阶段 7 知识快照，当前状态以 JSON 为准”；不修改架构规则本身 | R03/R10 仍有非机器源冲突；新会话可能读旧结论 | 更新现状节/页首状态指针；保留历史快照说明；不把架构规则改写 | 已确认 | 是（状态节），否（冻结架构语义） |
| RF-DOC-02 | G0_DECISION_LIST 页首仍称 G0 未裁决/未通过 | P2 | `docs/state/G0_DECISION_LIST.md` | L3–L4、L6–L10、L20 | 页首说“未裁决；不改变 G0 NOT_STARTED”；第 2–4 项表格仍“待裁决”；下方更新注说 2026-11-10 已裁决，但页首未标记历史 | 作为历史记录保留原始表；页首加“历史文件；G0 已于 2026-11-10 PASS；2–4 项已裁决，见更新注” | 读者可能把历史待裁决项当成当前开放项 | 只加历史横幅/指针；不改原表内容 | 已确认 | 是 |

### 3.2 已确认但非阻断的追溯/工程质量问题

| 编号 | 问题名称 | 严重程度 | 文件路径 | 代码位置 | 当前事实 | 预期状态 | 影响范围 | 修复建议 | 是否确认 | 是否允许修改 |
|---|---|---|---|---|---|---|---|---|---|---|
| RF-STATE-01 | `T-PSEUDO-001` 元数据过期且无阻塞标记 | P1 | `docs/state/project_state.json` | L394–416 | 标题“P0 伪代码规格阶段（P1–P10，当前至 P6）”；状态 `IN_REVIEW`；`blocker=null`；验收标准只写“P1–P7 覆盖…P8–P10 覆盖…” | 标题反映 P1–P10；P9 缺失应挂阻塞/未完成说明；阶段状态由注册表承载 | 与 INDEX/STAGE_LOG 冲突；P9 缺失被掩盖 | 随 RF-STATUS-01 一并修正；不把 P2–P8 标 DONE | 已确认 | 是（需批准状态模型） |
| RF-API-02 | 幂等键字符集/长度未校验，OQ §12-8 仍 OPEN | P1（WP-03 前置） | `researchflow/api/app.py`、`M02_state_machine/MODULE.md`、`OPEN_QUESTIONS.md` | app L151；M02 L328；OQ L37 | 任意 `Idempotency-Key`（含空串、超长、空白）都被接受并存入内存；M02 提议可见 ASCII 1–255 无空白；06 §4.5 未冻结 | 在 WP-03 建表前确定字符集/长度/空键语义，并与 API 422 行为一致 | WP-03 SQLite 约束可能与 API 行为冲突；空键语义不一致 | 用户裁决；建议 1–255 可见 ASCII、空键 422 `SCHEMA_INVALID`；不在未批准前擅自改公共行为 | 已确认（行为）；决策未定 | 否（需裁决） |
| RF-API-03 | 请求哈希不是 JCS，与 M02 设计口径不一致 | P2 | `researchflow/api/app.py`、`M02_state_machine/MODULE.md` | app L63–65；M02 L268 | 使用 `json.dumps(sort_keys=True)`；M02 写 `sha256(JCS(原始请求体))`；06 §4.5 只写“规范化请求哈希” | 明确 WP-03 使用的规范化算法；WP-02 存根与 WP-03 持久层不能产生不同的同键判定 | 迁移后同一键同体可能变成异体；历史键不可复用 | 在 WP-03 前裁决；建议统一为 JCS 或明确记录“WP-02 存根非最终算法”；不静默改 | 已确认（实现差异） | 否（需裁决） |
| RF-API-04 | `GET /tasks/{id}` 直接返回内部记录（含 `spec`），响应契约未定义 | P2（待确认） | `researchflow/api/app.py` | L185–190 | 200 返回 `{task_id,state,graph_version,spec}`；06 §4.1 只说“任务详情、状态、资源摘要”；M19 P10 拟返回 `created_at/spec/resource_summary` | 06 明确 GET 响应字段，或项目决定 `spec` 属于可公开详情；不得把内部记录直接当公共 DTO | 若 `spec` 不应公开，则是泄漏；若应公开，则当前缺 `created_at/resource_summary` 且与 P10 设计不一致 | 作为契约澄清项，不擅自改 GET；在 WP-03/API 阶段定义响应 DTO | 未确认（契约未定义） | 否（需契约澄清） |
| RF-STATE-02 | `last_verified_commit` 与 HEAD 不一致 | P2 | `docs/state/project_state.json` | L565 | `1c9a104`；HEAD `309083e`；`check_docs_drift` WARNING=1 | 在有真实提交且验证后更新；未提交整改前不得声称 HEAD 已验证 | R12/状态追溯；不影响业务正确性 | 整改完成并获提交授权后更新；否则保留并在报告中说明 | 已确认 | 否（需提交授权） |
| RF-DOC-03 | 冻结 G0/PRD/design 文末仍有“G0 未 PASS、未建 .venv、未写业务代码”的历史状态 | P2（历史遗留） | `docs/G0/01_BASELINE_AND_TERMS.md`、`docs/PRD/02_REQUIREMENT_TRACEABILITY.md`、`docs/PRD/03_PRD_T0.md`、`docs/design/04_ARCHITECTURE.md`、`05_CONTRACTS_AND_STATES.md`、`06_DATA_AND_API.md`、`07_T0_PLAN_AND_GATES.md` | 各文末“标记”段；例如 04 L261、05 L595、06 L461、07 L478、G0/01 L55–L63 | 这些是 G0 冻结时的历史快照，文字真实反映冻结时点；当前已 G0 PASS、已有 `.venv`/业务代码 | 冻结文件不得改写；由当前状态文档明确“冻结件状态段为历史快照，当前以 JSON 为准” | 若被当作当前事实，会与 README/JSON 冲突 | 不修改冻结件；在 README/DEVELOPMENT/OVERVIEW 加指针说明 | 已确认 | 否（冻结件） |
| RF-CLEAN-01 | 测试/缓存/临时残留 | P2 | `.pytest_cache/`、根 `__pycache__/`、`researchflow/**/__pycache__/`、`tests/__pycache__/`、`tmp/unittest-temp/`、`tmple0ojac0/` | 目录级 | `.pytest_cache` 4 文件；`tmp/unittest-temp` 23 个 `rf_state_sync_*` 残留；`tmple0ojac0` 空；均被 `.gitignore` 覆盖 | 保留 `.gitignore`；只清理已确认的缓存/测试残留；不删除 `tmp/stage6_asar`（阶段 6 证据）与 `tmp/commitmsg_g0.txt` | 目录清洁；误删风险低但需批准 | 经批准后删除 `__pycache__`/`.pytest_cache`/`tmp/unittest-temp`/空 `tmple0ojac0`；记录 before/after | 已确认 | 否（删除操作需批准） |
| RF-OPEN-01 | `OQ-DB-2` 与 §12-1..§12-10 的状态/死线未纳入阶段状态依据 | P1 | `OPEN_QUESTIONS.md`、`M02_state_machine/MODULE.md` | OQ L29–39；M02 L310–361 | 11 条 OPEN/DEFERRED 问题存在，但 `T-PSEUDO-001` 的 `blocker=null`，没有“哪些阻塞 WP-03”的结构化标记 | 每条 OQ 有状态/死线/阻塞对象；WP-03 前必须关闭的项在阶段注册表中显式阻塞 | WP-03 可能在关键歧义未决时启动 | 在阶段注册表/状态文件中标 A/B/C/D 分类；不擅自关闭 OPEN | 已确认 | 是（分类/登记），否（裁决） |
| RF-PSEUDO-02 | P7/P8 没有 STAGE_LOG 条目，未登记阶段收尾 | P1 | `design/pseudocode/STAGE_LOG.md`、`INDEX.md` | STAGE_LOG L56–66；INDEX L3–5 | P7（M13/M14，11 文件/6,576 行）与 P8（M17/M18，15 文件/9,361 行）产物存在；STAGE_LOG 无 P7/P8 条目；INDEX 说“未纳入本表” | 补登 P7/P8 阶段日志（实际文件/行数、自检结论、未验收），INDEX 收录 M13/M14/M17/M18/M19 或明确排除理由 | R04 归属不清；P7/P8 是否算“完成”无依据 | 追加 P7/P8 日志；不改历史；标明“未验收，仅静态自检” | 已确认 | 是 |
| RF-PSEUDO-03 | P9 OQ 落点引用不存在的代码 | P1 | `OPEN_QUESTIONS.md`、`M15_dcspa/MODULE.md`、`M16_vas/MODULE.md` | OQ-P9-01/02/03/06/07/08/09/10/11/12/14/15 的落点列；M15 L26–29；M16 L26–28 | 多条 OQ 指向 `dc_issuer.compute_dc_id`、`spa_judge`、`knapsack`、`risk_features` 等不存在文件 | 落点应指向真实存在的文件；缺失文件应先登记为 P9 未完成项 | 追溯链失效；评审无法按落点核对 | 与 RF-PSEUDO-01 一并修正；保留 OQ 编号与问题本身 | 已确认 | 是（文档），否（补代码） |

### 3.3 尚待验证的问题

| 编号 | 问题 | 为何未确认 | 需要什么证据/裁决 |
|---|---|---|---|
| RF-UNVER-01 | P9 缺失的 6 个 `.py` 是否存在于其他会话/机器/备份 | 工作区、Git 全历史、当前 ZIP 均无；未搜索项目外全部磁盘（只读搜索了工作区邻近目录与 Downloads） | 用户确认是否有其他副本；若没有，只能将 P9 标 IN_PROGRESS/BLOCKED，不得重写冒充原件 |
| RF-UNVER-02 | P7/P8 是否曾被用户口头/书面验收 | `STAGE_LOG`/`project_state` 无记录；模块头却写“已验收”；可能是并发会话产物 | 用户确认；若无，保持 IN_REVIEW，不得补写“已验收” |
| RF-UNVER-03 | P10/M19 是否为授权产物 | 无 INDEX/STAGE_LOG/OQ/状态记录；文件时间晚于最后一次状态同步 | 用户确认；建议登记为 P10 IN_PROGRESS，保留文件，不删除 |
| RF-UNVER-04 | `GET /tasks/{id}` 的 `spec` 是否属于公共响应 | 06 §4.1 只给“任务详情、状态、资源摘要”，未列字段；M19 P10 提案含 `spec` | 需要契约澄清/用户裁决；本轮不擅自改 GET |
| RF-UNVER-05 | full-access 下业务测试是否全绿 | 当前 workspace-write 只跑到 112 passed；全量被环境 ACL 阻断；未获准切换权限 | 用户批准一次性 full-access 运行；结果只用于业务回归，不用于关闭 BLK-003/安全项 |
| RF-UNVER-06 | 幂等键字符集与 JCS 哈希是否应按 M02 提案冻结 | 06 未定义；M02 是伪代码提案，不是冻结契约；改动会影响公共行为 | 用户裁决；WP-03 前必须定 |

### 3.4 仅属于未来开发任务、本次不得实施的事项

- SQLite 正式持久化、数据库迁移、StateMachine 运行时代码、audit_log 真实写入。
- DAG 调度引擎、Executor、Collector、Gate、Verifier L1/L2/L3、Ed25519/JCS/Merkle、签名、证据包、`verify_bundle.py`。
- WP-03 及后续工作包的任何业务实现。
- P9 缺失伪代码的“补写”若没有原始来源，属于设计补做，不是本次 P0 整改；需用户另行授权。
- P10/M19 的正式 API 实现；当前只有伪代码。

---

## 4. P1–P10 阶段矩阵（审计时点的真实产物）

> 统计口径：文件数 = 模块目录下全部文件；行数 = 以 UTF-8 文本换行计（与 `git show --numstat` 的新增行口径一致）。P1–P6 的行数与 `STAGE_LOG` 完全一致；P7/P8 无日志，按实际文件统计；P9/P10 为缺失状态。

| 阶段 | 模块 | 实际文件数 | 实际行数 | 应有状态 | 状态依据 | 未完成/缺口 |
|---|---|---:|---:|---|---|---|
| P1 契约对齐与配置基座 | M01、M03 | 14 | 3,229 | **ACCEPTED** | `INDEX.md` L9、`STAGE_LOG.md` L6–12；用户 2026-11-11 验收 | `OQ-P1-03/05` 决议正文缺失（RF-P1-OQ） |
| P2 持久层与状态机 | M02 | 10 | 5,991 | **IN_REVIEW** | `STAGE_LOG.md` L14–20；无用户验收记录 | §12-2 阻塞 WP-03；§12-1..§12-10 多数 OPEN；负例未执行 |
| P3 DAG 与执行器 | M04、M05 | 14 | 7,858 | **IN_REVIEW** | `STAGE_LOG.md` L22–28；无用户验收记录 | 负例未执行；OQ-P3-01/05/06/07/08/10 OPEN |
| P4 模板与证据链 | M06、M07 | 14 | 6,109 | **IN_REVIEW** | `STAGE_LOG.md` L30–36；无用户验收记录 | OQ-P4-01 等 OPEN；E3 写入路径未实现 |
| P5 门控与三级验证 | M08、M09、M10 | 16 | 7,923 | **IN_REVIEW** | `STAGE_LOG.md` L38–44；无用户验收记录 | OQ-P5-01/02/03/04/09/10/12 OPEN |
| P6 签名与离线凭证 | M11、M12 | 11 | 7,584 | **IN_REVIEW** | `STAGE_LOG.md` L46–52；无用户验收记录 | OQ-P6 多条 OPEN；非 VERIFIED 签名口径未定 |
| P7 调度与定向恢复 | M13、M14 | 11 | 6,576 | **IN_REVIEW** | 产物存在；**无 STAGE_LOG**；模块头错误声称 P2–P4 已验收 | 未登记收尾；未验收；OQ-P7-01..12 OPEN/DEFERRED |
| P8 六角色与知识库 | M17、M18 | 15 | 9,361 | **IN_REVIEW** | 产物存在；**无 STAGE_LOG**；模块头错误声称 P1–P7 已验收 | 未登记收尾；未验收；OQ-P8-01..13 OPEN/DEFERRED |
| P9 DC/SPA 与 VAS | M15、M16 | **5** | **1,404** | **IN_PROGRESS**（不是 IN_REVIEW） | `STAGE_LOG.md` L58–66 声称 11 文件/7,427 行；实际缺 6 个 `.py` | M15 缺 4 个 `.py`；M16 缺 2 个 `.py`；无法验收 |
| P10 接入、实验与交付 | M19 | 5 | 2,138 | **IN_PROGRESS** | 仅 5 个 API 伪代码；无 `MODULE.md`/`NEGATIVE_TESTS.md`/日志/状态 | 缺模块文档、负例、阶段记录；未登记 |

**结论：** 只有 P1 可以被表述为“已验收”；P2–P8 最多是“产物存在、待验收”；P9 是“未完成”；P10 是“部分产物、未登记”。任何“P2–P9 已完成”或“P1–P7 已验收”的表述都必须删除或改为事实性描述。

---

## 5. 关键问题的详细证据

### 5.1 API 幂等重放缺陷（RF-API-01）

真实复现命令（只读，未写项目文件）：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& .venv/Scripts/python.exe -c "..."   # 见 §1.4 执行记录
```

真实输出：

```text
first_status 201
second_status 201
first_keys  ['graph_version', 'state', 'task_id']
second_keys ['graph_version', 'spec', 'state', 'task_id']
bodies_equal False
first_body  {"graph_version":1,"state":"CREATED","task_id":"task_1a59189b-..."}
second_body {"graph_version":1,"state":"CREATED","task_id":"task_1a59189b-...",
             "spec":{...完整 TaskSpec...}}
```

对照冻结契约：

- `docs/design/06_DATA_AND_API.md` L305–309 的 201 响应明确只有 `task_id`、`state`、`graph_version`；
- L379–391 的幂等规则要求“同键同体返回原任务”，没有授权额外返回 `spec`；
- `tests/test_api_422.py` L111–117 只断言状态码和 `task_id`，没有断言完整响应体，因此原验收 `docs/verification/t0/wp-02/40_wp02_acceptance.md` L17 的“幂等”判定不充分。

**修复边界：** 只改实现，不改 06/contracts；首次与重放共用同一公共响应体；GET 行为不在本项修复范围内（另见 RF-API-04）。

### 5.2 P9 产物缺失（RF-PSEUDO-01）

`design/pseudocode/M15_dcspa/MODULE.md` L26–29 声明 4 个“完成（伪代码）”文件：

```text
orchestration/determinism/dc_eligibility.py   1,317 行
orchestration/determinism/dc_issuer.py          973 行
orchestration/determinism/spa_judge.py        1,327 行
orchestration/determinism/prr_ledger.py         842 行
```

实际目录只有：

```text
M15_dcspa/MODULE.md
M15_dcspa/NEGATIVE_TESTS.md
```

`design/pseudocode/M16_vas/MODULE.md` L26–28 声明 3 个文件：

```text
orchestration/vas/risk_features.py   749 行    ← 缺失
orchestration/vas/knapsack.py        815 行    ← 缺失
orchestration/vas/strategies.py      644 行    ← 存在
```

实际目录只有 `MODULE.md`、`NEGATIVE_TESTS.md`、`strategies.py`。

`STAGE_LOG.md` L61 声称“产出文件数 / 总行数：11 / 7,427”，L62 标“待验收（IN_REVIEW）”；`INDEX.md` L21–22 声称 M15 6 文件、M16 5 文件。实际 5 文件 / 1,404 行。该差异不是“行数口径”问题，而是 **6 个文件不存在**。

### 5.3 状态源冲突（RF-STATUS-01）

以“P7 是否开始”为例，同一时点存在四种表述：

| 文件 | 表述 |
|---|---|
| `docs/SESSION_HANDOFF.md` L26 | “P7–P10 未开始” |
| `design/pseudocode/INDEX.md` L4 | “P7/P8 的 M13/M14/M17/M18 未纳入本表” |
| 文件系统 | `M13_scheduler/`、`M14_recovery/` 共 11 文件 / 6,576 行，均存在 |
| `design/pseudocode/M13_scheduler/MODULE.md` L6 | “前置：P2–P4 已验收” |

以“P9 是否可验收”为例：

| 文件 | 表述 |
|---|---|
| `STAGE_LOG.md` L62 | “待验收（IN_REVIEW）” |
| `INDEX.md` L21–22 | “待验收”，6/5 文件 |
| 文件系统 | 5 文件 / 1,404 行，缺 6 个 `.py` |
| `M15_dcspa/MODULE.md` L7 | “前置：P5 验证、P6 签名、P7 恢复已验收” |

这类冲突不能靠“以某一份文档为准”解决，必须在 `project_state.json` 中建立唯一阶段状态，再由 INDEX/STAGE_LOG/OPEN_QUESTIONS/SESSION_HANDOFF 引用。

### 5.4 OQ-P1-03 / OQ-P1-05 的证据搜索（RF-P1-OQ）

已执行：

1. 工作区全文搜索 `OQ-P1-03|OQ-P1-05`：仅命中 M01/M03 的“已由用户处理”、OPEN_QUESTIONS 两行、STAGE_LOG 一行；
2. `git log --all -S'OQ-P1-03'` / `-S'OQ-P1-05'`：只命中 `1c9a104`、`309083e` 两个提交，内容均为占位句；
3. `git log --all --diff-filter=D`：无删除文件记录；
4. 当前 ZIP（`D:\ResearchFlow-project.zip`）内对应文件与工作区逐字节相同；
5. 邻近目录与 Downloads 未发现其他项目归档；未发现会议记录、阶段报告或历史决议文件。

结论：**无法恢复原始问题与裁决正文**。只能标注 `NEEDS_CONFIRMATION`；不得把占位句改写成推测内容。

### 5.5 BLK-003 复现（RF-BLK-003）

命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

真实结果：

```text
112 passed, 23 failed, 20 errors in 3.19s
exit 1
```

失败全部集中在 `tests/test_state_sync.py`：

- 23 个测试的 `setUp` 在 `tempfile.TemporaryDirectory(prefix="rf_state_sync_")` 下创建 `docs/state` 时得到 `PermissionError: [WinError 5]`；
- 20 个 `tearDown` 在清理临时目录时同样得到 `PermissionError`；
- 无 `AssertionError`，无业务代码失败；
- 失败路径示例：`C:\Users\ADMINI~1\AppData\Local\Temp\dsh-cKWUng\rf_state_sync_*\docs`。

这与 `project_state.json` L553–563 的历史描述一致，但 2026-11-11 的旧复核没有真正运行 pytest；本次补上了真实运行。**BLK-003 仍为 OPEN**；在 workspace-write 下全量 pytest 未通过，不能关闭。

### 5.6 WP-03 前置设计问题（RF-WP03-01）

`M02_state_machine/MODULE.md` L314–316：

> “任务/节点创建写者：06 §3 写‘tasks/nodes W=StateMachine’，但创建 INSERT 路径未分配。M02 把‘创建’与‘状态迁移’分开：INSERT 只能进入初始状态，之后只能 transition。待 WP-03 确认创建入口归属。”

`OPEN_QUESTIONS.md` L31 将 `§12-2` 标为 `OPEN`，死线“WP-03 开工前”。这是 WP-03 唯一被明确标为“开工前必须关闭”的 P2 问题；另有 §12-8 标“WP-02（幂等实现）”，但 WP-02 已经实现，实际需在 WP-03 建表前定稿。

---

## 6. WP-03 前置问题分类（A/B/C/D）

> 分类标准：A = WP-03 编码前必须裁决；B = 可留到对应后续 WP；C = 需要用户确认（含冻结契约/公共行为）；D = 需要实验或环境验证。

| 编号 | 问题 | 分类 | 理由 | 建议处理 |
|---|---|---|---|---|
| §12-2 | Task/Node 创建 INSERT 路径归属 | **A + C** | WP-03 第一行代码就要决定谁创建初始行；涉及“StateMachine 唯一写入口”边界 | 用户裁决；建议 `StateMachine.create_initial()` 统一创建 + 初始审计，API 只调用该入口 |
| §12-6 | Task/Node `BLOCKED` 是否为终态 | **A + C** | 直接决定迁移表；05 §9.2/§9.3 未给出边 | 用户裁决；建议 T0 视为终态，解除阻塞需新 ADR |
| §12-7 | `idempotency_keys.task_id` 可空性/FK | **A + C** | WP-03 建表；06 DDL 可空，M02 收紧 NOT NULL + FK，属于对冻结 DDL 的偏离 | 用户裁决；建议 NOT NULL + FK + 同事务；若坚持“先占键后建任务”则改可空/延迟 FK |
| §12-8 | 幂等键字符集/长度/空键 | **A + C** | WP-03 建表约束与 API 422 行为必须一致；06 未定义 | 用户裁决；建议 1–255 可见 ASCII、无空白、空键 422 |
| §12-5 | 冻结事件先后用 `created_at` 是否足够/时钟回拨 | **A + D** | WP-03 审计排序与恢复守卫需要；强单调序要加 `audit_seq`（schema 变更） | 先按 fail-closed 实现；是否需要 `audit_seq` 用实验/评审确认 |
| §12-1 | Evidence 摄入状态持久化 | B | WP-07 才写入证据表 | 保留 M02 不加列方案；WP-07 前 ADR/MINOR |
| §12-3 | 失败审计的“声称旧值/实际旧值” | B | WP-08 失败审计测试才需要 | 保留 M02 方案；WP-08 前确认 |
| §12-4 | `audit_id`/`invalidation_id` 形态 | B | WP-03 可用不透明 UUID，不影响正确性 | 记录为 T0 实现选择；如需前缀再改 |
| §12-9 | `OBJECT_NOT_FOUND` 是否映射 404 | B + C | API 查询已实际返回 404；06 未定义错误码映射 | WP-08/API 错误映射前裁决；当前 GET 404 不改 |
| §12-10 | Verifier 能否直接驱动 Node 状态 | B | WP-11/WP-12 集成才需要 | 保持 M02 边界：Verifier 只签发报告/证书 |
| `OQ-DB-2` | 幂等键保留期/清理 | B | 不影响 WP-03 建表；T0 可保留至任务完成 | WP-03 建表留字段；清理策略后置 |
| `OQ-P1-03/05` | 缺决议正文 | **C** | 无法从证据恢复 | 用户补正文或确认标 `NEEDS_CONFIRMATION`；不影响 WP-03 代码，但影响 P1 追溯完整性 |

**WP-03 进入条件建议（在用户批准后写入文档）：**

1. API 幂等缺陷已修复，测试 A–E 通过；
2. P2 状态为 `ACCEPTED`（由用户正式验收），或用户明确书面豁免 P2 阶段验收；
3. §12-2、§12-6、§12-7、§12-8 已裁决并写入 M02 `DECISIONS`/ADR；
4. P9 缺失状态已如实登记（不作为 WP-03 输入）；
5. `BLK-003` 状态如实保留（OPEN）并记录其对全量验收的影响；
6. 不把 P0 整改 PASS 等同于 G1 PASS。

---

## 7. 历史遗留问题（保留，不重写历史）

以下内容不应被当作当前状态，也不应删除：

1. `docs/CHANGELOG_DEV.md` 中早期“0 commit / 未建 .venv / G0 NOT_STARTED”记录：历史事实，保留。
2. `docs/SESSION_HANDOFF.md` L38 以后的旧交接：历史记录，保留；只新增置顶条目。
3. `docs/G0/01_BASELINE_AND_TERMS.md`、`docs/PRD/02`、`03`、`docs/design/04`–`07` 文末的冻结时点状态标记：冻结件，保留原文；不得用当前状态覆盖。
4. `docs/memory/feedback-and-lessons.md` 中“G0–G7 全部 NOT_STARTED”的教训条目：历史语境，保留；不据此判断当前状态。
5. `docs/SKILL_CATALOG.md` 中阶段验证记录：历史验证结果，保留。
6. `docs/verification/stage8/G0_DECISION_LIST.md` 的“待裁决”表：历史输入；页首加历史横幅即可，不改表。

---

## 8. 本次审计未做的事（边界声明）

- 未修改任何既有项目文件；未改 `contracts/`、`docs/design/`、`docs/ADR/`、`researchflow/`、`tests/`。
- 未实现 WP-03 或任何后续工作包。
- 未关闭、未降级 `BLK-003`。
- 未修改 `project_state.json` 的任何状态。
- 未 commit、未 `git add`、未改 Git 身份。
- 未删除缓存/临时目录/未跟踪文件。
- 未把 P9 缺失文件补写成“已完成”。
- 未把 `OQ-P1-03/05` 的占位句改写成推测决议。

---

## 9. 审计结论与待批准事项

### 9.1 结论

审计前状态：**FAIL（整改前）**。理由：

- R01 API 幂等一致性：**不通过**（已复现）；
- R03 P1–P10 状态统一：**不通过**（多源冲突）；
- R04 P7/P8/P9 归属：**不通过**（P9 缺 6 文件；P7/P8 未登记）；
- R05 README：**不通过**；
- R06 DEVELOPMENT_WORKFLOW：**不通过**；
- R07 P1 决议：**不通过/缺证**；
- R08 P2 前置决议：**不通过**（§12-2 等未决）；
- R09 BLK-003：**OPEN**（已复现，不能关闭）；
- R10 PROJECT_STATE 与 JSON：**表面一致**（生成文件与 JSON 一致，但 JSON 本身缺阶段状态）；
- R11 测试环境：**部分通过**（112 业务测试通过；全量被 ACL 阻断）；
- R12 修改安全性：**基线已记录；尚未修改**。

### 9.2 需要用户批准/裁决的事项

1. **是否批准第二阶段**：按本报告与 `P0_REMEDIATION_PLAN.md` 修复 `researchflow/api/app.py` 的幂等响应，并新增测试 A–E；不改变冻结契约。
2. **P1–P10 状态模型**：推荐在 `project_state.json` 增加 `pseudocode_stages` 段（严格使用 NOT_STARTED/IN_PROGRESS/IN_REVIEW/BLOCKED/ACCEPTED/DEFERRED），并扩展 `state_sync.py validate/render`；备选是新增 10 个任务并使用既有任务状态（需接受 ACCEPTED↔DONE 映射）。请选择。
3. **OQ-P1-03/05**：请提供当时的决议正文/来源；若无法提供，是否批准标为 `NEEDS_CONFIRMATION`（而不是继续标 DECIDED）。
4. **WP-03 前置裁决**：是否批准本报告 §6 的建议（§12-2 由 `StateMachine.create_initial()` 统一创建；§12-6 T0 视 BLOCKED 为终态；§12-7 NOT NULL+FK；§12-8 1–255 可见 ASCII、空键 422）。如不同意，请给出替代口径。
5. **BLK-003**：是否批准一次性 full-access 运行全量 pytest，仅用于业务回归、**不关闭 BLK-003**、不用于安全项；若不批准，最终报告将保留“全量测试环境阻塞”。
6. **P9 缺失文件**：是否有其他副本可恢复；若无，是否批准将 P9 标为 IN_PROGRESS/BLOCKED 并保留缺口清单（不补写、不删除现有文档）。
7. **P10/M19**：是否确认其为授权在研产物；建议登记为 P10 IN_PROGRESS，不删除。
8. **提交与 `last_verified_commit`**：整改完成后是否授权创建提交并更新该字段；若否，最终报告将保留 `check_docs_drift` 的 WARNING 并说明工作区已验证但未提交。
9. **文档清理**：是否批准更新非冻结的 `docs/PROJECT_OVERVIEW.md`、`docs/ARCHITECTURE.md` 现状节与 `docs/state/G0_DECISION_LIST.md` 历史横幅；冻结件不修改。
10. **缓存/临时目录**：是否批准清理 `.pytest_cache`、`__pycache__`、`tmp/unittest-temp`、空 `tmple0ojac0`；保留 `tmp/stage6_asar` 与 `tmp/commitmsg_g0.txt`。

> 在收到批准前，不进入第二阶段，不修改任何既有项目文件。