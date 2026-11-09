# 06 数据模型与 API（SQLite WAL + REST，v1.0）

> 冻结日期：2026-11-10｜状态：**G0 冻结**｜被取代版本：**v0.2（候选）**｜G0 门禁 PASS 由用户宣布，本文不代替门禁判定。
> 状态：**G0 文档 ⑥ v1.0（G0 冻结）**；**不是 G0 门禁 PASS，不是 T0 开发批准**。
> 日期：2026-11-10（Asia/Shanghai）；候选期内容更新于 2026-11-09。
> 基线：策划书内部 v4.3.0（文件名标签 v4.3.1；`BLK-002` 已关闭）；术语按 [01](../G0/01_BASELINE_AND_TERMS.md) v1.0；契约与状态按 [05](05_CONTRACTS_AND_STATES.md) v1.0；机器可读契约见 [`contracts/`](../../contracts/)（⑨ v1.0）。
> 重要边界：**策划书没有给出 DDL、索引、外键或事务边界的原文**。本文表结构全部标 `【工程建议】`，随 G0 冻结作为基线，但不是原文要求；字段名以 05 与 `contracts/*.schema.json` 为准，不新增契约字段。
> API 部分：路径、方法、状态码、错误码、幂等规则来自 §6.4 / TABLE 28 与附录 E / TABLE 69，属 `【策划书】`；候选期 v0.2 的两处偏离（`dataset_ref` 对象化、T0 关闭 `POST /recover`）来自用户决议，逐条标注，现随 v1.0 冻结。

## 1. 数据模型总则

### 1.1 存储与运行模式

| 项 | 值 | 来源 |
|---|---|---|
| 引擎 | SQLite，WAL 模式 | §15.4 / TABLE 58 R04 |
| 并发 | 单机；应用并发上限 2 | §5.4 / TABLE 22 |
| 事务 | 短事务；写操作串行化 | `【工程建议】` |
| 时间 | UTC RFC 3339 文本存储 | 附录 D.6 / P0575 |
| 哈希 | SHA-256 小写十六进制 | 附录 D.6 / P0575 |
| 外键 | 启用 `PRAGMA foreign_keys=ON` | `【工程建议】` |
| 恢复计划存储 | **内容寻址文件** `<root>/recovery_plans/<plan_hash>.json`，不入库、不签名、不对外 | 决议 3 |

### 1.2 表清单（全部为 `【工程建议】`）

| 表 | 用途 | 唯一写者 | 追加写 | 可删除 |
|---|---|---|---|---|
| `tasks` | 任务主记录与当前状态 | StateMachine | 否（状态字段） | 否 |
| `nodes` | 节点主记录与当前状态 | StateMachine | 否 | 否 |
| `graph_versions` | 图版本与图快照哈希 | DAG Builder（经 StateMachine 登记） | 是 | 否 |
| `evidence` | 证据记录（E0–E3） | Collector（E0–E2）、Verifier（E3） | **是** | 否 |
| `evidence_invalidations` | stale/失效记录 | WP-R（经 StateMachine） | **是** | 否 |
| `audit_log` | 状态迁移、工具请求、密钥操作审计 | StateMachine | **是** | 否 |
| `reports` | VerificationReport | Verifier | 否 | 否 |
| `certificates` | CompletionCertificate | Verifier | 否 | 否 |
| `idempotency_keys` | 幂等键与请求哈希 | API | 是 | 否（按保留期归档） |
| `ingestion_log` | 重复投递计数 | Collector | 是 | 否 |

规则：

1. **只追加表**（`evidence`、`evidence_invalidations`、`audit_log`、`ingestion_log`）禁止 `UPDATE`/`DELETE`；纠错用新记录引用旧记录（附录 D.6 / P0578）。
2. 状态字段只允许 StateMachine 写；其他组件通过接口请求迁移。
3. 报告/凭证表由 Verifier 写，签发后不得修改；撤销走 revocation（T1）。
4. **恢复计划不入库**（决议 3）：`RecoveryPlan` 是 T0 内部不可变产物，存为**内容寻址文件**（文件名 = `sha256`，即 `plan_hash`），DB 只存 `nodes.plan_id`/`nodes.plan_hash` 与 `audit_log` 的冻结记录。原 v0.1 的 `recovery_plans` 表**删除**；不得以“库里存一份”替代内容寻址文件。

### 1.3 建议 DDL（G0 冻结基线，非原文）

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE tasks (
  task_id           TEXT PRIMARY KEY,
  schema_version    TEXT NOT NULL,
  domain_pack       TEXT NOT NULL,
  goal              TEXT NOT NULL,
  task_spec_hash    TEXT NOT NULL,
  state             TEXT NOT NULL,
  graph_version     INTEGER,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE TABLE nodes (
  task_id           TEXT NOT NULL REFERENCES tasks(task_id),
  node_id           TEXT NOT NULL,
  schema_version    TEXT NOT NULL,
  node_type         TEXT NOT NULL,
  template_id       TEXT NOT NULL,
  state             TEXT NOT NULL,
  attempt_seq       INTEGER NOT NULL DEFAULT 0,
  plan_id           TEXT,
  plan_hash         TEXT,
  updated_at        TEXT NOT NULL,
  PRIMARY KEY (task_id, node_id),
  CHECK ((plan_id IS NULL AND plan_hash IS NULL)
      OR (plan_id IS NOT NULL AND plan_hash IS NOT NULL))
);

CREATE TABLE graph_versions (
  task_id           TEXT NOT NULL REFERENCES tasks(task_id),
  graph_version     INTEGER NOT NULL,
  graph_hash        TEXT NOT NULL,
  topology_order    TEXT NOT NULL,
  created_at        TEXT NOT NULL,
  PRIMARY KEY (task_id, graph_version)
);

CREATE TABLE evidence (
  evidence_id       TEXT PRIMARY KEY,
  task_id           TEXT NOT NULL REFERENCES tasks(task_id),
  node_id           TEXT NOT NULL,
  attempt_id        TEXT NOT NULL,
  event_seq         INTEGER NOT NULL,
  level             TEXT NOT NULL CHECK (level IN ('E0','E1','E2','E3')),
  kind              TEXT NOT NULL,
  producer          TEXT NOT NULL,
  timestamp         TEXT NOT NULL,
  payload_hash      TEXT NOT NULL,
  artifact_refs     TEXT,
  prev_hash         TEXT NOT NULL,
  chain_hash        TEXT NOT NULL,
  UNIQUE (task_id, event_seq)
);

CREATE TABLE evidence_invalidations (
  invalidation_id   TEXT PRIMARY KEY,
  task_id           TEXT NOT NULL REFERENCES tasks(task_id),
  node_id           TEXT NOT NULL,
  evidence_id       TEXT NOT NULL REFERENCES evidence(evidence_id),
  reason_code       TEXT NOT NULL,
  cause_type        TEXT NOT NULL
                    CHECK (cause_type IN ('INPUT_CHANGE','PREDECESSOR_CHANGE',
                                          'GRAPH_VERSION_CHANGE','RULESET_CHANGE')),
  cause_ref         TEXT,
  plan_id           TEXT,
  plan_hash         TEXT,
  created_at        TEXT NOT NULL
);

CREATE TABLE audit_log (
  audit_id          TEXT PRIMARY KEY,
  task_id           TEXT,
  node_id           TEXT,
  actor             TEXT NOT NULL,
  action            TEXT NOT NULL,
  previous_state    TEXT,
  next_state        TEXT,
  reason_code       TEXT,
  rule_version      TEXT,
  correlation_id    TEXT,
  plan_id           TEXT,
  plan_hash         TEXT,
  result            TEXT NOT NULL CHECK (result IN ('OK','DENIED')),
  error_code        TEXT,
  created_at        TEXT NOT NULL
);

CREATE TABLE reports (
  report_id         TEXT PRIMARY KEY,
  schema_version    TEXT NOT NULL,
  task_id           TEXT NOT NULL REFERENCES tasks(task_id),
  final_state       TEXT NOT NULL,
  l1_status         TEXT NOT NULL,
  l2_status         TEXT NOT NULL,
  l3_status         TEXT NOT NULL,
  ruleset_hash      TEXT NOT NULL,
  evidence_root     TEXT NOT NULL,
  l3_coverage       REAL NOT NULL,
  issued_at         TEXT NOT NULL,
  key_id            TEXT NOT NULL,
  signature         TEXT NOT NULL
);

CREATE TABLE certificates (
  cert_id           TEXT PRIMARY KEY,
  schema_version    TEXT NOT NULL,
  report_id         TEXT NOT NULL REFERENCES reports(report_id),
  final_state       TEXT NOT NULL CHECK (final_state = 'VERIFIED'),
  merkle_root       TEXT NOT NULL,
  tree_size         INTEGER NOT NULL,
  ruleset_hash      TEXT NOT NULL,
  code_hash         TEXT NOT NULL,
  env_fingerprint   TEXT NOT NULL,
  l3_coverage       REAL NOT NULL,
  skipped_nodes     TEXT NOT NULL,
  alg               TEXT NOT NULL CHECK (alg = 'Ed25519'),
  key_id            TEXT NOT NULL,
  key_fingerprint   TEXT NOT NULL,
  signature         TEXT NOT NULL,
  issued_at         TEXT NOT NULL
);

-- 决议 3：recovery_plans 表已删除。冻结计划是内容寻址文件
-- （路径 <store>/recovery_plans/<plan_hash>.json，文件名即 sha256），
-- DB 只保留 nodes.plan_id / nodes.plan_hash 与 audit_log 的冻结记录；计划正文不入库。

CREATE TABLE idempotency_keys (
  idem_key          TEXT PRIMARY KEY,
  request_hash      TEXT NOT NULL,
  task_id           TEXT,
  created_at        TEXT NOT NULL
);

CREATE TABLE ingestion_log (
  ingestion_id      TEXT PRIMARY KEY,
  evidence_id       TEXT NOT NULL,
  delivery_seq      INTEGER NOT NULL,
  received_at       TEXT NOT NULL
);
```

`【工程建议】` 索引：

| 索引 | 目的 |
|---|---|
| `idx_nodes_state(task_id, state)` | 就绪/失效查询 |
| `idx_evidence_task_seq(task_id, event_seq)` | 链校验与分页 |
| `idx_audit_task_time(task_id, created_at)` | 审计追溯 |
| `idx_reports_task(task_id)` | 报告查询 |
| `idx_invalidations_node(task_id, node_id)` | stale 判定 |
| `idx_invalidations_evidence(task_id, evidence_id)` | 证据是否 stale 的点查（Gate 必检项） |
| `idx_audit_plan(plan_hash)` | 计划冻结/守卫校验追溯 |
| `idx_audit_result(task_id, result, created_at)` | `DENIED` 迁移审计核查 |

## 2. 事务边界

| 操作 | 事务范围 | 必须原子 | 失败处理 |
|---|---|---|---|
| 状态迁移（成功） | `tasks`/`nodes` 状态更新 + `audit_log(result=OK)` 插入 | **是**（同事务） | 全回滚，不留半迁移 |
| 状态迁移（拒绝/失败） | 状态写回滚后，**独立事务**写 `audit_log(result=DENIED)` | 否（与状态解耦） | 见下“失败迁移审计”（决议 7） |
| 证据追加 | `evidence` 插入 + `event_seq` 分配 + `audit_log` | **是** | 回滚；不占用 `event_seq` |
| 证据失效 | `evidence_invalidations` 插入 + `audit_log(result=OK)` | **是** | 回滚；不得只写一半 |
| 图版本登记 | `graph_versions` 插入 + `tasks.graph_version` 更新 | **是** | 回滚 |
| 恢复计划冻结 | ① 内容寻址文件写入并 fsync；② `audit_log(result=OK, plan_id, plan_hash)`；③ 不迁移状态 | 文件与审计**不跨事务**，按 ①→② 顺序 | ② 失败：文件成孤儿（按 hash 可回收），不写节点计划字段，不认为已冻结 |
| 恢复计划执行（`INVALIDATED → READY`） | 守卫三项校验（只读）→ `nodes` 更新 + `audit_log(result=OK)` | **是** | 守卫任一不满足 → 独立事务写 `DENIED`，状态不变 |
| 报告签发 | `reports` 插入 | 单表 | 失败重试；`report_id` 唯一 |
| 凭证签发 | `certificates` 插入 + 报告存在性检查 | **是** | 失败不签发；`cert_id` 唯一 |
| 幂等创建 | `idempotency_keys` 插入 + `tasks` 插入 | **是** | 冲突返回 409 |

**失败迁移审计（决议 7）**：

1. 状态写失败 → 状态事务回滚 → 在**新事务**写 `audit_log(result=DENIED, error_code, previous_state, next_state, correlation_id, actor, reason_code, rule_version)`。不得把 `DENIED` 记录塞进已回滚的事务。
2. 测试必须证明该记录在回滚后仍存在（真实 SQLite 文件，不用 mock、不用内存库替身）。
3. 第二个事务也失败时：降级写**结构化 stderr**（单行 JSON，含同样字段 + `audit_write_failed=true`），并在测试报告中计为**测试缺口**；不得静默吞掉，也不得写成通过。
4. 降级路径本身要有测试：人为制造审计写失败，断言 stderr 行出现。

`【已关闭 · OQ-DB-1】` “失败迁移也写审计”与“同事务回滚”的冲突由决议 7 关闭：**成功同事务、失败独立事务**。上表按此执行，不再保留两种口径。

## 3. 表级写入权限

| 表 | StateMachine | DAG Builder | Collector | WP-R | Gate | Verifier | API |
|---|---|---|---|---|---|---|---|
| `tasks` | W | — | — | — | R | R | R |
| `nodes` | W | — | — | R | R | R | R |
| `graph_versions` | W（登记） | 计算 | — | R | R | R | R |
| `evidence` | — | — | W（E0–E2） | R | R | W（E3） | R |
| `evidence_invalidations` | W（经迁移） | — | — | 计算 | R | R | R |
| `audit_log` | W | — | — | — | R | R | R |
| `reports` | — | — | — | — | R | W | R |
| `certificates` | — | — | — | — | R | W | R |
| `idempotency_keys` | — | — | — | — | — | — | W |
| `ingestion_log` | — | — | W | — | — | — | R |

规则：

1. 任何组件不得跨表越权写。
2. `【工程建议】` 用 SQLite 触发器阻止对只追加表的 `UPDATE`/`DELETE`；触发器不是安全边界，但可防误操作。
3. 数据库文件权限限制为运行用户；Agent（T1）无连接权限。
4. **恢复计划不占表权限**（决议 3）：`WP-R` 只写内容寻址文件 + `audit_log`，并把 `plan_id`/`plan_hash` 交给 StateMachine 写入 `nodes`；不得新增 `recovery_plans` 表或把计划正文塞进 `audit_log` 的自由文本字段。
5. `evidence_invalidations` 只能追加（决议 4）；Gate 只读，不得因“证据已 stale”而删除或修改 `evidence` 行。

## 4. REST API

### 4.1 端点

【策划书】§6.4 / TABLE 28：

| 方法 | 路径 | 用途 | 错误语义 |
|---|---|---|---|
| POST | `/api/v1/tasks` | 创建任务；支持 `Idempotency-Key` | 422 Schema 错；409 幂等冲突 |
| GET | `/api/v1/tasks/{id}` | 任务详情、状态、资源摘要 | 404 不存在 |
| GET | `/api/v1/tasks/{id}/graph` | DAG、状态、指纹、DC/SPA | 409 图版本冲突 |
| GET | `/api/v1/tasks/{id}/evidence` | 证据分页与引用 | 403 无权限 |
| POST | `/api/v1/tasks/{id}/recover` | 触发恢复 | **T0 不注册该路由，访问返回 404**（决议 8）；T1 恢复：409 不可恢复；422 请求错误 |
| POST | `/api/v1/tasks/{id}/verify` | 执行 L1/L2/L3 | 429 预算不足；409 状态不允许 |
| GET | `/api/v1/tasks/{id}/report` | 报告、缺口、归因、签名 | 404 未生成 |
| GET | `/api/v1/tasks/{id}/certificate` | 仅 `VERIFIED` 返回凭证 | 409 非 `VERIFIED` |
| POST | `/api/v1/harness/events` | 接收标准化 Harness 事件 | 401/403 未认证；重复事件幂等 |
| GET | `/healthz`、`/readyz` | 健康检查 | 503 未就绪 |

T0 范围（`【工程建议】`）：

- 必须：`POST /tasks`、`GET /tasks/{id}`、`GET /tasks/{id}/graph`、`GET /tasks/{id}/evidence`、`POST /tasks/{id}/verify`、`GET /tasks/{id}/report`、`GET /tasks/{id}/certificate`、`/healthz`、`/readyz`。
- 不实现：`POST /harness/events`（T2）。
- **`POST /recover` 在 T0 不存在**（决议 8）：路由不注册，访问即 `404 Not Found`；不得返回 405/403，也不得用“空实现”接受请求。T0 的失效只由输入/图版本变化**内部触发**（Collector/StateMachine 路径），不接受外部恢复指令。负例测试必须断言 404 且无状态变化。

### 4.2 创建任务

【策划书】附录 E.1 / P0583–P0600：

```http
POST /api/v1/tasks
Idempotency-Key: demo-2026-001
Content-Type: application/json

{
  "schema_version": "1.0",
  "domain_pack": "tabular_ml@1.0.0",
  "goal": "Train and compare tabular classifiers on the bundled dataset.",
  "template_id": "classification_benchmark@1.0.0",
  "dataset_ref": {
    "uri": "local://datasets/synthetic_breast_cancer.csv",
    "sha256": "<64-hex>",
    "license": "CC-BY-4.0"
  },
  "parameters": {"target": "diagnosis", "seed": 42},
  "ruleset_hash": "<64-hex>",
  "limits": {"max_workers": 2, "wall_time_sec": 1800}
}
```

服务端生成 `task_id` 并在响应返回；请求体其余字段按 `TaskSpec`（`contracts/taskspec.schema.json`）校验。

响应 `201 Created`：

```json
{"task_id": "task_...", "state": "CREATED", "graph_version": 1}
```

**`dataset_ref` 形态（决议 9 / `ADR-002`）**：统一为对象 `{uri, sha256, license}`（附录 D.1）。附录 E.1 的字符串样例 `dataset://breast_cancer@sha256:<hash>` 偏离 D.1，本版不采用；收到字符串必须 `422` 并指明期望形态，**不得**自动解析：

```http
422 Unprocessable Entity
{"error_code": "SCHEMA_INVALID",
 "message": "dataset_ref must be an object with fields uri, sha256, license.",
 "field_path": "dataset_ref",
 "correlation_id": "req-..."}
```

`【已关闭 · OQ-API-2】` API 与 `TaskSpec` 的 `dataset_ref` 形态不一致由决议 9 关闭：API 接受对象形式，与 D.1 一致；偏离 E.1 已记 `ADR-002`，负例见 `contracts/examples/taskspec.negative.3.json`。

### 4.3 发起验证与读取凭证

【策划书】附录 E.2 / P0602–P0622：

```http
POST /api/v1/tasks/{task_id}/verify
{"mode": "full", "requested_checks": ["L1", "L2", "L3"]}
```

`200 OK`：

```json
{"report_id": "report_...", "final_state": "PARTIAL",
 "gaps": [{"code": "L3_SOURCE_NODE_NOT_REPLAYED", "node_id": "train_svm"}]}
```

`GET /certificate` 非 `VERIFIED`：

```http
409 Conflict
{"error_code": "CERTIFICATE_NOT_AVAILABLE", "message": "Only VERIFIED tasks can receive a completion certificate."}
```

`【OQ-API-3】` `mode` 的取值集合（示例仅 `full`）与 `requested_checks` 的合法值集合未定义。

### 4.4 错误码

【策划书】附录 E.3 / TABLE 69（原表 13 个错误码，全部保留）：

| 错误码 | HTTP | 含义 | 处理 |
|---|---|---|---|
| `SCHEMA_INVALID` | 422 | 请求字段/类型不合法 | 按字段错误修正 |
| `IDEMPOTENCY_CONFLICT` | 409 | 相同幂等键对应不同请求体 | 换新键或确认内容 |
| `STATE_TRANSITION_DENIED` | 409 | 状态迁移不符合状态机 | 查询当前状态，不绕过 |
| `TOOL_NOT_ALLOWLISTED` | 403 | 工具未注册或角色无权限 | 管理员审核工具契约 |
| `EVIDENCE_REFERENCE_NOT_FOUND` | 422 | 引用不存在 `evidence_id` | 丢弃引用并记录违规 |
| `REQUIRED_EVIDENCE_MISSING` | 409 | 必检证据缺失 | 补做真实执行/验证，不可伪造 |
| `RULESET_VERSION_MISMATCH` | 409 | 证据与当前规则版本不匹配 | 按当前规则重新验证 |
| `RESOURCE_BUDGET_EXCEEDED` | 429 | 资源/验证预算不足 | 排队、降并发或申请预算 |
| `RECOVERY_NOT_SAFE` | 409 | 恢复或剪枝条件不成立 | 保守重跑或人工升级 |
| `SIGNATURE_INVALID` | 422 | 签名或信任锚验证失败 | 拒绝凭证并保留审计 |
| `BUNDLE_TAMPERED` | 422 | 证据包哈希/证明不一致 | 拒绝导入 |
| `HARNESS_EVENT_DUPLICATE` | 200 | 重复事件已处理 | 幂等返回既有结果 |
| `HARNESS_EVENT_GAP` | 202 | 事件序列存在缺口 | 标记缺口并请求补发；不补造 |

`【工程建议】` 错误响应统一结构：

```json
{"error_code": "...", "message": "...", "field_path": "...", "correlation_id": "..."}
```

- `field_path` 仅 `SCHEMA_INVALID` 必填。
- 不返回堆栈、SQL、路径或密钥信息。
- `dataset_ref` 字符串形态、未知顶层字段、缺必填统一归 `SCHEMA_INVALID`（422），**不新增错误码**；附录 E.3 的 13 条错误码保持不变。
- `【OQ-API-4】` 错误响应体结构未在策划书定义，本条为工程建议。

### 4.5 幂等规则

【策划书】附录 E.4 / P0626–P0630：

| 对象 | 幂等边界 | 行为 |
|---|---|---|
| 任务创建 | `idempotency_key` + 规范化请求哈希 | 同键同体返回原任务；同键异体 409 |
| Harness 事件 | `source + session_id + event_id` | 重复返回既有结果（200）；乱序进缓冲区 |
| 执行 attempt | `attempt_id` 每次真实执行唯一 | 重试不得复用旧 `attempt_id` |
| 凭证签发 | `certificate_id` | 只签发一次 |
| 网络重试 | 仅幂等操作 | 非幂等操作不自动重试 |

`【工程建议】` 幂等键保留期与清理策略未定（`OQ-DB-2`）；T0 建议保留至任务完成后再归档。

### 4.6 认证与启动守卫（决议 8）

| 项 | T0 规则 |
|---|---|
| 绑定地址 | 默认且仅允许回环：`127.0.0.1`、`::1`、`localhost` |
| 认证 | 回环 + 单机场景**允许无认证**；该口径是**已接受风险**，不是“安全已实现” |
| 启动守卫 | 若配置的绑定地址非回环，且未配置访问 token（环境变量或受限配置文件），**拒绝启动**：不监听端口，退出码非 0，并写入一条启动审计（不含 token） |
| 失败信息 | 只说明“non-loopback bind requires token”，不回显配置值 |
| 负例测试 | 设 `bind=0.0.0.0` 且不配 token → 进程以非 0 退出、端口未监听、无任务创建；配置 token 后允许启动 |

边界：T0 不实现用户体系、TLS、反向代理鉴权；这些属 T1/T2，不得在 T0 文档或界面宣称“已安全加固”。`POST /recover` 的 404 与认证无关：即使未来加认证，T0 也不注册该路由。

`【已关闭 · OQ-021 / OQ-026】` T0 不开放 `POST /recover` 且仅在回环免认证，由决议 8 关闭；启动守卫与负例测试进入 ⑦ 测试矩阵。

## 5. 迁移与版本管理

| 项 | 规则 |
|---|---|
| Schema 变更 | 必须走迁移脚本；进入 ADR/版本管理（用户要求） |
| 迁移方向 | 只向前；回滚用备份恢复，不做破坏性降级 |
| 迁移记录 | `schema_migrations` 表（`【工程建议】`）记录版本、时间、哈希 |
| 契约版本 | 与 05 的 `schema_version` 同步；DB 版本独立编号；`tasks`/`nodes`/`reports`/`certificates` 均存契约版本列 |
| 契约文件 | `contracts/*.schema.json` 与本文 DDL 必须同步；改动后重跑 `scripts/validate_contracts.py`，任一 FAIL 不得合并 |
| 计划文件 | 内容寻址文件不参与 DB 迁移；更换存储根目录不影响 `plan_hash`（文件名仍是哈希） |
| 只追加表 | 迁移不得删除历史证据；需要改结构时新增列或新表 |
| 备份 | 迁移前必须备份 DB；备份不进入 Git |

## 6. 未决项

| 编号 | 问题 | 状态 | 去向 |
|---|---|---|---|
| `OQ-DB-1` | 失败迁移的审计写入与事务一致性 | **已关闭**（决议 7） | 成功同事务；失败独立事务写 `DENIED`；二次失败降级 stderr |
| `OQ-DB-2` | 幂等键保留期与清理 | 开放 | ⑦/⑧；T0 保留至任务完成后归档 |
| `OQ-DB-3` | 证据表是否需要按任务分表或分区（T0 单表） | 开放 | ⑦；T0 单表 + 索引 |
| `OQ-DB-4` | `skipped_nodes` 的存储形态（JSON 数组文本 vs 关联表） | 开放 | ⑦；T0 恒为空数组，用 JSON 文本 |
| `OQ-API-1` | T0 是否开放 `POST /recover` | **已关闭**（决议 8） | T0 不注册该路由，访问 404 |
| `OQ-API-2` | `dataset_ref` 在 API 与 TaskSpec 中的形态不一致 | **已关闭**（决议 9） | 统一对象形态；字符串 422；`ADR-002` |
| `OQ-API-3` | `mode` 与 `requested_checks` 取值集合 | 开放 | ⑤/⑥ 后续版本；T0 只支持 `full` + `L1/L2/L3` |
| `OQ-API-4` | 错误响应体统一结构 | 开放 | ⑥ 后续版本 |
| `OQ-API-5` | 分页参数与上限（`GET /evidence`） | 开放 | ⑥ 后续版本 |
| `OQ-API-6` | 认证方式（T0 单机是否免认证） | **已关闭**（决议 8） | 回环免认证 + 非回环缺 token 拒绝启动；已接受风险 |
| `OQ-API-7` | 恢复计划文件的存储根目录与保留期 | 开放 | ⑦ `WP-R`；根目录可配置，文件名恒为哈希，保留期随任务归档 |

## 7. 依据锚点

| 主题 | 锚点 |
|---|---|
| REST 端点与错误语义 | §6.4 / TABLE 28 |
| 创建任务样例 | 附录 E.1 / P0583–P0600 |
| 验证与凭证样例 | 附录 E.2 / P0602–P0622 |
| 错误码表 | 附录 E.3 / TABLE 69 |
| 幂等规则 | 附录 E.4 / P0626–P0630 |
| SQLite WAL | §15.4 / TABLE 58 |
| 证据只追加 | 附录 D.6 / P0578 |
| 状态迁移审计 | 附录 F.1 / P0637–P0640 |
| 失效/恢复控制事件 | 附录 F.1 / P0637–P0640；用户决议 4 |
| 用户决议 3/5/7/8/9 | 用户 2026-11-09 书面决议；ADR-002/004/005 |

## 8. 版本记录

| 版本 | 日期 | 变更 | 状态 |
|---|---|---|---|
| v0.1 | 2026-11-09 | 表清单、建议 DDL、事务边界、REST API、错误码、幂等 | 候选，已被 v0.2 取代 |
| v0.2 | 2026-11-09 | 删除 `recovery_plans` 表、计划改内容寻址文件（决议 3）；`evidence_invalidations` 强制引用 stale 证据（决议 4）；`nodes` 增 `plan_id`/`plan_hash`（决议 5）；`audit_log` 增 `plan_id`/`plan_hash`/`error_code`（决议 5/7）；失败迁移独立事务 `DENIED`（决议 7）；`POST /recover` 返回 404 + 启动守卫（决议 8）；`dataset_ref` 对象化 + 422（决议 9）；契约版本列（决议 2） | 候选，已被 v1.0 冻结取代 |
| v1.0 | 2026-11-10 | **G0 冻结定版**：补冻结日期、状态与被取代版本；基线引用升 05 v1.0、⑨ v1.0；表结构、事务边界、API、错误码、幂等规则按现值冻结。**语义未改** | **G0 冻结** |

---

**标记：本文件是 G0 文档 ⑥ v1.0（G0 冻结），不是 G0 门禁 PASS。** 表结构与错误响应体为冻结基线中的工程建议；G0 是否 PASS 由用户宣布；未建 `.venv`、未写业务代码。