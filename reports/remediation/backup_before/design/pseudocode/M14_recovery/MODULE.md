# M14 · 定向恢复与失效传播（P7）

> 阶段：P7「调度与定向恢复」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：错误签名与六类分类、§8.4 逐分支的 T0 保守实现、内容寻址的计划冻结、`INVALIDATED→READY` 三条守卫
> 不覆盖：完整 Recovery 状态机（`PROPOSED→…→CLOSED`，仅 T1）、Agent 提案、人工审批、DC/SPA 剪枝（T2）、
> 失效传播本身（P3 `invalidation.py` 已交付，本模块只消费其结果）
> 前置：P3 已验收（`descendants` / 失效集合）、P2 已验收（`StateMachine` 与 `PLAN_THREE_GUARDS`）、ADR-004 已 ACCEPTED
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码

## 1. 目标

把「失败之后做什么」写死为四件可复核的事：

1. **签名稳定**：错误签名只由封闭枚举字段构成，路径/时间/pid/主机名/堆栈一律不进入；
2. **影响面确定**：`affected = descendants(failed) ∪ {failed}`，按拓扑序遍历，集合与顺序都要校验；
3. **动作唯一**：T0 的 `RecoveryAction` 只有 `REEXECUTE`；§8.4 的 `sign_SPA` 分支在 T0 抛异常；
4. **计划不可变**：正文 → JCS 字节 → `plan_hash` → 内容寻址文件名；冻结记录只写 `audit_log`。

FR 归属：`FR-010`（恢复计划与失效传播）在追踪矩阵里是 **T0 最小 + T1 完整**。
本模块交付的是 T0 最小切片的**失败侧**（计划生成 + 冻结 + 三条守卫）；
失效传播与 `INVALIDATED→READY` 的判定入口在 P2/P3，M14 只提供可复用的守卫实现。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `orchestration/recovery/error_signature.py` | 六类分类、每类可重试性、稳定签名（无时间/路径） | 539 | 完成（伪代码） |
| `orchestration/recovery/planner.py` | `affected` 计算与校验、§8.4 逐分支、T0 单动作计划、all-or-nothing | 745 | 完成（伪代码） |
| `orchestration/recovery/plan_freeze.py` | 正文校验、内容寻址存储、冻结审计、三条守卫、`plan_id`/`plan_hash` | 768 | 完成（伪代码） |

计数口径：物理行数（`text.count("\n") + 1`）。三个文件均 ≤ 800 行，按 PHASE_RULES §5 第 1 档无需函数索引。

## 3. 边界（谁写什么）

| 对象 | 唯一写者 | 本模块的落点 |
|---|---|---|
| `nodes.state` / `tasks.state` | **StateMachine** | 不写；`RecoveryPlan` 只是“建议重跑”，不是状态 |
| `audit_log` | **StateMachine**（`RECOVERY_PLAN_FROZEN` 事件由它落库） | 经 `FreezeAuditPort` 请求；模块内**没有 SQL** |
| `evidence_invalidations` | StateMachine（在 `VERIFIED→INVALIDATED` 同事务） | 不写（属 M04/M02）；本模块不产生失效记录 |
| `evidence` | Collector（E0–E2）/ Verifier（E3） | 不写、不改、不删；**不占用 E0–E3** |
| 计划文件 | 本模块（内容寻址、只增不改） | `PlanStore.put`；文件名 = `plan_hash` |
| `nodes.plan_id` / `nodes.plan_hash` | StateMachine（`INVALIDATED→READY` 时写） | 只提供 `plan_id_for()` 与守卫判定 |
| 恢复计划的审批/状态 | **不存在**（T0） | 模块里没有 `RecoveryState`、没有审批字段 |

三条硬化：

1. **控制事件不入证据面**：失效与冻结只写 `audit_log` + `evidence_invalidations`（I-11）；
   本模块没有任何构造 `EvidenceRecord` 的代码，也没有 E0–E3 字面值。
2. **判定权归 StateMachine**：三条守卫在 M02 `_guard_plan_three` 里被再次执行；
   `assert_guard_is_not_a_bypass()` 禁止本模块提供 `transition/set_state`。
3. **无审批**：`assert_no_approval_states()`（planner）与 `assert_no_approval_state()`（plan_freeze）
   扫模块级常量与 dataclass 字段，出现 `PROPOSED/APPROVED/state/status/approved_by` 即失败。

## 4. 对外接口

| 接口 | 语义 |
|---|---|
| `error_signature.signature_from_failure(failure)` | 失败事实 → 稳定签名（六类） |
| `error_signature.ErrorSignature.key_material()` | 签名前像（8 个固定键，交 JCS） |
| `error_signature.CATEGORY_POLICY[cat].plan_eligible_in_t0` | 该类失败在 T0 能否自动重跑 |
| `planner.plan_recovery(...)` | 生成计划或给出升级原因（`RecoveryOutcome`） |
| `planner.affected_nodes_expected(graph, failed)` | `descendants ∪ {failed}` 的集合形态 |
| `planner.assert_topological_subset(order, graph, subset)` | 顺序与集合的双重校验 |
| `plan_freeze.PlanStore(root)` | 内容寻址存储（`path_for` / `put` / `read`） |
| `plan_freeze.freeze_plan(...)` | 规范化 → 哈希 → 落盘 → 冻结审计 |
| `plan_freeze.verify_three_guards(...)` | 三条守卫的检查报告 |
| `plan_freeze.plan_id_for(plan_hash)` | `plan_id` 形态（当前等于 `plan_hash`） |

## 5. 关键设计决定

### 5.1 签名稳定 ⇒ plan_hash 稳定（DEC-M14-01）

签名进入计划正文，正文决定 `plan_hash`。因此签名里**只能有封闭枚举**：

| 允许进签名 | 不允许进签名 | 原因 |
|---|---|---|
| `category`（6 值）、`retryability`（4 值） | 异常原文、stderr 片段 | 每次不同（路径/时间/pid） |
| `error_code`（注册表/内部码） | 堆栈、内存地址 | 每次不同 |
| `disposition`（9 值）、`exit_code_class`（3 值） | 原始 `exit_code=1..255` | 取值空间过大且与“类别”无关 |
| `limit_kind`（6 值）、`fault_code`（20 值） | 主机名、用户名、绝对路径 | 机器相关 |
| `message_class`（7 桶） | 原始 message 文本 | 由 `classify_message()` 归桶后才可用 |

`FailureInput` 的字段里**没有** `message`/`stderr`/`path`/`timestamp` 槽位；想加必须先改
dataclass，会在评审时暴露。`assert_no_volatile_fields()` 对 8 个字段跑易变模式扫描。

### 5.2 六类分类与判定顺序（DEC-M14-02）

判定顺序 `RESOURCE → PROTOCOL → INPUT → DATA → CODE → UNKNOWN`，首命中即类别。

- 顺序是策略：内存超限常表现为“模板非 0 退出”，先判 RESOURCE，否则重跑只会再 OOM 一次；
  链断裂常伴随空产物，先判 PROTOCOL，否则会把“链断了”误判成“数据坏了”。
- `CANCELLED` 落 `UNKNOWN`：取消不是失败，不得自动重跑。
- 未登记的 `disposition`/`fault_code` **抛错**（`SignatureInputInvalid`），不猜成 UNKNOWN：
  “码拼错了”和“失败未知”是两件事。

可重试性与 T0 计划资格：

| 类别 | 可重试性 | T0 生成计划？ | 理由 |
|---|---|---|---|
| `RESOURCE` | `RETRYABLE` | **是**（唯一） | 资源压力可外部解除；同一输入重跑有机会成功 |
| `DATA` | `RETRYABLE_AFTER_FIX` | 否 | 需先证明输入/前驱已变；T0 无该证据端口（OQ-P7-12） |
| `CODE` | `RETRYABLE_AFTER_FIX` | 否 | 模板/注册表要改；T0 无法证明改动已发生 |
| `PROTOCOL` | `NOT_RETRYABLE` | 否 | 链断/序列缺口重跑不会修复 |
| `INPUT` | `NOT_RETRYABLE` | 否 | 改输入属新任务或图变更 |
| `UNKNOWN` | `UNKNOWN_CONSERVATIVE` | 否 | 未知失败不得自动重跑 |

**这不是“只支持资源错误”的偷懒**，而是“只重跑可证明能恢复的失败”：
其余类别返回 `RecoveryOutcome.escalation`，由 Orchestrator 请求 `FAILED→BLOCKED`。

### 5.3 §8.4 的逐分支与 T0 的单动作（DEC-M14-03）

| 分支 | 条件 | T0 决策 | `ReexecuteReason` | T2 才有 |
|---|---|---|---|---|
| ① | `node == failed` 或 `not retryable` | 失败节点：REEXECUTE（不可重试时**不生成计划**） | `FAILED_NODE` | — |
| ② | `has_side_effect` | REEXECUTE | `SIDE_EFFECT` | — |
| ③ | `not evidence_valid` | REEXECUTE | `NO_VALID_EVIDENCE` | — |
| ④ | `not predecessor_hashes_unchanged` | REEXECUTE | `PREDECESSOR_HASH_CHANGED` | — |
| ⑤ | `not valid_DC` | REEXECUTE（T0 恒真） | `NO_VALID_DC` | DC |
| ⑥ | `not disk_rehash_matches` | REEXECUTE（T0 被 ⑤ 挡住，仍求值记录） | `DISK_REHASH_MISMATCH` | — |
| ⑦ | `not gate_passes_under_current_rules` | REEXECUTE（同上） | `GATE_NOT_PASSING` | — |
| ⑧ | else | **抛 `SpaForbiddenInT0`** | — | SPA |

`RecoveryAction` 只有一个成员；`assert_t0_single_action()` 断言成员数 = 1 且无 `SKIP/SPA/DEFER` 名。
七项检查**全部求值**（诊断需要），但决策理由只取第一条失败的分支（与 if/elif 语义一致）。

### 5.4 all-or-nothing（DEC-M14-04）

受影响集合里任一节点没有重试预算 → **不生成计划**，返回 `escalation(NO_RETRY_BUDGET)`。
理由：半套计划会制造“上游跑了、下游跑不动”的不可解释状态，比不做更危险
（与 M04 `apply_invalidations` 中途失败即整体报告同一口径）。

### 5.5 存储与三条守卫（DEC-M14-05）

- **文件名 = `plan_hash`**（64 位小写十六进制，无扩展名）：`path_for()` 只接受该形态，
  拼出路径再做前缀断言，杜绝 `../` 与目录逃逸；
- **不入库**：`plan_id`/`plan_hash` 由 `nodes` 两列保存，写入者是 StateMachine；
- **只增不改**：目标已存在时比对字节，相同 → 幂等返回，不同 → `PlanStoreCorrupt`（绝不覆盖）；
- **冻结记录**：`FreezeRecord.frozen_at` 由时钟提供，只进审计；审计不可用 → `AUDIT_WRITE_FAILED` 拒绝冻结
  （没有冻结记录的计划永远过不了守卫 2/3，所以不能“先落盘再说”）；
- **三条守卫**（`PLAN_HASH_MISMATCH` + 具体 reason）：
  1. `PLAN_FILE_MISSING`：文件不存在/不可读；
  2. `PLAN_FREEZE_RECORD_MISSING` / `PLAN_HASH_MISMATCH` / `PLAN_ID_MISMATCH`：哈希与冻结记录不一致；
  3. `PLAN_FROZEN_AFTER_RERUN`：冻结**不严格早于**重跑。时间先规范化到 **30 字符（小数补足 9 位）** 的
     `...Z` 形态再比较——`Z` 与 `+00:00` 直接做字符串比较会把“同刻冻结”判成“冻结更晚”，是一个放行方向的漏洞。
     注意：`ClockPort.now_utc()` 的**输入契约**是定长的秒级/微秒 UTC 形态（见其 docstring）；
     30 字符是 `_normalize_utc()` 的比较专用形态，两者不得混用。

### 5.6 `plan_id` 的当前形态（DEC-M14-06）

`plan_id = plan_hash`。ENCODING_RULES §1 明确 `plan_` **不是**既定前缀、`plan_id` 形态未定（OQ-P7-08）。
用哈希本身作身份是“最小假设”：不新造前缀、不引入第二套标识，同时满足 05 §9.3
「`plan_id` + `plan_hash` 成对」的要求。M02 的 `PLAN_ID_MISMATCH` 分支保留为纵深防御。

### 5.7 `plan_hash` 稳定性的完整论证（验收判据 3，DEC-M14-07）

**结论：同一输入两次生成的 `plan_hash` 必然相同。** 七条支撑，任何一条失效都会破坏结论：

1. **纯函数**：`planner.plan_recovery` 只读端口（`RecoveryFactsPort` / `OrderingPort`），
   不读时钟、不读随机源、不读环境变量、不读工作目录。
2. **键集合封闭**：正文恰好 9 个键且**顺序固定**（`assert_plan_structure`）；多一个键即失败。
3. **顺序确定**：决策顺序 = 受影响子图拓扑序（`assert_topological_subset`），
   不依赖 `set`/`dict` 迭代序；集合只在比较时使用，输出前转 `tuple`。
4. **无易变内容**：`assert_body_time_free` 同时扫**键名**（`FORBIDDEN_BODY_KEYS`：`frozen_at`/`created_at`/
   `timestamp`/`pid`/`hostname`/`tmp_dir`…）与**值**（RFC3339/绝对路径/pid/地址），命中即拒绝冻结。
5. **规范化由 JCS 完成**：`canonical_bytes` 来自 M01（RFC 8785），
   **不是** `json.dumps(sort_keys=True)`（码点序 ≠ UTF-16 码元序；ENCODING_RULES §5）；
   数组顺序由 JCS 保留，所以决策顺序必须在正文里已是拓扑序。
6. **哈希与命名同源**：`plan_hash = sha256(字节)`，文件名 = `plan_hash`；
   同内容重复冻结是幂等（同文件、同哈希），不会产生两个身份。
7. **身份不进正文**：`plan_id`/`plan_hash` 不写进正文（自指会让哈希无解），
   它们只出现在文件名、`nodes` 两列与审计记录里。

**验证方式（落地阶段必须真实执行）**：

- `assert_reproducible(make_body)`：同一工厂生成两次，断言字节相同、哈希相同（`GUARD-M14-01`）；
- `NEG-M14-17`：两次生成比对；`NEG-M14-12/13/14`：往正文注入时间/路径/pid 必须被拒绝；
- `NEG-M14-18`：JCS 与 `json.dumps(sort_keys=True)` 在 astral 字符上必须产生不同字节；
- 跨进程复现依赖 JCS 与 SHA-256 实现一致（P6 已冻结口径），本阶段不声称已实测跨机。

**边界**：以上只证明“同输入同哈希”，不证明“计划一定正确”或“恢复一定成功”。

## 6. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| 1. 六类分类各有可执行判据与可重试性 | `ErrorCategory` / `CATEGORY_POLICY` / `signature_from_failure` 六步；`assert_classification_total()` | 已定义，未执行 |
| 2. `affected = descendants ∪ {failed}` 且拓扑序 | `affected_nodes_expected()` + `assert_topological_subset()`；`NEG-M14-07/08/09` | 已定义，未执行 |
| 3. T0 只有 REEXECUTE、无 SPA 分支 | `RecoveryAction`（1 个成员）、`_decide` 的 ⑧ 抛 `SpaForbiddenInT0`、`assert_t0_single_action()` | 已定义，未执行 |
| 4. 计划两次生成同哈希（明确论证） | §5.7 七条 + `HASH_STABILITY_ARGUMENT` + `assert_reproducible()`；`NEG-M14-17`、`GUARD-M14-01` | 论证已写，**未实测** |
| 5. 无 PROPOSED/APPROVED、无审批 | `assert_no_approval_states()`、`assert_no_approval_state()`；`NEG-M14-22/23` | 已定义，未执行 |
| 6. 控制事件不入 E0–E3 | §3 边界表；模块里无 `EvidenceRecord` 构造、无 E0–E3 字面值 | 已核对（静态） |
| 7. 三条守卫各有一负例 | `guard_plan_file_present` / `guard_plan_hash_matches` / `guard_frozen_before_rerun`；`NEG-M14-26/27/29` | 已定义，未执行 |
| 8. 守卫缺省不得放行 | `verify_three_guards` 对 `freeze_record=None` 返回 `PLAN_FREEZE_RECORD_MISSING`；`NEG-M14-28` | 已定义，未执行 |

## 7. OPEN QUESTIONS（详见 `design/pseudocode/OPEN_QUESTIONS.md`）

| 编号 | 问题 | P7 临时处理 |
|---|---|---|
| `OQ-P7-08` | `plan_id` 形态未定（`plan_` 不是既定前缀） | `plan_id = plan_hash`；不新造前缀；M02 的 `PLAN_ID_MISMATCH` 保留为纵深防御 |
| `OQ-P7-09` | 计划文件无扩展名、目录布局与保留策略未定 | 严格按 ADR-004「文件名=SHA-256」用裸哈希名；保留/GC 留给 WP-R |
| `OQ-P7-10` | 计划不是七契约之一，`plan_format_version` 属新造 | 用 `plan_format_version`（**不是** `schema_version`）；未知版本拒绝冻结 |
| `OQ-P7-11` | `RECOVERY_PLAN_FROZEN` 审计只有一个 `node_id`，计划却跨多节点 | 用失败节点作为 `node_id`；多节点归属待裁决 |
| `OQ-P7-12` | `DATA`/`CODE` 类要求“输入已变/修复已发生”的证据，T0 无该端口 | T0 只对 `RESOURCE` 生成计划；其余升级，不自动重跑 |

## 8. 已知局限（P7-FIX1 登记）与本阶段不做

### 8.1 已知局限（P7-FIX1 登记）

以下 4 条是**未实现 / 设计约定**，不得读作“已实现”或“已核对通过”：

| # | 现状 | 影响 | 落地阶段必须补 |
|---|---|---|---|
| L1 | `PlanStore.exists/read/put` 与 `plan_hash_of` 是 `NotImplementedError` 桩；「已存在则比字节、不同即 `PlanStoreCorrupt`」目前**只在 docstring** | 内容寻址的「只增不改」尚未成为可执行行为；任何依赖它的守卫测试都无从运行 | 实现原子写（临时文件 + `os.replace`）、读回重算哈希、冲突拒绝；用 NEG-M14-34 锁定 |
| L2 | `freeze_plan` **不做正文结构校验**：`canonical_plan_bytes` 只查版本与时间，也不核对 `body["task_id"]/["failed_node"]` 与记录参数一致 | 正文键集合/顺序被改（例如多一个键）仍能冻结；冻结记录与正文可能描述不同任务 | 冻结前调用 `planner.assert_plan_structure()`，并新增 task_id/failed_node 一致性校验 |
| L3 | 正文含 `policy.approval_required=False`（`planner.py:105,362`），而 `assert_t0_single_action()` 只钉 `dc_used/spa_used` | 把它改成 `True` 会改变 `plan_hash`，但两个自检仍返回 `[]`——自检覆盖不到这个键 | 把 `approval_required` 纳入 `assert_t0_single_action()`（T0 必须为 `False`） |
| L4 | `FreezeAuditPort` 只有 `Protocol`，`design/pseudocode/` 内**没有实现** | 「唯一实现是 StateMachine 审计服务」是设计约定，不是既有代码事实；冻结审计的落库时机/事务边界未验证 | WP-R 落地时接 StateMachine 审计服务，并用真实 SQLite 事务负例验证 `AUDIT_WRITE_FAILED` 分支 |

### 8.2 本阶段不做

- 不做完整 Recovery 状态机（`PROPOSED→VALIDATED→APPROVED→EXECUTING→RECHECKED→CLOSED`）：T1/G4。
- 不做 Agent 提案、不做人工审批界面、不期望恢复请求走 API（T0 无 `POST /recover`）。
- 不做 DC/SPA（T2）：不签资格、不剪枝、不写 `skipped_nodes`。
- 不实现失效传播与 `INVALIDATED→READY` 的**判定入口**（P2/P3 已定）：本模块只提供守卫实现与负例锚点。
- 不做计划保留期/GC、不做跨机复现实测、不做包导出（WP-R/WP-12）。
- 不改 `contracts/`、不改 `docs/design/05`、不改 ADR、不改看板。