# SESSION_HANDOFF

> 会话交接文件。每次大任务结束前更新；最新交接置于最上方。
> 只记录已确认事实与真实测试结果；未确认内容标记“待核实”。

## 2026-11-15 · T0 · 首次提交与推送完成，远端干净快照验证通过

- 授权与执行：用户授权普通 commit + push 已验收 T0，本轮由 Harness 执行（Codex 未代执行）；此前“暂不 commit”作废。未启动 T1。
- 远端与可见性：`https://github.com/linhao3170/-Research_Flow.git`（前导连字符保留），空仓库起步；**实际为公开仓库**（GitHub API `private=false`、`visibility=public`），与此前“按私有仓库预期”不符；已报告，未修改可见性设置。
- 提交：内容提交 `35ab02bfe3d54799acb40e9a2ff632661d853111`（1783 files，+204801/−366），收尾文档提交 `0c9456a976ac404cb59dab1ea4da509a8defb657`；本条目的文字修订如另成提交，最终 SHA 以 `git log` 与远端 `main` 为准。身份 `ResearchFlow Dev <dev@researchflow.local>`，全局身份仍为空。
- 推送：`git push -u origin main` exit 0（8.1 s，`* [new branch] main -> main`）；本地 HEAD、`git ls-remote origin refs/heads/main`、GitHub API `commits/main` 三方 SHA 一致；未 force push、未改写历史。
- 干净快照：`runtime/clean-verify-20261115`（远端克隆，14.34 MB，HEAD 同上）；required entries 齐全，无 `.venv`、`runtime/`、SQLite 或私钥文件。`state_sync.py validate` / `check` exit 0；`validate_contracts.py` 72/72；`verify_bundle.py -E` 三次 `VERIFIED`（external trust anchor、32 证据、必检 8/8、L3 1.0）。
- 关键修复：`.gitattributes` 对 `docs/verification/t0/e2e/**` 与 `docs/verification/t0/g6-t0/**` 设 `-text`，按原始字节入库，避免 CRLF→LF 归一化导致新克隆离线验签失败（修正前 run_1 有 34/65 文件字节不一致，修正后 1427/1427 一致）。
- 验证口径：本轮真实运行契约 10/10、72/72、`state_sync` validate/render/check、`docs drift` ERROR=0/WARNING=1、索引与 7 个历史提交秘密扫描 0 findings；**历史 351 passed 未重跑**，不写成本轮通过；`last_verified_commit` 未改成 HEAD（仍 `1c9a10461c50c02058ce28be8b4b09c0c8870e80`）。本批无新增业务负例；验收负例沿用 A-01/A-02 记录。
- 并行写入：收尾期间其他会话创建了未跟踪的 `docs/goals/GOAL_02_EXECUTION_GUIDE.md`；未暂存、未提交，本会话未据其启动 T1。
- 未完成：T1/Goal 2 未启动；完整 G6（五类负例矩阵）、G4/G5/G7 未做；workspace-write 全绿（`BLK-003`）未取得；工作台分页/下载/失效原因未实现；预算余额未核实。
- A/B/C 遗留：`verify_bundle.py` 对 `coverage.missing` 算术与证书 `l3_coverage` 跨对象一致性仍属 B 类补强；`researchflow/api/app.py` 模块级 `app` 绕过 `serve()` 守卫是已披露入口边界；详见 `docs/verification/t0/T0_ACCEPTANCE.md` §4。
- 预算：开发 API **15.00 元**为本次用户确认的一次性记录（`docs/verification/budget/BUDGET_LEDGER.md`），更早批次与总余额未核实，不推算 185 元；产品运行 API 沿用 T0 无模型调用 **0 元**。
- 长期记忆：本轮更新 `docs/memory/environment.md`（origin、公开可见性、证据 `-text` 规则）与 `docs/memory/feedback-and-lessons.md`（L-17 证据字节入库）；`docs/memory/Memory.md` 索引无需变更；其余记忆文件已复核，无新增稳定事实。
- 环境与证据限制：全部 T0 测试在 `danger-full-access` 下运行（不写成 workspace-write 通过）；断网为“代码无外呼 + 代理黑洞 + 无模型客户端”，非 OS 级；L3 为“新目录 + 独立进程 + 原始数据重训”，非跨机；公开仓库如需转私有由用户在 GitHub 侧操作。
- 下一步：用户决定是否将仓库转私有、是否启动 T1；若启动，先读 `docs/goals/GOAL_02_COMPETITIVE_PRODUCT.md` 与 `MEMORY_CLOSEOUT`，按既有审批推进。本条目的文档收尾变更作为普通提交推送，其哈希以 `git log` 与远端 `main` 为准。

## 2026-11-15 · T0 提交审核完成，交由 Harness 提交

- 最新授权：用户要求提交 T0，并指定 **Harness 负责常规实施、commit 和 push；Codex 负责核心审核、方案判断及部分难点开发**。此前“验收 T0，暂不 commit”仅为历史记录；本次提交已获授权，不等于 T1 开工授权。
- 执行入口：`docs/verification/publication/2026-11-15/PUBLISH_HANDOFF.md`。目标 `https://github.com/linhao3170/-Research_Flow.git`，前导连字符必须保留；远端可见性、是否为空及访问权限待核实。
- 本轮已做：T0 收口材料核对、提交范围审核、忽略本地 runtime/数据库及临时文件、工作区候选扫描、预算记账和记忆同步。P9/P10 草稿保持 BLOCKED；保留现状不构成实施批准。
- 预算：本次开发 API **15 元，用户确认**；同批记录只计一次。更早消耗与累计余额未知，不能推算 185 元。产品侧沿用 T0 无模型调用的 0 元记录。
- 验证：state_sync validate/render/check 已通过；候选扫描记录见 `working_audit.json`。历史业务全量为 351 passed（395.66s），本轮未重跑。会话开始 docs drift 为 ERROR=0/WARNING=1，收尾未重跑；最终 staged 扫描与必要检查由 Harness 执行。
- Git：只读核对分支 main、7 个历史提交、HEAD `309083e715cb59a1f0c181d95df44e1946ffbaa5`，仓库身份 `ResearchFlow Dev <dev@researchflow.local>`。Codex **未暂存、未 commit、未修改 remote、未 push**；不变更 `last_verified_commit`。
- 保留限制：BLK-003 OPEN；G6 仍 IN_PROGRESS，仅 G6-T0 满足；G4/G5/G7 未启动。自动审批服务 404 曾阻断浏览器连接和部分提权请求，相关操作未执行，未更改权限或系统配置。
- 下一步：Harness 按交接核对最终范围、远端和身份，执行普通提交/推送，核对远端 SHA 与干净提交快照，再按 `docs/goals/MEMORY_CLOSEOUT.md` 自动更新状态、日志、交接和稳定记忆。不自动进入 Goal 2。

## 交接模板

### YYYY-MM-DD · 阶段 X

- 本次完成：
- 未完成：
- 已知问题/风险：
- 下一步：
- 待用户确认：
- 相关文件/命令：

## 交接记录

### 2026-11-15 · T0 验收通过（暂不 commit）

- 用户 2026-11-15 明确“验收 T0，暂不 commit”；`T-T0-ACCEPT-001` DONE，验收记录 `docs/verification/t0/T0_ACCEPTANCE.md`。
- 依据：A-01/A-02/A-03 收口；351 passed；三次 e2e consistent；三次离线验签 VERIFIED；契约/状态/文档检查 exit 0。
- 未完成：commit/推送（需单独授权并核对文件清单/Git 身份/忽略规则）、T1 启动、预算余额核实、完整 G6/G4/G5/G7。
- 风险：`BLK-003` OPEN；全部测试在 danger-full-access 下运行；工作台单页/无下载/无失效原因；断网非 OS 级；L3 非跨机。
- 下一步：用户决定 commit 与 T1；commit 前先核对仓库身份与具体文件清单，不盲目全目录暂存。

### 2026-11-15 · T0 · ADR-007 已批准（T0 验收/commit 仍待用户）

- 本次完成：用户选择“批准建议（推荐）”；ADR-007 转 `ACCEPTED`，三个边界为独立只读进程、四视图只读、证据单页 `limit=200` 无分页/下载、展示 STALE 不展示原因；`T-A03-001` 转 DONE，`BLK-004` 转 RESOLVED；正式记录 `docs/verification/t0/wp-13/ADR-007_DECISION.md`；state_sync 三步 exit 0。
- 未完成：T0 验收结论、commit、GitHub 推送、是否进入 T1；预算余额仍未核实。
- 风险/边界：G0 ⑧ 冻结正文保留 2026-11-10 的 PROPOSED 历史，差异在 ADR 索引登记；分页/下载/失效原因仍未实现；`BLK-003` 仍 OPEN；全部测试在 danger-full-access 下运行。
- 下一步：用户复核 A-01/A-02/A-03 与修复后 e2e，决定 T0 验收与 commit；提交前确认文件清单、Git 身份与忽略规则；核实预算余额。
- 相关文件：`docs/ADR/README.md`、`docs/ADR/ADR-007-t0-workbench-scope.md`、`docs/verification/t0/wp-13/ADR-007_DECISION.md`、`docs/state/project_state.json`。

### 2026-11-15 · T0 · A-01/A-02 修复与 WP-13 材料补齐（A-03 裁决待用户）

- 本次完成：
  - A-01：L1/L3 在当前 attempt 上交叉核对 NodeSpec、job、result、E2 `parameters_hash`；L3 在启动复跑前拒绝，split/train 负例齐全；正常恢复 attempt_02 不误拒。
  - A-02：真实 `taskkill /T` 中断 + 独立新进程重读；RUNNING 不默认 COMPLETED、0 报告/0 凭证、无残留进程；坏链/缺失 attempt 结果时 invalidate/rerun 以 `RECOVERY_NOT_SAFE` + 具体 L1 原因拒绝。
  - A-03 材料：四视图 + API 不可达截图、DOM 快照、`walkthrough.md`、ADR-007 三个边界的裁决建议；工作台新增 `?view=`/`?task_id=`/超时配置与 STALE AppTest。
  - 修复后重新生成三次隔离 e2e；修复前 e2e 整体归档到 `e2e/superseded_2026-11-15_pre_a01/` 并加 `SUPERSEDED_NOTICE.md`；三次离线验签 VERIFIED。
  - 状态：`T-A01-001`/`T-A02-001` DONE，`T-A03-001` IN_REVIEW，`BLK-004` OPEN；G1/G2/G3/G6 补新证据，G6 仍 IN_PROGRESS。
- 未完成：
  - ADR-007 正式裁决未发生；仓库文档未发现其 `ACCEPTED` 书面记录，ADR-007 仍 `PROPOSED`，`T-A03-001` 不标 DONE。
  - T0 验收结论、commit、GitHub 推送未做；`last_verified_commit` 仍 `1c9a10461c50c02058ce28be8b4b09c0c8870e80`，HEAD 仍 `309083e715cb59a1f0c181d95df44e1946ffbaa5`。
  - 完整 G6（五类负例矩阵）、G4/G5/G7 属 T1/T2；`BLK-003` 仍 OPEN。
- 已知问题/风险：
  - 全部测试在 `danger-full-access` 下运行，不写成 workspace-write 通过。
  - 工作台证据取 `limit=200` 单页、无分页/下载、不展示失效原因；原因展示需另立冻结 REST 契约变更方案。
  - `verify_bundle.py` 的 coverage 算术/证书 l3_coverage 跨对象一致性仍是 B 类补强；模块级 `app` 绕过 `serve()` 守卫仍是已披露入口边界。
  - 断网为“代码无外呼 + 代理黑洞 + 无模型客户端”，非 OS 级断网；L3 与执行器共用同一解释器安装。
- 实际测试命令与结果：
  - `& .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider` → 351 passed，395.66 s，exit 0；`docs/verification/t0/full_suite_2026-11-15.log`。
  - A-01：26 passed（a-01/pytest_targeted.log）；probe `verdict=PASS`（a-01/probe_report.json）。
  - A-02：4 passed（a-02/pytest_restart.log）；回归 11 passed（a-02/pytest_regression.log）；probe `verdict=PASS`。
  - WP-13：4 passed（wp-13/pytest_2026-11-15.log）；截图 `verdict=PASS`（wp-13/screenshots.json）。
  - e2e：三次 `consistent=true`；`verify_bundle.py` 三次 VERIFIED（g6-t0/2026-11-15/*.verify.log）。
  - 契约/状态/漂移：10/10、72/72、state_sync 三步 exit 0、docs drift ERROR=0/WARNING=1。
- 下一步：
  1. 用户对 `docs/verification/t0/wp-13/ADR-007_DECISION_PROPOSAL.md` 的三个边界作书面裁决；批准后再改 ADR-007/索引/D-29 并把 `T-A03-001` 转 DONE。
  2. 用户复核 A-01/A-02 证据与修复后 e2e，决定 T0 验收与 commit；commit 前确认文件清单、Git 身份与忽略规则。
  3. 核实阿里云两项 API 预算余额并回填 `docs/verification/budget/BUDGET_LEDGER.md`；不要在未核实余额时按 0 计。
- 待用户确认：ADR-007 三个边界；T0 验收/commit；是否进入 T1；预算余额。
- 相关文件：`docs/verification/t0/{a-01,a-02,wp-13}/**`、`docs/verification/t0/e2e/**`、`docs/verification/t0/g6-t0/2026-11-15/**`、`docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`、`docs/CHANGELOG_DEV.md`。

### 2026-11-14 · 三阶段 Goal 自动记忆与交接收尾（文档治理）

- 本次完成：新增 `docs/goals/MEMORY_CLOSEOUT.md`，三份 Goal 均在启动入口及完成清单引用；每包保存检查点，结束前自动同步，必需检查失败不得 complete。用户已要求该文档同步自动执行，无需逐次询问。
- 长期记忆：`docs/memory/feedback-and-lessons.md` 的 FB-29 记录自动同步偏好，Memory 索引增加规则入口。进度不复制到长期背景记忆；没有新增稳定事实时说明已复核无需修改。
- 真实验证：项目 `.venv/Scripts/python.exe` 3.11.16/64 位；四份文档 UTF-8/围栏/本地引用检查 exit 0；state_sync validate/render/check 均 exit 0。日志与哈希：`docs/goals/verification/memory_closeout_20261114/`。变更前文档漂移 ERROR=0/WARNING=1；收尾复查结果以该目录 `docs_drift.log` 为准。因已知沙箱 Git 子进程问题，该只读漂移检查申请了限定命令提权；不关闭 BLK-003。
- 业务接手注意：先读 `reports/t0_review_20261114/REVIEW.md`。A-01 参数绑定漏检已真实复现，A-02 中断/重启验收缺口、A-03 工作台裁决及材料待收口。用户已发出收口任务；本轮没有修复业务实现或核实收口完成，既有状态中的 DONE/PASS 不能单独代替新证据。
- 下一最小动作：Harness 读取对应 Goal 与 MEMORY_CLOSEOUT，核验 T0 三项收口和两项累计预算；满足前置后按 Goal 2 批次计划续建。已批准事项不重复询问，未知架构增量仍按 AGENTS 先提交具体 diff 方案。
- 状态/限制：仅新增 `T-GOALS-002` 文档任务；未改既有门禁、业务任务、预算余额、冻结件或 last_verified_commit。开发 API 200 元、产品 API 50 元跨阶段累计，余额仍需账单核实。
- Git/权限：main，HEAD `309083e715cb59a1f0c181d95df44e1946ffbaa5`（7 commits）；工作区有既有多模块差异，本次仅文档/生成页/验证日志增量，未 commit/push。未运行产品 pytest，无架构变化。

### 2026-11-14 · T0 · 后端可信闭环、工作台、三次 e2e 与独立验签（完成，未 commit）

- 本次完成：
  - WP-03 按 2026-11-14 复测（定向 87 / 全量 217 passed）转 `DONE`；新增 WP-04…14、WP-R 共 12 个任务并全部 `DONE`。
  - 实现 T0 全链：DAG/模板/数据 → 受控执行器 → Collector 链 → L1/L2/L3 → Gate → Ed25519 报告/凭证 → 证据包 → 独立离线验签；最小 Streamlit 四视图只读消费真实 API；FR-010 最小切片（确定性计划、三条件守卫、保守重跑）。
  - 三次隔离 e2e 全部 COMPLETED/VERIFIED，离线验签 exit 0；G6-T0 证据齐全；G1/G2/G3 记 `PASS`，G6 记 `IN_PROGRESS`（完整 G6 属 T1）。
  - 独立只读审查 A 类 1 项（内存只采样 venv 启动器）已修复：进程树采样、200 MB 校准、真实内存限额终止；B 类 9 项修复、3 项接受披露；旧 e2e 证据归档不删除。
- 未完成：
  - 完整 G6（五类负例矩阵）、G4/G5/G7 属 T1/T2；T1 未启动。
  - 工作台截图缺失（无浏览器自动化）；`BLK-003` 仍 OPEN；未 commit。
- 已知问题/风险：
  - 全部测试在 `danger-full-access` 下运行，不写成 workspace-write 通过。
  - 断网为“代码无外呼 + 代理黑洞 + 无模型客户端”，非 OS 级断网；L3 与执行器共用同一解释器安装，跨机复现未测。
  - 启动守卫只检查 token 是否存在，不提供鉴权；模块级 `app` 可绕过 `serve()` 守卫（已接受风险，见 D-23）。
  - 跨进程并发 verify 未实现（进程锁 + 幂等覆盖单进程）；T0 单用户边界。
- 实际测试命令与结果：
  - 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（3.11.16 / 64bit）。
  - 全量：`& .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider` → 339 passed，exit 0，312.44 s，日志 `docs/verification/t0/full_suite_2026-11-14_final.log`。
  - e2e：`python scripts/e2e_run.py --runs 3 --out docs/verification/t0/e2e` → 三次一致，日志与报告见 `docs/verification/t0/e2e/`。
  - 并发：`python scripts/measure_concurrency.py` → 并发 2、重叠 2.323 s、峰值 165.0/166.6 MB。
  - 契约/状态：`validate_contracts.py` 72/72；`state_sync.py validate|render|check` exit 0；`check_docs_drift.py` ERROR=0/WARNING=1。
- 下一步：
  1. 用户复核 T0 证据与门禁裁决（G1/G2/G3 PASS、G6-T0 满足），决定是否 commit 与是否进入 T1。
  2. 需要时补工作台截图（需浏览器自动化）与 workspace-write 全绿（需先关闭 BLK-003）。
  3. 核对阿里云两项 API 预算的实际余额并回填 `docs/verification/budget/BUDGET_LEDGER.md`。
- 待用户确认：T0 验收与 gate 裁决口径；commit 授权；是否开始 T1；预算余额。
- 相关文件：`docs/verification/t0/{WP_INDEX.md,00_implementation_decisions.md,review_2026-11-14.md,e2e/e2e_report.md}`、`researchflow/**`、`tests/t0/**`、`scripts/e2e_run.py`、`verify_bundle.py`、`docs/plans/goal-01-plan.md`、`docs/state/project_state.json`。

### 2026-11-14 · 三阶段 Harness Goal 文档交付（未实施三阶段开发，未 commit）

- 本次完成：三份入口为 `docs/goals/GOAL_01_CORE_BACKEND.md`、`GOAL_02_COMPETITIVE_PRODUCT.md`、`GOAL_03_COMPETITION.md`。每份含可复制短 Goal、事实源、范围/审批、工作包、统一契约和伪代码流程、A/B/C 审查、真实测试/负例、预算与交接、完成/停止条件。按用户要求后端先行，最小 UI 后置。
- 用户补充：赛道一 Agent 编排创新应用；通知图 `D:/bisai-xiangxi/72EE1C8758E9AC991F127B1913CD452E.jpg` 显示 11-20 初赛作品截止、12-06 决赛作品截止。官网正文仅 Loading，完整格式/评分/AI/IP 等仍待核实。模型阿里云 DeepSeek V4.1 Flash；按开发 API 200 元、产品运行/调试 API 50 元分别跨阶段累计，阶段分配是建议，不承诺足够完成所有实验。
- 本机事实：只读安装包 runtime 为 `0.2.2-rc.3`；Goal 默认 256 自动轮次不是金额限额；实际会话能力仍需发现。金额硬限制依赖宿主/供应商，开发额度临界时应提前交接并由用户实际暂停。
- 当前业务事实保持：WP-01/02 DONE、WP-03 IN_REVIEW；P1–P8 设计 ACCEPTED，P9/P10 BLOCKED；G0 PASS、G1–G7 NOT_STARTED；BLK-003 OPEN。历史 217 passed 属 full-access 补充，不是本次测试。
- 验证：项目 `.venv` 3.11.16/64bit；文档结构/引用/hash 校验 exit 0，日志 `docs/goals/verification/document_validation.json`；状态 validate/render/check exit 0，命令/时间/耗时见 `state_sync.log`；文档漂移 ERROR=0/WARNING=1，见 `docs_drift.log`。沙箱内 Git 子进程失败经批准只读复核；未据此关闭产品测试环境阻塞。未运行产品 pytest。
- 新登记 `T-GOALS-001` DONE 仅是文档交付，未改变现有门禁/任务结论。main，HEAD `309083e715cb59a1f0c181d95df44e1946ffbaa5`，last_verified_commit 仍 `1c9a10461c50c02058ce28be8b4b09c0c8870e80`；保留原有大量未提交改动，未 commit。
- 下一步：在 Harness 先做 Goal 1 的只读接手和预算/能力预检，集中形成批次 A 的具体 diff 与已决事项对账，再按现有审批推进；不得把三份文档本身当作未知架构方案的批准。
- 限制：三阶段全量工作不保证赶上初赛；T0 不是完整赛道一能力。正式盲测需隔离构造者，外部复核/试点需真人记录，禁止用 AI 自评伪造。两项预算是否足够按真实 usage 估算。
- 来源与审查详情：`docs/goals/verification/source_and_review.md`。无架构变化，未改业务实现、契约、插件或系统配置。

### 2026-11-12 · T0 WP-03 · SQLite、StateMachine、双事务审计（执行完成，待验收，未 commit）

- 本次完成：
  - 按用户 2026-11-12“按你的建议来吧”确认的 16 项裁决，写入 `docs/verification/t0/wp-03/00_decisions.md`；批准 9A（7 表 + 最小测试事实端口）与 Step 1 计划。
  - 实现 `researchflow/persistence/`：连接/事务、7 表 DDL 与触发器、只向前迁移、仓储、幂等键校验。
  - 实现 `researchflow/orchestration/`：Task 9 / Node 10 迁移表、`StateMachine.transition()`、`create_initial()`、守卫、事实端口、计划文件读取、最小不变量。
  - 新增 `researchflow/contracts/encoding.py`（RFC 8785 JCS）与 `errors.py`（13 个冻结 API 错误码）。
  - `researchflow/api/app.py` 从 `_EphemeralTaskRegistry` 切换到 SQLite 创建服务；保留 201/409/422/404、GET `spec`、`/recover` 404。
  - `docs/state/project_state.json` 新增 `T-WP-03-001`，状态 `IN_REVIEW`；`state_sync.py validate|render|check` 均 exit 0。
- 未完成：
  - `T-WP-03-001` 尚未经用户验收，未标 `DONE`；未 commit。
  - workspace-write 下因 `BLK-003` 在 pytest `tmp_path` 创建阶段失败，未取得 workspace-write 全绿；全量结果为 full-access 补充。
  - P9/P10 仍 `BLOCKED`；未读取其实现作为输入；未关闭阻塞。
- 已知问题/风险：
  - 全量 `217 passed` 来自 `danger-full-access` 补充运行，不能写成 workspace-write 通过；`BLK-003` 仍 `OPEN`。
  - `tasks.task_spec_json` 与 `idempotency_keys.task_id NOT NULL + FK` 是对 06 §1.3 的已批准偏离，已在裁决与计划中记录；未改 06 冻结件。
  - `INVALIDATED` 路径的 Gate/Report/Certificate 使用测试事实端口；只证明状态机/守卫逻辑，不证明真实 Gate/Verifier 结果。
  - `last_verified_commit` 仍 `1c9a104`，与 HEAD `309083e` 不一致；未在无真实 commit 时修改。
- 实际测试命令与结果：
  - 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（3.11.16 / 64bit）。
  - 定向：`& .venv/Scripts/python.exe -m pytest tests/test_jcs.py tests/test_persistence_migrations.py tests/test_state_machine.py tests/test_audit_dual_transaction.py tests/test_direct_write_guard.py tests/test_invalidated_guard.py tests/test_idempotency_sqlite.py tests/test_api_sqlite.py tests/test_api_422.py tests/test_api_idempotency.py -q -p no:cacheprovider --basetemp=runtime/pytest-tmp` → `87 passed`，exit 0；日志 `docs/verification/t0/wp-03/pytest_targeted.log`。
  - 全量：`& .venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp=runtime/pytest-tmp` → `217 passed`，exit 0；日志 `docs/verification/t0/wp-03/pytest_full.log`。
  - 证据脚本：`& .venv/Scripts/python.exe docs/verification/t0/wp-03/make_evidence.py` → `EVIDENCE_OK`，exit 0；七份证据日志见 `docs/verification/t0/wp-03/`。
  - `state_sync.py validate|render|check` → 均 exit 0；`PROJECT_STATE.md` SHA256 `7b6f2c46…`，`IMPLEMENTATION_STATUS.md` SHA256 `394a5127…`。
  - workspace-write 失败记录：`docs/verification/t0/wp-03/blk003_workspace_write_failure.md`（6 passed / 6 errors，均在 `tmp_path` setup 阶段 `PermissionError [WinError 5]`）。
- 当前分支与 commit：`main`；HEAD `309083e`；工作区含既有未提交变更与本轮 WP-03 代码/测试/文档；未 commit。
- 下一步：
  1. 用户审阅 WP-03 实现、证据与 `T-WP-03-001` 验收标准，决定是否转 `DONE`。
  2. 决定是否 commit（提交前确认 Git 身份；不得自动 commit）。
  3. 决定是否在 `BLK-003` 修复后补一次纯 workspace-write 全量测试。
- 待用户确认：WP-03 验收；commit 授权；`BLK-003` 后续处理。
- 相关文件/命令：`docs/verification/t0/wp-03/00_decisions.md`、`01_step1_plan.md`、`pytest_targeted.log`、`pytest_full.log`、`make_evidence.py`、`researchflow/persistence/*`、`researchflow/orchestration/*`、`researchflow/api/app.py`、`tests/wp03_support.py`、`docs/state/project_state.json`。

### 2026-11-12 · 伪代码 P2–P8 设计件验收 · WP-03 方案与提示词（执行完成，未 commit）

- 本次完成：
  - 按用户 2026-11-12 指令（C→B 顺序）完成 P2–P8 设计件审查：91 文件 / 51,402 行；14 个模块的 `MODULE.md`、`NEGATIVE_TESTS.md` 齐全；文件数/行数与 `INDEX.md`、`STAGE_LOG.md` 一致；每模块 ≥36 条负例标识；全部 `.py` 通过 `ast.parse`；>800 行文件已登记函数索引。报告：`reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`。
  - `docs/state/project_state.json`：P2–P8 由 `IN_REVIEW` 改为 `ACCEPTED`（仅设计件验收）；补 `acceptance_basis` 与验收证据；`T-PSEUDO-001` 验收标准同步；top-level `updated_at` 更新。
  - `STAGE_LOG.md`、`INDEX.md`、M04–M18 模块头、`README.md`、`ARCHITECTURE.md`、`DEVELOPMENT_WORKFLOW.md`、`PROJECT_OVERVIEW.md`、`memory/project-context.md` 同步为“P1–P8 设计件 ACCEPTED；P9/P10 BLOCKED”。
  - 新增 `docs/plans/WP-03_IMPLEMENTATION_PLAN.md`（草案，未获实施批准）和 `docs/plans/WP-03_IMPLEMENTATION_PROMPT.md`（下一阶段实施提示词）。
- 未完成：
  - `§12-2`/`§12-6`/`§12-7`/`§12-8` 未裁决；P9/P10 未处置；WP-03 未获明确开工指令；未 commit；`BLK-003` 仍 OPEN。
  - 未完成全量 pytest；定向 `tests/test_state_sync.py` 因 `BLK-003` 的 workspace-write 临时目录 ACL 阻塞（31 failed / 28 errors，均在 setUp/临时目录创建阶段，未见断言失败）；本轮无业务代码改动，只有设计验收状态、文档与计划。
- 修改文件：
  - `docs/state/project_state.json`、`docs/PROJECT_STATE.md`、`docs/IMPLEMENTATION_STATUS.md`；
  - `design/pseudocode/{STAGE_LOG.md,INDEX.md}` 与 M04–M18 的模块头；
  - `README.md`、`docs/{ARCHITECTURE.md,DEVELOPMENT_WORKFLOW.md,PROJECT_OVERVIEW.md}`、`docs/memory/project-context.md`；
  - `docs/CHANGELOG_DEV.md`、`docs/SESSION_HANDOFF.md`；
  - 新增 `reports/pseudocode/*`、`docs/plans/*`。
- 实际测试命令与结果：
  - 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（3.11.16 / 64bit）。
  - `& .venv/Scripts/python.exe scripts/state_sync.py validate` → exit 0；伪代码阶段 ACCEPTED 8 / BLOCKED 2。
  - `& .venv/Scripts/python.exe scripts/state_sync.py render` → 生成 2 文件；`check` → exit 0，逐字节一致（`PROJECT_STATE.md` SHA256 `20835f51…`，`IMPLEMENTATION_STATUS.md` SHA256 `72f499dc…`）。
  - `& .venv/Scripts/python.exe scripts/check_docs_drift.py` → ERROR=0、WARNING=1（`last_verified_commit` 与 HEAD 不一致，已知）。
  - 尝试 `& .venv/Scripts/python.exe -m pytest tests/test_state_sync.py -q -p no:cacheprovider`：31 failed / 28 errors，全部在 setUp/临时目录创建阶段出现 `PermissionError [WinError 5]`（或由此派生的 `FileNotFoundError`），未见断言失败；属 `BLK-003` workspace-write 环境阻塞，未据此关闭阻塞，也未修改测试。
  - 未改业务代码/契约/schema/测试；全量 pytest 未运行。
- 当前分支与 commit：`main`；HEAD `309083e`；`git rev-list --count --all` 为 7；未 commit；工作区同时含既有 P0/文档变更与本轮变更。
- 未解决/风险：
  - P2–P8 `ACCEPTED` 是**设计件验收**，不是运行时实现、测试通过或门禁 PASS；若用户不认可本轮审查口径，可回退状态。
  - WP-03 仍受 `DEVELOPMENT_WORKFLOW` §11.3 第 3/4/6 条阻塞；`PHASE_RULES` §9 的全阶段冻结审计仍因 P9/P10 未收口而不满足。若要先启动 WP-03，需要用户明确裁决审计范围/例外。
  - 4 个 OQ 的建议口径见 `reports/remediation/P0_REMEDIATION_PLAN.md` §6.2 与 WP-03 方案 §2.2，未自行生效。
  - JCS 与现有 `json.dumps(sort_keys=True)` 的请求哈希差异（RF-API-03）需在 WP-03 实施前确认。
  - 本轮 pytest 尝试在系统临时目录产生的 `rf_state_sync_*` 目录可能残留（`BLK-003` 现象），未手工清理。
- 下一步（最多 3 项）：
  1. 用户审阅 P2–P8 验收记录与 WP-03 方案，确认是否维持 `ACCEPTED`。
  2. 裁决 `§12-2`/`§12-6`/`§12-7`/`§12-8`、P9/P10 处置与 WP-03 指令。
  3. 决定是否 commit 当前批次（提交前确认 Git 身份）。
- 待用户确认：P2–P8 验收口径；4 个 OQ；P9/P10；WP-03 是否启动；commit 授权。
- 相关证据：`reports/pseudocode/P2_P8_ACCEPTANCE_REVIEW.md`、`reports/pseudocode/p2_p8_*.log`、`docs/plans/WP-03_IMPLEMENTATION_PLAN.md`、`docs/plans/WP-03_IMPLEMENTATION_PROMPT.md`、`docs/CHANGELOG_DEV.md` 2026-11-12 条目。

### 2026-11-12 · 文档治理 · 记忆与状态词汇对账（执行完成，未 commit）

- 本次完成：
  - 按用户“直接修复”指令，完成 2026-11-12 过时记忆审计后的文档修复；未改代码、契约、schema 或测试。
  - 高优先级：把 `ADR-001` 的 `INVALIDATED` 传播到 `AGENTS.md` §6.2、`docs/MEMORY_GUIDE.md` §5.2、`docs/GLOSSARY.md`、`docs/ARCHITECTURE.md` §4.1/§4.2、`docs/DEVELOPMENT_WORKFLOW.md` §10.2；Node 统一为 10 个状态，补两条迁移与 I-09–I-14。
  - `docs/state/runtime_states.md` 按 G0 冻结的 05 §9–§10 重写：Task 9、Node 10、Evidence 5、Recovery（T1）、I-01–I-14；删除“G0 未冻结/等待 G0”旧表述。
  - 记忆文件：`architecture-decisions.md` §5/§7、`feedback-and-lessons.md`（FB-17/FB-25、历史限定、L-12/L-13）、`references.md`（R-01/R-23/R-24–R-27）、`project-context.md`（阶段 8/G0/T0/P0、2D 待确认）、`environment.md`（Context7 新哈希、tmp 目录、140 passed、Docker/API Key 限定）、`Memory.md`（索引补项）。
  - 相邻文档：`G0_DECISION_LIST.md` 去掉 `NOT_STARTED` 残留并更新 R-2；`CONFLICT_REPORT.md` 方案 D 标为历史；`SECURITY_POLICY.md` §11 改为“G0 未覆盖、仍需裁决”。
- 未完成：
  - 2D 仍未见书面接受或补做记录；P9/P10 仍 `BLOCKED`；`BLK-003` 仍 `OPEN`。
  - 未 commit；未更新 `last_verified_commit`（无新的受控测试与真实 commit）。
- 修改文件：
  - `AGENTS.md`、`docs/MEMORY_GUIDE.md`、`docs/GLOSSARY.md`、`docs/ARCHITECTURE.md`、`docs/DEVELOPMENT_WORKFLOW.md`、`docs/SECURITY_POLICY.md`、`docs/state/runtime_states.md`、`docs/state/G0_DECISION_LIST.md`、`docs/reference/CONFLICT_REPORT.md`、`docs/memory/*`、`docs/CHANGELOG_DEV.md`、`docs/SESSION_HANDOFF.md`。
- 实际测试命令与结果：
  - 解释器：`D:\ResearchFlow-project\.venv\Scripts\python.exe`（3.11.16，64bit）。
  - `& .venv/Scripts/python.exe scripts/state_sync.py validate|render|check`：均 exit 0；`PROJECT_STATE.md` SHA256 `fb321d47…af98`，`IMPLEMENTATION_STATUS.md` SHA256 `e0ba518f…5fc3`，与 JSON 逐字节一致。
  - `& .venv/Scripts/python.exe scripts/check_docs_drift.py`：ERROR=0，WARNING=1（`last_verified_commit=1c9a104` 与 HEAD `309083e` 不一致，已知），exit 0。
  - 本地 Markdown 链接检查：15 个核心改动文档，`MISSING_LINKS=0`；`git diff --check` exit 0。
  - 未运行 pytest/unittest；本次为文档修复，未触碰运行时行为。
- 当前分支与 commit：`main`；HEAD `309083e`；`git rev-list --count --all` 为 7；本次未 commit。工作区同时含本次文档修改与既有 P0 未提交变更。
- 未解决/风险：
  - 2D 未裁决；P9 并发重写产物未验收；P10/M19 未获开发授权；`BLK-003` 仍 `OPEN`，140 passed 只代表受控 full-access。
  - `last_verified_commit` 与 HEAD 不一致，`check_docs_drift` 维持 1 条已知 WARNING。
- 下一步（最多 3 项）：
  1. 用户审阅本次文档 diff，决定是否 commit（提交前确认 Git 身份）。
  2. 裁决 2D：补做运行态验证，或书面接受“静态确认”口径。
  3. 决定 P9 并发重写产物与 P10/M19 的处置；未授权前不启动 WP-03。
- 待用户确认：commit 授权；2D 口径；P9/P10 与 WP-03 的下一步。
- 相关证据：`docs/CHANGELOG_DEV.md` 2026-11-12 条目；`scripts/check_docs_drift.py` 输出；`docs/state/runtime_states.md`；`docs/memory/*`。

### 2026-11-11 · P0 · API 幂等整改、full-access 测试与 P1–P10 状态注册表（执行完成，待裁决）

> 本条目取代下方 2026-11-11“伪代码 P1–P6 冻结”条目中的阶段状态表述；旧条目保留为历史。

- 本次完成：
  - A：`researchflow/api/app.py` 分离内部 `_TaskRecord` 与公共 201 回执；同键同体首次/重放共用同一响应体；新增 `tests/test_api_idempotency.py` 的 A–E 测试。
  - E：按用户授权执行一次受控 full-access 全量 pytest：`140 passed`，exit 0；完整日志 `reports/remediation/logs/21_full_pytest_fullaccess.log`。测试前后 Git 状态一致，项目内未新增临时目录；`BLK-003` 仍 `OPEN`，未据此关闭。
  - B：`docs/state/project_state.json` 新增独立 `pseudocode_stages`（P1–P10）；`state_sync.py` 增加枚举、路径存在性、ACCEPTED 证据、BLOCKED 原因校验与渲染；`P1 ACCEPTED`，P2–P8 `IN_REVIEW`，P9/P10 `BLOCKED`。
  - C：`OQ-P1-03`、`OQ-P1-05` 标 `NEEDS_CONFIRMATION`；`PHASE_RULES`、M01/M03、`STAGE_LOG` 同步，未编造原问题或裁决正文。
  - I：README、DEVELOPMENT_WORKFLOW、PROJECT_OVERVIEW、ARCHITECTURE、AGENTS 版本元数据、G0_DECISION_LIST 历史横幅已更新；冻结件未改。
  - 最终定向回归：API 422 + A–E + state_sync，`49 passed`，exit 0；报告见 `reports/remediation/P0_*`。
- 未完成 / 待确认：
  - D：§12-2 仅形成待裁决方案；§12-6/§12-7/§12-8 未裁决。未写入 M02 DECISIONS。
  - G：P10/M19 仅登记现状，未获开发授权；未删除、未标 ACCEPTED。
  - H：未 commit；`last_verified_commit` 未改。
  - J：未清理任何缓存/临时目录。
- 关键风险（必须保留）：
  - 2026-11-11 22:53:54–55 发现并发进程重写并落盘 P9 的 6 个 `.py`（另有 4 份文档被改）；这不是原始正文恢复。P9 已标 `BLOCKED`，逐项哈希/行数见 `reports/remediation/P0_OPEN_ISSUES.md`。
  - P9 的并发重写产物未运行 pytest、未导入、未验收；不得标 `ACCEPTED` 或当作原始设计。
  - `last_verified_commit=1c9a104` 与 HEAD `309083e` 不一致；整改未提交，不得擅自推进。
- 下一步：
  - 用户裁决 D 的 §12-2 方案与 §12-6/§12-7/§12-8；对 P9 并发重写产物决定“接受为设计稿 / 重新补齐 / 保持 BLOCKED”；确认是否授权 commit。
- 相关文件/命令：
  - `researchflow/api/app.py`、`tests/test_api_idempotency.py`、`docs/state/project_state.json`、`scripts/state_sync.py`、`design/pseudocode/INDEX.md`、`STAGE_LOG.md`、`OPEN_QUESTIONS.md`、`reports/remediation/`。
  - `& .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`；`& .venv/Scripts/python.exe scripts/state_sync.py validate|render|check`。

### 2026-11-11 · P0 · 伪代码 P1–P6 冻结

- 本次完成：
  - 83 个 P1–P6 文件提交 `1c9a104`；新增 `STAGE_LOG.md`、`INDEX.md`；`T-PSEUDO-001` 登记为 `IN_REVIEW`。
  - `last_verified_commit` 修正为 `1c9a104`；`state_sync.py validate|render|check` 均 exit 0。
  - `environment.md` 6 处与 `MEMORY_GUIDE.md` 1 处措辞处置；`check_docs_drift` ERROR=0、WARNING=0。
- 未完成：
  - P2–P6 逐阶段验收；P7–P10 未开始；M13/M14/M17/M18（P7/P8）未纳入本次提交。
  - `BLK-003` 仍 `OPEN`；本轮按铁律未运行 `pytest`/`unittest`；写入探针 exit 0，未复现 2026-11-08 的阻塞。
- 已知问题/风险：
  - 第二次提交后 HEAD 前移，`last_verified_commit` 与 HEAD 不一致，`check_docs_drift` 会报 1 条 WARNING（exit 0），属预期。
  - `OPEN_QUESTIONS.md` 已含 P7 条目（`OQ-P7-01`～`OQ-P7-12`），为并发阶段产物；本次未删除。
- 下一步：
  - 从 P2 起逐阶段验收；确认 P7/P8 产物归属后再单独提交。
- 待用户确认：
  - P7/P8 是否由另一会话继续；`BLK-003` 是否在 `danger-full-access` 下补跑测试套件。
- 相关文件/命令：
  - `design/pseudocode/STAGE_LOG.md`、`design/pseudocode/INDEX.md`、`docs/CHANGELOG_DEV.md`。

### 2026-11-10 · T0 · WP-02 验收通过

- 本次完成：
  - 用户验收 `T-WP-02-001`，状态转 `DONE`；验收记录见 `docs/verification/t0/wp-02/40_wp02_acceptance.md`。
  - `state_sync.py validate|render|check` 均 exit 0；`PROJECT_STATE.md` 与 `IMPLEMENTATION_STATUS.md` 已随状态重新生成。
- 未完成：
  - `WP-03`（SQLite + StateMachine + audit_log）未启动，等待用户指令。
  - `BLK-003` 仍 `OPEN` / `MEDIUM`；13b 仍 `NOT VERIFIED`；2D 未单独执行。
- 已知问题/风险：
  - API 的 `state` 字段当前来自临时内存注册表，WP-03 接入 `StateMachine` 时必须替换，不得沿用。
- 下一步：
  - 若用户下达指令，按 ⑦ §2.3 启动 `WP-03`；否则停在验收完成状态。
- 待用户确认：
  - 无。
- 相关文件/命令：
  - `docs/verification/t0/wp-02/WP-02_REPORT.md`、`docs/verification/t0/wp-02/40_wp02_acceptance.md`。

### 2026-11-10 · T0 · WP-02 核心契约落地完成 · 等待验收

- 本次完成：
  - 5 份冻结 schema 落成 Pydantic v2 模型（严格模式），并实现 schema 无法表达的跨字段约束：`level→producer/kind`、`SEM-NS-01`、`SEM-VR-01/02`。
  - RFC 8259 严格解析层：重复键、`NaN`/`Infinity`、非法 UTF-8 在进入模型前拒绝。
  - API 绑定 `POST /api/v1/tasks` 与 422 字段路径映射（`SCHEMA_INVALID` + `field_path` + `correlation_id`）；按决议 8 不注册 `/recover`。
  - `check_model_parity.py`：72 例行为一致 + 5 契约结构一致，`result=PASS`。
  - 测试：模型 89 项、API 13 项、全量 125 项全部通过。
  - `project_state.json`：新增 `T-WP-02-001`，状态 `IN_REVIEW`；`state_sync.py` 三条命令 exit 0。
- 未完成：
  - `T-WP-02-001` 尚未验收；未进入 `WP-03`。
  - 状态机、SQLite、其余 API 端点、启动守卫未实现（属后续工作包）。
  - `BLK-003` 仍 `OPEN` / `MEDIUM`；13b 仍 `NOT VERIFIED`；2D 未单独执行。
- 已知问题/风险：
  - API 返回的 `state="CREATED"` 来自临时内存注册表，是响应形态绑定，不是状态机；不得据此宣称运行时状态迁移已实现。
  - 模型错误消息为 pydantic 英文，仅 `dataset_ref` 使用 06 §4.2 固定文案；422 结构不受影响。
- 下一步：
  - 待用户验收 `T-WP-02-001`；通过后按 ⑦ 进入 `WP-03`（SQLite + StateMachine + audit_log）。
- 待用户确认：
  - 无（2026-11-10 已验收通过并授权提交）。
- 相关文件/命令：
  - `docs/verification/t0/wp-02/WP-02_REPORT.md`；`& .venv/Scripts/python.exe scripts/check_model_parity.py`；`& .venv/Scripts/python.exe -m pytest tests -q`。

### 2026-11-10 · T0 · WP-01 验收通过 · 进入 WP-02

- 本次完成：
  - 用户验收 `T-WP-01-001`，状态转 `DONE`；四项待决事项按用户选择落地（见 `docs/verification/t0/wp-01/30_wp01_acceptance.md`）。
  - `last_verified_commit` 更新为 `19c337f350fead30efd52c222356ad6248a3f937`；`current_milestone` 保持 `M0_GOVERNANCE_BASELINE`（T0 里程碑编号在冻结版 ⑦ 中未定义，未自造）。
  - `.venv` 502.3 MB 超矩阵估算，用户裁决“接受并记为已知偏差”，已写入 `09_dependency_matrix.md` §4 与验收记录。
  - `state_sync.py validate|render|check` 均 exit 0；stdout 见 `docs/verification/t0/wp-01/state_sync_acceptance.log`。
- 未完成：
  - `WP-02` 核心契约落地尚未产出 `model_parity.json`、`schema_validation.log`、`api_422.log`。
  - `BLK-003` 仍 `OPEN` / `MEDIUM`；13b 仍 `NOT VERIFIED`；2D 未单独执行。
- 已知问题/风险：
  - `.venv` 体积为已知偏差，未裁剪；如需优化另立任务。
- 下一步：
  - 按 ⑦ §2.2 完成 5 份 schema → Pydantic v2 模型、schema↔模型差异检查、API 请求/响应绑定与 422 字段路径映射。
- 待用户确认：
  - 本次提交授权（已于 2026-11-10 授权并提交 `678d2e8`）。
- 相关文件/命令：
  - `docs/state/project_state.json`、`docs/verification/t0/wp-01/30_wp01_acceptance.md`；`.venv/Scripts/python.exe scripts/state_sync.py validate|render|check`。

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
