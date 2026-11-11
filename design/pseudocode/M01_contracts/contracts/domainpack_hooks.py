"""M01 · contracts/domainpack_hooks.py — DomainPack 五钩子（CANDIDATE，P1 伪代码）。

状态：**CANDIDATE**｜依据：`OQ-CT-07`（05 §8.2）｜字段级 Schema：**未冻结**｜不出 JSON Schema。

本文件只冻结“调用形状”：钩子名、参数、返回类型、调用方、约束。
**不冻结**返回对象的字段（DataProfile / RequiredCheckDecl / ToolContract / KnowledgeSeed /
RenderedReport 都是不透明占位类型），也不给出任何 `schema_version`。

为什么是 CANDIDATE 而不是 v1.0：
  - 05 §8.2 明确：包标识、`schema_version`、钩子签名/返回类型、必检项 ID 清单均未定义；
  - 05 §12 的 `OQ-CT-07` 仍为开放；
  - 因此本文件**不得**被当作 v1.0 契约、不得被下游当作稳定接口。

调用纪律：
  - T0 只允许“登记 + 静态检查”，**不得真实调用**；调用即 `DOMAIN_PACK_HOOK_UNFROZEN`。
  - 调用方只能是 WP-05（模板/域包加载）与 WP-08（Gate 规则绑定）等声明位置；
    其他组件不得绕过。返回值不得直接写证据/报告/状态——写入职责属 Collector/Verifier/StateMachine。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, NewType, Protocol, runtime_checkable

if TYPE_CHECKING:  # 仅类型检查；P1 不在运行期依赖应用包
    from researchflow.contracts.models import DatasetRef, VerificationReport

__all__ = [
    "BLOCKED_BY",
    "CONTRACT_VERSION",
    "EMITS_JSON_SCHEMA",
    "HOOKS",
    "HOOK_STATUS",
    "HOOK_STATUS_BY_NAME",
    "DataProfile",
    "DomainPackHooks",
    "DomainPackNotFrozen",
    "HookSpec",
    "KnowledgeSeed",
    "ParamSpec",
    "RenderedReport",
    "RequiredCheckDecl",
    "ToolContract",
    "invoke",
]

HOOK_STATUS: Final[str] = "CANDIDATE"
BLOCKED_BY: Final[str] = "OQ-CT-07"
CONTRACT_VERSION: Final[str | None] = None   # 刻意不给版本号：不得标成 v1.0
EMITS_JSON_SCHEMA: Final[bool] = False
SCHEMA_FROZEN: Final[bool] = False

# 不透明返回类型：字段级未冻结，禁止在本阶段展开为 dataclass/TypedDict。
DataProfile = NewType("DataProfile", object)
RequiredCheckDecl = NewType("RequiredCheckDecl", object)
ToolContract = NewType("ToolContract", object)
KnowledgeSeed = NewType("KnowledgeSeed", object)
RenderedReport = NewType("RenderedReport", object)


class DomainPackNotFrozen(RuntimeError):
    """在 CANDIDATE 阶段调用了钩子；错误码固定 DOMAIN_PACK_HOOK_UNFROZEN。"""

    code: Final[str] = "DOMAIN_PACK_HOOK_UNFROZEN"

    def __init__(self, hook_name: str) -> None:
        self.hook_name = hook_name
        super().__init__(
            f"DomainPack 钩子 {hook_name!r} 仍是 CANDIDATE（{BLOCKED_BY} 未关闭、"
            "字段级 Schema 未冻结）；T0 不得调用"
        )


@runtime_checkable
class DomainPackHooks(Protocol):
    """域包实现方必须提供的五个钩子（签名 CANDIDATE）。

    约束（来自 05 §8.1，逐条对应）：
      - `profile_data`：只读数据；不得写证据。
      - `required_checks`：规则必须可机器判定且有测试；空集合语义未冻结。
      - `tool_contracts`：禁止任意 shell/Python 入口；参数 Schema 由模板层承担。
      - `knowledge_seeds`：来源/许可/版本/hash 的完备性属字段级，未冻结。
      - `render_report`：只展示 Verifier 结果，不得修改判定、不得签名。
    """

    def profile_data(
        self,
        dataset: "DatasetRef",
        *,
        sample_limit: int | None = None,
    ) -> DataProfile:
        """数据画像：字段、缺失、分布、标签、分组/时间字段。只读，结果由 Collector 记录。"""
        ...

    def required_checks(self, *, ruleset_hash: str) -> tuple[RequiredCheckDecl, ...]:
        """声明领域必检项与规则版本绑定。调用方：WP-08 Gate。"""
        ...

    def tool_contracts(self) -> tuple[ToolContract, ...]:
        """白名单工具、参数 Schema、超时与资源限制。调用方：WP-05 注册表 / WP-06 preflight。"""
        ...

    def knowledge_seeds(self, *, query: str | None = None) -> tuple[KnowledgeSeed, ...]:
        """领域规范、工具说明、故障案例。T0 仅登记，不检索。"""
        ...

    def render_report(
        self,
        report: "VerificationReport",
        *,
        output_format: str,
    ) -> RenderedReport:
        """渲染领域报告；只读 report，不得改判定、不得改签名。调用方：WP-13 工作台。"""
        ...


@dataclass(frozen=True, slots=True)
class ParamSpec:
    name: str
    type_expr: str
    required: bool
    note: str


@dataclass(frozen=True, slots=True)
class HookSpec:
    name: str
    signature: str
    params: tuple[ParamSpec, ...]
    returns: str
    callers: tuple[str, ...]
    constraints: tuple[str, ...]
    source: str
    status: str = HOOK_STATUS
    schema: None = None          # 结构性保证：没有 JSON Schema 槽位
    version: None = None         # 结构性保证：没有版本槽位


HOOKS: Final[tuple[HookSpec, ...]] = (
    HookSpec(
        name="profile_data",
        signature="profile_data(dataset: DatasetRef, *, sample_limit: int | None = None) -> DataProfile",
        params=(
            ParamSpec("dataset", "DatasetRef", True, "只读；来自 TaskSpec.dataset_ref"),
            ParamSpec("sample_limit", "int | None", False, "仅影响采样量，不得改变画像语义；None 表示调用方未限制"),
        ),
        returns="DataProfile（不透明；字段级未冻结）",
        callers=("WP-05 模板/域包加载（数据画像）", "Collector 记录其结果（等级按 01 §4.3 判定，不在签名内）"),
        constraints=(
            "只读数据，不得写 evidence/report/state",
            "不得联网；T0 断网（05 §2.1）",
            "结果必须可由输入数据与 sample_limit 复算，不得依赖随机未记录状态",
        ),
        source="05 §8.1；策划书 §5.7 / TABLE 24",
    ),
    HookSpec(
        name="required_checks",
        signature="required_checks(*, ruleset_hash: str) -> tuple[RequiredCheckDecl, ...]",
        params=(
            ParamSpec("ruleset_hash", "str", True, "64 位小写十六进制；必须等于 gates.yaml.ruleset_hash"),
        ),
        returns="tuple[RequiredCheckDecl, ...]（不透明；声明顺序即 Gate 展示顺序）",
        callers=("WP-08 Gate（规则集绑定、覆盖矩阵）", "WP-05 模板注册（静态登记）"),
        constraints=(
            "规则可机器判定且有测试；不得用自由文本替代缺口码",
            "返回值顺序不得由调用方重排；Gate 不得增删声明项",
            "空集合语义未在 G0 定义，P1 不补（OQ-CT-07）",
        ),
        source="05 §8.1；05 §13（l3 阈值属规则集）；策划书 §7.2",
    ),
    HookSpec(
        name="tool_contracts",
        signature="tool_contracts() -> tuple[ToolContract, ...]",
        params=(),
        returns="tuple[ToolContract, ...]（不透明；参数 Schema/超时/资源限制字段未冻结）",
        callers=("WP-05 模板注册表", "WP-06 Executor preflight（白名单校验）"),
        constraints=(
            "禁止任意 shell/Python 入口",
            "未列出的工具必须被 Executor 以 TOOL_NOT_ALLOWLISTED 拒绝",
            "本钩子不执行工具，只声明契约",
        ),
        source="05 §8.1；策划书 §5.7 / TABLE 24",
    ),
    HookSpec(
        name="knowledge_seeds",
        signature="knowledge_seeds(*, query: str | None = None) -> tuple[KnowledgeSeed, ...]",
        params=(
            ParamSpec("query", "str | None", False, "T0 不使用检索；仅为 T1 预留的只读查询串"),
        ),
        returns="tuple[KnowledgeSeed, ...]（不透明；来源/许可/版本/hash 字段未冻结）",
        callers=("WP-05 模板注册（T0 仅登记）", "T1 知识库（检索与过期检查）"),
        constraints=(
            "T0 不检索、不联网、不把外部资料升级为证据",
            "来源/许可/版本/hash 必须齐全——该要求属字段级 Schema（未冻结），不得在 P1 自造字段名",
            "结果不得进入 Agent 上下文并自动视为可信（AGENTS §1.9）",
        ),
        source="05 §8.1；策划书 §5.7；NFR-08",
    ),
    HookSpec(
        name="render_report",
        signature="render_report(report: VerificationReport, *, output_format: str) -> RenderedReport",
        params=(
            ParamSpec("report", "VerificationReport", True, "只读；必须是 Verifier 已签发对象"),
            ParamSpec("output_format", "str", True, "取值集合未冻结；实现必须拒绝未知格式"),
        ),
        returns="RenderedReport（不透明；渲染产物形态未冻结）",
        callers=("WP-13 最小工作台（报告展示）",),
        constraints=(
            "只展示 Verifier 结果，不得修改判定、不得改签名、不得重算结论",
            "不得成为第二事实源：展示缺失时显示缺口，不得补写结论",
            "渲染不得触发签名字段变化；render 前后 report 字节必须一致（负例锁定）",
        ),
        source="05 §8.1；策划书 §5.7；AGENTS §4.6",
    ),
)


FORBIDDEN: Final[tuple[str, ...]] = (
    "产出 JSON Schema（本阶段一律不出）",
    "给钩子或返回类型标 v1.0 / 任何契约版本号",
    "把 DataProfile 等展开为字段列表或 dataclass",
    "为迁就实现给参数改名（dataset/ruleset_hash/report 等不得改）",
    "在 T0 真实调用钩子",
    "让钩子直接写 evidence/report/certificate/state",
)

# 五个钩子的状态一目了然：全部 CANDIDATE，没有例外。
HOOK_STATUS_BY_NAME: Final[dict[str, str]] = {
    "profile_data": "CANDIDATE",
    "required_checks": "CANDIDATE",
    "tool_contracts": "CANDIDATE",
    "knowledge_seeds": "CANDIDATE",
    "render_report": "CANDIDATE",
}


def invoke(hook_name: str) -> None:
    """统一调用闸门：CANDIDATE 阶段任何调用都必须失败。

    P1 只定义行为，不实现分派；实现阶段必须：
      - 未登记钩子名 → KeyError；
      - 已登记钩子名 → 抛 DomainPackNotFrozen(code=DOMAIN_PACK_HOOK_UNFROZEN)。
    """
    raise DomainPackNotFrozen(hook_name)