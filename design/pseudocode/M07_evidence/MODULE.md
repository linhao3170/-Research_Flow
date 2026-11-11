# M07 · Evidence（P4）

> 阶段：P4「模板与证据链」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：Collector 单写者、Evidence Store 追加/查询/冲突保留、哈希链公式与断链检测、
> RFC 9162 Merkle 与 inclusion proof、事件缺口标记与 Gate 读取方式
> 不覆盖：Gate 判定（P5）、Ed25519 签名/信任锚（P6）、L3 重跑（P5）、Evidence Bundle 导出（P6/WP-12）
> 前置：P3 已验收；M01 错误码与 M02 evidence 表已冻结
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码

## 1. 目标

把“真实执行产生 E2 证据、证据可校验不可抵赖”闭合为五件可检查的东西：

1. **单写者**：只有 `collector.py` 能拿到写许可并打开写会话；E0/E1/E2 入队后由唯一
   writer 线程分配 `event_seq`、调链、落库；
2. **链**：`chain_hash` 覆盖除自身外全部字段，`prev_hash` 指向上一条链尾；
   读路径重算，断链/跳号/回退都能被发现；
3. **Merkle**：叶 `0x00`、内部 `0x01`、按 `event_seq` 定序；空树/单叶/奇数叶三边界明确；
4. **缺口**：`source_seq` 乱序有限缓冲；缺事件写 `evidence_gap`，不补造、不推断；
5. **可追责**：每次接受/拒绝都有记录；重复 event_id 不产生第二条逻辑记录；
   `payload_hash` 不符不入库；E0 带 `agent_claim` 标记且永不满足执行类必检。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `evidence/collector.py` | 投稿类型、E0 标记、单写队列、seq/链/落库、Gate 规则 helper | 768 | 完成（伪代码） |
| `evidence/store.py` | 写许可/写会话、追加 SQL、查询、ingestion_log、rejection 保留、payload sidecar | 676 | 完成（伪代码） |
| `evidence/chain.py` | chain_hash 前像/域分离、prev 传递、断链检测、追加守卫 | 420 | 完成（伪代码） |
| `evidence/merkle.py` | RFC 9162 MTH、tree_size、inclusion proof、验证、三边界 | 324 | 完成（伪代码） |
| `evidence/gaps.py` | 乱序缓冲、缺口记录、迟到补记、Gate 缺口视图、链缺口检测 | 550 | 完成（伪代码） |

行数为物理行数（含空行）。

均 ≤800 行，按 PHASE_RULES §5 第 1 档，无需函数索引。

## 3. 信任边界与权限矩阵

| 参与方 | 能做什么 | 不能做什么 | 本模块落点 |
|---|---|---|---|
| Agent/LLM | 提交 E0 声明（`AgentClaim`） | 写证据表、写状态、自报 level/producer、用 E0 满足执行类必检 | `EvidenceSubmission` 无 level/producer 字段；`assert_can_satisfy_execution_check` |
| Executor | 提交 `executor_launch` / `executor_process_exit` / `artifact_observed` 草稿 | 写状态、写证据、自报 event_seq/chain_hash、裁决 | M05 `EventDraft` 无链字段；`Collector.record()` 适配 |
| Collector | 接收 E0/E1/E2、判重、分配 seq、算链、写库、写拒绝日志 | 写任务/节点状态、写 audit_log、签名、接受 E3（P4） | 本模块；`assert_collector_boundary()` |
| Store | 提供写会话/只读查询 | 无许可写入、UPDATE/DELETE、purge | `WritePermit` token；`assert_store_boundary()` |
| Gate（P5） | 读证据/缺口/链，生成 coverage | 写证据、补造缺失、把 E0/E1 当执行证据 | `gate_view()` / `assert_can_satisfy_execution_check()` |
| Verifier（P6） | 产生 E3、验签、签报告 | 复用 Executor 状态、直接改证据 | P4 不接受 E3（OQ-P4-01） |

## 4. 单写者（`collector.py` + `store.py`）

### 4.1 代码结构

```
submit(EvidenceSubmission)
  → 有界 queue.Queue（满 → RESOURCE_BUDGET_EXCEEDED/queue）
  → 唯一 writer 线程 _writer_loop()
      → _process():
          1 等级由 kind 推导；E3 拒绝
          2 JCS(payload) → payload_hash；与自报值比对
          3 event_id：E0/E1 必填；E2 内容派生 "e2:<sha256>"
          4 event_id 级幂等/冲突
          5 E2 attempt 级唯一性（launch/exit/artifact refs）
          6 artifact_refs 存在性
          7 payload sidecar 内容寻址写
          8 with store.writer_session(permit):
                prev = last_record(task)
                seq = allocate_seq(task)
                chain_hash = hasher.hash(record)
                assert_appendable(prev, record, expected_seq=seq)
                insert(record)
                record_ingestion(event_id, evidence_id)
                commit
```

### 4.2 为什么只有 Collector 能写

- `store._COLLECTOR_TOKEN` 是模块私有对象；`_issue_collector_permit()` 只被
  `collector.py` 调用；`EvidenceStore.writer_session(permit)` 校验 token 身份。
- `INSERT INTO evidence` 只出现在 `store.EVIDENCE_APPEND_SQL`，只被
  `WriterSession.insert()` 使用；Store 没有公开 `execute/update/delete`。
- `assert_store_boundary()` 静态检查：
  1. `EvidenceStore` 不得有 `update/delete/purge/truncate`；
  2. `EVIDENCE_APPEND_SQL` 恰好一条 INSERT，且不含 UPDATE/DELETE；
  3. T0 保留策略必须是 `KEEP_ALL`。
- 负例 `NEG-M07-01..06` 逐条断言“非 Collector 写入被拒”。

### 4.3 event_seq 分配

- 单 writer 线程串行处理；并发投稿先在队列排队，不会抢到同一个 seq。
- `allocate_seq()` 在 `BEGIN IMMEDIATE` 事务内取 `MAX(event_seq)+1`；
  若 `COUNT(*) != MAX(event_seq)`（已有缺口）→ `EVENT_SEQ_GAP`，**拒绝在缺口后追加**。
- 事务失败回滚，seq 不被占用，不会留下空洞。
- 成功写入的 seq 连续 +1；读路径仍要校验（防外部改库/删行）。

### 4.4 重复与冲突

| 情况 | 处理 | 是否写 evidence |
|---|---|---|
| 同 event_id + 同 payload_hash | 幂等：返回既有 evidence_id；`ingestion_log.delivery_seq += 1` | 否（第二条逻辑记录不存在） |
| 同 event_id + 不同 payload_hash | `CONFLICT`：写 rejection 日志，返回 422 | 否 |
| E2 同 attempt/kind 不同内容 | `CONFLICT`：一个 attempt 只能一次 launch/exit | 否 |
| E2 artifact_observed 同 refs | `CONFLICT`：同组产物重复观测 | 否 |

## 5. E0/E1/E2 规则

### 5.1 E0 必须带 agent_claim

`EvidenceSubmission` 在 `kind=="agent_claim"` 时强制：
- `agent_claim` 非空，且含 `claim_id/agent_id/claim_type/claim_text/session_ref/asserted_at`；
- `artifact_refs` 必须为空（声明不得引用执行产物）；
- payload sidecar 里写入 `agent_claim` 对象与 `claim_origin="agent"`；
- 缺标记 → `SCHEMA_INVALID/AGENT_CLAIM_MISSING`，不写库。

level 由 kind 推导，投稿方不能自报；E0 的 `producer` 永远是 `collector`（记录者）。

### 5.2 E0/E1 永不满足执行类必检

```
EXECUTION_CRITICAL_LEVELS = ("E2", "E3")
can_satisfy_execution_check("E0") == False
can_satisfy_execution_check("E1") == False
can_satisfy_execution_check("E2") == True
assert_can_satisfy_execution_check(level, check_id)
    E0/E1 → CollectorError(REQUIRED_EVIDENCE_MISSING, 409)
```

P5 的 Gate 必须调用它；`agent_claim` / `tool_invocation` / `harness_trace` 只能辅助，
不能顶替 `dataset_hash_match` / `split_manifest_valid` / `metrics_recomputable` 等执行类必检。

### 5.3 E3 在 P4 不开放

`verifier_recheck` 在 P4 被拒绝（`SCHEMA_INVALID`，detail 指向 P6）。
原因：06 §3 的写者矩阵写的是 “Collector W(E0–E2)、Verifier W(E3)”，
而 P4 要求“Collector 是唯一能写证据表的模块”。两者需要用户在 P6 前裁决：
- 方案 A：Verifier 经 Collector 的 E3 入口提交（物理单写者，producer 仍 `verifier`）；
- 方案 B：Verifier 直接追加 E3（回到 06 §3 的双写者）。
P4 不擅自选；见 OQ-P4-01。

## 6. 哈希链（`chain.py`）

### 6.1 前像

```
projection = {schema_version, evidence_id, task_id, node_id, attempt_id,
              event_seq, level, kind, producer, timestamp, payload_hash,
              artifact_refs, prev_hash}
preimage  = b"RF-EVIDENCE-CHAIN\x00v1\x00" || JCS(projection)
chain_hash = hex(SHA-256(preimage))
```

- `chain_hash` 自身不进入前像。
- `artifact_refs` 缺失规范化为 `[]`；DB NULL 读回映射 `()`，前像稳定。
- `task_id` 在投影里，跨任务重放会变哈希。
- 域分离前缀与 Merkle `0x00/0x01`、签名载荷域都不同。
- 【OQ-P4-02】该前像/前缀是 P4 提案；P1 曾把 `chain_hash` 前像留给 WP-07，
  落地前需 ADR/WP-07 冻结，并用篡改负例锁定。

### 6.2 prev 传递

- 首条：`prev_hash` 只校 `[0-9a-f]{64}` 形态；**不比较全零**（OQ-CT-10 未决）。
  Collector 当前用 `"0"*64` 作为建议值，但它不是契约期望。
- 第二条起：`prev_hash == 上一条 chain_hash`；不满足 → `EVIDENCE_CHAIN_BROKEN`。
- `event_seq` 必须从 1 开始、严格 +1；跳号 → `EVENT_SEQ_GAP`，回退/重复 →
  `EVENT_SEQ_REGRESSION`。
- 读路径 `verify()` 按传入顺序检查，不排序；排序会掩盖存储顺序错误。

### 6.3 断链检测输出

`ChainVerification(ok, checked, first_seq, last_seq, broken_at_seq, reason,
expected, actual, detail)`；`reason` 固定为
`FIRST_SEQ_NOT_ONE` / `PREV_HASH_INVALID` / `SEQ_GAP` / `SEQ_REGRESSION` /
`PREV_HASH_MISMATCH` / `CHAIN_HASH_MISMATCH`。

**边界**：链能发现中间记录被改/删/重排、prev 被改、seq 跳号/回退；
**不能**发现“只改最后一条并把它自己的 chain_hash 一起重算”——没有后继 prev 会暴露它。
后者必须由报告 `evidence_root` / Merkle 根 / 外部锚定发现。本模块只声明“提高可发现性”，
不声明“绝对不可篡改”。

## 7. Merkle（`merkle.py`）

### 7.1 RFC 9162

```
MTH({})   = SHA-256()
MTH({d0}) = SHA-256(0x00 || d0)
MTH(D[n]) = SHA-256(0x01 || MTH(D[0:k]) || MTH(D[k:n]))
k = 小于 n 的最大 2 的幂
```

叶数据 = 证据 `chain_hash` 的 32 字节；叶顺序 = `event_seq` 升序，不排序、不去重。
`tree_size` = 叶数；证书 `tree_size ≥1`；空树 `root=SHA-256(b"")`。

### 7.2 三种边界（验收判据 1）

| 边界 | 返回值 | inclusion proof |
|---|---|---|
| 空树 `n=0` | `EMPTY_ROOT = SHA-256(b"")` | `inclusion_proof()` 抛 `EMPTY_TREE`；不返回空 proof 冒充通过 |
| 单叶 `n=1` | `leaf_hash = SHA-256(0x00 || leaf)` | 返回空元组；验证时 `sn=0` 直接比 root |
| 奇数叶 `n%2==1` | 按 `k` 分裂递归，右侧可为 1/3/… 叶 | 递归 PATH；**不复制末叶**；末叶哈希直接提升为父节点右子 |

`n=3`：`H(0x01, MTH(l0,l1), l2)`；`n=5`：`H(0x01, MTH(l0..l3), l4)`；
`n=7`：`H(0x01, MTH(l0..l3), MTH(l4..l6))`。复制末叶是 Bitcoin 变体，不是 RFC 9162。

### 7.3 inclusion proof

- 构造：`PATH(m, D[n])`；`m<k` 时递归左子树 + 右子树根；否则递归右子树 + 左子树根；
  返回顺序从叶到根。
- 验证：RFC 9162 §2.1.3.2 的 `fn/sn` 算法（不是“按 index 奇偶折叠”的完美树算法）。
- 失败原因：`EMPTY_TREE` / `INDEX_OUT_OF_RANGE` / `TREE_SIZE_MISMATCH` /
  `PROOF_TOO_LONG` / `PROOF_TOO_SHORT` / `ROOT_MISMATCH` / `LEAF_ORDER_INVALID`。
- 标准测试向量属 WP-11；P4 只钉算法与边界。

## 8. 缺口（`gaps.py`）

### 8.1 两种 seq

- `event_seq`：Collector 的链序号，成功写入连续 +1；读路径跳号 = 链缺口，不可推断。
- `source_seq`：Harness/Executor 自己的序号，可乱序/丢失；只在声明了它的流上缓冲。

### 8.2 缺口记录字段

`marker="evidence_gap", gap_id, task_id, node_id, attempt_id, stream,
first_missing_source_seq, last_missing_source_seq, missing_count, detection,
detected_at, status, fill_evidence_ids, note`

`detection`：`REORDER_TIMEOUT` / `WINDOW_OVERFLOW` / `CHAIN_SEQ_JUMP` / `ATTEMPT_INCOMPLETE`。
`missing_count` 是声明值，不是推断内容；`fill_evidence_ids` 只放真实 evidence_id。

### 8.3 乱序缓冲

- 每流一个 `ReorderBuffer`：`max_reorder=64`、`max_wait_sec=5`（非契约，OQ-P4-11）。
- `seq == expected`：立即发出并排空连续项；
- `seq < expected`：重复，幂等丢弃；
- `seq > expected`：入缓冲；窗口满/等待超时 → 只对**不在缓冲区**的序号按连续段声明缺口，
  再按序发出已到项；不造占位项。
- `close()`：缓冲中仍缺的序号声明缺口；迟到真实事件用 `fill_late()` 追加 `FILLED` 行，
  引用真实 evidence_id；历史 OPEN 行不删不改。
- `attempt_incomplete_gap()`：attempt 结束仍只有 launch、没有 exit → `ATTEMPT_INCOMPLETE`；
  `first/last_missing_source_seq=0` 是生命周期哨兵，`note` 写缺 `executor_process_exit`。
- **接线边界**：E2 不以 `source_seq` 缓冲，attempt 完整性由“launch 与 exit 是否都存在”
  判定；E1/Harness 的缓冲在 P10/T2 的 ingress 适配器接线，P4 只定义 `ReorderBuffer`
  与缺口日志，Collector 只提供 `gate_gap_view()` 读缺口。未接线的部分不得写成“已实现”。

### 8.4 Gate 读取方式（P5）

`gate_view(task_id, node_id, attempt_id, journal)` 返回 `GateGapView`：

- `open_gaps` 非空 → `blocked=True`；
- `blocks_execution_check(check_id)` 对任何 OPEN 缺口返回 True；
- `missing_count` 只汇总声明值；
- **缺就是缺**：不得用 0/默认值/相邻值/模型输出补齐；`evidence_gap` 行本身不能顶替任何
  required_check；`FILLED` 只表示“后来收到真实事件”，不抹掉历史。

## 9. Store 与保留（`store.py`）

### 9.1 表

| 表 | 写者 | 说明 |
|---|---|---|
| `evidence` | 仅 Collector（E0–E2，P4） | M02 已冻结；只 INSERT；本模块不建表 |
| `ingestion_log` | Collector | 06 §1.3 定义；`ingestion_id` = `<task_id>:<event_id>`（event_id 只保证任务内唯一，加 task 前缀防跨任务撞车）；`delivery_seq` 计数 |
| `evidence_ingest_rejections` | Collector | **M07 内部辅助表**（06 未列）；INVALID/CONFLICT 只追加 |

`evidence_ingest_rejections` 是 P4 新增建议，需 ADR/迁移批准（OQ-P4-05）；
在批准前不得声称“已在 06 契约内”。

### 9.2 保留策略

- T0 `KEEP_ALL`：`purge_after=NULL`，没有 `purge/delete/update` 方法；
- 删除证据或拒绝日志需要新 ADR + 审计迁移，不得由 Store 顺手做；
- 冲突记录不是证据：Gate 只能用它解释“为什么缺”，不能当“已发生/未发生”的证据。

### 9.3 payload sidecar

- DB 只存 `payload_hash`；payload 规范化字节写 `payloads/<hash>.json`，内容寻址、只增不删；
- 读取时重算哈希，不符 → `BUNDLE_TAMPERED`；
- 用途：L1 事后重算 `payload_hash`、证据包导出；不执行反序列化代码（只 `json.loads` 数据）。
- 数据最小化：payload 只放验证所需字段；E0 `claim_text` 上限 8192 字符，含敏感信息时
  必须先脱敏/截断再提交；禁止把凭据、令牌、私钥写入 payload/日志。【OQ-P4-09】

## 10. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| 1. Merkle 空树/单叶/奇数叶都有明确返回值 | `merkle._mth` 三个 early branch；`inclusion_proof` 空树抛错；本文 §7.2 | 已定义，未执行 |
| 2. Collector 是唯一能写证据表的模块 | `store._COLLECTOR_TOKEN` / `writer_session` / `EVIDENCE_APPEND_SQL`；`assert_store_boundary`；`NEG-M07-01..06` | 代码结构可核对，未执行 |
| 3. Splits 六字段且被 manifest 哈希覆盖 | M06 `splits.SPLIT_MANIFEST_FIELDS` / `compute_manifest_hash` | 见 M06 §4 |
| 4. 负例覆盖重复/乱序/篡改/缺事件补造/未登记数据集/越权写证据 | M06 `NEG-M06-01/35/47`；M07 `NEG-M07-01/07/09/13/15/18` | 判据已定义，未执行 |

## 11. OPEN QUESTIONS（新增，待用户裁决）

| 编号 | 问题 | P4 临时处理 |
|---|---|---|
| `OQ-P4-01` | E3 单写者 vs 06 §3 “Verifier W(E3)” | P4 拒绝 E3；P6 前裁决方案 A/B |
| `OQ-P4-02` | `chain_hash` 前像/域前缀未冻结 | P4 提案 `RF-EVIDENCE-CHAIN\x00v1\x00`；WP-07/ADR 冻结 |
| `OQ-P4-04` | `evidence_gaps` 表不在 06 §1.3 | 作为 M07 内部追加日志；需批准后进契约 |
| `OQ-P4-05` | `evidence_ingest_rejections` 表/保留期 | T0 KEEP_ALL；需 ADR/迁移批准 |
| `OQ-P4-06` | `ingestion_log.ingestion_id` 是否就是 event_id | P4 这样用；需在 06/契约注释确认 |
| `OQ-P4-09` | payload sidecar 目录/导出规则 | 内容寻址 `<hash>.json`；WP-07/WP-12 确认 |

## 12. 本阶段不做

- 不做 Gate 判定/coverage 矩阵（P5）。
- 不做 Ed25519/JCS 签名、信任锚、Evidence Bundle（P6/WP-11/WP-12）。
- 不做 L3 重跑/差异归因（P5）。
- 不接线 E1/Harness 的 `ReorderBuffer`（P10/T2）；P4 只定义缓冲器与缺口日志。
- 不做 API、任务创建、幂等中间件（P10）。
- 不建 `.venv`、不装依赖、不跑测试、不改看板。