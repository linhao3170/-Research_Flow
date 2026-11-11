# M04 · DAG 与图治理（P3）

> 阶段：P3「DAG 与执行器」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：静态图构建、六类图校验、图版本与回放缓照、图变更审批、失效传播
> 不覆盖：READY 选择与并发控制（P7）、Gate 判定（P5）、模板本体（P4）、API（P10）、恢复计划生成（WP-R）
> 前置：P2 已验收；DEC-01/02/03 已裁决（本文 §6 记录落点与「待文档同步」）
> 阶段约束（S0）：只读 05/06/ADR/M01/M02；不改 M02 schema；不建环境、不跑测试、不写业务代码

## 1. 目标

把「任务能被建图、被校验、被登记、失效能被传播」落成四件可检查的东西：

1. **同一个 TaskSpec 建出同一张图**：节点 ID 有确定规则，`graph_hash` 可复算，
   不含时间/task_id，所以跨任务重建也能对上（`builder.py`）；
2. **六类校验各有正例与负例**：环/自环、孤立、重复边、类型白名单、规模深度、输入引用；
   每条拒绝都给「错误码 + 违规码 + 涉及节点」（`validator.py` 的 `CHECK_MATRIX`）；
3. **图版本单调、冲突 409、可回放**：版本匹配、两段式登记、重建校验（`graph_version.py`）；
4. **改图不是改代码**：六项校验 + 人工批准阈值 + 已执行节点不可静默重写
   （`patch_approval.py`），以及「失效只写 invalidation + audit」（`invalidation.py`）。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `orchestration/dag/builder.py` | TaskSpec → 节点/边；node_id 规则；`graph_hash`；不落库、不持 `DAG_REGISTER` | 1031 | 完成 |
| `orchestration/dag/validator.py` | 六类校验、`VIOLATION_SPECS`、`CHECK_MATRIX`、`validate_graph` | 1029 | 完成 |
| `orchestration/dag/graph_version.py` | 版本比较/冲突/快照/两段式登记/重建校验 | 813 | 完成 |
| `orchestration/dag/patch_approval.py` | graph_patch 六项校验、权限包络、批准阈值、fail-closed 审计 | 968 | 完成 |
| `orchestration/dag/invalidation.py` | `descendants()`、失效集合、StateMachine 调用点 | 608 | 完成 |
| `MODULE.md`、`NEGATIVE_TESTS.md` | 模块说明与 44 条负例判据（P3 不执行） | — | 完成 |

## 2.1 文件导航（>800 行文件必填）

> 依据 PHASE_RULES §5 第 2 档：登记完整函数/类索引，不拆分、不压缩。
> 计数口径：`ast` 顶层 `class`/`def` + 类内方法/属性（含 `Protocol` 方法）+ 函数内局部 `def`，
> 一个定义占一行（`property` 也单列，不用区间行概括）。
> 行号取 `ast` 的 `lineno`；`2026-11-11` 用 `ast` 复核，四个文件合计 182 个定义。

### `builder.py`（1031 行 / 43 个类与函数）

| 行号 | 类/函数 | 职责（一句话） | 依据章节 |
|---:|---|---|---|
| 76 | `BuildViolation` | 建图拒绝原因码（非新错误码） | 05 §3.1/§3.3 |
| 102 | `ViolationSpec` | 原因码 → 注册表错误码/HTTP/语义 | 附录 E.3；06 §4.4 |
| 179 | `BuildRejected` | 建图拒绝异常（带原因码/错误码/节点/字段路径） | 06 §4.4 |
| 182 | `BuildRejected.__init__` | 拒绝异常消息与字段（原因码/错误码/节点/字段路径） | 06 §4.4 |
| 207 | `TemplateDescriptor` | 节点模板静态描述（无命令字符串入口） | 05 §3.1；策划书 §5.7 |
| 229 | `RetryPolicy` | `retry_policy` 值对象与约束 | 05 §3.1 |
| 233 | `RetryPolicy.__post_init__` | 重试参数非负约束（`backoff_sec ≥ 0`） | 05 §3.1 |
| 241 | `NodeBlueprint` | 蓝图节点（含 fan-out 键与参数绑定） | 05 §2.1/§3.1 |
| 256 | `GraphBlueprint` | 任务模板 → 图蓝图 + 产物生产者 | 策划书 §14.2 |
| 265 | `TemplateCatalogPort` | 模板目录只读端口 | 05 §3.1；OQ-CT-08 |
| 274 | `TemplateCatalogPort.task_template` | 按 `name@X.Y.Z` 取任务图蓝图（未注册 → None） | 05 §3.1 |
| 277 | `TemplateCatalogPort.node_template` | 取节点模板描述（未注册 → None） | 05 §3.1 |
| 280 | `TemplateCatalogPort.node_type_allowed` | node_type 是否在 DomainPack 契约登记内 | 05 §3.1 |
| 284 | `NodeIdRule` | Node ID 形态校验端口（不复制正则） | ENCODING_RULES §1 |
| 292 | `NodeIdRule.is_valid` | 委托唯一正则源校验 node_id 形态 | ENCODING_RULES §1 |
| 312 | `TaskSpecView` | Builder 需要的 TaskSpec 子集 | 05 §2.1 |
| 330 | `NodeDraft` | 待登记节点（参数只在内存，不入库） | 06 §1.3 |
| 349 | `Edge` | 依赖边（`src → dst`） | 05 §3.3 |
| 357 | `GraphDraft` | Builder 唯一产出：图 + 版本 + 哈希 + 拓扑序 | 06 §1.3；策划书 §6.1 |
| 377 | `GraphDraft.node_ids` | 节点 ID 序列（输入顺序） | 05 §13 |
| 381 | `GraphDraft.node_types` | node_id → node_type 只读映射 | 05 §13 |
| 385 | `GraphDraft.template_ids` | node_id → template_id 只读映射 | 05 §13 |
| 389 | `GraphDraft.dependencies` | node_id → depends_on 只读映射 | 05 §13 |
| 393 | `GraphDraft.input_refs` | node_id → input_refs 只读映射 | 05 §13 |
| 397 | `GraphDraft.edge_pairs` | 边二元组序列 | 05 §13 |
| 400 | `GraphDraft.artifacts_declared` | 由 input_refs 反推声明的上游产物名（去重排序） | 05 §3.2 |
| 408 | `build_graph` | 建图主流程（版本 = base+1、确定性、纯函数） | 05 §3；策划书 §6.1/§14.2 |
| 547 | `_ResolvedNode` | 展开后的节点中间值 | — |
| 559 | `_plan_instances` | 纯函数：蓝图 key → 实例键 | 05 §2.1 |
| 590 | `_expand_blueprint_node` | 单蓝图节点展开（模板/类型/参数/依赖/引用） | 05 §3.1 |
| 675 | `_instance_key` | fan-out 实例键折叠（确定性） | — |
| 702 | `_assert_node_id` | node_id 四道闸（长度/分隔符/保留名/形态） | 05 §3.1；ENCODING_RULES §1 |
| 723 | `_bind_params` | 参数绑定（只允许 `parameters.` / `literal:`） | 05 §2.1 |
| 774 | `_parse_literal` | 字面量解析（拒绝 NaN/Infinity） | 05 §1.3；ENCODING_RULES §7 |
| 787 | `_reject_constant` | 非有限数拒绝回调 | 05 §1.3 |
| 792 | `_resolve_dependencies` | 蓝图依赖 key → 实例 ID 集合 | 05 §3.1 |
| 831 | `_derive_input_refs` | 生成 `artifact://<name>` 并校验上游 | 05 §3.1/§3.2 |
| 881 | `_derive_edges` | 由 depends_on 生成边（排序） | 05 §3.3 |
| 888 | `_depths` | 最长路径深度 | 05 §13 |
| 912 | `_topological_order` | Kahn + 最小堆（`topological_then_node_id`） | M03 scheduler.ready_order |
| 943 | `_hash_params` | `parameters_hash`（复用 M01 `hash_payload`） | 05 §3.1；ENCODING_RULES §4 |
| 949 | `_hash_graph_payload` | `graph_hash` 前像（P3 约定） | 06 §1.3；本文 §5.2 |
| 1000 | `assert_no_scheduling_surface` | 自检：不得出现调度/写库入口 | 07 §2.4（边界） |

### `validator.py`（1029 行 / 41 个类与函数）

| 行号 | 类/函数 | 职责（一句话） | 依据章节 |
|---:|---|---|---|
| 73 | `CheckClass` | 六类校验标识 | 策划书 §6.1；05 §13 |
| 95 | `DagViolation` | 18 个违规原因码 | 05 §3.3、§13 |
| 126 | `ViolationSpec` | 违规 → 错误码/HTTP/reason | 附录 E.3 |
| 232 | `DagLimits` | 图规模上限（P3 建议值，非契约） | 策划书 §8.9 |
| 245 | `DagLimits.__post_init__` | 五类上限必须 ≥ 1 | 策划书 §8.9 |
| 259 | `GraphView` | 校验所需最小只读视图 | 05 §13 |
| 267 | `GraphView.node_ids` | 只读视图：节点 ID 序列 | 05 §13 |
| 271 | `GraphView.edge_pairs` | 只读视图：边二元组 | 05 §13 |
| 275 | `GraphView.dependencies` | 只读视图：前驱映射 | 05 §13 |
| 279 | `GraphView.node_types` | 只读视图：node_type 映射 | 05 §13 |
| 283 | `GraphView.template_ids` | 只读视图：template_id 映射 | 05 §13 |
| 287 | `GraphView.input_refs` | 只读视图：input_refs 映射 | 05 §13 |
| 292 | `ValidationFinding` | 一条拒绝（含涉及节点与字段路径） | 06 §4.4 |
| 305 | `ValidationFinding.spec` | 原因码 → `VIOLATION_SPECS` 条目 | 附录 E.3 |
| 309 | `ValidationFinding.check` | 该违规所属的校验类 | 05 §13 |
| 313 | `ValidationFinding.error_code` | 登记表里的错误码 | 附录 E.3 |
| 317 | `ValidationFinding.http_status` | 登记表里的 HTTP 状态 | 附录 E.3 |
| 321 | `ValidationFinding.reason` | 登记表里的 reason | 附录 E.3 |
| 324 | `ValidationFinding.sort_key` | 按 CHECK_ORDER + 首节点 + 原因码排序 | — |
| 329 | `ValidationReport` | 汇总结果 + `denial()` 出口 | 05 §9.7 |
| 346 | `ValidationReport.primary` | 首个违规（按 CHECK_ORDER）；无违规 → None | 05 §9.7 |
| 350 | `ValidationReport.denial` | 转 `(error_code, reason, details)` 供 DENIED 响应 | 05 §9.7 |
| 364 | `ArtifactProducerMap` | 产物名 → 生产者（含二义检查） | 05 §3.1 |
| 372 | `ArtifactProducerMap.producer_of` | 产物名 → 生产者（无则 None） | 05 §3.1 |
| 375 | `ArtifactProducerMap.producers_of` | 产物名 → 全部生产者（二义检查用） | 05 §3.1 |
| 382 | `_adjacency` | 后继/前驱表（排序） | — |
| 397 | `_depths` | 深度 + 有环标记 | — |
| 416 | `_topology` | `topological_then_node_id` | M03 |
| 436 | `_ancestors` | 传递前驱（用于「非上游」判定） | 05 §3.1 |
| 466 | `check_cycles` | 校验 1：自环 + 有向环（含环路径） | 05 §3.3 |
| 534 | `check_orphans` | 校验 2：孤立/不可达/死端 | 05 §13 |
| 607 | `check_duplicate_edges` | 校验 3：重复边/重复节点/悬空依赖 | 05 §3.3 |
| 661 | `check_node_types` | 校验 4：类型白名单/模板已注册/node_id | 05 §3.1 |
| 723 | `check_graph_limits` | 校验 5：规模/深度/扇入扇出 | 策划书 §8.9 |
| 778 | `check_input_refs` | 校验 6：引用形态/可解析/必须上游/二义 | 05 §3.1/§3.2 |
| 839 | `_producer_lookup` | Mapping 或端口统一适配 | — |
| 850 | `_producer_lookup.producer_of` | Mapping 形式的局部适配（键唯一，无 `producers_of`） | — |
| 859 | `_parse_artifact_ref` | `artifact://<name>` 形态解析 | 05 §3.2 |
| 885 | `validate_graph` | 一次跑六类（不 fail-fast）、给拓扑序 | 05 §13 |
| 957 | `CheckVector` | 正/负例矩阵条目 | 用户验收判据 1 |
| 1009 | `assert_validator_contract` | 自检：六类齐全、码不越界、负例有期望 | — |

### `graph_version.py`（813 行 / 44 个类与函数）

| 行号 | 类/函数 | 职责（一句话） | 依据章节 |
|---:|---|---|---|
| 100 | `GraphVersionState` | FIRST/NEXT/DUPLICATE/STALE/GAP | 06 §1.3 |
| 110 | `GraphVersionConflict` | 409 冲突（`STATE_TRANSITION_DENIED` + reason） | 06 §4.1/§4.4 |
| 124 | `GraphVersionConflict.__init__` | 冲突字段与消息（无绝对路径） | 06 §4.4 |
| 142 | `GraphVersionConflict.as_detail` | 可入审计/日志的字段 | 05 §9.7 |
| 153 | `compare_versions` | 纯函数版本判定 | 06 §1.3 |
| 176 | `NodeRegistrationRow` | `nodes` INSERT 行（恒 `PLANNED`） | 06 §1.3；DEC-01 |
| 196 | `NodeRegistrationRow.__post_init__` | 初始状态/attempt_seq/plan 字段约束 | DEC-01 |
| 206 | `GraphSnapshot` | 持久层可见版本（无边的限制写清） | 06 §1.3 |
| 232 | `GraphContent` | 内存全文（含边），失效/审批用 | 05 §13 |
| 246 | `GraphContent.dependencies` | 由边反推前驱 | 05 §3.1 |
| 275 | `serialize_topology_order` | 拓扑序 → TEXT（P3 约定，存储序列化） | 06 §1.3 |
| 292 | `parse_topology_order` | TEXT → 拓扑序（严格） | 06 §1.3 |
| 308 | `snapshot_digest` | 持久视图摘要（不含时间） | 05 §13 |
| 344 | `GraphDiff` | 两版结构差异 | 05 §9.3 |
| 358 | `GraphDiff.is_empty` | 是否空差异 | 05 §9.3 |
| 365 | `GraphDiff.touched_nodes` | 内容变化的节点 | 05 §9.3 |
| 371 | `diff_graphs` | 按 node_id 对齐比较 | 05 §9.3 |
| 421 | `ReplayMismatch` | 重建不一致（fail-closed） | ADR-001；本文 §5.2 |
| 436 | `ReplayMismatch.__init__` | 期望/实际哈希（截断展示） | 本文 §5.2 |
| 447 | `verify_rebuild` | 三项校验重建 == 登记 | 05 §13 |
| 483 | `GraphVersionStorePort` | `graph_versions` 读写端口（WP-04 实现） | DEC-01；06 §2 |
| 492 | `GraphVersionStorePort.latest` | 取该 task 最新版本快照 | 06 §2 |
| 495 | `GraphVersionStorePort.get` | 按 `(task_id, graph_version)` 取快照 | 06 §2 |
| 498 | `GraphVersionStorePort.list_versions` | 列该 task 全部版本快照 | 06 §2 |
| 501 | `GraphVersionStorePort.insert` | 唯一写入口：只 INSERT，capability 须为 `DAG_REGISTER` | DEC-01 |
| 505 | `NodeRegistrarPort` | M02 `_insert_planned` 结构视图 | DEC-01 |
| 508 | `NodeRegistrarPort._insert_planned` | M02 登记行的唯一写入口（初始恒 `PLANNED`） | DEC-01 |
| 512 | `UnitOfWorkPort` | M02 `UnitOfWork.immediate` 结构视图 | 06 §2 |
| 515 | `UnitOfWorkPort.immediate` | `BEGIN IMMEDIATE` 事务上下文 | 06 §2 |
| 519 | `CapabilityGatePort` | capability 闸门（身份比较） | M02 仓储 |
| 526 | `CapabilityGatePort.require` | capability 身份比较闸门（`is`，不收字符串） | M02 仓储 |
| 533 | `RegistrationViolation` | 登记拒绝原因码 | 06 §2 |
| 545 | `RegistrationRejected` | 登记异常（非版本类） | 06 §4.4 |
| 548 | `RegistrationRejected.__init__` | 登记拒绝消息与字段（默认 `STATE_TRANSITION_DENIED`） | 06 §4.4 |
| 558 | `GraphRegistrationResult` | 登记结果（含 pending task version） | 06 §2 |
| 575 | `ReadyTransitionRequest` | `PLANNING→READY` 请求描述（不调用） | 05 §9.2/§9.7 |
| 592 | `GraphRegistrar` | 两段式登记第一段 | DEC-01 |
| 603 | `GraphRegistrar.__init__` | 注入 store / nodes / uow / gate / clock 端口 | DEC-01 |
| 619 | `GraphRegistrar.register` | 能力 → 校验凭证 → 版本 → 同事务写 | 06 §2/§3 |
| 719 | `GraphRegistrar.build_ready_request` | 组装第二段参数 | 05 §9.2 |
| 745 | `_rows_from_draft` | 草案 → INSERT 行 | 06 §1.3 |
| 766 | `_result_from_snapshot` | 结果投影 | — |
| 778 | `_is_sha256_hex` | 哈希形态 | ENCODING_RULES §4 |
| 789 | `assert_graph_version_contract` | 自检（五分支/往返/摘要字段） | — |

### `patch_approval.py`（968 行 / 54 个类与函数）

| 行号 | 类/函数 | 职责（一句话） | 依据章节 |
|---:|---|---|---|
| 82 | `PatchOpKind` | 八种允许的变更操作 | 策划书 §8.9 |
| 96 | `PatchOp` | 一条变更（载荷键固定） | 策划书 §8.9 |
| 116 | `GraphPatch` | 补丁提案（含 `patch_hash`） | 策划书 §8.9 |
| 127 | `patch_hash` | 补丁内容哈希（批准票绑定） | 05 §13 |
| 151 | `_jsonable` | 载荷可序列化检查（不 str() 兜底） | — |
| 165 | `PatchViolation` | 15 个拒绝/升级原因 | 策划书 §8.9 |
| 188 | `PatchViolationSpec` | 原因 → 错误码/是否可以批准 | 附录 E.3 |
| 263 | `PatchDecision` | ACCEPT/ACCEPT_WITH_APPROVAL/APPROVAL_REQUIRED/REJECT | 策划书 §8.9 |
| 271 | `PatchFinding` | 一条 finding | — |
| 277 | `PatchFinding.spec` | 原因码 → `PATCH_VIOLATION_SPECS` 条目 | 附录 E.3 |
| 281 | `PatchFinding.error_code` | 登记表里的错误码 | 附录 E.3 |
| 285 | `PatchFinding.hard_reject` | 是否硬拒绝（不可经批准放行） | 策划书 §8.9 |
| 298 | `PermissionEnvelope` | 权限包络（side_effect/模板/网络/写面/上限） | 策划书 §8.9 |
| 319 | `BudgetEstimate` | 预算估计（模板上限累加） | M03 limits |
| 328 | `BudgetPort` | 剩余预算来源 | M03 limits |
| 331 | `BudgetPort.remaining` | 取该 task 的剩余预算估计 | M03 limits |
| 339 | `PatchContext` | 评估所需只读事实 | — |
| 359 | `PatchChannelPort` | 人工批准通道（T0 默认不可用） | 策划书 §8.9 |
| 362 | `PatchChannelPort.submit` | 提交人工审批，返回 `approved_by` 或 None | 策划书 §8.9 |
| 367 | `PatchAuditPort` | 审计端口（**当前无合法实现**，见 OQ-P3-05） | 06 §3 |
| 375 | `PatchAuditPort.record_patch_decision` | 写一条补丁决策审计（当前无合法实现，见 OQ-P3-05） | 06 §3 |
| 389 | `ApprovalTicket` | 内容寻址批准票（不新造 ID 前缀） | ENCODING_RULES §1 |
| 397 | `ApprovalTicket.digest` | 四个字段拼接后取 SHA-256 | ENCODING_RULES §1 |
| 405 | `_CandidateView` | 让 validator 跑在候选图上 | 05 §13 |
| 408 | `_CandidateView.__init__` | 持有候选图内容 | — |
| 412 | `_CandidateView.node_ids` | 候选图节点 ID（validator 视图） | 05 §13 |
| 416 | `_CandidateView.edge_pairs` | 候选图边二元组 | 05 §13 |
| 420 | `_CandidateView.dependencies` | 候选图前驱映射（委托 `GraphContent.dependencies`） | 05 §13 |
| 424 | `_CandidateView.node_types` | 候选图 node_type 映射 | 05 §13 |
| 428 | `_CandidateView.template_ids` | 候选图 template_id 映射 | 05 §13 |
| 432 | `_CandidateView.input_refs` | 候选图 input_refs 映射 | 05 §13 |
| 436 | `apply_patch` | 纯函数：应用补丁得到候选图 | 策划书 §8.9 |
| 515 | `_PatchError` | 补丁操作错误 | — |
| 516 | `_PatchError.__init__` | 补丁操作异常字段与消息 | — |
| 523 | `_require_key` | 取字符串载荷键；缺失/非串 → `UNSUPPORTED_OP` | — |
| 530 | `_require_node` | 取图中节点；不在图 → `NODE_NOT_IN_GRAPH` | — |
| 537 | `_replace` | 按字段替换生成新 `NodeDraft` | — |
| 543 | `_node_from_payload` | ADD_NODE 的结构占位（node_type 留空由重建补齐） | 05 §3.1 |
| 569 | `_hash_payload_or_raise` | 参数哈希（M01 落地） | 05 §3.1 |
| 586 | `_check_acyclic` | 六项之一：无环 | 05 §3.3 |
| 599 | `_check_whitelist` | 六项之二：节点/边白名单 | 05 §3.1 |
| 618 | `_check_limits` | 六项之三：规模/深度 | 策划书 §8.9 |
| 626 | `_check_budget` | 六项之四：预算（增量 vs 剩余） | 策划书 §8.9 |
| 654 | `_estimate` | 预算估算 | M03 limits |
| 667 | `_check_permission` | 六项之五：权限不扩大（四项比较） | 策划书 §8.9 |
| 703 | `_check_executed_nodes` | 六项之六：已执行节点不可静默重写 | 策划书 §8.9 |
| 762 | `_envelope` | 计算权限包络 | 策划书 §8.9 |
| 792 | `PatchDecisionReport` | 决策结果 | 策划书 §8.9 |
| 807 | `PatchDecisionReport.error_code` | 首个硬拒绝 finding 的错误码（无则 None） | 附录 E.3 |
| 820 | `evaluate_patch` | 决策主流程（六步） | 策划书 §8.9 |
| 903 | `_report` | 组装决策结果（版本只给建议值 +1，不登记） | 策划书 §8.9 |
| 923 | `_touched` | op 目标节点去重保序 | 策划书 §8.9 |
| 927 | `_affects_verified` | 触及已验证节点或其前驱/后继（保守判据） | 策划书 §8.9 |
| 952 | `assert_patch_approval_contract` | 自检：六项齐全、硬拒绝有码、该批准的不硬拒 | — |

## 3. 边界（谁写什么）

| 对象 | 唯一写者 | 本模块的落点 |
|---|---|---|
| `tasks` / `nodes` 的 INSERT | API 创建服务 / Orchestrator（DEC-01） | `graph_version.GraphRegistrar.register` → `NodeRepository._insert_planned` |
| `tasks.graph_version` | **StateMachine** | 只组装 `ReadyTransitionRequest`，不调用 |
| `nodes.state` / `tasks.state` | **StateMachine** | 完全不碰（无仓储依赖） |
| `graph_versions` | Orchestrator（`DAG_REGISTER`）+ WP-04 存储 | 端口 `GraphVersionStorePort`；P3 **不写 SQL** |
| `evidence_invalidations` / `audit_log` | StateMachine | `invalidation.apply_invalidations` 只调 `transition()` |
| `evidence` | Collector（E0–E2）/ Verifier（E3） | **不写**、不改、不删 |
| 图内容（内存） | Builder | 纯函数，无副作用 |

三条硬化：

1. **Builder 无落库调用、无 `DAG_REGISTER`**：`GraphDraft` 没有 repository 字段，
   `builder.py` 不 import 仓储；`assert_no_scheduling_surface()` 扫模块公开面。
2. **Builder ≠ Scheduler**：不产出「下一个跑谁」。`FORBIDDEN_SURFACE` 列出
   `next_node`/`ready_set`/`dispatch`/`schedule` 等 16 个禁名，
   完整清单见 `builder.FORBIDDEN_SURFACE`，不在此重复抄写。
3. **状态只经 `transition()`**：M04 全模块没有 `UPDATE ... SET state`；
   `invalidation.py` 的 `TransitionPort` 是唯一写路径。

## 4. 对外接口（供 P4–P7 引用）

| 接口 | 语义 |
|---|---|
| `builder.build_graph(task, base_version, catalog, node_id_rule)` | 静态图（未校验） |
| `validator.validate_graph(view, limits, catalog, producers, node_id_rule)` | 六类校验 → `ValidationReport` |
| `graph_version.GraphRegistrar.register(draft, report, capability, registered_at)` | 两段式登记第一段 |
| `graph_version.verify_rebuild(snapshot, rebuilt)` | 回放校验（fail-closed） |
| `graph_version.diff_graphs(before, after)` | 结构差异（给失效/审批） |
| `patch_approval.evaluate_patch(patch, ctx)` | 变更决策（四值） |
| `invalidation.descendants(graph, seeds)` | 下游集合（确定性顺序） |
| `invalidation.build_invalidation_set(...)` | 失效集合（四类原因） |
| `invalidation.apply_invalidations(plan, machine, ...)` | 唯一失效调用点 |

## 5. 关键设计决定

### 5.1 节点 ID 规则（`builder._assert_node_id`）

- 单实例：`node_id = blueprint.key`；fan-out：`<key>__<instance_key>`；
- 实例键折叠：小写、非 `[a-z0-9_]` → `_`、折叠重复、去首尾；折叠后为空/重复即拒绝；
- 硬拒绝：>128 字符、含 `/` `\`、Windows 保留设备名、结尾句点/空格；
- 不使用 `new_id`、不使用 `node_` 前缀（ENCODING_RULES §1）。

### 5.2 `graph_hash` 前像（`builder._hash_graph_payload`，`[P3 约定]`）

覆盖：`schema_version`、`graph_version`、`template_id`、`dataset_sha256`、`ruleset_hash`、
按 `node_id` 升序的节点（node_id/node_type/template_id/depends_on/input_refs/
parameters_hash/side_effect_class/retry_policy/required_checks）、升序边集合。
**不含** task_id、时间戳、参数原文、绝对路径。
风险：图内容依赖模板注册表（默认参数/产物声明）。注册表变了 → 重建哈希变 →
`verify_rebuild` 抛 `ReplayMismatch`。因此模板注册表必须随版本发布冻结（OQ-P3-08）。

### 5.3 两段式登记（DEC-01 与 06 §2 的口径差）

- 第一段（同事务）：`graph_versions` INSERT + `nodes(PLANNED)` INSERT；
- 第二段（另一事务）：`StateMachine.transition(PLANNING→READY, ctx.graph_version=N)` 写 `tasks.graph_version`；
- 06 §2 要求「图版本登记 + `tasks.graph_version` 更新必须原子」，与写者分离存在口径差
  → 见 §6，**本阶段不改 06**。

### 5.4 六类校验的错误码映射（不新增码）

| 违规 | 错误码 | HTTP | 理由 |
|---|---|---|---|
| 自环、重复边、重复节点、悬空依赖、引用形态 | `SCHEMA_INVALID` | 422 | 05 §3.3 的单节点/字段语义 |
| 环、孤立、死端、规模、深度、扇入扇出 | `STATE_TRANSITION_DENIED` | 409 | 图级问题 → `reason=DAG_INVALID`（对齐 M02 NEG-M02-16） |
| 类型白名单、模板未注册 | `TOOL_NOT_ALLOWLISTED` | 403 | errors.py 的 trigger 即「工具/模板未登记」 |
| 版本冲突 | `STATE_TRANSITION_DENIED` | 409 | `reason=GRAPH_VERSION_CONFLICT`（见 OQ-P3-03） |
| 预算超限 | `RESOURCE_BUDGET_EXCEEDED` | 429 | `detail.limit_kind` 区分维度 |
| 权限扩大 | `TOOL_NOT_ALLOWLISTED` | 403 | 权限问题，转人工批准 |

### 5.5 失效只写两处（DEC-03 / I-11）

`apply_invalidations()` 逐节点调用 `transition(NODE, node, "INVALIDATED", ctx.cause_*)`；
StateMachine 在**同一事务**写 `evidence_invalidations` + `audit_log`。
本模块不写 `evidence`、不加 `state` 列、不产生 E0–E3、不建 `evidence_rejections`。

### 5.6 重复失效（OQ-CT-12 未决）

已 `INVALIDATED` 的节点不重复迁移（没有合法边），列入 `deferred_reinvalidation` 并告警。
**风险**：该节点若再次受影响，没有新的 invalidation 记录；Gate（P5）必须把
「节点状态 = INVALIDATED」本身当作 stale 判据，不得只看 invalidation 行。

## 6. 待文档同步（不改 05/06/ADR，仅登记）

| 位置 | 现文 | 按裁决应为 | 状态 |
|---|---|---|---|
| 06 §1.2 | `graph_versions` 唯一写者「DAG Builder（经 StateMachine 登记）」 | Orchestrator（`DAG_REGISTER`）+ WP-04 存储；Builder 只计算 | 待文档同步 |
| 06 §3 | `graph_versions` 行：StateMachine W（登记）、Builder 计算 | 登记写者为 Orchestrator（DEC-01） | 待文档同步 |
| 06 §2 | `graph_versions` 插入 + `tasks.graph_version` 更新「必须原子」 | 两段式（本文 §5.3）；`tasks.graph_version` 只能由 StateMachine 写 | 待文档同步 |
| 06 §1.3 | `idempotency_keys.task_id` 可空 | 保持 `NOT NULL` + FK（DEC-02） | 待文档同步（本阶段不改） |
| 05 §9.4 | Evidence 状态机 | 不进 DB；`APPENDED` = 行存在（DEC-03） | 待文档同步（本阶段不改） |

## 7. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| 1. 六类校验各有正例与负例 | `validator.CHECK_MATRIX`（13 条：6 类各 1 正 1 负 + 自环负例）+ `NEGATIVE_TESTS.md` §A | 判据已定义，未执行 |
| 2. worker 超时分支能画出完整回收路径 | 见 M05 `process_control.TREE_KILL_SEQUENCE` + M05 MODULE §6.2 | 见 M05 |
| 3. registry 拒绝未注册模板有明确错误码 | `registry.TemplateNotRegistered.error_code = TOOL_NOT_ALLOWLISTED` | 判据已定义，未执行 |
| 4. 两个 NEGATIVE_TESTS 覆盖环/孤立/越权 patch/越界路径/残留进程/Executor 写状态 | M04 §A–§D、M05 §B–§D | 判据已定义，未执行 |
| 5. Builder 无落库、无 `DAG_REGISTER`；节点创建只经 Orchestrator + M02 仓储 | `builder.BOUNDARY_RULES` + `assert_no_scheduling_surface`；`graph_version` 端口 | 静态可核对，未执行 |
| 6. 未改 M02 schema；evidence 无 state 列；`idempotency_keys.task_id` 未改可空 | 本阶段零改 M02 文件（见自检表）；DEC-02/03 只在本文登记 | 已核对 |

## 8. OPEN QUESTIONS（新增，待用户裁决）

| 编号 | 问题 | 影响 | P3 的临时处理 |
|---|---|---|---|
| `OQ-P3-01` | 图规模上限（节点/边/深度/扇入扇出）没有配置键 | 各实现会各写一套阈值 | `DEFAULT_DAG_LIMITS`（32/160/16/16/8）+ 标注「非契约」，待 ADR-008 配置冻结 |
| `OQ-P3-02` | 「图规模/深度超限」没有专用错误码 | 只能借用 `STATE_TRANSITION_DENIED` | 409 + `reason=DAG_INVALID` + `detail` 带上限与实际值 |
| `OQ-P3-03` | 「图版本冲突」没有专用 409 码 | 只能借用 | `STATE_TRANSITION_DENIED` + `reason=GRAPH_VERSION_CONFLICT` |
| `OQ-P3-04` | `nodes`/`graph_versions` 不存边；回放靠重建 + `graph_hash` | 重建依赖模板注册表冻结 | `verify_rebuild()` fail-closed；差异比较用 `GraphContent` |
| `OQ-P3-05` | `graph_patch` 的审计写者未定义（`audit_log` 唯一写者是 StateMachine） | 改图可能「无审计」 | `PatchAuditPort` 必需；不可用 → `AUDIT_UNAVAILABLE` 拒绝 |
| `OQ-P3-06` | 工作根没有独立配置键（`security.yaml` 只有 `path_allowlist`） | Executor 根目录来源不明 | 由部署注入 + 强制在 `path_allowlist` 内；不改 M03 schema |
| `OQ-P3-07` | 「声明了产物但没写」缺独立子码 | 与「哈希失败」共用一个 fault | 暂用 `ARTIFACT_HASH_FAILED`，落地前补子码（不加注册表码） |
| `OQ-P3-08` | 模板注册表变更会让重建哈希变化 | 旧版本可能无法回放 | `ReplayMismatch` fail-closed；注册表须随发布冻结 |

## 9. 与 M02 / M05 的接口

- **M02**：`CapabilityGatePort` 对应 `_RepositoryBase._require_capability`；
  `NodeRegistrarPort._insert_planned` 对应 `NodeRepository._insert_planned`；
  `UnitOfWorkPort.immediate` 对应 `UnitOfWork.immediate`；
  `TransitionPort.transition` 对应 `StateMachine.transition`。
  本模块**不复制** capability 对象，只把调用方传入的对象原样传给 M02（身份比较）。
- **M05**：Executor 只消费节点参数与产物；`GraphDraft.nodes[*].parameters` 是
  参数进入 `params.json` 的唯一来源。图侧不调用 Executor，Executor 不回写图。

## 10. 本阶段不做

- 不选 READY、不做并发/优先级/资源水位（P7）。
- 不判定 Gate 覆盖、不算 PASS/FAIL（P5）。
- 不实现模板本体、不登记真实模板（P4）。
- 不实现 API、任务创建服务、幂等中间件（P10）。
- 不生成恢复计划、不写 `plan_id/plan_hash`（WP-R）。
- 不改 05/06/ADR/M02/M01/看板/`project_state.json`/`CHANGELOG`。