# A-02 收口报告：中断/重启安全接手

> 日期：2026-11-15（Asia/Shanghai）
> 依据：`docs/goals/GOAL_01_CORE_BACKEND.md:140`、`docs/PRD/03_PRD_T0.md:105`（US-T0-20）、`reports/t0_review_20261114/REVIEW.md` A-02。

## 1. 修复前行为（真实复现）

用真实执行 → 验证 → `mark_nodes_verified` 后删除一条 evidence payload，使证据链变为 `CHAIN_PAYLOAD_MISSING`，再调用 `RecoveryService.invalidate()`。修复前它**继续执行**：两个节点转 `INVALIDATED`、写入 2 条 `RECOVERY_PLAN_FROZEN`、生成计划文件。说明“证据链未经校验时拒绝恢复调度”在当时不成立。

该复现输出见本目录 [`probe_report.json`](probe_report.json) 的 `pre-fix` 用例（`simulated_pre_fix=true`，monkeypatch 移除新增的 L1 前置校验以复现代码路径）；修复前的实际运行也在本会话中直接观察到（`INVALIDATE PROCEEDED`，states INVALIDATED，freeze rows 2）。这里不伪造历史时间戳。

## 2. 修复内容

| 文件 | 变更 |
|---|---|
| `researchflow/recovery/service.py` | 新增 `RecoveryService._require_valid_evidence(task_id)`：只读 `load_context()` + `L1Verifier().run(ctx)`；`L1 != PASS` 时抛 `RecoveryError("RECOVERY_NOT_SAFE", "L1 precheck failed before recovery: <具体 L1 code/detail>")` |
| 同上 | `invalidate()` 在 ruleset 校验后、任何状态迁移/计划写入前调用；`rerun()` 在计划读取/归属校验后、任何 READY/RUNNING 迁移或执行前调用 |
| `tests/t0/test_wp_restart_safety.py` | 新增 4 条测试：真实 kill/restart、坏链拒绝 invalidate、缺失 attempt 结果拒绝 invalidate、坏链拒绝 rerun |
| `tests/t0/restart_probe.py` | 独立只读重启检查进程：SQLite `mode=ro`、attempt 目录、残留 python 进程 |

未新增状态边、未实现 T1 Recovery、未新增公共 `/recover` 路由、未修改冻结契约或数据库迁移。错误码沿用冻结的 `RECOVERY_NOT_SAFE`（409）；具体原因写入 detail，包含 `L1_CHAIN_PAYLOAD_MISSING` / `L1_ATTEMPT_RESULT_MISSING`。

## 3. 修复后证据

### 3.1 敏感度探针

命令：

```powershell
$rfPy = 'D:\ResearchFlow-project\.venv\Scripts\python.exe'
& $rfPy -B docs/verification/t0/a-02/recovery_chain_probe.py
```

[`probe_report.json`](probe_report.json)，2026-11-15T02:14:35Z，41.393 s，exit 0，`verdict=PASS`：

| 场景 | pre-fix 模拟 | post-fix |
|---|---|---|
| 坏链后 invalidate | PROCEEDED（2 条冻结） | **REFUSED** `RECOVERY_NOT_SAFE`，detail 含 `L1_CHAIN_PAYLOAD_MISSING`；节点仍 `VERIFIED`；freeze=0 |
| 删除 split `result.json` 后 invalidate | PROCEEDED | **REFUSED** `RECOVERY_NOT_SAFE`，detail 含 `L1_ATTEMPT_RESULT_MISSING`；节点仍 `VERIFIED`；freeze=0 |
| 有效失效后坏链 rerun | — | **REFUSED** `RECOVERY_NOT_SAFE`，detail 含 `L1_CHAIN_PAYLOAD_MISSING`；节点仍 `INVALIDATED`；无 `attempt_02` 目录 |

### 3.2 真实 kill/restart 测试

`tests/t0/test_wp_restart_safety.py::test_kill_restart_keeps_running_and_issues_no_certificate`：

1. 用项目解释器启动独立产品进程 `python -B -m researchflow.cli run-task --db ... --task ...`。
2. 轮询真实 SQLite，在“split attempt 已完成、train attempt `RUNNING` 且 `job.json` 存在、`result.json` 不存在”的检查点用 `taskkill /F /T` 杀掉整棵进程树。
3. 新进程 `tests/t0/restart_probe.py` 以 `mode=ro` 重读数据库与 attempt 目录，枚举残留 python 进程；断言：
   - task 仍 `RUNNING`，未变 `COMPLETED`；
   - `reports=0`、`certificates=0`；
   - evidence_count > 0，链在中断点仍完整；
   - split attempt 有 result，被中断的 train attempt 无 result；
   - `live_task_processes=[]`。
4. 第二个独立产品进程：真实 API `serve` 重新读取同一 SQLite。`GET /task` 为 `RUNNING`；`GET /graph` 中被中断节点为 `RUNNING`；`GET /evidence` 链 OK；`GET /report` 404；`GET /certificate` 409 `CERTIFICATE_NOT_AVAILABLE`；`POST /verify` 409 `STATE_TRANSITION_DENIED`，消息要求 `VERIFYING`。
5. 再次运行 probe：仍 `RUNNING`，reports/certificates 仍为 0，无残留任务进程。

### 3.3 测试日志

| 检查 | 结果 | 证据 |
|---|---|---|
| A-02 专项 | `4 passed in 31.24s`，exit 0 | [`pytest_restart.log`](pytest_restart.log) |
| 恢复/API 回归 | `11 passed in 65.28s`，exit 0 | [`pytest_regression.log`](pytest_regression.log) |
| 全量 | `351 passed in 395.66s`，exit 0 | `docs/verification/t0/full_suite_2026-11-15.log` |
| 新三次 e2e | `consistent=true`，三次 VERIFIED | `docs/verification/t0/e2e/` |

## 4. 结论与边界

A-02 的必需验收缺口已补齐：有真实进程中断、半完成 attempt、独立新进程重读、`RUNNING` 不被默认完成、不重复签发、坏链/缺失 attempt 证据时恢复拒绝及具体原因。拒绝发生在任何状态迁移或执行之前，且不引入 T1 完整 Recovery 状态机。

本报告不把“缺少测试”改写成“曾经发生错误恢复”；修复前实际观察到的是**恢复调度未校验证据链而继续**，未观察到错误签发证书或数据损坏。