# M16 · NEGATIVE_TESTS — VAS 特征、预算与四策略负例（P9）

> 阶段：P9｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：M16 落地（T2/FR-016）、G4/G5 验收；T0/T1 不启用 VAS
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P9 不得写成“已通过”**。
> 真实输入：真实候选集/预算/成本；DP 与贪心的差距必须用同一实例复算；
> 不得用 mock 证明“强制节点不会被排除”。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：`error_code` + `reason`，或结果中的
   `gap_basis/relative_gap/prr_*` 字段；只断言“抛异常”判失败。
2. 强制集合负例必须断言**没有产出部分分配**：抛出后不存在“删掉强制项但返回结果”的对象；
   若实现返回结果，断言 `set(result.mandatory_ids)` 完整且 `spent<=budget`。
3. 四策略负例必须断言**具体哪一项不可比**（预算/强制集/上下文/成本模型/候选集指纹），
   不能只说“不可比”。
4. 差距负例必须断言**口径**：`UPPER_BOUND_ONLY` 时 `relative_gap is None`；
   只有 `RELATIVE_TO_REFERENCE_OPTIMUM` 才允许 `relative_gap` 非空。
5. 权重负例必须区分“公式常量”与“五维总权重”：只有后者允许 G-dev 校准；
   G-hold 阶段冻结、冻结后换权重都必须拒绝。
6. 正例通过不构成完成证据；`GUARD-M16-01/02/03` 必须真实跑并留同一实例的复算记录。
7. 统计负例必须断言分母/任务级：不得把同一任务重复运行当成独立样本。

## 0.1 符号对照（初稿名 → 当前实现名）

> 负例 ID 与场景保留；下表把「预期拒绝原因」映射到当前实现符号。逐条文本重写列入 `OQ-P9-20`。

| 负例写法 | 当前符号 | 落点 |
|---|---|---|
| `VasFeatureError(reason="WEIGHTS_NOT_SUMMING_TO_ONE")` | `RiskRefused(reason="WEIGHTS_NOT_NORMALIZED")` | `risk_features.RiskWeights.__post_init__` |
| `reason="WEIGHT_NEGATIVE"` | `RiskRefused(reason="OUT_OF_RANGE")` | 同上（`_require_unit`） |
| `reason="WEIGHT_NOT_FINITE"` | `RiskRefused(reason="NAN_REJECTED")` | 同上 |
| `reason="UNSEEN_EXCEEDS_TOTAL"` | 无同名：本实现用**比例** `unseen_input_ratio ∈ [0,1]`，越界由 `OUT_OF_RANGE` 拒绝 | `RiskFacts.__post_init__` |
| `reason="DESCENDANTS_EXCEED_TOTAL"` | 无同名：用 `descendant_ratio ∈ [0,1]`，越界由 `OUT_OF_RANGE` 拒绝 | 同上 |
| `reason="REQUIRED_CHECKS_EMPTY"` | 不抛：`required_checks=0` 时 `G=0.0`（没有必检项就没有缺口） | `risk_features._gap_feature` |
| `reason="FEATURE_OUT_OF_RANGE"` | `RiskRefused(reason="OUT_OF_RANGE")` | `risk_features._require_unit` |
| `reason="VALUE_NOT_FINITE"` | `RiskRefused(reason="NAN_REJECTED")` | 同上 |

## A. 五特征与权重

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M16-01 | 权重和不为 1 | `RiskWeights(0.30,0.20,0.20,0.20,0.15)` | 抛 `VasFeatureError(reason="WEIGHTS_NOT_SUMMING_TO_ONE")` | §8.7 公式 |
| NEG-M16-02 | 负权重 | `RiskWeights(-0.05,0.30,0.25,0.25,0.25)` | 抛 `reason="WEIGHT_NEGATIVE"` | §8.7 |
| NEG-M16-03 | NaN/Inf 权重 | `RiskWeights(float("nan"),...)` | 抛 `reason="WEIGHT_NOT_FINITE"` | §8.7 |
| NEG-M16-04 | **失败数 > 试验数** | `RiskFacts(failures=5, trials=3, ...)` | 抛 `reason="FAILURES_EXCEED_TRIALS"` | Beta-Binomial 定义 |
| NEG-M16-05 | 未见输入 > 总数 | `NoveltyFacts(unseen_inputs=5, total_inputs=3, ...)` | 抛 `reason="UNSEEN_EXCEEDS_TOTAL"` | N 定义 |
| NEG-M16-06 | 已覆盖 > 必检 | `EvidenceGapFacts(required_checks=3, covered_checks=4, ...)` | 抛 `reason="COVERED_EXCEEDS_REQUIRED"` | G 定义；Gate coverage |
| NEG-M16-07 | 必检为 0 | `EvidenceGapFacts(required_checks=0, ...)` | 抛 `reason="REQUIRED_CHECKS_EMPTY"` | G 定义 |
| NEG-M16-08 | 后代数 > 节点总数 | `ImpactFacts(descendant_count=10, total_nodes=5, ...)` | 抛 `reason="DESCENDANTS_EXCEED_TOTAL"` | I 定义 |
| NEG-M16-09 | 特征越界 | `RiskFeatures(f=1.2, ...)` | 抛 `reason="FEATURE_OUT_OF_RANGE"` | 归一化要求 |
| NEG-M16-10 | NaN 特征 | `normalize(float("nan"))` | 抛 `reason="VALUE_NOT_FINITE"` | 不得静默变 0 |
| NEG-M16-11 | Beta 先验非正 | `BetaPrior(alpha=0.0)` | 抛 `reason="PRIOR_NOT_POSITIVE"` | 平滑定义 |
| NEG-M16-12 | 无历史被报成 0 风险 | `failures=0, trials=0` | `F == 0.5`（先验均值）；**不得**为 0 | §8.7；排序先验 |
| NEG-M16-13 | **G-hold 阶段冻结权重** | `freeze_weights(..., calibration_phase=G_HOLD, ...)` | 抛 `WeightFreezeConflict(reason="WEIGHTS_FROZEN_AT_WRONG_PHASE")` | “G-dev 校准后、G-hold 前冻结” |
| NEG-M16-14 | 冻结后换权重 | 先冻结 `W1`，再 `registry.register(W2)` | 抛 `reason="WEIGHTS_ALREADY_FROZEN"`；原冻结记录不变 | 冻结边界 |
| NEG-M16-15 | 未冻结就用于正式分配 | `WeightRegistry()` 空表调用 `resolve(hash)` | 抛 `reason="WEIGHTS_NOT_FROZEN"` | 冻结边界 |
| NEG-M16-16 | 哈希不符的权重 | `resolve("0"*64)`，已冻结另一哈希 | 抛 `reason="WEIGHTS_HASH_MISMATCH"` | 冻结边界 |
| NEG-M16-17 | 冻结时间非 UTC | `frozen_at="2026-11-11 12:00"` | 抛 `reason="FREEZE_TIME_INVALID"` | ENCODING_RULES §3 |
| NEG-M16-18 | 校准清单哈希非法 | `calibration_manifest_hash="abc"` | 抛 `reason="CALIBRATION_MANIFEST_INVALID"` | 冻结记录 |

## B. knapsack：强制集合与预算

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M16-19 | **强制集合被预算排除（超预算）** | 强制成本 9、预算 5 | 抛 `KnapsackRefused`；`error_code="RESOURCE_BUDGET_EXCEEDED"`；`reason="MANDATORY_BUDGET_EXCEEDED"`；detail 含缺口 4；**不返回**只含部分强制项的结果 | §8.7；验收判据 3 |
| NEG-M16-20 | 强制标记与 ID 列表不一致 | 候选 `mandatory=True`，`mandatory_ids=()` | 抛 `reason="MANDATORY_SET_MISMATCH"`；`error_code="SCHEMA_INVALID"` | 防止“忘了列强制项” |
| NEG-M16-21 | 强制 ID 重复 | `mandatory_ids=("a","a")` | 抛 `reason="MANDATORY_ID_DUPLICATE"` | 输入结构 |
| NEG-M16-22 | 强制 ID 不存在 | `mandatory_ids=("missing",)`，候选里没有 | 抛 `reason="MANDATORY_SET_MISMATCH"`（declared 空、expected 有） | 输入结构 |
| NEG-M16-23 | 结果排除强制项 | 构造 `KnapsackResult(selected_ids=(), mandatory_ids=("m",)...)` | 构造抛 `reason="MANDATORY_EXCLUDED"` | 结构约束 |
| NEG-M16-24 | 超预算结果 | 构造 `spent_ticks > budget_ticks` | 构造抛 `reason="BUDGET_OVERSPENT"` | 结构约束 |
| NEG-M16-25 | **无显式“强制先占”顺序** | 检查 `SELECTION_STEPS[1:3]`；构造“强制成本 9、预算 10、可选成本 5 高 utility” | `SELECTION_STEPS == ("VALIDATE","MANDATORY_RESERVED","OPTIONAL_OPTIMIZED","GAP_REPORTED")`；结果强制项全在、可选不选 | 验收判据 3 |
| NEG-M16-26 | 重复候选 | 两个 `node_id` 相同的候选 | 抛 `reason="DUPLICATE_CANDIDATE"` | 输入结构 |
| NEG-M16-27 | 浮点成本 | `cost_ticks=1.5` | 抛 `reason="COST_INVALID"`；不得静默取整 | 整数 tick |
| NEG-M16-28 | 负成本 | `cost_ticks=-1` | 抛 `reason="COST_INVALID"` | 整数 tick |
| NEG-M16-29 | 风险越界 | `risk=1.1` | 抛 `reason="VALUE_OUT_OF_RANGE"` | 特征范围 |
| NEG-M16-30 | 非布尔 mandatory | `mandatory="yes"` | 抛 `reason="MANDATORY_NOT_BOOL"` | 输入结构 |

## C. knapsack：精确/贪心与差距口径

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M16-31 | **显式精确模式超阈值** | 25 个可选节点，`mode=EXACT_DP` | 抛 `reason="EXACT_MODE_LIMIT_EXCEEDED"`；**不得**静默降级为贪心 | §8.7；OQ-P9-14 |
| NEG-M16-32 | **把上界差距写成最优差距** | 构造 `KnapsackResult(gap_basis=UPPER_BOUND_ONLY, relative_gap=0.1)` | 构造抛 `reason="UPPER_BOUND_CALLED_OPTIMAL_GAP"` | §8.7；口径诚实 |
| NEG-M16-33 | 精确解 gap 非 0 | 构造 `gap_basis=EXACT_OPTIMUM, relative_gap=0.1` | 构造抛 `reason="EXACT_GAP_NOT_ZERO"` | §8.7 |
| NEG-M16-34 | **参考最优低于已达成** | 贪心结果 utility=500000，`reference_optimum_units=400000` | 抛 `reason="REFERENCE_BELOW_ACHIEVED"` | 防止伪造最优 |
| NEG-M16-35 | 参考最优与精确解不一致 | `mode=EXACT_DP`，`reference_optimum_units=已达成+1` | 抛 `reason="REFERENCE_MISMATCH_WITH_EXACT"` | 参考值不可信 |
| NEG-M16-36 | 上界低于已达成 | 构造 `upper_bound_units < utility_units` | 构造抛 `reason="UPPER_BOUND_BELOW_ACHIEVED"` | LP 上界性质 |
| NEG-M16-37 | 贪心无参考却给 relative_gap | 构造 `gap_basis=UPPER_BOUND_ONLY, relative_gap=0.0` | 构造抛 `reason="UPPER_BOUND_CALLED_OPTIMAL_GAP"` | 口径诚实 |
| NEG-M16-38 | 零成本高效用被漏选 | 可选节点 `cost=0, utility>0`，预算充足 | 结果必须选中；`spent` 不增加；utility 增加 | §8.7 |
| NEG-M16-39 | 贪心不是按 Priority 排序 | 构造 ratio 高但成本大的节点与 ratio 低但成本小的节点 | 断言选中顺序符合 `utility/max(cost,ε)` 降序（不是原输入顺序） | §8.7 |

## D. 四策略与同预算对照

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M16-40 | **四策略用不同预算** | 构造四条 `Allocation`，预算分别为 12/13/12/12 | 抛 `StrategyRefused`；`error_code="RESOURCE_BUDGET_EXCEEDED"`；`reason="STRATEGY_BUDGET_MISMATCH"` | §8.8；验收判据 4 |
| NEG-M16-41 | 四策略强制集合不同 | 四条分配里一条 `mandatory_ids` 少一个 | 抛 `reason="STRATEGY_MANDATORY_MISMATCH"` | §8.8 |
| NEG-M16-42 | 四策略任务/验证器不同 | 一条 `verifier_id` 不同 | 抛 `reason="STRATEGY_CONTEXT_MISMATCH"` | §8.8 |
| NEG-M16-43 | 四策略成本模型不同 | 一条 `cost_model_version` 不同 | 抛 `reason="STRATEGY_COST_MODEL_MISMATCH"` | §8.8 |
| NEG-M16-44 | 四策略候选集不同 | 一条 `universe_hash` 不同 | 抛 `reason="STRATEGY_UNIVERSE_MISMATCH"` | §8.8 |
| NEG-M16-45 | **强制桶被标成可选** | `StrategyCandidate(is_final_report=True, candidate.mandatory=False)` | 抛 `reason="MANDATORY_BUCKET_NOT_MANDATORY"`；`error_code="RESOURCE_BUDGET_EXCEEDED"` | §8.7；验收判据 3 |
| NEG-M16-46 | 报告来源被标成可选 | `is_report_source=True, mandatory=False` | 同上 | §8.7 |
| NEG-M16-47 | 证据异常节点被标成可选 | `has_evidence_anomaly=True, mandatory=False` | 同上 | §8.7 |
| NEG-M16-48 | 安全关键节点被标成可选 | `is_safety_critical=True, mandatory=False` | 同上 | §8.7 |
| NEG-M16-49 | RANDOM 没有种子 | `Allocation(strategy=RANDOM, seed=None, ...)` | 构造抛 `reason="RANDOM_WITHOUT_SEED"` | §8.8；可复现 |
| NEG-M16-50 | RANDOM 同种子结果不同 | 同 `StrategyInput` 两次 `allocate(RANDOM)` | 两次 `selected_ids` 必须相同；若不同判失败（不是负例通过） | §8.8 |
| NEG-M16-51 | 策略排除强制项 | 构造 `Allocation(selected_ids=不含 mandatory, ...)` | 构造抛 `reason="MANDATORY_EXCLUDED"`；`error_code="RESOURCE_BUDGET_EXCEEDED"` | §8.7 |
| NEG-M16-52 | 策略超预算 | 构造 `spent_ticks > budget_ticks` | 构造抛 `reason="BUDGET_OVERSPENT"` | §8.7 |
| NEG-M16-53 | 拓扑序号重复 | 两个候选 `topological_index=0` | 抛 `reason="DUPLICATE_TOPOLOGICAL_INDEX"` | §8.8 |
| NEG-M16-54 | 种子越界 | `seed=2**32` | 抛 `reason="SEED_INVALID"` | 可复现 |
| NEG-M16-55 | 对照表缺一条策略 | 构造 `ComparisonReport(rows=3)` | 抛 `reason="COMPARISON_INCOMPLETE"` | §8.8 |
| NEG-M16-56 | 对照表预算不一致 | 构造 `ComparisonReport(rows=4, 其中一条 budget 不同)` | 抛 `reason="COMPARISON_BUDGET_MISMATCH"`；429 | §8.8 |
| NEG-M16-57 | 候选集为空 | `StrategyInput(candidates=())` | 抛 `reason="CANDIDATES_EMPTY"` | 输入结构 |
| NEG-M16-58 | 强制 ID 与标记不一致 | `StrategyInput(mandatory_ids=())`，候选有 mandatory | 抛 `reason="MANDATORY_SET_MISMATCH"` | 输入结构 |

## E. 误拒守卫（防止“过度收紧”）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M16-01 | **强制先占 + 可选补位** | 强制成本 7、预算 12、可选成本 3/2/1 | 强制全在；剩余 5 按策略选择；`spent<=12`；`trace` 第一步是 `MANDATORY_RESERVED` | §8.7 |
| GUARD-M16-02 | **四策略同预算同强制集** | 同一 `StrategyInput` 跑四策略 | 四行 `budget_ticks` 相同、`mandatory` 相同、`universe_hash` 相同；RANDOM 记录 seed；每行 `spent<=budget` | §8.8 |
| GUARD-M16-03 | **精确解与上界一致** | 小规模实例 `mode=EXACT_DP` | `gap_basis=EXACT_OPTIMUM`；`relative_gap=0`；`upper_bound_units == optimal_utility_units` | §8.7 |
| GUARD-M16-04 | 贪心不劣于“什么都不选” | 贪心实例 | `utility_units >= 0`；`upper_bound_units >= utility_units`；`bound_gap` 在 [0,1] | §8.7 |
| GUARD-M16-05 | 权重冻结后可用于 G-hold | G-dev 后冻结，G-hold 读取 | `resolve(freeze_hash)` 返回同一 `RiskWeights`；`WEIGHTS_STATUS` 仍标“未校准”只指默认值，不指已冻结版本 | 冻结边界 |
| GUARD-M16-06 | 自检全绿 | 依次调用 `assert_feature_definitions/assert_bounds_hold/assert_weights_sum_to_one/assert_calibration_boundary/assert_mandatory_first/assert_gap_honesty/assert_cost_units/assert_mandatory_buckets/assert_same_budget_contract/assert_report_first_order` | 全部返回 `[]` | 本阶段验收判据 |

## F. 执行记录模板（落地阶段填写，P9 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M16-01 | （待执行） | — | — | — | 未执行 |
| NEG-M16-13 | （待执行） | — | — | — | 未执行 |
| NEG-M16-19 | （待执行） | — | — | — | 未执行 |
| NEG-M16-25 | （待执行） | — | — | — | 未执行 |
| NEG-M16-31 | （待执行） | — | — | — | 未执行 |
| NEG-M16-32 | （待执行） | — | — | — | 未执行 |
| NEG-M16-34 | （待执行） | — | — | — | 未执行 |
| NEG-M16-40 | （待执行） | — | — | — | 未执行 |
| NEG-M16-45 | （待执行） | — | — | — | 未执行 |
| NEG-M16-49 | （待执行） | — | — | — | 未执行 |
| GUARD-M16-01 | （待执行） | — | — | — | 未执行 |
| GUARD-M16-02 | （待执行） | — | — | — | 未执行 |