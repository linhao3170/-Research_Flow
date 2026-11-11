# M08 · NEGATIVE_TESTS — Gate 与规则集负例（P5）

> 阶段：P5｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：M08 落地（WP-08）、Verifier 集成（WP-11）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P5 不得写成“已通过”**。
> 真实 Gate/真实规则集/真实证据链；不得用 mock 证明“缺证据会被拒绝”。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：`GateResult.verdict` + `GateGap.code` +
   `GateGap.error_code` + `GateGap.veto_class()`（至少三项），只断言“不是 PASS”判失败。
2. 四类 veto 同时断言 `GateResult.veto_classes()`；结构性 veto（如未知节点）必须
   `veto=True` 但 `veto_class() is None`，不得冒充四类。
3. 覆盖矩阵负例必须断言具体 `CoverageRow.result == "GAP"` 与 `required_check_id`；
   不得只看 `GateResult.coverage.missing > 0`。
4. 链/序列负例必须断言短路：`executed_steps == (STEP_1,)` 或 `(STEP_1, STEP_2)`，
   证明没有在断裂链上继续算 coverage。
5. 负例不得修改 expected、规则集或阈值来“修好”；原因不符即失败。
6. 正例通过不构成完成证据；本表必须真实执行并逐条留拒绝原因。
7. 装载期拒绝也是一票否决：必须断言 `load_ruleset` 抛出的 `error_code` 与 `reason`
   （`SCHEMA_INVALID` + 具体 reason），不得只断言“抛了异常”。

## A. 七步与四类 veto

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M08-01 | **缺 E2**：执行类必检只有 E0/E1 | 规则集 `metrics_recomputable.min_level=E2`；证据只有 `tool_invocation` + `agent_claim` | `verdict=BLOCKED`；`GateGap.code=REQUIRED_CHECK_MISSING`；`error_code=REQUIRED_EVIDENCE_MISSING`；`veto_class=REQUIRED_CHECK_MISSING`；`veto_classes` 含 `REQUIRED_CHECK_MISSING`；`coverage.row_for("metrics_recomputable")` 的 `level=None`、`evidence_ids=()`、`result=GAP` | 本文 §5 第 4/6 步；策划书 §7.2 |
| NEG-M08-02 | **规则版本不符** | `task_ruleset_hash` 改成另一个合法 64 hex | `verdict=BLOCKED`；`GateGap.code=TASK_RULESET_MISMATCH`；`error_code=RULESET_VERSION_MISMATCH`(409)；`veto_class=RULESET_VERSION_MISMATCH`；`executed_steps==(STEP_1,)` | 本文 §4；`ruleset.assert_task_binding` |
| NEG-M08-03 | 规则集内容被改但哈希未变 | 装载后修改 `required_checks`，保留旧 `ruleset_hash` | `verdict=BLOCKED`；`code=RULESET_HASH_UNSTABLE`；`error_code=RULESET_VERSION_MISMATCH`；不进入第 2 步 | 本文 §4 |
| NEG-M08-04 | 证据 schema_version 不是 1.0 | 一条记录 `schema_version="2.0"` | `verdict=BLOCKED`；`code=EVIDENCE_SCHEMA_VERSION_MISMATCH`；`veto_class=RULESET_VERSION_MISMATCH` | 05 §4.1；本文 §5 第 1 步 |
| NEG-M08-05 | **哈希不符**：产物被改 | `artifact_observed` 引用 `metrics.json`；磁盘哈希与 `artifact_manifest` 不同 | `verdict=BLOCKED`；`code=ARTIFACT_HASH_MISMATCH`；`error_code=BUNDLE_TAMPERED`；`veto_class=HASH_MISMATCH`；对应行 GAP | 本文 §5 第 3 步 |
| NEG-M08-06 | payload sidecar 被改 | 改 `payloads/<hash>.json` 一字节 | `code=PAYLOAD_HASH_MISMATCH`；`error_code=BUNDLE_TAMPERED`；`hash_status=MISMATCH`；该证据不进入 coverage | 本文 §5 第 3 步 |
| NEG-M08-07 | 产物哈希未登记 | `artifact_refs` 指向一个 E2 未观测的产物 | `code=ARTIFACT_HASH_NOT_REGISTERED`；`error_code=SCHEMA_INVALID`；`veto=True`；不得“稍后补哈希” | 本文 §5 第 3 步 |
| NEG-M08-08 | **冲突未解释** | `ConflictJournalPort` 返回 `resolved=False` 的冲突 | `verdict=BLOCKED`；`code=UNRESOLVED_EVIDENCE_CONFLICT`；`error_code=REQUIRED_EVIDENCE_MISSING`；`veto_class=UNRESOLVED_EVIDENCE_CONFLICT` | 本文 §7；策划书 §7.2 |
| NEG-M08-09 | 冲突日志不可读 | `unresolved()` 抛异常 | `code=CONFLICT_JOURNAL_UNAVAILABLE`；`verdict=BLOCKED`；不得当作“没有冲突” | 本文 §7 |
| NEG-M08-10 | 重复 launch | 同 `(task,node,attempt)` 两条 `executor_launch` | `code=DUPLICATE_ATTEMPT_EVENT`；`error_code=SCHEMA_INVALID`；`veto_class=UNRESOLVED_EVIDENCE_CONFLICT` | 本文 §5 第 5 步 |
| NEG-M08-11 | **必检缺失只告警不阻断** | 规则集有一项必检无任何证据；调用方只记录 warning | `verdict=BLOCKED`；`vetoes` 非空；`coverage.missing >= 1`；**不存在** `warning` 字段或“advisory”状态 | 本文 §7；AGENTS §8 |
| NEG-M08-12 | 必检项绑定不到节点 | 规则集有 `seed_recorded`，但所有 NodeSpec.required_checks 都不含它 | `code=CHECK_NOT_BOUND_TO_ANY_NODE`；`error_code=REQUIRED_EVIDENCE_MISSING`；`veto=True`；该行 GAP | 本文 §6 反空转 |
| NEG-M08-13 | **装载期拒绝 E0/E1 上的执行类必检** | (a) `execution_critical=True`、`min_level="E1"`；(b) `execution_critical=True`、`min_level="E2"`、`accepted_kinds=("tool_invocation",)` | (a) `load_ruleset` 抛 `RulesetError`：`error_code=SCHEMA_INVALID`、`reason=EXECUTION_CHECK_LEVEL_TOO_LOW`、`field_path` 指向 `required_checks[...].min_level`；(b) 抛 `SCHEMA_INVALID` / `EVIDENCE_RULE_BELOW_MIN_LEVEL`，`field_path` 指向 `evidence_rule` | `ruleset.RequiredCheck.__post_init__`；本文 §0 第 7 条 |
| NEG-M08-14 | **装载期拒绝 agent_claim 上的执行类必检** | `execution_critical=True`、`min_level="E2"`、`accepted_kinds=("agent_claim",)` | `load_ruleset` 抛 `RulesetError`：`error_code=SCHEMA_INVALID`、`reason=EVIDENCE_RULE_BELOW_MIN_LEVEL`、`field_path` 指向 `required_checks[...].evidence_rule` | 同上 |
| NEG-M08-15 | producer 错 | E2 记录 `producer="agent"` | `code=PRODUCER_MISMATCH`；`error_code=SCHEMA_INVALID`；`veto=True`；`hash_status=MISMATCH` | 05 §4.5 |
| NEG-M08-16 | level↔kind 错配 | `kind="artifact_observed"` 但 `level="E1"` | `code=LEVEL_KIND_MISMATCH`；`error_code=SCHEMA_INVALID`；`veto=True` | 05 §4.5 |

## B. 链与序列（第 2 步短路）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M08-17 | event_seq 跳号 | seq=1,2,4 | `code=SEQ_GAP`；`error_code=EVENT_SEQ_GAP`；`veto=True`；`executed_steps==(STEP_1, STEP_2)` | 本文 §5 第 2 步 |
| NEG-M08-18 | event_seq 回退 | seq=1,3,2 | `code=SEQ_REGRESSION`；`error_code=EVENT_SEQ_REGRESSION`；`veto=True` | 同上 |
| NEG-M08-19 | prev_hash 不接链 | 改第二条 `prev_hash` 一位 | `code=PREV_HASH_MISMATCH`；`error_code=EVIDENCE_CHAIN_BROKEN`；`veto=True`；`expected` 等于上一条 `chain_hash` | 本文 §5 第 2 步 |
| NEG-M08-20 | chain_hash 被改未重算 | 改记录字段，保留 `chain_hash` | `code=CHAIN_HASH_MISMATCH`；`error_code=EVIDENCE_CHAIN_BROKEN`；`veto=True` | 同上 |
| NEG-M08-21 | 首条 seq 不是 1 | 首条 `event_seq=2` | `code=FIRST_SEQ_NOT_ONE`；`error_code=EVENT_SEQ_GAP`；`veto=True` | 同上 |

## C. L3/IRC 门控（第 7 步）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M08-22 | 指标来源节点无 L3 | 节点在 `metric_source_nodes`，但 `l3_attestations` 为空 | `code=L3_ATTESTATION_MISSING`；`error_code=REQUIRED_EVIDENCE_MISSING`；`veto_class=REQUIRED_CHECK_MISSING`；`l3_coverage=0.0` | 本文 §5 第 7 步 |
| NEG-M08-23 | L3 物证规则版本不符 | `L3Attestation.ruleset_hash` 用另一个合法哈希 | `code=L3_RULESET_MISMATCH`；`error_code=RULESET_VERSION_MISMATCH`；`veto_class=RULESET_VERSION_MISMATCH` | 同上 |
| NEG-M08-24 | L3 物证不指向 E3 | `evidence_id` 指向一条 E2 `artifact_observed` | `code=L3_EVIDENCE_NOT_E3`；`error_code=SCHEMA_INVALID`；`veto=True` | 同上 |
| NEG-M08-25 | L3 物证引用的 E3 不存在 | `evidence_id="ev_..."` 不在记录索引 | `code=L3_EVIDENCE_NOT_FOUND`；`error_code=EVIDENCE_REFERENCE_NOT_FOUND`；`veto=True` | 同上 |
| NEG-M08-26 | 随机性模式种子不足 | `equivalence_mode=STOCHASTIC`、`seed_count=3` | `code=L3_INSUFFICIENT_SEEDS`；`error_code=REQUIRED_EVIDENCE_MISSING`；`veto=True` | 策划书 §9.4 |
| NEG-M08-27 | 等价性计划哈希缺失 | `plan_hash=""`（长度≠64） | `code=L3_PLAN_HASH_MISSING`；`error_code=REQUIRED_EVIDENCE_MISSING`；`veto=True` | 策划书 §9.4 |
| NEG-M08-28 | L3 覆盖不足 | 3 个指标来源节点只有 2 个 PASS L3，规则集 `required_coverage=1.0` | `code=L3_COVERAGE_INSUFFICIENT`；`l3_coverage≈0.667`；`veto=True`；`verdict=BLOCKED` | 本文 §5 第 7 步 |

## D. 跨模块：L2 通过、L3 拒绝（P5 验收必测）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M08-29 | **成套伪造（L2 过 L3 拒）** | 伪造 predictions + metrics + 混淆矩阵，使 L2 全 PASS；L3 重跑后预测/指标不同 | L2 `status=PASS` 且 `execution_claim=SELF_CONSISTENT_ONLY`；L3 `status=FAIL`；L3 `attribution.primary ∈ {DATA,CODE,ENVIRONMENT,UNKNOWN}`；Gate 第 7 步 `L3_NOT_PASS`/`L3_CHECK_NOT_PASS`；`verdict=BLOCKED` | M10 `NEG-M10-01`；本文 §8 |
| NEG-M08-30 | **只重算指标冒充 L3** | L3 只从原 predictions 重算 metrics，不启动模型 | L3 `code=L3_METRICS_ONLY`；`error_code=REQUIRED_EVIDENCE_MISSING`；Gate 不收该物证 | M10 `NEG-M10-02` |
| NEG-M08-31 | **原目录重跑** | `ProcessIdentity.cwd` 在原 attempt 目录 | L3 `code=L3_ORIGINAL_DIR_RERUN`；`error_code=TOOL_NOT_ALLOWLISTED`(403)；Gate 不收该物证 | M10 `NEG-M10-03` |
| NEG-M08-32 | **读取原运行产物** | 沙箱 audit 出现原 `predictions.csv`/`metrics.json` 读取 | L3 `code=L3_READ_ORIGINAL_ARTIFACTS`；`error_code=TOOL_NOT_ALLOWLISTED`；`audit.original_artifact_reads` 非空 | M10 `NEG-M10-04` |

## E. 误拒守卫（防止“过度收紧”）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M08-01 | 合法 Gate PASS | 8 项必检全部 E2/E3 覆盖、哈希一致、L3 4/4 PASS、无冲突 | `verdict=PASS`；`report_counts=(8,8,0)`；`veto_classes=()` | 本文 §5 |
| GUARD-M08-02 | 首条 prev 非全零不误拒 | 首条 `prev_hash="a"*64` | Gate 第 2 步接受（OQ-CT-10 只校形态）；不影响 PASS | 本文 §5 第 2 步 |
| GUARD-M08-03 | 非 L3 必检不误判 | `model_params_whitelisted` 只有 E1，`l3_required=False` | 行 `l3_status=SKIP`；只要 E1 足够即可 PASS；不得要求 L3 | 本文 §6 |
| GUARD-M08-04 | 非执行类 E1 可满足 | `seed_recorded` 由 `tool_invocation` 覆盖 | 行 PASS；不得触发 `E0_E1_CANNOT_SATISFY_EXECUTION_CHECK` | 本文 §5 第 6 步 |
| GUARD-M08-05 | 未知规则集字段被拒但合法字段不被误拒 | 规则集含全部 5 个顶层键 | `load_ruleset` 成功；`ruleset_hash` 稳定 | `ruleset.load_ruleset` |

## F. 执行记录模板（落地阶段填写，P5 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M08-01 | （待执行） | — | — | — | 未执行 |
| NEG-M08-02 | （待执行） | — | — | — | 未执行 |
| NEG-M08-05 | （待执行） | — | — | — | 未执行 |
| NEG-M08-11 | （待执行） | — | — | — | 未执行 |
| NEG-M08-29 | （待执行） | — | — | — | 未执行 |