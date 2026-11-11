# environment.md — 已核实环境、版本与配置摘要

> 核验时间：2026-11-08 11:25–12:36（阶段 4–6）；阶段 7 追加 12:41 起（资料抽取与工具限制）；2026-11-10 WP-01 追加环境与依赖实测。
> 核验方式：本机 PowerShell 命令实测 + 项目文件检查。
> 安全边界：本文件不记录任何密钥、令牌、凭据内容或 Session 标识；`C:\Users\Administrator\.dsh\.credentials.yaml` 未被读取。
> 标记规则：只有命令实测结果写入“已核实”；推断或待定内容写入“待核实”。

当前状态以 docs/state/project_state.json 为准。

## 1. 操作系统与硬件

| 项目 | 已核实值 | 备注 |
|---|---|---|
| OS | Microsoft Windows 11 专业版 | `Win32_OperatingSystem.Caption` |
| 版本 / Build | 10.0.22631 / 22631 | 64 位 |
| CPU | 13th Gen Intel(R) Core(TM) i7-13620H | 10 核 / 16 逻辑处理器 |
| 物理内存 | 15.74 GB（系统可见） | 项目设计约束为 16GB；以实测为准 |
| 磁盘可用 | C: 259.09 GB；D: 439.95 GB | 核验时点 |
| 时区 | Asia/Shanghai（UTC+08:00） | 文档时间以本地时区记录 |
| GPU | 未用于项目 | 第一版约束为 CPU-only；未做 GPU 推理 |

## 2. Python 解释器（关键约束）

### 2.1 项目基线（唯一允许）

| 项目 | 值 |
|---|---|
| 绝对路径 | `C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe` |
| 版本 | 3.11.16 |
| 架构 | 64-bit (AMD64) |
| 编译信息 | MSC v.1944 64 bit |
| pip | 26.2.1 |
| 状态 | 已实测存在并可运行 |

### 2.2 禁止使用的解释器

| 命令 | 实际路径 | 版本 / 架构 | 结论 |
|---|---|---|---|
| `python` | `C:\Program Files\Python312\python.exe` | 3.12.0 / 64-bit | 禁止用于本项目脚本与测试 |
| `py -3.11` | `C:\Program Files (x86)\Python311-32\python.exe` | 3.11.0 / 32-bit | 禁止；与项目基线不是同一解释器 |

### 2.3 项目虚拟环境

- `D:\ResearchFlow-project\.venv`：**已创建（2026-11-10，WP-01）**；`.venv\Scripts\python.exe` 实测 `3.11.16` + `64bit`。
- WP-01 之前为无虚拟环境、无第三方依赖状态（历史）；`state_sync.py` 与测试只使用标准库。
- 后续如重建 `.venv`，必须由上述 3.11.16（64 位）解释器或 uv 的 `--python 3.11.16` 创建，并在记忆与状态中登记。
- 资料抽取说明：阶段 4 使用 DSH 自带 Python 环境（含 `python-docx 1.2.0`）读取策划书 DOCX，仅用于抽取章节与表格；该环境未用于项目脚本、测试或交付代码。
- 阶段 7 的 DOCX 全文抽取改用项目 Python 3.11.16（64 位）+ 标准库（`zipfile` / `xml.etree`），脚本为 `docs/verification/stage7/extract_docx.py`；未使用 `python-docx` 写文件，未修改原件。
- 阶段 7 尝试用 Microsoft Word COM 只读获取页码：Word 进程启动阶段阻塞，分页未完成（历史）；文档未改动；LibreOffice/WPS 未采用（历史）。因此页码标注“不可用”，引用改用章节 + 段落锚点。

### 2.4 uv

- 版本：`uv 0.12.16 (761ff1379 2026-09-17 x86_64-pc-windows-msvc)`。
- 用途：提供项目 Python 3.11.16 基线；2026-11-10 WP-01 用其创建 `.venv`、安装依赖并生成锁文件。
- 矩阵列出的 `uv 0.13.7` 未采用/未升级（历史）；原因与偏差见 §2.5 与 `docs/verification/t0/wp-01/dependency_resolution.txt`。

### 2.5 WP-01 环境实测（2026-11-10）

| 项 | 实测 |
|---|---|
| 创建命令 | `uv venv --python 3.11.16 .venv` |
| uv | `0.12.16`；缓存目录改为 `D:\ResearchFlow-project\.uv-cache`（默认缓存目录在工作区沙箱外，首次失败） |
| `.venv` 解释器 | `D:\ResearchFlow-project\.venv\Scripts\python.exe`；3.11.16 / 64bit |
| SQLite | `3.53.1` |
| 直接依赖 | 16 个矩阵内 pin + `httpx2==2.16.0`（用户 2026-11-10 批准，TestClient 用） |
| 锁文件 | `requirements.lock`，58 个精确 pin；`requirements.in` 为直接清单 |
| `.venv` 体积 | 502,349,269 字节（502.3 MB）；矩阵估算 350–450 MB，超出上限 52.3 MB（+11.6%） |
| 安装耗时 | venv 0.51 s + 矩阵包 46.10 s + httpx2 12.87 s = 59.48 s |
| 冒烟 | FastAPI `TestClient` 200；uvicorn 实际启动 200；8 个模块导入成功 |
| 证据 | `docs/verification/t0/wp-01/` |

`uv` 版本与矩阵列的 0.13.7 不一致，按“工具、是否升级由 WP-01 决定”保留 0.12.16，偏差已记录。

## 3. Git 与版本控制

| 项目 | 已核实值 |
|---|---|
| Git | `git version 2.46.0.windows.1` |
| 当前分支 | `main` |
| commit 数 | 以 `git rev-list --count --all` 为准 |
| `user.name` | `ResearchFlow Dev`（仅本仓库 `--local`） |
| `user.email` | `dev@researchflow.local`（仅本仓库 `--local`） |
| `core.autocrlf` | `true` |
| 仓库根 | `D:\ResearchFlow-project` |

影响：

- Git 身份仅在本仓库配置：`user.name=ResearchFlow Dev`、`user.email=dev@researchflow.local`；全局身份仍为空。提交前仍须由用户批准，不得自行扩大提交范围。
- `core.autocrlf=true` 可能在检出时把文本转为 CRLF，破坏“逐字节一致”的 `state_sync.py check`。`.gitattributes` 已将 Python、JSON、Markdown、日志固定为 LF，并把 `.gitattributes` 自身固定为 LF。
- 阶段 4–8 未执行 `git add` / `git commit`；2026-11-10 按用户指令建立 G0 基线、G0 裁决与 WP-01 提交（以 `git log` 为准）。

## 4. Node.js 与 pnpm

| 项目 | 已核实值 |
|---|---|
| Node.js | `v20.17.0` |
| pnpm | `12.5.1` |
| pnpm 路径 | `C:\Users\Administrator\AppData\Roaming\npm\pnpm.cmd` |
| PowerShell 约束 | 必须使用 `pnpm.cmd`；`pnpm.ps1` 被执行策略拦截 |

本阶段未运行 pnpm；Node 依赖保持为空（截至 2026-11-11）。

## 5. PowerShell

- 版本：`5.1.22621.2506`。
- 本阶段测试命令通过 PowerShell 调用 Python 绝对路径；日志以 UTF-8 保存。
- 注意：控制台默认代码页可能不是 UTF-8，涉及中文输出时应显式设置 `PYTHONUTF8=1` 或 `encoding="utf-8"`。

## 6. DSH（DeepSeek Harness）配置

| 项目 | 已核实值 |
|---|---|
| `DSH_HOME` | `C:\Users\Administrator\.dsh` |
| `DSH_PROFILE` | `desktop` |
| `DSH_PROFILE_DIR` | `C:\Users\Administrator\.dsh\profiles\desktop` |
| `DSH_AGENTS_HOME` | 未设置（空） |
| 全局 AGENTS | `C:\Users\Administrator\.dsh\AGENTS.md` **不存在** |
| 项目 AGENTS | `D:\ResearchFlow-project\AGENTS.md` 存在，且已在本会话实际加载 |

### 6.1 AGENTS 加载机制核对

- `agent-instructions` 插件位于 `C:\Users\Administrator\.dsh\profiles\node_modules\@deepseek-ai\dsh-agent-instructions`。
- `desktop` Profile 的 host plane 通过 `dsh-web-app/cordis.patch.yml` 将 `agent-instructions` 标记为 `disabled: true`，这是为了把 Agent 层插件交给每个会话的 preset 挂载。
- DSH 默认 preset 为 `standard`；其配置在 `C:\Users\Administrator\.dsh\profiles\node_modules\@deepseek-ai\dsh\config\agent-presets\standard\agent.cordis.yml` 第 30–31 行重新挂载 `@deepseek-ai/dsh-agent-instructions`。
- 本会话启动时的系统提示已包含 “Instructions from: AGENTS.md”，且重写 `AGENTS.md` 后收到 “Updated instructions from: AGENTS.md”，内容为新版本。**结论：项目 AGENTS 已实际加载并刷新。**
- 全局 `C:\Users\Administrator\.dsh\AGENTS.md` 仍不存在（截至 2026-11-11）；本阶段未做创建或修改。如未来确有必要，须单独审批，方案见 `docs/reference/GLOBAL_AGENTS_PROPOSAL.md`。

### 6.2 Skills 发现机制（阶段 5 核实）

| 项 | 已核实值 |
|---|---|
| 桌面壳版本 | `@deepseek-ai/dsh-desktop@0.2.2-rc.1` |
| 内置 runtime | `@deepseek-ai/dsh-desktop-runtime@0.2.2-rc.1`，位于 `D:\deepseek_harness1\resources\app.asar` 内 |
| Provider | `@deepseek-ai/dsh-skill-filesystem@0.2.2-rc.1` |
| 项目级根 | `<projectRoot>/.dsh/skills`（rank 100）、`<projectRoot>/.agents/skills`（rank 200） |
| Registry | `@deepseek-ai/dsh-skill@0.2.2-rc.1`，通过 `ctx.skills` 合并 provider |
| Consumer | `@deepseek-ai/dsh-tool-skill@0.2.2-rc.1`，提供 catalog 与 `skill` 加载工具 |
| 本项目实际根 | `D:\ResearchFlow-project\.agents\skills`（project root 由 `.git` 判定） |
| 实际结果 | 创建 9 个 Skill 后 catalog 三次刷新，最终全部出现；`skill` 工具逐个加载成功 |

注意：profile 下的 npm 包 `C:\Users\Administrator\.dsh\profiles\node_modules\@deepseek-ai\dsh` 版本为 `0.1.0-rc.8`，不是桌面壳实际使用的 runtime 版本；扫描路径结论以 app.asar 内 `0.2.2-rc.1` 源码为准。详细证据见 `docs/verification/stage5/00_discovery.md`。

未在 `.dsh/skills`、`C:\Users\Administrator\.dsh\skills` 或 `C:\Users\Administrator\.agents\skills` 创建同名 ResearchFlow Skill。

### 6.3 MCP Client 能力与 Context7 接入（阶段 6 核实/执行）

| 项 | 已核实值 |
|---|---|
| MCP Client | `@deepseek-ai/dsh-mcp-client@0.2.2-rc.1`，位于 app.asar runtime 树内 |
| 传输 | `stdio`、`streamable-http`（远程 HTTPS） |
| 工具命名 | `mcp__<serverName>__<rawName>`；同一 server 内工具名稳定 |
| 配置方式 | Cordis 插件条目；profile `cordis.patch.yml` 用 `insert` 新增 server |
| 默认 MCP server | 无；`dsh-base` 只挂载 `mcp-resources`，不挂 `mcp-client` |
| Context7 端点 | `https://mcp.context7.com/mcp` 匿名可用；`initialize` / `tools/list` / `tools/call` 均 HTTP 200 |
| 当前接入状态 | **已接入并验证（2026-11-08 12:33）**；serverName=`context7`；两个工具已真实调用 |
| 配置文件 | `cordis.patch.yml` 1,462 字节 / SHA256 `6FF6…59E1`；备份 `.bak-20261108-stage6` 为原始 1,200 字节 |
| API Key | **未配置**；匿名可运行，带 Key 提高配额；未读取凭据文件 |

注意：profile 下 `0.1.0-rc.8` 的 `dsh-mcp-client` 只作解析回退，不作为当前行为依据；`dsh-app-boot` 的 bundle 解析是“安装锚点优先，profile 目录第二”。证据见 `docs/verification/stage6/`（执行结果见 `08_apply_result.md`）。

### 6.4 阶段 8 会话策略变更（临时运行态）

- 2026-11-08T13:10+08:00，用户将会话从 `workspace-write` / 审批 `ask` 切换为 `danger-full-access` / 审批关闭（`never ask`）。
- 该变更由用户发起，Agent 未请求提权、未设置 `sandbox_permissions`。
- 期望基线仍是 `workspace-write` / `ask`；不得把本次 `danger-full-access` 当成项目长期配置或安全验收通过。
- 在该会话下，23 项 `unittest` 真实运行 23/23 OK（3.2s，exit 0，`docs/verification/stage8/13_unittest_fullaccess.log`）；但 `workspace-write` 下仍会复现临时目录 ACL 阻塞，故 `BLK-003` 保持 `OPEN`，不得据此宣称 workspace-write 下测试通过。
- 2026-11-08T13:26+08:00，用户恢复 `workspace-write` / 审批 `ask`。补验结果：第 5、6、23 项 PASS；13b 在 workspace-write 下仍 23 tests / 43 errors（0.5s，无断言失败）。
- 按用户指定命令取证：`tempfile.mkdtemp(dir=D:\ResearchFlow-project)` 创建 `D:\ResearchFlow-project\tmpavet2qv9`，写 `probe.txt` 抛 `PermissionError [Errno 13] Permission denied: 'D:\ResearchFlow-project\tmpavet2qv9\probe.txt'`。系统临时目录拒绝属预期；工作区内 Python 新建子目录再写入也被拒。
- 用户 2026-11-08 用 DSH 权限诊断工具检查该目录，结论 `NOT_THIS_CLASS`：`WRITE_DAC` / `WRITE_OWNER` 均具备，无缺失权限、无需清理的第三方授权项；`FIXED=0`，未做任何改动。机制为沙箱进程新建子目录时得到令牌默认权限，项目根上的沙箱授权未传播下去；属于环境侧授权传播问题，不是仓库权限损坏。不得手工改 ACL、不得再跑第二遍诊断。
- `BLK-003` 因此由 HIGH 降为 MEDIUM，仍 OPEN；13b 维持 NOT VERIFIED。23 项 unittest 属代码正确性测试，可在单独批准的 full-access 会话运行，日志记录当次策略并立即恢复 workspace-write；结果不得用于第 5/6/23 项或任何安全项。
- `tmpavet2qv9` 为空目录，阶段 9 开始时只删除该目录，不动其他目录。
- 阶段 8 未在项目外写入任何文件（`C:\Users\Administrator\stage8_outside_probe.txt` 写入被拒，文件未生成）；未读取 `.credentials.yaml` 或 Session 内容。

## 7. 网络与依赖状态

- 阶段 5 及以前未主动测试外网连通性；阶段 6 对 `https://mcp.context7.com/mcp` 做了无凭据只读探测，并按批准接入该端点（匿名额度）。查询只含公开库名与技术问题。项目仍保持“不默认开放网络”的设计约束，未新增其他外网依赖。
- 2026-11-10 WP-01 通过 PyPI 安装 58 个 Python 包（含 `httpx2`）并生成 `requirements.lock`；这是受控安装，不等于运行期默认开放网络。
- Node 依赖保持为空；本阶段未运行 pnpm。
- 阶段 5 的 Skills 为 Markdown + YAML frontmatter，结构校验脚本只用 Python 标准库；WP-01 后项目脚本可使用 `.venv`。
- 未接入 LLM，未调用模型 API。
- 未部署 Docker、本地大模型或数据库。

## 8. 环境核验命令（摘要）

```powershell
# Python 基线
& 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe' -c "import sys,platform;print(sys.version);print(sys.executable);print(platform.architecture()[0])"

# PATH 解释器（仅用于确认禁用原因）
python --version
py -3.11 -c "import sys;print(sys.version);print(sys.executable)"

# Git / Node / pnpm / uv
git --version
git config user.name
git config user.email
node --version
pnpm.cmd --version
uv --version

# DSH
Write-Output $env:DSH_HOME
Write-Output $env:DSH_PROFILE
Test-Path 'C:\Users\Administrator\.dsh\AGENTS.md'
```

## 9. 待核实

- `.venv` 已创建（2026-11-10 WP-01，3.11.16/64bit），见 §2.5；未做干净机器复现（本机缓存预热）。
- 依赖版本已按矩阵锁定并写入 `requirements.lock`；`uv` 工具版本 0.12.16 与矩阵 0.13.7 的偏差已记录。
- 并发 2 与 16GB 内存下的实际资源峰值尚未实测。
- 外网在离线演示环境中的默认策略，需在 T0 验收方案中确认。
