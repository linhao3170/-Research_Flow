# M07 · NEGATIVE_TESTS — 负例判据（P4）

> 阶段：P4｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：M07 落地（WP-07）；Merkle 标准向量在 WP-11 接入
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P4 不得写成“已通过”**。
> 真实 SQLite、真实线程队列、真实 RFC 9162 向量；不得用 mock 证明并发/链/树正确。

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：异常类 + `error_code` + `reason` + `field_path`
   中至少三项与下表一致；只断言“抛异常了”判失败。
2. 链/序列类负例必须断言：**没有写入半条记录**（事务回滚后 evidence 行数不变），
   且失败后仍可继续写入（或按设计 fail-closed 停写）。
3. 幂等类负例必须断言：**evidence 行数不变**、`ingestion_log.delivery_seq` 增加、
   返回的 `evidence_id` 与首次相同。
4. Merkle 负例必须分别覆盖空树、单叶、奇数叶；奇数叶必须断言**没有复制末叶**
   （`n=3` 的根等于 `H(0x01, H(0x00,l0)||H(0x00,l1)), H(0x00,l2))` 的两层组合）。
5. 缺口负例必须断言：缺口行**没有** `evidence_id`/`value`/`inferred` 字段；
   `missing_count` 等于声明范围长度；Gate 视图 `blocked=True`。
6. 篡改类负例必须给出真实 diff（改前/改后字节或字段），并断言检测发生的具体字段。
7. 原因不符即失败；不得改期望值、放宽阈值、用“重试通过”覆盖失败记录。
8. 正例通过不构成完成证据；本表必须真实执行并逐条留下拒绝原因。

## A. 单写者与越权（`collector.py` / `store.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M07-01 | 非 Collector 写许可 | `WritePermit(writer="executor", token=<collector token>)` | `EvidenceStoreError`；`error_code=EVIDENCE_CHAIN_BROKEN`；`reason=WRITER_NOT_COLLECTOR`；`field_path=writer` | 本文 §4.2 |
| NEG-M07-02 | 伪造 token | `WritePermit(writer="collector", token=object())` | `EVIDENCE_CHAIN_BROKEN/WRITE_PERMIT_INVALID`；**打不开写会话** | 同上 |
| NEG-M07-03 | Store 无删除/更新入口 | `hasattr(EvidenceStore, "update"/"delete"/"purge")` | 全为 False；`assert_store_boundary()` 返回 `[]` | 同上 |
| NEG-M07-04 | 其他模块直接 INSERT | 静态扫描：只有 `store.EVIDENCE_APPEND_SQL` 含 `INSERT INTO evidence`；其他模块无 SQL | 除 `store.py` 外 0 处；`WriterSession` 只能由 token 打开 | 同上 |
| NEG-M07-05 | Collector 写状态/审计 | 静态：模块出现 `StateMachine`/`transition`/`audit_log`；或 Collector 调 `UPDATE tasks/nodes` | `assert_collector_boundary()` 非空；代码中 0 处 | AGENTS §4.4/§4.5 |
| NEG-M07-06 | E3 在 P4 被拒 | `EvidenceSubmission(kind="verifier_recheck", source="verifier", ...)` | `SCHEMA_INVALID`；detail 指向 P6/OQ-P4-01；evidence 行数不变 | 本文 §5.3 |
| NEG-M07-07 | 非 E0 带 agent_claim | `kind="tool_invocation"` + `AgentClaim` | `SCHEMA_INVALID/AGENT_CLAIM_ON_NON_E0`；`field_path=agent_claim` | 本文 §5.1 |
| NEG-M07-08 | E0 缺 agent_claim | `kind="agent_claim"` + `agent_claim=None` | `SCHEMA_INVALID/AGENT_CLAIM_MISSING`；不写库 | 同上 |
| NEG-M07-09 | E0 引用产物 | `kind="agent_claim"` + `artifact_refs=("artifact://m.pkl",)` | `SCHEMA_INVALID/E0_ARTIFACT_CLAIM`；声明不得当执行 | 同上 |
| NEG-M07-10 | E0 顶替执行类必检 | `assert_can_satisfy_execution_check("E0", check_id="metrics_recomputable")` | `CollectorError(REQUIRED_EVIDENCE_MISSING, 409)`；detail.min_level=E2 | 本文 §5.2 |
| NEG-M07-11 | E1 顶替执行类必检 | 同上，level=`E1` | 同 NEG-M07-10 | 同上 |
| NEG-M07-12 | 投稿自报 level/producer | 构造带 `level="E2"`/`producer="agent"` 的投稿 | `TypeError`（dataclass 无该字段）；不得“忽略后接受” | 本文 §5.1 |

## B. 重复与幂等（`collector.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M07-13 | 同 event_id 同 payload | 同一 E1 事件提交 2 次 | 第 2 次 `duplicate=True`；`evidence_id` 相同；evidence 行数仍 1；`delivery_seq=2` | 本文 §4.4 |
| NEG-M07-14 | 同 event_id 不同 payload | 同 event_id，改 payload 字段再提交 | `CONFLICT`；`SCHEMA_INVALID`；`field_path=event_id`；evidence 行数不变；rejection 行 +1 | 同上 |
| NEG-M07-15 | E2 launch 重复 | 同 attempt 提交第二次 `executor_launch`，payload 不同 | `CONFLICT`；`field_path=kind`；detail 含 `executor_launch`；evidence 行数不变 | 同上 |
| NEG-M07-16 | E2 exit 重复 | 同 attempt 提交第二次 `executor_process_exit` | 同 NEG-M07-15 | 同上 |
| NEG-M07-17 | artifact 重复观测 | 同 attempt 同组 `artifact_refs`，不同 event_id | `CONFLICT`；`field_path=artifact_refs`；不产生第二条 artifact_observed | 同上 |
| NEG-M07-18 | 并发投稿抢 seq | 50 个线程同时提交 50 个不同 event_id | 50 条 evidence；seq 恰为 1..50；无重复/空缺；`ChainVerifier.verify` ok | 本文 §4.3 |
| NEG-M07-19 | event_id 形态非法 | `event_id="a b"` / `""` / 129 字符 | `SCHEMA_INVALID/EVENT_ID_INVALID`；不写库 | `_EVENT_ID` |
| NEG-M07-20 | 重复 evidence_id | 桩：ID 工厂连续返回同一 `ev_` | `EVIDENCE_CHAIN_BROKEN` 或 `EVENT_SEQ_REGRESSION/EVIDENCE_ID_REUSED`；不产生第二条 | `WriterSession.insert` |

## C. 序列与链（`chain.py` / `store.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M07-21 | 首条 seq 不是 1 | `assert_appendable(None, record(event_seq=2))` | `EVENT_SEQ_GAP/FIRST_SEQ_NOT_ONE`；detail.expected=1 | 本文 §6.2 |
| NEG-M07-22 | seq 跳号 | prev.seq=3，new.seq=5 | `EVENT_SEQ_GAP/SEQ_GAP`；detail.missing=1；不写库 | 同上 |
| NEG-M07-23 | seq 回退 | prev.seq=3，new.seq=2 | `EVENT_SEQ_REGRESSION/SEQ_REGRESSION` | 同上 |
| NEG-M07-24 | seq 重复 | prev.seq=3，new.seq=3 | `EVENT_SEQ_REGRESSION/SEQ_DUPLICATED` | 同上 |
| NEG-M07-25 | 缺口后追加 | 手工删掉 seq=2 的行，再 `allocate_seq()` | `EVENT_SEQ_GAP/SEQ_GAP_BEFORE_APPEND`；detail.count/max/missing 正确；不追加 | 本文 §4.3 |
| NEG-M07-26 | 唯一约束冲突 | 直接 `INSERT` 同 (task_id,event_seq) | `EVENT_SEQ_REGRESSION/SEQ_DUPLICATED`；事务回滚 | `WriterSession.insert` |
| NEG-M07-27 | prev_hash 不符 | 改 new.prev_hash 一位 | `EVIDENCE_CHAIN_BROKEN/PREV_HASH_MISMATCH`；expected 为 prev.chain_hash | 本文 §6.2 |
| NEG-M07-28 | 改记录不重算 | 改 DB 的 payload_hash，保留 chain_hash | `ChainVerifier` → `CHAIN_HASH_MISMATCH`；broken_at_seq 精确 | 本文 §6.3 |
| NEG-M07-29 | 改记录并重算自身 | 改 record 并重算 chain_hash，但下一条 prev 未改 | 下一条 `PREV_HASH_MISMATCH`；链校验失败 | 策划书 §7.3 |
| NEG-M07-29a | 链尾篡改 + 重算 | 只改最后一条并重算其 chain_hash | 链校验可能 `ok=True`；**必须**由 `evidence_root`/Merkle 根/外部锚定发现：根哈希不符 → `BUNDLE_TAMPERED` | 本文 §6.3 边界 |
| NEG-M07-30 | 记录被重排 | 交换两条记录的存储顺序 | `SEQ_REGRESSION`；不得“排序后通过” | 本文 §6.3 |
| NEG-M07-31 | 跨任务接链 | new.task_id 与 prev 不同 | `EVIDENCE_CHAIN_BROKEN/TASK_MISMATCH`；field_path=task_id | 本文 §6.1 |
| NEG-M07-32 | 首条 prev 非全零 | 首条 `prev_hash="a"*64` | **接受**（只校形态；OQ-CT-10）；不得因非零拒绝 | 本文 §6.2 |
| NEG-M07-33 | 域分离缺失 | 去掉 `CHAIN_DOMAIN` 重算 | 哈希与带域值不同；`CHAIN_HASH_MISMATCH`；不得把同一 32 字节解释成 Merkle 节点 | 本文 §6.1 |

## D. Merkle（`merkle.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M07-34 | 空树 | `MerkleTree([])` | `root == SHA-256(b"")`；`tree_size=0`；`inclusion_proof(0)` 抛 `EMPTY_TREE` | 本文 §7.2 |
| NEG-M07-35 | 单叶 | `MerkleTree([h0])` | `root == SHA-256(0x00||h0)`；proof `audit_path=()`；verify ok | 同上 |
| NEG-M07-36 | 奇数叶 3 | `MerkleTree([h0,h1,h2])` | `root == H(0x01, H(0x00||h0,0x00||h1 的节点), 0x00||h2)`；**没有复制 h2** | 同上 |
| NEG-M07-37 | 奇数叶 5/7 | `n=5`、`n=7` 全索引 proof | 每个 proof 都 verify ok；根与递归定义一致 | 同上 |
| NEG-M07-38 | proof 兄弟哈希被改 | 改 `audit_path[0]` 一位 | `ROOT_MISMATCH`；computed_root 不等于 root | 本文 §7.3 |
| NEG-M07-39 | leaf_index 越界 | `leaf_index=tree_size` | `INDEX_OUT_OF_RANGE`；不返回 ok | 同上 |
| NEG-M07-40 | tree_size 不符 | proof.tree_size=4，树实际 3 叶 | `TREE_SIZE_MISMATCH`；不得按较小树“适配” | 同上 |
| NEG-M07-41 | 叶顺序错 | `from_records([seq2, seq1])` | `LEAF_ORDER_INVALID`；不得排序后通过 | 本文 §7.1 |
| NEG-M07-42 | proof 太短 | 多叶树传 `audit_path=()` | `PROOF_TOO_SHORT`；computed_root 给出 | 本文 §7.3 |
| NEG-M07-43 | proof 太长 | 单叶树传 1 个 sibling | `PROOF_TOO_LONG`；不得忽略多余项 | 同上 |
| NEG-M07-44 | 重复叶被去重 | 两片相同 chain_hash 的叶 | `tree_size=2`；根为两叶节点；**不得**去重成单叶 | RFC 9162 |
| NEG-M07-45 | 空 proof 冒充通过 | 空树 `verify(proof=None/空)` | `EMPTY_TREE`；不得 `ok=True` | 本文 §7.2 |

## E. 缺口与“不补造”（`gaps.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M07-46 | 乱序超时 | 先交 seq=2，等超过 `max_wait_sec`，再 `flush_expired()` | 生成 `OPEN` gap（first=1,last=1,missing_count=1,detection=REORDER_TIMEOUT）；seq=2 正常发出；**无占位项** | 本文 §8.3 |
| NEG-M07-47 | 窗口溢出 | buffer 满，提交一条跳号 | 只为“不在缓冲区”的序号声明 gap；已缓冲项不算缺失；随后按序发出 | 同上 |
| NEG-M07-48 | 迟到事件补记 | gap 覆盖 1..2，真实 seq=1 到达 | `append_fill(gap_id, evidence_ids=[ev_...])`；`FILLED` 行；历史 OPEN 行仍在；缺口行无 value | 本文 §8.3 |
| NEG-M07-49 | 缺事件不补造 | 缺口保持 OPEN，Gate 读取 | `GateGapView.blocked=True`；`blocks_execution_check()` True；`missing_count` 只汇总声明值 | 本文 §8.4 |
| NEG-M07-50 | 缺口记录带推断值 | 往 `EvidenceGap` 加 `value`/`evidence_id`/`inferred` | `TypeError`/静态检查非空；不得入库 | 本文 §8.2 |
| NEG-M07-51 | 链缺口 | `detect_chain_seq_gap([1,2,4])` | `ok=False`；`first_missing=3,last_missing=3,missing_count=1,reason=CHAIN_SEQ_JUMP`；**不可填** | 本文 §8.1 |
| NEG-M07-52 | 关闭时有洞 | buffer `{5,7}`，expected=4，`close()` | 只声明 4 和 6 两段（不含已到的 5/7）；发出 5/7 | 本文 §8.3 |
| NEG-M07-53 | 负/非法 source_seq | `source_seq=-1` / `True` | `ValueError`；不静默丢 | `ReorderBuffer.submit` |
| NEG-M07-54 | 缺口当证据 | 用 `evidence_gap` 行去满足 `metrics_recomputable` | Gate 必须返回 GAP；不得把 gap 行计入 evidence/coverage | 本文 §8.4 |

## F. payload、产物与资源（`collector.py` / `store.py`）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M07-55 | payload_hash 不符 | 自报 hash 与 JCS(payload) 不同 | `SCHEMA_INVALID`；`field_path=payload_hash`；evidence 行数不变 | 本文 §4.1 |
| NEG-M07-56 | payload 超限 | payload > `max_payload_bytes` | `RESOURCE_BUDGET_EXCEEDED`；`field_path=payload`；不写库 | 同上 |
| NEG-M07-57 | artifact 引用不存在 | `artifact_refs=("artifact://ghost",)` | `EVIDENCE_REFERENCE_NOT_FOUND`；`field_path=artifact_refs`；不写库 | 05 §4.1 |
| NEG-M07-58 | resolver 缺失 | 有 artifact_refs 但未注入 resolver | `EVIDENCE_CHAIN_BROKEN`；**不猜测存在**；不写库 | 同上 |
| NEG-M07-59 | 队列满 | 阻塞 writer，灌满队列后再提交 | `RESOURCE_BUDGET_EXCEEDED`；detail.limit_kind=queue；不静默丢 | 本文 §4.1 |
| NEG-M07-60 | Collector 未启动 | `Collector.submit()` 在 `start()` 前 | `EVIDENCE_CHAIN_BROKEN/COLLECTOR_NOT_RUNNING`；不排队 | 同上 |
| NEG-M07-61 | 提交超时 | writer 阻塞超过 timeout | `RESOURCE_BUDGET_EXCEEDED/COLLECTOR_TIMEOUT`；不返回假 receipt | 同上 |
| NEG-M07-62 | sidecar 被改 | 改 `payloads/<hash>.json` 一个字节后 `get()` | `BUNDLE_TAMPERED/PAYLOAD_HASH_MISMATCH`；不返回内容 | 本文 §9.3 |
| NEG-M07-63 | 冲突日志被删/改 | 对 `evidence_ingest_rejections` 执行 UPDATE/DELETE | SQLite trigger `APPEND_ONLY_TABLE` 拒绝；无 purge API | 本文 §9.2 |
| NEG-M07-64 | 缺事件时用推断值补齐 | 代码出现 `placeholder/synthetic/backfill` | `assert_gap_boundary()` 非空；Gate 不使用推断值 | 本文 §8.4 |

## G. 误拒守卫（防止“过度收紧”）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M07-01 | 合法 E2 被接受 | `executor_launch`（无 agent_claim） | receipt.seq=1；evidence 行 1；chain verify ok | 本文 §5 |
| GUARD-M07-02 | 合法 E0 被接受 | `agent_claim` + `AgentClaim` | receipt.level=E0；payload 含 `claim_origin="agent"`；**不推动状态** | 本文 §5.1 |
| GUARD-M07-03 | 首条 prev 非零不误拒 | `prev_hash="a"*64` | 接受；`verify()` ok（OQ-CT-10） | 本文 §6.2 |
| GUARD-M07-04 | 单叶 Merkle 不误拒 | 1 叶、proof 空 | verify ok；tree_size=1 | 本文 §7.2 |
| GUARD-M07-05 | 奇数叶 proof 全通过 | `n=3/5/7` 所有索引 | 全部 verify ok | 同上 |
| GUARD-M07-06 | 重复投递不误判冲突 | 同 event_id 同 payload | `duplicate=True`；不写 rejection | 本文 §4.4 |
| GUARD-M07-07 | E2 可满足执行类必检 | `assert_can_satisfy_execution_check("E2", check_id="x")` | 不抛；返回 True | 本文 §5.2 |

## H. 执行记录模板（落地阶段填写，P4 留空）

| ID | 命令 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|
| NEG-M07-01 | （待执行） | — | — | — | 未执行 |
| NEG-M07-14 | （待执行） | — | — | — | 未执行 |
| NEG-M07-25 | （待执行） | — | — | — | 未执行 |
| NEG-M07-36 | （待执行） | — | — | — | 未执行 |
| NEG-M07-46 | （待执行） | — | — | — | 未执行 |