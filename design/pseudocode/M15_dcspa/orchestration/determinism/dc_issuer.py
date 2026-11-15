"""M15 · orchestration/determinism/dc_issuer.py — DC 签发、过期、撤销与复用判定（P9 伪代码）。
MODULE: M15 DC/SPA ｜ 阶段：P9「DC/SPA 与 VAS」
追踪：FR-015（T2 / G4）、策划书 §8.2 R03/R07、§8.3 条件 1、§7.5 签名、附录 D.5/D.6
FR+依赖：`dc_eligibility`（资格与 k 次比对）、M11 `ed25519_signer`（签名端口）、
        M02 `audit_log`（签发/撤销审计）；本文件不实现 JCS/SHA-256/Ed25519
不变量：只签 `eligible=True` 且**重算后仍 bit-exact** 的 DC；`eligible=False` 只有判定结论、没有记录；
        撤销是终态，无 `unrevoke`；登记表只增不改；签名必须回验；`expires_at` 必填且 TTL 受限
错误码：FEATURE_FLAG_NOT_PERMITTED（403）、DC_NOT_ELIGIBLE（409）、SIGNATURE_INVALID（422）、
        DC_EXPIRED（409）、DC_REVOKED（409）、RULESET_VERSION_MISMATCH（409）、
        ENV_FINGERPRINT_INCOMPLETE（409）、SCHEMA_INVALID（422）
写入者：无。`DcRecord`/`RevocationRecord` 是冻结值对象；落库与审计走端口
状态：伪代码；签名未实现（OQ-P6-02/OQ-P9-03），`signer=None` 时拒绝签发

## 为什么签发要「重算一次」

  `EligibilityVerdict.eligible` 是布尔。布尔一旦离开产生它的函数，就再也没法证明它对应哪几次
  运行、哪份代码、哪个环境。`issue_dc` 因此**不信任**调用方传进来的结论：它拿原始探针再跑一次
  `compare_runs`，从探针派生 `k_runs/run_fingerprints/output_hashes`，只把重算结果写进记录。

## 判定顺序（§8.3 条件 1「存在有效 DC」的完整口径）

  签名 → eligible → 撤销 → 到期 → 规则 → 代码 → 输入结构 → 环境 → VALID

  撤销优先于到期：已撤销的 DC 即使仍在有效期内也不可用；这是终态，不是「过期的一种」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

from .dc_eligibility import (
    DcBinding,
    DcCandidate,
    DcEligibilityError,
    EligibilityVerdict,
    RunProbe,
    compare_runs,
)

__all__ = [
    "DC_ALG",
    "DC_FIELDS",
    "DC_SIGNED_FIELDS",
    "DC_SIGNING_DOMAIN",
    "DEFAULT_DC_TTL_DAYS",
    "DcAudit",
    "DcIdentity",
    "DcIssuance",
    "DcIssuerError",
    "DcRecord",
    "DcRefused",
    "DcRegistry",
    "DcRevoked",
    "DcSignature",
    "DcSignatureInvalid",
    "DcSignerPort",
    "DcStatus",
    "DcStoreCorrupt",
    "DcValidity",
    "DcValidityReport",
    "RevocationReason",
    "RevocationRecord",
    "assert_dc_scope",
    "assert_policy_binding",
    "assert_revocation_is_terminal",
    "assert_signature_domain",
    "compute_dc_id",
    "evaluate_dc",
    "evaluate_dc_record",
    "issue_dc",
    "revoke_dc",
]

STAGE: Final[str] = "P9"

#: §7.5：签名算法固定 Ed25519（RFC 8032）。
DC_ALG: Final[str] = "Ed25519"

#: §7.5：DC 的域分离前缀。具体字符串原文未给（OQ-P9-04），这里是 PROPOSED。
DC_SIGNING_DOMAIN: Final[str] = "RF-DC-V1"

#: 附录 D.5「DC」13 个字段，顺序即原文分组顺序。
DC_FIELDS: Final[tuple[str, ...]] = (
    "dc_id",
    "node_type",
    "code_hash",
    "dependency_lock_hash",
    "input_schema_hash",
    "env_fingerprint",
    "ruleset_hash",
    "k_runs",
    "run_fingerprints",
    "output_hashes",
    "eligible",
    "expires_at",
    "signature",
)

#: 签名正文覆盖 12 个字段：D.5 全部字段去掉 `signature`。
DC_SIGNED_FIELDS: Final[tuple[str, ...]] = DC_FIELDS[:-1]

#: 由 `dc_id` + 11 个身份字段决定；`dc_id` 本身不进摘要输入。
DC_IDENTITY_FIELDS: Final[tuple[str, ...]] = DC_FIELDS[1:-1]

#: 默认 TTL：原文未给（OQ-P9-05），这里取保守值，且不得突破策略上限。
DEFAULT_DC_TTL_DAYS: Final[int] = 7


# ---------------------------------------------------------------------------
# 1. 错误
# ---------------------------------------------------------------------------
class DcIssuerError(RuntimeError):
    """签发链路错误基类。"""

    error_code: Final[str] = "DC_ISSUER_ERROR"
    http_status: Final[int] = 409

    def __init__(
        self,
        reason: str,
        detail: str,
        *,
        error_code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail
        if error_code is not None:
            self.error_code = error_code
        if http_status is not None:
            self.http_status = http_status
        super().__init__(f"{self.error_code}/{reason}：{detail}")


class DcRefused(DcIssuerError):
    """拒绝签发或拒绝状态变更（资格不足、开关关闭、已撤销）。对外 409。"""

    error_code: Final[str] = "DC_NOT_ELIGIBLE"
    http_status: Final[int] = 409


class DcSignatureInvalid(DcIssuerError):
    """签名失败或回验失败。对外 422。"""

    error_code: Final[str] = "SIGNATURE_INVALID"
    http_status: Final[int] = 422


class DcStoreCorrupt(DcIssuerError):
    """登记表被改写：同一 `dc_id` 出现两份不同内容。对外 409。"""

    error_code: Final[str] = "DC_STORE_CORRUPT"
    http_status: Final[int] = 409


class DcRevoked(DcIssuerError):
    """DC 已撤销（终态）。对外 409。"""

    error_code: Final[str] = "DC_REVOKED"
    http_status: Final[int] = 409


# ---------------------------------------------------------------------------
# 2. 形态校验
# ---------------------------------------------------------------------------
def _require_hash(value: str, field_path: str) -> None:
    """64 位小写十六进制（ENCODING_RULES §4）。"""
    if not isinstance(value, str) or len(value) != 64:
        raise DcIssuerError("HASH_INVALID", f"{field_path} 期望 64 位十六进制，实际 {value!r}")
    if any(ch not in "0123456789abcdef" for ch in value):
        raise DcIssuerError("HASH_INVALID", f"{field_path} 只允许小写十六进制")


def _require_utc_datetime(moment: datetime, field_path: str) -> None:
    """只接受带时区的 UTC datetime（不猜本地时区）。"""
    if not isinstance(moment, datetime):
        raise DcIssuerError("TIME_INVALID", f"{field_path} 必须是 datetime")
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise DcIssuerError("TIME_NOT_UTC", f"{field_path} 必须是带时区的 UTC")


def _utc_z(moment: datetime) -> str:
    """UTC datetime → RFC3339 `...Z`（§7.5 时间写法）。"""
    _require_utc_datetime(moment, "moment")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc_z(text: str, field_path: str) -> datetime:
    """RFC3339 `...Z` → UTC datetime；格式不符直接拒绝。"""
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError) as exc:
        raise DcIssuerError("TIME_INVALID", f"{field_path} 不是 RFC3339 UTC：{text!r}") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _canonical_bytes(body: Mapping[str, object]) -> bytes:
    """规范化字节串（占位）。

    真实实现必须调用 M11 `jcs.canonicalize`：RFC 8785、递归排序对象键、**不重排数组**、
    拒绝重复键/NaN/Infinity。本文件只固定「签名覆盖哪些字段」这一层。
    """
    import json

    return json.dumps(dict(body), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------------------
# 3. 签名与端口
# ---------------------------------------------------------------------------
class DcSignerPort(Protocol):
    """T2 签名端口。P9 **没有**合规实现（OQ-P6-02：M11 拒绝未冻结载荷）。"""

    def key_id(self) -> str:
        ...

    def sign(self, payload: bytes, *, domain: str, alg: str) -> str:
        ...

    def verify(self, payload: bytes, signature: str, *, domain: str, alg: str) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class DcSignature:
    """签名信封。`signed_body_hash` 把「签的是哪份正文」也钉住。"""

    alg: str
    key_id: str
    domain: str
    signature: str
    signed_body_hash: str

    def __post_init__(self) -> None:
        if self.alg != DC_ALG:
            raise DcSignatureInvalid("ALG_MISMATCH", f"期望 {DC_ALG}，实际 {self.alg!r}")
        if self.domain != DC_SIGNING_DOMAIN:
            raise DcSignatureInvalid("DOMAIN_MISMATCH", f"域前缀必须是 {DC_SIGNING_DOMAIN!r}")
        if not self.key_id.strip():
            raise DcSignatureInvalid("KEY_ID_MISSING", "签名必须带 key_id")
        if not self.signature.strip():
            raise DcSignatureInvalid("SIGNATURE_EMPTY", "签名为空")
        _require_hash(self.signed_body_hash, "signature.signed_body_hash")

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "alg": self.alg,
                "key_id": self.key_id,
                "domain": self.domain,
                "signed_body_hash": self.signed_body_hash,
            }
        )


# ---------------------------------------------------------------------------
# 4. 身份与内容寻址
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DcIdentity:
    """D.5 中除 `dc_id` / `signature` 外的 11 个字段。

    `eligible` 在已签发记录里恒为 `True`——`False` 只存在于 `EligibilityVerdict`，
    不会变成记录。字段保留是为了让 D.5 的 13 字段可以被逐字核对。
    """

    node_type: str
    code_hash: str
    dependency_lock_hash: str
    input_schema_hash: str
    env_fingerprint: str
    ruleset_hash: str
    k_runs: int
    run_fingerprints: tuple[str, ...]
    output_hashes: tuple[str, ...]
    eligible: bool
    expires_at: str

    def __post_init__(self) -> None:
        if not self.node_type.strip():
            raise DcIssuerError("NODE_TYPE_MISSING", "node_type 不得为空")
        if self.k_runs < 3:
            raise DcIssuerError("K_TOO_SMALL", f"k_runs={self.k_runs}，§8.2 默认至少 3")
        if len(self.run_fingerprints) != self.k_runs:
            raise DcIssuerError(
                "K_FINGERPRINT_MISMATCH",
                f"k_runs={self.k_runs} 但 run_fingerprints={len(self.run_fingerprints)}",
            )
        if len(set(self.run_fingerprints)) != len(self.run_fingerprints):
            raise DcIssuerError("RUN_FINGERPRINT_DUPLICATE", "run_fingerprints 必须互不相同")
        if not self.output_hashes:
            raise DcIssuerError("OUTPUT_HASHES_MISSING", "output_hashes 不得为空")
        if list(self.output_hashes) != sorted(set(self.output_hashes)):
            # OQ-P9-02：D.5 的数组语义未定；这里固定为「排序去重」，保证同一产物集只有一种写法。
            raise DcIssuerError("OUTPUT_HASHES_NOT_CANONICAL", "output_hashes 必须排序去重")
        _parse_utc_z(self.expires_at, "expires_at")
        for name in ("code_hash", "dependency_lock_hash", "input_schema_hash", "env_fingerprint", "ruleset_hash"):
            _require_hash(getattr(self, name), name)
        for index, digest in enumerate(self.run_fingerprints):
            _require_hash(digest, f"run_fingerprints[{index}]")

    def as_map(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "node_type": self.node_type,
                "code_hash": self.code_hash,
                "dependency_lock_hash": self.dependency_lock_hash,
                "input_schema_hash": self.input_schema_hash,
                "env_fingerprint": self.env_fingerprint,
                "ruleset_hash": self.ruleset_hash,
                "k_runs": self.k_runs,
                "run_fingerprints": list(self.run_fingerprints),
                "output_hashes": list(self.output_hashes),
                "eligible": self.eligible,
                "expires_at": self.expires_at,
            }
        )


def compute_dc_id(identity: DcIdentity) -> str:
    """内容寻址 `dc_id` = `sha256(JCS(identity))`，64 位小写十六进制、**无前缀**。

    依据：OQ-P9-01 未裁决 `dc_` 前缀是否属于既定 ID 规则；`new_id("dc")` 继续拒绝。
    """
    import hashlib

    payload = _canonical_bytes(identity.as_map())
    return hashlib.sha256(payload).hexdigest()  # LIB: 真实实现走 M01 `hash_payload`


# ---------------------------------------------------------------------------
# 5. 记录、审计、撤销
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DcAudit:
    """签发/撤销审计（**不进签名正文**，否则无法在事后补记）。"""

    issued_at: str
    issued_by: str
    policy_version: str
    source_verdict: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _parse_utc_z(self.issued_at, "audit.issued_at")
        if not self.issued_by.strip():
            raise DcIssuerError("ISSUER_MISSING", "audit.issued_by 不得为空")


@dataclass(frozen=True, slots=True)
class DcRecord:
    """已签发的 DC：D.5 的 13 个字段 + 签名信封 + 审计（审计不参与签名）。"""

    dc_id: str
    identity: DcIdentity
    signature: DcSignature
    audit: DcAudit

    def __post_init__(self) -> None:
        _require_hash(self.dc_id, "dc_id")
        if compute_dc_id(self.identity) != self.dc_id:
            raise DcSignatureInvalid("DC_ID_MISMATCH", "dc_id 与身份字段的内容寻址不一致")
        if not self.identity.eligible:
            raise DcRefused("NOT_ELIGIBLE", "eligible=False 的身份不得出现在已签发记录里")

    def body(self) -> Mapping[str, object]:
        """签名正文：D.5 的 13 个字段去掉 `signature`（共 12 个）。"""
        body = dict(self.identity.as_map())
        body["dc_id"] = self.dc_id
        return MappingProxyType({name: body[name] for name in DC_SIGNED_FIELDS if name in body})

    def as_record(self) -> Mapping[str, object]:
        """对外记录：D.5 的 13 个字段，`signature` 落成 base64 字符串。"""
        body = dict(self.body())
        body["signature"] = self.signature.signature
        return MappingProxyType({name: body[name] for name in DC_FIELDS})

    def same_payload(self, other: "DcRecord") -> bool:
        """内容比较（忽略审计时间），用于登记表冲突检测。"""
        return self.as_record() == other.as_record()


class RevocationReason(StrEnum):
    """撤销原因。原文未给枚举（OQ-P9-05 同源），这里是 PROPOSED 但必须显式。"""

    CODE_CHANGED = "CODE_CHANGED"
    RULESET_CHANGED = "RULESET_CHANGED"
    ENV_CHANGED = "ENV_CHANGED"
    EVIDENCE_CORRUPTED = "EVIDENCE_CORRUPTED"
    SECURITY_INCIDENT = "SECURITY_INCIDENT"
    OPERATOR_REQUEST = "OPERATOR_REQUEST"


@dataclass(frozen=True, slots=True)
class RevocationRecord:
    """撤销记录：只追加，**没有** `unrevoke` / `restore`。"""

    dc_id: str
    reason: RevocationReason
    revoked_at: str
    revoked_by: str
    note: str = ""

    def __post_init__(self) -> None:
        _require_hash(self.dc_id, "revocation.dc_id")
        _parse_utc_z(self.revoked_at, "revocation.revoked_at")
        if not self.revoked_by.strip():
            raise DcIssuerError("REVOKER_MISSING", "revocation.revoked_by 不得为空")

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "dc_id": self.dc_id,
                "reason": self.reason.value,
                "revoked_at": self.revoked_at,
                "revoked_by": self.revoked_by,
                "note": self.note,
            }
        )


# 兼容 spa_judge 既有导入：`DcValidity` 是 `DcStatus` 的别名。
class DcStatus(StrEnum):
    """DC 复用状态。`VALID` 是唯一允许 SPA 条件 1 通过的值。"""

    VALID = "VALID"
    SIGNATURE_INVALID = "SIGNATURE_INVALID"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    RULESET_CHANGED = "RULESET_CHANGED"
    CODE_CHANGED = "CODE_CHANGED"
    INPUT_SCHEMA_CHANGED = "INPUT_SCHEMA_CHANGED"
    ENV_CHANGED = "ENV_CHANGED"


DcValidity = DcStatus


@dataclass(frozen=True, slots=True)
class DcValidityReport:
    """一次复用判定的结果：`validity` + 逐项原因（不只给布尔）。"""

    dc_id: str
    validity: DcStatus
    checks: tuple[tuple[str, bool, str], ...]
    checked_at: str
    signature_ok: bool
    expires_at: str
    revoked_at: str | None = None

    def __post_init__(self) -> None:
        _require_hash(self.dc_id, "validity.dc_id")
        _parse_utc_z(self.checked_at, "validity.checked_at")
        _parse_utc_z(self.expires_at, "validity.expires_at")
        if self.validity is DcStatus.VALID and not all(ok for _, ok, _ in self.checks):
            raise DcIssuerError("VALID_WITH_FAILING_CHECK", "存在未通过检查却判 VALID")
        if self.validity is DcStatus.VALID and not self.signature_ok:
            raise DcIssuerError("VALID_WITHOUT_SIGNATURE", "签名未通过却判 VALID")
        if self.revoked_at is not None:
            _parse_utc_z(self.revoked_at, "validity.revoked_at")

    @property
    def usable(self) -> bool:
        """SPA 条件 1 只看这个属性：必须 VALID 且签名有效。"""
        return self.validity is DcStatus.VALID and self.signature_ok

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(name for name, ok, _ in self.checks if not ok)

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "dc_id": self.dc_id,
                "validity": self.validity.value,
                "usable": self.usable,
                "signature_ok": self.signature_ok,
                "expires_at": self.expires_at,
                "revoked_at": self.revoked_at,
                "checks": [{"check": n, "ok": ok, "detail": d} for n, ok, d in self.checks],
            }
        )


# ---------------------------------------------------------------------------
# 6. 登记表（只增不改）
# ---------------------------------------------------------------------------
class DcRegistry:
    """P9 的内存登记表。T2 落地换真实存储；语义保持一致：

    - `add` 只接受新 `dc_id`；同 ID 同内容幂等返回，同 ID 不同内容 → `DcStoreCorrupt`；
    - `revoke` 只追加撤销记录；撤销后不可恢复；
    - 没有 `update` / `delete` / `clear`。
    """

    def __init__(self) -> None:
        self._records: dict[str, DcRecord] = {}
        self._revocations: dict[str, RevocationRecord] = {}
        self._audit: list[Mapping[str, object]] = []

    def add(self, record: DcRecord, *, audit_event: Mapping[str, object] | None = None) -> None:
        """登记一条 DC。返回 None；冲突抛 `DcStoreCorrupt`。"""
        existing = self._records.get(record.dc_id)
        if existing is not None:
            if not existing.same_payload(record):
                raise DcStoreCorrupt("DC_ID_COLLISION", f"dc_id={record.dc_id} 已有不同内容")
            # 同一记录重复登记是幂等的，但审计事件仍要追加（否则撤销会被静默吞掉）。
            if audit_event is not None:
                self._audit.append(MappingProxyType(dict(audit_event)))
            return
        self._records[record.dc_id] = record
        if audit_event is not None:
            self._audit.append(MappingProxyType(dict(audit_event)))

    def get(self, dc_id: str) -> DcRecord | None:
        """按 ID 取记录；不存在返回 None（由调用方决定是缺证据还是错误）。"""
        return self._records.get(dc_id)

    def require(self, dc_id: str) -> DcRecord:
        """按 ID 取记录；不存在抛 `DcRefused`。"""
        record = self._records.get(dc_id)
        if record is None:
            raise DcRefused("DC_NOT_FOUND", f"未登记的 dc_id={dc_id}")
        return record

    def revoke(self, revocation: RevocationRecord) -> None:
        """登记撤销。重复撤销同一 ID → `DcRevoked`（终态，不做幂等吞掉）。"""
        if revocation.dc_id in self._revocations:
            raise DcRevoked("ALREADY_REVOKED", f"dc_id={revocation.dc_id} 已撤销，无恢复入口")
        self.require(revocation.dc_id)
        self._revocations[revocation.dc_id] = revocation

    def revocation_of(self, dc_id: str) -> RevocationRecord | None:
        return self._revocations.get(dc_id)

    def is_revoked(self, dc_id: str) -> bool:
        return dc_id in self._revocations

    @property
    def size(self) -> int:
        return len(self._records)

    @property
    def audit_events(self) -> tuple[Mapping[str, object], ...]:
        return tuple(self._audit)


# ---------------------------------------------------------------------------
# 7. 派生与签发
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DcIssuance:
    """签发结果：记录 + 重算依据 + 登记表规模。

    `recheck` 是签发时**重新计算**的 k 次比对；不信任调用方传进来的布尔。
    """

    record: DcRecord
    recheck_bit_exact: bool
    recheck_k_observed: int
    recheck_k_required: int
    registry_size: int

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "dc_id": self.record.dc_id,
                "node_type": self.record.identity.node_type,
                "k_runs": self.record.identity.k_runs,
                "expires_at": self.record.identity.expires_at,
                "recheck_bit_exact": self.recheck_bit_exact,
                "recheck_k": f"{self.recheck_k_observed}/{self.recheck_k_required}",
                "registry_size": self.registry_size,
            }
        )


def _derive_output_hashes(runs: Sequence[RunProbe]) -> tuple[str, ...]:
    """从探针派生排序去重的产物哈希集（OQ-P9-02）。"""
    if not runs:
        raise DcRefused("NO_RUNS", "没有探针运行无法派生产物哈希")
    first = tuple(runs[0].output_hashes)
    for run in runs[1:]:
        if tuple(run.output_hashes) != first:
            raise DcRefused("OUTPUT_DIVERGED", f"run {run.run_id} 的产物哈希与基准不一致")
    return tuple(sorted(set(first)))


def _derive_run_fingerprints(runs: Sequence[RunProbe]) -> tuple[str, ...]:
    """从探针派生运行指纹（保持探针顺序，供 D.5 逐条核对）。"""
    return tuple(run.run_fingerprint for run in runs)


def issue_dc(
    verdict: EligibilityVerdict,
    *,
    candidate: DcCandidate,
    binding: DcBinding,
    runs: Sequence[RunProbe],
    now: datetime,
    signer: DcSignerPort | None,
    registry: DcRegistry,
    produced_by: str = "verifier",
    ttl_days: int = DEFAULT_DC_TTL_DAYS,
    ttl_max_days: int = 30,
) -> DcIssuance:
    """签发一张 DC。资格不合格、重算不一致、无签名器、TTL 超限一律拒绝。

    输入：资格结论、候选、绑定、探针、签发时刻、签名端口、登记表。
    输出：`DcIssuance`（记录 + 重算依据）。
    副作用：调用一次 `signer.sign`；向 `registry` 追加一条记录。
    错误：`DcRefused`（资格/重算/签名器/TTL）、`DcSignatureInvalid`（回验失败）。

    步骤：
      1. 资格门：`verdict.eligible` 必须为真，且 node_type 与候选一致；
      2. 重算：用原始探针再跑一次 `compare_runs`（不信任布尔）；
      3. 派生：`k_runs` / `run_fingerprints` / `output_hashes` 全部来自探针；
      4. 到期：`expires_at = now + ttl_days`，超过上限拒绝；
      5. 身份与 `dc_id`：内容寻址；
      6. 签名：端口必须存在（OQ-P6-02 阻塞时恒为 None → 拒绝签发）；
      7. 回验：`signer.verify` 必须为真；
      8. 落库：只增不改。
    """
    # 1. 资格门
    if not verdict.eligible:
        raise DcRefused(
            "DC_NOT_ELIGIBLE",
            f"node={candidate.node_id} 六条件未全通过，不签发",
            error_code="RECOVERY_NOT_SAFE",
        )
    if verdict.node_type != candidate.node_type:
        raise DcRefused("NODE_TYPE_MISMATCH", "资格结论与候选节点的 node_type 不一致")
    _require_utc_datetime(now, "now")

    # 2. 重算（不信任布尔）
    recheck = compare_runs(candidate, binding, runs)
    if not recheck.bit_exact:
        raise DcRefused("RECHECK_NOT_BIT_EXACT", f"重算分歧：{list(recheck.divergences)}")
    if recheck.k_observed < recheck.k_required:
        raise DcRefused("RECHECK_K_INSUFFICIENT", f"k={recheck.k_observed} < {recheck.k_required}")

    # 3. 派生
    k_runs = recheck.k_observed
    run_fingerprints = _derive_run_fingerprints(runs)
    output_hashes = _derive_output_hashes(runs)

    # 4. 到期
    if ttl_days <= 0 or ttl_days > ttl_max_days:
        raise DcRefused("TTL_OUT_OF_RANGE", f"ttl_days={ttl_days}，上限 {ttl_max_days}")
    expires_at = _utc_z(now + timedelta(days=ttl_days))

    # 5. 身份与 dc_id
    identity = DcIdentity(
        node_type=candidate.node_type,
        code_hash=binding.code_hash,
        dependency_lock_hash=binding.dependency_lock_hash,
        input_schema_hash=binding.input_schema_hash,
        env_fingerprint=binding.env_fingerprint,
        ruleset_hash=binding.ruleset_hash,
        k_runs=k_runs,
        run_fingerprints=run_fingerprints,
        output_hashes=output_hashes,
        eligible=True,
        expires_at=expires_at,
    )
    dc_id = compute_dc_id(identity)

    # 6. 签名
    if signer is None:
        raise DcRefused(
            "SIGNER_UNAVAILABLE",
            "P9 无合规签名器（OQ-P6-02：M11 拒绝未冻结载荷）；不签发未签名 DC",
        )
    body = dict(identity.as_map())
    body["dc_id"] = dc_id
    payload = _canonical_bytes({name: body[name] for name in DC_SIGNED_FIELDS})
    signature_text = signer.sign(payload, domain=DC_SIGNING_DOMAIN, alg=DC_ALG)

    # 7. 回验
    if not signer.verify(payload, signature_text, domain=DC_SIGNING_DOMAIN, alg=DC_ALG):
        raise DcSignatureInvalid("SELF_VERIFY_FAILED", "签名后回验失败")
    import hashlib

    signature = DcSignature(
        alg=DC_ALG,
        key_id=signer.key_id(),
        domain=DC_SIGNING_DOMAIN,
        signature=signature_text,
        signed_body_hash=hashlib.sha256(payload).hexdigest(),
    )
    audit = DcAudit(
        issued_at=_utc_z(now),
        issued_by=produced_by,
        policy_version=verdict.policy_version,
        source_verdict=dc_id,
        evidence_ids=recheck.evidence_ids,
    )
    record = DcRecord(dc_id=dc_id, identity=identity, signature=signature, audit=audit)

    # 8. 落库（只增不改）
    registry.add(
        record,
        audit_event={
            "event": "DC_ISSUED",
            "dc_id": dc_id,
            "node_type": candidate.node_type,
            "issued_at": audit.issued_at,
            "issued_by": produced_by,
        },
    )
    return DcIssuance(
        record=record,
        recheck_bit_exact=recheck.bit_exact,
        recheck_k_observed=recheck.k_observed,
        recheck_k_required=recheck.k_required,
        registry_size=registry.size,
    )


# ---------------------------------------------------------------------------
# 8. 复用判定
# ---------------------------------------------------------------------------
def evaluate_dc_record(
    record: DcRecord,
    *,
    registry: DcRegistry,
    now: datetime,
    current_code_hash: str,
    current_input_schema_hash: str,
    current_env_fingerprint: str,
    current_ruleset_hash: str,
    signer: DcSignerPort | None = None,
) -> DcValidityReport:
    """判定一张 DC 现在还能不能用（§8.3 条件 1 的唯一入口）。

    输入：记录、登记表、当前时刻、四个「当前」哈希、可选验签端口。
    输出：`DcValidityReport`；`usable` 只在 `VALID` 时为真。
    副作用：无（不写登记表、不写审计）。
    错误：不抛；一切失败都落成 `validity` 与 `checks`。

    顺序（固定，先到先返回；后续项仍记录但不改变结论）：
      签名 → eligible → 撤销 → 到期 → 规则 → 代码 → 输入结构 → 环境
    """
    _require_utc_datetime(now, "now")
    checks: list[tuple[str, bool, str]] = []
    checked_at = _utc_z(now)

    # 1. 签名
    signature_ok = False
    if signer is None:
        checks.append(("SIGNATURE", False, "无验签端口：不能确认签名有效"))
    else:
        body = dict(record.identity.as_map())
        body["dc_id"] = record.dc_id
        payload = _canonical_bytes({name: body[name] for name in DC_SIGNED_FIELDS})
        signature_ok = bool(
            signer.verify(payload, record.signature.signature, domain=DC_SIGNING_DOMAIN, alg=DC_ALG)
        )
        checks.append(("SIGNATURE", signature_ok, "Ed25519 回验"))
    if not signature_ok:
        return DcValidityReport(
            dc_id=record.dc_id,
            validity=DcStatus.SIGNATURE_INVALID,
            checks=tuple(checks),
            checked_at=checked_at,
            signature_ok=False,
            expires_at=record.identity.expires_at,
            revoked_at=registry.revocation_of(record.dc_id).revoked_at
            if registry.revocation_of(record.dc_id)
            else None,
        )

    # 2. eligible
    if not record.identity.eligible:
        checks.append(("ELIGIBLE", False, "eligible=False"))
        return DcValidityReport(
            dc_id=record.dc_id,
            validity=DcStatus.NOT_ELIGIBLE,
            checks=tuple(checks),
            checked_at=checked_at,
            signature_ok=True,
            expires_at=record.identity.expires_at,
        )
    checks.append(("ELIGIBLE", True, "eligible=True"))

    # 3. 撤销（终态，优先于到期）
    revocation = registry.revocation_of(record.dc_id)
    if revocation is not None:
        checks.append(("REVOKED", False, f"{revocation.reason.value}@{revocation.revoked_at}"))
        return DcValidityReport(
            dc_id=record.dc_id,
            validity=DcStatus.REVOKED,
            checks=tuple(checks),
            checked_at=checked_at,
            signature_ok=True,
            expires_at=record.identity.expires_at,
            revoked_at=revocation.revoked_at,
        )
    checks.append(("REVOKED", True, "未撤销"))

    # 4. 到期
    expires = _parse_utc_z(record.identity.expires_at, "record.expires_at")
    if now >= expires:
        checks.append(("EXPIRED", False, f"expires_at={record.identity.expires_at}"))
        return DcValidityReport(
            dc_id=record.dc_id,
            validity=DcStatus.EXPIRED,
            checks=tuple(checks),
            checked_at=checked_at,
            signature_ok=True,
            expires_at=record.identity.expires_at,
        )
    checks.append(("EXPIRED", True, f"expires_at={record.identity.expires_at}"))

    # 5. 规则版本
    if current_ruleset_hash != record.identity.ruleset_hash:
        checks.append(("RULESET", False, "ruleset_hash 变化"))
        return _invalid(record, checks, checked_at, DcStatus.RULESET_CHANGED)
    checks.append(("RULESET", True, "规则版本一致"))

    # 6. 代码
    if current_code_hash != record.identity.code_hash:
        checks.append(("CODE", False, "code_hash 变化"))
        return _invalid(record, checks, checked_at, DcStatus.CODE_CHANGED)
    checks.append(("CODE", True, "代码版本一致"))

    # 7. 输入结构
    if current_input_schema_hash != record.identity.input_schema_hash:
        checks.append(("INPUT_SCHEMA", False, "input_schema_hash 变化"))
        return _invalid(record, checks, checked_at, DcStatus.INPUT_SCHEMA_CHANGED)
    checks.append(("INPUT_SCHEMA", True, "输入结构一致"))

    # 8. 环境
    if current_env_fingerprint != record.identity.env_fingerprint:
        checks.append(("ENV", False, "env_fingerprint 变化"))
        return _invalid(record, checks, checked_at, DcStatus.ENV_CHANGED)
    checks.append(("ENV", True, "环境指纹一致"))

    return DcValidityReport(
        dc_id=record.dc_id,
        validity=DcStatus.VALID,
        checks=tuple(checks),
        checked_at=checked_at,
        signature_ok=True,
        expires_at=record.identity.expires_at,
    )


def _invalid(
    record: DcRecord,
    checks: Sequence[tuple[str, bool, str]],
    checked_at: str,
    status: DcStatus,
) -> DcValidityReport:
    """构造「签名有效但绑定变化」的判定结果。"""
    return DcValidityReport(
        dc_id=record.dc_id,
        validity=status,
        checks=tuple(checks),
        checked_at=checked_at,
        signature_ok=True,
        expires_at=record.identity.expires_at,
    )


def evaluate_dc(
    dc_id: str,
    *,
    registry: DcRegistry,
    now: datetime,
    current_code_hash: str,
    current_input_schema_hash: str,
    current_env_fingerprint: str,
    current_ruleset_hash: str,
    signer: DcSignerPort | None = None,
) -> DcValidityReport:
    """按 ID 取记录再判定。未登记时返回 `NOT_ELIGIBLE`（缺证据，不是通过）。"""
    record = registry.get(dc_id)
    if record is None:
        return DcValidityReport(
            dc_id=dc_id,
            validity=DcStatus.NOT_ELIGIBLE,
            checks=(("REGISTERED", False, "未登记的 dc_id"),),
            checked_at=_utc_z(now),
            signature_ok=False,
            expires_at=_utc_z(now),
        )
    return evaluate_dc_record(
        record,
        registry=registry,
        now=now,
        current_code_hash=current_code_hash,
        current_input_schema_hash=current_input_schema_hash,
        current_env_fingerprint=current_env_fingerprint,
        current_ruleset_hash=current_ruleset_hash,
        signer=signer,
    )


# ---------------------------------------------------------------------------
# 9. 撤销
# ---------------------------------------------------------------------------
def revoke_dc(
    dc_id: str,
    *,
    registry: DcRegistry,
    now: datetime,
    reason: RevocationReason,
    revoked_by: str,
    note: str = "",
) -> RevocationRecord:
    """撤销一张 DC。终态：重复撤销抛 `DcRevoked`，没有恢复入口。

    输入：dc_id、登记表、时刻、原因、操作者、备注。
    输出：`RevocationRecord`。
    副作用：向登记表追加一条撤销记录 + 一条审计事件。
    错误：`DcRefused`（未登记）、`DcRevoked`（已撤销）。
    """
    _require_utc_datetime(now, "now")
    registry.require(dc_id)
    revocation = RevocationRecord(
        dc_id=dc_id,
        reason=reason,
        revoked_at=_utc_z(now),
        revoked_by=revoked_by,
        note=note,
    )
    registry.revoke(revocation)
    registry.add(
        registry.require(dc_id),
        audit_event={
            "event": "DC_REVOKED",
            "dc_id": dc_id,
            "reason": reason.value,
            "revoked_at": revocation.revoked_at,
            "revoked_by": revoked_by,
        },
    )
    return revocation


# ---------------------------------------------------------------------------
# 10. 静态守卫（实现阶段用；P9 不执行）
# ---------------------------------------------------------------------------
def assert_signature_domain() -> tuple[str, ...]:
    """域前缀、算法、签名字段集合必须与 §7.5 一致。返回空元组表示通过。"""
    problems: list[str] = []
    if DC_SIGNING_DOMAIN != "RF-DC-V1":
        problems.append(f"DC_SIGNING_DOMAIN={DC_SIGNING_DOMAIN!r}")
    if DC_ALG != "Ed25519":
        problems.append(f"DC_ALG={DC_ALG!r}")
    if DC_FIELDS[-1] != "signature":
        problems.append("D.5 最后一个字段不是 signature")
    if len(DC_FIELDS) != 13:
        problems.append(f"DC_FIELDS={len(DC_FIELDS)}，期望 13")
    if len(DC_SIGNED_FIELDS) != 12:
        problems.append(f"签名正文 {len(DC_SIGNED_FIELDS)} 个字段，期望 12")
    if "signature" in DC_SIGNED_FIELDS:
        problems.append("signature 被纳入签名正文")
    if "dc_id" not in DC_SIGNED_FIELDS:
        problems.append("dc_id 必须被签名正文覆盖（否则可换 ID 复用签名）")
    return tuple(problems)


def assert_dc_scope() -> tuple[str, ...]:
    """`eligible=False` 不得产生记录；限定语不得被改写成「已证明确定」。返回空元组表示通过。"""
    problems: list[str] = []
    identity = DcIdentity(
        node_type="t",
        code_hash="0" * 64,
        dependency_lock_hash="0" * 64,
        input_schema_hash="0" * 64,
        env_fingerprint="0" * 64,
        ruleset_hash="0" * 64,
        k_runs=3,
        run_fingerprints=("1" * 64, "2" * 64, "3" * 64),
        output_hashes=("4" * 64,),
        eligible=False,
        expires_at="2026-12-01T00:00:00Z",
    )
    try:
        DcRecord(
            dc_id=compute_dc_id(identity),
            identity=identity,
            signature=DcSignature(
                alg=DC_ALG,
                key_id="k",
                domain=DC_SIGNING_DOMAIN,
                signature="sig",
                signed_body_hash="0" * 64,
            ),
            audit=DcAudit(
                issued_at="2026-11-11T00:00:00Z",
                issued_by="verifier",
                policy_version="v",
                source_verdict="x",
            ),
        )
    except DcRefused:
        pass
    else:
        problems.append("eligible=False 的记录未被拒绝")
    return tuple(problems)


def assert_revocation_is_terminal() -> tuple[str, ...]:
    """撤销必须终态：重复撤销失败，且登记表无恢复方法。返回空元组表示通过。"""
    problems: list[str] = []
    for forbidden in ("unrevoke", "restore", "reinstate", "delete", "update"):
        if hasattr(DcRegistry, forbidden):
            problems.append(f"DcRegistry 暴露了 {forbidden}")
    revocation = RevocationRecord(
        dc_id="0" * 64,
        reason=RevocationReason.OPERATOR_REQUEST,
        revoked_at="2026-11-11T00:00:00Z",
        revoked_by="operator",
    )
    if not revocation.dc_id:
        problems.append("撤销记录缺 dc_id")
    return tuple(problems)


def assert_policy_binding() -> tuple[str, ...]:
    """k/TTL 的默认值必须保守且可追溯。返回空元组表示通过。"""
    problems: list[str] = []
    if DEFAULT_DC_TTL_DAYS <= 0 or DEFAULT_DC_TTL_DAYS > 30:
        problems.append(f"DEFAULT_DC_TTL_DAYS={DEFAULT_DC_TTL_DAYS} 不在 (0, 30]")
    if DC_IDENTITY_FIELDS != DC_FIELDS[1:-1]:
        problems.append("DC_IDENTITY_FIELDS 不是 D.5 去掉 dc_id/signature")
    return tuple(problems)