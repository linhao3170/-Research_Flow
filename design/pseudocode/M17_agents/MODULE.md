# M17 · Agent Gateway 与六角色（P8）

> 阶段：P8「六角色与知识库」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：角色身份四元组、§10.2 权限矩阵 25 格、九类消息与方向、工具唯一出口、统一 LLM 客户端、角色调度、六个角色类与 role_off、CPG 五项指标
> 不覆盖：Verifier 裁决与签发（M08–M12）、图审批（M04）、调度（M13）、HTTP（P10）、知识库本体（M18）
> 前置：P1–P7 设计产物存在；验收状态以 `docs/state/project_state.json` 为准（P1–P8 设计件已验收；P9/P10 `BLOCKED`）；**T0 尚未验收**（G1–G7 `NOT_STARTED`，仅 WP-01/WP-02 DONE）
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码
> FR 归属：`FR-012`（六角色消息契约与权限）在追踪矩阵中是 **T1 / G2+G5**；本阶段不宣称 G2/G5 已通过

## 0. T0 未验收时的交付口径（先读）

用户指令：「本阶段属 T1，若 T0 尚未验收，只写接口不写行为。」当前 T0 全链路**不可用**，因此：

1. **M17 在 T0 没有行为**：`agents` feature flag 的 T0 强制值是 `false`（M03 `feature_flags.T0_FORCED`）。
   `AgentGateway.dispatch()` 的第一步就是拒绝：`FEATURE_FLAG_NOT_PERMITTED` /
   `AGENTS_DISABLED_IN_THIS_TIER`，**在调模型、调工具之前**返回。
2. **所有外部效应都在端口后面**：模型传输、工具执行、审计、E1 写入、调度提交、证据查找
   全部是 `Protocol`；端口缺失时模块拒绝服务（fail-closed），不内置默认实现。
3. **指标只定义分子分母，不填数值**：CPG、R1–R3、role_off 对照的数值必须来自真实运行；
   本文件不给出任何“已测得”的数字，也不把策划书目标值写成结果。
4. **没有接入 `researchflow/`**：本阶段没有 import、没有建表、没有启动守卫；
   `agents=false` 的启动拒绝由 M03/启动守卫承担（P10），M17 不重复实现。

## 1. 目标

把「多智能体有职责、有权限、有证据引用，但改不了任何状态」写成可复核的五段：

1. **身份可复算**：角色 = `contract_version + system policy + tool allowlist + context scope` 四元组；
   四项任何一项变化都必须得到不同身份摘要；
2. **权限逐格**：§10.2 的 5 行 × 5 列 = 25 格全部有 `CellGrant`，Agent 的「写状态/证据」与「签名」
   两列恒 `NONE`，且拒绝分支可断言；
3. **消息恰好九类**：类型、方向、必填字段、证据引用存在性都可在消息层拒绝；
4. **出口唯一**：Agent 的工具调用只经 `ToolGateway`；未注册/非白名单/参数越界/超时/无审计全部拒绝；
5. **关闭可观测**：六个角色都能显式关闭，关闭后有定义的确定性补位与观测指标，
   且**不存在**“单 Agent 全包”的路径。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `agents/contracts.py` | 身份四元组、25 格权限矩阵、六角色规格、禁止能力、静态守卫 | 891 | 完成（伪代码） |
| `agents/messages.py` | 九类消息 payload、方向表、严格解析、证据存在性、重放防护 | 1146 | 完成（伪代码） |
| `agents/tool_gateway.py` | 工具注册表、参数 Schema、预算、审计、E1 事件、唯一执行出口 | 838 | 完成（伪代码） |
| `agents/llm_client.py` | Prompt 信任边界、预算、缓存、超时、fallback | 646 | 完成（伪代码） |
| `agents/gateway.py` | 上下文装配、输出校验、审计、只投稿、九种终态 | 976 | 完成（伪代码） |
| `agents/roles.py` | 六角色类、输出语义校验、role_off 契约、关闭注册表 | 671 | 完成（伪代码） |
| `agents/cpg.py` | CPG 建图与五项指标（分子/分母/值） | 401 | 完成（伪代码） |

计数口径：物理行数（`text.count("\n") + 1`），与 P3–P7 一致。
`>800` 行文件按 PHASE_RULES §5 第 2 档登记完整函数索引；本模块四个：

### 2.1 `contracts.py`（891 行 / 36 个定义）

| 行号 | 类/函数 | 职责（一句话） | 依据 |
|---:|---|---|---|
| 82 | `Axis` | §10.2 五列权限轴 | §10.2 TABLE 41 |
| 101 | `RoleId` | 六个逻辑角色 | §10.1 TABLE 40 |
| 112 | `PrincipalKind` | §10.2 五类主体（只这五行） | §10.2 |
| 131 | `GrantKind` | 单元格授权形态枚举（`NONE` 表示禁止） | §10.2 |
| 153 | `CellGrant` | 一格：主体×轴→授权+原文短语+实现归属 | §10.2 |
| 164 | `CellGrant.__post_init__` | 原文不得空；PROPOSAL_ONLY 必须带角色范围 | §10.2 |
| 208 | `_build_matrix` | 25 格装配成只读矩阵，缺格/重复格即失败 | §10.2 |
| 232 | `matrix_cell` | 取一格；不存在即抛（无默认允许） | §10.2 |
| 240 | `ToolAccess` | Agent 工具访问类别，故意没有 SIDE_EFFECT | §10.1 禁止权限 |
| 249 | `AgentToolSpec` | 工具目录项（schema/超时/结果类型） | §5.7 工具契约 |
| 320 | `is_forbidden_tool` | 禁用名/前缀判定 | §10.2；E.3 TOOL_NOT_ALLOWLISTED |
| 331 | `DatasetScope` | 数据读取范围（无 ALL 档） | §10.1 Data |
| 340 | `ContextScope` | 知识类型/数据范围/证据等级/token 上限 | §10.1；§10.2「按角色受限」 |
| 348 | `ContextScope.__post_init__` | 范围越界/自相矛盾即拒绝 | §10.1 |
| 360 | `ContextScope.digest_payload` | 身份摘要的确定性输入 | §10.1 |
| 373 | `Prohibition` | §10.1 禁止项的结构化枚举 | §10.1 |
| 412 | `RoleSpec` | 角色职责/输入/输出/禁止/消息/工具/策略 | §10.1 |
| 425 | `RoleSpec.__post_init__` | 工具必须在目录、禁止项非空、消息已注册 | §10.1；§6.3 |
| 455 | `_policy` | 拼装 system policy 正文（身份哈希输入） | §10.1 |
| 614 | `system_policy_hash` | 角色策略 SHA-256 | 05 §1.3 |
| 625 | `RoleIdentity` | 身份四元组 | §10.1 首段 |
| 634 | `RoleIdentity.__post_init__` | 版本/哈希/白名单排序与禁用能力校验 | §10.1；§10.2 |
| 656 | `RoleIdentity.digest_payload` | 四元组的确定性投影 | §10.1 |
| 666 | `RoleIdentity.identity_digest` | 身份摘要（本地/审计用，非契约） | §10.1 |
| 672 | `identity_for` | 按规格装配身份，不接受自报白名单 | §10.1 |
| 688 | `AuthorizationDecision` | 授权判定结果（允许/拒绝+码+原因） | §10.2 |
| 699 | `AuthorizationDecision.__post_init__` | 允许不得带拒绝原因，拒绝必须带原因 | §10.2 |
| 705 | `AuthorizationDecision.as_detail` | 审计细节（无 prompt/密钥） | NFR-02 |
| 718 | `_deny` | 统一拒绝构造 | §10.2 |
| 722 | `authorize_agent` | 六角色×五轴唯一授权函数（五步） | §10.2 |
| 786 | `assert_matrix_matches_10_2` | 验收判据 1：25 格逐格对表 | 本阶段验收 1 |
| 807 | `assert_agent_cannot_write_or_sign` | Agent 写/签两列恒拒绝 | §10.2 R02 |
| 826 | `assert_identity_components` | 四元组齐全、六角色身份不碰撞 | §10.1 |
| 850 | `assert_agent_tools_side_effect_free` | 目录无副作用工具 | §10.1 |
| 865 | `assert_prohibition_enforcement` | 每个禁止项都有（位置/码/原因） | §10.1 |
| 887 | `assert_no_capability_export` | 本模块不导出写/签/迁移符号 | AGENTS §4 |

### 2.2 `messages.py`（1146 行 / 77 个定义）

| 行号 | 类/函数 | 职责（一句话） | 依据 |
|---:|---|---|---|
| 99 | `Endpoint` | 九个消息端点（六角色+调度/验证/状态机） | §6.3 |
| 125 | `MessageType` | 恰好九类消息 | §6.3 TABLE 27 |
| 140 | `Direction` | 一条方向约束（发送方/接收方/是否提案） | §6.3 |
| 149 | `Direction.__post_init__` | 方向不得为空/自环，必须保留原文 | §6.3 |
| 199 | `MessageMeta` | 信封：消息身份+关联+契约版本 | §6.3；OQ-P8-02 |
| 210 | `MessageMeta.__post_init__` | 版本必须当前、task_id 形态、无空白 | §6.3 |
| 226 | `ProgressStage` | PROGRESS 七阶段（仅展示） | §6.3 |
| 238 | `FindingSeverity` | FINDING 三级严重度 | §6.3 |
| 246 | `PatchOpKind` | 图补丁四种操作（无 REMOVE_NODE） | §8.9 |
| 255 | `EscalationReason` | 升级原因八类 | §6.3 |
| 266 | `EscalationNeed` | 升级所求六类 | §6.3 |
| 275 | `_require_text` | 非空文本校验 | §6.3 |
| 281 | `TaskAssign` | 调度派活（task/node/version/inputs/limits） | §6.3 R02 |
| 290 | `TaskAssign.__post_init__` | 引用形态、限额键与取值、workers≤2 | §6.3；05 §2.1 |
| 311 | `Progress` | 仅展示进度；`AFFECTS_STATE=False` | §6.3 R03 |
| 320 | `Progress.__post_init__` | percent∈[0,100]、stage 合法 | §6.3 |
| 330 | `EvidenceRef` | 引用一条证据（id+kind） | §6.3 R04 |
| 336 | `EvidenceRef.__post_init__` | ev_<uuid>、kind∈冻结 7 类 | §6.3；05 §4.5 |
| 344 | `FindingItem` | 一条机器可读发现 | §6.3 R05 |
| 351 | `FindingItem.__post_init__` | code 标识符、statement 非空 | §6.3 |
| 358 | `Finding` | 发现集合（至少一条证据） | §6.3 R05 |
| 366 | `Finding.__post_init__` | findings 非空/不重码、confidence、证据非空 | §6.3；DEC-M17-04 |
| 387 | `GraphOp` | 图补丁一步操作 | §8.9 |
| 397 | `GraphOp.__post_init__` | 四种 op 的字段组合校验 | §8.9 |
| 423 | `GraphPatch` | 补丁（base 版本 + ops） | §8.9 |
| 429 | `GraphPatch.__post_init__` | base≥1、ops≤32 | §8.9 |
| 439 | `ExpectedCost` | 提案预期成本 | §6.3 R06 |
| 446 | `ExpectedCost.__post_init__` | token/wall/node 取值 | §6.3 |
| 456 | `PlanProposal` | Planner 计划提案 | §6.3 R06 |
| 463 | `PlanProposal.__post_init__` | rationale≥10 | §6.3 |
| 468 | `RecoveryPlanRef` | 已冻结恢复计划的引用 | §6.3 R07；ADR-004 |
| 475 | `RecoveryPlanRef.__post_init__` | plan_hash 形态、格式版本 1.0 | ADR-004 |
| 485 | `RecoveryProposal` | Recovery 提案 | §6.3 R07 |
| 494 | `RecoveryProposal.__post_init__` | 受影响集合含失败节点、skip 必须空 | §6.3；§8.4 |
| 511 | `VerifyRequest` | 只请求验证 | §6.3 R08 |
| 518 | `VerifyRequest.__post_init__` | report_id 形态、checks 非空不重 | §6.3 |
| 532 | `Verdict` | Verifier→StateMachine 的裁决 | §6.3 R09 |
| 541 | `Verdict.__post_init__` | 四态、l3 四态、凭证三条件 | §6.3；05 §9.6 |
| 561 | `Verdict.signs_certificate` | 是否指向凭证签发 | 05 §9.6 |
| 567 | `Escalate` | 升级（原因/需要/阻塞证据） | §6.3 R10 |
| 574 | `Escalate.__post_init__` | needs 非空不重、证据 id 形态 | §6.3 |
| 599 | `payload_type` | 消息类型→payload 类 | §6.3 |
| 604 | `parse_payload` | 公开 payload 解析入口 | §6.3 |
| 613 | `AgentMessage` | 信封+payload 的完整消息 | §6.3 |
| 620 | `AgentMessage.message_type` | 从 payload 推导类型（不接受自报） | §6.3 |
| 626 | `AgentMessage.__post_init__` | 方向检查 + task_id 一致性 | §6.3 |
| 639 | `message_digest` | 消息摘要（去重/审计） | §6.3 |
| 655 | `payload_to_mapping` | payload→可审计字典 | NFR-02 |
| 669 | `to_mapping` | 整条消息→字典 | NFR-02 |
| 691 | `_strict_keys` | 键集合严格相等（未知/缺失拒绝） | §6.3 |
| 697 | `_texts` | 字符串数组校验 | §6.3 |
| 703 | `_ints` | 整数映射校验（bool 拒绝） | §6.3 |
| 714 | `_parse_payload` | 九类 payload 逐层严格解析 | §6.3 |
| 836 | `parse_message` | 从外部输入严格解析整条消息 | §6.3 |
| 880 | `ProtocolViolation` | 一条协议违规（只追加） | E.3；附录 E.4 |
| 889 | `ProtocolViolation.__post_init__` | task/reason 非空 | 附录 E.4 |
| 894 | `EvidenceLookupPort` | 只读证据查找端口 | 05 §4.4 |
| 897 | `EvidenceLookupPort.exists` | 证据是否存在 | 05 §4.4 |
| 899 | `EvidenceLookupPort.kind_of` | 证据 kind | 05 §4.5 |
| 901 | `EvidenceLookupPort.level_of` | 证据等级 | 05 §4.2 |
| 904 | `ViolationSinkPort` | 违规接收端 | 附录 E.4 |
| 907 | `ViolationSinkPort.record` | 追加违规并返回 id | 附录 E.4 |
| 910 | `MessageRejected` | 消息拒绝异常（码/原因/字段路径） | E.3 |
| 913 | `MessageRejected.__init__` | 拼装拒绝原因 | E.3 |
| 924 | `ReplayVerdict` | 重放判定 NEW/DUPLICATE | 附录 E.4 |
| 929 | `ReplayGuard` | 任务内消息去重 | 附录 E.4 |
| 934 | `ReplayGuard.__init__` | 初始化去重表 | 附录 E.4 |
| 937 | `ReplayGuard.check_and_record` | 登记并判重；超上限 fail-closed | 附录 E.4 |
| 955 | `ValidatedMessage` | 校验通过的消息+摘要+引用数 | §6.3 |
| 964 | `_evidence_refs` | 收集 payload 中的证据引用 | §6.3 R04/R05/R10 |
| 975 | `MessageValidator` | 消息校验唯一入口 | §6.3 |
| 978 | `MessageValidator.__init__` | 注入证据/违规/重放端口 | §6.3 |
| 989 | `MessageValidator.validate` | 方向→角色→版本→证据→重放→VERDICT 六步 | §6.3；§10.2 |
| 1072 | `MessageValidator._reject_and_record` | 先记违规再拒绝；记录失败→审计失败 | 附录 E.4 |
| 1101 | `assert_exactly_nine` | 验收判据 2：恰好九类 | 本阶段验收 2 |
| 1116 | `assert_direction_table` | 方向表自洽/提案标记/VERDICT 方向 | §6.3 |
| 1137 | `assert_no_agent_verdict` | Agent 不能发 VERDICT | §10.1 Verification |

### 2.3 `tool_gateway.py`（838 行 / 61 个定义）

| 行号 | 类/函数 | 职责（一句话） | 依据 |
|---:|---|---|---|
| 72 | `ParamKind` | 五种参数类型 | §5.7 工具契约 |
| 80 | `ToolArgsInvalid` | 参数不合法（reason+字段路径） | E.3 |
| 83 | `ToolArgsInvalid.__init__` | 拼装参数错误 | E.3 |
| 91 | `ParamSpec` | 单个参数约束（无默认值） | §5.7 |
| 105 | `ParamSpec.validate` | 类型/范围/长度/枚举/数组校验 | §5.7 |
| 150 | `ToolArgsSchema` | 工具参数 Schema | §5.7 |
| 157 | `ToolArgsSchema.__post_init__` | 名称/参数名唯一 | §5.7 |
| 163 | `ToolArgsSchema.validate` | 先拒未知键，再拒缺失，再逐项 | §5.7；OQ-CT-08 |
| 181 | `RegisteredTool` | 已注册工具（spec+schema） | §5.7 |
| 188 | `RegisteredTool.__post_init__` | 无副作用、超时≤30、非禁用名 | §5.7 |
| 199 | `ToolRegistry` | 工具注册表 | §5.7 |
| 202 | `ToolRegistry.__init__` | 空表 | §5.7 |
| 205 | `ToolRegistry.register` | 唯一注册入口；重复/目录不符拒绝 | §5.7 |
| 216 | `ToolRegistry.resolve` | 取工具；未注册即抛 | §5.7 |
| 222 | `ToolRegistry.names` | 已注册名快照 | §5.7 |
| 226 | `_p` | 参数规格简写 | §5.7 |
| 295 | `build_default_registry` | 按目录装配注册表，缺 Schema 即失败 | §5.7 |
| 309 | `ToolAuditPort` | 审计端口（begin/finish） | 附录 E.4 |
| 312 | `ToolAuditPort.begin` | 开始审计，返回 audit_id | 附录 E.4 |
| 314 | `ToolAuditPort.finish` | 完成审计 | 附录 E.4 |
| 317 | `ClockPort` | 单调时钟+UTC 墙钟 | ENCODING_RULES §3 |
| 320 | `ClockPort.monotonic` | 单调秒 | ENCODING_RULES §3 |
| 322 | `ClockPort.utc_now_iso` | UTC RFC3339 | ENCODING_RULES §3 |
| 325 | `RunnerStatus` | 执行端四态 | M05 §6 |
| 333 | `RunnerOutcome` | 执行事实（退出码/超时/回收） | M05 §6 |
| 342 | `RunnerOutcome.__post_init__` | EXITED 必带退出码、TIMEOUT 必带原因 | M05 §6 |
| 349 | `ToolRunnerPort` | 唯一执行端口 | M05 §6 |
| 352 | `ToolRunnerPort.run` | 按超时执行并杀进程树 | M05 §6 |
| 356 | `ToolEvidenceEvent` | 交给 Collector 的 E1 事件 | 05 §4.5 |
| 372 | `ToolEvidenceEvent.__post_init__` | 只允许 E1/tool_invocation | 05 §4.5 |
| 379 | `ToolEvidencePort` | E1 提交端口 | 05 §4.5 |
| 382 | `ToolEvidencePort.submit` | 提交观测 | 05 §4.5 |
| 386 | `ToolAuditRecord` | 审计开始记录（只存 args_hash） | 附录 E.4 |
| 399 | `ToolAuditRecord.__post_init__` | 哈希形态、键不重复 | 附录 E.4 |
| 407 | `ToolAuditOutcome` | 审计完成记录 | 附录 E.4 |
| 416 | `ToolAuditOutcome.__post_init__` | 成功/失败字段一致性 | 附录 E.4 |
| 427 | `ToolBudget` | 节点/任务调用预算 | NFR-06 |
| 433 | `ToolBudget.__post_init__` | 正数且任务≥节点 | NFR-06 |
| 438 | `ToolBudgetTracker` | 调用计数 | NFR-06 |
| 441 | `ToolBudgetTracker.__init__` | 初始化计数 | NFR-06 |
| 446 | `ToolBudgetTracker.consume` | 扣额度，超限抛 429 语义 | NFR-06 |
| 456 | `ToolBudgetTracker.snapshot` | 计数快照 | NFR-06 |
| 462 | `ToolTimeout` | 超时/预算拒绝 | E.3 |
| 465 | `ToolTimeout.__init__` | 拼装拒绝 | E.3 |
| 477 | `ToolCallRequest` | 一次调用申请 | §10.2 |
| 488 | `ToolCallRequest.__post_init__` | 身份/标识/args 校验 | §10.2 |
| 499 | `ToolCallStatus` | 六种终态 | §10.2；附录 E.4 |
| 509 | `ToolCallResult` | 调用结果（含 value 扣留） | §10.2 |
| 522 | `ToolCallResult.__post_init__` | OK 无错误码；失败必带原因 | §10.2 |
| 530 | `ToolCallResult.as_detail` | 结构化细节 | NFR-02 |
| 546 | `ToolGateway` | 工具唯一出口 | §10.2 |
| 562 | `ToolGateway.__init__` | 注入端口；缺端口记装配错误 | §10.2 |
| 583 | `ToolGateway.invoke` | 十步：授权→注册→参数→预算→审计→执行→E1→审计 | §10.2；E.3 |
| 738 | `ToolGateway._now` | 单调起点 | ENCODING_RULES §3 |
| 741 | `ToolGateway._elapsed` | 毫秒耗时 | NFR-02 |
| 747 | `ToolGateway._hash_args` | 参数哈希（审计不存原值） | 数据最小化 |
| 751 | `ToolGateway._finish_audit` | 写完成审计；失败返回 False | 附录 E.4 |
| 769 | `ToolGateway._deny` | 统一拒绝结果 | E.3 |
| 798 | `assert_no_write_tools` | 目录无写/签/密钥工具 | §10.1 |
| 813 | `assert_timeout_bounds` | 超时范围与 Schema 同源 | §5.7 |
| 828 | `assert_single_egress` | 只有一个执行入口 | §10.2 |

### 2.4 `gateway.py`（976 行 / 62 个定义）

| 行号 | 类/函数 | 职责（一句话） | 依据 |
|---:|---|---|---|
| 122 | `NodeFacts` | 节点事实视图（非证据） | 05 §3 |
| 133 | `TaskFactsPort` | 任务/节点只读事实 | 05 §2/§3 |
| 136 | `TaskFactsPort.goal` | 任务目标 | 05 §2 |
| 138 | `TaskFactsPort.node` | 节点事实 | 05 §3 |
| 142 | `KnowledgeQuery` | 检索请求（ktypes 已收敛） | §11.4 |
| 151 | `KnowledgeQuery.__post_init__` | ktypes 非空、limit 范围 | §11.4 |
| 161 | `KnowledgeHit` | 检索命中（含 stale/可注入） | §11.4 |
| 176 | `KnowledgeHit.__post_init__` | 冲突不可注入、哈希形态 | §11.4 |
| 186 | `KnowledgeConflict` | 冲突通知（不给推荐） | §11.4 |
| 194 | `KnowledgeConflict.__post_init__` | 至少两个候选 | §11.4 |
| 200 | `KnowledgeResult` | 检索结果+E1 事件 id | §11.4 |
| 209 | `KnowledgePort` | 知识检索端口（仅 Agent 侧） | §11.4 |
| 212 | `KnowledgePort.retrieve` | 执行检索 | §11.4 |
| 216 | `EvidenceFacts` | 证据索引行（不含 payload） | 05 §4 |
| 225 | `EvidenceFacts.__post_init__` | 等级合法 | 05 §4.2 |
| 230 | `EvidenceIndexPort` | 只读证据索引 | 05 §4.4 |
| 233 | `EvidenceIndexPort.facts` | 单条证据事实 | 05 §4.4 |
| 235 | `EvidenceIndexPort.list_for_task` | 任务证据列表 | 05 §4.4 |
| 238 | `SchedulerPort` | 提案接收端（只有 submit） | §10.1 |
| 241 | `SchedulerPort.submit` | 提交提案 | §10.1 |
| 245 | `AgentAuditRecord` | 一次 Agent 运行审计 | 附录 E.4 |
| 263 | `AgentAuditRecord.__post_init__` | 版本/标识校验 | 附录 E.4 |
| 270 | `AgentAuditPort` | 运行审计端口 | 附录 E.4 |
| 271 | `AgentAuditPort.record` | 写审计并返回 id | 附录 E.4 |
| 274 | `ClockPort` | UTC 墙钟 | ENCODING_RULES §3 |
| 275 | `ClockPort.utc_now_iso` | 当前 UTC | ENCODING_RULES §3 |
| 282 | `AgentContext` | 装配后的上下文 | §10.2 |
| 296 | `AgentContext.knowledge_kinds` | 上下文知识类型 | §10.2 |
| 299 | `AgentContext.evidence_levels` | 上下文证据等级 | §10.2 |
| 303 | `ContextOverflow` | 上下文超预算 | NFR-06 |
| 306 | `ContextOverflow.__init__` | 拼装 429 语义 | NFR-06 |
| 313 | `ContextAssembler` | 上下文装配（范围/冲突/预算） | §10.2 |
| 323 | `ContextAssembler.__init__` | 注入任务/知识/证据端口 | §10.2 |
| 330 | `ContextAssembler.assemble` | 五步装配：事实→检索→冲突→证据→预算 | §10.2 |
| 403 | `ContextAssembler._task_facts_evidence` | 证据索引等级收敛 | 05 §4.4 |
| 411 | `OutputInvalid` | 模型输出不合法 | E.3 |
| 414 | `OutputInvalid.__init__` | 拼装 422 | E.3 |
| 422 | `_no_duplicate_keys` | 重复键即拒绝 | 05 §1.3 |
| 431 | `_reject_constant` | NaN/Infinity 即拒绝 | 05 §1.3 |
| 435 | `loads_strict` | 严格 JSON 解析 | 05 §1.3 |
| 445 | `_scan_forbidden_keys` | 递归扫描越权键 | §10.2 |
| 463 | `ParsedOutput` | 通过校验的输出+理由 | §6.3 |
| 470 | `OutputValidator` | 模型输出→消息 | §6.3 |
| 473 | `OutputValidator.__init__` | 注入消息校验器/时钟 | §6.3 |
| 478 | `OutputValidator.validate` | 六步：完成性→JSON→越权键→类型→理由→角色/证据 | §6.3；§10.2 |
| 532 | `OutputValidator._meta` | 生成信封（唯一 message_id） | §6.3 |
| 553 | `DispatchStatus` | 八种调度终态 | 本 §7 |
| 565 | `DispatchOutcome` | 一次调度结果 | 本 §7 |
| 581 | `DispatchOutcome.__post_init__` | 状态与字段一致性 | 本 §7 |
| 589 | `DispatchOutcome.as_log_fields` | 日志字段 | NFR-02 |
| 606 | `AgentGateway` | 角色调度器 | §10.1 |
| 620 | `AgentGateway.__init__` | 注入端口 | §10.1 |
| 644 | `AgentGateway.dispatch` | 九步：gate→role_off→身份→上下文→模型→输出→审计→投稿 | §10.1/§10.4 |
| 807 | `AgentGateway._refuse` | 模型调用前拒绝 | §10.2 |
| 821 | `AgentGateway._build_request` | 装配 PromptSection（信任分级） | §10.2；§11.4 |
| 859 | `AgentGateway._escalate` | Gateway 自身生成 ESCALATE | §6.3 R10 |
| 882 | `AgentGateway._record_audit` | 提交前写审计 | 附录 E.4 |
| 921 | `AgentGateway._record_violation` | 输出违规写入违规流 | 附录 E.4 |
| 931 | `_violation` | 构造 ProtocolViolation | 附录 E.4 |
| 946 | `assert_context_scope_only` | 上下文不越界、不含冲突知识 | §10.2 |
| 963 | `assert_no_write_surface` | 无状态/证据/签名写入口 | AGENTS §4 |

## 3. 边界（谁写什么；每条都有拒绝分支）

| 对象 | 唯一写者 | M17 的落点与拒绝 |
|---|---|---|
| `tasks.state` / `nodes.state` | **StateMachine**（M02） | M17 没有迁移端口；`authorize_agent(WRITE)` 对六角色恒 `TOOL_NOT_ALLOWLISTED`/`AGENT_WRITE_FORBIDDEN`；`assert_no_write_surface()` |
| `audit_log` | **StateMachine**（M02） | 工具/运行审计走 `ToolAuditPort`/`AgentAuditPort`；审计不可用时**不执行**（`TOOL_AUDIT_UNAVAILABLE`）或**不提交提案**（`AGENT_AUDIT_UNAVAILABLE`） |
| `evidence`（E0/E1/E2） | **Collector**（M07） | 工具调用只提交 `ToolEvidenceEvent(level=E1, kind=tool_invocation)`；E1 写失败 → `EVIDENCE_UNAVAILABLE` + 扣留 value |
| E3 / `VerificationReport` / `CompletionCertificate` | **Verifier**（M09–M12） | Agent 的 `SIGN`/`WRITE` 两列恒拒绝；`VERDICT` 方向表只允许 Verifier→StateMachine；`assert_no_agent_verdict()` |
| 图（节点/边/版本） | **M04**（经 StateMachine 批准） | 只有 Planner/Recovery 能出 Proposal；`authorize_agent(GRAPH_CHANGE)` 对其他角色拒绝；提案交 `SchedulerPort.submit` |
| 私钥/密钥材料 | 签名进程（M11） | 进程不加载私钥；工具目录无 `secret.*`/`private_key.*`；`READ_PRIVATE_KEY` 映射 403 `AGENT_SECRET_FORBIDDEN` |
| CPG 指标 | M17 只读统计 | CPG 不进入 Gate/Verifier；`CPG_IS_NOT_QUALITY`；`assert_not_quality_claim()` |

三条硬化：

1. **身份不可自报**：`identity_for(role)` 从 `ROLE_SPECS` 装配；`RoleIdentity.__post_init__` 校验策略哈希与工具白名单排序。
2. **出口不可绕过**：`ToolGateway` 是唯一执行入口；`assert_single_egress()`；未注册工具在授权与注册表两层都被拒。
3. **输出不可夹带**：模型输出只接受 `{proposal_type, rationale, payload}` 三键；递归扫描 `state/final_state/signature/private_key/...`，
   未知字段在 `parse_payload` 处直接拒绝。

## 4. 六角色契约（§10.1 逐行）

| 角色 | 职责 | 输入/输出 | 禁止（拒绝分支） | 可发消息 | 可申请工具 |
|---|---|---|---|---|---|
| Planner | 理解目标、选模板、提出 DAG | 目标/知识→ExperimentSpec、DAG Proposal | 写图（`AGENT_GRAPH_WRITE_FORBIDDEN`）、改状态、写证据 | PROGRESS、EVIDENCE_REF、PLAN_PROPOSAL、ESCALATE | knowledge.search、template.list |
| Data | 检查数据结构与质量 | 数据引用→画像请求/异常解释 | 改原始数据（`AGENT_RAW_DATA_WRITE_FORBIDDEN`）、写 E2（`AGENT_E2_WRITE_FORBIDDEN`） | PROGRESS、EVIDENCE_REF、FINDING、ESCALATE | knowledge.search、dataset.schema.read、dataset.profile |
| Experiment | 把配置映射为白名单模板请求 | Spec/模板→参数化执行请求 | 生成/执行任意代码（`AGENT_CODE_EXEC_FORBIDDEN`） | PROGRESS、EVIDENCE_REF、FINDING、ESCALATE | knowledge.search、template.list、template.parameterize |
| Analysis | 解释指标并提出重算请求 | 预测引用/指标定义→复核请求 | 自签指标证据（`AGENT_METRIC_SELF_SIGN_FORBIDDEN`）、决定 VERIFIED（`MESSAGE_DIRECTION_DENIED`） | PROGRESS、EVIDENCE_REF、FINDING、ESCALATE | knowledge.search、metrics.read、predictions.summary.read |
| Recovery | 诊断错误并提出恢复计划 | 失败事件/DAG/知识→Recovery Proposal | 直接改图（`AGENT_GRAPH_WRITE_FORBIDDEN`）、签 SPA（`AGENT_SPA_SIGN_FORBIDDEN`） | PROGRESS、EVIDENCE_REF、FINDING、RECOVERY_PROPOSAL、ESCALATE | knowledge.search、error.signature.read、recovery.plan.validate |
| Verification | 提出验证计划、解释差异与缺口 | 证据索引/规则→Verify Request | 写 E3（`AGENT_E3_WRITE_FORBIDDEN`）、签报告/凭证（`AGENT_SIGN_FORBIDDEN`） | PROGRESS、EVIDENCE_REF、FINDING、VERIFY_REQUEST、ESCALATE | knowledge.search、evidence.index.read、ruleset.read、verification.plan.draft |

角色身份四元组（`contracts.RoleIdentity`）：

| 组成 | 落点 | 变化后果 |
|---|---|---|
| `contract_version` | `ROLE_CONTRACT_VERSION="role-contract/1.0"` | 消息/Meta 版本不符 → `SCHEMA_INVALID`/`ROLE_CONTRACT_VERSION_MISMATCH` |
| system policy | 每角色固定正文 → `system_policy_hash` | 正文改动 → 身份摘要变化；运行审计必须重记 |
| tool allowlist | 排序元组，必须 ⊆ `AGENT_TOOL_CATALOG` | 越界或禁用名 → 身份构造失败 |
| context scope | 知识类型/数据范围/证据等级/token 上限 | 越界 → `ContextAssembler` 拒绝或裁剪（裁剪可观测） |

## 5. 权限矩阵逐格对齐（§10.2 TABLE 41）

矩阵常量：`contracts.EXPECTED_CELLS`（25 行）；`assert_matrix_matches_10_2()` 返回空列表才算对齐。

| 主体 | 读数据/知识 | 提交工具请求 | 改图 | 写状态/证据 | 签名 |
|---|---|---|---|---|---|
| 六个 LLM Agent | 按角色受限（`SCOPED_BY_ROLE`） | 白名单请求（`ALLOWLIST_ONLY`） | 仅 Planner/Recovery 提案（`PROPOSAL_ONLY`） | 否（`NONE`） | 否（`NONE`） |
| StateMachine | 受限（`SCOPED_BY_OWNER`） | 不适用 | 批准/拒绝（`APPROVE_OR_REJECT`） | 仅状态（`STATE_ONLY`） | 否 |
| Collector | 事件源（`EVENT_SOURCE`） | 不适用 | 否 | E0/E1/E2 追加写（`APPEND_E0_E1_E2`） | 否 |
| Verifier | 证据/原始数据（`EVIDENCE_AND_RAW`） | 独立验证执行（`INDEPENDENT_VERIFICATION`） | 否 | E3/报告追加写（`APPEND_E3_REPORT`） | 是（`SIGN_ALLOWED`） |
| Executor | 模板/只读数据（`TEMPLATE_READONLY`） | 运行白名单模板（`RUN_ALLOWLISTED_TEMPLATE`） | 否 | 不写证据库（`NONE`） | 否 |

Agent 行的三个拒绝事实（`assert_agent_cannot_write_or_sign()`）：

1. 六角色 × `WRITE` → `TOOL_NOT_ALLOWLISTED` + `AGENT_WRITE_FORBIDDEN`；
2. 六角色 × `SIGN` → `TOOL_NOT_ALLOWLISTED` + `AGENT_SIGN_FORBIDDEN`；
3. `GRAPH_CHANGE` 只对 Planner/Recovery 返回允许，且资源标记为 `PROPOSAL_ONLY`（不是“已改图”）。

## 6. 九类消息（§6.3 TABLE 27）

| # | 类型 | 方向 | 必填字段 | 拒绝点（可断言） |
|---:|---|---|---|---|
| 1 | `TASK_ASSIGN` | Scheduler→Agent | task_id,node_id,contract_version,inputs,limits | 版本不符/limits 键不齐/workers∉{1,2} → `SCHEMA_INVALID` |
| 2 | `PROGRESS` | Agent→Scheduler | node_id,stage,percent | percent 越界 → `SCHEMA_INVALID`；`AFFECTS_STATE=False` |
| 3 | `EVIDENCE_REF` | Agent→Scheduler | evidence_id,kind | id 不存在 → `EVIDENCE_REFERENCE_NOT_FOUND` + 违规；kind 不符 → `EVIDENCE_KIND_MISMATCH` |
| 4 | `FINDING` | Agent→Scheduler | node_id,findings,confidence,evidence_ids | 无证据 → `SCHEMA_INVALID`；任一无效应 id → `EVIDENCE_REFERENCE_NOT_FOUND` |
| 5 | `PLAN_PROPOSAL` | Planner→Scheduler | graph_patch,rationale,expected_cost | 非 Planner → `MESSAGE_DIRECTION_DENIED`；模板未登记 → `ROLE_OUTPUT_VIOLATION` |
| 6 | `RECOVERY_PROPOSAL` | Recovery→Scheduler | failed_node,affected_nodes,plan,skip_candidates,rationale | skip 非空 → `SCHEMA_INVALID`（T0/T1 无 DC/SPA） |
| 7 | `VERIFY_REQUEST` | Verification→Verifier | report_id,checks_requested,reason | 非规则集 check → `CHECK_NOT_IN_RULESET`；已签发 report_id → 拒绝 |
| 8 | `VERDICT` | Verifier→StateMachine | report_id,final_state,l3_status,gaps,certificate_id? | Agent 发送 → `MESSAGE_DIRECTION_DENIED`；凭证三条件不满足 → `SCHEMA_INVALID` |
| 9 | `ESCALATE` | 任意角色→Scheduler | reason,needs,blocking_evidence_ids | needs 空 → `SCHEMA_INVALID`；阻塞证据不存在 → `EVIDENCE_REFERENCE_NOT_FOUND` |

方向的“角色输出映射”说明（§10.1 的“输出”没有第十类消息）：

- Data 的“画像请求”= 工具 `dataset.profile`（E1）+ `FINDING`；
- Experiment 的“参数化执行请求”= 工具 `template.parameterize`（纯函数）+ `FINDING`；不新增第十类消息（§6.3 是封闭集合）；
- Analysis 的“重算请求”= `FINDING(code=recompute_*)`，实际重算仍由 Verifier L2 执行；
- 该映射登记为 `OQ-P8-03`，若用户要求专用消息，必须改 §6.3 且升契约 `MAJOR`。

## 7. 关键设计决定

### 7.1 身份四元组与“可复算”（DEC-M17-01）

`contract_version` 不是 `schema_version`：五份冻结契约没有角色字段，`role-contract/1.0` 是 P8 装配常量（`OQ-P8-01`）。
身份摘要只用于本地比对/审计，不作为签名载荷；跨实现复算必须重新约定。

### 7.2 权限矩阵“逐格”而不是“按行概括”（DEC-M17-02）

`EXPECTED_CELLS` 保留 §10.2 的**原文短语**（如“仅 Planner/Recovery 提案”），并逐格登记实现者。
非 Agent 四行的实现者写在 `implementer` 列，M17 **不实现**它们（`assert_no_capability_export()` 扫描导出符号）。

### 7.3 假 `evidence_id` 是协议违规，不只是 422（DEC-M17-03）

`MessageValidator` 对三类消息（EVIDENCE_REF / FINDING / ESCALATE）逐 id 查存在性：
不存在 → 先写 `ProtocolViolation`，再抛 `EVIDENCE_REFERENCE_NOT_FOUND`；违规记录失败 → `AUDIT_WRITE_FAILED`。
**不允许**“忽略该引用继续”或“补造记录”。

### 7.4 FINDING 必须带证据（DEC-M17-04）

`Finding.evidence_ids` 最少一条。没有证据的结论只能走 `ESCALATE`（`MORE_EVIDENCE`）。
理由：E0 声明不得满足执行类必检项；把“无证据发现”挡在消息层，避免下游误当证据。

### 7.5 工具出口十步与“审计先于执行”（DEC-M17-05）

顺序：授权 → 注册表 → 参数 Schema → 预算 → **审计开始** → 执行 → 超时/失败 → **E1 提交** → **审计完成** → 返回。
三个 fail-closed：审计开始失败则不执行；E1 失败则扣留 value；审计完成失败则 `AUDIT_DEGRADED` 且扣留 value。
超时上限 30s；预算默认值标 `PROPOSED`（`OQ-P8-06`）。

### 7.6 统一客户端：温度 0、缓存带版本、回退不伪造（DEC-M17-06）

- `temperature` 必须为 0（可复现）；非零直接拒绝。
- 缓存键含 `role + contract_version + system_policy_hash + prompt_hash + model_id + max_tokens`；
  缓存命中仍消耗 1 次调用额度，但 0 token。
- 模型不可用/超时/限流/未配置 → `FallbackReason` + 角色模板键；**不产生任何模型文本**；
  由 `roles.py` 的确定性回退决定行为（离线表单/规则/模板）。

### 7.7 上下文只给该看的（DEC-M17-07）

- 检索请求的 `ktypes` 就按角色收敛，不做“先取全量再过滤”；
- `CONFLICTED` 命中不进 prompt，只产生冲突通知 → gateway 升级；
- `stale_kb` 命中保留但打标，`requires_confirmation=True`，不得当默认值；
- 超预算先丢知识、再丢证据索引；系统策略与任务事实永不丢；丢了多少必须可观测
  （`AgentContext.dropped_knowledge/dropped_evidence`）。

### 7.8 输出校验：三键 + 越权键扫描（DEC-M17-08）

模型只能输出 `{proposal_type, rationale, payload}`；`proposal_type` 不得是 `PROGRESS/TASK_ASSIGN/VERDICT`；
`payload` 键集合必须与九类 Schema 完全一致；递归扫描到 `state/final_state/signature/private_key/...` 即拒绝
（`OUTPUT_ATTEMPTS_WRITE`）。这类拒绝同时写协议违规。

口径说明：`TASK_ASSIGN` 是**节点级**派发；Planner 的允许模板集合取自已派发节点的 `template_id`，
换模板属于图变更（走 `PLAN_PROPOSAL` + M04 审批），不在本阶段放开。若未来 Planner 需要跨模板选型，
必须给 `TaskFactsPort` 增加只读模板目录（登记 OQ）。

## 8. role_off：六个角色都能关，关掉后不“单 Agent 全包”

`roles.ROLE_OFF_CONTRACTS` 为每个角色定义：补位方式、补位引用、可观测效果、禁止补位集合、必检保留、是否需人工。

| 关闭角色 | 补位（`ReplacementKind`） | 关闭后发生什么 | 观测指标 |
|---|---|---|---|
| Planner | `HUMAN_FORM` | 表单/预置 `template_id` 选模板；无模板 → `ESCALATE(HUMAN_DECISION)`，任务 `BLOCKED` | `plan_proposals=0` |
| Data | `DETERMINISTIC_RULE` | 仍跑 `dataset.profile` + 阈值规则；无异常解释 | `data_profile_coverage`、`analysis_findings=0` |
| Experiment | `DETERMINISTIC_TEMPLATE` | SPEC 默认值做参数映射；缺必填 → 升级，不猜值 | `default_value_correctness` |
| Analysis | `NONE` | 不解释指标；L2 重算不受影响；无叙述 | `analysis_findings=0` |
| Recovery | `NONE` | 无恢复提案；失败直接升级；不签 SPA | `recovery_success_rate=0`（如实报告） |
| Verification | `MANDATORY_VERIFIER_ONLY` | 不提交验证计划；Verifier 必检 L1/L2/L3 不变 | `verify_requests=0`、必检覆盖不变 |

三条拒绝“静默退化”的机制：

1. `RoleOffContract.forbidden_substitution` 必须是其余五个角色（不允许“另一个角色代做”）；
2. `RoleOffRegistry.disable()` 要求 `agents=true` 且 `role_off=true`（M03 组合规则），并且**审计成功**才生效；
3. `RoleOffRegistry.require_active()` 对已关闭角色抛 `RoleDisabled`，gateway 返回 `ROLE_DISABLED`，
   **不换角色重试**；全关时 `mode()==NO_AGENTS`，`SystemMode` 里没有 `SINGLE_AGENT`。

§10.4 对照指标（本阶段只定义，不填数值）：完成率、协议违规数、数据画像覆盖率、指标复核请求数、
恢复成功率、L3 计划覆盖率、token/wall 成本、CPG 五项。

## 9. CPG 五项指标（§10.3）

| 指标 | 定义（分子/分母） | 反作弊点 |
|---|---|---|
| 跨角色引用率 | 有效跨角色边 / 有效边 | 自引用不计；无效边不进分子也不进该分母 |
| 协作密度（固定分母） | 出现有效边的有向角色对数 / 30 | 分母固定 6×5，不随任务参与角色缩小 |
| 协作密度（活跃分母） | 同上 / k(k−1)（k=有产出的角色数） | 仅作诊断，不作主指标 |
| 角色贡献熵 | −Σp_r log2 p_r（p_r=实质产出/总产出），再除以 log2(6) | 贡献只算 FINDING/PLAN/RECOVERY/VERIFY_REQUEST；PROGRESS/EVIDENCE_REF/ESCALATE 不计 |
| 无产出角色数 | 被派发但实质产出为 0 的角色数 | 未被派发的另计 `idle_roles`，不得混入 |
| 引用有效率 | 有效引用 /（有效引用 + 被拒引用） | 被拒引用必须进入分母；丢样本即失败 |

`CPG_IS_NOT_QUALITY` 写进每个 `CPGMetrics.as_dict()`；`assert_not_quality_claim()` 扫描导出符号与字段，
确保 CPG 没有 `pass/verified/verdict/gate/certificate` 语义。

## 10. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| 1. 权限矩阵与 §10.2 逐格对齐 | `EXPECTED_CELLS` 25 行 + `assert_matrix_matches_10_2()`；§5 | 已定义，未执行 |
| 2. 消息恰好 9 类 | `MessageType` 9 值 + `assert_exactly_nine()`；§6 | 已定义，未执行 |
| 3. 六角色都能“关掉”且行为有定义 | `ROLE_OFF_CONTRACTS` 6 条 + `RoleOffRegistry` + `assert_role_off_defined()`；§8 | 已定义，未执行 |
| 4. 负例覆盖五类 | `NEGATIVE_TESTS.md` §A–§E | 已定义，未执行 |
| 5. 不写状态/证据/报告/私钥 | §3 表 + `authorize_agent` + `assert_no_write_surface()` | 已定义，未执行 |
| 6. 假 evidence_id 拒绝并记违规 | `MessageValidator.validate` 步骤 4 + `_reject_and_record` | 已定义，未执行 |
| 7. role_off 不退化 | `assert_no_silent_collapse()`、`SystemMode` 无 `SINGLE_AGENT` | 已定义，未执行 |
| 8. 未提前做裁决/签名/建图/调度 | 本模块无迁移/签名/图写/调度实现；`assert_no_capability_export()` | 已定义，未执行 |

## 11. OPEN QUESTIONS（详见 `design/pseudocode/OPEN_QUESTIONS.md`）

| 编号 | 问题 | P8 临时处理 |
|---|---|---|
| `OQ-P8-01` | 角色契约版本（`role-contract/1.0`）没有上游字段，是否要登记为独立契约？ | 作为装配常量；不进五份 schema；消息 Meta 必须带同一版本 |
| `OQ-P8-02` | §6.3 没给消息信封（message_id/sent_at/correlation_id），如何做重放防护与审计？ | 引入 `MessageMeta`，并校验与 payload 重复字段一致；若要进契约需 MINOR |
| `OQ-P8-03` | §10.1 的“参数化执行请求/画像请求/重算请求”在九类消息里没有专用类型 | 映射到工具请求 + FINDING；不新增第十类（§6.3 封闭） |
| `OQ-P8-04` | 消息方向违规没有专用错误码 | 用 `SCHEMA_INVALID`(422) + `MESSAGE_DIRECTION_DENIED`；不新增 E.3 第 14 码 |
| `OQ-P8-05` | 工具参数 Schema 不匹配，E.3 把它归到 `TOOL_NOT_ALLOWLISTED`(403)，与 422 直觉冲突 | 按 E.3 用 403 + `TOOL_ARGS_SCHEMA_INVALID` + `field_path` |
| `OQ-P8-06` | LLM/工具预算、超时、上下文 token 上限没有配置键 | `PROPOSED_*` 常量，标“未校准/非契约”；ADR-008 时冻结 |
| `OQ-P8-07` | Verification 角色可见 E2 是否过宽（可能提前看到执行证据） | 当前允许 E0/E1/E2；E3 永不；若要求只看索引元数据需裁决 |
| `OQ-P8-08` | Agent 工具调用的 E1 事件由 Collector 写，但 Collector 的 E3 入口受 `OQ-P4-01` 阻塞 | 只提交 E1；E3 不在 M17 范围 |
| `OQ-P8-09` | CPG 的“实质产出”口径（哪些消息计入）没有原文 | 只计 FINDING/PLAN/RECOVERY/VERIFY_REQUEST；PROGRESS/EVIDENCE_REF/ESCALATE 不计 |
| `OQ-P8-10` | 中文检索的 FTS5 分词口径未验证 | 查询侧 ASCII 词 + CJK bigram；索引侧 tokenizer 必须同口径（M18 OQ） |

## 12. 本阶段不做

- 不做裁决（Verifier 的 L1/L2/L3）、不签报告/凭证/SPA、不签任何东西；
- 不直接建图：只产出 `PLAN_PROPOSAL`/`RECOVERY_PROPOSAL`，审批与落图在 M04；
- 不做调度：`SchedulerPort.submit` 只是提案入口，队列/派发在 M13；
- 不实现 HTTP/启动守卫/配置 schema（P10、M03）；
- 不改 `contracts/`、`docs/design/**`、`docs/state/**`；
- 不宣称 FR-012/G2/G5 已通过；本阶段只交付可评审的伪代码规格。