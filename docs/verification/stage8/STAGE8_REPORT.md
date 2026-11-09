# 阶段 8 验收报告 — AI 研发工作站综合验收（初验 + 策略恢复后补验）

> 阶段：8 / AI 研发工作站综合验收
> 状态：**阶段 8 验收通过（用户 2026-11-08）；未进入阶段 9**
> 时间：2026-11-08 13:09–13:35（Asia/Shanghai）
> 执行人：DSH Agent（deepseek-flash）
> 结论：
> - 初验：22 PASS / 3 FAIL / 1 NOT VERIFIED。
> - 策略恢复后补验：第 5、6、23 项转 **PASS**；第 13 项拆分为 **13a PASS / 13b NOT VERIFIED**；第 20 项当时仍 **NOT VERIFIED**。
> - **2026-11-08 验收口径：25 PASS / 2 NOT VERIFIED / 0 FAIL（用户 2026-11-08 确认通过）。**
> - **2026-11-10 补测：第 20 项在基线 `91bde66` 上完成受控回滚，转 PASS（基线建立后补测）；当前口径 26 PASS / 1 NOT VERIFIED（13b）/ 0 FAIL。**
> - 历史 NOT VERIFIED 两项：13b（workspace-write 下 23 项测试未通过，仍未关闭）、20（当时 Git 无基线）。
> - 关键残留：`BLK-003` OPEN / MEDIUM（已诊断，非项目缺陷；13b 仅全权限下通过）；阶段 2D 未单独执行；Git 回滚已补测通过。

## 0. 策略恢复与补验摘要

| 项 | 初验（13:09–13:25） | 补验（13:26–13:28） | 当前判定 |
|---|---|---|---|
| 文件策略 | `danger-full-access` | `workspace-write` | 恢复 |
| 审批 | 关闭（`never ask`） | `ask`（提示启用） | 恢复 |
| 第 5 项 | FAIL | 工作区读写通过；项目外写入被拒 | **PASS** |
| 第 6 项 | FAIL | 工作区正确；`workspace-write` / `ask` | **PASS** |
| 第 23 项 | FAIL | 审批 `ask`；无 teams/parallel | **PASS** |
| 第 13 项 | PASS（未拆分） | 13a PASS；13b 43 errors | **13a PASS / 13b NOT VERIFIED** |
| 第 20 项 | NOT VERIFIED | 仍未实测回滚 | **NOT VERIFIED** |

## A. 验收总表（26 项，补验后）

| # | 验收项 | 实际命令 / 操作 | 退出码 / 结果 | 判定 | 证据路径 |
|---:|---|---|---|---|---|
| 1 | Desktop 正常启动，Profile=desktop | `Get-Process`；读取 `DSH_PROFILE`；`Invoke-WebRequest http://127.0.0.1:62627` | 6 个 `DeepSeek Harness` 进程；`DSH_PROFILE=desktop`；GUI 401（服务可达、需鉴权）；exit 0 | **PASS** | `docs/verification/stage8/01_startup_profile.log` |
| 2 | 2C 三项配置与 2D 结论一致 | 只读核对 `cordis.patch.yml` 三块 + 哈希；引用阶段 6 非回归日志 | 三项值正确；配置哈希与阶段 6 一致；**2D 未单独执行、运行态未观测** | **静态确认 PASS / 运行态未观测** | `02_security_2c.md`、`02_security_2c.log`、`docs/verification/stage6/07_post_write_verify.log` |
| 3 | 模型可调用，报告不含凭据 | 1 个子 Agent 最小模型探针；不调用工具、不读写文件 | 返回 `MODEL_PROBE_OK 2026-11-08T05:12:59Z`；无凭据 | **PASS** | `03_model_probe.md` |
| 4 | Terminal 可在授权范围执行只读命令 | `Get-Location`、`& $py --version`、`git status`、`Get-ChildItem docs` | 全部 exit 0；工作区正确 | **PASS** | `04_terminal_fs.log` |
| 5 | Filesystem 工作区读写；不能越权写入未授权目录 | 工作区写/读/删；尝试写 `C:\Users\Administrator\stage8_outside_probe.txt` | 工作区写读删成功；项目外写入 **DENIED**，错误为“访问被拒绝”，目标文件未生成 | **PASS** | `33_item5_workspacewrite.log` |
| 6 | 工作区 `D:\ResearchFlow-project`；沙箱/审批符合 `workspace-write` / `ask` | 读取运行时上下文与工作区 | 工作区正确；`workspace-write`；审批 `ask` | **PASS** | `30_policy_restored.log`、`34_item6_23_workspacewrite.log` |
| 7 | 项目级 AGENTS.md 已加载 | 检查 `AGENTS.md` 大小/哈希；核对会话系统提示 | 10,528 字节；SHA256 `50C34378…EDC9`；系统提示含 `Instructions from: AGENTS.md` | **PASS** | `07_agents_project.log` |
| 8 | 全局 AGENTS.md 状态明确 | `Test-Path C:\Users\Administrator\.dsh\AGENTS.md`；`...\.agents\AGENTS.md` | 两者均 `False`；未加载；未创建 | **PASS** | `08_agents_global.log` |
| 9 | Memory.md 索引存在，指向五个子文件，有来源标注 | 读取索引；逐文件检查存在性、字节数、哈希、来源标记 | 5 个子文件全部存在；来源标记 3–8 处/文件；索引链接 5 条 | **PASS** | `09_memory.log` |
| 10 | project_state.json 可读，schema 字段齐全 | `ConvertFrom-Json` + 字段核对 + `validate` | 9 个顶层字段齐全；4 任务；8 门禁；3 阻塞；`last_verified_commit=null` | **PASS** | `10_state_schema.log`、`11_state_sync_validate.log` |
| 11 | `state_sync.py validate` 真实通过 | `& $py scripts/state_sync.py validate` | exit 0；任务=4，门禁 PASS=0/8，阻塞=3 | **PASS** | `11_state_sync_validate.log` |
| 12 | `state_sync.py render` 真实通过 | `& $py scripts/state_sync.py render` | exit 0；生成 2 个文件，含 SHA256 | **PASS** | `12_state_sync_render.log` |
| 13a | `check` 负例（拆分子项） | 临时 fixture：基线 check → 追加一行 → check → 恢复 → check | 0 → 1（含预期/实际 SHA256 与 diff）→ 0；fixture 已删除 | **PASS** | `35_check_negative_workspacewrite.log` |
| 13b | 23 项 unittest（拆分子项，workspace-write） | `& $py -m unittest discover -s tests -v` | exit 1；`Ran 23 tests`；`FAILED (errors=43)`；0.5 s；无断言失败 | **NOT VERIFIED** | `32_unittest_workspacewrite.log` |
| 14 | 九个 Skills 能被发现 | 当前会话 catalog + `.agents/skills` 目录核对 | catalog 含 9 个 `researchflow-*`；目录 9、SKILL.md 9 | **PASS** | `14_skills_catalog.md`、`14_skills_catalog.log` |
| 15 | Skills 按需加载，不每轮注入全文 | 统计本阶段实际加载数；检查 catalog 形态 | 加载 6/9；catalog 仅名称/description；正文仅 `skill` 调用时返回 | **PASS** | `15_skills_on_demand.md` |
| 16 | 至少三个 Skill 无副作用调用测试 | 加载 evidence-security、contracts-api、dag-state-machine；前后 167 文件聚合 SHA256 | 前后聚合 SHA256 完全一致（`22d26124…c972`） | **PASS** | `16_skill_no_side_effect.log` |
| 17 | `docs/SKILL_CATALOG.md` 三态记录完整 | 解析 §3 表：行数、三态列、每行 8 列 | 9 行；表头含“已发现/已加载/已执行验证”；列数一致 | **PASS** | `17_skill_catalog_check.log`、`docs/SKILL_CATALOG.md` |
| 18 | Context7 MCP 最小真实调用 | `resolve-library-id(Pydantic)` + `query-docs(/pydantic/pydantic)` | 两次均成功；返回 Pydantic V2 文档；无 API Key、无 429 | **PASS** | `18_context7.md` |
| 19 | Git 状态清晰；无自动 commit；文件未丢；DOCX 哈希未变 | `git status`、`git rev-list`、`git ls-files`、`Get-FileHash`、DOCX/PDF 计数 | 0 commit、0 tracked；DOCX 111,209 字节 / `9E54168F…CCB3A`；全项目 DOCX/PDF=1；inbox 仅 `.gitkeep` | **PASS** | `19_git_docx.log` |
| 20 | Git 可审查、可回滚 | `git log`、`git status`、`git diff`、`git checkout --` | 2026-11-08：无基线，回滚未实测；**2026-11-10 基线 `91bde66` 上补测：探针修改可见、`git checkout --` exit 0、blob/SHA256 回到 HEAD 版本、探针无残留** | **PASS（基线建立后补测）** | `20_git_rollback.md` §3、`docs/verification/g0/18_git_rollback.log` |
| 21 | 凭据与 Session 未被读取/导出/写入项目 | 审计访问路径；对 stage8 与项目文本做 6 类密钥模式扫描 | `.credentials.yaml` 未读；`sessions/` 未读；0 命中；无 Session 标识写入 | **PASS** | `21_security_audit.md`、`21_secret_scan.log` |
| 22 | 旧 CLI 与 431 个目录联接完整 | 统计 `profiles/node_modules` 重解析点；逐个检查 target；读旧 CLI `package.json` | 431 个 Junction；0 断链；旧 CLI `0.1.0-rc.8` 存在（29,623 文件 / 214.8 MB） | **PASS** | `22_cli_junctions.log` |
| 23 | 自动审批、Agent Teams 未启用；无大量并行 Agent | 读取审批策略；搜索 Profile/插件中的 teams/parallel；统计子 Agent | 审批 `ask`；teams 0 命中；workflow 0；子 Agent 1（仅模型探针） | **PASS** | `34_item6_23_workspacewrite.log`、`30_policy_restored.log` |
| 24 | 未安装 Docker、本地大模型、CUDA、不必要大依赖 | 检查 `.venv`/node_modules/依赖文件/模型文件/命令/服务；读项目包列表 | 项目内均无；Python 仅 pip/setuptools；模型文件 0；`ollama`/`nvcc`/CUDA 目录无；**系统级 Docker Desktop 已存在但服务 Stopped、项目未使用** | **PASS（项目范围）** | `24_dependencies.md`、`24_dependencies.log` |
| 25 | 第一版仍按 16GB、CPU-only、并发 2 设计；未宣称已验证 | 读 `AGENTS.md` §5、`project-context.md`；全项目搜索“并发已实测/已验证” | 设计未变；并发声明 0 命中；并发能力未实测 | **PASS（设计）** | `25_scope_design.md`、`25_scope_design.log` |
| 26 | 策划书版本冲突已记录，用户已确认基线 | 读 `C-001`/`SOURCE_REGISTER`；核对 DOCX 哈希；读用户决议 | `C-001` RESOLVED；`BLK-002` RESOLVED；DOCX 未改；`T-DOCS-001` DONE | **PASS** | `26_version_resolution.md`、`docs/reference/CONFLICT_REPORT.md` |

## B. FAIL / NOT VERIFIED / DEFERRED / BLOCKED

### B.1 FAIL

- **无**。初验的第 5、6、23 项已在策略恢复后重跑并转 PASS，不接受“书面偏差”替代。

### B.2 NOT VERIFIED（1 项：13b；第 20 项已于 2026-11-10 补测转 PASS）

| 项 | 影响 | 原因 | 建议 |
|---|---|---|---|
| 13b | 不能宣称 workspace-write 下 23 项测试通过 | 43 个 `PermissionError`/`WinError 5`，无断言失败；失败发生在临时目录与工作区子目录写入 | `BLK-003` 保持 OPEN / MEDIUM；13b 维持 NOT VERIFIED；不引用全权限下的 23/23 |

**第 20 项补测**：2026-11-10 在基线 `91bde66` 上对 `docs/CHANGELOG_DEV.md` 写入探针，确认 `git status`/`git diff` 可见，执行 `git checkout --` 后退出码 0、blob 与 SHA256 均回到 HEAD 版本、探针无残留。判定改为 **PASS（基线建立后补测）**；命令与哈希见 [`docs/verification/g0/18_git_rollback.log`](../g0/18_git_rollback.log) 与 [`20_git_rollback.md`](20_git_rollback.md) §3。

### B.3 DEFERRED / BLOCKED

- 没有验收项标为 `DEFERRED` 或 `BLOCKED`。
- `BLK-003` 仍 `OPEN`，severity 已由 `HIGH` 降为 **`MEDIUM`**；备注：**“DSH 沙箱未向运行期新建子目录传播授权；已排除 ACL 损坏，非项目缺陷”**。
- 用户 2026-11-08 已完成 DSH 权限诊断：结论 `NOT_THIS_CLASS`，`WRITE_DAC` / `WRITE_OWNER` 均具备，无缺失权限、无需清理的第三方授权项；`FIXED=0`，未做任何改动，无需回滚。报告：`C:\Users\Administrator\AppData\Local\ResearchFlow\acl-diagnostics\acl-report-559f7ffa05844dce8e62ba3238f77f3b.jsonl`。
- 机制：沙箱进程新建子目录时得到令牌默认权限，项目根上的沙箱授权未传播下去，因此能建目录、不能写入。这是环境侧授权传播问题，不是仓库权限损坏；**不得手工改 ACL，不得再跑第二遍诊断**。

### B.4 口径与残留

1. **第 2 项**：2D 未单独执行；只做静态确认（配置值 + 阶段 6 非回归），运行态未观测。已列入 `docs/state/G0_DECISION_LIST.md` 的 G0 残留风险清单。
2. **第 24 项**：项目内无 Docker/CUDA/本地模型/大依赖；整机既有 Docker Desktop 与 NVIDIA 驱动工具，服务 Stopped、项目未使用。按“项目范围”判 PASS；按“整机从未安装 Docker”的字面口径则为 FAIL。
3. **13b 证据边界**：全权限下的 `13_unittest_fullaccess.log` 保留为历史运行记录，但**不作为 13b 通过依据**；13b 只引用 `32_unittest_workspacewrite.log`。

### B.5 BLK-003 处置与全权限绕行方式

1. **13b 维持 NOT VERIFIED**；只有日后在 `workspace-write` 下真跑通 23 项测试，才可改 PASS。
2. 23 项 unittest 属于**代码正确性测试，不测沙箱边界**。允许在**单独批准的 full-access 会话**中运行；日志必须记录当次会话策略，运行结束立即恢复 `workspace-write`。
3. 该 full-access 结果**不得用于第 5/6/23 项或任何安全项**，也不得写成“workspace-write 下已验证”。
4. 不得为让测试通过而修改测试、expected、目录结构或放宽权限；不得手工改 ACL，不得再跑第二遍诊断。
5. `D:\ResearchFlow-project\tmpavet2qv9` 是空目录；**阶段 9 开始时只删除这一个目录**，不要动其他任何目录。本次阶段 8 不删除。

## C. 安全审计

| 审计对象 | 本阶段动作 | 结果 |
|---|---|---|
| `.credentials.yaml` | 未打开、未复制、未回显；仅在 `.dsh` 目录列表看到文件名 | 未触碰内容 |
| `sessions/` | 未读取、未导出、未写入项目 | 未触碰 |
| `storages/` | 未读取 | 未触碰 |
| Profile `cordis.patch.yml` | 只读 2C 三块 + 哈希；未修改 | 哈希与阶段 6 一致 |
| 阶段 6 备份 | 只读大小/哈希 | 1,200 字节 / `664CE561…FFD8`；保留 |
| 431 个目录联接 | 只读计数与 target 检查 | 431 / 0 断链；未修改 |
| 旧 CLI 0.1.0-rc.8 | 只读 `package.json` | 存在；未修改 |
| 项目外写入 | 在 `workspace-write` 下尝试写用户目录，捕获拒绝 | **DENIED**；无文件生成 |
| 密钥扫描 | 6 类模式扫描 stage8 43 个文件 + 项目文本 169 个 | 0 命中 |

**策略时间线**：

- 13:09–13:25：`danger-full-access` / 审批关闭。该区间取得的全权限 23/23 只作为历史运行记录，不作为验收通过依据。
- 13:26 起：用户恢复 `workspace-write` / `ask`；第 5、6、23 项已按原口径重跑并 PASS。
- 未读取凭据或 Session；未在项目外写入；未修改 Profile 或 431 联接。

## D. 资源占用（补验后）

| 项 | 实测 |
|---|---|
| 磁盘 C: | 已用 141.03 GB；可用 259.66 GB |
| 磁盘 D: | 已用 60.06 GB；可用 439.94 GB |
| 物理内存 | 15.74 GB 可见；3 次采样空闲 6.75–6.78 GB，使用率约 56.9–57.1% |
| 工作集前 5 | chrome 612.4 MB；DeepSeek Harness 381.6 MB；chrome 217.9 MB；DeepSeek Harness 188 MB；chrome 124.9 MB |
| 项目体积 | 7,577,992 字节（194 个文件；不含 `.git`） |
| 阶段 8 证据 | 43 个文件（`docs/verification/stage8/`） |
| 诊断保留目录 | `D:\ResearchFlow-project\tmpavet2qv9`（0 文件；已诊断；阶段 9 开始时只删除此目录） |
| 并行 Agent | 1 个子 Agent（模型探针）；0 个 workflow；无 teams/parallel 配置 |
| 13b 耗时 | 23 项 / 0.5 s（workspace-write，43 errors） |

## E. 未完成风险与建议

1. **MEDIUM — BLK-003 / 13b**：workspace-write 下 23 项测试 43 errors；DSH 权限诊断为 `NOT_THIS_CLASS`，`FIXED=0`，非仓库 ACL 损坏；机制为沙箱授权未向运行期新建子目录传播。13b 维持 NOT VERIFIED。代码正确性测试可在单独批准的 full-access 会话运行，但结果不得用于安全项；不得手工改 ACL、不得重复诊断。
2. **MEDIUM — 2D 未单独执行**：第 2 项只有静态确认，运行态未观测；已列入 G0 残留风险。建议阶段 9/G0 前补做，或由用户书面接受静态口径。
3. **RESOLVED（2026-11-10）— Git 无基线**：基线 `91bde66` 已建立并完成受控回滚补测；第 20 项转 PASS。`BLK-001` 保持 RESOLVED。
4. **LOW — 历史文档仍写 `BLK-002 OPEN`**：`CHANGELOG_DEV.md`、`SESSION_HANDOFF.md`、`stage7/STAGE7_REPORT.md`、stage4/5 证据保留历史原文；当前状态以 `project_state.json` 与 `CONFLICT_REPORT` §1.7 为准。
5. **LOW — 整机既有 Docker Desktop**：项目未使用、服务 Stopped；若 G0 口径要求“整机未安装”，需用户单独处理，未擅自卸载。
6. **LOW — blocker schema 无 `CLOSED`**：`BLK-002` 使用 `RESOLVED` 表示关闭，并在 `resolution` 写明“等价 CLOSED”。
7. **LOW — Context7 匿名额度**：只做公开库查询，未配置 API Key；MCP 内容不作为项目证据。
8. **LOW — 临时 fixture**：13a 的 fixture 已删除；真实项目文件未被篡改；诊断目录 `tmpavet2qv9` 按用户要求保留。

## F. 阶段 8 结论与阶段 9 前置

**阶段 8 结论（2026-11-08 验收口径）：25 PASS / 2 NOT VERIFIED / 0 FAIL，用户 2026-11-08 验收通过。**

**2026-11-10 补测后口径：26 PASS / 1 NOT VERIFIED（13b）/ 0 FAIL；第 20 项 PASS（基线建立后补测）。**

- 25 PASS 包含 13a；2026-11-08 时的 2 NOT VERIFIED 为 13b 与 20；20 已于 2026-11-10 补测转 PASS。
- 三项初验 FAIL 已因策略恢复消除；不接受任何以 `danger-full-access` 换取验收通过的 ADR 或例外。
- 阶段 9 尚未开始；本次不进入阶段 9。

阶段 9 开始时必须处理：

1. **只删除** `D:\ResearchFlow-project\tmpavet2qv9` 这一个空目录；不要动其他任何目录。删除后在阶段 9 报告中确认。
2. `BLK-003` 保持 OPEN / MEDIUM；13b 维持 NOT VERIFIED。只有日后在 workspace-write 下真跑通 23 项测试才可改 PASS。
3. G0 残留风险已写入 [`docs/state/G0_DECISION_LIST.md`](../../state/G0_DECISION_LIST.md)：① 13b 仅在全权限下通过；② 2D 未单独执行、2C 运行态未观测；③ Git 基线已建立、回滚已于 2026-11-10 补测 PASS。
4. 若在单独批准的 full-access 会话运行 23 项 unittest：日志记录当次策略，结束立即恢复 workspace-write；结果不得用于第 5/6/23 项或任何安全项。
5. 不手工改 ACL；不再跑第二遍诊断。

截至 2026-11-08，G0–G7 全部 `NOT_STARTED`；2026-11-10 用户宣布 G0 PASS，G1–G7 仍 `NOT_STARTED`。阶段 8 当时未 commit、未创建 `.venv`、未开发业务代码。

## 附：本阶段明确未做

- 未 commit、未 `git add`、未创建基线 commit。
- 未创建 `.venv`、未安装依赖、未运行 `pnpm install`。
- 未开发 ResearchFlow 业务代码；`researchflow/`、`contracts/` 仍只有 `.gitkeep`。
- 未修改/改名/移动/复制 DOCX；未产生第二份策划书副本。
- 未修改测试、expected、目录结构或权限；未删除诊断目录 `tmpavet2qv9`。
- 未删除阶段 6 备份；未修改 431 个目录联接。
- 未读取 `.credentials.yaml`、Session 内容；未在项目外写入。
- 未进入阶段 9、未修改 G0–G7 状态。
