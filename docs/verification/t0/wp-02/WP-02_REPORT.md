# T0 · WP-02 核心契约落地报告

> 日期：2026-11-10 22:40（Asia/Shanghai）。
> 范围：把 G0 ⑨ 的 5 份 `contracts/*.schema.json` 落成 Pydantic v2 模型，做 schema↔模型一致性检查，并绑定 HTTP 创建接口与 422 字段路径映射。
> 状态：`IN_REVIEW`，等待用户验收；**验收前不进入 WP-03**。
> 计划：[`07_T0_PLAN_AND_GATES.md`](../../../design/07_T0_PLAN_AND_GATES.md) §2.2。
> 契约：[`contracts/README.md`](../../../../contracts/README.md)（⑨ v1.0，G0 冻结）。

## 1. 交付物

| 文件 | 作用 |
|---|---|
| [`researchflow/contracts/models.py`](../../../../researchflow/contracts/models.py) | 5 个契约的 Pydantic v2 模型、3 组枚举、条件与语义约束 |
| [`researchflow/contracts/parsing.py`](../../../../researchflow/contracts/parsing.py) | RFC 8259 严格解析：重复键、`NaN`/`Infinity`、非法 UTF-8 |
| [`researchflow/api/app.py`](../../../../researchflow/api/app.py) | `POST /api/v1/tasks` 绑定、422 统一错误体、幂等、`GET /tasks/{id}`、`/healthz`、`/readyz` |
| [`scripts/check_model_parity.py`](../../../../scripts/check_model_parity.py) | schema ↔ 模型行为/结构一致性检查，产出 `model_parity.json` |
| [`tests/test_contract_models.py`](../../../../tests/test_contract_models.py) | 72 个冻结用例 + 拒绝原因断言 |
| [`tests/test_api_422.py`](../../../../tests/test_api_422.py) | 422 字段路径、严格 JSON、幂等、`/recover` 404 |

## 2. 一致性策略（两层）

1. **行为一致**：`contracts/examples/` 全部 72 个用例，分别用 G0 校验器（schema + semantic + json 层）与 Pydantic 模型判定，接受/拒绝结论必须相同。
2. **结构一致**：逐契约递归比较 `properties`、`required`、`enum`、`const`、`pattern`、`additionalProperties`、`maxItems`，含嵌套对象 `dataset_ref`、`limits`、`retry_policy`、`required_check_coverage`、`parameters`。模型多字段、少字段、枚举放宽、pattern 漂移都会判 FAIL。

## 3. 真实结果

| 检查 | 结果 | 退出码 |
|---|---|---|
| `validate_contracts.py --selftest` | `SELFTEST 10/10 PASS` | 0 |
| `validate_contracts.py` | `contracts=5 cases=72 pass=72 fail=0` | 0 |
| `check_model_parity.py` | `cases=72 positives=5 negatives=67 agree=72 disagree=0 structure_problems=0 result=PASS` | 0 |
| `pytest tests/test_contract_models.py` | `89 passed` | 0 |
| `pytest tests/test_api_422.py` | `13 passed` | 0 |
| `pytest tests`（全量，含既有 state_sync 测试） | `125 passed` | 0 |

结构比较的逐契约结果见 [`model_parity.json`](model_parity.json) 的 `structure` 段（5 个契约均为 `ok: true`、`issues: []`）。

## 4. 语义约束在模型层的落点

| 约束 | 冻结层的实现 | 模型层实现 |
|---|---|---|
| `level → producer/kind`（原 `allOf`/`if-then`） | JSON Schema 条件 | `EvidenceRecord._level_consistency` |
| `SEM-NS-01` 自依赖 | `validate_contracts.run_semantic` | `NodeSpec._no_self_dependency` |
| `SEM-VR-01` 覆盖率算术 | 同上 | `VerificationReport._coverage_arithmetic` |
| `SEM-VR-02` `VERIFIED ⇒ missing==0` | 同上 | 同上 |
| 重复键 / `NaN` | JSON 层 | `parsing.loads_strict` |

## 5. API 绑定与 422 映射

- `POST /api/v1/tasks`：严格解析 → `TaskSpecCreate` 校验 → 服务端生成 `task_id` → `201 {"task_id", "state", "graph_version"}`。
- 422 统一体：`{"error_code": "SCHEMA_INVALID", "message", "field_path", "correlation_id"}`。
- `dataset_ref` 字符串形态 → `field_path="dataset_ref"`，`message` 固定为 06 §4.2 的 `dataset_ref must be an object with fields uri, sha256, license.`。
- 未知顶层字段 → `field_path` 为该字段名（`foo`）；缺必填 → 字段名；嵌套越界 → `limits.max_workers`。
- 重复键 → `field_path` 为重复的键名；`NaN` → `field_path="$"`。
- 幂等：同 `Idempotency-Key` 同体返回同一 `task_id`（201）；同键异体 409 `IDEMPOTENCY_CONFLICT`。
- 按决议 8 不注册 `POST /api/v1/tasks/{task_id}/recover`，负例已断言 404。

## 6. 边界与未实现（不得误读）

1. **`state` 字段不是状态机**：底层是 `_EphemeralTaskRegistry`（进程内、非持久、无迁移规则）。响应里的 `state="CREATED"` 只是 06 §4.2 冻结响应形态的绑定；状态机与 SQLite 在 WP-03，届时替换该注册表。不得据此宣称运行时状态迁移已实现。
2. 只绑定 `TaskSpec` 的创建与查询。`graph`／`evidence`／`verify`／`report`／`certificate` 端点未实现，依赖 WP-03、WP-06–WP-12。
3. 启动守卫（非回环绑定需 token）未实现；T0 默认回环运行，守卫属测试矩阵安全项，后续工作包落实。
4. API 请求体不含 `task_id`（服务端生成），故模型拆为 `TaskSpecCreate`（请求）与 `TaskSpec`（完整契约），字段差仅为 `task_id`。
5. 模型错误消息沿用 pydantic 英文；仅 `dataset_ref` 按 06 §4.2 固定为文档文案。422 JSON 结构不受影响。
6. 72 例之外的追加约束：`parameters` 已知键的显式 `null` 被拒绝，避免 pydantic 的 `Optional` 放宽 schema（schema 不接受 `null`）。

## 7. 复现命令

```powershell
& .venv/Scripts/python.exe scripts/validate_contracts.py --selftest
& .venv/Scripts/python.exe scripts/validate_contracts.py
& .venv/Scripts/python.exe scripts/check_model_parity.py
& .venv/Scripts/python.exe -m pytest tests -q
```

## 8. 证据清单

- [`model_parity.json`](model_parity.json)、[`model_parity.log`](model_parity.log)
- [`schema_validation.log`](schema_validation.log)、[`contracts_selftest.log`](contracts_selftest.log)
- [`model_validation.log`](model_validation.log)、[`api_422.log`](api_422.log)、[`full_suite.log`](full_suite.log)
