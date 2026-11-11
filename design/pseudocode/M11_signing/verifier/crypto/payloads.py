"""MODULE: M11 · verifier/crypto/payloads.py — 签名载荷白名单、域分离与版本化（P6 伪代码）
阶段/追踪: P6「签名与离线凭证」｜FR-008、NFR-05、策划书 §7.4（TABLE 32）、§7.5（P0173–P0178）、
          05 §1.5（决议 2）与附录 D.4/D.5
FR/依赖: FR-008；依赖 jcs.py（规范化）；被 ed25519_signer.py、bundle.packager、verify_bundle 调用
不变量/错误码: 只签名白名单字段，不按对象全部字段展开；Report/Certificate 的 schema_version 必须进入载荷；
              Report 载荷必须含 ruleset_hash、evidence_root、final_state；未知字段 fail-closed；
              Report 与 Certificate 域前缀不同，签名不可互换。错误码：SCHEMA_INVALID（422）或
              SIGNATURE_INVALID（422，仅签发前策略拒绝）
写入者: **无**；纯函数，只构造 `SigningPayload`，不签名、不写文件、不写证据
状态: 伪代码；T0 只启用 Report/Certificate 1.0；DC/SPA 为 T2 提案，未冻结、不得签发

## 为什么“按对象全部字段签名”是错的

  1. **字段集合会被实现细节污染**：对象里可能混入 `signature`、数据库读出的
     `created_at`、前端展示用的 `display_name`、缓存标记。全部字段签名等于把这些
     与判定无关的东西写进协议；任何 UI 改动都会让旧签名失效。
  2. **加字段即改签名语义**：新增一个可选字段会自动进入载荷，旧验签器看不到它，
     新验签器却把它算进去——同一份“v1.0”对象在不同实现下验签结果不同。
     白名单 + 版本号把“哪些字节属于协议”显式冻结。
  3. **跨版本重放**：没有 `schema_version` 时，V1 的载荷可以被塞进 V2 验签器，
     或 V2 产物降级当 V1 使用。决议 2 要求 `schema_version` 进入载荷并由验签方比对 MAJOR。
  4. **未知字段静默纳入**：攻击者可以添加一个不影响业务、但会改变载荷字节的字段，
     制造“同一语义、不同签名”的分裂；也可以利用实现 A 忽略、实现 B 纳入的差异绕过审计。
  5. **对象顺序/序列化不稳定**：全部字段展开会诱导实现依赖 dict 插入顺序或数据库列顺序；
     JCS 只解决键序，不解决“哪些键该在”。

  因此本文件把字段集合写成**代码常量 + 版本键**（`PAYLOAD_SPECS[(kind, version)]`），
  签名/验签双方都从同一张表取字段；对象上出现表外字段一律拒绝，不静默丢弃、不静默纳入。

## 签名载荷必须包含规则版本、证据根、状态

  - **状态**（`final_state` / `l1_status` / `l2_status` / `l3_status`）：没有它，
    PARTIAL 报告可以被改写成 VERIFIED 而签名仍“有效”——状态就不再受签名保护。
  - **规则版本**（`ruleset_hash`）：没有它，同一批证据可以在另一套规则下重新解释，
    旧签名无法说明“当时按哪套规则判定”。
  - **证据根**（`evidence_root` / `merkle_root`）：没有它，签名只绑定结论、不绑定证据集，
    替换证据后结论仍可复用。
  - **schema_version**：没有它，无法阻止跨版本重放/降级；验签方必须比对本地支持的 MAJOR。
  - **key_id**：没有它，验签方只能“试所有公钥”，且无法表达撤销与轮换。

## 字段来源口径

  - `[7.4]`：策划书 §7.4 TABLE 32 原文出现；
  - `[D.4]`：附录 D.4 JSON 示例出现；
  - `[05 §1.5]`：G0 冻结的签名载荷白名单；
  - `[决议 2]`：用户 2026-11-09 补入 `schema_version`（ADR-003）；
  - `[提案]`：DC/SPA 的 T2 字段，**不在任何冻结 schema 中**，不得当成已冻结契约。

  Report 的 `gaps`、`attribution`、`report_hash` 出现在 7.4 表格，但**不在冻结 schema**
  （`OQ-P5-02`），因此不进入 1.0 载荷；`report_hash` 也不必要——签名已覆盖载荷。
  Certificate 的 `task_id` 出现在 7.4 表格，但冻结 schema 与 05 §1.5 都没有该字段，
  本文件按 schema 排除，任务绑定走 `report_id`（`OQ-P6-01`）。

## DC/SPA 的临时处理

  T0 不生成 DC/SPA（`feature_flags.dc_spa=false`，证书 `skipped_nodes=[]`）。
  D.5 没有 `schema_version`，也没有 DC 的 `key_id`/`alg`。本文件给出 T2 提案：
  版本由域前缀 `RF-DC-V1\\0` / `RF-SPA-V1\\0` 承载，DC 增补 `key_id`/`alg`；
  `frozen=False`，`build_payload(..., allow_proposed=False)` 默认拒绝。
  在 T2 契约与 ADR 冻结之前，这些字段**不是**契约，不得签发、不得写入证据包。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

from verifier.crypto import jcs

__all__ = [
    "CERTIFICATE_V1_FIELDS",
    "DC_V1_FIELDS_PROPOSED",
    "DOMAIN_CERT_V1",
    "DOMAIN_DC_V1_PROPOSED",
    "DOMAIN_REPORT_V1",
    "DOMAIN_SPA_V1_PROPOSED",
    "PAYLOAD_SPECS",
    "REPORT_V1_FIELDS",
    "SPA_V1_FIELDS",
    "SUPPORTED_SCHEMA_MAJOR",
    "PayloadError",
    "PayloadField",
    "PayloadKind",
    "PayloadSpec",
    "SigningPayload",
    "SigningRefused",
    "assert_certificate_signable",
    "assert_report_signable",
    "build_payload",
    "parse_rfc3339_utc",
    "select_spec",
    "whitelist_rows",
]

# 域分离前缀：字节串，不是 JSON 字段。换前缀 = 换协议版本，旧签名不再通过新验签器。
DOMAIN_REPORT_V1: Final[bytes] = b"RF-REPORT-V1\x00"
DOMAIN_CERT_V1: Final[bytes] = b"RF-CERT-V1\x00"
DOMAIN_DC_V1_PROPOSED: Final[bytes] = b"RF-DC-V1\x00"
DOMAIN_SPA_V1_PROPOSED: Final[bytes] = b"RF-SPA-V1\x00"

# 本地支持的契约 MAJOR；未知 MAJOR 一律拒绝（05 §1.2/§1.5，决议 2）。
SUPPORTED_SCHEMA_MAJOR: Final[int] = 1

# `signature` 是信封字段，不属于被签名内容；允许出现在对象上，但绝不进入 body。
NON_SIGNED_ENVELOPE_FIELDS: Final[frozenset[str]] = frozenset({"signature"})

_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+)\.(\d+)$")
_REPORT_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^report_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_CERT_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^cert_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_TASK_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^task_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_KEY_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_HASH64_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$"
)

_FINAL_STATES: Final[frozenset[str]] = frozenset({"VERIFIED", "PARTIAL", "FAILED", "BLOCKED"})
_LEVEL_STATUSES: Final[frozenset[str]] = frozenset({"PASS", "FAIL", "SKIP", "NOT_RUN"})


class PayloadError(ValueError):
    """载荷白名单/版本/字段校验拒绝；默认映射 `SCHEMA_INVALID`(422)。

    职责：把“哪个字段、哪条规则”固定成 reason + field_path，供负例精确断言。
    输入：reason、message、field_path、detail、error_code（仅签发策略用 SIGNATURE_INVALID）。
    输出：异常。
    副作用：无。
    不变量：`signature` 永不进入 body；未知字段永不静默忽略。
    错误：本类自身；调用方必须断言 reason，不能只断言“抛异常”。
    """

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        field_path: str = "payload",
        detail: Mapping[str, object] | None = None,
        error_code: str = "SCHEMA_INVALID",
    ) -> None:
        self.error_code = error_code
        self.http_status = 422
        self.reason = reason
        self.field_path = field_path
        self.detail = dict(detail or {})
        super().__init__(f"{error_code}/{reason} @ {field_path}: {message}")


class SigningRefused(PayloadError):
    """签发前策略拒绝：非 VERIFIED、证书/报告不一致、T0 出现 SPA 等。

    错误码固定 `SIGNATURE_INVALID`(422)：这是“签名域”的拒绝，不新增注册表码
    （错误码注册表已冻结；`OQ-P6-04` 记录是否补内部码）。
    """

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        field_path: str = "payload",
        detail: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(
            reason,
            message,
            field_path=field_path,
            detail=detail,
            error_code="SIGNATURE_INVALID",
        )


class PayloadKind(StrEnum):
    """四类签名对象；字符串值与域前缀、清单角色保持一致。"""

    REPORT = "report"
    CERTIFICATE = "certificate"
    DC = "dc"
    SPA = "spa"


@dataclass(frozen=True, slots=True)
class PayloadField:
    """白名单中的一个字段。

    `value_kind` 决定基础类型；`format` 决定 ID/哈希/UTC/枚举等形态；
    `source` 必须能指回 7.4 / D.4 / 05 §1.5 的一行，不允许“凭感觉加字段”。
    """

    name: str
    value_kind: str
    source: str
    format: str | None = None
    required: bool = True
    frozen: bool = True
    unique: bool = False
    minimum: int | float | None = None
    maximum: int | float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        # 1. 字段名与来源必须非空；来源是追溯要求，不是装饰。
        if not self.name or not self.source:
            raise ValueError("PayloadField.name/source 不得为空")
        # 2. value_kind 只允许已实现的分支，避免拼写错误变成“永不校验”。
        allowed = {
            "string",
            "integer",
            "number",
            "boolean",
            "string_list",
            "hash64_list",
            "coverage",
            "object",
        }
        if self.value_kind not in allowed:
            raise ValueError(f"未知 value_kind：{self.value_kind!r}")
        # 3. minimum/maximum 只对数值类型有意义。
        if (self.minimum is not None or self.maximum is not None) and self.value_kind not in {
            "integer",
            "number",
        }:
            raise ValueError(f"{self.name}: minimum/maximum 只适用于数值字段")


@dataclass(frozen=True, slots=True)
class PayloadSpec:
    """某一类对象在某一版本下的完整签名协议。"""

    kind: PayloadKind
    version: str
    domain_prefix: bytes
    fields: tuple[PayloadField, ...]
    frozen: bool
    source: str
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # 1. 版本格式。
        if _VERSION_RE.match(self.version) is None:
            raise ValueError(f"版本必须形如 MAJOR.MINOR：{self.version!r}")
        # 2. 域前缀必须非空且以 NUL 结尾，防止与前缀相似的 JSON 字节混淆。
        if not self.domain_prefix or not self.domain_prefix.endswith(b"\x00"):
            raise ValueError("domain_prefix 必须非空且以 NUL 结尾")
        # 3. 字段名唯一；`signature` 不得出现在白名单里。
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.kind}/{self.version}: 字段名重复")
        if "signature" in names:
            raise ValueError("signature 是信封字段，不得进入签名白名单")

    def field_names(self) -> tuple[str, ...]:
        """返回白名单字段名（顺序固定，便于文档/测试逐字段核对）。"""
        return tuple(field.name for field in self.fields)

    def field(self, name: str) -> PayloadField:
        """按名取字段；找不到即抛 `KeyError`（调用方只能查白名单内字段）。"""
        for field in self.fields:
            if field.name == name:
                return field
        raise KeyError(name)


def _f(
    name: str,
    value_kind: str,
    source: str,
    *,
    format: str | None = None,
    required: bool = True,
    frozen: bool = True,
    unique: bool = False,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
    note: str = "",
) -> PayloadField:
    """构造白名单字段的短 helper；只减少重复，不隐藏来源。"""
    return PayloadField(
        name=name,
        value_kind=value_kind,
        source=source,
        format=format,
        required=required,
        frozen=frozen,
        unique=unique,
        minimum=minimum,
        maximum=maximum,
        note=note,
    )


# ---------------------------------------------------------------------------
# 1. 四类白名单（逐字段指回 7.4 / D.4 / 05 §1.5）
# ---------------------------------------------------------------------------
REPORT_V1_FIELDS: Final[tuple[PayloadField, ...]] = (
    _f("schema_version", "string", "05 §1.5；决议 2；ADR-003", format="schema_version"),
    _f("report_id", "string", "7.4 R02 / D.4 P0529", format="report_id"),
    _f("task_id", "string", "7.4 R02 / D.4 P0530", format="task_id"),
    _f("final_state", "string", "7.4 R02 / D.4 P0531", format="final_state"),
    _f("l1_status", "string", "7.4 R02「l1/l2/l3_status」/ D.4 P0532", format="level_status"),
    _f("l2_status", "string", "7.4 R02「l1/l2/l3_status」/ D.4 P0533", format="level_status"),
    _f("l3_status", "string", "7.4 R02「l1/l2/l3_status」/ D.4 P0534", format="level_status"),
    _f(
        "required_check_coverage",
        "coverage",
        "7.4 R02「coverage」/ D.4 P0535–P0537",
        note="required/passed/missing 三键；算术不变量归 Gate/验签策略，不在本文件重算",
    ),
    _f("ruleset_hash", "string", "7.4 R02 / D.4 P0538", format="hash64"),
    _f("evidence_root", "string", "7.4 R02 / D.4 P0539", format="hash64"),
    _f("l3_coverage", "number", "D.4 P0540 / 05 §1.5", format="ratio", minimum=0, maximum=1),
    _f("issued_at", "string", "7.4 R02 / D.4 P0541", format="utc"),
    _f("key_id", "string", "7.4 R02 / D.4 P0542 / 05 §1.5", format="key_id"),
)

CERTIFICATE_V1_FIELDS: Final[tuple[PayloadField, ...]] = (
    _f("schema_version", "string", "05 §1.5；决议 2；ADR-003", format="schema_version"),
    _f("cert_id", "string", "7.4 R03 / D.4 P0546", format="cert_id"),
    _f("report_id", "string", "7.4 R03 / D.4 P0547", format="report_id"),
    _f("final_state", "string", "7.4 R03 / D.4 P0548", format="final_state"),
    _f("merkle_root", "string", "7.4 R03 / D.4 P0549", format="hash64"),
    _f("tree_size", "integer", "7.4 R03 / D.4 P0550", minimum=1),
    _f("ruleset_hash", "string", "7.4 R03 / D.4 P0551", format="hash64"),
    _f("code_hash", "string", "7.4 R03 / D.4 P0552", format="hash64"),
    _f("env_fingerprint", "string", "7.4 R03「env_fp」/ D.4 P0553", format="hash64"),
    _f("l3_coverage", "number", "7.4 R03 / D.4 P0554", format="ratio", minimum=0, maximum=1),
    _f("skipped_nodes", "string_list", "7.4 R03 / D.4 P0555 / 05 §1.5", unique=True),
    _f("alg", "string", "7.4 R03 / D.4 P0556", note="值必须是 Ed25519；在策略层检查，不在 shape 层"),
    _f("key_id", "string", "7.4 R03 / D.4 P0557", format="key_id"),
    _f("key_fingerprint", "string", "7.4 R03 / D.4 P0558", format="hash64"),
    _f("issued_at", "string", "7.4 R03 / 决议 2 / D.4", format="utc"),
)

# DC/SPA：T2 提案，frozen=False。D.5 没有 schema_version；版本由域前缀承载。
DC_V1_FIELDS_PROPOSED: Final[tuple[PayloadField, ...]] = (
    _f("dc_id", "string", "D.5 DC / P0563", format="non_empty", frozen=False),
    _f("node_type", "string", "D.5 DC / P0563", format="non_empty", frozen=False),
    _f("code_hash", "string", "D.5 DC / P0563", format="hash64", frozen=False),
    _f("dependency_lock_hash", "string", "D.5 DC / P0563", format="hash64", frozen=False),
    _f("input_schema_hash", "string", "D.5 DC / P0564", format="hash64", frozen=False),
    _f("env_fingerprint", "string", "D.5 DC / P0564", format="hash64", frozen=False),
    _f("ruleset_hash", "string", "D.5 DC / P0564", format="hash64", frozen=False),
    _f("k_runs", "integer", "D.5 DC / P0565", minimum=1, frozen=False),
    _f("run_fingerprints", "hash64_list", "D.5 DC / P0565", unique=True, frozen=False),
    _f("output_hashes", "hash64_list", "D.5 DC / P0565", unique=True, frozen=False),
    _f("eligible", "boolean", "D.5 DC / P0566", frozen=False),
    _f("expires_at", "string", "D.5 DC / P0566", format="utc", frozen=False),
    _f("key_id", "string", "提案：D.5 未列；无 key_id 无法表达轮换/撤销", format="key_id", frozen=False),
    _f("alg", "string", "提案：D.5 未列；签名应绑定算法", frozen=False),
)

SPA_V1_FIELDS: Final[tuple[PayloadField, ...]] = (
    _f("spa_id", "string", "D.5 SPA / P0569", format="non_empty", frozen=False),
    _f("task_id", "string", "D.5 SPA / P0569", format="task_id", frozen=False),
    _f("node_id", "string", "D.5 SPA / P0569", format="non_empty", frozen=False),
    _f("recovery_plan_id", "string", "D.5 SPA / P0569", format="non_empty", frozen=False),
    _f("dc_id", "string", "D.5 SPA / P0570", format="non_empty", frozen=False),
    _f("predecessor_hashes", "hash64_list", "D.5 SPA / P0570", unique=True, frozen=False),
    _f("artifact_hash", "string", "D.5 SPA / P0570", format="hash64", frozen=False),
    _f("ruleset_hash", "string", "D.5 SPA / P0571", format="hash64", frozen=False),
    _f("gate_result", "object", "D.5 SPA / P0571", frozen=False),
    _f("skip_reason", "string", "D.5 SPA / P0571", format="non_empty", frozen=False),
    _f("verifier_key_id", "string", "D.5 SPA / P0572", format="key_id", frozen=False),
)


PAYLOAD_SPECS: Final[Mapping[tuple[PayloadKind, str], PayloadSpec]] = MappingProxyType(
    {
        (PayloadKind.REPORT, "1.0"): PayloadSpec(
            kind=PayloadKind.REPORT,
            version="1.0",
            domain_prefix=DOMAIN_REPORT_V1,
            fields=REPORT_V1_FIELDS,
            frozen=True,
            source="05 §1.5；策划书 7.4/7.5；附录 D.4",
        ),
        (PayloadKind.CERTIFICATE, "1.0"): PayloadSpec(
            kind=PayloadKind.CERTIFICATE,
            version="1.0",
            domain_prefix=DOMAIN_CERT_V1,
            fields=CERTIFICATE_V1_FIELDS,
            frozen=True,
            source="05 §1.5；策划书 7.4/7.5；附录 D.4",
        ),
        (PayloadKind.DC, "1.0"): PayloadSpec(
            kind=PayloadKind.DC,
            version="1.0",
            domain_prefix=DOMAIN_DC_V1_PROPOSED,
            fields=DC_V1_FIELDS_PROPOSED,
            frozen=False,
            source="附录 D.5（T2 提案；OQ-P6-02）",
            notes=("D.5 无 schema_version；版本由域前缀承载", "key_id/alg 为提案字段"),
        ),
        (PayloadKind.SPA, "1.0"): PayloadSpec(
            kind=PayloadKind.SPA,
            version="1.0",
            domain_prefix=DOMAIN_SPA_V1_PROPOSED,
            fields=SPA_V1_FIELDS,
            frozen=False,
            source="附录 D.5（T2 提案；OQ-P6-02）",
            notes=("D.5 无 schema_version；版本由域前缀承载",),
        ),
    }
)


# ---------------------------------------------------------------------------
# 2. 版本选择与字段校验
# ---------------------------------------------------------------------------
def select_spec(kind: PayloadKind | str, version: str = "1.0") -> PayloadSpec:
    """按对象类型与版本取协议；未知 MAJOR/未知 MINOR 一律拒绝。

    职责：把“支持哪些版本”集中到一处，禁止调用方自行拼字段。
    输入：kind（枚举或字符串）、version（MAJOR.MINOR）。
    输出：`PayloadSpec`。
    副作用：无。
    不变量：只接受 `SUPPORTED_SCHEMA_MAJOR`；不做“向前兼容猜测”。
    错误：`PayloadError`（PAYLOAD_KIND_UNKNOWN / PAYLOAD_VERSION_FORMAT /
          PAYLOAD_SCHEMA_MAJOR_UNSUPPORTED / PAYLOAD_VERSION_UNSUPPORTED）。
    """
    # 1. kind 归一化。
    try:
        normalized_kind = kind if isinstance(kind, PayloadKind) else PayloadKind(kind)
    except ValueError as exc:
        raise PayloadError("PAYLOAD_KIND_UNKNOWN", f"未知签名对象类型：{kind!r}") from exc

    # 2. 版本格式。
    match = _VERSION_RE.match(version) if isinstance(version, str) else None
    if match is None:
        raise PayloadError(
            "PAYLOAD_VERSION_FORMAT",
            f"版本必须形如 MAJOR.MINOR：{version!r}",
            field_path="schema_version",
        )

    # 2.1 拒绝前导零（"01.0"），否则会落到“未知版本”而不是“格式非法”。
    major_text, minor_text = match.group(1), match.group(2)
    if (len(major_text) > 1 and major_text.startswith("0")) or (
        len(minor_text) > 1 and minor_text.startswith("0")
    ):
        raise PayloadError(
            "PAYLOAD_VERSION_FORMAT",
            f"版本段不得有前导零：{version!r}",
            field_path="schema_version",
        )

    # 3. MAJOR 必须受支持；未知 MAJOR 不得尝试解析。
    major = int(major_text)
    if major != SUPPORTED_SCHEMA_MAJOR:
        raise PayloadError(
            "PAYLOAD_SCHEMA_MAJOR_UNSUPPORTED",
            f"本地只支持 MAJOR={SUPPORTED_SCHEMA_MAJOR}，收到 {version!r}",
            field_path="schema_version",
        )

    # 4. 精确版本查找；MINOR 升级必须显式登记新 spec。
    spec = PAYLOAD_SPECS.get((normalized_kind, version))
    if spec is None:
        raise PayloadError(
            "PAYLOAD_VERSION_UNSUPPORTED",
            f"未登记 {normalized_kind.value} 的版本 {version!r}",
            field_path="schema_version",
        )
    return spec


def build_payload(
    kind: PayloadKind | str,
    obj: Mapping[str, object],
    *,
    version: str = "1.0",
    allow_proposed: bool = False,
) -> SigningPayload:
    """从对象中**只取白名单字段**构造签名载荷；未知字段 fail-closed。

    职责：校验字段集合、必填、类型/格式、schema_version，返回可签名的 body。
    输入：kind、对象、版本、allow_proposed（仅测试/设计预览 DC/SPA）。
    输出：`SigningPayload`。
    副作用：无。
    不变量：
      1. body 的键集合 == spec 字段集合；`signature` 不在 body；
      2. 对象上出现表外字段 → 拒绝，不静默忽略；
      3. Report/Certificate 的 `schema_version` 必须等于所选版本；
      4. 不重算 coverage 算术、不判断 VERIFIED 之外的状态语义（归 Gate/策略层）。
    错误：`PayloadError`（PAYLOAD_*）。
    """
    # 1. 取协议。
    spec = select_spec(kind, version)

    # 2. 未冻结协议（DC/SPA）默认拒绝；T0 不得签发。
    if not spec.frozen and not allow_proposed:
        raise PayloadError(
            "PAYLOAD_NOT_FROZEN",
            f"{spec.kind.value} 的 {version} 载荷尚未冻结，T0 不得签发",
            field_path="payload",
        )

    # 3. 对象必须是映射，键必须是字符串。
    if not isinstance(obj, Mapping):
        raise PayloadError("PAYLOAD_NOT_MAPPING", f"对象必须是 Mapping，实际 {type(obj).__name__}")
    for key in obj.keys():
        if not isinstance(key, str):
            raise PayloadError(
                "PAYLOAD_KEY_NOT_STRING",
                f"对象键必须是字符串，实际 {type(key).__name__}",
                field_path="payload",
            )

    # 4. 未知字段：对象键减去白名单与信封字段；不静默丢弃。
    allowed = set(spec.field_names()) | set(NON_SIGNED_ENVELOPE_FIELDS)
    unknown = sorted(set(obj.keys()) - allowed)
    if unknown:
        raise PayloadError(
            "PAYLOAD_UNKNOWN_FIELD",
            f"{spec.kind.value} v{version} 不允许字段：{unknown}",
            field_path=unknown[0],
            detail={"unknown_fields": unknown, "allowed_fields": sorted(allowed)},
        )

    # 5. 必填字段缺失；列出全部缺失项，便于一次修正。
    missing = sorted(field.name for field in spec.fields if field.required and field.name not in obj)
    if missing:
        raise PayloadError(
            "PAYLOAD_FIELD_MISSING",
            f"{spec.kind.value} v{version} 缺少必填字段：{missing}",
            field_path=missing[0],
            detail={"missing_fields": missing},
        )

    # 6. schema_version 必须存在且等于所选版本（DC/SPA 白名单没有该字段，跳过）。
    if any(field.name == "schema_version" for field in spec.fields):
        actual_version = obj.get("schema_version")
        if actual_version != version:
            raise PayloadError(
                "PAYLOAD_SCHEMA_VERSION_MISMATCH",
                f"载荷版本 {actual_version!r} 与所选版本 {version!r} 不一致",
                field_path="schema_version",
            )

    # 7. 逐字段校验类型/格式；失败即定位到字段。
    for field in spec.fields:
        if field.name not in obj:
            continue
        _check_value(field, obj[field.name], f"{spec.kind.value}.{field.name}")

    # 8. body 只含白名单字段，顺序按 spec；用 MappingProxyType 防调用方改写。
    body = MappingProxyType({field.name: obj[field.name] for field in spec.fields})

    # 9. 构造并返回；SigningPayload 会再核对一次键集合。
    return SigningPayload(spec=spec, body=body)


def _check_value(field: PayloadField, value: object, field_path: str) -> None:
    """校验单个字段的基础类型、格式与范围；不判断跨字段语义。"""
    # 1. 按 value_kind 分派。
    if field.value_kind == "string":
        # 1.1 字符串必须非空；格式另行检查。
        if not isinstance(value, str) or not value:
            raise PayloadError(
                "PAYLOAD_FIELD_TYPE_INVALID",
                f"期望非空 string，实际 {type(value).__name__}",
                field_path=field_path,
                detail={"expected": "string", "actual": type(value).__name__},
            )
        _check_format(field, value, field_path)
        return

    if field.value_kind == "integer":
        # 1.2 bool 是 int 子类，必须显式排除。
        if isinstance(value, bool) or not isinstance(value, int):
            raise PayloadError(
                "PAYLOAD_FIELD_TYPE_INVALID",
                f"期望 integer，实际 {type(value).__name__}",
                field_path=field_path,
            )
        _check_numeric_bounds(field, value, field_path)
        return

    if field.value_kind == "number":
        # 1.3 只接受有限数；bool 排除。
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PayloadError(
                "PAYLOAD_FIELD_TYPE_INVALID",
                f"期望 number，实际 {type(value).__name__}",
                field_path=field_path,
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise PayloadError(
                "PAYLOAD_FIELD_TYPE_INVALID",
                "number 必须是有限数",
                field_path=field_path,
            )
        _check_numeric_bounds(field, value, field_path)
        _check_format(field, value, field_path)
        return

    if field.value_kind == "boolean":
        # 1.4 只接受 bool。
        if not isinstance(value, bool):
            raise PayloadError(
                "PAYLOAD_FIELD_TYPE_INVALID",
                f"期望 boolean，实际 {type(value).__name__}",
                field_path=field_path,
            )
        return

    if field.value_kind in {"string_list", "hash64_list"}:
        # 1.5 数组：元素类型、重复项、逐项格式。
        if not isinstance(value, list):
            raise PayloadError(
                "PAYLOAD_FIELD_TYPE_INVALID",
                f"期望 array，实际 {type(value).__name__}",
                field_path=field_path,
            )
        seen: set[str] = set()
        for index, item in enumerate(value):
            item_path = f"{field_path}[{index}]"
            if not isinstance(item, str) or not item:
                raise PayloadError(
                    "PAYLOAD_FIELD_TYPE_INVALID",
                    "数组元素必须是非空 string",
                    field_path=item_path,
                )
            if field.unique and item in seen:
                raise PayloadError(
                    "PAYLOAD_LIST_DUPLICATED",
                    f"数组元素重复：{item!r}",
                    field_path=item_path,
                )
            seen.add(item)
            if field.value_kind == "hash64_list" and _HASH64_RE.match(item) is None:
                raise PayloadError(
                    "PAYLOAD_HASH_INVALID",
                    f"数组元素必须是 64 位小写十六进制：{item!r}",
                    field_path=item_path,
                )
        return

    if field.value_kind == "coverage":
        # 1.6 覆盖计数：恰好三键，非负整数；算术留给策略层。
        if not isinstance(value, Mapping):
            raise PayloadError(
                "PAYLOAD_FIELD_TYPE_INVALID",
                f"期望 coverage object，实际 {type(value).__name__}",
                field_path=field_path,
            )
        expected_keys = {"required", "passed", "missing"}
        if set(value.keys()) != expected_keys:
            raise PayloadError(
                "PAYLOAD_COVERAGE_SHAPE_INVALID",
                f"coverage 必须恰好含 {sorted(expected_keys)}，实际 {sorted(value.keys())}",
                field_path=field_path,
            )
        for key in sorted(expected_keys):
            item = value[key]
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise PayloadError(
                    "PAYLOAD_COVERAGE_SHAPE_INVALID",
                    "coverage 计数必须是非负 integer",
                    field_path=f"{field_path}.{key}",
                )
        return

    if field.value_kind == "object":
        # 1.7 嵌套对象交给 JCS 校验，确保可规范化且无 NaN/代理项。
        if not isinstance(value, Mapping):
            raise PayloadError(
                "PAYLOAD_FIELD_TYPE_INVALID",
                f"期望 object，实际 {type(value).__name__}",
                field_path=field_path,
            )
        try:
            jcs.validate_value(value, field_path=field_path)
        except jcs.JcsError as exc:
            raise PayloadError(
                "PAYLOAD_FIELD_TYPE_INVALID",
                f"嵌套对象不是合法 JCS 值：{exc.reason}",
                field_path=exc.field_path,
            ) from exc
        return

    # 1.8 理论上不可达；保持 fail-closed。
    raise PayloadError(
        "PAYLOAD_FIELD_TYPE_INVALID",
        f"未实现的 value_kind：{field.value_kind!r}",
        field_path=field_path,
    )


def _check_numeric_bounds(field: PayloadField, value: int | float, field_path: str) -> None:
    """检查 minimum/maximum；只对数值字段调用。"""
    if field.minimum is not None and value < field.minimum:
        raise PayloadError(
            "PAYLOAD_NUMBER_OUT_OF_RANGE",
            f"{field.name} 必须 ≥ {field.minimum}，实际 {value}",
            field_path=field_path,
        )
    if field.maximum is not None and value > field.maximum:
        raise PayloadError(
            "PAYLOAD_NUMBER_OUT_OF_RANGE",
            f"{field.name} 必须 ≤ {field.maximum}，实际 {value}",
            field_path=field_path,
        )


def _check_format(field: PayloadField, value: object, field_path: str) -> None:
    """检查 ID/哈希/UTC/枚举等形态；格式名拼错必须显式失败。"""
    # 1. 无格式要求。
    if field.format is None:
        return

    # 2. 逐格式检查。
    fmt = field.format
    if fmt == "schema_version":
        if not isinstance(value, str) or _VERSION_RE.match(value) is None:
            raise PayloadError("PAYLOAD_VERSION_FORMAT", "schema_version 必须是 MAJOR.MINOR", field_path=field_path)
        return
    if fmt == "report_id":
        if not isinstance(value, str) or _REPORT_ID_RE.match(value) is None:
            raise PayloadError("PAYLOAD_ID_INVALID", "report_id 形态非法", field_path=field_path)
        return
    if fmt == "cert_id":
        if not isinstance(value, str) or _CERT_ID_RE.match(value) is None:
            raise PayloadError("PAYLOAD_ID_INVALID", "cert_id 形态非法", field_path=field_path)
        return
    if fmt == "task_id":
        if not isinstance(value, str) or _TASK_ID_RE.match(value) is None:
            raise PayloadError("PAYLOAD_ID_INVALID", "task_id 形态非法", field_path=field_path)
        return
    if fmt == "key_id":
        if not isinstance(value, str) or _KEY_ID_RE.match(value) is None:
            raise PayloadError("PAYLOAD_ID_INVALID", "key_id 形态非法", field_path=field_path)
        return
    if fmt == "hash64":
        if not isinstance(value, str) or _HASH64_RE.match(value) is None:
            raise PayloadError("PAYLOAD_HASH_INVALID", "必须是 64 位小写十六进制", field_path=field_path)
        return
    if fmt == "utc":
        parse_rfc3339_utc(value, field_path=field_path)
        return
    if fmt == "final_state":
        if value not in _FINAL_STATES:
            raise PayloadError(
                "PAYLOAD_ENUM_INVALID",
                f"final_state 必须是 {sorted(_FINAL_STATES)} 之一，实际 {value!r}",
                field_path=field_path,
            )
        return
    if fmt == "level_status":
        if value not in _LEVEL_STATUSES:
            raise PayloadError(
                "PAYLOAD_ENUM_INVALID",
                f"状态必须是 {sorted(_LEVEL_STATUSES)} 之一，实际 {value!r}",
                field_path=field_path,
            )
        return
    if fmt == "ratio":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise PayloadError("PAYLOAD_FIELD_TYPE_INVALID", "ratio 必须是 number", field_path=field_path)
        if not 0 <= float(value) <= 1:
            raise PayloadError("PAYLOAD_NUMBER_OUT_OF_RANGE", "ratio 必须在 [0,1]", field_path=field_path)
        return
    if fmt == "non_empty":
        if not isinstance(value, str) or not value:
            raise PayloadError("PAYLOAD_FIELD_TYPE_INVALID", "必须是非空字符串", field_path=field_path)
        return

    # 3. 未知 format 是编程错误，必须 fail-closed，不能跳过校验。
    raise PayloadError(
        "PAYLOAD_FIELD_TYPE_INVALID",
        f"未实现的格式校验：{fmt!r}",
        field_path=field_path,
    )


def parse_rfc3339_utc(value: object, *, field_path: str = "issued_at") -> datetime:
    """解析 RFC 3339 UTC 时间，返回 aware datetime；只接受 `Z` 或 `+00:00`。

    职责：把契约时间统一成 UTC，供有效期/先后比较使用。
    输入：字符串。
    输出：`datetime`（tzinfo=UTC）。
    副作用：无。
    不变量：不做本地时区转换；不接受无时区、非零偏移、纯日期。
    错误：`PayloadError(PAYLOAD_TIMESTAMP_INVALID)`。
    """
    # 1. 形态检查（与 schema 同一正则口径）。
    if not isinstance(value, str) or _UTC_RE.match(value) is None:
        raise PayloadError(
            "PAYLOAD_TIMESTAMP_INVALID",
            f"必须是 UTC RFC 3339（Z 或 +00:00）：{value!r}",
            field_path=field_path,
        )

    # 2. 解析；Python 3.11 支持 Z，但仍显式替换以保证跨版本一致。
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PayloadError(
            "PAYLOAD_TIMESTAMP_INVALID",
            f"时间无法解析：{value!r}",
            field_path=field_path,
        ) from exc

    # 3. 必须带 UTC 偏移，且偏移为 0。
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise PayloadError(
            "PAYLOAD_TIMESTAMP_INVALID",
            "时间必须带 UTC 偏移",
            field_path=field_path,
        )

    # 4. 归一化到 UTC 并返回。
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# 3. SigningPayload
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SigningPayload:
    """已按白名单选取的签名体；`signing_bytes()` 是唯一允许送进 Ed25519 的字节。

    职责：把“对象类型 + 版本 + 域前缀 + body”绑定在一起，防止调用方拿错类型/版本。
    输入：spec、body。
    输出：不可变对象。
    副作用：无。
    不变量：body 键集合 == spec 字段集合；不含 `signature`；域前缀非空。
    错误：`PayloadError`（构造期）。
    """

    spec: PayloadSpec
    body: Mapping[str, object]

    def __post_init__(self) -> None:
        # 1. 键集合必须与协议完全一致；多一个少一个都不行。
        expected = set(self.spec.field_names())
        actual = set(self.body.keys())
        if actual != expected:
            raise PayloadError(
                "PAYLOAD_FIELD_MISSING",
                f"签名体字段集合与协议不一致：缺少 {sorted(expected - actual)}，多出 {sorted(actual - expected)}",
            )
        # 2. 信封字段不得混入。
        if "signature" in self.body:
            raise PayloadError("PAYLOAD_UNKNOWN_FIELD", "signature 不得进入签名体", field_path="signature")

    @property
    def kind(self) -> PayloadKind:
        """对象类型。"""
        return self.spec.kind

    @property
    def version(self) -> str:
        """协议版本。"""
        return self.spec.version

    @property
    def domain_prefix(self) -> bytes:
        """域分离前缀。"""
        return self.spec.domain_prefix

    @property
    def key_id(self) -> str:
        """签名密钥标识；DC/SPA 使用 `verifier_key_id`。"""
        if isinstance(self.body.get("key_id"), str):
            return str(self.body["key_id"])
        if isinstance(self.body.get("verifier_key_id"), str):
            return str(self.body["verifier_key_id"])
        raise PayloadError("PAYLOAD_FIELD_MISSING", "载荷不含 key_id/verifier_key_id", field_path="key_id")

    def canonical_body(self) -> bytes:
        """只返回 JCS(body)，不含域前缀；用于调试/哈希对照，不直接签名。"""
        return jcs.canonicalize(dict(self.body))

    def signing_bytes(self) -> bytes:
        """返回 `domain_prefix || JCS(body)`；这是 Ed25519 的唯一输入。"""
        return self.spec.domain_prefix + self.canonical_body()

    def sha256_hex(self) -> str:
        """返回签名体（含域前缀）的 SHA-256 小写十六进制；用于审计关联，不替代签名。"""
        import hashlib

        return hashlib.sha256(self.signing_bytes()).hexdigest()

    def explain(self) -> Mapping[str, object]:
        """返回可安全写入日志的元数据：类型、版本、key_id、哈希；**不含 body**。"""
        return MappingProxyType(
            {
                "payload_kind": self.kind.value,
                "schema_version": self.version,
                "key_id": self.key_id,
                "signing_bytes_sha256": self.sha256_hex(),
            }
        )


# ---------------------------------------------------------------------------
# 4. 签发前策略（非 VERIFIED 不签、证书与报告必须一致）
# ---------------------------------------------------------------------------
def assert_report_signable(report: Mapping[str, object]) -> SigningPayload:
    """Report 签发前检查：白名单 shape + 只允许 VERIFIED。

    职责：阻止对 PARTIAL/FAILED/BLOCKED 报告签名（用户硬要求）。
    输入：报告对象。
    输出：`SigningPayload`。
    副作用：无。
    不变量：返回的载荷一定含 final_state、ruleset_hash、evidence_root。
    错误：`PayloadError`（shape）；`SigningRefused(SIGNING_REPORT_NOT_VERIFIED)`。
    """
    # 1. 先做白名单/类型校验，保证拒绝原因不是“字段缺失”冒充“状态不对”。
    payload = build_payload(PayloadKind.REPORT, report)

    # 2. 只签 VERIFIED；其他状态不得产生签名。
    if payload.body["final_state"] != "VERIFIED":
        raise SigningRefused(
            "SIGNING_REPORT_NOT_VERIFIED",
            f"报告 final_state={payload.body['final_state']!r}，只有 VERIFIED 允许签名",
            field_path="final_state",
        )

    # 3. 返回载荷。
    return payload


def assert_certificate_signable(
    certificate: Mapping[str, object],
    report: Mapping[str, object],
) -> SigningPayload:
    """Certificate 签发前检查：VERIFIED + 与来源报告一致 + T0 无 SPA。

    职责：把“证书只能来自 VERIFIED 报告”与跨文档一致性固化为签发前守卫。
    输入：证书对象、来源报告对象。
    输出：证书 `SigningPayload`。
    副作用：无。
    不变量：
      1. 报告与证书 final_state 均为 VERIFIED；
      2. report_id、merkle_root/evidence_root、ruleset_hash、l3_coverage 一致；
      3. T0 `skipped_nodes` 必须为空；
      4. `alg` 必须是 Ed25519。
    错误：`PayloadError`（shape）；`SigningRefused`（SIGNING_*）。
    """
    # 1. 双方 shape 校验。
    cert_payload = build_payload(PayloadKind.CERTIFICATE, certificate)
    report_payload = build_payload(PayloadKind.REPORT, report)

    # 2. 报告必须 VERIFIED。
    if report_payload.body["final_state"] != "VERIFIED":
        raise SigningRefused(
            "SIGNING_REPORT_NOT_VERIFIED",
            f"来源报告 final_state={report_payload.body['final_state']!r}，不得签发证书",
            field_path="report.final_state",
        )

    # 3. 证书必须 VERIFIED。
    if cert_payload.body["final_state"] != "VERIFIED":
        raise SigningRefused(
            "SIGNING_CERT_NOT_VERIFIED",
            "证书 final_state 必须是 VERIFIED",
            field_path="final_state",
        )

    # 4. 证书必须指向同一报告。
    if cert_payload.body["report_id"] != report_payload.body["report_id"]:
        raise SigningRefused(
            "SIGNING_CERT_REPORT_MISMATCH",
            "证书 report_id 与报告不一致",
            field_path="report_id",
        )

    # 5. 证据根必须一致。
    if cert_payload.body["merkle_root"] != report_payload.body["evidence_root"]:
        raise SigningRefused(
            "SIGNING_CERT_ROOT_MISMATCH",
            "证书 merkle_root 与报告 evidence_root 不一致",
            field_path="merkle_root",
        )

    # 6. 规则版本必须一致。
    if cert_payload.body["ruleset_hash"] != report_payload.body["ruleset_hash"]:
        raise SigningRefused(
            "SIGNING_CERT_RULESET_MISMATCH",
            "证书 ruleset_hash 与报告不一致",
            field_path="ruleset_hash",
        )

    # 7. L3 覆盖必须一致（同一判定事实，不允许证书另写一个数）。
    if float(cert_payload.body["l3_coverage"]) != float(report_payload.body["l3_coverage"]):
        raise SigningRefused(
            "SIGNING_CERT_L3_COVERAGE_MISMATCH",
            "证书 l3_coverage 与报告不一致",
            field_path="l3_coverage",
        )

    # 8. T0 无 DC/SPA，skipped_nodes 必须为空数组。
    if cert_payload.body["skipped_nodes"]:
        raise SigningRefused(
            "SIGNING_CERT_SPA_NOT_ALLOWED_T0",
            "T0 不允许 SPA，skipped_nodes 必须为空",
            field_path="skipped_nodes",
        )

    # 9. 算法固定 Ed25519；其他值不得签发。
    if cert_payload.body["alg"] != "Ed25519":
        raise SigningRefused(
            "SIGNING_CERT_ALG_UNSUPPORTED",
            f"alg 必须是 Ed25519，实际 {cert_payload.body['alg']!r}",
            field_path="alg",
        )

    # 10. 返回证书载荷。
    return cert_payload


# ---------------------------------------------------------------------------
# 5. 文档/测试用的白名单视图
# ---------------------------------------------------------------------------
def whitelist_rows(kind: PayloadKind | str, version: str = "1.0") -> tuple[Mapping[str, object], ...]:
    """返回逐字段的来源表，供 MODULE.md/测试断言“每个字段都能指回 7.4”。

    职责：把白名单导出为只读行；不参与签名。
    输入：kind、version。
    输出：每行含 field/source/frozen/value_kind/format。
    副作用：无。
    不变量：行数 == spec 字段数；source 非空。
    错误：`PayloadError`（版本/类型非法）。
    """
    # 1. 取协议。
    spec = select_spec(kind, version)

    # 2. 逐字段构造只读行。
    rows: list[Mapping[str, object]] = []
    for field in spec.fields:
        rows.append(
            MappingProxyType(
                {
                    "field": field.name,
                    "source": field.source,
                    "frozen": field.frozen,
                    "value_kind": field.value_kind,
                    "format": field.format,
                }
            )
        )
    return tuple(rows)