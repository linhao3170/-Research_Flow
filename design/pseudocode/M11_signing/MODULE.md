# M11 · 签名、密钥与信任锚（P6）

> 阶段：P6「签名与离线凭证」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：RFC 8785 JCS、四类签名载荷白名单与域分离、Ed25519 签名/验签、key_id/有效期/轮换/撤销、
> 包外信任锚与公钥指纹
> 不覆盖：L1/L2/L3 重新验证（P5 已定）、证据包布局与 CLI（M12）、证书签发编排（WP-11）、
> OS key store/HSM（部署，OQ-P6-05/06）、DC/SPA 契约冻结（T2）
> 前置：P5 已验收；M07 chain/merkle 前像提案可用；G0 契约与 05 §1.5 已冻结
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码

## 1. 目标

把“凭证能离开数据库和模型，被第三方离线复核”拆成五个可检查的部件：

1. **规范化**：同一语义对象在任何语言/平台得到同一字节串；数组不排序，数字按 ECMAScript；
2. **载荷**：只签白名单字段，版本化、域分离；未知字段 fail-closed；
3. **签名**：Ed25519（RFC 8032）；签名输入 = 域前缀 || JCS(body)；失败原因可逐条断言；
4. **密钥**：key_id、有效期、轮换、撤销；私钥只允许 Verifier 进程读取；
5. **信任锚**：验签只认包外 `trusted_keys.json`；证书自带指纹只被比对，不构造信任。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `verifier/crypto/jcs.py` | RFC 8785 规范化、严格 JSON 解析、数组保序/UTF-16 反例 | 704 | 完成（伪代码） |
| `verifier/crypto/payloads.py` | Report/Certificate/DC/SPA 白名单、域前缀、版本、签发前守卫 | 1055 | 完成（伪代码） |
| `verifier/crypto/ed25519_signer.py` | Ed25519 签名/验签、注册 spec 守卫、RFC 8032 向量 | 566 | 完成（伪代码） |
| `verifier/crypto/key_lifecycle.py` | KeyRecord/Keyring、有效期、轮换、撤销、真实环境角色检查 | 822 | 完成（伪代码） |
| `verifier/crypto/trust_store.py` | 包外信任库、指纹/有效期/撤销、包内自证拒绝 | 617 | 完成（伪代码） |

行数为物理行数（含空行）。`payloads.py` 1055 行、`key_lifecycle.py` 822 行，按 PHASE_RULES §5 第 2 档
分别在 §2.1/§2.2 登记函数索引；其余三个 ≤800 行，无需索引。

### 2.1 `payloads.py` 函数索引（800–1500 行档）

| 符号 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `PayloadError` | 132 | 载荷 shape/版本拒绝（SCHEMA_INVALID） | 05 §1.2/§1.5 |
| `SigningRefused` | 160 | 签发前策略拒绝（SIGNATURE_INVALID） | 7.4/7.6；用户硬要求 |
| `PayloadKind` | 184 | report/certificate/dc/spa | 7.5 四类对象 |
| `PayloadField` | 194 | 单字段白名单项（类型/格式/来源） | 7.4；05 §1.5 |
| `PayloadSpec` | 238 | 某类型某版本的完整协议 | 05 §1.5 |
| `_f` | 275 | 字段构造 helper | — |
| `REPORT_V1_FIELDS` | 306 | Report 13 字段白名单 | 7.4 R02；D.4；05 §1.5 |
| `CERTIFICATE_V1_FIELDS` | 327 | Certificate 15 字段白名单 | 7.4 R03；D.4；05 §1.5 |
| `DC_V1_FIELDS_PROPOSED` | 346 | DC T2 提案（frozen=False） | D.5；OQ-P6-02 |
| `SPA_V1_FIELDS` | 363 | SPA T2 提案（frozen=False） | D.5；OQ-P6-02 |
| `PAYLOAD_SPECS` | 378 | (kind, version) → spec | 05 §1.5；决议 2 |
| `select_spec` | 421 | 版本/MAJOR 选择，未知版本拒绝 | 05 §1.2 |
| `build_payload` | 478 | 从对象只取白名单字段；未知字段拒绝 | 05 §1.5 规则 1 |
| `_check_value` | 564 | 类型/数组/coverage/嵌套对象校验 | 7.4；D.6 |
| `_check_numeric_bounds` | 701 | 数值上下界 | 7.4 |
| `_check_format` | 717 | ID/哈希/UTC/枚举/ratio 形态 | D.6 |
| `parse_rfc3339_utc` | 787 | 契约时间解析（只接受 UTC） | D.6 |
| `SigningPayload` | 831 | 不可变签名体；`signing_bytes()` | 7.5 |
| `assert_report_signable` | 911 | 非 VERIFIED 不签 | 7.4；用户硬要求 |
| `assert_certificate_signable` | 936 | 证书/报告一致、T0 无 SPA、alg 固定 | 7.4；05 §6 |
| `whitelist_rows` | 1028 | 导出逐字段来源表，供文档/测试核对 | 验收判据 2 |

### 2.2 `key_lifecycle.py` 函数索引（800–1500 行档）

| 符号 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `KEY_ROLE_VERIFIER` | 74 | 唯一允许读私钥的进程角色 | 7.6 R03 |
| `DEFAULT_REVOCATION_POLICY` | 75 | 默认 `REVOKE_ALL` | OQ-P6-05 |
| `KeyLifecycleError` | 81 | 密钥生命周期拒绝（SIGNATURE_INVALID） | 7.6 |
| `KeyStatus` | 111 | ACTIVE/RETIRED/REVOKED | 7.6 R05 |
| `KeyRecord` | 120 | 公钥 + 有效期 + 状态；不含私钥 | 7.6 |
| `Revocation` | 229 | 只追加的撤销记录 | 7.6 R05 |
| `Keyring` | 261 | 公钥快照 + 撤销列表；签名/验签解析 | 7.6 |
| `Keyring.from_records` | 300 | 去重构造 | 7.6 |
| `Keyring.resolve_for_sign` | 333 | 只允许 ACTIVE/未撤销/有效期内 | 7.6 |
| `Keyring.resolve_for_verify` | 355 | 撤销优先；RETIRED 可验旧签名 | 7.6 R05 |
| `Keyring.rotate` | 400 | 旧 RETIRED + 新 key，禁止有效期空档 | 7.6 R05 |
| `Keyring.revoke` | 480 | 追加撤销，重复拒绝 | 7.6 R05 |
| `Keyring.to_trust_document` | 491 | 导出公开信任文档 | 7.6 R04 |
| `_assert_within_validity` | 524 | UTC 闭区间有效期检查 | 7.6 |
| `PrivateKeyHandle` | 554 | 不透明私钥句柄；repr 脱敏、禁 pickle | 7.6 R02/R03 |
| `assert_verifier_process` | 592 | 显式角色 + 真实 `RF_PROCESS_ROLE` 双检查 | 7.6 R03 |
| `assert_private_key_location` | 618 | 路径在 key_dir、无符号链接、避开禁止根 | 7.6 R03 |
| `load_private_key` | 688 | 角色/路径/权限/PEM/公钥对账 | 7.6 R02/R03 |

## 3. 信任边界与权限

| 参与方 | 能做什么 | 不能做什么 | 本模块落点 |
|---|---|---|---|
| Verifier（签名进程） | 读私钥、构造载荷、签名、验签自检 | 把私钥写日志/证据包/前端；跳过白名单 | `load_private_key`、`sign`、`build_payload` |
| Verifier（离线工具） | 读公钥/信任锚、验签、输出结果 | 读私钥、连数据库/模型/网络 | `trust_store`、`ed25519_signer.verify` |
| Bundle Exporter | 复制报告/证书/公钥指纹声明 | 复制私钥/信任库/模型/DB | `trusted_key_fingerprint` 只允许指纹 |
| Agent/Executor | 无 | 读私钥、签报告/凭证、改载荷 | 不提供任何入口 |
| 第三方复核者 | 提供包外 trust store、运行验签 | 用包内公钥自证 | `trust_store.assert_*` |

**私钥边界**：`PrivateKeyHandle` 只在 Verifier 进程内构造；`repr` 恒为 `<PrivateKeyHandle key_id=... private=REDACTED>`；
`__reduce__` 拒绝 pickle；不提供 `private_bytes()`；`load_private_key` 读取**真实进程环境**
`os.environ["RF_PROCESS_ROLE"]`，要求显式 `process_role` 与真实环境都为 `verifier`；`env_role`
只是可选一致性断言，不能替代真实环境。路径在 `key_dir` 内、无符号链接、不在仓库/工作区/证据包内；
POSIX 检查 mode，Windows 要求部署方 `acl_verified=True`。残余风险：同机管理员仍可读文件，见 `OQ-P6-05`。

## 4. 四类载荷白名单（逐字段指回 7.4）

### 4.1 `VerificationReport` v1.0（13 字段）

| # | 字段 | 7.4 / D.4 依据 | 05 §1.5 | 备注 |
|---:|---|---|---|---|
| 1 | `schema_version` | 7.4 未列；决议 2 补入 | ✓ | 必须参与签名；未知 MAJOR 拒绝 |
| 2 | `report_id` | 7.4 R02 `report_id`；D.4 P0529 | ✓ | `report_<uuid>` |
| 3 | `task_id` | 7.4 R02 `task_id`；D.4 P0530 | ✓ | `task_<uuid>` |
| 4 | `final_state` | 7.4 R02 `final_state`；D.4 P0531 | ✓ | 四态；仅 VERIFIED 可签 |
| 5 | `l1_status` | 7.4 R02 `l1/l2/l3_status`；D.4 P0532 | ✓ | PASS/FAIL/SKIP/NOT_RUN |
| 6 | `l2_status` | 同上；D.4 P0533 | ✓ | 同上 |
| 7 | `l3_status` | 同上；D.4 P0534 | ✓ | 同上 |
| 8 | `required_check_coverage` | 7.4 R02 `coverage`；D.4 P0535–P0537 | ✓ | required/passed/missing 三键 |
| 9 | `ruleset_hash` | 7.4 R02 `ruleset_hash`；D.4 P0538 | ✓ | 规则版本，必须进载荷 |
| 10 | `evidence_root` | 7.4 R02 `evidence_root`；D.4 P0539 | ✓ | 证据根，必须进载荷 |
| 11 | `l3_coverage` | 7.4 R02 未单列；D.4 P0540 | ✓ | [0,1] |
| 12 | `issued_at` | 7.4 R02 `issued_at`；D.4 P0541 | ✓ | UTC |
| 13 | `key_id` | 7.4 R02 `key_id`；D.4 P0542 | ✓ | 必须存在且未撤销 |

**明确排除**（不得静默纳入）：

| 7.4 字段 | 排除原因 |
|---|---|
| `gaps`、`attribution` | 冻结 schema 无该字段（`OQ-P5-02`）；作为结构化 sidecar，不进 1.0 载荷 |
| `report_hash` | 冻结 schema 无该字段；签名已覆盖载荷，再加自哈希会循环 |
| `signature` | 信封字段，签名不能覆盖自身 |

### 4.2 `CompletionCertificate` v1.0（15 字段）

| # | 字段 | 7.4 / D.4 依据 | 05 §1.5 | 备注 |
|---:|---|---|---|---|
| 1 | `schema_version` | 7.4 未列；决议 2 补入 | ✓ | 必须参与签名 |
| 2 | `cert_id` | 7.4 R03 `cert_id`；D.4 P0546 | ✓ | `cert_<uuid>` |
| 3 | `report_id` | 7.4 R03 `report_id`；D.4 P0547 | ✓ | 来源报告必须 VERIFIED |
| 4 | `final_state` | 7.4 R03 `final_state`；D.4 P0548 | ✓ | 仅 VERIFIED |
| 5 | `merkle_root` | 7.4 R03 `merkle_root`；D.4 P0549 | ✓ | 必须等于报告 evidence_root |
| 6 | `tree_size` | 7.4 R03 `tree_size`；D.4 P0550 | ✓ | ≥1；等于证据条数 |
| 7 | `ruleset_hash` | 7.4 R03 `ruleset_hash`；D.4 P0551 | ✓ | 与报告一致 |
| 8 | `code_hash` | 7.4 R03 `code_hash`；D.4 P0552 | ✓ | 执行代码快照 |
| 9 | `env_fingerprint` | 7.4 R03 `env_fp`；D.4 P0553 | ✓ | 字段名按 schema |
| 10 | `l3_coverage` | 7.4 R03 `l3_coverage`；D.4 P0554 | ✓ | [0,1] |
| 11 | `skipped_nodes` | 7.4 R03 `skipped_nodes`；D.4 P0555 | ✓ | T0 必须为空 |
| 12 | `alg` | 7.4 R03 `alg`；D.4 P0556 | ✓ | 固定 Ed25519 |
| 13 | `key_id` | 7.4 R03 `key_id`；D.4 P0557 | ✓ | 未撤销 |
| 14 | `key_fingerprint` | 7.4 R03 `key_fingerprint`；D.4 P0558 | ✓ | 必须命中包外信任锚 |
| 15 | `issued_at` | 7.4 R03 `issued_at`；D.4；决议 2 | ✓ | 不早于报告 issued_at |

**明确排除**：`task_id` 出现在 7.4 R03，但冻结 schema 与 05 §1.5 都没有该字段；本版按 schema 排除，
任务绑定走 `report_id`，登记 `OQ-P6-01`。`signature` 同样是信封字段。

### 4.3 DC / SPA（T2 提案，`frozen=False`）

- DC 14 字段（D.5 + 提案 `key_id`/`alg`）：`dc_id`、`node_type`、`code_hash`、`dependency_lock_hash`、
  `input_schema_hash`、`env_fingerprint`、`ruleset_hash`、`k_runs`、`run_fingerprints`、`output_hashes`、
  `eligible`、`expires_at`、`key_id`、`alg`；域前缀 `RF-DC-V1\0`。
- SPA 11 字段（D.5）：`spa_id`、`task_id`、`node_id`、`recovery_plan_id`、`dc_id`、`predecessor_hashes`、
  `artifact_hash`、`ruleset_hash`、`gate_result`、`skip_reason`、`verifier_key_id`；域前缀 `RF-SPA-V1\0`。
- D.5 没有 `schema_version`；版本由域前缀承载。`build_payload(..., allow_proposed=False)` 默认拒绝；
  T0 不得签发、不得写入证据包（`OQ-P6-02`）。

## 5. 为什么“按对象全部字段签名”是错的

1. **协议边界失控**：全部字段签名会把 `signature`、DB 读出的 `created_at`、UI 字段、缓存标记
   一并写进协议；这些字段与判定无关，却能让旧签名失效。
2. **加字段即改语义**：白名单外新增字段会被旧实现忽略、被新实现纳入，同一份“v1.0”对象
   在不同版本下验签结果不同。白名单 + 版本号把“哪些字节属于协议”冻结。
3. **跨版本重放**：没有 `schema_version` 参与签名与 MAJOR 比对，V1 载荷可被塞进 V2 验签器，
   V2 产物也可降级当 V1 使用（决议 2）。
4. **未知字段攻击面**：攻击者可加一个不影响业务、但改变载荷字节的字段，制造“同语义、不同签名”；
   也可利用实现 A 忽略、实现 B 纳入的差异绕过审计。
5. **顺序不稳定**：全部字段展开会诱导实现依赖 dict 插入顺序/数据库列顺序；JCS 只解决键序，
   不解决“哪些键该在”。本模块的 `build_payload` 从对象**只取** spec 字段，表外字段直接拒绝
   （`PAYLOAD_UNKNOWN_FIELD`），不静默丢弃、不静默纳入。

## 6. 为什么载荷必须包含规则版本、证据根、状态

| 必含项 | 去掉后的攻击 | 本模块落点 |
|---|---|---|
| `final_state` / `l1..l3_status` | PARTIAL 报告改写成 VERIFIED，旧签名仍“有效” | Report 白名单；`assert_report_signable` |
| `ruleset_hash` | 同一批证据换一套规则重新解释，旧签名无法说明按哪套规则判定 | Report/Certificate 白名单；M12 三方比对 |
| `evidence_root` / `merkle_root` | 替换证据集后复用结论 | Report/Certificate 白名单；M12 根一致性 |
| `schema_version` | 跨版本重放/降级 | 白名单 + `SUPPORTED_SCHEMA_MAJOR` |
| `key_id` / `key_fingerprint` | 无法表达轮换/撤销，验签方只能“试所有公钥” | 白名单 + trust_store |

`required_check_coverage` 进入载荷是为了让“必检缺口”也受签名保护；其算术与 `VERIFIED⇒missing==0`
由 Gate/验签策略检查，不在 `payloads.py` 重算（避免把 P5 的判定复制成第二套）。

## 7. 域分离与版本化

| 对象 | 域前缀 | 版本载体 | T0 |
|---|---|---|---|
| Report | `RF-REPORT-V1\0` | 字段 `schema_version` + 前缀 V1 | 启用 |
| Certificate | `RF-CERT-V1\0` | 字段 `schema_version` + 前缀 V1 | 启用 |
| DC | `RF-DC-V1\0` | 前缀 V1（D.5 无字段） | 不签发 |
| SPA | `RF-SPA-V1\0` | 前缀 V1（D.5 无字段） | 不签发 |

- 前缀是**字节**，拼在 JCS(body) 之前；不是 JSON 字段，不参与 JCS 排序。
- Report 与 Certificate 前缀不同，签名不可互换；即使两对象字段名相同也不会串。
- `select_spec` 只接受 `MAJOR == 1`；`MINOR` 升级必须显式登记新 spec，旧 spec 保留供历史校验。
- 未知字段/未知版本/未知 kind 一律拒绝，不猜测、不降级。

## 8. 密钥生命周期（7.6）

| 环节 | 本模块落点 | 关键拒绝 |
|---|---|---|
| 生成 | 不在本模块；`KeyRecord` 只描述公钥/指纹 | 指纹必须由公钥重算 |
| 存储 | `load_private_key`：角色、路径、符号链接、POSIX mode、Windows ACL 声明 | `PRIVATE_KEY_ROLE_FORBIDDEN` 等 |
| 信任 | `Keyring.to_trust_document()` 只导出公开部分 | 不导出私钥 |
| 轮换 | `Keyring.rotate`：旧 RETIRED + 新 key，禁止有效期空档 | `KEY_ROTATION_GAP` |
| 撤销 | `Keyring.revoke`：只追加，不可撤销“撤销” | `KEY_ALREADY_REVOKED` |
| 历史策略 | 默认 `REVOKE_ALL`：撤销 key 的全部历史签名拒绝 | `KEY_REVOKED` |

**为什么默认 REVOKE_ALL**：离线验签没有可信时钟，`issued_at` 是自报的；如果允许“撤销前签名仍有效”，
攻击者可以把伪造签名的 `issued_at` 改到撤销之前。要恢复历史验证必须引入外部时间锚或在线撤销状态，
不在 T0。该取舍见 `OQ-P6-05`。

## 9. 信任锚（7.6 R04）

1. `TrustStore.load` 只读包外 JSON；空库、包内库、哈希不符、未知字段、私钥字段全部拒绝。
2. `lookup(key_id, fingerprint, issued_at)`：key_id 必须命中；指纹必须一致；purpose 必须匹配；
   撤销优先；有效期按 `issued_at` 检查。
3. `assert_bundle_does_not_supply_trust`：包内 `trusted_key_fingerprint.json` 出现
   `public_key`/`private_key`/`private_key_seed`/`key_seed` 即拒绝（`BUNDLE_SUPPLIES_TRUST_MATERIAL`）；
   合法随机种子 `seed` 不在此列。
4. 证书的 `key_fingerprint` 只用于和信任库比对，**不用于构造信任**；包内公钥永远不参与验签。
5. 可选 `--trust-store-sha256`：把信任库文件哈希钉在命令行/发布说明，防替换信任库。

## 10. 失败码与拒绝点

| 错误码 | HTTP | 本模块典型 reason | 拒绝点 |
|---|---:|---|---|
| `SCHEMA_INVALID` | 422 | `JCS_DUPLICATE_KEY` / `JCS_NON_FINITE` / `JCS_INVALID_UNICODE` / `JCS_UNSAFE_INTEGER` / `PAYLOAD_UNKNOWN_FIELD` / `PAYLOAD_FIELD_MISSING` / `PAYLOAD_SCHEMA_VERSION_MISMATCH` / `PAYLOAD_NOT_FROZEN` | 解析/载荷构造 |
| `SIGNATURE_INVALID` | 422 | `SIGNING_PAYLOAD_UNREGISTERED` / `SIGNING_PAYLOAD_NOT_FROZEN` / `SIGNING_REPORT_NOT_VERIFIED` / `SIGNING_CERT_REPORT_MISMATCH` / `KEY_REVOKED` / `KEY_EXPIRED` / `SIGNATURE_MISMATCH` / `KEY_ID_MISMATCH` | 注册 spec/签发前守卫/验签 |
| `TRUST_ANCHOR_MISSING` | 503 | `TRUST_STORE_MISSING` / `TRUST_STORE_EMPTY` / `TRUST_STORE_INSIDE_BUNDLE` / `KEY_NOT_IN_TRUST_STORE` | 信任锚加载/查找 |

未新增注册表码：`SIGNING_*` 是 `SIGNATURE_INVALID` 的 reason，不是新错误码；是否补内部码见 `OQ-P6-04`。

## 11. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| JCS 数组保序显式反例 | `jcs.ARRAY_ORDER_COUNTEREXAMPLE`、`assert_array_order_is_preserved()`；`NEGATIVE_TESTS` GUARD-M11-01 | 已定义，未执行 |
| UTF-16 键序不是码点序 | `assert_utf16_sort_not_codepoint_sort()`；GUARD-M11-02 | 已定义，未执行 |
| 白名单逐字段指回 7.4 | §4.1/§4.2 表；`whitelist_rows()`；GUARD-M11-03 | 已定义，未执行 |
| 未知字段不静默纳入 | `build_payload` 的 `PAYLOAD_UNKNOWN_FIELD`；NEG-M11-12 | 已定义，未执行 |
| 非 VERIFIED 不签 | `assert_report_signable` / `assert_certificate_signable` / `sign` 守卫；NEG-M11-18/19/73/74 | 已定义，未执行 |
| 伪造 PayloadSpec 不签 | `sign` 校验 `PAYLOAD_SPECS` 身份相等；NEG-M11-76/77 | 已定义，未执行 |
| 真实环境角色检查 | `load_private_key` 读取 `os.environ["RF_PROCESS_ROLE"]`；NEG-M11-78 | 已定义，未执行 |
| 换公钥/自证被拒 | `trust_store`；NEG-M11-32/65/68 | 已定义，未执行 |
| 私钥不进日志/包/前端 | `PrivateKeyHandle.__repr__`/`__reduce__`；`assert_signer_boundary()`；NEG-M11-42/43/52 | 已定义，未执行 |
| 标准向量 | `RFC8032_VECTOR_1` / `check_rfc8032_vector_1()` | 已定义，未执行（WP-11） |

## 12. OPEN QUESTIONS（详见 `design/pseudocode/OPEN_QUESTIONS.md`）

| 编号 | 问题 | P6 临时处理 |
|---|---|---|
| `OQ-P6-01` | Certificate 7.4 列 `task_id`，冻结 schema 无 | 按 schema 排除；任务绑定走 report_id |
| `OQ-P6-02` | DC/SPA 无 `schema_version`，D.5 无 DC `key_id`/`alg` | 前缀承载版本；key_id/alg 为提案；`frozen=False` |
| `OQ-P6-03` | 非 VERIFIED 报告是否允许签名/持久化 | 按用户硬要求只签 VERIFIED；契约需裁决 |
| `OQ-P6-04` | 非 VERIFIED 签发拒绝无专用错误码 | 暂用 `SIGNATURE_INVALID` + reason |
| `OQ-P6-05` | 历史证书撤销策略/无可信时钟 | 默认 `REVOKE_ALL`；历史验证需外部时间锚 |
| `OQ-P6-06` | 信任库 JSON 格式/分发/Windows ACL | P6 内部格式 v1.0；ACL 由部署声明 |

## 13. 本阶段不做

- 不重新验证 L1/L2/L3（只验完整性、签名、根一致性）；
- 不生成新凭证、不写报告/证书、不签发；
- 不做密钥生成工具、OS key store/HSM、证书链/CA、时间戳服务；
- 不实现 DC/SPA 签发（T2）；
- 不建环境、不跑测试、不改看板、不写业务代码。本项目阶段只产出伪代码规格。