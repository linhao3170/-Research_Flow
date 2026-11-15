# ResearchFlow Goal 自动记忆与交接收尾

适用于 Goal 1、Goal 2、Goal 3。启动和续接时读取本文件，并按需加载 `researchflow-memory-handoff` Skill。项目文件是跨会话接手依据；聊天上下文、宿主记忆和 Goal 状态不能替代文件更新。

## 自动执行时机

- 每完成一个可验收切片或工作包，保存一个可续接检查点。
- 正常结束会话、准备上下文交接、遇到外部阻塞或预算接近上限时，在仍有执行机会与预算的情况下先完成收尾。
- 调用 Goal `complete` 前必须完成最终收尾；不得只在回复中说“记忆已更新”。
- 已批准范围内的状态、日志、交接与稳定记忆同步自动执行，不再询问“是否更新记忆”。新架构决策仍走原审批流程。
- 用户明确要求立即停止时立即停止，不以收尾为由继续执行。崩溃、断电、强制终止可能来不及写入；恢复后核对最后检查点、Git 差异及真实日志，补齐遗漏，不假定上轮成功。

## 信息写入位置

| 信息 | 唯一职责位置 |
|---|---|
| 研发任务进度、门禁、阻塞及证据索引 | `docs/state/project_state.json`；按真实结果更新，不提前 DONE/PASS |
| 项目目标、范围及长期设计原因 | `docs/memory/project-context.md`；不复制当前阶段进度 |
| 已批准的稳定架构决策及其来源 | `docs/memory/architecture-decisions.md`，引用 ADR；不能用记忆代替批准 |
| 用户稳定偏好、可复用失败经验 | `docs/memory/feedback-and-lessons.md` |
| 已核实环境及版本 | `docs/memory/environment.md`；不保存凭据 |
| 资料来源及引用 | `docs/memory/references.md` |
| 记忆导航 | `docs/memory/Memory.md`；只在索引变化时更新 |
| 本批改动和验证记录 | `docs/CHANGELOG_DEV.md`；只追加 |
| 完成/未完成、下一动作与接手条件 | `docs/SESSION_HANDOFF.md`；最新条目置顶，保留历史 |
| 开发与产品 API 的累计成本 | `docs/verification/budget/`；不因 Goal 切换清零 |

只写已确认事实；未确认事项标“待核实”。不得把模型自述、未核验外部资料、临时进度、原始聊天、密钥、令牌或 Session 标识写入长期记忆。没有新增稳定事实时，交接注明“长期记忆已复核，本批无需修改”，不要为更新而改写文件。

## 固定收尾顺序

1. 按 Skill 前置要求检查 `state_sync.py check` 与 `check_docs_drift.py`，核对当前改动和证据。检查失败先定位并按既有授权处理；不得改状态来掩盖错误，也不反复运行相同失败命令空转。
2. 更新 `docs/state/project_state.json`。未完成项保留实际状态；无新增研发事实不虚构任务。不得用当前 HEAD 替换未经对应测试验证的 `last_verified_commit`。
3. 使用项目解释器依次执行下列命令，三条均须 exit 0：

   ```powershell
   $rfPy = 'D:\ResearchFlow-project\.venv\Scripts\python.exe'
   & $rfPy -B scripts/state_sync.py validate
   & $rfPy -B scripts/state_sync.py render
   & $rfPy -B scripts/state_sync.py check
   ```

   必须先核实解释器为 3.11.16/64 位；失效时按 AGENTS 指定的 uv 解释器处理。不得手改生成的 `PROJECT_STATE.md`、`IMPLEMENTATION_STATUS.md`。
4. 追加 CHANGELOG；在 SESSION_HANDOFF 顶部新增交接条目；然后更新有新增稳定事实的记忆子文件。相关历史结论失效时注明被取代原因与新证据，不删除历史日志。仅当有架构变化且获批时引用对应 ADR，否则说明“无架构变化”及理由。
5. 运行 `state_sync.py check` 和 `check_docs_drift.py`，核对本次新增本地引用、状态与交接一致性。记录真实命令、cwd、解释器、起止时间、耗时、退出码、权限模式和日志路径。已知 WARNING 写明原因，不能隐瞒 ERROR。
6. 交接明确：本批完成/未完成、当前切片、批准范围及来源、真实测试/负例、证据、A/B/C 遗留项、下一最小动作、待决事项、权限/环境限制、Git 分支及未提交改动、两项累计预算及来源。检查哪些长期记忆需要更新，并列出文件；无需更新的说明理由。

已有工作区、相同阶段证据及账本应增量续接；不重建整个记忆系统，不覆盖旧日志，不自动 commit/push，不触碰凭据或全局配置。

## Goal 完成前置检查

- 本批文件已真实写入并可重新读取；进度只由状态 JSON 维护，相关稳定记忆已核对。
- 状态同步、生成文档、漂移检查及本阶段要求的验证均有真实结果。
- CHANGELOG 和最新交接可定位，下一会话可据此接手；预算及环境限制没有遗漏。
- 主任务书的全部必需出口已满足。收尾成功不等于业务验收通过。

任一必需项未完成，不得将 Goal 标 `complete`。保存实际缺口和续接位置，并按宿主当前工具规则处理 Goal 状态；不擅自恢复用户暂停的 Goal。最终回复简述记忆更新文件、检查结果、未完成项和下一步即可。
