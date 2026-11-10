# SESSION_HANDOFF

> 会话交接文件。每次大任务结束前更新；最新交接置于最上方。
> 只记录已确认事实与真实测试结果；未确认内容标记“待核实”。

## 交接模板

### YYYY-MM-DD · 阶段 X

- 本次完成：
- 未完成：
- 已知问题/风险：
- 下一步：
- 待用户确认：
- 相关文件/命令：

## 交接记录

### 2026-11-10 · T0 · WP-01 仓库与环境锁定完成 · 等待验收

- 本次完成：
  - `.venv` 由 uv 创建，解释器 `3.11.16` + `64bit`；SQLite `3.53.1`。
  - 矩阵内 16 个直接 pin 安装；`uv pip check` 全部兼容；`requirements.in` + `requirements.lock`（58 包）纳入版本控制。
  - 矩阵外 `httpx2==2.16.0` 经用户 2026-11-10 批准后安装（starlette 1.10.0 TestClient 要求），传递依赖 `httpcore2`、`truststore`。
  - TestClient `200 {'ok': True}`；uvicorn 实际启动 200；8 模块导入与 numpy 区间通过；干净环境从锁文件复现通过。
  - starlette 实测 `1.10.0` 与矩阵一致，**不回退**；uv 工具 `0.12.16` 与矩阵 `0.13.7` 的偏差已记录。
  - `.venv` 502.3 MB，高于矩阵估算 350–450 MB 上限 52.3 MB；安装主路径 59.48 s。
  - `project_state.json`：`current_phase=T0`；`T-WP-01-001=IN_REVIEW`；`current_milestone` 保持 `M0_GOVERNANCE_BASELINE`。
- 未完成：
  - `T-WP-01-001` 尚未验收；未进入 `WP-02`；T0 业务代码未开始。
  - 13b 仍 `NOT VERIFIED`；2D 未单独执行；`BLK-003` OPEN / MEDIUM。
  - `last_verified_commit` 仍 `null`。
- 已知问题/风险：
  - `.venv` 体积超出矩阵估算上限，原因是完整闭包 + Windows 二进制 wheel + 新增 `httpx2`；已如实记录。
  - `.uv-cache` 实测 473.7 MB，为 uv 本地解压缓存，不是网络下载字节；未拿它冒充下载量。
  - uv 版本偏差与矩阵外 `httpx2` 均由用户批准/记录，无静默变更。
- 实际测试命令与结果：
  - `uv venv --python 3.11.16 .venv` → 首次缓存失败；设 `UV_CACHE_DIR` 后 exit 0，0.51 s。
  - `& .venv/Scripts/python.exe -c "import sys,platform;print(sys.version,platform.architecture()[0])"` → `3.11.16 ... 64bit`，exit 0。
  - `uv pip install` 16 pins → exit 0，46.10 s。
  - `uv pip check` → 全部兼容，exit 0。
  - TestClient → `TESTCLIENT_OK 200`，exit 0；uvicorn → `STARTUP_OK`，exit 0。
  - `uv pip install -r requirements.lock`（干净 `.venv-repro`）→ TestClient 200，43.95 s，已删除。
  - `state_sync.py validate|render|check` → 均 exit 0；PROJECT_STATE `756d1f5f…3967`，IMPLEMENTATION_STATUS `1bca2b36…ed4b`。
- 下一步（等待用户）：
  1. 验收 `WP-01` 环境与依赖；确认后 `T-WP-01-001` 可由 `IN_REVIEW` 转 `DONE`。
  2. 验收通过后再批准 `WP-02`；不得连做。
  3. 如需 T0 里程碑编号，请指定；当前未自行发明。
- 待用户确认：
  - `.venv` 502.3 MB 超出矩阵估算是否接受。
  - `T-WP-01-001` 是否转 `DONE`；`last_verified_commit` 是否更新。
- 相关文件/命令：`requirements.in`、`requirements.lock`、`docs/verification/t0/wp-01/WP-01_REPORT.md`、`env_fingerprint.json`、`dependency_resolution.txt`、`testclient_smoke.log`、`startup.log`、`size_and_timing.md`、`docs/state/project_state.json`、`docs/CHANGELOG_DEV.md`。

### 2026-11-10 · G0 PASS · Git 回滚补测 · 阶段 8 第 20 项关闭

- 本次完成：
  - 用户 2026-11-10 宣布 **G0 PASS**：①–⑧ + ⑨ 全部 v1.0；五份 schema 72/72；阻塞级 OQ=0；基线 `91bde66` 已建立；DOCX 未入库、SHA256 未变。
  - `project_state.json`：`G0` → `PASS`（`decided_by=用户`、`decided_at=2026-11-10`，19 条证据路径）；`T-G0-001` → `DONE`；`G1`–`G7` 保持 `NOT_STARTED`。
  - `state_sync.py` 门禁增加 `decided_by` / `decided_at`（PASS 必填）；渲染器输出裁决人/时间；正例 + 4 个负例校验通过。
  - Git 回滚补测：`docs/CHANGELOG_DEV.md` 写入探针 → status/diff 可见 → `git checkout --` exit 0 → blob/SHA256 回到 HEAD → 探针无残留；日志 `docs/verification/g0/18_git_rollback.log`。
  - 阶段 8 第 20 项转 **PASS（基线建立后补测）**；`20_git_rollback.md`、`STAGE8_REPORT.md`、`G0_DECISION_LIST.md` R-3 同步；13b 仍 `NOT VERIFIED`。
  - `AGENTS.md` 两条负例规则修改经用户批准纳入本次提交。
- 未完成：
  - `WP-01` 尚未开始（下一步）；未创建 `.venv`、未安装依赖、未生成 lock。
  - 13b 仍 `NOT VERIFIED`；2D 未单独执行；`BLK-003` OPEN / MEDIUM。
- 已知问题/风险：
  - 会话开始时工作区并不干净：`AGENTS.md` 有未提交修改；已报告用户并获准纳入本次提交。
  - `state_sync.py` 门禁 schema 新增两个可选字段；旧状态文件（G1–G7 未 PASS）不受影响。
  - `last_verified_commit` 仍为 `null`；用户未下达更新指令。
- 实际测试命令与结果：
  - `validate_contracts.py --selftest` → `10/10 PASS`，exit 0。
  - `validate_contracts.py` → `cases=72 pass=72 fail=0`，exit 0。
  - `state_sync.py validate` → `OK`，任务 5，门禁 PASS=1/8，exit 0。
  - `state_sync.py render` → 2 文件，exit 0；`check` → 逐字节一致，exit 0。
  - `check_gate_decision.py` → `GATE_DECISION_SCHEMA_TEST=PASS`（1 正例 + 4 负例），exit 0。
  - 回滚：`git checkout --` exit 0；blob `051d761…` → `a4ae439…` → `051d761…`；SHA256 前后一致。
- 下一步（等待用户）：
  1. 验收本次 G0 PASS 提交与阶段 8 第 20 项关闭。
  2. 批准/验收 `WP-01`：`uv venv --python 3.11.16 .venv`、指纹校验、按锁定矩阵安装、生成锁文件、TestClient 冒烟、记录体积/耗时，提交 `feat(wp-01): 锁定 T0 依赖环境`。
  3. 决定是否将 `last_verified_commit` 更新为本轮 HEAD。
- 待用户确认：
  - `WP-01` 中 `httpx` 等 TestClient 运行依赖是否属于矩阵允许范围（若解析发现缺失，先报告再装）。
  - `ADR-007` 仍 `PROPOSED`，不早于 `WP-13` 裁决。
- 相关文件/命令：`docs/state/project_state.json`、`scripts/state_sync.py`、`docs/verification/g0/18_git_rollback.log`、`docs/verification/g0/19_g0_pass_decision.md`、`docs/verification/stage8/20_git_rollback.md`、`docs/verification/stage8/STAGE8_REPORT.md`、`docs/state/G0_DECISION_LIST.md`、`docs/CHANGELOG_DEV.md`。

### 2026-11-10 · G0 · 规格基线统一 v1.0 并提交

- 本次完成：
  - **Git 身份（仅本仓库）**：`git config --local user.name="ResearchFlow Dev"`、`user.email="dev@researchflow.local"`；`git config --global --get user.name/user.email` 仍为空；`BLK-001` 置 `RESOLVED`。
  - **DOCX 选 B**：`.gitignore` 增加精确规则 `/ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx`，不使用 `*.docx`；`git check-ignore -v` 命中，其他 `.docx` 路径不命中；DOCX 未修改、未改名、未移动。
  - **①–⑧ 与 ⑨ 全部 v1.0**：每份文档头加“冻结日期 2026-11-10｜状态 G0 冻结｜被取代版本”；① 的 v1.1 归并为 v1.0，版本记录保留历史。
  - **三组枚举按现值冻结**：`kind` 7、`l1/l2/l3_status` 4、`side_effect_class` 3；保留“按 `MINOR` 可变”注记；只改 schema 注记，未改 `enum` 与校验语义。
  - **依赖矩阵锁定**：`09_dependency_matrix.md` 为 `WP-01` 基线（17 个第三方包 + SQLite）；⑦ `WP-01` 入口条件写入矩阵与四条解释器硬约束（`uv venv --python 3.11.16`、3.11.16/64bit 指纹、架构优先排查、TestClient 冒烟与回退）。
  - **`ADR-007` 延后**：保持 `PROPOSED`，`WP-13` 前裁决；ADR 文件、索引与 ⑧ §4 一致。
  - **首次提交**：按用户给定提交信息 `chore(g0): 建立 G0 规格基线` 执行；提交结果以 `git log` / `git rev-parse HEAD` 为准。
- 未完成：
  - G0 是否 PASS 未宣布；`T-G0-001` 保持 `IN_PROGRESS`，G0–G7 保持 `NOT_STARTED`。
  - `last_verified_commit` 仍为 `null`，待用户确认后更新。
  - 未建 `.venv`、未安装依赖、未生成 lock；`WP-01` 的解释器校验与 TestClient 冒烟尚未执行。
- 已知问题/风险：
  - `BLK-003` 仍 `OPEN`；阶段 8 的 13b 与第 20 项仍 `NOT VERIFIED`，不因本提交改变。
  - Python 3.11 处于 security-only；依赖矩阵按“最后 3.11 线”锁定，不能追新。
  - `stage7/14_link_check.log` 曾被同名脚本覆盖且不可恢复，已按“不改写历史 + SUPERSEDED_NOTICE”处置。
- 实际测试命令与结果：
  - `& $py scripts/validate_contracts.py --selftest` → `SELFTEST 10/10 PASS`，exit 0。
  - `& $py scripts/validate_contracts.py` → `contracts=5 cases=72 pass=72 fail=0`，exit 0。
  - `& $py docs/verification/g0/check_terms.py` → `TERMS_RESULT=PASS`，exit 0。
  - `& $py docs/verification/g0/check_links_g0.py <本轮文档>` → `BROKEN=0`，exit 0。
  - `& $py scripts/state_sync.py validate|render|check` → 均 exit 0，2 个生成文件逐字节一致。
  - 日志：`docs/verification/g0/10_version_freeze_selftest.log`–`17_version_freeze_report.md`。
- 下一步（等用户）：
  1. 复核本轮提交与升版清单，宣布 G0 是否 PASS。
  2. G0 PASS 后再批准 T0 启动；`WP-01` 先按锁定矩阵建 `uv` 3.11.16（64 位）环境并跑指纹与 TestClient 冒烟。
  3. `WP-13` 前裁决 `ADR-007`。
- 待用户确认：
  - G0 是否 PASS；是否将 `last_verified_commit` 更新为本轮 HEAD。
  - `ADR-007` 四视图范围的最终裁决（不早于 `WP-13`）。
- 相关文件/命令：`docs/verification/g0/17_version_freeze_report.md`、`docs/verification/g0/09_dependency_matrix.md`、`docs/design/07_T0_PLAN_AND_GATES.md`、`docs/design/05_CONTRACTS_AND_STATES.md`、`docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md`、`contracts/README.md`、`.gitignore`、`docs/state/project_state.json`、`docs/CHANGELOG_DEV.md`。

### 2026-11-09 · G0 · 冻结前定向修订完成 · 待用户逐项签字

- 本次完成：
  - **Git 基线只读预检**：`user.name` / `user.email` 均未配置（全局与仓库级），分支 `main`，0 commit；`git check-ignore` 逐条证明 `contracts/*.json` 与 `docs/verification/**` 不被忽略；首提候选清单 282 个文件（未跟踪 283，排除 DOCX）；DOCX 三种处置方案已列，**未做任何配置、未 add、未 commit**。
  - **②③ 一致性**：`FR-008`、`US-T0-13` 及 ③ §3.1 第 9 步补 `schema_version`（const `"1.0"`）、证书 `issued_at`、签名载荷覆盖与对应反例引用；②③ 升 v0.2。
  - **四词自检**：②③④⑤⑥⑦ 中 `schema_version` / `INVALIDATED` / `plan_hash` / `dataset_ref` 的命中与一致性核对，`TERMS_RESULT=PASS`；自检发现并修正 ⑤ 两处（MINOR 兼容表述、§2.5→§2.4 误引）。
  - **① v1.1 / ④ v0.2 / ⑤ v0.3 / ⑧ v0.3**：① 索引加 ⑨ 并同步已决项；④ 同步 `OQ-ARCH-1/2`；⑤ 3 处定向修订；⑧ 新增风险 14、ADR 索引、§6.1 收敛为 1 项。
  - **`docs/ADR/`**：ADR-001–006 ACCEPTED、ADR-007 PROPOSED，含索引 README。
  - **stage7 覆盖日志**：新增 `SUPERSEDED_NOTICE.md`（不改写原 232 记录）；⑧ 风险表登记“证据日志可被同名脚本覆盖”。
  - **依赖矩阵**：10 个指定包 + 7 个关键传递依赖；全部有 cp311/win_amd64 或纯 Python wheel；numpy 固定 2.4.6、pydantic 2.14.3 + core 2.50.4、networkx 3.6.1（3.7 要 3.12）、scipy 1.17.1、pandas 3.1.1、scikit-learn 1.9.1；starlette 1.x 配对列为待实测风险。**未安装、未建 venv、未生成 lock**。
- 未完成：
  - **未 commit**：等用户提供 Git 身份、批准清单与提交信息。
  - G0 未冻结、T0 未开始；`T-G0-001` 仍 `IN_PROGRESS`。
  - 依赖矩阵只有元数据结论，没有安装实测；starlette 与 fastapi 的运行时配对需 WP-01 冒烟。
- 已知问题/风险：
  - `BLK-001`（Git 无身份/无基线）仍 `OPEN`；`BLK-003` 仍 `OPEN`；13b、第 20 项仍 `NOT VERIFIED`。
  - Python 3.11 处于 security-only；networkx 3.7 / numpy 2.5 / scipy 1.18 已要求 `>=3.12`，本矩阵是“最后 3.11 线”，只能锁定不能追新。
  - `stage7/14_link_check.log` 已被覆盖且不可恢复；处置为追加说明，不改历史。
- 实际测试命令与结果：
  - `& $py -X utf8 scripts/validate_contracts.py --selftest` → 10/10 PASS，exit 0。
  - `& $py -X utf8 scripts/validate_contracts.py` → 72/72 PASS，`exit=0`。
  - `& $py -X utf8 docs/verification/g0/check_terms.py` → `TERMS_RESULT=PASS`，exit 0。
  - `& $py -X utf8 docs/verification/g0/check_links_g0.py <20 文档>` → 77 links / 0 broken，exit 0。
  - `& $py -X utf8 docs/verification/g0/research_versions.py` → `RESULT=OK`，17 个包均有兼容 wheel。
  - `& $py scripts/state_sync.py validate|render|check` → 均 exit 0，生成文件逐字节一致。
- 下一步（等用户，不自动执行）：
  1. 提供 Git 身份 → 确认 `.gitignore` 方案（DOCX A/B/C）→ 确认 282 文件清单与提交信息 → 执行首提并校验 `git rev-parse HEAD` / `git status` 干净。
  2. 对“G0 冻结前检查清单”逐项签字；确认三组枚举是否按候选冻结。
  3. 批准后才讨论 G0 通过；T0 另需批准。
- 待用户确认：
  - Git `user.name` / `user.email` 的值与作用域（全局/仓库级）。
  - 首提是否按 282 清单全量；提交信息文本。
  - DOCX 处置 A（保持未跟踪）/ B（精确文件名忽略，建议）/ C（`*.docx` 忽略）。
  - 依赖矩阵是否作为 WP-01 锁定基线。
- 相关文件/命令：`docs/verification/g0/05_git_baseline_report.md`、`06_first_commit_filelist.txt`、`07_term_consistency.log`、`08_dependency_matrix.log`、`09_dependency_matrix.md`、`docs/ADR/`、`docs/verification/stage7/SUPERSEDED_NOTICE.md`、`docs/state/project_state.json`、`docs/CHANGELOG_DEV.md`。

### 2026-11-09 · G0 · ⑨ 契约机器可读化完成 · 待整体评审

- 本次完成：
  - 新增 G0 文档 ⑨：`contracts/` 五份 JSON Schema Draft 2020-12（TaskSpec、NodeSpec、EvidenceRecord、VerificationReport、CompletionCertificate），均含 `$id`、`title`、`schema_version const "1.0"`、显式 `additionalProperties`；枚举/pattern/必填/RFC 3339 全部落入 schema。
  - 新增 `scripts/validate_contracts.py`（仅标准库；schema lint + schema/semantic/json 三层；未知关键字 fail closed）。
  - 新增 `contracts/examples/`：5 正例 + 67 反例 = 72 例 + `manifest.json`；反例逐条声明期望 layer/keyword/pointer。
  - 按用户 10 项决议更新 ⑤（v0.2）、⑥（v0.2）、⑦（v0.2）、⑧（v0.2）：签名载荷白名单、`dataset_ref` 对象化、恢复计划内容寻址、失效记录驱动 stale 判定、`INVALIDATED→READY` 三条件守卫、T0 不复用 Recovery FSM、失败迁移独立事务 `DENIED`、`/recover` 404 + 启动守卫、`C-002/C-003` 接受口径。
  - `T-G0-001` 证据与验收条件已更新；`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md` 由 render 生成。
- 未完成：
  - ②③④ 本轮未改（按“只改 ⑤⑥⑦⑧”）；与已关闭项同源的旧表述见 ⑧ §6.1 第 3/4 项。
  - `ADR-002`–`ADR-006` 正式文件未创建（`docs/ADR/` 仍不存在）；以 ⑧ §4 与各文档段落为决策记录。
  - G0 未批准、T0 未开始、业务代码未写。
- 已知问题/风险：
  - **证据覆盖事故**：运行 `docs/verification/stage7/check_links.py` 前未确认其 `OUT` 常量，覆盖了 `docs/verification/stage7/14_link_check.log`。现内容 106 字节 / SHA256 `A3ECADA1…` / 239 links / 0 broken / PASS；阶段 7 报告记为 232 links，`16_final_inventory.log` 记录原 SHA256 `B9FDD0AB…`。无 git 基线，无法恢复；未再运行该脚本，本轮改用只读 `check_links_g0.py`。**处置：保留原 232 记录不动，新增 `docs/verification/stage7/SUPERSEDED_NOTICE.md`（原/现值、原因、无法恢复、后续只追加）；不把阶段 7 报告改成 239。**
  - `OQ-009/010/011` 的枚举集合是候选值，已落 schema；改值需 `MINOR` 调整并重跑校验器。
  - `BLK-001`（Git 无基线）、`BLK-003`（沙箱子目录授权）仍 `OPEN`；13b、第 20 项仍 `NOT VERIFIED`。
- 实际测试命令与结果：
  - `& $py scripts/validate_contracts.py --selftest` → `SELFTEST 10/10 PASS`，exit 0。
  - `& $py scripts/validate_contracts.py` → `SUMMARY contracts=5 cases=72 pass=72 fail=0 exit=0`；各契约：taskspec 16/14/13/15/14 全 PASS。
  - `& $py docs/verification/g0/check_links_g0.py <5 个改动文档>` → 43 links / 0 broken / PASS，exit 0。
  - `& $py scripts/state_sync.py validate|render|check` → 均 exit 0，2 个生成文件逐字节一致。
  - 日志：`docs/verification/g0/01_selftest.log`、`02_validate_contracts.log`、`03_link_check.log`。
  - 未修改测试、expected、阈值；未 commit、未建 `.venv`、未安装依赖。
- 下一步（等待用户，不自动执行）：
  1. 评审 ②–⑨；重点看 ⑤ §1.5/§9.3/§9.5/§9.7、⑥ §1.3/§2/§4.6、⑦ WP-02/WP-03/WP-08/WP-R、⑧ §6.1。
  2. 决定 `14_link_check.log` 覆盖事故的处置，以及 §6.1 的 4 项待确认。
  3. 批准后才讨论 G0 通过；T0 业务代码须另行批准。
- 待用户确认：
  - ① 索引是否升 v1.1（只加 ⑨）；ADR 正式文件落地时机；②③ 签名措辞与 ①/②/④ 旧表述同步时机；阶段 7 链接日志处置。
- 相关文件/命令：`contracts/`、`scripts/validate_contracts.py`、`docs/verification/g0/`、`docs/design/05`–`07`、`docs/G0/08`、`docs/state/project_state.json`、`docs/CHANGELOG_DEV.md`。

### 2026-11-08 · 阶段 8 验收通过 · 等待阶段 9

- 本次完成：
  - 用户确认阶段 8 结论：**25 PASS / 2 NOT VERIFIED / 0 FAIL，通过**。
  - `T-STAGE8-001` → `DONE`；`T-DOCS-001` 保持 `DONE`；`BLK-002` 保持 `RESOLVED`。
  - `BLK-003` 保持 `OPEN`，severity 由 `HIGH` 降为 **`MEDIUM`**；备注改为“DSH 沙箱未向运行期新建子目录传播授权；已排除 ACL 损坏，非项目缺陷”。
  - 记录 DSH 权限诊断：`NOT_THIS_CLASS`，`WRITE_DAC` / `WRITE_OWNER` 均具备、`FIXED=0`、未做任何改动；报告路径 `C:\Users\Administrator\AppData\Local\ResearchFlow\acl-diagnostics\acl-report-559f7ffa05844dce8e62ba3238f77f3b.jsonl`。
  - 写明 full-access 绕行方式：23 项 unittest 属代码正确性测试，可在单独批准的 full-access 会话运行；日志记录当次策略，结束立即恢复 workspace-write；结果不得用于第 5/6/23 项或任何安全项。
  - G0 残留风险收敛为三条：① 13b 仅在全权限下通过；② 2D 未单独执行、2C 运行态未观测；③ Git 无基线、回滚未实测。
  - 记录 `tmpavet2qv9` 为空目录，阶段 9 开始时只删除该目录，不动其他目录；本次未删。
- 未完成 / 未通过：
  - 13b 仍 `NOT VERIFIED`；只有日后在 workspace-write 下真跑通 23 项测试才可改 PASS。
  - 第 20 项仍 `NOT VERIFIED`（0 commit，无基线，回滚未实测）。
  - 阶段 9 未开始；未 commit、未建 `.venv`、未安装依赖、未开发业务代码。
- 已知问题/风险：
  - `BLK-003` OPEN / MEDIUM：环境侧授权传播问题，非仓库 ACL 损坏；不得手工改 ACL、不得再跑第二遍诊断。
  - 2D 未单独执行、2C 运行态未观测；已列入 G0 残留风险。
  - Git 无基线；回滚未实测。
  - 整机既有 Docker Desktop（服务 Stopped）与 NVIDIA 驱动工具；项目未使用，未卸载。
- 实际测试命令与结果：
  - `& $py scripts/state_sync.py validate`：exit 0；任务=4，门禁 PASS=0/8，阻塞=3（OPEN 2 / RESOLVED 1）。
  - `& $py scripts/state_sync.py render`：exit 0；`PROJECT_STATE.md` `197d9d85…13e34`、`IMPLEMENTATION_STATUS.md` `a15e38ae…73b5f`。
  - `& $py scripts/state_sync.py check`：exit 0；2 个文件逐字节一致。
  - 13b：仅引用 `32_unittest_workspacewrite.log`（23 tests / 43 errors），不引用全权限 23/23。
- 当前分支与 commit：`main`；`git rev-list --count --all` = 0；未 `git add` / `git commit`；`last_verified_commit=null`。
- 下一步（最多 3 项）：
  1. 阶段 9 开始时只删除 `D:\ResearchFlow-project\tmpavet2qv9` 这一个空目录，并在阶段 9 报告中确认；不得动其他目录。
  2. 按 `G0_DECISION_LIST.md` 的三条残留风险安排阶段 9 的验证/裁决；13b 仍为 NOT VERIFIED。
  3. 等待用户发送阶段 9；未获批准不进入。
- 待用户确认：
  - 阶段 9 的启动与范围。
  - 是否在单独批准的 full-access 会话运行 23 项 unittest；若运行，必须记录策略并立即恢复 workspace-write。
  - 三条 G0 残留风险的处理方式。
- 证据目录：`docs/verification/stage8/`；总报告 `STAGE8_REPORT.md`；G0 清单 `docs/state/G0_DECISION_LIST.md`。

### 2026-11-08 · 阶段 8 补验 · 策略恢复后重跑

- 本次完成：
  - 用户恢复 `workspace-write` / 审批 `ask`；第 5、6、23 项按原口径重跑并 **PASS**。
  - 第 13 项拆分：**13a PASS**（check 负例 0→1→0）；**13b NOT VERIFIED**（workspace-write 下 23 tests / 43 errors，无断言失败）。
  - 第 2 项改为“静态确认 PASS / 运行态未观测”；“2D 未单独执行”列入 `G0_DECISION_LIST.md` 的 G0 残留风险清单。
  - 按用户命令完成 BLK-003 取证：工作区内 `tempfile.mkdtemp(dir=D:\ResearchFlow-project)` 创建 `tmpavet2qv9` 后，写 `probe.txt` 抛 `PermissionError [Errno 13]`；路径 `D:\ResearchFlow-project\tmpavet2qv9\probe.txt`。目录保留供 DSH 权限诊断，未改代码/测试/expected/目录结构/权限。
  - `BLK-003` 保持 `OPEN`、`HIGH`，备注“待权限诊断”；`T-STAGE8-001` 仍 `IN_REVIEW`；生成状态文件重新渲染。
- 未完成 / 未通过：
  - 13b 仍未通过；`BLK-003` 待权限诊断。
  - 第 20 项仍 `NOT VERIFIED`（0 commit，无基线，回滚未实测）。
  - 2D 未单独执行，第 2 项运行态未观测。
  - 未 commit、未建 `.venv`、未安装依赖、未开发业务代码、未进入阶段 9。
- 已知问题/风险：
  - workspace-write 下工作区子目录写入异常：不是“系统临时目录在沙箱外”能单独解释的；需权限诊断。
  - 全权限下的 23/23 仅作历史记录，不得作为 13b 通过依据。
  - Git 无基线；提交前需确认身份。
  - 整机既有 Docker Desktop（服务 Stopped）与 NVIDIA 驱动工具；项目未使用，未卸载。
- 实际测试命令与结果：
  - 第 5 项：工作区写读删成功；写 `C:\Users\Administrator\stage8_outside_probe.txt` 被拒（访问被拒绝），目标文件未生成；`33_item5_workspacewrite.log`。
  - 第 6/23 项：运行时 `workspace-write` / 审批 `ask`；teams/parallel 0 命中；workflow 0；子 Agent 1；`30_policy_restored.log`、`34_item6_23_workspacewrite.log`。
  - 13a：基线 0 → 篡改 1 → 恢复 0；`35_check_negative_workspacewrite.log`。
  - 13b：`& $py -m unittest discover -s tests -v` → exit 1；`Ran 23 tests`；`FAILED (errors=43)`；0.5 s；`32_unittest_workspacewrite.log`。
  - BLK-003 取证：`PermissionError [Errno 13] Permission denied: 'D:\ResearchFlow-project\tmpavet2qv9\probe.txt'`；`31_blk003_probe.log`、`31b_probe_path_evidence.log`。
  - `& $py scripts/state_sync.py validate`：exit 0；任务=4，门禁 PASS=0/8，阻塞=3。
  - `& $py scripts/state_sync.py render`：exit 0；`PROJECT_STATE.md` `e7c9593e…cfff1`、`IMPLEMENTATION_STATUS.md` `6ed89f82…e508e`。
  - `& $py scripts/state_sync.py check`：exit 0；2 个文件逐字节一致。
- 当前分支与 commit：`main`；`git rev-list --count --all` = 0；未 `git add` / `git commit`；`last_verified_commit=null`。
- 下一步（最多 3 项）：
  1. 用户对 `D:\ResearchFlow-project\tmpavet2qv9` 运行 DSH 权限诊断工具；修复后重跑 13b。
  2. 补齐 2D 运行态验证，或书面接受“静态确认 / 运行态未观测”口径，并同步 G0 残留风险。
  3. 用户批准阶段 9 后再进入 G0 规格冻结准备；未批准前不进入。
- 待用户确认：
  - `BLK-003` 权限诊断结果与修复方式；修复前保持 OPEN/HIGH。
  - 2D 残留风险的处理口径。
  - 是否批准进入阶段 9。
- 证据目录：`docs/verification/stage8/`；总报告 `STAGE8_REPORT.md`；G0 清单 `docs/state/G0_DECISION_LIST.md`。

### 2026-11-08 · 阶段 8 · AI 研发工作站综合验收

- 本次完成：
  - 执行阶段 8 的 26 项验收并出具总报告 `docs/verification/stage8/STAGE8_REPORT.md`；判定 **22 PASS / 3 FAIL / 1 NOT VERIFIED**。
  - 按用户决议关闭 `BLK-002`（`RESOLVED`；内容基线=内部 v4.3.0，v4.3.1 为文件名标签）；`CONFLICT_REPORT` 的 `C-001` 标 `RESOLVED（用户决议）`，原始证据行全部保留。
  - `T-DOCS-001` → `DONE`；新增 `T-STAGE8-001`（阶段 8 综合验收）→ `IN_REVIEW`，等待用户验收。
  - 新增 `BLK-003`（OPEN，HIGH）：workspace-write 下 23 项测试受临时目录 ACL 阻塞；阶段 8 在 `danger-full-access` 下 23/23 OK，但不作为 workspace-write 证据。
  - 新增 `docs/state/G0_DECISION_LIST.md`：版本项“已决”，剩余 3 项（FR-010 的 T0 边界、§15.5 与附录 J 的顺序、FR-015/016/017 的 P1 与 T2 错位）。
  - 更新 `project_state.json`、生成状态文件、`SOURCE_REGISTER`、`CONFLICT_REPORT`、记忆文件、README 与当前知识文档；历史 CHANGELOG/交接/stage7 报告未改写。
- 未完成 / 未通过：
  - 第 5、6、23 项 **FAIL**：阶段 8 期间用户将会话从 `workspace-write` / 审批 `ask` 切换为 `danger-full-access` / 审批关闭；沙箱与审批不符合验收口径。
  - 第 20 项 **NOT VERIFIED**：0 commit、0 tracked，无基线，回滚未实测（`BLK-001`）。
  - 未 commit、未建 `.venv`、未安装依赖、未开发业务代码、未进入阶段 9。
- 已知问题/风险：
  - `BLK-003` 保持 OPEN；全权限下 23/23 只能证明代码可运行，不能证明 workspace-write 可用。
  - 当前策略为 `danger-full-access` / 审批关闭；恢复 `workspace-write` / `ask` 前，阶段 9 的文件操作缺少强制边界。
  - Git 无基线；回滚能力未实测；提交前需确认 Git 身份。
  - 项目内没有独立阶段 2D 报告；第 2 项引用阶段 6 的 2C 非回归证据与当前运行态，已在报告中标注口径。
  - 整机既有 Docker Desktop（服务 Stopped）与 NVIDIA 驱动工具；项目未使用，未卸载。
- 实际测试命令与结果：
  - `& $py scripts/state_sync.py validate`：exit 0；任务=4；门禁 PASS=0/8；阻塞=3。
  - `& $py scripts/state_sync.py render`：exit 0；2 个文件；`PROJECT_STATE.md` `2335a1d6…63ea5`、`IMPLEMENTATION_STATUS.md` `d04ff691…0cb8`。
  - `& $py scripts/state_sync.py check`：exit 0；2 个文件逐字节一致。
  - 受控不一致 fixture：0 → 1（含 diff/SHA256）→ 0；fixture 已删除。
  - `& $py -m unittest discover -s tests -v`（`danger-full-access`）：23/23 OK，3.2 s，exit 0；`BLK-003` 仍 OPEN。
  - DOCX：111,209 字节 / `9E54168F…CCB3A`；全项目 DOCX/PDF=1；inbox 仅 `.gitkeep`。
  - 431 个目录联接 / 0 断链；旧 CLI 0.1.0-rc.8；secret scan 0 命中。
- 当前分支与 commit：`main`；`git rev-list --count --all` = 0；未 `git add` / `git commit`；`last_verified_commit=null`。
- 下一步（最多 3 项）：
  1. 用户审阅 `STAGE8_REPORT.md`，对第 5/6/23 项的安全偏差与 `BLK-003` 给出决议；建议恢复 `workspace-write` / `ask` 后复测。
  2. 若需回滚能力，确认 Git 身份并批准基线 commit；否则第 20 项保持 `NOT VERIFIED`。
  3. 用户批准后再进入阶段 9（G0 规格冻结准备），逐项裁决 `G0_DECISION_LIST.md` 的 3 个开放项。
- 待用户确认：
  - 是否接受当前 `danger-full-access` / 审批关闭，或恢复 `workspace-write` / `ask`。
  - `BLK-003` 的处理：恢复策略后复测，还是保持 OPEN 至后续。
  - 是否创建 Git 基线 commit（需身份）。
  - 是否批准进入阶段 9。
- 证据目录：`docs/verification/stage8/`；总报告 `STAGE8_REPORT.md`；G0 清单 `docs/state/G0_DECISION_LIST.md`。

### 2026-11-08 · 阶段 7 · ResearchFlow 项目资料接手与知识基线

- 本次完成：
  - 只读扫描项目与 `docs/reference/`：根目录 `ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx` 为唯一权威原件；`docs/reference/inbox/` 只有 `.gitkeep`；**未复制、未移动、未重命名、未覆盖**原件。
  - 用项目 Python 3.11.16 + 标准库完成全文抽取：754/754 段落、80/80 表格、0 媒体/绘图/文本框、0 修订/批注、无 TOC、30 个手工分页符；证据在 `docs/verification/stage7/`。
  - 新增 `docs/reference/SOURCE_REGISTER.md`（含“禁止再产生第二份策划书副本”）、`docs/reference/CONFLICT_REPORT.md`（C-001–C-007）。
  - 新增 `docs/PROJECT_OVERVIEW.md`、`ARCHITECTURE.md`、`GLOSSARY.md`、`DEVELOPMENT_WORKFLOW.md`、`MEMORY_GUIDE.md`、`MCP_CATALOG.md`、`SECURITY_POLICY.md`；更新 `docs/SKILL_CATALOG.md`。
  - 更新记忆文件、`runtime_states.md`、README，修正版本引用为“内部 v4.3.0（文件名 v4.3.1，BLK-002）”。
  - `T-SKILLS-001` → `DONE`；`T-MCP-001` 保持 `DONE`；新增 `T-DOCS-001`（`IN_REVIEW`）；`BLK-002` 保持 `OPEN`、严重度 HIGH；G0–G7 未改。

- 未完成：
  - **版本基线未确认**：文件名 v4.3.1 / 内部 v4.3.0；`BLK-002` OPEN。
  - 飞书 AI 开发说明未落地；赛事通知原图/完整章程未落地。
  - 未取得可信页码（Word COM 启动阻塞；DOCX 无缓存分页）。
  - `state_sync` 23 项回归测试两次尝试均被 DSH 沙箱临时目录 ACL 拒绝（43 个 `PermissionError`，无断言失败）；`validate/render/check` 已通过；未改测试/阈值。见 `docs/verification/stage7/18_unittest_attempt.md`。
  - 未 commit、未建 `.venv`、未装依赖、未开发业务代码；未进入 G0/阶段 8。

- 已知问题/风险：
  - 版本冲突阻断 G0；确认前不得冻结契约，不得把目标数字当最终验收合同。
  - 文档内 `v4.3.1` 计数为 0；文件名是唯一 v4.3.1 来源；不得自行裁决。
  - DOCX 属性 `created/modified=2013-12-23T23:15:00Z`、`Pages=1`、`Words=0` 为生成残留，不可用。
  - 页码不可用时只能用 § + `P####` / `TABLE ##`；不得估算页码。
  - `docs/reference/inbox/` 仍为空；策划书副本禁止产生；DOCX 当前未被 `.gitignore` 忽略，后续 `git add` 必须排除。
  - 阶段 6 备份 `cordis.patch.yml.bak-20261108-stage6` 必须保留到阶段 8 验收结束。

- 实际测试命令与结果：

  ```powershell
  $py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'

  & $py docs/verification/stage7/extract_docx.py
  # DOCX_EXTRACT=OK；111,209 字节；SHA256 9E54168F…CCB3A；754 段/80 表；exit 0

  & $py docs/verification/stage7/verify_version_strings.py
  # VERSION_EVIDENCE=OK；文档内 v4.3.1=0，v4.3.0=6+1+1；exit 0

  & $py scripts/state_sync.py validate
  # OK；任务=3；门禁 PASS=0/8；阻塞=2；exit 0

  & $py scripts/state_sync.py render
  # 生成 2 个文件；exit 0

  & $py scripts/state_sync.py check
  # 2 个生成文件逐字节一致；exit 0

  & $py docs/verification/stage7/scan_secrets.py
  # 21 个文件；0 命中；SECRET_SCAN=PASS；exit 0
  ```

- 当前分支与 commit：
  - 分支 `main`；`git rev-list --count --all` = 0；未执行 `git add` / `git commit`。
  - `last_verified_commit` = `null`。

- 下一步（最多 3 项）：
  1. 用户回答 `BLK-002` 最小问题：内部 v4.3.0 是否为最终内容基线？v4.3.1 是否只是文件名标签？是否存在另一份 v4.3.1？
  2. 用户验收阶段 7；批准后再进入阶段 8（G0 准备/规格冻结）。
  3. 如需补齐来源，提供飞书导出件与赛事通知/章程到 `docs/reference/inbox/`，再登记。

- 待用户确认：
  - `BLK-002` 基线版本。
  - 是否验收阶段 7、是否进入阶段 8。
  - 是否保留新增的 `T-DOCS-001` 看板记录。
  - 飞书资料 / 赛事通知/章程是否补入。
  - 是否允许把 DOCX 忽略规则写入 `.gitignore`。

- 证据目录：`docs/verification/stage7/`；总报告 `STAGE7_REPORT.md`；来源/冲突 `docs/reference/SOURCE_REGISTER.md`、`CONFLICT_REPORT.md`。

### 2026-11-08 · 阶段 6 · Context7 接入执行与验证

- 本次完成：
  - 创建备份 `cordis.patch.yml.bak-20261108-stage6`（1,200 字节，SHA256 `664CE561…94FFD8`），与源文件逐字节相同。
  - 以二进制 LF 追加 9 行 / 262 字节；写入后 1,462 字节 / 52 行 / SHA256 `6FF6F1FC…59E1`；前 1,200 字节与备份一致；无 BOM、无 CRLF。
  - 热重载生效，**未重启桌面版**；当前会话出现 `mcp__context7__resolve-library-id` 与 `mcp__context7__query-docs`，并出现 server `context7` 的 instructions 与资源工具。
  - 真实查询：FastAPI → `/websites/fastapi_tiangolo`；Pydantic → `/pydantic/pydantic`（版本含 `v2.11.0`）；以 `/pydantic/pydantic/v2.11.0` 执行 `query-docs`，返回 v2.11.0 文档。无 429，无 API Key。
  - `T-MCP-001` 已转 `DONE`；`T-SKILLS-001` 仍 `IN_REVIEW`。
  - 更新 `00`/`01`/`02`/`03` 文档状态，新增 `08_apply_result.md`、`apply_context7_patch.py`、`06_apply.log`、`06_apply_summary.log`、`07_post_write_verify.log`、`09_state_sync_after_done.log`。

- 修改文件：
  - `C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml`（+9 行）及其备份。
  - `docs/verification/stage6/00_mcp_capability.md`、`01_context7_probe.md`、`02_config_diff_proposal.md`、`03_decision.md`、`08_apply_result.md`、`apply_context7_patch.py`、`06_apply.log`、`07_post_write_verify.log`、`09_state_sync_after_done.log`。
  - `docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`。
  - `docs/memory/environment.md`、`docs/memory/references.md`。
  - `docs/CHANGELOG_DEV.md`、`docs/SESSION_HANDOFF.md`、`README.md`。

- 实际测试命令与结果：

  ```powershell
  $py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'

  & $py docs/verification/stage6/apply_context7_patch.py backup
  # BACKUP_RESULT=OK；备份 SHA256=664C…FFD8

  & $py docs/verification/stage6/apply_context7_patch.py append
  # APPEND_RESULT=OK；1462 字节 / 52 行 / SHA256=6FF6…59E1；前缀一致

  & $py docs/verification/stage6/apply_context7_patch.py verify
  # 只读复核；当前哈希=6FF6…59E1

  & $py scripts/state_sync.py validate
  & $py scripts/state_sync.py render
  & $py scripts/state_sync.py check
  # 均 exit 0；日志 09_state_sync_after_done.log
  ```

  - MCP 工具调用：`resolve-library-id(FastAPI)`、`resolve-library-id(Pydantic)`、`query-docs(/pydantic/pydantic/v2.11.0)` 均成功。
  - 2C：`web-fetch-http disabled: true`、`session-telemetry-otel mode: DISABLED`、`session-log-deepseek enabled: false`。
  - 未测：匿名额度的具体数值、断网/错 URL 负例、长时间重连。

- 当前分支与 commit：
  - 分支 `main`；`git rev-list --count --all` = 0；未执行 `git add` / `git commit`。
  - `last_verified_commit` = `null`。

- 未解决/风险：
  - 匿名额度为“低限额”，官方未给确切数值；达到限额会返回 `429`，届时只报告，不擅自加 Key。
  - Context7 文档内容与 server instructions 仍是第三方不可信输入，不得推动 ResearchFlow 状态或证据等级。
  - 两个工具的描述/schema 每轮进入请求，存在持续 token 开销；具体 token 数未测。
  - 备份文件保留；阶段验收后再决定是否删除。

- 下一步：
  1. 等待用户验收阶段 6。
  2. 验收后决定是否保留备份、是否进入阶段 7（按用户批准的范围）。
  3. 若后续需要更高 Context7 额度，由用户在 Harness 凭据界面输入 Key，再单独审批 headers 引用方式。

- 待用户确认：
  - 是否验收阶段 6。
  - 备份是否保留到验收后删除。
  - 是否进入下一阶段。

- API Key 状态：**未配置**；未读取 `.credentials.yaml`，未索取、未写入、未回显任何 Key。

- 证据目录：`docs/verification/stage6/`；执行结果见 `08_apply_result.md`，状态同步见 `09_state_sync_after_done.log`。

### 2026-11-08 · 阶段 6 · MCP Client 能力核实与 Context7 接入评估

> 历史记录：本条目记录写入前的评估与提案；实际写入与验证见上一条“Context7 接入执行与验证”。

- 本次完成：
  - 以 app.asar 内 `0.2.2-rc.1` 的 `@deepseek-ai/dsh-mcp-client` 源码核实：支持 `stdio` 与 `streamable-http`，工具名 `mcp__<serverName>__<rawName>`，默认无 server，`mcp-resources` 已挂载。
  - 只读探测 `https://mcp.context7.com/mcp`：匿名 `initialize` / `tools/list` / `tools/call` 均 200；2 个工具；返回真实 FastAPI 库 ID。
  - 新增 `docs/verification/stage6/`：能力矩阵、Context7 探测、精确配置 diff、结论与复评条件、4 个日志、2 个只读证据脚本。
  - 登记 `T-MCP-001`（`IN_REVIEW`）；`current_phase` 仍为 `WORKSTATION_SETUP`；G0–G7 仍全 `NOT_STARTED`。
  - 删除冗余 `.agents/skills/.gitkeep`；九个 Skill 不变。
  - 更新 `docs/memory/environment.md` §6.3、`docs/memory/references.md` R-14…R-17、`docs/memory/feedback-and-lessons.md` FB-20…FB-24 / L-08。

- 未完成：
  - **未写入** `C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml`；Context7 尚未在 DSH 中实际加载。
  - 未测 `query-docs` 的返回质量/长度；未测匿名额度的具体数值；未做故障注入。
  - 未做 `git add` / `git commit`；未配置 Git 身份。

- 已知问题/风险：
  - 第三方文档内容与服务器 instructions 均不可信，只能作参考，不得推动 ResearchFlow 状态或证据等级。
  - 两个 MCP 工具的描述/schema 每轮进入请求，存在持续 token 开销；具体 token 数未测。
  - 启动时会 await 首次连接与发现；`failOnStartupError: false` 可避免阻止启动，但可能增加等待。
  - 匿名额度为“低限额”，官方未给确切数值；达到限额会返回 `429`。
  - profile 下 `0.1.0-rc.8` 的 `dsh-mcp-client` 仅作解析回退；`dsh-app-boot` 契约是安装锚点优先。

- 下一步（最多 3 项）：
  1. 用户审阅 `docs/verification/stage6/02_config_diff_proposal.md`，批准或拒绝精确 diff。
  2. 若批准：备份、按精确 LF 追加 262 字节、核对 SHA256 `6FF6...159E1`、热重载或重启、在新会话验证两个工具。
  3. 若拒绝：保持不写入，按用户决定将 `T-MCP-001` 转 `DEFERRED` 或取消。

- 待用户确认：
  - 是否批准配置 diff 与同目录备份。
  - 是否允许 Harness 访问 `https://mcp.context7.com/mcp`（仅该端点）。
  - 是否接受先按匿名额度运行、暂不配置 API Key。
  - 批准后由谁执行写入与重启。

- 实际测试命令与结果：

  ```powershell
  $py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'

  & $py docs/verification/stage6/inspect_mcp_client.py
  # exit 0；INSPECT_RESULT=PASS；日志 00_mcp_source.log

  & $py docs/verification/stage6/context7_probe.py
  # exit 0；PROBE_RESULT=PASS；Context7 4.5.0；日志 01_context7_probe.log

  & $py scripts/state_sync.py validate
  & $py scripts/state_sync.py render
  & $py scripts/state_sync.py check
  # 均 exit 0；2 个生成文件一致；日志 03_state_sync.log
  ```

  - 秘密扫描：7 类模式、13 个文件、0 命中；`04_secret_scan.log`。
  - 配置快照：1,200 字节、SHA256 `664CE561...94FFD8`、无 MCP/Context7 条目；`02_config_snapshot.log`。
  - 工作区：`main`；0 commit；`.venv` 不存在；`researchflow/` 仍只有 `.gitkeep`；`05_git_status.log`。

- 当前分支与 commit：
  - 分支 `main`；`git rev-list --count --all` = 0。
  - `last_verified_commit` = `null`；未执行 `git add` / `git commit`。

- API Key 状态：**未配置**；未读取 `.credentials.yaml`，未索取、未写入、未回显任何 Key。

- 阶段 2C 非回归：
  - `web-fetch-http` 仍 `disabled: true`；`session-telemetry-otel` 仍 `mode: DISABLED`；`session-log-deepseek` 仍 `enabled: false`。
  - 未把“web_fetch 被禁用”当作“MCP 不可用”；两者是不同通道。

- 证据目录：`docs/verification/stage6/`；结论与复评条件见 `03_decision.md`。

### 2026-11-08 · 阶段 5 · ResearchFlow 专属 Skills 系统

- 本次完成：
  - 在 `.agents/skills/` 创建九个项目级 Skill Bundle（每个含 `SKILL.md`，按需含 `references/`）。
  - 核实 DSH 0.2.2-rc.1 的 Skills Provider/Registry/Consumer：`dsh-skill-filesystem` 扫描 `<projectRoot>/.agents/skills`（rank 200），实际 catalog 三次刷新后九个 Skill 全部出现。
  - 通过 Harness `skill` 工具逐个加载九个 Skill；对 onboarding、spec-driven-development、memory-handoff 完成只读/干跑执行验证。
  - 新增 `docs/SKILL_CATALOG.md`（三态分列）与 `scripts/validate_skills.py`（仅标准库）。
  - 新增 `docs/verification/stage5/`：发现机制、结构校验、秘密扫描、调用测试、状态同步、23 项回归测试、结构负例。
  - `project_state.json`：`current_phase=WORKSTATION_SETUP`；登记 `T-SKILLS-001`（`IN_REVIEW`）；G0–G7 仍全 `NOT_STARTED`；`last_verified_commit=null`。
- 修改文件：
  - `.agents/skills/researchflow-*/SKILL.md` 与对应 `references/*.md`
  - `docs/SKILL_CATALOG.md`、`scripts/validate_skills.py`
  - `docs/verification/stage5/00_discovery.md` … `06_structure_negative.log`
  - `docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`
  - `AGENTS.md`、`README.md`
  - `docs/memory/project-context.md`、`environment.md`、`references.md`、`feedback-and-lessons.md`
  - `docs/CHANGELOG_DEV.md`、`docs/SESSION_HANDOFF.md`

- 实际测试命令与结果：

  ```powershell
  $py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'

  & $py scripts/validate_skills.py
  # 9 PASS; exit 0
  # 日志：docs/verification/stage5/01_structure.log

  & $py -m unittest discover -s tests -v
  # Ran 23 tests in 3.342s; OK; exit 0
  # 日志：docs/verification/stage5/05_validation.log

  & $py scripts/state_sync.py validate
  & $py scripts/state_sync.py render
  & $py scripts/state_sync.py check
  # 均 exit 0；2 个生成文件逐字节一致
  # 日志：docs/verification/stage5/04_state_sync.log
  ```

  - 结构负例：临时副本删除 `researchflow-onboarding/SKILL.md` 后 validator exit 1；日志 `06_structure_negative.log`。
  - 秘密扫描：7 类模式、20 个文件、0 命中；日志 `02_secret_scan.log`。
  - catalog：创建后三次 replacement；最终 18 个 Skill，其中 9 个 `researchflow-*`；无重启、无改配置。
  - 九个 Skill 的 `skill` 工具加载均成功；未执行真实业务修改。

- 当前分支与 commit：
  - 分支 `main`；`git rev-list --count --all` = 0；尚无 commit。
  - `last_verified_commit` = `null`。
  - 未执行 `git add` / `git commit`；未配置 Git 身份。

- 未解决问题：
  - Git 全局 `user.name` / `user.email` 为空，提交前需用户确认（`BLK-001`）。
  - 策划书 v4.3.1 是否为唯一冻结基线尚未书面确认（`BLK-002`）。
  - 全局 `C:\Users\Administrator\.dsh\AGENTS.md` 不存在；本阶段未创建、未修改。
  - `researchflow-harness-adapter` 仅在计划中，T2 前不得创建或注册。
  - 阶段 5 未创建 `.venv`、未安装依赖、未开发业务代码。

- 下一步（最多 3 项）：
  1. 等待用户验收阶段 5；未批准前不进入阶段 6。
  2. 用户确认策划书基线与 Git 身份；确认前不 commit、不据策划书数字宣布 G0 通过。
  3. 批准阶段 6 后，按 G0 范围建立契约、Schema、状态机与错误码；不提前开发 T0 业务闭环。

- 待确认事项：
  - 是否批准阶段 5 并进入阶段 6。
  - 策划书 v4.3.1 是否为唯一基线。
  - Git 提交身份与是否允许首次 commit。
  - 是否需要单独批准全局 `AGENTS.md`（当前建议不创建）。

- 项目 AGENTS 加载证据：
  - 本会话系统提示包含 `Instructions from: AGENTS.md`。
  - 修改 `AGENTS.md` 后收到 `Updated instructions from: AGENTS.md`，内容为阶段 5 基线。

- Skills 发现证据：
  - 桌面版 0.2.2-rc.1；app.asar 内 `dsh-skill-filesystem@0.2.2-rc.1/lib/index.js` 第 160–190 行扫描 `.agents/skills`。
  - 实际 catalog 在创建 1 个、5 个、9 个 Skill 后各刷新一次；九个全部出现。
  - 未在 `.dsh/skills` 或全局目录创建同名 Skill。

- 证据目录：`docs/verification/stage5/`；三态目录：`docs/SKILL_CATALOG.md`。

### 2026-11-08 · 阶段 4 · 持久记忆与动态状态系统

- 本次完成：
  - 建立项目级 `AGENTS.md`（行为规范、任务工作流、本机环境约束、14 条架构约束、第一版范围、研发/运行时状态分离）。
  - 建立 `docs/memory/` 索引与 5 个记忆子文件；建立 `docs/state/runtime_states.md`。
  - 建立 `docs/state/project_state.json`：`tasks` 为空、G0–G7 全部 `NOT_STARTED`、2 个 OPEN 阻塞、`last_verified_commit=null`。
  - 实现 `scripts/state_sync.py`（`validate` / `render` / `check`）与 `tests/test_state_sync.py`（23 个端到端测试）。
  - 生成 `docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`；新增 `.gitattributes` 固定 LF。
  - 保存真实验证日志到 `docs/verification/stage4/`；更新 `README.md`、`CHANGELOG_DEV.md`。
- 修改文件：
  - `AGENTS.md`、`README.md`、`.gitattributes`
  - `docs/memory/Memory.md`、`project-context.md`、`architecture-decisions.md`、`feedback-and-lessons.md`、`environment.md`、`references.md`
  - `docs/state/project_state.json`、`docs/state/runtime_states.md`
  - `docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`
  - `scripts/state_sync.py`、`tests/test_state_sync.py`
  - `docs/CHANGELOG_DEV.md`、`docs/SESSION_HANDOFF.md`
  - `docs/reference/GLOBAL_AGENTS_PROPOSAL.md`
  - `docs/verification/stage4/00_environment.log` … `07_check_after_restore.log`

- 实际测试命令与结果：

  ```powershell
  $py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'

  & $py -m unittest discover -s tests -v
  # Ran 23 tests in 3.392s; OK; exit 0
  # 日志：docs/verification/stage4/02_unittest.log

  & $py scripts/state_sync.py validate
  # OK; exit 0
  # 日志：docs/verification/stage4/01_validate.log

  & $py scripts/state_sync.py render
  # 生成 2 个文件；exit 0
  # 日志：docs/verification/stage4/03_render.log

  & $py scripts/state_sync.py check
  # 2 个生成文件逐字节一致；exit 0
  # 日志：docs/verification/stage4/04_check.log、07_check_after_restore.log

  # 负例：手工篡改 docs/PROJECT_STATE.md 后
  & $py scripts/state_sync.py check
  # exit 1，指出文件、预期/实际 SHA256、差异
  # 日志：docs/verification/stage4/05_check_after_tamper.log
  ```

- 当前分支与 commit：
  - 分支 `main`；`git rev-list --count --all` = 0；尚无 commit。
  - `last_verified_commit` = `null`。
  - 未执行 `git add` / `git commit`；未配置 Git 身份。

- 未解决问题：
  - Git 全局 `user.name` / `user.email` 为空，提交前需用户确认（`BLK-001`）。
  - 策划书 v4.3.1 是否为唯一冻结基线尚未书面确认（`BLK-002`）。
  - 全局 `C:\Users\Administrator\.dsh\AGENTS.md` 不存在；本阶段未创建，若未来需要须单独审批。
  - 阶段 4 只完成治理基线；ResearchFlow 业务代码、`.venv`、依赖、PRD、contracts、ADR 均尚未建立。

- 下一步（最多 3 项）：
  1. 等待用户批准阶段 5，并确认 G0 规格冻结的范围与交付顺序。
  2. 用户确认策划书基线版本与 Git 身份；确认前不 commit、不据策划书数字宣布 G0 通过。
  3. 批准后按 G0 计划先建立 `contracts/`、Schema、状态机与错误码，不提前开发 T0 业务闭环。

- 待确认事项：
  - 是否批准进入阶段 5 / G0。
  - 策划书 v4.3.1 是否为唯一基线。
  - Git 提交身份与是否允许首次 commit。
  - 是否需要单独批准全局 `AGENTS.md`（当前建议不创建）。

- 项目 AGENTS 加载证据：
  - 本会话启动时系统提示包含 `Instructions from: AGENTS.md`。
  - 重写 `AGENTS.md` 后收到 `Updated instructions from: AGENTS.md`，内容为新版本。
  - DSH `standard` preset 在 `config/agent-presets/standard/agent.cordis.yml` 第 30–31 行挂载 `@deepseek-ai/dsh-agent-instructions`。
  - 全局 `C:\Users\Administrator\.dsh\AGENTS.md` 不存在。

- 证据目录：`docs/verification/stage4/`（含环境、validate、23 项测试、render、check、篡改负例与恢复日志）。
