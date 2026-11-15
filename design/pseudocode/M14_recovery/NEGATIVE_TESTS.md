# M14 · NEGATIVE_TESTS — 定向恢复与计划冻结负例（P7）

> 阶段：P7｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：M14 落地（WP-R）、G4 恢复验收（T1）；T0 只跑最小切片
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P7 不得写成“已通过”**。
> 真实 SQLite（`audit_log` 追加）/真实文件系统（内容寻址）/真实 StateMachine 守卫；不得用 mock 证明“哈希不符会被拒”。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：`error_code` + `reason`（或 `FreezeRefused.error_code` +
   `detail` 关键字），只断言“抛异常”判失败。
2. 守卫负例必须断言**守卫序号**：`GuardReport.checked_steps` 停在失败前一步，
   证明不是“别的原因碰巧拒绝”。
3. 不稳定负例必须断言**差异来源**：`assert_reproducible()` 返回的问题文本里出现
   “时间/集合/plan_id”等具体原因，而不是只说“哈希不同”。
4. 审批负例必须断言**结构上不存在**：`RecoveryAction` 成员数 = 1、
   `RecoveryPlan` 无 `state/status/approval` 字段、模块内无 `PROPOSED/APPROVED` 字面值。
5. 负例不得修改 expected、阈值、样本或 `HASH_STABILITY_ARGUMENT`；原因不符即失败。
6. 正例通过不构成完成证据；`GUARD-M14-01` 必须真实跑两次并留存两次的字节哈希。
7. 守卫时间比较必须覆盖 `Z` 与 `+00:00` 两种写法（`NEG-M14-19`），否则会漏掉放行方向的漏洞。

## A. 签名与分类

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M14-01 | **原始异常文本混入签名** | 尝试构造 `FailureInput(..., message="FileNotFoundError: C:\\tmp\\x1\\data.csv")` | `TypeError`（`FailureInput` 没有 `message` 槽位）；若改用 `message_class=classify_message(原文)`，签名里只有桶名 `DATASET`；`assert_no_volatile_fields(sig) == []` | `error_signature.FailureInput`；§5.1 |
| NEG-M14-02 | 未登记处置被猜成 UNKNOWN | `FailureInput(error_code=None, disposition="NOT_A_DISPOSITION")` | 抛 `SignatureInputInvalid`；`error_code == "SCHEMA_INVALID"`；`reason == "ERROR_SIGNATURE_INPUT_INVALID"`；`field == "disposition"` | `signature_from_failure` 步骤 0 |
| NEG-M14-03 | 未登记故障码被猜成 UNKNOWN | `fault_code="SOMETHING_NEW"` | 同上，`field == "fault_code"` | 同上 |
| NEG-M14-04 | 内存超限 + 模板非 0 退出被判成 CODE | `limit_kind="memory"`、`disposition="TEMPLATE_ERROR"`、`exit_code=137` | `category == RESOURCE`；`retryability == RETRYABLE`；**不得**判 CODE（否则重跑再 OOM） | `CLASSIFICATION_ORDER`；§5.2 |
| NEG-M14-05 | 链断 + 空产物被判成 DATA | `error_code="EVIDENCE_CHAIN_BROKEN"`、`fault_code="ARTIFACT_UNDECLARED"` | `category == PROTOCOL`；`retryability == NOT_RETRYABLE` | 同上 |
| NEG-M14-06 | 退出码原文进签名 | 同一失败两次：`exit_code=1` 与 `exit_code=2` | `signature.key_material()["exit_code_class"]` 两次都为 `"NONZERO"`；两份 `key_material()` 完全相同（签名不随退出码数值漂移） | `ExitCodeClass`；§5.1 |

## B. 影响面与拓扑序

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M14-07 | **失效面过窄**（漏后代） | 图 `A→B→C`，`failed=A`，`OrderingPort` 返回 `(A, B)` | 抛 `PlanRefused`；`reason == "AFFECTED_SET_INVALID"`；`detail` 含 `C` | `assert_topological_subset`；§5.3 |
| NEG-M14-08 | **失效面过宽**（波及无关分支） | 图 `A→B`、`X→Y`，`failed=A`，返回 `(A, B, X, Y)` | 同上，`detail` 的“多”列表含 `X`、`Y` | 同上 |
| NEG-M14-09 | 拓扑序错误 | 返回 `(B, A)`（后代在父前） | 抛 `PlanRefused`；`reason == "TOPOLOGY_ORDER_INVALID"`；`detail` 指出 `A` 未排在 `B` 前 | `assert_topological_subset` 第 3 条 |
| NEG-M14-10 | 顺序含重复节点 | 返回 `(A, B, B)` | 抛 `PlanRefused`；`reason == "TOPOLOGY_ORDER_INVALID"`；`detail` 含“重复” | 同上第 1 条 |
| NEG-M14-11 | 失败节点不在图中 | `failed_node="Z"` | 抛 `PlanRefused`；`reason == "FAILED_NODE_NOT_IN_GRAPH"` | `affected_nodes_expected` |

## C. 计划不稳定（验收判据 3 的负例）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M14-12 | **正文带时间戳** | 在正文里加 `frozen_at="2026-11-11T09:00:00.000000Z"` | `canonical_plan_bytes` 抛 `FreezeRefused`；`error_code == "SCHEMA_INVALID"`；`detail` 含 `frozen_at`；**未落盘**（`store.put` 调用次数 0） | ADR-004 §3；§5.7 第 4 条 |
| NEG-M14-13 | 正文**值**里藏时间 | 合法键 `note` 的值是 RFC3339 时间 | 同上；`detail` 含“值命中易变模式” | `VOLATILE_VALUE_PATTERNS` |
| NEG-M14-14 | 正文带绝对路径/pid | 值含 `C:\\tmp\\x\\stderr.log` 或 `pid=4321` | 同上（`SCHEMA_INVALID` + 具体模式） | 同上 |
| NEG-M14-15 | 集合直接进正文 | `decisions` 用 `set` 承载 | `assert_plan_structure()` 返回问题（“直接是集合”）；`FreezeRefused` 于序列化前 | §5.7 第 3 条 |
| NEG-M14-16 | `plan_id` 写进正文 | 正文加 `plan_id` 键 | `assert_plan_structure()` 报“键集合/顺序不符”；预哈希阶段拒绝 | §5.7 第 7 条 |
| NEG-M14-17 | **两次生成不同哈希** | 同一输入，两次 `plan_recovery`，其中一次把 `OrderingPort` 换成依赖 `set` 迭代的实现 | `assert_reproducible()` 返回值非空（“同一输入两次规范化得到不同字节”）；`plan_hash` 不相等；测试失败点明确指向顺序来源 | §5.7；`assert_reproducible` |
| NEG-M14-18 | 用 `json.dumps(sort_keys=True)` 冒充 JCS | 构造含 astral 字符（如 `U+1F600`）的正文，分别用 JCS 与 `json.dumps(sort_keys=True)` 序列化 | 两份字节**不相等**；若实现用了 `json.dumps`，`assert_hash_stability_contract()` 的跨实现检查失败 | ENCODING_RULES §5；§5.7 第 5 条 |
| NEG-M14-19 | 未知 `plan_format_version` | 正文 `plan_format_version="9.9"` | `FreezeRefused`；`error_code == "SCHEMA_INVALID"`；**不猜版本** | §5.5；OQ-P7-10 |

## D. 动作与审批状态（「审批状态混入」）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M14-20 | **引入第二动作（SKIP/SPA）** | 给 `RecoveryAction` 加 `SKIP` 成员（模拟越权改动） | `assert_t0_single_action()` 返回问题（“成员必须恰好 1 个” + 命中 T2 禁名）；`NEG-M14-21` 的构造也会失败 | §5.3；ADR-004 §2.5 |
| NEG-M14-21 | **落到 §8.4 的 sign_SPA 分支** | 构造 `dc_available=True` 且其余检查全过的下游节点 | `_decide` 抛 `SpaForbiddenInT0`；`error_code == "STATE_TRANSITION_DENIED"`；`reason == "SPA_FORBIDDEN_IN_T0"`；**不生成计划** | §5.3 第 ⑧ 行 |
| NEG-M14-22 | **审批状态混入** | 给 `RecoveryPlan` 加 `status="APPROVED"` 字段、或模块加常量 `PROPOSED`（模拟越权改动） | `assert_no_approval_states()` 返回问题（“RecoveryPlan 不得有字段 status”“模块级常量出现 PROPOSED”）；`NEG-M14-23` 同类 | ADR-004 §2.5；§3 |
| NEG-M14-23 | 提供审批函数 | 模块里出现 `approve_plan()` | `assert_no_approval_states()` 返回“模块不得提供 approve_plan()” | 同上 |
| NEG-M14-24 | 计划模块越界改状态 | 给 `PlanStore` 加 `transition()` / `set_state()` | `assert_guard_is_not_a_bypass()` 返回问题；`hasattr(PlanStore, "transition") is False` | 05 §9.3；I-12 |
| NEG-M14-25 | 冻结记录带状态字段 | `FreezeRecord` 增 `next_state="READY"` | `assert_guard_is_not_a_bypass()` 返回“FreezeRecord 不得含字段 next_state”；构造 `FreezeRecord` 时 `TypeError` | §3 边界表 |

## E. 三条守卫与存储

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M14-26 | 计划文件缺失 | 内容寻址路径上无文件 | `PlanGuardDenied`；`error_code == "PLAN_HASH_MISMATCH"`；`reason == "PLAN_FILE_MISSING"`；`GuardReport.checked_steps == ()` | 05 §9.3 条件 ①；I-12 |
| NEG-M14-27 | 文件被改一字节 | 改文件后 `guard_plan_hash_matches` | `reason == "PLAN_HASH_MISMATCH"`；`detail` 同时含重算值与 `plan_hash`；`checked_steps == ("PLAN_FILE_PRESENT",)` | 条件 ② |
| NEG-M14-28 | 冻结记录缺失 | `freeze_record=None` | `reason == "PLAN_FREEZE_RECORD_MISSING"`；`checked_steps` 止于第 1 步 | 条件 ②；决议 5 |
| NEG-M14-29 | **冻结晚于重跑** | `frozen_at="2026-11-11T10:00:00.000000Z"`，`rerun="2026-11-11T09:00:00.000000Z"` | `reason == "PLAN_FROZEN_AFTER_RERUN"`；`checked_steps == ("PLAN_FILE_PRESENT","PLAN_HASH_MATCHES")` | 条件 ③ |
| NEG-M14-30 | **冻结与重跑同刻、时区写法不同** | `frozen_at="2026-11-11T09:00:00+00:00"`，`rerun="2026-11-11T09:00:00Z"` | 仍必须 `PLAN_FROZEN_AFTER_RERUN`（规范化后相等 ⇒ 不严格早于）；若通过则是漏洞。另断言 `_normalize_utc` 对两种写法的返回值 `len(...) == 30` 且**逐字符相同**（小数补足 9 位、统一 `Z`） | §5.5；`_normalize_utc` |
| NEG-M14-31 | `plan_id` 与 `plan_hash` 不一致 | 冻结记录 `plan_id="plan_abc"` | 构造 `FreezeRecord` 抛 `FreezeRefused`（`SCHEMA_INVALID`）；若绕过构造，守卫报 `PLAN_ID_MISMATCH` | OQ-P7-08；M02 `PLAN_ID_MISMATCH` |
| NEG-M14-32 | 存储根落在证据目录 | `PlanStore("/srv/researchflow/evidence/plans")` | 抛 `FreezeRefused`；`error_code == "SCHEMA_INVALID"`；`detail` 含 `evidence` | ADR-004 §2.2；`assert_store_root` |
| NEG-M14-33 | 路径逃逸 | `plan_hash="../../etc/passwd"` | `PlanGuardDenied`；`reason == "UNSAFE_PLAN_PATH"` | `PlanStore.path_for` |
| NEG-M14-34 | 覆盖已冻结计划 | `put` 同一 `plan_hash` 但字节不同 | `PlanStoreCorrupt`；**文件保持原字节**（比对读回哈希仍等于旧值） | ADR-004 §2「不可变」 |
| NEG-M14-35 | 冻结审计不可用 | `FreezeAuditPort.append` 抛异常 | `FreezeRefused`；`error_code == "AUDIT_WRITE_FAILED"`；`FrozenPlan` 不返回（调用方拿不到“已冻结”） | 05 §9.3 条件 ②；06 §3 |

## F. 业务拒绝（正常结果，不抛异常）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M14-36 | 节点不在 FAILED | `state_of(failed) == "RUNNING"` | `RecoveryOutcome.plan is None`；`escalation.reason == "STATE_MISMATCH"`；**不抛异常** | 05 §9.3 R11 |
| NEG-M14-37 | 失败节点预算耗尽 | `retry_budget_available(failed) == False` | `escalation.reason == "NO_RETRY_BUDGET"`；不生成计划 | 05 §3.1；§5.4 |
| NEG-M14-38 | 后代预算耗尽（all-or-nothing） | 后代 `C` 预算耗尽，其它都够 | `escalation.reason == "NO_RETRY_BUDGET"`；`escalation.failed_node == "C"`；**不得**生成只含 `A/B` 的计划 | §5.4 |
| NEG-M14-39 | CODE 类失败仍自动重跑 | `fault_code="TEMPLATE_NOT_REGISTERED"` | `escalation.reason == "CATEGORY_NOT_RECOVERABLE_IN_T0"`；`category == CODE`；不生成计划 | §5.2 |
| NEG-M14-40 | UNKNOWN 类失败自动重跑 | `disposition="CANCELLED"` | `escalation.reason == "UNKNOWN_FAILURE"`；`category == UNKNOWN` | §5.2 |

## G. 误拒守卫（防止“过度收紧”）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M14-01 | **同一输入两次同哈希** | 同一 `make_body` 工厂调用两次，走真实 `canonical_bytes` | 两次字节逐字节相同；两次 `plan_hash` 相同且等于 `expected_hash`；`assert_reproducible() == []`；两次日志各留一份哈希 | §5.7；验收判据 3 |
| GUARD-M14-02 | 合法计划生成 | `RESOURCE` 失败，图 `A→B→C`，预算充足 | `plan.decisions` 顺序 `(A,B,C)`；三条 `action == REEXECUTE`；`A.is_failed_node is True` 且 `reason == FAILED_NODE`；`B/C` 的 `reason` 按 §8.4 首命中分支 | §5.3 |
| GUARD-M14-03 | 无副作用节点不误判 SIDE_EFFECT | 下游 `B` 为 `PURE_FUNCTION`、证据有效、前驱未变 | `B.reason == NO_VALID_DC`（T0 保守），**不是** `SIDE_EFFECT`；`checks` 里 `SIDE_EFFECT.passed is True` | §5.3 第 ⑤ 行 |
| GUARD-M14-04 | 守卫全过 | 文件在、哈希符、冻结早于重跑 | `GuardReport(passed=True)`；`checked_steps == ("PLAN_FILE_PRESENT","PLAN_HASH_MATCHES","FROZEN_BEFORE_RERUN")`；`failure_reason is None` | 05 §9.3 |
| GUARD-M14-05 | 重复冻结幂等 | 同一正文先 `freeze_plan`，再 `freeze_plan` | 两次 `plan_hash` 相同；第二次 `created_new is False`；文件字节不变；审计**追加**两条（只追加，不改写） | ADR-004 §2.2 |
| GUARD-M14-06 | 签名键序固定 | `key_material()` 两次调用 | 键序都是 `(category, retryability, error_code, disposition, exit_code_class, limit_kind, fault_code, message_class)`；`len == 8` | §5.1 |
| GUARD-M14-07 | 自检全绿 | 依次调用 6 个 `assert_*` | 全部返回 `[]`（`assert_classification_total` / `assert_no_volatile_fields` / `assert_t0_single_action` / `assert_no_approval_states` / `assert_hash_stability_contract` / `assert_guard_is_not_a_bypass`） | 本阶段验收判据 |
| GUARD-M14-08 | 合法 RESOURCE 不被误升级 | 内存类失败、预算充足、节点 FAILED | `outcome.planned is True`；`escalation is None` | §5.2 |

## H. 执行记录模板（落地阶段填写，P7 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M14-12 | （待执行） | — | — | — | 未执行 |
| NEG-M14-17 | （待执行） | — | — | — | 未执行 |
| NEG-M14-21 | （待执行） | — | — | — | 未执行 |
| NEG-M14-22 | （待执行） | — | — | — | 未执行 |
| NEG-M14-29 | （待执行） | — | — | — | 未执行 |
| NEG-M14-30 | （待执行） | — | — | — | 未执行 |
| NEG-M14-34 | （待执行） | — | — | — | 未执行 |
| NEG-M14-38 | （待执行） | — | — | — | 未执行 |
| GUARD-M14-01 | （待执行） | — | — | — | 未执行 |