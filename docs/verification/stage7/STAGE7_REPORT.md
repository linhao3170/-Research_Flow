# 阶段 7 资料接手报告 — ResearchFlow

> 阶段：7 / 资料接手与知识基线
> 状态：**已完成，等待用户验收；未进入阶段 8**
> 时间：2026-11-08 12:41–13:02（Asia/Shanghai）
> 执行人：DSH Agent（deepseek-flash）
> 关键结论：**唯一权威原件已在根目录；未复制/移动/修改；全文已读；版本冲突未解决；`BLK-002` 保持 OPEN；G0 不得冻结。**

## 1. 结论摘要

| 项 | 结果 |
|---|---|
| 资料发现 | 根目录 1 份 DOCX；`docs/reference/inbox/` 只有 `.gitkeep`；无 PDF/其他策划书副本 |
| 文件完整性 | 111,209 字节；SHA256 `9E54168F…CCB3A`；执行前后一致 |
| 阅读完整性 | 754/754 段落；80/80 表格；0 图片/绘图/文本框；0 修订/批注；无 TOC |
| 版本 | 文件名 v4.3.1；文档内部 v4.3.0；文档内 `v4.3.1` 计数 0；**冲突未裁决** |
| 日期 | 文档控制表 2026-11-06；文件系统 mtime 2026-11-06 18:43:34；DOCX 属性 2013 默认值不可用 |
| 冲突 | C-001 版本冲突（HIGH，阻断 G0）；C-002 飞书缺失；C-003 赛事通知/章程缺失；C-004 属性失效；C-005 页码不可得；C-006 旧引用版本不一致；C-007 inbox 位置（已按指令处理） |
| 交付 | 2 份来源/冲突文档 + 8 份知识/架构文档 + 本报告 + 只读证据 |
| 状态 | `T-SKILLS-001` → `DONE`；`T-MCP-001` 保持 `DONE`；新增 `T-DOCS-001` `IN_REVIEW`；G0–G7 未改；`BLK-002` 保持 `OPEN` |
| 禁止项 | 未 commit、未建 `.venv`、未装依赖、未开发业务代码、未复制 DOCX、未删阶段 6 备份 |

## 2. 执行范围与约束遵守

### 2.1 已做

- 只读扫描项目目录与 `docs/reference/`，确认实际存在的资料。
- 用项目 Python 3.11.16 + 标准库只读抽取 DOCX 包、属性、正文、表格、页眉页脚、字段与版本字符串。
- 逐段/逐表阅读；对 80 个表全部展开，合并单元格标注。
- 建立来源登记、冲突报告、项目总览、架构、术语、开发工作流、记忆指南、Skill 目录更新、MCP 目录、安全政策。
- 更新研发看板、CHANGELOG、SESSION_HANDOFF、记忆文件与 README。
- 运行 `state_sync.py validate / render / check` 并留存日志。

### 2.2 明确未做

| 禁止项 | 实际 |
|---|---|
| 复制/移动/重命名/覆盖根目录 DOCX | **未做**；原件仍在根目录，哈希不变 |
| 在 `docs/reference/inbox/` 放策划书副本 | **未做**；inbox 仍只有 `.gitkeep` |
| 修改 DOCX 内容/属性 | **未做**；只读 zip 解析，未写回 |
| commit / `git add` | **未做**；0 commit |
| 创建 `.venv` / 安装依赖 | **未做**；`.venv` 不存在 |
| 开发业务代码 | **未做**；`researchflow/` 仍只有 `.gitkeep` |
| 删除阶段 6 备份 | **未做**；`cordis.patch.yml.bak-20261108-stage6` 保留 |
| 改 G0–G7 | **未做**；全部仍 `NOT_STARTED` |
| 自行裁决版本 | **未做**；只登记冲突与方案，`BLK-002` 保持 OPEN |
| 假装飞书/赛事资料可访问 | **未做**；登记为 RF-MISS-001/002 |

## 3. 资料发现

### 3.1 实际存在的资料

| 项 | 值 |
|---|---|
| 文件名 | `ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx` |
| 绝对路径 | `D:\ResearchFlow-project\ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx` |
| 类型 | DOCX（OOXML zip） |
| 大小 | 111,209 字节 |
| SHA256 | `9E54168FB1B553294ECB88E2E3F5C8CE878EE699FCF07E37D531A68C195CCB3A` |
| 文件系统时间 | `LastWriteTime=2026-11-06T18:43:34+08:00`；`CreationTime=2026-11-06T22:30:08+08:00` |
| 文档包成员 | 19 个；无 `word/media/`；有 `header1.xml`、`footer1.xml`、`core.xml`、`app.xml` |
| ZIP 完整性 | `ZIP_TEST=OK` |

完整清单：[`09_inventory.log`](09_inventory.log)、[`00_docx_package.txt`](00_docx_package.txt)。

### 3.2 未实际落地的资料

| 资料 | 事实 | 处理 |
|---|---|---|
| 飞书 AI 开发说明 | 项目内没有文件、路径或导出件 | 登记 RF-MISS-001；不引用、不假设 |
| 赛事通知图片 / 完整章程 | 项目内没有原图/PDF/章程；策划书 §1.3 说依据通知图片，官方页未返回完整章程 | 登记 RF-MISS-002；不推断评分/页数/匿名/AI/IP |
| 真正的 v4.3.1 内容 | 文档内 `v4.3.1` 计数 0；无另一份文件 | 登记 RF-MISS-003；`BLK-002` OPEN |

### 3.3 非资料类文件

- `docs/reference/GLOBAL_AGENTS_PROPOSAL.md`：项目内部治理提案（全局 AGENTS 未创建），不是外部资料。
- `docs/reference/inbox/.gitkeep`：0 字节占位，不是资料。

## 4. 阅读与解析完整性

| 项目 | 结果 | 证据 |
|---|---|---|
| 段落 | 754 / 754（100%） | `01_docx_properties.txt` §COUNTS |
| 表格 | 80 / 80（100%） | `05_docx_tables.txt` |
| 表格行/单元格 | 全展开；`gridSpan`/`vMerge` 标注 | 同上 |
| 嵌入图片 | 0（无 `word/media/`） | `01_docx_properties.txt` |
| 绘图/文本框 | 0 `w:drawing`、0 `w:pict`、0 VML shape、0 textbox | 同上 |
| 修订/批注 | 0 `w:ins`、0 `w:del`、0 `commentReference` | 同上 |
| 目录字段 | 无 TOC / PAGEREF | 同上 |
| 手工分页符 | 30 | 同上 |
| 缓存分页标记 | 0 `lastRenderedPageBreak` | 同上 |
| 流程图/图片 | 无嵌入图；主线 DAG 等以文字/表格表示 | `02_docx_body.txt` §14.2 |
| 页数/页码 | **不可靠**；未取得可信页码 | [`06_page_map_attempt.md`](06_page_map_attempt.md) |

**没有只根据文件名推断内容**：所有结论都能回到 `P####` 或 `TABLE ##`。例如：

- 六层架构：§5.2 / TABLE 21（P0096–P0097）。
- 六角色：§10.1 / TABLE 40（P0254–P0256）。
- T0/T1/T2：§15.2 / TABLE 56（P0379）。
- G0–G7：§15.3 / TABLE 57（P0381）。

## 5. 版本与日期证据

### 5.1 版本冲突 C-001

| 位置 | 原文 | 指向 |
|---|---|---|
| 文件名 | `..._v4.3.1_...docx` | v4.3.1 |
| 封面 | `ResearchFlow 3.1 v4.3.0` | v4.3.0 |
| 封面 | `v4.3.0 · 全面升级版` | v4.3.0 |
| 页眉 | `ResearchFlow 3.1  |  策划书与工程开发基线 v4.3.0` | v4.3.0 |
| 页脚 | `ResearchFlow 3.1 · 全面升级版 ·` | 无版本 |
| 正文升级说明 | `v4.3.0 的实质升级` | v4.3.0 |
| 文档控制表 | `策划书版本 | v4.3.0 全面升级版开发基线` | v4.3.0 |
| core 属性 title | `ResearchFlow 3.1 项目策划书与工程开发基线 v4.3.0` | v4.3.0 |
| 附录 I | `《ResearchFlow 3.1 v4.3.0 全面升级版》` | v4.3.0 |
| 文档内计数 | `v4.3.1` = 0；`v4.3.0` = 6 + 1 + 1 | v4.3.0 |

完整证据：[`07_version_strings.txt`](07_version_strings.txt)。

### 5.2 日期

| 来源 | 值 | 可用性 |
|---|---|---|
| 文档控制表 | `2026 年 11 月 6 日` | 可引用为“文档声明日期” |
| 正文 P0325 | `资料核验基准日期：2026-11-06` | 可引用 |
| 文件系统 | `2026-11-06T18:43:34+08:00` | 可引用为文件时间 |
| DOCX core `created/modified` | `2013-12-23T23:15:00Z` | **不可用**（模板默认值） |
| DOCX app `Pages/Words/Characters` | `1/0/0` | **不可用**（生成残留） |

### 5.3 版本影响

版本未定会影响：需求基线、六层架构/StateMachine/证据规则、Schema/API/错误码、T0/T1/T2 范围、G0 冻结、既有文档引用。**当前无业务代码，尚未产生运行时影响。**

### 5.4 方案与推荐

| 方案 | 做法 | 推荐度 |
|---|---|---|
| A | 用户确认“内部 v4.3.0 是内容基线，v4.3.1 只是文件名标签”；无另一份 v4.3.1 | **条件推荐**（仅在确认无 v4.3.1 内容时） |
| B | 用户提供真正的 v4.3.1 原件/差异说明；以 v4.3.1 为基线并重新评审 | **若存在 v4.3.1 内容则推荐** |
| C | 直接把文件名当 v4.3.1，不核内容 | **不推荐**（与 8 处以上证据冲突） |
| D | 暂不裁决，保持 `BLK-002` OPEN | **当前默认** |

推荐理由：现有证据只能证明不一致，不能证明哪一个是最终版；G0 冻结前必须由用户书面确认。详见 [`../reference/CONFLICT_REPORT.md`](../../reference/CONFLICT_REPORT.md) §1。

## 6. 交付文档

### 6.1 来源与冲突

| 文档 | 内容 |
|---|---|
| [`../reference/SOURCE_REGISTER.md`](../../reference/SOURCE_REGISTER.md) | 唯一权威原件、字段完整登记、版本证据、缺失资料、敏感信息/Git/解析完整性、禁止第二份副本 |
| [`../reference/CONFLICT_REPORT.md`](../../reference/CONFLICT_REPORT.md) | C-001–C-007、原文/位置、涉及模块、影响、方案、推荐、待用户回答 |

### 6.2 知识/架构文档

| 文档 | 内容 | 主要来源 |
|---|---|---|
| [`../PROJECT_OVERVIEW.md`](../../PROJECT_OVERVIEW.md) | 定位、问题、三主线、四类面/六层、角色、范围、T0/T1/T2、G0–G7、指标、现状 | §1、§3–5、§10、§15、§17–18 |
| [`../ARCHITECTURE.md`](../../ARCHITECTURE.md) | 六层架构、组件分离、状态机、E0–E3、L1–L3、Gate/凭证、JCS/Ed25519/Merkle、DC/SPA/VAS、数据流、资源预算、G0 缺口 | §5–9、§15、附录 D/F |
| [`../GLOSSARY.md`](../../GLOSSARY.md) | 术语、缩写、三组易混命名、易错表述 | §5–12、§15、附录 D/F |
| [`../DEVELOPMENT_WORKFLOW.md`](../../DEVELOPMENT_WORKFLOW.md) | 来源优先级、会话启动、阶段流程、T0 顺序、门禁、测试/证据、DoD、Git、状态同步、飞书缺口 | §6.7、§15、附录 I/J；AGENTS |
| [`../MEMORY_GUIDE.md`](../../MEMORY_GUIDE.md) | 记忆分层、读写顺序、状态词汇、卫生规则、交接模板 | AGENTS §6–7；memory-handoff Skill |
| [`../SKILL_CATALOG.md`](../../SKILL_CATALOG.md) | 九个 Skill 三态、阶段 7 复核、`T-SKILLS-001` DONE | 阶段 5 证据；阶段 7 会话 |
| [`../MCP_CATALOG.md`](../../MCP_CATALOG.md) | context7 server/tools、配置、能力矩阵、限制、信任边界 | 阶段 6 证据；app.asar README |
| [`../SECURITY_POLICY.md`](../../SECURITY_POLICY.md) | 威胁模型、不变量、权限、证据完整性、密钥、网络/数据、2C、事件处理 | §3.4、§7、§9、§10.2、§17；AGENTS |

每份文档都标注了来源章节/段落锚点，并区分 `[策划书]` / `[飞书]` / `[Harness]` / `[建议]` / `[待确认]` / `[现状]`。飞书资料未落地，文档明确写“未引用其内容”，没有把建议写成冻结决策。

## 7. 状态同步结果

### 7.1 变更

| 项 | 变更 |
|---|---|
| `T-SKILLS-001` | `IN_REVIEW` → **`DONE`**（阶段 5 已验收；阶段 7 状态同步） |
| `T-MCP-001` | 保持 **`DONE`** |
| `T-DOCS-001` | 新增，**`IN_REVIEW`**（阶段 7 资料接手，等待验收） |
| `BLK-002` | 保持 **`OPEN`**；严重度 MEDIUM → **HIGH**（阻断 G0）；描述补充版本证据；affected_tasks=`T-DOCS-001` |
| `BLK-001` | 不变（OPEN/MEDIUM） |
| G0–G7 | **全部不变**，仍 `NOT_STARTED` |
| `last_verified_commit` | 仍 `null` |
| `current_phase` / `current_milestone` | 仍 `WORKSTATION_SETUP` / `M0_GOVERNANCE_BASELINE` |

> 说明：新增 `T-DOCS-001` 是为了让阶段 7 的交付有研发看板记录；不改变 G0–G7，也不把阶段 7 标成已验收。如果用户不希望新增任务，可在验收时要求移除。

### 7.2 命令与结果

```powershell
$py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'

& $py scripts/state_sync.py validate
# OK: project_state.json 校验通过。阶段=WORKSTATION_SETUP，任务=3，门禁 PASS=0/8，阻塞=2。
# exit 0；日志 10_state_sync_validate.log

& $py scripts/state_sync.py render
# 已生成 docs/PROJECT_STATE.md sha256=5ecce6ed...
# 已生成 docs/IMPLEMENTATION_STATUS.md sha256=61eaa7bb...
# exit 0；日志 11_state_sync_render.log

& $py scripts/state_sync.py check
# [OK] 两个生成文件与 project_state.json 逐字节一致
# exit 0；日志 12_state_sync_check.log
```

## 8. 验证命令与结果

| 验证 | 命令 | 结果 | 日志 |
|---|---|---|---|
| DOCX 只读抽取 | `& $py docs/verification/stage7/extract_docx.py` | `DOCX_EXTRACT=OK`；754 段 / 80 表；exit 0 | `00_extract.log` |
| 版本字符串计数 | `& $py docs/verification/stage7/verify_version_strings.py` | `VERSION_EVIDENCE=OK`；`v4.3.1` 文档内 0；exit 0 | `07_version_strings.log`、`07_version_strings.txt` |
| 文件哈希 | `Get-FileHash ... -Algorithm SHA256` | `9E54168F…CCB3A`；111,209 字节 | `09_inventory.log` |
| 资料清单 | `Get-ChildItem` + hash | 根目录仅 1 份 DOCX；inbox 仅 `.gitkeep` | `09_inventory.log` |
| 状态同步 | `validate / render / check` | 均 exit 0；两文件逐字节一致 | `10`–`12` 日志 |
| 秘密扫描 | `& $py docs/verification/stage7/scan_secrets.py` | 21 个文件、0 命中、`SECRET_SCAN=PASS`、exit 0 | `13_secret_scan.log` |
| Markdown 链接 | `& $py docs/verification/stage7/check_links.py` | 232 个相对链接、0 断链、`LINK_CHECK=PASS`、exit 0 | `14_link_check.log` |
| 任务证据路径 | `& $py docs/verification/stage7/check_task_evidence.py` | 57 项、0 缺失、`TASK_EVIDENCE=PASS`、exit 0 | `15_task_evidence_check.log` |
| 编码/换行 | `& $py docs/verification/stage7/check_encoding.py` | 16 个文件、UTF-8 无 BOM、0 CR、末尾 LF、`ENCODING=PASS`、exit 0 | `17_encoding_check.log` |
| 回归测试（未完成） | `& $py -m unittest discover -s tests -v` | `Ran 23 tests` / `FAILED (errors=43)`；全部为临时目录 `PermissionError`，无断言失败；**不计为通过** | `18_unittest.log`、`18_unittest_attempt.md` |
| 最终非回归清单 | PowerShell inventory | DOCX 111,209 字节 / `9E54168F…CCB3A` / `MATCH=True`；项目内仅 1 份 DOCX/PDF；0 commit；无 `.venv`；无业务代码 | `16_final_inventory.log` |
| 页码尝试 | `powershell -File ...docx_page_map.ps1` | 未取得页码；未修改文档 | `06_page_map.log`、`06_page_map_attempt.md` |

## 9. 限制与未测

1. **页码不可用**：DOCX 无 TOC/缓存分页；`Pages=1` 失效；Word COM 启动阻塞。引用改用 § + `P####` / `TABLE ##`。
2. **飞书资料缺失**：未读取、未引用；方法论只依据 AGENTS、策划书附录 I 与项目实践。
3. **赛事通知/章程缺失**：§1.3 的赛事信息无法独立核验；未推断评分权重、页数、匿名、AI/IP。
4. **真正的 v4.3.1 未知**：文档内无 v4.3.1 字符串；无法证明是否存在另一版内容。
5. **未做 ResearchFlow 运行时测试**：没有业务代码、没有 `.venv`、没有依赖；本阶段只做文档/资料验证。
6. **state_sync 23 项回归测试未完成（环境阻塞）**：两次尝试均因 DSH 沙箱临时目录 ACL 拒绝（43 个 `PermissionError`，无断言失败）而中止；`state_sync validate/render/check` 均通过。未修改测试、expected 或阈值；详见 [`18_unittest_attempt.md`](18_unittest_attempt.md) 与 [`18_unittest.log`](18_unittest.log)。
7. **未做 OCR/页面渲染**：文档无嵌入图片/绘图；80 表已文本化；不需要图像读取。若未来加入扫描件/图片，需另做页面读取。
8. **未做 Word/LibreOffice 视觉排版核对**：无法确认封面/表格在渲染后的分页与视觉效果；文本内容已完整抽取。

## 10. 验收清单

| 检查 | 状态 | 证据 |
|---|---|---|
| 资料实际位置已报告 | ✅ | 本报告 §3；SOURCE_REGISTER |
| 未复制/移动/重命名/覆盖 DOCX | ✅ | 原件哈希不变；inbox 仍空 |
| 逐份阅读，不只按文件名推断 | ✅ | 754/754 段、80/80 表；`02`/`05` |
| DOCX 表格/图/流程图检查 | ✅ | 0 媒体；80 表全展开；无嵌入图 |
| 版本/日期逐项登记 | ✅ | SOURCE_REGISTER §3；CONFLICT_REPORT §1 |
| 未自行认定版本生效 | ✅ | BLK-002 OPEN；C-001 |
| 资料冲突有原文/位置/影响/方案/推荐 | ✅ | CONFLICT_REPORT |
| SOURCE_REGISTER 含全部要求字段 | ✅ | SOURCE_REGISTER §2 |
| 写明“禁止再产生第二份策划书副本” | ✅ | SOURCE_REGISTER §0 |
| 八份知识文档建立/更新 | ✅ | 本报告 §6.2 |
| 文档标注来源章节/页码 | ✅（页码不可用，使用 § + P/Table 锚点） | 各文档来源表 |
| 区分策划书/飞书/Harness/建议/待确认 | ✅ | 各文档标注 |
| 未把 T1/T2 写成 T0 已完成 | ✅ | PROJECT_OVERVIEW §7–10；ARCHITECTURE §9 |
| `T-SKILLS-001` DONE | ✅ | project_state.json |
| `T-MCP-001` 保持 DONE | ✅ | project_state.json |
| G0–G7 未改 | ✅ | project_state.json；PROJECT_STATE.md |
| `BLK-002` 保持 OPEN | ✅ | project_state.json |
| 未 commit / 未建 .venv / 未装依赖 / 未开发代码 | ✅ | 09_inventory.log；本报告 §2 |
| 备份保留 | ✅ | `cordis.patch.yml.bak-20261108-stage6` 未删除 |

## 11. 待用户确认

1. **`BLK-002`**：内部 v4.3.0 是否为最终内容基线？`v4.3.1` 是否只是文件名标签？是否存在另一份 v4.3.1？
2. 是否验收阶段 7，并批准进入阶段 8（G0 准备/规格冻结）？
3. 是否保留新增的 `T-DOCS-001` 研发看板记录？
4. 飞书 AI 开发说明是否需要补入 `docs/reference/inbox/`？
5. 赛事通知原图/完整章程是否需要补入？
6. 是否允许把 DOCX 的忽略规则写入 `.gitignore`（当前只登记“不纳入 Git”，未改 `.gitignore`）？

## 12. 下一步（等待批准，不自动执行）

1. 用户回答 `BLK-002` 的最小问题；如确认 v4.3.0，则更新来源登记与所有引用，关闭 BLK-002；如存在 v4.3.1，则按方案 B 重新评审。
2. 用户验收阶段 7；未批准前不进入阶段 8，不做 G0 冻结。
3. 批准阶段 8 后，按 G0 范围建立 contracts/Schema/状态机/错误码；仍不提前开发 T0 业务闭环。

## 13. 相关文件

- [`../../reference/SOURCE_REGISTER.md`](../../reference/SOURCE_REGISTER.md)
- [`../../reference/CONFLICT_REPORT.md`](../../reference/CONFLICT_REPORT.md)
- [`../../PROJECT_OVERVIEW.md`](../../PROJECT_OVERVIEW.md)
- [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)
- [`../../GLOSSARY.md`](../../GLOSSARY.md)
- [`../../DEVELOPMENT_WORKFLOW.md`](../../DEVELOPMENT_WORKFLOW.md)
- [`../../MEMORY_GUIDE.md`](../../MEMORY_GUIDE.md)
- [`../../MCP_CATALOG.md`](../../MCP_CATALOG.md)
- [`../../SECURITY_POLICY.md`](../../SECURITY_POLICY.md)
- [`../../SKILL_CATALOG.md`](../../SKILL_CATALOG.md)
- [`../../state/project_state.json`](../../state/project_state.json)
- [`../../state/runtime_states.md`](../../state/runtime_states.md)
