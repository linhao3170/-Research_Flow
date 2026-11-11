# M09 · NEGATIVE_TESTS — L1/L2 与泄漏五规则负例（P5）

> 阶段：P5｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：M09 落地（WP-11）、L2 与模板联调（WP-05/WP-11）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P5 不得写成“已通过”**。
> 真实证据链/真实 CSV/真实 predictions；不得用 mock 证明“泄漏会被抓住”。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：`L1Check.check_id` + `status` + `expected/actual`，
   或 `L2Check.check_id` + `status` + `L2Gap.code` + `L2Gap.error_code`（至少三项）。
2. 泄漏规则负例必须断言 `LeakageFinding.rule_id` + `status` + `code` + `pairs/counts`；
   只断言 `L2Result.status=FAIL` 判失败（可能是别的规则失败）。
3. `NOT_EVALUABLE` 必须断言“阻塞 L2”，不得被断言为 PASS 或 SKIP。
4. 篡改类负例必须给出真实 diff（改前/改后字节或字段），并断言检测发生的具体字段。
5. 不得修改 expected/阈值/规则来“修好”；原因不符即失败。
6. 正例通过不构成完成证据；本表必须真实执行并逐条留拒绝原因。

## A. L1 过程完整性

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M09-01 | schema_version 不符 | 一条记录 `schema_version="2.0"` | `L1-SCHEMA` FAIL；`actual` 含该 evidence_id；`L1Result.status=FAIL` | 本文 §3.1 |
| NEG-M09-02 | 记录缺必填字段 | schema 端口桩拒绝缺 `payload_hash` 的记录（不构造非法 dataclass） | `L1-SCHEMA` FAIL；端口异常文本含字段名；不得继续 PASS | 同上 |
| NEG-M09-03 | payload 被改 | 改 `payloads/<hash>.json` 一字节 | `L1-PAYLOAD-HASH` FAIL；`actual` 含两个哈希；`BUNDLE_TAMPERED` 语义 | 同上 |
| NEG-M09-04 | 产物被改 | 改 `artifacts/metrics.json` 一字节 | `L1-ARTIFACT-HASH` FAIL；`actual` 含 `metrics.json`；`checked` 计数正确 | 同上 |
| NEG-M09-05 | 产物未登记 | `artifact_refs` 指向清单外产物 | `L1-ARTIFACT-HASH` FAIL；`actual` 含“未登记哈希” | 同上 |
| NEG-M09-06 | event_seq 跳号 | seq=1,2,4 | `L1-EVENT-SEQ` FAIL；`expected=3`、`actual=4` | 同上 |
| NEG-M09-07 | event_seq 回退 | seq=1,3,2 | `L1-EVENT-SEQ` FAIL；`expected=3`、`actual=2` | 同上 |
| NEG-M09-08 | prev_hash 不接链 | 改第二条 `prev_hash` 一位 | `L1-CHAIN-HASH` FAIL；`expected` 为上一条 `chain_hash` | 同上 |
| NEG-M09-09 | chain_hash 重算不符 | 改记录字段，保留 `chain_hash` | `L1-CHAIN-HASH` FAIL；`expected` 为重算值 | 同上 |
| NEG-M09-10 | Merkle 根不符 | 改 `expected_evidence_root` 一位 | `L1-MERKLE` FAIL；`expected/actual` 均给出 | 同上 |
| NEG-M09-11 | inclusion proof 失败 | 改 proof 中一个 sibling | `L1-MERKLE` FAIL；`evidence_ids` 指出失败记录 | 同上 |
| NEG-M09-12 | 目录复用（同 inode） | 两个 attempt 目录 `(st_dev, st_ino)` 相同 | `L1-DIRECTORY-REUSE` FAIL；`actual` 含“共用 inode”与两个 attempt key | 同上 |
| NEG-M09-13 | 目录复用（同 realpath） | 两个 attempt 的 realpath 相同 | `L1-DIRECTORY-REUSE` FAIL；`actual` 含“共用 realpath” | 同上 |
| NEG-M09-14 | 目录创建早于任务 | attempt 目录 `created_at` 早于 `task_created_at` | `L1-DIRECTORY-REUSE` FAIL；`actual` 含“目录创建早于任务创建” | 同上 |
| NEG-M09-15 | Verifier/Executor 目录重叠 | `verifier_workspace` 是某 attempt 的父目录 | `L1-DIRECTORY-REUSE` FAIL；`actual` 含“Verifier 工作目录与 attempt 目录重叠” | 同上 |
| NEG-M09-16 | 目录索引缺失 | `directories=()` | `L1-DIRECTORY-REUSE` FAIL；消息明确“fail-closed”；不得跳过 | 同上 |
| NEG-M09-17 | 空证据集 | `records=()` | `L1-SCHEMA`/`L1-MERKLE` FAIL；`L1Result.status=FAIL`；`assert_no_execution_claim()` **不抛**（因为不是 PASS）；不得 PASS | 同上 |

## B. L2 覆盖与字段语义

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M09-18 | predictions 缺行 | test 有 10 行，predictions 9 行 | `L2-PREDICTIONS-COVERAGE` FAIL；`detail.missing` 含缺的 row_id；`L2Gap.code=PREDICTIONS_COVERAGE` | 本文 §4.1 |
| NEG-M09-19 | predictions 多行 | 多一条非 test 行 | 同上；`detail.extra` 含多出的 row_id | 同上 |
| NEG-M09-20 | row_id 重复 | 两条相同 row_id | `L2-PREDICTIONS-COVERAGE` FAIL；`actual` 含行数/唯一数 | 同上 |
| NEG-M09-21 | fold=0 行混入 | 一条 `fold=0` | `L2-PREDICTIONS-COVERAGE` FAIL；`actual` 含该 row_id | 同上 |
| NEG-M09-22 | y_true 与数据不一致 | 改一条 y_true | `L2-PREDICTIONS-COVERAGE` FAIL；`actual` 含该 row_id | 同上 |
| NEG-M09-23 | metrics.n_test 不符 | `n_test=9`，test 10 行 | `L2-PREDICTIONS-COVERAGE` FAIL；`expected=10`、`actual=9` | 同上 |
| NEG-M09-24 | 未声明列 | predictions 多一列 `secret_label` | `L2-FIELD-SEMANTICS` FAIL；`actual` 含 `secret_label` | 本文 §4.1 |
| NEG-M09-25 | 缺当前模型预测列 | `columns` 只有 `pred_svm`，`model_key=random_forest` | `L2-FIELD-SEMANTICS` FAIL；`expected=pred_random_forest` | 同上 |
| NEG-M09-26 | y_pred 标签不在 metrics.labels | 预测一个未登记类别 | `L2-FIELD-SEMANTICS` FAIL；`actual` 含该标签 | 同上 |
| NEG-M09-27 | scores 含未登记标签 | `scores` 多一个标签 | `L2-FIELD-SEMANTICS` FAIL；`actual` 含该标签 | 同上 |

## C. L2 指标重算与混淆矩阵

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M09-28 | metrics 数值被改 | 把 `f1_macro` 加 0.01 | `L2-METRICS-RECOMPUTE` FAIL；`mismatches` 含 `METRIC_MISMATCH:f1_macro`；`delta` 正确 | 本文 §4.1 |
| NEG-M09-29 | metrics 缺指标 | 删除 `roc_auc_ovr` | `L2-METRICS-RECOMPUTE` FAIL；`mismatches` 含 `METRIC_MISSING` | 同上 |
| NEG-M09-30 | AUC 不可定义但写了 0.0 | test 只有单类标签 / 无 scores | `L2-METRICS-RECOMPUTE` FAIL；`actual` 含 `METRIC_UNDEFINED`；不得把 0.0 当有效值 | 本文 §5 |
| NEG-M09-31 | 标签顺序不一致 | `metrics.labels` 逆序 | `L2-METRICS-RECOMPUTE` FAIL；`expected/actual` 给出两个标签序列 | 同上 |
| NEG-M09-32 | 混淆矩阵缺字段 | `metrics.confusion=None` | `L2-CONFUSION-CROSSCHECK` FAIL；消息明确“缺少 confusion” | 本文 §4.1 |
| NEG-M09-33 | 混淆矩阵被改一格 | 某格 +1 | `L2-CONFUSION-CROSSCHECK` FAIL；`expected/actual` 给出完整矩阵 | 同上 |
| NEG-M09-34 | 混淆矩阵行和错 | 行和 ≠ n_test | `L2-CONFUSION-CROSSCHECK` FAIL；`detail.row` 指出行号；列和错误改用 `detail.column` | 同上 |

## D. 泄漏五规则（每条必须单独命中）

| ID | 规则 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M09-35 | R1 精确重复 | test 行与 train 行特征完全相同 | `L2-LEAKAGE-R1` FAIL；`LeakageFinding.code=R1_DUPLICATE_SAMPLE`；`pairs` 至少 1 对 | 本文 §6 R1 |
| NEG-M09-36 | R1 近重复 | 数值行仅差 1e-12 | `R1_DUPLICATE_SAMPLE`；`pairs` 的 distance ≤ 阈值 | 同上 |
| NEG-M09-37 | R1 无特征列 | `feature_whitelist=()` | `R1_NO_FEATURES` / `NOT_EVALUABLE`；`L2` FAIL，不得 PASS | 同上 |
| NEG-M09-38 | R2 分组重叠 | 同一 group 同时出现在 train/test | `L2-LEAKAGE-R2` FAIL；`code=R2_GROUP_OVERLAP`；`overlap_sample` 含该 group | 本文 §6 R2 |
| NEG-M09-39 | R2 有 group 列但声明 none | `manifest.group_key=None`，数据列 role=group | `R2_GROUP_COLUMN_UNDECLARED`；FAIL | 同上 |
| NEG-M09-40 | R2 group_key 作特征 | group_key 在 feature_whitelist | `R2_GROUP_KEY_AS_FEATURE`；FAIL | 同上 |
| NEG-M09-41 | R2 缺 group 列 | manifest 声明 group_key，但数据无该列 | `R2_GROUP_COLUMN_MISSING`；NOT_EVALUABLE；L2 FAIL | 同上 |
| NEG-M09-42 | R3 时间倒置 | max(train_time) > min(test_time) | `L2-LEAKAGE-R3` FAIL；`code=R3_TIME_ORDER_VIOLATION`；给出两个边界值 | 本文 §6 R3 |
| NEG-M09-43 | R3 未来特征 | 某行 feature_time > label_time | `R3_FUTURE_FEATURE`；FAIL；`counts.violations` 正确 | 同上 |
| NEG-M09-44 | R3 时间列未声明 | 数据有 role=time 列，manifest.time_key=None | `R3_TIME_COLUMN_UNDECLARED`；FAIL | 同上 |
| NEG-M09-45 | R4 target 混入特征 | feature_whitelist 含 target | `L2-LEAKAGE-R4` FAIL；`code=R4_TARGET_IN_FEATURES` | 本文 §6 R4 |
| NEG-M09-46 | R4 白名单缺失 | `feature_whitelist=None` | `R4_WHITELIST_MISSING`；NOT_EVALUABLE；L2 FAIL | 同上 |
| NEG-M09-47 | R4 后验字段 | 特征与 target 完全相关（\|r\|≥0.999） | `R4_PERFECT_CORRELATION`；FAIL；`detail.correlation` 正确 | 同上 |
| NEG-M09-48 | R4 标签副本 | 特征列逐值等于 target 列 | `R4_TARGET_DUPLICATE_COLUMN`；FAIL | 同上 |
| NEG-M09-49 | R4 高基数 ID | 字符串特征逐行唯一且名如 `patient_id` | `R4_HIGH_CARDINALITY_ID`；FAIL | 同上 |
| NEG-M09-50 | R5 metrics 不是 test | `metrics.split="all"` | `L2-LEAKAGE-R5` FAIL；`code=R5_METRICS_NOT_TEST` | 本文 §6 R5 |
| NEG-M09-51 | R5 manifest 不符 | `metrics.split_manifest_hash` 改一位 | `R5_MANIFEST_HASH_MISMATCH`；FAIL | 同上 |
| NEG-M09-52 | R5 predictions 非 test 行 | predictions 含 train row | `R5_PREDICTIONS_NOT_TEST_ROWS`；FAIL；`detail.missing/extra` | 同上 |
| NEG-M09-53 | R5 指标不可重算 | 改 predictions 一行但保留 metrics | `R5_METRICS_NOT_RECOMPUTABLE`；FAIL；`mismatches` 非空 | 同上 |
| NEG-M09-54 | R5 含 train fold 指标 | `per_fold_values={0:...,1:...}` | `R5_TRAIN_METRICS_PRESENT`；FAIL | 同上 |

## E. “L2 通过 ≠ 真实执行”

| ID | 目标 | 输入 / 操作 | 预期结果（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M09-55 | L2 PASS 不得声明执行 | 构造 L2 全 PASS，再尝试把 `execution_claim` 改成 `"VERIFIED_EXECUTION"` | `L2Result.assert_not_execution_proof()` 抛 `L2Error`；`error_code=SCHEMA_INVALID`；`reason=L2_CLAIMS_EXECUTION`；默认值必须是 `SELF_CONSISTENT_ONLY` | 本文 §4.2 |
| NEG-M09-56 | 成套伪造 L2 全过 | 伪造 predictions/metrics/混淆矩阵，使 L2 全 PASS | L2 `status=PASS`；`execution_claim=SELF_CONSISTENT_ONLY`；**不得**出现 `VERIFIED`/`execution_proof` 字段；必须由 M10 L3 重跑拦截 | M10 `NEG-M10-01` |
| NEG-M09-57 | L2 PASS 被 Gate 当 E2 | 用 L2Result 冒充 `metrics_recomputable` 的证据；证据链合法但没有该 check 的 E2/E3 记录 | Gate 第 4 步该行 `level=None`、`result=GAP`；`GateGap.code=REQUIRED_CHECK_MISSING`；`error_code=REQUIRED_EVIDENCE_MISSING`；`veto_class=REQUIRED_CHECK_MISSING`；不得 PASS；不得断言 `E0_E1_CANNOT_SATISFY_EXECUTION_CHECK`（合法规则集下不可达） | M08 `NEG-M08-01` |

## F. 误拒守卫

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M09-01 | 首条 prev 非全零不误拒 | 首条 `prev_hash="a"*64` | `L1-CHAIN-HASH` PASS（OQ-CT-10 只校形态） | 本文 §3.1 |
| GUARD-M09-02 | 无产物不误拒 | 记录 `artifact_refs=()` | `L1-ARTIFACT-HASH` PASS；`checked=0`；不得 SKIP | 同上 |
| GUARD-M09-03 | 合法 L2 不被误拒 | 真实一致的 predictions/metrics/confusion/五规则全 PASS | `L2Result.status=PASS`；`execution_claim=SELF_CONSISTENT_ONLY` | 本文 §4 |
| GUARD-M09-04 | R2 无分组不误拒 | `group_key=None` 且无 group 列 | R2 `NOT_APPLICABLE`；L2 不因此 FAIL；报告展示 reason | 本文 §6 R2 |
| GUARD-M09-05 | R1 连续特征不误杀 | 数值特征逐行唯一但无重复 | R1 PASS；不得因“逐行唯一”判重复 | 本文 §6 R1 |
| GUARD-M09-06 | 3 分类 OvR AUC 不误判 UNDEFINED | 3 个观测标签、每行 scores 含三类分数 | `roc_auc_ovr` 返回 `[0,1]` 浮点数；`undefined` 不含 `roc_auc_ovr`；不得返回 `(None, "AUC_UNDEFINED")` | 本文 §5 |

## G. 执行记录模板（落地阶段填写，P5 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M09-03 | （待执行） | — | — | — | 未执行 |
| NEG-M09-12 | （待执行） | — | — | — | 未执行 |
| NEG-M09-28 | （待执行） | — | — | — | 未执行 |
| NEG-M09-35 | （待执行） | — | — | — | 未执行 |
| NEG-M09-42 | （待执行） | — | — | — | 未执行 |
| NEG-M09-55 | （待执行） | — | — | — | 未执行 |