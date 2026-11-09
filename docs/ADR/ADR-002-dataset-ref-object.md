# ADR-002：`dataset_ref` 统一为对象形态（偏离附录 E.1 字符串样例）

| 字段 | 内容 |
|---|---|
| 编号 | `ADR-002` |
| 状态 | **ACCEPTED**（用户 2026-11-09，决议 9） |
| 日期 | 2026-11-09 |
| 决策者 | 用户（书面决议 9） |
| 影响版本 | `TaskSpec` `1.0`；REST API `POST /api/v1/tasks` |
| 取代 | 无（编号由用户指定） |

## 1. 背景

策划书附录 D.1 的 `TaskSpec.dataset_ref` 是对象 `{uri, sha256, license}`；附录 E.1 的创建任务样例把它写成字符串 `dataset://breast_cancer@sha256:<hash>`。两种形态并存会导致：

- 同一个字段在不同入口语义不同，校验器必须写两套；
- 字符串形态无法携带 `license`，而 `license` 在 D.1 是必填；
- 若 API 静默把字符串解析成对象，会掩盖缺字段，等于替调用方补数据。

## 2. 决策

1. `TaskSpec.dataset_ref` 与 API 请求体统一为对象 `{uri, sha256, license}`，与 D.1 一致。
2. API 收到字符串形态必须返回 `422 SCHEMA_INVALID`，`field_path=dataset_ref`，消息写明期望对象形态；**不得**自动解析。
3. JSON Schema 中 `dataset_ref.type = object` 且 `additionalProperties: false`；`uri` 仅允许 `local://`（T0 断网）。
4. 该偏离记为本 ADR；不改写附录 E.1 原文，只声明本项目不采用其字符串样例。

## 3. 后果

- `contracts/taskspec.schema.json` 与 `contracts/examples/taskspec.negative.3.json` 覆盖该拒绝。
- ⑥ §4.2 的请求样例改为对象形态，并给出 422 示例。
- 客户端必须提供 `sha256` 与 `license`；缺任一即 422。
- 将来若支持多数据集，新增 `dataset_refs` 数组并按 `MINOR` 升级，不改变 `dataset_ref` 语义。

## 4. 备选（未选）

| 方案 | 未选原因 |
|---|---|
| API 接受字符串并内部转换 | 会静默补 `license`，且掩盖缺 `sha256`，审计无法追溯调用方真实输入 |
| 把 D.1 改成字符串 | 丢失哈希与许可字段，且改动的是策划书契约而非本项目接口 |
| 同时接受两种形态 | 校验双路径、错误码歧义，后续迁移成本更高 |

## 5. 验证

- `& $py scripts/validate_contracts.py` → `taskspec.negative.3.json` 命中 `type @ $.dataset_ref`，整体 72/72 PASS、exit 0。
- 日志：`docs/verification/g0/02_validate_contracts.log`。
- 文档：⑤ §2.4、⑥ §4.2/§4.4。