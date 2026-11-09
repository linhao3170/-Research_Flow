# 08 未决问题、风险与冻结决议（v1.0）

> 冻结日期：2026-11-10｜状态：**G0 冻结**｜被取代版本：**v0.3（候选）**｜G0 门禁 PASS 由用户宣布，本文不代替门禁判定。
> 状态：**G0 文档 ⑧ v1.0（G0 冻结）**；三组枚举已按现值冻结、依赖矩阵已锁定为 `WP-01` 基线、`ADR-007` 保持 `PROPOSED`；**不是 G0 门禁 PASS**。
> 日期：2026-11-10（Asia/Shanghai）；候选期内容更新于 2026-11-09。
> 基线：术语按 [01](01_BASELINE_AND_TERMS.md) v1.0；需求按 [02](../PRD/02_REQUIREMENT_TRACEABILITY.md) v1.0；故事按 [03](../PRD/03_PRD_T0.md) v1.0；架构按 [04](../design/04_ARCHITECTURE.md) v1.0；契约/状态按 [05](../design/05_CONTRACTS_AND_STATES.md) v1.0；数据/API 按 [06](../design/06_DATA_AND_API.md) v1.0；T0 计划/门禁按 [07](../design/07_T0_PLAN_AND_GATES.md) v1.0；机器可读契约按 [`contracts/`](../../contracts/)（⑨ v1.0）。
> 作用：集中登记未决问题、风险、ADR 与冻结决议；**不替用户做决定**，也不把“决议已落地”写成“G0 已通过”。

## 1. 汇总

| 类别 | 数量 | 说明 |
|---|---|---|
| 未决问题（OQ） | 30 | 15 项已关闭 / 0 项部分关闭 / 15 项开放；**阻塞 G0 的 0 项**（原 11 项已由 10 项决议关闭，3 项枚举取值已由 2026-11-10 裁决关闭） |
| 风险 | 14 | 见 §3；第 9 条“T0 回环免认证”与第 14 条“证据日志可被覆盖”为已接受风险 |
| ADR | 7 | `ADR-001`–`ADR-006` ACCEPTED；`ADR-007` 保持 PROPOSED，WP-13 前裁决 |
| 本轮用户决议 | 10 | **已裁决**（2026-11-09），落地位置见 §6 |
| 2026-11-10 裁决 | 4 | 枚举按现值冻结、依赖矩阵锁定为 `WP-01` 基线、`ADR-007` 延后、Git 仓库级身份与 DOCX 精确忽略；落地见 §6.1/§6.2 |
| 仍需用户确认 | 0 | 无（G0 是否 PASS 由用户宣布，不在本文“待确认”范围） |

## 2. 未决问题登记

等级说明：`A` = 阻塞 G0 冻结；`B` = 阻塞对应工作包但不阻塞 G0；`C` = 可延后到实现期。

| ID | 问题 | 来源 | 影响 | 建议 | 等级 | 状态 |
|---|---|---|---|---|---|---|
| `OQ-001` | `RecoveryPlan` 是内部产物还是公开契约 | ①/④/⑤ | 契约数量、签名范围、对外兼容 | 内部不可变产物（不签名、不进七契约、不对外） | A | **已关闭（决议 3）** |
| `OQ-002` | 失效/恢复控制事件写 `audit_log` 还是也写 E1/E2 | ①/④/⑤ | 证据链、Gate 判定、审计一致性 | 只写 `audit_log` + `evidence_invalidations`，不占用 E0–E3 | A | **已关闭（决议 4）** |
| `OQ-003` | 已签发 `CompletionCertificate` 之后的撤销路径 | ①（B1 决议） | T1 凭证生命周期 | 留 T1 与 revocation 机制，T0 不实现 | C | 开放 |
| `OQ-004` | `HarnessEvent` 无 Schema | ⑤/⑧ | T2 适配 | T2 前以固定版本官方契约补齐；G0 不冻结 | C | 开放 |
| `OQ-005` | `DomainPack` 字段级 Schema 缺失 | ⑤ | 域包冻结、`required_checks` 来源 | G0 只冻结钩子名与约束；字段待域包落地 | B | 开放 |
| `OQ-006` | `NodeSpec` 是否补 `schema_version` | ⑤ | 版本兼容 | 补，`const "1.0"` | A | **已关闭（决议 2）** |
| `OQ-007` | `VerificationReport` 是否补 `schema_version` | ⑤ | 版本兼容、签名载荷 | 补，且进入签名载荷 | A | **已关闭（决议 2）** |
| `OQ-008` | `CompletionCertificate` 是否补 `schema_version`、`issued_at` | ⑤ | 版本兼容、时间可追溯 | 两者都补 | A | **已关闭（决议 2）** |
| `OQ-009` | `EvidenceRecord.kind` 枚举未定义 | ⑤ | 证据分类、Gate 规则 | T0 最小集合 7 值已落 schema，2026-11-10 按现值冻结 | B | **已关闭（2026-11-10 冻结；按 MINOR 可变）** |
| `OQ-010` | `l1/l2/l3_status` 枚举未定义 | ⑤ | 报告校验 | `PASS/FAIL/SKIP/NOT_RUN` 已落 schema，2026-11-10 按现值冻结 | B | **已关闭（2026-11-10 冻结；按 MINOR 可变）** |
| `OQ-011` | `side_effect_class` 枚举未定义 | ⑤ | 执行与 DC 判据 | `PURE_FUNCTION/PURE_ARTIFACT/SIDE_EFFECT` 已落 schema，2026-11-10 按现值冻结 | B | **已关闭（2026-11-10 冻结；按 MINOR 可变）** |
| `OQ-012` | 首条 `prev_hash` 约定值 | ⑤ | 链起点校验 | 建议 32 字节全零十六进制；schema 暂只要求 64 位十六进制 | B | 开放 |
| `OQ-013` | `INVALIDATED → READY` 的计划引用形态 | ⑤/⑦ | WP-R 实现 | 存 `plan_id` + `plan_hash`；守卫三条件 | A | **已关闭（决议 5）** |
| `OQ-014` | `INVALIDATED` 重复失效是否幂等 | ⑤ | 迁移健壮性 | 建议只追加失效记录，不重复迁移 | B | 开放 |
| `OQ-015` | T0 是否复用 Recovery 状态机 | ⑤ | WP-R 边界、Agent 语义 | 不复用；无 `PROPOSED`/`APPROVED`；完整状态机属 T1 | A | **已关闭（决议 6）** |
| `OQ-016` | `parameters` 是否按模板强类型 | ⑤ | 校验严格度 | 单文档 schema 只约束已知键；未知参数由模板层拒绝 | B | 开放 |
| `OQ-017` | 失败迁移的审计与事务一致性 | ⑥ | 状态可信、审计完整 | 成功同事务；失败独立事务写 `DENIED`；二次失败降级 stderr | A | **已关闭（决议 7）** |
| `OQ-018` | 幂等键保留期与清理 | ⑥ | 存储增长、重放风险 | T0 保留至任务完成后归档 | C | 开放 |
| `OQ-019` | 证据表是否分区/分表 | ⑥ | T0 性能 | T0 单表 + 索引 | C | 开放 |
| `OQ-020` | `skipped_nodes` 存储形态 | ⑥ | T0 恒为空 | 存 JSON 数组文本；T0 用 `maxItems: 0` 约束 | C | 开放 |
| `OQ-021` | T0 是否开放 `POST /recover` | ⑥ | 范围、误用风险 | 不开放；路由不注册，访问 404 | A | **已关闭（决议 8）** |
| `OQ-022` | `dataset_ref` 在 API（字符串）与 TaskSpec（对象）不一致 | ⑥ | 接口与契约一致性 | 统一对象形态；字符串 422；`ADR-002` | A | **已关闭（决议 9）** |
| `OQ-023` | `mode` 与 `requested_checks` 取值集合 | ⑥ | 验证入口 | T0 只支持 `full` + `L1/L2/L3` | B | 开放 |
| `OQ-024` | 错误响应体统一结构 | ⑥ | 客户端契约 | `error_code/message/field_path?/correlation_id` | B | 开放 |
| `OQ-025` | 证据分页参数与上限 | ⑥ | 大任务查询 | `limit≤200`、游标 `event_seq` | C | 开放 |
| `OQ-026` | T0 认证方式 | ⑥ | 单机安全边界 | 仅回环 + 免认证；非回环无 token 拒绝启动；登记为已接受风险 | A | **已关闭（决议 8）** |
| `OQ-027` | 最小工作台四视图范围 | ④/③ | 范围蔓延 | 严格四视图，不做六页；`ADR-007` 保持 PROPOSED，WP-13 前裁决 | B | 开放（WP-13 前裁决） |
| `OQ-028` | API 与 StateMachine 是否同进程 | ④ | 隔离强度、复杂度 | T0 同进程但单写入口；T1 再拆 | B | 开放 |
| `OQ-029` | 私钥存储形态 | ④ | 密钥安全 | 受限目录 + ACL；开发密钥与交付锚分离 | B | 开放 |
| `OQ-030` | `C-002` 飞书资料、`C-003` 赛事章程是否补入 | ① | 方法论来源、赛事对题 | 不补入、不引用；赛事结论标“未独立核验” | C | **已关闭（决议 10）** |

## 3. 风险排序

按“影响 × 可能性”排序；前 5 项建议在 T0 启动前处理。

| 排序 | 风险 | 影响 | 现状 | 处理 |
|---|---|---|---|---|
| 1 | **13b 仅全权限通过**（`BLK-003`） | 代码正确性验证在正常策略下不可重复 | workspace-write 下 23 tests / 43 errors；诊断 `NOT_THIS_CLASS` | 维持 NOT VERIFIED；full-access 单独会话运行并记录策略；不得用于安全项 |
| 2 | **契约字段缺口**（原 `OQ-006/007/008`） | 契约冻结不完整，后续返工 | **已由决议 2 关闭**；三组枚举已于 2026-11-10 按 v1.0 现值冻结 | 只改枚举成员按 `MINOR`；改动必须重跑 `validate_contracts.py` 并同步 ⑤/⑧/schema |
| 3 | **失效语义未落到状态机前**（原 `OQ-013/015`） | WP-R 实现偏差、stale 证据漏判 | **已由决议 5/6 关闭** | 守卫三条件 + 计划确定性已写入 05/07；实现时按 `WP-R` 负例验收 |
| 4 | **Git 基线**（`BLK-001`） | 无法回溯、无法演示回滚 | **已建立 G0 规格基线提交**；仓库级身份已配置，全局身份仍为空 | 回滚演示仍属阶段 8 第 20 项 `NOT VERIFIED`，不因本提交自动通过；DOCX 已按精确文件名忽略 |
| 5 | **失败迁移审计的双事务实现**（原 `OQ-017`） | 状态可信度 | **语义已由决议 7 关闭**；实现未开始 | `WP-03` 用真实 SQLite 证明 `DENIED` 存活；二次失败降级 stderr 并计缺口 |
| 6 | 2C/2D 口径（阶段 8 残留） | 安全验收证据不足 | 2D 未执行、2C 静态确认 | 阶段 9/⑧ 决定补做或书面接受 |
| 7 | `C-002` 飞书资料缺失 | 方法论来源不可核 | **已接受（决议 10）** | 不补入、不引用；需要时由用户提供导出件 |
| 8 | `C-003` 赛事章程缺失 | 评分/格式/匿名规则不可核 | **已接受（决议 10）** | 只引策划书转述，一律标“未独立核验” |
| 9 | **T0 回环免认证** | 本机端口被同机进程或误配置暴露 | **已接受（决议 8）** | 默认仅回环；非回环且无 token 拒绝启动；`T0-SEC-BIND-*` 负例；不得宣称已加固 |
| 10 | 依赖未锁定 | L3 不可复现 | 矩阵已于 2026-11-10 锁定为 `WP-01` 基线 | 安装后按矩阵核对 + 环境指纹；偏差记录，不静默升级 |
| 11 | 数据集许可/隐私 | 合规风险 | 未选数据集 | `WP-05` 前确认许可 |
| 12 | 范围蔓延至 T1/T2 | T0 失控 | A1/D1 已设边界 | 变更需书面裁决 |
| 13 | 离线验签绕过信任锚 | G6-T0 失效 | 未实现 | 包外信任锚 + 负例 |
| 14 | **证据日志被同名脚本覆盖，且无 Git 基线时不可恢复** | 证据可追溯性受损；无法证明归档后未被改动 | **已发生**：`stage7/14_link_check.log` 被重跑覆盖（232→239） | 证据日志只追加；脚本输出路径必须显式参数化（参数或环境变量），**禁止默认覆盖既有日志**；只读检查脚本不写文件；原始记录不追改，另发 `SUPERSEDED_NOTICE.md`；建立 Git 基线后再做同类重跑 |

`C-002`/`C-003` 的处置口径（决议 10）：两项均**不补入、不引用**，不阻塞 G0；凡涉及赛事评分/页数/匿名/IP 的结论，必须逐句标“未独立核验”。① §2.2 仍把它们登记为 `OPEN`（资料缺失状态），与“G0 已接受该缺失”不矛盾，不因此修改已冻结的 ①。

## 4. ADR 登记

编号按用户决议固定：`ADR-002` 专用于 `dataset_ref` 对象化（用户 2026-11-09 指定）。原 v0.1 的 ADR 候选已顺延重编号。

| 编号 | 标题 | 状态 | 说明 |
|---|---|---|---|
| `ADR-001` | Node `INVALIDATED` state for FR-010 T0 minimal slice | **ACCEPTED**（2026-11-08） | 正式文件 [ADR-001](../ADR/ADR-001-invalidated-node-state.md) |
| `ADR-002` | `dataset_ref` 统一为对象形态（偏离附录 E.1 字符串样例） | **ACCEPTED**（2026-11-09，决议 9） | 对象 `{uri,sha256,license}`；字符串 422；负例 `taskspec.negative.3.json`；[ADR-002](../ADR/ADR-002-dataset-ref-object.md) |
| `ADR-003` | 为 `NodeSpec`/`VerificationReport`/`CompletionCertificate` 补 `schema_version`，证书补 `issued_at` | **ACCEPTED**（决议 2） | 均 `const "1.0"`；签名载荷必须含 `schema_version`（05 §1.5）；[ADR-003](../ADR/ADR-003-schema-version-and-issued-at.md) |
| `ADR-004` | T0 恢复边界：内部不可变计划 + 控制事件不入 E0–E3 + 不复用 Recovery 状态机 | **ACCEPTED**（决议 3/4/5/6） | 计划为内容寻址文件；`plan_id`+`plan_hash`；守卫三条件；确定性可重放；[ADR-004](../ADR/ADR-004-t0-recovery-boundary.md) |
| `ADR-005` | 失败迁移的审计写入语义 | **ACCEPTED**（决议 7） | 成功同事务；失败独立事务 `DENIED`；二次失败降级 stderr 并计缺口；[ADR-005](../ADR/ADR-005-failed-transition-audit.md) |
| `ADR-006` | T0 API 面与回环免认证 + 启动守卫 | **ACCEPTED**（决议 8） | `POST /recover` 404；非回环无 token 拒绝启动；已接受风险；[ADR-006](../ADR/ADR-006-t0-api-and-loopback-auth.md) |
| `ADR-007` | T0 最小工作台范围锁定为四视图 | **PROPOSED（保持；WP-13 前裁决）** | 依赖 `OQ-027`；防止范围蔓延；用户 2026-11-10 明确延后裁决，[ADR-007](../ADR/ADR-007-t0-workbench-scope.md) |

正式 ADR 文件已落地到 [`docs/ADR/`](../ADR/README.md)：`ADR-001`–`ADR-006` 为 `ACCEPTED`，`ADR-007` 为 `PROPOSED` 并保持到 `WP-13` 前裁决。内容与本表一致；两者冲突时以用户书面决议为准并立即报告。ADR 是决策记录，**不是 G0 通过**。

## 5. 冻结建议

### 5.1 已冻结（G0 基线）

| 项 | 依据 |
|---|---|
| 术语与基线口径（01） | 用户 2026-11-09 已确认 v1.0；2026-11-10 定版冻结 |
| 优先级/阶段正交、T0 能力下限、A1 使能项 | 用户 A1/D1 |
| E0–E3、验证级 L1–L3、架构层 L1–L6 | 策划书 §7.1/§9.1/§5.2 |
| Task/Node/Evidence 状态值与已授权迁移（含 `INVALIDATED`） | 附录 F + B1 + 决议 4/5/6 |
| 附录 C 的 20 条 FR 与 8 条 NFR 的编号、优先级、阶段 | 附录 C + 02 |
| REST 端点、错误码表、幂等规则（含 `dataset_ref` 对象化与 `/recover` 404） | 附录 E / TABLE 69 + 决议 8/9 |
| G6-T0 与 G6 完整版的分段 | 用户指令 |
| T0 工作包顺序与 `WP-R` 位置 | 用户 C1 |
| **五个契约的机器可读 schema + 正反例 + 校验器（⑨）** | 决议 2/9；`contracts/`；`docs/verification/g0/` |
| **签名载荷白名单（含 `schema_version`）** | 决议 2；05 §1.5 |
| **三组枚举按现值 v1.0 冻结（`kind` 7 / `l1-l3_status` 4 / `side_effect_class` 3）** | 2026-11-10 裁决；05 §1.6；`contracts/*.schema.json` |
| **依赖矩阵锁定为 `WP-01` 基线（17 个第三方包 + SQLite）** | 2026-11-10 裁决；07 `WP-01`；[`09_dependency_matrix.md`](../verification/g0/09_dependency_matrix.md) |
| **①–⑧ 与 ⑨ 统一 v1.0 + 冻结标记** | 2026-11-10 裁决；各文档头与版本记录 |

### 5.2 不冻结（需先裁决或需证据）

| 项 | 原因 |
|---|---|
| `HarnessEvent` Schema | 原文无 Schema；T2 才需要；不出 schema |
| `DomainPack` 字段级 Schema | 原文只有钩子；不出 schema |
| `ADR-007` 四视图范围 | 保持 `PROPOSED`，`WP-13` 前裁决；不随 G0 冻结为 `ACCEPTED` |
| 数据库 DDL/索引 | 随 v1.0 冻结为工程基线；实现期如需调整，必须记录理由并评估迁移 |
| 错误响应体结构 | 工程建议（`OQ-API-4`） |
| 并发 2 的验收阈值 | 未实测，不得写死 |
| 任何性能/资源数字 | 未实测 |

## 6. 本轮用户决议（已裁决）与落实位置

用户 2026-11-09 给出的 10 项决议，逐条落到文档；本表是索引，不是新决议。

| # | 决议 | 落实位置 |
|---|---|---|
| 1 | ① 冻结为 v1.0，作为 G0 基线术语 | 01（未改）；本文件 §5.1 |
| 2 | `NodeSpec`/`VerificationReport`/`CompletionCertificate` 补 `schema_version`；证书补 `issued_at`；FR-008 签名载荷必须含 `schema_version` | 05 §1.2/§1.5/§3/§5/§6；06 DDL 与 §5；`contracts/*.schema.json`；签名载荷白名单见 05 §1.5 |
| 3 | `RecoveryPlan` 为 T0 内部不可变产物：内容寻址文件、不入库、冻结写 `plan_hash`、`INVALIDATED→READY` 校验存在与 hash | 05 §9.3；06 §1.2/§1.3/§2；07 `WP-R`；`ADR-004` |
| 4 | 失效/恢复控制事件只写 `audit_log` + `evidence_invalidations`，不占 E0–E3；Gate 拒绝 stale，包内 stale 也不满足必检项 | 05 I-10/I-11、§4.5；06 `evidence_invalidations` DDL；07 `WP-08`；`ADR-004` |
| 5 | `INVALIDATED → READY` 存 `plan_id` + `plan_hash`，守卫校验存在、hash、先冻结；失败写 `DENIED` | 05 §9.3/§9.7；06 `nodes`/`audit_log` DDL；07 `WP-03`/`WP-R` |
| 6 | T0 不复用完整 Recovery 状态机；确定性、可重放 | 05 §9.5；07 `WP-R` 确定性约束；`ADR-004` |
| 7 | 失败迁移用独立事务写 `DENIED`；测试证明回滚后仍存在；二次失败降级 stderr 并计缺口 | 05 §9.7/I-14；06 §2；07 `WP-03`；`ADR-005` |
| 8 | T0 不开放 `POST /recover`（404）；回环免认证 + 非回环无 token 拒绝启动；已接受风险 + 负例 | 06 §4.1/§4.6；07 测试矩阵与风险表；`ADR-006` |
| 9 | `dataset_ref` 统一对象形态；字符串 422 并指明期望；配 `ADR-002` | 05 §2.4；06 §4.2/§4.4；`contracts/taskspec.schema.json`；`ADR-002` |
| 10 | `C-002` 维持已接受（不补入、不引用）；`C-003` 不补入，赛事结论标“未独立核验”；均不阻塞 G0 | 本文件 §3 第 7/8 行；01 §2.2 保持原状 |

### 6.1 2026-11-10 补充裁决（已落地，无待确认）

| # | 裁决 | 落实位置 |
|---|---|---|
| 1 | Git 仅在本仓库 `git config --local` 设 `ResearchFlow Dev` / `dev@researchflow.local`；全局身份保持为空，不改全局 `.gitconfig` | `.git/config`（不入库）；`project_state.json` 的 `BLK-001` 置 `RESOLVED`；命令与结果见本轮交接 |
| 2 | DOCX 按**精确文件名**忽略（`/ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx`），不使用 `*.docx`；原文件不动、不改名、不移动 | `.gitignore`；`git check-ignore -v` 验证该文件被忽略、其他 docx 不受影响 |
| 3 | `kind`（7）/ `l1-l3_status`（4）/ `side_effect_class`（3）按 v1.0 现值冻结，保留“按 `MINOR` 可变”；依赖矩阵锁定为 `WP-01` 基线 | 05 §1.6；07 `WP-01`；`contracts/*.schema.json`；[`09_dependency_matrix.md`](../verification/g0/09_dependency_matrix.md) |
| 4 | `ADR-007` 保持 `PROPOSED`，到 `WP-13` 前裁决 | 本文件 §4；[ADR-007](../ADR/ADR-007-t0-workbench-scope.md)；[ADR 索引](../ADR/README.md) |

原 4 项已于 2026-11-09 完成，不再列为待确认：① §6 已加 ⑨；`ADR-001`–`ADR-006` 已落地；② `FR-008`、③ `US-T0-13` 已补 `schema_version`/`issued_at`；①/②/④ 的旧表述已同步。**G0 是否 PASS 由用户宣布，不在本表“待确认”范围。**

## 7. G0 状态声明

**G0 规格文档已按用户指令冻结 ≠ G0 门禁 PASS。**

| 项 | 状态 |
|---|---|
| ①–⑧ 文档 | 全部 **v1.0（G0 冻结，2026-11-10）**；① 的 v1.1 为候选期编号，已归并 |
| ADR | `ADR-001`–`ADR-006` ACCEPTED；`ADR-007` 保持 PROPOSED，`WP-13` 前裁决 |
| ⑨ 机器可读契约 | 5 份 schema（v1.0）+ 72 个正反例 + 校验器；`--selftest` 10/10 PASS、全量 72/72 PASS、exit 0（真实日志见 `docs/verification/g0/`） |
| 未决问题 | 30 项：15 已关闭 / 0 部分关闭 / 15 开放；**0 项阻塞 G0** |
| 2026-11-09 决议 | 10 项全部裁决并落地 |
| 2026-11-10 裁决 | 枚举冻结、依赖矩阵锁定、`ADR-007` 延后、Git/DOCX 处置；见 §6.1 |
| G0 门禁 | `NOT_STARTED`（**PASS 由用户宣布**，Agent 不写 PASS） |
| T0 | 未开始 |
| 业务代码 | 未开发 |
| commit | 本轮建立 G0 规格基线提交；提交结果以 `git log` 为准 |

只有用户书面宣布 G0 PASS 后，才允许进入 T0 业务代码开发。文档 v1.0 冻结与 ⑨ 属于 G0 基线，**不是 T0 实现，也不代替门禁判定**。

## 8. 文档包状态

| 编号 | 文件 | 状态 |
|---|---|---|
| ① | [01_BASELINE_AND_TERMS.md](01_BASELINE_AND_TERMS.md) | **v1.0（G0 冻结；取代 v1.1 候选期编号）** |
| ② | [02_REQUIREMENT_TRACEABILITY.md](../PRD/02_REQUIREMENT_TRACEABILITY.md) | **v1.0（G0 冻结；取代 v0.2）** |
| ③ | [03_PRD_T0.md](../PRD/03_PRD_T0.md) | **v1.0（G0 冻结；取代 v0.2）** |
| ④ | [04_ARCHITECTURE.md](../design/04_ARCHITECTURE.md) | **v1.0（G0 冻结；取代 v0.2）** |
| ⑤ | [05_CONTRACTS_AND_STATES.md](../design/05_CONTRACTS_AND_STATES.md) | **v1.0（G0 冻结；取代 v0.3）** |
| ⑥ | [06_DATA_AND_API.md](../design/06_DATA_AND_API.md) | **v1.0（G0 冻结；取代 v0.2）** |
| ⑦ | [07_T0_PLAN_AND_GATES.md](../design/07_T0_PLAN_AND_GATES.md) | **v1.0（G0 冻结；取代 v0.2）** |
| ⑧ | 本文 | **v1.0（G0 冻结；取代 v0.3）** |
| ⑨ | [contracts/](../../contracts/) | **v1.0（G0 冻结）**：5 schema + 72 例 + 校验器 |
| ADR | [docs/ADR/](../ADR/README.md) | 6 ACCEPTED + 1 PROPOSED（`ADR-007`，`WP-13` 前裁决） |

---

**标记：本文件是 G0 文档 ⑧ v1.0（G0 冻结），不是 G0 门禁 PASS。** 文档已按用户 2026-11-10 指令冻结；G0 是否 PASS 由用户宣布；未建 `.venv`、未写业务代码。