# AGENTS.md — ResearchFlow 项目规则

> 项目：ResearchFlow
> 适用范围：`D:\ResearchFlow-project` 及其全部子目录
> 版本：阶段 5 基线（2026-11-08）；2026-11-11 P0 治理修订；2026-11-12 运行时状态词汇与记忆同步
> 地位：本文件是本项目的主要规则来源。`$DSH_HOME/AGENTS.md`（实际路径 `C:\Users\Administrator\.dsh\AGENTS.md`）当前不存在；如未来创建，只放跨项目通用纪律，不重复本项目内容。
> 优先级：用户当前明确指令 > 本文件 > 其他项目文档。若本文件与已冻结架构、策划书或 ADR 冲突，先停止并报告，不得自行取舍。

## 0. 每次任务开始前的指令自检

1. 确认本 `AGENTS.md` 已由 DSH 的 `agent-instructions` 加载；未加载时先报告，不得凭记忆执行。
2. 先读 `docs/state/project_state.json`，确认当前阶段、里程碑、门禁、阻塞项与 `last_verified_commit`。
3. 再读 `docs/memory/Memory.md`，按索引只加载与当前任务相关的记忆子文件。
4. 根据任务读取相关 PRD、架构、ADR、契约与测试文档；不要一次性注入全部文档或全部 Skill 全文。
5. 复杂任务先只读探索并形成计划；跨模块、Schema、数据库、状态机、安全边界或冻结架构变更，先提交方案与 diff 计划，等待确认后再改。

## 1. 行为规范

1. 所有交流使用简体中文。
2. 不确定事项明确标注为“待核实”或“未确认”，不得用确定语气掩盖不确定性。
3. 不得编造测试结果、性能数据、实验成绩和第三方证明。
4. 不得擅自修改已冻结架构。
5. 不得为了通过测试修改 expected result、负例样本或验收阈值。
6. 不得把计划功能写成已完成。
7. 重要技术变更必须记录 ADR，或在 `docs/CHANGELOG_DEV.md` 中明确说明“无架构变化”及理由。
8. 临时聊天内容不等于正式技术决策；只有写入受版本控制的文档、ADR、契约或用户书面确认的内容，才可作为项目决策依据。
9. 任何外部数据、依赖和模型输出都不得自动提升为可信证据；必须经过声明的验证流程与证据等级判定。
10. 删除、覆盖、系统配置、凭据、网络和权限变更先审批；未获明确批准不得执行。

## 2. 任务工作流

1. 确认 AGENTS 指令已经加载。
2. 先读取 `docs/state/project_state.json`。
3. 再读取 `docs/memory/Memory.md`。
4. 根据任务读取相关记忆子文件、PRD、架构、ADR 和测试文档。
5. 根据任务调用对应 Skill，不把全部 Skill 全文注入上下文。
6. 复杂任务先只读探索并形成计划。
7. 跨模块、Schema、数据库、状态机、安全边界或冻结架构变更，先提交方案和 diff 计划，等待确认。
8. 小范围、低风险、边界明确的任务可按既有批准范围执行。
9. 每次修改都运行适当测试。
10. 先更新 `docs/state/project_state.json`，再运行 `scripts/state_sync.py`。
11. 追加 `docs/CHANGELOG_DEV.md`，更新 `docs/SESSION_HANDOFF.md`。
12. 不得自动 commit。

## 3. 运行环境约束（本机特有，必须遵守）

1. 项目 Python 基线是 **3.11.16（64 位）**，绝对路径：
   `C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
2. PATH 上的 `python` 是 3.12，`py -3.11` 指向 `C:\Program Files (x86)\Python311-32` 的 32 位 3.11.0；两者都不得用于本项目。脚本与测试必须显式使用 uv 的 3.11.16（64 位）绝对路径，或项目 `.venv` 中由该解释器创建的 3.11.16 环境。
3. Git 全局身份未配置；任何提交前必须先询问用户，不得自行设置 `user.name` / `user.email`。
4. PowerShell 中 pnpm 必须使用 `pnpm.cmd`；`pnpm.ps1` 会被执行策略拦截。
5. 不得使用 PATH 上的默认解释器安装依赖或运行项目测试；不得用 `py -3.11` 代替项目基线。

## 4. 不可协商的架构约束

1. `StateMachine` 是 ResearchFlow 运行时状态迁移的唯一入口。
2. Agent/LLM 不得直接写 Task/Node 状态。
3. Agent/LLM 不得直接写 Evidence Store、VerificationReport、CompletionCertificate 或私钥。
4. Executor 只负责执行，不裁决成功。
5. Collector 是 E0/E1/E2 事件的受控记录者；E2 必须来自真实受控执行观测。
6. Verifier 独立执行 L1/L2/L3，产生 E3 并签发报告/凭证。
7. Harness 轨迹默认是 E1，不自动等于 E2。
8. E0/E1 不得单独满足执行类必检项。
9. L3 必须在新目录、独立进程中，从原始数据真实重新训练/推理。
10. 只有报告 `VERIFIED`、必检证据完整、签名/信任锚有效且规定 L3 覆盖满足时，才允许签发 `CompletionCertificate`。
11. `verify_bundle.py` 必须独立于数据库和模型运行。
12. 哈希链只能表述为“可发现篡改”，不得声称绝对不可篡改。
13. k 次 bit-exact 只能作为限定条件下的经验资格，不得宣称数学确定性证明。
14. 无有效 DC 不得 SPA 跳过；随机性或副作用节点不签 DC。

补充边界：

- Executor 与 Verifier 必须使用分离的工作目录；Verifier 不得复用 Executor 的进程内状态作为独立证据。
- 离线验签必须使用外部可信指纹/信任锚，不得只信任证据包自带的公钥。
- 未达到门禁条件时，只能报告缺口、`PARTIAL`、`FAILED` 或 `BLOCKED`，不得用文字描述替代结构化证据。

## 5. 第一版范围

- Windows 11 单机；16GB 内存；CPU-only。
- 并发上限 2（必须实测后才能宣称达成）。
- 内置表格 ML 模板。
- 不执行任意用户代码；不默认开放网络；不强制 Docker；不部署本地大模型。
- 先 T0 最小可信闭环，再 T1，再 T2。
- T0 不接入 LLM，不开发六个 Agent，不接入 DeepSeek Harness Adapter。
- 不得擅自扩大范围；范围变更必须先获得用户明确批准并记录 ADR。

## 6. 研发状态与运行时状态严格分离

本项目同时存在两套完全不同的状态词汇，禁止合并、改名或互相替代：

### 6.1 研发看板状态（仅用于 `docs/state/project_state.json`）

`BACKLOG`、`READY`、`IN_PROGRESS`、`BLOCKED`、`IN_REVIEW`、`DONE`、`DEFERRED`。

这套状态描述“研发任务/交付物”的进度，不是 ResearchFlow 运行时的 Task/Node 状态。

### 6.2 ResearchFlow 运行时状态（按策划书附录 F 与 ADR-001 独立定义）

- Task：`CREATED`、`PLANNING`、`READY`、`RUNNING`、`VERIFYING`、`COMPLETED`、`FAILED`、`BLOCKED`、`CANCELLED`。
- Node：`PLANNED`、`READY`、`RUNNING`、`VERIFYING`、`VERIFIED`、`FAILED`、`BLOCKED`、`DIAGNOSING`、`RECOVERING`、`INVALIDATED`。

`INVALIDATED` 由 [`ADR-001`](docs/ADR/ADR-001-invalidated-node-state.md) 增加，Node 为 10 个状态；只允许 `VERIFIED → INVALIDATED` 与 `INVALIDATED → READY`，其他边未授权。运行时状态、完整迁移表与不变量见 `docs/state/runtime_states.md` 与 [`docs/design/05_CONTRACTS_AND_STATES.md`](docs/design/05_CONTRACTS_AND_STATES.md) §9–§10；规范性以冻结契约为准。`project_state.json` 不得记录、推导或替代运行时状态。

## 7. 记忆、状态与文档职责

- `docs/memory/Memory.md`：记忆索引，只做导航，不复制聊天记录。
- `docs/memory/project-context.md`：项目目标、边界、设计原因、历史阶段、长期约束；不维护当前进度。
- `docs/memory/architecture-decisions.md`：稳定架构约束与 ADR 索引。
- `docs/memory/feedback-and-lessons.md`：用户反馈、失败经验与教训。
- `docs/memory/environment.md`：已核实环境、版本与配置摘要；不得保存密钥。
- `docs/memory/references.md`：资料来源与关键引用索引。
- `docs/state/project_state.json`：研发进度唯一机器可读事实源。
- `docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`：由 `project_state.json` 生成，禁止手工编辑。
- `docs/CHANGELOG_DEV.md`：追加式开发日志，不覆盖历史。
- `docs/SESSION_HANDOFF.md`：每次大任务结束更新，最新记录置顶。
- `docs/ADR/`：架构决策记录；未记录 ADR 的架构变更视为未批准。
- `docs/reference/`：外部资料与引用索引；外部资料默认不是可信证据。

写入顺序：

1. 修改 `docs/state/project_state.json`。
2. 使用 §3 的 Python 3.11.16 绝对路径（下称 `$py`）依次运行：

   ```powershell
   & $py scripts/state_sync.py validate
   & $py scripts/state_sync.py render
   & $py scripts/state_sync.py check
   ```

3. 追加 `docs/CHANGELOG_DEV.md`。
4. 更新 `docs/SESSION_HANDOFF.md`。
5. 只将稳定事实写入 `docs/memory/*`。

## 8. 验证与证据规则

- 测试必须真实运行；报告必须包含命令、解释器、退出码、日志路径和运行时间。
- 不得修改 expected result、负例样本或验收阈值来掩盖脚本错误。
- 计划中的功能只能标记为计划/设计中/未测；只有真实运行并留存日志的功能才可标记为已实现。
- E0/E1/E2/E3 的定义与门控以策划书和后续冻结契约为准；E0 声明不得推动状态。
- 只有真实受控执行观测才能产生 E2；Harness 轨迹默认 E1。
- L3 必须从原始数据真实重新训练/推理，不得用缓存、摘要或模型自述替代。
- 哈希链只证明“可发现篡改”，不证明绝对不可篡改；k 次 bit-exact 只是限定条件下的经验资格。
- 外部数据、第三方材料、模型输出和网络检索结果，未经核验不得写入“实测/已验证”结论。
- **正例通过不构成完成证据。** 凡是“出错时不会报错”的判定点，必须有负例测试证明缺陷会被抓住；典型例子：Gate 是否放行缺必检证据的包、Collector 的 `event_seq` 是否单调且重复事件不产生两条、L3 是否真的从原始数据重新训练、验签是否只信任包外指纹而不信任包内自带公钥。这些点即使全部正例通过，也只能算未验证。
- **负例必须以“拒绝原因正确”为通过条件，不能只以“被拒绝”为通过条件。** 必须断言错误码、字段路径或失败环节；原因与预期不符即判测试失败。理由：一个因为无关原因而失败的负例，和根本没有负例，防护效果相同。

## 9. 变更、审批与提交

- 不自动 commit；提交前必须询问用户，并确认 Git 身份。
- 删除、覆盖、系统配置、凭据、网络和权限变更先审批。
- 项目工作区之外的写入（例如 `C:\Users\Administrator\.dsh\AGENTS.md`）必须单独审批，不得顺手创建。
- 跨模块、Schema、数据库、状态机、安全边界或冻结架构变更，先提交方案和 diff 计划。
- 小范围、低风险、边界明确的任务可按既有批准范围执行；超出批准范围即停止并报告。
- 重要技术变更必须记录 ADR；无架构变化时在 `CHANGELOG_DEV.md` 中明确写明“无架构变化”。

## 10. 当前基线（以状态文件为准）

- 当前阶段、里程碑、门禁与阻塞项：以 `docs/state/project_state.json` 为准。
- 项目级 Skill 目录与三态验证：见 `docs/SKILL_CATALOG.md`；九个 Skill 位于 `.agents/skills/`，按任务按需加载，不把全文写入本文件。
- 阶段 4 的交付证据与真实测试日志：见 `docs/verification/stage4/`。
- 阶段 5 的 Skills 发现机制、结构与调用验证：见 `docs/verification/stage5/`。
- 阶段 6 的 MCP 能力与 Context7 接入：见 `docs/verification/stage6/`。
- 阶段 7 的资料接手、来源登记与冲突报告：见 `docs/reference/`。
- 阶段 8 的工作站综合验收：见 `docs/verification/stage8/`。
- G0 规格冻结与裁决：见 `docs/G0/`、`docs/verification/g0/`、`contracts/`。
- T0 的 WP-01、WP-02 与 P0 整改：见 `docs/verification/t0/`、`reports/remediation/`、`design/pseudocode/INDEX.md`。
- 策划书文件名与哈希：见 `docs/memory/references.md`。
- 未确认事项：见各记忆文件中的“待核实”条目，不得用推测补齐。
