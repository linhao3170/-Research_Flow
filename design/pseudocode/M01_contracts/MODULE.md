# M01 · 契约对齐（P1）

> 阶段：P1「契约对齐与配置基座」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：G0 冻结契约索引、ID/时间/哈希编码规则、错误码注册表、缺口登记、DomainPack 钩子签名
> 不覆盖：Schema 校验实现、持久化、状态机、签名、API 路由、数据表

## 1. 目标

把后续 9 个阶段会反复引用的“字面值”一次钉死，避免每个工作包各自解释：

1. 五份契约的字段**只有一份索引**（78 行），字段名/符号/必填性/枚举口径不再靠口头传递；
2. ID、UTC、SHA-256、JCS 的写法固定，签名/哈希/链校验不会各写一套；
3. 错误码只有一份注册表：附录 E.3 的 13 个码逐字保留，内部码补齐 T0 真实失败点；
4. 三类缺口（HarnessEvent、DC/SPA、9 类消息）登记在案，**明示“本阶段不定义”**，
   防止后续阶段“顺手”补字段；
5. DomainPack 只给五个钩子的**调用形状**（CANDIDATE），不冒充 v1.0。

## 2. 文件

| 文件 | 内容 | 状态 |
|---|---|---|
| `design/pseudocode/00_BASELINE/CONTRACT_INDEX.md` | 五份 schema 的 78 行字段索引 + 计数口径 | 完成 |
| `design/pseudocode/00_BASELINE/ENCODING_RULES.md` | 10 类 ID、UUID、UTC、哈希、JCS、创世 `prev_hash` | 完成 |
| `contracts/errors.py` | 13 个 E.3 码 + 14 个内部码（27 条） | 完成（注册表，无实现） |
| `contracts/encoding.py` | `new_id` / `new_attempt_id` / `now_utc` / `hash_bytes` / `hash_payload` / `canonical_bytes` 的签名与规则 | 完成（签名，无实现） |
| `contracts/gap_register.py` | 13 条缺口：OQ-CT-06、OQ-CT-07、DC、SPA、9 类消息 | 完成 |
| `contracts/domainpack_hooks.py` | 5 个钩子的签名/参数/返回类型/调用方，全部 CANDIDATE | 完成 |
| `MODULE.md`、`NEGATIVE_TESTS.md` | 模块说明与 15 条负例判据（P1 不执行） | 完成 |

## 3. 冻结边界（本模块不得做）

- 不重写、不改名、不“优化”`contracts/*.schema.json` 五份冻结 schema 的字段名/枚举/版本。
- 不为 HarnessEvent / DC / SPA / 消息信封写任何字段级定义、JSON Schema 或版本号。
- 不把 DomainPack 钩子签名标成 v1.0（`CONTRACT_VERSION = None`、`HOOK_STATUS = "CANDIDATE"`）。
- 不为迁就伪代码改字段名；不新增契约字段。
- 不动 `contracts/examples/` 下 72 个正反例，不新增/删除用例。
- 不改 05 §9 的状态枚举；本模块不涉及状态机。
- 不实现校验逻辑、不做签名、不建表、不写状态机。

## 4. 对外接口（供后续阶段引用）

| 接口 | 语义 |
|---|---|
| `errors.REGISTRY` / `errors.lookup(name)` | 错误码唯一来源；未注册码必须 `KeyError`，不得回退“通用错误” |
| `encoding.new_id(kind)` | 只对 task/evidence/report/cert 开放；其余 `UnfrozenIdKind` |
| `encoding.new_attempt_id(seq)` | `attempt_{seq:02d}`，≥2 位 |
| `encoding.now_utc()` | 微秒 + `Z` 的 UTC RFC3339 |
| `encoding.hash_bytes/hash_payload` | SHA-256 小写十六进制 |
| `encoding.canonical_bytes` | JCS；只排对象键，不排数组 |
| `gap_register.GAPS` | 13 条缺口；`disposition` 恒为“本阶段不定义” |
| `domainpack_hooks.HOOKS` | 5 个 CANDIDATE 钩子；`invoke()` 一律拒绝 |
| `domainpack_hooks.HOOK_STATUS` | 固定 `CANDIDATE`，不得改 |

## 5. 下游依赖

- **WP-02**：用 `errors` 的码 + `encoding` 的规则落地 API 422/幂等；模型层已存在，本模块不替换它。
- **WP-03 / WP-07**：`EVENT_SEQ_GAP` / `EVENT_SEQ_REGRESSION` / `EVIDENCE_CHAIN_BROKEN` 的抛出点；
  `chain_hash` 前像仍由 WP-07 定义（本阶段不补）。
- **WP-05**：只允许登记 DomainPack 钩子，不得调用；`profile_data` 等仍是 CANDIDATE。
- **WP-08**：Gate 用 `required_checks` × `REQUIRED_EVIDENCE_MISSING` / `RULESET_VERSION_MISMATCH`。
- **WP-12 / G6-T0**：`BUNDLE_TAMPERED` / `SIGNATURE_INVALID` / `TRUST_ANCHOR_MISSING`。

## 6. 验收（P1）

- `CONTRACT_INDEX.md` 字段行数 = 78（19+12+14+17+16），每字段一行。
- `errors.py` 覆盖附录 E.3 全部 13 个码，`http_status` 与 06 §4.4 一致。
- `domainpack_hooks.py` 五个钩子齐全，全部 CANDIDATE，无 JSON Schema、无版本号。
- `gap_register.py` 无 DC/SPA 字段定义（结构上无该槽位）。
- `NEGATIVE_TESTS.md` ≥8 条，且每条断言**拒绝原因**（错误码/字段路径/异常类），不是只断言“被拒绝”。

## 7. 已知缺口（不属本模块修复）

- OQ-CT-06（HarnessEvent）、OQ-CT-07（DomainPack 字段级）、OQ-CT-10（创世 `prev_hash`）仍开放。
- 06 §4.3 示例出现 `CERTIFICATE_NOT_AVAILABLE`，但附录 E.3/TABLE 69 无此码，§4.4 又声明“不新增错误码”；
  该冲突已由 P1 验收裁决关闭，见 §8 `OQ-P1-04`（不新增码）。
- `chain_hash` 前像、Merkle 构造、签名载荷实现均未在 P1 定义。

## 8. DECISIONS（P1 验收裁决 · 2026-11-11）

> 本节只记录裁决与落地位置，不改上游冻结件；原 OQ 编号保留以便追溯（PHASE_RULES §8）。
> 未列入本节的两条（`OQ-P1-03`、`OQ-P1-05`）已由用户处理，本模块不再记录。

### `OQ-P1-01` 首条 `prev_hash` 保持 PROPOSED

- **裁决**：保持 PROPOSED（`GENESIS_PREV_HASH_PROPOSED = "0" * 64`）；校验器只校形态，不比较创世值。
- **死线**：**WP-07 首次写证据之前**必须裁决；届时仍未裁决则不得开始写链。
- **约束**：未裁决前不得把“64 个 0”写成测试期望、API 文案或契约必填约束。
- **落地**：`00_BASELINE/ENCODING_RULES.md` §6；`contracts/encoding.py` 的 `GENESIS_PREV_HASH_PROPOSED`、`GENESIS_POLICY`、`accept_first_prev_hash()`。

### `OQ-P1-02` ID 前缀缺口（deferred）

- **裁决**：**不新增 UUID 型 ID**。`dc_` / `spa_` 随 T2 契约定义；`plan` 使用 `plan_hash`；`bundle` 是目录名，不是契约对象。
- **状态**：**deferred**（T2）；P1/P2 不生成、不预留、不实现。
- **约束**：`new_id` 继续只开放 task/ev/report/cert；`ENCODING_RULES.md` §1 的“未决/不存在”标注继续有效，不得因本裁决改成前缀。
- **落地**：`contracts/encoding.py` 的 `ID_SPECS`（DC/SPA/PLAN/BUNDLE 保持 `frozen=False`）；`contracts/gap_register.py` 的 `GAP-DC-01`、`GAP-SPA-01` 保持“本阶段不定义”。

### `OQ-P1-04` `CERTIFICATE_NOT_AVAILABLE` 不新增码

- **裁决**：**不新增第 14 个错误码**。该语义用 `STATE_TRANSITION_DENIED` + `detail.reason = "CERTIFICATE_NOT_AVAILABLE"` 表达，HTTP **409**。
- **约束**：E.3 的 13 条基线、状态码与语义均不改；该值不得作为独立 `error_code` 出现在 API 文档或测试断言中。
- **落地**：`contracts/errors.py` 的 `STATE_TRANSITION_DENIED` 条目下已加一行说明（2026-11-11）。

### `OQ-P1-07` `artifact_refs` 显式 null 非法

- **裁决**：**以 schema 为准，显式 `null` 非法**；不改 schema。
- **约束**：本阶段不改 `contracts/examples/`；`CONTRACT_INDEX.md` 第 43 行“必填：否”已表达“可缺省但不可为 null”。
- **待办**：**WP-02 复审时补 null 拒绝与反例**（新增 `evidencerecord.negative.*` 属 WP-02，不属 P1）。

### `OQ-P1-09` 内部码对外暴露口径

- **裁决**：内部码**全部 `user_visible=False`**；对外统一映射 **500/503**；**不进 API 文档**。
- **约束**：附录 E.3 的 13 条不在此列（保持原状态码与 `user_visible=True`）；对外仍用 E.3 码（如 `STATE_TRANSITION_DENIED`）。
- **落地**：`contracts/errors.py` 的 14 条内部码已调整（409→500；`user_visible` True→False；`PLAN_HASH_MISMATCH.surface` 改为 `INTERNAL`）；`REGISTRY_INVARIANTS` 新增一条。

### `OQ-P1-10` `chain_hash` 前像保持不补

- **裁决**：**保持不补**；由 WP-07 定义前像，并以篡改负例锁定。
- **约束**：P1/P2 不得自定义前像、不得在文档中写成“已定义”；`EVIDENCE_CHAIN_BROKEN` 只描述“重算不符”，不描述算法。
- **落地**：`00_BASELINE/ENCODING_RULES.md` §4 的 `[未决]` 标注；`contracts/errors.py` 的 `EVIDENCE_CHAIN_BROKEN` 触发点。