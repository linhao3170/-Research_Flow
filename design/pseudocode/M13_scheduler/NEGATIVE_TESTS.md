# M13 · NEGATIVE_TESTS — Ready Scheduler 与 Governor 负例（P7）

> 阶段：P7｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：M13 落地（WP-06 调度器）、G4 动态调度验收（T1）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P7 不得写成“已通过”**。
> 真实 StateMachine（SQLite 事务）/真实队列/真实 Governor；不得用 mock 证明“依赖未满足不会派发”。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：`DispatchResult.status` + `error_code` + `reason`
   （至少三项），只断言“没有派发”判失败。
2. 必须断言**副作用没有发生**：`machine.transition` 的调用记录里不出现被禁止的边
   （例如硬阈值派发负例要求调用次数为 0），以及 `DispatchResult.phases` 停在期望相位。
3. 必须断言**没有绕过状态机**：任何“节点被写成 FAILED”的负例，都要能在 `audit_log`
   里找到对应的 `STATE_TRANSITION`（成功）或 `DENIED`（失败）记录；找不到即失败。
4. 饥饿负例断言的是**选择结果与观测点**：`PopResult.selection_reason == "AGE_PROMOTION"`
   与 `starvation_report() == ()`；只断言“没饿死”判失败（没有可观测口径）。
5. 负例不得修改 expected、阈值、权重或样本；原因不符即失败。
6. 正例通过不构成完成证据；本表必须真实执行并逐条留拒绝原因。
7. 时间相关负例必须用**单调时钟注入**（`now_ticks` 参数），不得 `sleep` 真实等待。

## A. READY 判定与依赖（「未满足依赖就派发」）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M13-01 | **依赖未满足就派发** | 节点 `B` 的 `depends_on=(A,)`，`A` 仍是 `RUNNING`；把 `B` 放进队列后 `pop_best` | `ReadyDecision.ready is False`；`blockers == (DEPENDENCY_NOT_VERIFIED,)`；`PopResult.entry is None`；`PopResult.evicted[0].blocker == DEPENDENCY_NOT_VERIFIED`；`queue` 中不再有 `B`；`machine.calls` 不含 `READY→RUNNING` | 本文 §A；`ready_queue._dependency_blockers` 步骤 2 |
| NEG-M13-02 | 前驱状态读不到 | `state_of(A)` 抛 `FactsUnavailable` | `blockers` 含 `DEPENDENCY_STATE_UNKNOWN`；`ready is False`；**不得**把未知当 `VERIFIED` | `ready_queue._dependency_blockers` |
| NEG-M13-03 | 排队期间前驱被失效 | 入队时 `A=VERIFIED`；`pop_best` 前把 `A` 变 `INVALIDATED` | `PopResult.entry is None`；`PopResult.evicted[0].blocker == DEPENDENCY_NOT_VERIFIED`；`selection_reason == "EMPTY"`（驱逐后队列空）；`phases` 不含 `MARK_RUNNING` | 05 §9.3 R07；I-09 |
| NEG-M13-04 | 图版本变了 | 节点 `graph_version=1`，任务 `graph_version=2` | `blockers` 含 `GRAPH_VERSION_STALE`；`ready is False` | 05 §3.3；OQ-P3-03 |
| NEG-M13-05 | 输入引用解析不到 | `input_refs_resolvable=False` | `blockers` 含 `INPUT_UNRESOLVABLE`；`ready is False` | 05 §9.3 R07 |
| NEG-M13-06 | 非 READY 节点入队 | `enqueue(entry, current_state="PLANNED")` | 抛 `QueueInvariantViolated`，`reason == "QUEUE_NODE_NOT_READY"`，`error_code == "STATE_TRANSITION_DENIED"`；队列深度仍为 0 | `ready_queue.ReadyQueue.enqueue` |
| NEG-M13-07 | 重复入队被当幂等 | 同一 `node_id` 连续 `enqueue` 两次 | 抛 `QueueInvariantViolated`，`reason == "QUEUE_DUPLICATE_ENTRY"`；**不得**返回“已存在”成功 | 本表 §0 第 1 条 |
| NEG-M13-08 | 装配缺重验端口 | 不调用 `attach_ready_revalidator` 直接 `run_once` | `DispatchResult.status == DENIED`；`error_code == "STATE_TRANSITION_DENIED"`；`reason == "DISPATCH_NOT_ASSEMBLED"`；`detail` 含 `DispatchAssemblyError`；`phases == (ADMIT, DEQUEUE, FINISHED)`；`machine.calls == ()` | `dispatch.DispatchAssemblyError` |
| NEG-M13-09 | 拓扑名次与图不符 | 条目 `topological_rank=5`，`rank_of(node)=2` | 抛 `QueueInvariantViolated`，`reason == "QUEUE_RANK_MISMATCH"` | `ReadyQueue.enqueue` |

## B. 资源与硬阈值（「硬阈值仍派发」）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M13-10 | 无并发槽 | `ResourceOffer(free_slots=0)`；Governor `NORMAL` | `blockers` 含 `NO_CONCURRENCY_SLOT`；`Governor.admit(...).allowed is False`，`reason == "NO_CONCURRENCY_SLOT"`，`limit_kind == "concurrency"` | 05 §2.1；NFR-06 |
| NEG-M13-11 | **硬阈值仍派发** | `memory_used/memory_budget >= memory_hard_ratio`（0.85）；调用 `DispatchLoop.run_once` | `GovernorState.paused is True`、`allowed_slots == 0`；`DispatchResult.status == PAUSED`；`error_code == "RESOURCE_BUDGET_EXCEEDED"`；`reason == "MEMORY_HARD_LIMIT"`；`limit_kind == "memory"`；`phases == (ADMIT, FINISHED)`；**`machine.calls == ()`**；队列深度不变 | 策划书 §8.6 R02；05 §9.3 R08 |
| NEG-M13-12 | 内存需求超过剩余 | 需求 512 MB，剩余 256 MB，Governor `NORMAL` | `admit(...).allowed is False`，`reason == "MEMORY_INSUFFICIENT"`，`limit_kind == "memory"`；`DispatchResult.status == NOT_ADMITTED` | 策划书 §8.6；NFR-06 |
| NEG-M13-13 | 磁盘低于水位仍派发 | `disk_free_mb < disk_watermark_mb` | `paused is True`；含 `PAUSE_DISPATCH` 指令（`reason == "DISK_BELOW_WATERMARK"`）；该指令 `forbidden_side_effects` 包含 `delete_evidence`/`delete_artifacts`/`delete_audit`；`machine.calls == ()` | 策划书 §8.6 R04；AGENTS §4 |
| NEG-M13-14 | 预算硬阈值不暂停 | 预算占用 ≥ `budget_hard_ratio` | `paused is True`；含 `SWITCH_TEMPLATE_OR_MODEL`（`requires_orchestrator is True`）与 `PAUSE_DISPATCH`；`binding_limit_kind` ∈ `{token, wall_clock, retry}` | 策划书 §8.6 R05；§8.9 |
| NEG-M13-15 | 缺阈值键仍启动 | `thresholds_from_config({...缺少 recovery 不用管，缺 disk_soft_factor...})` | 抛 `ScoringConfigInvalid`，`code == "CONFIG_MISSING_KEY"`，`field_path` 指向缺失键；**不得**回退到 `PROPOSED_INITIAL_THRESHOLDS` | M03 schemas 硬规则 1 |
| NEG-M13-16 | 未知阈值键被忽略 | 传入 `{"memory_soft_ratio": ..., "t2_flag": true, ...}` | 抛 `ScoringConfigInvalid`，`code == "CONFIG_UNKNOWN_KEY"` | M03 schemas 硬规则 2 |
| NEG-M13-17 | 软阈值写成 ≥ 硬阈值 | `memory_soft_ratio=0.90`、`memory_hard_ratio=0.85` | 抛 `ScoringConfigInvalid`，`code == "CONFIG_VALUE_OUT_OF_RANGE"`；不得“自动交换” | 策划书 §8.6 |

## C. Governor 边界（不改状态 / 不取消必检与 L3）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M13-18 | **Governor 直接改节点状态** | 尝试 `governor.transition(...)`、`governor.set_state(...)`、`governor.mark_failed(...)`；给 `GovernorDirective` 传 `state_change="FAILED"` | 前三个 `AttributeError`；构造指令时 `TypeError`（`state_change` 是 `ClassVar`，不是字段）；`assert_no_state_change() == []`；`assert_no_forbidden_action() == []` | 05 §9.3；AGENTS §4.1；本阶段「必须拒绝」第 4 条 |
| NEG-M13-19 | **为省预算取消必检项** | `Governor.request_deferral(ProtectedWork("required:metrics_recomputable", "required_check", is_required_check=True))` | 抛 `MandatoryWorkProtected`；`error_code == "REQUIRED_EVIDENCE_MISSING"`；`reason == "MANDATORY_CHECK_DEFERRAL_REFUSED"`；`work_id` 原样出现在异常里 | 策划书 §8.9；05 §10 I-02 |
| NEG-M13-20 | **为省预算取消 L3** | `request_deferral(ProtectedWork("l3:train_random_forest", "l3_replay", is_l3=True))` | 同上（`error_code`/`reason` 一致）；且 `GovernorState.deferred_optional` 不包含该 id | 05 §10 I-04；AGENTS §4.9 |
| NEG-M13-21 | 构造“牺牲必检”的状态 | `GovernorState(..., mandatory_preserved=False)` 或 `l3_preserved=False` | 抛 `MandatoryWorkProtected`；**对象构造不出来** | 本阶段「必须拒绝」第 3 条 |
| NEG-M13-22 | 把必检混进可延后集合 | `evaluate(sample, optional_work=(ProtectedWork(..., is_required_check=True),))` | 抛 `MandatoryWorkProtected`；`state` 不返回（不产生“已延后”的记录） | `Governor.evaluate` 步骤 5 |
| NEG-M13-23 | 动作枚举被扩展 | 静态扫描 `GovernorAction` 成员 | 成员数必须为 5；名称不得命中 `FORBIDDEN_ACTIONS`（含 `CANCEL`/`SKIP`/`PAUSE_L3`）；`assert_no_forbidden_action() == []` | 本阶段验收判据 2 |

## D. 派发、角色与失败路径

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M13-24 | 用 scheduler 身份发 Orchestrator 的边 | 只授予 `{"scheduler"}`；执行结果为干净退出 | `DispatchResult.status == HANDOFF_REQUIRED`；`error_code == "STATE_TRANSITION_DENIED"`；`reason == "ROLE_NOT_GRANTED_FOR_EDGE"`；**`machine.calls` 不含 `RUNNING→VERIFYING`** | 05 §9.3 R09/R10；`EDGE_ROLES` |
| NEG-M13-25 | Executor 抛异常就自行写 FAILED | Executor 抛 `RuntimeError` | `DispatchResult.status == EXECUTOR_FAULT`；随后**必须**出现 `RUNNING→FAILED` 的 `machine.calls` 记录；`audit_log` 有一条对应 `STATE_TRANSITION`；**不存在**直接改库的痕迹 | 05 §9.3 R09；本阶段「必须拒绝」第 1 条的失败侧 |
| NEG-M13-26 | 迁移被拒后换身份重试 | `machine` 对 `RUNNING→FAILED` 抛 `StateTransitionDenied(reason="STALE_PREVIOUS_STATE")` | `DispatchResult.status == DENIED`；`reason == "STALE_PREVIOUS_STATE"`；`machine.calls` 恰好 1 次（**不得重试、不得换 actor**） | 05 §9.7 决议 7 |
| NEG-M13-27 | 回收失败仍允许再派发 | `AttemptFacts(disposition="RECLAIM_FAILED", escalation_required=True, failure_ref="...")`；随后再取该节点 | 第一次：`quarantined is True`；第二次：`status == DENIED`，`reason == "NODE_QUARANTINED"`；`release_quarantine(node, reclaimed_evidence="")` 抛 `ValueError` | M05 §6.2；AGENTS §4 补充边界 |
| NEG-M13-28 | 审计降级被当成成功 | `machine` 抛 `AuditWriteFailed`（`error_code="AUDIT_WRITE_FAILED"`） | `DispatchResult.status == AUDIT_DEGRADED`；`node_state_known is False`；`error_code == "AUDIT_WRITE_FAILED"`；**不得**返回 `RUNNING_TO_FAILED` | 05 §9.7 决议 7 第 3 条 |
| NEG-M13-29 | 先执行后迁移 | 人为把 `_enter(EXECUTE)` 放在 `_enter(MARK_RUNNING)` 之前 | `_enter` 抛 `ValueError`（相位倒退）；`assert_phase_order() == []` 证明常量顺序正确 | 本阶段「必须拒绝」第 1 条 |
| NEG-M13-30 | 干净退出判据放水 | `AttemptFacts(disposition="EXITED", exit_code=2)` 或 `timed_out=True` | `is_clean_exit is False`；走 `RUNNING→FAILED`；不得请求 `RUNNING→VERIFYING` | 05 §9.3 R09 |

## E. 饥饿（「无饥饿」的可观测口径）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M13-31 | **超龄条目被插队** | 条目 `A` 等待 130 s（阈值 120 s）、分数 0.10；条目 `B` 等待 1 s、分数 0.90；同一轮 `pop_best` | `PopResult.entry.node_id == "A"`；`selection_reason == "AGE_PROMOTION"`；`promotion_count` 从 0 → 1；若返回 `B` 即测试失败 | 策划书 §8.5「Age 防止饥饿」；§5.2 |
| NEG-M13-32 | 老化提升后仍有超龄条目 | `pop_best` 之后立即 `starvation_report(now_ticks=同一次)` | `starvation_report() == ()`（队列已空或剩余条目均未超龄）；非空即失败 | 本表 §0 第 4 条 |
| NEG-M13-33 | 时钟回退被静默接受 | `now_ticks` 小于 `enqueued_at_ticks` | `QueueEntry.age_sec` 抛 `ScoringInputInvalid`（`error_code="SCHEMA_INVALID"`、`reason="SCORING_INPUT_INVALID"`）；不得返回负数 | ENCODING_RULES §3；`scoring.normalize_age` |
| NEG-M13-34 | 老化阈值小于 Age 视界 | `StarvationPolicy(age_horizon_sec=120, promotion_age_sec=60)` | 抛 `ScoringConfigInvalid`，`code == "CONFIG_VALUE_OUT_OF_RANGE"` | 本 §5.2 |

## E2. P7-FIX1 回归（进程硬阈值 / 评分配置无默认值）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M13-35 | **进程类硬阈值仍派发**（B2 回归） | `runaway_trees > runaway_tree_limit`（其余指标正常）；调用 `Governor.evaluate` 与 `DispatchLoop.run_once` | `readings[0].level == "HARD"`；`paused is True`；`allowed_slots == 0`；含 `RECLAIM_PROCESS_TREE`（`requires_executor is True`）与 `PAUSE_DISPATCH`（`reason == "NO_CONCURRENCY_SLOT"`）；`admit(...).allowed is False` 且 `reason == "NO_CONCURRENCY_SLOT"`；`DispatchResult.status == PAUSED`；`phases == (ADMIT, FINISHED)`；`machine.calls == ()` | §8.6 表 36 进程行；`governor.py` 头部不变量「硬阈值未解除不得派发」 |
| NEG-M13-36 | **Risk 子权重有静默默认值**（F3 回归） | 不传 `policy` 调用 `normalize_risk(0.2, 0.5)`；再试 `normalize_risk(0.2, 0.5, policy=None)` | 两次都抛 `TypeError`（签名要求必填 keyword-only `policy`，`None` 不被接受）；**不得**回退到 `PROPOSED_RISK_POLICY`；`compute_score` 缺 `risk_policy` 同样 `TypeError` | §8.5；M03「缺键拒绝启动」；`scoring.normalize_risk` / `compute_score` |

## F. 误拒守卫（防止“过度收紧”）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M13-01 | 合法 READY 不被误拒 | 依赖全 `VERIFIED`、槽位 1、内存充足、模板已登记 | `ready is True`；`blockers == ()`；`primary_blocker is None` | 05 §9.3 R07 |
| GUARD-M13-02 | 软阈值仍可派发 | 内存占用 75%（软 70%/硬 85%） | `paused is False`；`allowed_slots == 1`；含 `REDUCE_CONCURRENCY`；`admit(...).allowed is True` | 策划书 §8.6「软阈值减并发」 |
| GUARD-M13-03 | 无饥饿（正观测） | 三条目均未超龄 | `starvation_report() == ()`；`selection_reason ∈ {"SCHED_SCORE","TOPOLOGY"}` | 本 §5.2 |
| GUARD-M13-04 | 关键路径优先 | 同权重、同等待、同为纯函数；`A` 关键路径 4/4、`B` 1/4 | `A` 先被选中；`SchedScore.features.critical_path` 分别 ≈ 1.0 / 0.0 | 策划书 §8.5 |
| GUARD-M13-05 | 可选项可延后且必检保留 | `optional_work=(ProtectedWork("optional:confusion_matrix","optional_check"),)`；CPU 持续高压 | `deferred_optional == ("optional:confusion_matrix",)`；`mandatory_preserved is True`；`l3_preserved is True`；`assert_preservation(state) == []` | 策划书 §8.9 |
| GUARD-M13-06 | 并列分数顺序稳定 | 两条目 `total` 完全相同、关键路径相同 | 按 `topological_rank` 升序；再相同则按 `node_id` 字典序；重复调用 100 次结果一致 | `scoring.compare_scores` |
| GUARD-M13-07 | 空队列不报错 | 队列为空时 `run_once` | `status == IDLE`；`phases == (ADMIT, DEQUEUE, FINISHED)`；不抛异常 | `ReadyQueue.pop_best` |
| GUARD-M13-08 | 授权完整时可移交验证 | 授予 `{"scheduler","orchestrator"}`；干净退出 | `status == RUNNING_TO_VERIFYING`；`machine.calls` 依次为 `READY→RUNNING`、`RUNNING→VERIFYING` | 05 §9.3 R09/R10 |
| GUARD-M13-09 | 五项归一化边界 | `assert_boundaries()` | 返回 `[]`（五项各有 0 与 1） | 本阶段验收判据 1 |
| GUARD-M13-10 | 阈值确实来自配置 | `thresholds_from_config(PROPOSED_INITIAL_THRESHOLDS)` | 装载成功且 `GovernorThresholds` 字段与传入值一致；`assert_thresholds_configurable() == []` | 本阶段「必须写清」第 1 条 |
| GUARD-M13-11 | 进程类软阈值不误暂停（B2 防过度收紧） | `zombie_processes > zombie_process_limit`，但 `runaway_trees` 未超上限 | `readings[0].level == "SOFT"`；`paused is False`；`allowed_slots == 1`；仍含 `RECLAIM_PROCESS_TREE`；`admit(...).allowed is True` | §8.6 表 36 进程行；`NEG-M13-35` 的反面 |
| GUARD-M13-12 | 多角色授权时 actor 不漂移（F4 回归） | 同一节点授予 `{"scheduler","orchestrator"}`；连续 100 次派发（含进程重启） | `machine.calls[-1].actor` **恒等于** `EDGE_ROLES[("RUNNING","VERIFYING")][0]`（`"orchestrator"`）；100 次结果完全相同；`EDGE_ROLES` 的值类型是 `tuple`，`usable[0]` 不随 `PYTHONHASHSEED` 变化 | 05 §9.3；`dispatch.EDGE_ROLES`；`NEG-M13-24` 的对偶 |

## G. 执行记录模板（落地阶段填写，P7 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M13-01 | （待执行） | — | — | — | 未执行 |
| NEG-M13-03 | （待执行） | — | — | — | 未执行 |
| NEG-M13-11 | （待执行） | — | — | — | 未执行 |
| NEG-M13-18 | （待执行） | — | — | — | 未执行 |
| NEG-M13-19 | （待执行） | — | — | — | 未执行 |
| NEG-M13-24 | （待执行） | — | — | — | 未执行 |
| NEG-M13-27 | （待执行） | — | — | — | 未执行 |
| NEG-M13-31 | （待执行） | — | — | — | 未执行 |
| NEG-M13-35 | （待执行） | — | — | — | 未执行 |
| GUARD-M13-09 | （待执行） | — | — | — | 未执行 |