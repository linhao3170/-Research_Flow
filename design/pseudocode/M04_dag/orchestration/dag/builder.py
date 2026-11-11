"""M04 · orchestration/dag/builder.py — 静态图构建（P3 伪代码）。
阶段：P3「DAG 与执行器」｜追踪：FR-002（DAG 编排）、FR-010（失效传播的图基础）
依赖：M01 contracts（encoding/errors）、M03 config（scheduler.ready_order、limits）、M04 validator/graph_version
不变量：只产出静态图 + 版本 + graph_hash；不产出“下一个跑谁”；不落库；不持 DAG_REGISTER
错误码：TOOL_NOT_ALLOWLISTED（未注册模板/类型）、SCHEMA_INVALID（节点字段/参数/引用）、STATE_TRANSITION_DENIED（整图拒绝，reason=DAG_INVALID）
写入者：**无**。tasks/nodes 的 INSERT 只经 Orchestrator（持 DAG_REGISTER）→ M02 `NodeRepository._insert_planned`
状态：伪代码；不执行、不建库、不跑模板、不连数据库

本文件回答三个问题：

  1. 给定一份 `TaskSpec`，图长什么样？（任务模板 → 节点蓝图 → 节点/边）
  2. 节点 ID 怎么来？（确定性规则，不用 UUID，不用 `node_` 前缀）
  3. 图的身份怎么算？（`graph_hash` 可复算；同输入 ⇒ 同哈希）

**Builder 与 Scheduler 的边界（不可越界）**：

  | 问题 | 谁回答 | 本文件 |
  |---|---|---|
  | 图里有哪些节点、哪些边 | Builder | ✅ 产出 |
  | 图是否合法（环/孤立/规模/引用） | validator | ❌ 不调用、不自证 |
  | 图版本号是多少、能否登记 | graph_version + Orchestrator | ❌ 不写库 |
  | **下一个跑谁、就绪队列、并发、优先级** | Scheduler（P7） | ❌ **绝不产出** |
  | 节点成败、证据、人工批准 | Gate/Verifier/Collector | ❌ 不涉及 |

于是本文件**没有**、也**不得有** `next_node()` / `ready_set()` / `pick_next()` / `schedule()`
这类函数；`assert_no_scheduling_surface()` 把这条边界做成可执行自检。

DEC-01（创建写者）在本文件的落点：

  - Builder 是**纯函数**：输入 TaskSpec + base_version，输出 `GraphDraft`；
  - 不 import 仓储、不拿 capability、不调用 `StateMachine.transition()`；
  - 图的 INSERT 由 Orchestrator 调 M02 `NodeRepository._insert_planned(capability=DAG_REGISTER)`；
  - 因此 `GraphDraft` 只是**内存值**，落地与版本登记见 `graph_version.py`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Mapping, Protocol, Sequence

if TYPE_CHECKING:  # 仅类型；P3 不在运行期依赖应用包
    from researchflow.contracts.encoding import JsonValue

__all__ = [
    "BOUNDARY_RULES",
    "BUILD_VIOLATIONS",
    "FORBIDDEN_SURFACE",
    "MAINLINE_DAG_SKETCH",
    "NODE_ID_RESERVED",
    "RESERVED_NODE_NAMES",
    "BuildRejected",
    "BuildViolation",
    "Edge",
    "GraphBlueprint",
    "GraphDraft",
    "NodeBlueprint",
    "NodeDraft",
    "NodeIdRule",
    "RetryPolicy",
    "TaskSpecView",
    "TemplateCatalogPort",
    "TemplateDescriptor",
    "assert_no_scheduling_surface",
    "build_graph",
]

SCHEMA_VERSION: Final[str] = "1.0"
RETRY_MAX_ATTEMPTS_T0: Final[int] = 2  # T0 模板默认值；非契约上限（M03 limits.max_attempts_cap 才是上限）


# ---------------------------------------------------------------------------
# 1. 拒绝码：本地 build 违规，**不是**新的 API 错误码
# ---------------------------------------------------------------------------
class BuildViolation(StrEnum):
    """Builder 侧的具体拒绝原因；对外错误码由 `BUILD_VIOLATIONS` 映射到 M01 已注册码。

    纪律（M01 errors.py）：注册表仍是 27 条，**本文件不新增错误码**；
    下面这些是“原因码”，等价于 `transitions.ReasonCode` 的角色，写进 `detail.reason`
    与结构化日志，不进 API 文档的错误码列。
    """

    UNSUPPORTED_BLUEPRINT = "UNSUPPORTED_BLUEPRINT"        # 任务模板不存在/非图模板
    TEMPLATE_NOT_REGISTERED = "TEMPLATE_NOT_REGISTERED"    # 节点模板未注册
    NODE_TYPE_NOT_ALLOWED = "NODE_TYPE_NOT_ALLOWED"        # 节点类型不在域包白名单
    PARAM_INVALID = "PARAM_INVALID"                        # 参数缺失/类型不符/绑定路径不存在
    PARAM_UNKNOWN = "PARAM_UNKNOWN"                        # 参数 Schema 未声明的键
    NODE_ID_INVALID = "NODE_ID_INVALID"                    # 违反 Node ID 字符集/长度
    NODE_ID_RESERVED = "NODE_ID_RESERVED"                  # 命中 Windows 保留设备名
    DUPLICATE_NODE_ID = "DUPLICATE_NODE_ID"                # 实例展开后撞名
    DUPLICATE_INSTANCE = "DUPLICATE_INSTANCE"              # fan-out 实例键重复
    UNKNOWN_BLUEPRINT_EDGE = "UNKNOWN_BLUEPRINT_EDGE"      # 蓝图依赖指向不存在的 key
    OUTPUT_UNKNOWN = "OUTPUT_UNKNOWN"                      # 引用蓝图未声明的产物
    INPUT_BINDING_INVALID = "INPUT_BINDING_INVALID"        # input_refs 绑定无法静态解析
    REQUIRED_CHECKS_EMPTY = "REQUIRED_CHECKS_EMPTY"        # 必检项为空（05 §3.1）
    GRAPH_EMPTY = "GRAPH_EMPTY"                            # 展开后 0 节点
    PARAMS_HASH_MISMATCH = "PARAMS_HASH_MISMATCH"          # 参数与 parameters_hash 不一致


@dataclass(frozen=True, slots=True)
class ViolationSpec:
    error_code: str          # 必须是 M01 注册表里的码
    http_status: int
    reason: str              # 写进 detail.reason / DENIED 审计的 reason_code
    note: str


# 违规原因 → 已注册错误码。为什么这样分：
#   - 未注册模板/节点类型 = “工具契约未登记” → TOOL_NOT_ALLOWLISTED(403)，与 errors.py 的 trigger 一致；
#   - 单节点字段/参数/引用形态 = 请求体问题 → SCHEMA_INVALID(422)；
#   - 整图问题（空图/撞名后的图不成立）留给 validator 的 409 路径，本文件只用 422/403。
BUILD_VIOLATIONS: Final[Mapping[BuildViolation, ViolationSpec]] = MappingProxyType(
    {
        BuildViolation.UNSUPPORTED_BLUEPRINT: ViolationSpec(
            "TOOL_NOT_ALLOWLISTED", 403, "TEMPLATE_NOT_REGISTERED",
            "任务模板未在模板注册表；先登记再建图（P4/WP-05）",
        ),
        BuildViolation.TEMPLATE_NOT_REGISTERED: ViolationSpec(
            "TOOL_NOT_ALLOWLISTED", 403, "TEMPLATE_NOT_REGISTERED",
            "节点模板未注册；不得按名字猜模板",
        ),
        BuildViolation.NODE_TYPE_NOT_ALLOWED: ViolationSpec(
            "TOOL_NOT_ALLOWLISTED", 403, "NODE_TYPE_NOT_ALLOWED",
            "05 §3.1「必须在域包允许类型内」",
        ),
        BuildViolation.PARAM_INVALID: ViolationSpec(
            "SCHEMA_INVALID", 422, "PARAM_INVALID",
            "参数绑定失败：field_path 指到 parameters.<key>",
        ),
        BuildViolation.PARAM_UNKNOWN: ViolationSpec(
            "SCHEMA_INVALID", 422, "PARAM_UNKNOWN",
            "未知参数默认拒绝（OQ-CT-08 的收紧方向）",
        ),
        BuildViolation.NODE_ID_INVALID: ViolationSpec(
            "SCHEMA_INVALID", 422, "NODE_ID_INVALID",
            "05 §3.1：任务内唯一、不得含路径分隔符；字符集见 ENCODING_RULES §1",
        ),
        BuildViolation.NODE_ID_RESERVED: ViolationSpec(
            "SCHEMA_INVALID", 422, "NODE_ID_RESERVED",
            "node_id 会成为目录名；Windows 保留设备名不得使用（workspace.py 同规则）",
        ),
        BuildViolation.DUPLICATE_NODE_ID: ViolationSpec(
            "SCHEMA_INVALID", 422, "DUPLICATE_NODE_ID",
            "05 §3.3：node_id 重复拒绝",
        ),
        BuildViolation.DUPLICATE_INSTANCE: ViolationSpec(
            "SCHEMA_INVALID", 422, "DUPLICATE_INSTANCE",
            "fan-out 实例键重复会让节点撞名；按参数数组原序展开、重复即拒绝",
        ),
        BuildViolation.UNKNOWN_BLUEPRINT_EDGE: ViolationSpec(
            "SCHEMA_INVALID", 422, "UNKNOWN_BLUEPRINT_EDGE",
            "蓝图内部错误：依赖 key 不存在（属模板缺陷，不是用户输入）",
        ),
        BuildViolation.OUTPUT_UNKNOWN: ViolationSpec(
            "SCHEMA_INVALID", 422, "OUTPUT_UNKNOWN",
            "05 §3.1 input_refs「必须可解析到已有产物引用」",
        ),
        BuildViolation.INPUT_BINDING_INVALID: ViolationSpec(
            "SCHEMA_INVALID", 422, "INPUT_BINDING_INVALID",
            "input_refs 由蓝图绑定生成，不接受用户直接注入",
        ),
        BuildViolation.REQUIRED_CHECKS_EMPTY: ViolationSpec(
            "SCHEMA_INVALID", 422, "REQUIRED_CHECKS_EMPTY",
            "05 §3.1/§3.3：required_checks 空数组拒绝",
        ),
        BuildViolation.GRAPH_EMPTY: ViolationSpec(
            "SCHEMA_INVALID", 422, "GRAPH_EMPTY",
            "0 节点的图不是合法图；不得“空图先跑起来”",
        ),
        BuildViolation.PARAMS_HASH_MISMATCH: ViolationSpec(
            "SCHEMA_INVALID", 422, "PARAMS_HASH_MISMATCH",
            "05 §3.1：parameters_hash 必须与解析后的参数一致",
        ),
    }
)


class BuildRejected(RuntimeError):
    """建图拒绝；携带原因码、错误码、涉及节点与字段路径（负例断言这两个字段）。"""

    def __init__(
        self,
        violation: BuildViolation,
        *,
        nodes: Sequence[str] = (),
        field_path: str | None = None,
        detail: str = "",
    ) -> None:
        spec = BUILD_VIOLATIONS[violation]
        self.violation = violation
        self.error_code = spec.error_code
        self.http_status = spec.http_status
        self.reason = spec.reason
        self.nodes: tuple[str, ...] = tuple(nodes)
        self.field_path = field_path
        self.detail = detail
        suffix = f"；{detail}" if detail else ""
        where = f"；nodes={list(self.nodes)}" if self.nodes else ""
        super().__init__(f"{spec.error_code}/{spec.reason}：{violation.value}{where}{suffix}")


# ---------------------------------------------------------------------------
# 2. 端口：模板目录、Node ID 规则（都由调用方注入，Builder 不查库）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TemplateDescriptor:
    """节点模板的**静态**描述；真正的模板实现属 P4/WP-05，本文件不内含模板本体。

    注意：这里没有 `entry_point` 字段的“命令字符串”形态。
    模板只能以 `module + symbol` 形式登记（见 M05 registry.py 的强制校验），
    Builder 不解析、不拼接任何可执行命令。
    """

    template_id: str                 # name@MAJOR.MINOR.PATCH
    node_type: str                   # 示例 ml.train.classifier
    side_effect_class: str           # PURE_FUNCTION / PURE_ARTIFACT / SIDE_EFFECT
    outputs: tuple[str, ...]         # 产物名（artifact:// 后面的名字），必须稳定
    inputs: tuple[str, ...]          # 允许消费的产物名
    default_params: Mapping[str, "JsonValue"] = field(default_factory=dict)
    required_checks: tuple[str, ...] = ()
    max_attempts: int = RETRY_MAX_ATTEMPTS_T0
    backoff_sec: float = 0.0
    dc_candidate: bool = False       # T2 才用；T0 只登记，不据此跳过任何节点
    resource_caps: Mapping[str, int] = field(default_factory=dict)  # wall_time_sec/memory_mb/disk_mb


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    backoff_sec: float

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("retry_policy.max_attempts 必须 ≥ 1（05 §3.1）")
        if self.backoff_sec < 0:
            raise ValueError("retry_policy.backoff_sec 不得为负（05 §3.1）")


@dataclass(frozen=True, slots=True)
class NodeBlueprint:
    """蓝图节点：一个 `key` 可展开为 1..N 个真实节点（fan-out）。"""

    key: str
    template_id: str
    depends_on_keys: tuple[str, ...] = ()
    # 参数绑定：node 参数名 → "parameters.<path>"（从 TaskSpec.parameters 取值）
    # 或 "literal:<json>"。**只允许这两种前缀**，不接受任意表达式。
    param_bindings: Mapping[str, str] = field(default_factory=dict)
    fan_out_key: str | None = None   # 从 parameters.<key> 的数组展开；None = 单实例
    required_checks: tuple[str, ...] = ()
    retry_policy: RetryPolicy | None = None


@dataclass(frozen=True, slots=True)
class GraphBlueprint:
    """任务模板 → 图的静态蓝图（示例见 `MAINLINE_DAG_SKETCH`）。"""

    template_id: str
    nodes: tuple[NodeBlueprint, ...]
    # 产物名 → 产生它的蓝图 key；用于把 input_refs 静态解析到上游节点
    artifact_producers: Mapping[str, str] = field(default_factory=dict)


class TemplateCatalogPort(Protocol):
    """模板目录的只读端口（P4/WP-05 实现；P3 只定义形状）。

    三条纪律：
      - 未注册模板必须返回 `None` 或抛 `KeyError`，**不得**回退到“同名 latest”；
      - 版本必须精确匹配 `name@X.Y.Z`，不接受区间/`latest`/`^1.0`；
      - `node_type_allowed` 来自 DomainPack 的工具契约登记，不得由调用方自报。
    """

    def task_template(self, template_id: str) -> GraphBlueprint | None:
        ...

    def node_template(self, template_id: str) -> TemplateDescriptor | None:
        ...

    def node_type_allowed(self, node_type: str) -> bool:
        ...


class NodeIdRule(Protocol):
    """Node ID 形态校验的端口。

    唯一正则来源是 `researchflow.contracts.models.NODE_ID_PATTERN`
    （ENCODING_RULES §1：Node 无前缀）。**本文件不复制第二份正则**，
    避免两处漂移；测试可用桩实现。
    """

    def is_valid(self, node_id: str) -> bool:
        ...


# Windows 保留设备名：node_id 会直接成为目录名，命中即拒绝（fail-closed）。
# 名字来源：Win32 文件命名规则；这里是**目录名安全**，不是契约字段约束。
RESERVED_NODE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "con", "prn", "aux", "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)
NODE_ID_RESERVED: Final[frozenset[str]] = RESERVED_NODE_NAMES


# ---------------------------------------------------------------------------
# 3. 输入与输出值对象
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TaskSpecView:
    """Builder 需要的 TaskSpec 子集；字段名与 `contracts/taskspec.schema.json` 一致。

    刻意不做的三件事：
      - 不解析 `dataset_ref.uri`（是否逃逸由 WP-02/WP-05 校验，这里只用 sha256 参与 graph_hash）；
      - 不读 `limits`（执行期预算由 M05 worker/process_control 执行，Builder 不裁决）；
      - 不接受“用户自报的节点列表”（图只能由任务模板展开，防止任意代码注入）。
    """

    task_id: str
    template_id: str
    domain_pack: str
    parameters: Mapping[str, "JsonValue"]
    dataset_sha256: str
    ruleset_hash: str


@dataclass(frozen=True, slots=True)
class NodeDraft:
    """一个待登记节点：字段与 M02 `NodeRow` 的 INSERT 列一一对应（外加参数与参数哈希）。"""

    node_id: str
    node_type: str
    template_id: str
    schema_version: str
    depends_on: tuple[str, ...]
    input_refs: tuple[str, ...]
    parameters_hash: str
    side_effect_class: str
    retry_policy: RetryPolicy
    required_checks: tuple[str, ...]
    # 参数只在内存里传给 Executor；**不入库**（06 §1.3 的 nodes 表无参数列），
    # 由 (TaskSpec.parameters, 蓝图绑定) 确定性推导，用 parameters_hash 校验一致性。
    parameters: Mapping[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class Edge:
    """依赖边：`src` 是前驱，`dst` 依赖 `src`。方向固定，不得反写。"""

    src: str
    dst: str


@dataclass(frozen=True, slots=True)
class GraphDraft:
    """Builder 的唯一产出：静态图 + 版本 + 身份哈希。

    这是**内存值**。它没有 repository 字段、没有 capability 字段、没有 `save()`，
    结构上就无法“顺手落库”。
    """

    task_id: str
    graph_version: int                 # 本稿“为哪个版本构建”；登记时须等于 store.last+1
    graph_hash: str                    # 64 位小写十六进制；同输入 ⇒ 同哈希
    template_id: str
    domain_pack: str
    dataset_sha256: str
    ruleset_hash: str
    nodes: tuple[NodeDraft, ...]       # 按 node_id 字典序（确定性）
    edges: tuple[Edge, ...]            # 按 (src, dst) 字典序
    topology_order: tuple[str, ...]    # `topological_then_node_id`（M03 scheduler.ready_order）

    # -- 供 validator 使用的只读视图（结构上满足 GraphView） ----------------
    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(n.node_id for n in self.nodes)

    @property
    def node_types(self) -> Mapping[str, str]:
        return MappingProxyType({n.node_id: n.node_type for n in self.nodes})

    @property
    def template_ids(self) -> Mapping[str, str]:
        return MappingProxyType({n.node_id: n.template_id for n in self.nodes})

    @property
    def dependencies(self) -> Mapping[str, tuple[str, ...]]:
        return MappingProxyType({n.node_id: n.depends_on for n in self.nodes})

    @property
    def input_refs(self) -> Mapping[str, tuple[str, ...]]:
        return MappingProxyType({n.node_id: n.input_refs for n in self.nodes})

    @property
    def edge_pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple((e.src, e.dst) for e in self.edges)

    def artifacts_declared(self) -> tuple[str, ...]:
        """本图声明产出的全部产物名（给 validator 做引用完整性用）。"""
        return tuple(sorted({ref.rsplit("/", 1)[-1] for n in self.nodes for ref in n.input_refs}))


# ---------------------------------------------------------------------------
# 4. 主流程
# ---------------------------------------------------------------------------
def build_graph(
    task: TaskSpecView,
    *,
    base_version: int,
    catalog: TemplateCatalogPort,
    node_id_rule: NodeIdRule,
    requested_version: int | None = None,
) -> GraphDraft:
    """从 TaskSpec 生成静态图。

    输入：
      - `task`：TaskSpec 子集（模板、参数、数据哈希、规则哈希）；
      - `base_version`：该任务当前已登记的图版本（首次建图为 0）；本函数**不读库**，
        由调用方从 `graph_version.GraphVersionStore` 读出后传入；
      - `catalog` / `node_id_rule`：只读端口。

    输出：`GraphDraft`（未校验、未登记）。校验由 `validator.validate_graph`，
    登记由 `graph_version.GraphRegistrar` —— 三者职责不合并。

    副作用：**无**（纯函数；不写文件、不写库、不记日志、不取时间）。

    不变量：
      - `graph_version == base_version + 1`；若显式给 `requested_version`，必须相等，
        否则 `BuildRejected(PARAM_INVALID)`（防止调用方偷偷回退版本）；
      - `nodes` 按 `node_id` 排序、`edges` 按 `(src,dst)` 排序、`topology_order` 由
        `topological_then_node_id` 产生 —— 三者都不依赖 dict 遍历顺序；
      - 同 `(task, base_version)` 两次调用必须得到完全相同的 `graph_hash`。

    错误（全部 `BuildRejected`，带已注册 error_code）：
      - 蓝图不存在 → 403 `TEMPLATE_NOT_REGISTERED`；
      - 节点模板未注册/类型不在白名单 → 403 `TOOL_NOT_ALLOWLISTED`；
      - 参数/ID/引用问题 → 422 `SCHEMA_INVALID`。
    """
    # 1) 任务模板 → 蓝图；未注册一律拒绝，不做“猜模板”。
    blueprint = catalog.task_template(task.template_id)
    if blueprint is None:
        raise BuildRejected(
            BuildViolation.UNSUPPORTED_BLUEPRINT,
            field_path="template_id",
            detail=f"task template {task.template_id!r} 未注册",
        )

    # 2) 版本必须严格递增 1；不做“自动修正”。
    expected_version = base_version + 1
    if expected_version < 1:
        raise BuildRejected(BuildViolation.PARAM_INVALID, field_path="graph_version",
                            detail="图版本从 1 开始")
    if requested_version is not None and requested_version != expected_version:
        raise BuildRejected(
            BuildViolation.PARAM_INVALID,
            field_path="graph_version",
            detail=f"requested={requested_version} 但 base+1={expected_version}",
        )

    # 3) 先把“每个蓝图 key 展开成哪些实例”算成一个纯映射（只依赖 TaskSpec.parameters），
    #    再逐节点展开。两步分开的理由：上游/下游必须用**同一份**实例键，
    #    否则会拼出悬空依赖；用纯映射而非模块级缓存，保证无隐藏状态、可并发。
    instance_index = _plan_instances(blueprint, task)
    resolved: list[_ResolvedNode] = []
    for bp in blueprint.nodes:
        resolved.extend(
            _expand_blueprint_node(bp, task, blueprint, catalog, node_id_rule, instance_index)
        )

    if not resolved:
        raise BuildRejected(BuildViolation.GRAPH_EMPTY, detail="展开后 0 节点")

    # 4) 撞名检查（实例展开后仍可能撞名，例如两个蓝图 key 拼出同一 ID）。
    seen: dict[str, str] = {}
    for node in resolved:
        if node.node_id in seen:
            raise BuildRejected(
                BuildViolation.DUPLICATE_NODE_ID,
                nodes=(node.node_id,),
                field_path="nodes",
                detail=f"与蓝图 key {seen[node.node_id]!r} 展开结果撞名",
            )
        seen[node.node_id] = node.blueprint_key

    # 5) 边：由 depends_on 实例集合生成；排序保证确定性。
    edges = _derive_edges(resolved)

    # 6) 深度（最长路径）；用于 depends_on 排序、拓扑序与规模校验的输入。
    depth = _depths([n.node_id for n in resolved], edges)

    # 7) depends_on 的规范顺序：(depth, node_id)。NodeSpec.depends_on 是数组，
    #    JCS 不排数组，所以“顺序”必须由 Builder 固定，否则 graph_hash 不稳定。
    ordered: list[NodeDraft] = []
    for node in resolved:
        deps = tuple(sorted(node.depends_on, key=lambda d: (depth.get(d, 0), d)))
        ordered.append(
            NodeDraft(
                node_id=node.node_id,
                node_type=node.descriptor.node_type,
                template_id=node.descriptor.template_id,
                schema_version=SCHEMA_VERSION,
                depends_on=deps,
                input_refs=tuple(node.input_refs),
                parameters_hash=node.parameters_hash,
                side_effect_class=node.descriptor.side_effect_class,
                retry_policy=node.retry_policy,
                required_checks=node.required_checks,
                parameters=node.parameters,
            )
        )
    ordered.sort(key=lambda n: n.node_id)

    # 8) 拓扑序：Kahn + 最小堆，键为 node_id（M03 scheduler.ready_order 的确定性来源）。
    topology = _topological_order([n.node_id for n in ordered],
                                  [(e.src, e.dst) for e in edges])

    # 9) 图身份：只覆盖语义字段，不含时间/task_id，保证跨任务可复算。
    graph_hash = _hash_graph_payload(
        graph_version=expected_version,
        template_id=task.template_id,
        dataset_sha256=task.dataset_sha256,
        ruleset_hash=task.ruleset_hash,
        nodes=ordered,
        edges=edges,
    )

    return GraphDraft(
        task_id=task.task_id,
        graph_version=expected_version,
        graph_hash=graph_hash,
        template_id=task.template_id,
        domain_pack=task.domain_pack,
        dataset_sha256=task.dataset_sha256,
        ruleset_hash=task.ruleset_hash,
        nodes=tuple(ordered),
        edges=tuple(edges),
        topology_order=topology,
    )


# ---------------------------------------------------------------------------
# 5. 实例展开与绑定
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _ResolvedNode:
    blueprint_key: str
    node_id: str
    descriptor: TemplateDescriptor
    parameters: Mapping[str, "JsonValue"]
    parameters_hash: str
    input_refs: tuple[str, ...]
    depends_on: tuple[str, ...]
    retry_policy: RetryPolicy
    required_checks: tuple[str, ...]


def _plan_instances(
    blueprint: GraphBlueprint, task: TaskSpecView
) -> Mapping[str, tuple[str | None, ...]]:
    """纯函数：蓝图 key → 实例键元组（单实例为 `(None,)`）。

    只读 `task.parameters`，不读蓝图其它节点，因此可以在展开前一次算完。
    fan-out 键：必须是非空数组；元素必须是字符串/整数；折叠后重复或为空即拒绝。
    """
    index: dict[str, tuple[str | None, ...]] = {}
    for bp in blueprint.nodes:
        if bp.fan_out_key is None:
            index[bp.key] = (None,)
            continue
        raw = task.parameters.get(bp.fan_out_key)
        if not isinstance(raw, list) or not raw:
            raise BuildRejected(
                BuildViolation.PARAM_INVALID,
                field_path=f"parameters.{bp.fan_out_key}",
                detail="fan-out 键必须是非空数组",
            )
        keys = tuple(_instance_key(v, bp.fan_out_key) for v in raw)
        if len(set(keys)) != len(keys):
            raise BuildRejected(
                BuildViolation.DUPLICATE_INSTANCE,
                field_path=f"parameters.{bp.fan_out_key}",
                detail="实例键重复（如 ['rf','rf']）会让节点撞名",
            )
        index[bp.key] = keys
    return MappingProxyType(index)


def _expand_blueprint_node(
    bp: NodeBlueprint,
    task: TaskSpecView,
    blueprint: GraphBlueprint,
    catalog: TemplateCatalogPort,
    node_id_rule: NodeIdRule,
    instance_index: Mapping[str, tuple[str | None, ...]],
) -> list[_ResolvedNode]:
    """把一个蓝图节点展开为 1..N 个实例。

    步骤（编号与代码内注释对应）：
      1. 取模板描述；未注册 → 403；节点类型不在白名单 → 403；
      2. 从 `instance_index` 取实例键（单实例为 None）；
      3. 每个实例：生成 node_id → 校验字符集/保留名 → 绑定参数 → 算 parameters_hash；
      4. 解析依赖 key → 实例集合（fan-out 上游默认“全体实例”）；
      5. 生成 input_refs：只引用**上游**声明的产物名，格式固定 `artifact://<name>`。

    错误：全部 `BuildRejected`；不做“跳过坏节点继续建图”。
    """
    # 1) 模板与类型
    descriptor = catalog.node_template(bp.template_id)
    if descriptor is None:
        raise BuildRejected(
            BuildViolation.TEMPLATE_NOT_REGISTERED,
            nodes=(bp.key,),
            field_path="template_id",
            detail=f"{bp.template_id!r} 未注册",
        )
    if not catalog.node_type_allowed(descriptor.node_type):
        raise BuildRejected(
            BuildViolation.NODE_TYPE_NOT_ALLOWED,
            nodes=(bp.key,),
            field_path="node_type",
            detail=f"{descriptor.node_type!r} 不在域包允许类型内",
        )

    # 2) 实例键（已在本轮建图开始时统一计算，绝不二次推导）
    instance_keys = instance_index[bp.key]

    out: list[_ResolvedNode] = []
    for inst in instance_keys:
        # 3a) node_id 生成规则（确定性、无 UUID、无 node_ 前缀）：
        #     单实例：<blueprint.key>
        #     fan-out：<blueprint.key>__<instance_key>
        node_id = bp.key if inst is None else f"{bp.key}__{inst}"
        _assert_node_id(node_id, node_id_rule)

        # 3b) 参数绑定
        params = _bind_params(bp, descriptor, task, inst)
        params_hash = _hash_params(params)

        # 3c) 依赖：解析蓝图 key → 该 key 的实例集合
        deps = _resolve_dependencies(bp, blueprint, instance_index)

        # 3d) 输入引用：只允许上游产物；
        input_refs = _derive_input_refs(bp, descriptor, deps, blueprint, instance_index)

        retry = bp.retry_policy or RetryPolicy(
            max_attempts=descriptor.max_attempts,
            backoff_sec=descriptor.backoff_sec,
        )
        checks = tuple(bp.required_checks or descriptor.required_checks)
        if not checks:
            raise BuildRejected(
                BuildViolation.REQUIRED_CHECKS_EMPTY,
                nodes=(node_id,),
                field_path="required_checks",
                detail="必检项空数组一律拒绝（05 §3.1）",
            )
        out.append(
            _ResolvedNode(
                blueprint_key=bp.key,
                node_id=node_id,
                descriptor=descriptor,
                parameters=params,
                parameters_hash=params_hash,
                input_refs=input_refs,
                depends_on=deps,
                retry_policy=retry,
                required_checks=checks,
            )
        )
    return out


def _instance_key(value: "JsonValue", fan_out_key: str) -> str:
    """把 fan-out 数组元素转成稳定的实例键。

    规则：字符串 → 小写、`[^a-z0-9_]+` 整体折叠为 `_`、去首尾 `_`；数字 → `10` 的十进制；
    其他类型 → `PARAM_INVALID`。折叠后为空 → `PARAM_INVALID`（不得用空串拼出 `x__`）。
    """
    if isinstance(value, bool):  # bool 是 int 子类，必须先判
        raise BuildRejected(BuildViolation.PARAM_INVALID,
                            field_path=f"parameters.{fan_out_key}", detail="布尔不能作为实例键")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        folded = "".join(ch if (ch.isascii() and (ch.islower() or ch.isdigit() or ch == "_"))
                         else "_" for ch in value.lower())
        folded = folded.strip("_")
        while "__" in folded:
            folded = folded.replace("__", "_")
        if not folded:
            raise BuildRejected(BuildViolation.PARAM_INVALID,
                                field_path=f"parameters.{fan_out_key}",
                                detail="实例键折叠后为空")
        return folded
    raise BuildRejected(BuildViolation.PARAM_INVALID,
                        field_path=f"parameters.{fan_out_key}",
                        detail=f"不支持的实例键类型 {type(value).__name__}")


def _assert_node_id(node_id: str, rule: NodeIdRule) -> None:
    """Node ID 的四道闸：形态 → 长度 → 保留名 → 路径分隔符。"""
    if not isinstance(node_id, str) or not node_id:
        raise BuildRejected(BuildViolation.NODE_ID_INVALID, nodes=(str(node_id),))
    # 长度：M02 schema 的 node_id CHECK 是 1..128；超长会在 INSERT 阶段才报错，这里提前拒。
    if len(node_id) > 128:
        raise BuildRejected(BuildViolation.NODE_ID_INVALID, nodes=(node_id,),
                            detail="node_id 超过 128 字符")
    if "/" in node_id or "\\" in node_id:
        raise BuildRejected(BuildViolation.NODE_ID_INVALID, nodes=(node_id,),
                            detail="node_id 不得含路径分隔符（05 §3.1）")
    if node_id.lower() in RESERVED_NODE_NAMES:
        raise BuildRejected(BuildViolation.NODE_ID_RESERVED, nodes=(node_id,))
    if node_id.endswith(".") or node_id.endswith(" "):
        raise BuildRejected(BuildViolation.NODE_ID_INVALID, nodes=(node_id,),
                            detail="Windows 会静默去掉结尾的句点/空格，导致目录名与 ID 不一致")
    if not rule.is_valid(node_id):
        raise BuildRejected(BuildViolation.NODE_ID_INVALID, nodes=(node_id,),
                            detail="不匹配 NODE_ID_PATTERN")


def _bind_params(
    bp: NodeBlueprint,
    descriptor: TemplateDescriptor,
    task: TaskSpecView,
    instance: str | None,
) -> Mapping[str, "JsonValue"]:
    """按 `param_bindings` 解析参数。

    绑定语法只有两种，**没有第三种**（拒绝任意表达式/模板字符串）：
      - `"parameters.<a>.<b>"`：从 TaskSpec.parameters 逐层取值；
      - `"literal:<json>"`：字面量（仅允许标量/数组/对象）。
    另外允许注入两个保留键（模板声明后才注入，未声明不注入）：
      - `"$instance"` → 当前 fan-out 实例原文（字符串或数字）；
      - `"$seed"` → `parameters.seed`（05 §2.1 要求记录到 Split Manifest）。

    未在模板 `default_params` 或绑定里出现的键不会凭空出现；
    模板 Schema 的“未知键拒绝”由 registry/worker 的 preflight 再验一次（纵深防御）。
    """
    params: dict[str, "JsonValue"] = dict(descriptor.default_params)
    for name, binding in bp.param_bindings.items():
        if binding.startswith("parameters."):
            path = binding[len("parameters."):].split(".")
            value: "JsonValue" = dict(task.parameters)
            for part in path:
                if not isinstance(value, Mapping) or part not in value:
                    raise BuildRejected(
                        BuildViolation.PARAM_INVALID,
                        field_path=f"parameters.{part}",
                        detail=f"绑定 {binding!r} 在 TaskSpec.parameters 中不存在",
                    )
                value = value[part]  # type: ignore[assignment]
            params[name] = value
        elif binding.startswith("literal:"):
            params[name] = _parse_literal(binding[len("literal:"):])
        else:
            raise BuildRejected(
                BuildViolation.INPUT_BINDING_INVALID,
                field_path=f"parameters.{name}",
                detail=f"绑定前缀只允许 parameters./literal:，收到 {binding[:16]!r}",
            )
    if instance is not None and "$instance" in descriptor.default_params:
        params["$instance"] = instance
    if "$seed" in descriptor.default_params:
        seed = task.parameters.get("seed")
        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            raise BuildRejected(BuildViolation.PARAM_INVALID, field_path="parameters.seed",
                                detail="seed 必须是非负整数（05 §2.1）")
        params["$seed"] = seed
    return MappingProxyType(params)


def _parse_literal(text: str) -> "JsonValue":
    """解析 `literal:` 后面的 JSON 字面量；非 JSON 一律拒绝（不 eval、不 exec）。"""
    import json  # 局部导入：伪代码只表达意图，避免顶部堆库

    # LIB: json.loads（严格模式；NaN/Infinity 由 M01 parsing 层拒绝，这里再查一次）
    try:
        value = json.loads(text, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise BuildRejected(BuildViolation.PARAM_INVALID, field_path="parameters",
                            detail=f"literal 不是合法 JSON：{type(exc).__name__}") from exc
    return value


def _reject_constant(name: str) -> "JsonValue":
    raise BuildRejected(BuildViolation.PARAM_INVALID, field_path="parameters",
                        detail=f"literal 含非有限数 {name}")


def _resolve_dependencies(
    bp: NodeBlueprint,
    blueprint: GraphBlueprint,
    instance_index: Mapping[str, tuple[str | None, ...]],
) -> tuple[str, ...]:
    """把蓝图依赖 key 解析成实例 ID 集合。

    规则：
      - 依赖 key 必须存在于蓝图节点集合，否则 `UNKNOWN_BLUEPRINT_EDGE`（模板缺陷）；
      - 上游是 fan-out 节点时，默认依赖其**全体实例**（保守：任一实例变化都要失效下游）；
      - 显式 `<key>[*]` 与默认等价，保留写法便于评审；不支持 `<key>[0]` 这类下标依赖。
    """
    known = {n.key: n for n in blueprint.nodes}
    out: list[str] = []
    for raw in bp.depends_on_keys:
        if raw.endswith("[*]"):
            key = raw[:-3]
        elif "[" in raw or "]" in raw:
            raise BuildRejected(
                BuildViolation.UNKNOWN_BLUEPRINT_EDGE,
                nodes=(bp.key,),
                field_path="depends_on",
                detail=f"不支持下标依赖 {raw!r}；只允许 <key> 或 <key>[*]",
            )
        else:
            key = raw
        target = known.get(key)
        if target is None:
            raise BuildRejected(
                BuildViolation.UNKNOWN_BLUEPRINT_EDGE,
                nodes=(bp.key,),
                field_path="depends_on",
                detail=f"蓝图依赖 {raw!r} 不存在",
            )
        for inst in instance_index[target.key]:
            out.append(target.key if inst is None else f"{target.key}__{inst}")
    return tuple(dict.fromkeys(out))  # 去重且保序（重复依赖由 validator 的 DUPLICATE_EDGE 再抓）


def _derive_input_refs(
    bp: NodeBlueprint,
    descriptor: TemplateDescriptor,
    deps: tuple[str, ...],
    blueprint: GraphBlueprint,
    instance_index: Mapping[str, tuple[str | None, ...]],
) -> tuple[str, ...]:
    """生成 `input_refs`（`artifact://<name>`，形态取自 05 §3.2 示例）。

    规则：
      1. 只允许引用**上游**（直接依赖）产出的产物名；
      2. 产物名 → 生产者的映射来自蓝图 `artifact_producers`，缺失 → `OUTPUT_UNKNOWN`；
      3. 生产者的任一实例必须是本节点的直接前驱，否则 → `INPUT_BINDING_INVALID`；
      4. 去重保序；空 → 允许（根节点无输入）。
    **不接受用户输入里的 input_refs**：图只能由蓝图生成，避免任意读取。
    """
    refs: list[str] = []
    dep_set = set(deps)
    for name in descriptor.inputs:
        producer_key = blueprint.artifact_producers.get(name)
        if producer_key is None:
            raise BuildRejected(
                BuildViolation.OUTPUT_UNKNOWN,
                nodes=(bp.key,),
                field_path="input_refs",
                detail=f"产物 {name!r} 没有生产者（蓝图 artifact_producers 缺失）",
            )
        producer_instances = instance_index.get(producer_key)
        if producer_instances is None:
            raise BuildRejected(
                BuildViolation.OUTPUT_UNKNOWN,
                nodes=(bp.key,),
                field_path="input_refs",
                detail=f"产物 {name!r} 的生产者 {producer_key!r} 不在蓝图内",
            )
        producer_ids = {
            producer_key if inst is None else f"{producer_key}__{inst}"
            for inst in producer_instances
        }
        if not (producer_ids & dep_set):
            raise BuildRejected(
                BuildViolation.INPUT_BINDING_INVALID,
                nodes=(bp.key,),
                field_path="input_refs",
                detail=f"产物 {name!r} 的生产者不是本节点的直接前驱",
            )
        refs.append(f"artifact://{name}")
    return tuple(dict.fromkeys(refs))


def _derive_edges(resolved: Sequence[_ResolvedNode]) -> list[Edge]:
    """由 depends_on 生成边；按 (src,dst) 排序。重复依赖不去重（留给 validator 报错）。"""
    edges = [Edge(src=dep, dst=node.node_id) for node in resolved for dep in node.depends_on]
    edges.sort(key=lambda e: (e.src, e.dst))
    return edges


def _depths(node_ids: Sequence[str], edges: Sequence[Edge]) -> dict[str, int]:
    """最长路径深度；有环时返回可达部分（环由 validator 负责报错，这里不吞）。

    实现：Kahn 分层；未能出队的节点（环上节点）深度记为 0 且不参与排序决策。
    """
    indeg = {n: 0 for n in node_ids}
    adj: dict[str, list[str]] = {n: [] for n in node_ids}
    for e in edges:
        if e.src in adj and e.dst in indeg:
            adj[e.src].append(e.dst)
            indeg[e.dst] += 1
    depth = {n: 0 for n in node_ids}
    queue = sorted([n for n, d in indeg.items() if d == 0])
    while queue:
        cur = queue.pop(0)
        for nxt in adj[cur]:
            depth[nxt] = max(depth[nxt], depth[cur] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
                queue.sort()
    return depth


def _topological_order(node_ids: Sequence[str], edge_pairs: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    """Kahn + 最小堆（键 `node_id`），即 M03 `ready_order=topological_then_node_id` 的图侧实现。

    有环时**不返回残缺序**：剩余节点按 node_id 追加在尾部并保持确定性，
    真正的拒绝由 validator 的 CYCLE 分支给出（Builder 不重复裁决）。
    """
    import heapq

    indeg = {n: 0 for n in node_ids}
    adj: dict[str, list[str]] = {n: [] for n in node_ids}
    for src, dst in edge_pairs:
        if src in adj and dst in indeg:
            adj[src].append(dst)
            indeg[dst] += 1
    heap = [n for n, d in indeg.items() if d == 0]
    heapq.heapify(heap)
    order: list[str] = []
    while heap:
        cur = heapq.heappop(heap)
        order.append(cur)
        for nxt in sorted(adj[cur]):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heapq.heappush(heap, nxt)
    leftover = sorted(set(node_ids) - set(order))
    return tuple(order + leftover)


# ---------------------------------------------------------------------------
# 6. 哈希
# ---------------------------------------------------------------------------
def _hash_params(params: Mapping[str, "JsonValue"]) -> str:
    """`parameters_hash = sha256(JCS(params))`；实现复用 M01 `hash_payload`（不自己拼 JSON）。"""
    # LIB: researchflow.contracts.encoding.hash_payload
    raise NotImplementedError("P3 伪代码：参数哈希由 M01 encoding.hash_payload 落地")


def _hash_graph_payload(
    *,
    graph_version: int,
    template_id: str,
    dataset_sha256: str,
    ruleset_hash: str,
    nodes: Sequence[NodeDraft],
    edges: Sequence[Edge],
) -> str:
    """`graph_hash` 的前像（P3 约定，非 G0 冻结）：

        {"schema_version":"1.0",
         "graph_version": N,
         "template_id": ..., "dataset_sha256": ..., "ruleset_hash": ...,
         "nodes":[ 按 node_id 升序，每项含
                   node_id, node_type, template_id, depends_on, input_refs,
                   parameters_hash, side_effect_class,
                   retry_policy{max_attempts,backoff_sec}, required_checks ],
         "edges":[[src,dst], ... 升序]}

    刻意**不含**：task_id、时间戳、参数原文、绝对路径、执行结果。
    理由：图身份是“同一任务模板 + 同一输入 + 同一规则 + 同一版本”的函数；
    含 task_id 会让跨任务回放失效，含参数原文会让哈希泄露数据细节。

    该前像未在 05/06 冻结，属 `[P3 约定]`；`graph_versions.graph_hash` 的语义以此为准，
    并以“同输入两跑同哈希 / 改一条边哈希必变”两条负例锁定（见 NEGATIVE_TESTS）。
    """
    # LIB: researchflow.contracts.encoding.hash_payload（JCS + SHA-256 小写十六进制）
    raise NotImplementedError("P3 伪代码：graph_hash 由 M01 encoding.hash_payload 落地")


# ---------------------------------------------------------------------------
# 7. 边界自检
# ---------------------------------------------------------------------------
# 这些名字一旦出现在本模块的公开面上，就说明 Builder 越界去做了调度或写库。
FORBIDDEN_SURFACE: Final[tuple[str, ...]] = (
    "next_node", "pick_next", "ready_set", "ready_queue", "schedule", "dispatch",
    "enqueue", "run", "execute", "transition", "save", "insert", "register_graph",
    "insert_planned", "insert_created", "commit",
)

BOUNDARY_RULES: Final[tuple[str, ...]] = (
    "Builder 只产出静态图 + 版本 + graph_hash；不产出“下一个跑谁”。",
    "Builder 不 import 仓储、不持 DAG_REGISTER、不调用 StateMachine.transition。",
    "nodes 的 INSERT 只经 Orchestrator + M02 NodeRepository._insert_planned（DEC-01）。",
    "参数从 TaskSpec.parameters + 蓝图绑定推导；不接受用户自报节点/边/input_refs。",
    "模板只能来自注册表（module+symbol）；Builder 不拼接任何可执行命令。",
    "同 (TaskSpec, base_version) 必须得到同一 graph_hash；不得引入时间/随机数。",
)


def assert_no_scheduling_surface() -> list[str]:
    """自检：本模块不得出现调度/写库入口。返回违反项（空列表 = 通过）。

    落地阶段由测试调用；静态扫描 `design/pseudocode/M04_dag/orchestration/dag/builder.py`
    的模块级 `def` 与 `class` 名，任何命中 `FORBIDDEN_SURFACE` 即失败。
    """
    problems: list[str] = []
    for name in FORBIDDEN_SURFACE:
        if name in globals():
            problems.append(f"builder 不得定义 {name}（调度/写库职责不在此）")
    return problems


# ---------------------------------------------------------------------------
# 8. 主线 DAG 速写（**非契约、非注册**；仅供评审对照策划书 14.2）
# ---------------------------------------------------------------------------
# 用途：让评审者一眼看出“Builder 生成什么形状的图”，而不是读散落的蓝图常量。
# 纪律：这不是模板注册项（P4 才有模板本体），也不得被 registry 导入。
# 对应策划书 §14.2：Dataset Profile → Split → Preprocess → {LR, RF, SVM}
#                  → Predictions+Metrics → Leakage/Protocol → L3 Replay → Report
MAINLINE_DAG_SKETCH: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("dataset_profile", ()),
    ("split_dataset", ("dataset_profile",)),
    ("preprocess", ("split_dataset",)),
    ("train", ("preprocess",)),                 # fan-out：parameters.models
    ("predict_metrics", ("train",)),
    ("leakage_checks", ("predict_metrics",)),
    ("l3_replay", ("leakage_checks",)),
    ("report", ("l3_replay",)),
)
# 典型规模：1 + 1 + 1 + 3 + 1 + 1 + 1 + 1 = 10 个节点、9 条边、深度 7。
# 该规模是 `DEFAULT_DAG_LIMITS` 建议值（见 validator.py）的来源，不是契约上限。