"""MODULE: M08 · evidence/ruleset.py — Gate 规则集装载、必检项与版本哈希（P5 伪代码）
阶段/追踪: P5「门控与三级验证」｜FR-006（必检覆盖矩阵）、I-02/I-04、策划书 §7.2、05 §13
FR/依赖: FR-006；依赖 M01 JCS/SHA-256 端口、M01 冻结枚举（level/kind/producer）、M06 required_checks 声明
不变量/错误码: 必检项非空且 ID 唯一；执行类必检 min_level ∈ {E2,E3}；规则集哈希覆盖全部规则字段且不含自身；
             task.ruleset_hash 必须等于装载后的 ruleset_hash；E0 不得作为任何必检项的最低等级。
             错误码：SCHEMA_INVALID（422，规则集结构/取值非法）、RULESET_VERSION_MISMATCH（409，版本/哈希不符）
写入者: **无**；规则集是只读输入，Gate 不得增删必检项、不得改写规则版本
状态: 伪代码；不建环境、不跑测试、不写业务代码；本文件不定义 HTTP 路由

## 规则集是什么

  `gates.yaml`（部署配置）在装载时被解析为 `Ruleset`：必检项清单、每项的**最低证据等级**、
  是否执行类、是否要求 L3/IRC、每项接受哪些证据 kind / 哪个产物名；外加 L3 覆盖策略与
  冲突策略。规则集本身**不是证据**，它只回答“判什么、按什么版本判”。

## 版本哈希（为什么必须能重算）

  `ruleset_hash = sha256(JCS(payload))`，`payload` 恰好是 `RULESET_FIELDS` 的五个字段：

      schema_version / ruleset_version / required_checks / l3_policy / conflict_policy

  - `ruleset_hash` 是信封字段，**不进入**前像；否则哈希会自指。
  - `required_checks` **保持声明顺序**，不排序：声明顺序就是 coverage 的展示顺序，
    排序会掩盖“规则集被重排/重写”的事实（JCS 只排对象键，不排数组）。
  - TaskSpec.ruleset_hash、Gate 装载后的 ruleset_hash、Verifier 报告 ruleset_hash
    三者必须一致；任何一处不同都抛 `RULESET_VERSION_MISMATCH`，不得“按最新规则继续判”。

## 反空转（anti-vacuity）

  规则集不允许空必检列表；Gate 也不允许“某必检项没有绑定任何节点”时按通过处理。
  本文件只负责在装载期拒绝空规则；矩阵层的空绑定判定见 `coverage_matrix.py`。

## 本文件不定义

  - 不定义 gates.yaml 的磁盘格式/键名之外的部署细节（WP-08 落地时以本 payload 为准）。
  - 不定义 L1/L2/L3 的算法（M09/M10）。
  - 不定义冲突如何解决：只声明 T0 策略为 `REJECT_UNRESOLVED`。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

__all__ = [
    "CHECK_ID_PATTERN",
    "CONFLICT_POLICY_REJECT_UNRESOLVED",
    "EVIDENCE_KINDS",
    "EXECUTION_CRITICAL_MIN_LEVEL",
    "KIND_LEVEL",
    "LEVEL_RANK",
    "RULESET_FIELDS",
    "RULESET_SCHEMA_VERSION",
    "EvidenceRule",
    "L3Policy",
    "RequiredCheck",
    "Ruleset",
    "RulesetError",
    "assert_ruleset_boundary",
    "assert_task_binding",
    "compute_ruleset_hash",
    "default_classification_ruleset",
    "load_ruleset",
]

RULESET_SCHEMA_VERSION: Final[str] = "1.0"
RULESET_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
    "ruleset_version",
    "required_checks",
    "l3_policy",
    "conflict_policy",
)
CONFLICT_POLICY_REJECT_UNRESOLVED: Final[str] = "REJECT_UNRESOLVED"

LEVEL_RANK: Final[Mapping[str, int]] = MappingProxyType({"E0": 0, "E1": 1, "E2": 2, "E3": 3})
EXECUTION_CRITICAL_MIN_LEVEL: Final[tuple[str, ...]] = ("E2", "E3")

EVIDENCE_KINDS: Final[tuple[str, ...]] = (
    "agent_claim",
    "tool_invocation",
    "harness_trace",
    "executor_launch",
    "executor_process_exit",
    "artifact_observed",
    "verifier_recheck",
)

# 05 §4.5 的等级-类型映射：规则集只能引用这张表，不得自造 kind。
KIND_LEVEL: Final[Mapping[str, str]] = MappingProxyType({
    "agent_claim": "E0",
    "tool_invocation": "E1",
    "harness_trace": "E1",
    "executor_launch": "E2",
    "executor_process_exit": "E2",
    "artifact_observed": "E2",
    "verifier_recheck": "E3",
})

CHECK_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")
_RULESET_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_HASH64 = re.compile(r"^[0-9a-f]{64}$")


class RulesetError(RuntimeError):
    """规则集装载/绑定失败；对外码只用已注册码。

    结构/取值问题 → `SCHEMA_INVALID`(422)；版本或哈希不符 → `RULESET_VERSION_MISMATCH`(409)。
    两者都不允许“降级为警告后继续”。
    """

    def __init__(
        self,
        error_code: str,
        reason: str,
        message: str,
        *,
        field_path: str = "",
        http_status: int = 422,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.error_code = error_code
        self.reason = reason
        self.field_path = field_path
        self.http_status = http_status
        self.detail = MappingProxyType(dict(detail or {}))
        super().__init__(f"{error_code}/{reason} @ {field_path}: {message}")


class CanonicalizerPort(Protocol):
    """JCS 规范化端口（M01 唯一实现；不得用 json.dumps(sort_keys=True) 替代）。"""

    def canonical_bytes(self, value: object) -> bytes: ...


# ---------------------------------------------------------------------------
# 1. 规则项
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EvidenceRule:
    """一个必检项接受什么证据。

    `accepted_kinds` 是**机器可判**的 kind 白名单；`artifact_name` 非空时，证据的
    `artifact_refs` 必须包含 `artifact://<artifact_name>`。Gate 不读取证据自报的
    “我满足哪个 check”——那会把判定权交回被验证方。

    `min_level` 在 `RequiredCheck` 上，不在本类重复；本类只描述“长什么样”。
    """

    accepted_kinds: tuple[str, ...]
    artifact_name: str | None = None

    def __post_init__(self) -> None:
        if not self.accepted_kinds:
            raise RulesetError(
                "SCHEMA_INVALID", "EVIDENCE_RULE_EMPTY",
                "accepted_kinds 不得为空", field_path="evidence_rule.accepted_kinds",
            )
        unknown = [k for k in self.accepted_kinds if k not in KIND_LEVEL]
        if unknown:
            raise RulesetError(
                "SCHEMA_INVALID", "EVIDENCE_KIND_UNKNOWN",
                f"未知证据 kind：{unknown}", field_path="evidence_rule.accepted_kinds",
            )
        if len(set(self.accepted_kinds)) != len(self.accepted_kinds):
            raise RulesetError(
                "SCHEMA_INVALID", "EVIDENCE_KIND_DUPLICATED",
                "accepted_kinds 不得重复", field_path="evidence_rule.accepted_kinds",
            )
        if self.artifact_name is not None and not _ARTIFACT_NAME.match(self.artifact_name):
            raise RulesetError(
                "SCHEMA_INVALID", "ARTIFACT_NAME_INVALID",
                f"artifact_name 形态非法：{self.artifact_name!r}",
                field_path="evidence_rule.artifact_name",
            )

    def matches_kind(self, kind: str) -> bool:
        return kind in self.accepted_kinds

    def matches_artifact(self, artifact_refs: Sequence[str]) -> bool:
        if self.artifact_name is None:
            return True
        wanted = f"artifact://{self.artifact_name}"
        return wanted in artifact_refs

    def as_payload(self) -> dict[str, object]:
        return {
            "accepted_kinds": list(self.accepted_kinds),
            "artifact_name": self.artifact_name,
        }


@dataclass(frozen=True, slots=True)
class RequiredCheck:
    """一个必检项：ID、最低证据等级、是否执行类、是否要求 L3、接受什么证据。

    `execution_critical=True` 时，`min_level` 必须是 E2/E3；E0/E1 永远不满足
    （Gate 第 6 步还会再查一遍，纵深防御）。
    """

    check_id: str
    description: str
    min_level: str
    execution_critical: bool
    l3_required: bool
    evidence_rule: EvidenceRule

    def __post_init__(self) -> None:
        if not isinstance(self.check_id, str) or not CHECK_ID_PATTERN.match(self.check_id):
            raise RulesetError(
                "SCHEMA_INVALID", "CHECK_ID_INVALID",
                f"check_id 必须匹配 ^[a-z][a-z0-9_]*$：{self.check_id!r}",
                field_path="required_checks[].check_id",
            )
        if not isinstance(self.description, str) or not self.description.strip():
            raise RulesetError(
                "SCHEMA_INVALID", "CHECK_DESCRIPTION_EMPTY",
                "description 不得为空", field_path=f"required_checks[{self.check_id}].description",
            )
        if self.min_level not in LEVEL_RANK or self.min_level == "E0":
            raise RulesetError(
                "SCHEMA_INVALID", "CHECK_MIN_LEVEL_INVALID",
                f"min_level 必须是 E1/E2/E3（E0 声明不能作为必检最低等级）：{self.min_level!r}",
                field_path=f"required_checks[{self.check_id}].min_level",
            )
        if self.execution_critical and self.min_level not in EXECUTION_CRITICAL_MIN_LEVEL:
            raise RulesetError(
                "SCHEMA_INVALID", "EXECUTION_CHECK_LEVEL_TOO_LOW",
                f"执行类必检 {self.check_id!r} 的 min_level 必须是 E2/E3，实际 {self.min_level}",
                field_path=f"required_checks[{self.check_id}].min_level",
            )
        for kind in self.evidence_rule.accepted_kinds:
            if LEVEL_RANK[KIND_LEVEL[kind]] < LEVEL_RANK[self.min_level]:
                raise RulesetError(
                    "SCHEMA_INVALID", "EVIDENCE_RULE_BELOW_MIN_LEVEL",
                    f"{self.check_id!r} 接受 {kind}（{KIND_LEVEL[kind]}），低于 min_level {self.min_level}；"
                    "这种规则永远无法满足，必须在装载期拒绝",
                    field_path=f"required_checks[{self.check_id}].evidence_rule",
                )
        if self.l3_required and self.min_level not in EXECUTION_CRITICAL_MIN_LEVEL:
            raise RulesetError(
                "SCHEMA_INVALID", "L3_REQUIRED_BUT_LEVEL_TOO_LOW",
                f"{self.check_id!r} 要求 L3，但 min_level 只有 {self.min_level}",
                field_path=f"required_checks[{self.check_id}].l3_required",
            )

    def as_payload(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "description": self.description,
            "min_level": self.min_level,
            "execution_critical": self.execution_critical,
            "l3_required": self.l3_required,
            "evidence_rule": self.evidence_rule.as_payload(),
        }


@dataclass(frozen=True, slots=True)
class L3Policy:
    """L3/IRC 覆盖策略（阈值属规则集，不属 schema；05 §13）。

    `required_coverage` 是报告指标来源节点中必须有 PASS L3 的比例，闭区间 [0,1]。
    T0 默认 1.0：任何指标来源节点缺 L3 都不能 PASS。
    `metric_source_check_ids` 是“指标来源”语义绑定的必检项；这些项必须存在。
    """

    required_coverage: float
    metric_source_check_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.required_coverage, bool) or not isinstance(self.required_coverage, (int, float)):
            raise RulesetError(
                "SCHEMA_INVALID", "L3_COVERAGE_TYPE",
                "required_coverage 必须是 number", field_path="l3_policy.required_coverage",
            )
        value = float(self.required_coverage)
        if not (0.0 <= value <= 1.0) or value != value:
            raise RulesetError(
                "SCHEMA_INVALID", "L3_COVERAGE_RANGE",
                f"required_coverage 必须在 [0,1]：{value}",
                field_path="l3_policy.required_coverage",
            )
        if not self.metric_source_check_ids:
            raise RulesetError(
                "SCHEMA_INVALID", "L3_METRIC_CHECKS_EMPTY",
                "metric_source_check_ids 不得为空（至少绑定一个指标来源必检项）",
                field_path="l3_policy.metric_source_check_ids",
            )
        for check_id in self.metric_source_check_ids:
            if not CHECK_ID_PATTERN.match(check_id):
                raise RulesetError(
                    "SCHEMA_INVALID", "L3_METRIC_CHECK_INVALID",
                    f"metric_source_check_ids 含非法 ID：{check_id!r}",
                    field_path="l3_policy.metric_source_check_ids",
                )
        if len(set(self.metric_source_check_ids)) != len(self.metric_source_check_ids):
            raise RulesetError(
                "SCHEMA_INVALID", "L3_METRIC_CHECK_DUPLICATED",
                "metric_source_check_ids 不得重复",
                field_path="l3_policy.metric_source_check_ids",
            )

    def as_payload(self) -> dict[str, object]:
        return {
            "required_coverage": float(self.required_coverage),
            "metric_source_check_ids": list(self.metric_source_check_ids),
        }


# ---------------------------------------------------------------------------
# 2. 规则集与版本哈希
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Ruleset:
    """一份已装载的规则集；`ruleset_hash` 为空表示尚未封哈希。

    构造会做结构校验；封哈希必须走 `with_hash()`，禁止调用方自报哈希。
    """

    schema_version: str
    ruleset_version: str
    required_checks: tuple[RequiredCheck, ...]
    l3_policy: L3Policy
    conflict_policy: str = CONFLICT_POLICY_REJECT_UNRESOLVED
    ruleset_hash: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != RULESET_SCHEMA_VERSION:
            raise RulesetError(
                "RULESET_VERSION_MISMATCH", "RULESET_SCHEMA_VERSION_UNSUPPORTED",
                f"只支持规则集 schema_version={RULESET_SCHEMA_VERSION}，实际 {self.schema_version!r}",
                field_path="schema_version", http_status=409,
            )
        if not isinstance(self.ruleset_version, str) or not _RULESET_VERSION.match(self.ruleset_version):
            raise RulesetError(
                "SCHEMA_INVALID", "RULESET_VERSION_INVALID",
                f"ruleset_version 形态非法：{self.ruleset_version!r}",
                field_path="ruleset_version",
            )
        if not self.required_checks:
            raise RulesetError(
                "SCHEMA_INVALID", "RULESET_EMPTY",
                "规则集不得为空：没有必检项就没有 Gate 判定",
                field_path="required_checks",
            )
        ids = [check.check_id for check in self.required_checks]
        if len(set(ids)) != len(ids):
            duplicated = sorted({x for x in ids if ids.count(x) > 1})
            raise RulesetError(
                "SCHEMA_INVALID", "CHECK_ID_DUPLICATED",
                f"必检项 ID 重复：{duplicated}", field_path="required_checks",
            )
        by_id = {check.check_id: check for check in self.required_checks}
        for check_id in self.l3_policy.metric_source_check_ids:
            check = by_id.get(check_id)
            if check is None:
                raise RulesetError(
                    "SCHEMA_INVALID", "L3_METRIC_CHECK_UNKNOWN",
                    f"L3 策略引用了不存在的必检项 {check_id!r}",
                    field_path="l3_policy.metric_source_check_ids",
                )
            if check.min_level not in EXECUTION_CRITICAL_MIN_LEVEL:
                raise RulesetError(
                    "SCHEMA_INVALID", "L3_METRIC_CHECK_NOT_EXECUTION",
                    f"指标来源必检项 {check_id!r} 的 min_level 必须是 E2/E3",
                    field_path=f"required_checks[{check_id}].min_level",
                )
        if self.conflict_policy != CONFLICT_POLICY_REJECT_UNRESOLVED:
            raise RulesetError(
                "SCHEMA_INVALID", "CONFLICT_POLICY_UNSUPPORTED",
                f"T0 只允许 {CONFLICT_POLICY_REJECT_UNRESOLVED}，实际 {self.conflict_policy!r}",
                field_path="conflict_policy",
            )
        if self.ruleset_hash and not _HASH64.match(self.ruleset_hash):
            raise RulesetError(
                "RULESET_VERSION_MISMATCH", "RULESET_HASH_INVALID",
                "ruleset_hash 必须是 64 位小写十六进制",
                field_path="ruleset_hash", http_status=409,
            )

    # -- 载荷与哈希 -------------------------------------------------------
    def payload(self) -> dict[str, object]:
        """恰好 `RULESET_FIELDS` 五个字段；顺序固定供 JCS/快照断言。"""
        return {
            "schema_version": self.schema_version,
            "ruleset_version": self.ruleset_version,
            "required_checks": [check.as_payload() for check in self.required_checks],
            "l3_policy": self.l3_policy.as_payload(),
            "conflict_policy": self.conflict_policy,
        }

    def with_hash(self, canonicalizer: CanonicalizerPort) -> "Ruleset":
        digest = compute_ruleset_hash(self.payload(), canonicalizer)
        return Ruleset(
            schema_version=self.schema_version,
            ruleset_version=self.ruleset_version,
            required_checks=self.required_checks,
            l3_policy=self.l3_policy,
            conflict_policy=self.conflict_policy,
            ruleset_hash=digest,
        )

    def verify_hash(self, canonicalizer: CanonicalizerPort) -> str:
        """重算并返回当前规则集的哈希；不修改对象。"""
        return compute_ruleset_hash(self.payload(), canonicalizer)

    def check(self, check_id: str) -> RequiredCheck:
        for item in self.required_checks:
            if item.check_id == check_id:
                return item
        raise RulesetError(
            "SCHEMA_INVALID", "CHECK_ID_UNKNOWN",
            f"规则集没有必检项 {check_id!r}", field_path="required_checks",
        )

    def check_ids(self) -> tuple[str, ...]:
        return tuple(item.check_id for item in self.required_checks)


def compute_ruleset_hash(payload: Mapping[str, object], canonicalizer: CanonicalizerPort) -> str:
    """`ruleset_hash = sha256(JCS(payload))`；只接受恰好五字段的映射。"""
    if set(payload) != set(RULESET_FIELDS):
        raise RulesetError(
            "SCHEMA_INVALID", "RULESET_FIELDS_MISMATCH",
            f"规则集载荷必须恰好包含 {list(RULESET_FIELDS)}，实际 {sorted(payload)}",
            field_path="ruleset_hash",
        )
    canonical = canonicalizer.canonical_bytes(dict(payload))
    return hashlib.sha256(canonical).hexdigest()


# ---------------------------------------------------------------------------
# 3. 装载
# ---------------------------------------------------------------------------
_TOP_KEYS: Final[frozenset[str]] = frozenset(RULESET_FIELDS)
_CHECK_KEYS: Final[frozenset[str]] = frozenset(
    {"check_id", "description", "min_level", "execution_critical", "l3_required", "evidence_rule"}
)
_RULE_KEYS: Final[frozenset[str]] = frozenset({"accepted_kinds", "artifact_name"})
_L3_KEYS: Final[frozenset[str]] = frozenset({"required_coverage", "metric_source_check_ids"})


def _expect_mapping(value: object, *, field_path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RulesetError(
            "SCHEMA_INVALID", "RULESET_NOT_OBJECT",
            f"{field_path} 必须是对象", field_path=field_path,
        )
    return value


def _expect_keys(raw: Mapping[str, object], allowed: frozenset[str], *, field_path: str) -> None:
    unknown = sorted(set(raw) - allowed)
    missing = sorted(allowed - set(raw))
    if unknown:
        raise RulesetError(
            "SCHEMA_INVALID", "RULESET_UNKNOWN_FIELD",
            f"{field_path} 出现未声明键：{unknown}", field_path=f"{field_path}.{unknown[0]}",
        )
    if missing:
        raise RulesetError(
            "SCHEMA_INVALID", "RULESET_MISSING_FIELD",
            f"{field_path} 缺少必填键：{missing}", field_path=f"{field_path}.{missing[0]}",
        )


def _parse_check(raw: object, index: int) -> RequiredCheck:
    item = _expect_mapping(raw, field_path=f"required_checks[{index}]")
    _expect_keys(item, _CHECK_KEYS, field_path=f"required_checks[{index}]")
    rule_raw = _expect_mapping(item["evidence_rule"], field_path=f"required_checks[{index}].evidence_rule")
    _expect_keys(rule_raw, _RULE_KEYS, field_path=f"required_checks[{index}].evidence_rule")
    kinds_raw = rule_raw["accepted_kinds"]
    if not isinstance(kinds_raw, list) or not all(isinstance(x, str) for x in kinds_raw):
        raise RulesetError(
            "SCHEMA_INVALID", "EVIDENCE_KINDS_NOT_ARRAY",
            "accepted_kinds 必须是字符串数组",
            field_path=f"required_checks[{index}].evidence_rule.accepted_kinds",
        )
    artifact_name = rule_raw["artifact_name"]
    if artifact_name is not None and not isinstance(artifact_name, str):
        raise RulesetError(
            "SCHEMA_INVALID", "ARTIFACT_NAME_TYPE",
            "artifact_name 必须是字符串或 null",
            field_path=f"required_checks[{index}].evidence_rule.artifact_name",
        )
    if not isinstance(item["execution_critical"], bool) or not isinstance(item["l3_required"], bool):
        raise RulesetError(
            "SCHEMA_INVALID", "CHECK_FLAG_TYPE",
            "execution_critical / l3_required 必须是 boolean",
            field_path=f"required_checks[{index}]",
        )
    return RequiredCheck(
        check_id=item["check_id"],  # type: ignore[arg-type]
        description=item["description"],  # type: ignore[arg-type]
        min_level=item["min_level"],  # type: ignore[arg-type]
        execution_critical=item["execution_critical"],  # type: ignore[arg-type]
        l3_required=item["l3_required"],  # type: ignore[arg-type]
        evidence_rule=EvidenceRule(
            accepted_kinds=tuple(kinds_raw),
            artifact_name=artifact_name,  # type: ignore[arg-type]
        ),
    )


def load_ruleset(raw: Mapping[str, object], canonicalizer: CanonicalizerPort) -> Ruleset:
    """把 `gates.yaml` 的解析结果装载为已封哈希的 `Ruleset`。

    步骤（顺序固定，负例按顺序断言）：
      1. 顶层必须是对象，且键恰好 `RULESET_FIELDS`；
      2. schema_version / ruleset_version 形态；
      3. required_checks 逐项解析（ID/等级/证据规则）；
      4. l3_policy 解析；
      5. 组装 `Ruleset`（构造期做跨字段校验）；
      6. 计算并封 `ruleset_hash`；
      7. 再重算一次哈希，断言封哈希过程没有改变语义。

    不读文件、不联网、不写文件；文件读取属 WP-08 部署层。
    """
    top = _expect_mapping(raw, field_path="$")
    _expect_keys(top, _TOP_KEYS, field_path="$")
    checks_raw = top["required_checks"]
    if not isinstance(checks_raw, list) or not checks_raw:
        raise RulesetError(
            "SCHEMA_INVALID", "REQUIRED_CHECKS_NOT_ARRAY",
            "required_checks 必须是非空数组", field_path="required_checks",
        )
    checks = tuple(_parse_check(item, index) for index, item in enumerate(checks_raw))
    l3_raw = _expect_mapping(top["l3_policy"], field_path="l3_policy")
    _expect_keys(l3_raw, _L3_KEYS, field_path="l3_policy")
    metric_ids = l3_raw["metric_source_check_ids"]
    if not isinstance(metric_ids, list) or not all(isinstance(x, str) for x in metric_ids):
        raise RulesetError(
            "SCHEMA_INVALID", "L3_METRIC_CHECKS_NOT_ARRAY",
            "metric_source_check_ids 必须是字符串数组",
            field_path="l3_policy.metric_source_check_ids",
        )
    for name in ("schema_version", "ruleset_version", "conflict_policy"):
        if not isinstance(top[name], str):
            raise RulesetError(
                "SCHEMA_INVALID", "RULESET_FIELD_TYPE",
                f"{name} 必须是字符串", field_path=name,
            )
    policy = L3Policy(
        required_coverage=l3_raw["required_coverage"],  # type: ignore[arg-type]
        metric_source_check_ids=tuple(metric_ids),
    )
    sealed = Ruleset(
        schema_version=top["schema_version"],  # type: ignore[arg-type]
        ruleset_version=top["ruleset_version"],  # type: ignore[arg-type]
        required_checks=checks,
        l3_policy=policy,
        conflict_policy=top["conflict_policy"],  # type: ignore[arg-type]
    ).with_hash(canonicalizer)
    if sealed.verify_hash(canonicalizer) != sealed.ruleset_hash:
        raise RulesetError(
            "RULESET_VERSION_MISMATCH", "RULESET_HASH_UNSTABLE",
            "封哈希后重算不一致：规则集含不稳定字段",
            field_path="ruleset_hash", http_status=409,
        )
    return sealed


# ---------------------------------------------------------------------------
# 4. 任务绑定
# ---------------------------------------------------------------------------
def assert_task_binding(task_ruleset_hash: str, ruleset: Ruleset) -> None:
    """TaskSpec.ruleset_hash 必须等于当前规则集哈希；不等即一票否决。

    为什么不在 Gate 里“自动升级到最新规则”：那会让历史任务在规则变化后静默改变判定，
    也让报告 ruleset_hash 失去意义。版本不符只能重新验证并重签。
    """
    if not isinstance(task_ruleset_hash, str) or not _HASH64.match(task_ruleset_hash):
        raise RulesetError(
            "SCHEMA_INVALID", "TASK_RULESET_HASH_INVALID",
            "TaskSpec.ruleset_hash 必须是 64 位小写十六进制", field_path="task.ruleset_hash",
        )
    if task_ruleset_hash != ruleset.ruleset_hash:
        raise RulesetError(
            "RULESET_VERSION_MISMATCH", "TASK_RULESET_MISMATCH",
            "任务绑定的规则版本与当前规则集不一致",
            field_path="task.ruleset_hash", http_status=409,
            detail={
                "task_ruleset_hash": task_ruleset_hash,
                "current_ruleset_hash": ruleset.ruleset_hash,
                "ruleset_version": ruleset.ruleset_version,
            },
        )


# ---------------------------------------------------------------------------
# 5. T0 默认规则集（classification_benchmark@1.0.0）
# ---------------------------------------------------------------------------
def default_classification_ruleset(canonicalizer: CanonicalizerPort) -> Ruleset:
    """T0 内置分类模板的规则集；不是 G0 契约，WP-08 可替换但必须保留本文件的校验。

    证据规则刻意与产物名绑定：
      - `split_manifest.json` / `predictions.csv` / `metrics.json` / `leakage_report.json`
        都是 M06 模板声明的产物名；改名必须同步规则集版本，否则 coverage 会变成 GAP。
      - E1 两项（模型/超参白名单、seed 记录）只能由 `tool_invocation` 证明，
        不满足执行类必检；它们不是“跑过了”的证据。
    """
    checks = (
        RequiredCheck(
            check_id="dataset_hash_match",
            description="绑定数据字节哈希 = 登记哈希",
            min_level="E2",
            execution_critical=True,
            l3_required=False,
            evidence_rule=EvidenceRule(("executor_launch", "executor_process_exit")),
        ),
        RequiredCheck(
            check_id="split_manifest_valid",
            description="六字段齐全且 manifest_hash 重算一致",
            min_level="E2",
            execution_critical=True,
            l3_required=True,
            evidence_rule=EvidenceRule(("artifact_observed",), artifact_name="split_manifest.json"),
        ),
        RequiredCheck(
            check_id="predictions_cover_test_rows",
            description="predictions 覆盖全部测试行且无多余行",
            min_level="E2",
            execution_critical=True,
            l3_required=True,
            evidence_rule=EvidenceRule(("artifact_observed",), artifact_name="predictions.csv"),
        ),
        RequiredCheck(
            check_id="metrics_recomputable",
            description="由 predictions + 标签可重算全部指标",
            min_level="E2",
            execution_critical=True,
            l3_required=True,
            evidence_rule=EvidenceRule(("artifact_observed",), artifact_name="metrics.json"),
        ),
        RequiredCheck(
            check_id="no_train_test_overlap",
            description="train/test 行无交集",
            min_level="E2",
            execution_critical=True,
            l3_required=True,
            evidence_rule=EvidenceRule(("executor_process_exit",)),
        ),
        RequiredCheck(
            check_id="leakage_report_present",
            description="泄漏诊断产物存在且字段完整",
            min_level="E2",
            execution_critical=True,
            l3_required=False,
            evidence_rule=EvidenceRule(("artifact_observed",), artifact_name="leakage_report.json"),
        ),
        RequiredCheck(
            check_id="model_params_whitelisted",
            description="模型与超参均来自白名单",
            min_level="E1",
            execution_critical=False,
            l3_required=False,
            evidence_rule=EvidenceRule(("tool_invocation",)),
        ),
        RequiredCheck(
            check_id="seed_recorded",
            description="seed 进入 split manifest 与 run_summary",
            min_level="E1",
            execution_critical=False,
            l3_required=False,
            evidence_rule=EvidenceRule(("tool_invocation", "harness_trace")),
        ),
    )
    return Ruleset(
        schema_version=RULESET_SCHEMA_VERSION,
        ruleset_version="t0-classification@1.0.0",
        required_checks=checks,
        l3_policy=L3Policy(
            required_coverage=1.0,
            metric_source_check_ids=("metrics_recomputable", "predictions_cover_test_rows"),
        ),
        conflict_policy=CONFLICT_POLICY_REJECT_UNRESOLVED,
    ).with_hash(canonicalizer)


# ---------------------------------------------------------------------------
# 6. 静态边界自检
# ---------------------------------------------------------------------------
def assert_ruleset_boundary() -> list[str]:
    """检查本模块没有变成“判定/写入”入口；返回违反项（空 = 通过）。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in ("Gate", "evaluate", "transition", "sign", "issue_report", "write"):
        if hasattr(module, attr):
            problems.append(f"ruleset 暴露禁用名 {attr!r}（判定/写入/签名不属于本文件）")
    if set(RULESET_FIELDS) != {
        "schema_version", "ruleset_version", "required_checks", "l3_policy", "conflict_policy"
    }:
        problems.append("RULESET_FIELDS 被改动")
    if EXECUTION_CRITICAL_MIN_LEVEL != ("E2", "E3"):
        problems.append("执行类必检最低等级必须恰为 E2/E3")
    if LEVEL_RANK["E0"] != 0 or LEVEL_RANK["E3"] != 3:
        problems.append("等级序被改动")
    return problems