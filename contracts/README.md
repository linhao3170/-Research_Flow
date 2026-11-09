# contracts — G0 机器可读契约（⑨ v1.0）

> 冻结日期：2026-11-10｜状态：**G0 冻结**｜被取代版本：**无（首次编号 v1.0；原“G0 冻结候选”未编号）**｜G0 门禁 PASS 由用户宣布，本文不代替门禁判定。
> 状态：**G0 文档 ⑨ v1.0（G0 冻结）**；不是 T0 开发批准。
> 版本：全部 `schema_version = "1.0"`；三组枚举按 2026-11-10 现值冻结，保留“按 `MINOR` 可变”注记。术语基线 [01](../docs/G0/01_BASELINE_AND_TERMS.md) v1.0；字段说明 [05](../docs/design/05_CONTRACTS_AND_STATES.md) v1.0。
> 依据：用户 2026-11-09 决议 2、9，2026-11-10 枚举冻结裁决，与 §10 的 ⑨ 要求。

## 1. 文件

| 文件 | 契约 | 草案字段来源 |
|---|---|---|
| [`taskspec.schema.json`](taskspec.schema.json) | `TaskSpec` | 策划书附录 D.1；05 §2 |
| [`nodespec.schema.json`](nodespec.schema.json) | `NodeSpec` | 附录 D.2；05 §3；决议 2 补 `schema_version` |
| [`evidencerecord.schema.json`](evidencerecord.schema.json) | `EvidenceRecord` | 附录 D.3；05 §4 |
| [`verificationreport.schema.json`](verificationreport.schema.json) | `VerificationReport` | 附录 D.4；05 §5；决议 2 补 `schema_version` |
| [`completioncertificate.schema.json`](completioncertificate.schema.json) | `CompletionCertificate` | 附录 D.4；05 §6；决议 2 补 `schema_version`、`issued_at` |
| [`examples/`](examples/) | 正例 / 反例 / `manifest.json` | 全部为**合成样例**，不含真实实验数据 |

`HarnessEvent`、`DomainPack` **不冻结、不出 schema**（05 §7、§8；⑧ `OQ-CT-06`）。

## 2. 三层校验（`scripts/validate_contracts.py`，仅标准库）

| 层 | 内容 | 为什么需要 |
|---|---|---|
| `schema` | JSON Schema Draft 2020-12 结构校验 | 类型、必填、枚举、pattern、format、additionalProperties、if/then |
| `semantic` | JSON Schema 无法表达的跨字段不变量（`SEM-NS-01`、`SEM-VR-01/02`） | 自依赖、覆盖率算术、`VERIFIED ⇒ missing==0` |
| `json` | RFC 8259 层：重复键、`NaN`/`Infinity` | 05 §1.3 的 JSON 规则不能靠 Schema 关键字表达 |

反例必须**因为声明的原因**被拒绝：`manifest.json` 为每个反例记录 `layer` / `keyword` / `pointer`，校验器逐条核对，拒绝原因不匹配即 FAIL，不回填期望值。

## 3. 运行

```powershell
$py = 'C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe'
& $py scripts/validate_contracts.py --selftest   # 校验器自检 10 项
& $py scripts/validate_contracts.py              # lint + 72 个用例
```

退出码：`0` 全部 PASS；`1` 存在 FAIL；`2` 环境/用法错误。
最近一次真实运行见 [`docs/verification/g0/`](../docs/verification/g0/) 的 `01_selftest.log`、`02_validate_contracts.log`。

## 4. 契约之外、但属于同一冻结面的约束

- 签名载荷白名单必须包含 `schema_version`（决议 2；05 §1.5）。schema 只能约束字段存在，不能证明签名覆盖了它。
- 证据链 `prev_hash`/`chain_hash` 的一致性、`VerificationReport.evidence_root` 与证据集的对应、`CompletionCertificate.merkle_root` 与报告的一致性，都是**跨记录/跨文档**不变量，属 Collector/Verifier/`verify_bundle.py`，不在单文档 schema 内。
- `dataset_ref` 为对象形态（`uri`/`sha256`/`license`），字符串形态由 API 返回 422（决议 9、`ADR-002`）。

## 5. 版本与变更

- 本目录文档版本 **v1.0** 与 `schema_version = "1.0"` 同步起算（2026-11-10 G0 冻结）；新增可选字段或新增枚举成员升 `MINOR`，删除/改类型/改语义/删除枚举成员升 `MAJOR`（05 §1.2、§11）。
- 修改 schema 必须同步 `docs/design/05_CONTRACTS_AND_STATES.md` 字段表、`examples/` 与 `manifest.json`，并重跑校验器；不得只改一边。
- `examples/` 由 [`docs/verification/g0/build_examples.py`](../docs/verification/g0/build_examples.py) 生成（证据构造脚本，不是运行期代码）。
- 2026-11-10 冻结只加版本/冻结标记与枚举注记，**未改 schema 校验语义**；72 例校验结果见 `docs/verification/g0/` 的本轮日志。