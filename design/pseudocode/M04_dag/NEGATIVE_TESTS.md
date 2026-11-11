# M04 · NEGATIVE_TESTS — 负例判据（P3）

> 阶段：P3｜状态：**判据定义，未执行**（本阶段限权：不建环境、不跑测试、不写业务代码）
> 执行阶段：M04 落地（WP-04 之后）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P3 不得写成"已通过"**。
> 数据库：真实 SQLite 文件（WAL）；禁止 mock 替代 `_insert_planned` / `transition` 的拒绝路径。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：`violation`（或 `reason`）+ `error_code` + 涉及节点中
   至少两项与下表一致；只断言"被拒绝了"判测试失败。
2. 涉及 `ValidationReport` 的负例必须断言 `report.ok is False`、`primary().violation`、
   `primary().nodes`、`primary().error_code`；多违规时断言**全部**违规码集合。
3. 涉及登记的负例必须断言：`nodes` 行数不变、`graph_versions` 行数不变、
   `tasks.state` 与 `tasks.graph_version` 未变。
4. 涉及 patch 的负例必须断言：`decision`、`findings` 中的 `violation`、
   **未**发生登记（`next_graph_version` 只是建议值，不等于已登记）。
5. 静态边界负例（§D）必须断言具体禁名/禁调用，不得只断言"看起来没有"。
6. 原因不符即失败；不得改期望值、放宽阈值、用"重试通过"覆盖失败记录。
7. 本表每条只计一次；同一用例重复运行不构成独立样本。
8. 正例通过不构成完成证据；本表必须真实执行并逐条留下拒绝原因。
9. 静态边界负例（§D）用 `ast` 断言 `import`/`call`/字段集合；源码中的注释、docstring、
   普通字符串常量（如 `BOUNDARY_RULES`、`FORBIDDEN_SURFACE` 自身）**不算命中**，
   也不得用“文本里出现过该词”当作已检查的证据。

## A. 图结构六类（对应 `validator.CHECK_MATRIX`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M04-01 | 环图被拒 | `a→b→c→a`，`validate_graph` | `ok=False`；`violation=CYCLE`；`error_code=STATE_TRANSITION_DENIED`；`nodes` 含 `a,b,c,a`；`detail` 含 `→` 路径 | 05 §3.3；`check_cycles` |
| NEG-M04-02 | 自环被拒 | `a.depends_on=["a"]` | `violation=SELF_LOOP`；`error_code=SCHEMA_INVALID`（422）；`field_path="nodes.a.depends_on"` | 05 §3.3 SEM-NS-01 |
| NEG-M04-03 | 孤立节点被拒 | 合法链 `a→b` 外挂游离节点 `z` | `violation=ORPHAN_NODE`；`nodes=(z,)`；`error_code=STATE_TRANSITION_DENIED`；**不得**把 `z` 当正常节点放行 | 05 §13；`check_orphans` |
| NEG-M04-04 | 死端被拒 | `a→b`、`b→c`、`c→b`（b/c 成环），`d→b` | `violation` 集合含 `CYCLE`；`d` 若到不了汇点 → `DEAD_END_NODE`；**不得**只报 `CYCLE` 而漏 `d` | 05 §13 |
| NEG-M04-05 | 重复边被拒 | `b.depends_on=["a","a"]` | `violation=DUPLICATE_EDGE`；`nodes=(b,a)`；`detail` 含"重复 2 次" | 策划书 §6.1 |
| NEG-M04-06 | 重复节点被拒 | `node_ids=["a","a"]` | `violation=DUPLICATE_NODE_ID`；`nodes=(a,)` | 05 §3.3 |
| NEG-M04-07 | 悬空依赖被拒 | `b.depends_on=["ghost"]` | `violation=UNKNOWN_DEPENDENCY`；`nodes=(b,ghost)` | 05 §3.3 |
| NEG-M04-08 | 节点类型不在白名单 | `node_type="os.shell"` | `violation=NODE_TYPE_NOT_ALLOWED`；`error_code=TOOL_NOT_ALLOWLISTED`（403） | 05 §3.1 |
| NEG-M04-09 | 未注册模板 | `template_id="ghost@1.0.0"` | `violation=TEMPLATE_NOT_REGISTERED`；`error_code=TOOL_NOT_ALLOWLISTED`；**不得**回退到同名其它版本 | 05 §3.1 |
| NEG-M04-10 | 图规模超限 | 33 节点（`DEFAULT_DAG_LIMITS.max_nodes=32`） | `violation=GRAPH_TOO_LARGE`；`detail` 含 `33 > 32`；`nodes` 列出全部节点 | 策划书 §8.9 |
| NEG-M04-11 | 图深度超限 | 深度 17（`max_depth=16`） | `violation=GRAPH_TOO_DEEP`；`nodes=(最深节点,)`；`detail` 含 `17 > 16` | 策划书 §8.9 |
| NEG-M04-12 | 引用无生产者 | `input_refs=["artifact://ghost_metrics"]` | `violation=INPUT_REF_UNRESOLVED`；`error_code=SCHEMA_INVALID`（422） | 05 §3.1 |
| NEG-M04-13 | 引用非上游 | `predict` 引用 `report` 才产出的 `artifact://final_metrics` | `violation=INPUT_REF_NOT_UPSTREAM`；`nodes=(predict, report)` | 05 §3.1 |
| NEG-M04-14 | 引用形态非法 | `input_refs=["artifact://../etc/passwd"]`、`["C:/x"]`、`["artifact://con"]` | 三条均 `violation=INPUT_REF_FORMAT_INVALID`；**不得**归一化后放行 | 05 §3.2 |
| NEG-M04-15 | 产物生产二义 | 两个节点都声明产出 `split_manifest`（端口 `producers_of` 返回两个） | `violation=ARTIFACT_DUPLICATE_PRODUCER`；`nodes` 含消费者与两个生产者 | 05 §3.1 |

## B. 版本、登记与回放

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M04-16 | 版本落后被拒 | 已登记 v2，登记 v1 | `GraphVersionConflict`；`reason=GRAPH_VERSION_CONFLICT`；`error_code=STATE_TRANSITION_DENIED`；`http_status=409`；`as_detail()` 含 `requested=1, latest=2` | 06 §1.3/§4.1 |
| NEG-M04-17 | 版本跳号被拒 | 已登记 v1，登记 v3 | `GraphVersionState.GAP`；`GraphVersionConflict`；**不得**自动补 v2 | 06 §1.3 |
| NEG-M04-18 | 同版本不同哈希被拒 | v2 已登记，再提交 v2 但 `graph_hash` 不同 | `GraphVersionConflict`；`detail` 含"版本不可改写"；`graph_versions` 行数不变 | 06 §1.3 |
| NEG-M04-19 | 无校验凭证不得登记 | `register(draft, report=None, ...)` | `RegistrationRejected`；`violation=VALIDATION_MISSING`；`nodes` 行数不变 | 06 §2 |
| NEG-M04-20 | 校验未通过不得登记 | `report.ok=False`（例如环图） | `violation=VALIDATION_FAILED`；`error_code` 等于报告的 `primary().error_code`；`detail` 含 `reason=DAG_INVALID` | 06 §2 |
| NEG-M04-21 | 拓扑序不一致不得登记 | 报告通过，但 `report.topology != draft.topology_order` | `violation=TOPOLOGY_MISMATCH`；提示"草案可能在提交后被改过" | 06 §2 |
| NEG-M04-22 | 无 capability 不得登记 | `capability=object()` | `violation=CAPABILITY_DENIED`；`detail` 含 `DAG_REGISTER`；`nodes`/`graph_versions` 均不变 | DEC-01；M02 仓储 |
| NEG-M04-23 | 非法哈希不得登记 | `draft.graph_hash="ABC"` / 大写 / 63 位 | `violation=HASH_INVALID`；**不得**自动小写化或补零 | ENCODING_RULES §4 |
| NEG-M04-24 | 重建不一致必须 fail-closed | 已登记 v1，模板默认参数被改后重建 | `ReplayMismatch`；`reason=GRAPH_REPLAY_MISMATCH`；`expected != actual`；**不得**继续算失效 | ADR-001；本文 §5.2 |

## C. graph_patch 审批（策划书 §8.9）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M04-25 | 越权 patch：扩大权限 | 把 `PURE_FUNCTION` 节点换成 `SIDE_EFFECT` 模板；或新增 `network_allowed` 模板；或提高 `max_wall_time_sec` | `decision=APPROVAL_REQUIRED`（无票）或 `ACCEPT_WITH_APPROVAL`（有票）；`findings` 含 `PERMISSION_EXPANSION`；`error_code=TOOL_NOT_ALLOWLISTED`；**不得**静默 ACCEPT | 策划书 §8.9 |
| NEG-M04-26 | 越权 patch：无票不得登记 | 同上，`ctx.approval=None` | `decision=APPROVAL_REQUIRED`；`requires_approval=True`；`candidate` 不进入登记；`graph_versions` 行数不变 | 策划书 §8.9 |
| NEG-M04-27 | 批准票错配 | 提供 `ApprovalTicket(patch_hash=<另一份补丁>)` | 仍 `APPROVAL_REQUIRED`；`findings` 含 `APPROVAL_REQUIRED`；**不得**按"有票就过" | 05 §13（绑定哈希） |
| NEG-M04-28 | 已执行节点被静默重写 | 节点 `attempt_seq=1`，patch 改其 `parameters` | `decision=REJECT`；`findings` 含 `EXECUTED_NODE_REWRITE`；`error_code=STATE_TRANSITION_DENIED` | 策划书 §8.9 |
| NEG-M04-29 | 删除必检项 | patch `required_checks=[]` 或删掉 `l3` 相关项 | `findings` 含 `REQUIRED_CHECKS_REMOVED`；`requires_approval=True`；空数组另由 `UNSUPPORTED_OP` 拒绝 | 策划书 §8.9「不得静默取消必检项或 L3」 |
| NEG-M04-30 | 预算超限 | 剩余 wall=100s，patch 新增模板合计 200s | `findings` 含 `BUDGET_EXCEEDED`；`error_code=RESOURCE_BUDGET_EXCEEDED`（429）；`detail` 含 `limit_kind=wall_clock` | 策划书 §8.9；M03 limits |
| NEG-M04-31 | 非 PLANNING 阶段改图 | `task_state="READY"` 提交 patch | `findings` 含 `PLAN_NOT_ALLOWED`（`reason=GRAPH_PATCH_NOT_ALLOWED`）；`decision=REJECT` | 本文 §5.3 |
| NEG-M04-32 | 旧基线补丁 | `patch.base_graph_version=1`，当前=2 | `findings` 含 `BASE_VERSION_STALE`；`reason=GRAPH_VERSION_CONFLICT` | 06 §1.3 |
| NEG-M04-33 | 审计不可用 | `ctx.audit_available=False` | `findings` 含 `AUDIT_UNAVAILABLE`；`decision=REJECT`；**不得**"先改图后补审计" | OQ-P3-05；06 §3 |
| NEG-M04-34 | patch 引入环 | 给 `a→b` 再加 `b→a` | `findings` 含 `CYCLE_INTRODUCED`；`error_code=STATE_TRANSITION_DENIED`；`reason=DAG_INVALID` | 策划书 §8.9 |

## D. 静态边界（Builder / 写者）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M04-35 | Builder 无调度入口 | `builder.assert_no_scheduling_surface()`；`dir(builder)` | 返回 `[]`；模块级不得出现 `next_node`/`ready_set`/`dispatch`/`schedule` 等 16 个禁名（完整清单见 `builder.FORBIDDEN_SURFACE`） | 用户判据 5；07 §2.4 |
| NEG-M04-36 | Builder 无落库调用 | `ast.parse` 扫 `builder.py`，只断言 AST 节点；注释、docstring、普通字符串常量不计入 | ① `Import`/`ImportFrom` 的模块名不含仓储/`graph_version`/`state_machine`；② `Call` 不出现 `_insert_planned`/`insert`/`transition`/`commit`；③ `GraphDraft.__dataclass_fields__` 不含 `save`/`repository` | DEC-01 |
| NEG-M04-37 | M04 不得直写状态 | `ast.parse` 扫 M04 五个 `.py`，只断言 AST 节点；说明文字（注释/docstring/常量）不计入 | ① 无 `UPDATE`/`INSERT`/`DELETE` 的 SQL 执行调用；② `transition` 的 `Call` 只允许在 `invalidation.py`（且为 `TransitionPort.transition`），`graph_version.py` 只组装 `ReadyTransitionRequest`、无实际 `transition` 调用；③ `audit_log`/`evidence` 只允许出现在说明文字，无写调用 | 06 §3；I-01 |
| NEG-M04-38 | 未新增错误码 | 扫描 `VIOLATION_SPECS`/`BUILD_VIOLATIONS`/`PATCH_VIOLATION_SPECS` 的 `error_code` 集合 | 只允许 `{SCHEMA_INVALID, TOOL_NOT_ALLOWLISTED, STATE_TRANSITION_DENIED, RESOURCE_BUDGET_EXCEEDED}`；注册表仍 27 条 | M01 errors；用户判据 6 |
| NEG-M04-39 | 自检函数本身有效 | 人为把某个 `ViolationSpec.fail_closed` 改成 False | `assert_validator_contract()` 返回非空且提示该违规；**否则自检是摆设** | AGENTS §8 负例纪律 |

## E. 误拒守卫（防止"过度收紧"把合法输入拒掉）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M04-01 | 主线 DAG 必须通过 | 10 节点/9 边/深度 7（`MAINLINE_DAG_SKETCH`） | `ok=True`；`topology` 长度 10；无 findings | 策划书 §14.2 |
| GUARD-M04-02 | 单节点图合法 | 只有 `dataset_profile` 一个节点 | `ok=True`；**不得**因"没有边"报 `ORPHAN_NODE` | 05 §13 |
| GUARD-M04-03 | 空差异不是失效 | `diff_graphs(v1, v1')` 内容相同、版本号 +1 | `GraphDiff.is_empty is True`；`build_invalidation_set` 返回 `targets=()` 且**不抛异常** | 本文 §5.3 |
| GUARD-M04-04 | 合法小补丁直接 ACCEPT | PLANNING 阶段、只新增一个下游节点、不动已执行节点 | `decision=ACCEPT`；`requires_approval=False`；`findings` 为空 | 策划书 §8.9 |
| GUARD-M04-05 | 正常版本递增不报冲突 | `compare_versions(1, 2)` | `GraphVersionState.NEXT`；**不得**因"版本号跳变"误判（连续 +1 是正常） | 06 §1.3 |

## F. 执行记录模板（落地阶段填写，P3 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M04-01 | （待执行） | — | — | — | 未执行 |
| NEG-M04-16 | （待执行） | — | — | — | 未执行 |
| NEG-M04-25 | （待执行） | — | — | — | 未执行 |
| NEG-M04-35 | （待执行） | — | — | — | 未执行 |