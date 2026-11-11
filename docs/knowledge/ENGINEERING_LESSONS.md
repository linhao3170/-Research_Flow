# ENGINEERING_LESSONS — ResearchFlow 工程经验库

> 版本：v1.0｜快照日期：2026-11-10｜范围：2026-11-08（阶段 3B）至 2026-11-10（WP-02 验收）。
> 性质：带日期的一次性经验快照，不是开发日志、状态文件、对话总结或 `AGENTS.md` 副本；仅在发生新事故时追加，不做定期维护。
> 来源范围：`AGENTS.md`、`docs/memory/*.md`、`docs/CHANGELOG_DEV.md`、`docs/SESSION_HANDOFF.md`、`docs/ADR/`、`docs/verification/**`、`tests/` 与测试记录、`git log 91bde66..HEAD`（含基线 `91bde66` 共 5 个提交：`91bde66`、`6c1783c`、`19c337f`、`678d2e8`、`29902ef`）。
> 收录口径：只收真实发生且有后果的问题、导致误判/误改的问题、环境/依赖/权限/测试缺口；不收聊天、无后果讨论、重复过程总结、纯代码流水。
> 边界：当前进度只以 `docs/state/project_state.json` 为准，本文不复述；架构决策以 ADR 为准，验证结论以对应日志为准；与 `AGENTS.md` 冲突时以 `AGENTS.md` 为准，本文不新增规则；不替代 `CHANGELOG_DEV.md` 与 `SESSION_HANDOFF.md`。
> 已固化、不再展开：`AGENTS.md` §4/§8；`docs/ADR/ADR-001`–`ADR-006`（ACCEPTED）与 `ADR-007`（PROPOSED）；`docs/design/05_CONTRACTS_AND_STATES.md` 与 `06_DATA_AND_API.md` 的规则。

### LESSON-001 证据日志被同名脚本覆盖，且无 Git 基线时不可恢复

- 分类：验证与证据
- 背景与表现：2026-11-09 做 G0 文档链接检查时，直接运行 `docs/verification/stage7/check_links.py`，未先确认脚本的 `OUT` 常量；脚本按设计把结果写回 `14_link_check.log`，把阶段 7 记录的 232 links 覆盖为 239 links。仓库当时 0 commit、无备份，原 106 字节 / SHA256 `B9FDD0AB…` 无法恢复，只能追加说明。
- 根因：已确证。脚本输出路径硬编码为自身目录下的固定文件，重跑即覆盖；当时没有 Git 基线或副本可回滚。
- 处理：停止再运行该脚本；新增只读 `docs/verification/g0/check_links_g0.py`（只写 stdout）；新增 `SUPERSEDED_NOTICE.md` 登记原值/现值/原因/不可恢复；阶段 7 报告仍保留 232，不改写历史。
- 预防：已落地：只读脚本 + `docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md` §3 风险 14（证据日志只追加、输出路径显式参数化、禁止默认覆盖）+ `SUPERSEDED_NOTICE.md` 追加式登记模板。未落地：没有通用检查扫描 evidence 脚本是否写固定路径。
- 状态：RESOLVED ｜ 证据：VERIFIED
- 来源：`docs/verification/stage7/SUPERSEDED_NOTICE.md#L20-L36`；`docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md#L76`；`docs/CHANGELOG_DEV.md#L245`；`docs/verification/stage7/STAGE7_REPORT.md#L216`
- 固化去向：`docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md` §3 风险 14。

### LESSON-002 workspace-write 沙箱不向运行期新建子目录传播授权，23 项测试在 setUp 全失败

- 分类：工具与沙箱
- 背景与表现：2026-11-08 阶段 7/8 在 `workspace-write` 下运行 `unittest discover -s tests`，23 项测试出现 43 个 `PermissionError [WinError 5]`，全部发生在 `tempfile.TemporaryDirectory()` 创建后的 `mkdir`/`cleanup`，无断言失败。后果是 13b 不能判 PASS，`BLK-003` 保持 OPEN/MEDIUM，测试只能在单独批准的全权限会话做代码正确性参考。
- 根因：已确证到环境侧：DSH 权限诊断结论 `NOT_THIS_CLASS`，`WRITE_DAC`/`WRITE_OWNER` 均具备，`FIXED=0`，排除仓库 ACL 损坏；机制为沙箱进程新建子目录未继承项目根授权。DSH 内部实现细节未读到源码，未确证。
- 处理：保留 `32_unittest_workspacewrite.log` 原样；`BLK-003` 由 HIGH 降 MEDIUM 但保持 OPEN；13b 维持 NOT VERIFIED；全权限 23/23 只作历史记录，不得用于安全项；不手工改 ACL、不重复诊断。
- 预防：未落地（仅登记 `docs/state/G0_DECISION_LIST.md` R-1 的绕行边界，无自动沙箱探针/CI 检查）。建议在 T0 测试入口加“工作区新建子目录可写”探针。
- 状态：OPEN ｜ 证据：VERIFIED
- 来源：`docs/verification/stage8/STAGE8_REPORT.md#L65-L78`；`docs/verification/stage8/32_unittest_workspacewrite.log#L1-L5`；`docs/verification/stage8/32_unittest_workspacewrite.log#L1465`；`docs/state/G0_DECISION_LIST.md#L27`；`docs/verification/stage7/18_unittest_attempt.md#L29-L37`；`docs/state/project_state.json#L529-L540`

### LESSON-003 验收与测试结果未绑定运行时沙箱/审批策略，同一套测试无法复用

- 分类：验证与证据
- 背景与表现：阶段 8 初验在用户切到 `danger-full-access` / 审批关闭后运行，第 5、6、23 项 FAIL；全权限下 23/23 OK，但不能作为 workspace-write 证据，恢复策略后三项重跑才 PASS。WP-02 的 `pytest tests` 记录 `125 passed`，日志只写 pytest/解释器，没有记录当次沙箱与审批策略；该结果包含 23 项 state_sync 测试，却无法用来关闭 13b。
- 根因：已确证：现有测试/验收日志模板只要求命令、解释器、退出码、日志路径与时间，没有 `file_policy`/`approvals` 字段；阶段 8 补验日志有 `POLICY=workspace-write`，WP-02 的 `full_suite.log` 没有。
- 处理：阶段 8 补验单独记录 `30_policy_restored.log`/`34_item6_23_workspacewrite.log` 的策略；13b 只引用 workspace-write 日志；全权限 23/23 仅作历史；WP-02 未宣告关闭 13b。
- 预防：未落地（无统一 test runner/日志头模板强制记录策略）。建议在测试报告模板固定写 `file_policy`、`approvals` 两行，由启动包装器写入。
- 状态：OPEN ｜ 证据：UNVERIFIED
- 来源：`docs/verification/stage8/STAGE8_REPORT.md#L17-L25`；`docs/verification/stage8/STAGE8_REPORT.md#L108-L112`；`docs/verification/t0/wp-02/full_suite.log#L1-L3`；`docs/verification/t0/wp-02/WP-02_REPORT.md#L31-L34`；`docs/state/G0_DECISION_LIST.md#L27`

### LESSON-004 0 commit 时无法验收 Git 回滚，证据覆盖也没有恢复源

- 分类：流程与协作
- 背景与表现：阶段 8 第 20 项要求 Git 可审查、可回滚，但仓库当时 0 commit、0 tracked，回滚未实测，只能判 NOT VERIFIED；同一时期被覆盖的 `14_link_check.log` 也没有 Git 历史可取回。直到 2026-11-10 建立基线 `91bde66`，才用探针 + `git checkout --` 补测通过。
- 根因：已确证。阶段 3B–8 期间未建立基线 commit（等待用户身份/批准），回滚没有可回滚对象，覆盖也没有恢复源。
- 处理：用户 2026-11-10 批准仓库级身份并建立 G0 基线；在 `CHANGELOG_DEV.md` 写探针，确认 `git status`/`git diff` 可见，`git checkout --` exit 0，blob/SHA256 回到 HEAD；第 20 项转 PASS（基线建立后补测）。
- 预防：已落地：基线 `91bde66`、`18_git_rollback.log`、`19_g0_pass_decision.md` §3。未落地：没有“长证据产出前先建基线”的强制检查项。
- 状态：RESOLVED ｜ 证据：VERIFIED
- 来源：`docs/verification/stage8/STAGE8_REPORT.md#L50-L51`；`docs/state/G0_DECISION_LIST.md#L29`；`docs/verification/g0/19_g0_pass_decision.md#L42-L57`；`docs/CHANGELOG_DEV.md#L303-L327`；commit `91bde66`、`6c1783c`

### LESSON-005 文件名版本号与文档内部版本不一致，差点把不存在的 v4.3.1 写进 G0

- 分类：契约与接口
- 背景与表现：根目录策划书文件名是 `v4.3.1`，但封面、页眉、正文升级说明、文档控制表、core 属性全部写 `v4.3.0`，文档内 `v4.3.1` 计数为 0。若按文件名冻结，需求基线、Schema/API 与验收合同都会引用一个不存在的版本；`BLK-002` 一度阻断 G0，直到用户书面确认“内容基线=内部 v4.3.0，v4.3.1 只是文件名标签”。
- 根因：未确证（缺少真正的 v4.3.1 原件或变更说明；只能证明文件名与内部标识不一致，不能判定是文件名多 `.1` 还是内容少一次升级）。
- 处理：阶段 7 全文抽取并逐处登记；`CONFLICT_REPORT` C-001 列原文/位置/影响/方案；不自行裁决，`BLK-002` 保持 OPEN；用户决议后关闭；新文档统一写“内部 v4.3.0（文件名 v4.3.1）”；旧记录不改写。
- 预防：已落地：`SOURCE_REGISTER.md` 的版本证据字段与“文件名是标签，不是内部版本证据”口径；`CONFLICT_REPORT` 保留 §1.1–1.6 决议前证据。未落地：没有脚本在引用策划书版本时自动比对封面/页眉/正文/文件名。
- 状态：RESOLVED ｜ 证据：VERIFIED
- 来源：`docs/reference/CONFLICT_REPORT.md#L25-L54`；`docs/reference/CONFLICT_REPORT.md#L100-L114`；`docs/verification/stage7/STAGE7_REPORT.md#L104-L119`；`docs/memory/feedback-and-lessons.md#L93-L99`；commit `91bde66`
- 固化去向：`docs/reference/SOURCE_REGISTER.md` §0 硬规则 3。

### LESSON-006 DOCX 属性日期/页数是模板残留，Word COM 又阻塞，页码只能放弃

- 分类：状态与文档治理
- 背景与表现：DOCX `core.xml` 的 created/modified 是 `2013-12-23`，`app.xml` 的 `Pages=1`、`Words=0`，与文档控制表 `2026-11-06`、正文 754 段/80 表矛盾；尝试 Word COM 只读分页时进程 180 秒无返回，未取得页码。若把属性当元数据，会写出错误日期/页数；若估算页码，会伪造引用。
- 根因：已确证（属性为 `python-docx` 生成残留，与正文计数矛盾）；Word COM 阻塞的具体原因未确证（未读到 Word 进程/自动化日志，仅观察到超时）。
- 处理：日期引用文档控制表/文件系统；页数标“不可用”；引用改用 `§章节 + P#### / TABLE ##` 锚点；不安装 LibreOffice/WPS、不改注册表；`06_page_map_attempt.md` 记录失败过程。
- 预防：已落地：`CONFLICT_REPORT` C-004/C-005 与 `SOURCE_REGISTER` 的“属性不可作证据/页码不可得”口径；知识文档统一锚点。未落地：无自动校验“引用页码时必须有可信分页来源”。
- 状态：RESOLVED ｜ 证据：VERIFIED
- 来源：`docs/verification/stage7/06_page_map_attempt.md#L8-L43`；`docs/reference/CONFLICT_REPORT.md#L16-L17`；`docs/memory/feedback-and-lessons.md#L101-L106`；`docs/verification/stage7/STAGE7_REPORT.md#L121-L129`

### LESSON-007 uv 默认缓存目录在工作区外，`uv venv` 首次创建失败

- 分类：环境与依赖
- 背景与表现：WP-01 执行 `uv venv --python 3.11.16 .venv` 时，uv 尝试初始化 `C:\Users\Administrator\AppData\Local\uv\cache`，被 workspace-write 沙箱拒绝，创建失败；首次工具捕获 exit 1，复现实测 uv exit 2。改用项目内 `UV_CACHE_DIR=D:\ResearchFlow-project\.uv-cache` 后 exit 0（0.51 s）。
- 根因：已确证：默认 uv 缓存在工作区沙箱之外，沙箱拒绝写该路径。工具层 exit 1 与 uv 自身 exit 2 的差异未确证（未定位包装层退出码映射）。
- 处理：设置项目内 `UV_CACHE_DIR` 重试；记录 `venv_cache_failure.log`；不改用 PATH 的 3.12 或 `py -3.11`；`.uv-cache` 不纳入 Git。
- 预防：未落地（仅写入 `docs/memory/environment.md` §2.5 与 WP-01 复现命令；无脚本在创建 venv 前自动设置/检查 `UV_CACHE_DIR`）。
- 状态：RESOLVED ｜ 证据：VERIFIED
- 来源：`docs/verification/t0/wp-01/WP-01_REPORT.md#L15-L22`；`docs/verification/t0/wp-01/venv_cache_failure.log#L1-L7`；`docs/memory/environment.md#L55-L70`；commit `19c337f`

### LESSON-008 依赖矩阵漏了 `httpx2`，TestClient 冒烟才发现

- 分类：环境与依赖
- 背景与表现：矩阵锁定 16 个直接 pin 后，`TestClient` 首次冒烟 exit 1，报 `The starlette.testclient module requires the httpx2 package`；starlette 1.10.0 的元数据是 `Requires-Dist: httpx2>=2.0.0; extra == 'full'`。若没有冒烟，测试导入会整体失败，或被误判为业务代码问题。
- 根因：已确证：依赖矩阵只覆盖直接运行依赖，没有覆盖 starlette 1.x `TestClient` 的测试 extra；`httpx2` 不是 `httpx`，名字差异也容易漏。
- 处理：报告用户并获批准后安装 `httpx2==2.16.0`（含 `httpcore2`、`truststore`）；`requirements.in` 记录矩阵外新增；`requirements.lock` 锁 58 包；干净 `.venv-repro` 从锁文件复现 TestClient 200。
- 预防：已落地：`requirements.lock` 作为唯一安装源；`docs/design/07_T0_PLAN_AND_GATES.md` §2.1 WP-01 入口条件第 4 条要求 starlette 安装后必须跑 TestClient 冒烟；WP-01 验收标准第 3/4 条把 `httpx2` 批准与锁文件复现写入。
- 状态：RESOLVED ｜ 证据：VERIFIED
- 来源：`docs/verification/t0/wp-01/WP-01_REPORT.md#L74-L80`；`docs/verification/t0/wp-01/install_httpx2.log#L1-L6`；`docs/design/07_T0_PLAN_AND_GATES.md#L82-L88`；`docs/verification/t0/wp-01/30_wp01_acceptance.md#L24-L27`；commit `19c337f`
- 固化去向：`docs/design/07_T0_PLAN_AND_GATES.md` §2.1 WP-01 入口条件 4。

### LESSON-009 `check_model_parity.py` 每次重写带时间戳的 `model_parity.json`，验收后工作区变脏

- 分类：验证与证据
- 背景与表现：WP-02 把 `docs/verification/t0/wp-02/model_parity.json` 纳入 Git；脚本 `generated_at` 取 `datetime.now()`，默认输出到该固定路径。验收后再次运行 parity，`generated_at` 从 `22:35:50` 变为 `22:38:12`，`git status` 出现 M；重跑检查会持续制造 diff，破坏“验收后工作区干净”的可核性。
- 根因：已确证：脚本 L203 生成当前时间，L226-L240 默认写回受版本控制路径；没有 `--check`/只读模式，也没有临时输出约定。
- 处理：当前未处理；验收记录仍引用该 JSON 的 `structure` 段；`git status` 的 M 保留未提交（本次审计未改）。脚本已有 `--json-out` 可改路径，但默认行为未改。
- 预防：未落地（无 `--check`/只读模式，未把 `model_parity.json` 改为生成物忽略或 CI 临时目录输出）。建议默认写临时文件，或仅在显式 `--json-out` 时写文件。
- 状态：OPEN ｜ 证据：VERIFIED
- 来源：`scripts/check_model_parity.py#L203-L240`；`docs/verification/t0/wp-02/model_parity.json`；`docs/verification/t0/wp-02/WP-02_REPORT.md#L31-L34`；commit `29902ef`

### LESSON-010 验收日志残留 `{state_hash[:16]}` 模板占位符，哈希不可核

- 分类：状态与文档治理
- 背景与表现：`CHANGELOG_DEV.md` 的 WP-01 验收条目写 `PROJECT_STATE.md SHA256 {state_hash[:16]}…`、`IMPLEMENTATION_STATUS.md SHA256 {status_hash[:16]}…`，模板变量未渲染就追加进 append-only 日志。后果是验收记录中的哈希不可核；实际值只存在于 `state_sync_acceptance.log` 与 `30_wp01_acceptance.md`。
- 根因：已确证：生成验收记录时直接复制了带占位符的模板/代码片段，没有做变量替换；追加前也没有检查 `{...}` 残留。
- 处理：不改写历史 CHANGELOG（append-only）；实际哈希在 `state_sync_acceptance.log` 与 `30_wp01_acceptance.md` §5 可查；本快照登记该缺陷。
- 预防：未落地（无“证据文本禁止 `{...}` 占位符”的检查脚本）。建议在写 CHANGELOG/验收记录前 grep `\{[a-z_]+\[`，或统一用模板渲染函数。
- 状态：OPEN ｜ 证据：VERIFIED
- 来源：`docs/CHANGELOG_DEV.md#L366`；`docs/verification/t0/wp-01/state_sync_acceptance.log#L1-L15`；`docs/verification/t0/wp-01/30_wp01_acceptance.md#L60-L63`；commit `678d2e8`

### LESSON-011 `DEVELOPMENT_WORKFLOW.md` 仍写 `last_verified_commit=null`、0 commit，与状态文件冲突

- 分类：状态与文档治理
- 背景与表现：`project_state.json` 已记录 `last_verified_commit=19c337f...`，但 `DEVELOPMENT_WORKFLOW.md` §9 仍写“当前 `last_verified_commit=null`；0 commit”。读者/AI 若先读流程文档，会把已建立的基线当成不存在，也违反 `AGENTS.md` §7“状态只以 `project_state.json` 为准”的单一事实源。
- 根因：已确证：流程文档把可变状态写进正文，2026-11-10 G0/WP-01 更新时没有同步或删除该段；没有生成/校验机制。
- 处理：本快照只登记，不改该文档（超出本次边界）；实际状态以 `docs/state/project_state.json` 为准。
- 预防：未落地（无“流程文档禁止写可变状态”的检查项）。建议流程文档只写“读 project_state.json”，删除具体 commit/值；或在 `state_sync.py` 中加入文档扫描。
- 状态：OPEN ｜ 证据：VERIFIED
- 来源：`docs/DEVELOPMENT_WORKFLOW.md#L185-L193`；`docs/state/project_state.json#L541`；`docs/CHANGELOG_DEV.md#L356-L368`
- 固化去向：`AGENTS.md` §7。

### LESSON-012 阶段 8 第 2 项只做静态确认，2D 未单独执行，2C 运行态未观测

- 分类：验证与证据
- 背景与表现：阶段 8 第 2 项要求“2C 三项配置与 2D 结论一致”，实际只做只读核对 `cordis.patch.yml` 三块与阶段 6 非回归日志；项目内没有独立 2D 报告，2C 运行态未观测。该项被判“静态确认 PASS / 运行态未观测”，作为 G0 残留风险 R-2 保留。后果是安全配置的“运行态有效”没有被证明，只是配置值正确。
- 根因：已确证：2D 报告未在项目内落地；验收项没有可执行的运行态观测步骤，只有静态检查。为什么 2D 未执行，现有材料未给出原因（未确证）。
- 处理：在 `STAGE8_REPORT` 明确写“静态确认 / 运行态未观测”，不写成 PASS；`G0_DECISION_LIST` R-2 保留；G0 PASS 决议未把它写成已验证，只作为残留风险。
- 预防：未落地（无 2C/2D 运行态探针或验收模板）。建议后续把“配置值 + 运行态观测”拆成两个必检子项，缺运行态即 NOT VERIFIED。
- 状态：OPEN ｜ 证据：VERIFIED
- 来源：`docs/verification/stage8/STAGE8_REPORT.md#L32`；`docs/verification/stage8/STAGE8_REPORT.md#L82`；`docs/state/G0_DECISION_LIST.md#L28`；`docs/verification/stage8/02_security_2c.md`

### LESSON-013 PowerShell 捕获的测试日志中，中文错误信息按本地代码页落盘成乱码

- 分类：工具与沙箱
- 背景与表现：`32_unittest_workspacewrite.log` 中 `PermissionError: [WinError 5]` 后的中文原因显示为乱码（本应是“拒绝访问”）；路径与 `EXIT=1` 仍可读，但错误原因文字已损坏。阶段 7 的 L-01 已经记录过“终端代码页会破坏中文输出”，本次在 PowerShell `2>&1` 重定向日志时复发。
- 根因：已确证现象；具体是 PowerShell 重定向、`$OutputEncoding` 还是 Python stderr 编码导致，未定位（缺少同一次运行的编码设置记录），未确证。
- 处理：阶段 8 报告用中文转述“拒绝访问”，并同时保留 `31_blk003_probe.log` 的可读英文 `Permission denied` 与路径；没有改写原始日志。
- 预防：未落地（无统一测试运行器强制 `PYTHONUTF8=1`、`[Console]::OutputEncoding` 与 UTF-8 重定向）。建议后续测试包装器统一设置编码并把 `POLICY` 一起写入日志头。
- 状态：OPEN ｜ 证据：VERIFIED
- 来源：`docs/verification/stage8/32_unittest_workspacewrite.log#L1465`；`docs/memory/feedback-and-lessons.md#L42-L47`；`docs/memory/environment.md#L101-L105`；`docs/verification/stage8/31_blk003_probe.log`

### LESSON-014 G0 提交前记录称工作区干净，实际 `AGENTS.md` 有未提交修改

- 分类：流程与协作
- 背景与表现：2026-11-10 G0 PASS 提交前，记录中的工作区状态是“干净”，但 `git status` 显示 `AGENTS.md` 有未提交修改（新增两条正例/负例证据规则）。若直接按“干净”提交，会把未单独审阅的规则变更混入 G0 基线；实际处理是报告用户并获批准后纳入该提交。
- 根因：已确证：记录声明与仓库实际状态不一致；前一修改未提交，提交前也没有用 `git status`/`git diff` 复核。为什么未提交，记录未说明（未确证）。
- 处理：提交前实测 `git status` 发现差异；向用户报告并获批准，把 `AGENTS.md` 修改纳入 `chore(g0)` 提交；`19_g0_pass_decision.md` §4 如实记录“与宣布的干净不一致”，未改写为干净。
- 预防：未落地（无 pre-commit 检查脚本）。建议提交前固定执行 `git status --porcelain` + `git diff --stat`，并把结果写入提交记录；不以口头声明替代 `git status`。
- 状态：RESOLVED ｜ 证据：VERIFIED
- 来源：`docs/verification/g0/19_g0_pass_decision.md#L59-L61`；commit `91bde66`；`docs/CHANGELOG_DEV.md#L311`

## 统计

- 条目总数：14
- 分类：环境与依赖 2（007/008）；工具与沙箱 2（002/013）；状态与文档治理 3（006/010/011）；契约与接口 1（005）；验证与证据 4（001/003/009/012）；流程与协作 2（004/014）。
- 状态：RESOLVED 7（001/004/005/006/007/008/014）；OPEN 7（002/003/009/010/011/012/013）。
- 证据：VERIFIED 13；UNVERIFIED 1（003：WP-02 那次 125-pass 的运行时策略无记录，无法复核）。

## 未纳入但建议保留的历史材料

1. `docs/verification/stage4/`–`stage6/`：阶段 4–6 的治理、Skills 与 MCP 证据；本快照未逐条提炼，但它们是 23 项测试基线、Skills 发现与 Context7 接入的原始证据。
2. `docs/verification/stage7/18_unittest.log` 与 `docs/verification/stage8/13_unittest_fullaccess.log`：前者是 BLK-003 的 workspace-write 原始失败记录；后者是全权限 23/23 的历史记录，保留但必须继续标注“不得用于 13b 或安全项”。
3. `docs/verification/stage7/14_link_check.log`、`16_final_inventory.log`、`SUPERSEDED_NOTICE.md`：三件必须一起保留；单独保留任何一件都会失去“原值/现值/不可恢复”的对照。
4. `docs/verification/g0/05_git_baseline_report.md`、`06_first_commit_filelist.txt`：首提 282 文件与 DOCX 排除的决策证据；后续若质疑“为什么没提交 DOCX”需要它们。
5. `docs/reference/CONFLICT_REPORT.md` §1.1–1.6：版本冲突的决议前证据；`C-001` 虽已关闭，但原证据不能删，否则无法解释决议依据。
6. `docs/verification/t0/wp-01/venv_cache_failure.log`、`install_httpx2.log`、`size_and_timing.md`：环境偏差的原始证据；不要用“最终成功”覆盖失败记录。
7. `docs/verification/stage7/06_page_map.log`、`docx_page_map.ps1`：页码不可得的失败证据；删除会让“为什么不用页码”无法复核。
8. `docs/verification/stage8/32_unittest_workspacewrite.log`（乱码原文）与 `31_blk003_probe.log`（可读英文）：两件一起保留，才能同时证明环境阻塞与编码问题。
9. `docs/state/G0_DECISION_LIST.md`、`docs/SESSION_HANDOFF.md` 的旧条目：阶段 8 的原始裁决与交接；保留历史，不改写。
10. `docs/verification/t0/wp-02/model_parity.json`：当前为 M 状态；在脚本改为只读/临时输出之前保留，不要用新生成物覆盖。

## 后续可归档清单（只给建议，不执行）

> 原则：凡被 `project_state.json` 的 `evidence_paths` 或当前文档链接引用的文件，先断链再移动；不要删除。

1. `docs/verification/stage4/`、`stage5/`：可在 T0 不再引用 23 项测试基线后整体归档；前置是更新 `18_unittest_attempt.md` 与 `project_state.json` 的引用。
2. `docs/verification/stage6/`：可在 MCP 配置冻结且不再变更后归档；保留 `08_apply_result.md` 与 `07_post_write_verify.log` 的可达性。
3. `docs/verification/g0/10*`–`17*`：G0 已 PASS，但仍被 `project_state.json` 的 G0 `evidence_paths` 引用；未改引用前不得移动。
4. `docs/verification/stage8/13_unittest_fullaccess.log`：仅历史记录；可在 `STAGE8_REPORT`/`G0_DECISION_LIST` 改为指向归档路径后移动，不得删除。
5. `docs/verification/stage7/02_docx_body.txt`、`05_docx_tables.txt`：体量大但仍是 `P####`/`TABLE ##` 的唯一锚点；所有引用改为归档路径前不得移动。
6. `docs/verification/stage7/06_page_map.log`、`docx_page_map.ps1`：可在“页码不可得”结论不再被引用后归档；当前仍支撑 C-005，建议保留。
7. 非归档对象：`.pytest_cache/`、`__pycache__/`、`.uv-cache/` 属本地缓存，可按环境策略清理；`tmpavet2qv9` 按既有决议只删除该空目录，另行处理。