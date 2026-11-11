# CONTRACT_INDEX — 五份冻结契约字段索引（P1 基线）

> 状态：**P1 契约索引**｜生成日期：2026-11-11｜不是契约本体，不是新版本，不是 G0 变更。
> 依据：`contracts/*.schema.json`（G0 冻结 ⑨ v1.0）、`researchflow/contracts/models.py`（WP-02）、
> `docs/design/05_CONTRACTS_AND_STATES.md` §1/§2–§6/§9/§10/§12/§13、`docs/design/06_DATA_AND_API.md` §4.4。
> 本文件**只做索引，不重抄定义**：格式列写形态或 `$ref` 名，不复制正则；必填性以各 schema 的 `required` 为准。
> 不改字段名、不改枚举、不改 `schema_version`；`contracts/examples/` 下 72 个正反例未触碰。

## 1. 计数口径（决定“不多不少”）

- 一个字段 = 任意层级 `properties` 下的一个键，**含嵌套对象字段**（如 `dataset_ref.uri`）；每个字段恰好一行。
- 不计入：`$defs`（`sha256`、`nameVersion`、`hash64`、`rfc3339Utc`，它们是格式别名不是字段）、
  `required` 数组、`items` 子模式（数组元素不是具名字段）、`allOf`/`if`/`then` 条件块。
- 结果：`taskspec` 19 + `nodespec` 12 + `evidencerecord` 14 + `verificationreport` 17 + `completioncertificate` 16 = **78 行**。
- 条件约束（如 `level → producer/kind`）不另立行，只在该字段的“枚举/格式”列标注；语义层规则见 §4。

## 2. 字段索引（78 行）

| # | 字段名 | 所属 schema | models.py 符号 | 必填 | 枚举 / 格式 | schema_version |
|---:|---|---|---|---|---|---|
| 1 | `schema_version` | `taskspec.schema.json` | `TaskSpec.schema_version` | 是 | `const "1.0"`；未知 MAJOR 拒绝 | `1.0` |
| 2 | `task_id` | `taskspec.schema.json` | `TaskSpec.task_id` | 是 | `task_<uuid>`（小写十六进制 8-4-4-4-12） | `1.0` |
| 3 | `domain_pack` | `taskspec.schema.json` | `TaskSpec.domain_pack` | 是 | `name@MAJOR.MINOR.PATCH`（`$defs/nameVersion`） | `1.0` |
| 4 | `goal` | `taskspec.schema.json` | `TaskSpec.goal` | 是 | string，`minLength 1`；不参与判定 | `1.0` |
| 5 | `dataset_ref` | `taskspec.schema.json` | `TaskSpec.dataset_ref` | 是 | object，`additionalProperties:false`；字符串形态拒绝（ADR-002） | `1.0` |
| 6 | `dataset_ref.uri` | `taskspec.schema.json` | `DatasetRef.uri` | 是 | `local://…`；T0 断网，网络 URI 拒绝 | `1.0` |
| 7 | `dataset_ref.sha256` | `taskspec.schema.json` | `DatasetRef.sha256` | 是 | `$defs/sha256`（64 位小写十六进制） | `1.0` |
| 8 | `dataset_ref.license` | `taskspec.schema.json` | `DatasetRef.license` | 是 | 非空，`[A-Za-z0-9][A-Za-z0-9.+-]*` | `1.0` |
| 9 | `template_id` | `taskspec.schema.json` | `TaskSpec.template_id` | 是 | `$defs/nameVersion`；须在白名单注册表 | `1.0` |
| 10 | `parameters` | `taskspec.schema.json` | `TaskSpec.parameters` | 是 | object，`additionalProperties:true`（OQ-CT-08 未决） | `1.0` |
| 11 | `parameters.target` | `taskspec.schema.json` | `TaskParameters.target` | 否 | string，`minLength 1`；显式 `null` 拒绝 | `1.0` |
| 12 | `parameters.seed` | `taskspec.schema.json` | `TaskParameters.seed` | 否 | integer `≥0`；须进 Split Manifest | `1.0` |
| 13 | `parameters.test_size` | `taskspec.schema.json` | `TaskParameters.test_size` | 否 | number，开区间 `(0,1)` | `1.0` |
| 14 | `parameters.models` | `taskspec.schema.json` | `TaskParameters.models` | 否 | array[string]，`minItems 1`、`uniqueItems`、`^[a-z][a-z0-9_]*$` | `1.0` |
| 15 | `ruleset_hash` | `taskspec.schema.json` | `TaskSpec.ruleset_hash` | 是 | `$defs/sha256`；须与 Gate 规则版本一致 | `1.0` |
| 16 | `limits` | `taskspec.schema.json` | `TaskSpec.limits` | 是 | object，`additionalProperties:false` | `1.0` |
| 17 | `limits.wall_time_sec` | `taskspec.schema.json` | `TaskLimits.wall_time_sec` | 是 | integer，`>0` | `1.0` |
| 18 | `limits.max_workers` | `taskspec.schema.json` | `TaskLimits.max_workers` | 是 | integer，`1–2`（第一版并发上限 2） | `1.0` |
| 19 | `limits.max_memory_mb` | `taskspec.schema.json` | `TaskLimits.max_memory_mb` | 是 | integer，`>0` | `1.0` |
| 20 | `schema_version` | `nodespec.schema.json` | `NodeSpec.schema_version` | 是 | `const "1.0"` | `1.0` |
| 21 | `node_id` | `nodespec.schema.json` | `NodeSpec.node_id` | 是 | `[A-Za-z0-9][A-Za-z0-9_.-]*`；无 `node_` 前缀要求（05 §1.4） | `1.0` |
| 22 | `node_type` | `nodespec.schema.json` | `NodeSpec.node_type` | 是 | 点分小写：`^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$` | `1.0` |
| 23 | `template_id` | `nodespec.schema.json` | `NodeSpec.template_id` | 是 | `$defs/nameVersion` | `1.0` |
| 24 | `depends_on` | `nodespec.schema.json` | `NodeSpec.depends_on` | 是 | array[string]，`uniqueItems`，元素为 `node_id` 形态 | `1.0` |
| 25 | `input_refs` | `nodespec.schema.json` | `NodeSpec.input_refs` | 是 | array[`artifact://…`] | `1.0` |
| 26 | `parameters_hash` | `nodespec.schema.json` | `NodeSpec.parameters_hash` | 是 | `$defs/sha256` | `1.0` |
| 27 | `side_effect_class` | `nodespec.schema.json` | `NodeSpec.side_effect_class` | 是 | enum 3：`PURE_FUNCTION` / `PURE_ARTIFACT` / `SIDE_EFFECT` | `1.0` |
| 28 | `retry_policy` | `nodespec.schema.json` | `NodeSpec.retry_policy` | 是 | object，`additionalProperties:false` | `1.0` |
| 29 | `retry_policy.max_attempts` | `nodespec.schema.json` | `RetryPolicy.max_attempts` | 是 | integer，`≥1`（含首次） | `1.0` |
| 30 | `retry_policy.backoff_sec` | `nodespec.schema.json` | `RetryPolicy.backoff_sec` | 是 | number，`≥0` | `1.0` |
| 31 | `required_checks` | `nodespec.schema.json` | `NodeSpec.required_checks` | 是 | array[string]，`minItems 1`、`uniqueItems`、`^[a-z][a-z0-9_]*$` | `1.0` |
| 32 | `schema_version` | `evidencerecord.schema.json` | `EvidenceRecord.schema_version` | 是 | `const "1.0"` | `1.0` |
| 33 | `evidence_id` | `evidencerecord.schema.json` | `EvidenceRecord.evidence_id` | 是 | `ev_<uuid>` | `1.0` |
| 34 | `task_id` | `evidencerecord.schema.json` | `EvidenceRecord.task_id` | 是 | `task_<uuid>` | `1.0` |
| 35 | `node_id` | `evidencerecord.schema.json` | `EvidenceRecord.node_id` | 是 | `[A-Za-z0-9][A-Za-z0-9_.-]*` | `1.0` |
| 36 | `attempt_id` | `evidencerecord.schema.json` | `EvidenceRecord.attempt_id` | 是 | `attempt_[0-9]{2,}` | `1.0` |
| 37 | `event_seq` | `evidencerecord.schema.json` | `EvidenceRecord.event_seq` | 是 | integer，`≥1`；任务内单调递增且唯一 | `1.0` |
| 38 | `level` | `evidencerecord.schema.json` | `EvidenceRecord.level`（`EvidenceLevel`） | 是 | enum 4：`E0` / `E1` / `E2` / `E3` | `1.0` |
| 39 | `kind` | `evidencerecord.schema.json` | `EvidenceRecord.kind`（`EvidenceKind`） | 是 | enum 7：`agent_claim`、`tool_invocation`、`harness_trace`、`executor_launch`、`executor_process_exit`、`artifact_observed`、`verifier_recheck` | `1.0` |
| 40 | `producer` | `evidencerecord.schema.json` | `EvidenceRecord.producer` | 是 | `^[a-z][a-z0-9_]*$`；E0–E2 只能 `collector`，E3 只能 `verifier` | `1.0` |
| 41 | `timestamp` | `evidencerecord.schema.json` | `EvidenceRecord.timestamp`（`UtcTimestamp`） | 是 | `$defs/rfc3339Utc`：UTC，`Z` 或 `+00:00` | `1.0` |
| 42 | `payload_hash` | `evidencerecord.schema.json` | `EvidenceRecord.payload_hash` | 是 | `$defs/sha256` | `1.0` |
| 43 | `artifact_refs` | `evidencerecord.schema.json` | `EvidenceRecord.artifact_refs` | 否 | array[`artifact://…`]，`uniqueItems`；可缺省，不得为 `null` 语义外值 | `1.0` |
| 44 | `prev_hash` | `evidencerecord.schema.json` | `EvidenceRecord.prev_hash` | 是 | `$defs/hash64`（64 位小写十六进制）；首条值 OQ-CT-10 未决 | `1.0` |
| 45 | `chain_hash` | `evidencerecord.schema.json` | `EvidenceRecord.chain_hash` | 是 | `$defs/hash64`；由规范化记录计算（前像未冻结，见 §4） | `1.0` |
| 46 | `schema_version` | `verificationreport.schema.json` | `VerificationReport.schema_version` | 是 | `const "1.0"`；必须进入签名载荷 | `1.0` |
| 47 | `report_id` | `verificationreport.schema.json` | `VerificationReport.report_id` | 是 | `report_<uuid>` | `1.0` |
| 48 | `task_id` | `verificationreport.schema.json` | `VerificationReport.task_id` | 是 | `task_<uuid>` | `1.0` |
| 49 | `final_state` | `verificationreport.schema.json` | `VerificationReport.final_state` | 是 | enum 4：`VERIFIED` / `PARTIAL` / `FAILED` / `BLOCKED` | `1.0` |
| 50 | `l1_status` | `verificationreport.schema.json` | `VerificationReport.l1_status`（`CheckStatus`） | 是 | enum 4：`PASS` / `FAIL` / `SKIP` / `NOT_RUN` | `1.0` |
| 51 | `l2_status` | `verificationreport.schema.json` | `VerificationReport.l2_status`（`CheckStatus`） | 是 | enum 4：同 `l1_status` | `1.0` |
| 52 | `l3_status` | `verificationreport.schema.json` | `VerificationReport.l3_status`（`CheckStatus`） | 是 | enum 4：同 `l1_status`；须与 `l3_coverage` 一致 | `1.0` |
| 53 | `required_check_coverage` | `verificationreport.schema.json` | `VerificationReport.required_check_coverage` | 是 | object，`additionalProperties:false` | `1.0` |
| 54 | `required_check_coverage.required` | `verificationreport.schema.json` | `RequiredCheckCoverage.required` | 是 | integer，`≥0` | `1.0` |
| 55 | `required_check_coverage.passed` | `verificationreport.schema.json` | `RequiredCheckCoverage.passed` | 是 | integer，`≥0`；`≤ required`（SEM-VR-01） | `1.0` |
| 56 | `required_check_coverage.missing` | `verificationreport.schema.json` | `RequiredCheckCoverage.missing` | 是 | integer，`≥0`；`== required - passed`（SEM-VR-01） | `1.0` |
| 57 | `ruleset_hash` | `verificationreport.schema.json` | `VerificationReport.ruleset_hash` | 是 | `$defs/sha256` | `1.0` |
| 58 | `evidence_root` | `verificationreport.schema.json` | `VerificationReport.evidence_root` | 是 | `$defs/sha256`；Merkle 根 | `1.0` |
| 59 | `l3_coverage` | `verificationreport.schema.json` | `VerificationReport.l3_coverage` | 是 | number，闭区间 `[0,1]` | `1.0` |
| 60 | `issued_at` | `verificationreport.schema.json` | `VerificationReport.issued_at` | 是 | `$defs/rfc3339Utc` | `1.0` |
| 61 | `key_id` | `verificationreport.schema.json` | `VerificationReport.key_id` | 是 | `[A-Za-z0-9][A-Za-z0-9._:-]*` | `1.0` |
| 62 | `signature` | `verificationreport.schema.json` | `VerificationReport.signature` | 是 | base64，`minLength 4` | `1.0` |
| 63 | `schema_version` | `completioncertificate.schema.json` | `CompletionCertificate.schema_version` | 是 | `const "1.0"`；必须进入签名载荷 | `1.0` |
| 64 | `cert_id` | `completioncertificate.schema.json` | `CompletionCertificate.cert_id` | 是 | `cert_<uuid>` | `1.0` |
| 65 | `report_id` | `completioncertificate.schema.json` | `CompletionCertificate.report_id` | 是 | `report_<uuid>`；来源报告须为 `VERIFIED` | `1.0` |
| 66 | `final_state` | `completioncertificate.schema.json` | `CompletionCertificate.final_state` | 是 | `const "VERIFIED"` | `1.0` |
| 67 | `merkle_root` | `completioncertificate.schema.json` | `CompletionCertificate.merkle_root` | 是 | `$defs/sha256`；须等于报告 `evidence_root` | `1.0` |
| 68 | `tree_size` | `completioncertificate.schema.json` | `CompletionCertificate.tree_size` | 是 | integer，`≥1`；须等于证据条数 | `1.0` |
| 69 | `ruleset_hash` | `completioncertificate.schema.json` | `CompletionCertificate.ruleset_hash` | 是 | `$defs/sha256`；须与报告一致 | `1.0` |
| 70 | `code_hash` | `completioncertificate.schema.json` | `CompletionCertificate.code_hash` | 是 | `$defs/sha256` | `1.0` |
| 71 | `env_fingerprint` | `completioncertificate.schema.json` | `CompletionCertificate.env_fingerprint` | 是 | `$defs/sha256`；须与 E2 记录一致 | `1.0` |
| 72 | `l3_coverage` | `completioncertificate.schema.json` | `CompletionCertificate.l3_coverage` | 是 | number，闭区间 `[0,1]` | `1.0` |
| 73 | `skipped_nodes` | `completioncertificate.schema.json` | `CompletionCertificate.skipped_nodes` | 是 | array[string]，`maxItems 0`（T0 无 SPA） | `1.0` |
| 74 | `alg` | `completioncertificate.schema.json` | `CompletionCertificate.alg` | 是 | `const "Ed25519"` | `1.0` |
| 75 | `key_id` | `completioncertificate.schema.json` | `CompletionCertificate.key_id` | 是 | `[A-Za-z0-9][A-Za-z0-9._:-]*` | `1.0` |
| 76 | `key_fingerprint` | `completioncertificate.schema.json` | `CompletionCertificate.key_fingerprint` | 是 | `$defs/sha256`；须命中包外信任锚（I-08） | `1.0` |
| 77 | `signature` | `completioncertificate.schema.json` | `CompletionCertificate.signature` | 是 | base64，`minLength 4` | `1.0` |
| 78 | `issued_at` | `completioncertificate.schema.json` | `CompletionCertificate.issued_at` | 是 | `$defs/rfc3339Utc` | `1.0` |

## 3. 分契约计数

- `TaskSpec`：19 行（9 顶层 + `dataset_ref` 3 + `parameters` 4 + `limits` 3）。
- `NodeSpec`：12 行（10 顶层 + `retry_policy` 2）。
- `EvidenceRecord`：14 行（13 必填 + `artifact_refs` 1 可选）。
- `VerificationReport`：17 行（14 顶层 + `required_check_coverage` 3）。
- `CompletionCertificate`：16 行（全部必填）。
- 合计：**78 行**。表头 2 行（标题行 + 分隔行）不计入字段行。

## 4. 索引不承担的语义（不得声称“已在 schema 内”）

- 跨字段：`SEM-NS-01`（自依赖）、`SEM-VR-01`（覆盖率算术）、`SEM-VR-02`（`VERIFIED ⇒ missing==0`）由模型/语义层承担。
- 跨记录：`prev_hash == 上一条 chain_hash`、`event_seq` 无缺口/回退、`payload_hash` 与 payload 一致（Collector / Gate，WP-07）。
- 跨文档：`merkle_root == report.evidence_root`、`tree_size == 证据条数`、证书 `ruleset_hash` 与报告一致（Verifier 签发入口 / `verify_bundle.py`）。
- 签名覆盖：`schema_version`、规则版本、证据根、状态必须进入签名载荷（05 §1.5）；字段存在 ≠ 已被签名覆盖。
- `chain_hash` 前像组合未在 G0 冻结；P1 不补定义，留给 WP-07 并以负例锁定。

## 5. 版本

- 五份 schema 的 `schema_version` 一律 `"1.0"`（`const`）；本索引随 v1.0 冻结面，不引入 `1.1`、不改成员、不改字段名。
- 新增可选字段或枚举成员升 `MINOR`；删除/改类型/改语义升 `MAJOR`（05 §1.2/§11）。索引必须与 schema 同次更新，否则以 `validate_contracts.py` 结果为准并立即报告。