# 05 核心契约与状态机（G0 冻结 v1.0）

> 冻结日期：2026-11-10｜状态：**G0 冻结**｜被取代版本：**v0.3（候选）**｜G0 门禁 PASS 由用户宣布，本文不代替门禁判定。
> 状态：**G0 文档 ⑤ v1.0（G0 冻结）**；字段、枚举、状态机与守卫按 2026-11-10 现值冻结；**不是 G0 门禁 PASS，不是 T0 开发批准**。
> 日期：2026-11-10（Asia/Shanghai）；候选期内容更新于 2026-11-09。
> 基线：策划书内部 v4.3.0（文件名标签 v4.3.1；`BLK-002` 已关闭）；术语按 [01_BASELINE_AND_TERMS.md](../G0/01_BASELINE_AND_TERMS.md) v1.0；需求按 [02_REQUIREMENT_TRACEABILITY.md](../PRD/02_REQUIREMENT_TRACEABILITY.md) v1.0；架构按 [04_ARCHITECTURE.md](04_ARCHITECTURE.md) v1.0。
> **契约本体**：五个可冻结契约的机器可读定义在 [`contracts/*.schema.json`](../../contracts/)（G0 文档 ⑨ v1.0），由 [`scripts/validate_contracts.py`](../../scripts/validate_contracts.py) 做正/反例校验。本文是字段来源、语义与版本策略说明；两者冲突时以 schema + 校验器结果为准并立即报告。
> 字段来源标注：`[D.x]` = 附录 D.x 原文出现；`[推导]` = 由原文语义可推出但未逐字列出；`[OQ]` = 原文未定义，**不得凭空补**。
> 硬约束：**不新增策划书没有的字段**；缺字段一律记 `OQ`，由用户在 ⑧ 裁决后再写入 Schema。本版新增的 `schema_version`/`issued_at` 与三组枚举均来自用户决议，逐条标注来源。

## 1. 契约总则

### 1.1 七个契约与当前可冻结程度

| 契约 | 原文依据 | 字段完整度 | 本版处理 |
|---|---|---|---|
| `TaskSpec` | 附录 D.1 / P0474–P0497 | 完整（示例含 9 个顶层键） | **可冻结**；`contracts/taskspec.schema.json` |
| `NodeSpec` | 附录 D.2 / P0499–P0509 | 完整（决议 2 补 `schema_version`） | **可冻结**；`contracts/nodespec.schema.json` |
| `EvidenceRecord` | 附录 D.3 / P0511–P0526 | 完整（`kind` 7 值已按 v1.0 冻结） | **可冻结**；`contracts/evidencerecord.schema.json` |
| `VerificationReport` | 附录 D.4 / P0528–P0544 | 完整（决议 2 补 `schema_version`；状态枚举已按 v1.0 冻结） | **可冻结**；`contracts/verificationreport.schema.json` |
| `CompletionCertificate` | 附录 D.4 / P0545–P0560 | 完整（决议 2 补 `schema_version`、`issued_at`） | **可冻结**；`contracts/completioncertificate.schema.json` |
| `HarnessEvent` | §15.5 / P0386 仅列名 | **无 Schema** | **不冻结、不出 schema**，整条 `OQ-CT-06` |
| `DomainPack` | §5.7 / TABLE 24 钩子 | 只有钩子，无字段 | 部分冻结 + `OQ-CT-07`；**不出 schema** |

说明：JSON Schema 只能表达单文档结构。跨字段算术、自依赖、跨记录链、跨文档一致性不在 schema 内，清单见 §13；不得把这些不变量写成“已由 schema 校验”。

### 1.2 版本策略

1. 每个契约必须有 `schema_version`，格式 `MAJOR.MINOR`；本版冻结值统一为 `"1.0"`，并在 `contracts/*.schema.json` 中以 `const: "1.0"` 落地。
2. **加法兼容**（新增可选字段）升 `MINOR`；删除字段、改类型、改语义、改枚举成员升 `MAJOR`。
3. 读取方遇到未知 `MAJOR` 必须拒绝；遇到更高 `MINOR` 时，未知可选字段可忽略但必须记录一次告警（不得静默丢弃语义）。
   实现口径：`contracts/*.schema.json` 用 `const "1.0"` 固化 1.0，**只接受 1.0**；MINOR 升级时同步发布新 schema 并同时保留旧 schema 供历史数据校验，不在 1.0 schema 内放行更高 MINOR。这样“拒绝未知版本”与“向前兼容”不会互相矛盾。
4. 已进入正式基准的字段名、枚举值、版本号必须冻结并做迁移管理（附录 D 开篇 / P0472）。
5. 迁移脚本与旧版本兼容范围必须在 ⑥ 的 DB 迁移策略中登记。
6. **`schema_version` 必须进入签名载荷**（用户决议 2）：报告与证书签名均把 `schema_version` 作为白名单字段参与 JCS 规范化；验签方必须比对本地支持的 `MAJOR`，未知 `MAJOR` 一律拒绝。这样可阻止把 V1 载荷重放到 V2 验签器，或把 V2 产物降级当 V1 使用。详见 §1.5。

### 1.3 通用字段规则

| 规则 | 内容 | 来源 |
|---|---|---|
| ID | 稳定前缀 + UUID；不可复用已删除 ID | 附录 D.6 / P0574 |
| 时间 | UTC RFC 3339；`Z` 或 `+00:00` | 附录 D.6 / P0575 |
| 哈希 | 明确算法与编码；默认 SHA-256 小写十六进制 64 位 | 附录 D.6 / P0575 |
| JSON | 禁止重复键、`NaN`、`Infinity` | 附录 D.6 / P0576 |
| 未知字段 | 按 Schema 版本策略拒绝或显式兼容；不得静默纳入签名载荷 | 附录 D.6 / P0576；§7.5 / P0177 |
| 数组顺序 | 有语义时保持原顺序；JCS 只规范化对象属性，不重排数组 | 附录 D.6 / P0577；§7.5 |
| 证据追加 | 只追加；纠错用新事件引用旧事件 | 附录 D.6 / P0578 |
| 凭证 | 仅 `VERIFIED` 可生成 | 附录 D.6 / P0579；§7.4 / P0172 |
| 签名载荷 | 含 `schema_version`、规则版本、证据根、状态；字段白名单 + 域分离前缀 | §7.5 / P0173–P0178；`AGENTS.md` §4.10；决议 2 |

### 1.4 ID 前缀

| 对象 | 前缀 | 来源 |
|---|---|---|
| Task | `task_` | D.1 |
| Evidence | `ev_` | D.3 |
| Report | `report_` | D.4 |
| Certificate | `cert_` | D.4 |
| Attempt | `attempt_` | D.3 示例 `attempt_02` |
| Node | 无前缀要求（示例 `train_random_forest`） | D.2 |
| DC / SPA | `dc_id` / `spa_id`（无前缀规定） | D.5 |

### 1.5 签名载荷白名单（决议 2）

签名对象只覆盖下列字段，按 JCS 规范化后签名；`signature` 自身不进入载荷。字段顺序由 JCS 决定，不依赖书写顺序。

| 签名对象 | 必须进入载荷的字段 | 域分离前缀 |
|---|---|---|
| `VerificationReport` | `schema_version`、`report_id`、`task_id`、`final_state`、`l1_status`、`l2_status`、`l3_status`、`required_check_coverage`、`ruleset_hash`、`evidence_root`、`l3_coverage`、`issued_at`、`key_id` | `RF-REPORT-V1\0` |
| `CompletionCertificate` | `schema_version`、`cert_id`、`report_id`、`final_state`、`merkle_root`、`tree_size`、`ruleset_hash`、`code_hash`、`env_fingerprint`、`l3_coverage`、`skipped_nodes`、`alg`、`key_id`、`key_fingerprint`、`issued_at` | `RF-CERT-V1\0` |

规则：

1. 载荷字段集合写入实现常量，**不得由对象字段自动展开**；对象新增字段不自动进入载荷（防“加字段即改签名语义”）。
2. `schema_version` 必须参与签名且必须被验签方比对；这是防跨版本重放的唯一机器可检查手段（决议 2 附加要求）。
3. 域分离前缀区分报告与证书，二者签名不可互换。
4. 载荷中任一字段变化都必须重签；改 `final_state` 后沿用旧签名必须验签失败（§5.2）。
5. 本节只定义载荷范围，不定义密钥管理与信任锚存储（见 04 与 `OQ-029`）。

### 1.6 v1.0 枚举冻结清单（2026-11-10）

用户 2026-11-10 裁决：三组枚举按现值冻结为 v1.0；**保留“按 `MINOR` 可变”注记**——新增成员升 `MINOR`，删除成员、改语义或收窄取值升 `MAJOR`。

| 枚举 | 数量 | v1.0 冻结值 | 变更规则 |
|---|---|---|---|
| `EvidenceRecord.kind` | 7 | `agent_claim`、`tool_invocation`、`harness_trace`、`executor_launch`、`executor_process_exit`、`artifact_observed`、`verifier_recheck` | 新增成员 `MINOR`；删除/改语义 `MAJOR` |
| `l1_status` / `l2_status` / `l3_status` | 4 | `PASS`、`FAIL`、`SKIP`、`NOT_RUN` | 新增成员 `MINOR`；删除/改语义 `MAJOR` |
| `NodeSpec.side_effect_class` | 3 | `PURE_FUNCTION`、`PURE_ARTIFACT`、`SIDE_EFFECT` | 新增成员 `MINOR`；删除/改语义 `MAJOR` |

约束：三组值已写入 `contracts/*.schema.json` 的 `enum`；改值必须同步 ⑤、⑧、schema 与 `contracts/examples/`，并重跑 `validate_contracts.py`。`OQ-CT-02/03/09` 的**取值部分**据此关闭；`OQ-CT-06/07/08/10/12` 不受影响。

## 2. `TaskSpec`

### 2.1 字段

| 字段 | 类型 | 必填 | 枚举/格式 | 校验规则 | 来源 |
|---|---|---|---|---|---|
| `schema_version` | string | 是 | `MAJOR.MINOR`，本版 `1.0` | 非 `1.0` 拒绝（本 schema 为 1.0 专用；MINOR 升级另发 schema） | D.1 |
| `task_id` | string | 是 | `task_<uuid>` | 全局唯一；不可复用 | D.1 + D.6 |
| `domain_pack` | string | 是 | `name@MAJOR.MINOR.PATCH`，示例 `tabular_ml@1.0.0` | 必须已注册；版本必须可解析 | D.1 |
| `goal` | string | 是 | 非空 | 仅描述目标，不参与判定 | D.1 |
| `dataset_ref.uri` | string | 是 | 本地 URI，示例 `local://datasets/...` | 不得逃逸受限目录；不得为网络 URI（T0 断网） | D.1 + §17.1 |
| `dataset_ref.sha256` | string | 是 | 64 位小写十六进制 | 与文件实际哈希一致 | D.1 |
| `dataset_ref.license` | string | 是 | 许可证 ID | 非空；来源可追溯 | D.1 + §17.2 |
| `template_id` | string | 是 | `name@MAJOR.MINOR.PATCH` | 必须在白名单注册表存在 | D.1 |
| `parameters` | object | 是 | 由模板 Schema 约束 | 未知参数默认拒绝；类型/范围校验 | D.1 |
| `parameters.target` | string | 否（示例必填） | 列名 | 必须存在于数据集字段 | D.1 |
| `parameters.seed` | integer | 否（示例必填） | ≥0 | 必须记录到 Split Manifest | D.1 |
| `parameters.test_size` | number | 否（示例必填） | 0 < x < 1 | 与 split 结果一致 | D.1 |
| `parameters.models` | array[string] | 否（示例必填） | 白名单模型名 | 空数组拒绝；重复项拒绝 | D.1 |
| `ruleset_hash` | string | 是 | 64 位小写十六进制 | 必须与 Gate 使用的规则版本一致 | D.1 |
| `limits.wall_time_sec` | integer | 是 | >0 | 超过则 Executor 终止并记录 | D.1 |
| `limits.max_workers` | integer | 是 | 1–2（第一版上限 2） | 超过 2 拒绝 | D.1 + §5.4 |
| `limits.max_memory_mb` | integer | 是 | >0 | 超过则终止/告警 | D.1 |

【OQ-CT-08】`parameters` 是自由对象还是按模板 Schema 强类型？本版建议按模板 Schema 强类型，但需裁决。

### 2.2 正例

```json
{
  "schema_version": "1.0",
  "task_id": "task_3f2c...",
  "domain_pack": "tabular_ml@1.0.0",
  "goal": "Train and independently verify classifiers",
  "dataset_ref": {"uri": "local://datasets/breast_cancer.csv", "sha256": "<64-hex>", "license": "CC-BY-4.0"},
  "template_id": "classification_benchmark@1.0.0",
  "parameters": {"target": "diagnosis", "seed": 42, "test_size": 0.2, "models": ["logistic_regression"]},
  "ruleset_hash": "<64-hex>",
  "limits": {"wall_time_sec": 1800, "max_workers": 2, "max_memory_mb": 4096}
}
```

### 2.3 负例

| 负例 | 期望 |
|---|---|
| 缺 `schema_version` | 422 |
| `schema_version: "2.0"` | 拒绝（未知 MAJOR） |
| `dataset_ref` 为字符串（附录 E.1 形态） | 422 `SCHEMA_INVALID`，`field_path=dataset_ref`，消息写明期望 `{uri,sha256,license}`（决议 9 / `ADR-002`） |
| `dataset_ref.sha256` 与实际文件不符 | 拒绝，返回字段路径 |
| `template_id` 未注册 | 拒绝，记录拒绝原因 |
| `limits.max_workers: 4` | 拒绝（超第一版上限） |
| 未知顶层字段 `foo` | 按版本策略拒绝（本版建议拒绝） |
| `parameters.models: []` | 拒绝 |
| `dataset_ref.uri` 为 `https://...` | T0 拒绝（断网约束） |

已落为机器可执行的用例：`contracts/examples/taskspec.negative.{1..15}.json`（含重复键与 `NaN` 两个 JSON 层反例）。`sha256` 与文件实际哈希不符、模板未注册属外部上下文校验，不在单文档 schema 内，由 API/注册表在 ⑥ 落地。

### 2.4 `dataset_ref` 形态（决议 9 / `ADR-002`）

`TaskSpec.dataset_ref` 与 API 请求统一为对象 `{uri, sha256, license}`（附录 D.1）。附录 E.1 的字符串样例 `dataset://breast_cancer@sha256:<hash>` **不再作为契约形态**：API 收到字符串必须返回 422 并指明期望对象形态，不得静默解析成对象。该偏离记 `ADR-002`。

### 2.5 迁移

- 字段只增不改；`dataset_ref` 若未来支持多数据集，应新增 `dataset_refs` 数组并升 `MINOR`，不得改变 `dataset_ref` 语义。

## 3. `NodeSpec`

### 3.1 字段

| 字段 | 类型 | 必填 | 枚举/格式 | 校验规则 | 来源 |
|---|---|---|---|---|---|
| `node_id` | string | 是 | 任务内唯一 | 重复拒绝；不得含路径分隔符 | D.2 + `[推导]` |
| `node_type` | string | 是 | 示例 `ml.train.classifier` | 必须在域包允许类型内 | D.2 |
| `template_id` | string | 是 | `name@MAJOR.MINOR.PATCH` | 已注册 | D.2 |
| `depends_on` | array[string] | 是 | 节点 ID | 必须存在；不得自依赖；不得成环 | D.2 |
| `input_refs` | array[string] | 是 | `artifact://...` | 必须可解析到已有产物引用 | D.2 |
| `parameters_hash` | string | 是 | 64 位小写十六进制 | 与解析后的参数一致 | D.2 |
| `side_effect_class` | string | 是 | `PURE_FUNCTION` / `PURE_ARTIFACT` / `SIDE_EFFECT`（v1.0 冻结，3 值；按 `MINOR` 可变） | 枚举外拒绝 | D.2 + ⑧ §2；2026-11-10 裁决 |
| `retry_policy.max_attempts` | integer | 是 | ≥1 | T0 上限 2（示例值） | D.2 |
| `retry_policy.backoff_sec` | number | 是 | ≥0 | 不得为负 | D.2 |
| `required_checks` | array[string] | 是 | 示例 `executor_observed`、`artifact_hash`、`metric_source` | 必须在规则集存在；空数组拒绝 | D.2 |
| `schema_version` | string | **是** | `1.0` | 不匹配拒绝；决议 2 补入，记 `ADR-003` | 决议 2 |

### 3.2 正例

```json
{
  "node_id": "train_random_forest",
  "node_type": "ml.train.classifier",
  "template_id": "random_forest@1.0.0",
  "depends_on": ["split_dataset", "preprocess"],
  "input_refs": ["artifact://split_manifest"],
  "parameters_hash": "<64-hex>",
  "side_effect_class": "PURE_ARTIFACT",
  "retry_policy": {"max_attempts": 2, "backoff_sec": 2},
  "required_checks": ["executor_observed", "artifact_hash", "metric_source"]
}
```

### 3.3 负例

| 负例 | 期望 |
|---|---|
| `depends_on` 含不存在节点 | 拒绝 |
| `depends_on` 自引用 | 拒绝（`SEM-NS-01`；JSON Schema 无法表达） |
| 节点构成环 | 拒绝并指出环路径 |
| `node_id` 重复 | 拒绝 |
| `required_checks: []` | 拒绝 |
| `side_effect_class` 未知值 | 拒绝（v1.0 冻结枚举外） |
| `parameters_hash` 与参数不一致 | 拒绝 |

已落为机器可执行的用例：`contracts/examples/nodespec.negative.{1..13}.json`。自引用由 `SEM-NS-01` 检查；成环、缺失前驱、重复节点属图级校验，在 DAG Builder（⑦ `WP-04`）。

### 3.4 迁移

- `schema_version` 已由决议 2 加入并作为 `1.0` 起点（不改变既有字段语义）。
- `side_effect_class` 三值已按 v1.0 冻结；新增成员按 `MINOR`，删除成员或改语义按 `MAJOR`。

## 4. `EvidenceRecord`

### 4.1 字段

| 字段 | 类型 | 必填 | 枚举/格式 | 校验规则 | 来源 |
|---|---|---|---|---|---|
| `schema_version` | string | 是 | `1.0` | 不匹配拒绝 | D.3 |
| `evidence_id` | string | 是 | `ev_<uuid>` | 唯一；不可复用 | D.3 + D.6 |
| `task_id` | string | 是 | `task_<uuid>` | 必须存在 | D.3 |
| `node_id` | string | 是 | 节点 ID | 必须存在于任务图 | D.3 |
| `attempt_id` | string | 是 | `attempt_NN` | 必须存在；与 Executor 记录一致 | D.3 |
| `event_seq` | integer | 是 | 单调递增、任务内唯一 | 缺口/回退拒绝 | D.3 + 附录 F.1 |
| `level` | string | 是 | `E0`、`E1`、`E2`、`E3` | 写入者必须匹配等级（见 01 §4.3） | D.3 + TABLE 31 |
| `kind` | string | 是 | 7 值 T0 最小集合（v1.0 冻结，§4.5；按 `MINOR` 可变） | 枚举外拒绝；等级与类型必须匹配 | D.3 + ⑧ §2；2026-11-10 裁决 |
| `producer` | string | 是 | 组件名，示例 `collector` | 必须与实际写入者一致 | D.3 |
| `timestamp` | string | 是 | RFC 3339 UTC | 允许时钟偏差但必须记录 | D.3 + D.6 |
| `payload_hash` | string | 是 | 64 位小写十六进制 | 与实际 payload 一致 | D.3 |
| `artifact_refs` | array[string] | 否 | `artifact://...` | 引用必须存在 | D.3 |
| `prev_hash` | string | 是 | 64 位十六进制；首条为约定值 | 必须等于上一条 `chain_hash` | D.3 |
| `chain_hash` | string | 是 | 64 位十六进制 | 由规范化记录计算 | D.3 |

【OQ-CT-10】首条 `prev_hash` 的约定值（全零 / 空串 / 创世哈希）未定义。

### 4.2 正例

```json
{
  "schema_version": "1.0",
  "evidence_id": "ev_9a1b...",
  "task_id": "task_3f2c...",
  "node_id": "train_random_forest",
  "attempt_id": "attempt_02",
  "event_seq": 17,
  "level": "E2",
  "kind": "executor_process_exit",
  "producer": "collector",
  "timestamp": "2026-11-06T09:00:00Z",
  "payload_hash": "<64-hex>",
  "artifact_refs": ["artifact://model.pkl"],
  "prev_hash": "<64-hex>",
  "chain_hash": "<64-hex>"
}
```

### 4.3 负例

| 负例 | 期望 |
|---|---|
| `event_seq` 重复或回退 | 拒绝 |
| `event_seq` 出现缺口 | 记录并标记链不完整 |
| `prev_hash` 与上一条 `chain_hash` 不符 | 链校验失败 |
| `payload_hash` 与 payload 不符 | 拒绝 |
| `level` 与 `producer` 不匹配（如 Agent 产 E2） | 拒绝 |
| `level` 与 `kind` 不匹配（如 E0 写 `executor_process_exit`） | 拒绝（§4.5） |
| `artifact_refs` 指向不存在产物 | 拒绝 |
| 修改历史记录后重算自身哈希 | 链校验失败（下游 `prev_hash` 不符） |
| 删除一条记录 | 缺口被检测 |

已落为机器可执行的用例：`contracts/examples/evidencerecord.negative.{1..12}.json`。`prev_hash` 与上一条 `chain_hash` 相符、`event_seq` 缺口/回退、`payload_hash` 与 payload 一致属**跨记录**校验，schema 无法表达，见 §13 与 ⑦ `WP-07`。

### 4.4 迁移

- 只追加；纠错新增记录并引用旧 `evidence_id`，不得原位覆盖（D.6 / P0578）。

### 4.5 等级-类型-写入者映射（`kind` v1.0 冻结集合）

| 等级 | 唯一允许的写入者 `producer` | 允许的 `kind` | 语义 |
|---|---|---|---|
| `E0` | `collector` | `agent_claim` | Agent 声明，Collector 标记；永不单独推动状态 |
| `E1` | `collector` | `tool_invocation`、`harness_trace` | 工具调用/轨迹存在，不等于真实执行 |
| `E2` | `collector` | `executor_launch`、`executor_process_exit`、`artifact_observed` | 受控执行发生、产物存在 |
| `E3` | `verifier` | `verifier_recheck` | 独立重算/重跑 |

该映射由 `contracts/evidencerecord.schema.json` 的 `allOf`/`if-then` 固化为机器约束；对应反例 `evidencerecord.negative.3.json`（E2 由 `agent` 写出）与 `negative.12.json`（E0 写执行类 `kind`）。

**v1.0 冻结（2026-11-10）**：`kind` 7 值按现值冻结；新增成员按 `MINOR`，删除或改语义按 `MAJOR`。本版把“等级-类型-写入者”一致性同时冻结，因为这直接对应 01 §4.3 与 `AGENTS.md` §4.5/§4.7，不是新语义。

【OQ-CT-10】首条 `prev_hash` 的约定值仍未定义。schema 只要求 64 位小写十六进制，不强制创世值；⑧ §2 建议 64 个 `0`，待确认后写入校验器与 `WP-07`。

## 5. `VerificationReport`

### 5.1 字段

| 字段 | 类型 | 必填 | 枚举/格式 | 校验规则 | 来源 |
|---|---|---|---|---|---|
| `report_id` | string | 是 | `report_<uuid>` | 唯一 | D.4 |
| `task_id` | string | 是 | `task_<uuid>` | 必须存在 | D.4 |
| `final_state` | string | 是 | `VERIFIED`、`PARTIAL`、`FAILED`、`BLOCKED` | 四态；仅 `VERIFIED` 可签发凭证 | D.4 + P0133 |
| `l1_status` | string | 是 | `PASS` / `FAIL` / `SKIP` / `NOT_RUN`（v1.0 冻结，4 值；按 `MINOR` 可变） | 枚举外拒绝 | D.4 + ⑧ §2；2026-11-10 裁决 |
| `l2_status` | string | 是 | 同上（v1.0 冻结，4 值；按 `MINOR` 可变） | 枚举外拒绝 | D.4 + ⑧ §2；2026-11-10 裁决 |
| `l3_status` | string | 是 | 同上（v1.0 冻结，4 值；按 `MINOR` 可变） | 枚举外拒绝；与 `l3_coverage` 一致 | D.4 + ⑧ §2；2026-11-10 裁决 |
| `required_check_coverage.required` | integer | 是 | ≥0 | 与规则集一致 | D.4 |
| `required_check_coverage.passed` | integer | 是 | 0–required | 不得大于 required | D.4 |
| `required_check_coverage.missing` | integer | 是 | ≥0 | `required - passed` 必须相等 | D.4 |
| `ruleset_hash` | string | 是 | 64 位十六进制 | 与 Gate 使用版本一致 | D.4 |
| `evidence_root` | string | 是 | Merkle 根 | 必须与证据链计算一致 | D.4 |
| `l3_coverage` | number | 是 | 0.0–1.0 | 报告指标来源节点必须达标 | D.4 + I-04 |
| `issued_at` | string | 是 | RFC 3339 UTC | 不得早于证据时间 | D.4 |
| `key_id` | string | 是 | 密钥标识 | 必须存在且未撤销 | D.4 |
| `signature` | string | 是 | base64 | 验签通过 | D.4 |
| `schema_version` | string | **是** | `1.0` | 不匹配拒绝；决议 2 补入，记 `ADR-003`；必须进入签名载荷 | 决议 2 |

### 5.2 正例与负例

正例：`final_state=VERIFIED`、`required=passed=12`、`missing=0`、`l3_coverage=1.0`、签名有效。

| 负例 | 期望 |
|---|---|
| `final_state=VERIFIED` 但 `missing>0` | 拒绝签发 |
| `passed > required` | 拒绝 |
| `evidence_root` 与证据链不符 | 拒绝 |
| `l3_coverage < 规定阈值` | 不得 `VERIFIED` |
| `ruleset_hash` 与 Gate 不一致 | 拒绝 |
| `signature` 缺失或无效 | 拒绝 |
| 修改 `final_state` 后沿用旧签名 | 验签失败 |

已落为机器可执行的用例：`contracts/examples/verificationreport.negative.{1..14}.json`。其中三条是**语义层**（`SEM-VR-01/02`）：`passed > required`、`missing != required - passed`、`VERIFIED` 但 `missing > 0`——JSON Schema 无法做算术与跨字段比较，因此不得声称这些规则“已在 schema 里”。

未落 schema、也不在本版语义层的两条：`evidence_root` 与证据链的一致性（跨记录，`verify_bundle.py` + Gate）、`l3_coverage` 是否达到规则集阈值（阈值属规则集，Gate 判定）。

### 5.3 迁移

- 四态不改名；新增状态必须升 `MAJOR` 并经 ADR。

## 6. `CompletionCertificate`

### 6.1 字段

| 字段 | 类型 | 必填 | 枚举/格式 | 校验规则 | 来源 |
|---|---|---|---|---|---|
| `cert_id` | string | 是 | `cert_<uuid>` | 唯一 | D.4 |
| `report_id` | string | 是 | `report_<uuid>` | 必须存在且为 `VERIFIED` | D.4 |
| `final_state` | string | 是 | 仅 `VERIFIED` | 其他状态禁止 | D.4 + P0133 |
| `merkle_root` | string | 是 | 根哈希 | 与报告 `evidence_root` 一致 | D.4 |
| `tree_size` | integer | 是 | ≥1 | 与证据条数一致 | D.4 |
| `ruleset_hash` | string | 是 | 64 位十六进制 | 与报告一致 | D.4 |
| `code_hash` | string | 是 | 64 位十六进制 | 与执行代码快照一致 | D.4 |
| `env_fingerprint` | string | 是 | 64 位十六进制 | 与 E2 记录一致 | D.4 |
| `l3_coverage` | number | 是 | 0.0–1.0 | 达标 | D.4 |
| `skipped_nodes` | array[string] | 是 | 可为空 | T0 必须为空（无 SPA） | D.4 + B1 |
| `alg` | string | 是 | `Ed25519` | 固定 | D.4 |
| `key_id` | string | 是 | 密钥标识 | 未撤销 | D.4 |
| `key_fingerprint` | string | 是 | 外部信任锚指纹 | 必须与信任锚匹配 | D.4 + I-08 |
| `signature` | string | 是 | base64 | 验签通过 | D.4 |
| `schema_version` | string | **是** | `1.0` | 不匹配拒绝；决议 2 补入，记 `ADR-003`；必须进入签名载荷 | 决议 2 |
| `issued_at` | string | **是** | RFC 3339 UTC | 不得早于报告 `issued_at`；决议 2 补入 | 决议 2 |

### 6.2 正例与负例

正例：`final_state=VERIFIED`、`tree_size` 与证据条数一致、`skipped_nodes=[]`、`alg=Ed25519`、`key_fingerprint` 命中外部信任锚。

| 负例 | 期望 |
|---|---|
| `report_id` 指向 `PARTIAL` | 拒绝生成 |
| `merkle_root` 与报告不符 | 拒绝 |
| `skipped_nodes` 非空（T0） | 拒绝（T0 不做 SPA） |
| `alg` 非 `Ed25519` | 拒绝 |
| `key_fingerprint` 不在信任锚内 | 验签失败 |
| 替换公钥并重签 | 指纹不匹配，拒绝 |

已落为机器可执行的用例：`contracts/examples/completioncertificate.negative.{1..13}.json`，其中包含决议 2 的两条（缺 `schema_version`、缺 `issued_at`）与 T0 的一条（`skipped_nodes` 非空）。

跨文档不变量（`merkle_root == report.evidence_root`、`tree_size == 证据条数`、`ruleset_hash` 与报告一致）无法在单文档 schema 内表达，由 Verifier 签发入口与 `verify_bundle.py` 校验，见 §13。

### 6.3 迁移

- 新增撤销语义必须通过 revocation event（§附录 F.1 / P0639），不得静默改旧凭证；Task 级撤销属 T1/⑧。

## 7. `HarnessEvent`（不冻结）

| 项 | 状态 |
|---|---|
| 原文出现 | §15.5 / P0386 仅列名；附录 D 无 Schema |
| 相关线索 | §6.3 / TABLE 27 消息协议是 Agent 内部消息，不是 Harness 事件 |
| 处理 | **整条 `OQ-CT-06`**；⑤ 不定义字段；T0 不实现；T2 前必须补齐 |
| 冻结前置 | 固定 Harness 版本 + 官方事件契约 + 契约测试 |

## 8. `DomainPack`（部分冻结）

### 8.1 已知钩子

| 钩子 | 职责 | 约束 | 来源 |
|---|---|---|---|
| `profile_data` | 数据画像：字段、缺失、分布、标签、分组/时间字段 | 只读数据，结果由 Collector 记录 | §5.7 / TABLE 24 |
| `required_checks` | 声明领域必检项与规则版本 | 规则可机器判定且有测试 | 同上 |
| `tool_contracts` | 白名单工具、参数 Schema、超时和资源限制 | 禁止任意 shell/Python 入口 | 同上 |
| `knowledge_seeds` | 领域规范、工具说明、故障案例 | 来源、许可、版本和 hash 齐全 | 同上 |
| `render_report` | 渲染领域报告 | 只展示 Verifier 结果，不修改判定 | 同上 |

### 8.2 缺失字段

| 缺失 | 说明 | 处理 |
|---|---|---|
| 包标识与版本 | D.1 使用 `tabular_ml@1.0.0`，但未定义 `DomainPack` 的 `name/version` 字段 | `OQ-CT-07` |
| `schema_version` | 未定义 | `OQ-CT-07` |
| 钩子签名/返回类型 | 未定义 | `OQ-CT-07` |
| 领域必检项 ID 清单 | 未定义 | ⑤ 不补；由 T0 域包落地时以规则文件登记 |

**结论：`DomainPack` 在 G0 只能冻结“钩子名与约束”，不能冻结字段级 Schema。**

## 9. 状态机

### 9.1 说明

【策划书】§6.2 / TABLE 26 的“四类状态机”是 **Task / Node / Evidence / Recovery**；报告与凭证状态在 P0133 单独定义。阶段 7 的 `runtime_states.md` 用“Task/Node/Report/Certificate”表述，与 TABLE 26 的归类不同但状态值不冲突；本文件按 TABLE 26 归类，并把 Report/Certificate 单列为“签发对象状态”。

【用户决议 B1】Node 新增 `INVALIDATED`，因此 Node 状态为 **10 个**。

### 9.2 Task 状态机（9 个状态）

| 当前 | 允许的下一状态 | 守卫 | 副作用 | 来源 |
|---|---|---|---|---|
| `CREATED` | `PLANNING`、`CANCELLED` | 无 | 写审计 | TABLE 70 R02 |
| `PLANNING` | `READY`、`BLOCKED`、`FAILED` | DAG 必须通过校验 | 写 `graph_version` | R03 |
| `READY` | `RUNNING`、`CANCELLED` | 至少一个节点 `READY` | 写审计 | R04 |
| `RUNNING` | `VERIFYING`、`FAILED`、`BLOCKED` | 执行未结束不能验证最终完成 | 写审计 | R05 |
| `VERIFYING` | `COMPLETED`、`FAILED`、`BLOCKED` | `COMPLETED` 需报告 `VERIFIED` 和凭证 | 写审计 | R06 |
| 其余 | 拒绝 | — | 失败也写审计 | F.1 |

未列出的迁移一律拒绝。

### 9.3 Node 状态机（10 个状态）

| 当前 | 允许的下一状态 | 守卫 | 副作用 | 来源 |
|---|---|---|---|---|
| `PLANNED` | `READY`、`BLOCKED` | 依赖未满足不能 `READY` | 写审计 | TABLE 70 R07 |
| `READY` | `RUNNING`、`BLOCKED` | 资源/权限检查通过 | 写审计 | R08 |
| `RUNNING` | `VERIFYING`、`FAILED` | 必须有 attempt 结束事件 | 记录 attempt | R09 |
| `VERIFYING` | `VERIFIED`、`FAILED`、`BLOCKED` | Gate PASS + Verifier `VERIFIED` + 有效凭证 | 写审计 | R10 + P0133 |
| `FAILED` | `DIAGNOSING`、`BLOCKED` | 恢复次数未超限 | 写审计 | R11 |
| `DIAGNOSING` | `RECOVERING`、`BLOCKED` | 根因/计划结构有效 | 写审计 | R12 |
| `RECOVERING` | `READY`、`BLOCKED` | 恢复计划执行完并复核 | 写审计 | R13 |
| `VERIFIED` | `INVALIDATED` | 上游输入/前驱/图版本/规则版本变化；证据判定 stale | 写失效记录；**不删除证据** | **B1 / ADR-001** |
| `INVALIDATED` | `READY` | 三条全部满足：① 计划文件存在于内容寻址路径；② `sha256(文件字节) == plan_hash`，且与 `audit_log` 冻结记录一致；③ 冻结事件早于本次重跑（决议 5） | 写 `nodes.plan_id`/`nodes.plan_hash` + `audit_log` | **B1 / ADR-001 / 决议 5** |

**未授权迁移**（一律拒绝，需新 ADR）：

- `VERIFIED → READY`（跳过 `INVALIDATED`）
- `INVALIDATED → VERIFYING`、`INVALIDATED → VERIFIED`、`INVALIDATED → FAILED`
- 任何状态直接回 `PLANNED`
- `COMPLETED` 相关的 Task 级失效（T1）

【已决议 · `OQ-CT-11`】`INVALIDATED → READY` 的计划引用形态由决议 5 关闭：**存 `plan_id` + `plan_hash`**，不是自由文本、也不只存 audit 事件 ID。守卫必须同时校验：

1. 计划文件存在于内容寻址路径（文件名 = `plan_hash`），且可读；
2. `sha256(文件字节) == plan_hash`，且该 `plan_hash` 与 `audit_log` 中本次失效的冻结记录一致；
3. 冻结事件早于本次重跑尝试（计划必须“重跑前已冻结”，不允许边跑边改）。

任一条不满足即拒绝迁移并写 `DENIED` 审计（§9.7）；不得“计划缺失但放行”。

【`OQ-CT-12`】`INVALIDATED` 重复失效是否幂等仍未裁决。本版建议：节点已是 `INVALIDATED` 时，重复失效只**追加** `evidence_invalidations` 记录（引用新的 stale `evidence_id` 与变更原因），不重复执行 `VERIFIED → INVALIDATED` 迁移、不回滚状态；幂等性以追加记录可追溯为准，待 ⑦ 实现前确认。

### 9.4 Evidence 状态机

| 当前 | 允许的下一状态 | 约束 | 来源 |
|---|---|---|---|
| `RECEIVED` | `VALIDATED`、`INVALID` | 写入后先进入 `RECEIVED` | TABLE 26 R04 |
| `VALIDATED` | `APPENDED`、`CONFLICT` | 链/哈希/等级校验通过 | 同上 |
| `APPENDED` | —（终态） | 只追加；不修改 | 同上 |
| `INVALID` / `CONFLICT` | —（终态，保留） | 无效记录保留并标注 | 同上 |

### 9.5 Recovery 状态机（**仅 T1**；T0 不复用）

【决议 6】T0 **不复用**本状态机：没有 `PROPOSED`/`APPROVED`，没有 Agent 提案，没有人工审批环节。T0 的恢复路径必须**确定性、可重放**：给定同一输入哈希、图版本、规则版本与失效集合，`plan_hash` 必须唯一且可复算。

T0 只用三样东西表达“恢复”：`evidence_invalidations`（追加失效，见 I-11 与 ⑥ §1.3）、内容寻址的冻结计划文件（`plan_id`/`plan_hash`、不签名、不进七契约、不对外）、`INVALIDATED → READY` 守卫（§9.3）。下表状态值**不得出现在 T0 代码或 DB 枚举中**。

| 当前 | 允许的下一状态 | 约束 | 来源 |
|---|---|---|---|
| `PROPOSED` | `VALIDATED`、`ESCALATED` | Recovery Agent 只提案 | TABLE 26 R05 |
| `VALIDATED` | `APPROVED`、`ESCALATED` | 计划结构有效 | 同上 |
| `APPROVED` | `EXECUTING` | 调度器/人工批准 | 同上 |
| `EXECUTING` | `RECHECKED`、`ESCALATED` | 计划不得中途改写 | 同上 |
| `RECHECKED` | `CLOSED`、`ESCALATED` | 复核完成 | 同上 |

【已决议 · `OQ-CT-13`】T0 不复用完整状态机；完整 Recovery 状态机与 G4 均留 T1。T0 的确定性要求由 `WP-R` 的测试证明（⑦）：同输入两次生成同一 `plan_hash`、计划文件不可改写、守卫三条件各有负例。

### 9.6 报告与凭证状态

| 对象 | 允许状态 | 规则 | 来源 |
|---|---|---|---|
| `VerificationReport` | `VERIFIED`、`PARTIAL`、`FAILED`、`BLOCKED` | 由独立 Verifier 签发；`PARTIAL` 映射为节点 `BLOCKED` | P0133 |
| `CompletionCertificate` | 仅 `VERIFIED` | 仅由 `VERIFIED` 报告生成；否则拒绝 | P0133、D.6 / P0579 |

### 9.7 迁移请求的必填参数

【策划书】附录 F.1 / P0637；`AGENTS.md` §4：

| 参数 | 说明 |
|---|---|
| `previous_state` | 必须与当前持久化状态一致，过期拒绝 |
| `next_state` | 必须在允许表内 |
| `actor` | 发起者标识 |
| `reason_code` | 结构化原因码 |
| `rule_version` | 规则版本 |
| `correlation_id` | 关联 ID（任务/attempt/计划） |
| `plan_id` / `plan_hash` | **仅 `INVALIDATED → READY` 必填**（决议 5）；其余迁移禁止携带 |

缺任一参数拒绝；迁移失败也写 `audit_log`。

**失败迁移的审计语义（决议 7）**：

1. 状态写失败 → 状态事务回滚 → **在独立事务**写一条 `audit_log(result=DENIED)`，含 `error_code`、尝试的 `previous_state`/`next_state`、`correlation_id`，以及 `actor`/`reason_code`/`rule_version`。
2. 测试必须证明该 `DENIED` 记录在状态回滚后仍存在（真实 SQLite，不用 mock）。
3. 若第二个事务也失败：降级写**结构化 stderr**（单行 JSON，含同样字段 + `audit_write_failed=true`），并在测试报告中计为**测试缺口**；不得静默吞掉，也不得把缺口写成通过。
4. 降级路径本身必须有测试覆盖（人为让审计事务失败，断言 stderr 行出现且退出码/告警符合预期）。

## 10. 不变量与一致性

| 编号 | 不变量 | 校验点 |
|---|---|---|
| I-01 | Agent 不能直接写 Task/Node 状态 | 权限矩阵 + 权限测试 |
| I-02 | E0/E1 不能单独满足执行类必检项 | Gate |
| I-03 | Verifier 与 Executor 工作目录分离 | 目录/进程检查 |
| I-04 | 报告指标来源节点必须达到规定 L3 覆盖 | Gate + Report |
| I-05 | 无有效 DC 的节点不能被 SPA 跳过 | T2 的 SPA 检查（T0 不适用） |
| I-06 | 签名载荷包含规则版本、证据根和状态（`schema_version` 的补充见 I-13） | 签名/验签 |
| I-07 | 非 `VERIFIED` 报告不产生 `CompletionCertificate` | 签发入口 |
| I-08 | 离线验签使用外部可信指纹，不信任证书自带公钥 | `verify_bundle.py` |
| **I-09** | **`INVALIDATED` 只从 `VERIFIED` 进入，且只能回 `READY`** | StateMachine（B1 / ADR-001） |
| **I-10** | **stale 证据不得满足必检项；证据不删除** | Gate + Evidence Store（B1 / 决议 4） |
| **I-11** | **失效/恢复控制事件不是证据**：只写 `audit_log` + `evidence_invalidations`，不占用 `E0–E3` | StateMachine / Collector（决议 4） |
| **I-12** | **`INVALIDATED → READY` 必须同时满足计划存在、`plan_hash` 一致、先冻结后重跑** | StateMachine（决议 5） |
| **I-13** | **报告与证书签名载荷必须含 `schema_version`；验签方拒绝未知 `MAJOR`** | Signing / Verifier（决议 2） |
| **I-14** | **失败迁移的 `DENIED` 审计在状态回滚后仍存在**；二次失败降级结构化 stderr 并计测试缺口 | StateMachine（决议 7） |

## 11. 契约与状态的迁移策略

| 变更 | 版本动作 | 是否需 ADR |
|---|---|---|
| 新增可选字段 | `MINOR` | 否，但需记录变更日志 |
| 新增枚举成员 | `MINOR` | 否，但需确认读取方兼容 |
| 删除字段、改类型、改语义 | `MAJOR` | **是** |
| 新增状态或迁移边 | `MAJOR`（状态机版本） | **是**（如 B1 的 `INVALIDATED` 已配 `ADR-001`） |
| 修改签名载荷字段 | `MAJOR` + 重新验签 | **是** |
| 补 `schema_version`（`NodeSpec`/`VerificationReport`/`CompletionCertificate`）与证书 `issued_at` | `MINOR`；本版作为 `1.0` 起点 | **是**（`ADR-003`） |
| `dataset_ref` 由字符串 URI 改为对象（API 层统一） | 在 `1.0` 冻结前完成，不产生契约版本变更 | **是**（`ADR-002`） |
| `RecoveryPlan` 定为 T0 内部不可变产物（不入七契约、不签名） | 不涉及契约版本 | **是**（`ADR-004`） |

## 12. 未决项清单

| 编号 | 问题 | 状态 | 结论 / 去向 |
|---|---|---|---|
| `OQ-CT-01` | `NodeSpec` 是否补 `schema_version` | **已关闭**（决议 2） | 必填，`const "1.0"` |
| `OQ-CT-02` | `EvidenceRecord.kind` 枚举 | **已关闭**（2026-11-10 按 v1.0 现值冻结） | 7 值与等级-写入者映射已冻结；新增成员按 `MINOR` |
| `OQ-CT-03` | `l1/l2/l3_status` 枚举 | **已关闭**（2026-11-10 按 v1.0 现值冻结） | `PASS/FAIL/SKIP/NOT_RUN` 四值已冻结；新增成员按 `MINOR` |
| `OQ-CT-04` | `VerificationReport` 是否补 `schema_version` | **已关闭**（决议 2） | 必填，且进入签名载荷 |
| `OQ-CT-05` | `CompletionCertificate` 是否补 `schema_version`、`issued_at` | **已关闭**（决议 2） | 两者必填，均进入签名载荷 |
| `OQ-CT-06` | `HarnessEvent` 无 Schema | 开放 | T2 前以固定版本官方契约补齐；G0 不冻结、不出 schema |
| `OQ-CT-07` | `DomainPack` 字段级 Schema | 开放 | G0 只冻结钩子名与约束；不出 schema |
| `OQ-CT-08` | `parameters` 是否强类型 | 开放 | 单文档 schema 只约束已知键；未知参数由模板 Schema 层拒绝 |
| `OQ-CT-09` | `side_effect_class` 枚举 | **已关闭**（2026-11-10 按 v1.0 现值冻结） | `PURE_FUNCTION/PURE_ARTIFACT/SIDE_EFFECT` 三值已冻结；新增成员按 `MINOR` |
| `OQ-CT-10` | 首条 `prev_hash` 约定 | 开放 | schema 只要求 64 位小写十六进制；建议 64 个 `0`，待确认 |
| `OQ-CT-11` | `INVALIDATED → READY` 计划引用形态 | **已关闭**（决议 5） | `plan_id` + `plan_hash`；守卫三条件（§9.3） |
| `OQ-CT-12` | `INVALIDATED` 重复失效幂等 | 开放 | 建议只追加 `evidence_invalidations`，不重复迁移 |
| `OQ-CT-13` | T0 是否复用 Recovery 状态机 | **已关闭**（决议 6） | 不复用；完整状态机仅 T1 |

**说明**：`OQ-CT-01/04/05/11/13` 已由用户 2026-11-09 决议关闭；`OQ-CT-02/03/09` 已于 2026-11-10 按 v1.0 现值冻结（只改成员仍按 `MINOR`，删除或改语义按 `MAJOR`）；`OQ-CT-06/07/08/10/12` 仍开放，其中 `OQ-CT-06/07` 不阻塞 G0，因为对应契约本就不冻结、不出 schema。

## 13. schema 外不变量清单（不得声称“已由 schema 校验”）

| 编号 | 不变量 | 在哪校验 | 对应反例 |
|---|---|---|---|
| `SEM-NS-01` | 节点不得依赖自身 | `validate_contracts.py` 语义层 | `nodespec.negative.13.json` |
| `SEM-VR-01` | `passed <= required` 且 `missing == required - passed` | 语义层 | `verificationreport.negative.5/6.json` |
| `SEM-VR-02` | `final_state=VERIFIED ⇒ missing == 0` | 语义层 | `verificationreport.negative.7.json` |
| — | `prev_hash` 等于上一条 `chain_hash`、`event_seq` 无缺口/回退、`payload_hash` 与 payload 一致 | Collector / Gate（跨记录） | ⑦ `WP-07` |
| — | `evidence_root` 与证据集一致、`merkle_root == report.evidence_root`、`tree_size == 证据条数` | Verifier 签发入口 / `verify_bundle.py` | ⑦ `WP-12`、G6-T0 |
| — | `l3_coverage` 达到规则集阈值 | Gate（阈值属规则集） | ⑦ `WP-08` |
| — | 图级：成环、孤立、缺失前驱、重复节点 | DAG Builder | ⑦ `WP-04` |
| — | 计划文件存在、`plan_hash` 一致、先冻结后重跑 | StateMachine 守卫 + `WP-R` | ⑦ `WP-R` |
| — | `DENIED` 审计在回滚后仍存在 | StateMachine + SQLite 集成测试 | ⑦ `WP-03` |

## 14. 版本记录

| 版本 | 日期 | 变更 | 状态 |
|---|---|---|---|
| v0.1 | 2026-11-09 | 七契约字段表、状态迁移、不变量、OQ 清单 | 候选，已被 v0.2 取代 |
| v0.2 | 2026-11-09 | 按用户 10 项决议：补三个 `schema_version` 与证书 `issued_at`（§1.2、§3、§5、§6）、新增签名载荷白名单（§1.5）、`dataset_ref` 对象化（§2.4）、`kind`/`side_effect_class`/状态枚举候选（§3、§4.5、§5）、`INVALIDATED → READY` 三条件守卫（§9.3）、T0 不复用 Recovery 状态机（§9.5）、失败迁移 `DENIED` 审计（§9.7）、I-11–I-14、schema 外不变量清单（§13） | 用户已认可 |
| v0.3 | 2026-11-09 | 定向修订 3 处：① §1.2 增补 `const "1.0"` 与 MINOR 兼容的实现口径（1.0 schema 只接受 1.0，MINOR 升级另发 schema）；② §2.1 `TaskSpec.schema_version` 校验列改为“非 `1.0` 拒绝”；③ 版本记录 §2.5→§2.4 误引修正。**字段、枚举、状态机、守卫均未改** | 候选，已被 v1.0 冻结取代 |
| v1.0 | 2026-11-10 | **G0 冻结定版**：三组枚举按现值冻结（`kind` 7 / `l1-l3_status` 4 / `side_effect_class` 3），新增 §1.6 冻结清单；`OQ-CT-02/03/09` 取值部分关闭；补冻结日期、状态与被取代版本。**字段、状态机、守卫、签名载荷未改** | **G0 冻结** |

---

**标记：本文件是 G0 文档 ⑤ v1.0（G0 冻结），不是 G0 门禁 PASS。** 契约机器可读定义见 [`contracts/`](../../contracts/)（v1.0）；G0 是否 PASS 由用户宣布；未建 `.venv`、未写业务代码。