# ENCODING_RULES — ID / 时间 / 哈希 / 规范化（P1 基线）

> 状态：**P1 编码规则**｜日期：2026-11-11｜适用范围：M01 契约层、M03 配置层，以及后续 WP-02–WP-12。
> 规范来源：`docs/design/05_CONTRACTS_AND_STATES.md` §1.3/§1.4、附录 D.6（P0574–P0579）、`contracts/*.schema.json` v1.0、`researchflow/contracts/models.py`。
> 本文件只钉“字面值与写法”，**不改任何 schema、不改字段名、不新增契约字段**。凡与 schema 冲突，以 schema + `validate_contracts.py` 为准并立即报告。
> 标记约定：`[冻结]` = G0 v1.0 已定；`[P1 约定]` = 本阶段为实现一致性钉死的写法，不改变 schema 合法性；`[未决]` = 不得当作契约使用。

## 1. ID 前缀表

十类对象全部列出。**表里出现某个“前缀”不等于它已冻结**：`node_`、`dc_`、`spa_`、`plan_`、`bundle_` 都没有被 05 §1.4 规定为前缀，本表把它们列出来正是为了钉死“不得使用”。

| 对象 | 前缀 / 形态 | 完整形态与来源 | 生成 | 唯一性 | 状态 / 依据 |
|---|---|---|---|---|---|
| Task | `task_` | `^task_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`（taskspec / evidencerecord / verificationreport） | `new_id("task")` | 全局唯一，删除后不可复用 | `[冻结]` 05 §1.4、附录 D.1/D.6 |
| Node | **无前缀** | `^[A-Za-z0-9][A-Za-z0-9_.-]*$`，示例 `train_random_forest` | 由 DAG Builder / 模板给出，**不得**用 `new_id` | 任务内唯一；不得含路径分隔符 | `[冻结]` 05 §1.4「Node 无前缀要求」、D.2 |
| Evidence | `ev_` | `^ev_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` | `new_id("ev")` | 全局唯一，不可复用 | `[冻结]` 05 §1.4、D.3 |
| Attempt | `attempt_` | `^attempt_[0-9]{2,}$`，示例 `attempt_02` | `new_attempt_id(seq)`（≥2 位零填充） | 每次真实执行唯一；重试不得复用旧 ID | `[冻结]` D.3 示例、06 §4.5 |
| Report | `report_` | `^report_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` | `new_id("report")` | 全局唯一 | `[冻结]` 05 §1.4、D.4 |
| Certificate | `cert_` | `^cert_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` | `new_id("cert")` | 全局唯一，只签发一次 | `[冻结]` 05 §1.4、D.4 |
| DC（确定性资格） | `dc_` **未规定** | 05 §1.4 仅写 `dc_id`，**无前缀规定、无字段级 Schema** | 不生成 | 未定义 | `[未决]` OQ-CT-06/07 同批；T2 前不得实现 |
| SPA（省略溯源） | `spa_` **未规定** | 05 §1.4 仅写 `spa_id`，**无前缀规定、无字段级 Schema** | 不生成 | 未定义 | `[未决]` 同上；T0 `skipped_nodes` 恒为空 |
| 恢复计划 | `plan_` **不是前缀** | `plan_id` + `plan_hash` 成对（05 §9.3 决议 5）；`plan_hash` = 内容寻址文件名 = `sha256(文件字节)`；`plan_id` 形态未定义 | 由 WP-R 生成 | 每个 `plan_hash` 对应唯一冻结文件 | `[部分冻结]` 决议 3/5、06 §1.1；`plan_id` 形态 `[未决]` |
| Evidence Bundle | `bundle_` **不存在** | 没有 `bundle_id` 契约；只有包内文件 `bundle_manifest.json` | 不生成 | 不适用 | `[未决]` 05/06 未定义包标识；P1 不新造 |

规则：

1. `new_id(kind)` 只对 `[冻结]` 且带 UUID 形态的五类开放：`task` / `ev` / `report` / `cert`（`attempt` 用序号函数）。其余 kind 必须抛 `UnfrozenIdKind`，**不得**返回临时前缀。
2. **不得**为 `node` 生成 `node_xxx`；`node_` 不是合法 node_id 前缀约束，只是名字里恰好出现下划线时仍受正则允许。索引/文档不得把 `node_` 写成契约前缀。
3. ID 是不透明标识：除本表前缀外，**不得**从 UUID 推断时间、机器、版本或顺序；排序一律用 `event_seq` / `created_at` 等显式字段。
4. 已删除/失效对象的 ID 不可复用（附录 D.6）。复用检测属持久层，不在编码函数内。

## 2. UUID 形态

- `[冻结]` 文本形态固定为 36 字符：`8-4-4-4-12`，**小写十六进制**，带连字符；仅此一种。
- `[冻结]` 必须拒绝：大写十六进制、无连字符的 32 hex、带花括号 `{...}`、`urn:uuid:` 前缀、带空白。
- `[P1 约定]` schema 的 `pattern` **没有**约束 UUID version/variant 位；因此生成器统一用 `uuid.uuid4()`（随机 v4），但校验器**不得**因 version 位不是 4 而拒绝——那会超出冻结 schema。
- `[P1 约定]` 生成后必须能通过对应 `pattern`；`new_id` 的实现若做了大小写转换即属违规（应直接生成小写）。

## 3. UTC RFC 3339 写法

- `[冻结]` 只接受 UTC：`Z` 或 `+00:00`；其他偏移（`+08:00`、`-05:00`）与无时区时间一律拒绝。
- `[冻结]` 正则与 `models.py` 的 `RFC3339_UTC_PATTERN` 同源：`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$`。**不在本文件重抄第二份正则**，实现必须引用同一常量。
- `[P1 约定]` 系统写入统一用**微秒精度 + `Z`**：`YYYY-MM-DDTHH:MM:SS.ffffffZ`（固定 27 字符，字典序 = 时间序）。
  - 读取方必须接受 0–9 位小数（schema 允许），**不得**因精度不同拒绝。
  - 不得输出 `+00:00` 与 `Z` 混用；内部一律 `Z`。
- `[P1 约定]` `now_utc()` 必须取 `datetime.now(timezone.utc)`；禁止 `datetime.utcnow()`（naive），禁止本地时间转换后再格式化。
- `[冻结]` 允许时钟偏差但必须记录；**顺序判定不得依赖 `timestamp`**，只能用 `event_seq`（05 §4.1、附录 F.1）。
- `[P1 约定]` 不得对时间做四舍五入到秒：截断会制造同秒并列，破坏“签发不早于证据”的可审计性。

## 4. 哈希算法与十六进制编码

- `[冻结]` 算法只有 **SHA-256**；输出 **64 位小写十六进制**（`[0-9a-f]{64}`）。
- `[P1 约定]` 实现形态固定为 `hashlib.sha256(data).hexdigest()`；禁止 `digest()` 后自行转大写、禁止 base64、禁止截断前缀。
  - 签名 `signature` 用 base64 是**另一个字段的编码**，不得与哈希混用。
- `[P1 约定]` 文件哈希必须以**二进制**读取（`open(path, "rb")`）。Windows 下文本模式会把 `\r\n` 规范化，导致哈希与另一台机器不一致；这是本项目的高频陷阱。
- `[P1 约定]` `payload_hash = sha256(canonical_bytes(payload))`；`canonical_bytes` 见 §5。
- `[未决]` `chain_hash` 的**前像组合**（哪些字段、按什么顺序、是否含 `prev_hash`、是否含 `chain_hash` 自身）G0 未冻结（05 §13 只写“由规范化记录计算”）。P1 **不补定义**，留给 WP-07，并必须用篡改负例锁定。
- `[P1 约定]` 哈希字段永远不写 `"0x"` 前缀、不写 `sha256:` 前缀；只是 64 个字符。

## 5. JCS 规范化

- `[冻结]` 使用 **JCS（RFC 8785）** 做签名/哈希前的规范化；`schema_version` 必须进入签名载荷（05 §1.5，I-13）。
- `[冻结]` **JCS 只排对象键，不排数组**：对象成员按键排序；数组元素**保持原顺序**，不得排序、去重或按值归一。
- `[P1 约定]` 输出为 UTF-8 字节，**无 BOM**，无多余空白；字符串转义按 JCS（不转义 `/`，控制字符用 `\uXXXX`）。
- `[P1 约定]` 排序是 **UTF-16 code unit** 序，不是 Unicode 码点序。**禁止用 `json.dumps(..., sort_keys=True)` 代替 JCS**：Python 按码点排序，遇到 astral 字符（如 emoji、部分 CJK 扩展）会与 JCS 产生不同字节序，签名跨实现即失败。
- `[P1 约定]` 数字序列化按 JCS/ECMAScript 规则；不做二进制浮点“美化”，不做四舍五入。契约中的金额/比例字段均为有限数。
- `[P1 约定]` **不做 Unicode 规范化**（不 NFC、不 NFD、不做 case folding）：规范化会改变字面值，等于改签名语义。
- `[P1 约定]` 只接受字符串键；对象键重复在解析层已被拒绝（见 §7），规范化层不得“后者覆盖前者”。

## 6. 首条 `prev_hash` 的当前约定（OQ-CT-10 未决）

- `[未决]` 05 §12 明确 `OQ-CT-10` 开放；schema 只要求 `hash64`（64 位小写十六进制），**不强制创世值**。
- `[P1 约定]` 当前**建议值**（不是契约）：`"0" * 64`，即 64 个 `0`。代码中只能以 `GENESIS_PREV_HASH_PROPOSED` 命名，并带 `OQ-CT-10` 标记。
- `[P1 约定]` 在 OQ-CT-10 关闭前：
  1. 校验器**只校验形态**，不得因首条 `prev_hash != 64 个 0` 而拒绝；
  2. 不得把“64 个 0”写进测试的期望拒绝原因、文档的必填约束或 API 错误文案；
  3. 第二条及以后必须满足 `prev_hash == 上一条 chain_hash`，这条与 OQ-CT-10 无关，必须校验。
- 关闭方式：由用户在 ⑧/后续阶段裁决并同步 05 §12、Collector 校验器、`WP-07` 负例；本阶段不改。

## 7. 禁止项与检查点（谁在什么位置拒绝）

| 禁止 | 检查点（拒绝位置） | 拒绝原因（必须可断言） |
|---|---|---|
| 对象键重复 | **解析层**：`parsing.loads_strict` 的 `object_pairs_hook` | `duplicate-key` + 键名；规范化层看不见重复键，不能靠它兜底 |
| `NaN` / `Infinity` / `-Infinity` | 解析层 `parse_constant`；规范化层再查一次（纵深防御） | `non-finite-number`；不得静默转 `null` |
| 非法 UTF-8 / 非法 JSON | 解析层 `json.JSONDecodeError` / `UnicodeDecodeError` 映射 | `invalid-json` / `invalid-encoding` + 行列或指针 |
| 孤立代理项（lone surrogate） | `canonical_bytes` 的 UTF-8 编码步骤 | `invalid-unicode`；`json.dumps` 默认 `ensure_ascii=True` 会掩盖该错误，禁止依赖 |
| 非字符串对象键 | 解析层（JSON 保证）与规范化层双查 | `non-string-key` |
| 大写/截断/带前缀哈希 | 模型层 `pattern` + 编码函数入口 | 字段路径 + `pattern` |
| 非 UTC 时间 | 模型层 `rfc3339Utc` + `_utc_rfc3339` | `field_path=timestamp/issued_at` |
| 数组被排序 | 规范化层单测：同元素不同顺序必须得到不同字节 | 断言 `canonical_bytes(a) != canonical_bytes(b)` |

## 8. 本文件不定义

- 不定义 `chain_hash` 前像、Merkle 叶子/树构造（WP-07 / WP-11）。
- 不定义 DC/SPA 的 ID 或字段（OQ-CT-06/07 同批；T2 前不实现）。
- 不定义 Evidence Bundle 的包标识或清单字段（05/06 未定义）。
- 不定义签名算法参数、密钥编码或信任锚存储（WP-11、I-08）。
- 不修改 `contracts/examples/` 的 72 个正反例，也不新增用例；用例变更属 WP 阶段。