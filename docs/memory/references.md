# references.md — 资料来源与关键引用索引

> 更新时间：2026-11-08（阶段 7；阶段 8 复核）
> 核验状态：策划书已做全文只读抽取（754/754 段落、80/80 表格）；文件大小与 SHA256 已复核。**版本冲突已由用户 2026-11-08 决议关闭**：内容基线为文档内部 v4.3.0，文件名 v4.3.1 仅为标签；`BLK-002` 已关闭。
> 证据规则：外部资料、官方网页、模型输出和第三方材料默认不是可信证据；只有经过声明的验证流程，才能用于“已实测 / 已验证”结论。

## 1. 项目主文档

### R-01 ResearchFlow 3.1 项目策划书

| 项目 | 值 |
|---|---|
| 文件名 | `ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx` |
| 仓库路径 | `D:\ResearchFlow-project\ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx` |
| 大小 | 111,209 字节 |
| SHA256 | `9E54168FB1B553294ECB88E2E3F5C8CE878EE699FCF07E37D531A68C195CCB3A` |
| 文件名版本 | v4.3.1（仅标签） |
| 文档内部版本 | **v4.3.0**（封面 P0001/P0007、页眉、正文 P0013、core title） |
| 日期 | 文档控制表 `2026 年 11 月 6 日`；文件系统 `2026-11-06 18:43:34`；core 属性 `2013-12-23T23:15:00Z` 为模板默认值，不可用 |
| 文档结构（实测） | 754 个段落；80 张表；0 图片/绘图/文本框；0 修订/批注；无 TOC；30 个手工分页符 |
| 核验状态 | 文件存在、大小、SHA256 与全文抽取已复核；**版本生效性待用户确认** |
| 详细登记 | [`../reference/SOURCE_REGISTER.md`](../reference/SOURCE_REGISTER.md)；冲突见 [`../reference/CONFLICT_REPORT.md`](../reference/CONFLICT_REPORT.md) |

本阶段实际对照的章节 / 表：

| 位置 | 用途 |
|---|---|
| §1.1 一句话定位 | 项目定位 |
| §1.4 三条技术主线 | EG/TLV、DC/SPA、Scheduler/Governor/VAS |
| §3.4 威胁模型 | 信任边界 |
| §4.2 核心验收指标 | 目标值（非实测） |
| §4.4 明确不做 | 第一版非目标 |
| §5.1 五条不可协商的架构原则 | 架构约束 |
| §5.2 六层架构 L1–L6 | 架构分层 |
| §5.3 数据流 | 任务/证据/恢复流 |
| §5.4 进程与资源预算 | 16GB/并发 2 设计边界 |
| §6.2 四类状态机 | 报告/凭证状态边界 |
| §7.1 E0–E3 证据等级 | 证据分级 |
| §7.2 Gate 规则 | Gate 顺序与必检项 |
| §7.3–7.5 哈希链/Merkle/JCS/Ed25519 | 密码学与离线验签 |
| §8.1–8.9 DC/SPA/恢复/调度 | T1/T2 机制 |
| §9.1–9.5 L1/L2/L3/证据包 | 独立验证 |
| §10.1–10.4 六角色/权限/CPG/Role-off | 多智能体边界 |
| §15.2 T0/T1/T2 交付阶段 | 阶段划分与 T0 出口 |
| §15.3 质量门禁 | G0–G7 名称与通过条件 |
| §15.5 开发顺序 | 先契约后实现 |
| §17.1 安全边界 | 执行/网络安全 |
| 附录 D/E/F/G/J | Schema、API、状态机、基准、T0 清单 |

**待核实**：该版本是否已被用户书面确认为唯一冻结基线。在确认前，不得把其中的目标数字当作最终验收合同，也不得据此宣布 G0 通过。

## 2. 赛事与外部资料

| 编号 | 资料 | 位置 | 状态 |
|---|---|---|---|
| R-02 | 赛事官方入口（策划书记录） | `https://www.omniedu.com/ai-hub/contest/detail/2111011327399952386/intro` | 未独立访问核验；仅作为索引 |
| R-03 | 赛事通知图片 / 官方动态页 | 策划书 §1.3 记录“本次读取未返回完整章程” | 待核实；评分权重、页数、匿名要求等不得自行推断 |
| R-04 | `docs/reference/inbox/` | 仓库目录，当前只有 `.gitkeep` | 无新增外部资料 |

外部资料使用规则：

1. 官方章程、网页、第三方证明必须记录 URL、访问日期与原文摘要。
2. 截图 / 图片中的数字不能直接当作实测数据；需标注来源与可复核路径。
3. 未核验的外部信息只能写入“参考 / 待核实”，不得写入验收证据。

## 3. DSH 与工具链参考

| 编号 | 资料 | 路径 | 用途 |
|---|---|---|---|
| R-05 | `agent-instructions` 插件说明 | `C:\Users\Administrator\.dsh\profiles\node_modules\@deepseek-ai\dsh-agent-instructions\README.md` | 解释 AGENTS 加载、刷新与预算机制 |
| R-06 | `standard` preset 配置 | `C:\Users\Administrator\.dsh\profiles\node_modules\@deepseek-ai\dsh\config\agent-presets\standard\agent.cordis.yml` | 默认 preset 的 `agent-instructions` 挂载核对；该 profile 包版本为 0.1.0-rc.8，不能替代桌面 runtime 0.2.2-rc.1 的行为核实 |
| R-07 | `desktop` Profile patch | `C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml`、`...\node_modules\@deepseek-ai\dsh-web-app\cordis.patch.yml` | 解释 host plane 与 preset 的插件分层 |
| R-08 | 本机 Python 基线 | `C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe` | 脚本与测试解释器 |
| R-09 | 项目规则 | `D:\ResearchFlow-project\AGENTS.md` | 项目主规则来源 |
| R-10 | 状态同步实现与测试 | `scripts/state_sync.py`、`tests/test_state_sync.py` | 本阶段可执行事实源 |
| R-11 | Skills Provider 源码（0.2.2-rc.1） | `D:\deepseek_harness1\resources\app.asar` 内 `dsh/node_modules/@deepseek-ai/dsh-skill-filesystem/lib/index.js` 第 160–190 行；同包 `README.md` 第 48–54 行 | 核实 `.dsh/skills` 与 `.agents/skills` 扫描根 |
| R-12 | Skills Registry / Consumer（0.2.2-rc.1） | app.asar 内 `dsh-skill`、`dsh-tool-skill` 的 `README.md` | 核实 `ctx.skills` 与 catalog/load 行为 |
| R-13 | 项目 Skills 目录与 Stage 5 证据 | `docs/SKILL_CATALOG.md`、`docs/verification/stage5/` | 九个 Skill 的发现、加载、调用与结构校验 |
| R-14 | MCP Client 源码（0.2.2-rc.1） | app.asar 内 `dsh/node_modules/@deepseek-ai/dsh-mcp-client/`：`package.json`、`lib/index.js`、`README.md` | 核实版本、`stdio` / `streamable-http`、配置字段、工具命名与限制 |
| R-15 | profile bundle 解析顺序 | app.asar 内 `dsh-app-boot/lib/index.js` 第 1317–1321、1763–1779 行 | 证明安装锚点优先、profile 目录仅第二锚点，0.1.0-rc.8 不能替代 0.2.2-rc.1 |
| R-16 | Context7 远程 MCP 端点与文档 | `https://mcp.context7.com/mcp`；[API Guide](https://github.com/upstash/context7/blob/23843e9c/docs/api-guide.mdx)、[Plans & Pricing](https://github.com/upstash/context7/blob/bfe89ea8/docs/plans-pricing.mdx) | 端点匿名探测、工具清单、配额说明；外部资料，访问日期 2026-11-08，默认不是项目证据 |
| R-17 | Stage 6 MCP 能力与配置执行 | `docs/verification/stage6/` | 能力矩阵、Context7 探测、配置 diff、写入校验、热重载与真实调用 |
| R-18 | Context7 接入执行结果 | `docs/verification/stage6/08_apply_result.md` | 备份哈希、写入前后哈希、前缀一致性、工具清单、真实查询与 2C 核对 |
| R-19 | 阶段 7 资料来源登记 | `docs/reference/SOURCE_REGISTER.md` | 原件、版本证据、缺失资料、敏感信息/Git/解析完整性 |
| R-20 | 阶段 7 冲突报告 | `docs/reference/CONFLICT_REPORT.md` | v4.3.1/v4.3.0 冲突、飞书/赛事资料缺失、方案与推荐 |
| R-21 | 阶段 7 只读抽取与版本证据 | `docs/verification/stage7/` | 754 段/80 表全文、`v4.3.1` 在文档内计数 0、页码不可用说明 |
| R-22 | 阶段 8 综合验收报告与证据 | `docs/verification/stage8/STAGE8_REPORT.md`、`docs/verification/stage8/` | 26 项验收、运行态证据、FAIL/NOT VERIFIED、资源与安全审计 |
| R-23 | G0 裁决清单（阶段 9 准备） | `docs/state/G0_DECISION_LIST.md` | 版本项已决；剩余 FR-010 边界、开发顺序、P1/T2 错位 3 项 |

## 4. 引用纪律

- 引用策划书时写明“内部 v4.3.0（文件名 v4.3.1，`BLK-002` 已关闭）§章节 / P#### / TABLE ##”，不写“策划书说”而不给位置；页码不可用时不得估算。
- 引用外部网页时写明 URL 与访问日期；未访问成功的，标注“未核验”。
- 引用测试结果时写明命令、解释器绝对路径、退出码、日志路径与运行时间。
- 不把 `docs/reference/inbox/` 中的原始资料改写后冒充原文；原文与摘要分开记录。
- 任何引用若与 `AGENTS.md`、ADR 或冻结契约冲突，以更高优先级文件为准并报告冲突。

## 5. 相关文件

- [`docs/memory/Memory.md`](Memory.md)
- [`docs/memory/project-context.md`](project-context.md)
- [`docs/memory/architecture-decisions.md`](architecture-decisions.md)
- [`docs/verification/stage4/`](../verification/stage4/)
- [`docs/verification/stage5/`](../verification/stage5/)
- [`docs/verification/stage6/`](../verification/stage6/)
- [`docs/verification/stage7/`](../verification/stage7/)
- [`docs/verification/stage8/`](../verification/stage8/)
- [`docs/state/G0_DECISION_LIST.md`](../state/G0_DECISION_LIST.md)
- [`docs/reference/SOURCE_REGISTER.md`](../reference/SOURCE_REGISTER.md)
- [`docs/reference/CONFLICT_REPORT.md`](../reference/CONFLICT_REPORT.md)
- [`docs/reference/GLOBAL_AGENTS_PROPOSAL.md`](../reference/GLOBAL_AGENTS_PROPOSAL.md)
