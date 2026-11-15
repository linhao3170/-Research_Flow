# DEVELOPMENT_WORKFLOW — ResearchFlow 开发工作流

> 状态：T0 P0 整改后的当前工作流；阶段 7/8 的历史执行约束保留在 §11.2，不再作为当前禁令。
> 基线：策划书内部 v4.3.0（文件名标签 v4.3.1；`BLK-002` 已关闭）；`AGENTS.md`（阶段 5 基线）
> 证据锚点：`P####` → [`02_docx_body.txt`](verification/stage7/02_docx_body.txt)；`TABLE ##` → [`05_docx_tables.txt`](verification/stage7/05_docx_tables.txt)
> 页码说明：DOCX 无可信页码（无 TOC/缓存分页；Word COM 不可用）；引用使用章节号 + `P####` + `TABLE ##`，可在上述文件中逐行核验。
> 标注：`[策划书]` / `[AGENTS]` / `[Harness]` / `[飞书]` / `[建议]` / `[待确认]`
> 重要：**飞书 AI 开发说明当前未落地**，本文件没有引用其内容；方法论基线来自 `AGENTS.md`、策划书附录 I 与阶段 4–6 的真实实践。

## 1. 来源优先级与冲突处理

| 优先级 | 来源 | 当前状态 | 用法 |
|---|---|---|---|
| 1 | 用户最终确认的 ResearchFlow 策划书 | **已确认**（2026-11-08）：内部 v4.3.0 为内容基线，v4.3.1 仅为文件名标签；`BLK-002` 已关闭 | 项目需求与架构基线 |
| 2 | 用户提供的飞书 AI 开发说明 | **未落地**（项目内无文件） | 开发方法论/工具参考；不覆盖项目架构 |
| 3 | DeepSeek Harness 官方文档 | 已安装 0.2.2-rc.1 的包内文档与阶段 6 证据 | Harness 实际配置依据 |
| 4 | 工程建议 | 本文件/架构文档标注 `[建议]` | 仅参考，不是冻结决策 |

冲突处理：

1. 先登记到 [`reference/CONFLICT_REPORT.md`](reference/CONFLICT_REPORT.md)，列出原文、位置、影响、方案。
2. 不自动合并两个版本或多个来源。
3. 用户当前明确指令 > `AGENTS.md` > 已批准 ADR/冻结契约 > 记忆索引/知识文档。
4. 版本已定（`BLK-002` 已关闭）；G0 已于 2026-11-10 `PASS`，冻结时的 3 项待裁决已由 G0 文档包关闭（历史见 `state/G0_DECISION_LIST.md`）。目标数字仍不是实测成绩，不得写成当前能力。

## 2. 每次任务开始前

`[AGENTS]` 顺序：

1. 确认 `AGENTS.md` 已由 DSH 的 `agent-instructions` 加载；未加载先报告。
2. 读 [`memory/Memory.md`](memory/Memory.md)，按索引只加载相关记忆子文件。
3. 读 [`state/project_state.json`](state/project_state.json)，确认阶段、里程碑、门禁、阻塞、`last_verified_commit`。
4. 按任务读 PRD、架构、ADR、契约与测试文档；不要一次注入全部文档或全部 Skill 全文。
5. 复杂任务先只读探索并形成计划；跨模块、Schema、数据库、状态机、安全边界或冻结架构变更，先提交方案与 diff 计划，等待确认。

> 阶段 7 的实际做法：先读 Memory/state/handoff → 只读抽取 DOCX → 核对版本 → 建立来源登记与冲突报告 → 再写知识文档。没有先写结论再找证据。

## 3. 阶段工作流（每个阶段通用）

```text
只读探索
  → 计划与范围（含不做什么）
  → 用户批准
  → 执行（小步、可回滚）
  → 真实测试/证据
  → 更新 project_state.json
  → state_sync validate / render / check
  → 追加 CHANGELOG_DEV.md
  → 更新 SESSION_HANDOFF.md
  → 输出阶段报告，停止等待验收
```

硬规则：

- 不自动 commit；提交前确认 Git 身份。
- 不把计划功能写成已完成；未测就是未测。
- 不改 expected result、负例样本或验收阈值来“通过”测试。
- 删除/覆盖/系统配置/凭据/网络/权限变更先审批。
- 重要技术变更记录 ADR；无架构变化时在 CHANGELOG 明确写“无架构变化”及理由。
- 阶段报告后停止；不自动进入下一阶段。

来源：`AGENTS.md` §2、§8、§9；[`memory/Memory.md`](memory/Memory.md) §3。

## 4. T0 开发顺序（先契约，后实现）

`[策划书]` §15.5 的顺序：

1. 先定义 contracts：`TaskSpec`、`NodeSpec`、`EvidenceRecord`、`VerificationReport`、`CompletionCertificate`、`HarnessEvent`、`DomainPack`。
2. 实现 StateMachine + SQLite + `audit_log`，禁止其他模块直接更新状态。
3. 实现内置模板 Executor 与独立工作目录，暂不接 LLM。
4. 实现 Collector 事件队列和 E0/E1/E2 追加写。
5. 实现 Gate 与 L1/L2/L3；L3 必须真实重训/推理。
6. 实现 Ed25519/JCS/Merkle 和 `verify_bundle.py`，建立真包/负例包。
7. 实现 DAG Scheduler、Governor、Recovery；在真实执行日志上验证动态变化。
8. 接入六逻辑 Agent 与知识库；所有角色通过 Tool Gateway。
9. 实现 RF-Bench、四方案/消融和统计脚本；先冻结任务再跑正式数据。
10. 最后接入 DeepSeek Harness 插件和第二领域包。

来源：§15.5 / P0386–P0395。

`[策划书]` 附录 I.2 的 T0 硬性原则：

- 先 contracts，再 StateMachine，再 Executor/Collector，再 Verifier，再签名与离线验签；
- 不先开发六个 Agent，不先做复杂前端，不先接 Harness；
- 只执行审核过的内置表格 ML 模板，不执行任意用户代码；
- Agent/LLM 不得写状态、证据库、报告或私钥；
- E0/E1 不能满足执行类必检项；E2 由 Collector 观察；E3 由独立 Verifier 产生；
- L3 必须在新目录、独立进程、从原始数据重新训练/推理；
- 只有 `VERIFIED` 才能签发 `CompletionCertificate`；
- `verify_bundle.py` 必须独立于数据库和模型运行。

来源：附录 I.2 / P0707–P0723。

## 5. T0 / T1 / T2 与 G0–G7

### 5.1 交付阶段

| 阶段 | 目标 | 出口 |
|---|---|---|
| T0 | 证明不是 PPT | 断网/无模型完成一条实验；导出证据包；第三方验签通过 |
| T1 | 覆盖赛道主要能力 | 六项能力均有运行演示与原始证据 |
| T2 | 证明机制贡献和外部适配 | 创新点有对照数据，至少一个 Harness 适配可复核 |

来源：§15.2 / TABLE 56。

### 5.2 质量门禁

G0 规格冻结 → G1 纵向闭环 → G2 证据可信 → G3 L3 独立重执行 → G4 动态调度/恢复 → G5 实验数据可信 → G6 外部复核 → G7 Harness 适配。

每道门禁的通过条件与未通过处理见 [`ARCHITECTURE.md`](ARCHITECTURE.md) §7 或 [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md) §7.2；原始表为 §15.3 / TABLE 57。

`[现状]` `G0` 已 `PASS`；`G1`–`G7` 仍 `NOT_STARTED`，不得提前标 PASS。P1–P8 伪代码设计件 `ACCEPTED`（P2–P8 于 2026-11-12 验收），P9/P10 `BLOCKED`；这些阶段状态不参与门禁计算。

## 6. 测试与证据规则

### 6.1 必须真实运行

`[AGENTS]` 测试报告必须包含：

- 命令；
- 解释器绝对路径（项目 Python 3.11.16 64 位）；
- 退出码；
- 日志路径；
- 运行时间（适用时）。

不得编造测试结果、性能数据、实验成绩或第三方证明。

### 6.2 测试分层

| 测试 | 对象 | 验收 |
|---|---|---|
| 单元 | 状态机、指纹、Gate、VAS、Recovery | 非法状态迁移全部拒绝；核心判定分支覆盖 |
| 契约 | Agent 消息、API、Domain Pack、Adapter | Schema/版本不匹配失败 |
| 权限 | Agent 写状态/证据/私钥/越界路径 | 越权全部拒绝并审计 |
| 集成 | Executor→Collector→Gate→Verifier→Certificate | 完整闭环成功 |
| 对抗 | F-1 至 F-7 和攻击变体 | 每类有预期状态与原始证据 |
| 离线 | 断网、无模型、单机 | 内置模板完成并导出可验签证据包 |

来源：§6.7 / TABLE 30。

### 6.3 证据等级规则

- 只有真实受控执行观测才能产生 E2；Harness 轨迹默认 E1。
- L3 必须从原始数据真实重新训练/推理，不得用缓存、摘要或模型自述替代。
- 外部数据、第三方材料、模型输出、网络检索结果，未经核验不得写入“实测/已验证”结论。
- 哈希链只证明“可发现篡改”，不证明绝对不可篡改；k 次 bit-exact 只是限定条件下的经验资格。
- 未达到门禁条件时，只能报告缺口、`PARTIAL`、`FAILED` 或 `BLOCKED`，不得用文字描述替代结构化证据。

来源：`AGENTS.md` §8；§7.1；§9.1–9.4。

### 6.4 测试失败时

1. 先修实现，不改 expected/负例/阈值。
2. 记录失败命令、退出码、日志与最小复现。
3. 如果失败暴露规格冲突，先登记冲突并暂停，不自行选择“看起来合理”的版本。
4. 失败事件不得删除或覆盖；补偿动作写 `audit_log`。

来源：`AGENTS.md` §1.5、§8；附录 E.4 / P0630。

## 7. Definition of Done

`[策划书]` 每模块完成定义：

- 有 Schema、错误码、日志、单测、集成测试和使用说明；
- 核心状态迁移、Gate、签名验签和剪枝判定有正例与负例；
- 每个创新点有开关/对照/消融或明确边界证明；
- 所有对外数字可追到原始数据；示意图明确标示；
- 离线启动、断网运行、无模型回退和离线验签在独立环境复测。

来源：§15.7 / P0408–P0412。

`[建议]` 在 G0 冻结时把上述 DoD 转成可勾选的验收矩阵，每项绑定测试命令与证据路径；没有证据路径的条目不勾选。

## 8. 版本、文档与引用纪律

1. 引用策划书写“内部 v4.3.0（文件名标签 v4.3.1，`BLK-002` 已关闭）§x.y / P####”；不要只写“策划书说”。
2. 引用外部网页写 URL 与访问日期；未访问成功标“未核验”。
3. 引用测试结果写命令、解释器、退出码、日志路径与运行时间。
4. 原始资料与摘要分开；不得改写原文冒充原文。
5. 不得复制/移动/重命名根目录策划书；只登记路径与 SHA256；`docs/reference/inbox/` 留给后续外部资料。
6. `BLK-002` 已关闭；G0 已于 2026-11-10 `PASS`。后续变更仍按 ADR/用户审批执行，不把目标数字写成实测成绩，不把伪代码阶段写成运行时能力。

来源：`AGENTS.md` §1.2、§1.7–1.8、§9；[`reference/SOURCE_REGISTER.md`](reference/SOURCE_REGISTER.md)；[`reference/CONFLICT_REPORT.md`](reference/CONFLICT_REPORT.md)。

## 9. Git 与提交

- 不自动 `git add` / `git commit`。
- 提交前询问用户并确认 `user.name` / `user.email`（`BLK-001`）。
- 当前有 7 个 commit；HEAD 为 `309083e`，`last_verified_commit` 为 `1c9a104`；两者不一致是未提交整改的预期状态，不得擅自推进 `last_verified_commit`。
- 策划书 DOCX 不纳入 Git（避免第二份副本）；已按精确文件名忽略，后续 `git add` 仍须显式核对。
- `.gitattributes` 固定 LF；`state_sync.py check` 依赖逐字节一致。

来源：`AGENTS.md` §3.3、§9；[`memory/environment.md`](memory/environment.md) §3；`09_inventory.log`。

## 10. 状态同步与交接

### 10.1 更新顺序

1. 修改 [`state/project_state.json`](state/project_state.json)。
2. 运行：

```powershell
$py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'
& $py scripts/state_sync.py validate
& $py scripts/state_sync.py render
& $py scripts/state_sync.py check
```

3. 追加 [`CHANGELOG_DEV.md`](CHANGELOG_DEV.md)。
4. 更新 [`SESSION_HANDOFF.md`](SESSION_HANDOFF.md)（最新置顶）。
5. 更新相关记忆文件与 [`PROJECT_STATE.md`](PROJECT_STATE.md)、[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md)（由 render 生成，禁止手改）。

### 10.2 状态词汇

- 研发看板只允许 `BACKLOG`、`READY`、`IN_PROGRESS`、`BLOCKED`、`IN_REVIEW`、`DONE`、`DEFERRED`。
- 伪代码阶段使用独立注册表 `pseudocode_stages`，只允许 `NOT_STARTED`、`IN_PROGRESS`、`IN_REVIEW`、`BLOCKED`、`ACCEPTED`、`DEFERRED`；`ACCEPTED` 只表示设计件验收，不表示运行时能力。
- 运行时 Task/Node 状态按附录 F 与 `ADR-001`（Node 增加 `INVALIDATED`，共 10 个状态）；不得写入 `project_state.json`。
- 门禁只有 `NOT_STARTED`、`IN_PROGRESS`、`PASS`、`FAIL`、`BLOCKED`；PASS 必须有证据路径、`decided_by`（裁决人）与 `decided_at`（裁决日期，`YYYY-MM-DD` 或带时区 ISO-8601）。

来源：`AGENTS.md` §6、§7；[`MEMORY_GUIDE.md`](MEMORY_GUIDE.md)。

## 11. 当前阶段的执行约束（T0 P0 整改后）

### 11.1 当前约束

- 不自动 commit；本轮整改只输出 Diff 与报告，等待用户单独批准。不得擅自修改 `last_verified_commit`。
- 不扩大 P10/M19 开发范围；不删除 M19；不得把 P9 并发重写文件标为 `ACCEPTED` 或原始正文。
- 不修改冻结契约、冻结架构、ADR 正文、PRD/G0/design 历史结论；只允许修正非冻结文档的现状说明与历史横幅。
- 不清理 `.pytest_cache`、`__pycache__`、`tmp/unittest-temp` 或其他临时目录；只记录。
- 不复制/移动/改名根目录 DOCX。
- `BLK-003`（workspace-write 下测试临时目录 ACL 阻塞）保持 `OPEN`；full-access 测试结果不用于关闭它。
- `G1`–`G7` 保持 `NOT_STARTED`；P0 整改完成不等于 G1 或 WP-03 启动授权。

### 11.2 历史约束（阶段 7/8，仅作记录）

- 阶段 7 的“不 commit、不建 `.venv`、不装依赖、不开发业务代码”已被后续 WP-01/WP-02 与 G0 PASS 取代，不再作为当前禁令。
- 阶段 6 备份 `cordis.patch.yml.bak-20261108-stage6` 仍保留；不得因本轮整改删除。
- `T-SKILLS-001` 已 `DONE`；`T-MCP-001` 保持 `DONE`。

来源：用户 2026-11-11 P0 整改授权；[`state/project_state.json`](state/project_state.json)。

### 11.3 WP-03 进入条件（部分满足）

1. API 幂等修复完成，测试 A–E 通过；本轮已做到。
2. P2 由用户正式验收，或书面豁免；**2026-11-12 已按 C 指令验收设计件**（不表示运行时实现）。
3. §12-2、§12-6、§12-7、§12-8 已裁决并写入 M02 `DECISIONS`/ADR；本轮只提交 D 方案，不自行生效。
4. P9 缺口/并发重写产物已获用户处置，不作为 WP-03 输入。
5. `BLK-003` 状态如实保留并说明影响。
6. 用户明确下达 WP-03 指令。

仍未满足第 3、4、6 条；第 2 条只完成设计件验收，不解除 §12 开放问题。在上述条件满足前，不得创建 WP-03 代码、数据库或迁移。

方案与提示词（草案，未获实施批准）：[`docs/plans/WP-03_IMPLEMENTATION_PLAN.md`](plans/WP-03_IMPLEMENTATION_PLAN.md)、[`docs/plans/WP-03_IMPLEMENTATION_PROMPT.md`](plans/WP-03_IMPLEMENTATION_PROMPT.md)。

## 12. 飞书资料缺口

`[飞书]` 用户给定的优先级 2 资料当前**未落地**：

- 项目目录没有该文件；
- `docs/reference/inbox/` 只有 `.gitkeep`；
- 本文件没有引用其内容，也没有把“飞书建议”写成项目规则。

如后续提供导出件，处理顺序：

1. 放入 `docs/reference/inbox/`（或用户指定位置），登记文件名、路径、大小、SHA256、版本/日期、敏感信息。
2. 只读阅读，标注“飞书资料建议”，与策划书明确要求分开。
3. 如与项目架构冲突，登记到 `CONFLICT_REPORT.md`，不自动覆盖策划书。
4. 更新本文件与 `SOURCE_REGISTER.md`，保留旧记录。

## 13. 相关文件

- [`AGENTS.md`](../AGENTS.md)
- [`PROJECT_OVERVIEW.md`](PROJECT_OVERVIEW.md)
- [`ARCHITECTURE.md`](ARCHITECTURE.md)
- [`SECURITY_POLICY.md`](SECURITY_POLICY.md)
- [`MEMORY_GUIDE.md`](MEMORY_GUIDE.md)
- [`SKILL_CATALOG.md`](SKILL_CATALOG.md)
- [`MCP_CATALOG.md`](MCP_CATALOG.md)
- [`reference/SOURCE_REGISTER.md`](reference/SOURCE_REGISTER.md)
- [`reference/CONFLICT_REPORT.md`](reference/CONFLICT_REPORT.md)
- [`verification/stage7/STAGE7_REPORT.md`](verification/stage7/STAGE7_REPORT.md)
