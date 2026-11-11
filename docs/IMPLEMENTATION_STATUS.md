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
| `DONE` | 完成 | 7 |
| `DEFERRED` | 延期 | 0 |
| **合计** | — | **8** |

## 2. 任务明细

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

### `T-PSEUDO-001` P0 伪代码规格阶段（P1–P10，当前至 P6）

- 阶段：`T0`
- 状态：`IN_REVIEW` 评审中
- 依赖：`T-WP-02-001`
- 更新时间：2026-11-11T18:10:00+08:00
- 阻塞：无
- 验收标准：
  - P1–P7 覆盖 T0 全链路且逐阶段验收
  - P8–P10 覆盖 T1/T2
  - 冻结审计通过
- 测试命令：
  - `ast.parse 语法自检`
  - `人工验收`
- 证据路径：
  - `design/pseudocode/00_BASELINE/PHASE_RULES.md`
  - `design/pseudocode/OPEN_QUESTIONS.md`

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

- 状态：`NOT_STARTED` 未开始
- 更新时间：2026-11-08T11:27:46+08:00
- 验收条件：
  - 无模型、离线、单任务从提交到凭证全链跑通
- 证据路径：
  - 无

### `G2` · 证据可信

- 状态：`NOT_STARTED` 未开始
- 更新时间：2026-11-08T11:27:46+08:00
- 验收条件：
  - E0 不推动状态
  - E2 由 Collector 观察
  - 权限拒绝通过
- 证据路径：
  - 无

### `G3` · L3 独立重执行

- 状态：`NOT_STARTED` 未开始
- 更新时间：2026-11-08T11:27:46+08:00
- 验收条件：
  - 新目录、独立进程、真实重跑
  - 假复现负例拒绝
- 证据路径：
  - 无

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

- 状态：`NOT_STARTED` 未开始
- 更新时间：2026-11-08T11:27:46+08:00
- 验收条件：
  - 真包通过、五类负例拒绝
  - 独立环境可验证
- 证据路径：
  - 无

### `G7` · Harness 适配

- 状态：`NOT_STARTED` 未开始
- 更新时间：2026-11-08T11:27:46+08:00
- 验收条件：
  - 固定版本插件、工具、事件映射和状态回传契约通过
- 证据路径：
  - 无

## 4. 阻塞项

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
- 描述：23 个用例在 workspace-write 下全部在 setUp 阶段失败，共 43 个 error，均为 PermissionError/WinError 5，无断言失败。用户 2026-11-08 用 DSH 权限诊断工具检查 D:\ResearchFlow-project\tmpavet2qv9，结论 NOT_THIS_CLASS：WRITE_DAC / WRITE_OWNER 均具备，无缺失权限、无需清理的第三方授权项；FIXED=0，未做任何改动，无需回滚。报告：C:\Users\Administrator\AppData\Local\ResearchFlow\acl-diagnostics\acl-report-559f7ffa05844dce8e62ba3238f77f3b.jsonl。机制：沙箱进程新建子目录时得到令牌默认权限，项目根上的沙箱授权未传播下去，因此能建目录、不能写入；这是环境侧授权传播问题，不是仓库权限损坏。不得手工改 ACL、不得再跑第二遍诊断。备注：DSH 沙箱未向运行期新建子目录传播授权；已排除 ACL 损坏，非项目缺陷。 2026-11-11 复核：会话策略在复核期间由 workspace-write 切换为 danger-full-access；按本轮铁律未运行 pytest/unittest。最小写入探针：Python `tempfile.mkdtemp(dir=D:/ResearchFlow-project)` 后写 `probe.txt`，exit 0（PROBE_WRITE=OK），未复现 2026-11-08 的 workspace-write 写入失败；测试套件本轮未复核，BLK-003 维持 OPEN，历史证据不删除。
- 影响任务：`T-STAGE8-001`
- 打开时间：2026-11-08T13:10:00+08:00
- 处理记录：未解决

---

本文件由 `scripts/state_sync.py` 从 `docs/state/project_state.json` 生成；请勿手工编辑。
