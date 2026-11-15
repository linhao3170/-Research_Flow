# A-01 收口报告：参数完整性绑定

> 日期：2026-11-15（Asia/Shanghai）
> 依据：`reports/t0_review_20261114/REVIEW.md` A-01、`docs/goals/GOAL_01_CORE_BACKEND.md:140`、`docs/design/05_CONTRACTS_AND_STATES.md` §3.1。
> 方案：[`docs/plans/A-01_PARAMETER_BINDING_PLAN.md`](../../../plans/A-01_PARAMETER_BINDING_PLAN.md)。

## 1. 修复内容

| 文件 | 变更 |
|---|---|
| `researchflow/verification/context.py` | 新增 `ParameterBinding` 与 `VerificationContext.parameter_binding()`：对当前 attempt 交叉核对 NodeSpec `parameters_hash`、`job.json.parameters_hash`、`hash_payload(job.parameters)`、`result.json.parameters_hash`、E2 `executor_launch.parameters_hash`；缺失记 `PARAMETERS_BINDING_MISSING`，不一致记 `PARAMETERS_HASH_MISMATCH` |
| `researchflow/verification/l1.py` | 当前 attempt 增加绑定检查；新原因码 `L1_PARAMETERS_BINDING_MISMATCH` / `L1_PARAMETERS_BINDING_INCOMPLETE` |
| `researchflow/verification/l3.py` | 在任何验证目录/子进程创建前 preflight split + 全部 metric 节点；失败返回 `L3Result(status=FAIL, coverage=0.0, nodes=(), verification_root="")`，原因码 `L3_PARAMETERS_BINDING_MISMATCH` / `L3_PARAMETERS_BINDING_INCOMPLETE`；删除 E2 launch 缺失时回退 `TaskSpec.parameters` 的分支 |
| `tests/t0/test_wp09_verifier_l12.py` | 新增 5 条负例：train/split 篡改、声明哈希未更新、E2 绑定缺失 |
| `tests/t0/test_wp10_verifier_l3.py` | 新增 3 条负例：train/split 篡改在启动前拒绝、E2 绑定缺失；断言无 L3 目录、无子进程 |
| `tests/t0/support.py` | 新增 `tamper_job_parameters()` 测试辅助 |

未修改 `contracts/**`、G0 冻结设计、数据库 Schema/迁移、Gate 规则、Executor/Collector 写哈希逻辑、状态迁移表。新原因码只出现在 `VerificationReport.gaps`/`L3Result.issues`，不新增 13 个冻结 API 错误码。

## 2. 修复前后证据

### 2.1 真实敏感度探针（含 pre-fix 模拟）

命令：

```powershell
$rfPy = 'D:\ResearchFlow-project\.venv\Scripts\python.exe'
& $rfPy -B docs/verification/t0/a-01/parameter_binding_probe.py
```

结果（[`probe_report.json`](probe_report.json)，2026-11-15T02:14:00Z，8.435 s，exit 0，`verdict=PASS`）：

| 阶段 | L1 | L3 | 说明 |
|---|---|---|---|
| pre-fix 模拟（信任 `job.json`，即移除检查的代码路径） | PASS | PASS，coverage 1.0，1 个节点，真实子进程 | 与 2026-11-14 复核报告的真实复现一致 |
| post-fix | **FAIL**，`L1_PARAMETERS_BINDING_MISMATCH` ×2 | **FAIL**，`L3_PARAMETERS_BINDING_MISMATCH` ×2，coverage 0，`nodes=()`，`processes=()`，`verification_root=""` | 未创建 L3 目录；`no_replay_side_effect=true` |

关键哈希：

- 原 job / NodeSpec / E2：`3cb72d132033aad0acfdbdd1029c30152b0fb5ed3504faf267c99f82684fef8a`
- 篡改后（seed 42→43，并重算声明哈希）：`45dc0c40aff877d53b56e4145bf7eb906fa7ac53155134e7183f831fba9b754d`
- `job_bytes_changed=true`；`nodespec_parameters_hash` 与 `e2_launch_parameters_hash` 均为原值。

pre-fix 行为由 monkeypatch `VerificationContext.parameter_binding` 为“信任 job”复现，明确标注 `simulated=true`；它不是对旧二进制的重跑。真实的旧行为另见 `reports/t0_review_20261114/run_345e8a5b/probe_report.json`（旧报告保留，不覆盖）。

### 2.2 定向测试

```powershell
& $rfPy -m pytest tests/t0/test_wp09_verifier_l12.py tests/t0/test_wp10_verifier_l3.py -q -p no:cacheprovider
```

结果：`26 passed`，exit 0，126.91 s；日志 [`pytest_targeted.log`](pytest_targeted.log)。修改前同一组 19 项基线为 `19 passed`。

### 2.3 正常执行/恢复回归

- `tests/t0/test_wp10_verifier_l3.py::test_l3_replays_from_raw_data_in_separate_processes` 通过。
- `tests/t0/test_wp_recovery.py::test_full_recovery_rerun_and_offline_bundle` 通过：attempt_02 的 job/result/E2 参数哈希仍与 NodeSpec 一致，绑定检查未误拒正常恢复。
- 全量：`351 passed in 395.66s`，exit 0，日志 `docs/verification/t0/full_suite_2026-11-15.log`。
- 三次新 e2e：`consistent=true`，三次均 32 证据 / 16 失效 / 必检 8/8 / L3 覆盖 1.0 / 离线验签 VERIFIED。

## 3. 结论

A-01 的参数完整性漏检已修复：L1 与 L3 都会在复跑前以具体原因拒绝 job 参数与 NodeSpec/E2 不一致的 attempt；L3 在拒绝时不创建目录、不启动子进程。正常执行与恢复重跑不受影响。**该结论不替代 A-03 的 ADR 裁决，也不单独宣布 T0 全部完成。**