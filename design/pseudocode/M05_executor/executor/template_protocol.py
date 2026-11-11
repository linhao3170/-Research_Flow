"""M05 · executor/template_protocol.py — 模板必须实现的协议（P3 伪代码）。
阶段：P3「DAG 与执行器」｜追踪：FR-004（内置模板执行）、FR-005（E2 来自真实受控执行）
依赖：M05 registry（TemplateRegistration）、M05 workspace（目录布局）、M01 encoding（哈希只算不报）
不变量：模板只声明产物路径，**不提供哈希**；不返回 PASS/FAIL；不写证据、不写状态、不联网
错误码：TOOL_NOT_ALLOWLISTED（模板未登记/协议不满足）、SCHEMA_INVALID（产物路径/声明非法）
写入者：模板写 `artifacts/`、`logs/`、`tmp/`；**不写** DB、evidence、状态、审计
状态：伪代码；不实现任何模板本体（P4）

## 协议三方法

    prepare(ctx: TemplateContext) -> PreparedPlan
    run(plan: PreparedPlan) -> RunReport
    emit_artifacts(report: RunReport) -> tuple[ArtifactDeclaration, ...]

  - `prepare`：校验输入、计算计划；**不产生副作用**（不写文件、不联网、不读密钥）。
  - `run`：真正计算；只写 `artifacts/`（+ `logs/`、`tmp/`）；可抛异常表示模板错误。
  - `emit_artifacts`：声明“我写了哪些文件”，给**相对路径**，不实现“我算出的哈希”。

## 参数从哪来（唯一通路）

  1. Orchestrator 把节点参数（`GraphDraft.nodes[*].parameters`）交给 worker；
  2. worker 校验 `parameters_hash` 与 registry 的 ParamSchema；
  3. worker **原子写** `inputs/params.json`（UTF-8、无 BOM）；
  4. worker 用 `build_argv()` 启动子进程：`python -m <module>.__main__ --params params.json`；
  5. 模板从 `ctx.params` 拿已解析对象。

  **不**从 argv 取参数值（注入/长度/凭据），**不**从环境变量取业务参数（不可审计），
  **不**让模板自己读 TaskSpec（那是编排层事实，模板不该有 DB 句柄）。

## 产物写到哪（唯一通路）

    <attempt>/artifacts/<relative_path>

  - `ArtifactDeclaration.relative_path` 必须是 `artifacts/` 下的 POSIX 相对名；
  - 绝对路径、`..`、盘符、ADS、符号链接一律拒绝（`workspace.resolve_inside` 复核）；
  - **哈希与大小由 worker 在子进程结束后计算**（二进制读、SHA-256、字节数）；
    模板给出的任何“哈希”字段都会被忽略并计为协议违规 —— 这样“自报哈希”无法伪造；
  - 未声明的文件出现在 `artifacts/` 下 → worker 判 `UNDECLARED_ARTIFACT` 并拒绝收产物。

## 返回值形态（为什么没有 verdict 字段）

  `RunReport` 里**结构上没有** `status`/`passed`/`success`/`verdict` 字段。
  模板能表达的只有：指标摘要、告警、备注。原因：Executor 只执行不裁决（AGENTS §4.4），
  裁决由 Gate/Verifier 在拿到 E2 证据之后做；若模板能自报 PASS，E2 就被自述污染。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence, runtime_checkable

__all__ = [
    "ARTIFACT_DECLARATION_FIELDS",
    "FORBIDDEN_TEMPLATE_ATTRS",
    "TEMPLATE_FORBIDDEN",
    "TEMPLATE_METHODS",
    "ArtifactDeclaration",
    "LoggerPort",
    "PreparedPlan",
    "RunReport",
    "TemplateContext",
    "TemplateContractError",
    "TemplatePhase",
    "TemplateProtocol",
    "TemplateViolation",
    "assert_template_contract",
    "validate_artifact_declaration",
]

TEMPLATE_METHODS: Final[tuple[str, ...]] = ("prepare", "run", "emit_artifacts")

TEMPLATE_FORBIDDEN: Final[tuple[str, ...]] = (
    "联网/访问外部服务（T0 断网；不得用 socket/requests/urllib/http.client）",
    "启动子进程或 shell（进程树由 Executor 统一管理，模板不得自己 fork）",
    "写 artifacts/ 之外的业务文件；tmp/ 与 logs/ 以外的路径只读",
    "使用绝对路径、盘符、UNC、`..`、符号链接或硬链接",
    "读取环境变量里的业务参数或凭据（PYTHONPATH 等由 Executor 白名单注入）",
    "自报产物哈希/大小（哈希由 Executor 计算，模板的哈希字段被忽略并计违规）",
    "返回 PASS/FAIL/成功/失败等裁决字段（模板不裁决，裁决属 Gate/Verifier）",
    "写 evidence、写数据库、写状态、调用 StateMachine",
    "修改 ctx/plan 里的输入产物（inputs/ 只读）",
    "`os.chdir` 或改变进程全局状态（会影响同进程内其它串行步骤）",
)

# 模板模块里不允许出现的公开属性名（静态扫描；命中即拒绝登记该模板）。
FORBIDDEN_TEMPLATE_ATTRS: Final[tuple[str, ...]] = (
    "requests", "urllib", "http", "socket", "subprocess", "multiprocessing",
    "system", "popen", "spawn", "urlopen", "sendall",
)

ARTIFACT_DECLARATION_FIELDS: Final[tuple[str, ...]] = (
    "name", "relative_path", "media_type", "description",
)
# 结构事实：这里**没有** sha256 / size_bytes 槽位。想伪造也没有字段可填。


# ---------------------------------------------------------------------------
# 1. 上下文
# ---------------------------------------------------------------------------
class LoggerPort(Protocol):
    """模板可用的日志端口：单行、已脱敏、不落原始数据。

    模板**不得**自己开文件写日志（会绕过脱敏与大小控制），只能通过本端口。
    """

    def info(self, event: str, **fields: object) -> None:
        ...

    def warning(self, event: str, **fields: object) -> None:
        ...


@dataclass(frozen=True, slots=True)
class TemplateContext:
    """模板执行上下文。

    `params` 是**已校验**的节点参数（worker 已完成 ParamSchema 校验与 `parameters_hash` 比对）。
    `workdir_*` 全部是**相对路径**（相对 attempt 根），模板不得自行拼绝对路径。
    """

    task_id: str
    node_id: str
    attempt_id: str
    template_id: str
    params: Mapping[str, object]
    seed: int | None
    relative_inputs: str = "inputs"
    relative_artifacts: str = "artifacts"
    relative_logs: str = "logs"
    relative_tmp: str = "tmp"
    wall_time_sec: int = 0
    max_artifacts: int = 0
    max_artifact_bytes: int = 0
    logger: LoggerPort | None = None

    def __post_init__(self) -> None:
        if not self.attempt_id.startswith("attempt_"):
            raise ValueError("attempt_id 必须以 attempt_ 开头（每次真实执行唯一）")
        for name in (self.relative_inputs, self.relative_artifacts, self.relative_logs, self.relative_tmp):
            if "/" in name or "\\" in name or name in ("", ".", ".."):
                raise ValueError("工作子目录必须是单段相对名")
        if self.wall_time_sec < 0 or self.max_artifacts < 0 or self.max_artifact_bytes < 0:
            raise ValueError("上限不得为负")


# ---------------------------------------------------------------------------
# 2. 计划、报告、产物声明
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PreparedPlan:
    """`prepare()` 的产物：只描述“打算怎么做”，不落地。

    `inputs` 是产物名 → **相对路径**（相对 attempt 根，形如 `inputs/split_manifest.json`）。
    `planned_artifacts` 是预期写出的文件（实际以 `emit_artifacts` 为准，二者不一致由
    worker 记 `PLAN_MISMATCH` 告警——**告警不阻断**，因为模板可能在运行中发现需要少写）。
    """

    inputs: Mapping[str, str]
    planned_artifacts: tuple[str, ...]
    notes: str = ""

    def __post_init__(self) -> None:
        for name, rel in self.inputs.items():
            if not isinstance(name, str) or not name:
                raise ValueError("输入产物名必须是非空字符串")
            _require_relative(rel, "inputs")
        for rel in self.planned_artifacts:
            _require_relative(rel, "artifacts")


@dataclass(frozen=True, slots=True)
class RunReport:
    """`run()` 的产物：**只有观测事实，没有裁决**。

    结构上缺三个字段：`status`、`passed`、`success`。这不是遗漏——
    模板无权判定研究结果是否成立；它只报告“我算出了什么”。
    `metrics_summary` 允许放指标名→数值，用于后续 L2 重算与人工查看；
    **不得**放“结论”“是否通过”这类自由文本（`notes` 只做补充说明）。
    """

    metrics_summary: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    warnings: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        for key, value in self.metrics_summary.items():
            if not isinstance(key, str) or not key:
                raise ValueError("指标名必须是非空字符串")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"指标 {key!r} 必须是数值（不得放结论/布尔）")
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError(f"指标 {key!r} 不得为 NaN/Infinity")


@dataclass(frozen=True, slots=True)
class ArtifactDeclaration:
    """模板声明“这个产物我写了”。

    `name` 是图里 `artifact://<name>` 的名字（用于下游引用解析）；
    `relative_path` 是 `artifacts/` 下的相对路径。
    **没有** `sha256`/`size_bytes`：那两项由 worker 计算并写进产物清单。
    """

    name: str
    relative_path: str
    media_type: str = "application/octet-stream"
    description: str = ""

    def __post_init__(self) -> None:
        validate_artifact_declaration(self)


def validate_artifact_declaration(decl: ArtifactDeclaration) -> None:
    """产物声明校验：名字与路径都必须“单段、相对、无逃逸”。

    错误码：`SCHEMA_INVALID`（422）——产物声明是模板输出契约的一部分，
    形态错误属请求/输出形态问题，不是执行失败。
    """
    if not isinstance(decl.name, str) or not decl.name:
        raise TemplateContractError(TemplateViolation.ARTIFACT_INVALID, "产物名必须非空")
    if "://" in decl.name or "/" in decl.name or "\\" in decl.name:
        raise TemplateContractError(TemplateViolation.ARTIFACT_INVALID,
                                    f"产物名 {decl.name!r} 不得含路径/协议前缀")
    _require_relative(decl.relative_path, "artifacts")
    if not decl.media_type or "/" not in decl.media_type:
        raise TemplateContractError(TemplateViolation.ARTIFACT_INVALID,
                                    f"media_type {decl.media_type!r} 形态非法")


def _require_relative(rel: str, required_prefix: str) -> None:
    if not isinstance(rel, str) or not rel:
        raise TemplateContractError(TemplateViolation.ARTIFACT_INVALID, "相对路径不得为空")
    normalized = rel.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise TemplateContractError(TemplateViolation.ABSOLUTE_PATH,
                                    f"{rel!r} 不得是绝对路径/盘符")
    parts = [p for p in normalized.split("/") if p]
    if any(p == ".." for p in parts):
        raise TemplateContractError(TemplateViolation.WRITE_OUTSIDE, f"{rel!r} 不得含 ..")
    if ":" in normalized:
        raise TemplateContractError(TemplateViolation.ARTIFACT_INVALID,
                                    f"{rel!r} 不得含冒号（ADS）")
    if not parts or parts[0] != required_prefix:
        raise TemplateContractError(
            TemplateViolation.WRITE_OUTSIDE,
            f"{rel!r} 必须位于 {required_prefix}/ 下",
        )


# ---------------------------------------------------------------------------
# 3. 违规与异常
# ---------------------------------------------------------------------------
class TemplateViolation(StrEnum):
    """协议违规原因（内部故障码；对外映射见 `TemplateContractError.error_code`）。"""

    MISSING_METHOD = "TEMPLATE_MISSING_METHOD"
    NETWORK = "TEMPLATE_NETWORK_ACCESS"
    SUBPROCESS = "TEMPLATE_SUBPROCESS"
    WRITE_OUTSIDE = "TEMPLATE_WRITE_OUTSIDE"
    ABSOLUTE_PATH = "TEMPLATE_ABSOLUTE_PATH"
    SELF_REPORTED_VERDICT = "TEMPLATE_SELF_REPORTED_VERDICT"
    SELF_REPORTED_HASH = "TEMPLATE_SELF_REPORTED_HASH"
    ARTIFACT_INVALID = "TEMPLATE_ARTIFACT_INVALID"
    ENV_SECRET_READ = "TEMPLATE_ENV_SECRET_READ"
    FORBIDDEN_IMPORT = "TEMPLATE_FORBIDDEN_IMPORT"


class TemplateContractError(RuntimeError):
    """模板不满足协议；登记期或 preflight 期抛出，**不是**执行结果。

    对外错误码：
      - 模板未登记/协议不满足 → `TOOL_NOT_ALLOWLISTED`(403)；
      - 产物声明形态非法 → `SCHEMA_INVALID`(422)。
    """

    def __init__(
        self,
        violation: TemplateViolation,
        detail: str,
        *,
        template_id: str = "",
    ) -> None:
        self.violation = violation
        self.detail = detail
        self.template_id = template_id
        self.error_code = (
            "TOOL_NOT_ALLOWLISTED"
            if violation in (TemplateViolation.MISSING_METHOD, TemplateViolation.FORBIDDEN_IMPORT,
                             TemplateViolation.NETWORK, TemplateViolation.SUBPROCESS,
                             TemplateViolation.SELF_REPORTED_VERDICT,
                             TemplateViolation.SELF_REPORTED_HASH)
            else "SCHEMA_INVALID"
        )
        self.http_status = 403 if self.error_code == "TOOL_NOT_ALLOWLISTED" else 422
        super().__init__(f"{self.error_code}/{violation.value}：{detail}")


# ---------------------------------------------------------------------------
# 4. 协议本体
# ---------------------------------------------------------------------------
@runtime_checkable
class TemplateProtocol(Protocol):
    """模板必须实现的三方法（P4 提供实现；本文件只定义形状）。

    实现纪律（逐条对应 `TEMPLATE_FORBIDDEN`）：
      - 只读 `ctx.params` 与 `ctx.relative_inputs` 下的输入；
      - 只写 `ctx.relative_artifacts` / `logs` / `tmp`；
      - 不联网、不起子进程、不读凭据、不写 evidence/DB/状态；
      - 不返回裁决；产物哈希不自报。
    """

    def prepare(self, ctx: TemplateContext) -> PreparedPlan:
        """校验输入并给出计划；**无副作用**。抛异常 = 模板无法开始（不是结果失败）。"""
        ...

    def run(self, plan: PreparedPlan) -> RunReport:
        """执行计算；只写 artifacts/logs/tmp。返回观测事实，不返回裁决。"""
        ...

    def emit_artifacts(self, report: RunReport) -> tuple[ArtifactDeclaration, ...]:
        """声明写出的产物（相对路径）；不得提供哈希/大小。"""
        ...


class TemplatePhase(StrEnum):
    PREPARE = "prepare"
    RUN = "run"
    EMIT = "emit_artifacts"


# ---------------------------------------------------------------------------
# 5. 契约自检（登记期/preflight 期调用）
# ---------------------------------------------------------------------------
def assert_template_contract(
    implementation: object,
    *,
    template_id: str,
    declared_outputs: Sequence[str],
    dc_candidate: bool = False,
) -> list[str]:
    """检查一个模板实现是否满足协议。

    检查项：
      1. 三个方法存在且可调用（缺一 → `MISSING_METHOD`）；
      2. 实现对象上不得有 `status`/`passed`/`success`/`verdict` 属性（自报裁决）；
      3. 声明的产物名必须与 `declared_outputs` 一致（多声明/少声明都不行）；
      4. 实现模块不得暴露 `FORBIDDEN_TEMPLATE_ATTRS` 中的名字（网络/子进程）；
      5. `dc_candidate=True` 时不得是副作用模板（由 registry 已拦，这里复核）。

    返回违反项列表（空 = 通过）。**不抛异常**：调用方决定是拒绝登记还是记告警。
    """
    problems: list[str] = []
    for method in TEMPLATE_METHODS:
        attr = getattr(implementation, method, None)
        if attr is None or not callable(attr):
            problems.append(
                f"{template_id}: 缺少方法 {method}（{TemplateViolation.MISSING_METHOD.value}）"
            )
    for verdict_attr in ("status", "passed", "success", "verdict", "result"):
        if hasattr(implementation, verdict_attr):
            problems.append(
                f"{template_id}: 不得暴露 {verdict_attr}（模板不裁决）"
            )
    impl_module = type(implementation).__module__
    for forbidden in FORBIDDEN_TEMPLATE_ATTRS:
        if hasattr(implementation, forbidden):
            problems.append(
                f"{template_id}: 模块 {impl_module} 暴露 {forbidden}（网络/子进程禁令）"
            )
    if not declared_outputs:
        problems.append(f"{template_id}: 必须声明至少一个产物")
    if dc_candidate and getattr(implementation, "side_effect_class", "") == "SIDE_EFFECT":
        problems.append(f"{template_id}: 副作用模板不得作为 DC 候选")
    return problems


# ---------------------------------------------------------------------------
# 6. 与 worker 的交接（谁算什么）
# ---------------------------------------------------------------------------
HANDOFF: Final[Mapping[str, str]] = MappingProxyType(
    {
        "params.json": "worker 写；模板只读（UTF-8 无 BOM，字段与 GraphDraft.parameters 一致）",
        "artifacts/*": "模板写；worker 结束后遍历声明、二进制读、算 SHA-256 与字节数",
        "logs/stdout.txt": "worker 重定向子进程 stdout；模板不得自己写同名文件",
        "logs/stderr.txt": "worker 重定向子进程 stderr",
        "logs/sample.jsonl": "worker 写的资源采样（时间/峰值内存/磁盘），模板不写",
        "产物清单": "worker 生成：relative_path + sha256 + size_bytes + attempt_id（四项齐全）",
        "退出码": "worker 从进程句柄读取；模板不得自报退出码",
    }
)


def artifact_manifest_fields() -> tuple[str, ...]:
    """产物清单的字段（验收要求：相对路径 + SHA-256 + 大小 + attempt_id）。"""
    return ("relative_path", "sha256", "size_bytes", "attempt_id")