"""M03 · config/schemas.py — configs/ 十个 YAML 的字段契约（P1 伪代码）。

阶段：P1｜状态：字段、类型、来源、缺失处理；**不实现加载器**。

硬规则（本模块的全部意义）：
  1. **缺失一律拒绝启动，不取默认**：没有 `default=`，没有 `or 默认值`，没有
     “缺了就按 False/0/空列表处理”。`default_for()` 永远抛异常。
  2. **未知键拒绝**：拼写错误不得被静默忽略；T1/T2 字段不得提前混入 T0 配置。
  3. **不做类型强转**：`"2"` 不是 `2`，`"false"` 不是 `False`。
  4. **键存在但值为 `null`** 属于类型错误（CONFIG_TYPE_INVALID），不是缺键。
  5. **YAML 层**：拒绝重复键、拒绝多文档、拒绝 merge key（`<<`）；PyYAML 默认
     “后者覆盖前者”的重复键行为必须被自定义 Loader 关掉。

配置 ≠ 契约：本文件的字段是**配置字段**，不是 05/contracts 的契约字段。不得因为
配置需要就把某个键写进 `contracts/*.schema.json`，也不得改动已冻结文档。

阶段门控（与 T0 范围一致）：
  - T0 生效：gates / scheduler / recovery(部分) / security / experiment(种子) / limits / domainpacks
  - T1 门控：agents（六角色，FR-012）
  - T2 门控：vas（FR-016）、harness（FR-017 / OQ-CT-06）
  - 门控文件在 T0 只允许门控键（`config_version` + `enabled=false`）；
    其余字段**未定义**，出现即 CONFIG_UNKNOWN_KEY。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, NoReturn

__all__ = [
    "ABORT",
    "CONFIG_FILES",
    "CONFIG_LOAD_ORDER",
    "CONFIG_ROOT_VERSION",
    "DEFAULT_SOURCE_NONE",
    "ConfigFileSpec",
    "ConfigRefused",
    "FieldSpec",
    "MissingAction",
    "ValueSource",
    "default_for",
    "require_key",
]

CONFIG_ROOT_VERSION: Final[str] = "1.0"
DEFAULT_SOURCE_NONE: Final[str] = "无（缺键拒绝启动；禁止隐式默认）"
CONFIG_DIR: Final[str] = "configs/"


class MissingAction(StrEnum):
    ABORT_STARTUP = "ABORT_STARTUP"   # P1 只有这一种


class ValueSource(StrEnum):
    FROZEN_CONTRACT = "FROZEN"        # 05/06 已冻结的值或上限
    PLAN_ANCHOR = "PLAN"              # 策划书 §6.6 / TABLE
    DERIVED = "DERIVED"               # 由冻结规则推导（[推导]，需评审）
    UNDEFINED = "UNDEFINED"           # 未定义，仅门控占位


ABORT: Final[MissingAction] = MissingAction.ABORT_STARTUP


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    type_expr: str
    required: bool
    source: ValueSource
    anchor: str
    default_source: str
    missing_action: MissingAction
    constraint: str


@dataclass(frozen=True, slots=True)
class ConfigFileSpec:
    filename: str
    stage: str
    purpose: str
    fields: tuple[FieldSpec, ...]
    deferred_fields: str          # 未定义字段的处置说明（不是字段列表）
    missing_file_action: MissingAction
    unknown_key_action: str
    duplicate_key_action: str
    coerce_types: bool = False


def _f(
    key: str,
    type_expr: str,
    source: ValueSource,
    anchor: str,
    constraint: str,
    *,
    default_source: str = DEFAULT_SOURCE_NONE,
) -> FieldSpec:
    return FieldSpec(
        key=key,
        type_expr=type_expr,
        required=True,
        source=source,
        anchor=anchor,
        default_source=default_source,
        missing_action=ABORT,
        constraint=constraint,
    )


CONFIG_FILES: Final[Mapping[str, ConfigFileSpec]] = MappingProxyType(
    {
        # ---------------------------------------------------------------- T1 门控
        "agents.yaml": ConfigFileSpec(
            filename="agents.yaml",
            stage="T1（门控；T0 禁止启用）",
            purpose="角色、模型、工具权限、预算（策划书 §6.6）",
            fields=(
                _f("config_version", 'str (const "1.0")', ValueSource.DERIVED, "P1 配置版本约定",
                   "只接受 1.0；配置迁移必须另立条目"),
                _f("enabled", "bool", ValueSource.FROZEN_CONTRACT, "AGENTS §5；FR-012 属 T1",
                   "T0 必须显式为 false；true → FEATURE_FLAG_NOT_PERMITTED"),
            ),
            deferred_fields=(
                "roles / model 路由 / 工具权限 / 预算：属 FR-012（T1），字段名与结构未冻结；"
                "T0 出现即 CONFIG_UNKNOWN_KEY，不得提前定义。"
            ),
            missing_file_action=ABORT,
            unknown_key_action="CONFIG_UNKNOWN_KEY",
            duplicate_key_action="CONFIG_TYPE_INVALID",
        ),
        # ------------------------------------------------------------------- T0
        "gates.yaml": ConfigFileSpec(
            filename="gates.yaml",
            stage="T0",
            purpose="必检项、证据等级、规则版本（策划书 §6.6）",
            fields=(
                _f("config_version", 'str (const "1.0")', ValueSource.DERIVED, "P1 配置版本约定",
                   "只接受 1.0"),
                _f("ruleset_hash", 'str (sha256: [0-9a-f]{64})', ValueSource.FROZEN_CONTRACT,
                   "05 §1.5/§2.1；06 §1.3 reports.ruleset_hash",
                   "必须等于 TaskSpec.ruleset_hash 与报告 ruleset_hash；不一致 → RULESET_VERSION_MISMATCH"),
                _f("required_checks", "list[object] (minItems 1, unique by check_id)",
                   ValueSource.FROZEN_CONTRACT, "NodeSpec.required_checks（05 §3.1）",
                   "空列表拒绝；重复 check_id 拒绝"),
                _f("required_checks[].check_id", 'str (^[a-z][a-z0-9_]*$)',
                   ValueSource.FROZEN_CONTRACT, "05 §3.1 required_checks 元素形态",
                   "必须在 NodeSpec.required_checks 中存在；Gate 不得增删"),
                _f("required_checks[].min_level", 'str (enum: "E2" | "E3")',
                   ValueSource.FROZEN_CONTRACT, "05 §10 I-02（E0/E1 不得满足执行类必检项）",
                   "禁止 E0/E1；出现即 CONFIG_VALUE_OUT_OF_RANGE"),
                _f("l3_min_coverage", "number [0,1]", ValueSource.FROZEN_CONTRACT,
                   "05 §13「l3_coverage 达到规则集阈值」",
                   "阈值属规则集，不在 schema 内；Gate 用此值判定"),
            ),
            deferred_fields="无。T0 使用完整字段集；新增字段需评审并记 CHANGELOG。",
            missing_file_action=ABORT,
            unknown_key_action="CONFIG_UNKNOWN_KEY",
            duplicate_key_action="CONFIG_TYPE_INVALID",
        ),
        "scheduler.yaml": ConfigFileSpec(
            filename="scheduler.yaml",
            stage="T0",
            purpose="READY 优先级、并发、资源水位（策划书 §6.6）",
            fields=(
                _f("config_version", 'str (const "1.0")', ValueSource.DERIVED, "P1 配置版本约定",
                   "只接受 1.0"),
                _f("max_workers", "int (1..2)", ValueSource.FROZEN_CONTRACT,
                   "05 §2.1 limits.max_workers；§5.4 并发上限 2",
                   ">2 → CONFIG_VALUE_OUT_OF_RANGE；实测前不得宣称并发 2 已达成"),
                _f("ready_order", 'str (const "topological_then_node_id")',
                   ValueSource.DERIVED, "T0 确定性调度（[推导]）",
                   "T0 只允许该值；其他排序会破坏可重放性"),
                _f("memory_watermark_mb", "int (>0)", ValueSource.PLAN_ANCHOR,
                   "NFR-06；策划书 §5.4 资源水位",
                   "达到水位不再派发新 worker；不得只告警继续跑"),
                _f("disk_watermark_mb", "int (>0)", ValueSource.PLAN_ANCHOR,
                   "NFR-06；策划书 §5.4",
                   "低于水位拒绝新任务写入"),
            ),
            deferred_fields="动态 Governor 调节参数属 T1/G4，未定义。",
            missing_file_action=ABORT,
            unknown_key_action="CONFIG_UNKNOWN_KEY",
            duplicate_key_action="CONFIG_TYPE_INVALID",
        ),
        "vas.yaml": ConfigFileSpec(
            filename="vas.yaml",
            stage="T2（门控；T0 禁止启用）",
            purpose="风险特征、权重、预算、覆盖下限（策划书 §6.6）",
            fields=(
                _f("config_version", 'str (const "1.0")', ValueSource.DERIVED, "P1 配置版本约定",
                   "只接受 1.0"),
                _f("enabled", "bool", ValueSource.FROZEN_CONTRACT,
                   "FR-016 属 T2；AGENTS §5",
                   "T0 必须显式为 false；true → FEATURE_FLAG_NOT_PERMITTED"),
            ),
            deferred_fields=(
                "风险特征 / 权重 / 验证预算 / 覆盖下限：FR-016（T2），字段名与算法未冻结；"
                "T0 出现即 CONFIG_UNKNOWN_KEY。"
            ),
            missing_file_action=ABORT,
            unknown_key_action="CONFIG_UNKNOWN_KEY",
            duplicate_key_action="CONFIG_TYPE_INVALID",
        ),
        "recovery.yaml": ConfigFileSpec(
            filename="recovery.yaml",
            stage="T0（仅计划存储）；T1 字段未定义",
            purpose="错误签名、重试、失效传播、剪枝条件（策划书 §6.6）",
            fields=(
                _f("config_version", 'str (const "1.0")', ValueSource.DERIVED, "P1 配置版本约定",
                   "只接受 1.0"),
                _f("plan_store_root", "str (absolute path, non-empty)", ValueSource.FROZEN_CONTRACT,
                   "06 §1.1 决议 3；OQ-API-7（根目录可配置，文件名恒为哈希）",
                   "必须存在且可写；不得指向证据目录或 Git 工作树内的临时目录"),
                _f("full_state_machine_enabled", "bool", ValueSource.FROZEN_CONTRACT,
                   "05 §9.5（完整 Recovery 状态机仅 T1；状态值不得出现在 T0 代码/DB）",
                   "T0 必须显式为 false；true → FEATURE_FLAG_NOT_PERMITTED"),
            ),
            deferred_fields=(
                "错误签名 / 重试策略 / 失效传播 / 剪枝条件：完整 Recovery 属 T1（05 §9.5）；"
                "T0 只允许确定性计划文件与 INVALIDATED→READY 三条件守卫。"
            ),
            missing_file_action=ABORT,
            unknown_key_action="CONFIG_UNKNOWN_KEY",
            duplicate_key_action="CONFIG_TYPE_INVALID",
        ),
        "security.yaml": ConfigFileSpec(
            filename="security.yaml",
            stage="T0",
            purpose="进程权限、路径白名单、密钥/信任锚（策划书 §6.6）",
            fields=(
                _f("config_version", 'str (const "1.0")', ValueSource.DERIVED, "P1 配置版本约定",
                   "只接受 1.0"),
                _f("bind_hosts", "list[str] (minItems 1)", ValueSource.FROZEN_CONTRACT,
                   "06 §4.6 决议 8（默认且仅允许回环）",
                   "T0 每项必须属于 {127.0.0.1, ::1, localhost}；非回环且无 token → 拒绝启动"),
                _f("auth_token_env", "str (可为空串)", ValueSource.FROZEN_CONTRACT,
                   "06 §4.6（非回环必须配置访问 token）",
                   "键必须存在；空串表示不配 token，仅回环可接受；不得把 token 明文写进本文件"),
                _f("path_allowlist", "list[str] (minItems 1, absolute)", ValueSource.PLAN_ANCHOR,
                   "策划书 §6.6；AGENTS §4 补充边界（目录分离）",
                   "不得含通配符；Verifier 工作目录不得落在 Executor 目录内"),
                _f("trust_store_path", "str (absolute path; 启动时必须存在)",
                   ValueSource.FROZEN_CONTRACT, "I-08；07 G6-T0",
                   "必须来自包外；不得指向证据包内部或证书自带路径"),
                _f("private_key_ref", "str (env/OS-credential reference)", ValueSource.PLAN_ANCHOR,
                   "04 §L6；NFR-05（私钥不进 Git/日志/证据包/前端）",
                   "只允许引用名（环境变量名/凭据句柄）；出现 PEM、base64 私钥或仓库内路径 → 拒绝启动"),
            ),
            deferred_fields="TLS、反向代理鉴权、用户体系属 T1/T2，未定义。",
            missing_file_action=ABORT,
            unknown_key_action="CONFIG_UNKNOWN_KEY",
            duplicate_key_action="CONFIG_TYPE_INVALID",
        ),
        "harness.yaml": ConfigFileSpec(
            filename="harness.yaml",
            stage="T2（门控；T0 禁止启用）",
            purpose="Adapter 版本、事件映射、认证（策划书 §6.6）",
            fields=(
                _f("config_version", 'str (const "1.0")', ValueSource.DERIVED, "P1 配置版本约定",
                   "只接受 1.0"),
                _f("enabled", "bool", ValueSource.FROZEN_CONTRACT,
                   "OQ-CT-06；FR-017 属 T2；AGENTS §5",
                   "T0 必须显式为 false；true → FEATURE_FLAG_NOT_PERMITTED"),
            ),
            deferred_fields=(
                "adapter_version / event_map / auth：HarnessEvent 无 Schema（OQ-CT-06），"
                "T2 前不得定义；T0 出现即 CONFIG_UNKNOWN_KEY。"
            ),
            missing_file_action=ABORT,
            unknown_key_action="CONFIG_UNKNOWN_KEY",
            duplicate_key_action="CONFIG_TYPE_INVALID",
        ),
        "experiment.yaml": ConfigFileSpec(
            filename="experiment.yaml",
            stage="T0（仅种子策略）；T1/T2 实验字段未定义",
            purpose="任务集、种子、重复、统计协议（策划书 §6.6）",
            fields=(
                _f("config_version", 'str (const "1.0")', ValueSource.DERIVED, "P1 配置版本约定",
                   "只接受 1.0"),
                _f("seed_policy", 'str (const "explicit_per_task")', ValueSource.FROZEN_CONTRACT,
                   "TaskSpec.parameters.seed（05 §2.1）+ 环境指纹组成项「种子策略」",
                   "T0 只允许显式种子；不得由系统随机生成后不回填 Split Manifest"),
            ),
            deferred_fields=(
                "任务集 / 重复次数 k / 统计协议 / 四方案消融：属 T1/T2（G5、RF-Bench）；"
                "T0 出现即 CONFIG_UNKNOWN_KEY。DC 的 k 次 bit-exact 属 T2，不在此定义。"
            ),
            missing_file_action=ABORT,
            unknown_key_action="CONFIG_UNKNOWN_KEY",
            duplicate_key_action="CONFIG_TYPE_INVALID",
        ),
        "limits.yaml": ConfigFileSpec(
            filename="limits.yaml",
            stage="T0",
            purpose="token、超时、内存、并发、磁盘（策划书 §6.6）",
            fields=(
                _f("config_version", 'str (const "1.0")', ValueSource.DERIVED, "P1 配置版本约定",
                   "只接受 1.0"),
                _f("token_budget_per_task", "int (>=0)", ValueSource.PLAN_ANCHOR,
                   "NFR-06；策划书 §6.6",
                   "0 表示不允许 token 消耗（T0 无 LLM 时的合法值）；负数拒绝"),
                _f("wall_clock_sec_per_task", "int (>0)", ValueSource.FROZEN_CONTRACT,
                   "05 §2.1 limits.wall_time_sec",
                   "必须与 TaskSpec.limits.wall_time_sec 兼容；任务级不得小于节点级"),
                _f("wall_clock_sec_per_node", "int (>0)", ValueSource.DERIVED,
                   "05 §2.1（[推导]：节点级上限）", "超时 → 回收进程树 + E2 退出事件"),
                _f("max_workers", "int (1..2)", ValueSource.FROZEN_CONTRACT,
                   "05 §2.1；§5.4 并发上限 2", "与 scheduler.max_workers 必须一致；>2 拒绝"),
                _f("max_memory_mb_per_worker", "int (>0)", ValueSource.FROZEN_CONTRACT,
                   "05 §2.1 max_memory_mb", "按 worker 计；超限终止 worker 并记录峰值"),
                _f("disk_quota_mb_per_task", "int (>0)", ValueSource.PLAN_ANCHOR,
                   "NFR-06；策划书 §5.4", "超限停止写入、保留现场、节点 BLOCKED"),
                _f("max_attempts_cap", "int (>=1)", ValueSource.DERIVED,
                   "05 §3.1 retry_policy.max_attempts（[推导]：配置侧上限）",
                   "不得小于 NodeSpec.retry_policy.max_attempts；T0 模板默认 2 非契约上限"),
                _f("backoff_sec_cap", "number (>=0)", ValueSource.DERIVED,
                   "05 §3.1 backoff_sec（[推导]：配置侧上限）",
                   "单次 backoff 不得超过该值；负数拒绝"),
                _f("verify_budget_sec", "int (>0)", ValueSource.PLAN_ANCHOR,
                   "06 §4.1（POST /verify 429 预算不足）；NFR-06",
                   "L1/L2/L3 总时长上限；超出 → RESOURCE_BUDGET_EXCEEDED"),
            ),
            deferred_fields="T1 Governor 的动态调节/回收参数未定义（G4）。",
            missing_file_action=ABORT,
            unknown_key_action="CONFIG_UNKNOWN_KEY",
            duplicate_key_action="CONFIG_TYPE_INVALID",
        ),
        "domainpacks.yaml": ConfigFileSpec(
            filename="domainpacks.yaml",
            stage="T0",
            purpose="审核过的 Domain Pack（策划书 §6.6）",
            fields=(
                _f("config_version", 'str (const "1.0")', ValueSource.DERIVED, "P1 配置版本约定",
                   "只接受 1.0"),
                _f("approved", "list[str] (minItems 1, unique, name@MAJOR.MINOR.PATCH)",
                   ValueSource.FROZEN_CONTRACT, "05 §2.1 domain_pack；TaskSpec.domain_pack",
                   "空列表拒绝；未登记域包 → 拒绝创建任务；T0 至少含 tabular_ml@1.0.0"),
            ),
            deferred_fields=(
                "域包字段级 Schema 未冻结（OQ-CT-07）；本文件只登记标识，不登记包内容。"
            ),
            missing_file_action=ABORT,
            unknown_key_action="CONFIG_UNKNOWN_KEY",
            duplicate_key_action="CONFIG_TYPE_INVALID",
        ),
    }
)

CONFIG_LOAD_ORDER: Final[tuple[str, ...]] = (
    "security.yaml",
    "limits.yaml",
    "scheduler.yaml",
    "gates.yaml",
    "recovery.yaml",
    "experiment.yaml",
    "domainpacks.yaml",
    "agents.yaml",
    "vas.yaml",
    "harness.yaml",
)

YAML_POLICY: Final[tuple[str, ...]] = (
    "只允许单文档；多文档流（---）拒绝",
    "拒绝重复键（自定义 Loader；PyYAML 默认后者覆盖前者）",
    "拒绝 merge key（<<）与自定义标签（!!python/object 等）",
    "标量保持字面值：不把 yes/no/on/off 当 bool 之外的隐式转换依据（以 schema 的类型为准）",
    "null 值属于类型错误，不是缺键",
)


class ConfigRefused(RuntimeError):
    """配置拒绝启动；`code` 必须是 errors.py 已注册的内部码。"""

    def __init__(self, code: str, filename: str, field_path: str, message: str) -> None:
        self.code = code
        self.filename = filename
        self.field_path = field_path
        super().__init__(f"[{code}] {CONFIG_DIR}{filename}:{field_path} {message}")


def default_for(key: str) -> NoReturn:
    """本模块没有默认值。任何“取默认”的调用都必须在这里失败。

    存在这个函数是为了让“缺键 → 取默认”在代码评审时可被一眼发现：
    它的返回类型是 NoReturn，签名上就不允许返回一个值。
    """
    raise ConfigRefused(
        code="CONFIG_MISSING_KEY",
        filename="*",
        field_path=key,
        message="配置没有隐式默认值；缺失必须拒绝启动（M03 硬规则）",
    )


def require_key(filename: str, key: str) -> None:
    """加载器在取值前必须调用；P1 不实现（实现阶段从 mapping 取值并判存在）。

    缺失时抛 ConfigRefused(code="CONFIG_MISSING_KEY", field_path=key)；
    值为 null 时抛 CONFIG_TYPE_INVALID；未声明键抛 CONFIG_UNKNOWN_KEY。
    """
    raise NotImplementedError("P1 伪代码：加载器属 M03 落地阶段")