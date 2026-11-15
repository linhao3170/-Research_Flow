# WP-13 最小工作台走查（真实 API 数据）

> 日期：2026-11-15（Asia/Shanghai）
> 范围：`researchflow/workbench/app.py`（T0 四视图，只读 REST）
> 依据：`docs/design/07_T0_PLAN_AND_GATES.md` §2.13（证据：`screenshots/` + `walkthrough.md`）、`docs/ADR/ADR-007-t0-workbench-scope.md`（仍为 PROPOSED）、`docs/verification/t0/00_implementation_decisions.md` D-24/D-29。
> 性质：走查记录与截图证据。**不**构成 ADR-007 的批准；正式裁决仍待用户。

## 1. 交付物

| 文件 | 说明 |
|---|---|
| [`screenshots/task.png`](screenshots/task.png) | 任务视图（默认标签页，含任务状态、图版本、模板与 TaskSpec） |
| [`screenshots/dag.png`](screenshots/dag.png) | DAG 视图（graph_version、graph_hash、确定性拓扑序、节点表） |
| [`screenshots/evidence.png`](screenshots/evidence.png) | 证据视图（证据条数、链校验、已失效证据数、STALE 标记） |
| [`screenshots/report.png`](screenshots/report.png) | 报告与凭证视图（报告状态、必检覆盖、L3 覆盖、报告 JSON、CompletionCertificate） |
| [`screenshots/overview.png`](screenshots/overview.png) | 默认标签页整体（与 `task.png` 相同，用于展示四标签布局） |
| [`screenshots/api_unreachable.png`](screenshots/api_unreachable.png) | API 不可达：显式错误，不伪造数据 |
| [`screenshots/dom/`](screenshots/dom/) | 每个视图的 DOM 文本快照，供机器核对可见文字 |
| [`screenshots.json`](screenshots.json) | 截图命令、时间、耗时、尺寸、SHA256、DOM 检查与 `verdict` |
| [`capture_screenshots.py`](capture_screenshots.py)、[`cdp_capture.py`](cdp_capture.py) | 可重放的截图脚本（Chrome DevTools Protocol） |

截图均为 1440×1200 PNG，由真实 Streamlit 进程渲染真实 REST API 数据后捕获；DOM 检查全部 `missing=[]`，`screenshots.json` 的 `verdict` 为 `PASS`。

## 2. 真实数据来源

截图运行使用 `docs/verification/t0/e2e/superseded_2026-11-15_pre_a01/run_1/runtime` 的**副本**（`runtime/wp13-screenshots/`，被 `.gitignore` 忽略）：

- 该 run_1 是 A-01/A-02 修复前的历史证据，已整体归档并在 [`SUPERSEDED_NOTICE.md`](../e2e/superseded_2026-11-15_pre_a01/SUPERSEDED_NOTICE.md) 标明；它只用于展示真实数据形态，不用于证明当前实现通过。
- 原归档目录未被修改、未被覆盖。
- 副本只包含 `researchflow.db` 与 `tasks/<task>/evidence_payloads/`，**不包含** `keys/` 私钥。
- API 以只读视图（GET）消费该副本；验证报告与凭证取数据库中的既有对象，不在截图流程中重新签发。

数据快照：

| 项 | 值 |
|---|---|
| task_id | `task_f1901dd5-29e0-4f0f-a93d-b1f175d086e2` |
| Task 状态 | `COMPLETED` |
| graph_version | `1` |
| 节点 | `split_dataset` / `train_logistic_regression` / `train_random_forest`，均 `VERIFIED`，`attempt_seq=2` |
| 证据 | 32 条；链校验 OK |
| 已失效证据 | 16 条（第一次 attempt 的证据，标记 STALE，未删除） |
| 最新报告 | `report_f3cba87b-969f-4028-a204-4934b8f65ccc`，`VERIFIED`，L3 覆盖 `1.0` |
| 最新凭证 | `cert_0e9d71cf-2c84-437c-acef-d0aceeec85f0` |

说明：run_1 在第一次验证后执行了失效与重跑，因此数据库同时保留第一次报告/凭证和第二次报告/凭证；工作台按 API 语义展示**最新**报告与凭证，证据视图同时展示新旧证据，旧证据带 `STALE` 标记。

## 3. 一键复现

在项目根目录：

```powershell
$rfPy = 'D:\ResearchFlow-project\.venv\Scripts\python.exe'
& $rfPy -B docs/verification/t0/wp-13/capture_screenshots.py
```

脚本会：复制 run_1 数据 → 启动真实 API（随机回环端口）→ 启动真实 Streamlit（随机回环端口）→ 通过 Chrome CDP 等待每个视图的预期文字出现后截图 → 停止 API 后由第二个 Streamlit 实例（指向未监听端口）捕获“API 不可达” → 写 `screenshots.json`。

## 4. 手工走查

```powershell
$rfPy = 'D:\ResearchFlow-project\.venv\Scripts\python.exe'
$task = 'task_f1901dd5-29e0-4f0f-a93d-b1f175d086e2'
$db = 'D:\ResearchFlow-project\runtime\wp13-screenshots\researchflow.db'

# 1) API（回环、无 token）
& $rfPy -B -m researchflow.cli serve --db $db --host 127.0.0.1 --port 8010 --log-level warning

# 2) 另开终端：工作台
$env:RESEARCHFLOW_API_URL = 'http://127.0.0.1:8010'
$env:RESEARCHFLOW_TASK_ID = $task
& $rfPy -B -m streamlit run researchflow/workbench/app.py `
    --server.headless=true --server.address=127.0.0.1 --server.port=8510 `
    --browser.gatherUsageStats=false --server.fileWatcherType=none
```

浏览器打开（`view` 仅选择初始标签页，默认仍为四标签）：

- `http://127.0.0.1:8510/?task_id=<task>&view=task`
- `http://127.0.0.1:8510/?task_id=<task>&view=dag`
- `http://127.0.0.1:8510/?task_id=<task>&view=evidence`
- `http://127.0.0.1:8510/?task_id=<task>&view=report`
- 不支持的 `view` 值回退到默认第一个标签页；`task_id` 也可只放在侧栏输入框。

API 不可达：停止 API 进程后刷新页面，工作台显示“无法读取任务：… 无法连接 API …”，不显示任何伪造的任务/证据/报告。截图 `api_unreachable.png` 使用指向未监听回环端口的第二个 Streamlit 实例捕获，以避免浏览器加载时序干扰。

## 5. 四视图内容与观察

### 5.1 任务视图

- 任务状态指标：`COMPLETED`；图版本：`1`；模板：`classification_benchmark@1.0.0`。
- TaskSpec JSON 只读展示（来自 `GET /api/v1/tasks/{id}`）。
- 无编辑、提交、重跑或恢复控件。

### 5.2 DAG 视图

- `graph_version=1`，展示 `graph_hash` 与确定性拓扑序 `split_dataset → train_logistic_regression → train_random_forest`。
- 节点表含 node_type、state、attempt_seq、depends_on、required_checks。
- 数据来自 `GET /api/v1/tasks/{id}/graph`；未登记图时 API 返回 409，工作台显示“DAG 尚不可用”。

### 5.3 证据视图

- 指标：证据条数 32、链校验 OK、已失效证据 16。
- 表格字段：event_seq、level、kind、node_id、attempt_id、timestamp、invalidated。
- 第一次 attempt 的 16 条证据显示 `STALE`；证据未被删除。
- 证据请求固定为 `?limit=200` 的一页；T0 无分页控件。
- **不展示失效原因**：当前 `GET /evidence` 只返回 `invalidated_evidence_ids` 与逐项 `invalidated` 布尔，不返回 `reason_code` / `cause_type` / `cause_ref`。要让视图展示原因，需要扩展冻结的 REST 契约（另列方案，不在本次擅自修改）。

### 5.4 报告与凭证视图

- 指标：报告状态 `VERIFIED`、必检通过 8/8、L3 覆盖 `1.0`；无缺口时不显示 warning。
- 只读展示报告 JSON 与 CompletionCertificate（包含 merkle_root、tree_size、key_fingerprint、issued_at 等）。
- 报告/凭证均从 `GET /report`、`GET /certificate` 取得；T0 不提供报告文件下载。
- 视图不重新验签，也不把“已展示证书”表述为“已离线验签”；离线验签证据在 `docs/verification/t0/g6-t0/`。

### 5.5 API 不可达

- 工作台捕获 `WorkbenchAPIError` 后显示 `st.error("无法读取任务：...")`，随后 `return`；不会渲染旧的或构造的数据。
- 既有 AppTest 用例 `test_workbench_reports_api_failure_without_inventing_data` 覆盖该路径；本次新增 `api_unreachable.png` 作为人工可查看证据。

## 6. 边界（供 ADR-007 裁决）

| # | 边界 | 当前实现 | 备注 |
|---|---|---|---|
| 1 | 接口边界：是否暴露分页、报告下载 | 只读当前页所需；证据单页 `limit=200`；无分页交互；无报告下载 | 与 ADR-007 选项 (a) 一致 |
| 2 | 进程边界：同进程还是独立只读服务 | 独立 Streamlit 进程，只发 GET，不 import 持久层/StateMachine/Collector | 与 ADR-007 选项 (b) 一致 |
| 3 | stale 展示：是否展示失效标记与原因 | 展示 `STALE` 与失效计数；**不展示原因**（API 未提供） | 标记满足；原因需另立 API 变更方案 |

## 7. 验证记录

| 检查 | 命令 | 结果 | 证据 |
|---|---|---|---|
| 工作台测试（含新增 stale 视图） | `& $rfPy -m pytest tests/t0/test_wp13_workbench.py -q -p no:cacheprovider` | **4 passed**，exit 0，23.50 s | [`pytest_2026-11-15.log`](pytest_2026-11-15.log)（历史 `pytest.log` 保留） |
| 截图与 DOM | `& $rfPy -B docs/verification/t0/wp-13/capture_screenshots.py` | exit 0，`verdict=PASS`，14.35 s 级 | [`screenshots.json`](screenshots.json)、[`screenshots/`](screenshots/) |
| 只读源码检查 | `test_workbench_source_is_read_only` | 通过 | 同上 pytest 日志 |

截图脚本使用 Chrome DevTools Protocol 等待每个视图的预期文字真实出现，再捕获 PNG/DOM；`screenshots.json` 中的 `dom_ok=true`、`images_ok=true`。DOM 检查覆盖：任务 `COMPLETED`、DAG 拓扑序、证据条数 32/失效 16、报告 `VERIFIED` + `CompletionCertificate`、四标签、API 不可达错误文字。

## 8. 限制与未做

1. 截图使用归档的修复前 run_1 数据副本；副本不含私钥，也不重新签发报告/凭证。归档目录未被修改；当前 e2e 的新 run_1..3 另行生成。
2. 浏览器为 Chrome headless；未引入 Playwright/Selenium 等新依赖，CDP 客户端仅用于证据脚本。
3. 工作台固定 `limit=200` 单页；超过 200 条证据时视图不会自动分页（T0 已披露边界，未在本次扩展）。
4. 不展示失效原因；不提供报告下载；不提供任何写操作或恢复入口。
5. Streamlit 日志出现 `use_container_width` 弃用提示（仅警告，不影响本次渲染）；未在本次做全站升级。
6. ADR-007 仍为 `PROPOSED`；本走查不改变其状态。

## 9. 正式裁决（已完成）

2026-11-15 用户选择“批准建议（推荐）”：

- 独立只读 Streamlit 进程，只发 GET；
- 四视图只读，证据固定 `limit=200` 单页、无分页、无报告下载；
- 展示 `STALE` 与失效计数，不展示失效原因（原因展示需另立 REST 契约变更方案）。

正式记录：[`ADR-007_DECISION.md`](ADR-007_DECISION.md)；ADR 状态已由 `PROPOSED` 改为 `ACCEPTED`，见 [`docs/ADR/ADR-007-t0-workbench-scope.md`](../../../ADR/ADR-007-t0-workbench-scope.md)。本走查与截图作为 ⑦ §2.13 的交付证据；T0 验收、commit 与是否进入 T1 仍由用户另行决定。