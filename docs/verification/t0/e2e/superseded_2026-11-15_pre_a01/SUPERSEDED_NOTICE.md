# SUPERSEDED：2026-11-15 A-01/A-02 修复前的三次 e2e 证据

> 状态：**历史证据，不再作为当前 T0 出口证据**。
> 归档日期：2026-11-15（Asia/Shanghai）
> 原路径：`docs/verification/t0/e2e/{run_1,run_2,run_3,e2e_report.md,runs_summary.json}`
> 新路径：本目录。

## 为什么归档

2026-11-14 的独立复核发现两项真实缺陷，修复后可信链路代码发生变化，按复核要求重新生成三次隔离 e2e；旧证据不删除、不覆盖，整体原样移到本目录：

1. **A-01**：L3 可从执行目录 `job.json` 取到与原声明不一致的参数而仍获三层 PASS。修复后 L1/L3 在启动复跑前交叉核对 job 参数、NodeSpec 与 E2 `executor_launch.parameters_hash`。
2. **A-02**：恢复调度未先校验证据链/必要 attempt 证据。修复后 `RecoveryService.invalidate/rerun` 先运行只读 L1，坏链或缺失 attempt 结果以 `RECOVERY_NOT_SAFE` + 具体 L1 原因拒绝。
3. 工作台为 A-03 增加可重放的 `?view=` 初始标签选择与 API 超时配置；截图/走查材料在 `docs/verification/t0/wp-13/`。

## 使用边界

- 本目录的证据只对应**修复前**的代码与运行环境；不得用它证明当前实现通过。
- 旧 `run_1` 的数据库/产物被 A-03 截图脚本作为**只读副本来源**使用；副本不含私钥，原目录未被修改。
- 历史 `superseded_2026-11-14_pre_memfix/` 保持原位；其与本次归档是不同批次。
- 当前 T0 出口证据以重新生成的 `docs/verification/t0/e2e/run_1..3`、`runs_summary.json`、`e2e_report.md` 与离线验签日志为准。

## 归档前摘要（原样保留）

`runs_summary.json` 与 `e2e_report.md` 随本目录保存；其运行时间、任务 ID、证据数与验签结果未改写。