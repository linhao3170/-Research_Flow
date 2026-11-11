# M11 · NEGATIVE_TESTS — JCS、载荷、签名、密钥与信任锚负例（P6）

> 阶段：P6｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：M11 落地（WP-11）、G6-T0 离线验签准备
> 记录要求：命令、解释器、退出码、日志路径、运行时间；**P6 不得写成“已通过”**。
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`

## 0. 判定纪律

1. 每条负例必须断言**拒绝原因正确**：`error_code` + `reason` + `field_path`（或 `JcsError.reason`），
   不能只断言“抛异常/返回 False”。原因不符即失败。
2. 验签负例必须断言 `VerifyResult.ok is False` 且 `reason` 精确；不得只断言 `False`。
3. 信任锚负例必须断言 **没有回退到包内公钥**；只断言“失败”不够。
4. 私钥负例必须断言异常/日志/`repr` 中**不出现**私钥字节、seed、passphrase、完整路径；
   断言 `PrivateKeyHandle.__reduce__` 抛 `PRIVATE_KEY_EXPORT_FORBIDDEN`。
5. 正例守卫单独列出；不得用“正例通过”代替负例。
6. 不得修改 expected/reason/阈值来“修好”；原因不符即失败。
7. 所有测试数据用合成值；不得把真实私钥/令牌写入仓库或日志。

## A. JCS（RFC 8785）

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M11-01 | 重复键 | `parse_strict('{"a":1,"a":2}')` | `JcsError(reason=JCS_DUPLICATE_KEY)`；`field_path="a"`；不得后者覆盖 | D.6 P0576 |
| NEG-M11-02 | NaN | `parse_strict('{"x":NaN}')` | `JCS_NON_FINITE`；不得转 null/0 | D.6 P0576 |
| NEG-M11-03 | Infinity | `parse_strict('{"x":Infinity}')` | `JCS_NON_FINITE` | 同上 |
| NEG-M11-04 | 孤立代理项 | `canonicalize({"x":"\\ud800"})`（Python 字符串含 U+D800） | `JCS_INVALID_UNICODE`；不得静默替换为 U+FFFD | 7.5 P0176 |
| NEG-M11-05 | 超大整数 | `canonicalize({"x": 2**53})` | `JCS_UNSAFE_INTEGER`；不得悄悄转 float | JCS/I-JSON |
| NEG-M11-06 | 非 JSON 类型 | `canonicalize({"x": {1,2}})` | `JCS_UNSUPPORTED_TYPE`；field_path 指向 x | 7.5 |
| NEG-M11-07 | BOM | `parse_strict(b"\\xef\\xbb\\xbf{}")` | `JCS_INVALID_JSON`；不得忽略 BOM | 7.5 |
| NEG-M11-08 | 非字符串键 | `canonicalize({1: "x"})` | `JCS_KEY_NOT_STRING` | JCS |
| NEG-M11-09 | 嵌套过深 | 构造 65 层数组 | `JCS_DEPTH_EXCEEDED`；不得栈溢出 | 防御性 |
| NEG-M11-10 | 浮点非有限 | `canonicalize({"x": float("inf")})` | `JCS_NON_FINITE` | D.6 |
| NEG-M11-11 | 版本格式 | `select_spec(REPORT, "1")` / `"v1.0"` / `"01.0"` | `PAYLOAD_VERSION_FORMAT`（三者一致）；拒绝前导零 | 05 §1.2 |

## B. 载荷白名单与版本

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M11-12 | 未知字段 | 在合法 report 上加 `"debug": true` | `PAYLOAD_UNKNOWN_FIELD`；`detail.unknown_fields=["debug"]`；body 不含该字段 | 05 §1.5 规则 1 |
| NEG-M11-13 | 缺必填字段 | 删除 report.final_state | `PAYLOAD_FIELD_MISSING`；`detail.missing_fields` 含 final_state | 05 §1.5 |
| NEG-M11-14 | 缺 schema_version | 删除 report.schema_version | `PAYLOAD_FIELD_MISSING`；不得默认补 1.0 | 决议 2 |
| NEG-M11-15 | schema_version 不符 | report.schema_version="2.0"，build 用 "1.0" | `PAYLOAD_SCHEMA_VERSION_MISMATCH` | 05 §1.2 |
| NEG-M11-16 | 未知 MAJOR | `select_spec(REPORT, "2.0")` | `PAYLOAD_SCHEMA_MAJOR_UNSUPPORTED`；不得尝试解析 | 决议 2 |
| NEG-M11-17 | 未冻结 DC/SPA | `build_payload(DC, dc_obj)`（allow_proposed=False） | `PAYLOAD_NOT_FROZEN`；T0 不得签发 | 05/7.5；OQ-P6-02 |
| NEG-M11-18 | 非 VERIFIED 报告签名 | `assert_report_signable({... final_state: "PARTIAL"})` | `SigningRefused(SIGNING_REPORT_NOT_VERIFIED)`；`error_code=SIGNATURE_INVALID` | 用户硬要求；7.4 |
| NEG-M11-19 | 证书来自 PARTIAL 报告 | 报告 PARTIAL + 证书 VERIFIED | `SIGNING_REPORT_NOT_VERIFIED`；不得只看证书状态 | 7.4；05 §6 |
| NEG-M11-20 | 证书/报告 ID 不一致 | cert.report_id 改一位 | `SIGNING_CERT_REPORT_MISMATCH`；`field_path=report_id` | 05 §6.2 |
| NEG-M11-21 | 证书/报告根不一致 | cert.merkle_root 改一位 | `SIGNING_CERT_ROOT_MISMATCH` | 05 §6.2 |
| NEG-M11-22 | 规则版本不一致 | cert.ruleset_hash 与 report 不同 | `SIGNING_CERT_RULESET_MISMATCH` | 05 §6.2 |
| NEG-M11-23 | T0 出现 SPA | cert.skipped_nodes=["train_rf"] | `SIGNING_CERT_SPA_NOT_ALLOWED_T0` | schema `maxItems:0` |
| NEG-M11-24 | 算法不是 Ed25519 | cert.alg="RSA" | `SIGNING_CERT_ALG_UNSUPPORTED` | 7.4/附录 D.4 |
| NEG-M11-25 | coverage 缺键 | coverage 只有 required/passed | `PAYLOAD_COVERAGE_SHAPE_INVALID` | D.4 P0535 |
| NEG-M11-26 | coverage 负数 | missing=-1 | `PAYLOAD_COVERAGE_SHAPE_INVALID`；不得接受后重算 | D.4 |
| NEG-M11-27 | l3_coverage 越界 | 1.5 | `PAYLOAD_NUMBER_OUT_OF_RANGE` | schema [0,1] |
| NEG-M11-28 | skipped_nodes 重复 | ["a","a"] | `PAYLOAD_LIST_DUPLICATED` | schema uniqueItems |
| NEG-M11-29 | 数组被排序 | 两个仅数组顺序不同的 JSON 对象（如 `{"a":[2,1]}` vs `{"a":[1,2]}`），分别 `canonicalize` | 两者字节**必须不同**；相同 → 判失败；期望字节见 `ARRAY_ORDER_COUNTEREXAMPLE` | 7.5 P0175；验收判据 1 |
| NEG-M11-30 | signature 混入 body | 带 `signature` 的对象 build 后检查 `body` | `body` 不含 signature；若含 → 判失败 | 05 §1.5 |

## C. Ed25519 签名/验签

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M11-31 | key_id 不一致 | 用 key-B 签 key_id=key-A 的载荷 | `SignerError(SIGNING_KEY_ID_MISMATCH)`；不得签 | 7.6 |
| NEG-M11-32 | 换公钥验签 | 用另一把公钥验原签名 | `VerifyResult(ok=False, reason=SIGNATURE_MISMATCH)` | 7.5/7.6 |
| NEG-M11-33 | 签名 base64 非法 | `"not base64!!"` | `SIGNATURE_BASE64_INVALID` | 7.5 |
| NEG-M11-34 | 签名长度错 | 32 字节签名的 base64 | `SIGNATURE_LENGTH_INVALID` | RFC 8032 |
| NEG-M11-35 | 公钥长度错 | 16 字节公钥的 base64 | `PUBLIC_KEY_LENGTH_INVALID` | RFC 8032 |
| NEG-M11-36 | 公钥非合法点 | 32 个 0xFF | `PUBLIC_KEY_INVALID` 或 `SIGNATURE_MISMATCH`（点校验由 `cryptography` 决定；P6 只保证长度/规范 base64） | RFC 8032 |
| NEG-M11-37 | 算法大小写变体 | alg="ed25519" | `ALGORITHM_NOT_ED25519`；不得大小写归一 | 7.4 固定值 |
| NEG-M11-38 | expected_key_id 不符 | 载荷 key_id=A，expected=B | `KEY_ID_MISMATCH`；先于内容验签 | 7.6 |
| NEG-M11-39 | 改一个签名字节 | 翻转最后 1 bit | `SIGNATURE_MISMATCH` | 7.5 |
| NEG-M11-40 | 改载荷一个字段 | 改 l3_coverage 后沿用旧签名 | `SIGNATURE_MISMATCH`；证明字段被覆盖 | 05 §1.5 规则 4 |
| NEG-M11-41 | 截断签名 | 去掉末 4 字符 | `SIGNATURE_BASE64_INVALID` 或 `SIGNATURE_LENGTH_INVALID`（按解码结果，二者必须其一） | 7.5 |
| NEG-M11-42 | 私钥进 repr | `repr(handle)` / `str(handle)` | 含 `REDACTED`；不含 seed/私钥 base64/文件路径 | 7.6 |
| NEG-M11-43 | pickle 私钥 | `pickle.dumps(handle)` | `PRIVATE_KEY_EXPORT_FORBIDDEN` | 7.6 |
| NEG-M11-44 | 日志含消息正文 | `signature_metadata()` 返回字段 | 只含 kind/key_id/哈希；不含 payload body/signature 全文 | 7.6 |
| NEG-M11-73 | 绕过 `assert_report_signable` 直接签 PARTIAL | 手工 `build_payload(REPORT, partial)` 后调用 `sign()` | `SignerError(SIGNING_REPORT_NOT_VERIFIED)`；不产生 base64 签名 | 用户硬要求；7.4 |
| NEG-M11-74 | 绕过 `assert_certificate_signable` 直接签非 VERIFIED 证书 | 手工 `build_payload(CERTIFICATE, cert)` 后调用 `sign()` | `SignerError(SIGNING_CERT_NOT_VERIFIED)`；不产生签名 | 7.4；05 §6 |
| NEG-M11-75 | T0 签冻结前协议 | 用 `allow_proposed=True` 构造 DC 载荷后 `sign()` | `SignerError(SIGNING_PAYLOAD_NOT_FROZEN)`；不产生签名 | OQ-P6-02 |
| NEG-M11-76 | 伪造 spec 加额外字段 | 自造 `PayloadSpec(frozen=True, fields=白名单+extra)` + `SigningPayload`，调用 `sign()` | `SIGNING_PAYLOAD_UNREGISTERED`；不产生签名；不得因 frozen=True 放行 | 05 §1.5 |
| NEG-M11-77 | 伪造 spec 用错域前缀 | 自造 `PayloadSpec(domain_prefix=RF-CERT-V1)` 签 Report，调用 `sign()` | `SIGNING_PAYLOAD_UNREGISTERED`；不产生签名 | 7.5 P0178 |

## D. 密钥生命周期

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M11-45 | 撤销后签发 | `keyring.revoke(k)` 后 `resolve_for_sign(k)` | `KEY_REVOKED` | 7.6 R05 |
| NEG-M11-46 | 撤销后验旧签名 | `resolve_for_verify(k, issued_at=撤销前)` | `KEY_REVOKED`；`detail.policy="REVOKE_ALL"`；不得按时间放行 | OQ-P6-05 |
| NEG-M11-47 | 过期 key 验签 | `issued_at > not_after` | `KEY_EXPIRED` | 7.6 |
| NEG-M11-48 | 未生效 key 验签 | `issued_at < not_before` | `KEY_NOT_YET_VALID` | 7.6 |
| NEG-M11-49 | RETIRED 仍签发 | `resolve_for_sign(retired)` | `KEY_NOT_ACTIVE` | 7.6 |
| NEG-M11-50 | 轮换空档 | 旧 key 退休早于新 key 生效 | `KEY_ROTATION_GAP` | 7.6 R05 |
| NEG-M11-51 | 重复撤销 | 同一 key 第二次 revoke | `KEY_ALREADY_REVOKED`；不得覆盖原因 | 7.6 R05 |
| NEG-M11-52 | 非 Verifier 读私钥 | role="executor" / env="executor" | `PRIVATE_KEY_ROLE_FORBIDDEN` | 7.6 R03 |
| NEG-M11-78 | 伪造 env_role 绕过角色检查 | `env_role="verifier"`，但真实 `RF_PROCESS_ROLE` 未设置或为 `executor` | `PRIVATE_KEY_ROLE_FORBIDDEN`；`field_path=RF_PROCESS_ROLE` | 7.6 R03 |
| NEG-M11-53 | 私钥在 key_dir 外 | path 指向工作区 | `PRIVATE_KEY_PATH_OUTSIDE_KEY_DIR` | 7.6 R03 |
| NEG-M11-54 | 私钥经符号链接 | key_dir 内 symlink 指向外部 | `PRIVATE_KEY_PATH_SYMLINK` | 7.6 R03 |
| NEG-M11-55 | Windows ACL 未声明 | `acl_verified=False` | `PRIVATE_KEY_ACL_UNVERIFIED`；不得默认放行 | OQ-P6-06 |
| NEG-M11-56 | 私钥与 keyring 不匹配 | 用另一把 key 文件 | `PRIVATE_KEY_MISMATCH`；比较公钥/指纹 | 7.6 |
| NEG-M11-57 | 指纹自报 | record.fingerprint 与公钥重算不符 | `KEY_FINGERPRINT_MISMATCH` | 7.6 R04 |
| NEG-M11-58 | 同指纹两把 key | 两个 key_id 共用公钥 | `KEY_FINGERPRINT_DUPLICATED`；撤销会失效 | 7.6 |

## E. 信任锚

| ID | 目标 | 输入 / 操作 | 预期拒绝原因（必须断言） | 依据 |
|---|---|---|---|---|
| NEG-M11-59 | 信任库缺失 | 路径不存在 | `TRUST_STORE_MISSING` | 7.6 R04 |
| NEG-M11-60 | 空信任库 | `keys=[]` | `TRUST_STORE_EMPTY`；不得“没有 key 就跳过” | 7.6 R04 |
| NEG-M11-61 | 信任库在包内 | `--trust-store evidence_bundle/trusted_keys.json` | `TRUST_STORE_INSIDE_BUNDLE` | I-08；7.6 R04 |
| NEG-M11-62 | 信任库哈希不符 | `--trust-store-sha256` 给错值 | `TRUST_STORE_HASH_MISMATCH` | 7.6 R04 |
| NEG-M11-63 | 信任库含私钥 | key 条目加 `private_key` | `TRUST_STORE_UNKNOWN_FIELD` 或 `TRUST_STORE_HAS_PRIVATE_MATERIAL` | 7.6 R02 |
| NEG-M11-64 | 指纹与公钥不符 | fingerprint 改一位 | `TRUST_FINGERPRINT_MISMATCH` | 7.6 R04 |
| NEG-M11-65 | key 不在锚内 | 签名 key_id 未登记 | `KEY_NOT_IN_TRUST_STORE`；不得回退包内公钥 | 7.6 R04 |
| NEG-M11-66a | key_id 未登记但指纹命中另一 key | 声明 key_id=A（未登记），指纹=B（已登记） | `KEY_ID_MISMATCH` | 7.6 R04 |
| NEG-M11-66b | key_id 已登记但指纹不符 | 声明 key_id=A（已登记），指纹=B | `KEY_FINGERPRINT_MISMATCH` | 7.6 R04 |
| NEG-M11-67 | 证书指纹不符 | cert.key_fingerprint 改一位 | `KEY_FINGERPRINT_MISMATCH` | 05 §6.2 |
| NEG-M11-68 | 包内自带公钥 | `trusted_key_fingerprint.json` 出现 public_key | `BUNDLE_SUPPLIES_TRUST_MATERIAL` | I-08 |
| NEG-M11-69 | anchor key 歧义 | 信任库两把 purpose=anchor | `ANCHOR_KEY_AMBIGUOUS` | OQ-P6-09 |
| NEG-M11-70 | anchor key 缺失 | 无 purpose=anchor | `ANCHOR_KEY_MISSING` | OQ-P6-09 |
| NEG-M11-71 | 撤销 key 在锚内 | status=REVOKED 但无 revoked_at | `TRUST_REVOCATION_INCOMPLETE` | 7.6 R05 |
| NEG-M11-72 | 非 REVOKED 带撤销时间 | status=ACTIVE + revoked_at | `TRUST_REVOCATION_INCONSISTENT` | 7.6 R05 |

## F. 正例守卫（不得因收紧而误拒）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M11-01 | 数组保序 | `assert_array_order_is_preserved()` | `preserved=True`；`original == expected_original`；`sorted_variant == expected_sorted_variant` | 验收判据 1 |
| GUARD-M11-02 | UTF-16 键序 | `assert_utf16_sort_not_codepoint_sort()` | `differs=True`；`jcs_order[0] == "\U0001F600"` | RFC 8785 |
| GUARD-M11-03 | 白名单计数 | `whitelist_rows(REPORT)` / `whitelist_rows(CERTIFICATE)` | 13 / 15 行；每行 source 非空 | 验收判据 2 |
| GUARD-M11-04 | 数字规范化 | `canonicalize(1e20)` / `-0.0` / `1e-7` / `1e21` | `b"100000000000000000000"` / `b"0"` / `b"1e-7"` / `b"1e+21"` | JCS/ECMAScript |
| GUARD-M11-05 | 签名可重放验证 | 同 payload/key 两次 `sign` | 两次签名相同（Ed25519 确定性）；`verify` 均通过 | RFC 8032 |
| GUARD-M11-06 | RFC 8032 向量 | `check_rfc8032_vector_1()` | `VerifyResult(ok=True)` | RFC 8032 §7.1 |
| GUARD-M11-07 | 域分离 | 同 body 的 report/cert | `signing_bytes()` 不同；前缀分别为 `RF-REPORT-V1\0` / `RF-CERT-V1\0` | 7.5 P0178 |
| GUARD-M11-08 | 未知字段不误拒合法对象 | 合法 report/cert 经 `build_payload` | 不抛；body 键集合等于白名单 | 05 §1.5 |
| GUARD-M11-09 | 私钥句柄可签名 | 正确 keyring + 正确私钥 + 正确角色 | `sign()` 返回 64 字节签名的 base64；`verify` 通过 | 7.6 |

## G. 执行记录模板（落地阶段填写，P6 留空）

| ID | 命令 | 解释器 | 退出码 | 断言到的原因 | 日志路径 | 结论 |
|---|---|---|---|---|---|---|
| NEG-M11-01 | （待执行） | 3.11.16 | — | — | — | 未执行 |
| NEG-M11-18 | （待执行） | 3.11.16 | — | — | — | 未执行 |
| NEG-M11-31 | （待执行） | 3.11.16 | — | — | — | 未执行 |
| NEG-M11-46 | （待执行） | 3.11.16 | — | — | — | 未执行 |
| NEG-M11-61 | （待执行） | 3.11.16 | — | — | — | 未执行 |
| GUARD-M11-01 | （待执行） | 3.11.16 | — | — | — | 未执行 |