# M16 · VAS 验证感知调度（P9）

> 阶段：P9「DC/SPA 与 VAS」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：F/N/G/I/A 五特征与归一化、Beta-Binomial 平滑、Utility/Priority、DP/贪心预算分配、
> 强制集合先占预算、四策略同预算对照、权重冻结边界
> 不覆盖：验证执行（M09–M10）、Gate 判定（M08）、Scheduler/Governor（M13）、
> 真实 G-dev 校准与 G-hold 实验（T2/G5）、科学正确性裁决
> 前置：P5 验证、P6 签名、P7 恢复已验收；T2 能力，**T0/T1 不启用**
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码

## 1. 目标

把“有限验证预算投向哪里”写成可复核的分配问题：

1. **风险分数可复算**：F/N/G/I/A 五个特征全部在 [0,1]，公式预注册；
   只有五维总权重允许在 G-dev 校准，且必须在 G-hold 前冻结。
2. **强制项不可被优化掉**：最终报告节点、报告指标来源节点、证据异常节点、安全关键节点
   先占预算；超预算时**拒绝**，不从强制集合里删节点。
3. **优化口径不吹牛**：小规模 DP 精确；大规模贪心并报告“相对上界”的差距；
   只有提供参考最优时才给“相对最优”差距。
4. **四策略可比**：随机/固定拓扑/报告优先/风险优先使用同一预算、同一任务、同一验证器、
   同一候选集、同一强制集合、同一成本模型；随机策略记录预注册种子。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `orchestration/vas/risk_features.py` | 五特征、Beta-Binomial、归一化、权重冻结 | 749 | 完成（伪代码） |
| `orchestration/vas/knapsack.py` | 强制先占、DP 精确、贪心 + 上界差距、参考最优差距 | 815 | 完成（伪代码） |
| `orchestration/vas/strategies.py` | 四策略、同预算对照、强制桶、统计口径 | 644 | 完成（伪代码） |

计数口径：物理行数（`text.count("\n") + 1`）。`knapsack.py` 在 800–1500 行档，
按 PHASE_RULES §5 第 2 档在 §3 登记完整函数索引；其余两个文件 ≤ 800 行，无需索引。

## 3. 文件导航（`knapsack.py`，800–1500 行档）

| 名称 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `KnapsackRefused` | 87 | 预算/结构拒绝（429/422） | 错误码注册表 |
| `SelectionMode` | 107 | AUTO/EXACT_DP/GREEDY | §8.7 |
| `SelectionStatus` | 115 | 强制/选中/预算排除/零效用 | §8.7 |
| `GapBasis` | 124 | 精确最优/参考最优/仅上界 | §8.7；本文件差距口径 |
| `_require_float01` / `_require_cost` | 132/149 | 特征与成本形态校验 | §8.7 |
| `utility_units` | 161 | `R×CoverageBenefit` → 整数 micro-utility | §8.7 |
| `ValidationCandidate` | 174 | 候选（风险/覆盖收益/成本/强制） | §8.7 |
| `candidate_universe_hash` | 222 | 候选集指纹（四策略可比性） | §8.8 |
| `MandatoryReservation` | 229 | 强制集合占预算结果 | §8.7 |
| `reserve_mandatory` | 242 | **第 2 步**：强制先占；超预算拒绝 | §8.7；验收判据 3 |
| `SelectionItem` | 327 | 逐项状态与原因 | §8.7 |
| `KnapsackResult` | 349 | 分配结果与不变量 | §8.7 |
| `_mask_key` | 462 | DP 平局决胜（少项、字典序） | §8.7 |
| `_solve_exact` | 467 | 整数 DP 精确解 | §8.7 |
| `_greedy_order` / `_solve_greedy` | 515/526 | 贪心顺序与装包 | §8.7 |
| `_lp_upper_bound` | 543 | LP 松弛上界（Fraction） | §8.7 |
| `select` | 573 | 主入口：VALIDATE→MANDATORY→OPTIONAL→GAP | §8.7；验收判据 3 |
| `assert_mandatory_first` | 739 | 自检：强制先占且超预算不丢 | 验收判据 3 |
| `assert_gap_honesty` | 768 | 自检：上界差距 ≠ 最优差距 | §8.7 |
| `assert_cost_units` | 802 | 自检：整数 tick 与取整规则 | §8.7 |

## 4. 边界（谁写什么）

| 对象 | 唯一写者 | 本模块落点 |
|---|---|---|
| 节点状态 / 执行 | StateMachine / Executor | 不写；VAS 只选“验证哪些节点” |
| 验证结果 / E3 | Verifier | 不写；VAS 不执行验证、不裁决结果 |
| 证据 / Gate | Collector / Gate | 不写；G 特征只消费 Gate coverage 聚合 |
| 验证预算 | 配置/Governor 提供的整数 tick | 只读；不写预算账本、不做单位换算 |
| 权重冻结 | 本模块 `WeightRegistry`（P9 内存设计） | G-dev 后、G-hold 前一次冻结 |
| 实验记录 / 对照 CSV | 实验层（T2/G5） | 不写；本模块只返回结构化分配 |
| 调度顺序 | Scheduler（M13） | 不写；VAS 不决定执行顺序 |

三条硬化：

1. **强制桶结构约束**：`StrategyCandidate` 命中四个强制桶之一但 `mandatory=False` → 构造失败。
2. **超预算拒绝**：`reserve_mandatory` 抛 `MANDATORY_BUDGET_EXCEEDED`，不返回部分强制集合。
3. **差距口径类型化**：`GapBasis` 区分 `EXACT_OPTIMUM` / `RELATIVE_TO_REFERENCE_OPTIMUM` /
   `UPPER_BOUND_ONLY`；`UPPER_BOUND_ONLY` 时 `relative_gap` 必须为 `None`。

## 5. 对外接口

| 接口 | 语义 |
|---|---|
| `risk_features.compute_features(facts)` | F/N/G/I/A 五特征 |
| `risk_features.compute_risk(facts, weights)` | `R = Σ weight·feature` |
| `risk_features.freeze_weights(...)` | G-dev 后、G-hold 前冻结 |
| `knapsack.reserve_mandatory(...)` | 强制集合先占预算（唯一入口） |
| `knapsack.select(...)` | 预算内选择（DP/贪心 + 差距） |
| `strategies.allocate(strategy, input)` | 单策略分配 |
| `strategies.compare_strategies(input)` | 四策略同预算对照 |

## 6. 关键设计决定

### 6.1 五特征与预注册（DEC-M16-01）

| 特征 | 公式 | 说明 |
|---|---|---|
| F | `(failures + α)/(trials + α + β)` | Jeffreys α=β=0.5；0 试验 → 0.5 |
| N | `0.50·未见输入比例 + 0.30·配置变更比例 + 0.10·新数据集 + 0.10·新模板` | 内部权重和 1 |
| G | `1 − 已覆盖/必检 + 0.5·未解释冲突/必检`，截断 [0,1] | 消费 Gate coverage，不重判证据等级 |
| I | `0.70·报告来源标志 + 0.30·后代占比` | 最终报告也算报告来源 |
| A | `Σ w_i·min(1, count_i/cap_i)` | 五类计数，cap 防单信号放大 |

特征公式在 G-dev 前固定（`FEATURE_VERSION = vas-features/1.0`）；
**只有** `RiskWeights` 的五个总权重允许校准。内部权重/cap 是 PROPOSED 常量（OQ-P9-11），
不得在看到 G-hold 结果后修改。

### 6.2 Beta-Binomial 平滑（DEC-M16-02）

直接 `failures/trials` 会让“0/1”变 0 风险、“无历史”无法排序。Beta-Binomial 把两者拉回
中性值 0.5；试验越多，数据越占主导。它只是**排序先验**，不裁决节点对错。

### 6.3 Utility / Priority / 整数预算（DEC-M16-03）

- `Utility = R × CoverageBenefit`；
- `Priority = Utility / max(Cost, ε)`，`ε=1e-9`；
- DP 在 `utility_units = round(R×Coverage×1e6)` 上做整数加法，避免浮点结合律；
- 成本/预算都是整数 tick；不做隐式单位换算；`Decimal` + HALF_UP 固定取整规则。

### 6.4 强制集合先占预算（DEC-M16-04，验收判据 3）

`select()` 的第 2 步是 `reserve_mandatory()`，第 3 步才优化可选集；
`SELECTION_STEPS` 与结果 `trace` 都记录这个顺序。强制集超预算时抛 429
`MANDATORY_BUDGET_EXCEEDED`，**不**从强制集合删节点。`strategies` 的四策略也调用同一个
`reserve_mandatory()`，避免某个策略忘了强制项。

### 6.5 DP 精确 vs 贪心 + 差距口径（DEC-M16-05）

- 阈值：可选 ≤ 24 项且剩余预算 ≤ 200,000 tick；超阈值 AUTO 用贪心，显式 `EXACT_DP` 则拒绝
  （不静默降级）。
- 精确解 `gap_basis=EXACT_OPTIMUM`，`relative_gap=0`；
- 贪心给 `upper_bound_units`（LP 松弛，Fraction 精确）与 `bound_gap`；
  **没有**参考最优时 `relative_gap=None`，`gap_basis=UPPER_BOUND_ONLY`；
- 只有在同一实例上提供 `reference_optimum_units` 时才给 `relative_gap`；
  参考值低于已达成值 → 拒绝，防止伪造“最优”。

### 6.6 四策略同预算可比（DEC-M16-06，验收判据 4）

| 策略 | 可选阶段顺序 | 目的 |
|---|---|---|
| `RANDOM` | 预注册种子洗牌（先按 ID 排序再 shuffle） | 无信息基线 |
| `TOPOLOGICAL` | 拓扑序升序 | 固定顺序基线 |
| `REPORT_FIRST` | 报告节点在强制集，可选阶段逆拓扑 | “只看最终输出”对照 |
| `RISK_PRIORITY` | Utility/Cost + DP/贪心 | 风险优先 |

`compare_strategies()` 只接受一个 `StrategyInput`；`assert_comparable()` 核对预算、任务、
验证器、强制集合、成本模型、候选集指纹。统计口径：任务是统计单位；同一任务重复运行
不是独立样本；二值检出用 McNemar，连续效用用任务级 bootstrap，多重比较用 Holm 或标探索性。

### 6.7 权重冻结边界（DEC-M16-07）

`WeightsFreeze.calibration_phase` 只允许 `POST_G_DEV_PRE_G_HOLD`：
G-dev 校准 → 冻结（`frozen_at` + `calibration_manifest_hash`）→ G-hold 只报告。
在 G-hold 阶段冻结、冻结后换权重、未冻结就用于正式分配，全部拒绝。
`WEIGHTS_STATUS = "UNCALIBRATED_UNTIL_G_DEV"` 明示默认权重不是最终值。

### 6.8 与 M13/M15 的边界（DEC-M16-08）

- VAS 不剪枝执行节点（那是 SPA/M15）；VAS 不决定执行顺序（那是 M13 Scheduler）。
- VAS 不执行验证、不重算指标、不裁决科学正确性；它只分配“验证预算”。
- VAS 的 R 可以来自 M15 的 DC/SPA 相关风险事实，但本模块不依赖 DC 判定结果；
  DC 剪枝与验证预算分配是两个正交决策。
- T0/T1 不启用 VAS；T0 的 `vas` feature flag 必须为 false。

## 7. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| 1. 五特征定义与归一化 | `RiskFeatures`、五个公式函数、`normalize`、`assert_bounds_hold()` | 已定义，未执行 |
| 2. Beta-Binomial 平滑 | `smoothed_failure_rate`、`BetaPrior`；0 试验=先验均值 | 已定义，未执行 |
| 3. Utility/Priority 公式 | `ValidationCandidate.utility/priority`、`utility_units` | 已定义，未执行 |
| 4. 强制集合先占预算 | `reserve_mandatory`、`SELECTION_STEPS`、`assert_mandatory_first()` | 已定义，未执行 |
| 5. DP 精确 + 贪心上界差距 | `_solve_exact`、`_solve_greedy`、`_lp_upper_bound`、`GapBasis` | 已定义，未执行 |
| 6. 四策略同预算可比 | `StrategyInput`、`compare_strategies`、`assert_comparable`、`assert_same_budget_contract()` | 已定义，未执行 |
| 7. 强制桶不可被预算排除 | `StrategyCandidate` 的桶→mandatory 约束、`Allocation` 强制子集约束 | 已定义，未执行 |
| 8. 权重 G-dev 后/G-hold 前冻结 | `WeightsFreeze`、`WeightRegistry`、`assert_calibration_boundary()` | 已定义，未执行 |

## 8. OPEN QUESTIONS（详见 `design/pseudocode/OPEN_QUESTIONS.md`）

| 编号 | 问题 | P9 临时处理 |
|---|---|---|
| `OQ-P9-10` | 验证预算/成本单位没有配置键 | 整数 tick；换算由调用方配置层负责；ADR-008 时补键 |
| `OQ-P9-11` | 特征内部权重/cap/冲突权重无原文 | 预注册常量；只有五维总权重可校准 |
| `OQ-P9-12` | 四策略种子/重复次数/盲测边界 | 种子进输入；同任务配对；重复运行不算独立样本；G-hold 不调参 |
| `OQ-P9-14` | DP 阈值（24 项/200k tick）无原文依据 | 标 PROPOSED；超过阈值用贪心并报告上界差距；不得写成验收阈值 |
| `OQ-P9-15` | 覆盖率收益 `CoverageBenefit` 的构造口径未定义 | 由调用方从 Gate coverage/报告指标映射给出并保持四策略一致；VAS 不自行重算 |

## 9. 本阶段不做

- 不做真实 G-dev 校准、不做 G-hold 盲测、不跑四策略实验；不写 `vas_four_strategies.json`。
- 不执行验证、不计算指标、不裁决科学正确性；不替代 Gate/Verifier。
- 不剪枝执行节点、不改图、不改状态、不写预算账本。
- 不新增配置键（`scheduler.yaml`/`gates.yaml` 均不改）；阈值只作为 PROPOSED 常量。
- 不改 `contracts/`、不改 `docs/design/**`、不改 ADR、不改看板、不 commit。