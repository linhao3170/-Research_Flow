# 06 工作区、沙箱与审批策略

- 工作区：`D:\ResearchFlow-project`（`Get-Location` 实测）。
- 阶段 8 开始时会话运行态：`workspace-write` + 审批 `ask`。
- 2026-11-08T13:10+08:00，用户将会话切换为：`danger-full-access` + 审批 `never ask`。该变更由用户发起，Agent 未请求提权。
- 期望基线（本阶段验收口径）：`workspace-write` / `ask`。
- 当前实际：`danger-full-access` / 审批关闭。

判定：

| 子项 | 结果 | 说明 |
|---|---|---|
| 工作区为 `D:\ResearchFlow-project` | PASS | 命令实测 |
| 文件沙箱为 `workspace-write` | **FAIL** | 当前为 `danger-full-access`，不再限制项目外写入 |
| 审批策略为 `ask` | **FAIL** | 当前审批提示关闭；需要审批的操作会被自动拒绝或直接放行，取决于操作类型 |

证据：`01_startup_profile.log`、`04_terminal_fs.log`、`23_approval_teams.log`；运行时上下文（2026-11-08T13:10+08:00）。

> 安全处置：没有在项目外执行任何写入来“证明”越权；当前策略已允许，但项目规则仍禁止。该 FAIL 是阶段 8 的关键安全偏差，不能由 Agent 自行改回。
