# ADR-007 裁决建议（2026-11-15 已获用户批准）

> 日期：2026-11-15（Asia/Shanghai）
> 性质：**提案记录**。用户已于 2026-11-15 选择“批准建议（推荐）”；正式裁决记录见 [`ADR-007_DECISION.md`](ADR-007_DECISION.md)，`ADR-007` 已改为 `ACCEPTED`。本文件保留批准前的建议文本与依据，不回溯修改。
> 依据：`docs/ADR/ADR-007-t0-workbench-scope.md`、`docs/G0/08_OPEN_QUESTIONS_AND_FREEZE.md` §4、`docs/design/07_T0_PLAN_AND_GATES.md` §2.13、`docs/verification/t0/00_implementation_decisions.md` D-29、`docs/verification/t0/wp-13/walkthrough.md`。

## 1. 当前状态与来源核实

- `ADR-007` 文件、`docs/ADR/README.md`、G0 ⑧ 三处一致：`PROPOSED（保持；WP-13 前裁决）`。
- 用户 2026-11-10 的书面裁决是“保持 `PROPOSED`，到 `WP-13` 前裁决”，记录在 ADR-007 §12、⑧ §6.1 与 `CHANGELOG_DEV.md`。
- 2026-11-15 在**仓库文档范围内**检索 `WP-13` / `ADR-007` / `D-29` / `四视图`，未发现将 ADR-007 改为 `ACCEPTED` 或明确批准三个待确认项的书面记录。该结论只覆盖仓库文档，不推断仓库之外的聊天或口头授权；若存在外部书面批准，应把来源补登到本文件与 ADR。
- 因此，当前不能把 ADR-007 标为 `ACCEPTED`，也不能把三个待确认项静默视为已批准。

## 2. 待裁决的三个边界

| # | ADR-007 §3 问题 | 选项 | 当前实现 | 建议 |
|---|---|---|---|---|
| 1 | 四视图的接口边界（是否暴露证据分页、报告下载） | (a) 只读当前页所需；(b) 暴露分页与下载 | 任务/DAG/证据/报告四视图；证据固定 `GET /evidence?limit=200` 单页；无分页控件；报告/凭证只读展示 JSON，无文件下载 | **(a)**：T0 维持单页与只读展示；分页/下载作为 T1 或后续 ADR，不占用 T0 出口 |
| 2 | 工作台与 API 是否同进程 | (a) 同进程只读；(b) 独立只读服务 | 独立 Streamlit 进程，只发 GET；不 import `researchflow.persistence` / `StateMachine` / `Collector`；API 不可达时显式报错 | **(b)**：独立只读进程，保持进程边界与可替换性；不因“都在本机”而合并进程 |
| 3 | “证据视图”是否展示 stale 标记与失效原因 | (a) 展示；(b) 只展示有效证据 | 展示 `STALE` 标记与“已失效证据”计数；**不展示**失效原因；`GET /evidence` 只返回 `invalidated` 布尔与 `invalidated_evidence_ids`，不返回 `reason_code`/`cause_type`/`cause_ref` | **标记按 (a)**；**原因暂不展示**。原因展示涉及冻结 REST 契约扩展，另立方案与 ADR，不在本次夹带 |

## 3. 建议的裁决正文（供用户确认）

> 批准 `ADR-007` 如下：
>
> 1. T0 工作台固定为任务、DAG、证据、报告四视图，只读，不写状态、不写证据、不触发恢复。
> 2. 四个视图由**独立只读 Streamlit 进程**通过已冻结的 REST GET 接口消费数据，不直接连接数据库，不 import 持久层/状态机/Collector。
> 3. 证据视图使用 `GET /api/v1/tasks/{id}/evidence?limit=200` 的**单页**结果，展示 `STALE` 标记与失效计数；T0 不实现分页交互、不提供报告/凭证文件下载。
> 4. 失效原因（`reason_code`/`cause_type`/`cause_ref`）不在 T0 视图中展示；如需展示，先提交冻结 REST 契约扩展方案，按变更流程另行批准。
> 5. 任何新增页面、写入型交互、分页或下载能力，均需新的 ADR，不得以“顺手加一个按钮”的方式扩范围。

## 4. 若批准，将执行的登记动作

1. `docs/ADR/ADR-007-t0-workbench-scope.md`：状态由 `PROPOSED` 改为 `ACCEPTED`，补充裁决日期、裁决者、三个边界的最终选择与依据。
2. `docs/ADR/README.md`：索引状态同步为 `ACCEPTED`。
3. `docs/verification/t0/00_implementation_decisions.md`：在 D-29 后追加“ADR-007 已由用户于 YYYY-MM-DD 批准；三个边界为 …；来源：本文件/用户书面确认”。
4. `docs/state/project_state.json` 的 `T-WP-13-001` 验收标准/证据路径补充 ADR-007 与 `wp-13/walkthrough.md`、`wp-13/screenshots/`。
5. `docs/CHANGELOG_DEV.md` 与 `docs/SESSION_HANDOFF.md` 追加记录。
6. **不修改** G0 冻结文档 ⑧ 的历史正文；如需在 ⑧ 标注后续状态，只能追加“后续裁决见 ADR-007”的引用，不改冻结时的 `PROPOSED` 记录。

## 5. 若用户不批准或要求调整

- 若选择 (b) 分页/下载：需要新增 REST 查询参数/端点或文件下载能力，先提交契约 diff、测试与安全影响；工作台不得先做。
- 若选择 (a) 同进程：需要重新评估进程边界、只读保证与启动方式；当前实现需改造，不能仅改文档。
- 若要求展示失效原因：先核实 `GET /evidence` 的冻结契约；当前实现没有原因字段，擅自加字段会破坏 `additionalProperties` 与契约冻结。方案应包含 `reason_code`、`cause_type`、`cause_ref` 的返回形态、向后兼容和负例。

## 6. 证据

- 四视图截图与 DOM：`docs/verification/t0/wp-13/screenshots/`、`docs/verification/t0/wp-13/screenshots.json`（`verdict=PASS`）。
- 走查：`docs/verification/t0/wp-13/walkthrough.md`。
- 工作台测试：`docs/verification/t0/wp-13/pytest_2026-11-15.log`（4 passed，含 stale 视图与 API 不可达负例）。
- 只读源码检查：`tests/t0/test_wp13_workbench.py::test_workbench_source_is_read_only`。

**当前结论：材料已补齐，且用户已于 2026-11-15 批准建议；正式裁决记录见 [`ADR-007_DECISION.md`](ADR-007_DECISION.md)。** 本文件保留为批准前的提案记录；三个边界的最终执行以 ADR-007 与正式裁决记录为准。