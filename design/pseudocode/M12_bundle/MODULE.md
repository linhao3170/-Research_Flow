# M12 · Evidence Bundle 与离线验签（P6）

> 阶段：P6「签名与离线凭证」｜日期：2026-11-11｜状态：**伪代码/设计件，不是实现**
> 覆盖：证据包 12 类文件、manifest 哈希、anchor_proof absent 语义、verify_bundle CLI、
> 固定检查顺序与退出码、五类负例
> 不覆盖：L1/L2/L3 重新验证、报告/证书签发（WP-11）、时间戳服务/外部锚定实现（OQ-P6-09）、
> 工作台展示（WP-13）
> 前置：M11 签名/信任锚伪代码可用；P5 Gate/L3 产物可导出；WP-12 落地
> 阶段约束（S0）：只写 `design/pseudocode/**`；不建环境、不跑测试、不改看板、不写业务代码

## 1. 目标

让凭证离开数据库和模型后，第三方只凭证据包 + 包外信任锚即可复核：

1. **包完整**：12 类必需文件齐全；缺件/多件/哈希不符可发现；
2. **内容可复算**：严格 JSON、payload_hash、chain_hash、Merkle 根、tree_size、规则版本、split manifest 内部哈希；
3. **签名可信**：Report/Certificate 的 Ed25519 签名只认包外信任锚；包内指纹声明只被比对；
4. **策略正确**：仅 VERIFIED、ID 贯穿、覆盖无缺口、T0 无 SPA、时间顺序合理；
5. **结果可判定**：固定检查顺序、fail-fast、退出码 ≥6 个不同值；**不统一返回 1**；
6. **边界诚实**：不重跑 L1/L2/L3，不生成新凭证，不把 anchor 缺失说成已锚定。

## 2. 文件

| 文件 | 内容 | 行数 | 状态 |
|---|---|---:|---|
| `verifier/bundle/packager.py` | 12 类文件生成、manifest、可选文件 absent、私钥/模型/DB 拒绝 | 871 | 完成（伪代码） |
| `verifier/bundle/verify_bundle.py` | 离线 CLI、10 阶段检查、退出码表、五类负例 | 2043 | 完成（伪代码） |

行数为物理行数。`packager.py` 871 行、`verify_bundle.py` 2043 行，按 PHASE_RULES §5 登记索引；
`verify_bundle.py` >1500 行，另在 §2.3 写职责单元与不拆理由，并登记 `OQ-P6-11`。

### 2.1 `packager.py` 函数索引（800–1500 行档）

| 符号 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `PackagerError` | 135 | 导出拒绝（BUNDLE_TAMPERED / SCHEMA_INVALID） | §9.5 |
| `BundleFileSpec` | 166 | 一类包文件的角色/路径/必需性/媒体类型 | §9.5 |
| `EvidenceEnvelope` | 233 | record + 内联 payload；重算 payload_hash | §9.5；M07 |
| `BundleInputs` | 256 | 导出最小输入集合 | §9.5 |
| `BundleExportResult` | 276 | 包目录、manifest 哈希、可选状态 | §9.5 |
| `_Entry` | 287 | 待写文件 + sha256 | §9.5 |
| `REQUIRED_BUNDLE_FILES` | 189 | 12 类必需文件（含 manifest 自身） | §9.5 |
| `OPTIONAL_BUNDLE_FILES` | 226 | anchor_proof / recheck_data | §9.5 “如有” |
| `plan_bundle` | 296 | 输入校验 + 规格选择 | §9.5；7.6 |
| `export_bundle` | 414 | 临时目录 → 写文件 → manifest → 原子 rename | §9.5 |
| `_render_file` | 486 | role → 字节（JCS/JSONL/工具/README） | §9.5 |
| `_build_manifest` | 536 | files/optional/counts/integrity_profile/tool | §9.5 |
| `compute_manifest_sha256` | 618 | manifest 原始字节哈希 | §9.5 |
| `_write_bytes` | 624 | 安全写 + fsync | §9.5 |
| `_fsync_directory` | 639 | 目录 fsync（Windows 跳过） | §9.5 |
| `_normalize_created_at` | 653 | UTC 时间规范化 | §9.5 |
| `_assert_anchor_proof_shape` | 670 | AnchorProof 七字段/类型 | 7.4 R04 |
| `_assert_claims_only` | 728 | 指纹声明只允许 key_id/key_fingerprint | 7.6 R04 |
| `_assert_no_forbidden_material` | 790 | 拒绝显式私钥/私钥种子/secret/PEM | 7.6 R02 |
| `assert_no_forbidden_material` | 824 | 公开材料扫描入口（verify_bundle 复用） | 7.6 R02 |
| `assert_no_pem_private_key` | 833 | 只查 PEM 私钥头（README） | 7.6 R02 |
| `assert_packager_boundary` | 852 | 12 类/11 哈希/禁止后缀静态检查 | §9.5 |

### 2.2 `verify_bundle.py` 函数索引（>800 行档）

| 符号 | 起始行 | 职责 | 依据 |
|---|---:|---|---|
| `ExitCodeInfo` | 190 | 退出码表行 | 本文件 §5 |
| `_CheckFailure` | 212 | 内部检查失败（check/exit/reason/field_path） | 本文件 §5 |
| `_UsageError` | 233 | CLI 用法错误 | 本文件 §5 |
| `CheckResult` | 238 | PASS/FAIL/SKIP 结果 | 本文件 §5 |
| `Outcome` | 253 | 退出码 + 检查列表 + 摘要 | 本文件 §5 |
| `_State` | 266 | 一次运行的只读视图 | 本文件 §3 |
| `_ArgumentParser` | 289 | 把 argparse exit(2) 收敛为返回值 | 本文件 §5 |
| `_build_parser` | 296 | CLI 参数 | 9.5 P0250 |
| `main` | 313 | CLI 入口 + 退出码表自检 | 本文件 §5 |
| `_run` | 349 | 10 阶段编排 + 异常映射 | 本文件 §3 |
| `_failed_outcome` | 423 | 已知异常 → Outcome | 本文件 §5 |
| `_emit` | 446 | 人读/JSON 输出 | 本文件 §6 |
| `_summary` | 484 | 脱敏摘要 | 本文件 §6 |
| `_anchor_status` | 507 | 从 manifest 读 anchor 状态 | §9.5 |
| `_phase_environment` | 522 | Python/禁止模块 | NFR-07 |
| `_phase_bundle_root` | 550 | 根目录/符号链接 | §9.5 |
| `_phase_trust` | 585 | 包外信任库加载 | 7.6 R04 |
| `_phase_manifest` | 618 | manifest 结构/12 类/计数/profile | §9.5 |
| `_phase_inventory` | 890 | 文件存在/路径/哈希/size/多出文件 | §9.5 |
| `_phase_parse` | 1005 | JSON/JSONL/payload 白名单/payload_hash/材料扫描 | 7.5；D.6 |
| `_phase_roots` | 1101 | chain/Merkle/tree_size/规则/划分哈希/proof | 7.3；9.3 |
| `_phase_signatures` | 1298 | Report/Cert Ed25519 + 指纹声明 | 7.5；7.6 |
| `_phase_policy` | 1398 | VERIFIED/ID/coverage/时间/SPA | 7.4；05 §5/§6 |
| `_phase_anchor` | 1525 | AnchorProof 验签或 ABSENT | 7.4/7.6 |
| `_read_bytes` | 1617 | 包内安全读 | §9.5 |
| `_read_json` | 1634 | 严格 JSON | D.6 |
| `_hash_file` | 1649 | 流式 sha256 | §9.5 |
| `_assert_relative_path` | 1666 | 拒绝绝对/../盘符/反斜杠；check 可选 | §9.5 |
| `_resolve_inside` | 1681 | realpath 不逃逸 | §9.5 |
| `_assert_within_root` | 1688 | commonpath 检查 | §9.5 |
| `_iter_files` | 1697 | 遍历文件/拒绝符号链接 | §9.5 |
| `_as_mapping` | 1725 | object 断言 | §9.5 |
| `_as_string` | 1732 | 非空 string 字段 | §9.5 |
| `_assert_no_forbidden_material` | 1747 | 复用 packager 扫描并映射为 4 | 7.6 R02 |
| `_validate_evidence_record` | 1761 | EvidenceRecord 字段/枚举/等级-写入者 | 05 §4 |
| `_validate_split_manifest` | 1838 | 六字段 + manifest_hash | 9.3；M06 |
| `_validate_merkle_proofs` | 1867 | root/tree_size/RFC9162/proofs | 7.3 |
| `_validate_trust_claims` | 1889 | claims_only/仅 key_id+fingerprint | 7.6 R04 |
| `_claim_map` | 1919 | key_id→fingerprint | 7.6 R04 |
| `_compute_chain_hash` | 1931 | P4 前像重算 chain_hash | M07；OQ-P4-02 |
| `_leaf_hash` | 1951 | `SHA-256(0x00 + chain_hash)` | RFC 9162 |
| `_node_hash` | 1956 | `SHA-256(0x01 + L + R)` | RFC 9162 |
| `_largest_power_of_two_less_than` | 1961 | RFC 9162 的 k | RFC 9162 |
| `_mth` | 1966 | MTH 递归 | RFC 9162 |
| `_compute_merkle_root` | 1977 | chain_hash 列表 → 根 | 7.3 |
| `_verify_inclusion` | 1982 | fn/sn 验证 | RFC 9162 §2.1.3.2 |
| `_decode_b64` | 2011 | anchor 签名 base64 严格解码 | 7.4 |
| `assert_exit_code_table` | 2027 | ≥6 值/不含 1/名称唯一 | 验收判据 3 |

### 2.3 `verify_bundle.py` 职责单元与“不拆”理由（>1500 行档）

**职责单元清单**（7 个，边界清晰）：

1. CLI/退出码（`main`、`_build_parser`、`assert_exit_code_table`）；
2. 运行编排/异常映射/输出（`_run`、`_failed_outcome`、`_emit`、`_summary`）；
3. 清单与文件完整性（`_phase_manifest`、`_phase_inventory` 及路径/哈希 helper）；
4. 内容解析与 record 校验（`_phase_parse` 及 `_validate_*`）；
5. 链/根复算（`_phase_roots` 及 Merkle/chain helper）；
6. 签名/策略/锚定（`_phase_signatures`、`_phase_policy`、`_phase_anchor`）；
7. 读取/路径/编码安全 helper。

**不拆理由**：`NFR-07` 要求证据包在无数据库环境独立验证，交付形态是**单文件 CLI**；
拆成多文件会让包内工具副本变大、引入包结构/导入路径/版本漂移问题，而验签器又不应执行包内代码。
本阶段保持单文件，用函数索引和 fail-fast 阶段划分控制复杂度。

**拆分方案（若用户要求）**：保留 `verify_bundle.py` 作为 CLI，把 3–6 拆到
`verifier/bundle/checks/{manifest,inventory,parse,roots,signature,policy,anchor}.py`，
单文件构建时再内联；该方案登记 `OQ-P6-11`，未裁决不阻塞 P6 验收。

## 3. 检查顺序（fail-fast）

| # | 阶段 | 退出码 | 主要检查 | 失败 reason 示例 |
|---:|---|---:|---|---|
| 1 | 环境 | 9 | Python ≥3.11；未加载 sqlite3/researchflow/sklearn/torch/joblib/requests 等 | `FORBIDDEN_DEPENDENCY_LOADED` |
| 2 | 包根 | 4 | 存在、目录、非符号链接 | `BUNDLE_NOT_FOUND` / `BUNDLE_ROOT_SYMLINK` |
| 3 | 信任锚 | 3 | 包外、非空、严格 JSON、可选钉死哈希、无包内自证 | `TRUST_STORE_INSIDE_BUNDLE` / `TRUST_STORE_EMPTY` |
| 4 | 清单 | 4 | 字段/12 类/11 哈希/计数/完整性 profile/不自哈希 | `REQUIRED_FILE_MISSING` / `MANIFEST_COUNTS_MISMATCH` |
| 5 | 文件 | 4 | 逐文件存在/路径/哈希/size；无多出文件；无符号链接 | `FILE_HASH_MISMATCH` / `EXTRA_FILE` / `PATH_ESCAPE` |
| 6 | 解析 | 4 | 严格 JSON；Report/Cert 白名单；evidence record/payload_hash；无重复 | `EVIDENCE_PAYLOAD_HASH_MISMATCH` / `PAYLOAD_UNKNOWN_FIELD` |
| 7 | 链/根 | 6 | event_seq/prev、chain_hash 重算、Merkle 根、tree_size、规则版本、split 哈希、inclusion proof | `EVIDENCE_CHAIN_HASH_MISMATCH` / `RULESET_HASH_MISMATCH` |
| 8 | 签名 | 5 | Report/Cert Ed25519；key_id/指纹；撤销/有效期；包内声明交叉核对 | `SIGNATURE_MISMATCH` / `KEY_REVOKED` |
| 9 | 策略 | 7 | 仅 VERIFIED；ID 贯穿；coverage 无缺口；时间顺序；T0 无 SPA | `REPORT_NOT_VERIFIED` / `COVERAGE_INCOMPLETE` |
| 10 | 锚定 | 8 | anchor 缺失=ABSENT；存在则验签 | `ANCHOR_CERT_HASH_MISMATCH` / `ANCHOR_SIGNATURE_INVALID` |

**顺序理由**：先建立信任锚，再读包；先验完整性，再验签名；**签名先于 final_state 策略**，
这样“改报告状态”会以签名失败（5）暴露，而不是被策略检查（7）掩盖。签名通过后仍非 VERIFIED 的
（例如内部人用受信 key 签了 PARTIAL）才由策略阶段拒绝（7）。

## 4. 证据包 12 类文件

| # | role | 路径 | 必需 | 被 manifest 哈希 | 来源 |
|---:|---|---|---|---|---|
| 1 | `bundle_manifest` | `bundle_manifest.json` | 是 | **否（自身）** | 9.5 |
| 2 | `task_spec` | `task_spec.json` | 是 | 是 | 9.5 |
| 3 | `graph` | `graph.json` | 是 | 是 | 9.5 |
| 4 | `evidence` | `evidence.jsonl` | 是 | 是 | 9.5 |
| 5 | `artifact_manifest` | `artifact_manifest.json` | 是 | 是 | 9.5 |
| 6 | `split_manifest` | `split_manifest.json` | 是 | 是 | 9.5 |
| 7 | `verification_report` | `verification_report.json` | 是 | 是 | 9.5 |
| 8 | `completion_certificate` | `completion_certificate.json` | 是 | 是 | 9.5 |
| 9 | `merkle_proofs` | `merkle_proofs.json` | 是 | 是 | 9.5 |
| 10 | `trusted_key_fingerprint` | `trusted_key_fingerprint.json` | 是 | 是 | 9.5 |
| 11 | `verify_bundle` | `verify_bundle.py` | 是 | 是 | 9.5 |
| 12 | `README` | `README.md` | 是 | 是 | 9.5 |
| 可选 | `anchor_proof` | `anchor_proof.json` | 否 | 存在时 | 9.5 “如有” |
| 可选 | `recheck_data` | `recheck_data.json` | 否 | 存在时 | 9.5 “必要” |

推导：9.5 的 14 项中，`anchor_proof` 明确“如有”、轻量复核数据是“必要”时才带；把两者作为可选，
其余 12 项为必需。`evidence.jsonl` 每行是 `{"record": EvidenceRecord, "payload": {...}}` 的**包信封**，
不是改冻结 schema；验签器据此重算 `payload_hash`。

## 5. Manifest 与自哈希

`bundle_manifest.json` 结构（JCS 字节，无多余空白）：

```json
{
  "bundle_format": "1.0",
  "created_at": "2026-11-11T08:00:00.000000Z",
  "task_id": "task_...",
  "report_id": "report_...",
  "cert_id": "cert_...",
  "manifest": {"path": "bundle_manifest.json", "self_hashed": false, "sha256_rule": "sha256(exact file bytes); reported by verifier, never embedded"},
  "files": [
    {"role": "task_spec", "path": "task_spec.json", "sha256": "<64-hex>", "size": 123, "media_type": "application/json", "required": true}
  ],
  "optional": {
    "anchor_proof": {"status": "absent", "reason": "NOT_PROVIDED"},
    "recheck_data": {"status": "absent", "reason": "NOT_PROVIDED"}
  },
  "counts": {"required_classes": 12, "required_present": 12, "hashed_in_manifest": 11, "required_hashed": 11, "optional_present": 0, "optional_absent": 2, "evidence_records": 17},
  "integrity_profile": {"jcs": "RFC8785", "evidence_envelope": "record+payload/v1", "chain_preimage": "RF-EVIDENCE-CHAIN\\x00v1\\x00 (P4 proposal; OQ-P4-02)", "merkle": "RFC9162"},
  "tool": {"name": "verify_bundle.py", "bundle_format": "1.0", "sha256": "<64-hex>"}
}
```

**自哈希不可能**：`sha256(bundle_manifest.json)` 无法写进同一个文件而不改变自身。
`files` 只列其余 11 个必需文件（+ 可选存在项）；整体清单哈希由导出器返回、由验签器重算并输出，
**不得**在包内写一个假 `manifest_hash` 冒充自哈希。

## 6. 输出与退出码

**人读输出**：bundle、manifest_sha256、report_id、cert_id、evidence_root、tree_size、anchor，
然后逐项 `[PASS]/[FAIL]`，最后 `RESULT: PASS/FAIL (exit N)`。
**JSON 输出**：`{"result","exit_code","checks":[...],"summary":{...}}`；不输出公钥/证据正文。

| code | 名称 | 含义 | 典型触发 |
|---:|---|---|---|
| 0 | `VERIFIED` | 全部检查通过 | 真包 + 正确外部信任锚 |
| 2 | `USAGE_ERROR` | 参数/用法错误 | 缺 `--trust-store`、未知参数 |
| 3 | `TRUST_ANCHOR_ERROR` | 信任锚不可用 | 信任库缺失/为空/在包内/哈希不符/未知 key |
| 4 | `BUNDLE_INTEGRITY_ERROR` | 包不完整或被改 | 缺 split_manifest、文件哈希不符、多出文件、JSON 非法、payload 哈希不符 |
| 5 | `SIGNATURE_ERROR` | 签名不可信 | 破签名、改报告状态、签名格式错、key 撤销/过期、指纹不符 |
| 6 | `ROOT_CONSISTENCY_ERROR` | 根/链/规则不一致 | 改证据记录、seq 断档、Merkle 根不符、tree_size 不符、规则版本不符 |
| 7 | `POLICY_ERROR` | 签名有效但不得作为完成凭证 | 非 VERIFIED、ID 不一致、覆盖缺口、T0 出现 SPA |
| 8 | `ANCHOR_ERROR` | AnchorProof 存在但无效 | anchor 签名错、certificate_hash 不符、anchor key 缺失/歧义 |
| 9 | `ENVIRONMENT_ERROR` | 离线环境不满足 | 依赖 DB/模型库、Python <3.11、内部异常 |

`assert_exit_code_table()` 要求：≥6 个不同值、名称唯一、**不含 1**。未预期异常统一 9；
`KeyboardInterrupt` 返回 130，不是验签结论。

## 7. 五类负例（必须逐条断言退出码）

| 负例 | 操作 | 期望退出码 | 期望 reason | 检测阶段 |
|---|---|---:|---|---|
| **改 payload** | 改 `evidence.jsonl` 某行 payload 内容，保留 record；**同步改 manifest 的 evidence 文件哈希**（manifest 无签名） | **4** | `EVIDENCE_PAYLOAD_HASH_MISMATCH` | 解析 |
| **换公钥** | 用攻击者 key 重签并替换包内指纹声明/证书指纹，**同步改 manifest 文件哈希** | **3** | `KEY_NOT_IN_TRUST_STORE` | 信任/签名 |
| **删 split_manifest** | 删除 `split_manifest.json`，不改 manifest | **4** | `REQUIRED_FILE_MISSING` | 清单/文件 |
| **改报告状态** | 把报告 `final_state` 改为 `PARTIAL`（或从 PARTIAL 改为 VERIFIED），**同步改 manifest 文件哈希** | **5** | `SIGNATURE_MISMATCH` | 签名 |
| **破签名** | 改 `signature` 最后一字节/截断 base64，**同步改 manifest 文件哈希** | **5** | `SIGNATURE_MISMATCH` / `SIGNATURE_BASE64_INVALID` | 签名 |

补充断言：

- 五类负例的退出码**不得是 1**，也不得全部相同；
- “删 split_manifest”必须断言 `field_path="split_manifest"` 或 `detail.missing_roles` 含该角色；
- “换公钥”必须断言没有读取包内 `public_key`（可用 monkeypatch/静态检查证明）；
- “改报告状态”若先触发 4（shape）说明白名单/枚举检查位置错了：报告状态是合法枚举，
  必须走到签名阶段，以 5 暴露；只有改成非法枚举才允许 4。

## 8. 信任边界与“不依赖数据库/模型”

| 参与方 | 能做什么 | 不能做什么 | 落点 |
|---|---|---|---|
| 导出器 | 读证据/报告/证书/公钥指纹声明，写包 | 写私钥/信任库/模型/DB；签名；改判定 | `packager.plan_bundle` |
| 离线验签器 | 读包 + 包外 trust store；验哈希/签名/根/策略 | 连数据库/模型/网络；读私钥；执行包内代码 | `verify_bundle` |
| 包内 `verify_bundle.py` | 被 manifest 哈希，供第三方参考 | 被当前验签器执行；作为信任源 | `_phase_inventory` |
| 包内指纹声明 | 声称 key_id→fingerprint | 构造信任；携带公钥 | `trust_store.assert_bundle_does_not_supply_trust` |

`_phase_environment` 显式拒绝 `sqlite3`、`researchflow`、`sklearn`、`torch`、`joblib`、`requests`、`pandas`、`urllib3`
已加载；`verify_bundle` 只导入标准库 + `cryptography` + M11 纯密码学模块。**包内工具副本不执行**：
第三方必须用外部发布/校验过的工具运行，包内副本只用于比对哈希。

**材料扫描范围（F1.2/F3）**：`plan_bundle` 扫描 `task_spec`、`graph`、`artifact_manifest`、
`split_manifest`、`merkle_proofs`、每条 `evidence[i].record` 与 `payload`、`report`、`certificate`、
`trusted_fingerprints`、`anchor_proof`、解析后的 `recheck_data`；README 只查 PEM 私钥头。
`verify_bundle._phase_parse` 同样扫描 `task_spec`、`graph`、`artifact_manifest`、`split_manifest`、
`merkle_proofs`、`evidence[i].record` 与 `payload`。**合法随机种子 `seed` 不在禁用集合内**；
禁止的是显式键名 `private_key`/`private_key_b64`/`private_key_seed`/`key_seed`/`secret`/`passphrase`
与 PEM 私钥文本。

## 9. 边界与已知限制

1. **不重跑 L1/L2/L3**：只验完整性、签名、根一致性；`split_manifest` 的 `manifest_hash` 会重算，
   但“划分是否真按该 seed 生成”属 L2/L3，P6 不判。
2. **manifest 本身没有签名**：它是完整性索引，不是信任根。攻击者可以重写 manifest 及其文件哈希；
   此时 report/cert 的签名仍保护 `final_state`/`evidence_root`/`ruleset_hash` 等关键字段。
   五类负例要到达签名/载荷检查，必须同步改 manifest 的对应文件哈希；否则会先触发
   `FILE_HASH_MISMATCH`（4）。这两种拒绝都是正确的，但负例必须明确自己测的是哪一层。
3. **split_manifest 未被报告/证书直接签名**：删除会被“必需文件”检查发现；若攻击者修改内容并
   同步重算 `manifest_hash` 与文件哈希，P6 无法发现（需要 L1/L2 重跑或把 split 哈希纳入签名载荷）。
   这是已知边界，登记 `OQ-P6-08`，不得声称“所有包内文件都被签名覆盖”。
4. **chain_hash 前像未冻结**（`OQ-P4-02`）：本工具按 M07 P4 提案重算，并在摘要标
   `chain_preimage=P4_PROPOSAL_V1`；前像变更必须升包格式版本，旧包不再通过新工具。
5. **anchor 缺失不是失败**：输出 `anchor=ABSENT`，仍可 PASS 完整性/签名/策略；
   不得写成“已外部锚定”。AnchorProof 存在但无效 → 8，不降级。
6. **信任库是快照**：签发后的撤销，离线旧快照不知道；必须重新分发信任库。信任库本身无签名，
   靠发布渠道 + `--trust-store-sha256` 钉死。
7. **同机管理员**可同时替换工具/信任库/包；本工具不承诺抵御本机 root（与 §7.7 一致）。
8. **`seed` 是合法随机种子**：`TaskSpec.parameters.seed` 与 `split_manifest.seed` 必须能通过
   `plan_bundle` 与 `verify_bundle`；材料扫描只拒绝显式私钥种子键名（`private_key_seed`/`key_seed`）
   与 PEM 头，**不得按裸 `seed` 键名或 64-hex 值猜私钥**。
9. **不生成新凭证**：不签报告/证书、不写证据/状态。

## 10. 验收对照

| 判据 | 落点 | 状态 |
|---|---|---|
| 12 类文件生成与 manifest 哈希 | `REQUIRED_BUNDLE_FILES`（12）/`_build_manifest`；本文 §4/§5 | 已定义，未执行 |
| manifest 不自哈希 | `BundleFileSpec.self_hashed=False`；`MANIFEST_SELF_HASHED`；§5 | 已定义，未执行 |
| anchor 缺失标 absent | `_build_manifest.optional`；`_phase_anchor`；§9.5 | 已定义，未执行 |
| CLI 命令与退出码表 | `main`/`_run`/`EXIT_CODE_TABLE`；§6；≥6 个不同值 | 已定义，未执行 |
| 五类负例各一条、写明期望退出码 | `NEGATIVE_TESTS.md` NEG-M12-01…05 | 判据已定义，未执行 |
| 不依赖 DB/模型 | `_phase_environment`；§8；NEG-M12-61/62 | 已定义，未执行 |
| 换公钥仍通过 = 失败 | `_phase_signatures` 只认 trust store；NEG-M12-02 | 已定义，未执行 |
| 缺 split_manifest 仍通过 = 失败 | `_phase_manifest`/`_phase_inventory`；NEG-M12-03 | 已定义，未执行 |
| 统一返回 1 = 失败 | `assert_exit_code_table()` 禁 1；NEG-M12-65 | 已定义，未执行 |
| 包内不得有私钥/信任库/模型/DB | `_assert_no_forbidden_material`/`_iter_files`；NEG-M12-41/66/67/70/72 | 已定义，未执行 |
| 合法 seed 不被误拒 | `plan_bundle` 不按裸 `seed` 拒绝；GUARD-M12-07 | 已定义，未执行 |

## 11. OPEN QUESTIONS（详见 `design/pseudocode/OPEN_QUESTIONS.md`）

| 编号 | 问题 | P6 临时处理 |
|---|---|---|
| `OQ-P6-07` | chain_hash 前像未冻结，verify_bundle 重算依赖 P4 提案 | 包格式 v1.0 固定 P4 提案；变更升格式版本 |
| `OQ-P6-08` | split_manifest 未被签名直接绑定 | 只查必需文件 + 内部 manifest_hash；修改后重算无法发现 |
| `OQ-P6-09` | AnchorProof 无 key_id，信任库如何选 anchor key | 要求信任库恰有一把 purpose=anchor 的 key |
| `OQ-P6-10` | 包内 `verify_bundle.py` 副本是否可执行 | 当前不执行；第三方用外部发布工具 |
| `OQ-P6-11` | verify_bundle.py 2043 行，是否拆分 | P6 保持单文件；拆分方案见 §2.3 |
| `OQ-P6-12` | bundle_manifest 自哈希不可能，是否加 detached `.sha256` | 当前只打印 manifest 哈希；不写包内假自哈希 |

## 12. 本阶段不做

- 不重新验证 L1/L2/L3、不重跑 Gate、不生成新报告/证书；
- 不实现外部时间戳/第二存储锚定（只定义 AnchorProof 的 absent/present 语义与验签入口）；
- 不做数据库导入、不做包内工具执行、不做网络/证书链；
- 不建环境、不跑测试、不改看板、不写业务代码。本项目阶段只产出伪代码规格。