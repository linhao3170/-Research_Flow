# T0 实施决策记录（WP-04–WP-14、WP-R）

> 日期：2026-11-14（Asia/Shanghai）
> 性质：实现层决策与偏离登记。**不修改** `contracts/**`、`docs/design/**`、`docs/ADR/**`、`design/pseudocode/**`。冻结件与本文冲突时以冻结件为准并立即报告。
> 关联：[GOAL_01 实施总计划](../../plans/goal-01-plan.md)、G0 文档 ⑤⑥⑦、`docs/verification/t0/wp-03/00_decisions.md`。

## 1. 数据库迁移

| 编号 | 事项 | 决策 | 理由 |
|---|---|---|---|
| D-01 | 新增迁移 0002 | 创建 `graph_versions`、`reports`、`certificates`、`ingestion_log` 四表与索引；**不修改 0001 语句与 checksum** | 06 §1.3 已冻结这四表；0001 改动会让既有数据库校验失败。只向前迁移，回滚用迁移前备份（`runtime/backups/`，不进 Git） |
| D-02 | `graph_versions.graph_json` | 存整张图快照（NodeSpec 列表 + 边 + 拓扑序 + 参数表） | 06 DDL 只有 `graph_hash/topology_order`，无法重建 DAG 视图；不改 `nodes` 列 |
| D-03 | `reports` 附加列 | `coverage_required/passed/missing`、`gaps_json`、`report_json` | 冻结 `VerificationReport` 契约要求 `required_check_coverage`，`GET /report` 要求缺口；06 DDL 未列存储列。不新增契约字段 |
| D-04 | `certificates` | 与 06 §1.3 列一一对应，无附加列 | 契约字段已全部覆盖 |
| D-05 | 新增迁移 0003 | 重建 `audit_log` 以扩展 `action` 取值（新增 `EVIDENCE_APPENDED`、`VERIFY_RUN`、`REPORT_ISSUED`、`CERTIFICATE_ISSUED`、`BUNDLE_EXPORTED`），行数据原样保留，重建索引与四个状态守卫触发器（保持 0001 的触发顺序） | 06 §2 要求证据追加写 `audit_log`；SQLite 不能改 CHECK。0001 与 0002 checksum 不变 |
| D-06 | `ingestion_log` 能力 | 由 Collector 以 `COLLECTOR_APPEND` 追加；重复投递递增 `delivery_seq` | 06 §1.2/§4.5 |
| D-07 | E3 写者 | `EvidenceRepository.append` 对 `level=E3` 强制要求 `VERIFIER_EVIDENCE` capability，E0–E2 要求 `COLLECTOR_APPEND`。**裁决口径**：以冻结的 05 §4.5 与 06 §3 权限矩阵为准（Collector 写 E0–E2，Verifier 写 E3）；“Collector 单写提案”不采用，因此不存在双写者冲突。capability 不是安全边界，但它阻止了公开接口成为第二条写入路径 | 05 §4.5 等级-写者映射；越权写入被拒（WP-07 负例） |

## 2. 运行时与编排语义

| 编号 | 事项 | 决策 |
|---|---|---|
| D-08 | `PLANNED → READY` 的“依赖满足” | 只有 `no deps` 视图 | 冻结语义按“依赖节点已完成执行并提交产物”实现：前置节点处于 `VERIFYING` 或 `VERIFIED` 即满足；最终裁决仍在任务级 Gate/Verifier。若用户认为应要求 `VERIFIED`，需新 ADR，且会与“节点 VERIFIED 守卫需要报告/凭证”形成循环 |
| D-09 | 并发上限 | `limits.max_workers ∈ {1,2}`（契约已限），编排器按拓扑批次并行执行，最多 `max_workers` 个节点；实测 2 节点重叠 2.3s，见 `docs/verification/t0/e2e/concurrency.json` | 07 WP-01/§5.4 上限 2；不再多线程写同一节点 |
| D-09b | 内存观测（审查后修正） | uv venv 的 `python.exe` 是启动器，真实解释器为其子进程。执行器改用 `ProcessTreeSampler` 枚举启动器及全部后代，取树内最大工作集，并把实际采样的 `worker_pids`、`kill_verified` 写入 E2/`result.json`；`ProcessMemorySampler` 保留用于单进程校准。校准测试用真实 200 MB 分配断言 150–400 MB，证明读数不是常数 | 原实现只采样启动器（约 3.4 MB），导致 `max_memory_mb` fail-open、E2 内存值失真；已于 2026-11-14 修复并重跑三次 e2e（旧证据归档在 `e2e/superseded_2026-11-14_pre_memfix/`） |
| D-10 | 执行入口 | T0 无 `/run` 等新公共路由；内部编排由 `researchflow.pipeline.TaskPipeline` / `python -m researchflow.cli run-task` 承担。CLI 的 `recover`/`invalidate`/`rerun` 属**运维内部编排**，不是 06 §4.1 的公开 API；`POST /api/v1/tasks/{id}/recover` 仍不注册并返回 404 | 06 §4.1 冻结端点列表；“T0 不接受外部恢复指令”按公开 API 口径执行，CLI 须本机操作权限 |
| D-11 | attempt 结果存储 | 06 未定义 attempts 表；执行观测以 `<task_root>/tasks/<task>/attempts/<node>/attempt_NN/result.json` 为事实源 | 不新增表；L1/Gate 读取该文件 |
| D-12 | 创世 `prev_hash` | 64 个 `0`（⑧ §2 建议值） | `OQ-CT-10` 形式上仍开放；若用户另定值需迁移 |
| D-13 | collector 事件幂等键 | `event_key` 含 `attempt_id`，同一 attempt 重投幂等、不同 attempt 产生独立证据 | 重跑必须产生新证据；同键异内容按 `CHAIN_CONTENT_CONFLICT` 拒绝并写 DENIED 审计 |
| D-14 | `runtime` 数据根 | `RESEARCHFLOW_DATA_ROOT` 覆盖默认 `researchflow/templates/data`；e2e 每次运行使用隔离副本 | 便于“输入变化→失效→重跑”真实发生，且不污染仓库内置数据 |
| D-15 | 恢复计划存储 | `<task_root>/recovery_plans/<plan_hash>.json`；临时文件+fsync+rename；冻结审计**按受影响节点各写一行** `RECOVERY_PLAN_FROZEN(OK)` | 冻结守卫按节点查询冻结记录；计划正文不含时间戳 |

## 3. 验证与签名语义

| 编号 | 事项 | 决策 |
|---|---|---|
| D-16 | L1 | 重算证据链（seq/prev/chain_hash/payload_hash/等级映射）、逐产物重算 SHA-256、attempt 目录复用检测、当前 attempt `result.json` 必须 `EXITED/0` |
| D-17 | L2 | 独立纯 Python 重算指标（与 sklearn 结果差 ≤1e-9）、`y_true` 与测试集真实标签逐行一致、泄漏五规则 R1–R5（目标进特征 / 行重叠 / 分组重叠 / 时序倒置 / 清单重复） |
| D-18 | L3 | 每次验证在**新目录**、**独立子进程**从原始数据集重跑 split 与 train；比较 split_hash、预测逐行、指标容差；隔离守卫拒绝执行器目录、本进程 PID、执行器产物作为输入；E3 只能由 Verifier capability 写入。E3 载荷必须绑定当前 split manifest（`executor_split_hash`）、真实重跑进程（`train_pid`）与 L3 目录（`l3_split_dir`），Gate 与离线 `verify_bundle` 都校验这三点（审查后加固） |
| D-19 | Gate | 纯读评估器；必检项只由规则集声明等级/类型满足，且代码硬编码下限（执行类 ≥E2、metric_source=E3），规则集被改弱时报 `GAP_RULESET_INVALID`；E0/E1 永不满足执行类；旧 attempt 证据记 `GAP_STALE_ATTEMPT`；`evidence_invalidations` 命中的证据记 `GAP_EVIDENCE_STALE` 且**不删除**；`ruleset_hash` 不符立即失败；metric_source 还要求 E3 绑定当前 split 与 L3 进程（`GAP_E3_NOT_BOUND`） |
| D-20 | 报告/凭证签名 | Ed25519 + JCS + 域分离前缀；载荷字段白名单常量；`schema_version` 必须参与签名并拒绝未知 MAJOR；证书仅在报告 `VERIFIED`、必检缺口 0、L3 覆盖达标、链有效、E2 环境指纹存在时签发 |
| D-21 | Bundle 验签 | 独立 `verify_bundle.py` 只依赖 stdlib+cryptography，不 import 产品包；信任锚必须来自包外；重算清单哈希、证据链、Merkle 根、报告/证书签名，并从包内 graph/ruleset/records/invalidations **重新执行 Gate 判定**；包内仍存在且哈希正确的 stale 证据不能放行 |
| D-22 | 私钥 | 只存 `<task_root>/keys/*.private.json`（本地、gitignore）；不进入 bundle、payload、报告、证书或日志（测试扫描断言） |
| D-23 | 启动守卫 | 非回环且无 `RESEARCHFLOW_API_TOKEN` → 写 `STARTUP_GUARD/DENIED` 审计、结构化 stderr（不含 token）、退出码 2、不监听端口。**已接受风险**：token 只作为“已声明认证配置存在”的启动条件，T0 端点不做鉴权；`uvicorn researchflow.api.app:app --host 0.0.0.0` 直接引用模块级 app 会绕过 `serve()` 守卫，属运行方式风险，已在 `SECURITY_POLICY`/本文披露 |
| D-24 | 工作台 | Streamlit 四视图，只做 GET；不 import 持久层；用 `AppTest` 对真实 API 数据做运行级测试；截图未提供（无浏览器自动化），以运行日志与走查替代并披露 |
| D-25 | 验证幂等/串行 | `VerificationService.verify` 对同一 DB 加进程锁；若最新报告为 VERIFIED、证据根未变、无失效记录、节点无 INVALIDATED 且 Gate 仍通过，则返回既有报告/凭证，不重复签发。并发验证在同一进程内串行；跨进程并发未实现，属 T0 单用户边界 |
| D-26 | stale 展示 | `GET /report`、`GET /certificate` 增加 `stale` 布尔：节点 INVALIDATED 或存在不早于报告 `issued_at` 的失效记录即 true；T0 不做撤销 |
| D-27 | 证据 schema_version | `evidence` 表无版本列；链与 Merkle 叶固定使用契约值 `1.0`，API 证据项显式返回 `schema_version: "1.0"`。不新增列 |
| D-28 | 证书时间顺序 | 证书 `issued_at` 必须不早于报告 `issued_at`；Verifier 签发前校验，`verify_bundle` 亦校验 |
| D-29 | ADR-007 与工作台 | WP-13 只实现 07 §2.13 与 ADR-007（PROPOSED）所述**四视图最小工作台**，未扩大到六页/写操作；未修改或“通过” ADR-007，其正式裁决仍属用户。无架构变化（只读消费已冻结 REST API） |

## 4. 已知边界（不宣称）

1. **T0 无 LLM、无六角色、无 DC/SPA、无完整 Recovery 状态机**；`POST /recover` 保持 404，恢复仅内部编排。
2. 哈希链只证明“可发现篡改”，不是不可篡改；k 次一致只是限定条件下的经验资格。
3. L3 与执行器共用同一台机器/同一个解释器安装；隔离级别是“新目录 + 独立进程 + 原始数据重训”，不是另一台设备。
4. 断网以“代码不访问网络 + 代理黑洞 + 无模型客户端”为证据，未做操作系统级断网。
5. `BLK-003` 未关闭：全部测试在会话 `danger-full-access` 下运行，不写成 workspace-write 通过。
6. 工作台截图缺失；`OQ-CT-10/12`、`OQ-API-3/5`、`OQ-DB-2` 仍开放，但已按本文口径实现且不影响 T0 出口。
7. 规则集是 T0 数据文件 `researchflow/rules/ruleset.v1.json`，非冻结契约；改规则必须同时升 `ruleset_version` 并重跑全部证据。

## 5. 2026-11-15 A-01/A-02/A-03 收口决策

| 编号 | 事项 | 决策 | 理由与证据 |
|---|---|---|---|
| D-30 | 有效参数来源与 L1/L3 绑定 | 当前有效参数以注册图 `graph_json.nodes[].parameters_hash`（NodeSpec 声明）为准；当前 attempt 必须同时满足 `hash_payload(job.parameters)==job.parameters_hash`、`result.json.parameters_hash` 与 E2 `executor_launch.parameters_hash` 均等于 NodeSpec 哈希。任一项缺失记 `PARAMETERS_BINDING_MISSING`，不一致记 `PARAMETERS_HASH_MISMATCH`；L1/L3 分别映射为 `L1_/L3_PARAMETERS_BINDING_MISMATCH` 或 `..._INCOMPLETE` | 05 §3.1 已要求 `parameters_hash` 与参数一致；原 L1/L3 只读 job 参数，未交叉核对。不新增契约字段/表；新原因码只进 `gaps`/`issues`。证据：`a-01/summary.md`、`a-01/probe_report.json` |
| D-31 | L3 参数 preflight 的副作用 | L3 在创建验证目录或启动 split/train 子进程**之前**检查 split 与全部 metric 节点；失败返回 `status=FAIL, coverage=0, nodes=(), verification_root="", processes=()`，不产生任何复跑副作用 | 先跑后靠预测/指标差异间接发现参数变化不满足“以明确参数绑定错误拒绝”。正常执行/恢复 attempt_02 仍通过（`test_wp_recovery.py` 回归） |
| D-32 | 恢复调度前的证据校验 | `RecoveryService.invalidate()` 与 `rerun()` 在任何状态迁移、计划写入或执行前运行只读 L1；失败抛 `RECOVERY_NOT_SAFE`，detail 保留具体 `L1_*` 原因 | US-T0-20 负例“证据链未校验时拒绝恢复调度”。不新增状态边、不实现 T1 Recovery、不改 `/recover` 404。证据：`a-02/summary.md`、`a-02/probe_report.json`、`tests/t0/test_wp_restart_safety.py` |
| D-33 | WP-13 截图与走查 | 工作台支持 `?view=task|dag|evidence|report` 选择初始标签页、`?task_id=` 预填任务、`RESEARCHFLOW_API_TIMEOUT` 配置读取超时；截图用独立 Chrome CDP 脚本对真实 API/Streamlit 数据捕获，DOM 文本同时保存并断言 | 07 §2.13 要求 `screenshots/` 与 `walkthrough.md`；原实现只有 AppTest。未新增分页、下载、写操作或失效原因展示；ADR-007 仍 `PROPOSED`。证据：`wp-13/walkthrough.md`、`wp-13/screenshots.json`（`verdict=PASS`） |
| D-34 | ADR-007 正式裁决 | 2026-11-15 用户批准三个边界：(1) 独立只读 Streamlit 进程、只发 GET；(2) 四视图只读，证据固定 `limit=200` 单页、无分页/报告下载；(3) 展示 `STALE` 与失效计数、不展示失效原因（原因需另立 REST 契约方案）。ADR-007 由 `PROPOSED` 改为 `ACCEPTED`，索引与 D-29 历史同步登记；G0 ⑧ 冻结正文不回溯改写，差异在 ADR 索引登记 | 用户 2026-11-15 在 DSH 裁决问答中选择“批准建议（推荐）”；正式记录 `wp-13/ADR-007_DECISION.md`；证据 `wp-13/walkthrough.md`、`screenshots.json`、`pytest_2026-11-15.log`。不表示 T0 已全部验收或 commit 已授权 |