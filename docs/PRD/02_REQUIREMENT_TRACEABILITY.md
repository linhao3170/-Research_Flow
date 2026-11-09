# 02 需求追踪矩阵（FR-001–FR-020 + NFR-01–08）

> 冻结日期：2026-11-10｜状态：**G0 冻结**｜被取代版本：**v0.2（候选）**｜G0 门禁 PASS 由用户宣布，本文不代替门禁判定。
> 状态：**G0 文档 ② v1.0（G0 冻结）**；**不是 G0 门禁 PASS，不是 T0 开发批准**。
> 日期：2026-11-10（Asia/Shanghai）；候选期内容更新于 2026-11-09。
> 候选期 v0.2 变更：`FR-008` 验收方法/证据列补 `schema_version`（const `"1.0"`）、证书 `issued_at` 与签名载荷覆盖，并引用 `contracts/` 与 72 例中的对应反例；§4.4 的 `RecoveryPlan` 行同步为已决。**FR 编号、优先级、阶段、阈值均未改**。
> 基线：策划书内部 v4.3.0（文件名标签 v4.3.1；`BLK-002` 已关闭）；术语按 [01_BASELINE_AND_TERMS.md](../G0/01_BASELINE_AND_TERMS.md) v1.0。
> 范围：`FR-001`–`FR-020` + `NFR-01`–`NFR-08`，共 28 条，一条不漏、编号不合并。
> 阶段口径：只使用 `T0`、`T1`、`T2`、`T0 最小 + T1 完整`；不使用“后续/待定”。
> 证据口径：本表命令与路径是 **T0/T1/T2 计划证据**；未真实生成前，不得写“已生成/已验证/PASS”。
> `$py`：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`（3.11.16，64 位）。

## 1. 使用说明

### 1.1 列定义

| 列 | 含义 |
|---|---|
| `来源锚点` | 策划书章节 / `P####` / `TABLE ##`；主锚点为附录 C，辅以相关章节 |
| `原文摘要` | 附录 C 原文的短摘要，不改写语义；详细解释见 03/05 |
| `优先级` | `P0/P1/P2`（仅 FR）；NFR 原文未标，写“未标（NFR 强制）” |
| `阶段` | `T0`、`T1`、`T2` 或 `T0 最小 + T1 完整` |
| `模块` | 需求归属模块，不表示代码结构 |
| `依赖` | 实现/验收前必须满足的 FR/NFR |
| `输入/输出` | 需求级输入与可观察输出，不写实现细节 |
| `风险` | 该需求最可能失效的方式 |
| `验收方法` | 可观察、可测试的判定动作；正例、负例、边界 |
| `验收证据` | 具体测试命令 + 证据目录/产物名；均为计划证据 |
| `对应门禁` | `G0`–`G7`；G6 区分 `G6-T0` 与 `G6 完整版（T1）` |

### 1.2 优先级与阶段

- `P0/P1/P2` 是**业务重要度**，不是阶段；阶段按 §15.2 与 01 的交叉表。
- NFR 在附录 C.1 中没有 P0/P1/P2 标注；本表不擅自赋值，统一写“未标（NFR 强制）”。NFR 的阶段列表示**首次强制验收阶段**，T1/T2 仍持续适用。
- `FR-010` 一行双阶段：T0 只做 `WP-R` 最小切片，T1 做完整 Recovery；证据分列。
- `FR-009` 阶段为 T0，但 T0 只验“真包 + 独立环境”；五类负例矩阵属 G6 完整版（T1），证据分列。

### 1.3 证据约定

- T0 测试：`tests/t0/test_fr_###_*.py`、`tests/t0/test_nfr_##_*.py`；证据：`docs/verification/t0/...`。
- T1 测试：`tests/t1/...`；证据：`docs/verification/t1/...`。
- T2 测试：`tests/t2/...`；证据：`docs/verification/t2/...`。
- 命令示例：`& $py -m unittest discover -s tests/t0 -p "test_fr_001*.py" -v`。
- 所有证据路径是**计划路径**；实现后按实际产物登记，不得用文件存在代替真实执行。

### 1.4 计数总览

| 维度 | 数量 | 明细 |
|---|---|---|
| FR | 20 | FR-001–FR-020 |
| NFR | 8 | NFR-01–NFR-08 |
| 优先级 | P0 10 / P1 8 / P2 2 | FR-001–010 / FR-011–018 / FR-019–020 |
| FR 阶段 | T0 9 + 双阶段 1 + T1 5 + T2 5 | FR-001–009；FR-010；FR-011–014、FR-018；FR-015–017、FR-019–020 |
| NFR 阶段 | T0 7 + 双阶段 1 | NFR-01–05、NFR-07–08；NFR-06 |

## 2. FR 矩阵

### 2.1 T0：FR-001–FR-010

| ID | 来源锚点 | 原文摘要 | 优先级 | 阶段 | 模块 | 依赖 | 输入/输出 | 风险 | 验收方法 | 验收证据 | 门禁 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `FR-001` | 附录 C / TABLE 67 R02 / P0466；§6.4 / TABLE 28；附录 E.1 | 创建任务并校验输入 Schema。 | P0 | T0 | API / Contracts | NFR-03 | 入：TaskSpec（task_id、goal、dataset_ref、template_id、parameters、ruleset_hash、limits）；出：持久化任务、校验错误（422） | Schema 漂移、未知字段被静默接受、重复 task_id 产生双任务 | 合法 TaskSpec 创建成功；缺必填/类型错/未知字段按版本策略拒绝并返回 422；重复提交幂等 | `& $py -m unittest discover -s tests/t0 -p "test_fr_001*.py" -v`；`docs/verification/t0/fr-001/{positive.json,negative_422.json,idempotent_duplicate.json,run.log}` | G0 / G1 |
| `FR-002` | 附录 C / TABLE 67 R03 / P0466；§6.1 / TABLE 25 R03；附录 J 04 | 生成 DAG 并检测循环/孤立节点。 | P0 | T0 | DAG Builder | FR-001 | 入：TaskSpec + 节点/边声明；出：校验通过的 DAG、graph_version、拓扑序；非法图拒绝 | 环/孤立/重复边漏检、图版本漂移、非法图进入执行 | 构造环、孤立节点、重复边、缺失依赖、超深/超宽图，全部拒绝；合法图版本固定且可重放 | `& $py -m unittest discover -s tests/t0 -p "test_fr_002*.py" -v`；`docs/verification/t0/fr-002/{cycle.json,orphan.json,duplicate_edge.json,graph_version.json,run.log}` | G0 / G1 |
| `FR-003` | 附录 C / TABLE 67 R04 / P0466；§6.2 / TABLE 26；附录 F / TABLE 70 | 所有状态迁移经 StateMachine。 | P0 | T0 | StateMachine | FR-001、FR-002；NFR-05 | 入：迁移请求（previous/next、actor、reason_code、rule_version、correlation_id）；出：新状态 + audit_log；非法迁移拒绝 | 旁路写状态、缺少审计、过期 previous_state 被接受 | 直接写库/旁路写状态被拒绝；非法迁移被拒绝；成功与失败都写 audit_log；过期 previous_state 拒绝 | `& $py -m unittest discover -s tests/t0 -p "test_fr_003*.py" -v`；`docs/verification/t0/fr-003/{direct_write_reject.log,illegal_transition.log,audit_log.jsonl}` | G0 / G1 / G2 |
| `FR-004` | 附录 C / TABLE 67 R05 / P0466；§5.1 / TABLE 20；附录 J 06 | 白名单模板执行与独立工作目录。 | P0 | T0 | Executor | FR-001、FR-002、FR-003；NFR-06 | 入：template_id + 参数 + 独立 workspace；出：子进程结果、产物、退出码、资源峰值；未注册模板拒绝 | 执行任意代码、工作目录复用、超时进程残留、产物被篡改 | 未注册模板拒绝；工作目录隔离；超时回收进程树；退出码/产物哈希/资源峰值被记录 | `& $py -m unittest discover -s tests/t0 -p "test_fr_004*.py" -v`；`docs/verification/t0/fr-004/{unregistered_template.log,workspace_isolation.json,timeout_tree.log,artifact_hashes.json}` | G1 / G2 |
| `FR-005` | 附录 C / TABLE 67 R06 / P0466；§7.1 / TABLE 31；附录 F.1 | Collector 追加 E0/E1/E2。 | P0 | T0 | Evidence / Collector | FR-003、FR-004；NFR-03 | 入：E0/E1/E2 事件；出：追加证据记录、单调 event_seq、链哈希；重复/乱序可检测 | 事件丢失/重复/乱序、链断、Agent 自述被当 E2 | 重复 event_id 只产生一次逻辑记录；乱序/缺口被检测；篡改链校验失败；E0/E1 不单独满足执行类必检项 | `& $py -m unittest discover -s tests/t0 -p "test_fr_005*.py" -v`；`docs/verification/t0/fr-005/{event_seq.jsonl,duplicate.jsonl,tamper_chain.log,e0_e1_reject.log}` | G2 |
| `FR-006` | 附录 C / TABLE 67 R07 / P0466；§7.2 / P0159–P0168 | Gate 生成必检覆盖矩阵。 | P0 | T0 | Gate | FR-005；NFR-02 | 入：证据集、RequiredChecks、rule_version；出：coverage matrix、GAP/PASS | 缺必检项仍 PASS、规则版本不匹配、冲突未解释 | 缺必检证据 → GAP 非 PASS；规则版本不匹配拒绝；coverage row 完整；未解释冲突拒绝 | `& $py -m unittest discover -s tests/t0 -p "test_fr_006*.py" -v`；`docs/verification/t0/fr-006/{coverage_matrix.json,missing_check_gap.json,rule_version_mismatch.log}` | G0 / G2 |
| `FR-007` | 附录 C / TABLE 67 R08 / P0466；§9.1–9.3 / TABLE 38；附录 J 09–10 | L1/L2/L3 独立验证。 | P0 | T0 | Verifier | FR-005、FR-006；NFR-07 | 入：证据包、原始数据、配置、Split Manifest；出：L1/L2/L3 结果、E3、报告；L3 新目录重跑 | 假 L3（只重算指标/重读 predictions）、复用 Executor 产物、工作目录未隔离 | L1 哈希/序列；L2 指标重算/泄漏五规则；L3 新目录独立进程真实重训/推理；成套伪造拒绝 | `& $py -m unittest discover -s tests/t0 -p "test_fr_007*.py" -v`；`docs/verification/t0/fr-007/{l1.json,l2.json,l3/retrain.log,l3_fake_reject.log}` | G3 |
| `FR-008` | 附录 C / TABLE 67 R09 / P0466；§7.4 / TABLE 32；§7.5 | 签发/验签报告与完成凭证。 | P0 | T0 | Signing / Verifier | FR-006、FR-007；NFR-05 | 入：VerificationReport、证据根、规则版本、私钥；出：签名报告、CompletionCertificate、验签结果；非 VERIFIED 不签 | 非 VERIFIED 被签发、签名载荷缺规则/证据根/`schema_version`、私钥泄漏 | 非 VERIFIED 不签；报告与证书均含 `schema_version`（const `"1.0"`）与 `issued_at`；签名载荷覆盖 `schema_version`、规则版本/证据根/状态；换公钥/改报告状态/破签名验签失败 | `& $py -m unittest discover -s tests/t0 -p "test_fr_008*.py" -v`；`docs/verification/t0/fr-008/{report.sig.json,certificate.json,verify_negative.log}`；`contracts/completioncertificate.schema.json`、`contracts/verificationreport.schema.json`；72 例中的 `completioncertificate.negative.1.json`（缺 `schema_version`）、`completioncertificate.negative.3.json`（缺 `issued_at`）、`verificationreport.negative.1.json`（缺 `schema_version`） | G2 / G6-T0 |
| `FR-009` | 附录 C / TABLE 67 R10 / P0466；§9.5 / P0249–P0251；附录 J 12 | 导出 Evidence Bundle 并离线验签。 | P0 | T0 | Bundle / verify_bundle | FR-007、FR-008；NFR-07 | 入：证据、报告、证书、信任锚；出：Evidence Bundle、verify_bundle 结果 | Bundle 缺清单/证明、信任包自带公钥、负例被放行 | T0：独立环境用外部可信指纹验签真包通过（G6-T0）；T1：五类负例矩阵拒绝 | T0：`& $py -m unittest discover -s tests/t0 -p "test_fr_009_bundle*.py" -v`；`docs/verification/t0/fr-009/`；G6-T0：`& $py docs/verification/t0/g6-t0/bundle/verify_bundle.py docs/verification/t0/g6-t0/bundle --trust-store docs/verification/t0/g6-t0/trusted_keys.json`；`docs/verification/t0/g6-t0/true_bundle.verify.log`；T1：`tests/t1/test_fr_009_negative*.py` + `docs/verification/t1/g6/` | G6-T0（T0）；G6（T1 五类负例） |
| `FR-010` | 附录 C / TABLE 67 R11 / P0466；§8.4 / P0201–P0214；附录 F / TABLE 70 | 恢复计划与失效传播。 | P0 | T0 最小 + T1 完整 | Recovery / StateMachine | T0：FR-002、FR-003、FR-004、FR-005、FR-006；T1 完整另依 FR-011 | T0：入 上游变化/失效节点 + DAG/证据；出 失效后代、冻结恢复计划、保守重跑证据。T1：入 完整恢复触发/上游变化/资源；出 完整恢复计划、受影响子图重跑、调度审批与复核 | stale 证据复用、计划执行中被改写、过宽/过窄失效、T1 完整机制/DC-SPA 被误当 T0 | T0：上游变化 → 后代 `INVALIDATED`；计划哈希冻结；受影响后代全部重跑；stale 证据被 Gate 拒绝；无关节点不重跑。T1：完整 Recovery（恢复计划、受影响子图、调度审批、retry/escalate；无 DC 保守重跑）；DC/SPA 剪枝在 T2/FR-015；G4 | T0：`& $py -m unittest discover -s tests/t0 -p "test_fr_010_minimal*.py" -v`；`docs/verification/t0/fr-010/{invalidated.jsonl,recovery_plan.json,rerun_attempts.jsonl,stale_reject.log}`；T1：`& $py -m unittest discover -s tests/t1 -p "test_fr_010_full*.py" -v`；`docs/verification/t1/fr-010/{full_recovery_plan.json,scheduler_approval.json,retry_escalate.log}` | G2（T0）；G4（T1 完整） |

### 2.2 T1：FR-011–FR-014、FR-018

| ID | 来源锚点 | 原文摘要 | 优先级 | 阶段 | 模块 | 依赖 | 输入/输出 | 风险 | 验收方法 | 验收证据 | 门禁 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `FR-011` | 附录 C / TABLE 67 R12 / P0466；§8.5–8.6 / P0216–P0219 | Ready Scheduler 与 Governor。 | P1 | T1 | Scheduling | FR-002、FR-003；NFR-06 | 入：READY 节点、依赖、资源水位、优先级；出：调度序列、并发调整、资源告警 | 饥饿、资源超卖、优先级反转、调度日志缺失 | 依赖/资源变化改变队列；并发上限 2；无饥饿；调度/资源轨迹可复核 | `& $py -m unittest discover -s tests/t1 -p "test_fr_011*.py" -v`；`docs/verification/t1/fr-011/{sched_queue.jsonl,resource_change.json,starvation_check.json}` | G4 |
| `FR-012` | 附录 C / TABLE 67 R13 / P0466；§10.1–10.2 / TABLE 40–41 | 六角色消息契约与权限。 | P1 | T1 | Agents | FR-003、FR-004；NFR-05 | 入：角色请求、工具白名单、消息 Schema；出：授权/拒绝、消息记录、role-off 结果 | 越权工具调用、角色冒用、消息重放、权限矩阵漂移 | 越权调用拒绝；消息 Schema 校验；role-off 对照可测；权限矩阵可审计 | `& $py -m unittest discover -s tests/t1 -p "test_fr_012*.py" -v`；`docs/verification/t1/fr-012/{permission_deny.log,message_schema.json,role_off.json}` | G2 / G5 |
| `FR-013` | 附录 C / TABLE 67 R14 / P0466；§11.2 / P0272–P0277 | 知识单元版本治理与检索。 | P1 | T1 | Knowledge | FR-005；NFR-02 | 入：KnowledgeUnit、查询、版本；出：命中/冲突/过期结果、引用 ID | 过期/冲突知识被命中、无许可来源、引用无法追溯 | 版本冲突/过期命中测试；引用知识 ID；来源/许可可追溯 | `& $py -m unittest discover -s tests/t1 -p "test_fr_013*.py" -v`；`docs/verification/t1/fr-013/{version_conflict.json,expired_hit.log,citations.jsonl}` | G2 / G5 |
| `FR-014` | 附录 C / TABLE 67 R15 / P0466；§11.5 / TABLE 44 | FOL 三层反馈环。 | P1 | T1 | Feedback | FR-013、FR-018 | 入：执行/知识/策略反馈；出：R1/R2/R3 对照结果、策略更新记录 | 反馈过拟合、虚假相关、负结果被隐藏 | R1/R2/R3 对照；预注册；负面结果保留 | `& $py -m unittest discover -s tests/t1 -p "test_fr_014*.py" -v`；`docs/verification/t1/fr-014/{r1_r2_r3.json,strategy_update.json,negative_results.md}` | G5 |
| `FR-018` | 附录 C / TABLE 67 R19 / P0466；§12.2–12.7 / P0299–P0317 | RF-Bench 60 任务与统计。 | P1 | T1 | Bench | FR-007、FR-008；NFR-05 | 入：60 任务、预注册、四方案/消融；出：原始 JSON、统计脚本、报告 | 任务泄漏、预注册被改、统计错误、只报正面结果 | 预注册/冻结哈希；60 任务；四方案/消融；原始 JSON + 统计脚本可复算 | `& $py -m unittest discover -s tests/t1 -p "test_fr_018*.py" -v`；`docs/verification/t1/fr-018/{prereg.json,tasks60.json,raw_results/,stats.py,report.md}` | G5 |

### 2.3 T2：FR-015–FR-017、FR-019–FR-020

| ID | 来源锚点 | 原文摘要 | 优先级 | 阶段 | 模块 | 依赖 | 输入/输出 | 风险 | 验收方法 | 验收证据 | 门禁 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `FR-015` | 附录 C / TABLE 67 R16 / P0466；§8.2–8.3 / TABLE 34；P0195–P0200 | DC 资格和 SPA 证明。 | P1 | T2 | Recovery / DC / SPA | FR-010（T1 完整）、FR-003、FR-005 | 入：节点类型、输入/代码/环境/规则、k 次运行；出：DC 资格、SPA 记录/拒绝 | DC 误当确定性证明、随机/副作用节点签 DC、无 DC 仍 SPA | 无 DC 不剪枝；DC 失效回滚；k 次 bit-exact；随机/副作用节点不签 DC | `& $py -m unittest discover -s tests/t2 -p "test_fr_015*.py" -v`；`docs/verification/t2/fr-015/{dc_eligibility.json,spa_no_dc_reject.log,k_run_bit_exact.json}` | G4 |
| `FR-016` | 附录 C / TABLE 67 R17 / P0466；§8.7–8.8 / P0222–P0230 | VAS 四策略预算调度。 | P1 | T2 | VAS | FR-007、FR-011 | 入：验证预算、风险/覆盖/成本；出：四策略分配、同预算比较 | 预算博弈、强制验证被排除、四策略不可比 | 四策略同预算比较；强制验证节点不被排除；报告相对最优差距 | `& $py -m unittest discover -s tests/t2 -p "test_fr_016*.py" -v`；`docs/verification/t2/fr-016/{vas_four_strategies.json,budget_comparison.csv}` | G4 / G5 |
| `FR-017` | 附录 C / TABLE 67 R18 / P0466；§13.2 / P0327–P0328 | DeepSeek Harness Adapter。 | P1 | T2 | Adapter | FR-003、FR-005；NFR-03 | 入：固定版本 Harness、任务/事件；出：插件加载、事件映射、状态回传、契约测试 | 版本漂移、事件丢失、状态回传不一致、预览接口变更 | 固定版本插件加载；任务提交/事件映射/状态回传契约测试；版本不匹配拒绝 | `& $py -m unittest discover -s tests/t2 -p "test_fr_017*.py" -v`；`docs/verification/t2/fr-017/{adapter_contract.json,event_mapping.jsonl,version_mismatch.log}` | G7 |
| `FR-019` | 附录 C / TABLE 67 R20 / P0466；§12.4 / P0305 | G-hold-72 独立盲测扩展。 | P2 | T2 | Bench | FR-018 | 入：独立构造 72 任务、哈希封存；出：盲测结果、置信区间 | 盲测污染、样本不足、把 0/72 上界当确定性 | 独立构造/哈希封存；不混入 G-dev；报告置信区间与假设 | `& $py -m unittest discover -s tests/t2 -p "test_fr_019*.py" -v`；`docs/verification/t2/fr-019/{blind72/,sealed_hashes.txt,results.json}` | G5 |
| `FR-020` | 附录 C / TABLE 67 R21 / P0466；§14.5 / P0370–P0371 | 第二领域包。 | P2 | T2 | Domain Pack | FR-013、FR-018 | 入：第二领域数据/报告；出：Domain Pack 钩子、数字重算结果 | 硬编码单领域、报告数字不可复算、钩子绕过 Gate | Domain Pack 钩子；数据分析报告数字重算；不硬编码 | `& $py -m unittest discover -s tests/t2 -p "test_fr_020*.py" -v`；`docs/verification/t2/fr-020/{domainpack_hooks.json,report_recompute.json}` | G5 / G6 |

## 3. NFR 矩阵（NFR-01–NFR-08）

> NFR 原文没有 P0/P1/P2 标注；本表写“未标（NFR 强制）”，不擅自赋优先级。阶段列表示首次强制验收阶段，T1/T2 仍持续适用。

| ID | 来源锚点 | 原文摘要 | 优先级 | 阶段 | 模块 | 依赖 | 输入/输出 | 风险 | 验收方法 | 验收证据 | 门禁 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `NFR-01` | 附录 C.1 / TABLE 68 R02 / P0468；§15.2 / TABLE 56 | 离线可用：无网络、无模型情况下运行内置模板并导出证据包。 | 未标（NFR 强制） | T0 | Runtime / Executor / Bundle | FR-004、FR-009 | 入：断网/无模型 + 内置模板；出：完整证据包、离线验签结果 | 隐式网络/模型依赖、只测“无网”未测“无模型” | 断网 + 无模型跑通；无外部请求；导出包可离线验签 | `& $py -m unittest discover -s tests/t0 -p "test_nfr_01*.py" -v`；`docs/verification/t0/nfr-01/{offline_run.log,no_network.log,bundle/}` | G1 / G6-T0 |
| `NFR-02` | 附录 C.1 / TABLE 68 R03 / P0468；§7.2 | 可解释：每个拒绝结果有 gap_code、evidence_id 和规则引用。 | 未标（NFR 强制） | T0 | Gate / API | FR-006、FR-008 | 入：拒绝结果；出：gap_code、evidence_id、rule_ref | 自由文本替代结构化缺口、证据/规则引用缺失 | 每个拒绝有 gap_code/evidence_id/rule_ref；无自由文本替代 | `& $py -m unittest discover -s tests/t0 -p "test_nfr_02*.py" -v`；`docs/verification/t0/nfr-02/{gap_codes.json,rule_refs.json}` | G2 |
| `NFR-03` | 附录 C.1 / TABLE 68 R04 / P0468；附录 E.4 | 幂等：重复提交/事件不产生重复任务或重复证据。 | 未标（NFR 强制） | T0 | API / Collector | FR-001、FR-005 | 入：重复提交/重复 event_id；出：去重结果、幂等响应 | 重复任务、重复证据、幂等键冲突 | 重复提交不重复建任务；重复 event_id 只一次逻辑记录 | `& $py -m unittest discover -s tests/t0 -p "test_nfr_03*.py" -v`；`docs/verification/t0/nfr-03/{duplicate_submit.json,duplicate_event.json}` | G1 / G2 |
| `NFR-04` | 附录 C.1 / TABLE 68 R05 / P0468；附录 F.1 | 可恢复：进程重启后从持久化状态安全恢复，不重复签发。 | 未标（NFR 强制） | T0 | StateMachine / DB / Verifier | FR-003、FR-005、FR-008 | 入：进程重启、未完成 attempt；出：安全恢复状态、不重复签发 | RUNNING 默认 COMPLETED、重复签发、证据链未校验 | kill/restart 后恢复；RUNNING 不默认 COMPLETED；不重复签发 | `& $py -m unittest discover -s tests/t0 -p "test_nfr_04*.py" -v`；`docs/verification/t0/nfr-04/{restart_recovery.log,no_duplicate_certificate.log}` | G1（T0）；G4（T1 完整） |
| `NFR-05` | 附录 C.1 / TABLE 68 R06 / P0468；§5.1、§7.6 | 可审计：状态迁移、工具请求、密钥操作均有审计记录。 | 未标（NFR 强制） | T0 | StateMachine / Tool Gateway / Key Mgmt | FR-003、FR-004、FR-008 | 入：状态迁移/工具请求/密钥操作；出：audit_log | 失败迁移未记、密钥操作无审计、日志被篡改 | 状态/工具/密钥操作 audit_log 覆盖；失败也记录 | `& $py -m unittest discover -s tests/t0 -p "test_nfr_05*.py" -v`；`docs/verification/t0/nfr-05/{audit_sample.jsonl,key_ops.log}` | G2 |
| `NFR-06` | 附录 C.1 / TABLE 68 R07 / P0468；§5.4 / TABLE 22 | 资源受控：并发、内存、CPU、磁盘、时长和 token 有配置上限。 | 未标（NFR 强制） | T0 最小 + T1 完整 | Config / Executor / Governor | FR-004 | 入：并发/内存/CPU/磁盘/时长/token；出：上限配置、超限拒绝/降级记录 | 无上限导致 OOM、超限未记录、T1 Governor 被误当 T0 | T0：配置上限、超限拒绝/降级并记录；T1：Governor 动态调节和回收 | T0：`& $py -m unittest discover -s tests/t0 -p "test_nfr_06*.py" -v`；`docs/verification/t0/nfr-06/{limits.yaml,resource_peak.json}`；T1：`tests/t1/test_nfr_06_governor*.py` + `docs/verification/t1/nfr-06/` | G1（T0）；G4（T1） |
| `NFR-07` | 附录 C.1 / TABLE 68 R08 / P0468；§9.5 | 可移植：Evidence Bundle 在无数据库环境独立验证。 | 未标（NFR 强制） | T0 | Bundle / verify_bundle | FR-009 | 入：Evidence Bundle；出：无 DB 环境验证结果 | 验签依赖 DB/模型、信任包自带公钥 | 无 DB/模型环境 verify_bundle 通过；外部信任锚 | `& $py -m unittest discover -s tests/t0 -p "test_nfr_07*.py" -v`；`docs/verification/t0/nfr-07/{offline_verify.log}` | G6-T0 |
| `NFR-08` | 附录 C.1 / TABLE 68 R09 / P0468；§17.2 | 隐私最小化：默认不将原始课程数据放入外部模型请求。 | 未标（NFR 强制） | T0 | Config / Agent Gateway / Adapter | FR-001、FR-017 | 入：课程数据/外部模型请求；出：最小化/脱敏策略、请求审计 | 原始数据泄漏到外部模型、T1 Adapter 绕过策略 | 默认不发送原始课程数据；请求审计；脱敏/最小化配置生效 | `& $py -m unittest discover -s tests/t0 -p "test_nfr_08*.py" -v`；`docs/verification/t0/nfr-08/{payload_audit.log,privacy_config.yaml}` | G2 |

## 4. 一致性与未决项

### 4.1 覆盖检查

| 检查 | 结果 |
|---|---|
| FR-001–FR-020 | 20/20，一条不漏 |
| NFR-01–NFR-08 | 8/8，一条不漏 |
| 编号合并 | 0；FR-010 用一行双阶段，不拆号 |
| 阶段空值/模糊值 | 0；只出现 `T0`、`T1`、`T2`、`T0 最小 + T1 完整` |
| 优先级空值 | 0；FR 为 P0/P1/P2，NFR 为“未标（NFR 强制）” |
| 验收证据为空 | 0；每行都有命令 + 证据路径/产物名（计划） |

### 4.2 阶段/优先级分布

| 阶段 | FR | NFR |
|---|---|---|
| T0 | FR-001–009 | NFR-01–05、NFR-07–08 |
| T0 最小 + T1 完整 | FR-010 | NFR-06 |
| T1 | FR-011–014、FR-018 | — |
| T2 | FR-015–017、FR-019–020 | — |

### 4.3 门禁覆盖（粗映射）

| 门禁 | 主要需求 |
|---|---|
| G0 | FR-001、FR-002、FR-003、FR-006 |
| G1 | FR-001–004、NFR-01、NFR-03、NFR-04、NFR-06（T0） |
| G2 | FR-003–006、FR-008、FR-010（T0）、NFR-02、NFR-05、NFR-08 |
| G3 | FR-007 |
| G4 | FR-010（T1）、FR-011、FR-015、FR-016、NFR-04、NFR-06（T1） |
| G5 | FR-012–014、FR-016、FR-018–020 |
| G6 | FR-009（G6-T0 / G6 完整版）、FR-020、NFR-01、NFR-07 |
| G7 | FR-017 |

### 4.4 未决项索引（进 ⑧/⑤/⑥，不在本表留空）

| 项 | 影响 | 去向 |
|---|---|---|
| Task 级 `COMPLETED` 后撤销 | FR-010 T1 的 revocation 细节 | ⑧ |
| `RecoveryPlan` 内部/公开 | FR-010 的契约形态 | **已决**（决议 3 / `ADR-004`）：T0 内部不可变产物，内容寻址文件；见 05 §9.3/§9.5 |
| `HarnessEvent`、`DomainPack` Schema | FR-017、FR-020 的字段冻结 | ⑤ |
| 附录 E 之外的 API 路径/状态码 | FR-001 等 API 细节 | ⑥/⑧ |
| NFR-06 具体阈值 | 资源上限验收 | ⑤/⑥ |
| 第二领域包选择 | FR-020 的领域数据 | ⑧ |
| G6-T0 独立环境细节 | FR-009、NFR-07 的验签环境 | ⑦ |
| 计划证据路径的实际命名 | 全部证据 | ⑦/⑧；不得改变需求语义 |

---

**标记：本文件是 G0 文档 ② v1.0（G0 冻结），不是 G0 门禁 PASS。** 文档已按用户 2026-11-10 指令冻结；G0 是否 PASS 由用户宣布；未建 `.venv`、未写业务代码。
