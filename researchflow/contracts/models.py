"""ResearchFlow 冻结契约的 Pydantic v2 模型（T0 · WP-02）。

与 `contracts/*.schema.json` v1.0 逐字段对应：

- `extra="forbid"` ↔ `additionalProperties: false`
- `Field(pattern=...)` ↔ JSON Schema `pattern`
- `Literal[...]` ↔ `const` / `enum`
- `model_validator` 承担 Schema 无法表达的跨字段约束：EvidenceRecord 的
  `level → producer/kind` 条件（原 `allOf`/`if-then`），以及 SEM-NS-01、
  SEM-VR-01、SEM-VR-02。

本模块只做契约落地，不含任何运行时状态迁移；状态迁移属于 WP-03 的
`StateMachine`。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1.0"

TASK_ID_PATTERN = r"^task_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
EVIDENCE_ID_PATTERN = r"^ev_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
REPORT_ID_PATTERN = r"^report_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
CERT_ID_PATTERN = r"^cert_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
ATTEMPT_ID_PATTERN = r"^attempt_[0-9]{2,}$"
NODE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
NODE_TYPE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
KEY_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
NAME_VERSION_PATTERN = r"^[a-z][a-z0-9_]*@\d+\.\d+\.\d+$"
RFC3339_UTC_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$"
ARTIFACT_URI_PATTERN = r"^artifact://[A-Za-z0-9][A-Za-z0-9._/-]*$"
LOCAL_URI_PATTERN = r"^local://[A-Za-z0-9][A-Za-z0-9._/-]*$"
LICENSE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9.+-]*$"
MODEL_NAME_PATTERN = r"^[a-z][a-z0-9_]*$"
BASE64_PATTERN = r"^[A-Za-z0-9+/]+={0,2}$"


def _utc_rfc3339(value: str) -> str:
    """校验 `format: date-time` 且时区必须为 UTC（Z 或 +00:00）。"""
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:  # pragma: no cover - pattern 已先拦截大部分
        raise ValueError(f"不是合法的 RFC 3339 时间：{value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"时间必须是 UTC（Z 或 +00:00）：{value!r}")
    return value


def _unique(values: list[str], label: str) -> list[str]:
    if len(values) != len(dict.fromkeys(values)):
        raise ValueError(f"{label} 不得包含重复项")
    return values


class _StrictModel(BaseModel):
    """严格模式：拒绝类型强转，等价于 JSON Schema 的类型判定。"""

    model_config = ConfigDict(strict=True, extra="forbid")


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
NameVersion = Annotated[str, Field(pattern=NAME_VERSION_PATTERN)]
UtcTimestamp = Annotated[
    str, Field(pattern=RFC3339_UTC_PATTERN), AfterValidator(_utc_rfc3339)
]
Base64Signature = Annotated[str, Field(min_length=4, pattern=BASE64_PATTERN)]


# --------------------------------------------------------------------- TaskSpec
class DatasetRef(_StrictModel):
    uri: str = Field(pattern=LOCAL_URI_PATTERN)
    sha256: Sha256
    license: str = Field(min_length=1, pattern=LICENSE_PATTERN)


class TaskParameters(BaseModel):
    """`additionalProperties: true`：已知键强类型，模板自定义键由模板层校验。"""

    model_config = ConfigDict(strict=True, extra="allow")

    target: str | None = Field(default=None, min_length=1)
    seed: int | None = Field(default=None, ge=0)
    test_size: float | None = Field(default=None, gt=0, lt=1)
    models: list[Annotated[str, Field(pattern=MODEL_NAME_PATTERN)]] | None = Field(
        default=None, min_length=1
    )

    @field_validator("models")
    @classmethod
    def _models_unique(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            _unique(value, "parameters.models")
        return value

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in ("target", "seed", "test_size", "models"):
                if key in data and data[key] is None:
                    raise ValueError(f"parameters.{key} 不得为 null")
        return data


class TaskLimits(_StrictModel):
    wall_time_sec: int = Field(gt=0)
    max_workers: int = Field(ge=1, le=2)
    max_memory_mb: int = Field(gt=0)


class TaskSpecCreate(_StrictModel):
    """API 创建请求体：与 TaskSpec 相同，唯独 `task_id` 由服务端生成。"""

    schema_version: Literal["1.0"]
    domain_pack: NameVersion
    goal: str = Field(min_length=1)
    dataset_ref: DatasetRef
    template_id: NameVersion
    parameters: TaskParameters
    ruleset_hash: Sha256
    limits: TaskLimits


class TaskSpec(TaskSpecCreate):
    task_id: str = Field(pattern=TASK_ID_PATTERN)


# --------------------------------------------------------------------- NodeSpec
class RetryPolicy(_StrictModel):
    max_attempts: int = Field(ge=1)
    backoff_sec: float = Field(ge=0)


class NodeSpec(_StrictModel):
    schema_version: Literal["1.0"]
    node_id: str = Field(pattern=NODE_ID_PATTERN)
    node_type: str = Field(pattern=NODE_TYPE_PATTERN)
    template_id: NameVersion
    depends_on: list[Annotated[str, Field(pattern=NODE_ID_PATTERN)]]
    input_refs: list[Annotated[str, Field(pattern=ARTIFACT_URI_PATTERN)]]
    parameters_hash: Sha256
    side_effect_class: Literal["PURE_FUNCTION", "PURE_ARTIFACT", "SIDE_EFFECT"]
    retry_policy: RetryPolicy
    required_checks: list[Annotated[str, Field(pattern=MODEL_NAME_PATTERN)]]

    @field_validator("depends_on")
    @classmethod
    def _depends_unique(cls, value: list[str]) -> list[str]:
        return _unique(value, "depends_on")

    @field_validator("required_checks")
    @classmethod
    def _checks_present(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("required_checks 不得为空")
        return _unique(value, "required_checks")

    @model_validator(mode="after")
    def _no_self_dependency(self) -> "NodeSpec":
        """SEM-NS-01：节点不得依赖自身。"""
        if self.node_id in self.depends_on:
            raise ValueError(f"SEM-NS-01：node_id={self.node_id!r} 不能出现在 depends_on")
        return self


# ---------------------------------------------------------------- EvidenceRecord
EvidenceLevel = Literal["E0", "E1", "E2", "E3"]
EvidenceKind = Literal[
    "agent_claim",
    "tool_invocation",
    "harness_trace",
    "executor_launch",
    "executor_process_exit",
    "artifact_observed",
    "verifier_recheck",
]

_LEVEL_RULES: dict[str, tuple[str, frozenset[str]]] = {
    "E0": ("collector", frozenset({"agent_claim"})),
    "E1": ("collector", frozenset({"tool_invocation", "harness_trace"})),
    "E2": (
        "collector",
        frozenset({"executor_launch", "executor_process_exit", "artifact_observed"}),
    ),
    "E3": ("verifier", frozenset({"verifier_recheck"})),
}


class EvidenceRecord(_StrictModel):
    schema_version: Literal["1.0"]
    evidence_id: str = Field(pattern=EVIDENCE_ID_PATTERN)
    task_id: str = Field(pattern=TASK_ID_PATTERN)
    node_id: str = Field(pattern=NODE_ID_PATTERN)
    attempt_id: str = Field(pattern=ATTEMPT_ID_PATTERN)
    event_seq: int = Field(ge=1)
    level: EvidenceLevel
    kind: EvidenceKind
    producer: str = Field(pattern=MODEL_NAME_PATTERN)
    timestamp: UtcTimestamp
    payload_hash: Sha256
    artifact_refs: list[Annotated[str, Field(pattern=ARTIFACT_URI_PATTERN)]] | None = None
    prev_hash: Sha256
    chain_hash: Sha256

    @field_validator("artifact_refs")
    @classmethod
    def _artifact_refs_unique(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is not None:
            _unique(value, "artifact_refs")
        return value

    @model_validator(mode="after")
    def _level_consistency(self) -> "EvidenceRecord":
        """固化 01 §4.3 的 `level → producer/kind` 机器约束（原 allOf）。"""
        expected_producer, expected_kinds = _LEVEL_RULES[self.level]
        if self.producer != expected_producer:
            raise ValueError(
                f"level={self.level} 的证据只能由 {expected_producer!r} 写入，"
                f"实际 producer={self.producer!r}"
            )
        if self.kind not in expected_kinds:
            allowed = ", ".join(sorted(expected_kinds))
            raise ValueError(f"level={self.level} 的 kind 只能是 [{allowed}]，实际 {self.kind!r}")
        return self


# ------------------------------------------------------------ VerificationReport
CheckStatus = Literal["PASS", "FAIL", "SKIP", "NOT_RUN"]


class RequiredCheckCoverage(_StrictModel):
    required: int = Field(ge=0)
    passed: int = Field(ge=0)
    missing: int = Field(ge=0)


class VerificationReport(_StrictModel):
    schema_version: Literal["1.0"]
    report_id: str = Field(pattern=REPORT_ID_PATTERN)
    task_id: str = Field(pattern=TASK_ID_PATTERN)
    final_state: Literal["VERIFIED", "PARTIAL", "FAILED", "BLOCKED"]
    l1_status: CheckStatus
    l2_status: CheckStatus
    l3_status: CheckStatus
    required_check_coverage: RequiredCheckCoverage
    ruleset_hash: Sha256
    evidence_root: Sha256
    l3_coverage: float = Field(ge=0, le=1)
    issued_at: UtcTimestamp
    key_id: str = Field(pattern=KEY_ID_PATTERN)
    signature: Base64Signature

    @model_validator(mode="after")
    def _coverage_arithmetic(self) -> "VerificationReport":
        """SEM-VR-01：passed<=required 且 missing==required-passed。"""
        coverage = self.required_check_coverage
        if coverage.passed > coverage.required:
            raise ValueError(
                f"SEM-VR-01：passed={coverage.passed} 大于 required={coverage.required}"
            )
        expected_missing = coverage.required - coverage.passed
        if coverage.missing != expected_missing:
            raise ValueError(
                "SEM-VR-01：missing 必须等于 required-passed"
                f"（期望 {expected_missing}，实际 {coverage.missing}）"
            )
        if self.final_state == "VERIFIED" and coverage.missing != 0:
            raise ValueError(
                f"SEM-VR-02：VERIFIED 报告不得有必检缺口（missing={coverage.missing}）"
            )
        return self


# --------------------------------------------------------- CompletionCertificate
class CompletionCertificate(_StrictModel):
    schema_version: Literal["1.0"]
    cert_id: str = Field(pattern=CERT_ID_PATTERN)
    report_id: str = Field(pattern=REPORT_ID_PATTERN)
    final_state: Literal["VERIFIED"]
    merkle_root: Sha256
    tree_size: int = Field(ge=1)
    ruleset_hash: Sha256
    code_hash: Sha256
    env_fingerprint: Sha256
    l3_coverage: float = Field(ge=0, le=1)
    skipped_nodes: list[Annotated[str, Field(pattern=NODE_ID_PATTERN)]] = Field(
        max_length=0
    )
    alg: Literal["Ed25519"]
    key_id: str = Field(pattern=KEY_ID_PATTERN)
    key_fingerprint: Sha256
    signature: Base64Signature
    issued_at: UtcTimestamp


MODEL_BY_CONTRACT: dict[str, type[BaseModel]] = {
    "taskspec": TaskSpec,
    "nodespec": NodeSpec,
    "evidencerecord": EvidenceRecord,
    "verificationreport": VerificationReport,
    "completioncertificate": CompletionCertificate,
}

__all__ = [
    "MODEL_BY_CONTRACT",
    "CompletionCertificate",
    "DatasetRef",
    "EvidenceRecord",
    "NodeSpec",
    "RequiredCheckCoverage",
    "RetryPolicy",
    "TaskLimits",
    "TaskParameters",
    "TaskSpec",
    "TaskSpecCreate",
    "VerificationReport",
]