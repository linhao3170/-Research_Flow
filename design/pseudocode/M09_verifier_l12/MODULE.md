# M09 · L1/L2 独立验证（P5）

> 阶段：P5「门控与三级验证」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：L1 过程完整性（schema/哈希/seq/链/Merkle/目录复用）、L2 结果自洽（指标重算/字段语义/混淆矩阵/R1–R5）
> 不覆盖：L3 重跑（M10）、签名/信任锚（P6）、验证预算（P9）、科学结论评价
> 前置：P4 设计产物存在；验收状态以 `docs/state/project_state.json` 为准（P4 设计件已验收；实现未开始）；M07 chain/merkle、M06 Split Manifest、M01 冻结 schema 可用
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码

## 1. 目标

把“过程完整性”和“结果自洽”拆成两个**可独立重算**的层级：

1. L1 只回答“这批证据在结构与指纹上是否自洽”，不回答“是否真实执行”；
2. L2 只回答“预测/指标/划分/泄漏检查是否内部一致”，**不回答“是否真实执行”**；
3. L2 PASS 的准确表述是“结果自洽”；把 L2 PASS 写成“已验证真实执行”是契约违反；
4. L1/L2 的每个判定都有机器判据；`NOT_EVALUABLE` 按 fail-closed 处理，不得当 PASS；
5. 指标重算的口径、容差、AUC 未定义边界写死，避免“没算出来”被写成 0.0。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `verifier/l1_integrity.py` | L1 七项检查、`L1Result`、目录复用检测 | 571 | 完成（伪代码） |
| `verifier/l2_consistency.py` | L2 五项/多子项检查、`L2Result`、`SELF_CONSISTENT_ONLY` | 557 | 完成（伪代码） |
| `verifier/metric_recompute.py` | accuracy/precision/recall/f1/AUC 口径、混淆矩阵、比较容差 | 586 | 完成（伪代码） |
| `verifier/leakage_rules.py` | R1–R5 五条机器判据、`LeakageReport` | 987 | 完成（伪代码） |

### 2.1 `leakage_rules.py` 函数索引（>800 行，按 PHASE_RULES §5 第 2 档登记）

| 符号 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `RuleStatus` | 87 | PASS/FAIL/NOT_APPLICABLE/NOT_EVALUABLE | 本文 §6/§7 |
| `ColumnSpec` | 95 | 列名/角色/类型 | 本文 §6 R4 |
| `DatasetTable` | 112 | 只读数据表与 row_id 唯一性 | 本文 §6 |
| `SplitManifestView` | 153 | 六字段 + 信封的只读视图 | M06 §4 |
| `SplitAssignment` | 169 | train/test 行集与 fold 分配 | 本文 §6 R2/R3/R5 |
| `NearDuplicateSpec` | 191 | 近重复阈值/窗口 | 本文 §6 R1 |
| `MetricsArtifactView` | 210 | metrics.json 只读视图（含 confusion 归一） | 本文 §6 R5 |
| `PredictionsArtifactView` | 251 | predictions.csv 只读视图 | 本文 §6 R5 |
| `LeakageContext` | 266 | 五规则的完整只读输入 | 本文 §6 |
| `LeakageFinding` | 297 | 单条规则判定 + 判据 + 计数/配对 | 本文 §6 |
| `LeakageReport` | 317 | R1–R5 汇总与阻塞判定 | 本文 §7 |
| `_column_names` | 350 | 列名列表 | 本文 §6 |
| `_feature_columns` | 354 | 白名单优先的特征列 | 本文 §6 R1/R4 |
| `_value_token` | 360 | 稳定值 token（bool/float/string 区分） | 本文 §6 R1/R4 |
| `_row_token` | 373 | 行规范化 token | 本文 §6 R1 |
| `_row_hash` | 377 | `sha256(row_token)` | 本文 §6 R1 |
| `_is_number` | 381 | 有限数值判定 | 本文 §6 R1/R4 |
| `_to_float` | 385 | 安全转 float | 本文 §6 R1/R4 |
| `_shingles` | 389 | 文本 3-gram 集合 | 本文 §6 R1 |
| `_jaccard` | 396 | Jaccard 相似度 | 本文 §6 R1 |
| `_time_value` | 404 | 数值/ISO-8601 时间解析（必须带时区） | 本文 §6 R3 |
| `_numeric_matrix` | 422 | 全数值特征矩阵 | 本文 §6 R1 |
| `r1_duplicate_samples` | 442 | R1 重复/近重复样本 | 策划书 §9.2 R1 |
| `r2_group_leakage` | 535 | R2 分组交集/未声明分组列 | 策划书 §9.2 R2 |
| `r3_temporal_leakage` | 597 | R3 时间边界/未来特征 | 策划书 §9.2 R3 |
| `_column_hash` | 698 | 列值哈希（R4 target 副本检测） | 本文 §6 R4 |
| `_is_forbidden_feature_name` | 703 | 标签/后验命名 token 判据 | 本文 §6 R4 |
| `_pearson` | 720 | Pearson 相关系数 | 本文 §6 R4 |
| `r4_label_or_posterior_fields` | 734 | R4 白名单/角色/相关/确定性映射 | 策划书 §9.2 R4 |
| `r5_metric_source` | 867 | R5 metrics 来源/test/重算 | 策划书 §9.2 R5 |
| `evaluate_all` | 960 | R1→R5 顺序执行 | 本文 §6 |
| `assert_leakage_boundary` | 971 | 无 I/O/网络/裁决的静态检查 | AGENTS §4 |

其余三个文件 ≤800 行，无需索引。

## 3. L1：过程完整性

### 3.1 七项检查

| check_id | 判据 | 失败语义 |
|---|---|---|
| `L1-SCHEMA` | 每条记录过冻结 schema；schema_version=1.0；task_id 一致；evidence_id 唯一 | `SCHEMA_INVALID` |
| `L1-PAYLOAD-HASH` | `sha256(payload sidecar bytes) == payload_hash` | `BUNDLE_TAMPERED` |
| `L1-ARTIFACT-HASH` | 每个 artifact_ref 重算值 == E2 清单值；未登记/缺失即失败 | `BUNDLE_TAMPERED` / `EVIDENCE_REFERENCE_NOT_FOUND` |
| `L1-EVENT-SEQ` | 首项=1、严格 +1；不排序 | `EVENT_SEQ_GAP/REGRESSION` |
| `L1-CHAIN-HASH` | prev_hash 接链；chain_hash 重算一致；首条只校形态 | `EVIDENCE_CHAIN_BROKEN` |
| `L1-MERKLE` | 根 == `expected_evidence_root`；每条 inclusion proof 通过 | `BUNDLE_TAMPERED` |
| `L1-DIRECTORY-REUSE` | attempt 目录键唯一；`(st_dev, st_ino)`/realpath 不重复；创建时间不早于任务；与 Verifier 目录不重叠 | `SCHEMA_INVALID` |

### 3.2 能证明 / 不能证明

**能证明**：证据集 schema/哈希/seq/链/Merkle 自洽；attempt 目录独立；Verifier 与 Executor 目录分离。
**不能证明**：代码真的执行过；时间戳/进程身份不可伪造；指标正确；结果可复现；
攻击者同时控制证据库并重算整条链时，L1 可能“看起来通过”。

因此 L1 PASS 的准确表述是“**证据集在结构与指纹上自洽**”，不是“任务真实完成”。

## 4. L2：结果自洽

### 4.1 检查

| check_id | 判据 | 失败语义 |
|---|---|---|
| `L2-PREDICTIONS-COVERAGE` | predictions 行集 == test 行集；fold=1；y_true 与数据标签一致；n_test 一致 | `REQUIRED_EVIDENCE_MISSING` |
| `L2-FIELD-SEMANTICS` | 必需列在；未声明列拒绝；当前模型预测列在；y_pred/scores 标签 ∈ metrics.labels | `SCHEMA_INVALID` |
| `L2-METRICS-RECOMPUTE` | 五个指标由 predictions 重算并落在容差内；标签顺序一致 | `REQUIRED_EVIDENCE_MISSING` |
| `L2-CONFUSION-CROSSCHECK` | 混淆矩阵逐格一致；行/列和 = n_test；缺 confusion 即失败 | `REQUIRED_EVIDENCE_MISSING` |
| `L2-LEAKAGE-R1..R5` | 五规则逐条执行；FAIL/NOT_EVALUABLE 阻塞 | `REQUIRED_EVIDENCE_MISSING` |

### 4.2 能证明 / 不能证明

**能证明**：predictions/metrics/混淆矩阵内部一致；R1–R5 在给定输入上可计算且未命中。
**不能证明**：predictions 是模型真实产生的；模型被训练/执行；不存在未声明的泄漏方式。

成套伪造可以让 predictions、metrics、混淆矩阵完全自洽并通过 L2；只有 L3 独立重跑
（M10）才能拦截。`L2Result.execution_claim` 固定为 `SELF_CONSISTENT_ONLY`；
`assert_not_execution_proof()` 拒绝任何“L2 PASS = 已验证执行”的声明。

## 5. 指标重算口径（`metric_recompute.py`）

| 指标 | 定义 | 边界 |
|---|---|---|
| `accuracy` | 正确行 / n_test | n_test=0 拒绝 |
| `precision_macro` | 对标签集合 L 逐类 P 后算术平均 | 分母 0 → P=0，记 `zero_division_hits` |
| `recall_macro` | 对 L 逐类 R 后平均 | 同上 |
| `f1_macro` | 对 L 逐类 `2PR/(P+R)` 后平均 | P+R=0 → F1=0 |
| `roc_auc_ovr` | 对 L 逐类 one-vs-rest AUC 后 macro 平均（多分类先逐类二值化） | 任一类单类/缺分数 → 整体 `UNDEFINED` |

- L = `sorted(set(y_true) ∪ set(y_pred))`；也可显式传 labels，但必须是并集超集。
- AUC 用 Mann–Whitney 秩和；同分取平均秩；全同分 → 0.5；单类 → `UNDEFINED`（不写 0.0）。
- 比较容差：`abs_tol=1e-12`、`rel_tol=1e-9`；L3 确定性模式不用此容差，改用 bit-exact。
- `bit_identical()` 比较 float64 位；`-0.0` 与 `+0.0` 不相等；NaN 永不相等。

## 6. 泄漏五规则的机器判据

| 规则 | 机器判据 | 通过条件 | 不可评估时 |
|---|---|---|---|
| R1 重复样本 | 特征 token 的 SHA-256 在 train/test 相同；数值 L∞ ≤ 阈值；文本 3-gram Jaccard ≥ 阈值 | 无同哈希/无近重复对 | `NOT_EVALUABLE`（无特征/无近重复可计算类型） |
| R2 分组泄漏 | `set(group(train)) ∩ set(group(test)) == ∅`；声明 none 但存在 group 列 → FAIL | 交集为空且 group_key 不作特征 | 缺 group 列 → `NOT_EVALUABLE` |
| R3 时序泄漏 | `max(time(train)) ≤ min(time(test))`；每个 feature_time 列逐行 `≤ label_time` | 两条都成立 | 时间无法解析/缺列 → `NOT_EVALUABLE` |
| R4 标签/后验 | 特征集合 == 白名单；target/ID/time/group/score 角色不得作特征；特征列哈希 ≠ target 哈希；\|Pearson\| < 0.999；低基数列不得每个取值唯一决定 target | 全部成立 | 白名单缺失 → `NOT_EVALUABLE` |
| R5 指标来源 | `metrics.split=="test"`；manifest_hash 一致；predictions 行集 == test；指标可重算；无非 test fold 指标 | 全部成立 | 缺 metrics/predictions → `NOT_EVALUABLE` |

- R1 的“近重复”只在 `NearDuplicateSpec.enabled=True` 时执行；阈值是策略值，改动必须升规则版本。
- R4 的确定性映射只对低基数（2–20 个取值）且非逐行唯一的列判定；连续特征不因逐行唯一被误杀。
- 所有 `NOT_APPLICABLE` 必须带 `reason`；`NOT_EVALUABLE` 一律阻塞 L2，不得写成 PASS。

## 7. 状态语义

| 状态 | 含义 | L2 是否阻塞 |
|---|---|---|
| `PASS` | 判据真实计算且成立 | 否 |
| `FAIL` | 判据计算后不成立 | 是 |
| `NOT_APPLICABLE` | 规则在声明语义下不适用，必须带 reason | 否（但报告必须展示） |
| `NOT_EVALUABLE` | 缺输入/无法计算 | **是（fail-closed）** |

L1/L2 的 `CheckStatus` 只用 `PASS/FAIL/SKIP/NOT_RUN` 四值；L2 不使用 `SKIP` 来跳过检查，
缺输入一律 `FAIL`。`LeakageReport.status()` 在 FAIL+NOT_EVALUABLE 并存时返回 FAIL。

## 8. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| L1 七项检查齐全 | `l1_integrity.L1IntegrityVerifier.CHECK_ORDER`；本文 §3.1 | 已定义，未执行 |
| L2 指标从 predictions 重算 | `metric_recompute.recompute_all`；`l2_consistency._check_metrics_recompute` | 已定义，未执行 |
| 混淆矩阵交叉校验 | `l2_consistency._check_confusion` | 已定义，未执行 |
| 五条泄漏规则有可执行判据 | `leakage_rules.r1..r5`；本文 §6 | 已定义，未执行 |
| L2 PASS 不写成“真实执行” | `L2Result.execution_claim`；`assert_not_execution_proof()`；本文 §4.2 | 已定义，未执行 |
| 负例覆盖伪造/误判 | `M09_verifier_l12/NEGATIVE_TESTS.md` | 判据已定义，未执行 |

## 9. OPEN QUESTIONS（详见 `design/pseudocode/OPEN_QUESTIONS.md`）

| 编号 | 问题 | P5 临时处理 |
|---|---|---|
| `OQ-P5-08` | R1 近重复/R4 相关系数阈值是策略常量 | 写入 `NearDuplicateSpec`/`correlation_threshold`；是否进规则集待裁决 |
| `OQ-P5-11` | L2 的 `confusion` 字段不在 M06 五产物契约内 | L2 要求 metrics.json 含 confusion；缺失按 FAIL；需 WP-05 确认 |

## 10. 本阶段不做

- 不做 L3 重跑与等价性判定（M10）。
- 不做签名、证书、离线验签（P6）。
- 不评价实验设计/科学结论；不修改 expected/阈值。
- 不建库、不跑测试、不写业务代码。