"""M03 · config/feature_flags.py — 六个能力开关（P1 伪代码）。

阶段：P1｜状态：开关语义、T0 强制取值、关闭后的**最小可观测行为集合**；不实现开关系统。

来源：AGENTS §5（T0 不接 LLM、不开发六 Agent、不接 Harness Adapter；DC/SPA/VAS 属 T2）、
05 §9.5（完整 Recovery 仅 T1）、策划书 §10.4（role-off）、§11 消融（Ab1 关闭 EG 仅记录）。

硬规则：
  1. **T0 只允许 `eg=true`**；其余五个必须为 `false`。任何偏离 → FEATURE_FLAG_NOT_PERMITTED，
     进程拒绝启动（退出码 2，不监听端口）。改配置不是“开启能力”的合法途径。
  2. 开关必须真的改变行为：**只把值读出来、日志里回显一行，不算实现**。
     每个 flag 都给出“最小可观测集合”，负例测试至少要断言其中一条
     （路由是否注册 / 表是否存在 / 证据等级集合 / 判定分支 / 审计事件）。
  3. 非法组合优先于单值判断：先查组合，再查 T0 强制值，错误信息只报开关名与期望值，
     不回显其他配置内容。
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping

__all__ = [
    "FLAGS",
    "FORBIDDEN_COMBINATIONS",
    "T0_ALLOWED_TRUE",
    "T0_FORCED",
    "FlagSpec",
    "effective_value",
    "validate_flags",
]


@dataclass(frozen=True, slots=True)
class FlagSpec:
    name: str
    t0_value: bool
    owner_stage: str
    purpose: str
    on_min_deltas: tuple[str, ...]    # 打开后必须出现的最小行为
    off_min_deltas: tuple[str, ...]   # 关闭后必须消失/改变的最小行为
    forbidden_when: tuple[str, ...]   # 依赖：这些条件不满足时不得为 true
    source: str
    evidence: str


FLAGS: Final[Mapping[str, FlagSpec]] = MappingProxyType(
    {
        "eg": FlagSpec(
            name="eg",
            t0_value=True,
            owner_stage="T0（核心机制；T1 才允许消融对照）",
            purpose="证据门控：Gate 依据覆盖矩阵判定是否允许 VERIFIED 与签发凭证。",
            on_min_deltas=(
                "Gate 产出覆盖矩阵并按必检项判定 PASS/缺口",
                "存在 VERIFIED→凭证 的合法签发路径",
                "必检缺口会阻止 VERIFIED（REQUIRED_EVIDENCE_MISSING）",
            ),
            off_min_deltas=(
                "Gate 不再判 PASS：所有 required_check 只记录不裁决，报告不得为 VERIFIED",
                "凭证签发入口无可达路径（不存在“关闭 EG 仍出凭证”的分支）",
                "覆盖率矩阵的 result 不得出现 PASS 语义",
                "不得因 E0/E1 推进节点状态（该不变量在 off 时仍成立）",
            ),
            forbidden_when=(),
            source="AGENTS §4；策划书 §11 Ab1（关闭内部证据门控，仅记录）",
            evidence="tests：Gate off 模式下 certificate 不可达 + VERIFIED 不可能",
        ),
        "dc_spa": FlagSpec(
            name="dc_spa",
            t0_value=False,
            owner_stage="T2（DC/SPA 能力包）",
            purpose="确定性资格（DC）与安全剪枝（SPA）：允许在满足条件时跳过重执行并出溯源。",
            on_min_deltas=(
                "存在 DC/SPA 记录与对应持久化结构",
                "Gate/调度可依据有效 DC 判定可跳过节点",
                "凭证 skipped_nodes 可非空且每项有可审计来源",
            ),
            off_min_deltas=(
                "不存在 DC/SPA 记录或表；GET graph 不返回 dc/spa 段",
                "Gate 不做任何跳过判定；每个节点都必须真实执行",
                "凭证 skipped_nodes 恒为空数组（schema maxItems=0）",
                "不产生 DC/SPA 审计事件",
            ),
            forbidden_when=("eg",),   # 无 EG 就谈不上“可跳过的证据判定”
            source="AGENTS §4.14；05 §6（skipped_nodes 空）；附录 D.5",
            evidence="tests：T0 下 true → 启动拒绝；skipped_nodes 恒 []",
        ),
        "vas": FlagSpec(
            name="vas",
            t0_value=False,
            owner_stage="T2（FR-016）",
            purpose="验证预算与风险评分：按风险特征分配验证资源。",
            on_min_deltas=(
                "存在风险评分产物并进入调度/验证预算决策",
                "验证预算随风险变化（可观测的预算差异）",
            ),
            off_min_deltas=(
                "调度不读取任何风险分；READY 顺序只由拓扑序 + node_id 决定",
                "不加载 VAS 权重/覆盖下限等参数",
                "不产生风险相关审计或指标",
            ),
            forbidden_when=(),
            source="FR-016（T2）；策划书 §6.6 vas.yaml",
            evidence="tests：T0 下 true → 启动拒绝；调度输入不含风险分",
        ),
        "agents": FlagSpec(
            name="agents",
            t0_value=False,
            owner_stage="T1（FR-012）",
            purpose="六角色 Agent 协作：消息、权限、上下文与 role-off 实验。",
            on_min_deltas=(
                "存在 Agent 进程/角色上下文与消息总线",
                "可产生 E0 agent_claim（仍永不单独推动状态）",
                "权限矩阵生效（越权工具调用被拒绝）",
            ),
            off_min_deltas=(
                "无 Agent 进程/线程；无角色上下文与消息总线",
                "不产生 E0 agent_claim",
                "不落任何 Agent 消息表/消息记录",
                "role_off 被强制为 false（无角色可关）",
            ),
            forbidden_when=(),
            source="AGENTS §5（T0 不接 LLM、不开发六 Agent）；FR-012（T1）",
            evidence="tests：T0 下 true → 启动拒绝；无 E0 证据产生",
        ),
        "adapter": FlagSpec(
            name="adapter",
            t0_value=False,
            owner_stage="T2（FR-017 / G7）",
            purpose="DeepSeek Harness Adapter：接收标准化事件并映射为 E1 harness_trace。",
            on_min_deltas=(
                "注册 POST /api/v1/harness/events",
                "事件可映射为 E1 harness_trace（默认不等于 E2）",
                "重投幂等、缺口标记可观测",
            ),
            off_min_deltas=(
                "不注册 /api/v1/harness/events（访问 404，不是 405/403）",
                "不产生 harness_trace 证据（E1 集合只剩 tool_invocation）",
                "harness.yaml 只允许门控键，不得出现事件映射字段",
            ),
            forbidden_when=(),
            source="FR-017（T2）；OQ-CT-06；AGENTS §4.7（Harness 轨迹默认 E1）",
            evidence="tests：T0 下 true → 启动拒绝；路由 404",
        ),
        "role_off": FlagSpec(
            name="role_off",
            t0_value=False,
            owner_stage="T1（FR-012 对照实验）",
            purpose="逐角色关闭的对照实验（证明角色差异不是摆设）。",
            on_min_deltas=(
                "存在 role-off 运行配置与对照产物",
                "关闭某角色后，相关指标/CPG 可观测变化",
            ),
            off_min_deltas=(
                "不产生 role-off 对照产物",
                "不改变任何角色权限矩阵（T0 无角色）",
                "在 agents=false 时必须为 false（不能只关角色不关 Agent）",
            ),
            forbidden_when=("agents",),
            source="策划书 §10.4；FR-012；AGENTS §5",
            evidence="tests：T0 下 true → 启动拒绝；agents=false 时组合拒绝",
        ),
    }
)

T0_FORCED: Final[Mapping[str, bool]] = MappingProxyType(
    {name: spec.t0_value for name, spec in FLAGS.items()}
)
T0_ALLOWED_TRUE: Final[frozenset[str]] = frozenset(
    name for name, value in T0_FORCED.items() if value
)  # = {"eg"}

FORBIDDEN_COMBINATIONS: Final[tuple[tuple[str, str, str], ...]] = (
    ("role_off", "agents", "role_off=true 要求 agents=true；只关角色不关 Agent 不是合法组合"),
    ("dc_spa", "eg", "dc_spa=true 要求 eg=true；没有证据门控就谈不上安全跳过"),
)


def effective_value(name: str, configured: bool) -> bool:
    """返回最终生效值；不允许“配置 true 但静默降级为 false”。

    若配置值与 T0 强制值不一致，必须抛 FEATURE_FLAG_NOT_PERMITTED，
    而不是返回强制值——静默纠正会让“配置写了什么”与“实际跑什么”脱节。
    """
    raise NotImplementedError("P1 伪代码：开关装配属 M03 落地阶段")


def validate_flags(configured: Mapping[str, bool]) -> None:
    """启动时校验：缺项、未知项、T0 强制值、非法组合。

    顺序（错误信息只报开关名与期望值）：
      1. 缺任何一个开关 → FEATURE_FLAG_NOT_PERMITTED（配置缺键已先由 schemas 拦截）；
      2. 出现未登记开关 → FEATURE_FLAG_NOT_PERMITTED；
      3. 组合校验：FORBIDDEN_COMBINATIONS，被依赖项为 false 时拒绝；
      4. T0 强制值：与 T0_FORCED 不一致即拒绝。
    """
    raise NotImplementedError("P1 伪代码：开关校验属 M03 落地阶段")