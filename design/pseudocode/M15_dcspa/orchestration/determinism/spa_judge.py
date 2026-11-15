"""M15 · orchestration/determinism/spa_judge.py — SPA 五条件判定与省略凭证（P9 伪代码）。
MODULE: M15 DC/SPA ｜ 阶段：P9「DC/SPA 与 VAS」
追踪：FR-015（T2 / G4）、策划书 §8.3、§8.4 ⑧ 分支、附录 D.5、§7.5 签名
FR+依赖：`dc_issuer`（DC 复用判定）、M09 `Gate` 的只读复检结果、M11 签名端口（SPA 由 Verifier 签）
不变量：**默认动作是 REEXECUTE**；只有五条件全部为真且每条都有证据才 SKIP；
        任一条件「拿不到证据」→ REEXECUTE；签名失败/无签名器 → REEXECUTE（绝不返回无签名 SKIP）
错误码：FEATURE_FLAG_NOT_PERMITTED（403）、SIGNATURE_INVALID（422）、SCHEMA_INVALID（422）、
        RECOVERY_NOT_SAFE（409）
写入者：无。`SpaRecord` 是冻结值对象；签名与落库走端口
状态：伪代码；不执行、不真签、不剪枝

## 为什么「默认重跑」必须写成枚举第一项

  §8.3 的五条是**合取**：全部满足才允许跳过。把默认值写成 `REEXECUTE` 意味着新增条件、
  证据缺失、端口异常、代码改动都会自动退回安全侧；只有显式拼齐五条证据才可能走到 SKIP。
  `SpaDecision` 在构造期拒绝「SKIP 但没有记录」和「REEXECUTE 却带记录」，所以这个默认值
  不是注释，是结构。

## 五条件与证据（§8.3 逐字）

  | 条件 | 原文 | 需要什么证据 |
  |---|---|---|
  | DC_VALID | 节点类型存在有效 DC，且输入结构、代码、环境和规则版本与当前一致。 | `DcValidityReport.usable` + 四个当前哈希 |
  | PREDECESSOR_HASHES_UNCHANGED | 所有直接前驱输出哈希与恢复前历史一致；上游变化沿 DAG 传播失效。 | 每个直接前驱的 (node_id, hash) 对 |
  | DISK_REHASH_MATCHES | 磁盘产物现场重算 SHA-256，与历史证据一致；解析软链接后不得越界或指向旧目录。 | 现场重算结果 + realpath 归属 |
  | GATE_RECHECK_PASSES | 节点旧证据在当前规则集下仍通过 Gate，未过期、未撤销、无新冲突。 | 当前 ruleset 下的 Gate 复检 |
  | NO_SIDE_EFFECT | 节点无副作用，且任务规则未要求本次必须实际执行。 | 副作用类别 + 本次执行要求 |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

from .dc_issuer import (
    DcIssuerError,
    DcRecord,
    DcStatus,
    DcValidityReport,
    evaluate_dc_record,
)

__all__ = [
    "ALLOWED_PRODUCERS",
    "DEFAULT_ACTION",
    "FORBIDDEN_PRODUCERS",
    "SPA_CONDITION_ORDER",
    "SPA_FIELDS",
    "SPA_LITERALS",
    "SPA_SIGNING_DOMAIN",
    "ArtifactExpectation",
    "ArtifactInspection",
    "ConditionOutcome",
    "EvidenceRef",
    "GateRecheck",
    "ReexecuteReason",
    "SideEffectFacts",
    "SkipReason",
    "SpaAction",
    "SpaCondition",
    "SpaDecision",
    "SpaJudgeError",
    "SpaIdentity",
    "SpaRecord",
    "SpaRefused",
    "SpaRequest",
    "SpaSignature",
    "SpaSignerPort",
    "assert_default_reexecute",
    "assert_evidence_is_not_boolean",
    "assert_fields_match_d5",
    "assert_no_side_effect_skip",
    "assert_no_unsigned_skip",
    "assert_skip_requires_all_five",
    "compute_spa_id",
    "judge_spa",
]

STAGE: Final[str] = "P9"


# ---------------------------------------------------------------------------
# 1. 动作、条件、原因
# ---------------------------------------------------------------------------
class SpaAction(StrEnum):
    """SPA 判定的动作。**第一成员是 REEXECUTE**：默认值不是靠 if 兜底，是靠枚举顺序。"""

    REEXECUTE = "REEXECUTE"
    SKIP = "SKIP"


DEFAULT_ACTION: Final[SpaAction] = SpaAction.REEXECUTE


class SpaCondition(StrEnum):
    """§8.3 的五条，顺序即原文顺序。"""

    DC_VALID = "DC_VALID"
    PREDECESSOR_HASHES_UNCHANGED = "PREDECESSOR_HASHES_UNCHANGED"
    DISK_REHASH_MATCHES = "DISK_REHASH_MATCHES"
    GATE_RECHECK_PASSES = "GATE_RECHECK_PASSES"
    NO_SIDE_EFFECT = "NO_SIDE_EFFECT"


SPA_CONDITION_ORDER: Final[tuple[SpaCondition, ...]] = (
    SpaCondition.DC_VALID,
    SpaCondition.PREDECESSOR_HASHES_UNCHANGED,
    SpaCondition.DISK_REHASH_MATCHES,
    SpaCondition.GATE_RECHECK_PASSES,
    SpaCondition.NO_SIDE_EFFECT,
)

#: §8.3 五条原文，逐字。
SPA_LITERALS: Final[Mapping[SpaCondition, str]] = MappingProxyType(
    {
        SpaCondition.DC_VALID: "节点类型存在有效 DC，且输入结构、代码、环境和规则版本与当前一致。",
        SpaCondition.PREDECESSOR_HASHES_UNCHANGED: "所有直接前驱输出哈希与恢复前历史一致；上游变化沿 DAG 传播失效。",
        SpaCondition.DISK_REHASH_MATCHES: "磁盘产物现场重算 SHA-256，与历史证据一致；解析软链接后不得越界或指向旧目录。",
        SpaCondition.GATE_RECHECK_PASSES: "节点旧证据在当前规则集下仍通过 Gate，未过期、未撤销、无新冲突。",
        SpaCondition.NO_SIDE_EFFECT: "节点无副作用，且任务规则未要求本次必须实际执行。",
    }
)


class ReexecuteReason(StrEnum):
    """重跑原因。区分「缺证据」与「证据为假」——两者都必须重跑，但归因不同。"""

    DEFAULT_CONSERVATIVE = "DEFAULT_CONSERVATIVE"
    NO_DC = "NO_DC"
    DC_NOT_VALID = "DC_NOT_VALID"
    DC_SIGNATURE_INVALID = "DC_SIGNATURE_INVALID"
    PREDECESSOR_HASH_CHANGED = "PREDECESSOR_HASH_CHANGED"
    PREDECESSOR_MISSING = "PREDECESSOR_MISSING"
    DISK_REHASH_MISMATCH = "DISK_REHASH_MISMATCH"
    ARTIFACT_MISSING_ON_DISK = "ARTIFACT_MISSING_ON_DISK"
    DISK_PATH_ESCAPE = "DISK_PATH_ESCAPE"
    DISK_PATH_LEGACY = "DISK_PATH_LEGACY"
    GATE_NOT_PASSING = "GATE_NOT_PASSING"
    GATE_EXPIRED = "GATE_EXPIRED"
    GATE_REVOKED = "GATE_REVOKED"
    GATE_CONFLICT = "GATE_CONFLICT"
    SIDE_EFFECT_NODE = "SIDE_EFFECT_NODE"
    MANDATORY_EXECUTION = "MANDATORY_EXECUTION"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_PRODUCER_FORBIDDEN = "EVIDENCE_PRODUCER_FORBIDDEN"
    PLAN_NOT_FROZEN = "PLAN_NOT_FROZEN"
    SIGNER_UNAVAILABLE = "SIGNER_UNAVAILABLE"
    SIGNING_FAILED = "SIGNING_FAILED"


class SkipReason(StrEnum):
    """跳过原因。D.5 的 `skip_reason` 只允许这些值（原文未给枚举，PROPOSED）。"""

    DC_AND_PREDECESSORS_UNCHANGED = "DC_AND_PREDECESSORS_UNCHANGED"
    DC_AND_GATE_RECHECK_PASSED = "DC_AND_GATE_RECHECK_PASSED"


# ---------------------------------------------------------------------------
# 2. 错误
# ---------------------------------------------------------------------------
class SpaJudgeError(RuntimeError):
    """SPA 判定错误基类。"""

    error_code: Final[str] = "SPA_ERROR"
    http_status: Final[int] = 422

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{self.error_code}/{reason}：{detail}")


class SpaRefused(SpaJudgeError):
    """记录/输入不合格（字段不符 D.5、计划未冻结、开关关闭）。"""

    error_code: Final[str] = "SCHEMA_INVALID"
    http_status: Final[int] = 422


class SpaNotEnabled(SpaRefused):
    """T0/T1 或开关关闭时要求判 SPA：能力未开。对外 403。"""

    error_code: Final[str] = "FEATURE_FLAG_NOT_PERMITTED"
    http_status: Final[int] = 403

    def __init__(self, tier: str, flag_state: str) -> None:
        super().__init__(
            "DC_SPA_REQUIRES_T2",
            f"tier={tier!r}，dc_spa={flag_state!r}；SPA 判定只在 T2 且开关为 true 时可用",
        )


# ---------------------------------------------------------------------------
# 3. 证据
# ---------------------------------------------------------------------------
#: 允许生产 SPA 证据的角色。Agent/LLM/Harness 声明的「已检查」不得作为证据。
ALLOWED_PRODUCERS: Final[frozenset[str]] = frozenset(
    {"collector", "verifier", "m03_env", "m08_gate", "m14_recovery", "m11_signer"}
)

#: 明确禁止的生产者（E0/E1 边界，AGENTS §4.2/§4.8）。
FORBIDDEN_PRODUCERS: Final[frozenset[str]] = frozenset(
    {"agent", "llm", "harness", "planner", "executor", "adapter"}
)


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """证据引用。`producer` 必须在白名单内——这是把 E0 声明挡在门外的唯一位置。"""

    evidence_id: str
    producer: str
    kind: str

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise SpaRefused("EVIDENCE_ID_MISSING", "证据引用必须有编号")
        if not self.kind.strip():
            raise SpaRefused("EVIDENCE_KIND_MISSING", f"证据 {self.evidence_id} 缺 kind")
        lowered = self.producer.strip().lower()
        if lowered in FORBIDDEN_PRODUCERS:
            raise SpaRefused(
                "EVIDENCE_PRODUCER_FORBIDDEN",
                f"{self.evidence_id} 的生产者 {self.producer!r} 不得提供执行类证据（E0/E1 边界）",
            )
        if lowered not in ALLOWED_PRODUCERS:
            raise SpaRefused(
                "EVIDENCE_PRODUCER_UNKNOWN",
                f"{self.evidence_id} 的生产者 {self.producer!r} 不在白名单",
            )

    def as_detail(self) -> Mapping[str, str]:
        return MappingProxyType(
            {"evidence_id": self.evidence_id, "producer": self.producer, "kind": self.kind}
        )


@dataclass(frozen=True, slots=True)
class ConditionOutcome:
    """一条条件的结论。PASS 必须带证据；非 PASS 必须带原因。"""

    condition: SpaCondition
    outcome: SpaAction
    evidence: tuple[EvidenceRef, ...] = ()
    reason: ReexecuteReason | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.outcome is SpaAction.SKIP and not self.evidence:
            raise SpaRefused(
                "PASS_WITHOUT_EVIDENCE",
                f"{self.condition.value} 判为通过但没有证据引用：无编号的结论不可复核",
            )
        if self.outcome is SpaAction.SKIP and self.reason is not None:
            raise SpaRefused("PASS_WITH_REASON", f"{self.condition.value} 通过却带重跑原因")
        if self.outcome is SpaAction.REEXECUTE and self.reason is None:
            raise SpaRefused("REEECUTE_WITHOUT_REASON", f"{self.condition.value} 未通过但没有原因")

    @property
    def passed(self) -> bool:
        return self.outcome is SpaAction.SKIP

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "condition": self.condition.value,
                "outcome": self.outcome.value,
                "reason": self.reason.value if self.reason else None,
                "evidence": [e.as_detail() for e in self.evidence],
                "detail": self.detail,
            }
        )


# ---------------------------------------------------------------------------
# 4. 输入事实
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ArtifactExpectation:
    """历史证据里的产物期望：相对路径 + 当时的 SHA-256。"""

    relative_path: str
    expected_sha256: str

    def __post_init__(self) -> None:
        if not self.relative_path.strip():
            raise SpaRefused("ARTIFACT_PATH_MISSING", "产物路径不得为空")
        _require_sha256(self.expected_sha256, f"artifact.{self.relative_path}.expected")


@dataclass(frozen=True, slots=True)
class ArtifactInspection:
    """现场复算结果：实际哈希、解析软链接后的真实路径、是否仍在工作区。"""

    relative_path: str
    actual_sha256: str | None
    resolved_path: str
    within_workspace: bool
    points_to_legacy_directory: bool = False

    def __post_init__(self) -> None:
        if not self.relative_path.strip():
            raise SpaRefused("ARTIFACT_PATH_MISSING", "产物路径不得为空")
        if self.actual_sha256 is not None:
            _require_sha256(self.actual_sha256, f"artifact.{self.relative_path}.actual")
        if not self.resolved_path.strip():
            raise SpaRefused("ARTIFACT_REALPATH_MISSING", "必须记录 realpath 结果")

    @property
    def exists(self) -> bool:
        return self.actual_sha256 is not None


@dataclass(frozen=True, slots=True)
class GateRecheck:
    """当前规则集下的 Gate 复检。四个字段缺一不可：通过、过期、撤销、新冲突。"""

    ruleset_hash: str
    passed: bool
    expired: bool
    revoked: bool
    conflicts: tuple[str, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        _require_sha256(self.ruleset_hash, "gate.ruleset_hash")

    @property
    def clean(self) -> bool:
        return self.passed and not self.expired and not self.revoked and not self.conflicts


@dataclass(frozen=True, slots=True)
class SideEffectFacts:
    """副作用与「本次必须执行」。两个字段都是保守方向：不知道就算有。"""

    has_side_effect: bool
    rules_require_execution: bool
    evidence: tuple[EvidenceRef, ...] = ()

    @property
    def can_skip(self) -> bool:
        return not self.has_side_effect and not self.rules_require_execution


@dataclass(frozen=True, slots=True)
class SpaRequest:
    """一次判定的全部只读输入。判定期间不得再读外部状态（避免 TOCTOU）。"""

    task_id: str
    node_id: str
    recovery_plan_id: str
    recovery_plan_frozen: bool
    dc_id: str
    dc_record: DcRecord | None
    dc_validity: DcValidityReport | None
    predecessor_hashes_now: tuple[tuple[str, str], ...]
    predecessor_hashes_at_recovery: tuple[tuple[str, str], ...]
    artifacts_expected: tuple[ArtifactExpectation, ...]
    artifacts_inspected: tuple[ArtifactInspection, ...]
    gate: GateRecheck
    side_effects: SideEffectFacts
    now: datetime
    current_code_hash: str
    current_input_schema_hash: str
    current_env_fingerprint: str
    current_ruleset_hash: str
    evidence: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        for name in ("task_id", "node_id", "recovery_plan_id"):
            if not str(getattr(self, name)).strip():
                raise SpaRefused("IDENTITY_MISSING", f"{name} 不得为空")
        _require_utc(self.now, "request.now")
        if not self.predecessor_hashes_now:
            raise SpaRefused(
                "PREDECESSORS_MISSING",
                "即使没有前驱也必须显式表达；空元组会被读成「没检查」",
            )
        # 前驱是否变化不在构造期判：交给条件 2 产出可断言的结论。
        if len({p for p, _ in self.predecessor_hashes_now}) != len(self.predecessor_hashes_now):
            raise SpaRefused("PREDECESSOR_DUPLICATE", "同一前驱出现两次")

    def evidence_for(self, condition: SpaCondition) -> tuple[EvidenceRef, ...]:
        """按 kind 取该条件相关证据；kind 约定为条件名的小写。"""
        wanted = condition.value.lower()
        return tuple(e for e in self.evidence if e.kind.lower() == wanted)


@dataclass(frozen=True, slots=True)
class SpaSignature:
    """SPA 签名信封。`verify` 由端口完成；本对象只固定「签了什么」。"""

    alg: str
    key_id: str
    domain: str
    signature: str
    signed_body_hash: str

    def __post_init__(self) -> None:
        if self.alg != "Ed25519":
            raise SpaRefused("ALG_MISMATCH", "SPA 只接受 Ed25519（§7.5）")
        if self.domain != SPA_SIGNING_DOMAIN:
            raise SpaRefused("DOMAIN_MISMATCH", f"域前缀必须是 {SPA_SIGNING_DOMAIN!r}")
        if not self.key_id.strip() or not self.signature.strip():
            raise SpaRefused("SIGNATURE_FIELDS_MISSING", "key_id / signature 不得为空")
        _require_sha256(self.signed_body_hash, "signature.signed_body_hash")


#: §7.5 要求 DC/SPA 各自有域分离前缀；具体字符串原文未给（OQ-P9-04，PROPOSED）。
SPA_SIGNING_DOMAIN: Final[str] = "RF-SPA-V1"

#: 附录 D.5「SPA」12 个字段，顺序即原文分组顺序。
SPA_FIELDS: Final[tuple[str, ...]] = (
    "spa_id",
    "task_id",
    "node_id",
    "recovery_plan_id",
    "dc_id",
    "predecessor_hashes",
    "artifact_hash",
    "ruleset_hash",
    "gate_result",
    "skip_reason",
    "verifier_key_id",
    "signature",
)

SPA_SIGNED_FIELDS: Final[tuple[str, ...]] = SPA_FIELDS[:-1]
SPA_IDENTITY_FIELDS: Final[tuple[str, ...]] = SPA_FIELDS[1:-1]


class SpaSignerPort(Protocol):
    """SPA 签名端口（Verifier 进程）。P9 无合规实现（OQ-P6-02/OQ-P9-03）。"""

    def key_id(self) -> str:
        ...

    def sign(self, payload: bytes, *, domain: str, alg: str) -> str:
        ...

    def verify(self, payload: bytes, signature: str, *, domain: str, alg: str) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class SpaIdentity:
    """D.5 中除 `spa_id` / `signature` 外的 10 个字段。"""

    task_id: str
    node_id: str
    recovery_plan_id: str
    dc_id: str
    predecessor_hashes: tuple[str, ...]
    artifact_hash: str
    ruleset_hash: str
    gate_result: str
    skip_reason: str
    verifier_key_id: str

    def as_map(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "task_id": self.task_id,
                "node_id": self.node_id,
                "recovery_plan_id": self.recovery_plan_id,
                "dc_id": self.dc_id,
                "predecessor_hashes": list(self.predecessor_hashes),
                "artifact_hash": self.artifact_hash,
                "ruleset_hash": self.ruleset_hash,
                "gate_result": self.gate_result,
                "skip_reason": self.skip_reason,
                "verifier_key_id": self.verifier_key_id,
            }
        )


def compute_spa_id(identity: SpaIdentity) -> str:
    """内容寻址 `spa_id` = `sha256(JCS(identity))`，64 位小写十六进制、无前缀（OQ-P9-01）。"""
    import hashlib

    return hashlib.sha256(_canonical_bytes(identity.as_map())).hexdigest()


@dataclass(frozen=True, slots=True)
class SpaRecord:
    """已签名的 SPA 记录：D.5 的 12 个字段。"""

    spa_id: str
    identity: SpaIdentity
    signature: SpaSignature
    signed_at: str

    def __post_init__(self) -> None:
        _require_sha256(self.spa_id, "spa_id")
        if compute_spa_id(self.identity) != self.spa_id:
            raise SpaRefused("SPA_ID_MISMATCH", "spa_id 与身份字段不一致")
        _require_utc_z(self.signed_at, "signed_at")

    def body(self) -> Mapping[str, object]:
        body = dict(self.identity.as_map())
        body["spa_id"] = self.spa_id
        return MappingProxyType({name: body[name] for name in SPA_SIGNED_FIELDS})

    def as_record(self) -> Mapping[str, object]:
        body = dict(self.body())
        body["signature"] = self.signature.signature
        return MappingProxyType({name: body[name] for name in SPA_FIELDS})


@dataclass(frozen=True, slots=True)
class SpaDecision:
    """判定结果。结构上不允许「SKIP 无记录」或「REEXECUTE 带记录」。"""

    node_id: str
    action: SpaAction = DEFAULT_ACTION
    outcomes: tuple[ConditionOutcome, ...] = ()
    causes: tuple[ReexecuteReason, ...] = ()
    record: SpaRecord | None = None

    def __post_init__(self) -> None:
        if self.action is SpaAction.SKIP and self.record is None:
            raise SpaRefused("SKIP_WITHOUT_RECORD", "跳过必须产出已签名 SPA 记录")
        if self.action is SpaAction.SKIP and self.causes:
            raise SpaRefused("SKIP_WITH_CAUSES", "跳过时不得同时带重跑原因")
        if self.action is SpaAction.REEXECUTE and self.record is not None:
            raise SpaRefused("RECORD_ON_REEXECUTE", "重跑不得产出 SPA 记录")
        if self.action is SpaAction.REEXECUTE and not self.causes:
            # 默认分支也必须能解释「为什么重跑」，否则无法与「没判」区分。
            raise SpaRefused("REEXECUTE_WITHOUT_CAUSE", "重跑必须带至少一个原因")

    @property
    def skipped(self) -> bool:
        return self.action is SpaAction.SKIP

    def as_detail(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "node_id": self.node_id,
                "action": self.action.value,
                "causes": [c.value for c in self.causes],
                "spa_id": self.record.spa_id if self.record else None,
                "outcomes": [o.as_detail() for o in self.outcomes],
            }
        )


# ---------------------------------------------------------------------------
# 5. 形态工具
# ---------------------------------------------------------------------------
def _require_sha256(value: str, field_path: str) -> None:
    """SHA-256 十六进制：64 位小写。"""
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise SpaRefused("HASH_INVALID", f"{field_path} 不是 64 位小写十六进制：{value!r}")


def _require_utc(moment: datetime, field_path: str) -> None:
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise SpaRefused("TIME_NOT_UTC", f"{field_path} 必须是带时区的 UTC")


def _require_utc_z(text: str, field_path: str) -> None:
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError) as exc:
        raise SpaRefused("TIME_INVALID", f"{field_path} 不是 RFC3339 UTC：{text!r}") from exc


def _utc_z(moment: datetime) -> str:
    _require_utc(moment, "moment")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_bytes(body: Mapping[str, object]) -> bytes:
    """规范化字节串（占位）。真实实现走 M11 `jcs.canonicalize`（RFC 8785）。"""
    import json

    return json.dumps(dict(body), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sorted_pairs(pairs: Sequence[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    """前驱哈希按节点名排序后比较（顺序无语义，不得让顺序差异变成「变化」）。"""
    return tuple(sorted(pairs))


def _artifact_hash(inspections: Sequence[ArtifactInspection]) -> str:
    """把多产物合成一个 `artifact_hash`：排序后的 `{path: hash}` 的 JCS 哈希（OQ-P9-06）。"""
    mapping = {item.relative_path: item.actual_sha256 or "" for item in inspections}
    import hashlib

    return hashlib.sha256(_canonical_bytes(mapping)).hexdigest()


# ---------------------------------------------------------------------------
# 6. 五个条件
# ---------------------------------------------------------------------------
def _dc_outcome(request: SpaRequest) -> ConditionOutcome:
    """条件 1：存在有效 DC，且输入结构/代码/环境/规则与当前一致。

    `dc_validity` 必须由 `dc_issuer.evaluate_dc_record` 产出；本函数不重新解释 DC 字段。
    """
    if request.dc_record is None or request.dc_validity is None:
        return ConditionOutcome(
            condition=SpaCondition.DC_VALID,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.NO_DC,
            detail="无 DC 记录：§8.3 条件 1 不成立",
        )
    if request.dc_validity.validity is DcStatus.SIGNATURE_INVALID:
        return ConditionOutcome(
            condition=SpaCondition.DC_VALID,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.DC_SIGNATURE_INVALID,
            detail="DC 签名无效：不得据此剪枝",
        )
    if not request.dc_validity.usable:
        return ConditionOutcome(
            condition=SpaCondition.DC_VALID,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.DC_NOT_VALID,
            detail=f"DC 状态 {request.dc_validity.validity.value}",
        )
    identity = request.dc_record.identity
    drifted: list[str] = []
    if identity.code_hash != request.current_code_hash:
        drifted.append("code_hash")
    if identity.input_schema_hash != request.current_input_schema_hash:
        drifted.append("input_schema_hash")
    if identity.env_fingerprint != request.current_env_fingerprint:
        drifted.append("env_fingerprint")
    if identity.ruleset_hash != request.current_ruleset_hash:
        drifted.append("ruleset_hash")
    if drifted:
        return ConditionOutcome(
            condition=SpaCondition.DC_VALID,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.DC_NOT_VALID,
            detail=f"与当前不一致：{drifted}",
        )
    evidence = request.evidence_for(SpaCondition.DC_VALID)
    if not evidence:
        return ConditionOutcome(
            condition=SpaCondition.DC_VALID,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.EVIDENCE_MISSING,
            detail="DC 有效性没有证据引用",
        )
    return ConditionOutcome(
        condition=SpaCondition.DC_VALID,
        outcome=SpaAction.SKIP,
        evidence=evidence,
        detail=f"dc_id={request.dc_id[:12]}… usable",
    )


def _predecessor_outcome(request: SpaRequest) -> ConditionOutcome:
    """条件 2：所有直接前驱输出哈希与恢复前历史一致（上游变化沿 DAG 传播失效）。"""
    now_pairs = _sorted_pairs(request.predecessor_hashes_now)
    then_pairs = _sorted_pairs(request.predecessor_hashes_at_recovery)
    if not then_pairs:
        return ConditionOutcome(
            condition=SpaCondition.PREDECESSOR_HASHES_UNCHANGED,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.PREDECESSOR_MISSING,
            detail="恢复前没有记录前驱哈希：无法证明未变化",
        )
    if now_pairs != then_pairs:
        changed = sorted(set(now_pairs) ^ set(then_pairs))
        return ConditionOutcome(
            condition=SpaCondition.PREDECESSOR_HASHES_UNCHANGED,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.PREDECESSOR_HASH_CHANGED,
            detail=f"变化的前驱：{[p for p, _ in changed]}",
        )
    evidence = request.evidence_for(SpaCondition.PREDECESSOR_HASHES_UNCHANGED)
    if not evidence:
        return ConditionOutcome(
            condition=SpaCondition.PREDECESSOR_HASHES_UNCHANGED,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.EVIDENCE_MISSING,
            detail="前驱哈希比较没有证据引用",
        )
    return ConditionOutcome(
        condition=SpaCondition.PREDECESSOR_HASHES_UNCHANGED,
        outcome=SpaAction.SKIP,
        evidence=evidence,
        detail=f"{len(now_pairs)} 个直接前驱哈希一致",
    )


def _disk_outcome(request: SpaRequest) -> ConditionOutcome:
    """条件 3：现场重算 SHA-256 与历史一致；realpath 不得越界或指向旧目录。"""
    expected = {a.relative_path: a.expected_sha256 for a in request.artifacts_expected}
    inspected = {a.relative_path: a for a in request.artifacts_inspected}
    if not expected:
        return ConditionOutcome(
            condition=SpaCondition.DISK_REHASH_MATCHES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.EVIDENCE_MISSING,
            detail="历史证据里没有产物期望：无法复算",
        )
    missing = sorted(set(expected) - set(inspected))
    if missing:
        return ConditionOutcome(
            condition=SpaCondition.DISK_REHASH_MATCHES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.ARTIFACT_MISSING_ON_DISK,
            detail=f"未现场复算：{missing}",
        )
    escaped = [p for p, item in inspected.items() if not item.within_workspace]
    if escaped:
        return ConditionOutcome(
            condition=SpaCondition.DISK_REHASH_MATCHES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.DISK_PATH_ESCAPE,
            detail=f"realpath 越界：{escaped}",
        )
    legacy = [p for p, item in inspected.items() if item.points_to_legacy_directory]
    if legacy:
        return ConditionOutcome(
            condition=SpaCondition.DISK_REHASH_MATCHES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.DISK_PATH_LEGACY,
            detail=f"指向旧目录：{legacy}",
        )
    divergent = [
        path
        for path, digest in expected.items()
        if inspected[path].actual_sha256 != digest
    ]
    if divergent:
        return ConditionOutcome(
            condition=SpaCondition.DISK_REHASH_MATCHES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.DISK_REHASH_MISMATCH,
            detail=f"哈希不一致：{divergent}",
        )
    evidence = request.evidence_for(SpaCondition.DISK_REHASH_MATCHES)
    if not evidence:
        return ConditionOutcome(
            condition=SpaCondition.DISK_REHASH_MATCHES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.EVIDENCE_MISSING,
            detail="磁盘复算没有证据引用",
        )
    return ConditionOutcome(
        condition=SpaCondition.DISK_REHASH_MATCHES,
        outcome=SpaAction.SKIP,
        evidence=evidence,
        detail=f"{len(expected)} 个产物现场复算一致",
    )


def _gate_outcome(request: SpaRequest) -> ConditionOutcome:
    """条件 4：旧证据在当前规则集下仍通过 Gate，未过期、未撤销、无新冲突。"""
    gate = request.gate
    if gate.expired:
        return ConditionOutcome(
            condition=SpaCondition.GATE_RECHECK_PASSES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.GATE_EXPIRED,
            detail="Gate 结论已过期",
        )
    if gate.revoked:
        return ConditionOutcome(
            condition=SpaCondition.GATE_RECHECK_PASSES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.GATE_REVOKED,
            detail="Gate 结论已撤销",
        )
    if gate.conflicts:
        return ConditionOutcome(
            condition=SpaCondition.GATE_RECHECK_PASSES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.GATE_CONFLICT,
            detail=f"新冲突：{list(gate.conflicts)}",
        )
    if not gate.passed:
        return ConditionOutcome(
            condition=SpaCondition.GATE_RECHECK_PASSES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.GATE_NOT_PASSING,
            detail="当前规则集下 Gate 未通过",
        )
    if gate.ruleset_hash != request.current_ruleset_hash:
        return ConditionOutcome(
            condition=SpaCondition.GATE_RECHECK_PASSES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.GATE_NOT_PASSING,
            detail="Gate 复检的 ruleset 与请求不一致",
        )
    evidence = tuple(gate.evidence) or request.evidence_for(SpaCondition.GATE_RECHECK_PASSES)
    if not evidence:
        return ConditionOutcome(
            condition=SpaCondition.GATE_RECHECK_PASSES,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.EVIDENCE_MISSING,
            detail="Gate 复检没有证据引用",
        )
    return ConditionOutcome(
        condition=SpaCondition.GATE_RECHECK_PASSES,
        outcome=SpaAction.SKIP,
        evidence=evidence,
        detail="当前规则集下仍通过，未过期/未撤销/无新冲突",
    )


def _side_effect_outcome(request: SpaRequest) -> ConditionOutcome:
    """条件 5：节点无副作用，且任务规则未要求本次必须实际执行。"""
    facts = request.side_effects
    if facts.has_side_effect:
        return ConditionOutcome(
            condition=SpaCondition.NO_SIDE_EFFECT,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.SIDE_EFFECT_NODE,
            detail="节点有外部副作用：不得用 SPA 跳过",
        )
    if facts.rules_require_execution:
        return ConditionOutcome(
            condition=SpaCondition.NO_SIDE_EFFECT,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.MANDATORY_EXECUTION,
            detail="任务规则要求本次必须实际执行",
        )
    evidence = tuple(facts.evidence) or request.evidence_for(SpaCondition.NO_SIDE_EFFECT)
    if not evidence:
        return ConditionOutcome(
            condition=SpaCondition.NO_SIDE_EFFECT,
            outcome=SpaAction.REEXECUTE,
            reason=ReexecuteReason.EVIDENCE_MISSING,
            detail="副作用判定没有证据引用",
        )
    return ConditionOutcome(
        condition=SpaCondition.NO_SIDE_EFFECT,
        outcome=SpaAction.SKIP,
        evidence=evidence,
        detail="无副作用且本次不要求执行",
    )


# ---------------------------------------------------------------------------
# 7. 判定主入口
# ---------------------------------------------------------------------------
def _reexecute(
    request: SpaRequest,
    outcomes: Sequence[ConditionOutcome],
    extra: Sequence[ReexecuteReason] = (),
) -> SpaDecision:
    """构造 REEXECUTE 决定：原因去重但保持首次出现顺序；`DEFAULT_CONSERVATIVE` 兜底。"""
    causes: list[ReexecuteReason] = [o.reason for o in outcomes if o.reason is not None]
    causes.extend(extra)
    unique = tuple(dict.fromkeys(causes)) or (ReexecuteReason.DEFAULT_CONSERVATIVE,)
    return SpaDecision(
        node_id=request.node_id,
        action=SpaAction.REEXECUTE,
        outcomes=tuple(outcomes),
        causes=unique,
    )


def judge_spa(
    request: SpaRequest,
    *,
    signer: SpaSignerPort | None,
    tier: str = "T2",
    dc_spa_enabled: bool = True,
    skip_reason: SkipReason = SkipReason.DC_AND_PREDECESSORS_UNCHANGED,
) -> SpaDecision:
    """判定一个节点能否用 SPA 跳过本次执行。

    输入：`SpaRequest`（全部事实）、签名端口、阶段开关、跳过原因。
    输出：`SpaDecision`；`SKIP` 时附已签名 `SpaRecord`，否则带全部重跑原因。
    副作用：仅在 SKIP 路径调用一次 `signer.sign`。
    错误：`SpaNotEnabled`（T0/T1）；其余失败一律转成 REEXECUTE，**不抛**。

    步骤：
      1. 能力门（T0/T1 拒绝调用）；
      2. 计划门（§8.4：恢复计划必须在执行前冻结）；
      3. 五条件按 `SPA_CONDITION_ORDER` 逐条求值（全量，不只到第一个失败）；
      4. 任一未通过 → REEXECUTE；
      5. 缺签名端口 → REEXECUTE(SIGNER_UNAVAILABLE)；
      6. 签名 + 回验；失败 → REEXECUTE(SIGNING_FAILED)，**不返回无签名 SKIP**；
      7. 构造 `SpaRecord` 并返回 SKIP。
    """
    # 1. 能力门
    if tier != "T2" or not dc_spa_enabled:
        raise SpaNotEnabled(tier, str(dc_spa_enabled).lower())

    # 2. 计划门
    if not request.recovery_plan_frozen:
        return _reexecute(
            request,
            (),
            (ReexecuteReason.PLAN_NOT_FROZEN,),
        )

    # 3. 五条件
    outcomes = (
        _dc_outcome(request),
        _predecessor_outcome(request),
        _disk_outcome(request),
        _gate_outcome(request),
        _side_effect_outcome(request),
    )

    # 4. 任一未通过
    if any(not o.passed for o in outcomes):
        return _reexecute(request, outcomes)

    # 5. 签名端口
    if signer is None:
        return _reexecute(request, outcomes, (ReexecuteReason.SIGNER_UNAVAILABLE,))

    identity = SpaIdentity(
        task_id=request.task_id,
        node_id=request.node_id,
        recovery_plan_id=request.recovery_plan_id,
        dc_id=request.dc_id,
        predecessor_hashes=tuple(h for _, h in _sorted_pairs(request.predecessor_hashes_now)),
        artifact_hash=_artifact_hash(request.artifacts_inspected),
        ruleset_hash=request.current_ruleset_hash,
        gate_result="PASS",
        skip_reason=skip_reason.value,
        verifier_key_id=_safe_key_id(signer),
    )
    spa_id = compute_spa_id(identity)
    body = dict(identity.as_map())
    body["spa_id"] = spa_id
    payload = _canonical_bytes({name: body[name] for name in SPA_SIGNED_FIELDS})

    # 6. 签名与回验（失败一律回退重跑）
    try:
        signature_text = signer.sign(payload, domain=SPA_SIGNING_DOMAIN, alg="Ed25519")
        verified = signer.verify(payload, signature_text, domain=SPA_SIGNING_DOMAIN, alg="Ed25519")
    except (SpaJudgeError, DcIssuerError, RuntimeError):  # 端口异常不得升级为 SKIP
        return _reexecute(request, outcomes, (ReexecuteReason.SIGNING_FAILED,))
    if not verified:
        return _reexecute(request, outcomes, (ReexecuteReason.SIGNING_FAILED,))

    import hashlib

    signature = SpaSignature(
        alg="Ed25519",
        key_id=_safe_key_id(signer),
        domain=SPA_SIGNING_DOMAIN,
        signature=signature_text,
        signed_body_hash=hashlib.sha256(payload).hexdigest(),
    )

    # 7. SKIP
    record = SpaRecord(
        spa_id=spa_id,
        identity=identity,
        signature=signature,
        signed_at=_utc_z(request.now),
    )
    return SpaDecision(
        node_id=request.node_id,
        action=SpaAction.SKIP,
        outcomes=outcomes,
        causes=(),
        record=record,
    )


def _safe_key_id(signer: SpaSignerPort) -> str:
    """取 key_id；端口异常时返回空串（后续由 `SpaSignature` 拒绝空 key_id）。"""
    try:
        return str(signer.key_id())
    except (AttributeError, RuntimeError):
        return ""


# ---------------------------------------------------------------------------
# 8. 静态守卫（实现阶段用；P9 不执行）
# ---------------------------------------------------------------------------
def _dummy_dc_record(digest) -> tuple[DcRecord, DcValidityReport]:
    """构造一张「签名有效、未过期、绑定一致」的 DC，供守卫函数走通条件 1。"""
    from .dc_issuer import DC_ALG, DC_SIGNING_DOMAIN, DcAudit, DcIdentity, DcSignature, compute_dc_id

    identity = DcIdentity(
        node_type="transform",
        code_hash=digest("code"),
        dependency_lock_hash=digest("lock"),
        input_schema_hash=digest("schema"),
        env_fingerprint=digest("env"),
        ruleset_hash=digest("rules"),
        k_runs=3,
        run_fingerprints=(digest("r1"), digest("r2"), digest("r3")),
        output_hashes=(digest("artifact"),),
        eligible=True,
        expires_at="2026-12-01T00:00:00Z",
    )
    dc_id = compute_dc_id(identity)
    record = DcRecord(
        dc_id=dc_id,
        identity=identity,
        signature=DcSignature(
            alg=DC_ALG,
            key_id="verifier-key-01",
            domain=DC_SIGNING_DOMAIN,
            signature="c2ln",
            signed_body_hash=digest("body"),
        ),
        audit=DcAudit(
            issued_at="2026-11-11T00:00:00Z",
            issued_by="verifier",
            policy_version="dc-policy/1.0-proposed",
            source_verdict=dc_id,
        ),
    )
    report = DcValidityReport(
        dc_id=dc_id,
        validity=DcStatus.VALID,
        checks=(("SIGNATURE", True, "自检替身"),),
        checked_at="2026-11-11T12:00:00Z",
        signature_ok=True,
        expires_at=identity.expires_at,
    )
    return record, report


def _dummy_request(**overrides: object) -> SpaRequest:
    """构造一个「五条件全绿」的请求，供守卫改字段做负例。"""
    import hashlib

    digest = lambda tag: hashlib.sha256(tag.encode()).hexdigest()
    expected = ArtifactExpectation(relative_path="out/pred.csv", expected_sha256=digest("artifact"))
    inspected = ArtifactInspection(
        relative_path="out/pred.csv",
        actual_sha256=digest("artifact"),
        resolved_path="D:/workspace/task/out/pred.csv",
        within_workspace=True,
    )
    evidence = tuple(
        EvidenceRef(evidence_id=f"ev_{c.value.lower()}", producer="verifier", kind=c.value.lower())
        for c in SPA_CONDITION_ORDER
    )
    record, validity = _dummy_dc_record(digest)
    base: dict[str, object] = dict(
        task_id="task_1",
        node_id="node_1",
        recovery_plan_id="plan_1",
        recovery_plan_frozen=True,
        dc_id=record.dc_id,
        dc_record=record,
        dc_validity=validity,
        predecessor_hashes_now=(("node_0", digest("p0")),),
        predecessor_hashes_at_recovery=(("node_0", digest("p0")),),
        artifacts_expected=(expected,),
        artifacts_inspected=(inspected,),
        gate=GateRecheck(
            ruleset_hash=digest("rules"),
            passed=True,
            expired=False,
            revoked=False,
            evidence=(EvidenceRef("ev_gate", "m08_gate", "gate_recheck_passes"),),
        ),
        side_effects=SideEffectFacts(
            has_side_effect=False,
            rules_require_execution=False,
            evidence=(EvidenceRef("ev_side", "m14_recovery", "no_side_effect"),),
        ),
        now=datetime(2026, 11, 11, 12, 0, 0, tzinfo=timezone.utc),
        current_code_hash=digest("code"),
        current_input_schema_hash=digest("schema"),
        current_env_fingerprint=digest("env"),
        current_ruleset_hash=digest("rules"),
        evidence=evidence,
    )
    base.update(overrides)
    return SpaRequest(**base)  # type: ignore[arg-type]


def assert_default_reexecute() -> tuple[str, ...]:
    """默认动作必须是 REEXECUTE；无记录 SKIP 必须被结构拒绝。返回空元组表示通过。"""
    problems: list[str] = []
    if next(iter(SpaAction)) is not SpaAction.REEXECUTE:
        problems.append("SpaAction 首成员不是 REEXECUTE")
    if DEFAULT_ACTION is not SpaAction.REEXECUTE:
        problems.append("DEFAULT_ACTION 不是 REEXECUTE")
    try:
        SpaDecision(node_id="n", action=SpaAction.SKIP, causes=())
    except SpaRefused:
        pass
    else:
        problems.append("无记录的 SKIP 未被拒绝")
    try:
        SpaDecision(node_id="n", action=SpaAction.REEXECUTE, causes=(ReexecuteReason.NO_DC,), record=object())
    except SpaRefused:
        pass
    else:
        problems.append("REEXECUTE 带记录未被拒绝")
    decision = judge_spa(_dummy_request(), signer=None)
    if decision.action is not SpaAction.REEXECUTE:
        problems.append("无签名器时未返回 REEXECUTE")
    if ReexecuteReason.SIGNER_UNAVAILABLE not in decision.causes:
        problems.append("无签名器时未记录 SIGNER_UNAVAILABLE")
    return tuple(problems)


def assert_evidence_is_not_boolean() -> tuple[str, ...]:
    """PASS 必须有证据；Agent/LLM 不得作为证据生产者。返回空元组表示通过。"""
    problems: list[str] = []
    try:
        ConditionOutcome(condition=SpaCondition.DC_VALID, outcome=SpaAction.SKIP, evidence=())
    except SpaRefused:
        pass
    else:
        problems.append("无证据的 PASS 未被拒绝")
    try:
        EvidenceRef(evidence_id="ev_x", producer="agent", kind="dc_valid")
    except SpaRefused:
        pass
    else:
        problems.append("agent 生产的证据未被拒绝")
    for producer in sorted(FORBIDDEN_PRODUCERS):
        if producer in ALLOWED_PRODUCERS:
            problems.append(f"{producer} 同时在允许与禁止名单")
    return tuple(problems)


def assert_no_unsigned_skip() -> tuple[str, ...]:
    """无签名器不得 SKIP：五条件全绿也只会得到 REEXECUTE(SIGNER_UNAVAILABLE)。"""
    problems: list[str] = []
    decision = judge_spa(_dummy_request(), signer=None)
    if decision.skipped:
        problems.append("无签名器仍 SKIP")
    if decision.record is not None:
        problems.append("重跑分支带出了 SPA 记录")
    if ReexecuteReason.SIGNER_UNAVAILABLE not in decision.causes:
        problems.append("五条件全绿但无签名器时未记录 SIGNER_UNAVAILABLE")
    return tuple(problems)


class _FakeSigner:
    """自检替身：只证明 SKIP 路径可达，不证明签名安全。"""

    def key_id(self) -> str:
        return "verifier-key-01"

    def sign(self, payload: bytes, *, domain: str, alg: str) -> str:
        return "ZmFrZQ=="

    def verify(self, payload: bytes, signature: str, *, domain: str, alg: str) -> bool:
        return True


class _BrokenSigner(_FakeSigner):
    """签名成功但回验失败：必须回退 REEXECUTE，而不是抛异常或给出 SKIP。"""

    def verify(self, payload: bytes, signature: str, *, domain: str, alg: str) -> bool:
        return False


def assert_skip_requires_all_five() -> tuple[str, ...]:
    """五条件全绿 + 可用签名器 → SKIP；任一条被破坏 → REEXECUTE。"""
    problems: list[str] = []
    decision = judge_spa(_dummy_request(), signer=_FakeSigner())
    if decision.action is not SpaAction.SKIP:
        problems.append(f"五条件全绿却未 SKIP：{decision.causes}")
    if decision.record is None:
        problems.append("SKIP 未产出 SpaRecord")
    elif compute_spa_id(decision.record.identity) != decision.record.spa_id:
        problems.append("spa_id 与身份字段不一致")

    broken = judge_spa(_dummy_request(), signer=_BrokenSigner())
    if broken.action is not SpaAction.REEXECUTE:
        problems.append("回验失败却返回 SKIP")
    if ReexecuteReason.SIGNING_FAILED not in broken.causes:
        problems.append("回验失败未记录 SIGNING_FAILED")

    no_dc = judge_spa(
        _dummy_request(dc_record=None, dc_validity=None),
        signer=_FakeSigner(),
    )
    if no_dc.action is not SpaAction.REEXECUTE:
        problems.append("无 DC 却 SKIP")
    if ReexecuteReason.NO_DC not in no_dc.causes:
        problems.append("无 DC 未记录 NO_DC")
    return tuple(problems)


def assert_no_side_effect_skip() -> tuple[str, ...]:
    """副作用或「必须执行」的节点一律重跑。返回空元组表示通过。"""
    problems: list[str] = []
    side = _dummy_request(
        side_effects=SideEffectFacts(
            has_side_effect=True,
            rules_require_execution=False,
            evidence=(EvidenceRef("ev_side", "m14_recovery", "no_side_effect"),),
        )
    )
    decision = judge_spa(side, signer=None)
    if decision.action is not SpaAction.REEXECUTE:
        problems.append("副作用节点未重跑")
    if ReexecuteReason.SIDE_EFFECT_NODE not in decision.causes:
        problems.append("副作用节点未记录 SIDE_EFFECT_NODE")
    mandatory = _dummy_request(
        side_effects=SideEffectFacts(
            has_side_effect=False,
            rules_require_execution=True,
            evidence=(EvidenceRef("ev_side", "m14_recovery", "no_side_effect"),),
        )
    )
    decision = judge_spa(mandatory, signer=None)
    if ReexecuteReason.MANDATORY_EXECUTION not in decision.causes:
        problems.append("必须执行的节点未记录 MANDATORY_EXECUTION")
    return tuple(problems)


def assert_fields_match_d5() -> tuple[str, ...]:
    """SPA 字段必须与 D.5 的 12 个一致。返回空元组表示通过。"""
    problems: list[str] = []
    if SPA_FIELDS != (
        "spa_id", "task_id", "node_id", "recovery_plan_id", "dc_id", "predecessor_hashes",
        "artifact_hash", "ruleset_hash", "gate_result", "skip_reason", "verifier_key_id", "signature",
    ):
        problems.append("SPA_FIELDS 顺序与 D.5 不一致")
    if len(SPA_SIGNED_FIELDS) != 11:
        problems.append(f"签名正文 {len(SPA_SIGNED_FIELDS)} 个字段，期望 11（12 减去 signature）")
    if SPA_CONDITION_ORDER[0] is not SpaCondition.DC_VALID:
        problems.append("五条件首位不是 DC_VALID")
    return tuple(problems)