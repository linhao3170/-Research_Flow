# M08 · Gate 与规则集（P5）

> 阶段：P5「门控与三级验证」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：规则集装载与版本哈希、coverage row 七字段、Gate 七步判定、四类一票否决
> 不覆盖：Ed25519 签名/信任锚（P6）、验证预算分配（P9）、报告签发（P6/WP-11）、科学结论评价
> 前置：P4 设计产物存在；验收状态以 `docs/state/project_state.json` 为准（P4 设计件已验收；实现未开始）；M01 错误码、M06 required_checks、M07 collector 已冻结
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码

## 1. 目标

把“证据 → 判定”这一跳写死为七步：

1. 规则集是**只读输入**，版本可重算（`ruleset_hash`），任务绑定不可自动升级；
2. Gate 只读结构化证据与规则，不写证据/状态、不签名、不签发报告；
3. 每项必检生成七字段 coverage row，`result` 由前六列计算，调用方不能自报 PASS；
4. 缺必检、哈希不符、规则版本不符、冲突未解释 = 一票否决；
5. E0/E1 永不满足执行类必检；报告指标来源节点必须有 PASS 的 L3/IRC 物证；
6. 七步顺序固定，任何一步的失败都不能被后续步骤“补回来”；
7. Gate 只返回 `PASS / GAP / BLOCKED`，永不返回 `VERIFIED`。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `evidence/ruleset.py` | 规则集结构、必检项/证据规则/L3 策略、`ruleset_hash` 装载与任务绑定 | 704 | 完成（伪代码） |
| `evidence/coverage_matrix.py` | `CoverageRow` 七字段、`build_row()` 计算、`CoverageMatrix.report_counts()`、`L3Attestation` | 482 | 完成（伪代码） |
| `evidence/gate.py` | 七步 Gate、四类 veto、缺口收集、PASS/GAP/BLOCKED 结论 | 1176 | 完成（伪代码） |

### 2.1 `gate.py` 函数索引（>800 行，按 PHASE_RULES §5 第 2 档登记）

| 符号 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `GateError` | 154 | Gate 输入/端口/程序性错误；常规缺口不抛异常 | 05 §13 |
| `RecordView` | 179 | EvidenceRecord 的只读投影（不含 payload） | 05 §4.1 |
| `RecordSchemaPort` | 219 | 冻结 schema 独立复核端口 | 05 §13 |
| `PayloadReaderPort` | 225 | 按 payload_hash 读规范化字节 | 05 §13 |
| `ArtifactHasherPort` | 231 | 按 attempt + artifact ref 重算 SHA-256 | 05 §13 |
| `ChainHashPort` | 237 | M07 ChainHasher 只读端口 | 本文 §5 第 2 步 |
| `ConflictJournalPort` | 256 | 未解释冲突读取；不可用即 fail-closed | 本文 §7 |
| `GateInput` | 267 | 七步的完整只读输入 | 本文 §5 |
| `GateGap` | 307 | 结构化缺口（code/error_code/step/node/check/veto） | 本文 §7 |
| `GateGap.veto_class` | 323 | 具体缺口码 → 四类 veto 归类 | 本文 §7 |
| `GateResult` | 329 | PASS/GAP/BLOCKED、coverage、vetoes、executed_steps | 本文 §5 |
| `GateResult.veto_classes` | 357 | 命中的四类 veto 去重保序 | 本文 §7 |
| `_GateContext` | 377 | 单次判定的工作区（hash_status/gaps/matrix） | 本文 §5 |
| `Gate.evaluate` | 421 | 按 7.2 顺序调度七步；第 1/2 步 veto 即 BLOCKED | 策划书 §7.2 |
| `validate_schema_and_versions` | 474 | 第 1 步：证据 schema、规则集哈希、任务绑定、节点/必检项引用 | 策划书 §7.2 第 1 句 |
| `verify_event_sequence_and_hash_chain` | 556 | 第 2 步：event_seq 连续、prev_hash 接链、chain_hash 重算 | §7.2 第 2 句、§7.3 |
| `verify_artifact_hashes_and_producers` | 625 | 第 3 步：level/kind/producer、payload_hash、artifact 哈希 | §7.2 第 3 句 |
| `build_required_check_coverage_matrix` | 704 | 第 4 步：按节点/证据规则生成七字段行 | §7.2 第 4 句 |
| `reject_unresolved_evidence_conflicts` | 829 | 第 5 步：冲突日志 + 重复执行事件检测 | §7.2 第 5 句 |
| `require_e2_e3_for_execution_critical_checks` | 886 | 第 6 步：执行类必检 E2/E3，E0/E1 降级 + veto | §7.2 第 6 句 |
| `require_l3_irc_for_report_metric_source_nodes` | 926 | 第 7 步：指标来源节点的 L3 物证回查与覆盖率 | §7.2 第 7 句 |
| `_conclude` | 1055 | 第 8 步：PASS only if all pass，否则 GAP(list) | §7.2 第 8 句 |
| `_blocked` | 1084 | 第 1/2 步 veto 的短路结论 | 本文 §5.1 |
| `_can_satisfy_execution_check` | 1102 | 与 M07 同口径的 E2/E3 判定 | M07 §5.2 |
| `_gap` | 1111 | GateGap 构造与 detail 只读化 | 本文 §7 |
| `assert_step_order` | 1139 | 七步名称/顺序与 §7.2 一一对应 | 验收判据 1 |
| `assert_gate_boundary` | 1161 | Gate 无写入/状态/签名/VERIFIED 的静态检查 | AGENTS §4 |

`ruleset.py`、`coverage_matrix.py` ≤800 行，无需索引。

## 3. 信任边界与权限矩阵

| 参与方 | 能做什么 | 不能做什么 | 本模块落点 |
|---|---|---|---|
| Agent/LLM | 提交 E0 声明 | 写证据、写状态、自报 level/producer、用 E0 满足执行类必检 | Gate 不读取 Agent 自述；只读 Collector 记录的 E0 |
| Executor | 产生 E2 事件/产物 | 自报 coverage、自报 PASS、写规则集 | 第 3 步只信 Collector 记录 + 产物重算 |
| Collector（M07） | 单写 E0–E2、分配 seq/链 | 判定 Gate、签发报告、接受 E3（P4） | 第 2 步复用链校验端口 |
| Gate（本模块） | 读证据/规则/L3 物证，生成 coverage 与 GAP | 写证据/状态、签名、签发报告、修改规则集 | 全模块；`assert_gate_boundary()` |
| Verifier（P6） | 消费 GateResult，组装报告/证书 | 让 Gate 直接产出 VERIFIED | `GateResult.assert_no_verified_claim()` |

## 4. 规则集与版本哈希

`ruleset_hash = sha256(JCS({schema_version, ruleset_version, required_checks, l3_policy, conflict_policy}))`。

- `ruleset_hash` 不进前像（否则自指）；`required_checks` 保持声明顺序，不排序。
- `RequiredCheck`：`check_id`、`description`、`min_level`、`execution_critical`、`l3_required`、`evidence_rule`。
- `EvidenceRule`：`accepted_kinds` + 可选 `artifact_name`。Gate **不读取**证据自报的 check_id；它按 kind/产物名匹配，防止被验证方自选必检项。
- `L3Policy`：`required_coverage`（T0 默认 1.0）+ `metric_source_check_ids`。
- 装载期拒绝：空必检、重复 ID、执行类 min_level 低于 E2、接受的 kind 低于 min_level、L3 要求但等级不足、L3 引用了不存在的必检项、冲突策略不是 `REJECT_UNRESOLVED`。
- 绑定：`TaskSpec.ruleset_hash` 必须等于当前规则集哈希；不等抛 `RULESET_VERSION_MISMATCH`(409)，**不得自动升级到最新规则**。

## 5. 七步 Gate（顺序不可交换）

| 步 | 方法 | 关键检查 | 失败处理 |
|---:|---|---|---|
| 1 | `validate_schema_and_versions` | 证据 schema_version=1.0；规则集哈希可重算；TaskSpec 绑定；节点/必检项/指标节点引用存在 | 任一 veto → **BLOCKED**，不进入第 2 步 |
| 2 | `verify_event_sequence_and_hash_chain` | seq 从 1 起严格 +1；evidence_id 唯一；prev_hash 接链；chain_hash 重算 | 任一 veto → **BLOCKED** |
| 3 | `verify_artifact_hashes_and_producers` | level↔kind、level↔producer；payload_hash；artifact_refs 重算 vs E2 清单 | 记录 `hash_status=MISMATCH`，继续 4–7 收集缺口，最终 **BLOCKED** |
| 4 | `build_required_check_coverage_matrix` | 每个必检项按节点/证据规则生成七字段行；空绑定/缺节点证据 → GAP + veto | 继续；最终 **BLOCKED** |
| 5 | `reject_unresolved_evidence_conflicts` | 冲突日志未解释；重复 launch/exit；重复 artifact 观测；日志不可读 |  veto，继续；最终 **BLOCKED** |
| 6 | `require_e2_e3_for_execution_critical_checks` | 执行类行的 level ∈ {E2,E3}；E0/E1 行降级 GAP + veto | 继续；最终 **BLOCKED** |
| 7 | `require_l3_irc_for_report_metric_source_nodes` | 每个指标来源节点有 PASS L3 物证、规则版本一致、E3 回查、随机性模式 ≥5 种子、plan_hash 预冻结 | 缺口 + veto；覆盖率不足 → **BLOCKED** |
| 8 | `_conclude` | 无缺口、无 veto、coverage missing=0、l3_coverage ≥ 阈值 | 否则 `GAP(list)`；有 veto 则 `BLOCKED` |

### 5.1 为什么第 1/2 步短路

schema/版本不成立时，后面生成的 coverage 没有可信前提；链断裂时，证据集可能已被替换。此时继续“算一个覆盖率”只会制造虚假精确。第 3 步起继续收集缺口，是为了让用户一次看到所有可修复项，但 veto 结果不变。

## 6. coverage row 七字段

`required_check_id / evidence_ids / level / producer / hash_status / l3_status / result`

- `result` **由 `build_row()` 计算**，不接受调用方输入；没有证据必然 GAP；哈希不是 MATCH 必然 GAP；要求 L3 而 `l3_status != PASS` 必然 GAP。
- `l3_status` 不要求 L3 时必须是 `SKIP`；要求 L3 时 `SKIP` 也算 GAP（不能把“跳过”当“通过”）。
- 一个 check 绑定多个节点时做**全称聚合**：所有适用节点都通过才 PASS；任一节点缺证据，整行 GAP，具体缺口由 `GateGap.node_id` 指出。
- 反空转：必检项没有绑定任何节点时按 GAP + veto 处理，不得“没有适用节点所以通过”。
- `report_counts()` 返回 `(required, passed, missing)`，满足 SEM-VR-01；`VERIFIED ⇒ missing==0` 由 `assert_report_counts_consistent(verified=True)` 再判（SEM-VR-02）。

## 7. 四类一票否决

| veto code | 触发 | 注册错误码 | 实现位置 |
|---|---|---|---|
| `REQUIRED_CHECK_MISSING` | 必检项无合格证据/绑定不到节点/执行类未通过 | `REQUIRED_EVIDENCE_MISSING`(409) | 第 4/6 步 |
| `HASH_MISMATCH` | payload/产物哈希与记录或清单不符 | `BUNDLE_TAMPERED`(422) | 第 3 步 |
| `RULESET_VERSION_MISMATCH` | task/规则集/证据 schema 版本或哈希不一致 | `RULESET_VERSION_MISMATCH`(409) | 第 1 步 |
| `UNRESOLVED_EVIDENCE_CONFLICT` | 冲突日志未解释/重复执行事件 | `REQUIRED_EVIDENCE_MISSING`(409) | 第 5 步 |

四类之外还有结构性 veto（未知节点、节点要求了规则集没有的 check、L3 物证引用非 E3 记录等）；它们同样 fail-closed，但不改变“四类必须否决”的口径。

**E0/E1 的拦截位置（写死）**：E0/E1 先由**装载期**拒绝（执行类 `min_level` 低于 E2 →
`EXECUTION_CHECK_LEVEL_TOO_LOW`；接受的 kind 低于 `min_level` → `EVIDENCE_RULE_BELOW_MIN_LEVEL`），
再由 Gate 第 4 步按等级过滤；第 6 步的 `E0_E1_CANNOT_SATISFY_EXECUTION_CHECK` 只是
**纵深防御**。合法规则集下该码不可达，不得写成“Gate 第 6 步是主判据”。

## 8. 三级验证边界（M08 只消费，不实现）

- **L1**：能证明证据集 schema/哈希/seq/链/Merkle/目录独立；不能证明代码真的执行过，也不能在攻击者同时控制证据库时保证不可伪造。Gate 不把 L1 PASS 当执行证据。
- **L2**：能证明 predictions/metrics/混淆矩阵内部自洽且 R1–R5 未命中；**L2 自洽 ≠ 真实执行**，成套伪造可以让 L2 全过。Gate 不把 L2 当 E2/E3。
- **L3**：只支持**同环境**独立重执行；新目录、独立进程、只读白名单、真实重训/重推。Gate 第 7 步只接受 L3 物证的 PASS；L3 失败/未跑不能由 L2 顶替。

## 9. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| 1. 七步与 7.2 一一对应、顺序不能换 | `SEVEN_STEPS`；`Gate.evaluate` 顺序；`assert_step_order()`；E0/E1 主要由装载期 + 第 4 步等级过滤拦截，第 6 步仅纵深防御；本文 §5 | 已定义，未执行 |
| 2. 五条泄漏规则有可执行判据 | M09 `leakage_rules.py`；本文 §8 引用；M09 MODULE §6 | 已定义，未执行 |
| 3. `l3_sandbox` 只读清单是白名单 | M10 `READONLY_ALLOWLIST`；`is_read_allowed()` 默认拒绝；无黑名单分支 | 已定义，未执行 |
| 4. NEGATIVE_TESTS 覆盖六类场景 | `M08_gate/NEGATIVE_TESTS.md` 的 NEG-M08-29..32 指向 M10；M09/M10 负例表 | 判据已定义，未执行 |

## 10. OPEN QUESTIONS（详见 `design/pseudocode/OPEN_QUESTIONS.md`）

| 编号 | 问题 | P5 临时处理 |
|---|---|---|
| `OQ-P5-01` | 冻结 `EvidenceRecord` 没有 `ruleset_version` 字段（§7.3 要求记录） | Gate 在任务级 + E3 物证级绑定规则版本；证据级绑定待 MINOR/ADR |
| `OQ-P5-02` | `VerificationReport` schema 没有 `gaps`/`attribution` 字段（§7.4 列出） | GateResult/L3 结果作为结构化 sidecar；报告字段待裁决 |
| `OQ-P5-03` | `l3_coverage` 分母未定义 | P5 取“报告指标来源节点”；待用户确认 |
| `OQ-P5-09` | coverage row 无 node_id，多节点只能聚合 | GateGap 带 node_id；逐节点明细待 schema/sidecar |
| `OQ-P5-10` | 冲突日志来源未统一（M07 rejection log vs StateMachine invalidations） | Gate 通过 `ConflictJournalPort` 读取；端口实现待 WP-08 |

## 11. 本阶段不做

- 不做签名、证书、信任锚、离线验签（P6）。
- 不做验证预算分配/VAS（P9）。
- 不评价科学结论、不判断实验设计优劣。
- 不实现 Gate 的 HTTP 路由、不建库、不跑测试。