# ADR-007 正式裁决记录

> 日期：2026-11-15（Asia/Shanghai）
> 裁决对象：[`docs/ADR/ADR-007-t0-workbench-scope.md`](../../../ADR/ADR-007-t0-workbench-scope.md)
> 裁决来源：用户在当前 DSH 会话的裁决问答中选择“**批准建议（推荐）**”。
> 性质：正式裁决记录。`ADR-007` 据此由 `PROPOSED` 改为 `ACCEPTED`；本记录不修改 G0 冻结正文，不表示 T0 已全部验收或 commit 已获授权。

## 1. 裁决内容

| # | 边界 | 最终裁决 |
|---|---|---|
| 1 | 四视图的接口边界 | **只读当前页所需**：证据固定 `GET /evidence?limit=200` 单页；T0 无分页交互、无报告/凭证文件下载；报告/凭证以只读 JSON 展示 |
| 2 | 工作台与 API 的进程边界 | **独立只读 Streamlit 进程**：只发 GET，不 import 持久层/StateMachine/Collector；API 不可达时显式报错，不伪造数据 |
| 3 | 证据视图的 stale 展示 | **展示 `STALE` 与失效计数；暂不展示失效原因**。原因字段当前不在 `GET /evidence` 契约内；如需展示，先提交冻结 REST 契约扩展方案与 ADR，不夹带修改 |

其他边界保持不变：四视图固定、只读、不写状态/证据、不触发恢复、不实现六页工作台；新增页面或写入型交互需新 ADR。

## 2. 来源与时间

- 2026-11-09：ADR-007 提出。
- 2026-11-10：用户书面意见为“保持 `PROPOSED`，到 `WP-13` 前裁决”。
- 2026-11-15：用户在当前 DSH 会话中回答“是否批准 ADR-007 三个边界”，选择“批准建议（推荐）”；同日完成本记录、ADR 状态与索引更新。
- 该问答是本次批准的直接来源；未把未发生的聊天或口头授权补造成书面文件。

## 3. 落地动作

| 对象 | 变更 |
|---|---|
| `docs/ADR/ADR-007-t0-workbench-scope.md` | 状态 `PROPOSED → ACCEPTED`；补 §3 最终选择、§6 裁决来源、§7 PROPOSED 历史 |
| `docs/ADR/README.md` | 索引状态改为 `ACCEPTED（2026-11-15 用户批准）`；登记与 G0 冻结历史的差异 |
| `docs/verification/t0/00_implementation_decisions.md` | 追加 D-34（ADR-007 裁决与三个边界），保留 D-29 历史 |
| `docs/verification/t0/wp-13/walkthrough.md`、`ADR-007_DECISION_PROPOSAL.md` | 更新为“已裁决”，链接本记录 |
| `docs/state/project_state.json` | `T-A03-001` 转 `DONE`；`BLK-004` 转 `RESOLVED`；`T-WP-13-001` 验收标准同步 |
| `docs/CHANGELOG_DEV.md`、`docs/SESSION_HANDOFF.md` | 追加裁决与收口记录 |

## 4. G0 冻结历史差异

`docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md` §4 仍保留 2026-11-10 冻结时的 `ADR-007 PROPOSED` 行。该文件是 G0 冻结件，**未回溯改写**；ADR-007 的后续用户裁决以 ADR 文件、ADR 索引与本记录为准。差异已按 `docs/ADR/README.md` 规则在索引中登记。

## 5. 证据

- 四视图 + API 不可达截图、DOM 快照：`docs/verification/t0/wp-13/screenshots/`、`screenshots.json`（`verdict=PASS`）。
- 走查：`docs/verification/t0/wp-13/walkthrough.md`。
- 工作台测试：`docs/verification/t0/wp-13/pytest_2026-11-15.log`（4 passed，含 stale 视图）。
- 修复后 e2e 与离线验签：`docs/verification/t0/e2e/`、`docs/verification/t0/g6-t0/2026-11-15/`。

## 6. 边界

本次批准只覆盖 T0 四视图工作台的上述三个边界；不覆盖分页、报告下载、失效原因展示、T1 六页工作台、写操作或恢复入口。T0 验收、commit 与是否进入 T1 仍由用户另行决定。