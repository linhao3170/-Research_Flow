<!-- 由 project_state.json 自动生成，请勿手工编辑。 -->
# ResearchFlow 实现状态

> 由 project_state.json 自动生成，请勿手工编辑。
> 数据源：`docs/state/project_state.json`；生成器：`scripts/state_sync.py`。
> 本文件只记录研发看板状态，不记录 ResearchFlow 运行时 Task/Node 状态。

## 1. 任务状态统计

| 状态 | 含义 | 数量 |
|---|---|---|
| `BACKLOG` | 待办 | 0 |
| `READY` | 就绪 | 0 |
| `IN_PROGRESS` | 进行中 | 0 |
| `BLOCKED` | 阻塞 | 0 |
| `IN_REVIEW` | 评审中 | 1 |
| `DONE` | 完成 | 28 |
| `DEFERRED` | 延期 | 0 |
| **合计** | — | **29** |

## 2. 任务明细

### `T-A01-001` A-01 参数完整性绑定：L1/L3 交叉核对 job/NodeSpec/E2

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-09-001`、`T-WP-10-001`
- 更新时间：2026-11-15T10:41:24+08:00
- 阻塞：无
- 验收标准：
  - 当前 attempt 的 job.parameters、job.parameters_hash、result.json.parameters_hash 与 E2 executor_launch.parameters_hash 必须全部等于注册图 NodeSpec parameters_hash；缺失或不一致以具体 L1_/L3_ 参数绑定原因拒绝
  - L3 在创建验证目录或子进程前 preflight split 与全部 metric 节点；拒绝时 coverage 0、nodes 空、无目录、无子进程
  - split 与 train 两类负例覆盖：篡改参数并重算声明哈希、只改参数不改声明哈希、E2 绑定缺失；断言具体错误码与 node_id
  - 正常执行与恢复 attempt_02 不被误拒；全量 351 passed，新三次 e2e consistent=true
  - 不修改 contracts、Schema、迁移、状态边或 Gate 规则；新原因码只进 gaps/issues
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp09_verifier_l12.py tests/t0/test_wp10_verifier_l3.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -B docs/verification/t0/a-01/parameter_binding_probe.py`
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp_recovery.py -q -p no:cacheprovider`
- 证据路径：
  - `docs/plans/A-01_PARAMETER_BINDING_PLAN.md`
  - `docs/verification/t0/a-01/summary.md`
  - `docs/verification/t0/a-01/probe_report.json`
  - `docs/verification/t0/a-01/pytest_targeted.log`
  - `researchflow/verification/context.py`
  - `researchflow/verification/l1.py`
  - `researchflow/verification/l3.py`
  - `tests/t0/test_wp09_verifier_l12.py`
  - `tests/t0/test_wp10_verifier_l3.py`
  - `tests/t0/support.py`
  - `docs/verification/t0/review_2026-11-15.md`

### `T-A02-001` A-02 中断/重启安全接手与恢复前证据校验

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-07-001`、`T-WP-R-001`
- 更新时间：2026-11-15T10:41:24+08:00
- 阻塞：无
- 验收标准：
  - 独立产品进程在 split 完成、train RUNNING 且 result.json 缺失的检查点被 taskkill /T 中断；新进程以 SQLite mode=ro 重读数据库与 attempt 目录并枚举残留 python 进程
  - 中断后 task 仍 RUNNING、reports=0、certificates=0、链仍完整、被中断 attempt 无 result；API 新进程 GET report 404、GET certificate 409、POST verify 409 STATE_TRANSITION_DENIED
  - 坏链或缺失 attempt 结果时 RecoveryService.invalidate 以 RECOVERY_NOT_SAFE + L1_CHAIN_PAYLOAD_MISSING / L1_ATTEMPT_RESULT_MISSING 拒绝，节点状态与计划不变
  - 有效失效后坏链时 rerun 同样拒绝，节点保持 INVALIDATED，不创建 attempt_02
  - 不新增状态边、不实现 T1 Recovery、不注册 /recover；全量 351 passed，新三次 e2e consistent=true
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp_restart_safety.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -B docs/verification/t0/a-02/recovery_chain_probe.py`
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp_recovery.py tests/t0/test_wp_api.py -q -p no:cacheprovider`
- 证据路径：
  - `docs/verification/t0/a-02/summary.md`
  - `docs/verification/t0/a-02/probe_report.json`
  - `docs/verification/t0/a-02/pytest_restart.log`
  - `docs/verification/t0/a-02/pytest_regression.log`
  - `docs/verification/t0/a-02/recovery_chain_probe.py`
  - `tests/t0/test_wp_restart_safety.py`
  - `tests/t0/restart_probe.py`
  - `researchflow/recovery/service.py`
  - `docs/verification/t0/review_2026-11-15.md`

### `T-A03-001` A-03 ADR-007 正式裁决与 WP-13 交付材料

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-13-001`
- 更新时间：2026-11-15T10:46:04+08:00
- 阻塞：无
- 验收标准：
  - 四视图截图与 walkthrough 已用真实 API/Streamlit 数据补齐；覆盖任务、DAG、证据 STALE、报告/凭证、API 不可达；DOM 断言通过，screenshots.json verdict=PASS
  - 三个边界在 ADR-007_DECISION.md 中明确并经用户 2026-11-15 批准：独立只读进程、四视图只读、证据单页 limit=200 无分页/下载、展示 STALE 不展示原因
  - ADR-007 已由 PROPOSED 改为 ACCEPTED；裁决来源登记为用户 2026-11-15 在 DSH 裁决问答中的“批准建议（推荐）”；G0 ⑧ 冻结正文未回溯改写，差异在 ADR 索引登记
  - 未获批准的扩展（分页、报告下载、失效原因展示、六页工作台、写操作）未被夹带实现
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp13_workbench.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -B docs/verification/t0/wp-13/capture_screenshots.py`
- 证据路径：
  - `docs/verification/t0/wp-13/walkthrough.md`
  - `docs/verification/t0/wp-13/screenshots.json`
  - `docs/verification/t0/wp-13/screenshots/`
  - `docs/verification/t0/wp-13/pytest_2026-11-15.log`
  - `docs/verification/t0/wp-13/ADR-007_DECISION_PROPOSAL.md`
  - `docs/ADR/ADR-007-t0-workbench-scope.md`
  - `docs/verification/t0/review_2026-11-15.md`
  - `docs/verification/t0/wp-13/ADR-007_DECISION.md`
  - `docs/ADR/README.md`

### `T-DOCS-001` ResearchFlow 项目资料接手、来源登记与知识基线整理

- 阶段：`WORKSTATION_SETUP`
- 状态：`DONE` 完成
- 依赖：无
- 更新时间：2026-11-08T13:25:00+08:00
- 阻塞：无
- 验收标准：
  - 根目录 DOCX 未被复制/移动/重命名/修改；大小与 SHA256 复核一致
  - 754/754 段落、80/80 表格、0 媒体/绘图/文本框、0 修订/批注完成只读抽取
  - 版本冲突（文件名 v4.3.1 / 内部 v4.3.0）已登记；用户 2026-11-08 确认内部 v4.3.0 为内容基线，BLK-002 关闭
  - SOURCE_REGISTER、CONFLICT_REPORT 与八份知识/架构文档建立并标注来源锚点
  - T-SKILLS-001 转 DONE；T-MCP-001 保持 DONE；G0–G7 未改
  - 未 commit、未建 .venv、未安装依赖、未开发业务代码
- 测试命令：
  - `& $py docs/verification/stage7/extract_docx.py`
  - `& $py docs/verification/stage7/verify_version_strings.py`
  - `& $py docs/verification/stage7/scan_secrets.py`
  - `& $py docs/verification/stage7/check_links.py`
  - `& $py docs/verification/stage7/check_task_evidence.py`
  - `& $py scripts/state_sync.py validate`
  - `& $py scripts/state_sync.py render`
  - `& $py scripts/state_sync.py check`
- 证据路径：
  - `docs/reference/SOURCE_REGISTER.md`
  - `docs/reference/CONFLICT_REPORT.md`
  - `docs/PROJECT_OVERVIEW.md`
  - `docs/ARCHITECTURE.md`
  - `docs/GLOSSARY.md`
  - `docs/DEVELOPMENT_WORKFLOW.md`
  - `docs/MEMORY_GUIDE.md`
  - `docs/MCP_CATALOG.md`
  - `docs/SECURITY_POLICY.md`
  - `docs/SKILL_CATALOG.md`
  - `docs/verification/stage7/STAGE7_REPORT.md`
  - `docs/verification/stage7/00_extract.log`
  - `docs/verification/stage7/01_docx_properties.txt`
  - `docs/verification/stage7/02_docx_body.txt`
  - `docs/verification/stage7/03_docx_outline.txt`
  - `docs/verification/stage7/04_docx_version_scan.txt`
  - `docs/verification/stage7/05_docx_tables.txt`
  - `docs/verification/stage7/07_version_strings.txt`
  - `docs/verification/stage7/09_inventory.log`
  - `docs/verification/stage7/06_page_map_attempt.md`
  - `docs/verification/stage7/13_secret_scan.log`
  - `docs/verification/stage7/14_link_check.log`
  - `docs/verification/stage7/15_task_evidence_check.log`
  - `docs/verification/stage7/16_final_inventory.log`
  - `docs/verification/stage8/26_version_resolution.md`

### `T-G0-001` G0 规格冻结文档包

- 阶段：`G0_PREPARATION`
- 状态：`DONE` 完成
- 依赖：`T-DOCS-001`、`T-STAGE8-001`
- 更新时间：2026-11-10T00:45:00+08:00
- 阻塞：无
- 验收标准：
  - ①–⑧ 八份 G0 文档全部升为 v1.0 并标「G0 冻结」（冻结日期 2026-11-10、被取代版本）；① 的 v1.1 候选期编号归并回 v1.0
  - ⑨ 五份契约 JSON Schema v1.0 + 72 个正反例 + validate_contracts.py，真实 exit 0
  - FR-001–FR-020 与 NFR-01–08 一条不漏，追踪矩阵含来源、优先级、阶段、依赖、输入/输出、风险、验收方法、证据与门禁
  - 契约/状态、数据/API、T0 计划/门禁四份设计文档通过内部一致性检查
  - 未决问题、风险排序与冻结决议清单完成；G0 是否 PASS 留待用户宣布
  - 用户 2026-11-09 的 10 项决议与 2026-11-10 的 4 项裁决逐条落地到 ⑤⑥⑦⑧、contracts/、.gitignore 与 Git 配置
  - 三组枚举按现值冻结：kind(7) / l1-l3_status(4) / side_effect_class(3)，保留按 MINOR 可变注记
  - 依赖矩阵锁定为 WP-01 基线并写入 ⑦ WP-01 入口条件；解释器硬约束（uv 3.11.16 64 位、指纹校验、TestClient 冒烟与回退）已写入
  - ADR-001–006 ACCEPTED；ADR-007 保持 PROPOSED，WP-13 前裁决
  - Git 身份按仓库级配置（ResearchFlow Dev / dev@researchflow.local），全局身份仍为空；DOCX 按精确文件名忽略且原文件未动、未改名、未移动
  - G0 规格基线提交完成（91bde66）；用户 2026-11-10 宣布 G0 PASS，T-G0-001 转 DONE；G1–G7 仍 NOT_STARTED
  - 未建 .venv、未装依赖、未写业务代码
- 测试命令：
  - `git config --local --get user.name`
  - `git config --local --get user.email`
  - `git config --global --get user.name`
  - `git config --global --get user.email`
  - `git check-ignore -v -- ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx`
  - `& $py scripts/validate_contracts.py --selftest`
  - `& $py scripts/validate_contracts.py`
  - `& $py docs/verification/g0/check_terms.py`
  - `& $py docs/verification/g0/check_links_g0.py <files>`
  - `& $py scripts/state_sync.py validate`
  - `& $py scripts/state_sync.py render`
  - `& $py scripts/state_sync.py check`
  - `git rev-parse HEAD`
  - `git status --short`
  - `git ls-files \| Measure-Object -Line`
- 证据路径：
  - `docs/G0/01_BASELINE_AND_TERMS.md`
  - `docs/PRD/02_REQUIREMENT_TRACEABILITY.md`
  - `docs/PRD/03_PRD_T0.md`
  - `docs/design/04_ARCHITECTURE.md`
  - `docs/design/05_CONTRACTS_AND_STATES.md`
  - `docs/design/06_DATA_AND_API.md`
  - `docs/design/07_T0_PLAN_AND_GATES.md`
  - `docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md`
  - `docs/state/G0_DECISION_LIST.md`
  - `docs/ADR/README.md`
  - `contracts/README.md`
  - `contracts/taskspec.schema.json`
  - `contracts/nodespec.schema.json`
  - `contracts/evidencerecord.schema.json`
  - `contracts/verificationreport.schema.json`
  - `contracts/completioncertificate.schema.json`
  - `contracts/examples/manifest.json`
  - `scripts/validate_contracts.py`
  - `docs/verification/g0/build_examples.py`
  - `docs/verification/g0/check_terms.py`
  - `docs/verification/g0/check_links_g0.py`
  - `docs/verification/g0/research_versions.py`
  - `docs/verification/g0/01_selftest.log`
  - `docs/verification/g0/02_validate_contracts.log`
  - `docs/verification/g0/03_link_check.log`
  - `docs/verification/g0/04_artifacts_sha256.log`
  - `docs/verification/g0/05_git_baseline_report.md`
  - `docs/verification/g0/06_first_commit_filelist.txt`
  - `docs/verification/g0/07_term_consistency.log`
  - `docs/verification/g0/08_dependency_matrix.log`
  - `docs/verification/g0/09_dependency_matrix.md`
  - `docs/verification/stage7/SUPERSEDED_NOTICE.md`
  - `docs/verification/g0/10_version_freeze_selftest.log`
  - `docs/verification/g0/11_version_freeze_validate_contracts.log`
  - `docs/verification/g0/12_version_freeze_terms.log`
  - `docs/verification/g0/13_version_freeze_links.log`
  - `docs/verification/g0/14_version_freeze_state_validate.log`
  - `docs/verification/g0/15_version_freeze_state_render.log`
  - `docs/verification/g0/16_version_freeze_state_check.log`
  - `docs/verification/g0/17_version_freeze_report.md`
  - `docs/verification/g0/18_git_rollback.log`
  - `docs/verification/g0/19_g0_pass_decision.md`
  - `docs/verification/g0/20_g0_pass_recheck.log`
  - `docs/verification/g0/21_state_sync_g0_pass.log`
  - `docs/verification/g0/22_gate_decision_schema_test.log`
  - `docs/verification/g0/check_gate_decision.py`

### `T-GOALS-001` 三阶段 DeepSeek Harness Goal 任务书与赛道一执行规划（文档交付）

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：无
- 更新时间：2026-11-14T18:04:00+08:00
- 阻塞：无
- 验收标准：
  - 三份独立可读取的中文 Markdown Goal 文档，按 T0 后端可信闭环、T1 竞争力、T2 差异化与竞赛交付递进
  - 按当前 WP-01/02 已完成、WP-03 待验收、P9/P10 与 BLK-003 阻塞续建，不把历史 full-access 测试写成受限环境通过
  - 开发方法落实统一契约和命名、伪代码先行、批次实施、A/B/C 分级审查、真实负例与记忆交接
  - 按本机 Harness 0.2.2-rc.3 Goal 机制编写，并区分轮数、费用和项目运行时状态
  - 结合用户赛道一通知图及阿里云 DeepSeek V4.1 Flash，分别约束开发 API 200 元和项目运行调试 API 50 元的跨阶段总额
  - 文档结构和本地引用检查通过；不修改业务实现、冻结契约、既有门禁、last_verified_commit 或既有任务状态
- 测试命令：
  - `PowerShell here-string \| D:/ResearchFlow-project/.venv/Scripts/python.exe -B -：UTF-8、Markdown 代码围栏、本地链接、文件与来源 SHA256 校验`
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B scripts/state_sync.py validate`
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B scripts/state_sync.py render`
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B scripts/state_sync.py check`
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B scripts/check_docs_drift.py`
- 证据路径：
  - `docs/goals/GOAL_01_CORE_BACKEND.md`
  - `docs/goals/GOAL_02_COMPETITIVE_PRODUCT.md`
  - `docs/goals/GOAL_03_COMPETITION.md`
  - `docs/goals/verification/document_validation.json`
  - `docs/goals/verification/source_and_review.md`
  - `docs/goals/verification/state_sync.log`
  - `docs/goals/verification/docs_drift.log`

### `T-GOALS-002` 三阶段 Goal 自动记忆与交接收尾（文档治理）

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-GOALS-001`
- 更新时间：2026-11-14T23:17:07+08:00
- 阻塞：无
- 验收标准：
  - 三份 Goal 启动与完成清单均引用统一自动收尾规则
  - 每包保存检查点；稳定记忆与研发进度分离；无新增稳定事实时注明已复核无需修改
  - 收尾记录真实验证、批准来源、累计预算和下一动作；必需检查失败不得 complete
  - 仅文档治理，不改变业务实现、冻结架构、既有任务/门禁、last_verified_commit 或预算余额
- 测试命令：
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B scripts/state_sync.py validate`
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B scripts/state_sync.py render`
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B scripts/state_sync.py check`
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B scripts/check_docs_drift.py`
- 证据路径：
  - `docs/goals/MEMORY_CLOSEOUT.md`
  - `docs/goals/GOAL_01_CORE_BACKEND.md`
  - `docs/goals/GOAL_02_COMPETITIVE_PRODUCT.md`
  - `docs/goals/GOAL_03_COMPETITION.md`
  - `docs/goals/verification/memory_closeout_20261114/document_validation.json`
  - `docs/goals/verification/memory_closeout_20261114/state_sync.log`
  - `docs/goals/verification/memory_closeout_20261114/docs_drift.log`

### `T-MCP-001` 核实 DSH MCP Client 能力并完成 Context7 接入验证

- 阶段：`WORKSTATION_SETUP`
- 状态：`DONE` 完成
- 依赖：无
- 更新时间：2026-11-08T12:34:18+08:00
- 阻塞：无
- 验收标准：
  - 以 app.asar 内 0.2.2-rc.1 实现确认支持 streamable-http 远程 MCP
  - Context7 端点匿名探测返回真实工具与结果
  - 经批准写入 cordis.patch.yml，字节/哈希/前缀三项校验通过
  - 热重载后 mcp__context7__ 两个工具出现并完成真实查询
  - 未配置 API Key，web_fetch/telemetry/session-log 配置未改动
- 测试命令：
  - `& $py docs/verification/stage6/inspect_mcp_client.py`
  - `& $py docs/verification/stage6/context7_probe.py`
  - `& $py docs/verification/stage6/apply_context7_patch.py verify`
  - `& $py scripts/state_sync.py validate`
  - `& $py scripts/state_sync.py check`
- 证据路径：
  - `docs/verification/stage6/00_mcp_capability.md`
  - `docs/verification/stage6/01_context7_probe.md`
  - `docs/verification/stage6/02_config_diff_proposal.md`
  - `docs/verification/stage6/03_decision.md`
  - `docs/verification/stage6/08_apply_result.md`
  - `docs/verification/stage6/00_mcp_source.log`
  - `docs/verification/stage6/01_context7_probe.log`
  - `docs/verification/stage6/02_config_snapshot.log`
  - `docs/verification/stage6/03_state_sync.log`
  - `docs/verification/stage6/04_secret_scan.log`
  - `docs/verification/stage6/05_git_status.log`
  - `docs/verification/stage6/06_apply.log`
  - `docs/verification/stage6/06_apply_summary.log`
  - `docs/verification/stage6/07_post_write_verify.log`
  - `docs/verification/stage6/09_state_sync_after_done.log`
  - `docs/verification/stage6/10_verify_script.log`

### `T-PSEUDO-001` P0 伪代码规格阶段（P1–P10，独立阶段注册表）

- 阶段：`T0`
- 状态：`IN_REVIEW` 评审中
- 依赖：`T-WP-02-001`
- 更新时间：2026-11-12T17:41:01+08:00
- 阻塞：无
- 验收标准：
  - P1–P10 在 pseudocode_stages 中有唯一状态、模块、交付物、验收依据与证据路径
  - P1–P8 ACCEPTED 有用户验收记录（P1 2026-11-11；P2–P8 2026-11-12）；P9/P10 未验收且不得标 ACCEPTED
  - P9 六个并发重写文件逐项登记；P10 的 M19 仅登记现状，未获开发授权
  - INDEX/STAGE_LOG/OPEN_QUESTIONS/SESSION_HANDOFF 与本状态源保持一致
  - state_sync.py validate/render/check 真实 exit 0
- 测试命令：
  - `& .venv/Scripts/python.exe scripts/state_sync.py validate`
  - `& .venv/Scripts/python.exe scripts/state_sync.py render`
  - `& .venv/Scripts/python.exe scripts/state_sync.py check`
  - `& .venv/Scripts/python.exe -m pytest tests/test_state_sync.py -q -p no:cacheprovider`
- 证据路径：
  - `design/pseudocode/INDEX.md`
  - `design/pseudocode/STAGE_LOG.md`
  - `design/pseudocode/OPEN_QUESTIONS.md`
  - `docs/state/project_state.json`
  - `reports/remediation/P0_STATE_CONSISTENCY_REPORT.md`
  - `reports/remediation/logs/30_p9_missing_search.log`
  - `reports/remediation/logs/41_state_sync_new_tests.log`
  - `reports/remediation/P0_CHANGELOG.md`
  - `reports/remediation/P0_TEST_REPORT.md`
  - `reports/remediation/P0_OPEN_ISSUES.md`
  - `reports/remediation/P0_FINAL_ACCEPTANCE.md`
  - `reports/remediation/logs/31_p9_artifact_inventory.txt`
  - `reports/remediation/logs/32_m19_inventory.txt`
  - `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`

### `T-PUBLISH-001` T0 首次普通提交、推送与干净快照验证

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-PUBLISH-PREP-001`、`T-T0-ACCEPT-001`
- 更新时间：2026-11-15T11:32:00+08:00
- 阻塞：无
- 验收标准：
  - 准确远端 https://github.com/linhao3170/-Research_Flow.git（前导连字符保留），远端无既有分支；可见性经 GitHub API 核实为公开并如实报告与私有预期的差异
  - 沿用仓库级身份 ResearchFlow Dev <dev@researchflow.local>，未改全局配置
  - 候选清单经审核后按清单暂存，不使用无清单 git add .；最终索引与 7 个历史提交的秘密扫描均 0 findings；私钥、凭据与本地运行数据库被排除
  - 证据包按原始字节入库（e2e/g6-t0 使用 -text），修正换行归一化导致的离线验签风险
  - P9/P10 仅保存为明确 BLOCKED 的历史草稿，不视为验收或开发批准，不执行、不改其状态
  - 契约 10/10 与 72/72、state_sync validate/render/check、docs drift 均为本次真实运行；历史 351 passed 仅作历史证据，不写成本次重跑
  - 普通 commit 与普通 push 成功，本地与远端 main 的 SHA 一致；未 force push、未删除既有工作、未修改验收标准
  - 在新临时目录克隆远端快照，验证状态校验入口与离线验签入口
  - 按 MEMORY_CLOSEOUT 同步状态、日志、交接与稳定记忆；T1 未启动
  - 结果（2026-11-15）：内容提交 35ab02bfe3d54799acb40e9a2ff632661d853111 已推送，本地/远端/GitHub API 三方 SHA 一致；远端快照 14.34 MB，state_sync validate/check 与契约 72/72 exit 0，run_1..3 离线验签三次 VERIFIED（trust_anchor_source=external）
- 测试命令：
  - `git ls-remote --heads origin`
  - `& .venv/Scripts/python.exe -B docs/verification/publication/2026-11-15/audit_snapshot.py staged`
  - `& .venv/Scripts/python.exe -B scripts/validate_contracts.py --selftest`
  - `& .venv/Scripts/python.exe -B scripts/validate_contracts.py`
  - `& .venv/Scripts/python.exe -B scripts/state_sync.py validate`
  - `& .venv/Scripts/python.exe -B scripts/state_sync.py render`
  - `& .venv/Scripts/python.exe -B scripts/state_sync.py check`
  - `& .venv/Scripts/python.exe -B scripts/check_docs_drift.py`
  - `& .venv/Scripts/python.exe -E verify_bundle.py --bundle docs/verification/t0/e2e/run_1/bundle --trust-store docs/verification/t0/e2e/run_1/isolated-verifier/trust_store.json`
  - `git rev-parse HEAD; git ls-remote origin refs/heads/main`
- 证据路径：
  - `docs/verification/publication/2026-11-15/PUBLISH_HANDOFF.md`
  - `docs/verification/publication/2026-11-15/working_audit.json`
  - `docs/verification/publication/2026-11-15/staged_audit.json`
  - `docs/verification/publication/2026-11-15/01_contracts_selftest.log`
  - `docs/verification/publication/2026-11-15/02_contracts.log`
  - `docs/verification/publication/2026-11-15/03_state_validate.log`
  - `docs/verification/publication/2026-11-15/04_state_render.log`
  - `docs/verification/publication/2026-11-15/05_state_check.log`
  - `docs/verification/publication/2026-11-15/06_docs_drift.log`
  - `docs/verification/publication/2026-11-15/07_commit_push.log`
  - `docs/verification/publication/2026-11-15/08_clean_state_validate.log`
  - `docs/verification/publication/2026-11-15/09_clean_state_check.log`
  - `docs/verification/publication/2026-11-15/10_clean_contracts.log`
  - `docs/verification/publication/2026-11-15/11_clean_verify_run1.log`
  - `docs/verification/publication/2026-11-15/12_clean_verify_run2.log`
  - `docs/verification/publication/2026-11-15/13_clean_verify_run3.log`
  - `docs/verification/publication/2026-11-15/14_final_state_validate.log`
  - `docs/verification/publication/2026-11-15/15_final_state_render.log`
  - `docs/verification/publication/2026-11-15/16_final_state_check.log`
  - `docs/verification/publication/2026-11-15/17_final_docs_drift.log`

### `T-PUBLISH-PREP-001` T0 GitHub 提交范围审核与 Harness 交接（未提交/未推送）

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-T0-ACCEPT-001`
- 更新时间：2026-11-15T11:04:35+08:00
- 阻塞：无
- 验收标准：
  - 核对T0收口验收入口、仓库身份与候选文件范围，不重写业务实现或历史证据
  - 记录用户确认本次开发API消耗15元，累计余额仍待核实
  - 排除运行私钥、本地e2e数据库及测试临时目录；候选扫描不回显秘密
  - 提供准确仓库URL与Harness提交交接，明确工作区扫描不等于已提交/已推送
- 测试命令：
  - `git status --short --untracked-files=no`
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B docs/verification/publication/2026-11-15/audit_snapshot.py working --paths-file`
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B scripts/state_sync.py validate`
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B scripts/state_sync.py render`
  - `& D:/ResearchFlow-project/.venv/Scripts/python.exe -B scripts/state_sync.py check`
- 证据路径：
  - `docs/verification/publication/2026-11-15/PUBLISH_HANDOFF.md`
  - `docs/verification/publication/2026-11-15/working_audit.json`
  - `docs/verification/budget/BUDGET_LEDGER.md`

### `T-SKILLS-001` 建立项目级 Skills 系统并验证发现、加载与调用

- 阶段：`WORKSTATION_SETUP`
- 状态：`DONE` 完成
- 依赖：无
- 更新时间：2026-11-08T12:56:05+08:00
- 阻塞：无
- 验收标准：
  - 九个 Skill 通过结构校验且无多层嵌套 SKILL.md
  - 九个 Skill 出现在 Harness catalog 并可逐个按名称加载
  - onboarding、spec-driven-development、memory-handoff 完成无副作用执行验证
  - 未在 .dsh/skills 或全局目录创建同名 Skill
  - 状态、CHANGELOG、交接和验证日志齐全
- 测试命令：
  - `& $py scripts/validate_skills.py`
  - `& $py -m unittest discover -s tests -v`
  - `Harness skill tool: load 9 researchflow-* skills by exact name`
- 证据路径：
  - `docs/verification/stage5/00_discovery.md`
  - `docs/verification/stage5/01_structure.log`
  - `docs/verification/stage5/02_secret_scan.log`
  - `docs/verification/stage5/03_invocation_tests.md`
  - `docs/verification/stage5/04_state_sync.log`
  - `docs/verification/stage5/05_validation.log`
  - `docs/verification/stage5/06_structure_negative.log`
  - `docs/verification/stage5/07_repo_secret_scan.log`
  - `docs/SKILL_CATALOG.md`

### `T-STAGE8-001` AI 研发工作站综合验收（阶段 8）

- 阶段：`WORKSTATION_SETUP`
- 状态：`DONE` 完成
- 依赖：`T-SKILLS-001`、`T-MCP-001`、`T-DOCS-001`
- 更新时间：2026-11-08T13:35:00+08:00
- 阻塞：无
- 验收标准：
  - 26 项验收逐项给出 PASS/FAIL/NOT VERIFIED/DEFERRED/BLOCKED 判定与证据路径
  - 运行态证据来自真实命令、进程或调用，不以文件存在或 Agent 自述代替
  - FAIL、NOT VERIFIED、DEFERRED、BLOCKED 项列出影响与建议处理
  - 安全审计覆盖凭据、Session、431 个目录联接与 Profile；报告不回显密钥
  - 13a/13b 分开判定；13b 不得引用 danger-full-access 下的 23/23 作为通过依据
  - 阶段 8 经用户 2026-11-08 验收通过：25 PASS / 2 NOT VERIFIED / 0 FAIL；残留风险已写入 G0 决策清单
  - 未 commit、未进入阶段 9、未开发业务代码
- 测试命令：
  - `& $py scripts/state_sync.py validate`
  - `& $py scripts/state_sync.py render`
  - `& $py scripts/state_sync.py check`
  - `& $py -m unittest discover -s tests -v`
- 证据路径：
  - `docs/verification/stage8/01_startup_profile.log`
  - `docs/verification/stage8/02_security_2c.log`
  - `docs/verification/stage8/03_model_probe.md`
  - `docs/verification/stage8/04_terminal_fs.log`
  - `docs/verification/stage8/06_workspace_policy.md`
  - `docs/verification/stage8/07_agents_project.log`
  - `docs/verification/stage8/08_agents_global.log`
  - `docs/verification/stage8/09_memory.log`
  - `docs/verification/stage8/10_state_schema.log`
  - `docs/verification/stage8/11_state_sync_validate.log`
  - `docs/verification/stage8/12_state_sync_render.log`
  - `docs/verification/stage8/12_state_sync_check.log`
  - `docs/verification/stage8/13_check_negative.log`
  - `docs/verification/stage8/14_skills_catalog.log`
  - `docs/verification/stage8/15_skills_on_demand.md`
  - `docs/verification/stage8/16_skill_no_side_effect.log`
  - `docs/verification/stage8/17_skill_catalog_check.log`
  - `docs/verification/stage8/18_context7.md`
  - `docs/verification/stage8/19_git_docx.log`
  - `docs/verification/stage8/20_git_rollback.md`
  - `docs/verification/stage8/21_security_audit.md`
  - `docs/verification/stage8/21_secret_scan.log`
  - `docs/verification/stage8/22_cli_junctions.log`
  - `docs/verification/stage8/23_approval_teams.md`
  - `docs/verification/stage8/23_approval_teams.log`
  - `docs/verification/stage8/24_dependencies.md`
  - `docs/verification/stage8/24_dependencies.log`
  - `docs/verification/stage8/25_scope_design.md`
  - `docs/verification/stage8/25_scope_design.log`
  - `docs/verification/stage8/26_version_resolution.md`
  - `docs/verification/stage8/30_policy_restored.log`
  - `docs/verification/stage8/31_blk003_probe.log`
  - `docs/verification/stage8/31b_probe_path_evidence.log`
  - `docs/verification/stage8/32_unittest_workspacewrite.log`
  - `docs/verification/stage8/33_item5_workspacewrite.log`
  - `docs/verification/stage8/34_item6_23_workspacewrite.log`
  - `docs/verification/stage8/35_check_negative_workspacewrite.log`
  - `docs/verification/stage8/D_resources.log`
  - `docs/state/G0_DECISION_LIST.md`
  - `docs/verification/stage8/STAGE8_REPORT.md`

### `T-T0-ACCEPT-001` T0 阶段验收（用户 2026-11-15 接受；暂不 commit）

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-A01-001`、`T-A02-001`、`T-A03-001`、`T-WP-14-001`
- 更新时间：2026-11-15T10:48:04+08:00
- 阻塞：无
- 验收标准：
  - 用户 2026-11-15 在 DSH 会话中明确选择“验收 T0，暂不 commit”；T0 通过验收
  - A-01 参数绑定、A-02 中断/重启与恢复前证据校验、A-03 ADR-007 裁决与 WP-13 截图/走查均已完成并有真实证据
  - 修复后全量 351 passed、三次 e2e consistent=true、三次离线验签 VERIFIED；契约/状态/文档检查 exit 0
  - 验收不表示 commit/推送已授权、不表示完整 G6 通过、不表示 T1 启动；BLK-003 与 B 类入口边界仍如实披露
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -B scripts/e2e_run.py --runs 3 --out docs/verification/t0/e2e`
  - `& .venv/Scripts/python.exe -E verify_bundle.py --bundle docs/verification/t0/e2e/run_1/bundle --trust-store docs/verification/t0/e2e/run_1/isolated-verifier/trust_store.json`
  - `& .venv/Scripts/python.exe -B scripts/state_sync.py validate`
  - `& .venv/Scripts/python.exe -B scripts/state_sync.py render`
  - `& .venv/Scripts/python.exe -B scripts/state_sync.py check`
  - `& .venv/Scripts/python.exe -B scripts/check_docs_drift.py`
- 证据路径：
  - `docs/verification/t0/T0_ACCEPTANCE.md`
  - `docs/verification/t0/review_2026-11-15.md`
  - `docs/verification/t0/a-01/summary.md`
  - `docs/verification/t0/a-02/summary.md`
  - `docs/verification/t0/wp-13/ADR-007_DECISION.md`
  - `docs/verification/t0/wp-13/walkthrough.md`
  - `docs/verification/t0/wp-13/screenshots.json`
  - `docs/verification/t0/e2e/runs_summary.json`
  - `docs/verification/t0/e2e/e2e_run_2026-11-15.log`
  - `docs/verification/t0/g6-t0/2026-11-15/run_1.verify.log`
  - `docs/verification/t0/g6-t0/2026-11-15/run_2.verify.log`
  - `docs/verification/t0/g6-t0/2026-11-15/run_3.verify.log`
  - `docs/verification/t0/full_suite_2026-11-15.log`

### `T-WP-01-001` T0 WP-01 仓库与环境锁定

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-G0-001`
- 更新时间：2026-11-10T22:16:00+08:00
- 阻塞：无
- 验收标准：
  - .venv 由 uv 托管 CPython 3.11.16 创建；sys.version 含 3.11.16 且 platform.architecture()[0] 为 64bit
  - 矩阵内 16 个直接 pin 与 SQLite 逐项核对；uv 工具版本偏差单独记录原因，无静默升级
  - httpx2==2.16.0 仅在用户 2026-11-10 批准后安装，并记录 starlette 1.10.0 的 TestClient 约束
  - requirements.lock 锁定 58 个包；干净环境从锁文件复现安装并 TestClient 200
  - TestClient 最小端点返回 200；starlette 1.10.0 与矩阵一致、不回退；8 个模块导入与 numpy [2.0.2,2.7) 区间通过
  - .venv 体积与耗时实测并对照矩阵估算；超出估算的偏差如实记录，不用估算值回填
  - researchflow/ 仍只有 .gitkeep；未写业务代码、未建数据库、未写 API、未做模板；证据齐全
- 测试命令：
  - `& .venv/Scripts/python.exe -c "import sys,platform;print(sys.version,platform.architecture()[0])"`
  - `uv pip check --python .venv/Scripts/python.exe`
  - `& .venv/Scripts/python.exe -c "import fastapi,pydantic,networkx,pandas,sklearn,cryptography,streamlit,pytest,numpy,scipy"`
  - `uv pip install -r requirements.lock --python .venv/Scripts/python.exe`
  - `& .venv/Scripts/python.exe docs/verification/t0/wp-01/make_evidence.py`
- 证据路径：
  - `requirements.in`
  - `requirements.lock`
  - `docs/verification/t0/wp-01/WP-01_REPORT.md`
  - `docs/verification/t0/wp-01/env_fingerprint.json`
  - `docs/verification/t0/wp-01/dependency_resolution.txt`
  - `docs/verification/t0/wp-01/dependency_resolution_dryrun.log`
  - `docs/verification/t0/wp-01/install.log`
  - `docs/verification/t0/wp-01/install_httpx2.log`
  - `docs/verification/t0/wp-01/venv_cache_failure.log`
  - `docs/verification/t0/wp-01/lockfile.txt`
  - `docs/verification/t0/wp-01/pip_check.log`
  - `docs/verification/t0/wp-01/pip_list.log`
  - `docs/verification/t0/wp-01/testclient_smoke.log`
  - `docs/verification/t0/wp-01/starlette_resolution.txt`
  - `docs/verification/t0/wp-01/version_combo.log`
  - `docs/verification/t0/wp-01/startup.log`
  - `docs/verification/t0/wp-01/clean_room_install.log`
  - `docs/verification/t0/wp-01/size_and_timing.md`
  - `docs/verification/t0/wp-01/make_evidence.py`
  - `docs/verification/t0/wp-01/make_evidence.log`
  - `docs/verification/t0/wp-01/state_sync.log`
  - `docs/verification/t0/wp-01/30_wp01_acceptance.md`
  - `docs/verification/t0/wp-01/state_sync_acceptance.log`

### `T-WP-02-001` T0 WP-02 核心契约落地（schema → Pydantic/API）

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-01-001`
- 更新时间：2026-11-10T22:45:00+08:00
- 阻塞：无
- 验收标准：
  - 5 份冻结 schema 落成 Pydantic v2 模型；properties/required/enum/const/pattern/additionalProperties 与 schema 逐节点一致
  - 72 个冻结用例在模型层的接受/拒绝结论与 schema 层完全一致（5 正例接受，67 反例拒绝），且反例断言拒绝原因
  - schema 无法表达的跨字段约束在模型层实现：level→producer/kind、SEM-NS-01、SEM-VR-01、SEM-VR-02
  - 重复键与 NaN/Infinity 在 JSON 层拒绝，不进入模型
  - API 绑定 TaskSpec 创建；422 统一返回 SCHEMA_INVALID + field_path + correlation_id，dataset_ref 字符串形态与文档文案一致
  - 按决议 8 不注册 POST /recover，访问返回 404；幂等同键同体 201、同键异体 409
  - validate_contracts.py 与全量 pytest 仍 exit 0；证据齐全；未实现部分（状态机/持久化/其余端点）已如实标注
- 测试命令：
  - `& .venv/Scripts/python.exe scripts/validate_contracts.py --selftest`
  - `& .venv/Scripts/python.exe scripts/validate_contracts.py`
  - `& .venv/Scripts/python.exe scripts/check_model_parity.py`
  - `& .venv/Scripts/python.exe -m pytest tests -q`
- 证据路径：
  - `researchflow/contracts/models.py`
  - `researchflow/contracts/parsing.py`
  - `researchflow/api/app.py`
  - `scripts/check_model_parity.py`
  - `tests/test_contract_models.py`
  - `tests/test_api_422.py`
  - `conftest.py`
  - `docs/verification/t0/wp-02/WP-02_REPORT.md`
  - `docs/verification/t0/wp-02/model_parity.json`
  - `docs/verification/t0/wp-02/model_parity.log`
  - `docs/verification/t0/wp-02/schema_validation.log`
  - `docs/verification/t0/wp-02/contracts_selftest.log`
  - `docs/verification/t0/wp-02/model_validation.log`
  - `docs/verification/t0/wp-02/api_422.log`
  - `docs/verification/t0/wp-02/full_suite.log`
  - `docs/verification/t0/wp-02/40_wp02_acceptance.md`
  - `docs/verification/t0/wp-02/state_sync.log`
  - `tests/test_api_idempotency.py`
  - `reports/remediation/logs/10_api_pytest_before_fullaccess.log`
  - `reports/remediation/logs/21_full_pytest_fullaccess.log`
  - `reports/remediation/P0_TEST_REPORT.md`
  - `reports/remediation/P0_CHANGELOG.md`

### `T-WP-03-001` T0 WP-03 SQLite 迁移、StateMachine 唯一写入口与双事务审计

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-02-001`
- 更新时间：2026-11-14T18:40:00+08:00
- 阻塞：无
- 验收标准：
  - 7 表 DDL（tasks/nodes/evidence/evidence_invalidations/audit_log/idempotency_keys/schema_migrations）按 06 §1.3/§5 基线落地；task_spec_json 与 §12-7 收紧两项偏离已在 00_decisions.md 记录
  - 迁移可重复、checksum 不符 fail-closed、失败全回滚；真实 SQLite 测试通过
  - StateMachine.transition() 是唯一改变已有状态的公开入口；create_initial() 是唯一创建入口；仓储无公开裸写方法
  - 合法迁移状态更新与 audit_log(OK) 同事务；失败回滚后 DENIED 仍存在；审计二次失败写结构化 stderr 并抛 AuditWriteFailed
  - 直接 SQL 更新/插入/删除被触发器拒绝；断言触发器名，目标行状态未变
  - INVALIDATED→READY 三条件守卫各失败一次，原因分别为 PLAN_FILE_MISSING、PLAN_HASH_MISMATCH、PLAN_FREEZE_RECORD_MISSING、PLAN_FROZEN_AFTER_RERUN；三条件全满足的正例通过
  - JCS 键序/astral/数字向量通过；同键同体 201、同键异体 409；未带 key 允许创建
  - API 201/409/422/404 回归；GET 重启后读取同一 SQLite 文件；/recover 仍 404
  - 定向 87 passed；全量 217 passed（full-access 补充运行；workspace-write 因 BLK-003 在 tmp_path 创建阶段失败，未写成通过）
  - 2026-11-14 复测：定向 87 passed、全量 217 passed，均 exit 0（危险全权限会话；不写成 workspace-write 通过），日志 docs/verification/t0/wp-03/pytest_targeted_2026-11-14.log 与 pytest_full_2026-11-14.log
  - 未修改冻结件、未把 P9/P10 当输入、未 commit
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/test_jcs.py tests/test_persistence_migrations.py tests/test_state_machine.py tests/test_audit_dual_transaction.py tests/test_direct_write_guard.py tests/test_invalidated_guard.py tests/test_idempotency_sqlite.py tests/test_api_sqlite.py tests/test_api_422.py tests/test_api_idempotency.py -q -p no:cacheprovider --basetemp=runtime/pytest-tmp`
  - `& .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp=runtime/pytest-tmp`
  - `& .venv/Scripts/python.exe docs/verification/t0/wp-03/make_evidence.py`
  - `& .venv/Scripts/python.exe scripts/state_sync.py validate`
  - `& .venv/Scripts/python.exe scripts/state_sync.py render`
  - `& .venv/Scripts/python.exe scripts/state_sync.py check`
- 证据路径：
  - `docs/verification/t0/wp-03/00_decisions.md`
  - `docs/verification/t0/wp-03/01_step1_plan.md`
  - `docs/verification/t0/wp-03/transitions.jsonl`
  - `docs/verification/t0/wp-03/illegal.log`
  - `docs/verification/t0/wp-03/direct_write.log`
  - `docs/verification/t0/wp-03/audit_log.jsonl`
  - `docs/verification/t0/wp-03/denied_survives_rollback.log`
  - `docs/verification/t0/wp-03/audit_degraded_stderr.log`
  - `docs/verification/t0/wp-03/invalidated_guard.log`
  - `docs/verification/t0/wp-03/pytest_targeted.log`
  - `docs/verification/t0/wp-03/pytest_full.log`
  - `docs/verification/t0/wp-03/make_evidence.log`
  - `docs/verification/t0/wp-03/make_evidence.py`
  - `docs/verification/t0/wp-03/contracts_validation.log`
  - `docs/verification/t0/wp-03/blk003_workspace_write_failure.md`
  - `researchflow/persistence/db.py`
  - `researchflow/persistence/schema_sql.py`
  - `researchflow/persistence/migrations.py`
  - `researchflow/persistence/repositories.py`
  - `researchflow/persistence/idempotency.py`
  - `researchflow/orchestration/transitions.py`
  - `researchflow/orchestration/state_machine.py`
  - `researchflow/orchestration/ports.py`
  - `researchflow/orchestration/creation.py`
  - `researchflow/orchestration/invariants.py`
  - `researchflow/contracts/encoding.py`
  - `researchflow/contracts/errors.py`
  - `researchflow/api/app.py`
  - `tests/wp03_support.py`
  - `tests/test_jcs.py`
  - `tests/test_persistence_migrations.py`
  - `tests/test_state_machine.py`
  - `tests/test_audit_dual_transaction.py`
  - `tests/test_direct_write_guard.py`
  - `tests/test_invalidated_guard.py`
  - `tests/test_idempotency_sqlite.py`
  - `tests/test_api_sqlite.py`
  - `tests/test_api_422.py`
  - `tests/test_api_idempotency.py`
  - `docs/verification/t0/wp-03/pytest_targeted_2026-11-14.log`
  - `docs/verification/t0/wp-03/pytest_full_2026-11-14.log`

### `T-WP-04-001` T0 WP-04 静态 DAG、图版本与 0002/0003 迁移

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-03-001`
- 更新时间：2026-11-14T19:20:00+08:00
- 阻塞：无
- 验收标准：
  - 合法图生成确定性拓扑序；同输入 graph_hash 稳定；图版本登记幂等、冲突拒绝
  - 环、自依赖、重复边、缺依赖、孤立节点、超规模全部按具体 code 拒绝
  - 迁移 0002 创建 graph_versions/reports/certificates/ingestion_log；0001 语句与 checksum 未改
  - 迁移 0003 扩展 audit_log 动作并保留历史行，重建索引与四个守卫触发器（保持 0001 触发顺序）
  - GET /tasks/{id}/graph 返回真实节点状态与必检项；未登记图返回 409
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp04_dag.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -m pytest tests/test_persistence_migrations.py -q -p no:cacheprovider`
- 证据路径：
  - `researchflow/dag/builder.py`
  - `researchflow/persistence/schema_sql_v2.py`
  - `researchflow/persistence/schema_sql_v3.py`
  - `researchflow/persistence/migrations.py`
  - `researchflow/persistence/records.py`
  - `researchflow/api/app.py`
  - `tests/t0/test_wp04_dag.py`
  - `tests/test_persistence_migrations.py`
  - `docs/verification/t0/wp-04/pytest.log`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`

### `T-WP-05-001` T0 WP-05 内置数据、模板注册表、参数与 Split Manifest

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-02-001`
- 更新时间：2026-11-14T19:20:00+08:00
- 阻塞：无
- 验收标准：
  - 内置合成数据可确定性重建，哈希与 registry 一致，许可 CC0-1.0，来源无第三方数据
  - 模板注册表白名单与参数强校验；未知模板/参数/模型按 code+field_path 拒绝
  - Split Manifest 确定性、含种子/划分/分组/行指纹/类别计数，无时间戳
  - 泄漏五规则 R1–R5 在 manifest 上可机器判定
  - 规则集 ruleset.v1.json 提供必检项、L2 容差、L3 覆盖与容差，ruleset_hash 稳定
- 测试命令：
  - `& .venv/Scripts/python.exe scripts/build_template_dataset.py`
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp05_templates.py -q -p no:cacheprovider`
- 证据路径：
  - `scripts/build_template_dataset.py`
  - `researchflow/templates/registry.py`
  - `researchflow/templates/datasets.py`
  - `researchflow/templates/split.py`
  - `researchflow/templates/estimators.py`
  - `researchflow/templates/data/registry.json`
  - `researchflow/templates/data/NOTICE.md`
  - `researchflow/rules/ruleset.v1.json`
  - `tests/t0/test_wp05_templates.py`
  - `docs/verification/t0/wp-05/pytest.log`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`

### `T-WP-06-001` T0 WP-06 受控执行器（子进程、独立 attempt 目录、超时与资源观测）

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-03-001`、`T-WP-05-001`
- 更新时间：2026-11-14T19:20:00+08:00
- 阻塞：无
- 验收标准：
  - 白名单外模板在派生进程前被拒；attempt 目录复用被拒；输入拷贝并校验哈希
  - 子进程最小环境、超时后进程树回收、内存超限终止、峰值工作集采样与 OS 口径交叉核对
  - 产物逐文件 SHA-256 与大小记录；执行器只记录观测，不发布完成裁决
  - worker 失败以非零退出与结构化 worker_error 透传，不被吞掉
  - 内存观测按进程树采样：venv python.exe 是启动器，已采样其真实解释器子进程；200 MB 真实分配校准测试通过，max_memory_mb 由真实读数驱动；worker_pids/kill_verified 入 E2
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp06_executor.py -q -p no:cacheprovider`
- 证据路径：
  - `researchflow/execution/executor.py`
  - `researchflow/execution/worker.py`
  - `researchflow/execution/sampler.py`
  - `researchflow/execution/env.py`
  - `tests/t0/test_wp06_executor.py`
  - `docs/verification/t0/wp-06/pytest.log`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`
  - `docs/verification/t0/review_2026-11-14.md`

### `T-WP-07-001` T0 WP-07 Collector：单调序号、事件幂等、哈希链与内容寻址载荷

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-06-001`
- 更新时间：2026-11-14T19:20:00+08:00
- 阻塞：无
- 验收标准：
  - event_seq 在写事务内连续分配；同 attempt 重复投递不新增证据且 delivery_seq 递增
  - 同事件键异内容返回 CHAIN_CONTENT_CONFLICT 并写 DENIED 审计
  - prev_hash/chain_hash 链、payload 哈希、等级-写者映射可离线复算；缺口/篡改可发现
  - E3 只能由 Verifier capability 写入；E0 不推进 Task/Node 状态
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp07_collector.py -q -p no:cacheprovider`
- 证据路径：
  - `researchflow/evidence/collector.py`
  - `researchflow/evidence/chain.py`
  - `tests/t0/test_wp07_collector.py`
  - `docs/verification/t0/wp-07/pytest.log`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`

### `T-WP-08-001` T0 WP-08 Gate：必检覆盖、缺口码、规则绑定与 stale 判定

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-07-001`
- 更新时间：2026-11-14T19:20:00+08:00
- 阻塞：无
- 验收标准：
  - 必检项只由规则集声明等级/类型满足；E0/E1 永不满足执行类
  - 旧 attempt 证据记 GAP_STALE_ATTEMPT；invalidated 证据记 GAP_EVIDENCE_STALE 且不删除
  - 规则版本不符、图缺失/哈希不符、链断、产物缺失/哈希错均使 Gate 失败
  - 覆盖计数与报告 required/passed/missing 一致；l3_coverage 由 metric_source 覆盖计算
  - 代码硬编码执行类必检下限（≥E2，metric_source=E3）；规则集被改弱时报 GAP_RULESET_INVALID
  - metric_source 要求 E3 绑定当前 split manifest、L3 进程与 L3 目录；未绑定记 GAP_E3_NOT_BOUND
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp08_gate.py -q -p no:cacheprovider`
- 证据路径：
  - `researchflow/gate/gate.py`
  - `researchflow/rules/ruleset.v1.json`
  - `tests/t0/test_wp08_gate.py`
  - `docs/verification/t0/wp-08/pytest.log`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`
  - `docs/verification/t0/review_2026-11-14.md`

### `T-WP-09-001` T0 WP-09 Verifier L1/L2：过程完整性与结果自洽

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-07-001`
- 更新时间：2026-11-15T10:40:30+08:00
- 阻塞：无
- 验收标准：
  - L1 重算链、产物哈希、attempt 结果与目录复用；失败给出具体 L1_* code
  - L2 独立纯 Python 重算指标并与上报值比对；y_true 与数据真实标签逐行一致
  - 泄漏五规则各自可命中并给规则码；L2 失败不签发凭证
  - 2026-11-15 A-01：L1 当前 attempt 交叉核对 job/NodeSpec/E2 参数哈希，缺失或不一致分别以 L1_PARAMETERS_BINDING_INCOMPLETE / L1_PARAMETERS_BINDING_MISMATCH 拒绝
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp09_verifier_l12.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp09_verifier_l12.py tests/t0/test_wp10_verifier_l3.py -q -p no:cacheprovider`
- 证据路径：
  - `researchflow/verification/l1.py`
  - `researchflow/verification/l2.py`
  - `tests/t0/test_wp09_verifier_l12.py`
  - `docs/verification/t0/wp-09/pytest.log`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`
  - `docs/verification/t0/a-01/summary.md`
  - `docs/verification/t0/a-01/probe_report.json`
  - `docs/verification/t0/a-01/pytest_targeted.log`

### `T-WP-10-001` T0 WP-10 Verifier L3：新目录独立进程从原始数据重训

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-09-001`、`T-WP-06-001`
- 更新时间：2026-11-15T10:40:30+08:00
- 阻塞：无
- 验收标准：
  - L3 在新目录、独立子进程重跑 split+train，不读执行器预测作为输入
  - 隔离守卫拒绝执行器目录、本进程 PID、执行器产物作输入（伪 L3）
  - 比较 split_hash、逐行预测与指标容差；差异可归因；覆盖 = 通过节点/指标节点
  - E3 由 Verifier capability 写入，Gate 只接受 l3_status=PASS 的 live E3
  - 2026-11-15 A-01：L3 在创建验证目录/子进程前 preflight split 与全部 metric 节点参数绑定；失败返回 FAIL、coverage 0、无目录、无子进程，原因码 L3_PARAMETERS_BINDING_MISMATCH / ..._INCOMPLETE
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp10_verifier_l3.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -B docs/verification/t0/a-01/parameter_binding_probe.py`
- 证据路径：
  - `researchflow/verification/l3.py`
  - `researchflow/verification/verifier.py`
  - `tests/t0/test_wp10_verifier_l3.py`
  - `docs/verification/t0/wp-10/pytest.log`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`
  - `docs/verification/t0/a-01/summary.md`
  - `docs/verification/t0/a-01/probe_report.json`
  - `docs/verification/t0/a-01/pytest_targeted.log`

### `T-WP-11-001` T0 WP-11 Ed25519、JCS 载荷白名单、Merkle 与信任锚

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-07-001`
- 更新时间：2026-11-14T19:20:00+08:00
- 阻塞：无
- 验收标准：
  - RFC 8032 标准向量通过；报告/证书域分离，改载荷或换密钥验签失败
  - 签名载荷字段白名单常量；schema_version 参与签名且未知 MAJOR 拒绝
  - Merkle 根与包含证明可复算、篡改叶失败；私钥不进入 bundle/日志/报告
  - 证书仅在报告 VERIFIED、必检缺口 0、L3 覆盖达标、链有效、E2 环境指纹存在时签发
  - 证书 issued_at 不早于报告 issued_at；Verifier 与 verify_bundle 均校验
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp11_signing.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_pipeline_verified.py -q -p no:cacheprovider`
- 证据路径：
  - `researchflow/signing/keys.py`
  - `researchflow/signing/payloads.py`
  - `researchflow/signing/merkle.py`
  - `researchflow/verification/verifier.py`
  - `tests/t0/test_wp11_signing.py`
  - `tests/t0/test_pipeline_verified.py`
  - `docs/verification/t0/wp-11/pytest.log`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`
  - `docs/verification/t0/review_2026-11-14.md`

### `T-WP-12-001` T0 WP-12 Evidence Bundle 与独立 verify_bundle

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-10-001`、`T-WP-11-001`
- 更新时间：2026-11-14T19:20:00+08:00
- 阻塞：无
- 验收标准：
  - Bundle 含任务/节点/图/证据/载荷/产物/失效/规则集/报告/证书/历史/清单
  - verify_bundle 只依赖 stdlib+cryptography，不 import 产品包；信任锚必须包外
  - 重算清单哈希、证据链、Merkle、报告/证书签名，并从包内数据重新执行 Gate 判定
  - 缺件、篡改载荷、伪签名、错误/包内信任锚均按具体 code 拒绝；私钥不在包内
  - G6-T0 记录：隔离目录 + 外部信任锚 + 三次真包通过
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp12_bundle.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -E docs/verification/t0/e2e/run_1/isolated-verifier/verify_bundle.py --bundle docs/verification/t0/e2e/run_1/isolated-verifier/bundle --trust-store docs/verification/t0/e2e/run_1/isolated-verifier/trust_store.json`
- 证据路径：
  - `verify_bundle.py`
  - `researchflow/bundle/export.py`
  - `tests/t0/test_wp12_bundle.py`
  - `docs/verification/t0/wp-12/pytest.log`
  - `docs/verification/t0/g6-t0/env_isolation.log`
  - `docs/verification/t0/g6-t0/true_bundle.verify.log`
  - `docs/verification/t0/g6-t0/trust_store.json`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`
  - `docs/verification/t0/review_2026-11-14.md`

### `T-WP-13-001` T0 WP-13 最小工作台四视图（只读消费真实 API）

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-08-001`、`T-WP-12-001`
- 更新时间：2026-11-15T10:46:04+08:00
- 阻塞：无
- 验收标准：
  - 任务/DAG/证据/报告四视图全部来自真实 REST API，含缺口、stale 与报告状态
  - 不直接连接数据库、不写状态/证据、不伪造数据；API 不可达时显式报错
  - Streamlit AppTest 对真实 API 数据运行通过；2026-11-15 已补真实 API 四视图截图、DOM 文本快照与 walkthrough
  - 2026-11-15 A-03：任务/DAG/证据/报告四视图 + API 不可达截图由真实 API/Streamlit 数据捕获，screenshots.json verdict=PASS；ADR-007 已于 2026-11-15 由用户批准为 ACCEPTED，正式记录见 T-A03-001 / ADR-007_DECISION.md
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp13_workbench.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -B docs/verification/t0/wp-13/capture_screenshots.py`
- 证据路径：
  - `researchflow/workbench/app.py`
  - `tests/t0/test_wp13_workbench.py`
  - `docs/verification/t0/wp-13/pytest.log`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`
  - `docs/verification/t0/wp-13/walkthrough.md`
  - `docs/verification/t0/wp-13/screenshots.json`
  - `docs/verification/t0/wp-13/pytest_2026-11-15.log`
  - `docs/verification/t0/wp-13/ADR-007_DECISION_PROPOSAL.md`
  - `docs/verification/t0/wp-13/ADR-007_DECISION.md`

### `T-WP-14-001` T0 WP-14 三次离线端到端与独立验签

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-R-001`、`T-WP-12-001`
- 更新时间：2026-11-15T10:40:30+08:00
- 阻塞：无
- 验收标准：
  - run_1..run_3 在隔离目录真实运行：创建→执行→验证→失效→重跑→再验证→完成→导出→离线验签
  - 三次运行终态/覆盖/L3 覆盖/证据数/失效数/验签结果一致，原始日志可定位
  - 断网意图与无模型：无外呼代码、代理黑洞、无模型客户端，已有披露
  - 并发上限 2 与 16GB 主机资源实测，未测部分不宣称
  - 独立只读审查 A 类清零；B 类修复或披露；旧 e2e 证据归档不删除
  - 2026-11-15 复跑：A-01/A-02 修复后重新生成 run_1..3，consistent=true；三次 32 证据/16 失效/必检 8/8/L3 1.0；仓库 verify_bundle.py + 包外 trust_store 三次 VERIFIED，exit 0；旧 e2e 归档 superseded_2026-11-15_pre_a01
- 测试命令：
  - `& .venv/Scripts/python.exe scripts/e2e_run.py --runs 3 --out docs/verification/t0/e2e`
  - `& .venv/Scripts/python.exe scripts/measure_concurrency.py`
- 证据路径：
  - `scripts/e2e_run.py`
  - `scripts/measure_concurrency.py`
  - `docs/verification/t0/e2e/runs_summary.json`
  - `docs/verification/t0/e2e/e2e_report.md`
  - `docs/verification/t0/e2e/concurrency.json`
  - `docs/verification/t0/e2e/run_1/logs/run_summary.json`
  - `docs/verification/t0/e2e/run_2/logs/run_summary.json`
  - `docs/verification/t0/e2e/run_3/logs/run_summary.json`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`
  - `docs/verification/t0/review_2026-11-14.md`
  - `docs/verification/t0/full_suite_2026-11-14_final.log`
  - `docs/verification/t0/pipeline_tests.log`
  - `docs/verification/t0/e2e/superseded_2026-11-15_pre_a01/SUPERSEDED_NOTICE.md`
  - `docs/verification/t0/e2e/e2e_run_2026-11-15.log`
  - `docs/verification/t0/g6-t0/2026-11-15/run_1.verify.log`
  - `docs/verification/t0/g6-t0/2026-11-15/run_2.verify.log`
  - `docs/verification/t0/g6-t0/2026-11-15/run_3.verify.log`

### `T-WP-R-001` T0 WP-R FR-010 最小切片：失效传播、确定性计划与保守重跑

- 阶段：`T0`
- 状态：`DONE` 完成
- 依赖：`T-WP-13-001`
- 更新时间：2026-11-15T10:40:30+08:00
- 阻塞：无
- 验收标准：
  - 上游变化只使受影响后代 INVALIDATED；无关节点保持 VERIFIED
  - 计划为纯函数，同输入同 plan_hash；正文无时间戳；内容寻址写入不可改写
  - INVALIDATED→READY 三条件守卫各有一条 DENIED，原因分别为文件缺失/哈希不符/未冻结/冻结晚于重跑
  - 受影响后代以新 attempt 保守重跑并重新验证；包内 stale 证据不放行
  - 2026-11-15 A-02：invalidate/rerun 在任何状态迁移、计划写入或执行前运行只读 L1；坏链或缺失 attempt 证据以 RECOVERY_NOT_SAFE + 具体 L1_* 原因拒绝，不新增状态边、不实现 T1 Recovery
- 测试命令：
  - `& .venv/Scripts/python.exe -m pytest tests/t0/test_wp_recovery.py -q -p no:cacheprovider`
  - `& .venv/Scripts/python.exe -B docs/verification/t0/a-02/recovery_chain_probe.py`
- 证据路径：
  - `researchflow/recovery/impact.py`
  - `researchflow/recovery/plan.py`
  - `researchflow/recovery/service.py`
  - `tests/t0/test_wp_recovery.py`
  - `docs/verification/t0/wp-r/pytest.log`
  - `docs/verification/t0/00_implementation_decisions.md`
  - `docs/verification/t0/WP_INDEX.md`
  - `docs/verification/t0/a-02/summary.md`
  - `docs/verification/t0/a-02/probe_report.json`
  - `docs/verification/t0/a-02/pytest_restart.log`
  - `docs/verification/t0/a-02/pytest_regression.log`

## 3. 阶段门禁明细

### `G0` · 规格冻结

- 状态：`PASS` 通过
- 更新时间：2026-11-10T00:45:00+08:00
- 裁决人：用户
- 裁决时间：2026-11-10
- 验收条件：
  - 数据模型、状态机、API、错误码、证据等级和规则版本确定
- 证据路径：
  - `docs/G0/01_BASELINE_AND_TERMS.md`
  - `docs/PRD/02_REQUIREMENT_TRACEABILITY.md`
  - `docs/PRD/03_PRD_T0.md`
  - `docs/design/04_ARCHITECTURE.md`
  - `docs/design/05_CONTRACTS_AND_STATES.md`
  - `docs/design/06_DATA_AND_API.md`
  - `docs/design/07_T0_PLAN_AND_GATES.md`
  - `docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md`
  - `contracts/README.md`
  - `contracts/taskspec.schema.json`
  - `contracts/nodespec.schema.json`
  - `contracts/evidencerecord.schema.json`
  - `contracts/verificationreport.schema.json`
  - `contracts/completioncertificate.schema.json`
  - `docs/verification/g0/09_dependency_matrix.md`
  - `docs/verification/g0/17_version_freeze_report.md`
  - `docs/verification/g0/18_git_rollback.log`
  - `docs/verification/g0/19_g0_pass_decision.md`
  - `docs/verification/g0/20_g0_pass_recheck.log`

### `G1` · 纵向闭环

- 状态：`PASS` 通过
- 更新时间：2026-11-15T10:41:24+08:00
- 裁决人：实施会话 + 复核（2026-11-15 修复后重跑三次 e2e）
- 裁决时间：2026-11-14
- 验收条件：
  - 无模型、离线、单任务从提交到凭证全链跑通
- 证据路径：
  - `docs/verification/t0/e2e/runs_summary.json`
  - `docs/verification/t0/e2e/e2e_report.md`
  - `docs/verification/t0/e2e/run_1/logs/run_summary.json`
  - `docs/verification/t0/e2e/run_2/logs/run_summary.json`
  - `docs/verification/t0/e2e/run_3/logs/run_summary.json`
  - `docs/verification/t0/review_2026-11-14.md`
  - `docs/verification/t0/a-01/summary.md`
  - `docs/verification/t0/a-02/summary.md`
  - `docs/verification/t0/e2e/e2e_run_2026-11-15.log`
  - `docs/verification/t0/review_2026-11-15.md`

### `G2` · 证据可信

- 状态：`PASS` 通过
- 更新时间：2026-11-15T10:41:24+08:00
- 裁决人：实施会话 + 复核（2026-11-15 A-02 恢复拒绝负例）
- 裁决时间：2026-11-14
- 验收条件：
  - E0 不推动状态
  - E2 由 Collector 观察
  - 权限拒绝通过
  - stale 证据不满足必检项且不删除
- 证据路径：
  - `docs/verification/t0/wp-07/pytest.log`
  - `docs/verification/t0/wp-08/pytest.log`
  - `docs/verification/t0/wp-r/pytest.log`
  - `docs/verification/t0/wp-03/denied_survives_rollback.log`
  - `docs/verification/t0/e2e/run_1/logs/evidence_after_invalidation.json`
  - `docs/verification/t0/review_2026-11-14.md`
  - `docs/verification/t0/a-01/summary.md`
  - `docs/verification/t0/a-02/summary.md`
  - `docs/verification/t0/a-02/pytest_restart.log`
  - `docs/verification/t0/review_2026-11-15.md`

### `G3` · L3 独立重执行

- 状态：`PASS` 通过
- 更新时间：2026-11-15T10:41:24+08:00
- 裁决人：实施会话 + 复核（2026-11-15 A-01 绑定负例与三次 e2e）
- 裁决时间：2026-11-14
- 验收条件：
  - 新目录、独立进程、真实重跑
  - 假复现负例拒绝
- 证据路径：
  - `docs/verification/t0/wp-10/pytest.log`
  - `docs/verification/t0/e2e/e2e_report.md`
  - `docs/verification/t0/e2e/run_1/logs/verify_2.json`
  - `docs/verification/t0/review_2026-11-14.md`
  - `docs/verification/t0/a-01/summary.md`
  - `docs/verification/t0/a-01/probe_report.json`
  - `docs/verification/t0/review_2026-11-15.md`

### `G4` · 动态调度/恢复

- 状态：`NOT_STARTED` 未开始
- 更新时间：2026-11-08T11:27:46+08:00
- 验收条件：
  - 资源变化改变调度
  - 失败能执行恢复计划
- 证据路径：
  - 无

### `G5` · 实验数据可信

- 状态：`NOT_STARTED` 未开始
- 更新时间：2026-11-08T11:27:46+08:00
- 验收条件：
  - 预注册、冻结哈希、四方案、原始 JSON 和统计脚本齐全
- 证据路径：
  - 无

### `G6` · 外部复核

- 状态：`IN_PROGRESS` 进行中
- 更新时间：2026-11-15T10:41:24+08:00
- 裁决人：实施会话 + 复核（仅 G6-T0；2026-11-15 三次离线验签）
- 裁决时间：2026-11-14
- 验收条件：
  - G6-T0（T0 出口）：独立目录 + 包外信任锚离线验签真包通过 —— 已满足
  - G6 完整版（T1）：五类负例矩阵（改 payload、换公钥、删 split、改状态、破签名）—— NOT_STARTED，不提前通过
- 证据路径：
  - `docs/verification/t0/g6-t0/env_isolation.log`
  - `docs/verification/t0/g6-t0/true_bundle.verify.log`
  - `docs/verification/t0/g6-t0/trust_store.json`
  - `docs/verification/t0/g6-t0/run_1.verify.json`
  - `docs/verification/t0/g6-t0/run_2.verify.json`
  - `docs/verification/t0/g6-t0/run_3.verify.json`
  - `docs/verification/t0/review_2026-11-14.md`
  - `docs/verification/t0/g6-t0/2026-11-15/run_1.verify.log`
  - `docs/verification/t0/g6-t0/2026-11-15/run_2.verify.log`
  - `docs/verification/t0/g6-t0/2026-11-15/run_3.verify.log`
  - `docs/verification/t0/e2e/superseded_2026-11-15_pre_a01/SUPERSEDED_NOTICE.md`
  - `docs/verification/t0/review_2026-11-15.md`

### `G7` · Harness 适配

- 状态：`NOT_STARTED` 未开始
- 更新时间：2026-11-08T11:27:46+08:00
- 验收条件：
  - 固定版本插件、工具、事件映射和状态回传契约通过
- 证据路径：
  - 无

## 4. 伪代码阶段明细

> 与研发任务、阶段门禁使用不同状态枚举；`ACCEPTED` 仅指设计件验收。

### `P1` · 契约对齐与配置基座

- 状态：`ACCEPTED` 已验收
- 模块：`M01_contracts`、`M03_config_env`
- 验收依据：用户 2026-11-11 验收 P1（STAGE_LOG §P1）；验收证据仅限现有设计件与阶段日志，不含无法恢复的历史决议正文。
- 更新时间：2026-11-11T22:58:00+08:00
- 阻塞：无
- 验收标准：
  - M01/M03 设计件存在；P1 用户验收记录见 STAGE_LOG §P1 与 INDEX。
  - OQ-P1-03、OQ-P1-05 的原问题与裁决正文缺失，已标 NEEDS_CONFIRMATION，不得作为先例。
- 交付物：
  - `design/pseudocode/M01_contracts`
  - `design/pseudocode/M03_config_env`
  - `design/pseudocode/STAGE_LOG.md`
  - `design/pseudocode/INDEX.md`
- 证据路径：
  - `design/pseudocode/STAGE_LOG.md`
  - `design/pseudocode/INDEX.md`
  - `design/pseudocode/M01_contracts/MODULE.md`
  - `design/pseudocode/M03_config_env/MODULE.md`

### `P2` · 持久层与状态机

- 状态：`ACCEPTED` 已验收
- 模块：`M02_state_machine`
- 验收依据：用户 2026-11-12 指令按 C→B 顺序推进；经只读完整性/一致性审查，M02 的 10 文件 / 5,991 行、MODULE.md、NEGATIVE_TESTS.md（66 条负例 ID）齐全，文件数与 INDEX/STAGE_LOG 一致，.py 全部通过 ast.parse，>800 行文件已登记函数索引；验收仅指设计件，不表示运行时实现，§12-2/§12-6/§12-7/§12-8 仍 OPEN，WP-03 不得以本阶段已验收启动。详见 reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md。
- 更新时间：2026-11-12T17:41:01+08:00
- 阻塞：无
- 验收标准：
  - M02 伪代码与负例存在；用户 2026-11-12 按 C 指令验收设计件。
  - §12-2、§12-6、§12-7、§12-8 仍 OPEN；WP-03 不得以本阶段已验收启动。
- 交付物：
  - `design/pseudocode/M02_state_machine`
- 证据路径：
  - `design/pseudocode/M02_state_machine/MODULE.md`
  - `design/pseudocode/M02_state_machine/NEGATIVE_TESTS.md`
  - `design/pseudocode/STAGE_LOG.md`
  - `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`

### `P3` · DAG 与执行器

- 状态：`ACCEPTED` 已验收
- 模块：`M04_dag`、`M05_executor`
- 验收依据：用户 2026-11-12 指令按 C→B 顺序推进；经只读完整性/一致性审查，M04/M05 的 14 文件 / 7,858 行、MODULE.md、NEGATIVE_TESTS.md（88 条负例 ID）齐全，文件数与 INDEX/STAGE_LOG 一致，.py 全部通过 ast.parse，>800 行文件已登记函数索引；验收仅指设计件，不表示运行时实现，OQ-P3 开放项不因此关闭。详见 reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md。
- 更新时间：2026-11-12T17:41:01+08:00
- 阻塞：无
- 验收标准：
  - M04/M05 设计件与负例存在；用户 2026-11-12 按 C 指令验收设计件。
  - OQ-P3 多条仍 OPEN/DEFERRED；验收不关闭开放问题。
- 交付物：
  - `design/pseudocode/M04_dag`
  - `design/pseudocode/M05_executor`
- 证据路径：
  - `design/pseudocode/M04_dag/MODULE.md`
  - `design/pseudocode/M05_executor/MODULE.md`
  - `design/pseudocode/STAGE_LOG.md`
  - `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`

### `P4` · 模板与证据链

- 状态：`ACCEPTED` 已验收
- 模块：`M06_templates`、`M07_evidence`
- 验收依据：用户 2026-11-12 指令按 C→B 顺序推进；经只读完整性/一致性审查，M06/M07 的 14 文件 / 6,109 行、MODULE.md、NEGATIVE_TESTS.md（123 条负例 ID）齐全，文件数与 INDEX/STAGE_LOG 一致，.py 全部通过 ast.parse，>800 行文件已登记函数索引；验收仅指设计件，不表示运行时实现，OQ-P4 开放项不因此关闭。详见 reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md。
- 更新时间：2026-11-12T17:41:01+08:00
- 阻塞：无
- 验收标准：
  - M06/M07 设计件与负例存在；用户 2026-11-12 按 C 指令验收设计件。
  - OQ-P4-01（E3 写入路径）等仍 OPEN；验收不表示 E3 已实现。
- 交付物：
  - `design/pseudocode/M06_templates`
  - `design/pseudocode/M07_evidence`
- 证据路径：
  - `design/pseudocode/M06_templates/MODULE.md`
  - `design/pseudocode/M07_evidence/MODULE.md`
  - `design/pseudocode/STAGE_LOG.md`
  - `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`

### `P5` · 门控与三级验证

- 状态：`ACCEPTED` 已验收
- 模块：`M08_gate`、`M09_verifier_l12`、`M10_verifier_l3`
- 验收依据：用户 2026-11-12 指令按 C→B 顺序推进；经只读完整性/一致性审查，M08–M10 的 16 文件 / 7,923 行、MODULE.md、NEGATIVE_TESTS.md（151 条负例 ID）齐全，文件数与 INDEX/STAGE_LOG 一致，.py 全部通过 ast.parse，>800 行文件已登记函数索引；验收仅指设计件，不表示运行时实现，OQ-P5 开放项不因此关闭。详见 reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md。
- 更新时间：2026-11-12T17:41:01+08:00
- 阻塞：无
- 验收标准：
  - M08–M10 设计件与负例存在；用户 2026-11-12 按 C 指令验收设计件。
  - OQ-P5 多条仍 OPEN/DEFERRED；L3 未真实重跑，验收不表示 L1/L2/L3 已实现。
- 交付物：
  - `design/pseudocode/M08_gate`
  - `design/pseudocode/M09_verifier_l12`
  - `design/pseudocode/M10_verifier_l3`
- 证据路径：
  - `design/pseudocode/M08_gate/MODULE.md`
  - `design/pseudocode/M09_verifier_l12/MODULE.md`
  - `design/pseudocode/M10_verifier_l3/MODULE.md`
  - `design/pseudocode/STAGE_LOG.md`
  - `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`

### `P6` · 签名与离线凭证

- 状态：`ACCEPTED` 已验收
- 模块：`M11_signing`、`M12_bundle`
- 验收依据：用户 2026-11-12 指令按 C→B 顺序推进；经只读完整性/一致性审查，M11/M12 的 11 文件 / 7,584 行、MODULE.md、NEGATIVE_TESTS.md（153 条负例 ID）齐全，文件数与 INDEX/STAGE_LOG 一致，.py 全部通过 ast.parse，>800 行文件已登记函数索引；验收仅指设计件，不表示运行时实现，OQ-P6 开放项不因此关闭。详见 reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md。
- 更新时间：2026-11-12T17:41:01+08:00
- 阻塞：无
- 验收标准：
  - M11/M12 设计件与负例存在；用户 2026-11-12 按 C 指令验收设计件。
  - DC/SPA 签名载荷与证书字段仍有 OPEN 项；验收不表示签名/离线验签已实现。
- 交付物：
  - `design/pseudocode/M11_signing`
  - `design/pseudocode/M12_bundle`
- 证据路径：
  - `design/pseudocode/M11_signing/MODULE.md`
  - `design/pseudocode/M12_bundle/MODULE.md`
  - `design/pseudocode/STAGE_LOG.md`
  - `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`

### `P7` · 调度与定向恢复

- 状态：`ACCEPTED` 已验收
- 模块：`M13_scheduler`、`M14_recovery`
- 验收依据：用户 2026-11-12 指令按 C→B 顺序推进；经只读完整性/一致性审查，M13/M14 的 11 文件 / 6,576 行、MODULE.md、NEGATIVE_TESTS.md（76 条负例 ID）齐全，文件数与 INDEX/STAGE_LOG 一致，.py 全部通过 ast.parse，>800 行文件已登记函数索引；验收仅指设计件，不表示运行时实现，P7 属 T1，OQ-P7 开放项不因此关闭。详见 reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md。
- 更新时间：2026-11-12T17:41:01+08:00
- 阻塞：无
- 验收标准：
  - M13/M14 设计件与负例存在；用户 2026-11-12 按 C 指令验收设计件。
  - P7 属 T1 方向；STAGE_LOG 的 P7 条目为 2026-11-11 补登；验收不表示调度/恢复运行时已实现。
- 交付物：
  - `design/pseudocode/M13_scheduler`
  - `design/pseudocode/M14_recovery`
- 证据路径：
  - `design/pseudocode/M13_scheduler/MODULE.md`
  - `design/pseudocode/M14_recovery/MODULE.md`
  - `design/pseudocode/STAGE_LOG.md`
  - `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`

### `P8` · 六角色与知识库

- 状态：`ACCEPTED` 已验收
- 模块：`M17_agents`、`M18_knowledge`
- 验收依据：用户 2026-11-12 指令按 C→B 顺序推进；经只读完整性/一致性审查，M17/M18 的 15 文件 / 9,361 行、MODULE.md、NEGATIVE_TESTS.md（125 条负例 ID）齐全，文件数与 INDEX/STAGE_LOG 一致，.py 全部通过 ast.parse，>800 行文件已登记函数索引；验收仅指设计件，不表示运行时实现，P8 属 T1，OQ-P8 开放项不因此关闭。详见 reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md。
- 更新时间：2026-11-12T17:41:01+08:00
- 阻塞：无
- 验收标准：
  - M17/M18 设计件与负例存在；用户 2026-11-12 按 C 指令验收设计件。
  - P8 属 T1（FR-012/FR-013/FR-014）；OQ-P8 多条仍 OPEN/DEFERRED；验收不表示 Agent/知识库运行时已实现。
- 交付物：
  - `design/pseudocode/M17_agents`
  - `design/pseudocode/M18_knowledge`
- 证据路径：
  - `design/pseudocode/M17_agents/MODULE.md`
  - `design/pseudocode/M18_knowledge/MODULE.md`
  - `design/pseudocode/STAGE_LOG.md`
  - `reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`

### `P9` · DC/SPA 与 VAS

- 状态：`BLOCKED` 阻塞
- 模块：`M15_dcspa`、`M16_vas`
- 验收依据：并发重写产物已落盘，但来源、版本与接口一致性未确认；原始正文仍不可追溯，不得据此标 ACCEPTED。
- 更新时间：2026-11-11T22:58:00+08:00
- 阻塞：并发重写产物的来源/版本未确认；用户需裁决是否接受为设计稿；未运行测试、未验收。
- 验收标准：
  - 2026-11-11 22:53:54–55 有并发进程重写并落盘 6 个 .py；不是原始正文恢复。
  - 六个文件已逐项登记来源时间、SHA256 与行数；未运行 pytest、未导入被测模块、未验收。
- 交付物：
  - `design/pseudocode/M15_dcspa`
  - `design/pseudocode/M16_vas`
- 证据路径：
  - `design/pseudocode/M15_dcspa/MODULE.md`
  - `design/pseudocode/M15_dcspa/NEGATIVE_TESTS.md`
  - `design/pseudocode/M15_dcspa/orchestration/determinism/dc_eligibility.py`
  - `design/pseudocode/M15_dcspa/orchestration/determinism/dc_issuer.py`
  - `design/pseudocode/M15_dcspa/orchestration/determinism/spa_judge.py`
  - `design/pseudocode/M15_dcspa/orchestration/determinism/prr_ledger.py`
  - `design/pseudocode/M16_vas/MODULE.md`
  - `design/pseudocode/M16_vas/NEGATIVE_TESTS.md`
  - `design/pseudocode/M16_vas/orchestration/vas/risk_features.py`
  - `design/pseudocode/M16_vas/orchestration/vas/knapsack.py`
  - `design/pseudocode/M16_vas/orchestration/vas/strategies.py`
  - `reports/remediation/logs/00_baseline.txt`
  - `reports/remediation/logs/30_p9_missing_search.log`

### `P10` · 接入、实验与交付（M19）

- 状态：`BLOCKED` 阻塞
- 模块：`M19_api`
- 验收依据：文件存在不等于开发授权；P10 当前仅做现状登记。
- 更新时间：2026-11-11T22:58:00+08:00
- 阻塞：用户尚未确认 M19 是否为授权产物；暂缓扩大 P10 开发范围。
- 验收标准：
  - M19 现有 5 个 API .py；无 MODULE.md、NEGATIVE_TESTS.md、阶段日志与 OQ。
  - 仅登记现状；未获正式开发授权，不得删除或标 ACCEPTED。
- 交付物：
  - `design/pseudocode/M19_api`
- 证据路径：
  - `reports/remediation/logs/00_baseline.txt`
  - `reports/remediation/logs/30_p9_missing_search.log`

## 5. 阻塞项

### `BLK-001` Git 全局身份未配置

- 状态：`RESOLVED` 已解决
- 严重度：`MEDIUM` 中
- 描述：git config user.name 与 user.email 均为空，当前无法创建经身份确认的 commit。提交前必须由用户确认身份，不得由 Agent 自行配置。
- 影响任务：`T-G0-001`
- 打开时间：2026-11-08T11:27:46+08:00
- 处理记录：用户 2026-11-10 指令：仅在本仓库执行 git config --local，user.name=ResearchFlow Dev，user.email=dev@researchflow.local；未使用 --global，未改全局 .gitconfig，全局 user.name/user.email 仍为空。仓库级身份已用于 G0 规格基线提交，复核命令与结果见 docs/verification/g0/17_version_freeze_report.md。

### `BLK-002` 策划书基线版本待确认

- 状态：`RESOLVED` 已解决
- 严重度：`HIGH` 高
- 描述：文件名标注 v4.3.1，但文档内部封面、页眉、正文升级说明与 core 属性标题均为 v4.3.0；文档内 v4.3.1 字符串计数为 0。用户已于 2026-11-08 书面确认最终冻结基线（内部 v4.3.0 为内容基线，v4.3.1 仅为文件名标签）。证据见 docs/reference/SOURCE_REGISTER.md 与 docs/reference/CONFLICT_REPORT.md（C-001）。本条保留为历史登记；版本已决不等于 G0 已通过，G0 仍有 3 项待裁决。
- 影响任务：`T-DOCS-001`
- 打开时间：2026-11-08T11:27:46+08:00
- 处理记录：用户 2026-11-08 确认：以文档内部 v4.3.0 为内容基线，v4.3.1 为文件名标签；BLK-002 关闭（project_state schema 无 CLOSED 枚举，使用 RESOLVED 表示关闭）。severity 保留 HIGH 作为历史属性；DOCX 未修改、未改名、未移动；SOURCE_REGISTER 的禁止第二份副本规则继续有效。

### `BLK-003` 测试套件环境阻塞（workspace-write 临时目录/工作区子目录写入）

- 状态：`OPEN` 未解决
- 严重度：`MEDIUM` 中
- 描述：23 个用例在 workspace-write 下全部在 setUp 阶段失败，共 43 个 error，均为 PermissionError/WinError 5，无断言失败。用户 2026-11-08 用 DSH 权限诊断工具检查 D:\ResearchFlow-project\tmpavet2qv9，结论 NOT_THIS_CLASS：WRITE_DAC / WRITE_OWNER 均具备，无缺失权限、无需清理的第三方授权项；FIXED=0，未做任何改动，无需回滚。报告：C:\Users\Administrator\AppData\Local\ResearchFlow\acl-diagnostics\acl-report-559f7ffa05844dce8e62ba3238f77f3b.jsonl。机制：沙箱进程新建子目录时得到令牌默认权限，项目根上的沙箱授权未传播下去，因此能建目录、不能写入；这是环境侧授权传播问题，不是仓库权限损坏。不得手工改 ACL、不得再跑第二遍诊断。备注：DSH 沙箱未向运行期新建子目录传播授权；已排除 ACL 损坏，非项目缺陷。 2026-11-11 复核：会话策略在复核期间由 workspace-write 切换为 danger-full-access；按本轮铁律未运行 pytest/unittest。最小写入探针：Python `tempfile.mkdtemp(dir=D:/ResearchFlow-project)` 后写 `probe.txt`，exit 0（PROBE_WRITE=OK），未复现 2026-11-08 的 workspace-write 写入失败；测试套件本轮未复核，BLK-003 维持 OPEN，历史证据不删除。 2026-11-11 22:54–22:55 按用户 E 项授权执行一次受控 full-access 全量 pytest：& .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider；140 passed，exit 0；日志 reports/remediation/logs/21_full_pytest_fullaccess.log。该结果只证明本次 full-access 下业务测试全绿，不关闭 workspace-write 阻塞；BLK-003 维持 OPEN。 P0 测试报告：reports/remediation/P0_TEST_REPORT.md；BLK-003 仍 OPEN。
- 影响任务：`T-STAGE8-001`
- 打开时间：2026-11-08T13:10:00+08:00
- 处理记录：未解决

### `BLK-004` ADR-007 正式裁决待用户

- 状态：`RESOLVED` 已解决
- 严重度：`MEDIUM` 中
- 描述：ADR-007 自 2026-11-10 起保持 PROPOSED；WP-13 四视图与截图/走查材料已补齐，但仓库文档中未发现将其标为 ACCEPTED 的书面裁决。裁决前不得把三个边界静默视为已批准，也不得据此扩分页、下载或失效原因展示。
- 影响任务：`T-A03-001`、`T-WP-13-001`
- 打开时间：2026-11-15T10:40:30+08:00
- 处理记录：用户 2026-11-15 在 DSH 裁决问答中选择“批准建议（推荐）”：独立只读 Streamlit 进程；四视图只读；证据单页 limit=200、无分页/报告下载；展示 STALE 但不展示失效原因。ADR-007 已由 PROPOSED 改为 ACCEPTED；正式记录 docs/verification/t0/wp-13/ADR-007_DECISION.md；G0 ⑧ 冻结正文保留历史 PROPOSED，差异在 docs/ADR/README.md 登记。

---

本文件由 `scripts/state_sync.py` 从 `docs/state/project_state.json` 生成；请勿手工编辑。
