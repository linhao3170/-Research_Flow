# M18 · NEGATIVE_TESTS — 知识版本、冲突、检索、绑定与 FOL（P8）

> 阶段：P8｜状态：**判据定义，未执行**（S0：不建库、不跑检索、不写业务代码）
> 执行阶段：M18 落地（知识库 WP）、G5 知识/反馈实验（T1）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P8 不得写成“已通过”**。
> 纪律：负例以“拒绝原因正确”为通过条件——断言错误码/`reason`/`field_path` 至少两项 + 副作用未发生。

## 0. 判定纪律

1. 每条负例断言 `error_code`（或异常类型）、`reason`、`field_path` 中的至少两项；
2. 必须断言**没有写库**：`store.append_calls == 0`、`store.update_calls == 0`（知识写入）；
3. 必须断言**检索没有返回被禁内容**：冲突/越界/过期未确认的 kid 不出现在 `hits` 里；
4. 必须断言**E1 只写 E1**：`evidence.submit_calls == 1` 且 `event.level == "E1"`、`kind == "tool_invocation"`；
   任何 E2/E3 写入尝试都必须失败；
5. 时间相关用例必须传 `now=`，不得 `sleep`；不依赖真实时钟；
6. 不得修改 expected、阈值、白名单或样本；原因不符即失败；
7. 正例通过不构成完成证据；本表必须真实执行并逐条留拒绝原因。

## A. 版本与“覆盖旧知识”（只增不改）

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M18-01 | **原地覆盖旧版本** | 对已有 `KnowledgeUnit` 赋 `text`/`structured`；或调用 `set_text`/`update_*` | 赋值为 `FrozenInstanceError`；方法不存在；`assert_append_only() == ()`；`store.update_calls == 0` | §11.4「只增不改」 |
| NEG-M18-02 | 新版本内容与旧版相同 | `unit.new_version(structured=同内容, text=同文本)` | `KnowledgeValidationError`；`reason == "DUPLICATE_REVISION"`；`field_path == "structured"` | §11.4「修订产生新版本」 |
| NEG-M18-03 | 改内容不重算哈希 | 构造时 `content_hash="0"*64` 而内容为新 | `reason == "CONTENT_HASH_MISMATCH"`；`field_path == "content_hash"` | §11.2；§11.4 |
| NEG-M18-04 | `supersedes` 指向自身 | `supersedes == 自身 content_hash` | `reason == "SUPERSEDES_SELF"`；`field_path == "supersedes"` | §11.4 |
| NEG-M18-05 | `supersedes` 形态非法 | `supersedes="v1"` | `reason == "SUPERSEDES_INVALID"` | §11.2 |
| NEG-M18-06 | **DEPRECATED 复活** | 对 `DEPRECATED` 记录调 `deprecate()`；或 `can_transition(DEPRECATED, ACTIVE)` | `KnowledgeGovernanceError`；`reason == "KNOWLEDGE_STATUS_TRANSITION_DENIED"`；`can_transition` 返回 False | §11.4；本 §4.1 |
| NEG-M18-07 | 字段漂移 | 增删字段后 `assert_field_parity()` | 返回非空，列出实际字段元组；`len(fields) == 15` 仍失败 | §11.2 |
| NEG-M18-08 | **Agent 写知识** | `created_by="planner"` 或 `"agent:planner"` | `KnowledgeGovernanceError`；`error_code == "TOOL_NOT_ALLOWLISTED"`；`reason == "KNOWLEDGE_WRITE_BY_AGENT_FORBIDDEN"` | §11.4 L-B；§10.2 |
| NEG-M18-09 | 无复核人 | `reviewed_by=""` | `reason == "KNOWLEDGE_NOT_REVIEWED"`；`error_code == "STATE_TRANSITION_DENIED"` | §11.4 L-B |
| NEG-M18-10 | 许可不可追溯 | `license="UNKNOWN"` 或空串 | `reason == "LICENSE_INVALID"`；`field_path == "license"` | FR-013 |
| NEG-M18-11 | 有效期倒挂 | `expires_at <= effective_at` | `reason == "EXPIRY_NOT_AFTER_EFFECTIVE"` | §11.2 |
| NEG-M18-12 | payload 类型与 ktype 不符 | `ktype=SPEC` 但 `structured=ToolPayload(...)` | `reason == "PAYLOAD_TYPE_MISMATCH"`；detail 含 `SpecPayload` 与 `ToolPayload` | §11.1 |
| NEG-M18-13 | 记录级与 payload 许可冲突 | `DATASET.license="CC-BY-4.0"`、记录 `license="MIT"` | `reason == "DATASET_LICENSE_CONFLICT"`；`field_path == "structured.license"` | §11.1 |
| NEG-M18-14 | 论文 URL 与 source_url 冲突 | `PAPER_DOC.url` ≠ `source_url` | `reason == "PAPER_URL_CONFLICT"` | §11.1 |

## B. 冲突：标记 + 人工，模型不得选边

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M18-15 | **同 scope 字段冲突未标记** | 两条 `ACTIVE`、同 `ktype`+`scope`、`test_ratio` 不同 | `detect_conflict` 返回 `ConflictRecord`；`conflicting_keys == ("test_ratio",)`；`requires_human is True`；`contenders` 两条 | §11.4 |
| NEG-M18-16 | **模型自选版本** | `HumanResolution(source=ResolutionSource.MODEL, ...)` | `KnowledgeGovernanceError`；`reason == "MODEL_CANNOT_RESOLVE_CONFLICT"`；无 winner 产生 | §11.4；本阶段「必须拒绝」 |
| NEG-M18-17 | 人工裁决缺批准号 | `HumanResolution(source=HUMAN, approved_by="alice", approval_id="")` | `reason == "HUMAN_APPROVAL_REQUIRED"` | §11.4 |
| NEG-M18-18 | KEEP_ONE 未给 winner | `decision=KEEP_ONE_DEPRECATE_OTHERS, winner=None` | `reason == "RESOLUTION_WINNER_MISSING"` | §11.4 |
| NEG-M18-19 | REJECT_CONFLICT 却给 winner | `decision=REJECT_CONFLICT_KEEP_ALL, winner="kb@2"` | `reason == "RESOLUTION_WINNER_UNEXPECTED"` | §11.4 |
| NEG-M18-20 | **冲突知识被注入** | 构造 `RetrievalHit(status="CONFLICTED", ...)` | `reason == "HIT_STATUS_NOT_RETRIEVABLE"`；gateway 的 `KnowledgeHit(status="CONFLICTED", injectable=True)` 拒绝 | §11.4；M17 NEG-51 |
| NEG-M18-21 | 冲突只出通知不出内容 | 检索命中一条 `CONFLICTED` | `result.conflicts` 含该 kid；`result.hits` **不含**该 kid；`hits` 的 text 为空亦不允许 | §11.4 |
| NEG-M18-22 | 不同 scope 被误判冲突 | 同 ktype、不同 scope、字段不同 | `detect_conflict(...) is None` | §11.4 |
| NEG-M18-23 | 已废弃记录被误判冲突 | 一方 `DEPRECATED` | `detect_conflict(...) is None` | §11.4 |
| NEG-M18-24 | 冲突键顺序不稳定 | 多次检测同一对记录 | `conflicting_keys` 每次完全相同且按字典序 | §11.4 |

## C. 检索：过滤、过期、E1 与拒绝面

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M18-25 | ktype 过滤被绕过 | 伪造 reader 返回 `ktype="TOOL"`，查询 `ktypes=("SPEC",)` | `RetrievalRefused`；`reason == "ROW_KTYPE_OUT_OF_QUERY"`；结果不返回 | §11.4 |
| NEG-M18-26 | scope 过滤被绕过 | 查询 `scope_prefix="template:a"`，reader 返回 `template:b:...` | `reason == "ROW_SCOPE_OUT_OF_QUERY"` | §11.4 |
| NEG-M18-27 | **FTS 注入** | `text='" OR * NEAR( secret'` | `tokenize_query` 只留词项；`build_fts_query` 输出只含带引号短语；`*`/`NEAR`/括号不在 MATCH 串中 | §11.4；安全审计 |
| NEG-M18-28 | 空查询 | `text="!!!"` 或空白 | `reason == "QUERY_NO_TERMS"`；reader **未被调用** | §11.4 |
| NEG-M18-29 | ktype 为空 | `RetrievalQuery(ktypes=())` | `reason == "KTYPES_REQUIRED"`；等于放开边界，必须拒绝 | §11.4 |
| NEG-M18-30 | **过期知识未降权** | 命中 `expires_at < now` | `hit.stale_kb is True`；`requires_confirmation is True`；`score == 原分×0.5`；`hit_reason.stale_downweighted is True` | §11.4 |
| NEG-M18-31 | 不允许过期时仍返回 | `allow_stale=False`，唯一命中过期 | `result.hits == ()`；`dropped_stale == 1` | §11.4 |
| NEG-M18-32 | DEPRECATED 默认被返回 | 唯一命中为 `DEPRECATED` | `hits == ()`；`dropped_deprecated == 1`；`include_deprecated=True` 时才返回且 `status=="DEPRECATED"` | §11.4 |
| NEG-M18-33 | 旧版本被返回 | 同 kid 有 v1、v2，均命中 | 只返回 v2；v1 不在 hits | §11.4 |
| NEG-M18-34 | **E1 写失败仍返回结果** | `evidence.submit` 抛异常 | `RetrievalEvidenceUnavailable`；`error_code == "AUDIT_WRITE_FAILED"`；`reason == "RETRIEVAL_E1_UNAVAILABLE"`；无结果返回 | §11.4；05 §4.5 |
| NEG-M18-35 | 检索事件写成 E2/E3 | `RetrievalEvidenceEvent(level="E2")` | `RetrievalRefused`；`reason == "RETRIEVAL_LEVEL_NOT_E1"` | 05 §4.5；AGENTS §4.5 |
| NEG-M18-36 | T0 装配检索 | `KnowledgeRetrieval(tier="T0", ...)` | `RetrievalTierRefused`；`error_code == "FEATURE_FLAG_NOT_PERMITTED"`；`reason == "KNOWLEDGE_RETRIEVAL_REQUIRES_T1"` | FR-013 属 T1 |
| NEG-M18-37 | 中文查询被丢成空 | `text="分类模型"` | `tokenize_query` 返回非空 bigram 集合；`build_fts_query` 可生成 MATCH | §11.4；`OQ-P8-10` |
| NEG-M18-38 | 命中理由缺失 | 构造 `HitReason(matched_terms=())` | `reason == "HIT_REASON_EMPTY"`；不得只返回分数 | §11.4 |
| NEG-M18-39 | 结果 stale 标记不一致 | 手工构造 `hits` 有 stale 但 `stale_hits=()` | `reason == "RESULT_STALE_INCONSISTENT"` | §11.4 |

## D. 绑定：知识不得覆盖规格、不得改必检

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M18-40 | **知识注入必检项** | `Injection(payload={"required_checks": ("x",)})` | `BindingRefused`；`error_code == "STATE_TRANSITION_DENIED"`；`reason == "KNOWLEDGE_BINDS_IMMUTABLE_TARGET"` | §11.3；本阶段「必须拒绝」第 4 条 |
| NEG-M18-41 | 知识覆盖显式 seed | 显式 `seed=42`，知识 `seed=7` | `injection.payload` 不含 `seed`；`overrides[0].winner == "EXPLICIT_CONTRACT_OR_SPEC"`；显式值未被改写 | §11.3 |
| NEG-M18-42 | 知识被标为权威 | `InjectionItem(..., authoritative=True)` | `reason == "KNOWLEDGE_CANNOT_BE_AUTHORITATIVE"` | §11.4「只回答怎么做」 |
| NEG-M18-43 | **过期默认值被用** | 唯一 SPEC 命中 stale，`confirmation=None` | `injected is False`；`skipped_reason == "STALE_NOT_CONFIRMED"`；`payload` 为空 | §11.4「要求确认」 |
| NEG-M18-44 | Agent 绑定跨角色知识 | `AgentBinding.bind(role="data", allowed_ktypes={"DATASET"}, hits=含 FAULT_CASE)` | `injection.items` 无 FAULT_CASE；`payload["dropped"] == 1`；`irrelevant_knowledge_ratio == 0.0` | §11.3 Agent 行 |
| NEG-M18-45 | 数据集许可冲突仍注入 | KB `license=CC-BY`，任务 `license=MIT` | `reason == "DATASET_LICENSE_CONFLICT"`；`error_code == "STATE_TRANSITION_DENIED"` | §11.1 |
| NEG-M18-46 | 基准任务缺 expected | `expected=()` | `reason == "EXPECTED_KB_HIT_EMPTY"` | §11.3 基准行 |
| NEG-M18-47 | 指标分母 0 写成 0% | `tool_metrics(calls=0, ...)` | `value is None`（不是 0.0）；`denominator == 0` | 统计纪律 |
| NEG-M18-48 | 版本命中被 Recall 冒名 | expected `kb@2`，实际只命中 `kb@1` | `recall_at_k.value == 0.0`；`version_hit_rate.value == 0.0`；两者分开报 | §11.3 |

## E. FOL：方向、批准、R 臂与负面结果

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M18-49 | **数据向下/参数向上** | `UpwardRecord(loop=L_C, ...)` | `DirectionViolation`；`reason == "UPWARD_FROM_POLICY_LOOP"` | §11.5 |
| NEG-M18-50 | 未批准策略下发 | `bus.publish_downward(DownwardParameter(policy_version_hash=未登记, ...))` | `reason == "POLICY_VERSION_NOT_APPROVED"`；`bus.downward() == ()` | §11.5 |
| NEG-M18-51 | 版本缺批准号 | `PolicyVersion(approval_id="")` | `reason == "POLICY_NOT_APPROVED"` | §11.5 |
| NEG-M18-52 | 未实测候选被批准 | `PolicyLoop.approve(measured=False)` | `ClaimNotAllowed`；`reason == "POLICY_NOT_MEASURED"` | §11.6 |
| NEG-M18-53 | **负面结果被隐藏** | `PolicyCandidate(negative_results=())` | `ClaimNotAllowed`；`reason == "NEGATIVE_RESULTS_HIDDEN"` | FR-014；§11.6 |
| NEG-M18-54 | Agent/模型批准知识 | `HumanApproval(approved_by="model")` 或候选 `created_by="data"` | `KnowledgeWriteForbidden`；`reason == "KNOWLEDGE_WRITE_BY_AGENT_FORBIDDEN"`；`store.append_calls == 0` | §11.4 L-B |
| NEG-M18-55 | 非法 R 臂组合 | `LoopToggles(l_a=False, l_b=True, l_c=False)` 或 `l_c=True, l_b=False` | `DirectionViolation`；`reason` ∈ `{ARM_WITHOUT_EXECUTION_LOOP, ARM_POLICY_WITHOUT_KNOWLEDGE}` | §11.6 |
| NEG-M18-56 | 回滚到自身 | `rollback(target=current)` | `reason == "ROLLBACK_TO_SELF"` | §11.5「可回滚」 |
| NEG-M18-57 | 失败被记成“独立样本” | 同一 `task_id` 重复 4 次，样本数写成 4 | `RunRecord`/`ArmMetrics` 层面要求任务级统计；测试断言样本按 `task_id` 去重（重复运行不算独立） | 统计纪律；FR-014 |
| NEG-M18-58 | 首期上强化学习 | 扫描 `feedback.__all__` | `assert_no_rl() == ()`；无 gradient/reward/ppo 符号 | §11.5「首期不引入 RL」 |

## F. 判定隔离：知识不参与“做没做”

| ID | 目标 | 输入 / 操作 | 预期拒绝（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M18-59 | **知识参与必检判定** | 绑定注入 `required_checks`/`ruleset_hash`；或 Gate 读取知识 | 绑定层拒绝（同 NEG-40）；`assert_no_decision_binding() == ()`；M18 不导出 Gate/Verifier 判定符号 | §11.4；AGENTS §4 |
| NEG-M18-60 | 知识自称 VERIFIED | 扫描 `KnowledgeUnit` 字段/`__all__` | 无 `final_state`/`verdict`/`certificate` 字段；知识不能产生 E3 | §11.4 |
| NEG-M18-61 | 检索写 E3 | 尝试 `RetrievalEvidenceEvent(level="E3")` | `RETRIEVAL_LEVEL_NOT_E1`；`assert_only_e1() == ()` | 05 §4.5 |
| NEG-M18-62 | 用 E1 检索记录推动状态 | 断言检索事件不被 StateMachine 订阅（静态） | M18 提交的是 `tool_invocation` E1；无状态迁移调用面 | AGENTS §4.5 |

## G. 误拒守卫（防止“过度收紧”）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M18-01 | 合法知识入库 | 五类各一条合法记录（人工复核） | 构造成功；`content_hash` 可复算；`assert_field_parity() == ()` | §11.2 |
| GUARD-M18-02 | 合法新版本 | 改 seed 后 `new_version` | `version+1`；`supersedes == 旧 hash`；旧记录 `deprecate` 后 `DEPRECATED` | §11.4 |
| GUARD-M18-03 | 合法检索 | 3 条 ACTIVE，`ktypes=("SPEC",)` | 3 条 hits；`evidence.submit_calls == 1`；`event.level == "E1"` | §11.4 |
| GUARD-M18-04 | 过期但已确认 | stale 命中 + `ConfirmationPort.confirm → True` | `injected is True`；`requires_confirmation is True`；`stale_kb is True` | §11.4 |
| GUARD-M18-05 | 显式值优先但默认值补齐 | 显式 `seed=42`，知识给 `test_ratio` | `payload == {"test_ratio": ...}`；`seed` 未出现 | §11.3 |
| GUARD-M18-06 | 合法人工裁决 | `KEEP_ONE` + winner + 批准号 | 返回成功；被淘汰版本需 `DEPRECATED`；winner 保持 ACTIVE | §11.4 |
| GUARD-M18-07 | 合法 R1/R2/R3 | `assert_arm_matrix()` | 返回 `()`；`toggles_for` 三个臂均可取 | §11.6 |
| GUARD-M18-08 | 合法批准与下发 | 实测候选 + 人工批准 + 回放证据 | `publish` 后 `bus.downward()` 含参数；`approved_by` 与 `replay_evidence_id` 可追溯 | §11.5 |
| GUARD-M18-09 | 中文检索可用 | `text="分类模型"` | 词项非空；MATCH 串可构造；不抛异常 | §11.4 |
| GUARD-M18-10 | 知识类型对表 | `assert_ktype_parity()`、`assert_payload_keys_match_11_1()` | 均返回 `()` | §11.1 |

## H. 执行记录模板（落地阶段填写，P8 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M18-01 | （待执行） | — | — | — | 未执行 |
| NEG-M18-02 | （待执行） | — | — | — | 未执行 |
| NEG-M18-08 | （待执行） | — | — | — | 未执行 |
| NEG-M18-15 | （待执行） | — | — | — | 未执行 |
| NEG-M18-16 | （待执行） | — | — | — | 未执行 |
| NEG-M18-20 | （待执行） | — | — | — | 未执行 |
| NEG-M18-25 | （待执行） | — | — | — | 未执行 |
| NEG-M18-30 | （待执行） | — | — | — | 未执行 |
| NEG-M18-34 | （待执行） | — | — | — | 未执行 |
| NEG-M18-40 | （待执行） | — | — | — | 未执行 |
| NEG-M18-50 | （待执行） | — | — | — | 未执行 |
| NEG-M18-53 | （待执行） | — | — | — | 未执行 |
| NEG-M18-59 | （待执行） | — | — | — | 未执行 |
| GUARD-M18-03 | （待执行） | — | — | — | 未执行 |