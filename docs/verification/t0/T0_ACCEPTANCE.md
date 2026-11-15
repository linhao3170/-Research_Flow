# T0 验收记录（2026-11-15）

> 验收对象：ResearchFlow T0 可信后端闭环 + 最小工作台 + 三次离线端到端与独立验签。
> 验收来源：用户 2026-11-15 在当前 DSH 会话中明确选择“**验收 T0，暂不 commit**”。
> 性质：T0 阶段验收记录。不表示 commit 已授权、不表示完整 G6 已通过、不表示 T1 已启动。

## 1. 验收结论

**T0 通过验收。** 依据：

- A-01 参数完整性漏检已修复并验证：L1/L3 交叉核对 job/NodeSpec/E2；split/train 负例均以具体原因拒绝；L3 拒绝时无目录、无子进程。
- A-02 中断/重启安全接手已补齐：真实 `taskkill /T` 中断、独立新进程重读、`RUNNING` 不默认 `COMPLETED`、0 报告/0 凭证、无残留进程；坏链/缺失 attempt 证据时恢复拒绝。
- A-03 WP-13 正式裁决与材料已收口：用户批准 ADR-007 三个边界；四视图截图、DOM 快照、walkthrough 与工作台测试齐全。
- 修复后三次隔离 e2e 一致，三次离线验签 `VERIFIED`；全量 351 passed；契约/状态/文档检查有真实日志。

## 2. 验收时的真实验证

| 检查 | 命令 | 结果 | 证据 |
|---|---|---|---|
| 全量回归 | `& .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider` | **351 passed**，395.66 s，exit 0 | [`full_suite_2026-11-15.log`](full_suite_2026-11-15.log) |
| A-01 定向 | `pytest tests/t0/test_wp09_verifier_l12.py tests/t0/test_wp10_verifier_l3.py` | 26 passed，exit 0 | [`a-01/pytest_targeted.log`](a-01/pytest_targeted.log) |
| A-01 探针 | `python -B docs/verification/t0/a-01/parameter_binding_probe.py` | `verdict=PASS`，exit 0 | [`a-01/probe_report.json`](a-01/probe_report.json) |
| A-02 专项 | `pytest tests/t0/test_wp_restart_safety.py` | 4 passed，exit 0 | [`a-02/pytest_restart.log`](a-02/pytest_restart.log) |
| A-02 回归 | `pytest tests/t0/test_wp_recovery.py tests/t0/test_wp_api.py` | 11 passed，exit 0 | [`a-02/pytest_regression.log`](a-02/pytest_regression.log) |
| A-02 探针 | `python -B docs/verification/t0/a-02/recovery_chain_probe.py` | `verdict=PASS`，exit 0 | [`a-02/probe_report.json`](a-02/probe_report.json) |
| WP-13 | `pytest tests/t0/test_wp13_workbench.py` | 4 passed，exit 0 | [`wp-13/pytest_2026-11-15.log`](wp-13/pytest_2026-11-15.log) |
| WP-13 截图 | `python -B docs/verification/t0/wp-13/capture_screenshots.py` | `verdict=PASS`，exit 0 | [`wp-13/screenshots.json`](wp-13/screenshots.json) |
| 三次 e2e | `python -B scripts/e2e_run.py --runs 3 --out docs/verification/t0/e2e` | `consistent=true`；三次 32 证据/16 失效、必检 8/8、L3 1.0 | [`e2e/runs_summary.json`](e2e/runs_summary.json)、[`e2e/e2e_report.md`](e2e/e2e_report.md) |
| 离线验签 | `verify_bundle.py -E --bundle ... --trust-store <包外>` ×3 | 三次 `VERIFIED`，exit 0 | [`g6-t0/2026-11-15/`](g6-t0/2026-11-15/) |
| 契约 | `validate_contracts.py --selftest` / 默认 | 10/10、72/72，exit 0 | 本会话输出 |
| 状态/文档 | `state_sync.py validate/render/check`；`check_docs_drift.py` | 均 exit 0；ERROR=0/WARNING=1（`last_verified_commit` 与 HEAD 差异，已知） | 生成状态文档、本会话输出 |

## 3. 验收范围

**包含：**

- FR-001–FR-009 的 T0 后端能力；FR-010 的 T0 最小切片（失效传播、确定性计划冻结、三条件守卫、保守重跑）。
- L1/L2/L3 独立验证、Gate、Collector 证据链、Ed25519 报告/凭证、Evidence Bundle、独立 `verify_bundle.py`。
- 最小 Workbench 四视图（用户 2026-11-15 批准的三个边界）。
- 三次隔离 e2e、无模型/断网意图、离线验签、并发/内存实测的既有证据。

**不包含：**

- 完整 G6 五类负例矩阵（T1）；G4/G5/G7（T1/T2）；T1 完整 Recovery、动态调度、六角色、KB/FOL、DC/SPA、VAS、RF-Bench、Harness 产品适配。
- commit、GitHub 推送、T1 启动；这些需用户另行授权。
- 分页、报告下载、失效原因展示；需另立冻结 REST 契约方案。
- OS 级断网、跨机 L3、任意启动方式的安全加固；按已披露边界处理。

## 4. 验收时仍开放的风险/限制

1. `BLK-003` 仍 OPEN：全部测试在 `danger-full-access` 下运行，不写成 workspace-write 通过。
2. `verify_bundle.py` 对 `coverage.missing` 算术与证书 `l3_coverage` 跨对象一致性未完整复核（B 类）；未发现正常签发路径生成坏对象。
3. `researchflow/api/app.py` 仍暴露模块级 `app`，直接交给 ASGI 服务器绑定非回环地址可绕开 `serve()` 守卫；T0 演示只使用回环 CLI 启动，进入 T1 前单独收口。
4. 断网为“代码无外呼 + 代理黑洞 + 无模型客户端”，非 OS 级断网；L3 与执行器共用同一解释器安装，隔离级别为“新目录 + 独立进程 + 原始数据重训”，非跨机。
5. 预算：开发 API 200 元 / 产品调试 API 50 元的实际余额未核实，未按 0 元记账；后续按 `docs/verification/budget/` 核账。
6. 工作台证据单页 `limit=200`；超过 200 条时不自动分页（已批准边界）。

## 5. 验收后的下一步

1. **commit 作为单独事项**：用户另行授权后，先核对 Git 身份、具体文件清单、忽略规则与是否混入历史未验收产物，再提交；不盲目全目录暂存，不把运行私钥纳入提交。
2. GitHub 仓库目标、可见性与推送范围另行明确。
3. T1 是否启动由用户决定；本验收不自动进入 Goal 2。
4. 预算余额核实并回填账本。

## 6. 关联记录

- 复核输入：[`reports/t0_review_20261114/REVIEW.md`](../../../reports/t0_review_20261114/REVIEW.md)
- 收口复核：[`review_2026-11-15.md`](review_2026-11-15.md)
- A-01：[`a-01/summary.md`](a-01/summary.md)
- A-02：[`a-02/summary.md`](a-02/summary.md)
- A-03：[`wp-13/ADR-007_DECISION.md`](wp-13/ADR-007_DECISION.md)、[`wp-13/walkthrough.md`](wp-13/walkthrough.md)
- ADR-007：`docs/ADR/ADR-007-t0-workbench-scope.md`（ACCEPTED）
- 状态：`docs/state/project_state.json`（`T-T0-ACCEPT-001` DONE）