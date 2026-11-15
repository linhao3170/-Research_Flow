# Goal 1（T0 后端可信闭环）实施总计划

> 编制日期：2026-11-14（Asia/Shanghai）
> 依据：[GOAL_01_CORE_BACKEND.md](../goals/GOAL_01_CORE_BACKEND.md)、AGENTS.md、G0 冻结文档 ⑤⑥⑦、`contracts/*.schema.json`、[WP-03 裁决](../verification/t0/wp-03/00_decisions.md)
> 性质：本文件是实施导航与决策/依赖指针，不是第二份看板；研发进度唯一事实源仍是 `docs/state/project_state.json`。
> 约束：不修改 `contracts/`、G0 冻结设计、ADR、数据库结构语义；不重写 WP-01/02/03 已通过契约与代码；不自动 commit。

## 1. 起点核实（2026-11-14）

| 项 | 实测结果 | 证据 |
|---|---|---|
| 解释器 | `D:\ResearchFlow-project\.venv\Scripts\python.exe`，3.11.16，64bit | 本机 `-c` 输出 |
| Git | `main`，HEAD `309083e`；大量既有未提交改动，未清理 | `git status --short`（66 项） |
| WP-03 定向测试 | **87 passed**，exit 0，11.94s | `docs/verification/t0/wp-03/pytest_targeted_2026-11-14.log` |
| WP-03 全量测试 | **217 passed**，exit 0，16.17s | `docs/verification/t0/wp-03/pytest_full_2026-11-14.log` |
| 依赖 | `requirements.lock` 已锁定 58 包；uvicorn 0.54.0 / cryptography 50.0.2 / streamlit 1.67.0 / scikit-learn 1.9.1 均在锁内 | `requirements.lock` |
| 审批 | 会话审批策略为“不再询问”；Goal 授权在既有批准范围内自主连续实施；本计划只做冻结件范围内的落地 | 本轮 Goal 指令 |
| 环境阻塞 | `BLK-003` 仍 OPEN；本轮测试在 `danger-full-access` 下运行，不写成 workspace-write 通过 | 状态 JSON |

WP-03 结论：按真实实现与 2026-11-14 复测证据，`T-WP-03-001` 可转 `DONE`；历史 2026-11-12 的两次运行保留不改。

## 2. 需求—WP—模块—接口—测试—证据矩阵

| 需求 | WP | 新增/复用模块 | 对外接口（唯一名称） | 关键负例（断言原因） | 证据目录 |
|---|---|---|---|---|---|
| FR-002 | 04 | `researchflow/dag/builder.py`（新）、`graph_versions` 表（迁移 0002） | `build_graph(task_spec) -> GraphSpec`；`register_graph()`；`GET /tasks/{id}/graph` | 环 `DAG_CYCLE`、孤立 `DAG_ORPHAN`、重复边 `DAG_DUPLICATE_EDGE`、缺依赖 `DAG_MISSING_DEPENDENCY`、超规模 `DAG_TOO_LARGE`、同输入 graph_hash 稳定 | `wp-04/` |
| FR-004/NFR-01 | 05 | `researchflow/templates/{registry.py,dataset.py}`（新）、`researchflow/templates/data/*`（新数据） | `Registry.get(template_id)`；`dataset_fingerprint()`；Split Manifest 由 worker 产出 | 未注册模板 `TEMPLATE_NOT_REGISTERED`、非法参数 `PARAM_INVALID`（含 field_path）、数据哈希不符 `DATASET_HASH_MISMATCH`、网络 URI `DATASET_URI_INVALID`、许可缺失 | `wp-05/` |
| FR-004/NFR-06 | 06 | `researchflow/execution/{executor.py,worker.py,sampler.py,artifacts.py}`（新） | `Executor.run(node_job) -> AttemptObservation`（不含可信裁决） | 非零退出 `EXIT_CODE_NONZERO`、超时回收 `TIMEOUT_TREE_KILLED`、旧目录复用 `ATTEMPT_DIR_REUSED`、越界路径 `PATH_ESCAPE`、白名单外模板 `TOOL_NOT_ALLOWLISTED` | `wp-06/` |
| FR-005/NFR-03 | 07 | `researchflow/evidence/{collector.py,chain.py}`（新）、`ingestion_log` 表 | `Collector.append_event()`；`Collector.verify_chain()` | 同 event 不产生两条（`delivery_seq` 递增）、缺口 `CHAIN_GAP`、`prev_hash` 不符 `CHAIN_PREV_MISMATCH`、载荷篡改 `CHAIN_PAYLOAD_HASH_MISMATCH`、E0 不推进状态 | `wp-07/` |
| FR-006/NFR-02 | 08 | `researchflow/gate/{gate.py,ruleset.py}`（新）、`researchflow/rules/ruleset.v1.json` | `Gate.evaluate(task_id) -> GateResult(gaps, coverage, ruleset_hash, evidence_root)` | 缺 E2 `GAP_E2_MISSING`、缺 E3 `GAP_E3_MISSING`、规则版本不符 `RULESET_VERSION_MISMATCH`、stale 证据不满足必检 `GAP_EVIDENCE_STALE`（证据不删除）、E0/E1 冒充 E2 | `wp-08/` |
| FR-007 | 09 | `researchflow/verification/{l1.py,l2.py}`（新） | `L1.run(ctx)`；`L2.run(ctx)`；状态 `PASS/FAIL/SKIP/NOT_RUN` | 链断、产物哈希不符、指标重算不一致、预测/标签错位、泄漏五规则 R1–R5 各一条负例 | `wp-09/` |
| FR-007/G3 | 10 | `researchflow/verification/l3.py`（新） | `L3.rerun(node) -> L3Result(match_mode, attribution, coverage)` | 复用 executor predictions `L3_REUSED_EXECUTOR_OUTPUT`、非新目录 `L3_DIR_NOT_ISOLATED`、非原始数据 `L3_INPUT_NOT_RAW`、进程内复用 `L3_IN_PROCESS_STATE` | `wp-10/` |
| FR-008/NFR-05 | 11 | `researchflow/signing/{keys.py,merkle.py,payloads.py}`（新，复用 JCS） | `sign_report()`、`sign_certificate()`、`verify_signature()`、`merkle_root()`、`inclusion_proof()` | RFC 8032 向量、改载荷验签失败、换公钥失败、域分离错配失败、私钥不进包/日志 | `wp-11/` |
| FR-009/NFR-07 | 12 | `researchflow/bundle/export.py`（新）、根 `verify_bundle.py`（新） | `export_bundle(task_id) -> Path`；`verify_bundle.py --bundle --trust-store` | 缺件、清单哈希不符、包内伪公钥/信任锚在包内、报告/证书签名错、merkle 不符、非 VERIFIED 证书 | `wp-12/`、`g6-t0/` |
| FR-001 可见性 | 13 | `researchflow/workbench/app.py`（新，Streamlit 四视图） | 只读消费 `/api/v1/tasks/{id}{/graph,/evidence,/report,/certificate}` | 不直接读写 DB/证据；API 不可用时显示错误不伪造数据；stale 与缺口可见 | `wp-13/` |
| FR-010 T0 | R | `researchflow/recovery/{impact.py,plan.py,service.py}`（新） | `RecoveryService.invalidate_and_rerun()`（T0 无公开 API） | 同输入同 `plan_hash`；计划文件缺失/哈希不符/先重跑后冻结三条 `DENIED`；无关节点不失效；包内 stale 不放行 | `wp-r/` |
| FR-001–010 | 14 | `scripts/e2e_run.py`、`scripts/measure_concurrency.py`（新） | 三次隔离运行 + 独立验签 | 断网、无模型、三次一致；并发 ≤2 实测；离线验签在独立目录 | `docs/verification/t0/e2e/` |

## 3. 文件级清单

### 3.1 新增（本 Goal 写入）

- 持久层：`researchflow/persistence/schema_sql_v2.py`（迁移 0002 语句）、`researchflow/persistence/readmodels.py`（图谱/报告/证书/证据读取）。
- 领域：`researchflow/dag/`、`researchflow/templates/`（含 `data/` 与 `manifests/`）、`researchflow/execution/`、`researchflow/evidence/`、`researchflow/gate/`、`researchflow/rules/ruleset.v1.json`、`researchflow/verification/`、`researchflow/signing/`、`researchflow/bundle/`、`researchflow/recovery/`、`researchflow/workbench/`、`researchflow/pipeline.py`、`researchflow/cli.py`。
- 工具：根 `verify_bundle.py`、`scripts/e2e_run.py`、`scripts/measure_concurrency.py`、`scripts/build_template_dataset.py`。
- 测试：`tests/t0/` 下按 WP 分文件（`test_wp04_dag.py` … `test_wp14_e2e.py`），共用 `tests/t0/support.py`。
- 证据：`docs/verification/t0/wp-04` … `wp-r`、`e2e/run_1..3`、`g6-t0/`、`docs/verification/budget/`。

### 3.2 修改（最小、向后兼容）

- `researchflow/persistence/migrations.py`：注册 0002（0001 语句与 checksum **不变**，避免既有 DB 迁移失败）。
- `researchflow/persistence/repositories.py`：新增 Verifier 的 E3 追加能力与报告/证书/图版本仓储；保留既有 5 个 capability 语义。
- `researchflow/orchestration/ports.py`：用 SQLite 实现替换 fail-closed 的生产端口（`verify_chain`、`env_fingerprint`、graph/gate/report/certificate/node facts）。
- `researchflow/api/app.py`：注册 `GET /graph`、`GET /evidence`、`POST /verify`、`GET /report`、`GET /certificate`；保持 `/recover` 404；加入非回环无 token 启动守卫。
- `docs/state/project_state.json`、`docs/CHANGELOG_DEV.md`、`docs/SESSION_HANDOFF.md`、`docs/PROJECT_STATE.md`/`IMPLEMENTATION_STATUS.md`（生成）、`docs/memory/*`（稳定事实）。
- `requirements.lock`：**不改**（所需依赖均已锁定）。

不修改：`contracts/**`、`docs/design/**`、`docs/ADR/**`、`design/pseudocode/**`、根 DOCX、历史日志。

## 4. 跨模块数据流

```text
POST /tasks ──> TaskCreationService ──> StateMachine.create_initial (CREATED)
CLI run-task（内部编排，非新公共路由）
  └─ DAGBuilder.build_graph(task_spec) ──> graph_versions(0002)
     └─ Task CREATED→PLANNING→READY→RUNNING
        └─ Node PLANNED→READY→RUNNING
           └─ Executor: attempt_NN 子进程（worker 只做计算，不裁决）
              └─ Collector: E2 executor_launch / process_exit / artifact_observed
                 └─ Node RUNNING→VERIFYING（ATTEMPT_ENDED 守卫读 attempt result.json）
     └─ Task RUNNING→VERIFYING
        └─ Gate.evaluate（规则集 + 证据 + invalidations）
        └─ Verifier L1（链/哈希/产物）→ L2（指标重算 + 泄漏五规则）
        └─ L3（新目录、独立子进程、原始数据重训）→ E3 verifier_recheck
        └─ 签发 VerificationReport（Ed25519，载荷白名单）→ reports
        └─ 仅 VERIFIED + 必检完整 + L3 覆盖达标 → CompletionCertificate → certificates
        └─ Node VERIFYING→VERIFIED（Gate/报告/证书守卫）→ Task VERIFYING→COMPLETED
POST /verify ──> 同一 Verification 管线（用户可重跑；幂等以 report_id 唯一）
BundleExport ──> 目录 + manifest + manifest.sig.json
verify_bundle.py（独立进程、只 stdlib+cryptography、信任锚在包外）
WP-R: 输入变化 → 后代 VERIFIED→INVALIDATED（追加 invalidations）
      → RecoveryPlan 纯函数 + 内容寻址冻结（<plan_hash>.json + 审计）
      → INVALIDATED→READY 三条件守卫 → 新 attempt 保守重跑 → 重新验证
```

## 5. 数据库影响（迁移 0002，只向前）

| 表 | 用途 | 与 06 §1.3 的关系 |
|---|---|---|
| `graph_versions` | 图版本、`graph_hash`、确定性拓扑序、图快照 | 06 基线 + `graph_json TEXT`（持久化 NodeSpec 以重建 DAG 视图） |
| `reports` | VerificationReport | 06 基线 + `coverage_required/passed/missing`、`gaps_json`、`report_json`（契约要求 coverage 与缺口，06 DDL 未列存储列） |
| `certificates` | CompletionCertificate | 与 06 完全一致 |
| `ingestion_log` | 重复投递计数 | 与 06 完全一致 |
| 索引 | `idx_reports_task`、`idx_ingestion_evidence` | 06 建议索引 |

偏离说明：只增加“持久化冻结契约已要求字段”的存储列，不新增契约字段、不改语义、不改 0001；回滚方案为备份 DB 后恢复（只向前，无破坏性降级）。全部偏离登记在 `docs/verification/t0/wp-04/00_decisions.md`。

## 6. 已决事项与实现口径（不重复求裁决）

| 编号 | 事项 | 口径 |
|---|---|---|
| P-01 | WP-03 验收 | 2026-11-14 复测 87/217 passed 后转 DONE；不改历史结论写法 |
| P-02 | 创世 `prev_hash`（OQ-CT-10 仍开放） | 实现取 64 个 `0`（⑧ §2 建议值），仅 WP-07 内部常量，不写成冻结契约 |
| P-03 | attempt 结果存储 | 06 未定义 attempts 表；以 attempt 目录 `result.json`（执行观测）为事实源，不新增表 |
| P-04 | 规则集 | 新文件 `researchflow/rules/ruleset.v1.json`，`ruleset_hash` 由 JCS 计算；任务创建时校验与注册值一致 |
| P-05 | 数据集 | 自建确定性合成表格数据（CC0-1.0），生成脚本与哈希登记；不引用外部数据、不联网 |
| P-06 | 执行编排入口 | T0 不加 `/run` 等公共路由；内部 CLI `python -m researchflow.cli run-task` |
| P-07 | 报告签名策略 | 按 05 §1.5 白名单签名；`issued_at` 用 UTC 27 字符文本进载荷 |
| P-08 | 离线验签 | `verify_bundle.py` 不 import `researchflow`，只 stdlib+cryptography；信任锚必须来自包外路径 |
| P-09 | 审查 | A/B/C 分级；每 WP 一次独立只读审查（子 Agent 仅只读），主 Agent 修复并复验 |
| P-10 | 环境 | `BLK-003` 未关闭前，测试结果一律标注 `danger-full-access`；不宣称 workspace-write 通过 |

## 7. 批次与顺序

1. 批次 1（WP-03 验收 + WP-04/05）：迁移 0002、DAG、模板/数据/规则集、API `/graph`。
2. 批次 2（WP-06/07）：Executor/worker、Collector/链、E2 证据。
3. 批次 3（WP-08/09/10）：Gate、L1/L2、L3 独立重训。
4. 批次 4（WP-11/12）：签名/Merkle、Bundle 导出与独立验签。
5. 批次 5（管线/API 收口、WP-13 工作台、WP-R、WP-14 三次 e2e、文档、状态同步）。

每批出口：受影响测试真实通过 + 证据日志 + A 类清零；阶段出口跑全量 pytest 与 `state_sync`/契约校验。

## 8. 回滚方案

- 代码：按文件粒度回退新增模块与 `api/app.py`/`ports.py`/`repositories.py`/`migrations.py` 的改动（均为新增分支，不动既有公开行为）。
- 数据：迁移 0002 只新增表/索引；回退需恢复迁移前 DB 备份（`runtime/backups/`，不进 Git）。不写破坏性降级脚本。
- 文档：状态 JSON 手工回退后重跑 `state_sync`；CHANGELOG 追加更正条目，不覆盖历史。
- 冻结件：本计划不含对 `contracts/`、`docs/design/`、ADR 的任何修改。

## 9. 下一步指针

- 当前批次：**批次 1–5 全部完成（2026-11-14）**；WP-03 验收通过，WP-04–14 与 WP-R 全部 DONE。
- 已验证：
  - 三次隔离 e2e（`docs/verification/t0/e2e/run_1..3`）全部 COMPLETED/VERIFIED，独立离线验签 exit 0；
  - 并发上限 2 与 16GB 主机资源实测（`docs/verification/t0/e2e/concurrency.json`）；
  - 全量测试 339 passed（`docs/verification/t0/full_suite_2026-11-14_final.log`）；
  - 独立审查 A 类清零（`docs/verification/t0/review_2026-11-14.md`）。
- 门禁：G1/G2/G3 PASS；G6 IN_PROGRESS（仅 G6-T0 满足，完整 G6 属 T1，未提前通过）。
- 未决（不阻塞 T0 技术出口，留给用户/后续阶段）：`OQ-CT-10`、`OQ-CT-12`、`OQ-API-3/5`、`OQ-DB-2`；`BLK-003`；工作台截图；workspace-write 全绿；跨设备 G6；物理断网；预算余额核实。
- 下一步（需用户书面指令）：复核 T0 证据与门禁、决定 commit、再决定是否启动 Goal 2 / T1。