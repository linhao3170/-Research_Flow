"""MODULE: M10 · verifier/l3_replay.py — L3 独立重放与等价性判定（P5 伪代码）
阶段/追踪: P5「门控与三级验证」｜FR-007、策划书 §9.3/§9.4、05 §13
FR/依赖: FR-007；依赖 M10 l3_sandbox（新目录/白名单/独立进程）、M10 attribution（六类归因）、
        M09 metric_recompute（指标 bit-exact/比较）、M06 Split Manifest、M08 ruleset（L3 阈值）
不变量/错误码: L3 必须真重训/重推：新进程、新目录、只读白名单、无原运行产物输入；
             只重算指标或只重读 predictions 不算 L3；原目录重跑不算 L3；
             确定性模式 bit-exact；随机性模式 ≥5 个预注册种子 + TOST + 边界哈希预冻结。
             错误码：REQUIRED_EVIDENCE_MISSING（409，L3 未执行/覆盖不足/种子不足）、
             SCHEMA_INVALID（422，计划/输入非法）、BUNDLE_TAMPERED（422，哈希不符）、
             TOOL_NOT_ALLOWLISTED（403，沙箱读取/进程隔离拒绝）
写入者: **无**；L3 只产生内存结果与沙箱产物，E3 由 Verifier 写入（OQ-P4-01）
状态: 伪代码；进程启动/训练属 WP-08，本文件定义流程、判定与拒绝点

## 重放流程（9.3 逐条）

  1. Verifier 创建新临时目录、记录目录与进程标识；
  2. 只读白名单：原始数据、代码快照、配置快照、依赖锁、Split Manifest、规则集、任务/图；
     **禁止**读取原运行 metrics/predictions/model/结果目录；
  3. 校验 Split Manifest 六字段（dataset_hash / split / seed / row_id_hash /
     fold_assignment_hash / semantics）；
  4. 在独立进程真实重跑训练/推理；只重算指标或重读 predictions 不算 L3；
  5. 比较预测、指标、产物；按环境/数据/代码/随机性/规则/未知六类归因；
  6. 确定性模式 bit-exact；随机性模式 ≥5 个预注册种子 + TOST + 边界哈希预冻结。

## 为什么“比较”不在沙箱进程里做

  沙箱进程只能读白名单输入，**不能**读原运行 predictions/metrics；否则它可以把原预测
  复制出来冒充重跑。比较发生在 Verifier 进程（持有 evidence 的只读视图），
  沙箱进程只负责“从原始数据重新算”；两者用输出目录交接。

## 等价性（9.4 写死）

  - 确定性模式：预测（含 scores）逐 float64 位相同；指标逐 float64 位相同；
    Split Manifest 哈希相同；确定性产物哈希相同；k=1。
  - 随机性模式：`EquivalencePlan.seeds` 必须是 ≥5 个**预注册**整数；对每个指标做
    TOST（90% CI 落在 ±margin 内）；`plan_hash` 必须在首次重跑前冻结；
    报告每种子值、均值、标准差与 CI；不接受“跑 2 次看起来差不多”。

## 伪 L3 的判定点（必须拒绝）

  | 伪 L3 | 判定点 |
  |---|---|
  | 只重算指标 | `SandboxRunOutput.metrics_only=True` / 无新 predictions / 无模型 fit |
  | 只重读 predictions | 沙箱输入允许清单不含 predictions；audit 出现原产物读取 |
  | 原目录重跑 | `ProcessIdentity.cwd` 在原 attempt 目录内，或 sandbox_root 与原目录重叠 |
  | 复用 Executor 进程 | `pid == executor_pid` 或 `parent_pid == executor_pid` |
  | 没有新进程 | `process_count == 0` / `predictions_source != "sandbox_run"` |
  | 复制原预测 | 无 model_fit/infer 计数；输出 predictions 哈希等于原值且无执行证据 |
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

from .attribution import (
    AttributionInput,
    AttributionReport,
    Cause,
    FactorCheck,
    RandomnessCheck,
    attribute,
)
from .l3_sandbox import (
    READONLY_ALLOWLIST,
    ProcessIdentity,
    ProcessSpec,
    SandboxPlan,
    SandboxPolicy,
    build_process_spec,
    plan_sandbox,
)
from .metric_recompute import (
    METRIC_NAMES,
    MetricSet,
    PredictionRow,
    bit_identical,
)
from .leakage_rules import (
    DatasetTable,
    SplitAssignment,
    SplitManifestView,
)

__all__ = [
    "ArtifactComparison",
    "EquivalenceMode",
    "EquivalencePlan",
    "ExecutionMode",
    "L3Error",
    "L3ReplayResult",
    "L3Replayer",
    "MetricComparison",
    "OriginalRunRef",
    "PredictionComparison",
    "ProcessRunEvidence",
    "ReplayInput",
    "SandboxAudit",
    "SandboxRunOutput",
    "SplitComparison",
    "TOSTResult",
    "assert_l3_boundary",
    "compute_plan_hash",
    "new_l3_run_id",
    "tost_equivalence",
]

_HASH64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$")

# 90% 双侧 CI 对应的单侧 95% t 临界值（df=4..30）；df>30 用正态近似。
_T_CRIT_95: Final[Mapping[int, float]] = MappingProxyType({
    4: 2.1318, 5: 2.0150, 6: 1.9432, 7: 1.8946, 8: 1.8595, 9: 1.8331,
    10: 1.8125, 11: 1.7959, 12: 1.7823, 13: 1.7709, 14: 1.7613, 15: 1.7531,
    16: 1.7459, 17: 1.7396, 18: 1.7341, 19: 1.7291, 20: 1.7247, 21: 1.7207,
    22: 1.7171, 23: 1.7139, 24: 1.7109, 25: 1.7081, 26: 1.7056, 27: 1.7033,
    28: 1.7011, 29: 1.6991, 30: 1.6973,
})


class L3Error(RuntimeError):
    """L3 前置条件/执行证据失败；对外码按语义选择。"""

    def __init__(
        self,
        error_code: str,
        reason: str,
        message: str,
        *,
        field_path: str = "",
        http_status: int = 409,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.error_code = error_code
        self.reason = reason
        self.field_path = field_path
        self.http_status = http_status
        self.detail = MappingProxyType(dict(detail or {}))
        super().__init__(f"{error_code}/{reason} @ {field_path}: {message}")


class ExecutionMode(StrEnum):
    RETRAIN = "RETRAIN"
    REINFER = "REINFER"


class EquivalenceMode(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    STOCHASTIC = "STOCHASTIC"


def new_l3_run_id() -> str:
    """Verifier 每次 L3 新生成的 run id；不得复用旧目录。"""
    return f"l3_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# 1. 原运行、计划与输入
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class OriginalRunRef:
    """原运行的**哈希引用**；不携带原产物路径，避免 L3 顺手读取。"""

    attempt_id: str
    seed: int
    code_hash: str
    config_hash: str
    dependency_lock_hash: str
    env_fingerprint: str
    ruleset_hash: str
    split_manifest_hash: str
    predictions_hash: str
    metrics_hash: str
    artifact_hashes: Mapping[str, str]
    created_at: str

    def __post_init__(self) -> None:
        if not self.attempt_id.startswith("attempt_"):
            raise L3Error("SCHEMA_INVALID", "ATTEMPT_ID_INVALID",
                          "attempt_id 形态非法", field_path="attempt_id")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise L3Error("SCHEMA_INVALID", "SEED_INVALID", "seed 必须是非负 integer", field_path="seed")
        for name in ("code_hash", "config_hash", "dependency_lock_hash", "env_fingerprint",
                     "ruleset_hash", "split_manifest_hash", "predictions_hash", "metrics_hash"):
            value = getattr(self, name)
            if not _HASH64.match(value):
                raise L3Error("SCHEMA_INVALID", f"{name.upper()}_INVALID",
                              f"{name} 必须是 64 位十六进制", field_path=name)
        if not _UTC.match(self.created_at):
            raise L3Error("SCHEMA_INVALID", "CREATED_AT_INVALID",
                          "created_at 必须是 UTC RFC 3339", field_path="created_at")
        for name, value in self.artifact_hashes.items():
            if not _HASH64.match(value):
                raise L3Error("SCHEMA_INVALID", "ARTIFACT_HASH_INVALID",
                              f"产物 {name} 的哈希非法", field_path=f"artifact_hashes.{name}")


@dataclass(frozen=True, slots=True)
class EquivalencePlan:
    """预注册的等价性计划；`plan_hash` 必须在首次重跑前冻结。"""

    mode: EquivalenceMode
    metric_names: tuple[str, ...]
    seeds: tuple[int, ...]
    margin: float
    alpha: float
    plan_hash: str
    frozen_at: str
    pre_registered: bool = True

    def __post_init__(self) -> None:
        if not self.metric_names or any(name not in METRIC_NAMES for name in self.metric_names):
            raise L3Error("SCHEMA_INVALID", "PLAN_METRICS_INVALID",
                          "metric_names 必须非空且属于五个指标", field_path="metric_names")
        if len(set(self.seeds)) != len(self.seeds):
            raise L3Error("SCHEMA_INVALID", "PLAN_SEEDS_DUPLICATED",
                          "seeds 不得重复", field_path="seeds")
        if self.mode is EquivalenceMode.DETERMINISTIC:
            if len(self.seeds) != 1:
                raise L3Error("SCHEMA_INVALID", "DETERMINISTIC_SEED_COUNT",
                              "确定性模式恰好一个种子", field_path="seeds")
            if self.margin != 0.0:
                raise L3Error("SCHEMA_INVALID", "DETERMINISTIC_MARGIN",
                              "确定性模式 margin 必须为 0", field_path="margin")
        else:
            if len(self.seeds) < 5:
                raise L3Error(
                    "REQUIRED_EVIDENCE_MISSING", "INSUFFICIENT_SEEDS",
                    "随机性模式至少需要 5 个预注册种子", field_path="seeds", http_status=409,
                )
            if not (self.margin > 0.0):
                raise L3Error("SCHEMA_INVALID", "STOCHASTIC_MARGIN",
                              "随机性模式 margin 必须 > 0", field_path="margin")
        if self.alpha != 0.05:
            raise L3Error("SCHEMA_INVALID", "ALPHA_UNSUPPORTED",
                          "T0 只支持 alpha=0.05", field_path="alpha")
        if not self.pre_registered:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "PLAN_NOT_PREREGISTERED",
                          "等价性计划必须预注册", field_path="pre_registered", http_status=409)
        if not _HASH64.match(self.plan_hash):
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "PLAN_HASH_MISSING",
                          "plan_hash 必须是 64 位十六进制（边界预冻结）",
                          field_path="plan_hash", http_status=409)
        if not _UTC.match(self.frozen_at):
            raise L3Error("SCHEMA_INVALID", "PLAN_FROZEN_AT_INVALID",
                          "frozen_at 必须是 UTC RFC 3339", field_path="frozen_at")

    def payload(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "metric_names": list(self.metric_names),
            "seeds": list(self.seeds),
            "margin": float(self.margin),
            "alpha": float(self.alpha),
        }

    def assert_seed_allowed(self, seed: int) -> None:
        if seed not in self.seeds:
            raise L3Error(
                "REQUIRED_EVIDENCE_MISSING", "SEED_NOT_PREREGISTERED",
                f"seed={seed} 不在预注册集合内", field_path="seeds", http_status=409,
            )

    def assert_pre_frozen(self, first_run_started_at: str) -> None:
        """边界哈希必须在首次重跑前冻结；晚于重跑一律拒绝。"""
        if not _UTC.match(first_run_started_at):
            raise L3Error("SCHEMA_INVALID", "FIRST_RUN_TIME_INVALID",
                          "first_run_started_at 必须是 UTC RFC 3339", field_path="first_run_started_at")
        if _parse_utc(self.frozen_at) > _parse_utc(first_run_started_at):
            raise L3Error(
                "REQUIRED_EVIDENCE_MISSING", "EQUIVALENCE_PLAN_NOT_PRE_FROZEN",
                "等价性计划在首次重跑后才冻结", field_path="frozen_at", http_status=409,
                detail={"frozen_at": self.frozen_at, "first_run_started_at": first_run_started_at},
            )


class CanonicalizerPort(Protocol):
    def canonical_bytes(self, value: object) -> bytes: ...


def compute_plan_hash(payload: Mapping[str, object], canonicalizer: CanonicalizerPort) -> str:
    """`plan_hash = sha256(JCS(payload))`；与 M06/M08 的哈希口径一致。"""
    return hashlib.sha256(canonicalizer.canonical_bytes(dict(payload))).hexdigest()


@dataclass(frozen=True, slots=True)
class SplitComparison:
    six_fields_ok: bool
    manifest_hash_match: bool
    reason: str = ""

    def passed(self) -> bool:
        return self.six_fields_ok and self.manifest_hash_match


@dataclass(frozen=True, slots=True)
class PredictionComparison:
    row_set_match: bool
    bit_exact: bool
    mismatch_count: int
    first_mismatches: tuple[str, ...] = ()
    reason: str = ""

    def passed(self) -> bool:
        return self.row_set_match and self.bit_exact and self.mismatch_count == 0


@dataclass(frozen=True, slots=True)
class TOSTResult:
    metric: str
    original: float
    seed_count: int
    mean: float
    stdev: float
    ci_low: float
    ci_high: float
    margin: float
    equivalent: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class MetricComparison:
    mode: EquivalenceMode
    deterministic_mismatches: tuple[str, ...]
    tost: tuple[TOSTResult, ...]
    reason: str = ""

    def passed(self) -> bool:
        if self.mode is EquivalenceMode.DETERMINISTIC:
            return not self.deterministic_mismatches and not self.reason
        return bool(self.tost) and all(result.equivalent for result in self.tost)


@dataclass(frozen=True, slots=True)
class ArtifactComparison:
    missing: tuple[str, ...]
    extra: tuple[str, ...]
    mismatched: tuple[str, ...]

    def passed(self) -> bool:
        return not self.missing and not self.extra and not self.mismatched


# ---------------------------------------------------------------------------
# 2. 沙箱输出与审计
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SandboxAudit:
    """沙箱审计；`original_artifact_reads` 必须为空。"""

    allowed_reads: tuple[str, ...]
    denied_reads: tuple[str, ...]
    original_artifact_reads: tuple[str, ...]
    inputs_manifest_hash: str
    log_hash: str

    def __post_init__(self) -> None:
        if not _HASH64.match(self.log_hash):
            raise L3Error("SCHEMA_INVALID", "AUDIT_LOG_HASH_INVALID",
                          "log_hash 必须是 64 位十六进制", field_path="log_hash")

    def assert_clean(self) -> None:
        if self.original_artifact_reads:
            raise L3Error(
                "TOOL_NOT_ALLOWLISTED", "L3_READ_ORIGINAL_ARTIFACTS",
                "沙箱读取了原运行产物", field_path="original_artifact_reads", http_status=403,
                detail={"reads": list(self.original_artifact_reads)[:10]},
            )
        if self.denied_reads:
            raise L3Error(
                "TOOL_NOT_ALLOWLISTED", "L3_DENIED_READ_ATTEMPTED",
                "沙箱尝试读取允许清单之外的路径", field_path="denied_reads", http_status=403,
                detail={"reads": list(self.denied_reads)[:10]},
            )


@dataclass(frozen=True, slots=True)
class SandboxRunOutput:
    """一次沙箱运行的输出；`predictions_source` 必须是 sandbox_run。"""

    seed: int
    predictions: tuple[PredictionRow, ...]
    metrics: MetricSet
    artifacts: Mapping[str, str]
    model_fit_count: int
    infer_rows: int
    predictions_source: str
    metrics_only: bool
    execution_id: str
    run_summary: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise L3Error("SCHEMA_INVALID", "OUTPUT_SEED_INVALID", "seed 非法", field_path="seed")
        if not self.predictions:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "OUTPUT_NO_PREDICTIONS",
                          "沙箱没有产出 predictions", field_path="predictions")
        if self.model_fit_count < 0 or self.infer_rows < 0:
            raise L3Error("SCHEMA_INVALID", "OUTPUT_COUNT_INVALID",
                          "模型 fit/infer 计数必须非负", field_path="model_fit_count")
        if self.predictions_source not in ("sandbox_run", "original_run", "cache"):
            raise L3Error("SCHEMA_INVALID", "PREDICTIONS_SOURCE_INVALID",
                          f"未知 predictions 来源 {self.predictions_source!r}",
                          field_path="predictions_source")
        for name, digest in self.artifacts.items():
            if not _HASH64.match(digest):
                raise L3Error("SCHEMA_INVALID", "OUTPUT_ARTIFACT_HASH_INVALID",
                              f"产物 {name} 哈希非法", field_path=f"artifacts.{name}")


@dataclass(frozen=True, slots=True)
class ProcessRunEvidence:
    identity: ProcessIdentity
    exit_code: int
    ended_at: str
    cpu_time_sec: float
    stdout_hash: str
    stderr_hash: str

    def __post_init__(self) -> None:
        if self.cpu_time_sec < 0:
            raise L3Error("SCHEMA_INVALID", "CPU_TIME_INVALID",
                          "cpu_time_sec 必须非负", field_path="cpu_time_sec")
        if not _HASH64.match(self.stdout_hash) or not _HASH64.match(self.stderr_hash):
            raise L3Error("SCHEMA_INVALID", "STDIO_HASH_INVALID",
                          "stdout/stderr 哈希必须是 64 位十六进制", field_path="stdout_hash")


class SplitVerifierPort(Protocol):
    def verify(self, manifest: SplitManifestView, dataset: DatasetTable) -> SplitComparison: ...


class CodeSnapshotPort(Protocol):
    def hash(self) -> str: ...


class ConfigSnapshotPort(Protocol):
    def hash(self) -> str: ...


class ProcessRunnerPort(Protocol):
    def run(self, spec: ProcessSpec, *, plan: SandboxPlan, seed: int) -> ProcessRunEvidence: ...


class SandboxAuditPort(Protocol):
    def read(self, plan: SandboxPlan) -> SandboxAudit: ...


class SandboxOutputReaderPort(Protocol):
    def read(self, plan: SandboxPlan, seed: int) -> SandboxRunOutput: ...


@dataclass(frozen=True, slots=True)
class ReplayInput:
    """L3 的完整输入；原运行只给哈希引用，不给可读路径。"""

    task_id: str
    node_id: str
    original: OriginalRunRef
    dataset: DatasetTable
    dataset_hash: str
    split_manifest: SplitManifestView
    split_assignment: SplitAssignment
    equivalence_plan: EquivalencePlan
    execution_mode: ExecutionMode
    template_entrypoint: str
    sandbox_policy: SandboxPolicy
    ruleset_hash: str
    environment_fingerprint: str
    dependency_lock_hash: str
    executor_pid: int
    executor_workspace_root: str
    original_run_root: str
    started_at: str
    expected_predictions: tuple[PredictionRow, ...]
    expected_metrics: Mapping[str, float]
    expected_artifacts: Mapping[str, str]
    split_verifier: SplitVerifierPort
    code_snapshot: CodeSnapshotPort
    config_snapshot: ConfigSnapshotPort
    process_runner: ProcessRunnerPort
    audit_reader: SandboxAuditPort
    output_reader: SandboxOutputReaderPort
    canonicalizer: CanonicalizerPort

    def __post_init__(self) -> None:
        if not self.task_id.startswith("task_"):
            raise L3Error("SCHEMA_INVALID", "TASK_ID_INVALID", "task_id 形态非法", field_path="task_id")
        if not self.node_id:
            raise L3Error("SCHEMA_INVALID", "NODE_ID_EMPTY", "node_id 不得为空", field_path="node_id")
        if not _HASH64.match(self.dataset_hash):
            raise L3Error("SCHEMA_INVALID", "DATASET_HASH_INVALID",
                          "dataset_hash 必须是 64 位十六进制", field_path="dataset_hash")
        for name in ("ruleset_hash", "environment_fingerprint", "dependency_lock_hash"):
            if not _HASH64.match(getattr(self, name)):
                raise L3Error("SCHEMA_INVALID", f"{name.upper()}_INVALID",
                              f"{name} 必须是 64 位十六进制", field_path=name)
        if not _UTC.match(self.started_at):
            raise L3Error("SCHEMA_INVALID", "STARTED_AT_INVALID",
                          "started_at 必须是 UTC RFC 3339", field_path="started_at")
        if self.executor_pid <= 0:
            raise L3Error("SCHEMA_INVALID", "EXECUTOR_PID_INVALID",
                          "executor_pid 必须是正整数", field_path="executor_pid")
        if not self.expected_predictions:
            raise L3Error("SCHEMA_INVALID", "EXPECTED_PREDICTIONS_EMPTY",
                          "expected_predictions 不得为空", field_path="expected_predictions")


# ---------------------------------------------------------------------------
# 3. L3 结果
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class L3ReplayResult:
    """L3 结论；`to_attestation()` 产出 Gate 可消费的结构化物证。"""

    node_id: str
    status: str                     # PASS / FAIL
    execution_mode: ExecutionMode
    equivalence_mode: EquivalenceMode
    plan_hash: str
    ruleset_hash: str
    seeds: tuple[int, ...]
    split: SplitComparison
    predictions: PredictionComparison
    metrics: MetricComparison
    artifacts: ArtifactComparison
    attribution: AttributionReport
    outputs: tuple[SandboxRunOutput, ...]
    processes: tuple[ProcessRunEvidence, ...]
    audits: tuple[SandboxAudit, ...]
    l3_coverage: float
    check_statuses: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.status not in ("PASS", "FAIL"):
            raise L3Error("SCHEMA_INVALID", "L3_STATUS_INVALID",
                          "L3 status 只允许 PASS/FAIL", field_path="status")
        if not (0.0 <= float(self.l3_coverage) <= 1.0):
            raise L3Error("SCHEMA_INVALID", "L3_COVERAGE_RANGE",
                          "l3_coverage 必须在 [0,1]", field_path="l3_coverage")

    def passed(self) -> bool:
        return (
            self.status == "PASS"
            and self.split.passed()
            and self.predictions.passed()
            and self.metrics.passed()
            and self.artifacts.passed()
            and not self.attribution.unexplained
        )

    @property
    def l3_status(self) -> str:
        """报告字段 `l3_status` 的投影；只允许 PASS/FAIL。"""
        return self.status

    def assert_no_fake_l3(self) -> None:
        """伪 L3 的机器判定；任何一条不满足都不能 PASS。"""
        if not self.processes:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_NO_NEW_PROCESS",
                          "L3 没有任何独立进程执行证据", field_path="processes")
        for audit in self.audits:
            audit.assert_clean()
        for output in self.outputs:
            if output.predictions_source != "sandbox_run":
                raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_READS_ORIGINAL_PREDICTIONS",
                              "predictions 不是沙箱运行产生", field_path="predictions_source")
            if output.metrics_only:
                raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_METRICS_ONLY",
                              "只重算指标不算 L3", field_path="metrics_only")
            if self.execution_mode is ExecutionMode.RETRAIN and output.model_fit_count < 1:
                raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_NO_MODEL_FIT",
                              "重训模式没有模型 fit 证据", field_path="model_fit_count")
            if self.execution_mode is ExecutionMode.REINFER and output.infer_rows < 1:
                raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_NO_INFERENCE",
                              "重推模式没有推理行", field_path="infer_rows")
        if self.equivalence_mode is EquivalenceMode.STOCHASTIC and len(self.seeds) < 5:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_INSUFFICIENT_SEEDS",
                          "随机性模式少于 5 个种子", field_path="seeds")
        if self.status == "PASS" and self.attribution.unexplained:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_PASS_WITH_UNEXPLAINED_DIFF",
                          "存在未解释差异不能 PASS", field_path="attribution")

    def to_attestation(self, *, evidence_id: str, produced_at: str) -> Mapping[str, object]:
        """构造 M08 Gate 消费的 L3Attestation 字段；E3 记录由 Verifier 写入。"""
        if not evidence_id.startswith("ev_"):
            raise L3Error("SCHEMA_INVALID", "E3_EVIDENCE_ID_INVALID",
                          "E3 evidence_id 形态非法", field_path="evidence_id")
        if not _UTC.match(produced_at):
            raise L3Error("SCHEMA_INVALID", "PRODUCED_AT_INVALID",
                          "produced_at 必须是 UTC RFC 3339", field_path="produced_at")
        return MappingProxyType({
            "node_id": self.node_id,
            "l3_status": "PASS" if self.passed() else "FAIL",
            "coverage": float(self.l3_coverage),
            "evidence_id": evidence_id,
            "ruleset_hash": self.ruleset_hash,
            "execution_mode": self.execution_mode.value,
            "equivalence_mode": self.equivalence_mode.value,
            "seed_count": len(self.seeds),
            "plan_hash": self.plan_hash,
            "check_statuses": dict(self.check_statuses),
            "produced_at": produced_at,
        })


# ---------------------------------------------------------------------------
# 4. Replayer
# ---------------------------------------------------------------------------
class L3Replayer:
    """L3 重放器；只读输入 + 沙箱执行 + 比较 + 归因。"""

    def run(self, replay_input: ReplayInput) -> L3ReplayResult:
        """按 9.3 流程执行；任何前置/隔离/伪 L3 失败都返回 FAIL 或抛 L3Error。"""
        self._assert_preconditions(replay_input)
        plan = plan_sandbox(
            replay_input.sandbox_policy,
            task_id=replay_input.task_id,
            run_id=new_l3_run_id(),
            created_at=replay_input.started_at,
        )
        outputs: list[SandboxRunOutput] = []
        processes: list[ProcessRunEvidence] = []
        audits: list[SandboxAudit] = []
        for seed in replay_input.equivalence_plan.seeds:
            spec = build_process_spec(
                plan, seed=seed, entrypoint=replay_input.template_entrypoint,
                timeout_sec=replay_input.sandbox_policy.max_wall_time_sec,
            )
            process = replay_input.process_runner.run(spec, plan=plan, seed=seed)
            self._assert_process(replay_input, plan, process)
            audit = replay_input.audit_reader.read(plan)
            audit.assert_clean()
            output = replay_input.output_reader.read(plan, seed)
            self._assert_real_output(replay_input, output)
            outputs.append(output)
            processes.append(process)
            audits.append(audit)

        split = replay_input.split_verifier.verify(
            replay_input.split_manifest, replay_input.dataset,
        )
        predictions = self._compare_predictions(
            replay_input, outputs,
        )
        metrics = self._compare_metrics(replay_input, outputs)
        artifacts = self._compare_artifacts(replay_input, outputs)
        attribution = self._attribute(replay_input, split, predictions, metrics, artifacts)

        check_statuses = {
            "split_manifest_valid": "PASS" if split.passed() else "FAIL",
            "predictions_cover_test_rows": "PASS" if predictions.row_set_match else "FAIL",
            "metrics_recomputable": "PASS" if metrics.passed() else "FAIL",
            "no_train_test_overlap": "PASS" if split.six_fields_ok else "FAIL",
        }
        status = "PASS" if (
            split.passed() and predictions.passed() and metrics.passed()
            and artifacts.passed() and not attribution.unexplained
        ) else "FAIL"
        result = L3ReplayResult(
            node_id=replay_input.node_id,
            status=status,
            execution_mode=replay_input.execution_mode,
            equivalence_mode=replay_input.equivalence_plan.mode,
            plan_hash=replay_input.equivalence_plan.plan_hash,
            ruleset_hash=replay_input.ruleset_hash,
            seeds=replay_input.equivalence_plan.seeds,
            split=split,
            predictions=predictions,
            metrics=metrics,
            artifacts=artifacts,
            attribution=attribution,
            outputs=tuple(outputs),
            processes=tuple(processes),
            audits=tuple(audits),
            l3_coverage=1.0 if status == "PASS" else 0.0,
            check_statuses=MappingProxyType(check_statuses),
        )
        result.assert_no_fake_l3()
        return result

    # -- 4.1 原运行基线回绑 ----------------------------------------------
    def _assert_original_baseline(self, replay_input: ReplayInput) -> None:
        """把 expected_* 与原运行声明的哈希绑定，防止伪造“原运行基线”。

        载荷口径（固定）：
          - predictions：[{row_id, fold, y_true, y_pred, scores}...]，保持输入顺序；
            scores 为 None 或 dict(sorted(items))；
          - metrics：dict(sorted(expected_metrics.items()))；
          - artifacts：dict(sorted(expected_artifacts.items()))。
        predictions/metrics 用 canonical_bytes + SHA-256 比对；
        artifacts 与 original.artifact_hashes 逐键值比较。
        不符 → `BUNDLE_TAMPERED` / `ORIGINAL_BASELINE_MISMATCH`，在创建沙箱前 fail-closed。
        """
        predictions_payload = [
            {
                "row_id": row.row_id,
                "fold": row.fold,
                "y_true": row.y_true,
                "y_pred": row.y_pred,
                "scores": None if row.scores is None else dict(sorted(row.scores.items())),
            }
            for row in replay_input.expected_predictions
        ]
        metrics_payload = dict(sorted(replay_input.expected_metrics.items()))
        artifacts_payload = dict(sorted(replay_input.expected_artifacts.items()))

        predictions_hash = hashlib.sha256(
            replay_input.canonicalizer.canonical_bytes(predictions_payload)
        ).hexdigest()
        if predictions_hash != replay_input.original.predictions_hash:
            raise L3Error(
                "BUNDLE_TAMPERED", "ORIGINAL_BASELINE_MISMATCH",
                "expected_predictions 与原运行 predictions_hash 不符",
                field_path="predictions_hash", http_status=422,
                detail={
                    "expected": replay_input.original.predictions_hash,
                    "actual": predictions_hash,
                },
            )
        metrics_hash = hashlib.sha256(
            replay_input.canonicalizer.canonical_bytes(metrics_payload)
        ).hexdigest()
        if metrics_hash != replay_input.original.metrics_hash:
            raise L3Error(
                "BUNDLE_TAMPERED", "ORIGINAL_BASELINE_MISMATCH",
                "expected_metrics 与原运行 metrics_hash 不符",
                field_path="metrics_hash", http_status=422,
                detail={
                    "expected": replay_input.original.metrics_hash,
                    "actual": metrics_hash,
                },
            )
        original_artifacts = dict(sorted(replay_input.original.artifact_hashes.items()))
        if artifacts_payload != original_artifacts:
            raise L3Error(
                "BUNDLE_TAMPERED", "ORIGINAL_BASELINE_MISMATCH",
                "expected_artifacts 与原运行 artifact_hashes 不符",
                field_path="artifact_hashes", http_status=422,
                detail={
                    "mismatched": sorted(
                        key for key in set(artifacts_payload) | set(original_artifacts)
                        if artifacts_payload.get(key) != original_artifacts.get(key)
                    ),
                },
            )

    # -- 4.2 前置条件 -----------------------------------------------------
    def _assert_preconditions(self, replay_input: ReplayInput) -> None:
        self._assert_original_baseline(replay_input)
        original = replay_input.original
        if replay_input.dataset_hash != replay_input.split_manifest.dataset_hash:
            raise L3Error("BUNDLE_TAMPERED", "DATASET_HASH_MISMATCH",
                          "数据集哈希与 Split Manifest 不一致", field_path="dataset_hash")
        if replay_input.split_manifest.manifest_hash != original.split_manifest_hash:
            raise L3Error("BUNDLE_TAMPERED", "SPLIT_MANIFEST_HASH_MISMATCH",
                          "Split Manifest 与原运行不一致", field_path="split_manifest")
        if replay_input.code_snapshot.hash() != original.code_hash:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "CODE_SNAPSHOT_MISMATCH",
                          "代码快照哈希与原运行不一致", field_path="code_snapshot")
        if replay_input.config_snapshot.hash() != original.config_hash:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "CONFIG_SNAPSHOT_MISMATCH",
                          "配置快照哈希与原运行不一致", field_path="config_snapshot")
        if replay_input.ruleset_hash != original.ruleset_hash:
            raise L3Error("RULESET_VERSION_MISMATCH", "L3_RULESET_MISMATCH",
                          "L3 规则版本与原运行不一致", field_path="ruleset_hash", http_status=409)
        if replay_input.environment_fingerprint != original.env_fingerprint:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_ENVIRONMENT_MISMATCH",
                          "L3 环境指纹与原运行不一致：不能做同环境重执行",
                          field_path="environment_fingerprint")
        if replay_input.dependency_lock_hash != original.dependency_lock_hash:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_DEPENDENCY_LOCK_MISMATCH",
                          "L3 依赖锁与原运行不一致", field_path="dependency_lock_hash")
        expected_plan_hash = compute_plan_hash(
            replay_input.equivalence_plan.payload(), replay_input.canonicalizer,
        )
        if expected_plan_hash != replay_input.equivalence_plan.plan_hash:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "PLAN_HASH_MISMATCH",
                          "等价性计划哈希与内容不一致", field_path="plan_hash")
        replay_input.equivalence_plan.assert_pre_frozen(replay_input.started_at)
        replay_input.equivalence_plan.assert_seed_allowed(original.seed)
        split = replay_input.split_verifier.verify(
            replay_input.split_manifest, replay_input.dataset,
        )
        if not split.passed():
            raise L3Error("BUNDLE_TAMPERED", "SPLIT_MANIFEST_INVALID",
                          f"Split Manifest 校验失败：{split.reason}", field_path="split_manifest")

    # -- 4.3 进程与真实执行 ----------------------------------------------
    def _assert_process(
        self, replay_input: ReplayInput, plan: SandboxPlan, process: ProcessRunEvidence,
    ) -> None:
        identity = process.identity
        if identity.pid == replay_input.executor_pid:
            raise L3Error("TOOL_NOT_ALLOWLISTED", "L3_SAME_PID",
                          "L3 进程复用了 Executor PID", field_path="pid", http_status=403)
        if identity.parent_pid == replay_input.executor_pid:
            raise L3Error("TOOL_NOT_ALLOWLISTED", "L3_PARENT_IS_EXECUTOR",
                          "L3 进程由 Executor 直接派生", field_path="parent_pid", http_status=403)
        if not _is_within(plan.root, identity.cwd):
            raise L3Error("TOOL_NOT_ALLOWLISTED", "L3_CWD_OUTSIDE_SANDBOX",
                          "L3 进程 cwd 不在沙箱内", field_path="cwd", http_status=403)
        if _is_within(replay_input.original_run_root, identity.cwd):
            raise L3Error("TOOL_NOT_ALLOWLISTED", "L3_ORIGINAL_DIR_RERUN",
                          "L3 在原运行目录内重跑", field_path="cwd", http_status=403)
        if _is_within(replay_input.executor_workspace_root, identity.cwd):
            raise L3Error("TOOL_NOT_ALLOWLISTED", "L3_CWD_IN_EXECUTOR_WORKSPACE",
                          "L3 cwd 在 Executor 工作区内", field_path="cwd", http_status=403)
        if not _is_within(plan.root, identity.sandbox_root):
            raise L3Error("TOOL_NOT_ALLOWLISTED", "L3_SANDBOX_ROOT_MISMATCH",
                          "进程记录的 sandbox_root 不是本沙箱", field_path="sandbox_root",
                          http_status=403)
        if _is_within(replay_input.original_run_root, identity.sandbox_root):
            raise L3Error("TOOL_NOT_ALLOWLISTED", "L3_SANDBOX_REUSED",
                          "沙箱根在原运行目录内", field_path="sandbox_root", http_status=403)
        if process.exit_code != 0:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_PROCESS_FAILED",
                          f"L3 进程退出码 {process.exit_code}", field_path="exit_code")
        if process.cpu_time_sec <= 0:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_NO_CPU_TIME",
                          "没有 CPU 时间，疑似未真实执行", field_path="cpu_time_sec")
        try:
            started_at = _parse_utc(identity.started_at)
            sandbox_created_at = _parse_utc(plan.created_at)
        except ValueError as exc:
            raise L3Error("SCHEMA_INVALID", "L3_TIMESTAMP_INVALID",
                          f"进程/沙箱时间无法解析：{exc}", field_path="started_at") from exc
        if started_at < sandbox_created_at:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_PROCESS_BEFORE_SANDBOX",
                          "进程启动早于沙箱创建", field_path="started_at")

    def _assert_real_output(self, replay_input: ReplayInput, output: SandboxRunOutput) -> None:
        if output.predictions_source != "sandbox_run":
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_READS_ORIGINAL_PREDICTIONS",
                          "predictions 来自原运行/缓存，不是沙箱", field_path="predictions_source")
        if output.metrics_only:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_METRICS_ONLY",
                          "只重算指标不算 L3", field_path="metrics_only")
        if replay_input.execution_mode is ExecutionMode.RETRAIN and output.model_fit_count < 1:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_NO_MODEL_FIT",
                          "重训模式没有模型 fit 证据", field_path="model_fit_count")
        if replay_input.execution_mode is ExecutionMode.REINFER and output.infer_rows < 1:
            raise L3Error("REQUIRED_EVIDENCE_MISSING", "L3_NO_INFERENCE",
                          "重推模式没有推理行", field_path="infer_rows")

    # -- 4.4 比较 ---------------------------------------------------------
    def _compare_predictions(
        self, replay_input: ReplayInput, outputs: Sequence[SandboxRunOutput],
    ) -> PredictionComparison:
        expected = {row.row_id: row for row in replay_input.expected_predictions}
        mismatches: list[str] = []
        row_set_match = True
        bit_exact = True
        for output in outputs:
            actual = {row.row_id: row for row in output.predictions}
            # 随机性模式只对原种子的输出要求 bit-exact；其它种子只要求覆盖与标签一致。
            if replay_input.equivalence_plan.mode is EquivalenceMode.STOCHASTIC \
                    and output.seed != replay_input.original.seed:
                if set(actual) != set(expected):
                    row_set_match = False
                for row_id in set(actual) & set(expected):
                    if actual[row_id].y_true != expected[row_id].y_true:
                        mismatches.append(row_id)
                continue
            if set(actual) != set(expected):
                row_set_match = False
                continue
            for row_id, expected_row in expected.items():
                actual_row = actual[row_id]
                if actual_row.y_true != expected_row.y_true:
                    mismatches.append(f"{row_id}:y_true")
                    continue
                if actual_row.y_pred != expected_row.y_pred:
                    mismatches.append(f"{row_id}:y_pred")
                    continue
                if (expected_row.scores is None) != (actual_row.scores is None):
                    mismatches.append(f"{row_id}:scores_presence")
                    continue
                if expected_row.scores is not None:
                    assert actual_row.scores is not None
                    if set(expected_row.scores) != set(actual_row.scores):
                        mismatches.append(f"{row_id}:score_labels")
                        continue
                    for label, expected_score in expected_row.scores.items():
                        if not bit_identical(float(expected_score), float(actual_row.scores[label])):
                            mismatches.append(f"{row_id}:score:{label}")
                            break
        if mismatches:
            bit_exact = False
        return PredictionComparison(
            row_set_match=row_set_match,
            bit_exact=bit_exact,
            mismatch_count=len(mismatches),
            first_mismatches=tuple(mismatches[:10]),
            reason="" if row_set_match and bit_exact else "PREDICTIONS_DIFFER",
        )

    def _compare_metrics(
        self, replay_input: ReplayInput, outputs: Sequence[SandboxRunOutput],
    ) -> MetricComparison:
        plan = replay_input.equivalence_plan
        if plan.mode is EquivalenceMode.DETERMINISTIC:
            reported = replay_input.expected_metrics
            actual = outputs[0].metrics
            mismatches: list[str] = []
            for name in plan.metric_names:
                if name in actual.undefined:
                    mismatches.append(f"{name}:UNDEFINED")
                    continue
                if name not in reported or name not in actual.values:
                    mismatches.append(f"{name}:MISSING")
                    continue
                if not bit_identical(float(reported[name]), float(actual.values[name])):
                    mismatches.append(name)
            return MetricComparison(
                mode=plan.mode,
                deterministic_mismatches=tuple(mismatches),
                tost=(),
                reason="" if not mismatches else "METRICS_NOT_BIT_EXACT",
            )

        tost_results: list[TOSTResult] = []
        for name in plan.metric_names:
            original = replay_input.expected_metrics.get(name)
            if original is None:
                return MetricComparison(
                    mode=plan.mode, deterministic_mismatches=(), tost=(),
                    reason=f"ORIGINAL_METRIC_MISSING:{name}",
                )
            values: list[float] = []
            for output in outputs:
                if name in output.metrics.undefined or name not in output.metrics.values:
                    return MetricComparison(
                        mode=plan.mode, deterministic_mismatches=(), tost=(),
                        reason=f"SEED_METRIC_UNDEFINED:{name}:{output.seed}",
                    )
                values.append(float(output.metrics.values[name]))
            tost_results.append(tost_equivalence(
                name, float(original), values, margin=plan.margin, alpha=plan.alpha,
            ))
        return MetricComparison(
            mode=plan.mode, deterministic_mismatches=(), tost=tuple(tost_results),
            reason="" if all(result.equivalent for result in tost_results) else "TOST_NOT_EQUIVALENT",
        )

    def _compare_artifacts(
        self, replay_input: ReplayInput, outputs: Sequence[SandboxRunOutput],
    ) -> ArtifactComparison:
        missing: list[str] = []
        mismatched: list[str] = []
        extra: list[str] = []
        for name, expected in replay_input.expected_artifacts.items():
            for output in outputs:
                if name not in output.artifacts:
                    missing.append(name)
                elif output.artifacts[name] != expected:
                    mismatched.append(name)
        known = set(replay_input.expected_artifacts)
        for output in outputs:
            for name in output.artifacts:
                if name not in known:
                    extra.append(name)
        return ArtifactComparison(
            missing=tuple(sorted(set(missing))),
            extra=tuple(sorted(set(extra))),
            mismatched=tuple(sorted(set(mismatched))),
        )

    # -- 4.5 归因 ---------------------------------------------------------
    def _attribute(
        self,
        replay_input: ReplayInput,
        split: SplitComparison,
        predictions: PredictionComparison,
        metrics: MetricComparison,
        artifacts: ArtifactComparison,
    ) -> AttributionReport:
        original = replay_input.original
        rules_match = replay_input.ruleset_hash == original.ruleset_hash
        data_match = (
            replay_input.dataset_hash == replay_input.split_manifest.dataset_hash
            and split.manifest_hash_match
        )
        code_match = (
            replay_input.code_snapshot.hash() == original.code_hash
            and replay_input.config_snapshot.hash() == original.config_hash
        )
        environment_match = (
            replay_input.environment_fingerprint == original.env_fingerprint
            and replay_input.dependency_lock_hash == original.dependency_lock_hash
        )
        output_differs = not (
            split.passed() and predictions.passed() and metrics.passed() and artifacts.passed()
        )
        randomness = RandomnessCheck(
            fixed_seed=replay_input.equivalence_plan.mode is EquivalenceMode.DETERMINISTIC,
            seeds_pre_registered=replay_input.equivalence_plan.pre_registered,
            seed_count=len(replay_input.equivalence_plan.seeds),
            within_variance=metrics.passed() if metrics.mode is EquivalenceMode.STOCHASTIC else True,
            variance_explains=metrics.mode is EquivalenceMode.STOCHASTIC and metrics.passed(),
            details={"mode": replay_input.equivalence_plan.mode.value},
        )
        return attribute(AttributionInput(
            rules=FactorCheck(
                Cause.RULES, rules_match,
                original.ruleset_hash, replay_input.ruleset_hash,
                note="规则版本逐字比较 ruleset_hash",
            ),
            data=FactorCheck(
                Cause.DATA, data_match,
                original.split_manifest_hash, replay_input.split_manifest.manifest_hash,
                note="dataset_hash + Split Manifest 六字段",
            ),
            code=FactorCheck(
                Cause.CODE, code_match,
                original.code_hash, replay_input.code_snapshot.hash(),
                note="代码/配置快照哈希",
            ),
            environment=FactorCheck(
                Cause.ENVIRONMENT, environment_match,
                original.env_fingerprint, replay_input.environment_fingerprint,
                note="环境指纹 + 依赖锁哈希分别比较",
            ),
            randomness=randomness,
            equivalence_mode=replay_input.equivalence_plan.mode.value,
            output_differs=output_differs,
        ))


# ---------------------------------------------------------------------------
# 5. TOST
# ---------------------------------------------------------------------------
def _t_critical_95(df: int) -> float:
    """df=4..30 查表；df>30 用正态近似 1.6449（# LIB: scipy.stats.t.ppf(0.95, df)）。"""
    if df < 4:
        raise L3Error("SCHEMA_INVALID", "TOST_DF_TOO_SMALL", "TOST 至少需要 5 个种子", field_path="df")
    return _T_CRIT_95.get(df, 1.6449)


def tost_equivalence(
    metric: str,
    original: float,
    seed_values: Sequence[float],
    *,
    margin: float,
    alpha: float,
) -> TOSTResult:
    """TOST：90% CI（alpha=0.05 单侧）落在 ±margin 内即等价。

    计算的是 `seed_value - original` 的均值与 CI；`ci_low > -margin` 且 `ci_high < margin`。
    边界严格不等号：恰好等于边界不算等价（保守）。
    """
    if metric not in METRIC_NAMES:
        raise L3Error("SCHEMA_INVALID", "TOST_METRIC_UNKNOWN", f"未知指标 {metric!r}", field_path="metric")
    if len(seed_values) < 5:
        raise L3Error("REQUIRED_EVIDENCE_MISSING", "TOST_INSUFFICIENT_SEEDS",
                      "TOST 至少需要 5 个种子", field_path="seed_values")
    if margin <= 0:
        raise L3Error("SCHEMA_INVALID", "TOST_MARGIN_INVALID", "margin 必须 > 0", field_path="margin")
    if alpha != 0.05:
        raise L3Error("SCHEMA_INVALID", "TOST_ALPHA_UNSUPPORTED", "只支持 alpha=0.05", field_path="alpha")
    diffs = [float(value) - float(original) for value in seed_values]
    mean_diff = statistics.fmean(diffs)
    sd = statistics.stdev(diffs) if len(diffs) > 1 else 0.0
    if sd == 0.0:
        ci_low = ci_high = mean_diff
    else:
        se = sd / math.sqrt(len(diffs))
        t_crit = _t_critical_95(len(diffs) - 1)
        ci_low = mean_diff - t_crit * se
        ci_high = mean_diff + t_crit * se
    equivalent = ci_low > -margin and ci_high < margin
    return TOSTResult(
        metric=metric,
        original=float(original),
        seed_count=len(seed_values),
        mean=float(original) + mean_diff,
        stdev=sd,
        ci_low=ci_low,
        ci_high=ci_high,
        margin=float(margin),
        equivalent=equivalent,
        reason="" if equivalent else "CI_OUTSIDE_MARGIN",
    )


# ---------------------------------------------------------------------------
# 6. 静态边界
# ---------------------------------------------------------------------------
def _parse_utc(value: str) -> datetime:
    """把 RFC3339 UTC 解析为带时区 datetime；Z 与 +00:00 等价。"""
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("时间必须带时区")
    return parsed.astimezone(timezone.utc)


def _is_within(parent: str, child: str) -> bool:
    """纯路径判断（不碰文件系统）；不同盘符返回 False。"""
    try:
        parent_real = os.path.normcase(os.path.realpath(parent))
        child_real = os.path.normcase(os.path.realpath(child))
        return os.path.commonpath([parent_real, child_real]) == parent_real
    except ValueError:
        return False


def assert_l3_boundary() -> list[str]:
    """L3 不得把原运行产物放进沙箱输入，也不得用指标重算冒充重跑。"""
    problems: list[str] = []
    names = [entry.logical_name for entry in READONLY_ALLOWLIST]
    for forbidden in ("predictions", "metrics", "model", "artifacts"):
        if forbidden in names:
            problems.append(f"L3 允许清单不得包含 {forbidden!r}")
    fields = set(L3ReplayResult.__dataclass_fields__)
    for forbidden in ("final_state", "signature", "verified"):
        if forbidden in fields:
            problems.append(f"L3ReplayResult 不得有 {forbidden!r} 字段")
    if EquivalenceMode.DETERMINISTIC.value == "STOCHASTIC":
        problems.append("确定性/随机性模式被混同")
    return problems