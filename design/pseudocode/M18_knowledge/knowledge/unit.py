"""MODULE：M18 · knowledge/unit.py — KnowledgeUnit 全字段、三态与五类差异字段（P8 伪代码）。
阶段+追踪：P8「六角色与知识库」｜FR-013（知识单元版本治理）｜策划书 §11.1 TABLE 42、§11.2、§11.4
FR+依赖：FR-013；依赖 M01 的 UTF-8/SHA-256/UTC 口径（本文件只写意图，不 import 实现）、M18 无上游
不变量+错误码：15 个字段与 §11.2 逐字一致；只增不改（修订 = 新版本 + 旧版本 DEPRECATED）；
              冲突标 CONFLICTED 并升级人工，模型不得自选版本；Agent 不得写知识。
              TOOL_NOT_ALLOWLISTED(403) / STATE_TRANSITION_DENIED(409) / SCHEMA_INVALID(422)
写入者：无。知识写入由人工/导入器经 KnowledgeStore（未在本模块实现）；本文件只构造与校验记录。
状态：伪代码；不建库、不写 FTS、不执行检索。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import StrEnum
from typing import Final, Mapping

__all__ = [
    "AGENT_ROLE_NAMES",
    "CONTENT_HASH_NOTE",
    "EXPECTED_FIELDS",
    "KType",
    "KnowledgeGovernanceError",
    "KnowledgeStatus",
    "KnowledgeUnit",
    "KnowledgeValidationError",
    "PayloadKind",
    "ConflictRecord",
    "HumanResolution",
    "ResolutionDecision",
    "ResolutionSource",
    "DatasetPayload",
    "FaultCasePayload",
    "MetricDef",
    "PaperDocPayload",
    "SpecPayload",
    "ToolPayload",
    "assert_append_only",
    "assert_field_parity",
    "assert_ktype_parity",
    "assert_no_model_selection",
    "assert_payload_keys_match_11_1",
    "assert_status_transitions",
    "can_transition",
    "compute_content_hash",
    "detect_conflict",
]

# M17 的六角色名（小写）。知识作者不得是 Agent；用字面值避免 M18 反向 import M17。
AGENT_ROLE_NAMES: Final[frozenset[str]] = frozenset(
    {"planner", "data", "experiment", "analysis", "recovery", "verification"}
)

CONTENT_HASH_NOTE: Final[str] = (
    "content_hash 覆盖 kid/ktype/scope/structured/text/source_url/license/effective_at/expires_at，"
    "不覆盖 status/created_by/reviewed_by/supersedes；"
    "规范化用本地确定性 JSON（[P8 约定]），不是签名载荷，不得与 JCS 签名语义混用。"
)

EXPECTED_FIELDS: Final[tuple[str, ...]] = (
    "kid",
    "ktype",
    "scope",
    "version",
    "source_url",
    "license",
    "effective_at",
    "expires_at",
    "structured",
    "text",
    "content_hash",
    "supersedes",
    "status",
    "created_by",
    "reviewed_by",
)

UTC_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$"
)
HASH64_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
IDENT_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@/-]*$")
SCOPE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*(:[A-Za-z0-9][A-Za-z0-9._@/-]*)+$")


class KnowledgeValidationError(ValueError):
    """知识记录不合法；`field_path`/`reason` 是断言对象。"""

    def __init__(self, reason: str, field_path: str, detail: str) -> None:
        self.error_code = "SCHEMA_INVALID"
        self.reason = reason
        self.field_path = field_path
        self.detail = detail
        super().__init__(f"[SCHEMA_INVALID] {field_path}: {reason}（{detail}）")


class KnowledgeGovernanceError(RuntimeError):
    """治理拒绝（Agent 写知识、模型自选版本、非法状态迁移）。"""

    def __init__(self, code: str, reason: str, detail: str) -> None:
        self.error_code = code
        self.reason = reason
        self.detail = detail
        super().__init__(f"[{code}] {reason}（{detail}）")


class KType(StrEnum):
    """策划书 §11.1 的五类知识。字面值必须与 M17 contracts.KNOWLEDGE_KINDS 一致。"""

    SPEC = "SPEC"
    TOOL = "TOOL"
    DATASET = "DATASET"
    FAULT_CASE = "FAULT_CASE"
    PAPER_DOC = "PAPER_DOC"


class KnowledgeStatus(StrEnum):
    """§11.2 的三态。**没有** DRAFT；未审核不得入库。"""

    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    CONFLICTED = "CONFLICTED"


class PayloadKind(StrEnum):
    """`structured` 的运行时类型标签（与 ktype 一一对应）。"""

    SPEC = "SpecPayload"
    TOOL = "ToolPayload"
    DATASET = "DatasetPayload"
    FAULT_CASE = "FaultCasePayload"
    PAPER_DOC = "PaperDocPayload"


# ---------------------------------------------------------------------------
# 0. 五类差异字段（§11.1「关键字段」列）
# ---------------------------------------------------------------------------
def _utc(value: str, field_path: str) -> datetime:
    """解析 UTC RFC 3339；非 UTC/无时区一律拒绝。"""
    if not UTC_PATTERN.fullmatch(value):
        raise KnowledgeValidationError("TIMESTAMP_NOT_UTC", field_path, value)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KnowledgeValidationError("TIMESTAMP_INVALID", field_path, value) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise KnowledgeValidationError("TIMESTAMP_NOT_UTC", field_path, value)
    return parsed


@dataclass(frozen=True, slots=True)
class MetricDef:
    """SPEC 的指标口径。`source_split` 必须显式，防止“训练集冒充测试集”。"""

    name: str
    direction: str
    source_split: str
    formula_ref: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.name):
            raise KnowledgeValidationError("METRIC_NAME_INVALID", "structured.metric_defs[].name", self.name)
        if self.direction not in ("HIGHER_IS_BETTER", "LOWER_IS_BETTER"):
            raise KnowledgeValidationError("METRIC_DIRECTION_INVALID", "structured.metric_defs[].direction", self.direction)
        if self.source_split not in ("train", "validation", "test"):
            raise KnowledgeValidationError("METRIC_SPLIT_INVALID", "structured.metric_defs[].source_split", self.source_split)
        if not self.formula_ref.strip():
            raise KnowledgeValidationError("METRIC_FORMULA_MISSING", "structured.metric_defs[].formula_ref", "")


@dataclass(frozen=True, slots=True)
class SpecPayload:
    """SPEC：实验规范/划分/种子/指标口径。"""

    seed_required: bool
    test_ratio: float
    metric_defs: tuple[MetricDef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.seed_required, bool):
            raise KnowledgeValidationError("SPEC_SEED_NOT_BOOL", "structured.seed_required", type(self.seed_required).__name__)
        if isinstance(self.test_ratio, bool) or not isinstance(self.test_ratio, (int, float)):
            raise KnowledgeValidationError("SPEC_RATIO_NOT_NUMBER", "structured.test_ratio", type(self.test_ratio).__name__)
        if not 0.0 < float(self.test_ratio) < 1.0:
            raise KnowledgeValidationError("SPEC_RATIO_OUT_OF_RANGE", "structured.test_ratio", str(self.test_ratio))
        if not self.metric_defs:
            raise KnowledgeValidationError("SPEC_METRICS_EMPTY", "structured.metric_defs", "至少一条指标口径")
        if len({m.name for m in self.metric_defs}) != len(self.metric_defs):
            raise KnowledgeValidationError("SPEC_METRICS_DUPLICATE", "structured.metric_defs", "指标名重复")


@dataclass(frozen=True, slots=True)
class ParamRule:
    """TOOL 参数约束的知识表达（与 M05/M17 的 ParamSchema 同义，不替代它）。"""

    kind: str
    required: bool
    enum_values: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in ("STRING", "INTEGER", "NUMBER", "BOOLEAN", "ARRAY_STRING"):
            raise KnowledgeValidationError("TOOL_PARAM_KIND_INVALID", "structured.params_schema[].kind", self.kind)


@dataclass(frozen=True, slots=True)
class KnownError:
    """TOOL 的已知错误；`retryable` 只描述工具层，不描述节点是否该重试。"""

    code: str
    message: str
    retryable: bool

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", self.code):
            raise KnowledgeValidationError("TOOL_ERROR_CODE_INVALID", "structured.known_errors[].code", self.code)
        if not self.message.strip():
            raise KnowledgeValidationError("TOOL_ERROR_MESSAGE_EMPTY", "structured.known_errors[].message", "")


@dataclass(frozen=True, slots=True)
class ToolPayload:
    """TOOL：工具契约/参数/版本差异/已知错误。"""

    tool_name: str
    params_schema: Mapping[str, ParamRule]
    timeout_sec: int
    known_errors: tuple[KnownError, ...]

    def __post_init__(self) -> None:
        if not IDENT_PATTERN.fullmatch(self.tool_name):
            raise KnowledgeValidationError("TOOL_NAME_INVALID", "structured.tool_name", self.tool_name)
        if not self.params_schema:
            raise KnowledgeValidationError("TOOL_PARAMS_EMPTY", "structured.params_schema", "至少一个参数")
        for name, rule in self.params_schema.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                raise KnowledgeValidationError("TOOL_PARAM_NAME_INVALID", f"structured.params_schema.{name}", name)
            if not isinstance(rule, ParamRule):
                raise KnowledgeValidationError("TOOL_PARAM_RULE_INVALID", f"structured.params_schema.{name}", type(rule).__name__)
        if not 0 < self.timeout_sec <= 300:
            raise KnowledgeValidationError("TOOL_TIMEOUT_OUT_OF_RANGE", "structured.timeout_sec", str(self.timeout_sec))
        if len({e.code for e in self.known_errors}) != len(self.known_errors):
            raise KnowledgeValidationError("TOOL_ERRORS_DUPLICATE", "structured.known_errors", "错误码重复")


@dataclass(frozen=True, slots=True)
class DatasetPayload:
    """DATASET：字段/标签/缺失模式/许可。`license` 必须与记录级 license 一致。"""

    dataset_hash: str
    target: str
    dtypes: Mapping[str, str]
    license: str

    def __post_init__(self) -> None:
        if not HASH64_PATTERN.fullmatch(self.dataset_hash):
            raise KnowledgeValidationError("DATASET_HASH_INVALID", "structured.dataset_hash", self.dataset_hash)
        if not self.target.strip():
            raise KnowledgeValidationError("DATASET_TARGET_EMPTY", "structured.target", "")
        if not self.dtypes:
            raise KnowledgeValidationError("DATASET_DTYPES_EMPTY", "structured.dtypes", "")
        for column, dtype in self.dtypes.items():
            if not column or not dtype:
                raise KnowledgeValidationError("DATASET_DTYPE_INVALID", f"structured.dtypes.{column}", "")
        if not self.license.strip():
            raise KnowledgeValidationError("DATASET_LICENSE_EMPTY", "structured.license", "")


@dataclass(frozen=True, slots=True)
class FaultCasePayload:
    """FAULT_CASE：错误签名/根因/修复/前置条件。必须人工确认后才能入库。"""

    signature: str
    root_cause: str
    fix: str
    preconditions: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (("signature", self.signature), ("root_cause", self.root_cause), ("fix", self.fix)):
            if not value.strip():
                raise KnowledgeValidationError("FAULT_CASE_FIELD_EMPTY", f"structured.{name}", "")
        if not self.preconditions:
            raise KnowledgeValidationError(
                "FAULT_CASE_PRECONDITIONS_EMPTY", "structured.preconditions",
                "没有前置条件的修复不可复用",
            )


@dataclass(frozen=True, slots=True)
class PaperDocPayload:
    """PAPER/DOC：论文/官方文档。`url`/`license` 必须与记录级字段一致。"""

    title: str
    document_version: str
    section: str
    url: str
    license: str

    def __post_init__(self) -> None:
        for name, value in (
            ("title", self.title),
            ("document_version", self.document_version),
            ("section", self.section),
            ("url", self.url),
            ("license", self.license),
        ):
            if not value.strip():
                raise KnowledgeValidationError("PAPER_FIELD_EMPTY", f"structured.{name}", "")


PAYLOAD_BY_KTYPE: Final[Mapping[KType, type]] = {
    KType.SPEC: SpecPayload,
    KType.TOOL: ToolPayload,
    KType.DATASET: DatasetPayload,
    KType.FAULT_CASE: FaultCasePayload,
    KType.PAPER_DOC: PaperDocPayload,
}

PAYLOAD_KEYS_BY_KTYPE: Final[Mapping[KType, tuple[str, ...]]] = {
    KType.SPEC: ("seed_required", "test_ratio", "metric_defs"),
    KType.TOOL: ("tool_name", "params_schema", "timeout_sec", "known_errors"),
    KType.DATASET: ("dataset_hash", "target", "dtypes", "license"),
    KType.FAULT_CASE: ("signature", "root_cause", "fix", "preconditions"),
    KType.PAPER_DOC: ("title", "document_version", "section", "url", "license"),
}


def _payload_mapping(payload: object) -> dict[str, object]:
    """把 payload 变成确定性字典（嵌套 dataclass 递归展开）。"""
    result: dict[str, object] = {}
    for field in fields(payload):  # type: ignore[arg-type]
        value = getattr(payload, field.name)
        if hasattr(value, "__dataclass_fields__"):
            result[field.name] = _payload_mapping(value)
        elif isinstance(value, Mapping):
            result[field.name] = {
                key: (
                    _payload_mapping(item)
                    if hasattr(item, "__dataclass_fields__")
                    else (item.value if isinstance(item, StrEnum) else item)
                )
                for key, item in value.items()
            }
        elif isinstance(value, tuple):
            result[field.name] = [
                _payload_mapping(v) if hasattr(v, "__dataclass_fields__") else (v.value if isinstance(v, StrEnum) else v)
                for v in value
            ]
        else:
            result[field.name] = value
    return result


def compute_content_hash(
    *,
    kid: str,
    ktype: KType,
    scope: str,
    structured: object,
    text: str,
    source_url: str,
    license: str,
    effective_at: str,
    expires_at: str,
) -> str:
    """内容寻址哈希：只覆盖“内容 + 有效期 + 来源/许可”，不覆盖治理字段。"""
    projection = {
        "kid": kid,
        "ktype": ktype.value,
        "scope": scope,
        "structured": _payload_mapping(structured),
        "text": text,
        "source_url": source_url,
        "license": license,
        "effective_at": effective_at,
        "expires_at": expires_at,
    }
    canonical = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()  # LIB: hashlib.sha256


# ---------------------------------------------------------------------------
# 1. KnowledgeUnit
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class KnowledgeUnit:
    """§11.2 的 15 个字段。字段名、顺序、语义均不得改写。

    字段映射说明（差异字段与记录级字段重复时以记录级为准）：
      - DATASET.license == 记录级 license；
      - PAPER_DOC.url == source_url，PAPER_DOC.license == license；
      - PAPER_DOC.document_version 是“文档版本”，与记录级 revision `version` 不是同一概念。
    """

    kid: str
    ktype: KType
    scope: str
    version: int
    source_url: str
    license: str
    effective_at: str
    expires_at: str
    structured: object
    text: str
    content_hash: str
    supersedes: str | None
    status: KnowledgeStatus
    created_by: str
    reviewed_by: str

    # -- 构造 -------------------------------------------------------------
    def __post_init__(self) -> None:
        # 0. 枚举类型（字符串会静默通过会比较，必须先挡）
        if not isinstance(self.ktype, KType):
            raise KnowledgeValidationError("KTYPE_INVALID", "ktype", type(self.ktype).__name__)
        if not isinstance(self.status, KnowledgeStatus):
            raise KnowledgeValidationError("STATUS_INVALID", "status", type(self.status).__name__)

        # 1. 标识与版本
        if not self.kid.strip() or any(ch.isspace() for ch in self.kid):
            raise KnowledgeValidationError("KID_INVALID", "kid", self.kid)
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise KnowledgeValidationError("VERSION_INVALID", "version", str(self.version))
        if not SCOPE_PATTERN.fullmatch(self.scope):
            raise KnowledgeValidationError("SCOPE_INVALID", "scope", self.scope)

        # 2. 来源与许可（可追溯）
        if not re.fullmatch(r"(https|http|local|file|doi):[^\s]+", self.source_url):
            raise KnowledgeValidationError("SOURCE_URL_INVALID", "source_url", self.source_url)
        if not self.license.strip() or self.license.strip().upper() in ("UNKNOWN", "TBD", "NONE"):
            raise KnowledgeValidationError(
                "LICENSE_INVALID", "license", "来源/许可必须可追溯；UNKNOWN 不得入库"
            )

        # 3. 有效期
        start = _utc(self.effective_at, "effective_at")
        end = _utc(self.expires_at, "expires_at")
        if end <= start:
            raise KnowledgeValidationError("EXPIRY_NOT_AFTER_EFFECTIVE", "expires_at", "过期时间必须晚于生效时间")

        # 4. 正文与结构化负载
        if not self.text.strip():
            raise KnowledgeValidationError("TEXT_EMPTY", "text", "text 是检索与阅读入口，不得为空")
        if len(self.text) > 20_000:
            raise KnowledgeValidationError("TEXT_TOO_LONG", "text", f"len={len(self.text)}")
        expected_cls = PAYLOAD_BY_KTYPE[self.ktype]
        if not isinstance(self.structured, expected_cls):
            raise KnowledgeValidationError(
                "PAYLOAD_TYPE_MISMATCH", "structured",
                f"{self.ktype.value} 需要 {expected_cls.__name__}，实际 {type(self.structured).__name__}",
            )
        self._assert_payload_consistency()

        # 5. 内容哈希
        expected_hash = compute_content_hash(
            kid=self.kid, ktype=self.ktype, scope=self.scope, structured=self.structured,
            text=self.text, source_url=self.source_url, license=self.license,
            effective_at=self.effective_at, expires_at=self.expires_at,
        )
        if self.content_hash != expected_hash:
            raise KnowledgeValidationError(
                "CONTENT_HASH_MISMATCH", "content_hash",
                "内容被改动但未重算哈希；不得原地覆盖旧版本",
            )

        # 6. 替代关系
        if self.supersedes is not None:
            if not HASH64_PATTERN.fullmatch(self.supersedes):
                raise KnowledgeValidationError("SUPERSEDES_INVALID", "supersedes", self.supersedes)
            if self.supersedes == self.content_hash:
                raise KnowledgeValidationError("SUPERSEDES_SELF", "supersedes", "不得引用自身")

        # 7. 治理字段
        if self.created_by.strip().lower() in AGENT_ROLE_NAMES or self.created_by.lower().startswith("agent:"):
            raise KnowledgeGovernanceError(
                "TOOL_NOT_ALLOWLISTED", "KNOWLEDGE_WRITE_BY_AGENT_FORBIDDEN",
                f"created_by={self.created_by}",
            )
        if not self.created_by.strip() or not self.reviewed_by.strip():
            raise KnowledgeGovernanceError(
                "STATE_TRANSITION_DENIED", "KNOWLEDGE_NOT_REVIEWED",
                "created_by/reviewed_by 都必须有人；未复核知识不得入库",
            )

        # 8. 状态
        if self.status is KnowledgeStatus.DEPRECATED and self.supersedes is None and self.version > 1:
            raise KnowledgeValidationError(
                "DEPRECATED_WITHOUT_SUPERSEDES", "status",
                "被替代的旧版本必须指向新版本（或由 store 记录替代者）",
            )

    def _assert_payload_consistency(self) -> None:
        """跨字段一致性：DATASET/PAPER_DOC 的许可与 URL 不得与记录级冲突。"""
        payload = self.structured
        if isinstance(payload, DatasetPayload) and payload.license != self.license:
            raise KnowledgeValidationError("DATASET_LICENSE_CONFLICT", "structured.license", payload.license)
        if isinstance(payload, PaperDocPayload):
            if payload.url != self.source_url:
                raise KnowledgeValidationError("PAPER_URL_CONFLICT", "structured.url", payload.url)
            if payload.license != self.license:
                raise KnowledgeValidationError("PAPER_LICENSE_CONFLICT", "structured.license", payload.license)

    # -- 修订 -------------------------------------------------------------
    @classmethod
    def create(
        cls,
        *,
        kid: str,
        ktype: KType,
        scope: str,
        version: int,
        source_url: str,
        license: str,
        effective_at: str,
        expires_at: str,
        structured: object,
        text: str,
        supersedes: str | None,
        created_by: str,
        reviewed_by: str,
        status: KnowledgeStatus = KnowledgeStatus.ACTIVE,
    ) -> "KnowledgeUnit":
        """构造一条记录并计算 content_hash（唯一合法构造入口）。"""
        content_hash = compute_content_hash(
            kid=kid, ktype=ktype, scope=scope, structured=structured, text=text,
            source_url=source_url, license=license, effective_at=effective_at, expires_at=expires_at,
        )
        return cls(
            kid=kid, ktype=ktype, scope=scope, version=version, source_url=source_url, license=license,
            effective_at=effective_at, expires_at=expires_at, structured=structured, text=text,
            content_hash=content_hash, supersedes=supersedes, status=status,
            created_by=created_by, reviewed_by=reviewed_by,
        )

    def new_version(
        self,
        *,
        structured: object,
        text: str,
        source_url: str,
        license: str,
        effective_at: str,
        expires_at: str,
        created_by: str,
        reviewed_by: str,
    ) -> "KnowledgeUnit":
        """产生新版本（只增不改）。旧版本由 store 迁移为 DEPRECATED。"""
        candidate = KnowledgeUnit.create(
            kid=self.kid, ktype=self.ktype, scope=self.scope, version=self.version + 1,
            source_url=source_url, license=license, effective_at=effective_at, expires_at=expires_at,
            structured=structured, text=text, supersedes=self.content_hash,
            created_by=created_by, reviewed_by=reviewed_by, status=KnowledgeStatus.ACTIVE,
        )
        if candidate.content_hash == self.content_hash:
            raise KnowledgeValidationError(
                "DUPLICATE_REVISION", "structured", "新版本内容与旧版本完全相同；这不是修订"
            )
        return candidate

    def deprecate(self, *, superseded_by_hash: str) -> "KnowledgeUnit":
        """把当前版本标记为 DEPRECATED。只改状态，不改内容。"""
        if not can_transition(self.status, KnowledgeStatus.DEPRECATED):
            raise KnowledgeGovernanceError(
                "STATE_TRANSITION_DENIED", "KNOWLEDGE_STATUS_TRANSITION_DENIED",
                f"{self.status.value}→DEPRECATED",
            )
        if not HASH64_PATTERN.fullmatch(superseded_by_hash) or superseded_by_hash == self.content_hash:
            raise KnowledgeValidationError("SUPERSEDED_BY_INVALID", "superseded_by_hash", superseded_by_hash)
        from dataclasses import replace

        return replace(self, status=KnowledgeStatus.DEPRECATED)

    def mark_conflicted(self) -> "KnowledgeUnit":
        """标记冲突；**不**自动选择谁对。升级人工由 retrieval/gateway 负责。"""
        if not can_transition(self.status, KnowledgeStatus.CONFLICTED):
            raise KnowledgeGovernanceError(
                "STATE_TRANSITION_DENIED", "KNOWLEDGE_STATUS_TRANSITION_DENIED",
                f"{self.status.value}→CONFLICTED",
            )
        from dataclasses import replace

        return replace(self, status=KnowledgeStatus.CONFLICTED)


# ---------------------------------------------------------------------------
# 2. 状态机
# ---------------------------------------------------------------------------
_ALLOWED_TRANSITIONS: Final[Mapping[KnowledgeStatus, frozenset[KnowledgeStatus]]] = {
    KnowledgeStatus.ACTIVE: frozenset({KnowledgeStatus.DEPRECATED, KnowledgeStatus.CONFLICTED}),
    KnowledgeStatus.CONFLICTED: frozenset({KnowledgeStatus.DEPRECATED, KnowledgeStatus.ACTIVE}),
    KnowledgeStatus.DEPRECATED: frozenset(),  # 终态：复活必须走新版本
}


def can_transition(source: KnowledgeStatus, target: KnowledgeStatus) -> bool:
    """查询状态迁移是否允许；同态不算迁移。"""
    if source is target:
        return False
    return target in _ALLOWED_TRANSITIONS[source]


def assert_status_transitions() -> tuple[str, ...]:
    """三态合法性：DEPRECATED 是终态；CONFLICTED→ACTIVE 只能由人工否决冲突触发。"""
    problems: list[str] = []
    if can_transition(KnowledgeStatus.DEPRECATED, KnowledgeStatus.ACTIVE):
        problems.append("DEPRECATED 不得复活")
    if can_transition(KnowledgeStatus.ACTIVE, KnowledgeStatus.ACTIVE):
        problems.append("同态迁移不得算作迁移")
    if not can_transition(KnowledgeStatus.CONFLICTED, KnowledgeStatus.ACTIVE):
        problems.append("人工否决冲突后必须允许 CONFLICTED→ACTIVE")
    if set(_ALLOWED_TRANSITIONS) != set(KnowledgeStatus):
        problems.append("状态迁移表未覆盖三态")
    return tuple(problems)


# ---------------------------------------------------------------------------
# 3. 冲突：检测 + 人工裁决，模型不得自选
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ConflictRecord:
    """一次冲突。`contenders` 只是候选，不含“推荐哪个”。"""

    ktype: KType
    scope: str
    conflicting_keys: tuple[str, ...]
    contenders: tuple[str, ...]
    requires_human: bool = True

    def __post_init__(self) -> None:
        if not self.conflicting_keys:
            raise KnowledgeValidationError("CONFLICT_KEYS_EMPTY", "conflicting_keys", "")
        if len(self.contenders) < 2:
            raise KnowledgeValidationError("CONFLICT_CONTENDERS_INSUFFICIENT", "contenders", str(len(self.contenders)))
        if not self.requires_human:
            raise KnowledgeGovernanceError(
                "STATE_TRANSITION_DENIED", "CONFLICT_REQUIRES_HUMAN",
                "冲突必须升级人工；不存在自动裁决",
            )


class ResolutionSource(StrEnum):
    HUMAN = "HUMAN"
    MODEL = "MODEL"  # 永远拒绝


class ResolutionDecision(StrEnum):
    KEEP_ONE_DEPRECATE_OTHERS = "KEEP_ONE_DEPRECATE_OTHERS"
    REJECT_CONFLICT_KEEP_ALL = "REJECT_CONFLICT_KEEP_ALL"


@dataclass(frozen=True, slots=True)
class HumanResolution:
    """人工裁决记录。`approved_by`/`approval_id` 缺一不可。"""

    source: ResolutionSource
    decision: ResolutionDecision
    approved_by: str
    approval_id: str
    winner: str | None  # kid@version；KEEP_ALL 时必须为 None

    def __post_init__(self) -> None:
        if self.source is ResolutionSource.MODEL:
            raise KnowledgeGovernanceError(
                "STATE_TRANSITION_DENIED", "MODEL_CANNOT_RESOLVE_CONFLICT",
                "模型不得自选知识版本",
            )
        if not self.approved_by.strip() or not self.approval_id.strip():
            raise KnowledgeGovernanceError(
                "STATE_TRANSITION_DENIED", "HUMAN_APPROVAL_REQUIRED",
                "人工裁决必须带 approved_by 与 approval_id",
            )
        if self.decision is ResolutionDecision.KEEP_ONE_DEPRECATE_OTHERS and not self.winner:
            raise KnowledgeValidationError("RESOLUTION_WINNER_MISSING", "winner", "")
        if self.decision is ResolutionDecision.REJECT_CONFLICT_KEEP_ALL and self.winner is not None:
            raise KnowledgeValidationError("RESOLUTION_WINNER_UNEXPECTED", "winner", self.winner)


def _flatten(value: object, prefix: str, out: dict[str, object]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _flatten(item, f"{prefix}.{key}" if prefix else str(key), out)
    elif isinstance(value, (list, tuple)):
        out[prefix] = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    else:
        out[prefix] = value


def detect_conflict(left: KnowledgeUnit, right: KnowledgeUnit) -> ConflictRecord | None:
    """检测同一 (ktype, scope) 两条 ACTIVE 记录的字段冲突。

    规则：
      - 不同 ktype/scope → 不构成冲突；
      - 任一方非 ACTIVE → 不构成冲突（已废弃/已冲突的不再重复告警）；
      - 逐字段比较 `structured`，冲突键按字典序输出，保证可复现。
    """
    if left.ktype is not right.ktype or left.scope != right.scope:
        return None
    if left.status is not KnowledgeStatus.ACTIVE or right.status is not KnowledgeStatus.ACTIVE:
        return None
    left_flat: dict[str, object] = {}
    right_flat: dict[str, object] = {}
    _flatten(_payload_mapping(left.structured), "", left_flat)
    _flatten(_payload_mapping(right.structured), "", right_flat)
    keys = sorted(
        key for key in set(left_flat) | set(right_flat)
        if left_flat.get(key, object()) != right_flat.get(key, object())
    )
    if not keys:
        return None
    return ConflictRecord(
        ktype=left.ktype,
        scope=left.scope,
        conflicting_keys=tuple(keys),
        contenders=(
            f"{left.kid}@{left.version}#{left.content_hash[:12]}",
            f"{right.kid}@{right.version}#{right.content_hash[:12]}",
        ),
    )


# ---------------------------------------------------------------------------
# 4. 静态守卫
# ---------------------------------------------------------------------------
def assert_field_parity() -> tuple[str, ...]:
    """验收判据：字段名与 §11.2 逐字一致（15 个，顺序也一致）。"""
    actual = tuple(f.name for f in fields(KnowledgeUnit))
    problems: list[str] = []
    if actual != EXPECTED_FIELDS:
        problems.append(f"字段不一致：{actual}")
    if len(actual) != 15:
        problems.append(f"字段数应为 15，实际 {len(actual)}")
    for required in ("kid", "ktype", "scope", "version", "structured", "text", "content_hash", "supersedes", "status"):
        if required not in actual:
            problems.append(f"缺少字段 {required}")
    return tuple(problems)


def assert_ktype_parity() -> tuple[str, ...]:
    """五类知识字面值必须与 M17 contracts.KNOWLEDGE_KINDS 一致（重复声明，故意可校验）。"""
    expected = ("SPEC", "TOOL", "DATASET", "FAULT_CASE", "PAPER_DOC")
    actual = tuple(k.value for k in KType)
    problems: list[str] = []
    if actual != expected:
        problems.append(f"KType 不一致：{actual}")
    if len(actual) != 5:
        problems.append(f"知识类型应为 5，实际 {len(actual)}")
    if set(PAYLOAD_BY_KTYPE) != set(KType):
        problems.append("payload 映射未覆盖五类")
    return tuple(problems)


def assert_payload_keys_match_11_1() -> tuple[str, ...]:
    """五类差异字段与 §11.1 的关键字段一致（PAPER_DOC 的 version 映射为 document_version）。"""
    problems: list[str] = []
    for ktype, payload_cls in PAYLOAD_BY_KTYPE.items():
        actual = tuple(f.name for f in fields(payload_cls))
        if actual != PAYLOAD_KEYS_BY_KTYPE[ktype]:
            problems.append(f"{ktype.value} 差异字段不一致：{actual}")
    if "metric_defs" not in PAYLOAD_KEYS_BY_KTYPE[KType.SPEC]:
        problems.append("SPEC 缺 metric_defs")
    if "signature" not in PAYLOAD_KEYS_BY_KTYPE[KType.FAULT_CASE]:
        problems.append("FAULT_CASE 缺 signature")
    return tuple(problems)


def assert_append_only() -> tuple[str, ...]:
    """知识记录不得有原地覆盖入口：只有 create/new_version/deprecate/mark_conflicted。"""
    problems: list[str] = []
    allowed = {"create", "new_version", "deprecate", "mark_conflicted"}
    for name in dir(KnowledgeUnit):
        if name.startswith("_"):
            continue
        if name in allowed:
            continue
        if any(token in name for token in ("set_", "update_", "overwrite", "replace_", "edit")):
            problems.append(f"KnowledgeUnit 暴露了原地修改入口 {name}")
    for name in ("set_status", "update_text", "overwrite"):
        if hasattr(KnowledgeUnit, name):
            problems.append(f"KnowledgeUnit 存在 {name}")
    return tuple(problems)


def assert_no_model_selection() -> tuple[str, ...]:
    """模型不得成为冲突裁决来源。"""
    problems: list[str] = []
    if ResolutionSource.MODEL.value != "MODEL":
        problems.append("ResolutionSource.MODEL 必须存在但被拒绝")
    try:
        HumanResolution(
            source=ResolutionSource.MODEL, decision=ResolutionDecision.KEEP_ONE_DEPRECATE_OTHERS,
            approved_by="human", approval_id="apr-1", winner="kb@2",
        )
    except KnowledgeGovernanceError:
        pass
    else:
        problems.append("模型裁决未被拒绝")
    return tuple(problems)