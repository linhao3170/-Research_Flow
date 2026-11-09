# ADR-003：为三个契约补 `schema_version`、为证书补 `issued_at`

| 字段 | 内容 |
|---|---|
| 编号 | `ADR-003` |
| 状态 | **ACCEPTED**（用户 2026-11-09，决议 2） |
| 日期 | 2026-11-09 |
| 决策者 | 用户（书面决议 2） |
| 影响版本 | `NodeSpec` / `VerificationReport` / `CompletionCertificate` 均 `1.0` |
| 取代 | 无（原 v0.1 的 ADR 候选编号已顺延） |

## 1. 背景

策划书附录 D.2 与 D.4 的示例字段没有 `schema_version`；`CompletionCertificate` 也没有 `issued_at`。后果：

- 无法判断一份历史产物属于哪个契约版本，迁移与回放没有依据；
- 签名载荷若不覆盖版本，V1 载荷可能被重放到 V2 验签器，或 V2 产物被降级当 V1 使用；
- 证书缺签发时间，无法判断“证书是否在报告之后签发”。

## 2. 决策

1. `NodeSpec`、`VerificationReport`、`CompletionCertificate` 均新增 `schema_version`（必填，本版 `const "1.0"`）。
2. `CompletionCertificate` 新增 `issued_at`（必填，UTC RFC 3339）。
3. **签名载荷白名单必须包含 `schema_version`**；报告与证书各自使用域分离前缀（`RF-REPORT-V1\0` / `RF-CERT-V1\0`）。
4. 验签方必须比对本地支持的 `MAJOR`；未知 `MAJOR` 一律拒绝。MINOR 升级另发 schema，不在 `1.0` schema 内放行更高 MINOR。
5. `1.0` schema 用 `const "1.0"` 固化，作为后续 MINOR/MAJOR 的起点。

## 3. 后果

- DB 的 `nodes`/`reports`/`certificates` 增加 `schema_version` 列；`certificates` 增加 `issued_at` 列（⑥ §1.3）。
- ⑤ §1.5 固化载荷白名单；`I-06` 增补为 `I-13`。
- 负例：`completioncertificate.negative.1/2/3.json`、`verificationreport.negative.1/2/14.json`。
- 本轮同时把 ② `FR-008`、③ `US-T0-13` 的验收句补齐，避免散文与 schema 分叉。

## 4. 备选（未选）

| 方案 | 未选原因 |
|---|---|
| 不补版本，只靠证据包清单记版本 | 清单不在签名载荷内，可被替换；无法防跨版本重放 |
| 只在证书补，报告不补 | 报告是证书的来源，报告无版本使证书无法证明来源版本 |
| 用 `pattern` 允许 `1.x` | 与“未知版本必须拒绝”冲突；且 `1.x` 放行会让新增字段静默进入旧读取方 |

## 5. 验证

- 三个 schema 的 `schema_version.const = "1.0"` 由 `validate_contracts.py` 的 lint 强制（缺 `const`、缺 `required` 均 FAIL）。
- 证书 `issued_at` 缺失由 `completioncertificate.negative.3.json` 命中 `required @ $`。
- 签名载荷覆盖 `schema_version` 属实现约束，`WP-11` 的签名/验签测试必须包含“改版本号后验签失败”。
- 文档：⑤ §1.2/§1.5/§3/§5/§6、⑥ §5、② `FR-008`、③ `US-T0-13`。