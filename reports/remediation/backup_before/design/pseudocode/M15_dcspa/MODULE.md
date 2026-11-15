# M15 · DC 与 SPA（P9）

> 阶段：P9「DC/SPA 与 VAS」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：DC 六类资格条件、DC 签发/过期/撤销、SPA 五项判定、PRR 逐节点台账
> 不覆盖：重跑本身（P7/M14）、Scheduler/Governor（P7/M13）、L1–L3 验证（P5/M09–M10）、
> 签名算法实现（P6/M11）、Gate 判定（P5/M08）、科学正确性裁决
> 前置：P5 验证、P6 签名、P7 恢复已验收；T2 能力，**T0/T1 不启用**
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码

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
| `orchestration/determinism/dc_eligibility.py` | 六类条件、随机性否决、k 次 bit-exact 比对、有效期/规则版本 | 1,317 | 完成（伪代码） |
| `orchestration/determinism/dc_issuer.py` | DC identity/内容寻址 ID、签发、过期、撤销、复用判定 | 973 | 完成（伪代码） |
| `orchestration/determinism/spa_judge.py` | 五项条件、证据对象、签名记录、默认 REEXECUTE | 1,327 | 完成（伪代码） |
| `orchestration/determinism/prr_ledger.py` | 逐节点剪枝/重跑/结果变化台账、精确二项上界 | 842 | 完成（伪代码） |

计数口径：物理行数（`text.count("\n") + 1`）。四个文件均在 800–1500 行档，
按 PHASE_RULES §5 第 2 档在 §3 登记完整函数索引；不拆分，理由见 §7.8。

## 3. 文件导航（PHASE_RULES §5 第 2 档：800–1500 行）

### 3.1 `dc_eligibility.py`

| 名称 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `Condition` | 101 | 六类条件枚举 | TABLE 34 R02–R07 |
| `ConditionStatus` | 129 | PASS/FAIL/MISSING_EVIDENCE/VETO | §8.2；“缺证据不等于通过” |
| `DcReason` | 138 | 拒绝/否决策略原因 | §8.2 |
| `DcEligibilityError` | 173 | 输入结构错误（非资格不合格） | 错误码注册表 |
| `DcPolicy` | 192 | k 下限/增量/上限、TTL、独立进程目录要求 | §8.2 R05/R07 |
| `DcCandidate` | 230 | 节点静态声明（纯度/随机性/敏感因素） | §8.2 R02/R06 |
| `_require_hash` / `_require_hash_map` | 279/287 | 哈希与映射形态校验 | ENCODING_RULES §4 |
| `DcBinding` | 303 | 输入/代码/模板/环境/规则绑定 | §8.2 R03/R04/R07 |
| `RunProbe` | 346 | 单次探针运行的可观测事实 | §8.2 R05 |
| `EnvComparisonView` | 415 | M03 环境比较结果的只读投影 | §8.2 R04 |
| `ConditionResult` | 446 | 条件结论；PASS 必须带证据引用 | §8.2；本文件核心约束 |
| `RunComparison` | 486 | k 次比对结果 | §8.2 R05 |
| `EligibilityVerdict` | 510 | 六项结论与 eligible 的一致性校验 | §8.2；验收判据 2 |
| `required_k` | 589 | 敏感因素 → 探针数 | §8.2 R05 |
| `_canonical_directory` | 616 | 目录比较的保守规范化 | §8.2 R05 |
| `compare_runs` | 626 | k 次运行 bit-exact 判定（主逻辑） | §8.2 R05 |
| `_divergent` | 838 | 构造“有差异”的结果 | §8.2 R05 |
| `_randomness_result` | 861 | 随机性一票否决 | §8.2 R06；验收判据 2 |
| `_purity_result` | 896 | 节点纯度 | §8.2 R02 |
| `_input_fixed_result` | 950 | 输入固定 | §8.2 R03 |
| `_env_result` | 988 | 环境指纹 | §8.2 R04 |
| `_k_run_result` | 1026 | 重复执行条件 | §8.2 R05 |
| `_validity_result` | 1066 | 有效期与规则版本 | §8.2 R07 |
| `_require_utc` | 1132 | UTC datetime 校验 | ENCODING_RULES §3 |
| `evaluate_dc_eligibility` | 1143 | 六项逐条判定主入口 | §8.2 |
| `assert_randomness_is_veto` | 1210 | 自检：否决优先且结构不可绕过 | 验收判据 2 |
| `assert_conservative_defaults` | 1260 | 自检：默认保守、缺证据不通过 | 本阶段判据 |
| `assert_scope_statement` | 1289 | 自检：DC 限定语未被改写 | AGENTS §4.13 |
| `assert_condition_math` | 1304 | 自检：6 条件、k 单调性 | §8.2 R05 |

### 3.2 `dc_issuer.py`

| 名称 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `DcIssuerError` / `DcRefused` / `DcSignatureInvalid` / `DcStoreCorrupt` | 128–156 | 签发/签名/存储拒绝 | 错误码注册表 |
| `_require_hash` / `_require_utc_datetime` / `_utc_z` | 166–178 | 形态与 UTC 固定写法 | ENCODING_RULES §3/§4 |
| `DcSignature` | 184 | 签名信封；要求回验 | §7.5；OQ-P6-02 |
| `DcSignerPort` | 221 | T2 签名端口；P9 无合规实现 | §7.5；OQ-P9-03 |
| `DcIdentity` | 250 | 除 `dc_id` 外的 13 个签名字段 | 附录 D.5；M11 提案 |
| `compute_dc_id` | 345 | 内容寻址 `dc_id`（JCS+SHA-256） | OQ-P9-01 |
| `DcRecord` | 363 | 已签发 DC（14 字段 + 签名） | 附录 D.5 |
| `DcAudit` | 448 | 签发审计（不进签名正文） | §7.4/§7.6 |
| `RevocationReason` / `RevocationRecord` | 472/486 | 撤销原因与记录 | §8.2 R07；终态 |
| `DcStatus` / `DcValidity` | 509/525 | 复用状态与一致性 | §8.3 条件 1 |
| `DcRegistry` | 544 | 只增不改的登记表（P9 内存设计） | 附录 D.6 |
| `DcIssuance` | 611 | 签发结果 | — |
| `_derive_output_hashes` | 617 | 排序去重产物哈希 | OQ-P9-02 |
| `issue_dc` | 627 | 签发主流程（复核、派生、签名、落库、审计） | §8.2；D.5 |
| `evaluate_dc_record` | 760 | 过期/撤销/绑定/签名的复用判定 | §8.3 条件 1 |
| `evaluate_dc` | 835 | 按 ID 取记录再判定 | §8.3 条件 1 |
| `revoke_dc` | 851 | 撤销入口 | §8.2 R07 |
| `assert_signature_domain` | 885 | 自检：域前缀/字段顺序/算法 | §7.5；M11 |
| `assert_dc_scope` | 915 | 自检：eligible=false 不签发、限定语 | AGENTS §4.13 |
| `assert_revocation_is_terminal` | 949 | 自检：无恢复入口 | §8.2 R07 |
| `assert_policy_binding` | 962 | 自检：策略版本/k/TTL 保守 | OQ-P9-04/05 |

### 3.3 `spa_judge.py`

| 名称 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `SpaAction` / `DEFAULT_ACTION` | 127/133 | 动作枚举；默认 REEXECUTE | §8.3；验收判据 1 |
| `SpaCondition` / `SPA_CONDITION_ORDER` | 137/146 | 五项条件与顺序 | §8.3 / P0196–P0200 |
| `ReexecuteReason` | 156 | 重跑原因（区分“缺证据”与“证据为假”） | §8.3 |
| `SkipReason` | 177 | 唯一合法跳过原因 | 附录 D.5 |
| `SpaJudgeError` / `SpaRefused` | 183/194 | 输入结构错误 / 记录签名拒绝 | 错误码注册表 |
| `EvidenceRef` | 235 | 证据引用；生产者白名单 | §8.3；E0/E1 边界 |
| `ConditionOutcome` | 264 | 条件结论；PASS 必带证据 | 验收判据 1 |
| `DcLookupPort` / `PredecessorHashPort` / `ArtifactDiskPort` / `GateRecheckPort` / `SideEffectPort` / `SpaSignerPort` | 303–348 | 六个只读/签名端口 | §8.3 |
| `ArtifactExpectation` / `ArtifactInspection` | 367/386 | 产物期望与磁盘复算结果 | §8.3 条件 3 |
| `_canonical_path` / `_is_within` | 415/421 | 路径包含判定 | §8.3 条件 3 |
| `GateRecheck` | 429 | 当前规则集下的 Gate 复检（含过期/撤销/冲突） | §8.3 条件 4 |
| `SideEffectFacts` | 461 | 副作用与“本次必须执行”事实 | §8.3 条件 5 |
| `SpaRequest` | 479 | 一次判定的全部只读输入 | §8.3 |
| `SpaSignature` | 533 | SPA 签名信封；要求回验 | §7.5；OQ-P6-02 |
| `SpaIdentity` | 573 | 除 `spa_id` 外的 10 个签名字段 | 附录 D.5；M11 |
| `compute_spa_id` | 646 | 内容寻址 `spa_id` | OQ-P9-01 |
| `SpaRecord` | 653 | 已签名 SPA 记录 | 附录 D.5 |
| `SpaDecision` | 717 | SKIP/REEXECUTE 的结构约束 | 验收判据 1 |
| `_dc_outcome` | 760 | 条件 1 | §8.3 |
| `_predecessor_outcome` | 799 | 条件 2 | §8.3 |
| `_disk_outcome` | 865 | 条件 3 | §8.3 |
| `_gate_outcome` | 904 | 条件 4 | §8.3 |
| `_side_effect_outcome` | 963 | 条件 5 | §8.3 |
| `_gate_result_body` / `_artifact_hash` | 1014/1029 | 签名正文片段 | 附录 D.5 |
| `_reexecute` | 1035 | 默认分支 | 验收判据 1 |
| `judge_spa` | 1052 | 五项判定主入口 | §8.3 |
| `_reexecute_with_signing_failure` | 1154 | 签名失败回退重跑 | §8.3 条件 1/5 |
| `assert_default_reexecute` | 1170 | 自检：默认分支与无记录 SKIP 拒绝 | 验收判据 1 |
| `assert_evidence_is_not_boolean` | 1222 | 自检：PASS 必须有证据、生产者白名单 | §8.3；E0/E1 |
| `assert_no_unsigned_skip` | 1246 | 自检：无回验签名不得跳过 | §7.5 |
| `assert_no_side_effect_skip` | 1271 | 自检：副作用/必须执行必重跑 | §8.3 条件 5 |
| `_StaticSideEffectPort` / `_dummy_request` | 1292/1302 | 自检替身 | — |

### 3.4 `prr_ledger.py`

| 名称 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `PrrRefused` / `_require_at` | 97/117 | 台账拒绝与时间校验 | 附录 D.6 |
| `ResultFingerprint` | 128 | 结果指纹（状态/产物/指标/退出码） | §4.2 R08 |
| `PruningAuthorization` | 172 | SPA+DC+计划三元授权 | §8.3；I-05 |
| `PrrEventType` / `EpisodeStatus` / `ComparisonBasis` | 204–226 | 事件、状态、比较依据 | §4.2 R08 |
| `PrrEvent` | 235 | 追加事件 | 附录 D.6 |
| `PrrEpisode` | 262 | 单 episode 快照 | §4.2 R08 |
| `PrrReport` | 284 | 单任务报告（分子/分母/覆盖率/上界/逐节点行） | §4.2 R08 |
| `clopper_pearson_upper` | 364 | 精确二项上界 | 策划书 §4.3；0/72≈4.99% |
| `_EpisodeState` | 400 | 内部可变状态 | — |
| `PrrLedger` | 421 | 单任务台账（pruning/rerun/result/correction/report） | §4.2 R08；验收判据 4 |
| `assert_denominator_policy` | 784 | 自检：分母政策与 0/72 上界 | §4.2 R08 |
| `assert_no_zero_without_denominator` | 800 | 自检：无分母不报 0 | §4.2 R08 |
| `assert_task_scoped` | 814 | 自检：无跨任务合并 | 策划书 §4.3 |
| `assert_prr_records_raw` | 828 | 自检：逐节点原始行 | §4.2 R08 |

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