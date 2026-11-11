# M10 · L3 / IRC 独立重执行（P5）

> 阶段：P5「门控与三级验证」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：L3 新目录/只读白名单/独立进程、重放流程、伪 L3 判定、等价性（bit-exact/TOST）、六类归因
> 不覆盖：签名/信任锚（P6）、验证预算/VAS（P9）、跨环境普遍复现、科学结论评价
> 前置：P4 已验收；M05 workspace 目录分离、M06 Split Manifest、M08 L3 阈值、M09 指标口径可用
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码

## 1. 目标

把“L3 必须真重跑”写成可机器判定的流程：

1. **新目录**：Verifier 每次生成新 `l3_<32hex>` 目录，`exist_ok=False`，不复用旧目录；
2. **只读白名单**：沙箱读取默认拒绝，只有 `READONLY_ALLOWLIST` 九类可读；
3. **独立进程**：新 PID、新 cwd、`shell=False`、`-I` 隔离模式、BLAS 线程=1、无网络/代理/凭据；
4. **真重跑**：读代码快照/配置/依赖锁/Split Manifest → 真重训或重推 → 比较预测/指标/产物；
5. **伪 L3 拒绝**：只重算指标、只重读 predictions、原目录重跑、复用 Executor 进程、无新进程、
   复制原预测 —— 全部有判定点；
6. **等价性**：确定性 bit-exact；随机性 ≥5 个预注册种子 + TOST + 边界哈希预冻结；
7. **六类归因**：环境/数据/代码/随机性/规则/未知，每类有机器判据与置信说明。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `verifier/l3_sandbox.py` | 新目录计划、只读白名单、进程规格/隔离断言、禁止读取清单 | 547 | 完成（伪代码） |
| `verifier/l3_replay.py` | 重放流程、真实执行证明、预测/指标/产物比较、TOST、L3 物证 | 1132 | 完成（伪代码） |
| `verifier/attribution.py` | 六类归因、置信、人工复核条件 | 293 | 完成（伪代码） |

### 2.1 `l3_replay.py` 函数索引（>800 行，按 PHASE_RULES §5 第 2 档登记）

| 符号 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `L3Error` | 130 | L3 前置/隔离/执行失败；对外码按语义选择 | 本文 §3 |
| `ExecutionMode` | 151 | RETRAIN / REINFER | 策划书 §9.3 |
| `EquivalenceMode` | 156 | DETERMINISTIC / STOCHASTIC | 策划书 §9.4 |
| `new_l3_run_id` | 161 | 新 `l3_<32hex>`，不复用 | 本文 §3 |
| `OriginalRunRef` | 170 | 原运行的哈希引用（不含可读路径） | 本文 §4 |
| `EquivalencePlan` | 208 | 模式/种子/边界/plan_hash/冻结时间 | 策划书 §9.4 |
| `assert_seed_allowed` | 266 | 种子必须在预注册集合内 | 同上 |
| `assert_pre_frozen` | 273 | 计划必须在首次重跑前冻结 | 同上 |
| `compute_plan_hash` | 290 | `sha256(JCS(payload))` | 同上 |
| `SplitComparison` | 296 | 六字段/manifest_hash 校验结果 | 策划书 §9.3 |
| `PredictionComparison` | 306 | 行集/bit-exact/差异计数 | 同上 |
| `TOSTResult` | 318 | 单指标 TOST 结果 | 策划书 §9.4 |
| `MetricComparison` | 332 | 确定性 mismatch 或随机性 TOST 集合 | 同上 |
| `ArtifactComparison` | 345 | 确定性产物哈希比较 | 同上 |
| `SandboxAudit` | 358 | 允许/拒绝/原产物读取审计 | 本文 §3 |
| `SandboxRunOutput` | 388 | 一次沙箱输出（predictions/metrics/artifacts/fit/infer） | 本文 §4 |
| `ProcessRunEvidence` | 422 | PID/exit/CPU/stdio 哈希 | 本文 §3 |
| `SplitVerifierPort` | 439 | M06 `SplitService.verify` 端口 | 策划书 §9.3 |
| `ReplayInput` | 464 | 完整只读输入（原运行只给哈希） | 本文 §4 |
| `L3ReplayResult` | 523 | 比较/归因/check_statuses/coverage | 本文 §5 |
| `L3ReplayResult.l3_status` | 563 | 报告字段投影（PASS/FAIL） | 本文 §5 |
| `assert_no_fake_l3` | 567 | 六类伪 L3 的机器判定 | 本文 §6 |
| `to_attestation` | 594 | 构造 M08 Gate 消费的 L3 物证 | M08 §5 第 7 步 |
| `L3Replayer.run` | 623 | 按 9.3 流程执行 | 策划书 §9.3 |
| `_assert_original_baseline` | 693 | expected 基线哈希回绑；篡改即 fail-closed | 本文 §4 第 1 步 |
| `_assert_preconditions` | 759 | 数据/代码/配置/依赖/规则/计划前置 | 本文 §4 |
| `_assert_process` | 800 | PID/cwd/sandbox/PID 分离/退出码/CPU | 本文 §6 |
| `_assert_real_output` | 842 | predictions 来源/metrics-only/fit/infer | 本文 §6 |
| `_compare_predictions` | 857 | 行集/bit-exact（随机性只对原种子） | 本文 §5 |
| `_compare_metrics` | 908 | 确定性 bit-exact / 随机性 TOST | 本文 §5 |
| `_compare_artifacts` | 956 | 缺失/多出/哈希不符 | 本文 §5 |
| `_attribute` | 980 | 构造四因子 + 随机性证据并调用归因 | 本文 §7 |
| `_t_critical_95` | 1043 | df=4..30 查表；>30 正态近似 | 本文 §5 |
| `tost_equivalence` | 1050 | 90% CI 落在 ±margin 内 | 策划书 §9.4 |
| `_parse_utc` | 1100 | RFC3339 UTC 解析（Z 与 +00:00 等价） | 本文 §3.3/§6 |
| `_is_within` | 1109 | 纯路径包含判断 | 本文 §6 |
| `assert_l3_boundary` | 1119 | 允许清单无原产物、结果无 VERIFIED | AGENTS §4 |

`l3_sandbox.py`、`attribution.py` ≤800 行，无需索引。

## 3. 沙箱：新目录、只读白名单、独立进程

### 3.1 只读白名单（唯一判据）

`SandboxPolicy.is_read_allowed(relative_path)` 只做一件事：路径是否命中 `READONLY_ALLOWLIST`。
未命中即拒绝，**没有黑名单分支**。允许九类：

| 逻辑名 | 允许路径模式 | 用途 |
|---|---|---|
| `dataset` | `datasets/*/*.csv`、`datasets/*/*.json` | 原始数据字节（只读） |
| `dataset_binding` | `inputs/dataset_binding.json` | 数据登记/哈希声明 |
| `code_snapshot` | `code/*/*.py`、`code/*/*.json` | 代码快照 |
| `config_snapshot` | `config/*/*.json`、`config/*/*.yaml` | 配置快照 |
| `dependency_lock` | `deps/requirements.lock` | 依赖锁 |
| `split_manifest` | `inputs/split_manifest.json` | 六字段划分清单 |
| `ruleset` | `inputs/ruleset.json` | 规则版本 |
| `task_spec` | `inputs/task_spec.json` | 任务声明 |
| `graph` | `inputs/graph.json` | 任务图 |

### 3.2 L3 禁止读取的路径清单（文档与负例）

以下路径不在允许清单内，因此默认拒绝：

1. 原运行 attempt 目录的 `artifacts/`、`logs/`、`tmp/`；
2. 原运行 `metrics.json`、`predictions.csv`、`run_summary.json`、`leakage_report.json`；
3. 任何模型二进制（`.pkl/.joblib/.dill`）与结果目录；
4. Evidence Store 数据库、payload sidecar、证据包导出目录；
5. Executor 工作区 `tasks/<task>/nodes/<node>/attempts/<attempt>`；
6. 其它 L3 run 目录、Verifier 私有报告/密钥目录；
7. 用户主目录/桌面/下载/系统临时目录中的任意文件；
8. UNC/网络路径、`http(s)://`、`file://`。

机制是允许清单；上面这份是**文档与负例目标**，不是让实现去匹配黑名单。
`assert_sandbox_boundary()` 检查模块没有 `deny`/`blacklist`/`allow_all` 入口。

### 3.3 独立进程

- `ProcessSpec`：`argv` 绝对解释器 + `-I -B -m <entrypoint>`；`shell=False`；`close_fds=True`；
  `stdin=DEVNULL`；stdout/stderr 落 `<sandbox>/logs/`；cwd=`<sandbox>/work/<seed>`。
- 环境只来自 `environment_allowlist()`：`PYTHONHASHSEED=0`、`TZ=UTC`、`LC_ALL=C`、
  `OMP/OPENBLAS/MKL/NUMEXPR_NUM_THREADS=1`、`RF_L3_RUN_ID`；不继承 `PYTHONPATH`/代理/凭据。
- `assert_process_isolated()`：PID ≠ Executor PID；parent ≠ Executor PID；cwd 在沙箱内；
  sandbox_root 与本沙箱一致；解释器哈希等于基线；启动时间不早于沙箱创建。
- **边界声明**：这是目录/进程隔离，不是 OS 沙箱；不设 ACL、不建受限用户、不承诺阻断同机 root。

## 4. 重放流程（9.3）

1. `_assert_original_baseline`：把 `expected_predictions/metrics/artifacts` 回绑到
   `OriginalRunRef.predictions_hash/metrics_hash/artifact_hashes`；不符即
   `BUNDLE_TAMPERED` / `ORIGINAL_BASELINE_MISMATCH`，在创建沙箱前 fail-closed。
2. `_assert_preconditions`：dataset_hash ↔ Split Manifest；code/config 快照哈希；
   ruleset_hash、环境指纹、依赖锁分别与原运行一致；`plan_hash` 重算；计划预冻结；
   种子在预注册集合内；Split Manifest 六字段复核。
3. `plan_sandbox()`：新 `l3_<32hex>` 目录，`exist_ok=False`，记录 `(st_dev, st_ino)`。
4. 对每个种子：`build_process_spec` → `ProcessRunnerPort.run`（新进程）→ `_assert_process`
   → `SandboxAudit.assert_clean` → `_assert_real_output`。
5. 比较：`_compare_predictions`、`_compare_metrics`、`_compare_artifacts`、
   `SplitVerifierPort.verify`。
6. 归因：`_attribute` 构造规则/数据/代码/环境四因子 + 随机性证据，调用 `attribution.attribute`。
7. 生成 `L3ReplayResult`；`assert_no_fake_l3()` 再查一遍；`to_attestation()` 产出 Gate 物证。

**关键边界**：比较在 Verifier 进程完成，不在沙箱进程内完成。沙箱进程读不到原
predictions/metrics；否则它可以把原预测复制出来冒充重跑。

## 5. 等价性（9.4 写死）

### 5.1 确定性模式

- `seeds` 恰好 1 个（原运行 seed），`margin=0`；
- 预测（含 scores）逐 float64 位相同；指标逐 float64 位相同；
- Split Manifest 哈希相同；确定性产物哈希相同；
- 不一致 → FAIL + 归因；**不得**归因为随机性。

### 5.2 随机性模式

- `seeds` ≥5 个、唯一、预注册；`margin>0`；`alpha=0.05`；
- `plan_hash` 必须在首次重跑前冻结；晚于重跑 → `EQUIVALENCE_PLAN_NOT_PRE_FROZEN`；
- 每个指标对 `seed_value - original` 做 TOST：90% CI 必须落在 `(-margin, +margin)`；
  边界严格不等号；
- 报告每种子值、均值、标准差、CI；不接受“跑 2 次看起来差不多”。

### 5.3 k 次 bit-exact 的表述

k 次 bit-exact 只是**限定条件下的经验资格**，不是数学确定性证明；不得写成“绝对可复现”。

## 6. 伪 L3 的判定点

| 伪 L3 | 判定点 | 拒绝码 |
|---|---|---|
| 只重算指标 | `SandboxRunOutput.metrics_only=True` / 无新 predictions / RETRAIN 无 fit | `L3_METRICS_ONLY` / `L3_NO_MODEL_FIT` |
| 只重读 predictions | 允许清单不含 predictions；audit 出现原产物读取 | `L3_READ_ORIGINAL_ARTIFACTS` |
| 原目录重跑 | `ProcessIdentity.cwd` 在原 attempt 目录内 | `L3_ORIGINAL_DIR_RERUN` |
| 复用 Executor 进程 | `pid == executor_pid` 或 `parent_pid == executor_pid` | `L3_SAME_PID` / `L3_PARENT_IS_EXECUTOR` |
| 没有新进程 | `processes=()` / `predictions_source != "sandbox_run"` | `L3_NO_NEW_PROCESS` / `L3_READS_ORIGINAL_PREDICTIONS` |
| 复制原预测 | 无 fit/infer 计数但 predictions 与原值相同 | `L3_NO_MODEL_FIT` / `L3_NO_INFERENCE` |
| 少种子 | STOCHASTIC 且 `len(seeds)<5` | `L3_INSUFFICIENT_SEEDS` |
| 计划后冻结 | `frozen_at > started_at` | `EQUIVALENCE_PLAN_NOT_PRE_FROZEN` |

## 7. 六类归因

| 类别 | 机器判据 | 置信 |
|---|---|---|
| 环境 | 环境指纹组成项/依赖锁/Python 版本任一不同 | HIGH（单因子）/MEDIUM（多因子） |
| 数据 | dataset_hash、row_id_hash、fold_assignment_hash、行数/标签任一不同 | HIGH |
| 代码 | code_hash、config_hash、template_version、parameters_hash 任一不同 | HIGH |
| 随机性 | 同环境/数据/代码 + 随机性模式 + ≥5 预注册种子 + 方差落在等价边界内 | MEDIUM |
| 规则 | ruleset_hash、指标定义、等价性计划哈希任一不同 | HIGH |
| 未知 | 以上因子全部一致（或无法判定），仍无法解释差异 | LOW；必须人工复核 |

优先级：`规则 > 数据 > 代码 > 环境 > 随机性 > 未知`。多因子同时不一致 → primary 最高优先级，
其余进 contributors，置信 MEDIUM，要求人工复核。确定性模式下所有已知因子一致但输出不同 →
UNKNOWN（HIGH），明确“随机性被排除”，不得归因 RANDOMNESS。

**前置不符 vs 重跑后归因**：数据/代码/环境/规则的前置哈希不符时，`_assert_preconditions`
直接 fail-closed（不在错误前提下重跑）；六类归因用于“通过前置后仍出现的差异”（随机性、
运行中漂移、未知），也作为独立单元供其它调用方使用。不得把“前置不符被拒”写成“已归因”。

## 8. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| L3 新目录/独立进程/真实重跑 | `SandboxPlan`/`ProcessSpec`/`L3Replayer.run`；本文 §3/§4 | 已定义，未执行 |
| 只读清单是白名单 | `READONLY_ALLOWLIST`；`is_read_allowed()` 默认拒绝；本文 §3.1 | 已定义，未执行 |
| 伪 L3 六类拒绝 | `assert_no_fake_l3()`；`_assert_process`；`_assert_real_output`；本文 §6 | 已定义，未执行 |
| 确定性 bit-exact | `_compare_predictions`/`_compare_metrics`；`bit_identical` | 已定义，未执行 |
| 随机性 ≥5 种子 + TOST + 预冻结 | `EquivalencePlan`/`tost_equivalence`/`assert_pre_frozen` | 已定义，未执行 |
| 六类归因 | `attribution.attribute`；本文 §7 | 已定义，未执行 |
| 负例覆盖六类场景 | `M10_verifier_l3/NEGATIVE_TESTS.md` | 判据已定义，未执行 |

## 9. OPEN QUESTIONS（详见 `design/pseudocode/OPEN_QUESTIONS.md`）

| 编号 | 问题 | P5 临时处理 |
|---|---|---|
| `OQ-P5-04` | E3 写入路径仍受 OQ-P4-01 阻塞 | L3 产出 attestation；E3 由 Verifier 写入，P6 前不实现 |
| `OQ-P5-05` | L3 读取拒绝无专用错误码 | 用 `TOOL_NOT_ALLOWLISTED`(403) + `reason=L3_READ_OUTSIDE_ALLOWLIST` |
| `OQ-P5-06` | Windows 无“只读挂载” | 只读 open + 运行前后哈希；残余风险登记 |
| `OQ-P5-07` | BLAS/线程导致浮点不确定 | 沙箱固定线程=1；要求环境指纹包含线程变量 |
| `OQ-P5-12` | TOST 的 margin 由谁预注册、如何审计 | `EquivalencePlan.margin` + `plan_hash`；审计流程待定 |

## 10. 本阶段不做

- 不做签名/证书/信任锚/离线验签（P6）。
- 不做验证预算/VAS（P9）。
- 不承诺跨环境普遍复现；L3 只支持同环境独立重执行。
- 不建库、不跑测试、不写业务代码。