# G0 裁决清单（历史；G0 已于 2026-11-10 通过）

> **历史文件（2026-11-10 起）**：G0 已于 2026-11-10 由用户宣布 `PASS`；下表第 2–4 项已由 G0 文档包关闭。本表以下为阶段 8 的原始记录，不再作为当前待裁决项；当前状态以 `docs/state/project_state.json` 为准。
>
> 原文状态（历史）：阶段 9 输入，未裁决；该表形成时 G0 尚未通过。G0 已于 2026-11-10 由用户宣布通过；本表不再作为当前待裁决项。
> 来源：用户 2026-11-08 阶段 8 指令；策划书内部 v4.3.0（文件名标签 v4.3.1；`BLK-002` 已关闭）。
> 证据锚点：`P####` → `docs/verification/stage7/02_docx_body.txt`；`TABLE ##` → `docs/verification/stage7/05_docx_tables.txt`。

| 序号 | 事项 | 冲突/问题 | 证据锚点 | 状态 | 阶段 9 处理 |
|---|---|---|---|---|---|
| 1 | 策划书版本基线 | 文件名 v4.3.1 vs 文档内部 v4.3.0 | `C-001`；`07_version_strings.txt` | **已决**（2026-11-08） | 内容基线 = 文档内部 v4.3.0；v4.3.1 仅为文件名标签；不修改 DOCX/文件名/位置 |
| 2 | FR-010 的 T0 边界 | FR-010“恢复计划与失效传播”标 P0，但 T0 必须完成清单未列 Recovery；Recovery 出现在 T1 | TABLE 67 R11；TABLE 56 R02–R03；§15.2 / P0379 | **待裁决** | 明确 FR-010 是否进入 T0；若进入，T0 需增加最小恢复/失效传播验收；若不进入，记录 P0 与阶段错位的理由 |
| 3 | §15.5 与附录 J 的顺序 | §15.5：contracts → StateMachine/SQLite → Executor → Collector → Gate/L1–L3 → 签名/验签 → Scheduler/Governor/Recovery → 六 Agent → Bench；附录 J：仓库/环境 → contracts → SQLite/StateMachine → DAG Builder → 内置模板 → Executor → Collector → Gate → Verifier L1/L2 → L3 → 签名 → Bundle → 工作台 → E2E | §15.5 / P0386–P0395；TABLE 78 R02–R15 | **待裁决** | 选定 T0 实施顺序，或给出合并顺序；明确 DAG Builder、内置模板、Scheduler/Recovery、最小工作台的位置 |
| 4 | FR-015/016/017 的 P1 与 T2 错位 | FR-015（DC/SPA）、FR-016（VAS）、FR-017（Harness Adapter）均标 P1，但 T2 必须完成清单包含 DC/SPA、VAS、Harness 插件 | TABLE 67 R16–R18；TABLE 56 R04 | **待裁决** | 明确 P1 是“重要度”还是“交付阶段”；若 P1 表示 T1，则需调整 T2 清单或提前实现；若表示重要度，则在契约中写明 |

## 使用规则（历史，阶段 8 原文）

> 2026-11-10 更新：第 2–4 项已由 G0 文档包裁决（FR-010 的 T0 最小切片见 ⑦ `WP-R` 与 `ADR-004`；WP 顺序按 ⑦ §1 的用户决议 C1；P0/P1/P2 为重要度而非阶段，见 ① §4.1）。本表保留阶段 8 的原始记录，不再作为待裁决项。R-3 的 Git 基线已建立，回滚已于 2026-11-10 在 `91bde66` 上补测 PASS，阶段 8 第 20 项转 PASS（见 `docs/verification/g0/18_git_rollback.log`）。

1. 本清单只记录待裁决项，不构成 G0 通过。
2. 第 1 项已由用户决议，不再作为阶段 9 的开放裁决项；阶段 9 只需引用决议，不重新讨论版本。
3. 第 2–4 项必须在 G0 规格冻结前逐项裁决并留下书面结论；未裁决前不得把对应 FR 写成冻结契约。
4. 裁决结果应写入 ADR 或 G0 冻结记录，并同步 `project_state.json` 的 `stage_gates.G0` 证据路径；本次不修改 G0 状态。

## G0 残留风险清单（阶段 8 验收后）

| # | 残留风险 | 现状 | 证据 | 处理口径 |
|---|---|---|---|---|
| R-1 | **13b 仅在全权限下通过** | 13b 在 workspace-write 下 23 tests / 43 errors，0 断言失败；`BLK-003` OPEN / MEDIUM；DSH 权限诊断结论 `NOT_THIS_CLASS`（WRITE_DAC / WRITE_OWNER 均具备，无缺失权限、无第三方授权项，FIXED=0，未做改动）；机制为沙箱授权未向运行期新建子目录传播 | `docs/verification/stage8/31_blk003_probe.log`、`32_unittest_workspacewrite.log`、`31b_probe_path_evidence.log`；诊断报告 `C:\Users\Administrator\AppData\Local\ResearchFlow\acl-diagnostics\acl-report-559f7ffa05844dce8e62ba3238f77f3b.jsonl` | 13b 维持 NOT VERIFIED，只有日后在 workspace-write 下真跑通才可改 PASS。23 项 unittest 属代码正确性测试，不测沙箱边界，允许在**单独批准的 full-access 会话**中运行；日志必须记录当次会话策略，运行结束立即恢复 `workspace-write`；结果不得用于第 5/6/23 项或任何安全项。不得手工改 ACL、不得再跑第二遍诊断。`tmpavet2qv9` 在 2026-11-12 复核时已不存在（`Test-Path` 为 False）；删除时间/执行者未记录，原“阶段 9 开始时只删除”不再适用 |
| R-2 | **2D 未单独执行、2C 运行态未观测** | 阶段 2D 报告未在项目内落地；阶段 8 第 2 项只做静态确认（配置值 + 阶段 6 非回归），运行态未观测 | `docs/verification/stage8/02_security_2c.md`、`02_security_2c.log` | G0 已于 2026-11-10 通过，但 2D 未见补做或书面接受记录；待用户裁决补做或书面接受，不得写成运行态已验证 |
| R-3 | **Git 无基线、回滚未实测** | **已关闭（2026-11-10）**：基线 `91bde66` 已建立；受控回滚补测通过，阶段 8 第 20 项转 PASS | `docs/verification/g0/18_git_rollback.log`、`docs/verification/stage8/20_git_rollback.md` §3 | 后续按 Git 基线与提交规则执行；DOCX 继续精确忽略 |

附加环境说明：整机既有 Docker Desktop（服务 Stopped），项目未使用；若 G0 口径要求“整机未安装”，由用户决定是否处理，不擅自卸载。证据：`docs/verification/stage8/24_dependencies.md`。

> 以上风险不改变 G0 已于 2026-11-10 通过的历史结论；R-1/R-2 仍需跟踪，当前状态以 `docs/state/project_state.json` 为准。
