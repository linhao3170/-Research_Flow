# M13 · Ready Scheduler 与 Governor（P7）

> 阶段：P7「调度与定向恢复」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：READY 三合取判定、确定性就绪队列与饥饿处理、SchedScore 五项归一化、Governor 五类监控与五个动作、派发七相
> 不覆盖：DC/SPA 剪枝（T2）、VAS 验证预算分配（P9）、模板本体（P4）、恢复计划生成与冻结（M14）、HTTP 路由（P10）
> 前置：P2–P4 已验收（StateMachine/状态机、图与失效传播、Executor 与模板）；M03 `scheduler.yaml`、M01 错误码已冻结
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码

## 1. 目标

把「下一个跑谁、能不能跑、跑不动时怎么办」写死为可复核的四段：

1. **READY 是合取，不是打分**：依赖全部 `VERIFIED` ∧ 资源允许 ∧ 权限通过，任一项未知也算不满足；
2. **排队顺序确定**：同一批候选、同一组权重、同一时钟读数 ⇒ 同一顺序（堆不稳定，因此显式全序键）；
3. **饥饿有硬保证**：超过阈值且可派发的条目优先于任何更年轻条目；不能保证的是“资源永远会允许”；
4. **Governor 只出指令**：不改节点状态、不取消必检、不动 L3；硬阈值未解除时不派发。

FR 归属要说清：`FR-011`（Ready Scheduler 与 Governor）在追踪矩阵里是 **T1/G4**，本阶段只做
「T0 可证明的最小集」；M13 的产物不改变 G1–G3 的判定，也不宣称 G4 已通过。

策划书 §8.1 把动态调度拆成**四个可独立实现的决策组件**：Ready Scheduler（决定 READY 节点执行顺序）、
Governor（决定并发与资源水位）、Recovery（决定失败后谁失效、谁必须重跑）、VAS（决定有限验证预算投向哪里）。
P7 覆盖前两个（M13）与 Recovery 的 T0 最小切片（M14）；VAS 留 P9；DC/SPA 属 T2，
是本阶段**拒绝**实现的剪枝依据，不得作为 M13 的排序输入。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `orchestration/scheduler/scoring.py` | 五项归一化（各带 0/1 边界）、权重配置装载、确定性比较 | 862 | 完成（伪代码） |
| `orchestration/scheduler/ready_queue.py` | READY 三合取判定、就绪队列、饥饿老化提升、出队前重验 | 856 | 完成（伪代码） |
| `orchestration/scheduler/governor.py` | 五类监控读数、五个动作指令、准入裁决、必检/L3 保护 | 1064 | 完成（伪代码） |
| `orchestration/scheduler/dispatch.py` | 派发七相、角色与边绑定、失败经状态机、隔离 | 853 | 完成（伪代码） |

计数口径：物理行数（`text.count("\n") + 1`），与 P3–P6 的登记口径一致。

### 2.1 文件导航（>800 行文件必填）

> 依据 PHASE_RULES §5 第 2 档：登记完整函数/类索引，不拆分、不压缩。
> 计数口径：`ast` 顶层 `class`/`def` + 类内方法（含 `Protocol` 方法、`property`），一个定义一行。
> 行号取 `ast` 的 `lineno`，`2026-11-11` 用 `ast` 复核：scoring 44 / ready_queue 54 / governor 49 / dispatch 46 个定义。
> P7-FIX1（2026-11-11 第二轮）后按**同一口径**重建索引：只更新「行号」列，职责/依据两列原文未动；定义数未变（新增 0 个）。

#### `scoring.py`（862 行 / 44 个定义）

| 行号 | 类/函数 | 职责（一句话） | 依据章节 |
|---:|---|---|---|
| 112 | `CalibrationState` | 权重校准状态（T0 只允许 `UNCALIBRATED`） | 策划书 §8.5 |
| 122 | `ScoringConfigInvalid` | 权重/策略配置错误（带注册表配置码与字段路径） | M03 缺键拒绝启动 |
| 129 | `ScoringConfigInvalid.__init__` | 拼装 `[code] field_path: message` | M03 schemas |
| 135 | `_require_float` | 取有限浮点；bool/字符串/NaN 一律拒绝 | M03 硬规则 3 |
| 154 | `_require_enum_text` | 取非空枚举文本（不猜大小写） | M03 硬规则 3 |
| 168 | `SchedScoreWeights` | 五权重 + 校准声明（构造期校验和 = 1） | 策划书 §8.5 P0217 |
| 185 | `SchedScoreWeights.__post_init__` | 权重范围/归一化/`CALIBRATED` 拒绝 | §8.5；OQ-P7-02 |
| 209 | `SchedScoreWeights.as_mapping` | 固定顺序权重视图 | §8.5 |
| 214 | `SchedScoreWeights.weights_id` | 权重身份（值 + 校准状态，无时间戳） | §8.5；ENCODING_RULES §4 |
| 224 | `weights_from_config` | 从 `scheduler.yaml` 装载权重（缺键/未知键/类型/越界全拒） | M03 schemas；OQ-P7-02 |
| 269 | `RiskPolicy` | Risk 的两个子权重（和为 1 才能取到 0/1 边界） | §8.5 |
| 276 | `RiskPolicy.__post_init__` | 子权重范围与归一化校验 | §8.5 |
| 314 | `risk_policy_from_config` | 装载 Risk 子权重（缺键拒绝） | M03 schemas |
| 333 | `ScoringInputInvalid` | 特征原值越域（负年龄/负长度） | NFR-02 |
| 344 | `ScoringInputInvalid.__init__` | 拼装 422 + `SCORING_INPUT_INVALID` | 06 §4.4 |
| 350 | `_clamp_unit` | 比值钳制 [0,1]，NaN/Inf 仍拒绝 | §8.5 |
| 364 | `normalize_critical_path` | CriticalPath 归一化（1→0，最长→1） | §8.5 |
| 391 | `normalize_risk` | Risk = 失败压力 ⊕ 副作用强度加权和 | §8.5 |
| 417 | `normalize_age` | Age = 等待/视界，饱和于 1 | §8.5「Age 防止饥饿」 |
| 445 | `ResourceDemand` | 节点三元资源需求（非负有限） | NFR-06 |
| 452 | `ResourceDemand.__post_init__` | 需求非负有限校验 | NFR-06 |
| 458 | `ResourceDemand.as_mapping` | 固定顺序需求视图 | NFR-06 |
| 463 | `ResourceCaps` | 三维上限（必须来自配置/契约，无默认） | 05 §2.1；NFR-06 |
| 470 | `ResourceCaps.__post_init__` | 上限必须 > 0 | NFR-06 |
| 481 | `normalize_resource_fit` | ResourceFit = 1 − 最紧维度占用比 | §8.5 |
| 515 | `normalize_user_priority` | 档位 0–3 → [0,1]（0→0.0，3→1.0） | §8.5；OQ-P7-03 |
| 537 | `SchedFeatures` | 五项归一化特征向量（构造期断言 [0,1]） | §8.5 |
| 546 | `SchedFeatures.__post_init__` | 特征越界即拒绝 | §8.5 |
| 552 | `SchedFeatures.as_mapping` | 固定顺序特征视图 | §8.5 |
| 557 | `SchedScore` | 一次评分的完整记录（含权重、校准、声明） | §8.5 |
| 571 | `SchedScore.__post_init__` | 总分范围与校准一致性校验 | §8.5 |
| 581 | `SchedScore.contributions` | 逐项贡献（解释“为什么它先跑”） | §8.5 |
| 590 | `SchedScore.as_log_fields` | 调度日志字段（无时间戳、无 plan_*） | §8.5；ADR-004 §3 |
| 608 | `NodeScoreFacts` | 评分所需的已观测事实（无仓储/时钟） | §8.5 |
| 625 | `ClockPort` | 只读单调时钟（只服务 Age，不参与哈希） | §8.5 |
| 628 | `ClockPort.monotonic` | 单调秒读数 | §8.5 |
| 632 | `_failure_pressure` | 失败次数 / `max_attempts`，钳制 [0,1] | 05 §3.1；§8.5 |
| 647 | `compute_score` | 按 §8.5 公式算六步并返回 `SchedScore` | 策划书 §8.5 P0217 |
| 713 | `compare_scores` | 总分→关键路径→拓扑名次→node_id 的全序比较 | §8.5；M03 `ready_order` |
| 757 | `assert_boundaries` | 验收判据 1：五项都能取到 0 与 1 | 本阶段验收判据 1 |
| 802 | `_probe_caps` | 自检用临时上限（不是配置默认值） | 本 §6 |
| 807 | `assert_not_optimality_claim` | 未校准声明、`CALIBRATED` 拒绝、缺键拒绝 | §8.5；OQ-P7-02 |
| 843 | `assert_feature_order_complete` | 特征/权重/字段三者的键集合一致 | §8.5 |
| 856 | `_sequence_guard` | 禁止用集合承载候选（顺序不可控） | §8.5 |

#### `ready_queue.py`（856 行 / 54 个定义）

| 行号 | 类/函数 | 职责（一句话） | 依据章节 |
|---:|---|---|---|
| 99 | `SelectionPolicy` | 选择策略（`TOPOLOGICAL_ONLY` / `SCHED_SCORE`） | §8.5；OQ-P7-01 |
| 116 | `ReadyBlocker` | 16 种“不 READY”的结构化原因 | 05 §9.3 R07/R08 |
| 167 | `FactsUnavailable` | 事实端口不可用（必须转成阻塞，不得假设可用） | 05 §9.3 |
| 171 | `DependencyFactsPort` | 依赖事实只读端口 | 05 §9.3 R07 |
| 174 | `DependencyFactsPort.state_of` | 节点当前状态（查不到即抛） | 05 §9.3 R07 |
| 178 | `DependencyFactsPort.dependencies_of` | 前驱集合 | 05 §9.3 R07 |
| 181 | `DependencyFactsPort.input_refs_resolvable` | 输入引用可否解析 | 05 §9.3 R07 |
| 184 | `DependencyFactsPort.graph_version_of` | 任务当前图版本 | 05 §3.3；OQ-P3-03 |
| 187 | `DependencyFactsPort.node_graph_version` | 节点所属图版本 | 05 §3.3 |
| 191 | `ResourceFactsPort` | 资源水位只读端口 | 05 §9.3 R08；NFR-06 |
| 194 | `ResourceFactsPort.offer` | 当前可用资源快照 | NFR-06 |
| 198 | `PermissionFactsPort` | 模板/类型/路径/角色白名单只读端口 | FR-004；errors `TOOL_NOT_ALLOWLISTED` |
| 201 | `PermissionFactsPort.template_allowed` | 模板是否已登记 | M05 registry |
| 204 | `PermissionFactsPort.node_type_allowed` | node_type 是否在白名单 | M05 registry |
| 207 | `PermissionFactsPort.path_allowed` | 工作路径是否落在 allowlist | 06 §4.6 |
| 210 | `PermissionFactsPort.role_allowed` | 执行角色是否有权 | 05 §9.3 |
| 215 | `ResourceOffer` | 某时刻可用于派发的资源视图 | NFR-06 |
| 229 | `ResourceOffer.__post_init__` | 槽位/内存/磁盘/预算非负校验 | NFR-06 |
| 242 | `ReadyDecision` | 一次 READY 判定的完整结果（三项布尔 + 阻塞） | 05 §9.3 R07/R08 |
| 253 | `ReadyDecision.__post_init__` | `ready ⇔ 无阻塞` 与三合取一致性 | 05 §9.3 |
| 260 | `ReadyDecision.primary_blocker` | 第一个阻塞原因（保序，不按枚举序） | 05 §9.3 |
| 264 | `ReadyDecision.as_detail` | 结构化细节（供调度日志/审计） | NFR-02 |
| 278 | `_dependency_blockers` | 依赖合取项（图版本→前驱状态→输入解析） | 05 §9.3 R07 |
| 308 | `_resource_blockers` | 资源合取项（暂停→槽位→内存→磁盘→预算） | 05 §9.3 R08；NFR-06 |
| 335 | `_permission_blockers` | 权限合取项（模板→类型→路径→角色） | FR-004 |
| 358 | `evaluate_ready` | 三项独立求值 + 合取汇总（不给部分通过） | 05 §9.3 R07/R08 |
| 417 | `QueueInvariantViolated` | 队列不变量破坏（重复入队/非 READY 入队） | 本 §5 |
| 427 | `QueueInvariantViolated.__init__` | 拼装 409 + `QUEUE_*` 原因 | 06 §4.4 |
| 434 | `QueueEntry` | 就绪候选（单调时钟入队时刻 + 分数） | §8.5 |
| 448 | `QueueEntry.__post_init__` | 名次/时钟/attempt 非负校验 | §8.5 |
| 458 | `QueueEntry.age_sec` | 等待时长；时钟回退抛错 | §8.5「Age」 |
| 468 | `Eviction` | 出队前重验失败的驱逐记录 | 本 §5 |
| 478 | `PopResult` | 出队结果（候选/驱逐/原因/求值次数） | 本 §5 |
| 487 | `PopResult.empty` | 是否没有候选 | 本 §5 |
| 492 | `StarvationPolicy` | 饥饿策略两参数（Age 视界、老化阈值） | §8.5；OQ-P7-07 |
| 498 | `StarvationPolicy.__post_init__` | 阈值 > 0 且老化阈值 ≥ Age 视界 | §8.5 |
| 516 | `queue_policy_from_config` | 装载队列策略（缺键/未知键/类型/取值全拒） | M03 schemas；OQ-P7-01 |
| 563 | `ReadyQueue` | 确定性就绪队列（不持仓储/时钟） | §8.5 |
| 569 | `ReadyQueue.__init__` | 注入策略/饥饿参数/名次函数 | §8.5 |
| 585 | `ReadyQueue.policy` | 当前选择策略 | §8.5 |
| 589 | `ReadyQueue.evictions` | 历史驱逐记录（追加写） | 本 §5 |
| 594 | `ReadyQueue.promotion_count` | 老化提升次数（证明饥饿处理真实发生） | §8.5 |
| 598 | `ReadyQueue.depth` | 队列深度 | §8.5 |
| 601 | `ReadyQueue.entries` | 确定性快照（名次, node_id） | §8.5 |
| 605 | `ReadyQueue.__contains__` | 条目是否在队列 | §8.5 |
| 609 | `ReadyQueue.enqueue` | 入队：只接受 READY，重复即错 | 05 §9.3 R07 |
| 632 | `ReadyQueue.remove` | 移除条目（节点被外部迁出 READY 时） | 05 §9.3 |
| 637 | `ReadyQueue.pop_best` | 老化提升 → 策略选优 → 重验 → 驱逐/返回 | §8.5；本 §5 |
| 701 | `ReadyQueue._best_by_policy` | 拓扑序或 SchedScore 选优（全序键） | §8.5 |
| 739 | `ReadyQueue.starvation_report` | 超龄条目（`pop_best` 后应为空） | §8.5；验收判据「无饥饿」 |
| 751 | `ReadyQueue.build_entry` | 算分并构造条目（不自作入队） | §8.5 |
| 793 | `compare_entries` | 条目级确定性比较（-1/0/1） | §8.5 |
| 815 | `assert_queue_invariants` | 快照不变量（重复/名次/分数/时钟） | 本 §5 |
| 832 | `assert_queue_boundary` | 无仓储依赖、阻塞码全覆盖、合取函数齐全、提议值为正 | 本 §6 |

#### `governor.py`（1064 行 / 49 个定义）

| 行号 | 类/函数 | 职责（一句话） | 依据章节 |
|---:|---|---|---|
| 97 | `MonitorKind` | 五类监控（内存/CPU/磁盘/预算/进程） | 策划书 §8.6 TABLE 36 |
| 105 | `PressureLevel` | 三档压力（NORMAL/SOFT/HARD） | 策划书 §8.6 |
| 115 | `GovernorThresholds` | 全部阈值（构造期校验软<硬、范围、并发 1–2） | 策划书 §8.6；OQ-P7-02 |
| 136 | `GovernorThresholds.__post_init__` | 阈值合法性与软硬顺序校验 | 策划书 §8.6 |
| 164 | `GovernorThresholds.as_mapping` | 固定顺序阈值视图（调度日志用） | 策划书 §8.6 |
| 218 | `thresholds_from_config` | 装载阈值（缺键/未知键/类型/越界全拒，无默认回退） | M03 schemas；OQ-P7-02 |
| 276 | `ResourceSample` | 一次资源快照（非负有限，禁 NaN） | 策划书 §8.6 |
| 297 | `ResourceSample.__post_init__` | 采样值合法性（失败不得用 0 冒充正常） | 策划书 §8.6 |
| 317 | `ResourceSample.memory_ratio` | 内存占用比（钳制 1） | 策划书 §8.6 |
| 320 | `ResourceSample.budget_ratio` | 预算占用：token/wall/重试取最紧 | 策划书 §8.6 |
| 332 | `ResourceSample.budget_binding_kind` | 哪一维预算最紧（映射 `LimitKind`） | M03 limits |
| 348 | `MonitorReading` | 一类监控的读数与判定 | 策划书 §8.6 |
| 358 | `MonitorReading.as_detail` | 读数结构化细节 | NFR-02 |
| 374 | `GovernorAction` | **恰好五个**动作（无取消/跳过/改状态） | 策划书 §8.6/§8.9 |
| 398 | `MandatoryWorkProtected` | 试图取消/延后必检或 L3 时的拒绝 | AGENTS §4；05 §10 I-02 |
| 409 | `MandatoryWorkProtected.__init__` | 拼装 `REQUIRED_EVIDENCE_MISSING` + 原因 | 06 §4.4 |
| 419 | `ProtectedWork` | 一件可能被延后的验证工作（含保护标记） | 策划书 §8.9 |
| 431 | `ProtectedWork.__post_init__` | kind 与保护标记的一致性校验 | 策划书 §8.9 |
| 446 | `ProtectedWork.is_protected` | 是否必检项或 L3 | 05 §10 I-02 |
| 449 | `ProtectedWork.assert_deferrable` | 受保护项直接抛（延后路径唯一闸门） | 策划书 §8.9 |
| 459 | `GovernorDirective` | 一条治理指令（`state_change` 恒 None） | 策划书 §8.6 |
| 474 | `GovernorDirective.__post_init__` | 换模板需 orchestrator、回收需 executor、禁破坏性副作用 | 策划书 §8.9 |
| 486 | `GovernorDirective.as_detail` | 指令结构化细节 | NFR-02 |
| 502 | `GovernorState` | 一次评估结果（读数/指令/等级/槽位/延后） | 策划书 §8.6 |
| 515 | `GovernorState.__post_init__` | 暂停⇒0 槽；牺牲必检/L3 的状态构造不出来 | 05 §10 |
| 524 | `GovernorState.directive_for` | 按动作筛选指令 | 策划书 §8.6 |
| 527 | `GovernorState.as_detail` | 状态结构化细节 | NFR-02 |
| 544 | `Admission` | 一次“能否派发”的裁决 | 05 §9.3 R08 |
| 553 | `Admission.__post_init__` | 允许不带 limit_kind；拒绝必须给 reason | 06 §4.4 |
| 559 | `Admission.as_detail` | 裁决结构化细节 | NFR-02 |
| 574 | `Governor` | 治理器：只读样本 → 只出指令（无状态机端口） | 策划书 §8.6 |
| 581 | `Governor.__init__` | 注入阈值并初始化槽位 | 策划书 §8.6 |
| 586 | `Governor.thresholds` | 当前阈值（只读） | 策划书 §8.6 |
| 590 | `Governor.slots` | 当前允许并发（1–2） | 05 §2.1；NFR-06 |
| 595 | `Governor.evaluate` | 五类读数 → 压力 → 指令 → 槽位 → 延后（受保护项直接抛） | 策划书 §8.6 TABLE 36 |
| 788 | `Governor.admit` | 硬阈值/槽位/内存/磁盘四道准入 | 05 §9.3 R08 |
| 854 | `Governor.request_deferral` | 延后请求唯一入口（必检/L3 被拒） | 策划书 §8.9 |
| 863 | `Governor._read_process` | 进程读数（僵尸 SOFT、未退出树 HARD） | 策划书 §8.6 R06 |
| 879 | `Governor._read_disk` | 磁盘读数（水位 HARD、水位×系数 SOFT） | 策划书 §8.6 R04 |
| 900 | `Governor._read_memory` | 内存读数（软/硬阈值） | 策划书 §8.6 R02 |
| 917 | `Governor._read_cpu` | CPU 读数（持续窗口才触发） | 策划书 §8.6 R03 |
| 935 | `Governor._read_budget` | 预算读数（软/硬阈值） | 策划书 §8.6 R05 |
| 954 | `Governor._aggregate_level` | 取最严重等级 | 策划书 §8.6 |
| 962 | `Governor._reduced_slots` | 软压力下调 1 槽，下限 1 | 05 §2.1 |
| 969 | `_limit_kind_of` | 治理原因 → `LimitKind` 字面值 | M03 limits |
| 984 | `assert_no_state_change` | 验收判据 2：指令无状态变更、Governor 无迁移方法 | 本阶段验收判据 2 |
| 1007 | `assert_no_forbidden_action` | 动作枚举恰 5 个且无禁名 | 策划书 §8.6/§8.9 |
| 1020 | `assert_preservation` | 必检与 L3 未被取消/延后 | AGENTS §4；05 §10 |
| 1041 | `assert_thresholds_configurable` | 阈值键一一对应、缺键必拒、无默认回退 | 本阶段「必须写清」第 1 条 |

#### `dispatch.py`（853 行 / 46 个定义）

| 行号 | 类/函数 | 职责（一句话） | 依据章节 |
|---:|---|---|---|
| 99 | `ActorRef` | 迁移发起者（`role:identity` 审计口径） | 05 §9.7；M02 `Actor` |
| 105 | `ActorRef.__post_init__` | 角色/身份非空、分隔符校验 | 05 §9.7 |
| 112 | `ActorRef.audit_value` | 审计用 `role:identity` | 06 §1.3 |
| 117 | `DispatchContext` | 一次派发的审计必填上下文 | 05 §9.7 |
| 125 | `DispatchContext.__post_init__` | 四项必填不得为空 | 05 §9.7 |
| 131 | `HandoffRequired` | 所需角色未授予（交还 Orchestrator） | 05 §9.3 |
| 142 | `HandoffRequired.__init__` | 拼装 `ROLE_NOT_GRANTED_FOR_EDGE` 与角色集合 | 05 §9.3 |
| 154 | `RoleNotGranted` | `HandoffRequired` 的别名（负例断言用） | 本表 §D |
| 158 | `DispatchAssemblyError` | 装配错误（缺重验端口），拒绝派发 | 本表 §5.5 |
| 168 | `DispatchAssemblyError.__init__` | 拼装 `DISPATCH_NOT_ASSEMBLED` | 06 §4.4 |
| 176 | `TransitionPort` | StateMachine 的结构视图（唯一状态写入口） | 05 §9.3；AGENTS §4.1 |
| 179 | `TransitionPort.transition` | 与 M02 `transition()` 同签名 | M02 |
| 192 | `AttemptFacts` | 执行事实（不是裁决） | FR-004；M05 `AttemptOutcome` |
| 208 | `AttemptFacts.__post_init__` | `EXITED`/超时/升级的一致性校验 | 05 §9.3 R09 |
| 219 | `AttemptFacts.is_clean_exit` | 干净退出判据（0 退出、未超时、无升级） | 05 §9.3 R09 |
| 230 | `ExecutorPort` | M05 `run_attempt` 的结构视图 | FR-004 |
| 233 | `ExecutorPort.run_attempt` | 启动一次 attempt | FR-004 |
| 244 | `AttemptIdPort` | attempt_id 分配（与 attempt_seq 同源） | 05 §9.3 R08；ENCODING_RULES §1 |
| 247 | `AttemptIdPort.next_attempt_id` | 按下一序号分配 | 同上 |
| 251 | `ReadyRevalidator` | 出队前 READY 重验回调 | 05 §9.3 R07 |
| 254 | `ReadyRevalidator.__call__` | 重验单节点 | 同上 |
| 258 | `ReadyQueuePort` | 就绪队列的结构视图 | 本表 §4 |
| 265 | `ReadyQueuePort.pop_best` | 出队（含老化与重验） | §8.5 |
| 272 | `DispatchPhase` | 七个相位 | 本表 §5.5 |
| 293 | `DispatchStatus` | 十种结果状态 | 本表 §5.5 |
| 307 | `DispatchResult` | 一次派发的结构化结果 | 本表 §5.5 |
| 320 | `DispatchResult.__post_init__` | 审计降级⇒状态未知；拒绝必带码与原因 | 05 §9.7 |
| 327 | `DispatchResult.as_detail` | 结构化细节（调度日志/审计） | NFR-02 |
| 346 | `DispatchLoop` | 派发循环（无仓储、无连接） | 本表 §5.5 |
| 352 | `DispatchLoop.__init__` | 注入队列/Governor/状态机/执行器/角色/上下文 | 本表 §3 |
| 377 | `DispatchLoop.granted_roles` | 当前授予的角色集合 | 05 §9.3 |
| 381 | `DispatchLoop.quarantined_nodes` | 隔离节点快照 | M05 §6.2 |
| 384 | `DispatchLoop.is_quarantined` | 是否被隔离 | M05 §6.2 |
| 387 | `DispatchLoop.release_quarantine` | 解除隔离（必须给回收确认） | M05 §6.2 |
| 397 | `DispatchLoop.run_once` | 七相推进一次派发 | 本表 §5.5 |
| 587 | `DispatchLoop._route_verifying` | 请求 `RUNNING→VERIFYING`（Orchestrator 边） | 05 §9.3 R09 |
| 628 | `DispatchLoop._route_failure` | 请求 `RUNNING→FAILED`（失败唯一落点） | 05 §9.3 R09 |
| 682 | `DispatchLoop._transition` | 角色检查 + 唯一 `transition()` 调用点 | 05 §9.3；本表 §3 |
| 718 | `DispatchLoop._revalidate` | 缺端口即拒（fail-closed） | 05 §9.3 R07 |
| 728 | `DispatchLoop.attach_ready_revalidator` | 装配重验端口 | 本表 §5.5 |
| 733 | `DispatchLoop._denied_result` | 拒绝转结构化结果（区分 DENIED / AUDIT_DEGRADED） | 05 §9.7 |
| 772 | `DispatchLoop._enter` | 记录相位，倒退即抛错 | 本表 §5.5 |
| 781 | `DispatchLoop.snapshot_phases` | 已走相位快照 | 本表 §5.5 |
| 788 | `assert_phase_order` | 相位常量顺序与 docstring 一致 | 验收判据 |
| 805 | `assert_governor_first` | ADMIT 分支必须早于取队列 | 验收判据 |
| 831 | `assert_no_direct_state_write` | 无直写状态/证据调用面 | AGENTS §4.1 |

## 3. 边界（谁写什么）

| 对象 | 唯一写者 | 本模块的落点 |
|---|---|---|
| `tasks.state` / `nodes.state` | **StateMachine** | 只经 `TransitionPort`；Governor 连端口都没有 |
| `audit_log` | **StateMachine** | 不写；调度日志是结构化日志，不是审计 |
| `evidence` | Collector（E0–E2）/ Verifier（E3） | 不写、不改、不删 |
| `evidence_invalidations` | StateMachine | 不写（属 M04/M02 的失效路径） |
| 并发槽 | Governor（内存态，由调用方持久化） | `GovernorState.allowed_slots`；上限 2 是契约值 |
| 就绪队列 | 调度器内存 | `ReadyQueue`；不落库 |
| 执行事实 | Executor / Collector | 只读 `AttemptFacts` |

三条硬化：

1. **Governor 没有状态机端口**：`GovernorDirective.state_change` 是 `ClassVar[None]`，
   `assert_no_state_change()` 扫公开面禁止 `transition/set_state/mark_*`。
2. **延后只有一条通路**：`Governor.request_deferral()` → `ProtectedWork.assert_deferrable()`；
   必检与 L3 在这里被拒绝，绕不过去。
3. **派发只有一条通路**：`DispatchLoop._transition()` 是唯一调用 `StateMachine.transition` 的地方，
   且每次都要先过 `EDGE_ROLES` 的角色检查。

## 4. 对外接口（供 M14 / P8–P10 引用）

| 接口 | 语义 |
|---|---|
| `scoring.weights_from_config(raw)` | 装载五权重（缺键拒绝） |
| `scoring.compute_score(facts, ...)` | 算一个节点的 SchedScore |
| `scoring.compare_scores(a, b, topological_rank=...)` | 全序比较 |
| `ready_queue.evaluate_ready(...)` | READY 三合取判定 |
| `ready_queue.ReadyQueue.pop_best(now_ticks, revalidate)` | 出队（含老化与重验） |
| `governor.thresholds_from_config(raw)` | 装载五类监控阈值 |
| `governor.Governor.evaluate(sample, optional_work=())` | 五类读数 → 指令 |
| `governor.Governor.admit(state=..., demand_mb=...)` | 准入裁决 |
| `dispatch.DispatchLoop.run_once(now_ticks, governor_state)` | 一次派发（七相） |

## 5. 关键设计决定

### 5.1 READY 是合取（DEC-M13-01）

`READY(n) = 依赖 ∧ 资源 ∧ 权限`。三处细节写死：

- 前驱必须 `VERIFIED`（不是 `READY`、不是 `RUNNING`、不是“跑过”）；查不到状态按阻塞处理；
- 图版本不一致 → 阻塞（图变了，旧的就绪判断作废）；
- 端口故障 → `FACTS_UNAVAILABLE` 阻塞，**不得**当成可用。

**软压力的两层口径（写清差异，避免“只告警却拦了”的读法不一致）**：
在 READY 层，判据是「节点声明需求 **是否超过当前可用**」——超过即阻塞，软/硬只决定错误码形态
（`MEMORY_SOFT_LIMIT` / `MEMORY_HARD_LIMIT`）；READY 层不做“软阈值只告警”的降级。
「软阈值只降并发、不停止已排队节点」发生在 **Governor 层**：`Governor.evaluate()` 软压力下调槽位，
`paused` 仍为 `False`，`admit()` 仍可放行（见 `GUARD-M13-02`）。两层职责不同，不得互相套用。

### 5.2 两层饥饿处理（DEC-M13-02）

| 层 | 机制 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| 软 | SchedScore 的 Age（权重 0.20），饱和于视界 | 等待越久越可能被选中 | 一定不被插队 |
| 硬 | `starvation_promotion_age_sec`：超龄且**可派发**的条目优先 | 资源一旦允许，超龄条目先走 | 资源永远会允许（那是 Governor/容量问题） |

`ReadyQueue.starvation_report()` 是“无饥饿”的观测点：`pop_best` 之后它必须为空
（除非队列已空）。这条断言写进了 `NEGATIVE_TESTS` 的正例守卫 `GUARD-M13-03`。

### 5.3 权重与阈值只来自配置（DEC-M13-03）

- `PROPOSED_WEIGHTS` / `PROPOSED_INITIAL_THRESHOLDS` 是**配置模板候选**，不是默认值：
  `weights_from_config` / `thresholds_from_config` 缺键即 `CONFIG_MISSING_KEY`；
- `CalibrationState.CALIBRATED` 在 T0 直接 `FEATURE_FLAG_NOT_PERMITTED`（没有回放校准证据）；
- 每次分数输出都带 `CALIBRATION_DISCLAIMER`；`assert_not_optimality_claim()` 检查它存在。

### 5.4 Governor 的五个动作与「绝不取消 L3」（DEC-M13-04）

| 动作 | 触发 | 谁执行 | 是否改状态 |
|---|---|---|---|
| `REDUCE_CONCURRENCY` | 内存软阈值 / CPU 持续高 / 磁盘近水位 | 调度器（槽位） | 否 |
| `PAUSE_DISPATCH` | 内存硬阈值 / 磁盘低于水位 / 预算硬阈值 / **未退出进程树超限** | 调度器（`admit` 拒绝） | 否 |
| `RECLAIM_PROCESS_TREE` | 僵尸/未退出进程树 / 内存超预算 | **M05 Executor**（`requires_executor=True`） | 否（失败后由 Orchestrator 请求 `RUNNING→FAILED`） |
| `SWITCH_TEMPLATE_OR_MODEL` | 预算硬阈值 | **Orchestrator**（`requires_orchestrator=True`，需 `graph_patch` 审批） | 否 |
| `DEFER_NON_CRITICAL_VERIFICATION` | CPU/预算压力 | 验证调度（只挑可选项） | 否 |

“绝不取消必检与 L3”的落点：
`GovernorAction` 里没有取消类成员（`assert_no_forbidden_action` 扫禁名）；
`request_deferral` → `ProtectedWork.assert_deferrable()` 对必检/L3 抛
`MandatoryWorkProtected(REQUIRED_EVIDENCE_MISSING)`；
`GovernorState.__post_init__` 在 `mandatory_preserved=False` 或 `l3_preserved=False` 时
**构造不出对象**（不是“记个标志位”）。

**进程类硬阈值也暂停（P7-FIX1 / B2）**：`_read_process` 判为 `HARD`（未退出进程树超过上限）时，
`evaluate()` 除了发 `RECLAIM_PROCESS_TREE`，还会置 `paused=True`；因此 `allowed_slots=0`、
`admit()` 拒绝新节点。依据是策划书 §8.6 表 36「进程」行（按进程组/Job Object 回收）+ 本文件
头部不变量「硬阈值未解除不得派发」——残留进程会污染后续 attempt，不能一边回收一边继续派。
进程类 `SOFT`（仅僵尸数超限、未退出树未超）只记录并回收，不暂停（`GUARD-M13-11`）。

**「Governor 只能建议」族**：换模板/模型与进程回收同属这一类——本模块只出
`SWITCH_TEMPLATE_OR_MODEL(requires_orchestrator=True)`，实际替换 `template_id` 必须走图变更
（graph_patch）审批，**不得就地替换**；该越权边界并入 `OQ-P7-06` 处理，未单独立号。

### 5.5 派发七相与角色绑定（DEC-M13-05）

- 相序：`ADMIT → DEQUEUE → REVALIDATE → MARK_RUNNING → EXECUTE → ROUTE → FINISHED`；
  `_enter()` 对相位倒退直接抛错；
- `MARK_RUNNING` 必须先于 `EXECUTE`：先迁移后执行，不允许“先跑后补状态”；
- 每条边只用 05 §9.3 授权的角色；`RUNNING→VERIFYING` / `RUNNING→FAILED` 属 Orchestrator，
  未授予时返回 `HANDOFF_REQUIRED`，**不借身份硬发**；
- 失败路径只有一种形状：组装 `failure_ref` → 请求 `RUNNING→FAILED`；
  被拒就返回拒绝原因（`DENIED` / `AUDIT_DEGRADED`），不自行写状态；
- 回收失败（`escalation_required`）→ 隔离该节点，`release_quarantine` 必须给出回收确认。

### 5.6 `ready_order` 的口径冲突（DEC-M13-06，见 OQ-P7-01）

M03 `scheduler.yaml: ready_order` 是 `const "topological_then_node_id"`，
并注明「T0 只允许该值」；策划书 §8.5 要求 SchedScore 排序。
M13 **不改 M03**，两种策略都实现：

- `TOPOLOGICAL_ONLY`：与 M03 现值一致，可用；
- `SCHED_SCORE`：SchedScore 排序，拓扑序降级为并列裁决，**在 OQ-P7-01 裁决前不得在 T0 启用**。

落地时必须由启动守卫拦 `SCHED_SCORE`（M13 不实现启动守卫，属 M03/P10）。

## 6. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| 1. 五项归一化都有 0 与 1 边界 | `normalize_*` 五个函数各自的边界注释 + `assert_boundaries()`；§5.3 | 已定义，未执行 |
| 2. Governor 动作与「绝不取消 L3」在代码里可见 | `GovernorAction`（5 个）、`FORBIDDEN_ACTIONS`、`MandatoryWorkProtected`、`ProtectedWork.assert_deferrable`、`GovernorState.__post_init__`、`assert_no_state_change()`、`assert_preservation()` | 已定义，未执行 |
| 3. 依赖未满足不得派发 | `evaluate_ready` 的 `DEPENDENCY_NOT_VERIFIED`；`pop_best` 的 `revalidate` + `Eviction`；`NEG-M13-01/02` | 已定义，未执行 |
| 4. 硬阈值仍派发被拒 | `Governor.evaluate` → `paused=True` → `admit` 拒绝 → `DispatchLoop` 在 `ADMIT` 相直接返回 `PAUSED`；`NEG-M13-11` | 已定义，未执行 |
| 5. 饥饿处理有可观测保证 | `ReadyQueue.starvation_report()` 与 `promotion_count`；`NEG-M13-31/32`、`GUARD-M13-03` | 已定义，未执行 |
| 6. Governor 不改节点状态 | `GovernorDirective.state_change: ClassVar[None]`；`assert_no_state_change()`；`NEG-M13-18` | 已定义，未执行 |
| 7. 阈值可配置且未校准 | `FOOTPRINT_KEYS`、`thresholds_from_config`（缺键拒绝）、`CALIBRATION_NOTE`、`assert_thresholds_configurable()` | 已定义，未执行 |
| 8. 未提前实现 T2 剪枝 | 本模块没有 DC/SPA 符号；`RecoveryAction` 属 M14；`assert_no_forbidden_action()` 扫 `SKIP` | 已定义，未执行 |

## 7. OPEN QUESTIONS（详见 `design/pseudocode/OPEN_QUESTIONS.md`）

本表只列与本模块直接相关、且编号与 `OPEN_QUESTIONS.md` 一致的 OQ；未单独立号的边界问题写在 §5 对应小节。

| 编号 | 问题 | P7 临时处理 |
|---|---|---|
| `OQ-P7-01` | M03 `ready_order` 是 `const topological_then_node_id`，与 §8.5 的 SchedScore 冲突 | 两种策略都实现；T0 只允许 `TOPOLOGICAL_ONLY`；不改 M03 |
| `OQ-P7-02` | 权重与 Governor 阈值没有配置键（M03 把动态参数登记为 T1/G4 未定义） | 定义 `FOOTPRINT_KEYS` 与提议值；缺键拒绝启动；不声称已冻结 |
| `OQ-P7-03` | `TaskSpec` 19 个冻结字段里没有 priority | `UserPriority` 来自调度侧显式登记（默认 0），不改契约 |
| `OQ-P7-04` | 硬阈值拒绝没有专用错误码/HTTP 语义 | 用 `RESOURCE_BUDGET_EXCEEDED`(429) + `detail.limit_kind` + `reason=GOVERNOR_*` |
| `OQ-P7-05` | CPU「持续 30 秒」的采样归属与频率未定义 | 只接受 `ResourceSample` 快照；采样由部署层负责 |
| `OQ-P7-06` | 进程树回收/换模板的越权边界（Governor 建议 vs M05 / Orchestrator 执行） | `requires_executor=True` / `requires_orchestrator=True`；失败后状态迁移由 Orchestrator 经 StateMachine |
| `OQ-P7-07` | 饥饿阈值无配置键、无验收口径 | `PROPOSED_STARVATION_PROMOTION_AGE_SEC`（未校准）；必须配 `starvation_promotion_age_sec` |

## 8. 已知局限（P7-FIX1 登记）与本阶段不做

### 8.1 已知局限（P7-FIX1 登记）

以下 4 条属 M14 的实现边界，但直接影响调度侧对「计划可复用」的假设，故在 M13 同步登记
（**不重复实现**）。一律是**未实现 / 设计约定**，不得读作“已实现”或“已核对通过”：

| # | 现状 | 影响 | 落地阶段必须补 |
|---|---|---|---|
| L1 | `PlanStore.exists/read/put` 与 `plan_hash_of` 是 `NotImplementedError` 桩；「已存在则比字节、不同即 `PlanStoreCorrupt`」目前**只在 docstring** | 内容寻址的「只增不改」尚未成为可执行行为；调度侧不能假定“计划一定读得回来” | 实现原子写、读回重算哈希、冲突拒绝；用 NEG-M14-34 锁定 |
| L2 | `freeze_plan` **不做正文结构校验**：`canonical_plan_bytes` 只查版本与时间，也不核对 `body["task_id"]/["failed_node"]` 与记录参数一致 | 正文键集合/顺序被改仍能冻结；冻结记录与正文可能描述不同任务 | 冻结前调用 `planner.assert_plan_structure()`，并补 task_id/failed_node 一致性校验 |
| L3 | 正文含 `policy.approval_required=False`（`planner.py:105,362`），而 `assert_t0_single_action()` 只钉 `dc_used/spa_used` | 改成 `True` 会改变 `plan_hash`，但两个自检仍返回 `[]` | 把 `approval_required` 纳入 `assert_t0_single_action()`（T0 必须为 `False`） |
| L4 | `FreezeAuditPort` 只有 `Protocol`，`design/pseudocode/` 内**没有实现** | 「唯一实现是 StateMachine 审计服务」是设计约定，不是既有代码事实 | WP-R 落地时接 StateMachine 审计服务，并用真实 SQLite 事务负例验证 `AUDIT_WRITE_FAILED` 分支 |

### 8.2 本阶段不做

- 不做 DC/SPA（T2，FR-015）：不签资格、不省略、不剪枝。
- 不做 VAS 验证预算分配（P9，FR-016）。
- 不执行模板、不启动进程（P3/P4 已定，此处只调用端口）。
- 不实现 HTTP 路由、不建库、不写启动守卫（P10 / WP-06）。
- 不改 M03 的 `scheduler.yaml` schema、不改 M02 的迁移表、不改 `contracts/`。
- 不宣称 FR-011/G4 已通过：本阶段只交付可评审的伪代码规格。
