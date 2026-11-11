# M12 · NEGATIVE_TESTS — Evidence Bundle 与离线验签负例（P6）

> 阶段：P6｜状态：**判据定义，未执行**（S0：不建环境、不跑测试、不写业务代码）
> 执行阶段：WP-12 落地、G6-T0（T0 只要求真包通过 + 外部信任锚；五类负例矩阵完整版归 G6/T1）
> 解释器（届时必须）：`C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe`
> 命令模板：
> `& $py verify_bundle.py .\evidence_bundle --trust-store .\trusted_keys.json`
> 记录要求：命令、解释器、退出码、断言到的 reason、日志路径、运行时间；**P6 不得写成“已通过”**。

## 0. 判定纪律

1. 每条负例必须断言**退出码 + reason + field_path**；只断言“非零退出”判失败。
2. **不得统一返回 1**：每条负例额外断言 `exit_code != 1`，且 `exit_code` 在
   `EXIT_CODE_TABLE` 的 code 集合内；出现 1 即判失败。
3. 五类必测负例的退出码必须按下表；若实际退出码不同，先查“是不是别的检查先失败”，
   不得修改期望值迁就实现。
4. “换公钥”必须证明**没有读取包内公钥**：可用 monkeypatch 让包内
   `trusted_key_fingerprint.json` 带 `public_key` 字段，断言先以 3 拒绝
   （`BUNDLE_SUPPLIES_TRUST_MATERIAL`），而不是拿它验签。
5. “删 split_manifest”必须断言缺件角色；不得只断言“文件打不开”。
6. “改报告状态”必须断言 `SIGNATURE_MISMATCH`（5），证明状态字段在签名载荷内；
   若变成 4（shape）说明枚举检查位置错误，若变成 7 说明签名检查被策略前置，均判失败。
7. 正例守卫单独列出；真包通过不构成完成证据。
8. 不得修改 expected/阈值/负例样本来“修好”。
9. **B–F 段凡修改包内文件的负例，必须同步更新 `bundle_manifest.json` 对应条目的 `sha256` 与 `size`**；
   否则会先以 4 `FILE_HASH_MISMATCH`/`FILE_SIZE_MISMATCH` 拒绝，无法到达 6/5/7 的目标检查。
   负例必须写明自己测的是“完整性层”还是“签名/根/策略层”。

## A. 五类必测负例（P6 验收）

| ID | 负例 | 输入 / 操作 | 期望退出码 | 期望 reason（必须断言） | 依据 |
|---|---|---|---:|---|---|
| **NEG-M12-01** | **改 payload** | 改 `evidence.jsonl` 某行 `payload` 的一个字段，保留 `record.payload_hash` 不变；**同步改 manifest 的 evidence 文件哈希**（否则先触发 `FILE_HASH_MISMATCH`） | **4** | `EVIDENCE_PAYLOAD_HASH_MISMATCH`；`field_path=evidence[i].record.payload_hash` | 9.5 P0251 |
| **NEG-M12-02** | **换公钥** | 用攻击者 key 重签 report/cert，把 `trusted_key_fingerprint.json` 改成攻击者指纹，并**同时把 report/cert 的 key_id 改为未登记值**；同步改 manifest 文件哈希 | **3** | `KEY_NOT_IN_TRUST_STORE`；`field_path=key_id`；不得回退包内公钥 | 7.6 R04；I-08 |
| **NEG-M12-03** | **删 split_manifest** | 删除 `evidence_bundle/split_manifest.json`，不改 manifest | **4** | `REQUIRED_FILE_MISSING`；`field_path=split_manifest`（或 `detail.missing_roles` 含该角色） | 9.5 P0251 |
| **NEG-M12-04** | **改报告状态** | 把 `verification_report.json` 的 `final_state` 从 `VERIFIED` 改为 `PARTIAL`，保留签名；**同步改 manifest 的 report 文件哈希** | **5** | `SIGNATURE_MISMATCH`；`field_path=verification_report.signature`；不得是 7 | 7.4/7.5；05 §5.2 |
| **NEG-M12-05** | **破签名** | 把 report/cert 的 `signature` 最后一个 base64 字符改掉（或截断 4 字符）；**同步改 manifest 文件哈希** | **5** | `SIGNATURE_MISMATCH` 或 `SIGNATURE_BASE64_INVALID`；二选一必须精确 | 7.5 |

> 执行记录必须同时写：`exit_code ∈ {2,3,4,5,6,7,8,9}` 且 `!= 1`。
>
> **manifest 本身无签名**：01/02/04/05 若不更新 manifest 的对应文件哈希，会先在清单/文件层被
> `FILE_HASH_MISMATCH`（4）拒绝；那是完整性层，不是目标层。负例必须写明自己测的是哪一层，
> 不能把“因为文件哈希不符而失败”当成“签名检查抓住了改状态”。

## B. 包完整性 / manifest

| ID | 目标 | 输入 / 操作 | 期望退出码 | 期望 reason | 依据 |
|---|---|---:|---|---|---|
| NEG-M12-06 | 缺 completion_certificate | 删除 `completion_certificate.json` | 4 | `REQUIRED_FILE_MISSING` | 9.5 |
| NEG-M12-07 | 多出文件 | 包内放 `notes.txt`（不在 manifest） | 4 | `EXTRA_FILE`；`field_path=notes.txt` | 9.5 |
| NEG-M12-08 | 文件哈希不符 | 改 `README.md` 一个字符 | 4 | `FILE_HASH_MISMATCH`；`field_path=README` | 9.5 |
| NEG-M12-09 | 文件大小不符 | 在 JSON 尾部加空格但不改 manifest size | 4 | `FILE_SIZE_MISMATCH` 或 `FILE_HASH_MISMATCH`（先 size 则前者） | 9.5 |
| NEG-M12-10 | manifest 哈希自指 | 在 manifest 加 `manifest_sha256` 字段 | 4 | `MANIFEST_FIELDS_INVALID` | §5 |
| NEG-M12-11 | 计数不符 | counts.required_classes=11 | 4 | `MANIFEST_COUNTS_MISMATCH` | §5 |
| NEG-M12-12 | 未知角色 | files 加 role="extra" | 4 | `MANIFEST_ROLE_UNKNOWN` | §5 |
| NEG-M12-13 | 路径逃逸 | manifest 条目 path="../secret.json" | 4 | `PATH_TRAVERSAL` | 9.5 |
| NEG-M12-14 | 符号链接文件 | 用 symlink 替换 `task_spec.json` | 4 | `SYMLINK_FORBIDDEN` | 9.5 |
| NEG-M12-15 | 未知 bundle_format | 改 "2.0" | 4 | `BUNDLE_FORMAT_UNSUPPORTED` | §5 |
| NEG-M12-16 | 未知完整性 profile | merkle="perfect-tree" | 4 | `INTEGRITY_PROFILE_UNSUPPORTED` | §5 |
| NEG-M12-66 | 包内混入私钥文件 | 放 `id_ed25519.key` 到包目录 | 4 | `EXTRA_FILE`；若 packager 导出则 `PRIVATE_MATERIAL_IN_BUNDLE`/禁止后缀 | 7.6 R02 |
| NEG-M12-67 | 包内混入信任库 | 放 `trusted_keys.json` 到包目录 | 4 | `EXTRA_FILE`；若把它当 `--trust-store` 则 `TRUST_STORE_INSIDE_BUNDLE`(3) | 7.6 R04 |
| NEG-M12-68 | 包内混入模型二进制 | 放 `model.pkl` 到包目录 | 4 | `EXTRA_FILE`；packager 禁止 `.pkl` | NFR-07 |
| NEG-M12-71 | README 含 PEM 私钥头 | `README.md` 写入 `-----BEGIN PRIVATE KEY-----` | —（packager 拒绝） | `PRIVATE_MATERIAL_IN_BUNDLE`；README 普通文字里的 `private_key` 不拒绝 | 7.6 R02 |

## C. 解析 / 载荷白名单

| ID | 目标 | 输入 / 操作 | 期望退出码 | 期望 reason | 依据 |
|---|---|---:|---|---|---|
| NEG-M12-17 | 报告加未知字段 | `verification_report.json` 加 `"debug": true` | 4 | `PAYLOAD_UNKNOWN_FIELD`；`field_path=debug` | 05 §1.5 |
| NEG-M12-18 | 证书缺 schema_version | 删除 cert.schema_version | 4 | `PAYLOAD_FIELD_MISSING` | 决议 2 |
| NEG-M12-19 | evidence 行重复键 | 某行 JSON 出现两个 `record` | 4 | `EVIDENCE_JSON_INVALID` / `JCS_DUPLICATE_KEY` | D.6 |
| NEG-M12-20 | evidence 非 UTF-8 | 插入 `0xFF` 字节 | 4 | `EVIDENCE_NOT_UTF8` 或 `EVIDENCE_JSON_INVALID` | D.6 |
| NEG-M12-21 | 证据等级-类型不符 | E0 + kind=executor_launch | 4 | `EVIDENCE_LEVEL_KIND_INVALID` | 05 §4.5 |
| NEG-M12-22 | 证据 producer 不符 | E2 + producer=agent | 4 | `EVIDENCE_PRODUCER_INVALID` | 05 §4.5 |
| NEG-M12-23 | evidence_id 重复 | 两行同一 evidence_id | 4 | `EVIDENCE_ID_DUPLICATED` | 附录 D.6 |
| NEG-M12-24 | event_seq 重复 | 两行同一 seq | 4 | `EVIDENCE_SEQ_DUPLICATED` | 附录 F.1 |
| NEG-M12-25 | 证据记录多字段 | record 加 `debug` | 4 | `EVIDENCE_RECORD_FIELDS_INVALID` | schema additionalProperties=false |
| NEG-M12-26 | payload_hash 格式错 | 改成大写 hex | 4 | `EVIDENCE_HASH_INVALID` | D.6 |
| NEG-M12-70 | evidence payload 含 `private_key` | `evidence[i].payload` 加 `private_key` 字段 | 4（verify）；packager 直接拒绝 | `PRIVATE_MATERIAL_IN_BUNDLE`；不得因字段在 payload 内漏扫 | 7.6 R02 |
| NEG-M12-72 | 手工包 evidence payload 含 `private_key` | 绕过 packager 手工改包，同步改 manifest 文件哈希 | 4 | `PRIVATE_MATERIAL_IN_BUNDLE`；`field_path` 指向 payload | 7.6 R02 |
| NEG-M12-74 | task_spec 含私钥种子 | `parameters.private_key_seed` = 64-hex | 4（verify）；packager 直接拒绝 | `PRIVATE_MATERIAL_IN_BUNDLE`；**不能**把合法 `parameters.seed` 当私钥 | 7.6 R02 |
| NEG-M12-75 | split_manifest 含显式私钥键 | split 加 `key_seed` 或 `private_key` | 4（verify）；packager 直接拒绝 | `PRIVATE_MATERIAL_IN_BUNDLE`；合法 `seed` 不受影响 | 7.6 R02 |

## D. 链 / 根 / 证明

> 本段凡修改/删除包内文件，均须同步更新 manifest 对应 `sha256`/`size`；否则先以 4 被拒，到不了 6。

| ID | 目标 | 输入 / 操作 | 期望退出码 | 期望 reason | 依据 |
|---|---|---:|---|---|---|
| NEG-M12-27 | event_seq 断档 | 删除中间一条证据 | 6 | `EVENT_SEQ_GAP` | 7.3；附录 F.1 |
| NEG-M12-28 | prev_hash 断链 | 改一条 prev_hash | 6 | `EVIDENCE_CHAIN_BROKEN` | 7.3 |
| NEG-M12-29 | chain_hash 重算不符 | 改 record.kind 但保留 chain_hash | 6 | `EVIDENCE_CHAIN_HASH_MISMATCH` | 7.3；OQ-P4-02 |
| NEG-M12-30 | 报告 evidence_root 不符 | 改 report.evidence_root（不重签） | 6 | `EVIDENCE_ROOT_MISMATCH` | 7.4；05 §13 |
| NEG-M12-31 | 证书 merkle_root 不符 | 改 cert.merkle_root | 6 | `CERT_MERKLE_ROOT_MISMATCH` | 7.4 |
| NEG-M12-32 | tree_size 不符 | 改 cert.tree_size | 6 | `TREE_SIZE_MISMATCH` | 7.4 |
| NEG-M12-33 | 规则版本不一致 | cert.ruleset_hash 与 report 不同（先改再重签，确保不是 5） | 6 | `RULESET_HASH_MISMATCH` | 05 §1.5；I-06 |
| NEG-M12-34 | inclusion proof 缺失 | 删除 proofs 数组一项 | 6 | `INCLUSION_PROOFS_INCOMPLETE` | RFC 9162；7.3 |
| NEG-M12-35 | inclusion proof 伪造 | 改 audit_path 一项 | 6 | `INCLUSION_PROOF_INVALID` | RFC 9162 |
| NEG-M12-36 | split manifest 内部哈希不符 | 改 split.seed，保留 manifest_hash | 6 | `SPLIT_MANIFEST_HASH_MISMATCH` | 9.3；M06 |
| NEG-M12-37 | 证据顺序被重排 | 交换两行 evidence.jsonl | 6 | `EVENT_SEQ_GAP` 或 `EVIDENCE_CHAIN_BROKEN` | 7.3 |

## E. 签名 / 信任锚

> 本段凡修改包内文件，均须同步更新 manifest 对应 `sha256`/`size`；否则先以 4 被拒，到不了 5/3。

| ID | 目标 | 输入 / 操作 | 期望退出码 | 期望 reason | 依据 |
|---|---|---:|---|---|---|
| NEG-M12-38 | 信任库为空 | `{"schema_version":"1.0","keys":[]}` | 3 | `TRUST_STORE_EMPTY` | 7.6 R04 |
| NEG-M12-39 | 信任库在包内 | `--trust-store bundle/trusted_keys.json` | 3 | `TRUST_STORE_INSIDE_BUNDLE` | I-08 |
| NEG-M12-40 | 信任库哈希不符 | `--trust-store-sha256` 给错值 | 3 | `TRUST_STORE_HASH_MISMATCH` | 7.6 R04 |
| NEG-M12-41 | 包内自带公钥 | `trusted_key_fingerprint.json` 加 `public_key` | 3 | `BUNDLE_SUPPLIES_TRUST_MATERIAL` | I-08 |
| NEG-M12-42 | 证书指纹不符 | cert.key_fingerprint 改一位（不重签） | 5 | `KEY_FINGERPRINT_MISMATCH` | 05 §6.2 |
| NEG-M12-43 | key 已撤销 | 信任库对应 key status=REVOKED | 5 | `KEY_REVOKED` | 7.6 R05 |
| NEG-M12-44 | key 已过期 | 信任库 not_after 早于 issued_at | 5 | `KEY_EXPIRED` | 7.6 R05 |
| NEG-M12-45 | 指纹声明与锚不符 | 包内 claim 改成另一指纹 | 5 | `TRUSTED_FINGERPRINT_CLAIM_MISMATCH` | 7.6 R04 |
| NEG-M12-46 | 证书 alg 非 Ed25519 | cert.alg="RSA"（重签前先改 shape） | 5 | `ALGORITHM_NOT_ED25519` | 7.4 |
| NEG-M12-47 | 签名 base64 非法 | `"!!!"` | 5 | `SIGNATURE_BASE64_INVALID` | 7.5 |
| NEG-M12-48 | 签名长度错 | 32 字节签名 | 5 | `SIGNATURE_LENGTH_INVALID` | RFC 8032 |
| NEG-M12-73 | 保留受信 key_id 只换指纹 | cert.key_fingerprint 改成另一把已登记 key 的指纹，同步改 manifest；key_id 仍为受信值 | 5 | `KEY_FINGERPRINT_MISMATCH`；证明“换指纹”与“换 key_id”是两条独立拒绝路径 | 05 §6.2；7.6 R04 |

## F. 策略 / 锚定

> 本段凡修改包内文件，均须同步更新 manifest 对应 `sha256`/`size`；否则先以 4 被拒，到不了 7/8。

| ID | 目标 | 输入 / 操作 | 期望退出码 | 期望 reason | 依据 |
|---|---|---:|---|---|---|
| NEG-M12-49 | 非 VERIFIED 但有有效签名 | 内部人用受信 key 签 PARTIAL 报告与证书 | 7 | `REPORT_NOT_VERIFIED` | 7.4；用户硬要求 |
| NEG-M12-50 | 证书/报告 ID 不一致 | cert.report_id 指向另一报告（重签） | 7 | `CERT_REPORT_ID_MISMATCH` | 05 §6 |
| NEG-M12-51 | 覆盖有缺口 | 有效签名但 missing>0 | 7 | `COVERAGE_INCOMPLETE` | SEM-VR-02 |
| NEG-M12-52 | 覆盖算术错 | passed>required | 7 | `COVERAGE_ARITHMETIC_INVALID` | SEM-VR-01 |
| NEG-M12-53 | T0 出现 SPA | cert.skipped_nodes=["train_rf"]（重签） | 7 | `SPA_NOT_ALLOWED_T0` | schema maxItems=0 |
| NEG-M12-54 | 证书早于报告 | cert.issued_at < report.issued_at（重签） | 7 | `CERT_ISSUED_BEFORE_REPORT` | 05 §6.1 |
| NEG-M12-55 | anchor 存在但证书哈希不符 | 改 anchor.certificate_hash | 8 | `ANCHOR_CERT_HASH_MISMATCH` | 7.4 R04 |
| NEG-M12-56 | anchor 签名无效 | 改 proof_signature | 8 | `ANCHOR_SIGNATURE_INVALID` | 7.4 R04 |
| NEG-M12-57 | anchor 缺失 | manifest 标 absent，无文件 | **0**（不是负例失败） | 摘要 `anchor=ABSENT`；不得声称已锚定 | 7.6 R06 |
| NEG-M12-58 | anchor 标 absent 但文件存在 | 放 `anchor_proof.json` 同时 status=absent | 4 | `OPTIONAL_FILE_UNEXPECTED` | §5 |

## G. 环境 / CLI / “统一 1”守卫

| ID | 目标 | 输入 / 操作 | 期望退出码 | 期望 reason | 依据 |
|---|---|---:|---|---|---|
| NEG-M12-59 | 缺 --trust-store | 只给 bundle 路径 | 2 | argparse 用法错误 | 9.5 P0250 |
| NEG-M12-60 | 未知参数 | `--trust-store x --bogus` | 2 | 用法错误 | 9.5 |
| NEG-M12-61 | 离线环境加载 DB | 在进程内先 `import sqlite3` 再调用 `main()` | 9 | `FORBIDDEN_DEPENDENCY_LOADED` | NFR-07 |
| NEG-M12-62 | 离线环境加载模型库 | 先 `import sklearn` | 9 | `FORBIDDEN_DEPENDENCY_LOADED` | NFR-07 |
| NEG-M12-63 | Python 版本不足 | monkeypatch `sys.version_info=(3,10)` | 9 | `PYTHON_VERSION_UNSUPPORTED` | NFR-07 |
| NEG-M12-64 | 未预期异常 | monkeypatch 一个 helper 抛 RuntimeError | 9 | `INTERNAL_ERROR`；**不得 1** | §6 |
| NEG-M12-65 | **统一返回 1 守卫** | 对 A–F 所有负例收集退出码 | 全部 `!= 1` 且 ∈ {2,3,4,5,6,7,8,9} | 出现 1 → 判失败 | 验收判据 3/4 |

## H. 正例守卫（不得误拒）

| ID | 守卫目标 | 输入 / 操作 | 期望 | 依据 |
|---|---|---|---|---|
| GUARD-M12-01 | 真包通过 | 合法 bundle + 正确 trust store | `exit 0`；`summary.anchor=ABSENT`（无 anchor 时） | 9.5；G6-T0 |
| GUARD-M12-02 | anchor 存在且有效 | 合法 AnchorProof + anchor key | `exit 0`；`anchor=PRESENT` | 7.6 R06 |
| GUARD-M12-03 | 可选 recheck 存在 | 合法 `recheck_data.json` | `exit 0`；`optional_present` 含 recheck_data | 9.5 |
| GUARD-M12-04 | 无多余文件 | 包内只有 12 类 + 可选 | `exit 0`；`EXTRA_FILE` 不触发 | 9.5 |
| GUARD-M12-05 | JSON 输出可机读 | `--json` | stdout 是合法 JSON；含 `exit_code/checks/summary` | §6 |
| GUARD-M12-06 | 退出码表自检 | `assert_exit_code_table()` | 不抛；≥6 个不同非零值；不含 1 | 验收判据 3 |
| GUARD-M12-07 | 合法 seed 不被误判为私钥 | `task_spec.parameters.seed=42` + `split_manifest.seed=42`，走 `plan_bundle` | 不抛 `PRIVATE_MATERIAL_IN_BUNDLE`；`seed` 是合法随机种子 | 05 §2.1；M06 六字段 |

## I. 执行记录模板（落地阶段填写，P6 留空）

| ID | 命令 | 退出码 | 断言到的 reason | 日志路径 | 结论 |
|---|---|---:|---|---|---|
| NEG-M12-01 | `verify_bundle.py ...` | — | — | — | 未执行 |
| NEG-M12-02 | `verify_bundle.py ...` | — | — | — | 未执行 |
| NEG-M12-03 | `verify_bundle.py ...` | — | — | — | 未执行 |
| NEG-M12-04 | `verify_bundle.py ...` | — | — | — | 未执行 |
| NEG-M12-05 | `verify_bundle.py ...` | — | — | — | 未执行 |
| NEG-M12-65 | 汇总 | — | `!=1` | — | 未执行 |
| GUARD-M12-01 | `verify_bundle.py ...` | — | — | — | 未执行 |