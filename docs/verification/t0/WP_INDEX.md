# T0 工作包证据索引（WP-04 – WP-14、WP-R）

> 日期：2026-11-15（A-01/A-02/A-03 收口后）。所有结果均来自本机真实运行；权限为会话 `danger-full-access`，不写成 workspace-write 通过。
> 解释器统一为 `D:\ResearchFlow-project\.venv\Scripts\python.exe`（3.11.16 / 64bit）。
> 实现层决策与偏离见 [00_implementation_decisions.md](00_implementation_decisions.md)；独立审查与 A/B/C 处置见 [review_2026-11-14.md](review_2026-11-14.md)。
> 2026-11-15 修复了 A-01 参数绑定与 A-02 恢复前证据校验；修复前 e2e 已归档到 [e2e/superseded_2026-11-15_pre_a01/](e2e/superseded_2026-11-15_pre_a01/SUPERSEDED_NOTICE.md)，旧证据未删除。

| WP | 状态 | 交付 | 真实测试证据 | 关键负例（断言原因） |
|---|---|---|---|---|
| 03 | DONE | SQLite 7 表、StateMachine、双事务审计 | [wp-03/pytest_targeted_2026-11-14.log](wp-03/pytest_targeted_2026-11-14.log)、[wp-03/pytest_full_2026-11-14.log](wp-03/pytest_full_2026-11-14.log)、[wp-03/acceptance_2026-11-14.md](wp-03/acceptance_2026-11-14.md) | 见 WP-03 验收表 |
| 04 | DONE | `researchflow/dag/`、迁移 0002/0003、`GET /graph` | [wp-04/pytest.log](wp-04/pytest.log)（15 passed） | 环/自依赖/重复边/缺依赖/孤立/超规模/未知模板/数据哈希不符/非法参数，均断言错误码与 field_path |
| 05 | DONE | 内置合成数据（CC0-1.0）、模板注册表、参数校验、Split Manifest、规则集 | [wp-05/pytest.log](wp-05/pytest.log)（15 passed） | 未注册模板、未知参数、非法模型、seed 类型、URI 逃逸、哈希不符、R1–R5 泄漏规则 |
| 06 | DONE | `researchflow/execution/`（子进程、进程树超时回收、进程树内存采样、产物哈希、输入拷贝） | [wp-06/pytest.log](wp-06/pytest.log)（10 passed，含 200 MB 校准与真实内存终止） | 非白名单模板、attempt 目录复用、超时 TIMEOUT、内存上限、越界输入名、worker 错误透传 |
| 07 | DONE | `researchflow/evidence/`（单调序号、链、幂等、内容冲突、payload 存储） | [wp-07/pytest.log](wp-07/pytest.log)（9 passed） | 重复投递不新增行、同键异内容 DENIED、缺口/链哈希/prev/载荷篡改、E0 不推进状态、E3 能力隔离 |
| 08 | DONE | `researchflow/gate/`、`ruleset.v1.json` | [wp-08/pytest.log](wp-08/pytest.log)（14 passed） | 缺 E3、E3 FAIL/未绑定 split、E0 冒充执行、stale 证据（仍存在且链有效）、缺产物、哈希篡改、链篡改、规则版本不符/规则被改弱、无图/无节点行、旧 attempt |
| 09 | DONE | L1/L2 验证器 | [wp-09/pytest.log](wp-09/pytest.log)（11 passed）；A-01 增补 [a-01/pytest_targeted.log](a-01/pytest_targeted.log)（26 passed，含 WP-10） | 产物缺失/哈希错、链缺口、result.json 缺失、指标篡改、y_true 篡改、R1/R3/R4 泄漏；**job 参数与 NodeSpec/E2 不一致（`L1_PARAMETERS_BINDING_MISMATCH`）、绑定缺失（`..._INCOMPLETE`）** |
| 10 | DONE | L3 独立重跑 | [wp-10/pytest.log](wp-10/pytest.log)（8 passed）；A-01 增补 [a-01/pytest_targeted.log](a-01/pytest_targeted.log)（26 passed，含 WP-09） | 执行器目录复用、进程内状态、执行器产物作输入、指标/预测篡改、缺执行器产物；L3 目录/进程/Split 输入均独立；**split/train 参数篡改在创建目录/子进程前以 `L3_PARAMETERS_BINDING_MISMATCH` 拒绝，绑定缺失以 `..._INCOMPLETE` 拒绝** |
| 11 | DONE | Ed25519 + JCS 载荷白名单 + Merkle | [wp-11/pytest.log](wp-11/pytest.log)（9 passed） | RFC 8032 向量、改载荷/换密钥/域分离错配、未知 MAJOR、VERIFIED+缺口被契约拒绝、skipped_nodes 非空被拒 |
| 12 | DONE | Bundle 导出 + 独立 `verify_bundle.py` | [wp-12/pytest.log](wp-12/pytest.log)（11 passed） | 缺文件、篡改载荷、manifest 签名、信任锚在包内、错误信任锚、报告签名、Merkle 不符、失败报告无凭证、私钥不入包、隔离目录运行 |
| 13 | DONE | Streamlit 四视图工作台 | [wp-13/pytest_2026-11-15.log](wp-13/pytest_2026-11-15.log)（4 passed）；[wp-13/screenshots.json](wp-13/screenshots.json)（`verdict=PASS`）；[wp-13/walkthrough.md](wp-13/walkthrough.md) | 真实 API 数据渲染；API 不可达时报错而非造数据；源码只读检查；**失效后证据显示 STALE 标记（新增 AppTest）**；ADR-007 仍待正式裁决，见 [wp-13/ADR-007_DECISION_PROPOSAL.md](wp-13/ADR-007_DECISION_PROPOSAL.md) |
| R | DONE | 失效传播、确定性计划、三条件守卫、保守重跑 | [wp-r/pytest.log](wp-r/pytest.log)（6 passed）；A-02 增补 [a-02/pytest_restart.log](a-02/pytest_restart.log)（4 passed）、[a-02/pytest_regression.log](a-02/pytest_regression.log)（11 passed） | 同输入同 plan_hash、重复失效同哈希、无关节点不失效、计划缺失/哈希不符/未冻结/冻结晚于重跑四条 DENIED、包内 stale 证据不放行；**坏链/缺失 attempt 结果时 invalidate 与坏链时 rerun 以 `RECOVERY_NOT_SAFE` + 具体 `L1_*` 原因拒绝** |
| 14 | DONE | 三次隔离 e2e + 独立验签 + 并发/内存实测 | [e2e/runs_summary.json](e2e/runs_summary.json)（2026-11-15，`consistent=true`）、[e2e/e2e_report.md](e2e/e2e_report.md)、[e2e/concurrency.json](e2e/concurrency.json)、[g6-t0/2026-11-15/](g6-t0/2026-11-15/) | 三次运行一致（32 证据 / 16 失效 / 8/8 / L3 1.0）；三次离线验签 exit 0、`VERIFIED`；篡改类负例见 WP-12 |
| A-01 | DONE | 参数完整性绑定（L1/L3 preflight） | [a-01/summary.md](a-01/summary.md)、[a-01/probe_report.json](a-01/probe_report.json)、[a-01/pytest_targeted.log](a-01/pytest_targeted.log) | pre-fix 模拟三层 PASS；post-fix L1/L3 具体绑定原因拒绝，L3 无目录/子进程副作用 |
| A-02 | DONE | 中断/重启安全接手与恢复前证据校验 | [a-02/summary.md](a-02/summary.md)、[a-02/probe_report.json](a-02/probe_report.json)、[a-02/pytest_restart.log](a-02/pytest_restart.log)、[a-02/pytest_regression.log](a-02/pytest_regression.log) | kill/restart 后 RUNNING 不默认 COMPLETED、0 报告/0 凭证、无残留进程；坏链/缺失证据恢复拒绝 |
| A-03 | DONE | WP-13 四视图截图 + walkthrough + ADR-007 正式裁决 | [wp-13/walkthrough.md](wp-13/walkthrough.md)、[wp-13/screenshots.json](wp-13/screenshots.json)、[wp-13/ADR-007_DECISION.md](wp-13/ADR-007_DECISION.md) | 四视图 + API 不可达截图；DOM 断言通过；用户 2026-11-15 批准 ADR-007 三个边界，ADR-007 `ACCEPTED` |
| T0 验收 | DONE | 用户 2026-11-15 接受 T0（暂不 commit） | [T0_ACCEPTANCE.md](T0_ACCEPTANCE.md)、[review_2026-11-15.md](review_2026-11-15.md) | A-01/A-02/A-03 收口；351 passed；三次 e2e + 三次离线验签；commit/T1 另行授权 |

## 覆盖与门禁映射

- G1（纵向闭环）：`e2e/run_1..3/` 全部 `COMPLETED` + `VERIFIED`，覆盖 8/8，L3 覆盖 1.0。
- G2（证据可信）：WP-07/WP-08/WP-R 负例；E0 不推进状态、stale 证据不删除且不放行、DENIED 审计回滚可见。
- G3（L3 独立重执行）：WP-10 + e2e 中的独立目录/进程/原始数据重跑。
- G6-T0：`g6-t0/` 下的包外信任锚与隔离目录验签日志；**G6 完整版属 T1，状态 JSON 记为 `IN_PROGRESS`，未提前通过**。
- 管线级验证：[pipeline_tests.log](pipeline_tests.log)（5 passed）覆盖签名报告/凭证、Merkle 根、二次 verify 不重复签发、失败不签证书。
- 全量回归：[full_suite_2026-11-15.log](full_suite_2026-11-15.log)（351 passed，395.66 s，exit 0）；历史 [full_suite_2026-11-14_final.log](full_suite_2026-11-14_final.log)（339 passed）保留。