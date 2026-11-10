# CHANGELOG_DEV

> 追加式开发日志：只在文件末尾追加新记录，不修改或删除历史记录。
> 每条记录包含：日期、阶段、变更、原因、验证、影响/后续、相关文件。

## 记录

### 2026-11-08 · 阶段 3B · 仓库初始化与工程骨架

- 变更：初始化 Git 仓库（分支 main）；创建基础目录、`.gitignore` 与文档骨架。
- 原因：为阶段 4 及后续开发提供可追踪的工程起点。
- 验证：目录树、`git status`、`.gitignore` 自检、策划书 DOCX SHA256 复核。
- 影响/后续：未执行 `git add` / `git commit`；等待阶段 4 批准。
- 相关文件：`AGENTS.md`、`README.md`、`.gitignore`、`docs/*`。

### 2026-11-08 · 阶段 4 · ResearchFlow 持久记忆与动态状态系统

- 变更：
  - 重写项目级 `AGENTS.md`，写入行为规范、任务工作流、本机环境约束、14 条不可协商架构约束、第一版范围，以及“研发看板状态 / 运行时状态”严格分离规则。
  - 建立 `docs/memory/`：索引 `Memory.md` 及 `project-context.md`、`architecture-decisions.md`、`feedback-and-lessons.md`、`environment.md`、`references.md`。
  - 建立 `docs/state/runtime_states.md`，单独记录运行时 Task/Node/Report/Certificate 状态与迁移，避免与研发看板混用。
  - 建立 `docs/state/project_state.json`：`tasks` 为空数组；G0–G7 全部 `NOT_STARTED`；记录 2 个真实 OPEN 阻塞；`last_verified_commit` 为 `null`。
  - 实现 `scripts/state_sync.py`：`validate` / `render` / `check` 三个子命令，仅标准库，字段路径错误提示，临时文件 + 原子替换。
  - 实现 `tests/test_state_sync.py`：23 个端到端测试，覆盖合法状态、缺字段、非法状态、重复 ID、无效依赖、循环依赖、render/check、手工篡改、JSON 损坏等。
  - 新增 `.gitattributes`，将 `.py` / `.md` / `.json` / `.yml` / `.yaml` 固定为 LF，保证 `check` 逐字节比较在 Windows `core.autocrlf=true` 下仍可复现。
  - 更新 `README.md`，补充项目定位、规则入口、Python 3.11.16 约束与状态同步命令。
  - 检查全局 `C:\Users\Administrator\.dsh\AGENTS.md`：不存在；未创建、未修改；提案与回滚办法见 `docs/reference/GLOBAL_AGENTS_PROPOSAL.md`。
- 原因：建立可审计的项目记忆、单一机器可读研发状态源与自动一致性检查，为 G0 规格冻结和后续阶段提供治理基线；不开发 ResearchFlow 业务代码。
- 验证：
  - Python：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`（3.11.16, 64-bit）。
  - 使用上述 Python 3.11.16 绝对路径运行 `-m unittest discover -s tests -v`：23 tests，OK，exit 0。
  - 使用上述绝对路径运行 `scripts/state_sync.py validate`：exit 0。
  - 使用上述绝对路径运行 `scripts/state_sync.py render`：exit 0，生成 2 个文件。
  - 使用上述绝对路径运行 `scripts/state_sync.py check`：exit 0，逐字节一致。
  - 手工篡改 `docs/PROJECT_STATE.md` 后 `check`：exit 1，指出文件、预期/实际 SHA256 与差异；`render` 恢复后 `check`：exit 0。
  - 证据日志目录：`docs/verification/stage4/`。
- 影响/后续：
  - **无 ResearchFlow 运行时架构变化**；不新增 ADR。本阶段仅新增项目治理、状态同步工具与测试。
  - 未创建 `.venv`、未安装依赖、未接入 LLM、未开发业务代码。
  - 未执行 `git add` / `git commit`；Git 身份仍未配置。
  - 等待用户批准阶段 5；批准前不进入 T0 开发。
- 相关文件：`AGENTS.md`、`README.md`、`.gitattributes`、`docs/memory/*`、`docs/state/project_state.json`、`docs/state/runtime_states.md`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`scripts/state_sync.py`、`tests/test_state_sync.py`、`docs/verification/stage4/*`、`docs/reference/GLOBAL_AGENTS_PROPOSAL.md`。

### 2026-11-08 · 阶段 5 · ResearchFlow 专属 Skills 系统

- 变更：
  - 在 `.agents/skills/` 创建九个 Skill Bundle，每个含 `SKILL.md` 与必要的 `references/`；未使用多层嵌套 `SKILL.md`。
  - 九个 Skill：`researchflow-onboarding`、`researchflow-spec-driven-development`、`researchflow-prompt-workflow`、`researchflow-contracts-api`、`researchflow-python-backend`、`researchflow-dag-state-machine`、`researchflow-evidence-security`、`researchflow-testing-benchmark`、`researchflow-memory-handoff`。
  - 新增 `docs/SKILL_CATALOG.md`，分别记录“已发现 / 已加载 / 已执行验证”三态，并将 `researchflow-harness-adapter` 标为计划在 T2 创建。
  - 新增 `scripts/validate_skills.py`（仅标准库），校验 frontmatter、name/description、八个必备章节、引用资源与无嵌套 `SKILL.md`。
  - 新增 `docs/verification/stage5/`：发现机制、结构校验、秘密扫描、无副作用调用、状态同步、23 项回归测试与结构负例日志。
  - 将 `project_state.json` 的 `current_phase` 调整为 `WORKSTATION_SETUP`，登记 `T-SKILLS-001`（`IN_REVIEW`，等待验收）；G0–G7 仍全部 `NOT_STARTED`。
  - 更新 `AGENTS.md` 版本基线、`README.md`、项目上下文、环境、参考资料、失败教训与交接记录。
- 原因：让 ResearchFlow 的规格、契约、后端、状态机、证据安全、测试、记忆交接等流程有可路由、按需加载的项目级 Skill；避免把九个 Skill 全文写入 `AGENTS.md` 或每轮注入。
- 验证：
  - 当前 DSH 桌面版 0.2.2-rc.1；Provider `dsh-skill-filesystem@0.2.2-rc.1` 的 `lib/index.js` 第 160–190 行确认扫描 `<projectRoot>/.agents/skills`；实际 catalog 三次刷新后九个全部出现。
  - 通过 Harness `skill` 工具逐个加载九个 Skill，均返回正确 `<skill_content>` 与 resource base。
  - 对 onboarding、spec-driven-development、memory-handoff 完成只读/干跑调用验证；其余六个仅按需加载。
  - `scripts/validate_skills.py`：9 个 PASS，exit 0；临时副本删除一个 `SKILL.md` 后 exit 1，负例通过。
  - `python -m unittest discover -s tests -v`：23 tests，OK，exit 0，3.342s。
  - `state_sync.py validate` / `render` / `check`：均 exit 0；2 个生成文件逐字节一致。
  - 7 类秘密模式扫描 20 个 Stage 5 文件：0 命中；全仓库文本扫描：0 命中。
- 影响/后续：
  - **无 ResearchFlow 运行时架构变化**；Skills 为项目级工作流说明，不改变状态机、证据等级、API 或安全边界，因此不新增 ADR。
  - 未创建 `.venv`、未安装依赖、未接入 LLM、未开发业务代码。
  - 未在 `.dsh/skills`、全局目录创建同名 Skill；未修改 DSH Profile/preset。
  - 未执行 `git add` / `git commit`；commit 数仍为 0，`last_verified_commit` 仍为 `null`。
  - 停止并等待用户批准阶段 6；批准前不进入下一阶段。
- 相关文件：`.agents/skills/**`、`docs/SKILL_CATALOG.md`、`scripts/validate_skills.py`、`docs/verification/stage5/*`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`AGENTS.md`、`README.md`、`docs/memory/*`、`docs/SESSION_HANDOFF.md`。

### 2026-11-08 · 阶段 6 · MCP Client 能力核实与 Context7 接入评估

- 变更：
  - 以 app.asar 内 `0.2.2-rc.1` 的 `@deepseek-ai/dsh-mcp-client` 源码核实：原生支持 `stdio` 与 `streamable-http`，工具名为 `mcp__<serverName>__<rawName>`，无默认 server，`mcp-resources` 已由 `dsh-base` 挂载。
  - 只读探测 `https://mcp.context7.com/mcp`：`initialize` / `tools/list` / `tools/call` 均 HTTP 200，匿名可用；2 个工具 `resolve-library-id`、`query-docs`。
  - 新增 `docs/verification/stage6/`：能力矩阵、Context7 探测、精确配置 diff、结论与复评条件、真实日志，以及两个仅标准库的只读证据脚本。
  - 登记 `T-MCP-001`（`IN_REVIEW`，等待配置变更批准）；G0–G7 仍全部 `NOT_STARTED`；`last_verified_commit` 仍为 `null`。
  - 删除冗余的 `.agents/skills/.gitkeep`（该目录已有 9 个 Skill）。
  - 更新 `docs/memory/environment.md`（§6.3 MCP 能力）、`docs/memory/references.md`（R-14…R-17）、`docs/memory/feedback-and-lessons.md`（FB-20…FB-24、L-08）。
- 原因：确认当前 DSH 是否具备远程 MCP 能力，评估 Context7 能否以第一方通道接入，并在不扩权、不写配置的前提下给出可审批的最小变更。
- 验证：
  - `& $py docs/verification/stage6/inspect_mcp_client.py`：exit 0，`INSPECT_RESULT=PASS`；日志 `00_mcp_source.log`。
  - `& $py docs/verification/stage6/context7_probe.py`：exit 0，`PROBE_RESULT=PASS`；Context7 4.5.0，协议 2025-06-18，2 个工具，匿名调用返回真实库 ID；日志 `01_context7_probe.log`。
  - `& $py scripts/state_sync.py validate` / `render` / `check`：均 exit 0；2 个生成文件逐字节一致；日志 `03_state_sync.log`。
  - 7 类秘密模式扫描 13 个 Stage 6 文件：0 命中；日志 `04_secret_scan.log`。
  - 配置快照：`cordis.patch.yml` 仍为 1,200 字节、SHA256 `664CE561...94FFD8`，无 MCP/Context7 条目；日志 `02_config_snapshot.log`。
  - `git rev-list --count --all` = 0；`.venv` 不存在；`researchflow/` 仍只有 `.gitkeep`；日志 `05_git_status.log`。
- 影响/后续：
  - **无 ResearchFlow 运行时架构变化**；未改状态机、契约、证据等级、API 或安全边界，不新增 ADR。
  - **未写入** `C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml`；Context7 尚未接入，不声称“已接入”。
  - 未配置 API Key；未读取凭据文件；匿名额度足够做技术验证，额度不足时再单独评估。
  - 未改 `web_fetch` / `telemetry` / `session-log` 配置；未安装依赖、未创建 `.venv`、未 commit。
  - 下一步：等待用户批准精确 diff；批准后执行写入、热重载/重启、工具出现与公开库查询验证。
- 相关文件：`docs/verification/stage6/*`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/memory/environment.md`、`docs/memory/references.md`、`docs/memory/feedback-and-lessons.md`、`docs/SESSION_HANDOFF.md`、`README.md`、`.agents/skills/`。

### 2026-11-08 · 阶段 6 · Context7 配置写入与真实调用验证

- 变更：
  - 创建备份 `C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml.bak-20261108-stage6`，1,200 字节，SHA256 `664CE561…94FFD8`。
  - 在 `cordis.patch.yml` 末尾以二进制追加 9 行 / 262 字节；写入后 1,462 字节 / 52 行 / SHA256 `6FF6F1FC…59E1`；前 1,200 字节与备份逐字节相同。
  - 热重载生效，未重启桌面版；当前会话出现 `mcp__context7__resolve-library-id` 与 `mcp__context7__query-docs`。
  - 完成真实查询：FastAPI → `/websites/fastapi_tiangolo`；Pydantic → `/pydantic/pydantic`（版本含 `v2.11.0`）；`query-docs` 以 `/pydantic/pydantic/v2.11.0` 返回 v2.11.0 文档。
  - `T-MCP-001` 由 `IN_REVIEW` 转 `DONE`；`T-SKILLS-001` 保持 `IN_REVIEW`；G0–G7 仍全 `NOT_STARTED`。
  - 新增 `08_apply_result.md`、`apply_context7_patch.py`、`06_apply.log`、`06_apply_summary.log`、`07_post_write_verify.log`、`09_state_sync_after_done.log`；更新 `00`、`01`、`02`、`03` 文档状态。
- 原因：执行用户批准的精确配置变更，并在真实运行环境中验证 MCP 工具可用，而不是只停留在端点探测。
- 验证：
  - 备份 SHA256 = `664CE561…94FFD8`；与源文件逐字节相同。
  - 写入后 1,462 字节 / 52 行 / 末尾 LF / 无 BOM / 无 CRLF；SHA256 = `6FF6…59E1`；前 1,200 字节与备份一致。
  - 两个 MCP 工具出现；三次调用（FastAPI resolve、Pydantic resolve、v2.11.0 query-docs）均成功，无 HTTP 429，无 API Key。
  - 2C 三项：`web-fetch-http disabled: true`、`session-telemetry-otel mode: DISABLED`、`session-log-deepseek enabled: false`，未改动。
  - `& $py scripts/state_sync.py validate` / `render` / `check`：均 exit 0；日志 `09_state_sync_after_done.log`。
- 影响/后续：
  - **无 ResearchFlow 运行时架构变化**；未改状态机、契约、证据等级、API 或安全边界，不新增 ADR。
  - 未配置 API Key；未读取凭据文件；匿名额度用尽时只报告 `429`，不擅自加 Key。
  - 未重启 Harness、未新建替代服务、未结束进程。
  - 未安装依赖、未创建 `.venv`、未 commit；commit 数仍为 0，`last_verified_commit` 仍为 `null`。
  - 备份保留到阶段验收后再由用户决定是否删除。
- 相关文件：`C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml`（及其备份）、`docs/verification/stage6/08_apply_result.md`、`docs/verification/stage6/apply_context7_patch.py`、`docs/verification/stage6/06_apply.log`、`docs/verification/stage6/07_post_write_verify.log`、`docs/verification/stage6/09_state_sync_after_done.log`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/memory/environment.md`、`docs/SESSION_HANDOFF.md`、`README.md`。

### 2026-11-08 · 阶段 7 · ResearchFlow 项目资料接手与知识基线

- 变更：
  - 只读扫描项目目录与 `docs/reference/`：确认根目录 `ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx` 为唯一权威原件；`docs/reference/inbox/` 只有 `.gitkeep`；未复制、未移动、未重命名、未覆盖原件。
  - 使用项目 Python 3.11.16（64 位）+ 标准库完成 DOCX 全文抽取：754/754 段落、80/80 表格、0 图片/绘图/文本框、0 修订/批注、无 TOC、30 个手工分页符；证据在 `docs/verification/stage7/`。
  - 新增 `docs/reference/SOURCE_REGISTER.md`：登记文件名、路径、类型、大小、SHA256、资料类型、内部版本、日期、内容/重要章节、适用范围、敏感信息、脱敏、Git 跟踪、解析完整性、最后核验；写明“禁止再产生第二份策划书副本”。
  - 新增 `docs/reference/CONFLICT_REPORT.md`：登记 C-001 版本冲突（HIGH，阻断 G0）、C-002 飞书资料缺失、C-003 赛事通知/章程缺失、C-004 DOCX 属性失效、C-005 页码不可得、C-006 旧引用版本不一致、C-007 inbox 位置；含原文/位置、涉及模块、影响、方案与推荐。
  - 新增 `docs/PROJECT_OVERVIEW.md`、`ARCHITECTURE.md`、`GLOSSARY.md`、`DEVELOPMENT_WORKFLOW.md`、`MEMORY_GUIDE.md`、`MCP_CATALOG.md`、`SECURITY_POLICY.md`；更新 `docs/SKILL_CATALOG.md`。
  - 更新 `docs/memory/references.md`、`project-context.md`、`architecture-decisions.md`、`feedback-and-lessons.md`、`environment.md`、`docs/state/runtime_states.md`、`README.md`，修正版本引用为“内部 v4.3.0（文件名 v4.3.1，BLK-002）”。
  - `T-SKILLS-001` 由 `IN_REVIEW` 转 `DONE`；`T-MCP-001` 保持 `DONE`；新增 `T-DOCS-001`（`IN_REVIEW`，阶段 7 交付）；`BLK-002` 保持 `OPEN`，严重度改为 `HIGH`；`BLK-001` 不变；G0–G7 全部未改，仍 `NOT_STARTED`。
- 原因：按用户批准的阶段 7 范围完成资料发现、逐份阅读、版本/冲突登记、来源登记与知识整理；在不修改原件、不复制副本、不进入 G0 的前提下，为后续 G0 冻结提供可核查基线。
- 验证：
  - `& $py docs/verification/stage7/extract_docx.py`：`DOCX_EXTRACT=OK`；111,209 字节；SHA256 `9E54168F…CCB3A`；754 段 / 80 表；exit 0；日志 `00_extract.log`。
  - `& $py docs/verification/stage7/verify_version_strings.py`：`VERSION_EVIDENCE=OK`；文档内 `v4.3.1` 计数 0，`v4.3.0` 计数 6（document.xml）+1（header）+1（core）；exit 0；日志 `07_version_strings.log`。
  - 文件哈希：`Get-FileHash` = `9E54168FB1B553294ECB88E2E3F5C8CE878EE699FCF07E37D531A68C195CCB3A`；执行前后一致；`09_inventory.log`。
  - `& $py scripts/state_sync.py validate`：`OK`，任务=3，门禁 PASS=0/8，阻塞=2；exit 0；日志 `10_state_sync_validate.log`。
  - `& $py scripts/state_sync.py render`：生成 `PROJECT_STATE.md` SHA256 `5ecce6ed…b0b229`、`IMPLEMENTATION_STATUS.md` SHA256 `61eaa7bb…bfc540`；exit 0；日志 `11_state_sync_render.log`。
  - `& $py scripts/state_sync.py check`：两个生成文件逐字节一致；exit 0；日志 `12_state_sync_check.log`。
  - `& $py docs/verification/stage7/scan_secrets.py`：21 个文件、0 命中、`SECRET_SCAN=PASS`；日志 `13_secret_scan.log`。
  - `& $py -m unittest discover -s tests -v`：两次尝试均被 DSH 沙箱临时目录 ACL 拒绝（`Ran 23 tests` / `FAILED (errors=43)`，均为 `PermissionError [WinError 5]`，无断言失败）；**不计为测试通过**；未修改测试/expected/阈值；说明见 `18_unittest_attempt.md`，原始日志 `18_unittest.log`。
  - 页码尝试：Word COM 只读启动阻塞，未取得页码；未修改文档；见 `06_page_map_attempt.md`。
- 影响/后续：
  - **无 ResearchFlow 运行时架构变化**；未改 StateMachine、Schema、API、证据等级、安全边界或 G0–G7，不新增 ADR。
  - **版本基线未定**：文件名 v4.3.1 / 内部 v4.3.0；`BLK-002` 保持 OPEN。确认前不得进入 G0 冻结，不得把目标数字当最终验收合同，也不得把 v4.3.0 改写成 v4.3.1。
  - **未复制/移动/修改 DOCX**；原件仍在根目录；`docs/reference/inbox/` 保持空（仅 `.gitkeep`）；“禁止再产生第二份策划书副本”已写入 SOURCE_REGISTER。
  - 阶段 6 备份 `cordis.patch.yml.bak-20261108-stage6` 保留，至少到阶段 8 验收结束。
  - 未 commit、未 `git add`、未建 `.venv`、未安装依赖、未开发业务代码；commit 数仍 0，`last_verified_commit` 仍 `null`。
  - 停止并等待用户验收阶段 7；未批准前不进入阶段 8。
- 相关文件：`docs/reference/SOURCE_REGISTER.md`、`docs/reference/CONFLICT_REPORT.md`、`docs/PROJECT_OVERVIEW.md`、`docs/ARCHITECTURE.md`、`docs/GLOSSARY.md`、`docs/DEVELOPMENT_WORKFLOW.md`、`docs/MEMORY_GUIDE.md`、`docs/MCP_CATALOG.md`、`docs/SECURITY_POLICY.md`、`docs/SKILL_CATALOG.md`、`docs/verification/stage7/*`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/memory/*`、`docs/SESSION_HANDOFF.md`、`README.md`。

### 2026-11-08 · 阶段 8 · AI 研发工作站综合验收

- 变更：
  - 执行阶段 8 的 26 项验收，逐项记录命令/操作、退出码、结果与证据；总报告 `docs/verification/stage8/STAGE8_REPORT.md`。
  - 按用户决议关闭 `BLK-002`（`RESOLVED`，resolution 写明“内容基线=内部 v4.3.0；v4.3.1 为文件名标签”；severity 保留 `HIGH` 作为历史属性）；`CONFLICT_REPORT` 的 `C-001` 标 `RESOLVED（用户决议）`，保留全部原始证据行。
  - `T-DOCS-001` 由 `IN_REVIEW` 转 `DONE`；新增 `T-STAGE8-001`（阶段 8 综合验收）为 `IN_REVIEW`，等待用户验收。
  - 新增 `BLK-003`（OPEN，HIGH）：workspace-write 下 23 项测试受临时目录 ACL 阻塞；记录“不得改测试/expected/临时目录位置”的处置原则。
  - 新增 `docs/state/G0_DECISION_LIST.md`：版本项标“已决”，剩余 3 项为 FR-010 的 T0 边界、§15.5 与附录 J 的顺序、FR-015/016/017 的 P1 与 T2 错位。
  - 更新 `docs/reference/SOURCE_REGISTER.md`、`CONFLICT_REPORT.md`、`docs/memory/*`、`README.md`、`ARCHITECTURE.md`、`GLOSSARY.md`、`DEVELOPMENT_WORKFLOW.md`、`PROJECT_OVERVIEW.md`、`SECURITY_POLICY.md`、`docs/state/runtime_states.md`、`docs/SKILL_CATALOG.md` 的版本/阻塞/阶段 8 记录；`docs/PROJECT_STATE.md` 与 `IMPLEMENTATION_STATUS.md` 由 render 生成。
- 原因：用户批准阶段 8，要求以真实运行证据验收工作站；同时按用户 2026-11-08 决议关闭 BLK-002、登记 BLK-003、更新 G0 裁决清单。
- 验证：
  - `& $py scripts/state_sync.py validate`：exit 0；任务=4；门禁 PASS=0/8；阻塞=3（OPEN 2 / RESOLVED 1）。
  - `& $py scripts/state_sync.py render`：exit 0；生成 `PROJECT_STATE.md` SHA256 `2335a1d6…63ea5`、`IMPLEMENTATION_STATUS.md` SHA256 `d04ff691…0cb8`。
  - `& $py scripts/state_sync.py check`：exit 0；2 个生成文件逐字节一致。
  - 受控不一致：临时 fixture 基线 check exit 0 → 追加一行后 exit 1（含预期/实际 SHA256 与 diff）→ 恢复后 exit 0；fixture 已删除；真实项目文件未篡改。
  - `& $py -m unittest discover -s tests -v`：在用户切换后的 `danger-full-access` 会话下 23/23 OK，3.2 s，exit 0；**不能据此宣称 workspace-write 下通过**，`BLK-003` 保持 OPEN。
  - DOCX：111,209 字节；SHA256 `9E54168FB1B553294ECB88E2E3F5C8CE878EE699FCF07E37D531A68C195CCB3A`；全项目 DOCX/PDF=1；inbox 仅 `.gitkeep`。
  - 431 个目录联接：431 / 0 断链；旧 CLI `0.1.0-rc.8` 完整。
  - 阶段 8 证据秘密扫描：0 命中；未读取 `.credentials.yaml` 或 Session。
- 影响/后续：
  - **无 ResearchFlow 运行时架构变化**；未改 StateMachine、Schema、API、证据等级、安全边界或 G0–G7，不新增 ADR。
  - **阶段 8 未全部通过**：第 5、6、23 项 FAIL（会话被用户切换为 `danger-full-access` / 审批关闭，沙箱与审批不符合 `workspace-write` / `ask`）；第 20 项 NOT VERIFIED（0 commit，回滚未实测）；其余 22 项 PASS。
  - `BLK-003` 保持 OPEN；阶段 8 不把全权限下的 23/23 写成 workspace-write 已验证。
  - 未 commit、未 `git add`、未建 `.venv`、未安装依赖、未开发业务代码、未进入阶段 9；`last_verified_commit` 仍 `null`。
  - 阶段 6 备份保留；DOCX 未修改/未改名/未移动；未产生第二份策划书副本。
- 相关文件：`docs/verification/stage8/*`、`docs/state/project_state.json`、`docs/state/G0_DECISION_LIST.md`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/reference/SOURCE_REGISTER.md`、`docs/reference/CONFLICT_REPORT.md`、`docs/memory/*`、`docs/SKILL_CATALOG.md`、`docs/SESSION_HANDOFF.md`、`README.md`。

### 2026-11-08 · 阶段 8 补验 · 策略恢复后重跑

- 变更：
  - 用户在 Desktop 恢复 `workspace-write` / 审批 `ask`；本阶段在恢复后的策略下重跑第 5、6、23 项。
  - 第 13 项拆分为 13a（check 负例）与 13b（23 项 unittest）；13a 保留 PASS，13b 在 workspace-write 下重跑。
  - 第 2 项措辞改为“静态确认 PASS / 运行态未观测”；“2D 未单独执行”加入 `docs/state/G0_DECISION_LIST.md` 的 G0 残留风险清单。
  - 按用户给定命令执行 BLK-003 最小取证；保留失败路径目录 `D:\ResearchFlow-project\tmpavet2qv9` 供权限诊断，未改代码/测试/expected/目录结构/权限。
  - 更新 `BLK-003` 描述为“待权限诊断”；`T-STAGE8-001` 证据路径增加补验日志；生成状态文件重新渲染。
  - 更新 `STAGE8_REPORT.md`、`02_security_2c.md`、`G0_DECISION_LIST.md`、记忆文件与交接。
- 原因：阶段 8 初验的 5/6/23 FAIL 必须通过恢复策略后重跑消除，不接受书面偏差；BLK-003 需先取证再判断，不得下结论说环境不可修。
- 验证：
  - 第 5 项：`workspace-write` 下工作区写/读/删成功；写 `C:\Users\Administrator\stage8_outside_probe.txt` 被拒（访问被拒绝），目标文件未生成；日志 `33_item5_workspacewrite.log`。
  - 第 6 项：运行时上下文为 `workspace-write` / 审批 `ask`；日志 `30_policy_restored.log`、`34_item6_23_workspacewrite.log`。
  - 第 23 项：审批 `ask`；Profile/插件 teams/parallel 命中 0；workflow 0；子 Agent 1；日志 `34_item6_23_workspacewrite.log`。
  - 13a：临时 fixture 基线 check exit 0 → 篡改后 exit 1（含 SHA256/diff）→ 恢复后 exit 0；fixture 已删除；日志 `35_check_negative_workspacewrite.log`。
  - 13b：`& $py -m unittest discover -s tests -v` 在 workspace-write 下 exit 1，`Ran 23 tests`，`FAILED (errors=43)`，0.5 s，无断言失败；日志 `32_unittest_workspacewrite.log`。**不引用全权限下的 23/23 作为通过依据。**
  - BLK-003 取证：`tempfile.mkdtemp(dir=D:\ResearchFlow-project)` 创建 `D:\ResearchFlow-project\tmpavet2qv9` 后，写 `probe.txt` 抛 `PermissionError [Errno 13] Permission denied: 'D:\ResearchFlow-project\tmpavet2qv9\probe.txt'`；exit 1。系统临时目录拒绝属预期，工作区子目录写入被拒属待诊断；日志 `31_blk003_probe.log`、`31b_probe_path_evidence.log`。
  - `& $py scripts/state_sync.py validate`：exit 0；任务=4，门禁 PASS=0/8，阻塞=3。
  - `& $py scripts/state_sync.py render`：exit 0；`PROJECT_STATE.md` SHA256 `e7c9593e…cfff1`、`IMPLEMENTATION_STATUS.md` SHA256 `6ed89f82…e508e`。
  - `& $py scripts/state_sync.py check`：exit 0；2 个生成文件逐字节一致。
- 影响/后续：
  - 第 5、6、23 项 FAIL 已消除；**阶段 8 无 FAIL 项**。
  - 13b、20 仍 `NOT VERIFIED`；`BLK-003` 保持 `OPEN`、`HIGH`，备注“待权限诊断”；不得降级、不得关闭。
  - 第 2 项只有静态确认；2D 未单独执行，列入 G0 残留风险。
  - 未 commit、未建 `.venv`、未开发业务代码、未进入阶段 9；DOCX 未修改；阶段 6 备份保留。
- 相关文件：`docs/verification/stage8/30*`–`35*`、`docs/verification/stage8/STAGE8_REPORT.md`、`docs/state/project_state.json`、`docs/state/G0_DECISION_LIST.md`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/memory/project-context.md`、`docs/memory/environment.md`、`docs/memory/feedback-and-lessons.md`、`docs/SESSION_HANDOFF.md`。

### 2026-11-08 · 阶段 8 · 验收通过

- 变更：
  - 用户确认阶段 8 结论：**25 PASS / 2 NOT VERIFIED / 0 FAIL，通过**；三项初验 FAIL 已因策略恢复消除。
  - `T-STAGE8-001` 由 `IN_REVIEW` 转 `DONE`；`T-DOCS-001` 保持 `DONE`；`BLK-002` 保持 `RESOLVED`。
  - `BLK-003` 保持 `OPEN`，severity 由 `HIGH` 降为 `MEDIUM`；备注改为“DSH 沙箱未向运行期新建子目录传播授权；已排除 ACL 损坏，非项目缺陷”。
  - 记录 DSH 权限诊断结果：`NOT_THIS_CLASS`，`WRITE_DAC` / `WRITE_OWNER` 均具备、无缺失权限、`FIXED=0`、未做任何改动；报告路径 `C:\Users\Administrator\AppData\Local\ResearchFlow\acl-diagnostics\acl-report-559f7ffa05844dce8e62ba3238f77f3b.jsonl`。
  - 写明 23 项 unittest 的全权限绕行方式：属代码正确性测试，可在单独批准的 full-access 会话运行；日志记录当次策略，结束立即恢复 workspace-write；结果不得用于第 5/6/23 项或任何安全项。
  - G0 残留风险清单收敛为三条：① 13b 仅在全权限下通过；② 2D 未单独执行、2C 运行态未观测；③ Git 无基线、回滚未实测。
  - 记录 `tmpavet2qv9` 为空目录，阶段 9 开始时只删除该目录，不动其他目录；本次未删。
- 原因：用户完成阶段 8 验收与 BLK-003 权限诊断；按用户决议降级阻塞、固化绕行边界、收敛 G0 风险，不进入阶段 9。
- 验证：
  - `& $py scripts/state_sync.py validate`：exit 0；任务=4；门禁 PASS=0/8；阻塞=3（OPEN 2 / RESOLVED 1）。
  - `& $py scripts/state_sync.py render`：exit 0；`PROJECT_STATE.md` SHA256 `197d9d85…13e34`、`IMPLEMENTATION_STATUS.md` SHA256 `a15e38ae…73b5f`。
  - `& $py scripts/state_sync.py check`：exit 0；2 个生成文件逐字节一致。
  - 13b 保持 NOT VERIFIED；仅引用 `32_unittest_workspacewrite.log`，不引用全权限 23/23。
  - 未重新运行权限诊断；未手工改 ACL；未修改测试、expected、目录结构或权限。
- 影响/后续：
  - 阶段 8 已通过；阶段 9 尚未开始。
  - 阶段 9 开始时只删除 `D:\ResearchFlow-project\tmpavet2qv9` 这一个空目录；不得动其他目录。
  - 三条 G0 残留风险见 `docs/state/G0_DECISION_LIST.md`。
  - 未 commit、未建 `.venv`、未安装依赖、未开发业务代码；`last_verified_commit` 仍 `null`。
- 相关文件：`docs/verification/stage8/STAGE8_REPORT.md`、`docs/state/project_state.json`、`docs/state/G0_DECISION_LIST.md`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/memory/project-context.md`、`docs/memory/environment.md`、`docs/memory/feedback-and-lessons.md`、`docs/SESSION_HANDOFF.md`。

### 2026-11-09 · G0 · ⑨ 契约机器可读化与 10 项决议落地

- 变更：
  - 新增 ⑨：`contracts/` 下五份 JSON Schema Draft 2020-12（`TaskSpec`、`NodeSpec`、`EvidenceRecord`、`VerificationReport`、`CompletionCertificate`）。每份含 `$id`、`title`、`schema_version`（`const "1.0"`）、显式 `additionalProperties`；枚举、pattern、必填、RFC 3339 `date-time` 均落入 schema，不留 Markdown-only 规则。
  - 新增 `scripts/validate_contracts.py`：仅标准库；schema lint + `schema`/`semantic`/`json` 三层校验；未实现关键字 fail closed，避免拼写错误静默放行。
  - 新增 `contracts/examples/`：5 个正例 + 67 个反例（共 72 例）+ `manifest.json`；每个反例声明期望的 layer/keyword/pointer，拒绝原因不匹配即 FAIL，不按实际结果回填。
  - 新增 `contracts/README.md`、`docs/verification/g0/build_examples.py`（证据构造脚本，非运行期代码）、`docs/verification/g0/check_links_g0.py`（只读链接检查）。
  - 按用户 10 项决议更新 ⑤⑥⑦⑧：补三个 `schema_version` 与证书 `issued_at`、签名载荷白名单（05 §1.5）、`dataset_ref` 对象化（05 §2.4）、`INVALIDATED → READY` 三条件守卫（05 §9.3）、T0 不复用 Recovery 状态机（05 §9.5）、失败迁移 `DENIED` 审计（05 §9.7、06 §2）、删除 `recovery_plans` 表并改内容寻址文件（06 §1.3）、`/recover` 404 与启动守卫（06 §4.1、§4.6）、I-11–I-14 与 schema 外不变量清单（05 §10、§13）。
- 原因：用户要求把已可冻结的五个契约写成机器可读定义并在 G0 冻结前跑通正反例；随后按 10 项决议修正受影响段落，避免散文表格与机器定义分叉。
- 验证：
  - `& $py scripts/validate_contracts.py --selftest`：10/10 PASS，exit 0；日志 `docs/verification/g0/01_selftest.log`。
  - `& $py scripts/validate_contracts.py`：`contracts=5 cases=72 pass=72 fail=0 exit=0`；taskspec 16、nodespec 14、evidencerecord 13、verificationreport 15、completioncertificate 14，各自 PASS；日志 `docs/verification/g0/02_validate_contracts.log`。
  - `& $py docs/verification/g0/check_links_g0.py <5 个改动文档>`：43 links / 0 broken / PASS，exit 0；日志 `docs/verification/g0/03_link_check.log`。
  - `& $py scripts/state_sync.py validate|render|check`：均 exit 0；2 个生成文件逐字节一致。
  - 契约文件哈希（SHA256）：`taskspec` `b3601c60…`、`nodespec` `40438535…`、`evidencerecord` `7c581ac5…`、`verificationreport` `3e4baa46…`、`completioncertificate` `71abc245…`、`validate_contracts.py` `fc2ee856…`；完整值与字节数见 `docs/verification/g0/04_artifacts_sha256.log`。
  - 全部文件 LF、无 BOM；`contracts/examples` 文件数 73（72 例 + manifest）；日志以 UTF-8 写出（`-X utf8` + `PYTHONIOENCODING=utf-8`），已用读取工具复核中文未乱码。
- 影响/后续：
  - **证据覆盖事故（如实登记）**：运行 `docs/verification/stage7/check_links.py` 前未确认其 `OUT` 常量，该脚本按设计覆盖了 `docs/verification/stage7/14_link_check.log`。当前内容为 106 字节 / SHA256 `A3ECADA1042A2780F7AC8E4BC3470B6F9CEB165D4B5304061CC43F534EF60965` / 239 links / 0 broken / PASS；阶段 7 报告记为 232 links，`16_final_inventory.log` 记录原 SHA256 为 `B9FDD0AB…`。无 git 基线，无法恢复原字节；**未再运行该脚本**，本轮改用只读的 `check_links_g0.py`。处置按用户 2026-11-09 指令执行：**不改写历史**，原 232 记录保持不动，新增 `docs/verification/stage7/SUPERSEDED_NOTICE.md` 登记原值/现值、覆盖原因、无法恢复与后续只追加规则；⑧ 风险表新增第 14 条。
  - ②③④ 本轮未改（按用户“只改 ⑤⑥⑦⑧”）；与已关闭项同源的旧表述列在 ⑧ §6.1 第 4 项，②③ 的 `schema_version` 措辞列在第 3 项。
  - 未 commit、未建 `.venv`、未安装依赖、未写业务代码；G0–G7 仍 `NOT_STARTED`；`T-G0-001` 仍 `IN_PROGRESS`，等待用户整体评审。
- 相关文件：`contracts/README.md`、`contracts/*.schema.json`、`contracts/examples/*`、`scripts/validate_contracts.py`、`docs/verification/g0/*`、`docs/design/05_CONTRACTS_AND_STATES.md`、`docs/design/06_DATA_AND_API.md`、`docs/design/07_T0_PLAN_AND_GATES.md`、`docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/SESSION_HANDOFF.md`。

### 2026-11-09 · G0 · 用户验收 ⑨ 后的定向修订（Git 预检、②③ 一致性、依赖矩阵、ADR 落地）

- 变更：
  - **Git 基线预检（只读，未配置身份、未 add、未 commit）**：报告 `user.name` / `user.email` 均未配置、分支 `main`、0 commit；逐条 `git check-ignore` 证明 `contracts/*.json` 与 `docs/verification/**` **不被忽略**（`/*.log` 只匹配根目录、`/tmp/` 只忽略根 `tmp/`）；生成首提候选清单 282 个文件（未跟踪 283，排除 DOCX 1 个）。报告见 `docs/verification/g0/05_git_baseline_report.md`，清单见 `06_first_commit_filelist.txt`。
  - **②③ 一致性**：② `FR-008` 验收方法与证据列补 `schema_version`（const `"1.0"`）、证书 `issued_at`、签名载荷覆盖，并引用 `contracts/completioncertificate.schema.json` 与 `completioncertificate.negative.1/3.json`、`verificationreport.negative.1.json`；③ `US-T0-13` 与 §3.1 第 9 步同步同一句。②③ 升 v0.2。
  - **四词自检**：在 ②③④⑤⑥⑦ 搜索 `schema_version` / `INVALIDATED` / `plan_hash` / `dataset_ref`，输出逐行命中与 3 条自动断言（无字符串形态 `dataset_ref`、`plan_hash` 必伴随 `plan_id`、`schema_version` 必伴 `1.0`），`TERMS_RESULT=PASS`；自检当场修正 ⑤ 两处（`const "1.0"` 与 MINOR 兼容的表述、版本记录 §2.5→§2.4 误引）。
  - **① v1.1**：§6 索引增加 ⑨，②–⑧/ADR 状态更新；§4.8、§7 的 `OQ-B1-1/2`、`OQ-BASE-1` 同步为已决；§2.3 契约状态改为“五份 schema 已建（⑨，未冻结）”。术语未改。
  - **④ v0.2**：`OQ-ARCH-1/2` 同步为已决；架构分层与信任边界未改。
  - **⑤ v0.3**：3 处定向修订（见版本记录）；**⑧ v0.3**：新增风险第 14 条、ADR 正式文件索引、§6.1 收敛为 1 项待确认、文档包状态更新。
  - **新建 `docs/ADR/`**：`ADR-001`–`ADR-006` 为 `ACCEPTED`，`ADR-007` 为 `PROPOSED`，另加索引 `README.md`；内容与 ⑧ 已裁决文本一致。
  - **stage7 覆盖日志处置**：按用户指令“不改写历史”，新增 `docs/verification/stage7/SUPERSEDED_NOTICE.md`（原 232 / `B9FDD0AB…`，现 239 / `A3ECADA1…`，原因、不可恢复、后续只追加）；未改 `STAGE7_REPORT.md` 与 `16_final_inventory.log`。⑧ 风险表新增“证据日志可被同名脚本覆盖”一条。
  - **依赖版本矩阵（只读调研）**：新增 `docs/verification/g0/09_dependency_matrix.md` + `research_versions.py` + 原始日志；覆盖 10 个指定包 + 7 个关键传递依赖，全部有 cp311/win_amd64 或纯 Python wheel；numpy 固定 2.4.6（2.x 唯一可行线），pydantic 2.14.3 + pydantic-core 2.50.4，starlette 1.x 配对列为待实测风险。
  - **schema 描述**：`kind`、`l1/l2/l3_status`、`side_effect_class` 的 `description` 注明“候选集合，按 MINOR 可变”。
- 原因：用户验收 ⑨ 后要求先建 Git 基线的前置调查、修正 ②③ 与 ⑤ 的不一致、给出 WP-01 依赖预检、并按规定方式处置被覆盖日志；同时把 ①/②/④ 的旧表述一次性同步，避免冻结前遗留矛盾。
- 验证：
  - `& $py -X utf8 scripts/validate_contracts.py --selftest`：10/10 PASS，exit 0。
  - `& $py -X utf8 scripts/validate_contracts.py`：`contracts=5 cases=72 pass=72 fail=0 exit=0`。
  - `& $py -X utf8 docs/verification/g0/check_terms.py`：`TERMS_RESULT=PASS`，exit 0。
  - `& $py -X utf8 docs/verification/g0/check_links_g0.py <20 个文档>`：`FILES=20 LINKS_CHECKED=77 BROKEN=0`，exit 0。
  - `& $py -X utf8 docs/verification/g0/research_versions.py`：17 个包全部找到兼容 wheel，`RESULT=OK`，日志 `08_dependency_matrix.log`。
  - `& $py scripts/state_sync.py validate|render|check`：均 exit 0；生成文件 `PROJECT_STATE.md` `eaa0b11b…`、`IMPLEMENTATION_STATUS.md` `4dfbfa90…`。
  - 全部新增/修改文件 LF、无 BOM；`docs/verification/g0/04_artifacts_sha256.log` 记录 33 个产物的 SHA256。
  - 未重跑 `docs/verification/stage7/check_links.py`；未安装依赖、未建 `.venv`、未生成 lock。
- 影响/后续：
  - **未 commit**：等用户提供 Git 身份并批准提交信息与清单；`BLK-001` 仍 `OPEN`。
  - G0 仍 `NOT_STARTED`；`T-G0-001` 仍 `IN_PROGRESS`；等待“G0 冻结前检查清单”逐项签字。
  - 仍待用户确认：三组枚举候选集合是否按现值冻结（⑧ §6.1 唯一 1 项）；DOCX 忽略方案 A/B/C；依赖矩阵是否作为 WP-01 锁定基线。
- 相关文件：`docs/verification/g0/05_git_baseline_report.md`、`docs/verification/g0/06_first_commit_filelist.txt`、`docs/verification/g0/07_term_consistency.log`、`docs/verification/g0/08_dependency_matrix.log`、`docs/verification/g0/09_dependency_matrix.md`、`docs/ADR/*`、`docs/verification/stage7/SUPERSEDED_NOTICE.md`、`docs/G0/01_BASELINE_AND_TERMS.md`、`docs/PRD/02_REQUIREMENT_TRACEABILITY.md`、`docs/PRD/03_PRD_T0.md`、`docs/design/04_ARCHITECTURE.md`、`docs/design/05_CONTRACTS_AND_STATES.md`、`docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md`、`contracts/*.schema.json`。

### 2026-11-10 · G0 · 规格基线统一 v1.0、枚举/依赖锁定与首次提交

- 变更：
  - **①–⑧ 与 ⑨ 全部升 v1.0**：每份文档头加一行“冻结日期 2026-11-10｜状态 G0 冻结｜被取代版本”，版本记录保留历史；① 的 v1.1 明确为候选期编号，冻结后归并为 v1.0。
  - **三组枚举按现值冻结**：`kind`（7）、`l1/l2/l3_status`（4）、`side_effect_class`（3）；05 新增 §1.6 冻结清单，⑧ §5.1/§6.1 同步，schema 仅改 `$comment`/`description` 注记，未改 `enum` 与校验语义；保留“按 `MINOR` 可变”。
  - **依赖矩阵锁定为 `WP-01` 基线**：`09_dependency_matrix.md` 标为 v1.0 锁定基线；⑦ `WP-01` 入口条件写入 17 个第三方包 + SQLite，并新增四条解释器硬约束（`uv venv --python 3.11.16`、3.11.16/64bit 指纹、架构优先排查、TestClient 冒烟与回退）。
  - **`ADR-007` 延后**：保持 `PROPOSED`，`WP-13` 前裁决；ADR 文件、索引与 ⑧ §4 三处一致。
  - **Git 身份**：仅在本仓库 `git config --local` 设 `ResearchFlow Dev` / `dev@researchflow.local`；全局身份仍为空；`BLK-001` 置 `RESOLVED`。
  - **DOCX 选 B**：`.gitignore` 增加精确文件名规则，不使用 `*.docx`；DOCX 未修改、未改名、未移动。
  - `project_state.json`：`T-G0-001` 保持 `IN_PROGRESS`；G0–G7 保持 `NOT_STARTED`；`last_verified_commit` 仍为 `null`。
- 原因：按用户 2026-11-10 指令，把候选期版本号统一为 v1.0 后建立可回溯的 G0 规格基线；冻结枚举与依赖，避免 G0 通过后仍以候选值开工；首次提交前完成身份、DOCX 与状态一致性处置。
- 验证：
  - `& $py scripts/validate_contracts.py --selftest`：`SELFTEST 10/10 PASS`，exit 0。
  - `& $py scripts/validate_contracts.py`：`contracts=5 cases=72 pass=72 fail=0 exit=0`。
  - `& $py docs/verification/g0/check_terms.py`：`TERMS_RESULT=PASS`，exit 0。
  - `& $py docs/verification/g0/check_links_g0.py <本轮文档>`：`BROKEN=0`，exit 0；完整计数见 `13_version_freeze_links.log`。
  - `& $py scripts/state_sync.py validate|render|check`：均 exit 0；2 个生成文件逐字节一致。
  - Git：`git check-ignore -v` 对 DOCX 命中 `.gitignore` 精确规则；其他 `.docx` 路径未命中；`git config --global --get user.name/user.email` 仍为空。
- 影响/后续：
  - 本轮建立首次 G0 规格基线提交；`last_verified_commit` 不自动更新，G0 是否 PASS 由用户宣布。
  - 未创建 `.venv`、未安装依赖、未生成 lock、未写业务代码；`WP-01` 的解释器与 TestClient 冒烟在 T0 启动后执行。
  - `BLK-003` 与阶段 8 的 13b/第 20 项仍未关闭或仍 `NOT VERIFIED`，不因本提交改变。
- 相关文件：`docs/G0/01_BASELINE_AND_TERMS.md`、`docs/PRD/02_REQUIREMENT_TRACEABILITY.md`、`docs/PRD/03_PRD_T0.md`、`docs/design/04_ARCHITECTURE.md`、`docs/design/05_CONTRACTS_AND_STATES.md`、`docs/design/06_DATA_AND_API.md`、`docs/design/07_T0_PLAN_AND_GATES.md`、`docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md`、`contracts/README.md`、`contracts/*.schema.json`、`docs/ADR/ADR-007-t0-workbench-scope.md`、`docs/ADR/README.md`、`docs/verification/g0/09_dependency_matrix.md`、`docs/verification/g0/10*`–`17*`、`.gitignore`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/SESSION_HANDOFF.md`。

### 2026-11-10 · G0 PASS · Git 回滚补测 · 阶段 8 第 20 项关闭

- 变更：
  - 用户 2026-11-10 宣布 **G0 PASS**；依据 ①–⑧ + ⑨ 全部 v1.0、五份 schema 72/72、阻塞级 OQ=0、Git 基线 `91bde66`、DOCX 哈希未变。
  - `project_state.json`：`stage_gates.G0` → `PASS`，`decided_by="用户"`、`decided_at="2026-11-10"`，`evidence_paths` 指向 ①–⑨ 与 `docs/verification/g0/` 下的决议、复核、回滚日志；`T-G0-001` → `DONE`；`G1`–`G7` 保持 `NOT_STARTED`。
  - `scripts/state_sync.py`：门禁新增可选字段 `decided_by` / `decided_at`；`PASS` 时两者必填，`decided_at` 接受 `YYYY-MM-DD` 或带时区 ISO-8601；`IMPLEMENTATION_STATUS.md` 渲染裁决人与裁决时间。`DEVELOPMENT_WORKFLOW.md` §10.2 同步。
  - Git 回滚补测：在已跟踪文件 `docs/CHANGELOG_DEV.md` 末尾写入 `PROBE-G0-ROLLBACK-20261110`，确认 `git status` 显示修改、`git diff` 可见该行；执行 `git checkout -- docs/CHANGELOG_DEV.md`，退出码 0；blob 与 SHA256 均回到 HEAD 版本，探针无残留。
  - 阶段 8 第 20 项由 `NOT VERIFIED` 改为 **`PASS`（基线建立后补测）**；`20_git_rollback.md`、`STAGE8_REPORT.md` 与 `G0_DECISION_LIST.md` R-3 同步；13b 仍 `NOT VERIFIED`。
  - `AGENTS.md` 新增的两条“正例/负例证据”规则，经用户 2026-11-10 批准纳入本次提交。
  - 新增 `docs/verification/g0/19_g0_pass_decision.md`、`18_git_rollback.log`、`20_g0_pass_recheck.log`、`21_state_sync_g0_pass.log`、`22_gate_decision_schema_test.log`、`check_gate_decision.py`。
- 原因：按用户 2026-11-10 指令记录 G0 PASS、补测 Git 回滚能力并关闭阶段 8 第 20 项，随后才进入 T0 `WP-01`。
- 验证：
  - `& $py -X utf8 scripts/validate_contracts.py --selftest` → `SELFTEST 10/10 PASS`，exit 0。
  - `& $py -X utf8 scripts/validate_contracts.py` → `contracts=5 cases=72 pass=72 fail=0 exit=0`。
  - `& $py -X utf8 scripts/state_sync.py validate` → `OK`，任务 5，门禁 PASS=1/8，阻塞 3，exit 0。
  - `& $py -X utf8 scripts/state_sync.py render` → 生成 2 文件；`PROJECT_STATE.md` SHA256 `b753e313…07c9f`，`IMPLEMENTATION_STATUS.md` SHA256 `961520cb…c2360`，exit 0。
  - `& $py -X utf8 scripts/state_sync.py check` → 2 文件逐字节一致，exit 0。
  - `& $py -X utf8 docs/verification/g0/check_gate_decision.py` → `GATE_DECISION_SCHEMA_TEST=PASS checks=1 positive + 4 negative`，exit 0。
  - 回滚：`git checkout --` exit 0；blob `051d761…` → `a4ae439…` → `051d761…`；SHA256 `070CF8F…AB81` 前后一致；文件级 `git status` 为空。
- 影响/后续：
  - G0 门禁 PASS；未开发 T0 业务代码，下一步只做 `WP-01` 环境与依赖锁定。
  - 本提交未创建 `.venv`、未安装依赖、未生成 lock；`researchflow/` 仍只有 `.gitkeep`。
  - `BLK-003` 保持 `OPEN` / `MEDIUM`；13b 仍 `NOT VERIFIED`；2D 未单独执行。
  - `last_verified_commit` 保持 `null`；用户未下达更新指令，未自行改写。
- 相关文件：`AGENTS.md`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`scripts/state_sync.py`、`docs/DEVELOPMENT_WORKFLOW.md`、`docs/state/G0_DECISION_LIST.md`、`docs/verification/g0/18*`–`22*`、`docs/verification/g0/check_gate_decision.py`、`docs/verification/stage8/20_git_rollback.md`、`docs/verification/stage8/STAGE8_REPORT.md`、`docs/memory/project-context.md`、`docs/SESSION_HANDOFF.md`。

### 2026-11-10 · T0 · WP-01 仓库与环境锁定

- 变更：
  - 用 uv 创建 `.venv`：`uv venv --python 3.11.16 .venv`；首次因默认缓存目录 `C:\Users\Administrator\AppData\Local\uv\cache` 在工作区沙箱外而失败（首次工具捕获 exit 1；复现 uv exit 2），设 `UV_CACHE_DIR=D:\ResearchFlow-project\.uv-cache` 后成功（exit 0，0.51 s）。
  - 解释器指纹：`3.11.16` + `64bit`；`.venv\Scripts\python.exe` 为 3.11.16（MSC v.1944 64 bit）。
  - 按矩阵安装 16 个直接 pin；解析 55 个包、安装 46.10 s；`uv pip check` 全部兼容。
  - 矩阵外新增 `httpx2==2.16.0`（用户 2026-11-10 批准）：starlette 1.10.0 的 `TestClient` 要求 `httpx2` 而非 `httpx`；同时安装 `httpcore2==2.16.0`、`truststore==0.10.5`。
  - 生成 `requirements.in`（直接清单）与 `requirements.lock`（58 个精确 pin）；干净环境 `.venv-repro` 从锁文件安装并 TestClient 200，43.95 s，已删除。
  - 逐项核对：矩阵内 16 包与 SQLite 全部一致；starlette `1.10.0` 与矩阵一致，TestClient 通过后**不回退**；uv 工具版本 `0.12.16` 与矩阵 `0.13.7` 不一致，保留原因已记录（工具不进入 `.venv`，矩阵注明由 WP-01 决定）。
  - `.venv` 实测 502,349,269 字节（502.3 MB），高于矩阵估算 350–450 MB 上限 52.3 MB（+11.6%）；安装主路径 59.48 s。矩阵无耗时估算，未编造对比。
  - `project_state.json`：`current_phase` 转 `T0`；新增 `T-WP-01-001`，状态 `IN_REVIEW`，等待用户验收；`current_milestone` 保持 `M0_GOVERNANCE_BASELINE`（G0 文档未定义 T0 里程碑编号，未自行发明）；G1–G7 仍 `NOT_STARTED`。
  - `researchflow/` 仍只有 `.gitkeep`；未写业务代码、未建数据库、未写 API、未做模板。
- 原因：按用户 2026-11-10 指令进入 T0 `WP-01`，只锁定解释器与依赖；`httpx2` 缺失是真实冒烟发现的矩阵遗漏，先报告并获批准后才安装。
- 验证：
  - `.venv\Scripts\python.exe -c "import sys,platform;print(sys.version,platform.architecture()[0])"` → `3.11.16 ... 64bit`，exit 0。
  - `uv pip check --python .venv/Scripts/python.exe` → `All installed packages are compatible`，exit 0。
  - TestClient：`TESTCLIENT_OK 200 {'ok': True}`，exit 0。
  - 8 模块导入 + numpy/scipy/pandas/sklearn 组合：`2.4.6 / 1.17.1 / 3.1.1 / 1.9.1`，numpy 区间 PASS，exit 0。
  - uvicorn 实际启动：`STARTUP_OK`，HTTP 200 `{"ok":true}`，exit 0。
  - `state_sync.py validate|render|check` → 均 exit 0；`PROJECT_STATE.md` SHA256 `756d1f5f…3967`，`IMPLEMENTATION_STATUS.md` SHA256 `1bca2b36…ed4b`。
- 影响/后续：
  - `T-WP-01-001` 为 `IN_REVIEW`，验收前不进入 `WP-02`；T0 业务代码仍未开始。
  - `BLK-003` 保持 `OPEN` / `MEDIUM`；13b 仍 `NOT VERIFIED`；2D 未单独执行。
  - `last_verified_commit` 保持 `null`；未按未经指令的方式改写。
  - `.venv`、`.uv-cache` 不纳入 Git；`requirements.in`、`requirements.lock` 纳入版本控制。
- 相关文件：`requirements.in`、`requirements.lock`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/verification/t0/wp-01/*`、`docs/memory/environment.md`、`docs/memory/project-context.md`、`docs/SESSION_HANDOFF.md`。

### 2026-11-10 · T0 · WP-01 验收通过

- 变更：
  - 用户逐项裁决四项待决事项：`T-WP-01-001` → `DONE`；`.venv` 502.3 MB 超估算一事接受为已知偏差；`last_verified_commit` → `19c337f350fead30efd52c222356ad6248a3f937`；T0 里程碑暂不指定，保持 `M0_GOVERNANCE_BASELINE`。
  - `project_state.json`：`T-WP-01-001.status=DONE`、`updated_at=2026-11-10T22:16:00+08:00`，`evidence_paths` 增补 `30_wp01_acceptance.md` 与 `state_sync_acceptance.log`；顶层 `last_verified_commit` 由 `null` 更新为 `19c337f`；`current_milestone` 未改。
  - 新增 [`docs/verification/t0/wp-01/30_wp01_acceptance.md`](verification/t0/wp-01/30_wp01_acceptance.md)：四项裁决、7 条验收标准逐条对账、体积偏差处置、未随验收改变的事项。
  - `09_dependency_matrix.md` §4 增补 WP-01 实测体积/耗时与“接受为已知偏差”的裁决记录；`WP-01_REPORT.md` 状态行由 `IN_REVIEW` 改为 `DONE`。
- 原因：用户 2026-11-10 验收 `T-WP-01-001`，并就体积、`last_verified_commit`、里程碑编号作出明确选择。
- 验证：
  - `state_sync.py validate|render|check` 均 exit 0；完整 stdout 见 `docs/verification/t0/wp-01/state_sync_acceptance.log`。
  - `PROJECT_STATE.md` SHA256 `{state_hash[:16]}…`，`IMPLEMENTATION_STATUS.md` SHA256 `{status_hash[:16]}…`。
- 影响/后续：解除“验收前不进入 WP-02”的限制，进入 `WP-02` 核心契约落地；`BLK-003` 仍 `OPEN` / `MEDIUM`，13b 仍 `NOT VERIFIED`，2D 未单独执行。
- 相关文件：`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/verification/t0/wp-01/30_wp01_acceptance.md`、`docs/verification/t0/wp-01/state_sync_acceptance.log`、`docs/verification/g0/09_dependency_matrix.md`、`docs/verification/t0/wp-01/WP-01_REPORT.md`、`docs/SESSION_HANDOFF.md`。
- 架构变化：无（仅研发状态与文档更新，未触及运行时契约与代码）。

### 2026-11-10 · T0 · WP-02 核心契约落地

- 变更：
  - 新增 [`researchflow/contracts/models.py`](researchflow/contracts/models.py)：5 份冻结 schema 的 Pydantic v2 模型；严格模式（`strict=True` + `extra="forbid"`）对应 JSON Schema 的类型与 `additionalProperties` 语义。
  - 新增 [`researchflow/contracts/parsing.py`](researchflow/contracts/parsing.py)：RFC 8259 严格解析，拒绝重复键、`NaN`/`Infinity`、非法 UTF-8。
  - 新增 [`researchflow/api/app.py`](researchflow/api/app.py)：`POST /api/v1/tasks` 契约绑定、422 统一错误体（`SCHEMA_INVALID` + `field_path` + `correlation_id`）、幂等、`GET /tasks/{id}`、`/healthz`、`/readyz`；按决议 8 不注册 `/recover`。
  - 新增 [`scripts/check_model_parity.py`](scripts/check_model_parity.py)：行为 + 结构双层一致性检查，产出 `model_parity.json`。
  - 新增 [`tests/test_contract_models.py`](tests/test_contract_models.py)（89 项）与 [`tests/test_api_422.py`](tests/test_api_422.py)（13 项）。
  - `project_state.json`：新增 `T-WP-02-001`，状态 `IN_REVIEW`；`current_phase` 仍 `T0`，`current_milestone` 未改。
- 原因：用户 2026-11-10 验收 WP-01 后批准直接进入 WP-02；按 ⑦ §2.2 与 ⑨ v1.0 把 schema 落成模型并绑定 API。
- 验证：
  - `validate_contracts.py --selftest` → `SELFTEST 10/10 PASS`，exit 0。
  - `validate_contracts.py` → `contracts=5 cases=72 pass=72 fail=0`，exit 0。
  - `check_model_parity.py` → `agree=72 disagree=0 structure_problems=0 result=PASS`，exit 0。
  - `pytest tests` → `125 passed`，exit 0（模型 89 + API 13 + 既有 23）。
  - `state_sync.py validate|render|check` → 均 exit 0；`PROJECT_STATE.md` SHA256 `032858c586d9acda…`，`IMPLEMENTATION_STATUS.md` SHA256 `8f759dea8430d744…`。
- 影响/后续：
  - `T-WP-02-001` 为 `IN_REVIEW`，验收前不进入 `WP-03`。
  - API 的 `state` 字段是 06 §4.2 响应形态绑定，底层为临时内存注册表，**不是状态机**；状态机与 SQLite 在 WP-03 接管。
  - `graph`／`evidence`／`verify`／`report`／`certificate` 端点、启动守卫未实现，已在报告中登记。
  - `BLK-003` 仍 `OPEN` / `MEDIUM`；13b 仍 `NOT VERIFIED`；2D 未单独执行。
- 相关文件：`researchflow/contracts/*`、`researchflow/api/*`、`scripts/check_model_parity.py`、`tests/test_contract_models.py`、`tests/test_api_422.py`、`conftest.py`、`docs/verification/t0/wp-02/*`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/SESSION_HANDOFF.md`。
- 架构变化：无。契约 schema 未修改；新增的是契约的模型实现与 HTTP 绑定。API 的临时注册表已明确标注为 WP-03 前的存根，不构成架构决策。

### 2026-11-10 · T0 · WP-02 验收通过

- 变更：
  - 用户验收 `T-WP-02-001`：状态 `IN_REVIEW` → `DONE`；`updated_at=2026-11-10T22:45:00+08:00`；`evidence_paths` 增补验收记录与状态同步日志。
  - 新增 [`docs/verification/t0/wp-02/40_wp02_acceptance.md`](verification/t0/wp-02/40_wp02_acceptance.md)：7 条验收标准逐条对账、复核命令与真实结果、边界确认。
- 原因：用户 2026-11-10 选择"验收通过并提交"。
- 验证：`state_sync.py validate|render|check` 均 exit 0；`PROJECT_STATE.md` SHA256 `096130298a153690…`，`IMPLEMENTATION_STATUS.md` SHA256 `9fd641b5465daa09…`。
- 影响/后续：`T-WP-02-001` 关闭；WP-03（SQLite + StateMachine + audit_log）可启动，但需用户另行指令。
- 相关文件：`docs/state/project_state.json`、`docs/verification/t0/wp-02/40_wp02_acceptance.md`、`docs/verification/t0/wp-02/state_sync.log`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/SESSION_HANDOFF.md`。
- 架构变化：无。
