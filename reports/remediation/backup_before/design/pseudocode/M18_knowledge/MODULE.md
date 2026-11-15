# M18 · 知识库与 FOL 三层环（P8）

> 阶段：P8「六角色与知识库」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：KnowledgeUnit 15 字段与三态、五类差异字段、版本治理与冲突升级、FTS5/BM25 检索与过滤、过期降权、检索 E1、五种绑定、L-A/L-B/L-C、R1–R3 对照
> 不覆盖：SQLite/FTS5 建表与迁移（WP 落地）、HTTP、知识写入 UI、真实基准运行（RF-Bench 属 T1/G5）
> 前置：P1–P7 已验收；**T0 尚未验收**（G1–G7 `NOT_STARTED`）
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建库、不跑检索、不改看板、不写业务代码
> FR 归属：`FR-013`（知识单元版本治理与检索）、`FR-014`（FOL 三层反馈环）均为 **T1**；本阶段不宣称 G5 已通过

## 0. T0 未验收时的交付口径（先读）

1. **M18 在 T0 不装配**：`KnowledgeRetrieval(tier="T0")` 直接抛 `RetrievalTierRefused`
   （`FEATURE_FLAG_NOT_PERMITTED` / `KNOWLEDGE_RETRIEVAL_REQUIRES_T1`）。T0 没有任何调用方。
2. **写入只允许人工**：`KnowledgeUnit.created_by` 不得是六角色名或 `agent:` 前缀；
   `reviewed_by` 为空即拒绝；`KnowledgeLoop` 必须带 `HumanApproval`。Agent/模型没有知识写路径。
3. **检索必须留 E1**：`RetrievalEvidencePort` 不可用或提交失败 → `RetrievalEvidenceUnavailable`，
   **不返回结果**（fail-closed）。E1 只由 Collector 写，本模块不碰证据库。
4. **指标只定义口径**：Recall@k / MRR / 版本命中率、R1–R3 差值、命中率等都不填数值；
   任何“实测结果”必须来自真实运行并留日志（G5 前不写结论）。
5. **没有接入 `researchflow/`**：无建表、无 FTS 索引、无导入器、无 UI。

## 1. 目标

把「知识只回答怎么做，不参与做没做的判定」落成五段：

1. **字段可对表**：15 个字段与 §11.2 逐字一致；五类差异字段与 §11.1 一致；
2. **只增不改**：修订 = 新版本 + 旧版本 `DEPRECATED`；没有原地覆盖入口；`content_hash` 覆盖内容，不覆盖治理字段；
3. **冲突不选边**：同 scope 字段冲突 → `CONFLICTED` + 人工升级；模型裁决在构造期就被拒；
4. **检索可追溯**：ktype/scope 过滤下推、过期降权标 `stale_kb`、命中理由结构化、检索写 E1（且只写 E1）；
5. **绑定不越权**：五种绑定只注入“建议”，显式规格永远赢；知识不得绑定必检项、规则哈希、限额与状态。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `knowledge/unit.py` | 15 字段、五类 payload、三态迁移、内容哈希、冲突检测、人工裁决 | 799 | 完成（伪代码） |
| `knowledge/retrieval.py` | 查询分词、FTS 构造、过滤、过期降权、去重、E1 事件 | 560 | 完成（伪代码） |
| `knowledge/binding.py` | 五种绑定、注入/覆盖/可测指标、基准 Recall@k/MRR | 631 | 完成（伪代码） |
| `knowledge/feedback.py` | L-A/L-B/L-C、方向通道、策略版本/回滚、R1–R3 | 742 | 完成（伪代码） |

计数口径：物理行数（`text.count("\n") + 1`）。四个文件均 ≤ 800，按 PHASE_RULES §5 第 1 档，
不要求完整函数索引；关键符号见各节。

### 2.1 关键符号

| 文件 | 公开符号（节选） |
|---|---|
| `unit.py` | `KType`、`KnowledgeStatus`、`KnowledgeUnit`、`SpecPayload`、`ToolPayload`、`DatasetPayload`、`FaultCasePayload`、`PaperDocPayload`、`compute_content_hash`、`detect_conflict`、`HumanResolution`、`assert_field_parity`、`assert_append_only` |
| `retrieval.py` | `RetrievalQuery`、`RetrievalHit`、`HitReason`、`ConflictNotice`、`KnowledgeRetrieval`、`tokenize_query`、`build_fts_query`、`RetrievalEvidenceEvent`、`assert_only_e1` |
| `binding.py` | `BindingKind`、`ToolBinding`、`TemplateBinding`、`DatasetBinding`、`AgentBinding`、`BenchmarkBinding`、`Injection`、`Override`、`tool_metrics`/`template_metrics`/`dataset_metrics`/`agent_metrics` |
| `feedback.py` | `LoopId`、`Arm`、`LoopToggles`、`FeedbackBus`、`UpwardRecord`、`DownwardParameter`、`KnowledgeLoop`、`PolicyLoop`、`ArmMetrics`、`compare_arms` |

## 3. 字段与五类差异（§11.1 / §11.2）

### 3.1 KnowledgeUnit 15 字段

| # | 字段 | 约束 | 来源 |
|---:|---|---|---|
| 1 | `kid` | 非空、无空白；形态未冻结（见 `OQ-P8-11`） | §11.2 |
| 2 | `ktype` | `SPEC`/`TOOL`/`DATASET`/`FAULT_CASE`/`PAPER_DOC` | §11.1 |
| 3 | `scope` | `kind:name[@version]`，小写前缀；禁止 `*`、空白、`..` | §11.4（同 scope 冲突） |
| 4 | `version` | 整数 ≥1；同一 kid 单调递增 | §11.4「修订产生新版本」 |
| 5 | `source_url` | `https|http|local|file|doi`；用于溯源，不在运行时抓取 | §11.2 |
| 6 | `license` | 非空；`UNKNOWN/TBD/NONE` 拒绝 | FR-013「来源/许可可追溯」 |
| 7 | `effective_at` | UTC RFC3339 | §11.2 |
| 8 | `expires_at` | UTC，必须晚于生效 | §11.2 |
| 9 | `structured` | 五类 payload 之一，类型必须与 ktype 匹配 | §11.2 |
| 10 | `text` | 非空、≤20000 字符；检索与阅读入口 | §11.4 |
| 11 | `content_hash` | 内容寻址；构造期必须与重算一致 | §11.2；§11.4 |
| 12 | `supersedes` | 旧版本 `content_hash` 或 `null`；不得指向自身 | §11.4（方向见 `OQ-P8-11`） |
| 13 | `status` | `ACTIVE`/`DEPRECATED`/`CONFLICTED` | §11.2 |
| 14 | `created_by` | 人类/导入器；Agent 名或 `agent:` 前缀拒绝 | §11.4 L-B「人工确认」 |
| 15 | `reviewed_by` | 必填；未复核不得入库 | §11.4 L-B |

字段名与顺序由 `assert_field_parity()` 对表；`EXPECTED_FIELDS` 是唯一期望源。

### 3.2 五类差异字段

| ktype | payload | 差异字段 | 与记录级字段的一致性 |
|---|---|---|---|
| `SPEC` | `SpecPayload` | `seed_required`、`test_ratio`、`metric_defs` | `metric_defs[]` 的 `source_split` 必须显式（防训练集冒充测试集） |
| `TOOL` | `ToolPayload` | `tool_name`、`params_schema`、`timeout_sec`、`known_errors` | 参数 Schema 是知识表达，**不替代** M05 注册表 |
| `DATASET` | `DatasetPayload` | `dataset_hash`、`target`、`dtypes`、`license` | `license` 必须等于记录级 `license` |
| `FAULT_CASE` | `FaultCasePayload` | `signature`、`root_cause`、`fix`、`preconditions` | 必须有人工确认与失败证据（L-B） |
| `PAPER_DOC` | `PaperDocPayload` | `title`、`document_version`、`section`、`url`、`license` | `url == source_url`、`license == license`；`document_version` ≠ revision `version` |

## 4. 三态治理与“只增不改”

### 4.1 状态迁移（`can_transition`）

| 当前 | 允许到 | 触发 | 禁止 |
|---|---|---|---|
| `ACTIVE` | `DEPRECATED` | 出现新版本并指向它 | 直接删除/覆盖内容 |
| `ACTIVE` | `CONFLICTED` | 同 scope 字段冲突 | 模型自选版本 |
| `CONFLICTED` | `DEPRECATED` | 人工裁决淘汰 | 自动淘汰 |
| `CONFLICTED` | `ACTIVE` | 人工否决冲突（`REJECT_CONFLICT_KEEP_ALL`），内容不变 | 模型否决 |
| `DEPRECATED` | — | 终态 | 复活；复活必须发新版本 |

### 4.2 版本与哈希

- `new_version()`：`version+1`、`supersedes=旧 content_hash`、状态 `ACTIVE`；
  与旧内容完全相同 → `DUPLICATE_REVISION` 拒绝（“改个版本号”不是修订）。
- `compute_content_hash` 覆盖 `kid/ktype/scope/structured/text/source_url/license/effective_at/expires_at`，
  **不覆盖** `status/created_by/reviewed_by/supersedes`；治理字段变化不改变内容身份。
- 哈希规范化是本地确定性 JSON（`[P8 约定]`），**不是**签名载荷；不得与 JCS 签名语义混用
  （`CONTENT_HASH_NOTE`）。

### 4.3 原地覆盖的拒绝

`assert_append_only()` 扫描 `KnowledgeUnit` 的公开面：只允许
`create/new_version/deprecate/mark_conflicted`；出现 `set_*/update_*/overwrite*/replace_*` 即失败。
`deprecate()` 只改 `status`，不改内容；`content_hash` 不变，可被审计核对。

## 5. 冲突：检测 → 标记 → 人工裁决（§11.4）

1. `detect_conflict(left, right)`：同 `ktype`+`scope`、双方 `ACTIVE`、`structured` 逐字段比较；
   冲突键按字典序输出，结果可复现；不同 scope/ktype 不算冲突。
2. 冲突记录 `ConflictRecord` 只列候选（`kid@version#hash`），**没有 winner 字段**；
   `requires_human=True` 在构造期强制。
3. `HumanResolution`：
   - `ResolutionSource.MODEL` → 构造期抛 `KNOWLEDGE_MODEL_CANNOT_RESOLVE_CONFLICT`；
   - 必须带 `approved_by` + `approval_id`；
   - `KEEP_ONE_DEPRECATE_OTHERS` 必须给 `winner`；`REJECT_CONFLICT_KEEP_ALL` 必须不带 winner。
4. 冲突知识在检索中只返回 `ConflictNotice`，`RetrievalHit` 构造期禁止 `CONFLICTED + injectable`；
   gateway 侧看到冲突必须 `ESCALATE`，不得在 prompt 里“让模型选一个”。

## 6. 检索（§11.4）

### 6.1 流程

1. `RetrievalQuery` 校验（ktype 非空、limit∈[1,20]、scope 形态）；
2. `tokenize_query`：ASCII 词 + 中文 bigram；操作符词（and/or/not/near）剔除；
3. `build_fts_query`：每个词加双引号、词间 `OR`；`NEAR/*/括号/冒号` 无法进入 MATCH；
4. `KnowledgeReaderPort.search`：ktype/scope/deprecated 作为**入参**下推（不在 Python 后过滤）；
   scope 前缀用范围查询（`>= prefix AND < prefix+'\uffff'`），避免 LIKE 注入；
5. 每行判定：非最新版本跳过；`CONFLICTED` → 通知；`DEPRECATED` → 默认丢弃；
   过期 → 降权 ×0.5 + `stale_kb=True` + `requires_confirmation=True`；
6. 排序：`score` 降序 → `kid` 升序 → `version` 降序；截断到 limit；
7. **写 E1**：`RetrievalEvidenceEvent(level="E1", kind="tool_invocation")` 交 Collector；
   失败 → `RetrievalEvidenceUnavailable`，不返回结果。

### 6.2 返回契约

`RetrievalResult` 含：`hits`（kid/version/content_hash/source_url/ktype/scope/text/score/stale/requires_confirmation/hit_reason）、
`stale_hits`、`conflicts`、`query_hash`、`filters`、`dropped_deprecated`、`dropped_stale`、`evidence_event_id`。
`HitReason` 给出匹配词、生效过滤、BM25 原值、名次、是否降权——**不只给一个分数**。

### 6.3 已知边界

- 中文 bigram 与 FTS5 tokenizer 必须同口径，尚未在真实 SQLite 上验证（`OQ-P8-10`）；
- 检索只做词法匹配，不做语义相似；`Recall@k` 的“k”与排序稳定性需基准任务验证；
- `stale` 降权系数 0.5 是提议值（`OQ-P8-09` 同类装配常量），不是契约。

## 7. 五种绑定（§11.3）

| 绑定 | 注入时机 | 注入什么 | 可测指标 | 永不注入 |
|---|---|---|---|---|
| 工具 | 调用前 | 参数约束、已知错误、超时参考 | `knowledge_hit_rate`、`invalid_param_rate` | 工具白名单、执行权限、超时真值（注册表赢） |
| 模板 | DAG 构建时 | 默认 seed/test_ratio/metric_defs | `spec_missing_rate`、`default_value_correctness` | `required_checks`、`ruleset_hash`、`limits` |
| 数据集 | 画像前 | 字段解释、target/dtypes、质量规则 | `field_recognition_accuracy`、`profile_coverage` | 原始数据、许可（冲突即拒） |
| Agent | 组上下文时 | 按角色允许的 ktype 过滤 | `irrelevant_knowledge_ratio`（目标 0）、`context_token_cost` | 越界 ktype、其他角色知识 |
| 基准任务 | 评分时 | `expected_kb_hit` 对照 | `Recall@k`、`MRR`、`version_hit_rate` | 任务判定、Gate/Verifier 结果 |

三条硬规则：

1. **显式赢**：`Override.winner` 只能是 `EXPLICIT_CONTRACT_OR_SPEC`；`InjectionItem.authoritative` 恒 `False`，
   构造为 True 即抛 `KNOWLEDGE_CANNOT_BE_AUTHORITATIVE`；
2. **不可变目标**：`Injection.payload` 的键与 `IMMUTABLE_KNOWLEDGE_TARGETS` 有交集即拒绝
   （必检/规则哈希/限额/状态/证据/报告/证书/签名/私钥）；
3. **过期需确认**：stale 命中在没有 `ConfirmationPort` 或确认失败时**不注入**；
   不得用硬编码默认值顶替，也不得“先用了再补确认”。

## 8. FOL 三层环与 R1–R3（§11.5 / §11.6）

### 8.1 三个环

| 环 | 周期 | 输入 → 动作 | 指标/证伪 | 关闭后 |
|---|---|---|---|---|
| L-A 执行环 | 秒—分钟 | 失败/缺口 → 错误分类、有限重试、定向恢复 | 恢复率、尝试次数、重跑数 | 观察退化（R1 基线） |
| L-B 知识环 | 分钟—天 | 人工确认的故障案例 → 入库 → 下次注入 | 知识命中、同类错误复发、R1/R2 差异 | R1 与 R2 的差异即知识环贡献 |
| L-C 策略环 | 周/批次 | 历史回放/网格 → 候选 → 人工批准 → 版本化参数 | 尝试次数、预算利用率、R2/R3 差异 | R2 与 R3 的差异即策略环贡献 |

### 8.2 方向（写死）

- 向上：`UpwardRecord`，只允许 L-A/L-B；`L-C` 发向上记录即 `UPWARD_FROM_POLICY_LOOP`。
- 向下：`DownwardParameter`，只允许 L-C 的**已批准**版本；`FeedbackBus` 未登记该 `policy_hash`
  → `POLICY_VERSION_NOT_APPROVED`；`PolicyVersion.approval_id` 与 `HumanApproval` 不符 → 拒绝。
- 知识注入不是参数通道：它在读取时发生，不进入 `DownwardParameter`；避免“知识绕过批准改执行参数”。

### 8.3 R1–R3

| 臂 | L-A | L-B | L-C | 说明 |
|---|---|---|---|---|
| R1 | 开 | 关 | 关 | 仅执行环基线 |
| R2 | 开 | 开 | 关 | +知识环 |
| R3 | 开 | 开 | 开 | +策略环 |

- `assert_arm_matrix()` 校验 R1 ⊂ R2 ⊂ R3 且 L-A 恒开；
- `ArmMetrics` 的 `sample_size` 必须显式；重复运行**不得**当独立样本；
- `compare_arms` 输出 `first_pass_delta_pp` 等差值，并带 `negative` 标记（退化必须保留）；
- `TARGET_IMPROVEMENT_PP=15.0` 是**目标**；`PolicyCandidate` 必须带 `negative_results`，
  空即 `NEGATIVE_RESULTS_HIDDEN`；`PolicyLoop.approve` 对 `measured=False` 抛 `POLICY_NOT_MEASURED`；
- 首期不引入强化学习（`assert_no_rl()`）。

## 9. 边界：知识只回答“怎么做”

| 禁止 | 落点 |
|---|---|
| 知识参与必检判定 | `binding.IMMUTABLE_KNOWLEDGE_TARGETS` 含 `required_checks`/`ruleset_hash`/`state`/`evidence`/`report`/`certificate`；`Injection.payload` 命中即拒绝 |
| 知识作为完成证据 | 检索写 E1，不是 E2/E3；`assert_only_e1()`；E3 只能 Verifier 产生 |
| 知识决定 VERIFIED | 本模块没有 `VERDICT`/`final_state` 字段；M17 方向表禁止 Agent 发 VERDICT |
| 模型自选版本 | `ResolutionSource.MODEL` 构造期拒绝；`ConflictRecord` 没有 winner |
| 覆盖旧版本 | `assert_append_only()`；`new_version` + `deprecate`；`DUPLICATE_REVISION` 拒绝 |
| 过期知识静默使用 | `stale_kb` + `requires_confirmation`；无确认不注入 |

## 10. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| 1. 15 字段与 §11.2 逐字一致 | `EXPECTED_FIELDS` + `assert_field_parity()` | 已定义，未执行 |
| 2. 五类差异字段与 §11.1 一致 | `PAYLOAD_KEYS_BY_KTYPE` + `assert_payload_keys_match_11_1()` | 已定义，未执行 |
| 3. 三态迁移合法、只增不改 | `can_transition` + `assert_status_transitions()` + `assert_append_only()` | 已定义，未执行 |
| 4. 冲突标 CONFLICTED 并升级 | `detect_conflict` + `ConflictRecord` + `HumanResolution` + `assert_no_model_selection()` | 已定义，未执行 |
| 5. 检索带 kid/version/hash/source_url/理由 | `RetrievalHit` + `HitReason`；§6.2 | 已定义，未执行 |
| 6. 过期降权标 stale_kb | `STALE_KB_WEIGHT` + `requires_confirmation` + `assert_stale_downweighted()` | 已定义，未执行 |
| 7. 检索只写 E1 | `RetrievalEvidenceEvent` 固定 level/kind + `assert_only_e1()` | 已定义，未执行 |
| 8. 五种绑定与可测指标 | `BindingKind` 5 值 + 五个绑定类 + 指标函数 | 已定义，未执行 |
| 9. FOL 方向/R1–R3/负面结果 | `FeedbackBus` + `assert_direction_only()` + `assert_arm_matrix()` + `assert_negative_results_kept()` | 已定义，未执行 |
| 10. 知识不参与必检 | §9 表 + `assert_no_decision_binding()` | 已定义，未执行 |

## 11. OPEN QUESTIONS（详见 `design/pseudocode/OPEN_QUESTIONS.md`）

| 编号 | 问题 | P8 临时处理 |
|---|---|---|
| `OQ-P8-10` | 中文检索：FTS5 tokenizer 与查询侧 bigram 是否同口径？ | 查询侧 ASCII 词 + CJK bigram；索引侧口径待实现时用真实 SQLite 验证 |
| `OQ-P8-11` | `kid` 形态未定义；`supersedes` 方向（§11.4 字面“指向新版本”）如何解释？ | `kid` 为不透明字符串；`supersedes` 放在新版本上指向旧 `content_hash`（标准语义），待裁决 |
| `OQ-P8-12` | 知识人工批准/复核的流程与存储未定义；T1 才装配 | `HumanApproval` + `reviewed_by` 必填；写入端口由 WP 落地；T0 tier 直接拒绝 |
| `OQ-P8-09` | 过期降权系数、CPG 产出定义等装配常量无原文 | 标 `PROPOSED`/`[P8 约定]`，不进契约，不写成验收阈值 |

## 12. 本阶段不做

- 不建 SQLite/FTS5 表、不写迁移、不导入任何真实知识；
- 不运行检索、不跑 RF-Bench、不计算 R1–R3 数值、不写统计结论；
- 不实现知识写入 UI、审核台、冲突裁决台；
- 不改 `contracts/`、`docs/design/**`、`docs/state/**`；
- 不把知识接入 Gate/Verifier 的判定路径（这是禁止项，不是“待办”）；
- 不宣称 FR-013/FR-014/G5 已通过；本阶段只交付可评审的伪代码规格。