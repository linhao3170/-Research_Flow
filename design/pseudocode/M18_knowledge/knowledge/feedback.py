"""MODULE：M18 · knowledge/feedback.py — FOL 三层环 L-A/L-B/L-C、方向约束与 R1–R3 对照（P8 伪代码）。
阶段+追踪：P8「六角色与知识库」｜FR-014（FOL 三层反馈环；T1，G5）｜策划书 §11.4、§11.5 TABLE 44、§11.6
FR+依赖：FR-014；依赖 unit.py（FAULT_CASE）、M07 证据引用（只读）、M14 恢复结果（只读）
不变量+错误码：数据只向上（失败→案例→策略评估），参数只向下（批准策略→阈值→执行）；
              Agent 不得写知识；未批准策略不得下发；R1/R2/R3 组合固定；负面结果必须保留。
              TOOL_NOT_ALLOWLISTED(403) / STATE_TRANSITION_DENIED(409) / SCHEMA_INVALID(422)
写入者：无。反馈只产出“记录/候选/版本”，写入由 KnowledgeStore / PolicyStore（未在本模块实现）承担。
状态：伪代码；不跑网格、不更新真实阈值、不做强化学习。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

from .unit import FaultCasePayload

__all__ = [
    "TARGET_IMPROVEMENT_PP",
    "Arm",
    "ArmDelta",
    "ArmMetrics",
    "ClaimNotAllowed",
    "DirectionViolation",
    "DownwardParameter",
    "FaultCaseCandidate",
    "FeedbackBus",
    "HumanApproval",
    "KnowledgeLoop",
    "KnowledgeWritePort",
    "KnowledgeWriteRequest",
    "LoopId",
    "LoopToggles",
    "PolicyCandidate",
    "PolicyLoop",
    "PolicyVersion",
    "Rate",
    "RunRecord",
    "UpwardRecord",
    "assert_arm_matrix",
    "assert_direction_only",
    "assert_negative_results_kept",
    "assert_no_rl",
    "assert_target_only_after_measurement",
    "compare_arms",
    "evaluate_arm",
    "toggles_for",
]

# 策划书 §11.6：R3 相对 R1 首轮通过率 +15pp 是“目标值”，只有实测后才能形成结论。
TARGET_IMPROVEMENT_PP: Final[float] = 15.0

TARGET_CLAIM_NOTE: Final[str] = (
    "R3 相对 R1 首轮通过率 +15pp 是预先声明的目标值，不是已达成结果；"
    "未实测、未预注册、样本不足时不得把它写成结论。"
)


class DirectionViolation(RuntimeError):
    """反馈方向违规（数据向下、参数向上、未批准下发）。"""

    def __init__(self, reason: str, detail: str) -> None:
        self.error_code = "STATE_TRANSITION_DENIED"
        self.reason = reason
        self.detail = detail
        super().__init__(f"[STATE_TRANSITION_DENIED] {reason}（{detail}）")


class KnowledgeWriteForbidden(RuntimeError):
    """Agent/模型写知识；`created_by` 不是人类即拒绝。"""

    def __init__(self, detail: str) -> None:
        self.error_code = "TOOL_NOT_ALLOWLISTED"
        self.reason = "KNOWLEDGE_WRITE_BY_AGENT_FORBIDDEN"
        self.detail = detail
        super().__init__(f"[TOOL_NOT_ALLOWLISTED] {self.reason}（{detail}）")


class ClaimNotAllowed(RuntimeError):
    """未满足实测/预注册条件就宣称收益。"""

    def __init__(self, reason: str, detail: str) -> None:
        self.error_code = "STATE_TRANSITION_DENIED"
        self.reason = reason
        self.detail = detail
        super().__init__(f"[STATE_TRANSITION_DENIED] {reason}（{detail}）")


class LoopId(StrEnum):
    """§11.5 的三层环。**恰好三个**。"""

    L_A_EXECUTION = "L_A_EXECUTION"   # 秒—分钟：失败/缺口 → 分类、有限重试、定向恢复
    L_B_KNOWLEDGE = "L_B_KNOWLEDGE"   # 分钟—天：人工确认故障案例入库，下次注入
    L_C_POLICY = "L_C_POLICY"         # 周/批次：离线网格/回放，人工批准策略版本


class Arm(StrEnum):
    """§11.6 的三个实验臂：R1 仅执行环；R2 +知识环；R3 +策略环。"""

    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


@dataclass(frozen=True, slots=True)
class LoopToggles:
    """三个环的开关。R 臂组合必须精确匹配，不接受“近似”组合。"""

    l_a: bool
    l_b: bool
    l_c: bool

    def __post_init__(self) -> None:
        if not self.l_a:
            raise DirectionViolation("ARM_WITHOUT_EXECUTION_LOOP", "L-A 是基线，不得关闭")
        if self.l_c and not self.l_b:
            raise DirectionViolation("ARM_POLICY_WITHOUT_KNOWLEDGE", "L-C 依赖 L-B 的案例输入")

    def as_tuple(self) -> tuple[bool, bool, bool]:
        return (self.l_a, self.l_b, self.l_c)


ARM_TOGGLES: Final[Mapping[Arm, LoopToggles]] = MappingProxyType(
    {
        Arm.R1: LoopToggles(True, False, False),
        Arm.R2: LoopToggles(True, True, False),
        Arm.R3: LoopToggles(True, True, True),
    }
)


def toggles_for(arm: Arm) -> LoopToggles:
    """取实验臂的开关组合；未知臂直接拒绝。"""
    if arm not in ARM_TOGGLES:
        raise DirectionViolation("UNKNOWN_ARM", arm.value)
    return ARM_TOGGLES[arm]


def assert_arm_matrix() -> tuple[str, ...]:
    """R1 ⊂ R2 ⊂ R3，且 L-A 恒开（关掉执行环就不是同一实验）。"""
    problems: list[str] = []
    if set(ARM_TOGGLES) != set(Arm):
        problems.append("实验臂未覆盖 R1–R3")
    if not all(toggles.l_a for toggles in ARM_TOGGLES.values()):
        problems.append("L-A 必须在三个臂中都开启")
    if not (ARM_TOGGLES[Arm.R2].l_b and not ARM_TOGGLES[Arm.R2].l_c):
        problems.append("R2 必须只增加 L-B")
    if not (ARM_TOGGLES[Arm.R3].l_b and ARM_TOGGLES[Arm.R3].l_c):
        problems.append("R3 必须同时有 L-B/L-C")
    return tuple(problems)


# ---------------------------------------------------------------------------
# 1. 向上数据 / 向下参数
# ---------------------------------------------------------------------------
class UpwardKind(StrEnum):
    FAILURE_EVENT = "FAILURE_EVENT"
    GAP_RECORD = "GAP_RECORD"
    FAULT_CASE_CANDIDATE = "FAULT_CASE_CANDIDATE"
    RUN_METRIC = "RUN_METRIC"


@dataclass(frozen=True, slots=True)
class UpwardRecord:
    """向上流动的数据。只有 L-A/L-B 能发；L-C 只消费。"""

    loop: LoopId
    kind: UpwardKind
    evidence_ids: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        if self.loop is LoopId.L_C:
            raise DirectionViolation("UPWARD_FROM_POLICY_LOOP", "L-C 只消费数据，不产出数据")
        if self.kind is UpwardKind.FAULT_CASE_CANDIDATE and not self.evidence_ids:
            raise DirectionViolation("CANDIDATE_WITHOUT_EVIDENCE", "故障案例候选必须带失败证据")
        if not self.summary.strip():
            raise DirectionViolation("UPWARD_SUMMARY_EMPTY", self.loop.value)


@dataclass(frozen=True, slots=True)
class DownwardParameter:
    """向下流动的参数。只有 L-C 的已批准策略能发。"""

    name: str
    value: float | int | bool | str
    policy_version_hash: str
    approved_by: str
    replay_evidence_id: str
    applies_to: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.applies_to.strip():
            raise DirectionViolation("PARAMETER_FIELD_EMPTY", self.name)
        if len(self.policy_version_hash) != 64:
            raise DirectionViolation("POLICY_HASH_INVALID", self.policy_version_hash)
        if not self.approved_by.strip() or not self.replay_evidence_id.strip():
            raise DirectionViolation("POLICY_NOT_APPROVED", "参数必须绑定人工批准与回放证据")


class FeedbackBus:
    """方向校验的唯一入口。三个拒绝分支：

      1. 向上通道收到 L-C → 拒绝；
      2. 向下通道未登记批准版本 → 拒绝；
      3. 向下参数缺 approved_by/replay_evidence_id → 拒绝（构造期已挡）。
    """

    def __init__(self) -> None:
        self._upward: list[UpwardRecord] = []
        self._downward: list[DownwardParameter] = []
        self._approved: set[str] = set()

    def register_approved_version(self, policy_version_hash: str) -> None:
        """登记一个已批准策略版本；只有它能下发参数。"""
        if len(policy_version_hash) != 64:
            raise DirectionViolation("POLICY_HASH_INVALID", policy_version_hash)
        self._approved.add(policy_version_hash)

    def publish_upward(self, record: UpwardRecord) -> None:
        if record.loop is LoopId.L_C:
            raise DirectionViolation("UPWARD_FROM_POLICY_LOOP", "L-C 不产出数据")
        self._upward.append(record)

    def publish_downward(self, parameter: DownwardParameter) -> None:
        if parameter.policy_version_hash not in self._approved:
            raise DirectionViolation("POLICY_VERSION_NOT_APPROVED", parameter.policy_version_hash)
        self._downward.append(parameter)

    def upward(self) -> tuple[UpwardRecord, ...]:
        return tuple(self._upward)

    def downward(self) -> tuple[DownwardParameter, ...]:
        return tuple(self._downward)


# ---------------------------------------------------------------------------
# 2. L-B：知识环（人工确认才入库）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class HumanApproval:
    """人工批准。Agent/模型不得自批。"""

    approved_by: str
    approval_id: str
    at: str

    def __post_init__(self) -> None:
        if not self.approved_by.strip() or not self.approval_id.strip():
            raise DirectionViolation("HUMAN_APPROVAL_REQUIRED", "approved_by/approval_id 不得为空")
        if self.approved_by.strip().lower() in {"agent", "model", "llm", "assistant"}:
            raise KnowledgeWriteForbidden(f"approver={self.approved_by}")


@dataclass(frozen=True, slots=True)
class FaultCaseCandidate:
    """从失败中提取的候选案例；`created_by` 必须是人类/导入器。"""

    scope: str
    payload: FaultCasePayload
    source_url: str
    license: str
    effective_at: str
    expires_at: str
    evidence_ids: tuple[str, ...]
    created_by: str

    def __post_init__(self) -> None:
        if self.created_by.strip().lower() in {
            "planner", "data", "experiment", "analysis", "recovery", "verification",
        } or self.created_by.lower().startswith("agent:"):
            raise KnowledgeWriteForbidden(f"created_by={self.created_by}")
        if not self.evidence_ids:
            raise DirectionViolation("CANDIDATE_WITHOUT_EVIDENCE", self.scope)


@dataclass(frozen=True, slots=True)
class KnowledgeWriteRequest:
    """交给 KnowledgeStore 的追加请求；`supersedes` 指向旧内容哈希。"""

    scope: str
    payload: FaultCasePayload
    source_url: str
    license: str
    effective_at: str
    expires_at: str
    evidence_ids: tuple[str, ...]
    created_by: str
    reviewed_by: str
    approval_id: str
    supersedes: str | None


class KnowledgeWritePort(Protocol):
    """知识写入端口。实现方必须再次校验人工批准；本模块不落库。"""

    def append(self, request: KnowledgeWriteRequest) -> str: ...


class KnowledgeLoop:
    """L-B：分钟—天。候选案例 → 人工确认 → 新版本入库（只增不改）。"""

    loop = LoopId.L_B_KNOWLEDGE

    def submit_candidate(
        self,
        *,
        candidate: FaultCaseCandidate,
        approval: HumanApproval,
        supersedes: str | None = None,
    ) -> KnowledgeWriteRequest:
        """构造写入请求；未批准、无证据、Agent 来源一律拒绝。"""
        if not approval.approved_by.strip():
            raise KnowledgeWriteForbidden("missing approver")
        if supersedes is not None and len(supersedes) != 64:
            raise DirectionViolation("SUPERSEDES_INVALID", supersedes)
        return KnowledgeWriteRequest(
            scope=candidate.scope,
            payload=candidate.payload,
            source_url=candidate.source_url,
            license=candidate.license,
            effective_at=candidate.effective_at,
            expires_at=candidate.expires_at,
            evidence_ids=candidate.evidence_ids,
            created_by=candidate.created_by,
            reviewed_by=approval.approved_by,
            approval_id=approval.approval_id,
            supersedes=supersedes,
        )

    def publish(self, *, request: KnowledgeWriteRequest, store: KnowledgeWritePort) -> str:
        """写入知识库；store 负责幂等与版本追加。"""
        if not request.reviewed_by.strip() or not request.approval_id.strip():
            raise KnowledgeWriteForbidden("request not reviewed")
        return store.append(request)


# ---------------------------------------------------------------------------
# 3. L-C：策略环（离线网格 + 人工批准 + 可回滚）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Rate:
    """比例（分子/分母/值）。分母为 0 时值 None。"""

    numerator: int
    denominator: int
    value: float | None

    def __post_init__(self) -> None:
        if self.numerator < 0 or self.denominator < 0 or self.numerator > max(self.denominator, 0):
            raise DirectionViolation("RATE_COUNT_INVALID", f"{self.numerator}/{self.denominator}")
        expected = None if self.denominator == 0 else self.numerator / self.denominator
        if expected is None and self.value is not None:
            raise DirectionViolation("RATE_VALUE_INVALID", "分母为 0")
        if expected is not None and (self.value is None or abs(expected - self.value) > 1e-12):
            raise DirectionViolation("RATE_VALUE_INVALID", f"{self.value}!={expected}")

    def as_dict(self) -> dict[str, object]:
        return {"numerator": self.numerator, "denominator": self.denominator, "value": self.value}


@dataclass(frozen=True, slots=True)
class RunRecord:
    """一次运行的结果摘要（用于 R1–R3 对照）。不含模型自述。"""

    task_id: str
    first_pass: bool
    attempts: int
    same_error: bool
    tokens: int
    recovery_time_sec: float
    protocol_violations: int

    def __post_init__(self) -> None:
        if not self.task_id.startswith("task_"):
            raise DirectionViolation("RUN_TASK_ID_INVALID", self.task_id)
        if self.attempts < 1 or self.tokens < 0 or self.recovery_time_sec < 0 or self.protocol_violations < 0:
            raise DirectionViolation("RUN_COUNT_INVALID", self.task_id)
        if not isinstance(self.first_pass, bool) or not isinstance(self.same_error, bool):
            raise DirectionViolation("RUN_FLAG_INVALID", self.task_id)


@dataclass(frozen=True, slots=True)
class ArmMetrics:
    """一个实验臂的指标。`sample_size` 必须显式，重复运行不算独立样本。"""

    arm: Arm
    first_pass_rate: Rate
    mean_attempts: float
    same_error_rate: Rate
    token_cost: int
    recovery_time_sec: float
    protocol_violations: int
    sample_size: int

    def __post_init__(self) -> None:
        if self.sample_size < 0:
            raise DirectionViolation("ARM_SAMPLE_NEGATIVE", self.arm.value)
        if self.first_pass_rate.denominator != self.sample_size and self.sample_size:
            raise DirectionViolation("ARM_DENOMINATOR_MISMATCH", self.arm.value)
        if self.same_error_rate.denominator != self.sample_size and self.sample_size:
            raise DirectionViolation("ARM_DENOMINATOR_MISMATCH", self.arm.value)

    def as_dict(self) -> dict[str, object]:
        return {
            "arm": self.arm.value,
            "first_pass_rate": self.first_pass_rate.as_dict(),
            "mean_attempts": self.mean_attempts,
            "same_error_rate": self.same_error_rate.as_dict(),
            "token_cost": self.token_cost,
            "recovery_time_sec": self.recovery_time_sec,
            "protocol_violations": self.protocol_violations,
            "sample_size": self.sample_size,
        }


def evaluate_arm(arm: Arm, records: Sequence[RunRecord]) -> ArmMetrics:
    """从原始运行记录计算一个臂的指标；记录为空时比例值必须为 None。"""
    if not records:
        empty = Rate(0, 0, None)
        return ArmMetrics(arm, empty, 0.0, empty, 0, 0.0, 0, 0)
    size = len(records)
    first_pass = sum(1 for record in records if record.first_pass)
    same_error = sum(1 for record in records if record.same_error)
    return ArmMetrics(
        arm=arm,
        first_pass_rate=Rate(first_pass, size, first_pass / size),
        mean_attempts=sum(record.attempts for record in records) / size,
        same_error_rate=Rate(same_error, size, same_error / size),
        token_cost=sum(record.tokens for record in records),
        recovery_time_sec=sum(record.recovery_time_sec for record in records) / size,
        protocol_violations=sum(record.protocol_violations for record in records),
        sample_size=size,
    )


@dataclass(frozen=True, slots=True)
class ArmDelta:
    """两个臂的差值。`negative` 标记“新臂更差”的结果，必须保留上报。"""

    base: Arm
    other: Arm
    first_pass_delta_pp: float | None
    mean_attempts_delta: float
    same_error_delta_pp: float | None
    token_delta: int
    recovery_time_delta: float
    protocol_violation_delta: int
    negative: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "base": self.base.value,
            "other": self.other.value,
            "first_pass_delta_pp": self.first_pass_delta_pp,
            "mean_attempts_delta": self.mean_attempts_delta,
            "same_error_delta_pp": self.same_error_delta_pp,
            "token_delta": self.token_delta,
            "recovery_time_delta": self.recovery_time_delta,
            "protocol_violation_delta": self.protocol_violation_delta,
            "negative": self.negative,
        }


def compare_arms(base: ArmMetrics, other: ArmMetrics) -> ArmDelta:
    """比较两个臂；first-pass 改善为正即为正向，但 `negative` 会标出综合退化。"""
    first = None
    if base.first_pass_rate.value is not None and other.first_pass_rate.value is not None:
        first = (other.first_pass_rate.value - base.first_pass_rate.value) * 100.0
    same = None
    if base.same_error_rate.value is not None and other.same_error_rate.value is not None:
        same = (other.same_error_rate.value - base.same_error_rate.value) * 100.0
    negative = (first is not None and first < 0) or other.mean_attempts > base.mean_attempts
    return ArmDelta(
        base=base.arm,
        other=other.arm,
        first_pass_delta_pp=first,
        mean_attempts_delta=other.mean_attempts - base.mean_attempts,
        same_error_delta_pp=same,
        token_delta=other.token_cost - base.token_cost,
        recovery_time_delta=other.recovery_time_sec - base.recovery_time_sec,
        protocol_violation_delta=other.protocol_violations - base.protocol_violations,
        negative=negative,
    )


@dataclass(frozen=True, slots=True)
class PolicyCandidate:
    """离线网格搜索的候选。`measured` 必须为 True 才允许讨论收益。"""

    parameters: Mapping[str, float]
    policy_hash: str
    replay_metrics: Mapping[str, float]
    evaluation_plan_hash: str
    measured: bool
    negative_results: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.parameters:
            raise DirectionViolation("POLICY_PARAMS_EMPTY", self.policy_hash)
        if len(self.policy_hash) != 64 or len(self.evaluation_plan_hash) != 64:
            raise DirectionViolation("POLICY_HASH_INVALID", self.policy_hash)
        if not self.negative_results:
            raise ClaimNotAllowed("NEGATIVE_RESULTS_HIDDEN", "必须保留并上报负面结果（FR-014）")


@dataclass(frozen=True, slots=True)
class PolicyVersion:
    """一个已批准、可回放的策略版本。`approval_id` 是下发时的核对凭据。"""

    policy_hash: str
    candidate_hash: str
    approved_by: str
    approved_at: str
    approval_id: str
    replay_evidence_id: str
    rollback_to: str | None
    parameters: Mapping[str, float]

    def __post_init__(self) -> None:
        if len(self.policy_hash) != 64 or len(self.candidate_hash) != 64:
            raise DirectionViolation("POLICY_HASH_INVALID", self.policy_hash)
        if not self.approved_by.strip() or not self.approved_at.strip() or not self.replay_evidence_id.strip():
            raise DirectionViolation("POLICY_NOT_APPROVED", self.policy_hash)
        if not self.approval_id.strip():
            raise DirectionViolation("POLICY_NOT_APPROVED", "缺少 approval_id")
        if self.rollback_to is not None and len(self.rollback_to) != 64:
            raise DirectionViolation("ROLLBACK_HASH_INVALID", self.rollback_to)


class PolicyLoop:
    """L-C：周/批次。离线网格 → 候选 → 人工批准 → 版本化参数 → 可回滚。"""

    loop = LoopId.L_C_POLICY

    def evaluate(
        self,
        *,
        history: Sequence[RunRecord],
        grid: Mapping[str, Sequence[float]],
        evaluation_plan_hash: str,
        negative_results: Sequence[str],
    ) -> PolicyCandidate:
        """在历史回放上做确定性网格搜索；不更新任何线上参数。"""
        if not history:
            raise DirectionViolation("POLICY_HISTORY_EMPTY", "没有历史回放就没有策略环")
        if len(evaluation_plan_hash) != 64:
            raise DirectionViolation("EVALUATION_PLAN_NOT_FROZEN", evaluation_plan_hash)
        if not grid:
            raise DirectionViolation("GRID_EMPTY", "网格为空")
        if not negative_results:
            raise ClaimNotAllowed("NEGATIVE_RESULTS_HIDDEN", "候选必须携带负面结果")

        best: tuple[tuple[float, float, float, tuple[tuple[str, float], ...]], Mapping[str, float]] | None = None
        for params in self._iter_grid(grid):
            score = self._score(history, params)
            key = (score, tuple(sorted(params.items())))
            if best is None or key > best[0]:
                best = (key, params)
        if best is None:
            raise DirectionViolation("GRID_EMPTY", "网格没有组合")
        parameters = best[1]
        policy_hash = hashlib.sha256(  # LIB: hashlib.sha256
            json.dumps(
                {"params": dict(sorted(parameters.items())), "plan": evaluation_plan_hash},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return PolicyCandidate(
            parameters=MappingProxyType(dict(sorted(parameters.items()))),
            policy_hash=policy_hash,
            replay_metrics={"objective": best[0][0]},
            evaluation_plan_hash=evaluation_plan_hash,
            measured=True,
            negative_results=tuple(negative_results),
        )

    def approve(self, candidate: PolicyCandidate, *, approval: HumanApproval, replay_evidence_id: str) -> PolicyVersion:
        """人工批准候选；未实测/未批准/无回放证据一律拒绝。"""
        if not candidate.measured:
            raise ClaimNotAllowed("POLICY_NOT_MEASURED", candidate.policy_hash)
        if not replay_evidence_id.strip():
            raise DirectionViolation("POLICY_NOT_APPROVED", "缺少回放证据")
        return PolicyVersion(
            policy_hash=candidate.policy_hash,
            candidate_hash=candidate.policy_hash,
            approved_by=approval.approved_by,
            approved_at=approval.at,
            approval_id=approval.approval_id,
            replay_evidence_id=replay_evidence_id,
            rollback_to=None,
            parameters=candidate.parameters,
        )

    def rollback(self, *, target: PolicyVersion, current: PolicyVersion, approval: HumanApproval,
                 replay_evidence_id: str) -> PolicyVersion:
        """回滚 = 新建一个指向旧版本的版本；不得删除历史版本。"""
        if target.policy_hash == current.policy_hash:
            raise DirectionViolation("ROLLBACK_TO_SELF", target.policy_hash)
        return PolicyVersion(
            policy_hash=hashlib.sha256(  # LIB: hashlib.sha256
                (current.policy_hash + "\x1f" + target.policy_hash).encode("utf-8")
            ).hexdigest(),
            candidate_hash=target.policy_hash,
            approved_by=approval.approved_by,
            approved_at=approval.at,
            approval_id=approval.approval_id,
            replay_evidence_id=replay_evidence_id,
            rollback_to=target.policy_hash,
            parameters=target.parameters,
        )

    def publish(
        self, version: PolicyVersion, *, bus: FeedbackBus, applies_to: str, approval: HumanApproval
    ) -> None:
        """把已批准版本登记并下发参数；未批准/凭据不符一律拒绝。"""
        if version.approval_id != approval.approval_id:
            raise DirectionViolation("POLICY_NOT_APPROVED", "approval_id 与版本不一致")
        bus.register_approved_version(version.policy_hash)
        for name, value in sorted(version.parameters.items()):
            bus.publish_downward(
                DownwardParameter(
                    name=name,
                    value=value,
                    policy_version_hash=version.policy_hash,
                    approved_by=version.approved_by,
                    replay_evidence_id=version.replay_evidence_id,
                    applies_to=applies_to,
                )
            )

    # -- 内部 -------------------------------------------------------------
    @staticmethod
    def _iter_grid(grid: Mapping[str, Sequence[float]]) -> tuple[Mapping[str, float], ...]:
        """笛卡尔积；按参数名排序，保证可复现。"""
        names = sorted(grid)
        combos: list[dict[str, float]] = [{}]
        for name in names:
            values = grid[name]
            if not values:
                raise DirectionViolation("GRID_AXIS_EMPTY", name)
            combos = [{**combo, name: float(value)} for combo in combos for value in values]
        if len(combos) > 10_000:
            raise DirectionViolation("GRID_TOO_LARGE", str(len(combos)))
        return tuple(combos)

    @staticmethod
    def _score(history: Sequence[RunRecord], params: Mapping[str, float]) -> float:
        """回放目标：首轮通过率高、尝试次数少、token 少（全部来自历史记录）。"""
        size = len(history)
        first = sum(1 for record in history if record.first_pass) / size
        attempts = sum(record.attempts for record in history) / size
        tokens = sum(record.tokens for record in history) / size
        # 参数通过“最大尝试次数”影响有效尝试次数；这里只做确定性的惩罚项，不模拟真实执行。
        max_attempts = float(params.get("max_attempts", attempts))
        penalty = max(0.0, attempts - max_attempts)
        return round(first * 1000.0 - attempts * 10.0 - tokens / 1000.0 - penalty * 100.0, 6)


# ---------------------------------------------------------------------------
# 4. 静态守卫
# ---------------------------------------------------------------------------
def assert_direction_only() -> tuple[str, ...]:
    """数据只向上、参数只向下；未批准策略不得下发。"""
    problems: list[str] = []
    try:
        UpwardRecord(loop=LoopId.L_C, kind=UpwardKind.RUN_METRIC, evidence_ids=(), summary="x")
    except DirectionViolation:
        pass
    else:
        problems.append("L-C 被允许发向上数据")
    bus = FeedbackBus()
    unapproved = DownwardParameter(
        name="max_attempts", value=3, policy_version_hash="0" * 64,
        approved_by="human", replay_evidence_id="ev_x", applies_to="recovery",
    )
    try:
        bus.publish_downward(unapproved)
    except DirectionViolation:
        pass
    else:
        problems.append("未登记批准版本的向下参数未被拒绝")
    try:
        bus.publish_upward(UpwardRecord(loop=LoopId.L_B_KNOWLEDGE, kind=UpwardKind.RUN_METRIC,
                                        evidence_ids=(), summary="ok"))
    except DirectionViolation:
        problems.append("合法的向上数据被误拒")
    return tuple(problems)


def assert_negative_results_kept() -> tuple[str, ...]:
    """负面结果不得被隐藏：候选与比较都带 negative 标记。"""
    problems: list[str] = []
    try:
        PolicyCandidate(
            parameters={"max_attempts": 3.0}, policy_hash="0" * 64,
            replay_metrics={}, evaluation_plan_hash="0" * 64, measured=True, negative_results=(),
        )
    except ClaimNotAllowed:
        pass
    else:
        problems.append("空负面结果的候选被放行")
    if "negative" not in getattr(ArmDelta, "__dataclass_fields__", {}):
        problems.append("ArmDelta 缺少 negative 标记")
    return tuple(problems)


def assert_target_only_after_measurement() -> tuple[str, ...]:
    """+15pp 只能作为目标；实测前不得声称达成。"""
    problems: list[str] = []
    if TARGET_IMPROVEMENT_PP != 15.0:
        problems.append("目标值被改写")
    if "只有实测" not in TARGET_CLAIM_NOTE:
        problems.append("缺少“实测后才能形成结论”的声明")
    unmeasured = PolicyCandidate(
        parameters={"max_attempts": 3.0}, policy_hash="0" * 64,
        replay_metrics={}, evaluation_plan_hash="0" * 64, measured=False, negative_results=("x",),
    )
    try:
        PolicyLoop().approve(
            unmeasured,
            approval=HumanApproval(approved_by="human", approval_id="apr", at="2026-11-11T00:00:00Z"),
            replay_evidence_id="ev_x",
        )
    except ClaimNotAllowed:
        pass
    else:
        problems.append("未实测候选被批准")
    return tuple(problems)


def assert_no_rl() -> tuple[str, ...]:
    """首期不引入强化学习；本模块没有 RL 训练入口。"""
    problems: list[str] = []
    for name in __all__:
        if any(token in name.lower() for token in ("gradient", "reward", "qlearning", "ppo", "train")):
            problems.append(f"导出了 RL 相关符号 {name}")
    return tuple(problems)