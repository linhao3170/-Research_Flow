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

### 2026-11-10 · 工程经验库快照 v1.0

- 新增 `docs/knowledge/ENGINEERING_LESSONS.md`：从阶段 3B–WP-02 记录提炼 14 条工程教训，均带来源锚点或 commit SHA。
- 范围：只读审计；未修改业务代码、契约、`AGENTS.md`、ADR、`project_state.json`；未移动或删除历史文件。
- 验证：逐条核对来源路径/行号；文件 184 行（≤250）；未新增规则，状态仍以 `project_state.json` 为准。
- 架构变化：无（文档治理快照）。

### 2026-11-11 · P0 · 伪代码 P1–P6 冻结与状态对账

- 变更：
  - 建立 `design/pseudocode/` P1–P6 基线并纳入版本控制：仅暂存 83 个文件（M01–M12 79 + `00_BASELINE` 3 + `OPEN_QUESTIONS.md` 1），提交 `1c9a104`，`83 files changed, 39146 insertions(+)`。
  - 新增 [`design/pseudocode/STAGE_LOG.md`](design/pseudocode/STAGE_LOG.md) 与 [`design/pseudocode/INDEX.md`](design/pseudocode/INDEX.md)：P1–P6 六条阶段日志、12 模块索引；P1 标已验收（2026-11-11），P2–P6 标待验收。
  - `project_state.json`：`last_verified_commit` 由 `19c337f` 修正为 `1c9a104`；新增 `T-PSEUDO-001`（T0 / `IN_REVIEW` / 依赖 `T-WP-02-001`），未把 P2–P6 标为 `DONE`。
  - `BLK-003` 复核：会话策略在复核期间由 `workspace-write` 切换为 `danger-full-access`；按本轮铁律未运行 `pytest`/`unittest`；最小写入探针 exit 0，未复现 2026-11-08 的写入失败；阻塞保留 `OPEN`，历史描述未删除。
  - `environment.md` 6 处与 `MEMORY_GUIDE.md` 1 处“未…”措辞按“历史/当前”逐条处置（历史加“（历史）”，当前改为无过期措辞）；`check_docs_drift` 由 WARNING=8 降为 0。
  - `docs/knowledge/ENGINEERING_LESSONS.md` 纳入 Git 跟踪；`Memory.md` 已有指向它的索引行，未重复添加。
  - `AGENTS.md`：§0/§2 读取顺序改为 `project_state.json` 先于 `Memory.md`；§7 改名“写入顺序”并拆为 state → 同步 → CHANGELOG → 交接 → 稳定记忆；`project-context.md` 描述改为背景、不维护当前进度。
  - `docs/memory/*`：`Memory.md` 去掉“最近更新/是否已核验”列与时间戳；`project-context.md` 删除当前阶段/任务/门禁段，改为背景与历史；`architecture-decisions.md` 改为 G0 已冻结、ADR 共 7 份；`environment.md` 增加状态指针、commit 数改为动态；`references.md` 增加状态指针与 G0 PASS 引用；`MEMORY_GUIDE.md` 与两个 Skill 的读/写顺序同步为 AGENTS §0/§7。
- 原因：用户明令执行 P0 冻结与对账；在两次提交授权内固定 P1–P6 伪代码基线、修正状态漂移并补齐索引。
- 验证：
  - `git show --numstat HEAD`：83 文件 / 39,146 行。
  - `state_sync.py validate|render|check`：均 exit 0（任务 8，门禁 PASS=1/8，阻塞 3）。
  - `scripts/check_docs_drift.py`：ERROR=0，WARNING=0，exit 0。
- 影响/后续：
  - P7/P8 产物（M13/M14/M17/M18）未纳入本次提交，保持未跟踪；P2–P6 仍需逐阶段验收。
  - `last_verified_commit` 指向 `1c9a104`；第二次提交后 HEAD 前移，`check_docs_drift` 会提示该字段与 HEAD 不一致（WARNING，exit 0），属预期。
- 相关文件：`design/pseudocode/*`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/memory/environment.md`、`docs/MEMORY_GUIDE.md`、`docs/SESSION_HANDOFF.md`。
- 架构变化：无。仅伪代码规格、状态看板与文档治理；未改 `contracts/`、`researchflow/`、`docs/design/`、`docs/ADR/`。

### 2026-11-11 · P0 · API 幂等整改、full-access 测试与 P1–P10 阶段注册表

- 变更：
  - A：`researchflow/api/app.py` 分离内部 `_TaskRecord` 与公共 201 回执；同键同体首次/重放共用同一响应体；新增 `tests/test_api_idempotency.py` A–E；`GET` 结构与 422 顺序未改。
  - E：按用户授权执行一次受控 full-access 全量 pytest，`140 passed`、exit 0；测试前后 Git 状态一致，项目内未新增临时目录；`BLK-003` 仍 `OPEN`。
  - B：`docs/state/project_state.json` 新增 `pseudocode_stages`（P1–P10，独立状态枚举）；`scripts/state_sync.py` 增加校验/渲染/检查；P1 `ACCEPTED`，P2–P8 `IN_REVIEW`，P9/P10 `BLOCKED`。
  - C：`OQ-P1-03`、`OQ-P1-05` 标 `NEEDS_CONFIRMATION`；同步 `PHASE_RULES`、M01/M03、`STAGE_LOG`；未编造决议正文。
  - F：P9 六个 `.py` 为 2026-11-11 22:53:54–55 并发重写落盘，不是原始正文恢复；逐项登记 SHA256/行数/时间，P9 标 `BLOCKED`，未标 `ACCEPTED`。
  - G：P10/M19 仅登记 5 文件 / 2,138 行与依赖；未删除、未获开发授权。
  - I：README、DEVELOPMENT_WORKFLOW、SESSION_HANDOFF、AGENTS 版本元数据、PROJECT_OVERVIEW、ARCHITECTURE、G0_DECISION_LIST 历史横幅更新；冻结件未改。
  - D：仅提交 §12-2/§12-6/§12-7/§12-8 的 A/B 方案与影响，未写入正式决议。
- 原因：用户 2026-11-11 P0 整改授权 A–J；修复 WP-02 幂等验收缺口并建立唯一阶段状态源。
- 验证：
  - API 422 + A–E：`18 passed`，exit 0。
  - 受控 full-access 全量：`140 passed`，exit 0（B 之前）。
  - B 后定向回归（API 422 + A–E + state_sync）：`49 passed`，exit 0。
  - `validate_contracts.py --selftest`：`10/10 PASS`；`validate_contracts.py`：`72/72`，exit 0。
  - `state_sync.py validate|render|check`：均 exit 0，逐字节一致。
  - `check_docs_drift.py`：ERROR=0，WARNING=1（`last_verified_commit` 与 HEAD 不一致，预期），exit 0。
  - 状态一致性断言：52/52 PASS。
- 影响/后续：
  - P9 并发重写产物的来源/版本未确认；P10 未授权；§12-2/6/7/8 未裁决；WP-03 不得启动。
  - 未 commit；`last_verified_commit` 保持 `1c9a104`；未清理临时目录。
  - 报告：`reports/remediation/P0_CHANGELOG.md`、`P0_TEST_REPORT.md`、`P0_FINAL_ACCEPTANCE.md`、`P0_OPEN_ISSUES.md`、`P0_STATE_CONSISTENCY_REPORT.md`。
- 架构变化：无。未改冻结 API 契约、状态迁移规则、证据/验证/签名边界或 ADR；P9 未验收，不构成运行时实现声明。

### 2026-11-12 · 文档治理 · 记忆与状态词汇对账

- 变更：
  - 高优先级：把 `ADR-001` 的 `INVALIDATED` 传播到 `AGENTS.md` §6.2、`docs/MEMORY_GUIDE.md` §5.2、`docs/GLOSSARY.md`、`docs/ARCHITECTURE.md` §4.1/§4.2、`docs/DEVELOPMENT_WORKFLOW.md` §10.2；Node 统一为 10 个状态，补两条迁移与 I-09–I-14。
  - `docs/state/runtime_states.md` 按 G0 冻结的 05 §9–§10 重写：Task 9、Node 10、Evidence 5、Recovery（T1）、I-01–I-14；删除“详细契约尚未在 G0 冻结 / 等待 G0”的旧表述。
  - `docs/memory/architecture-decisions.md` §5 改为 Task/Node/Evidence/Recovery 分类；§7 区分已冻结与仍开放项，明确密钥/信任锚/`gates.yaml` 字段未冻结（`OQ-029`）。
  - `docs/memory/feedback-and-lessons.md`：FB-17/FB-25 标注为阶段 4/7 当时快照并补当前状态；FB-04/13/18/21 加“当时”限定；新增 L-12（并发重写设计件）与 L-13（文件存在不等于开发授权）；L-11 补 140 passed 与 `BLK-003` 仍 OPEN。
  - `docs/memory/references.md`：修正 R-01“版本生效性待确认”；R-23 改为历史；新增 R-24–R-27（WP-01/WP-02/P0/伪代码注册表）。
  - `docs/memory/project-context.md`：§7 历史补到阶段 8/G0/T0/P0；Context7 配置大小更新；§8 增加 2D 待确认。
  - `docs/memory/environment.md`：Context7 配置更新为 3,616 字节 / `F6AE…CD46`；`tmpavet2qv9` 已不存在；补 140 passed 与 `BLK-003` 仍 OPEN；Docker 表述改为整机已装、项目未使用；API Key/LLM 表述加“未复核/项目范围”限定。
  - `docs/memory/Memory.md`：runtime_states 指向 05 §9–§10；补 P1–P10 注册表与 P0 报告索引。
  - `docs/state/G0_DECISION_LIST.md`：去掉“G0 `NOT_STARTED`”残留；R-2 的 2D 改为“G0 已通过但未见书面接受”；`tmpavet2qv9` 更新为已不存在。
  - `docs/reference/CONFLICT_REPORT.md`：方案 D 标为历史默认；业务代码现状更新。
  - `docs/SECURITY_POLICY.md` §11：把“G0 必须冻结的安全项”改为“G0 未覆盖、仍需裁决”，避免与 G0 通过冲突。
- 原因：用户 2026-11-12 要求全面审计过时记忆并直接修复；审计发现 `ADR-001` 未传播、`runtime_states` 停留在 G0 前、`architecture-decisions` §7 过冻结、FB/环境/索引状态滞后。
- 验证：
  - `& .venv/Scripts/python.exe scripts/state_sync.py validate|render|check`：均 exit 0；生成文件逐字节一致。
  - `& .venv/Scripts/python.exe scripts/check_docs_drift.py`：ERROR=0，WARNING=1（`last_verified_commit` 与 HEAD 不一致，已知），exit 0。
  - 本地 Markdown 链接检查：15 个核心改动文档，`MISSING_LINKS=0`。
  - `git diff --check`：exit 0。
  - 未运行 pytest/unittest；本次只改文档，未触碰代码、契约、schema 或测试。
- 影响/后续：
  - 无运行时/契约/状态机代码变更；`project_state.json` 的任务、门禁、阻塞与 `last_verified_commit` 未改。
  - 2D 仍未见书面接受记录；P9/P10 仍 `BLOCKED`；`BLK-003` 仍 `OPEN`。
  - 未 commit；等待用户审阅与提交决定。
- 相关文件：`AGENTS.md`、`docs/MEMORY_GUIDE.md`、`docs/GLOSSARY.md`、`docs/ARCHITECTURE.md`、`docs/DEVELOPMENT_WORKFLOW.md`、`docs/SECURITY_POLICY.md`、`docs/state/runtime_states.md`、`docs/state/G0_DECISION_LIST.md`、`docs/reference/CONFLICT_REPORT.md`、`docs/memory/*`。
- 架构变化：无。对齐已冻结的 `ADR-001` 与 05 §9–§10，不新增或修改架构决策。


### 2026-11-12 · 伪代码 P2–P8 设计件验收 · WP-03 方案与提示词（执行完成，未 commit）

- 变更：
  - 按用户 2026-11-12 指令（C→B 顺序）完成 P2–P8 设计件验收审查：91 文件 / 51,402 行；14 个模块的 `MODULE.md`、`NEGATIVE_TESTS.md` 齐全；文件数/行数与 `INDEX.md`、`STAGE_LOG.md` 一致；每模块 ≥36 条负例标识；全部 `.py` 通过 `ast.parse`；>800 行文件已登记函数索引。审查报告：`reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`。
  - `docs/state/project_state.json`：P2–P8 状态由 `IN_REVIEW` 改为 `ACCEPTED`（仅设计件验收）；补 `acceptance_basis` 与验收证据路径；`T-PSEUDO-001` 验收标准同步为 P1–P8 ACCEPTED；top-level `updated_at` 更新。
  - `design/pseudocode/STAGE_LOG.md`：P2–P8 验收状态改为“已验收（2026-11-12；设计件）”，补验收依据；P9/P10 保持原状态。`INDEX.md` 与 M04–M18 的模块头状态引用同步为“设计件已验收；实现未开始”。
  - `README.md`、`docs/ARCHITECTURE.md`、`docs/DEVELOPMENT_WORKFLOW.md`、`docs/PROJECT_OVERVIEW.md`、`docs/memory/project-context.md`：同步为 P1–P8 设计件 ACCEPTED、P9/P10 BLOCKED；`DEVELOPMENT_WORKFLOW` §11.3 标题改为“部分满足”并注明第 2 条仅完成设计件验收。
  - 新增 `docs/plans/WP-03_IMPLEMENTATION_PLAN.md`（草案，未获实施批准）与 `docs/plans/WP-03_IMPLEMENTATION_PROMPT.md`（下一阶段实施提示词）。
  - 新增 `reports/pseudocode/` 下 3 份只读审计日志：`p2_p8_inventory.log`、`p2_p8_doc_summary.log`、`p2_p8_large_files.log`。
- 原因：用户 2026-11-12 指令按 C（逐阶段验收 P2–P8）→ B（WP-03 方案）顺序推进；先完成设计件验收，再出方案与提示词。
- 验证：
  - `& .venv/Scripts/python.exe scripts/state_sync.py validate` → exit 0；伪代码阶段 ACCEPTED 8 / BLOCKED 2。
  - `& .venv/Scripts/python.exe scripts/state_sync.py render` → 生成 2 文件；`check` → exit 0，逐字节一致（`PROJECT_STATE.md` SHA256 `20835f51…`，`IMPLEMENTATION_STATUS.md` SHA256 `72f499dc…`）。
  - `& .venv/Scripts/python.exe scripts/check_docs_drift.py` → ERROR=0、WARNING=1（`last_verified_commit` 与 HEAD 不一致，已知）。
  - 尝试 `& .venv/Scripts/python.exe -m pytest tests/test_state_sync.py -q -p no:cacheprovider`：31 failed / 28 errors，全部在 setUp/临时目录创建阶段出现 `PermissionError [WinError 5]`（或由此派生的 `FileNotFoundError`），未见断言失败；属 `BLK-003` workspace-write 环境阻塞，未据此关闭阻塞，也未修改测试。
  - 本次只改设计验收状态、文档与计划，未改业务代码、契约、schema 或测试。
- 影响/后续：
  - P2–P8 设计件已验收；`ACCEPTED` 不表示运行时实现、测试通过或门禁 PASS。
  - WP-03 仍未满足 `DEVELOPMENT_WORKFLOW` §11.3 第 3/4/6 条：`§12-2`/`§12-6`/`§12-7`/`§12-8` 未裁决、P9/P10 未处置、未下达 WP-03 指令。
  - `BLK-003` 仍 OPEN；`last_verified_commit` 仍 `1c9a104`；未 commit。
- 架构变化：无。仅设计阶段验收与计划文档；未改冻结契约/架构/ADR，未写业务代码。
- 相关文件：`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`design/pseudocode/{STAGE_LOG.md,INDEX.md}`、`design/pseudocode/M04_dag/MODULE.md` 至 `M18_knowledge/MODULE.md`、`reports/pseudocode/*`、`docs/plans/*`、`README.md`、`docs/{ARCHITECTURE.md,DEVELOPMENT_WORKFLOW.md,PROJECT_OVERVIEW.md}`、`docs/memory/project-context.md`。

### 2026-11-12 · T0 WP-03 · SQLite 迁移、StateMachine 与双事务审计（执行完成，待验收，未 commit）

- 变更：
  - 新增 `researchflow/persistence/`：连接/事务助手、7 表 DDL 与触发器、只向前迁移执行器、Task/Node/Evidence/Audit/Idempotency 仓储、幂等键校验。
  - 新增 `researchflow/orchestration/`：Task 9 / Node 10 迁移表、`StateMachine.transition()`、`create_initial()`、守卫、事实端口、内容寻址计划读取、最小不变量。
  - 新增 `researchflow/contracts/encoding.py`（RFC 8785 JCS）与 `researchflow/contracts/errors.py`（13 个冻结 API 错误码）。
  - `researchflow/api/app.py` 从 `_EphemeralTaskRegistry` 切换到 SQLite 创建服务；保留 201/409/422/404 与 `/recover` 404；`GET /tasks/{id}` 保留 `spec`。
  - 7 表：`tasks`、`nodes`、`evidence`、`evidence_invalidations`、`audit_log`、`idempotency_keys`、`schema_migrations`；`tasks.task_spec_json` 与 `idempotency_keys.task_id NOT NULL + FK` 按 `00_decisions.md` 记录为已批准偏离。
  - 新增 WP-03 定向测试、全量回归、证据脚本；`docs/state/project_state.json` 新增 `T-WP-03-001`（`IN_REVIEW`）。
- 原因：用户 2026-11-12 确认 16 项裁决（“按你的建议来吧”），批准 9A 范围与 Step 1 计划；实现 T0 WP-03 最小持久层与状态机唯一写入口。
- 验证：
  - 定向：`87 passed`，exit 0；日志 `docs/verification/t0/wp-03/pytest_targeted.log`。
  - 全量：`217 passed`，exit 0；日志 `docs/verification/t0/wp-03/pytest_full.log`。该全量结果来自 `danger-full-access` 补充运行；workspace-write 下 `BLK-003` 仍在 pytest `tmp_path` setup 阶段失败，未写成 workspace-write 通过。
  - 证据脚本：`make_evidence.py` exit 0；生成 `transitions.jsonl`、`illegal.log`、`direct_write.log`、`audit_log.jsonl`、`denied_survives_rollback.log`、`audit_degraded_stderr.log`、`invalidated_guard.log`。
  - `state_sync.py validate|render|check`：均 exit 0；生成文件逐字节一致。
  - `BLK-003` 仍 OPEN；`last_verified_commit` 未改；未 commit。
- 影响/后续：
  - `T-WP-03-001` 置 `IN_REVIEW`，等待用户验收；未标 DONE。
  - 全量测试为 full-access 补充结果；workspace-write 阻塞仍如实保留。
  - 未修改冻结契约/设计/ADR/PRD/G0；未把 P9/P10 当输入。
- 架构变化：无新增架构决策；按 05/06/07/ADR-001/004/005 与已批准裁决落地；两项 DDL 偏离已记录。
- 相关文件：`researchflow/persistence/*`、`researchflow/orchestration/*`、`researchflow/contracts/{encoding,errors}.py`、`researchflow/api/app.py`、`tests/wp03_support.py`、`tests/test_{jcs,persistence_migrations,state_machine,audit_dual_transaction,direct_write_guard,invalidated_guard,idempotency_sqlite,api_sqlite}.py`、`tests/test_api_{422,idempotency}.py`、`docs/verification/t0/wp-03/*`、`docs/state/project_state.json`、`docs/{PROJECT_STATE.md,IMPLEMENTATION_STATUS.md,CHANGELOG_DEV.md,SESSION_HANDOFF.md}`。

### 2026-11-14 · 三阶段 DeepSeek Harness Goal 任务书（文档交付，未 commit）

- 新增 `docs/goals/GOAL_01_CORE_BACKEND.md`、`GOAL_02_COMPETITIVE_PRODUCT.md`、`GOAL_03_COMPETITION.md`：按 T0 后端可信闭环→T1 赛道竞争力→T2 差异化/竞赛交付递进。结合用户两张开发方法图，落实统一契约/命名、伪代码、分批实现、A/B/C 审查与状态/记忆交接。
- 依据现有代码/状态续建，明确 WP-03 待验收、历史 full-access 测试、BLK-003 与 P9/P10 阻塞；不重做 WP-01/02，不把设计件或测试事实端口当生产闭环。
- 只读核实 Harness 安装包 runtime 已为 `0.2.2-rc.3`，按实际 Goal 工具、自动轮数、恢复/暂停/阻塞语义编写；说明提示词/轮数不提供金额硬限额。
- 纳入用户赛道一通知图：初赛作品截止 11-20、决赛作品截止 12-06；完整官网章程仍未取得，不虚构评分/格式/奖项认定。模型按用户指定阿里云 DeepSeek V4.1 Flash；开发 API 200 元与产品运行/调试 50 元跨阶段分别累计。
- 三路只读审查修正：明确重启/非回环拒绝测试、WP 依赖；盲测正式运行前不暴露细节、污染后转开发集；开发费用与产品费用分别停止，模型操作本地文件仍耗开发费用；有限试点协议避免无界等待。
- 验证：项目 `.venv` CPython 3.11.16/64bit；文档 UTF-8/围栏/本地引用/来源 hash 校验 exit 0，记录 `docs/goals/verification/document_validation.json`；`state_sync.py validate/render/check` 均 exit 0（2026-11-14 18:04，约 0.21/0.20/0.17 秒），日志 `state_sync.log`；`check_docs_drift.py` exit 0、ERROR=0/WARNING=1（约 0.25 秒），日志 `docs_drift.log`。首次受限环境 Git 子进程失败后，获准只读沙箱外复核；该复核不证明 BLK-003 已解决。
- `T-GOALS-001` DONE 仅表示文档交付。当前阶段、既有任务、门禁、伪代码状态、阻塞和 last_verified_commit 保持原值；生成视图由脚本同步。
- 未运行产品 pytest、未改业务代码/冻结契约、未安装插件/依赖、未改 DSH 配置、未调用收费 API、未提交赛事或 Git commit。
- **无架构变化**：新增阶段任务书、事实/来源核对和文档交付登记；未来架构/契约实施仍需具体方案及批准。
- 相关文件：`docs/goals/`、`docs/state/project_state.json`、生成状态视图、CHANGELOG、SESSION_HANDOFF、Memory 索引与环境核验补记。

### 2026-11-14 · T0 · 后端可信闭环、最小工作台、三次离线端到端与独立验签

- 变更：
  - 迁移 0002/0003（只向前）：新增 `graph_versions/reports/certificates/ingestion_log`；重建 `audit_log` 扩展动作并保留历史行、索引与四个状态守卫触发器。0001 语句与 checksum 未改。
  - 新增 T0 产品模块：`researchflow/dag`、`templates`（内置合成数据 CC0-1.0 + 注册表 + Split Manifest）、`execution`（受控子进程、进程树超时回收、进程树内存采样）、`evidence`（Collector/链/内容寻址载荷）、`gate` + `rules/ruleset.v1.json`、`verification`（L1/L2/L3 + 报告/凭证签发）、`signing`（Ed25519/JCS 白名单/Merkle/信任锚）、`bundle`、`recovery`、`pipeline`、`server`、`cli`、`workbench`；根 `verify_bundle.py` 独立离线验签。
  - API 增加 `GET /graph`、`GET /evidence`、`POST /verify`、`GET /report`、`GET /certificate`；`POST /recover` 仍 404；启动守卫拒绝非回环且无 token；报告/凭证响应带 `stale`。
  - 新增 T0 测试 `tests/t0/*`（契约、DAG、模板、执行、Collector、Gate、L1/L2/L3、签名、Bundle、恢复、工作台、API、管线）与 `scripts/e2e_run.py`、`scripts/measure_concurrency.py`、`scripts/build_template_dataset.py`。
  - 独立只读审查（2026-11-14）：发现并修复 A 类“内存只采样 venv 启动器”问题（改为进程树采样 + 200 MB 真实分配校准 + 真实内存上限终止），并加固 E3 绑定、规则等级下限、verify 幂等、`attempt_end` 严格性、证书时间顺序等 B 类项；旧 e2e 证据归档在 `docs/verification/t0/e2e/superseded_2026-11-14_pre_memfix/`，不删除。
  - `docs/state/project_state.json`：WP-03 转 `DONE`；新增 T-WP-04…14 与 T-WP-R 共 12 个任务并转 `DONE`；G1/G2/G3 `PASS`（实施会话 + 独立审查证据复核），G6 `IN_PROGRESS`（仅 G6-T0 满足，完整 G6 属 T1）。
- 原因：按 GOAL_01 完成 T0 可信闭环：真实执行、受控证据、独立验证、条件签发、离线验签；保留已通过的 WP-01/02/03 契约与实现。
- 验证（解释器 `.venv/Scripts/python.exe`，3.11.16/64bit；会话 `danger-full-access`）：
  - 定向各 WP：wp-04 15、wp-05 15、wp-06 10、wp-07 9、wp-08 14、wp-09 11、wp-10 8、wp-11 9、wp-12 11、wp-13 3、wp-r 6、pipeline 5，全部 exit 0；日志在 `docs/verification/t0/wp-*/pytest.log` 与 `docs/verification/t0/pipeline_tests.log`。
  - 全量：`& .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider` → **339 passed**，exit 0，312.44 s；日志 `docs/verification/t0/full_suite_2026-11-14_final.log`。
  - 三次 e2e：`python scripts/e2e_run.py --runs 3 --out docs/verification/t0/e2e` → 三次 COMPLETED/VERIFIED，必检 8/8、L3 覆盖 1.0、32 条证据（16 条失效）、63 个 Bundle 文件、独立验签 exit 0，`consistent=true`；报告 `docs/verification/t0/e2e/e2e_report.md`。
  - 并发/内存：`python scripts/measure_concurrency.py` → 观测并发 2、重叠 2.323 s、两 worker 峰值 165.004/166.586 MB；主机 16,117 MB。
  - G6-T0：`docs/verification/t0/g6-t0/`（包外信任锚、隔离目录、三次真包通过；`verify_bundle.py` SHA256 `595f2fae…b3e18`）。
  - 契约：`validate_contracts.py --selftest` 10/10 PASS；`validate_contracts.py` 72/72 exit 0；`state_sync.py validate|render|check` 均 exit 0；`check_docs_drift.py` ERROR=0、WARNING=1（`last_verified_commit` 与 HEAD 不一致，已知）。
- 影响/后续：
  - 冻结件未改（`contracts/`、`docs/design/`、`docs/ADR/`、`design/pseudocode/`）；实现层偏离与已接受风险见 `docs/verification/t0/00_implementation_decisions.md`，独立审查见 `docs/verification/t0/review_2026-11-14.md`。
  - `BLK-003` 仍 `OPEN`；全部结果不写成 workspace-write 通过。工作台截图未提供（AppTest 替代并披露）。断网为“代码无外呼 + 代理黑洞 + 无模型客户端”，非物理断网。
  - 完整 G6、G4、G5、G7 属 T1/T2，未启动；`POST /recover` 仍 404；T0 无 LLM/DC/SPA/完整 Recovery 状态机。
  - 未 commit；`last_verified_commit` 仍为 `1c9a10461c50c02058ce28be8b4b09c0c8870e80`（未用 HEAD 冒充）。
- 相关文件：`researchflow/**`、`tests/t0/**`、`scripts/{e2e_run,measure_concurrency,build_template_dataset}.py`、`verify_bundle.py`、`researchflow/rules/ruleset.v1.json`、`docs/plans/goal-01-plan.md`、`docs/verification/t0/**`、`docs/verification/budget/BUDGET_LEDGER.md`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`。


## 2026-11-14 · Goal 自动记忆与交接收尾规则

- 用户要求：Harness 每批及结束前主动更新项目记忆与交接，无需再次提醒。
- 变更：新增 `docs/goals/MEMORY_CLOSEOUT.md`；三份 Goal 的启动入口和完成清单均引用。要求稳定记忆与研发进度分离、无新事实时说明无需修改、每包检查点、真实验证和批准来源/累计预算交接、收尾失败不 complete；明确崩溃和用户立即停止时的边界。
- 状态：仅新增文档任务 `T-GOALS-002`；未变更既有业务任务、门禁、阶段、预算余额或 `last_verified_commit`。
- 验证：四份 Markdown UTF-8/代码围栏/本地链接/收尾引用检查通过；`state_sync.py validate/render/check` 均 exit 0。记忆前置漂移检查 ERROR=0/WARNING=1（已知 last_verified_commit 与 HEAD 差异）；收尾完整结果见 `docs/goals/verification/memory_closeout_20261114/`。只改文档，不运行产品测试。
- 无架构变化：本次仅强化已有记忆、状态及交接流程，不改变产品契约、状态机、权限边界或实现。
- 记忆：在 `feedback-and-lessons.md` 登记自动同步偏好，Memory 索引指向收尾规则；未把待修复项写成已完成。
- 交接：最新记录置顶，并指向 `reports/t0_review_20261114/REVIEW.md` 的三项 T0 收口要求。当前仅确认收口任务已发出，未核实修复验收完成。
- Git：main，HEAD `309083e715cb59a1f0c181d95df44e1946ffbaa5`，本次未 commit/push；保留既有工作区差异。

### 2026-11-15 · T0 · A-01/A-02 修复、WP-13 材料补齐与三次 e2e 重跑（未 commit）

- 变更：
  - A-01 参数完整性：`VerificationContext.parameter_binding()` 对当前 attempt 交叉核对 NodeSpec、`job.json`、`result.json` 与 E2 `executor_launch` 的 `parameters_hash`；L1 新增 `L1_PARAMETERS_BINDING_MISMATCH/INCOMPLETE`；L3 在创建目录/子进程前 preflight split 与全部 metric 节点，失败返回 `coverage=0`、`nodes=()`、`verification_root=""`，原因码 `L3_PARAMETERS_BINDING_MISMATCH/INCOMPLETE`。未改 contracts/Schema/迁移/Gate/状态边。
  - A-02 恢复安全：`RecoveryService.invalidate()` 与 `rerun()` 在状态迁移、计划写入或执行前运行只读 L1；坏链或缺失 attempt 结果以 `RECOVERY_NOT_SAFE` + 具体 `L1_*` 原因拒绝。新增真实 `taskkill /T` 中断/新进程重读测试、坏链/缺失证据恢复拒绝测试；未实现 T1 Recovery、未新增状态边、`/recover` 仍 404。
  - A-03 材料：WP-13 支持 `?view=` 初始标签页、`?task_id=` 预填与 `RESEARCHFLOW_API_TIMEOUT`；新增 CDP 截图脚本、四视图 + API 不可达截图、DOM 快照、`walkthrough.md`、`ADR-007_DECISION_PROPOSAL.md`；新增失效证据 STALE 的 AppTest。ADR-007 仍 `PROPOSED`，正式裁决待用户。
  - 证据：`docs/verification/t0/a-01/`、`a-02/`、`wp-13/`；修复前 e2e 整体归档到 `docs/verification/t0/e2e/superseded_2026-11-15_pre_a01/`（未删除、未改写），新 e2e 写入 `docs/verification/t0/e2e/`；新离线验签日志在 `docs/verification/t0/g6-t0/2026-11-15/`。
  - 状态：新增 `T-A01-001`、`T-A02-001`（DONE）与 `T-A03-001`（IN_REVIEW，ADR 裁决待用户），新增 `BLK-004` OPEN；G1/G2/G3/G6 补新证据，G6 仍 `IN_PROGRESS`；`last_verified_commit` 未改。
- 原因：复核报告 A-01/A-02/A-03 要求先修复真实负例缺口并补齐 WP-13 冻结交付，再谈 T0 验收；旧 e2e 不能证明修复后代码。
- 验证（解释器 `D:\ResearchFlow-project\.venv\Scripts\python.exe`，3.11.16/64bit；会话 `danger-full-access`）：
  - `pytest tests/t0/test_wp09_verifier_l12.py tests/t0/test_wp10_verifier_l3.py` → **26 passed**，126.91 s，exit 0；日志 `docs/verification/t0/a-01/pytest_targeted.log`。
  - `docs/verification/t0/a-01/parameter_binding_probe.py` → exit 0，`verdict=PASS`；pre-fix 模拟 L1/L3 均 PASS，post-fix L1/L3 均 FAIL 且 L3 无目录/子进程；`probe_report.json`。
  - `pytest tests/t0/test_wp_restart_safety.py` → **4 passed**，31.24 s；`pytest tests/t0/test_wp_recovery.py tests/t0/test_wp_api.py` → **11 passed**，65.28 s；日志 `a-02/`。
  - `docs/verification/t0/a-02/recovery_chain_probe.py` → exit 0，`verdict=PASS`；坏链/缺失结果 invalidate 与坏链 rerun 均 `RECOVERY_NOT_SAFE`，状态/计划未变。
  - `pytest tests/t0/test_wp13_workbench.py` → **4 passed**，23.50 s（含 stale 视图）；`wp-13/capture_screenshots.py` → exit 0，`verdict=PASS`，四视图 + API 不可达 + DOM。
  - 全量 `pytest tests -q -p no:cacheprovider` → **351 passed**，395.66 s，exit 0；日志 `docs/verification/t0/full_suite_2026-11-15.log`。
  - 三次 e2e `python scripts/e2e_run.py --runs 3 --out docs/verification/t0/e2e` → `consistent=true`，三次 COMPLETED/VERIFIED、32 证据/16 失效、必检 8/8、L3 1.0；`e2e/runs_summary.json`、`e2e_report.md`。
  - 仓库 `verify_bundle.py -E` + 包外 `trust_store.json` 对 run_1..3 → 三次 `VERIFIED`，exit 0；日志 `g6-t0/2026-11-15/`。
  - `validate_contracts.py --selftest` 10/10；`validate_contracts.py` 72/72 exit 0；`state_sync.py validate/render/check` 均 exit 0；`check_docs_drift.py` ERROR=0/WARNING=1（last_verified_commit 与 HEAD 不一致，已知）。
- 影响/后续：
  - 无契约/Schema/迁移/状态边变化；ADR-007 未批准、未扩分页/下载/失效原因；T0 不宣布全部完成，ADR-007 裁决与 T0 验收/commit 仍待用户。
  - `BLK-003` 仍 OPEN；`BLK-004`（ADR-007 正式裁决）OPEN；完整 G6/G4/G5/G7 属 T1/T2，未启动。
- 相关文件：`researchflow/verification/{context,l1,l3}.py`、`researchflow/recovery/service.py`、`researchflow/workbench/app.py`、`tests/t0/{test_wp09_verifier_l12,test_wp10_verifier_l3,test_wp_restart_safety,test_wp13_workbench,support,restart_probe}.py`、`docs/verification/t0/{a-01,a-02,wp-13}/**`、`docs/plans/A-01_PARAMETER_BINDING_PLAN.md`、`docs/verification/t0/e2e/**`、`docs/verification/t0/g6-t0/2026-11-15/**`、`docs/state/project_state.json`、生成状态文档、本 CHANGELOG、`docs/SESSION_HANDOFF.md`。

### 2026-11-15 · T0 · ADR-007 正式批准

- 变更：用户在当前 DSH 会话的裁决问答中选择“批准建议（推荐）”；`ADR-007` 由 `PROPOSED` 改为 `ACCEPTED`。三个边界：①独立只读 Streamlit 进程、只发 GET；②四视图只读，证据固定 `limit=200` 单页、无分页/报告下载；③展示 `STALE` 与失效计数、不展示失效原因（需另立 REST 契约方案）。新增 `docs/verification/t0/wp-13/ADR-007_DECISION.md`，更新 ADR 文件/索引/D-34、`T-A03-001`（DONE）、`BLK-004`（RESOLVED）与生成状态文档。
- 原因：A-03 的正式裁决来源缺失；材料补齐后由用户明确裁决，避免把待选项静默视为已批准。
- 验证：`state_sync.py validate/render/check` 均 exit 0；ADR 文件、索引与 D-34 状态一致；G0 ⑧ 冻结正文未改写，差异在 ADR 索引登记。
- 影响/后续：T0 四视图范围已锁定；分页、下载、失效原因展示仍不在范围。T0 验收、commit 与是否进入 T1 仍由用户决定；未 commit、未推送。
- 相关文件：`docs/ADR/ADR-007-t0-workbench-scope.md`、`docs/ADR/README.md`、`docs/verification/t0/wp-13/{ADR-007_DECISION,ADR-007_DECISION_PROPOSAL,walkthrough}.md`、`docs/verification/t0/00_implementation_decisions.md`、`docs/state/project_state.json`、生成状态文档。

### 2026-11-15 · T0 · 用户验收通过（暂不 commit）

- 用户在当前 DSH 会话中明确选择“**验收 T0，暂不 commit**”。T0 阶段验收通过；新增 `docs/verification/t0/T0_ACCEPTANCE.md` 与状态任务 `T-T0-ACCEPT-001`（DONE）。
- 验收依据：A-01/A-02/A-03 收口；全量 351 passed（395.66 s）；三次新 e2e `consistent=true`（32 证据/16 失效/必检 8/8/L3 1.0）；三次离线验签 `VERIFIED`；契约 10/10、72/72；state_sync 三步 exit 0。
- 边界：验收不表示 commit/推送已授权、不表示完整 G6（T1）通过、不表示 T1 启动；`BLK-003` 仍 OPEN，B 类入口/验签补强与预算余额未核实均如实披露。
- 下一步：commit 作为单独事项（先核对 Git 身份、文件清单、忽略规则、历史未验收产物）；T1、GitHub 目标/可见性/推送范围与预算由用户另行决定。
- 相关文件：`docs/verification/t0/T0_ACCEPTANCE.md`、`docs/verification/t0/review_2026-11-15.md`、`docs/state/project_state.json`、生成状态文档、`docs/CHANGELOG_DEV.md`、`docs/SESSION_HANDOFF.md`。

### 2026-11-15 · 安全 · 忽略运行私钥文件

- 变更：`.gitignore` 增加 `*.private.json`；`git check-ignore -v` 确认 `docs/verification/t0/e2e/run_1/runtime/keys/rf-t0-ed25519-01.private.json` 被忽略。
- 原因：三次 e2e 的 runtime 目录含测试私钥，当前工作区未 commit；即使未来提交，也不得把运行私钥纳入版本库。公开密钥 `*.public.json` 不忽略。
- 验证：`git check-ignore -v` 输出命中 `.gitignore:15:*.private.json`；未修改已有私钥文件，未删除 e2e 证据。
- 影响：仅忽略规则；无业务代码、契约、Schema 或运行状态变化。

### 2026-11-15 · T0 · GitHub 提交审核与 Harness 交接

- 用户已将此前“暂不 commit”调整为提交并推送已验收 T0，随后指定由 DeepSeek Harness 执行；Codex 负责核心审核、方案判断与部分难点开发。准确仓库为 `https://github.com/linhao3170/-Research_Flow`，保留前导连字符；远端可见性、空仓库状态及权限待 Harness 核实。
- 预算台账追加本次开发 API 消耗 **15.00 元（用户确认）**，更正同批未知记录且不重复累计；此前批次消耗与总余额仍未核实，不推算剩余 185 元。
- 提交范围审核与执行步骤写入 `docs/verification/publication/2026-11-15/PUBLISH_HANDOFF.md`。`.gitignore` 增量排除 e2e runtime 数据库、临时目录、内部裁剪图和候选 NUL 文件；未删除文件。公开 Bundle、信任锚及验收证据保留。
- P9/P10 仅作为仍为 BLOCKED 的历史草稿保存，以满足登记目录完整性；不代表设计验收或实施授权，不执行、不改状态。
- 工作区候选路径/典型秘密格式扫描结果见同目录 `working_audit.json`；扫描不回显秘密值，不等同于最终 staged 或历史无秘密证明。最终暂存内容由 Harness 重新审核。
- 状态任务 `T-PUBLISH-PREP-001` 记录审核交接 DONE；`state_sync.py validate/render/check` 均 exit 0。历史全量 351 passed、三次 e2e 和离线验签仅核对材料，本轮未重跑。会话开始文档漂移检查 ERROR=0/WARNING=1；收尾未重跑漂移检查，不宣称最终文档检查通过。
- 本轮浏览器连接与部分提权请求因自动审批服务 404（代理不支持 `codex-auto-review`）未执行；未修改审批或系统配置。候选扫描后改用直接 Git 导出与受限文件读取，不绕过审批。
- 自动更新 SESSION_HANDOFF 与长期分工偏好 FB-30。**无架构变化**：仅预算、发布准备和文档治理；未修改业务实现、冻结契约或门禁，未变更 `last_verified_commit`。
- Codex 未暂存、未 commit、未添加或修改 remote、未 push；T1 未启动。后续由 Harness 按提交交接执行真实提交、推送及自动记忆收尾。

### 2026-11-15 · T0 · 首次普通提交与推送（Harness 执行，提交时记录）

- 变更：
  - 核对并新增 `origin` = `https://github.com/linhao3170/-Research_Flow.git`（前导连字符保留）：`git ls-remote --heads origin` exit 0、0 个 ref；GitHub API 返回 `private=false`、`size=0`、`default_branch=main`，即**公开空仓库**，与此前“按私有仓库预期”不符。已在 `PUBLISH_HANDOFF.md` 报告差异，未修改仓库可见性。
  - 按重新生成的候选清单逐路径暂存 T0 验收成果，不使用无清单 `git add .`；最终索引扫描 `staged_audit.json` 与 7 个历史提交扫描均 0 findings；未暂存私钥、凭据或本地运行数据库。
  - `.gitattributes` 将 `docs/verification/t0/e2e/**` 与 `docs/verification/t0/g6-t0/**` 标为 `-text`，按原始字节入库。原因：e2e Bundle 的 `manifest.json` 记录文件原始字节的 SHA-256；提交前实测 run_1 Bundle 34/65 个文件被 CRLF→LF 归一化，新克隆中离线验签会失败；修正后 1427 个证据文件工作区与索引逐字节一致。
  - 新增 `T-PUBLISH-001`（提交时 `IN_PROGRESS`）；`docs/verification/publication/2026-11-15/` 保存提交前检查日志。
- 原因：用户授权把已验收 T0 普通提交并推送到指定仓库，要求真实执行、证据完整、排除敏感内容且不改验收标准。
- 验证：
  - `validate_contracts.py --selftest` → 10/10；`validate_contracts.py` → 72/72，exit 0。
  - `state_sync.py validate` / `render` / `check` → 均 exit 0，两条生成文件逐字节一致；`check_docs_drift.py` → ERROR=0、WARNING=1（`last_verified_commit` 与 HEAD 不同，已知）。
  - 索引/历史秘密扫描 0 findings；证据文件字节一致性 1427/1427。
  - 历史全量 351 passed（395.66 s）为既有证据，本次未重跑，不写成本轮通过；`last_verified_commit` 保持 `1c9a10461c50c02058ce28be8b4b09c0c8870e80`。
- 影响/后续：仓库实际公开，若需私有须由用户在 GitHub 侧调整；P9/P10 仍为 `BLOCKED` 草稿，不构成验收或开发批准；T1 未启动。推送结果、远端 SHA 与干净快照验证见后续收尾条目。
- 相关文件：`.gitattributes`、`.gitignore`、`docs/state/project_state.json`、`docs/verification/publication/2026-11-15/**`、`docs/verification/budget/BUDGET_LEDGER.md`、`docs/SESSION_HANDOFF.md`。
- **无架构变化**：仅发布准备、忽略/换行规则、状态与文档治理；未改业务实现、冻结契约、Schema、迁移、状态边或门禁。

### 2026-11-15 · T0 · 首次提交已推送并通过远端干净快照验证

- 结果：内容提交 `35ab02bfe3d54799acb40e9a2ff632661d853111`（1783 files，+204801/−366）于 2026-11-15T11:27:17+08:00 创建并普通推送至 `origin/main`；本地 HEAD、`git ls-remote origin refs/heads/main` 与 GitHub API `commits/main` 三方 SHA 一致。作者 `ResearchFlow Dev <dev@researchflow.local>`，全局身份仍为空。
- 干净快照：在 `runtime/clean-verify-20261115` 从远端克隆（14.34 MB，HEAD 同为 `35ab02b`）；`state_sync.py validate` / `check` exit 0（`PROJECT_STATE.md` SHA256 `54ce63d1…`、`IMPLEMENTATION_STATUS.md` `c7b8d16f…` 逐字节一致）；`validate_contracts.py` 72/72 exit 0；`verify_bundle.py -E` 对 run_1..3 三次 `VERIFIED`、exit 0、`trust_anchor_source=external`、32 证据/必检 8/8/L3 1.0。该结果同时验证了 `-text` 字节入库修复：若按文本归一化，包内 manifest 哈希与新克隆字节不一致。
- 可见性：GitHub API `private=false`、`visibility=public`、`default_branch=main`；从空仓库首推，页面 SHA 与本地一致。该事实与“按私有仓库预期核对”不符，已在交接明示，未修改仓库可见性设置。
- 并行写入：收尾期间发现未跟踪文件 `docs/goals/GOAL_02_EXECUTION_GUIDE.md`（11:22 由其他会话创建，内容涉及 Goal 2/T1 启动）。本轮未暂存、未修改、未提交该文件，也不据此启动 T1；提交前核查跟踪文件的工作区改动为 0。
- 预算：本轮无新增用户确认的开发消耗；15.00 元仍为同一批一次性记录，不重复累计，不推算余额。
- 状态：`T-PUBLISH-001` 转 `DONE`；`last_verified_commit` 仍为 `1c9a10461c50c02058ce28be8b4b09c0c8870e80`（未用 HEAD 冒充；351 项全量未在提交快照上重跑），`check_docs_drift.py` 因此仍为 ERROR=0/WARNING=1（已知）。
- 影响/后续：`BLK-003` 仍 OPEN；G6 仍 `IN_PROGRESS`（仅 G6-T0 满足）；G4/G5/G7 未启动；T1 未启动。公开仓库如需转私有由用户在 GitHub 侧调整。
- 相关文件：`docs/verification/publication/2026-11-15/**`、`docs/state/project_state.json`、`docs/SESSION_HANDOFF.md`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`。
- **无架构变化**：仅发布、状态与文档治理；未改业务实现、冻结契约或门禁。
