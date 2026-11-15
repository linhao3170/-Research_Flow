# M15 · DC 与 SPA（P9）

> 阶段：P9「DC/SPA 与 VAS」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：DC 六类资格条件、DC 签发/过期/撤销、SPA 五项判定、PRR 逐节点台账
> 不覆盖：重跑本身（P7/M14）、Scheduler/Governor（P7/M13）、L1–L3 验证（P5/M09–M10）、
> 签名算法实现（P6/M11）、Gate 判定（P5/M08）、科学正确性裁决
> 前置：P5/P6/P7 设计产物存在；验收状态以 `docs/state/project_state.json` 为准（P5–P8 设计件已验收；P9 `BLOCKED`）；T2 能力，**T0/T1 不启用**
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码
>
> **复核修正（2026-11-11）**：本模块 4 个 `.py` 由并发进程于 22:53:54–55 重写并落盘，不是原始正文恢复；未运行测试、未验收；P9 在状态源中为 `BLOCKED`。下方“完成（伪代码）”只表示文件存在，不表示已验证。

## 1. 目标

把两个“省成本”的机制写成“条件不满足就退回保守方案”的形状：

1. **DC** 只证明“在某节点类型、固定输入/代码/依赖/环境/规则下，观察到 k 次跨进程跨目录
   bit-exact 一致”的**经验性资格**，不是确定性证明；随机性或副作用节点一票否决。
2. **SPA** 只有五项条件**同时**有证据才允许跳过；默认动作是 `REEXECUTE`，
   任何一项拿不到证据也返回 `REEXECUTE`。
3. **PRR** 逐节点记录“剪了谁、事后是否重跑、结果是否变化”；没有分母不得报 0，
   不跨任务合并。
4. 所有“省成本”的路径都可追溯到签名凭证与逐节点原始行；没有“因为看起来一样所以跳过”。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `orchestration/determinism/dc_eligibility.py` | 六类条件、随机性否决、k 次 bit-exact 比对、有效期/规则版本 | 1,173 | 存在（并发重写，未测试） |
| `orchestration/determinism/dc_issuer.py` | DC identity/内容寻址 ID、签发、过期、撤销、复用判定 | 1,035 | 存在（并发重写，未测试） |
| `orchestration/determinism/spa_judge.py` | 五项条件、证据对象、签名记录、默认 REEXECUTE | 1,227 | 存在（并发重写，未测试） |
| `orchestration/determinism/prr_ledger.py` | 逐节点剪枝/重跑/结果变化台账、精确二项上界 | 830 | 存在（并发重写，未测试） |

计数口径：物理行数。四个文件均在 800–1500 行档，按 PHASE_RULES §5 第 2 档在 §3 登记完整函数索引；不拆分，理由见 §6.8。

## 3. 文件导航（PHASE_RULES §5 第 2 档：四个文件均在 800–1500 行）

> 行数为物理行数。索引由脚本按 AST 起始行生成，不手填，避免「文档指向不存在的函数」。
> 依据列统一见各函数 docstring 内的章节号。

### 3.1 `dc_eligibility.py`（1,173 行，32 个类/函数）

> 六类条件、k 次 bit-exact 比对、随机性否决、有效期。索引按源码起始行生成，与文件一一对应。

| 名称 | 起始行 | 职责（docstring 首行） |
|---|---:|---|
| `Condition` | 77 | §8.2 TABLE 34 的六行，顺序即表格顺序（报告顺序）。 |
| `DcReason` | 168 | 不通过原因。每条对应一个可断言的判断点。 |
| `ConditionStatus` | 196 | 条件结论。`MISSING_EVIDENCE` 与 `FAIL` 都不得当成通过。 |
| `PurityClass` | 205 | 节点纯度分类。`STRICT_PURE` 是唯一可申请 DC 的类别。 |
| `DcEligibilityError` | 230 | 输入事实自相矛盾（不是「资格不合格」）。对外 422。 |
| `DcNotEnabled` | 243 | T0/T1 或 `dc_spa=false` 时申请 DC：能力未开。对外 403。 |
| `DcPolicy` | 259 | DC 判定参数。除 `k_min=3` 外全部是 PROPOSED（OQ-P9-04/05）。 |
| `DcCandidate` | 287 | 节点的静态声明：能决定「能不能申请 DC」的那部分。 |
| `DcBinding` | 314 | §8.2「输入固定」要求绑定的一整套哈希（缺一项即 MISSING_EVIDENCE）。 |
| `EnvComparisonView` | 353 | M03 环境比较结果的只读投影：每个组成项是否与历史一致。 |
| `RunProbe` | 379 | 单次探针运行的可观测事实（由 M05 采集，本文件只读）。 |
| `ConditionResult` | 415 | 一条条件的结论。 |
| `RunComparison` | 472 | k 次运行比对结果。`bit_exact` 为真时才可能签 DC。 |
| `EligibilityVerdict` | 511 | 六条件结论汇总。`eligible` 由结构强制，不由调用方填。 |
| `_require_hash` | 574 | 哈希必须是 64 位小写十六进制（ENCODING_RULES §4）。 |
| `_require_utc` | 582 | 时间必须是带时区的 UTC（不接受 naive，不猜本地时区）。 |
| `_canonical_directory` | 590 | 目录比较用的保守规范化：去尾分隔符、转小写、统一分隔符。 |
| `required_k` | 605 | 按敏感因素计算所需探针次数：`k_min + step × 因子数`，封顶 `k_max`。 |
| `_divergent` | 624 | 构造一条「不通过」的检查行。 |
| `compare_runs` | 629 | 比对 k 次探针运行是否 bit-exact，并检查「独立」与「未被复用」。 |
| `_randomness_result` | 769 | 条件 5：随机性节点一票否决（EVALUATION_ORDER 第一位）。 |
| `_purity_result` | 800 | 条件 1：节点纯度。任一污染源命中即「永不签 DC」。 |
| `_input_fixed_result` | 842 | 条件 2：输入固定。数据/配置/代码/模板/依赖/上游哈希必须齐全且一致。 |
| `_env_result` | 868 | 条件 3：环境指纹。七组成项缺一项即不完整；不一致即失效。 |
| `_k_run_result` | 909 | 条件 4：重复执行。k 次跨进程跨目录且产物/指标 bit-exact。 |
| `_reason_of` | 952 | 从失败的检查行反推原因，保证条件结果与比对明细一致。 |
| `_validity_result` | 964 | 条件 6：有效期与规则版本。四个字段必须在、未过期、TTL 不超上限。 |
| `evaluate_dc_eligibility` | 1015 | 六条件逐条判定，返回资格结论（不签发）。 |
| `assert_randomness_is_veto` | 1082 | 随机性必须是否决项，且结构上无法绕过。返回空元组表示通过。 |
| `assert_conservative_defaults` | 1112 | 缺证据不得通过；默认策略必须保守。返回空元组表示通过。 |
| `assert_scope_statement` | 1136 | 限定语必须写明「不是数学确定性证明」。返回空元组表示通过。 |
| `assert_condition_math` | 1147 | 六条件齐全、k 单调、封顶生效。返回空元组表示通过。 |

### 3.2 `dc_issuer.py`（1,035 行，33 个类/函数）

> 内容寻址 ID、签发、过期、撤销、复用判定。索引按源码起始行生成，与文件一一对应。

| 名称 | 起始行 | 职责（docstring 首行） |
|---|---:|---|
| `DcIssuerError` | 116 | 签发链路错误基类。 |
| `DcRefused` | 139 | 拒绝签发或拒绝状态变更（资格不足、开关关闭、已撤销）。对外 409。 |
| `DcSignatureInvalid` | 146 | 签名失败或回验失败。对外 422。 |
| `DcStoreCorrupt` | 153 | 登记表被改写：同一 `dc_id` 出现两份不同内容。对外 409。 |
| `DcRevoked` | 160 | DC 已撤销（终态）。对外 409。 |
| `_require_hash` | 170 | 64 位小写十六进制（ENCODING_RULES §4）。 |
| `_require_utc_datetime` | 178 | 只接受带时区的 UTC datetime（不猜本地时区）。 |
| `_utc_z` | 186 | UTC datetime → RFC3339 `...Z`（§7.5 时间写法）。 |
| `_parse_utc_z` | 192 | RFC3339 `...Z` → UTC datetime；格式不符直接拒绝。 |
| `_canonical_bytes` | 201 | 规范化字节串（占位）。 |
| `DcSignerPort` | 215 | T2 签名端口。P9 **没有**合规实现（OQ-P6-02：M11 拒绝未冻结载荷）。 |
| `DcSignature` | 229 | 签名信封。`signed_body_hash` 把「签的是哪份正文」也钉住。 |
| `DcIdentity` | 264 | D.5 中除 `dc_id` / `signature` 外的 11 个字段。 |
| `compute_dc_id` | 324 | 内容寻址 `dc_id` = `sha256(JCS(identity))`，64 位小写十六进制、**无前缀**。 |
| `DcAudit` | 339 | 签发/撤销审计（**不进签名正文**，否则无法在事后补记）。 |
| `DcRecord` | 355 | 已签发的 DC：D.5 的 13 个字段 + 签名信封 + 审计（审计不参与签名）。 |
| `RevocationReason` | 387 | 撤销原因。原文未给枚举（OQ-P9-05 同源），这里是 PROPOSED 但必须显式。 |
| `RevocationRecord` | 399 | 撤销记录：只追加，**没有** `unrevoke` / `restore`。 |
| `DcStatus` | 427 | DC 复用状态。`VALID` 是唯一允许 SPA 条件 1 通过的值。 |
| `DcValidityReport` | 445 | 一次复用判定的结果：`validity` + 逐项原因（不只给布尔）。 |
| `DcRegistry` | 493 | P9 的内存登记表。T2 落地换真实存储；语义保持一致： |
| `DcIssuance` | 557 | 签发结果：记录 + 重算依据 + 登记表规模。 |
| `_derive_output_hashes` | 583 | 从探针派生排序去重的产物哈希集（OQ-P9-02）。 |
| `_derive_run_fingerprints` | 594 | 从探针派生运行指纹（保持探针顺序，供 D.5 逐条核对）。 |
| `issue_dc` | 599 | 签发一张 DC。资格不合格、重算不一致、无签名器、TTL 超限一律拒绝。 |
| `evaluate_dc_record` | 728 | 判定一张 DC 现在还能不能用（§8.3 条件 1 的唯一入口）。 |
| `_invalid` | 854 | 构造「签名有效但绑定变化」的判定结果。 |
| `evaluate_dc` | 871 | 按 ID 取记录再判定。未登记时返回 `NOT_ELIGIBLE`（缺证据，不是通过）。 |
| `revoke_dc` | 908 | 撤销一张 DC。终态：重复撤销抛 `DcRevoked`，没有恢复入口。 |
| `assert_signature_domain` | 950 | 域前缀、算法、签名字段集合必须与 §7.5 一致。返回空元组表示通过。 |
| `assert_dc_scope` | 970 | `eligible=False` 不得产生记录；限定语不得被改写成「已证明确定」。返回空元组表示通过。 |
| `assert_revocation_is_terminal` | 1011 | 撤销必须终态：重复撤销失败，且登记表无恢复方法。返回空元组表示通过。 |
| `assert_policy_binding` | 1028 | k/TTL 的默认值必须保守且可追溯。返回空元组表示通过。 |

### 3.3 `spa_judge.py`（1,227 行，45 个类/函数）

> 五项条件、证据、Gate 复检、默认 REEXECUTE。索引按源码起始行生成，与文件一一对应。

| 名称 | 起始行 | 职责（docstring 首行） |
|---|---:|---|
| `SpaAction` | 88 | SPA 判定的动作。**第一成员是 REEXECUTE**：默认值不是靠 if 兜底，是靠枚举顺序。 |
| `SpaCondition` | 98 | §8.3 的五条，顺序即原文顺序。 |
| `ReexecuteReason` | 128 | 重跑原因。区分「缺证据」与「证据为假」——两者都必须重跑，但归因不同。 |
| `SkipReason` | 154 | 跳过原因。D.5 的 `skip_reason` 只允许这些值（原文未给枚举，PROPOSED）。 |
| `SpaJudgeError` | 164 | SPA 判定错误基类。 |
| `SpaRefused` | 176 | 记录/输入不合格（字段不符 D.5、计划未冻结、开关关闭）。 |
| `SpaNotEnabled` | 183 | T0/T1 或开关关闭时要求判 SPA：能力未开。对外 403。 |
| `EvidenceRef` | 211 | 证据引用。`producer` 必须在白名单内——这是把 E0 声明挡在门外的唯一位置。 |
| `ConditionOutcome` | 242 | 一条条件的结论。PASS 必须带证据；非 PASS 必须带原因。 |
| `ArtifactExpectation` | 282 | 历史证据里的产物期望：相对路径 + 当时的 SHA-256。 |
| `ArtifactInspection` | 295 | 现场复算结果：实际哈希、解析软链接后的真实路径、是否仍在工作区。 |
| `GateRecheck` | 318 | 当前规则集下的 Gate 复检。四个字段缺一不可：通过、过期、撤销、新冲突。 |
| `SideEffectFacts` | 337 | 副作用与「本次必须执行」。两个字段都是保守方向：不知道就算有。 |
| `SpaRequest` | 350 | 一次判定的全部只读输入。判定期间不得再读外部状态（避免 TOCTOU）。 |
| `SpaSignature` | 394 | SPA 签名信封。`verify` 由端口完成；本对象只固定「签了什么」。 |
| `SpaSignerPort` | 436 | SPA 签名端口（Verifier 进程）。P9 无合规实现（OQ-P6-02/OQ-P9-03）。 |
| `SpaIdentity` | 450 | D.5 中除 `spa_id` / `signature` 外的 10 个字段。 |
| `compute_spa_id` | 481 | 内容寻址 `spa_id` = `sha256(JCS(identity))`，64 位小写十六进制、无前缀（OQ-P9-01）。 |
| `SpaRecord` | 489 | 已签名的 SPA 记录：D.5 的 12 个字段。 |
| `SpaDecision` | 515 | 判定结果。结构上不允许「SKIP 无记录」或「REEXECUTE 带记录」。 |
| `_require_sha256` | 554 | SHA-256 十六进制：64 位小写。 |
| `_require_utc` | 560 | — |
| `_require_utc_z` | 565 | — |
| `_utc_z` | 572 | — |
| `_canonical_bytes` | 577 | 规范化字节串（占位）。真实实现走 M11 `jcs.canonicalize`（RFC 8785）。 |
| `_sorted_pairs` | 584 | 前驱哈希按节点名排序后比较（顺序无语义，不得让顺序差异变成「变化」）。 |
| `_artifact_hash` | 589 | 把多产物合成一个 `artifact_hash`：排序后的 `{path: hash}` 的 JCS 哈希（OQ-P9-06）。 |
| `_dc_outcome` | 600 | 条件 1：存在有效 DC，且输入结构/代码/环境/规则与当前一致。 |
| `_predecessor_outcome` | 659 | 条件 2：所有直接前驱输出哈希与恢复前历史一致（上游变化沿 DAG 传播失效）。 |
| `_disk_outcome` | 694 | 条件 3：现场重算 SHA-256 与历史一致；realpath 不得越界或指向旧目录。 |
| `_gate_outcome` | 757 | 条件 4：旧证据在当前规则集下仍通过 Gate，未过期、未撤销、无新冲突。 |
| `_side_effect_outcome` | 811 | 条件 5：节点无副作用，且任务规则未要求本次必须实际执行。 |
| `_reexecute` | 847 | 构造 REEXECUTE 决定：原因去重但保持首次出现顺序；`DEFAULT_CONSERVATIVE` 兜底。 |
| `judge_spa` | 864 | 判定一个节点能否用 SPA 跳过本次执行。 |
| `_safe_key_id` | 969 | 取 key_id；端口异常时返回空串（后续由 `SpaSignature` 拒绝空 key_id）。 |
| `_dummy_dc_record` | 980 | 构造一张「签名有效、未过期、绑定一致」的 DC，供守卫函数走通条件 1。 |
| `_dummy_request` | 1026 | 构造一个「五条件全绿」的请求，供守卫改字段做负例。 |
| `assert_default_reexecute` | 1078 | 默认动作必须是 REEXECUTE；无记录 SKIP 必须被结构拒绝。返回空元组表示通过。 |
| `assert_evidence_is_not_boolean` | 1105 | PASS 必须有证据；Agent/LLM 不得作为证据生产者。返回空元组表示通过。 |
| `assert_no_unsigned_skip` | 1126 | 无签名器不得 SKIP：五条件全绿也只会得到 REEXECUTE(SIGNER_UNAVAILABLE)。 |
| `_FakeSigner` | 1139 | 自检替身：只证明 SKIP 路径可达，不证明签名安全。 |
| `_BrokenSigner` | 1152 | 签名成功但回验失败：必须回退 REEXECUTE，而不是抛异常或给出 SKIP。 |
| `assert_skip_requires_all_five` | 1159 | 五条件全绿 + 可用签名器 → SKIP；任一条被破坏 → REEXECUTE。 |
| `assert_no_side_effect_skip` | 1187 | 副作用或「必须执行」的节点一律重跑。返回空元组表示通过。 |
| `assert_fields_match_d5` | 1215 | SPA 字段必须与 D.5 的 12 个一致。返回空元组表示通过。 |

### 3.4 `prr_ledger.py`（830 行，21 个类/函数）

> 逐节点剪枝/重跑/结果变化台账、精确二项上界。索引按源码起始行生成，与文件一一对应。

| 名称 | 起始行 | 职责（docstring 首行） |
|---|---:|---|
| `PrrRefused` | 62 | 台账拒绝：字段不符、授权缺失、顺序错乱、试图改写历史。 |
| `_require_at` | 74 | 台账时间必须是带时区的 UTC（不猜本地时区）。 |
| `_utc_z` | 82 | — |
| `_require_id` | 87 | — |
| `ResultFingerprint` | 96 | 结果指纹：状态、产物哈希集、指标哈希、退出码。 |
| `PruningAuthorization` | 142 | 剪枝三元授权。少一个就不是「有授权的剪枝」，而是「无凭据的跳过」。 |
| `PrrEventType` | 157 | 台账事件。顺序即允许发生的顺序。 |
| `EpisodeStatus` | 168 | 单个被剪节点的状态。仅 `RERUN_COMPLETED` 计入分母。 |
| `ComparisonBasis` | 178 | `changed` 的比较依据。随机节点按保守方向处理，单列一档。 |
| `PrrEvent` | 187 | 追加事件。`seq` 由台账分配，调用方不得自填（防重排）。 |
| `_require_at_text` | 221 | — |
| `PrrEntry` | 229 | 单个被剪节点的台账行（对外只读快照）。 |
| `clopper_pearson_upper` | 297 | 精确二项（Clopper–Pearson）**双侧** 95% 上界。 |
| `PrrReport` | 318 | 单任务、单计划的台账报告。**不含**跨任务合并字段。 |
| `_EpisodeState` | 380 | 内部可变状态：一个节点从剪枝到复核的全过程。 |
| `PrrLedger` | 439 | 单任务台账。只追加；没有 `merge` / `aggregate` / `combine`。 |
| `_probe_entry` | 714 | 构造一行合法的探针台账，供守卫函数使用（不写台账、不产事件）。 |
| `assert_denominator_policy` | 737 | 分母只含已完成重跑；覆盖率不足不给点估计；0/72 上界对齐 4.99%。 |
| `assert_no_zero_without_denominator` | 764 | 没有分母时不得报 0；报告必须区分「0/0」与「0/n」。 |
| `assert_no_cross_task_merge` | 795 | 台账不得提供跨任务合并/聚合入口。 |
| `assert_prr_records_raw` | 806 | 逐节点原始行必须完整：授权、时间、比较依据、差异都不许缺。 |

## 4. 边界（谁写什么）

| 对象 | 唯一写者 | 本模块落点 |
|---|---|---|
| `nodes.state` / `tasks.state` | **StateMachine** | 不写；SPA 判定只是“建议跳过”，最终由 Recovery/StateMachine 决定 |
| `evidence` | Collector（E0–E2）/ Verifier（E3） | 不写、不改、不删；DC/SPA 不是证据记录 |
| DC 登记表 | 本模块 `DcRegistry`（P9 内存设计） | T2 落地改真实存储；只增不改 |
| SPA 记录 | 签名端口产出、本模块校验 | 不落库；T2 由 Verifier/存储层落 |
| `skipped_nodes` | Verifier 签发证书时写 | T0 必须为空；本模块不写证书 |
| PRR 台账 | 本模块（单任务、只追加） | 不写实验报告/统计脚本 |
| 预算账本 | Governor/VAS 落地层 | 不写；本模块只返回分配结果 |

三条硬化：

1. **默认保守**：`SpaAction` 第一成员 = `REEXECUTE`；`SpaDecision` 不允许“无记录 SKIP”。
2. **证据不可用布尔顶替**：`ConditionOutcome` 的 PASS 必须带 `EvidenceRef`，
   生产者不能是 `agent/llm/harness/planner`。
3. **无 DC 不剪枝**：SPA 条件 1 直接调用 `evaluate_dc_record`；PRR 登记剪枝必须带
   `spa_id + dc_id + recovery_plan_id`，缺一拒绝。

## 5. 对外接口

| 接口 | 语义 |
|---|---|
| `dc_eligibility.evaluate_dc_eligibility(...)` | 六类条件 → `EligibilityVerdict` |
| `dc_eligibility.compare_runs(...)` | k 次运行 → `RunComparison`（bit-exact 与否） |
| `dc_issuer.issue_dc(...)` | 资格通过 + 复核通过 + 签名 → `DcIssuance` |
| `dc_issuer.evaluate_dc_record(...)` | 过期/撤销/绑定 → `DcValidity` |
| `dc_issuer.revoke_dc(...)` | 追撤销记录（终态） |
| `spa_judge.judge_spa(...)` | 五项 → `SpaDecision`（默认 REEXECUTE） |
| `spa_judge.compute_spa_id(...)` | 内容寻址 `spa_id` |
| `prr_ledger.PrrLedger` | 逐节点剪枝/重跑/结果/纠错/报告 |

## 6. 关键设计决定

### 6.1 六类条件与随机性一票否决（DEC-M15-01）

`CONDITION_ORDER` 是 TABLE 34 的报告顺序；`EVALUATION_ORDER` 把 `RANDOMNESS` 提前。
`EligibilityVerdict.__post_init__` 强制：任一 `VETO` 或任一非 `PASS` ⇒ `eligible=False`。
即使 k 次运行恰好 bit-exact，声明为随机/外部随机源的节点仍不签 DC——这是“经验性资格”
与“这次碰巧一样”的分界。

### 6.2 k=3 跨进程跨目录 bit-exact 是经验性资格（DEC-M15-02）

- 默认 `k=3`；敏感因素每项 +2，封顶 9（PROPOSED，OQ-P9-04）。
- 进程号、工作目录、`run_fingerprint` 必须互不相同；产物哈希与 `metric_hash` 必须逐字节一致。
- `run_fingerprints` 是**运行身份**（进程/目录/输入/产物/指标的合成），k 次之间必须不同；
  bit-exact 比较的是产物与指标，不是运行身份。
- 结论只覆盖“该节点类型 + 该输入结构 + 该代码/依赖/环境/规则版本 + 该 k 次观测”；
  不证明未来所有执行都确定，不是数学证明。`DC_SCOPE_STATEMENT` 写死这句话。

### 6.3 默认 REEXECUTE，SPA 五项全证据（DEC-M15-03）

五项顺序固定：DC 有效 → 前驱哈希未变 → 磁盘复算一致 → 当前规则 Gate 复检通过 → 无副作用
且任务不要求本次执行。每一项都返回带 `EvidenceRef` 的 `ConditionOutcome`；
PASS 无证据在构造时即失败。前驱哈希与 Gate 复检各取一次快照，判定与签名共用，避免 TOCTOU。
签名失败/无签名端口 → REEXECUTE；绝不返回无签名的 SKIP。

### 6.4 DC 签发/过期/撤销（DEC-M15-04）

- `eligible=False` 只产出 `EligibilityVerdict`，不产出 `DcRecord`；
- `issue_dc` 不信任布尔，自己再跑一次 `compare_runs`；
- `k_runs/run_fingerprints/output_hashes` 从探针派生，不由调用方“对齐”；
- 判定顺序：签名 → eligible → 撤销 → 到期 → 规则 → 代码 → 输入结构 → 环境 → VALID；
  撤销优先于到期，是终态；没有 `unrevoke`。
- `expires_at` 必填；TTL 上限 30 天（PROPOSED，OQ-P9-05）。

### 6.5 PRR 逐节点台账（DEC-M15-05）

- 剪枝必须带 SPA/DC/计划三元授权；重跑必须先有 `RERUN_STARTED`（证明真的跑了）；
- `changed` 由 `ResultFingerprint` 逐项精确比较；随机节点按保守方向记 `changed=True`
  并标 `PRUNED_STOCHASTIC_NODE`；
- 分母只含 `RERUN_COMPLETED`；`NOT_RERUN`/`RERUN_FAILED`/`RERUNNING` 进 `unresolved`；
- 只有 `coverage == 1.0` 才给 `prr_point_estimate`；否则为 `None`；
- 零错误时报告 Clopper–Pearson 双侧 95% 上界（0/72 ≈ 4.99%），不得只写“PRR=0”；
- 只提供单任务台账，无 `merge/aggregate/combine`。

### 6.6 ID 与签名（DEC-M15-06）

- `dc_id` / `spa_id` 都是**内容寻址哈希**（64 位小写十六进制，无前缀）：
  `dc_id = sha256(JCS(identity_without_dc_id))`，`spa_id` 同理。
  `new_id("dc"/"spa")` 继续抛 `UnfrozenIdKind`，不新造前缀（OQ-P9-01）。
- 域前缀 `RF-DC-V1\0` / `RF-SPA-V1\0`，Ed25519，签名前回验。
- **签名阻塞**：M11 `ed25519_signer.sign()` 对 `frozen=False` 的 DC/SPA 载荷直接拒绝
  （OQ-P6-02）。P9 只定义 `DcSignerPort` / `SpaSignerPort`；T2 契约冻结前，
  `issue_dc` 没有合规签名器，`judge_spa` 默认 `signer=None` 因而**总是** REEXECUTE。
  这不是“已实现签名”，是已知阻塞（OQ-P9-03）。

### 6.7 与 M14 / M13 的边界（DEC-M15-07）

- M14 的 `RecoveryAction` 在 T0 只有 `REEXECUTE`；M15 不改变 T0 行为。
- SPA 是 Recovery 的“可跳过”依据，不是 Scheduler 的排序依据；VAS 只决定验证预算。
- M15 不生成恢复计划、不冻结计划、不做失效传播；这些属 M14/P3。
- T0/T1 不启用 DC/SPA；证书 `skipped_nodes` 在 T0 必须为空。

### 6.8 为什么四个文件不拆分（DEC-M15-08）

按“职责单元”而不是行数：资格判定（条件与比对）、凭证生命周期（签发/过期/撤销）、
跳过的举证（五项+签名）、事后审计（PRR）是四个独立职责，各自内部高内聚。
拆成更小文件会把“条件结果/证据/签名/台账”的约束分散，反而更容易绕过。
本档登记完整函数索引，不触发第 3 档（>1500 行）的拆分裁决。

## 7. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| 1. `spa_judge` 默认分支是 `REEXECUTE` | `SpaAction` 首成员、`DEFAULT_ACTION`、`SpaDecision` 结构约束、`judge_spa` 步骤 2/3、`assert_default_reexecute()` | 已定义，未执行 |
| 2. “随机性节点”是一票否决 | `VETO_CONDITIONS`、`EVALUATION_ORDER[0]`、`_randomness_result`、`EligibilityVerdict` 结构约束、`assert_randomness_is_veto()` | 已定义，未执行 |
| 3. 六类条件逐条判定 | `CONDITION_ORDER`、六个 `_*_result`、`evaluate_dc_eligibility` | 已定义，未执行 |
| 4. k=3 跨进程跨目录 bit-exact | `compare_runs` 第 1–10 步；`required_k`；`NEG-M15-05…10` | 已定义，**未实测** |
| 5. 无 DC 不剪枝 / 无证据不跳过 | `_dc_outcome`、`ConditionOutcome`、`PruningAuthorization`；`NEG-M15-35/50/52/60` | 已定义，未执行 |
| 6. PRR 逐节点且不合并 | `PrrLedger`、`prr_report`、`assert_task_scoped`、`assert_prr_records_raw` | 已定义，未执行 |
| 7. DC 不是确定性证明 | `DC_SCOPE_STATEMENT`、`assert_scope_statement()`、`assert_dc_scope()` | 已核对（静态） |
| 8. 签名未实现是明示阻塞 | §6.6；`DcSignerPort`/`SpaSignerPort` 只有 Protocol；`judge_spa(signer=None)` 默认重跑 | 已声明，未实现 |

## 8. OPEN QUESTIONS（详见 `design/pseudocode/OPEN_QUESTIONS.md`）

| 编号 | 问题 | P9 临时处理 |
|---|---|---|
| `OQ-P9-01` | `dc_id` / `spa_id` 形态未冻结（`dc_`/`spa_` 不是既定前缀） | 内容寻址 64 hex，无前缀；`new_id` 继续拒绝；T2 契约裁决 |
| `OQ-P9-02` | D.5 的 `output_hashes[]` 语义与 M11 `unique=True` 冲突 | 解释为“排序去重的产物哈希集合”；若改为逐运行列表，M11 提案必须去掉 unique |
| `OQ-P9-03` | M11 拒绝未冻结 DC/SPA 载荷（OQ-P6-02），P9 无合规签名器 | 只定义签名端口；`signer=None` 时 SPA 恒 REEXECUTE；不声称签发可用 |
| `OQ-P9-04` | 敏感因素“增加探针”的具体增量与上限无原文 | `+2/因子，封顶 9` 标 PROPOSED，不得写成验收阈值 |
| `OQ-P9-05` | DC 的 TTL 时长无原文 | `expires_at` 必填、上限 30 天（PROPOSED） |
| `OQ-P9-06` | D.5 的 `artifact_hash` 单值无法表达多产物 | 用“排序后的 `{path: hash}` 的 JCS 哈希”合成一个值 |
| `OQ-P9-07` | SPA `predecessor_hashes` 的键/顺序/重复语义未定义 | 只存排序去重哈希值（满足 M11 unique）；丢键名，需 T2 契约补 |
| `OQ-P9-08` | PRR 分母与目标 0 的统计口径未定义 | 分母只含已完成重跑；覆盖率不足不给点估计；零错误给 CP 上界 |
| `OQ-P9-09` | PRR 审计抽样比例/策略无原文 | 默认全量重跑审计（`coverage=1`）；抽样方案需 G5 前裁决 |
| `OQ-P9-10` | VAS 验证预算/成本单位没有配置键 | 整数 tick，由调用方定义换算；ADR-008 配置冻结时补 |
| `OQ-P9-11` | 特征内部权重、cap、冲突权重无原文 | 预注册常量，写在 `risk_features.py`；只有五维总权重可校准 |
| `OQ-P9-12` | 四策略随机种子/重复次数/盲测边界未定义 | 种子进输入并记录；同任务配对，重复运行不算独立样本；G-hold 不调参 |
| `OQ-P9-13` | M15/M16 编号缺口（原 `OQ-P8-13`） | 按用户 P9 指令映射：M15=DC/SPA，M16=VAS；关闭 P8 的编号缺口 |

## 9. 本阶段不做

- 不做重跑本身（P7/M14 已交付）；不做 Scheduler/Governor（P7/M13）。
- 不做 L1/L2/L3 验证、不替代 Gate、不判定科学正确性。
- 不实现真实签名（OQ-P6-02）、不做持久化、不做密钥管理。
- 不跑 k 次探针、不做 G-dev 校准、不做真实 PRR 统计。
- 不改 `contracts/`、不改 `docs/design/**`、不改 ADR、不改看板、不 commit。
- 不把 T0/T1 写成已具备 DC/SPA；T0 证书 `skipped_nodes` 仍必须为空。