# T0 · WP-02 验收记录

> 日期：2026-11-10 22:45（Asia/Shanghai）。
> 裁决人：`用户`（本会话选择"验收通过并提交"）。
> 结论：`T-WP-02-001` → `DONE`。
> 依据：[`WP-02_REPORT.md`](WP-02_REPORT.md) 与 `docs/verification/t0/wp-02/` 全部证据。

## 1. 验收标准逐条对账

| # | 验收标准（摘自 `project_state.json` 原值，未改写） | 证据 | 判定 |
|---|---|---|---|
| 1 | 5 份冻结 schema 落成 Pydantic v2 模型；`properties`/`required`/`enum`/`const`/`pattern`/`additionalProperties` 与 schema 逐节点一致 | `researchflow/contracts/models.py`；`model_parity.json` → `structure` 5/5 `ok: true` | 通过 |
| 2 | 72 个冻结用例在模型层的接受/拒绝结论与 schema 层完全一致（5 正例接受，67 反例拒绝），且反例断言拒绝原因 | `model_parity.log`：`agree=72 disagree=0`；`model_validation.log`：89 passed，含原因断言 | 通过 |
| 3 | schema 无法表达的跨字段约束在模型层实现：`level→producer/kind`、`SEM-NS-01`、`SEM-VR-01`、`SEM-VR-02` | `models.py` 四个 `model_validator`；`model_validation.log` 对应用例 | 通过 |
| 4 | 重复键与 `NaN`/`Infinity` 在 JSON 层拒绝，不进入模型 | `researchflow/contracts/parsing.py`；`model_validation.log` 两个 JSON 层用例；`api_422.log` | 通过 |
| 5 | API 绑定 TaskSpec 创建；422 统一返回 `SCHEMA_INVALID` + `field_path` + `correlation_id`，`dataset_ref` 字符串形态与文档文案一致 | `api_422.log`：13 passed（含 5 条 422 路径断言） | 通过 |
| 6 | 按决议 8 不注册 `POST /recover`，访问返回 404；幂等同键同体 201、同键异体 409 | `api_422.log`：`test_recover_route_is_not_registered`、`test_idempotent_*` | 通过 |
| 7 | `validate_contracts.py` 与全量 pytest 仍 exit 0；证据齐全；未实现部分已如实标注 | `schema_validation.log`、`contracts_selftest.log`、`full_suite.log`；`WP-02_REPORT.md` §6 | 通过 |

## 2. 复核命令与真实结果

| 命令 | 结果 | 退出码 |
|---|---|---|
| `validate_contracts.py --selftest` | `SELFTEST 10/10 PASS` | 0 |
| `validate_contracts.py` | `contracts=5 cases=72 pass=72 fail=0` | 0 |
| `check_model_parity.py` | `agree=72 disagree=0 structure_problems=0 result=PASS` | 0 |
| `pytest tests` | `125 passed` | 0 |
| `state_sync.py validate\|render\|check` | 均通过；见 `state_sync.log` | 0 |

生成文件 SHA256：

- `docs/PROJECT_STATE.md`：`096130298a153690c2f7373440b84744adaa1131ed767f1f4b775d0dab7c6cc8`
- `docs/IMPLEMENTATION_STATUS.md`：`9fd641b5465daa09b2bbeeb30e277aad19bb6636f0d5b92387a321381e507e31`

## 3. 随验收确认的边界

- API 的 `state="CREATED"` 是 06 §4.2 响应形态绑定，底层为临时内存注册表，**不是状态机**；`StateMachine` 与 SQLite 属 WP-03。
- `graph`／`evidence`／`verify`／`report`／`certificate` 端点、启动守卫未实现，已在 `WP-02_REPORT.md` §6 登记。
- 未修改任何冻结 schema；`contracts/` 与 72 例保持原样。

## 4. 未随验收改变的事项

- `current_phase` 仍 `T0`；`current_milestone` 仍 `M0_GOVERNANCE_BASELINE`。
- `G1`–`G7` 仍 `NOT_STARTED`；`last_verified_commit` 仍 `19c337f`。
- `BLK-003` 仍 `OPEN` / `MEDIUM`；13b 仍 `NOT VERIFIED`；2D 未单独执行。
