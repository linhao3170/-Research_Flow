# M10 · NEGATIVE_TESTS — L3 沙箱、重放与归因负例（P5）

> 阶段：P5｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：M10 落地（WP-08）、L3 与 Verifier 联调（WP-11）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P5 不得写成“已通过”**。
> 真实目录/真实进程/真实数据；不得用 mock 证明“L3 真的重跑”。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：`L3Error.error_code` + `reason` + `field_path`，
   或 `L3ReplayResult.status=FAIL` + `attribution.primary` + 具体 comparison 字段。
2. 伪 L3 负例必须断言**没有产生 PASS**；只断言“抛异常”判失败（可能是别的原因）。
3. 沙箱负例必须断言 `SandboxViolation.error_code=TOOL_NOT_ALLOWLISTED`(403) 且
   `reason` 精确（如 `L3_READ_OUTSIDE_ALLOWLIST`）。
4. 等价性负例必须断言种子数、`plan_hash`、`frozen_at` 或 TOST 的具体字段；
   不得只断言“结果不同”。
5. 归因负例必须断言 `primary` 类别与 `confidence`；确定性模式下输出不同却
   `primary=RANDOMNESS` 判失败。
6. 不得修改 expected/阈值/规则来“修好”；原因不符即失败。
7. 正例通过不构成完成证据；本表必须真实执行并逐条留拒绝原因。

## A. 六个必测场景（P5 验收）

| ID | 场景 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M10-01 | **成套伪造：L2 过、L3 拒** | 伪造 predictions + metrics + confusion，使 L2 全 PASS；L3 从原始数据重训后预测/指标不同 | L2 `status=PASS` 且 `execution_claim=SELF_CONSISTENT_ONLY`；L3 `status=FAIL`；`attribution.primary ∈ {DATA,CODE,ENVIRONMENT,RULES,UNKNOWN}`；`metrics.deterministic_mismatches` 非空；`L3ReplayResult.passed()=False` | 策划书 §7.7；本文 §6 |
| NEG-M10-02 | **只重算指标冒充 L3** | 沙箱不启动模型，只从原 predictions 重算 metrics | `SandboxRunOutput.metrics_only=True` → `L3Error(L3_METRICS_ONLY, REQUIRED_EVIDENCE_MISSING)`；或 `predictions_source != "sandbox_run"` → `L3_READS_ORIGINAL_PREDICTIONS`；不得 PASS | 策划书 §9.3 |
| NEG-M10-03 | **原目录重跑** | `ProcessIdentity.cwd` 在原 attempt 目录内 | `L3Error(L3_ORIGINAL_DIR_RERUN, TOOL_NOT_ALLOWLISTED, 403)`；`field_path=cwd`；不得进入比较 | 策划书 §9.3；AGENTS §4.9 |
| NEG-M10-04 | **读取原运行产物** | 沙箱 audit 记录读取原 `predictions.csv`/`metrics.json` | `SandboxAudit.assert_clean()` 抛 `L3Error(L3_READ_ORIGINAL_ARTIFACTS, TOOL_NOT_ALLOWLISTED, 403)`；`original_artifact_reads` 非空；不得 PASS | 策划书 §9.3 |
| NEG-M10-05 | 缺 E2 的节点被送进 L3 | 节点没有 E2 `executor_launch/exit`，只有 E0 | L3 前置要求原运行 E2 引用；`OriginalRunRef` 构造/校验失败或 L3 物证无 E3 回查；Gate 第 7 步 `L3_ATTESTATION_MISSING`；不得 PASS | M08 §5 第 7 步 |
| NEG-M10-06 | 规则版本不符仍想 L3 PASS | `ReplayInput.ruleset_hash` 与原运行不同 | `L3Error(L3_RULESET_MISMATCH, RULESET_VERSION_MISMATCH, 409)`；`field_path=ruleset_hash`；不得执行 | M08 §4 |

## B. 沙箱与进程隔离

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M10-07 | 读取允许清单外文件 | `resolve_read("artifacts/metrics.json")` | `SandboxViolation(L3_READ_OUTSIDE_ALLOWLIST, TOOL_NOT_ALLOWLISTED, 403)` | 本文 §3.1 |
| NEG-M10-08 | `..` 路径逃逸 | `resolve_read("../predictions.csv")` | `L3_PATH_TRAVERSAL`；403；不得回退到模糊匹配 | 同上 |
| NEG-M10-09 | 绝对路径/盘符/UNC | `resolve_read("C:/Windows/...")` / `\\\\server\\share` | `L3_PATH_DRIVE` / `L3_PATH_ABSOLUTE`；403 | 同上 |
| NEG-M10-10 | 复用 Executor PID | `ProcessIdentity.pid == executor_pid` | `L3Error(L3_SAME_PID, TOOL_NOT_ALLOWLISTED, 403)`；`field_path=pid` | 本文 §3.3 |
| NEG-M10-11 | Executor 直接派生 L3 | `parent_pid == executor_pid` | `L3_PARENT_IS_EXECUTOR`；403 | 同上 |
| NEG-M10-12 | cwd 在 Executor 工作区 | `cwd` 在 `executor_workspace_root` 内 | `L3_CWD_IN_EXECUTOR_WORKSPACE`；403 | 同上 |
| NEG-M10-13 | cwd 不在沙箱 | `cwd` 为任意其它目录 | `L3_CWD_OUTSIDE_SANDBOX`；403 | 同上 |
| NEG-M10-14 | sandbox_root 不是本沙箱 | `sandbox_root` 指向旧 L3 目录 | `L3_SANDBOX_ROOT_MISMATCH` 或 `L3_SANDBOX_REUSED`；403 | 同上 |
| NEG-M10-15 | 进程启动早于沙箱 | `started_at < plan.created_at` | `L3_PROCESS_BEFORE_SANDBOX`；不得 PASS | 同上 |
| NEG-M10-16 | 进程非零退出 | `exit_code=1` | `L3Error(L3_PROCESS_FAILED, REQUIRED_EVIDENCE_MISSING)`；不得比较 | 同上 |
| NEG-M10-17 | 没有 CPU 时间 | `cpu_time_sec=0` | `L3_NO_CPU_TIME`；疑似未执行；不得 PASS | 同上 |
| NEG-M10-18 | 继承代理/凭据 | env 含 `HTTP_PROXY`/`PYTHONPATH` | `SandboxViolation(L3_ENV_INHERITED)`；拒绝构造 `ProcessSpec` | 本文 §3.3 |
| NEG-M10-19 | shell 启动 | `ProcessSpec.shell=True` | `L3_SHELL_FORBIDDEN`；不得启动 | 同上 |
| NEG-M10-20 | 沙箱根在 Executor 工作区 | `plan.root` 落在 `executor_workspace_root` | `L3_ROOT_INSIDE_EXECUTOR`；拒绝 plan | 同上 |
| NEG-M10-21 | 复用旧 run_id | `run_id` 已存在 | `L3_RUN_DIR_COLLISION`（创建时 `exist_ok=False`）；不得覆盖 | 本文 §3 |

## C. 真实执行证明（伪 L3）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M10-22 | 没有新进程 | `processes=()` | `L3Error(L3_NO_NEW_PROCESS, REQUIRED_EVIDENCE_MISSING)` | 本文 §6 |
| NEG-M10-23 | predictions 来自原运行 | `predictions_source="original_run"` | `L3_READS_ORIGINAL_PREDICTIONS`；不得 PASS | 同上 |
| NEG-M10-24 | predictions 来自缓存 | `predictions_source="cache"` | 同上 | 同上 |
| NEG-M10-25 | RETRAIN 但没有 fit | `execution_mode=RETRAIN`、`model_fit_count=0` | `L3_NO_MODEL_FIT`；不得 PASS | 同上 |
| NEG-M10-26 | REINFER 但没有推理行 | `execution_mode=REINFER`、`infer_rows=0` | `L3_NO_INFERENCE`；不得 PASS | 同上 |
| NEG-M10-27 | 复制原预测 | predictions 与原值完全相同、无 fit/infer、audit 无读取 | `L3_NO_MODEL_FIT`/`L3_NO_INFERENCE`；`assert_no_fake_l3()` 拒绝 | 同上 |
| NEG-M10-28 | 只有 metrics 产物 | `artifacts={"metrics.json":...}`，无 predictions | `OUTPUT_NO_PREDICTIONS`；不得 PASS | 同上 |
| NEG-M10-29 | 空 predictions | `predictions=()` | `OUTPUT_NO_PREDICTIONS`；不得 PASS | 同上 |
| NEG-M10-30 | 沙箱审计有拒绝读取 | `denied_reads` 非空 | `L3_DENIED_READ_ATTEMPTED`；403；fail-closed | 本文 §3.1 |

## D. 等价性

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M10-31 | 随机性种子 <5 | `EquivalencePlan(mode=STOCHASTIC, seeds=(1,2,3))` | `L3Error(INSUFFICIENT_SEEDS, REQUIRED_EVIDENCE_MISSING, 409)`；`field_path=seeds` | 策划书 §9.4 |
| NEG-M10-32 | 种子重复 | `seeds=(1,1,2,3,4)` | `PLAN_SEEDS_DUPLICATED`；拒绝 | 同上 |
| NEG-M10-33 | 种子未预注册 | 运行时用 `seeds` 之外的 seed | `SEED_NOT_PREREGISTERED`；409 | 同上 |
| NEG-M10-34 | 计划后冻结 | `frozen_at > started_at` | `EQUIVALENCE_PLAN_NOT_PRE_FROZEN`；409 | 同上 |
| NEG-M10-35 | plan_hash 与内容不符 | 改 margin/种子但保留旧 `plan_hash` | `PLAN_HASH_MISMATCH`；409 | 同上 |
| NEG-M10-36 | 确定性模式多 seed | `mode=DETERMINISTIC, seeds=(1,2)` | `DETERMINISTIC_SEED_COUNT`；拒绝 | 同上 |
| NEG-M10-37 | 确定性模式 margin>0 | `mode=DETERMINISTIC, margin=0.01` | `DETERMINISTIC_MARGIN`；拒绝 | 同上 |
| NEG-M10-38 | 随机性模式 margin=0 | `mode=STOCHASTIC, margin=0` | `STOCHASTIC_MARGIN`；拒绝 | 同上 |
| NEG-M10-39 | TOST 不通过 | 5 个种子均值偏离原值超过 margin | `TOST_NOT_EQUIVALENT`；`MetricComparison.passed()=False`；`TOSTResult.ci_low/ci_high` 落在边界外 | 策划书 §9.4 |
| NEG-M10-40 | 确定性预测差一位 | 改一个 score 的最低位 | `PredictionComparison.bit_exact=False`；`mismatch_count>0`；`metrics`/`predictions` 均 FAIL | 同上 |
| NEG-M10-41 | 确定性指标差一位 | 改 metrics 最后一位 | `MetricComparison.deterministic_mismatches` 非空；不得用 L2 容差放过 | 同上 |

## E. 前置哈希与归因

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M10-42 | 数据哈希不符 | `dataset_hash` 与 manifest 不同 | `L3Error(DATASET_HASH_MISMATCH, BUNDLE_TAMPERED)` | 本文 §4 |
| NEG-M10-43 | Split Manifest 被改 | manifest_hash 与原运行不同 | `SPLIT_MANIFEST_HASH_MISMATCH`；`BUNDLE_TAMPERED` | 同上 |
| NEG-M10-44 | Split 六字段非法 | train/test 重叠 | `SPLIT_MANIFEST_INVALID`；不得进入重跑 | 同上 |
| NEG-M10-45 | 代码快照不符 | code_hash 不同 | `CODE_SNAPSHOT_MISMATCH`；不得执行 | 同上 |
| NEG-M10-46 | 配置快照不符 | config_hash 不同 | `CONFIG_SNAPSHOT_MISMATCH`；不得执行 | 同上 |
| NEG-M10-47 | 依赖锁不符 | dependency_lock_hash 不同 | `L3_DEPENDENCY_LOCK_MISMATCH` | 同上 |
| NEG-M10-48 | 环境指纹不符 | env_fingerprint 不同 | `L3_ENVIRONMENT_MISMATCH`；不得声称同环境 | 同上 |
| NEG-M10-49 | 归因：环境（单元） | 直接调用 `attribution.attribute`；仅 environment `FactorCheck.matched=False`，其它匹配 | `primary=ENVIRONMENT`；`confidence=HIGH`；`unexplained=False` | 本文 §7 |
| NEG-M10-50 | 归因：数据（单元） | 直接调用 `attribution.attribute`；仅 data 不匹配 | `primary=DATA`；`confidence=HIGH` | 同上 |
| NEG-M10-51 | 归因：代码（单元） | 直接调用 `attribution.attribute`；仅 code 不匹配 | `primary=CODE`；`confidence=HIGH` | 同上 |
| NEG-M10-52 | 归因：规则（单元） | 直接调用 `attribution.attribute`；rules 与 data 同时不匹配 | `primary=RULES`；`contributors=(DATA,)`；`confidence=MEDIUM`；`requires_human_review=True` | 同上 |
| NEG-M10-53 | 归因：确定性 + 全一致 + 输出不同 | 四因子全匹配、DETERMINISTIC、预测不同 | `primary=UNKNOWN`；`confidence=HIGH`；`unexplained=True`；**不得** `RANDOMNESS` | 同上 |
| NEG-M10-54 | 归因：随机性不可解释 | 四因子全匹配、STOCHASTIC、种子未预注册 | `primary=UNKNOWN`；`confidence=LOW`；`requires_human_review=True` | 同上 |
| NEG-M10-55 | PASS 但存在未解释差异 | 手工构造 `status=PASS` + `attribution.unexplained=True` | `assert_no_fake_l3()` 抛 `L3_PASS_WITH_UNEXPLAINED_DIFF`；不得 PASS | 本文 §6 |
| NEG-M10-56 | **原运行基线被篡改** | 改 `expected_predictions` 一行/`expected_metrics` 一项/`expected_artifacts` 一个哈希，使 canonical 哈希或逐键值与 `OriginalRunRef` 不符 | `_assert_original_baseline` 抛 `L3Error(BUNDLE_TAMPERED, ORIGINAL_BASELINE_MISMATCH, 422)`；`field_path` 分别为 `predictions_hash`/`metrics_hash`/`artifact_hashes`；**未调用 `plan_sandbox`**（无新沙箱目录） | 本文 §4 第 1 步 |

## F. 误拒守卫

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M10-01 | 允许清单内的数据可读 | `is_read_allowed("datasets/wine/wine.csv")` | True；`resolve_read` 返回 source_root 内绝对路径 | 本文 §3.1 |
| GUARD-M10-02 | 确定性 bit-exact 可 PASS | 同一代码/配置/数据/种子，预测与指标逐位相同 | `status=PASS`；`predictions.bit_exact=True`；`attribution.no_difference=True` | 本文 §5.1 |
| GUARD-M10-03 | 随机性 TOST 通过可 PASS | 5 个预注册种子，每个指标 90% CI 在 ±margin 内 | `status=PASS`；`metric.TOSTResult.equivalent=True`；`attribution.primary=RANDOMNESS` 或 no_difference | 本文 §5.2 |
| GUARD-M10-04 | 非原产物审计不误拒 | audit 只有允许清单内读取，`original_artifact_reads=()` | `SandboxAudit.assert_clean()` 不抛；L3 可继续 | 本文 §3.1 |
| GUARD-M10-05 | 进程独立但不误拒 | 新 PID、parent=Verifier、cwd 在沙箱 | `_assert_process` 通过；不得因 `pid != executor_pid` 误判 | 本文 §3.3 |

## G. 执行记录模板（落地阶段填写，P5 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M10-01 | （待执行） | — | — | — | 未执行 |
| NEG-M10-02 | （待执行） | — | — | — | 未执行 |
| NEG-M10-03 | （待执行） | — | — | — | 未执行 |
| NEG-M10-04 | （待执行） | — | — | — | 未执行 |
| NEG-M10-31 | （待执行） | — | — | — | 未执行 |
| NEG-M10-53 | （待执行） | — | — | — | 未执行 |