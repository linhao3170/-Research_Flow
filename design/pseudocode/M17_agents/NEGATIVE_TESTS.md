# M17 · NEGATIVE_TESTS — 六角色、消息、工具出口与 role_off（P8）

> 阶段：P8｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：M17 落地（WP-12 之后、T1 六角色接入）、G2 权限拒绝、G5 对照实验
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P8 不得写成“已通过”**。
> 纪律：负例以“拒绝原因正确”为通过条件——必须断言错误码 + reason（至少两项）+ 副作用未发生。

## 0. 判定纪律

1. 每条负例断言 `error_code`、`reason`、`field_path`（或方向/状态字段）三者中的至少两项；
   只断言“抛异常”判失败。
2. 必须断言**副作用没有发生**：`model.calls == 0`、`runner.calls == 0`、`scheduler.submit_calls == 0`、
   `store.writes == 0`，按用例选择。
3. 必须断言**违规被记录**：假 `evidence_id`、越权输出、方向违规都要在 `ViolationSink` 里出现，
   且 `violation.reason` 与预期一致；没有记录即失败。
4. 必须断言**审计成功/失败的真实状态**：审计不可用时工具不得执行、提案不得提交。
5. 权限矩阵负例必须以 `EXPECTED_CELLS` 为准，不得在测试里另写一份“期望矩阵”。
6. 不得修改 expected、阈值、白名单或样本；原因不符即失败。
7. 正例通过不构成完成证据；本表必须真实执行并逐条留拒绝原因。

## 0.1 本阶段要求覆盖的五类（对照用户验收判据 4）

| 要求覆盖 | 本表用例 | 跨模块补充 |
|---|---|---|
| 越权写库 | NEG-M17-01 ~ NEG-M17-07 | — |
| 调用未注册工具 | NEG-M17-08、NEG-M17-09、NEG-M17-10 | — |
| 假 `evidence_id` | NEG-M17-21、NEG-M17-22、NEG-M17-23、NEG-M17-32 | — |
| 冲突知识自选 | NEG-M17-51、NEG-M17-52 | `M18_knowledge/NEGATIVE_TESTS.md` NEG-M18-15/16/20 |
| role_off 退化成单 Agent | NEG-M17-43 ~ NEG-M17-50 | — |

## A. 越权写库 / 签名 / 密钥（§10.2 Agent 行）

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M17-01 | **Agent 写节点状态** | `authorize_agent(identity, Axis.WRITE)`，六角色各一次 | `allowed is False`；`error_code == "TOOL_NOT_ALLOWLISTED"`；`reason == "AGENT_WRITE_FORBIDDEN"`；`assert_agent_cannot_write_or_sign() == ()` | §10.2 R02；AGENTS §4.2 |
| NEG-M17-02 | **Agent 签名** | `authorize_agent(identity, Axis.SIGN)`，六角色各一次 | `error_code == "TOOL_NOT_ALLOWLISTED"`；`reason == "AGENT_SIGN_FORBIDDEN"`；`AgentGateway` 无 `sign*` 方法 | §10.2 R02 |
| NEG-M17-03 | 申请写证据工具 | `authorize_agent(identity, Axis.TOOL_REQUEST, tool_name="evidence.append")` | `reason == "TOOL_CAPABILITY_FORBIDDEN"`；`field_path`/`resource == "evidence.append"`；工具未注册 | §10.1；E.3 |
| NEG-M17-04 | 申请读私钥工具 | `tool_name="secret.read"` 或 `"private_key.read"` | `reason == "TOOL_CAPABILITY_FORBIDDEN"`；`registry.names()` 不含该名 | §10.1；AGENTS §4.3 |
| NEG-M17-05 | 申请写审计工具 | `tool_name="audit.write"` | `reason == "TOOL_CAPABILITY_FORBIDDEN"`；`assert_no_write_tools() == ()` | §10.2 Collector 行 |
| NEG-M17-06 | 把 E1 冒名成 E2 | 构造 `ToolEvidenceEvent(level="E2", ...)` | 构造即抛，消息含 `E1`；`level` 不得被接受 | 05 §4.5；AGENTS §4.5 |
| NEG-M17-07 | 直接 new 一个 StateMachine 端口 | 检查 `AgentGateway` 的公开面 | 不存在 `transition`/`set_state`；`assert_no_write_surface() == ()` | AGENTS §4.1 |

## B. 工具网关（未注册 / 参数 / 超时 / 审计 / 证据）

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M17-08 | **调用未注册工具** | `gateway.invoke(tool_name="db.write")` | `status == DENIED`；`error_code == "TOOL_NOT_ALLOWLISTED"`；`reason == "TOOL_CAPABILITY_FORBIDDEN"`；`runner.calls == 0` | E.3 TOOL_NOT_ALLOWLISTED |
| NEG-M17-09 | 目录内但注册表缺失 | 从 registry 删除 `knowledge.search` 后调用 | `reason == "TOOL_NOT_REGISTERED"`；`audit.begin_calls == 0`（授权后、执行前拒绝即可，但不得执行） | §5.7 |
| NEG-M17-10 | 角色越权调用工具 | Data 调用 `template.parameterize` | `reason == "ROLE_TOOL_NOT_ALLOWED"`；`resource == "template.parameterize"` | §10.1 Data |
| NEG-M17-11 | 参数未知键 | `{"query":"x","ktypes":["SPEC"],"limit":5,"unexpected":1}` | `reason == "TOOL_ARGS_SCHEMA_INVALID"`；`field_path == "args.unexpected"`；detail 含 `UNKNOWN_PARAM` | OQ-CT-08 收紧方向 |
| NEG-M17-12 | 缺必填参数 | `{"query":"x","limit":5}` | `reason == "TOOL_ARGS_SCHEMA_INVALID"`；detail 含 `MISSING_PARAM`；`field_path == "args.ktypes"` | §5.7 |
| NEG-M17-13 | 参数类型/范围越界 | `limit=0` 或 `limit="5"` | `reason == "TOOL_ARGS_SCHEMA_INVALID"`；detail 含 `VALUE_OUT_OF_RANGE` 或 `TYPE_MISMATCH` | §5.7 |
| NEG-M17-14 | 执行超时 | runner 返回 `RunnerStatus.TIMEOUT`、`child_tree_reclaimed=True` | `status == TIMEOUT`；`reason == "TOOL_TIMEOUT"`；`error_code == "RESOURCE_BUDGET_EXCEEDED"`；`value is None` | 策划书 §8.6 R06 |
| NEG-M17-15 | 调用预算耗尽 | 同一 node 第 9 次调用（预算 8） | `status == DENIED`；`reason == "TOOL_CALL_LIMIT_PER_NODE"`；`field_path == "node_id"`；runner 第 9 次未被调用 | NFR-06 |
| NEG-M17-16 | 审计不可用仍执行 | `audit.begin` 抛异常 | `status == DENIED`；`reason == "TOOL_AUDIT_UNAVAILABLE"`；`error_code == "AUDIT_WRITE_FAILED"`；**`runner.calls == 0`** | 附录 E.4 |
| NEG-M17-17 | E1 记录失败仍返回结果 | `evidence.submit` 抛异常 | `status == EVIDENCE_UNAVAILABLE`；`reason == "TOOL_EVIDENCE_NOT_RECORDED"`；`value_withheld is True`；`value is None` | 05 §4.5；本阶段「必须写清」 |
| NEG-M17-18 | 审计完成失败仍返回结果 | `audit.finish` 抛异常 | `status == AUDIT_DEGRADED`；`reason == "TOOL_AUDIT_FINISH_FAILED"`；`value_withheld is True` | 附录 E.4 |
| NEG-M17-19 | 非零退出被当成功 | runner 返回 `EXITED, exit_code=2` | `status == FAILED`；`reason == "TOOL_EXIT_NONZERO"`；`detail` 含 `2` | M05 §6 |
| NEG-M17-20 | 装配缺端口 | `ToolGateway(runner=None, ...)` 调 `invoke` | `status == DENIED`；`reason == "TOOL_GATEWAY_NOT_ASSEMBLED"`；audit/runner 均未调用 | fail-closed |

## C. 消息协议（9 类 / 方向 / 假 evidence_id / 重放）

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M17-21 | **假 evidence_id（EVIDENCE_REF）** | `EvidenceRef(evidence_id="ev_"+uuid, kind="tool_invocation")`，证据库不存在 | `MessageRejected.error_code == "EVIDENCE_REFERENCE_NOT_FOUND"`；`reason == "EVIDENCE_ID_NOT_FOUND"`；`field_path == "payload.evidence_id"`；**违规流恰 1 条**，`violation.reason` 同上 | E.3；§6.3 R04 |
| NEG-M17-22 | **假 evidence_id（FINDING 列表）** | `Finding.evidence_ids` 含 1 个真 id + 1 个假 id | 同上错误码；违规流 `offending` 含假 id；真实 id 未被写入任何证据 | 附录 E.4 |
| NEG-M17-23 | kind 与记录不符 | 引用真实 `ev_*`，但 `EvidenceRef.kind="agent_claim"` 而记录是 `tool_invocation` | `error_code == "SCHEMA_INVALID"`；`reason == "EVIDENCE_KIND_MISMATCH"`；`field_path == "payload.kind"` | §6.3 R04 |
| NEG-M17-24 | 引用不可见等级 | Data 引用一条 E3 证据 | `reason == "EVIDENCE_LEVEL_NOT_VISIBLE"`；`offending` 含 `E3` | §10.2「按角色受限」 |
| NEG-M17-25 | Agent 发 VERDICT | Planner 端点发送 `Verdict` | `AgentMessage` 构造/校验抛；`reason == "MESSAGE_DIRECTION_DENIED"`；`assert_no_agent_verdict() == ()` | §6.3 R09 |
| NEG-M17-26 | 非 Planner 发 PLAN_PROPOSAL | Analysis 发送 `PlanProposal` | `reason == "MESSAGE_DIRECTION_DENIED"`；若绕过方向，`MESSAGE_NOT_ALLOWED_FOR_ROLE` | §6.3 R06 |
| NEG-M17-27 | 消息重放 | 同一 `message_id` 连续 `validate` 两次 | 第二次 `error_code == "SCHEMA_INVALID"`；`reason == "MESSAGE_REPLAY"`；`field_path == "meta.message_id"` | 附录 E.4；FR-012 |
| NEG-M17-28 | payload 未知字段 | 在 `TASK_ASSIGN.payload` 加 `"override_state": "VERIFIED"` | `parse_message` 抛 `ValueError`（`MSG-PARSE`）；字段被拒绝，消息未进入 validator | §6.3 |
| NEG-M17-29 | 信封与 payload task 不一致 | `meta.task_id` 与 `TaskAssign.task_id` 不同 | gateway 返回 `REFUSED`，`reason == "META_PAYLOAD_TASK_MISMATCH"`；模型调用 0 次 | §6.3 |
| NEG-M17-30 | T0/T1 恢复提案带 skip | `RecoveryProposal(skip_candidates=("n2",))` | 构造抛 `ValueError`，消息含 `skip_candidates`；`RECOVERY_NOT_SAFE` 语义 | 策划书 §8.4；T2 前无 DC |
| NEG-M17-31 | PARTIAL 却带凭证 | `Verdict(final_state="PARTIAL", certificate_id="cert_...")` | 构造抛；`certificate_id` 只允许 `VERIFIED + l3 PASS + gaps 空` | 05 §9.6 |
| NEG-M17-32 | 违规记录失败被吞 | `ViolationSink.record` 抛异常，提交假 evidence_id | `MessageRejected.error_code == "AUDIT_WRITE_FAILED"`；`reason == "PROTOCOL_VIOLATION_NOT_RECORDED"`；原因为 `EVIDENCE_ID_NOT_FOUND` 出现在 detail | 附录 E.4 |
| NEG-M17-33 | 消息类型被扩到 10 类 | 尝试 `MessageType("EXEC_REQUEST")` | `ValueError`；`assert_exactly_nine() == ()`；`len(MessageType) == 9` | 本阶段验收 2 |

## D. 模型输出越权（夹带写 / 未知字段 / 越界提案）

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M17-34 | 输出夹带 `final_state` | 模型返回 `{"proposal_type":"FINDING","rationale":"...","payload":{...,"final_state":"VERIFIED"}}` | `DispatchOutcome.status == OUTPUT_REJECTED`；`error_code == "SCHEMA_INVALID"`；`reason == "OUTPUT_ATTEMPTS_WRITE"`；`scheduler.submit_calls == 0`；违规流 1 条 | §10.2；AGENTS §4 |
| NEG-M17-35 | 输出夹带 `signature`/`private_key` | 同上，payload 含 `signature` | 同 `OUTPUT_ATTEMPTS_WRITE`；字段路径指向越权键 | §10.2 R02 |
| NEG-M17-36 | 输出多带字段 | 顶层加 `"explanation"` | `reason == "OUTPUT_KEYS_MISMATCH"`；`scheduler.submit_calls == 0` | §6.3 |
| NEG-M17-37 | 模型发 PROGRESS/VERDICT | `proposal_type="PROGRESS"` 或 `"VERDICT"` | `reason == "PROGRESS_IS_GATEWAY_ONLY"` / `"AGENT_CANNOT_VERDICT"`；无提交 | §6.3 |
| NEG-M17-38 | Planner 提未登记模板 | `GraphOp(ADD_NODE, template_id="rogue@9")` | `reason == "ROLE_OUTPUT_VIOLATION"`；detail 含 `TEMPLATE_NOT_ALLOWED:rogue@9` | §8.9 |
| NEG-M17-39 | Planner 图补丁过大 | `ops` 超过 `max_nodes`/32 | `reason == "ROLE_OUTPUT_VIOLATION"`；detail 含 `PLAN_TOO_LARGE` 或 `PLAN_NODE_COUNT_EXCEEDS_LIMIT` | §8.9 |
| NEG-M17-40 | Recovery 受影响集合不符 | 提案 `affected_nodes` 与 DAG 后代不一致 | `ROLE_OUTPUT_VIOLATION`，detail 含 `RECOVERY_AFFECTED_SET_MISMATCH` | §8.4 |
| NEG-M17-41 | Verification 请求规则集外检查 | `checks_requested=("magic_check",)` | `ROLE_OUTPUT_VIOLATION`，detail 含 `CHECK_NOT_IN_RULESET` | §8.7 |
| NEG-M17-42 | 输出非法 JSON / NaN | 返回 `{"proposal_type": NaN}` | `reason == "NON_FINITE_NUMBER"`；`scheduler.submit_calls == 0` | 05 §1.3 |

## E. role_off（不得静默退化成“单 Agent 全包”）

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M17-43 | **T0 下关闭角色** | `flags={"agents": False, "role_off": False}`，`disable(planner)` | `RoleRegistryRefused`；`code == "FEATURE_FLAG_NOT_PERMITTED"`；`reason == "ROLE_OFF_REQUIRES_AGENTS"` | M03 组合规则；§10.4 |
| NEG-M17-44 | role_off 开关未开 | `flags={"agents": True, "role_off": False}` | `reason == "ROLE_OFF_FLAG_DISABLED"`；状态仍 `ACTIVE` | M03 `role_off` |
| NEG-M17-45 | 关闭时审计不可用 | `audit.record` 抛异常 | `code == "AUDIT_WRITE_FAILED"`；`reason == "ROLE_OFF_AUDIT_UNAVAILABLE"`；`status(role) == ACTIVE`（不得“先关后补审计”） | 本阶段「关闭必须留痕」 |
| NEG-M17-46 | **关闭后由别的角色代做计划** | Planner `DISABLED`；Experiment 尝试发 `PLAN_PROPOSAL` | 方向拒绝 `MESSAGE_DIRECTION_DENIED`；`EXCLUSIVE_MESSAGES[PLAN_PROPOSAL] == PLANNER`；`assert_no_silent_collapse() == ()` | §10.4；本阶段「必须拒绝」第 6 条 |
| NEG-M17-47 | 关闭 Planner 后仍出提案 | Planner `DISABLED`，`dispatch(TASK_ASSIGN→planner)` | `status == ROLE_DISABLED`；`off_contract.replacement == HUMAN_FORM`；`model.calls == 0`；`messages` 只允许 `ESCALATE`（若有） | §10.4 |
| NEG-M17-48 | 关闭 Verification 后必检缩水 | Verification `DISABLED`；执行一次验证 | `verify_requests == 0`；但 `required_checks` 集合不变、L1/L2/L3 覆盖不变；`off.mandatory_preserved is True` | §10.4；AGENTS §4.9 |
| NEG-M17-49 | 全关被解释成单 Agent | 六角色全部 `DISABLED` | `mode() == SystemMode.NO_AGENTS`；`SystemMode` 无 `SINGLE_AGENT`；任何 `dispatch` 都返回 `ROLE_DISABLED` | 本阶段「必须拒绝」第 6 条 |
| NEG-M17-50 | 关闭后“重试换角色” | 对已关闭角色连续 `dispatch`，再改 receiver 重试 | 两次都 `ROLE_DISABLED`；`scheduler.submit_calls == 0`；不得以其他角色身份提交 | §10.2「角色冒用」 |

## F. 知识冲突与上下文范围（与 M18 的接口）

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M17-51 | **冲突知识被注入** | `KnowledgeHit(status="CONFLICTED", injectable=True)` | 构造即抛，消息含 `CONFLICTED`；`assert_context_scope_only(ctx)` 返回 `CONFLICTED_KNOWLEDGE_INJECTED` | §11.4；本阶段「必须写清」第 4 条 |
| NEG-M17-52 | 冲突由模型自选版本 | 检索结果含两条冲突版本（`KnowledgeResult.conflicts` 非空） | `DispatchOutcome.status == CONTEXT_INSUFFICIENT`；`error_code == "STATE_TRANSITION_DENIED"`；`reason == "KNOWLEDGE_CONFLICT_REQUIRES_HUMAN"`；`messages` 含 `ESCALATE(reason=KNOWLEDGE_CONFLICT, needs=(APPROVED_KNOWLEDGE_VERSION, HUMAN_DECISION))`；**`model.calls == 0`**；`KnowledgeConflict` 无 winner 字段 | §11.4；OQ-P8-09 |
| NEG-M17-53 | 上下文越界 | Data 角色上下文里混入 `FAULT_CASE` 命中 | `assert_context_scope_only` 返回 `KNOWLEDGE_OUT_OF_SCOPE:FAULT_CASE`；该命中未进入 prompt | §10.2「按角色受限」 |
| NEG-M17-54 | 过期知识当默认值 | 唯一 SPEC 命中 `stale_kb=True` 且无确认 | `TemplateBinding.bind(..., confirmation=None)` 返回 `injected=False`，`skipped_reason == "STALE_NOT_CONFIRMED"` | §11.4「要求确认」 |
| NEG-M17-55 | 上下文超预算仍截断证据 | 构造超预算上下文 | `ContextOverflow`；`reason` ∈ `{CONTEXT_OVERFLOW_POLICY, CONTEXT_OVERFLOW_HARD}`；**不返回**被截断的上下文 | NFR-06 |

## G. CPG 指标（不得成为质量证明）

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M17-56 | 无效引用被丢出分母 | 图含 1 条有效 + 1 条被拒引用 | `reference_validity_rate.denominator == 2`；`numerator == 1`；`value == 0.5` | §10.3；FR-012 |
| NEG-M17-57 | PROGRESS 刷产出 | 某角色只发 100 条 `PROGRESS` | 该角色 `outputs == 0`；`silent_role_count` 计入 | §10.3 |
| NEG-M17-58 | ESCALATE 刷产出 | 某角色只发 100 条 `ESCALATE` | 同 `outputs == 0`；`assert_denominators() == ()` | §10.3 |
| NEG-M17-59 | 密度分母被缩小 | 只用 2 个角色的任务 | `collaboration_density_fixed.denominator == 30`；活跃分母单列 | §10.3 |
| NEG-M17-60 | CPG 被当成判定输入 | 静态扫描 `cpg.__all__` 与 `CPGMetrics` 字段 | 不含 `pass/verified/verdict/gate/certificate`；`assert_not_quality_claim() == ()` | §10.3；AGENTS §4 |

## H. 误拒守卫（防止“过度收紧”把正常路径挡掉）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M17-01 | 合法权限矩阵全通过 | `assert_matrix_matches_10_2()` | 返回 `()` | 验收判据 1 |
| GUARD-M17-02 | 合法身份六角色 | `assert_identity_components()` | 返回 `()`；六个 `identity_digest()` 互不相同 | §10.1 |
| GUARD-M17-03 | 合法工具调用 | Data 调 `dataset.profile`（合法参数） | `status == OK`；`audit.begin/finish` 各 1；E1 事件 1；value 返回 | §10.2 |
| GUARD-M17-04 | 合法 Planner 提案 | 已登记模板 + 合法 ops | `status == PROPOSED`；恰好 1 条 `PLAN_PROPOSAL`；`scheduler.submit_calls == 1` | §6.3 R06 |
| GUARD-M17-05 | 合法 Finding | 3 条真实 `ev_*` + confidence 0.8 | `validate` 通过；`evidence_ref_count == 3` | §6.3 R05 |
| GUARD-M17-06 | 缓存命中仍计调用 | 同一请求第二次（temperature=0） | `cache_hit is True`；`completion_tokens == 0`；调用计数 +1 | §10.4 |
| GUARD-M17-07 | 离线回退不伪造 | `offline=True` | `finish_reason == FALLBACK`；`text == ""`；`fallback_role_template` 非空；审计 1 条 | §10.4 |
| GUARD-M17-08 | 单角色关闭其余正常 | 只关 Analysis | `mode() == PARTIAL_ROLE_OFF`；其他五个角色 `dispatch` 正常 | §10.4 |
| GUARD-M17-09 | 方向表自洽 | `assert_direction_table()` | 返回 `()`；`proposal_only` 只标在三条提案/请求消息上 | §6.3 |
| GUARD-M17-10 | Agent 工具目录无副作用 | `assert_agent_tools_side_effect_free()` | 返回 `()`；`assert_no_write_tools()` 返回 `()` | §10.1 |

## I. 执行记录模板（落地阶段填写，P8 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M17-01 | （待执行） | — | — | — | 未执行 |
| NEG-M17-08 | （待执行） | — | — | — | 未执行 |
| NEG-M17-16 | （待执行） | — | — | — | 未执行 |
| NEG-M17-21 | （待执行） | — | — | — | 未执行 |
| NEG-M17-34 | （待执行） | — | — | — | 未执行 |
| NEG-M17-43 | （待执行） | — | — | — | 未执行 |
| NEG-M17-46 | （待执行） | — | — | — | 未执行 |
| NEG-M17-48 | （待执行） | — | — | — | 未执行 |
| NEG-M17-51 | （待执行） | — | — | — | 未执行 |
| NEG-M17-56 | （待执行） | — | — | — | 未执行 |
| GUARD-M17-03 | （待执行） | — | — | — | 未执行 |
| GUARD-M17-07 | （待执行） | — | — | — | 未执行 |