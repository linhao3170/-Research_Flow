"""M05 · executor/registry.py — 模板注册表（P3 伪代码）。
阶段：P3「DAG 与执行器」｜追踪：FR-004（执行模板白名单）、NFR-06（资源上限）
依赖：M01 contracts（errors 只引用；`NAME_VERSION_PATTERN` 只按符号引用）、M03 limits（上限口径）
不变量：模板只能来自冻结注册表；未注册一律拒绝；不存在任意 shell/python 入口；运行期不可注册
错误码：TOOL_NOT_ALLOWLISTED（403，未注册模板/类型不匹配）、SCHEMA_INVALID（422，参数不合 Schema）
写入者：**无**（注册表是只读内存表；不写库、不写文件、不写审计）
状态：伪代码；不执行、不加载模板、不建环境、不跑测试

## 三条不可协商

  1. **未注册即拒绝**：`resolve()` 只认精确 `name@MAJOR.MINOR.PATCH`；
     没有 `latest`、没有区间、没有“同名首命中”、没有环境变量开关。
  2. **没有任意入口**：模板只能以 `module + symbol` 形式登记（Python 模块路径 + 标识符），
     注册表**不接受**命令字符串、脚本路径、`python -c`、`sh -c`、`.exe/.bat/.ps1`。
     执行时的 argv 由 `process_control.py` 用固定解释器 + 固定模块拼出，参数走文件不走命令行。
  3. **运行期不可注册**：本类没有 `register()` / `add()` / `reload()`。
     新增模板 = 新版本发布 + 启动时重建注册表；否则“今天能跑的模板”会随进程状态漂移。

## 与其它模块的分工

  | 问题 | 归属 |
  |---|---|
  | 模板实现（prepare/run/emit_artifacts） | P4 模板本体（本文件只登记） |
  | 参数 Schema 长什么样 | 本文件定义校验器；Schema 内容由模板登记 |
  | 参数从哪来 | `template_protocol.py`：`params.json`，命令行只传路径 |
  | 资源上限怎么执行 | `process_control.py` / `worker.py`（本文件只给上限值） |
  | DC 候选资格 | 本文件只登记 `dc_candidate`；T0 `dc_spa=false`，**不使用** |
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

__all__ = [
    "ENTRYPOINT_FORBIDDEN_TOKENS",
    "FORBIDDEN_REGISTRY_OPERATIONS",
    "REGISTRY_LIFECYCLE",
    "SIDE_EFFECT_CLASSES",
    "ParamField",
    "ParamSchema",
    "ParamType",
    "ParamViolation",
    "RegistryContractError",
    "ResourceCaps",
    "TemplateIdParts",
    "TemplateIdRule",
    "TemplateNotRegistered",
    "TemplateRegistration",
    "TemplateRegistry",
    "assert_registry_contract",
    "parse_template_id",
]

SIDE_EFFECT_CLASSES: Final[tuple[str, ...]] = ("PURE_FUNCTION", "PURE_ARTIFACT", "SIDE_EFFECT")

# 模板 ID 的权威正则只有一处：`researchflow.contracts.models.NAME_VERSION_PATTERN`
# （= ^[a-z][a-z0-9_]*@\d+\.\d+\.\d+$）。本文件**不复制**该正则，
# 通过 `TemplateIdRule` 端口注入；未注入即构造失败（fail-closed，不给默认宽松实现）。
TEMPLATE_ID_PATTERN_SYMBOL: Final[str] = "NAME_VERSION_PATTERN"

# 注册表操作禁令：出现即契约破坏（`assert_registry_contract` 会检查）。
FORBIDDEN_REGISTRY_OPERATIONS: Final[tuple[str, ...]] = (
    "register", "add", "reload", "update", "remove", "unregister", "upsert",
)

REGISTRY_LIFECYCLE: Final[tuple[str, ...]] = (
    "启动时由 WP-05 的静态模板清单构造，构造后不可变（MappingProxyType）。",
    "新增/修改模板 = 新版本发布 + 重启；运行期没有注册/刷新入口。",
    "模板 ID 精确匹配；`latest`、`^1.0`、`~1.2`、通配符一律不认。",
    "同一 template_id 出现两次 = 启动失败（不允许后者覆盖前者）。",
    "节点类型必须与登记一致；调用方不得自报 node_type。",
)


# ---------------------------------------------------------------------------
# 1. 模板 ID
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TemplateIdParts:
    """`name@MAJOR.MINOR.PATCH` 的分解；只用于日志与比较，不用于排序推断。"""

    name: str
    major: int
    minor: int
    patch: int
    raw: str


class TemplateIdRule(Protocol):
    """模板 ID 形态校验端口；生产实现使用 `models.NAME_VERSION_PATTERN`。"""

    def is_valid(self, template_id: str) -> bool:
        ...


def parse_template_id(template_id: str, *, rule: TemplateIdRule) -> TemplateIdParts:
    """拆分模板 ID；形态不合规立即拒绝（不返回“尽力解析”的结果）。

    顺序：先由 `rule` 判定（唯一正则来源），再按 `@` 与 `.` 拆分。
    这样本文件里没有第二份正则，也没有“大小写宽容”。
    """
    if not isinstance(template_id, str) or not template_id:
        raise RegistryContractError("template_id 必须是非空字符串")
    if not rule.is_valid(template_id):
        raise RegistryContractError(
            f"template_id {template_id!r} 不匹配 {TEMPLATE_ID_PATTERN_SYMBOL}"
            "（name@MAJOR.MINOR.PATCH，全小写）"
        )
    name, _, version = template_id.partition("@")
    major, minor, patch = (int(x) for x in version.split("."))
    return TemplateIdParts(name=name, major=major, minor=minor, patch=patch, raw=template_id)


# ---------------------------------------------------------------------------
# 2. 参数 Schema
# ---------------------------------------------------------------------------
class ParamType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


@dataclass(frozen=True, slots=True)
class ParamField:
    """一个参数声明。**没有** `default`：默认值属于模板，不属于 Schema 校验。

    `enum` 用元组而不是集合：报错信息必须按声明顺序稳定输出。
    """

    name: str
    type: ParamType
    required: bool
    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    enum: tuple[object, ...] = ()
    items: ParamType | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class ParamViolation:
    field_path: str
    keyword: str        # required / type / minimum / maximum / enum / unknown-key / length
    message: str


class ParamSchema:
    """极简参数 Schema：够 T0 用，且**严格**。

    支持：required、type、minimum/maximum、min_length/max_length、enum、array items。
    不支持（也不假装支持）：`oneOf`/`$ref`/`patternProperties`/`additionalProperties: true`。
    未知键默认拒绝（OQ-CT-08 的收紧方向；05 §2.1「未知参数默认拒绝」）。
    """

    def __init__(self, fields: Sequence[ParamField]) -> None:
        names = [f.name for f in fields]
        if len(set(names)) != len(names):
            raise RegistryContractError("ParamSchema 字段名重复")
        self._fields = tuple(fields)
        self._by_name = MappingProxyType({f.name: f for f in fields})

    @property
    def fields(self) -> tuple[ParamField, ...]:
        return self._fields

    @property
    def required_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self._fields if f.required)

    def validate(self, params: Mapping[str, object], *, prefix: str = "parameters") -> tuple[ParamViolation, ...]:
        """校验参数；返回**全部**违规（不 fail-fast），供一次报清 field_path。

        类型判定不做强转：`"2"` 不是 integer；`True` 不是 integer；
        `1` 也不是 number 之外的 integer 泛化（integer 只接受 int 且非 bool）。
        """
        violations: list[ParamViolation] = []
        for name in params:
            if name not in self._by_name:
                violations.append(ParamViolation(
                    f"{prefix}.{name}", "unknown-key",
                    f"未声明的参数 {name!r}（未知参数默认拒绝）",
                ))
        for spec in self._fields:
            path = f"{prefix}.{spec.name}"
            if spec.name not in params:
                if spec.required:
                    violations.append(ParamViolation(path, "required", "缺少必填参数"))
                continue
            violations.extend(_validate_value(spec, params[spec.name], path))
        return tuple(violations)


def _validate_value(spec: ParamField, value: object, path: str) -> list[ParamViolation]:
    out: list[ParamViolation] = []
    ok = _type_ok(spec.type, value)
    if not ok:
        out.append(ParamViolation(path, "type", f"期望 {spec.type.value}，实际 {type(value).__name__}"))
        return out   # 类型不符时不再比上下界，避免二次噪声

    if spec.type in (ParamType.INTEGER, ParamType.NUMBER):
        numeric = float(value)  # type: ignore[arg-type]
        if spec.minimum is not None and numeric < spec.minimum:
            out.append(ParamViolation(path, "minimum", f"{numeric} < {spec.minimum}"))
        if spec.maximum is not None and numeric > spec.maximum:
            out.append(ParamViolation(path, "maximum", f"{numeric} > {spec.maximum}"))
    if spec.type is ParamType.STRING:
        text = str(value)
        if spec.min_length is not None and len(text) < spec.min_length:
            out.append(ParamViolation(path, "length", f"长度 {len(text)} < {spec.min_length}"))
        if spec.max_length is not None and len(text) > spec.max_length:
            out.append(ParamViolation(path, "length", f"长度 {len(text)} > {spec.max_length}"))
        if any(not ch.isprintable() for ch in text):
            out.append(ParamViolation(path, "type", "字符串含不可打印字符"))
    if spec.type is ParamType.ARRAY and spec.items is not None:
        for idx, item in enumerate(value):  # type: ignore[union-attr]
            if not _type_ok(spec.items, item):
                out.append(ParamViolation(f"{path}[{idx}]", "type",
                                          f"元素期望 {spec.items.value}"))
    if spec.enum and value not in spec.enum:
        out.append(ParamViolation(path, "enum", f"{value!r} 不在 {list(spec.enum)}"))
    return out


def _type_ok(expected: ParamType, value: object) -> bool:
    if expected is ParamType.STRING:
        return isinstance(value, str)
    if expected is ParamType.BOOLEAN:
        return isinstance(value, bool)
    if expected is ParamType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is ParamType.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected is ParamType.ARRAY:
        return isinstance(value, list)
    if expected is ParamType.OBJECT:
        return isinstance(value, Mapping)
    return False


# ---------------------------------------------------------------------------
# 3. 资源上限与登记项
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ResourceCaps:
    """模板自带的**上限**（不是实测值；执行器按此设置超时与配额）。

    与 M03 `limits.yaml` 的关系：这里是“模板想要多少”，
    实际生效值 = min(模板上限, 任务级上限, 配置上限)（由 worker 计算，本文件不做合并）。
    """

    wall_time_sec: int
    memory_mb: int
    disk_mb: int
    max_attempts: int
    max_artifacts: int
    max_artifact_bytes: int
    network_allowed: bool = False   # T0 恒 False；登记为 True 即构造失败

    def __post_init__(self) -> None:
        for name in ("wall_time_sec", "memory_mb", "disk_mb", "max_attempts",
                     "max_artifacts", "max_artifact_bytes"):
            if getattr(self, name) < 1:
                raise RegistryContractError(f"ResourceCaps.{name} 必须 ≥ 1")
        if self.network_allowed:
            raise RegistryContractError("T0 断网：ResourceCaps.network_allowed 必须为 False")


# 入口禁令：命中任一 token 即拒绝登记（不是“警告”）。
ENTRYPOINT_FORBIDDEN_TOKENS: Final[tuple[str, ...]] = (
    "python", "py ", "cmd", "powershell", "pwsh", "bash", "sh ", "wsl",
    "-c", "&&", "||", ";", "|", ">", "<", "`", "$(", "${",
    "..", "/", "\\", ":", "~", "*", "?",
    ".exe", ".bat", ".cmd", ".ps1", ".py", ".dll", ".sh",
    "http://", "https://", "file://",
)

_MODULE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_SYMBOL_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class TemplateRegistration:
    """一条模板登记。

    `module`/`symbol` 是**唯一**的入口形态：
      - `module` 形如 `researchflow.templates.tabular_ml.random_forest`（≥2 段，全小写）；
      - `symbol` 形如 `RandomForestTemplate`（标识符，≤64 字符）。
    执行器拼 argv 时只做 `(sys.executable, "-m", f"{module}.__main__")` 或
    `(sys.executable, "-c", ...)` 之外的形式；**具体形态见 process_control.py**，
    本文件不生成命令。
    """

    template_id: str
    node_type: str
    side_effect_class: str
    module: str
    symbol: str
    param_schema: ParamSchema
    caps: ResourceCaps
    outputs: tuple[str, ...]
    inputs: tuple[str, ...] = ()
    required_checks: tuple[str, ...] = ()
    dc_candidate: bool = False

    def __post_init__(self) -> None:
        if self.side_effect_class not in SIDE_EFFECT_CLASSES:
            raise RegistryContractError(
                f"side_effect_class {self.side_effect_class!r} 不在 {SIDE_EFFECT_CLASSES}"
            )
        _assert_static_entrypoint(self.module, self.symbol)
        if not self.outputs:
            raise RegistryContractError("模板必须声明至少一个产物（否则执行没有可观测输出）")
        if len(set(self.outputs)) != len(self.outputs):
            raise RegistryContractError("outputs 不得重复")
        for name in self.outputs:
            _assert_artifact_name(name)
        if self.dc_candidate and self.side_effect_class == "SIDE_EFFECT":
            # AGENTS §4.14：随机性或副作用节点不签 DC。
            raise RegistryContractError("SIDE_EFFECT 模板不得登记为 dc_candidate")

    @property
    def version(self) -> tuple[int, int, int]:
        name, _, ver = self.template_id.partition("@")
        major, minor, patch = (int(x) for x in ver.split("."))
        return (major, minor, patch)


def _assert_static_entrypoint(module: str, symbol: str) -> None:
    """入口必须是“静态模块 + 标识符”，且不命中任何命令/路径/URL 片段。"""
    for text, label in ((module, "module"), (symbol, "symbol")):
        lowered = text.lower()
        for token in ENTRYPOINT_FORBIDDEN_TOKENS:
            if token in lowered:
                raise RegistryContractError(
                    f"模板入口 {label}={text!r} 命中禁令 {token!r}："
                    "只接受 module+symbol，不接受命令/路径/脚本"
                )
    if not _MODULE_RE.fullmatch(module):
        raise RegistryContractError(f"module {module!r} 必须是 ≥2 段全小写 Python 模块路径")
    if not _SYMBOL_RE.fullmatch(symbol):
        raise RegistryContractError(f"symbol {symbol!r} 必须是合法标识符")


def _assert_artifact_name(name: str) -> None:
    if not name or len(name) > 128:
        raise RegistryContractError("产物名长度必须在 1..128")
    if any(ch in name for ch in "/\\:"):
        raise RegistryContractError(f"产物名 {name!r} 不得含路径分隔符/冒号")
    if ".." in name or name.startswith(".") or name.endswith("."):
        raise RegistryContractError(f"产物名 {name!r} 不得含 .. 或首尾句点")


# ---------------------------------------------------------------------------
# 4. 拒绝与异常
# ---------------------------------------------------------------------------
class RegistryContractError(RuntimeError):
    """注册表契约被破坏（重复登记、非法入口、非法产物名）。启动期错误，不是 API 错误。"""


class TemplateNotRegistered(LookupError):
    """未注册模板/类型不匹配；对外 403 `TOOL_NOT_ALLOWLISTED`。

    `reason` 区分两种情形（都在同一错误码下，避免新增码）：
      - `TEMPLATE_NOT_REGISTERED`：ID 不在表里；
      - `NODE_TYPE_NOT_ALLOWED`：ID 在表里但 node_type 与登记不一致（调用方自报类型）。
    """

    error_code: Final[str] = "TOOL_NOT_ALLOWLISTED"
    http_status: Final[int] = 403

    def __init__(
        self,
        template_id: str,
        *,
        reason: str = "TEMPLATE_NOT_REGISTERED",
        detail: str = "",
    ) -> None:
        self.template_id = template_id
        self.reason = reason
        self.detail = detail
        suffix = f"；{detail}" if detail else ""
        super().__init__(
            f"{self.error_code}/{reason}：模板 {template_id!r} 未获准执行{suffix}"
        )


# ---------------------------------------------------------------------------
# 5. 注册表
# ---------------------------------------------------------------------------
class TemplateRegistry:
    """不可变模板注册表。

    构造时做**全部**静态校验（重复 ID、入口形态、Schema 字段、资源上限、产物名）；
    构造成功后没有任何修改方法。`resolve()` 是唯一查询入口。
    """

    def __init__(
        self,
        registrations: Sequence[TemplateRegistration],
        *,
        template_id_rule: TemplateIdRule,
        allowed_node_types: Sequence[str] = (),
    ) -> None:
        self._rule = template_id_rule
        table: dict[str, TemplateRegistration] = {}
        for reg in registrations:
            parts = parse_template_id(reg.template_id, rule=template_id_rule)
            if parts.raw != reg.template_id:
                raise RegistryContractError("template_id 拆分结果与原值不一致")
            if parts.raw in table:
                raise RegistryContractError(
                    f"template_id {parts.raw!r} 重复登记：不允许后者覆盖前者"
                )
            table[parts.raw] = reg
        self._table: Mapping[str, TemplateRegistration] = MappingProxyType(table)
        types = set(allowed_node_types) | {r.node_type for r in registrations}
        self._node_types: frozenset[str] = frozenset(types)

    # -- 查询 -------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._table)

    def __contains__(self, template_id: object) -> bool:
        return template_id in self._table

    def ids(self) -> tuple[str, ...]:
        """按字典序返回全部 ID（确定性；用于启动日志与负例断言）。"""
        return tuple(sorted(self._table))

    def registrations(self) -> tuple[TemplateRegistration, ...]:
        return tuple(self._table[k] for k in sorted(self._table))

    def resolve(self, template_id: str) -> TemplateRegistration:
        """精确取模板；未注册 → `TemplateNotRegistered`（403）。

        不做的事：不做前缀匹配、不做版本排序、不回退到同名其它版本、
        不在缺失时返回 `None` 让调用方自己判空。
        """
        if not isinstance(template_id, str) or not template_id:
            raise TemplateNotRegistered(str(template_id), detail="template_id 必须是非空字符串")
        reg = self._table.get(template_id)
        if reg is None:
            raise TemplateNotRegistered(template_id)
        return reg

    def try_resolve(self, template_id: str) -> TemplateRegistration | None:
        """只给“探测是否存在”的场景用（如启动自检）；**执行路径必须用 `resolve`**。"""
        return self._table.get(template_id) if isinstance(template_id, str) else None

    def resolve_for(self, template_id: str, node_type: str) -> TemplateRegistration:
        """解析并校验节点类型：调用方自报的 node_type 必须与登记一致。"""
        reg = self.resolve(template_id)
        if reg.node_type != node_type:
            raise TemplateNotRegistered(
                template_id,
                reason="NODE_TYPE_NOT_ALLOWED",
                detail=f"登记 node_type={reg.node_type!r}，请求 {node_type!r}",
            )
        return reg

    def node_type_allowed(self, node_type: str) -> bool:
        return node_type in self._node_types

    def dc_candidates(self) -> tuple[TemplateRegistration, ...]:
        """T2 用；T0 `dc_spa=false`，调用方不得据此跳过任何节点。"""
        return tuple(r for r in self.registrations() if r.dc_candidate)

    # -- 与 Builder/validator 的适配 --------------------------------------
    def as_node_catalog(self) -> "NodeCatalogAdapter":
        """给 `builder.TemplateCatalogPort` 的**节点侧**适配器。

        图模板（任务模板 → 蓝图）由 WP-05 另外提供；本适配器只回答
        “这个节点模板存在吗、它的 node_type 允许吗”。
        """
        return NodeCatalogAdapter(self)


class NodeCatalogAdapter:
    """`TemplateCatalogPort` 的最小实现（`task_template` 恒返回 None）。

    设计意图：注册表**不**伪装成图模板目录。把 `task_template` 写成返回 None，
    是为了让 Builder 在误用适配器时**立刻失败**（`UNSUPPORTED_BLUEPRINT`），
    而不是悄悄建出一张空图或单节点图。
    """

    def __init__(self, registry: TemplateRegistry) -> None:
        self._registry = registry

    def task_template(self, template_id: str) -> None:
        return None

    def node_template(self, template_id: str) -> "TemplateDescriptorView | None":
        reg = self._registry.try_resolve(template_id)
        return None if reg is None else TemplateDescriptorView.from_registration(reg)

    def node_type_allowed(self, node_type: str) -> bool:
        return self._registry.node_type_allowed(node_type)


@dataclass(frozen=True, slots=True)
class TemplateDescriptorView:
    """把 `TemplateRegistration` 投影成 `builder.TemplateDescriptor` 的字段形状。"""

    template_id: str
    node_type: str
    side_effect_class: str
    outputs: tuple[str, ...]
    inputs: tuple[str, ...]
    default_params: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    required_checks: tuple[str, ...] = ()
    max_attempts: int = 1
    backoff_sec: float = 0.0
    dc_candidate: bool = False
    resource_caps: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def from_registration(cls, reg: TemplateRegistration) -> "TemplateDescriptorView":
        return cls(
            template_id=reg.template_id,
            node_type=reg.node_type,
            side_effect_class=reg.side_effect_class,
            outputs=reg.outputs,
            inputs=reg.inputs,
            required_checks=reg.required_checks,
            max_attempts=reg.caps.max_attempts,
            dc_candidate=reg.dc_candidate,
            resource_caps=MappingProxyType({
                "wall_time_sec": reg.caps.wall_time_sec,
                "memory_mb": reg.caps.memory_mb,
                "disk_mb": reg.caps.disk_mb,
            }),
        )


# TemplateDescriptorView 由 `from_registration()` 构造；不提供第二个构造入口，
# 避免“两处拼字段”导致 builder 与 registry 对同一模板看到不同的 caps。


# ---------------------------------------------------------------------------
# 6. 自检
# ---------------------------------------------------------------------------
def assert_registry_contract(registry: TemplateRegistry) -> list[str]:
    """自检：不可变、无动态注册、入口静态、DC 资格合规。返回违反项。"""
    problems: list[str] = []
    for name in FORBIDDEN_REGISTRY_OPERATIONS:
        if hasattr(registry, name):
            problems.append(f"TemplateRegistry 不得有 {name}()（运行期注册必须不存在）")
    for reg in registry.registrations():
        if not reg.module or not reg.symbol:
            problems.append(f"{reg.template_id} 缺少静态入口")
        if reg.caps.network_allowed:
            problems.append(f"{reg.template_id} 声明了网络访问（T0 断网）")
        if reg.side_effect_class == "SIDE_EFFECT" and reg.dc_candidate:
            problems.append(f"{reg.template_id} 是副作用节点却标了 dc_candidate")
        if not reg.outputs:
            problems.append(f"{reg.template_id} 没有声明产物")
    return problems