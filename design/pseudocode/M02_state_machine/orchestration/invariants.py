"""M02 · orchestration/invariants.py — I-01…I-08 可调用断言（P2 伪代码）。

阶段：P2｜状态：断言函数、调用时机、违反时错误码；**不执行校验、不计算 Gate**。
规范来源：策划书附录 F.2 核心不变量（I-01–I-08）、`docs/design/05_CONTRACTS_AND_STATES.md`
§10（I-01–I-14）、`docs/state/runtime_states.md` §5、`AGENTS.md` §4。

边界：
  - M02 只提供**断言函数**，不实现 Gate/Verifier/签名；I-02/I-04/I-06/I-07/I-08
    由 Gate/Verifier/verify_bundle 在各自入口调用，M02 **不调用**它们。
  - 不新增错误码：违反时抛 `InvariantViolation`，其 `code` 取自 M01 已注册的码。
  - I-05 在 T0 不适用：调用即 `NotApplicableInT0`；T0 不得返回 `RECOVERY_NOT_SAFE`。
  - 每个断言都要求调用方传入**已计算好的事实**（等级集合、覆盖率、payload、信任锚），
    本模块不重新计算 Gate 结果，也不验签。

与 05 §10 的 I-09–I-14 关系：
  - I-09/I-12 由 `transitions.py` 的边和 `state_machine._guard_plan_three` 直接执行；
  - I-10/I-11 由 `evidence_invalidations` 只追加 + Gate stale 判定执行；
  - I-13/I-14 由签名入口与 `StateMachine._deny` 执行；
  - 本文件不重复实现，只在 `I09_I14_ENFORCEMENT` 中登记落点。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

__all__ = [
    "I09_I14_ENFORCEMENT",
    "INVARIANTS",
    "INVARIANTS_BY_ID",
    "CheckClass",
    "InvariantId",
    "InvariantSpec",
    "InvariantViolation",
    "NotApplicableInT0",
    "assert_i01_no_direct_state_write",
    "assert_i01_repository_surface",
    "assert_i02_e01_not_sufficient",
    "assert_i03_workdirs_separated",
    "assert_i04_l3_coverage",
    "assert_i05_dc_before_spa",
    "assert_i06_signature_payload",
    "assert_i07_certificate_requires_verified",
    "assert_i08_external_trust_anchor",
    "assert_invariant_contract",
]


class InvariantId(StrEnum):
    I01 = "I-01"
    I02 = "I-02"
    I03 = "I-03"
    I04 = "I-04"
    I05 = "I-05"
    I06 = "I-06"
    I07 = "I-07"
    I08 = "I-08"


class CheckClass(StrEnum):
    EXECUTION = "EXECUTION"          # 执行类必检项：E0/E1 不得单独满足
    NON_EXECUTION = "NON_EXECUTION"  # 非执行类：等级规则由 Gate 规则集决定


@dataclass(frozen=True, slots=True)
class InvariantSpec:
    invariant_id: InvariantId
    title: str
    when: str
    on_violation_code: str | None
    http_status: int | None
    enforced_by: str
    source: str
    note: str = ""


INVARIANTS: Final[tuple[InvariantSpec, ...]] = (
    InvariantSpec(
        InvariantId.I01,
        "Agent/LLM 不能直接写 Task/Node 状态",
        when="仓储写入口；每次 _apply_transition；发布前静态检查",
        on_violation_code="STATE_TRANSITION_DENIED",
        http_status=409,
        enforced_by="StateMachine + repositories capability + DB 触发器 + 负例",
        source="附录 F.2；AGENTS §4.1；05 §10",
        note="直接 SQL UPDATE 由 trg_tasks_state_requires_audit / "
             "trg_nodes_state_requires_audit 拒绝（STATE_WRITE_WITHOUT_AUDIT）。",
    ),
    InvariantSpec(
        InvariantId.I02,
        "E0/E1 不能单独满足执行类必检项",
        when="Gate 生成覆盖矩阵时；不得在 StateMachine 内调用",
        on_violation_code="REQUIRED_EVIDENCE_MISSING",
        http_status=409,
        enforced_by="Gate（WP-08）调用本断言",
        source="附录 F.2；05 §10；07 WP-08",
        note="只接受已算好的 levels 集合；本模块不重算 Gate。",
    ),
    InvariantSpec(
        InvariantId.I03,
        "Verifier 与 Executor 工作目录分离",
        when="Verifier 启动前 / 每次 L3 重执行前",
        on_violation_code="ENV_FINGERPRINT_MISMATCH",
        http_status=409,
        enforced_by="Verifier 入口（WP-09/WP-11）调用本断言",
        source="附录 F.2；AGENTS §4；04 §4.4",
        note="目录相同或互为祖先即违反；按环境不合格处理，映射到 env 不一致码。",
    ),
    InvariantSpec(
        InvariantId.I04,
        "报告指标来源节点必须达到规定 L3 覆盖",
        when="Verifier 签发报告前；Gate 计算 L3 覆盖时",
        on_violation_code="REQUIRED_EVIDENCE_MISSING",
        http_status=409,
        enforced_by="Gate/Verifier 调用本断言",
        source="附录 F.2；05 §10；07 WP-08/WP-09",
        note="阈值属于规则集；本函数只比较，不定义阈值。",
    ),
    InvariantSpec(
        InvariantId.I05,
        "无有效 DC 的节点不能被 SPA 跳过",
        when="T1/T2 的 SPA 判定；T0 不调用（T0 无 DC/SPA）",
        on_violation_code="RECOVERY_NOT_SAFE",
        http_status=409,
        enforced_by="T1/T2 SPA 检查",
        source="附录 F.2；T2/FR-015；05 §10",
        note="T0 调用即 NotApplicableInT0；T0 不得返回 RECOVERY_NOT_SAFE。",
    ),
    InvariantSpec(
        InvariantId.I06,
        "签名载荷包含规则版本、证据根和状态",
        when="Verifier 签名前；verify_bundle 验签前",
        on_violation_code="SIGNATURE_INVALID",
        http_status=422,
        enforced_by="Signing/Verifier/verify_bundle 调用本断言",
        source="附录 F.2；05 §1.5；I-06/I-13",
        note="payload 必须含 schema_version；未知 MAJOR 的拒绝在验签入口执行。",
    ),
    InvariantSpec(
        InvariantId.I07,
        "非 VERIFIED 报告不产生 CompletionCertificate",
        when="凭证签发入口；任何 cert 插入前",
        on_violation_code="REQUIRED_EVIDENCE_MISSING",
        http_status=409,
        enforced_by="Verifier 签发入口（WP-11）调用本断言",
        source="附录 F.2；05 §9.6；I-07",
        note="PARTIAL/FAILED/BLOCKED 一律不得签发；不得用文字声明替代。",
    ),
    InvariantSpec(
        InvariantId.I08,
        "离线验签使用外部可信指纹，不信任证书自带公钥",
        when="verify_bundle 验签前；签发前自检",
        on_violation_code="TRUST_ANCHOR_MISSING",
        http_status=503,
        enforced_by="verify_bundle.trust_store + Verifier",
        source="附录 F.2；05 §10；I-08；07 G6-T0",
        note="trust_store 为空、指纹不在锚内、只匹配包内指纹，均 fail-closed。",
    ),
)

INVARIANTS_BY_ID: Final[Mapping[InvariantId, InvariantSpec]] = MappingProxyType(
    {spec.invariant_id: spec for spec in INVARIANTS}
)


class InvariantViolation(RuntimeError):
    """不变量被违反；`code` 必须是 M01 已注册的错误码。"""

    def __init__(
        self,
        invariant_id: InvariantId,
        code: str,
        message: str,
        *,
        http_status: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.invariant_id = invariant_id
        self.code = code
        self.http_status = http_status
        self.details = dict(details or {})
        super().__init__(f"{invariant_id.value} 违反：{message}（code={code}）")


class NotApplicableInT0(RuntimeError):
    """T0 调用了仅 T1/T2 适用的不变量（I-05）。"""

    invariant_id = InvariantId.I05
    code = None
    http_status = None

    def __init__(self) -> None:
        super().__init__(
            "I-05（DC/SPA）在 T0 不适用；T0 调用即编程错误，"
            "不得返回 RECOVERY_NOT_SAFE"
        )


# ---------------------------------------------------------------------------
# I-01：唯一写入口 / 仓储无裸 update
# ---------------------------------------------------------------------------
def assert_i01_no_direct_state_write(
    *, writer: str, target: str, via_state_machine: bool
) -> None:
    """在每次状态写入前调用；`writer` 是组件名，`target` 是 task/node。

    违反时抛 `InvariantViolation(I-01, "STATE_TRANSITION_DENIED")`。
    """
    if not via_state_machine:
        raise InvariantViolation(
            InvariantId.I01,
            "STATE_TRANSITION_DENIED",
            f"{writer} 试图直接写 {target} 状态；必须经 StateMachine.transition()",
            http_status=409,
            details={"writer": writer, "target": target},
        )


def assert_i01_repository_surface(repository_cls: type) -> None:
    """静态检查：仓储不得暴露 `update`/`set_state`/`save`/`delete` 等公开方法。"""
    for name in ("update", "update_state", "set_state", "save", "delete", "force_state"):
        if hasattr(repository_cls, name):
            raise InvariantViolation(
                InvariantId.I01,
                "STATE_TRANSITION_DENIED",
                f"{repository_cls.__name__} 暴露了裸写方法 {name}",
                http_status=409,
                details={"repository": repository_cls.__name__, "method": name},
            )


# ---------------------------------------------------------------------------
# I-02：E0/E1 不得单独满足执行类必检项
# ---------------------------------------------------------------------------
def assert_i02_e01_not_sufficient(
    *,
    check_id: str,
    check_class: CheckClass,
    levels: frozenset[str],
) -> None:
    """Gate 在把某必检项判为 PASS 前调用。

    - `check_class=EXECUTION` 且 `levels ⊆ {E0,E1}`（含空集）→
      抛 `REQUIRED_EVIDENCE_MISSING`；
    - 非执行类不在此断言范围（由规则集决定）。
    """
    if check_class is not CheckClass.EXECUTION:
        return
    if levels.issubset({"E0", "E1"}):
        raise InvariantViolation(
            InvariantId.I02,
            "REQUIRED_EVIDENCE_MISSING",
            f"执行类必检项 {check_id} 只有 {sorted(levels)!r}；E0/E1 不能单独满足",
            http_status=409,
            details={"check_id": check_id, "levels": sorted(levels)},
        )


# ---------------------------------------------------------------------------
# I-03：Executor 与 Verifier 工作目录分离
# ---------------------------------------------------------------------------
def _same_or_nested(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def assert_i03_workdirs_separated(*, executor_dir: Path, verifier_dir: Path) -> None:
    """Verifier 启动 / L3 重执行前调用。

    相同目录、互为祖先目录、或解析后相同 → 抛
    `InvariantViolation(I-03, "ENV_FINGERPRINT_MISMATCH")`。
    """
    a = executor_dir.resolve(strict=False)
    b = verifier_dir.resolve(strict=False)
    if _same_or_nested(a, b):
        raise InvariantViolation(
            InvariantId.I03,
            "ENV_FINGERPRINT_MISMATCH",
            "Executor 与 Verifier 工作目录相同或互为祖先；不得复用进程内状态",
            http_status=409,
            details={"executor_dir": str(a), "verifier_dir": str(b)},
        )


# ---------------------------------------------------------------------------
# I-04：L3 覆盖
# ---------------------------------------------------------------------------
def assert_i04_l3_coverage(
    *,
    required_nodes: Sequence[str],
    l3_coverage: Mapping[str, float],
    min_coverage: float,
) -> None:
    """Verifier 签发报告前 / Gate 计算 L3 覆盖时调用。

    任一个 required node 缺覆盖率或 `< min_coverage` →
    抛 `REQUIRED_EVIDENCE_MISSING`（I-04）。阈值由规则集给出，本函数不定义。
    """
    if not 0.0 <= min_coverage <= 1.0:
        raise ValueError(f"min_coverage 必须在 [0,1]：{min_coverage!r}")
    for node_id in required_nodes:
        value = l3_coverage.get(node_id)
        if (
            value is None
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < min_coverage
        ):
            raise InvariantViolation(
                InvariantId.I04,
                "REQUIRED_EVIDENCE_MISSING",
                f"节点 {node_id} 的 L3 覆盖率 {value!r} 低于阈值 {min_coverage}",
                http_status=409,
                details={
                    "node_id": node_id,
                    "coverage": value,
                    "min_coverage": min_coverage,
                },
            )


# ---------------------------------------------------------------------------
# I-05：DC / SPA（T0 不适用）
# ---------------------------------------------------------------------------
def assert_i05_dc_before_spa(
    *, dc_valid: bool, spa_skipped: bool, t0: bool = True
) -> None:
    """T1/T2 的 SPA 判定前调用。

    - `t0=True` 时调用即抛 `NotApplicableInT0`（T0 无 DC/SPA，不得返回 RECOVERY_NOT_SAFE）；
    - `t0=False` 且 `spa_skipped=True` 且 `dc_valid=False` →
      抛 `InvariantViolation(I-05, "RECOVERY_NOT_SAFE")`。
    """
    if t0:
        raise NotApplicableInT0()
    if spa_skipped and not dc_valid:
        raise InvariantViolation(
            InvariantId.I05,
            "RECOVERY_NOT_SAFE",
            "没有有效 DC 却 SPA 跳过节点",
            http_status=409,
            details={"dc_valid": dc_valid, "spa_skipped": spa_skipped},
        )


# ---------------------------------------------------------------------------
# I-06：签名载荷字段
# ---------------------------------------------------------------------------
SIGNATURE_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "schema_version", "ruleset_hash", "evidence_root", "final_state",
)


def assert_i06_signature_payload(
    *,
    payload: Mapping[str, Any],
    required_fields: Sequence[str] = SIGNATURE_REQUIRED_FIELDS,
) -> None:
    """Verifier 签名前 / verify_bundle 验签前调用。

    缺少任一必含字段或值为空 → 抛 `SIGNATURE_INVALID`（I-06）。
    `schema_version` 的未知 MAJOR 拒绝在验签入口另行执行（I-13）。
    """
    missing = [
        field
        for field in required_fields
        if field not in payload or payload[field] in (None, "", [], {})
    ]
    if missing:
        raise InvariantViolation(
            InvariantId.I06,
            "SIGNATURE_INVALID",
            f"签名载荷缺少字段：{missing!r}",
            http_status=422,
            details={"missing": missing},
        )
    if payload.get("schema_version") not in ("1.0",):
        # 05 §1.2：未知 MAJOR 拒绝；1.x 的 MINOR 读取方应兼容。
        major = str(payload.get("schema_version", "")).split(".")[0]
        if major != "1":
            raise InvariantViolation(
                InvariantId.I06,
                "SIGNATURE_INVALID",
                f"未知 schema_version MAJOR：{payload.get('schema_version')!r}",
                http_status=422,
                details={"schema_version": payload.get("schema_version")},
            )


# ---------------------------------------------------------------------------
# I-07：非 VERIFIED 报告不产生证书
# ---------------------------------------------------------------------------
def assert_i07_certificate_requires_verified(
    *, report_final_state: str, certificate_requested: bool
) -> None:
    """凭证签发入口调用；PARTIAL/FAILED/BLOCKED 请求签发即拒绝。

    违反时抛 `InvariantViolation(I-07, "REQUIRED_EVIDENCE_MISSING")`。
    """
    if certificate_requested and report_final_state != "VERIFIED":
        raise InvariantViolation(
            InvariantId.I07,
            "REQUIRED_EVIDENCE_MISSING",
            f"报告 final_state={report_final_state!r}，不得签发 CompletionCertificate",
            http_status=409,
            details={"report_final_state": report_final_state},
        )


# ---------------------------------------------------------------------------
# I-08：外部信任锚
# ---------------------------------------------------------------------------
def assert_i08_external_trust_anchor(
    *,
    key_fingerprint: str,
    trust_store: Mapping[str, str],
    cert_embedded_fingerprint: str | None,
) -> None:
    """verify_bundle 验签前 / 签发前自检调用。

    - trust_store 为空 → `TRUST_ANCHOR_MISSING`；
    - key_fingerprint 不在 trust_store → `TRUST_ANCHOR_MISSING`；
    - 只匹配证书自带指纹（不在外部锚）→ `TRUST_ANCHOR_MISSING`。
    """
    if not trust_store:
        raise InvariantViolation(
            InvariantId.I08,
            "TRUST_ANCHOR_MISSING",
            "缺少包外 trust store；不得回退到证书自带公钥",
            http_status=503,
        )
    if key_fingerprint not in trust_store:
        raise InvariantViolation(
            InvariantId.I08,
            "TRUST_ANCHOR_MISSING",
            "key_fingerprint 不在外部 trust store 中",
            http_status=503,
            details={
                "key_fingerprint": key_fingerprint,
                "embedded_only": key_fingerprint == cert_embedded_fingerprint,
            },
        )


# ---------------------------------------------------------------------------
# I-09–I-14 的执行落点（不重复实现）
# ---------------------------------------------------------------------------
I09_I14_ENFORCEMENT: Final[Mapping[str, str]] = MappingProxyType(
    {
        "I-09": "transitions.NODE_TRANSITIONS：VERIFIED 唯一出边 INVALIDATED；"
                "INVALIDATED 唯一出边 READY",
        "I-10": "evidence_invalidations 只追加 + Gate 按 evidence_id 拒绝 stale；"
                "任何路径不得删除 evidence",
        "I-11": "失效只写 evidence_invalidations + audit_log；不占 E0–E3；"
                "StateMachine 不写 evidence 表",
        "I-12": "state_machine._guard_plan_three：文件存在/哈希一致/先冻结后重跑",
        "I-13": "assert_i06_signature_payload + verify_bundle 拒绝未知 MAJOR",
        "I-14": "state_machine._deny：状态回滚后独立事务写 DENIED；"
                "二次失败写 stderr(audit_write_failed=true)",
    }
)


# ---------------------------------------------------------------------------
# 自检（实现阶段调用；P2 只定义）
# ---------------------------------------------------------------------------
def assert_invariant_contract() -> list[str]:
    problems: list[str] = []
    expected = [f"I-{i:02d}" for i in range(1, 9)]
    actual = [spec.invariant_id.value for spec in INVARIANTS]
    if actual != expected:
        problems.append(f"不变量必须恰好 I-01…I-08：{actual!r}")
    if len(set(actual)) != len(actual):
        problems.append("不变量编号重复")
    for spec in INVARIANTS:
        if not spec.when or not spec.enforced_by:
            problems.append(f"{spec.invariant_id} 缺少 when/enforced_by")
        if spec.invariant_id is InvariantId.I05:
            if spec.on_violation_code != "RECOVERY_NOT_SAFE":
                problems.append("I-05 的 T1 违反码应为 RECOVERY_NOT_SAFE")
        elif not spec.on_violation_code:
            problems.append(f"{spec.invariant_id} 缺少违反码")
    if set(I09_I14_ENFORCEMENT) != {f"I-{i:02d}" for i in range(9, 15)}:
        problems.append("I-09–I-14 落点必须登记完整")
    return problems