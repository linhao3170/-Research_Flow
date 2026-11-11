"""M01 · contracts/gap_register.py — 缺口登记（P1 伪代码）。

阶段：P1｜状态：只登记“缺什么、为什么缺、阻塞谁”，**不给任何字段级定义**。

处置口径（与 S0 §0.6 裁决一致，本次以用户 P1 指令原文为准）：
  - 只补 `DomainPack` 五个钩子的**签名**（CANDIDATE，见 domainpack_hooks.py）；
  - `HarnessEvent`、DC、SPA、9 类消息**一律不定义**（不写字段、不写 Schema、不写版本号）。

结构约束（结构性保证，不靠自觉）：
  `GapEntry` **没有** fields/properties/schema/required 槽位；想在某条缺口里记录字段
  定义，必须先改本 dataclass —— 那会在代码评审时暴露，而不是悄悄写进注释。
  因此 `gap_register.py` 不可能“顺手”定义 DC/SPA 的字段。

来源：05 §7/§8/§12、附录 D.5、策划书 §6.3 TABLE 27、`docs/state/G0_DECISION_LIST.md`。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

__all__ = [
    "DISPOSITION_THIS_STAGE",
    "GAPS",
    "GapEntry",
    "G0Status",
    "STAGE",
    "by_code",
    "forbidden_definition_attributes",
]

STAGE: Final[str] = "P1"
DISPOSITION_THIS_STAGE: Final[str] = "本阶段不定义"


class G0Status(StrEnum):
    """缺口在 G0 冻结面上的状态。"""

    FROZEN = "FROZEN"            # 已冻结，有 Schema
    PARTIAL = "PARTIAL"          # 只冻结了钩子名/约束，无字段级 Schema
    NOT_FROZEN = "NOT_FROZEN"    # 整条未冻结，无 Schema、无字段


@dataclass(frozen=True, slots=True)
class GapEntry:
    """一条缺口。

    只有五类信息：码、契约名、G0 状态、处置、阻塞阶段。
    没有“字段定义”槽位——这是本模块最重要的约束。
    """

    code: str
    contract: str
    g0_status: G0Status
    disposition: str
    blocks_stage: str
    evidence_anchor: str
    note: str


# ---------------------------------------------------------------------------
# 13 条：OQ-CT-06(1) + OQ-CT-07(1) + DC(1) + SPA(1) + 9 类消息(9)
# ---------------------------------------------------------------------------
GAPS: Final[tuple[GapEntry, ...]] = (
    GapEntry(
        code="OQ-CT-06",
        contract="HarnessEvent",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T2 / G7（Harness Adapter）",
        evidence_anchor="05 §7；05 §12；⑧ §2",
        note="原文仅列名（§15.5 / P0386），无字段、无 Schema；T0 不实现、T2 前以固定版本官方契约补齐。",
    ),
    GapEntry(
        code="OQ-CT-07",
        contract="DomainPack",
        g0_status=G0Status.PARTIAL,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T2（字段级）；T0 仅允许 CANDIDATE 钩子签名",
        evidence_anchor="05 §8.1/§8.2；05 §12；⑧ §2",
        note=(
            "G0 只冻结五个钩子名与约束；包标识、schema_version、字段级结构、必检项 ID 清单均未定义。"
            "P1 仅在 domainpack_hooks.py 补 CANDIDATE 钩子签名，**不冻结字段**、不出 Schema。"
        ),
    ),
    GapEntry(
        code="GAP-DC-01",
        contract="DC（Deterministic Certificate，确定性资格）",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T2（DC/SPA 能力包）",
        evidence_anchor="05 §1.1；附录 D.5；策划书 §8.4",
        note="T0/T1 不实现；本阶段不写 dc_id 形态、不写资格字段、不写 k 次判定结构。",
    ),
    GapEntry(
        code="GAP-SPA-01",
        contract="SPA（Skip Provenance Attestation，省略溯源）",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T2（DC/SPA 能力包）",
        evidence_anchor="05 §1.1；附录 D.5；AGENTS §4.14",
        note="T0 skipped_nodes 必须为空数组；本阶段不写 spa_id 形态、不写跳过条件字段。",
    ),
    GapEntry(
        code="MSG-TASK_ASSIGN",
        contract="消息 TASK_ASSIGN（Scheduler→Agent）",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T1（FR-012 六角色消息契约）",
        evidence_anchor="策划书 §6.3 / TABLE 27 R02；05 §7 相关线索",
        note="只有原文列举，无 Schema、无版本、无字段级冻结；P1 不落信封结构。",
    ),
    GapEntry(
        code="MSG-PROGRESS",
        contract="消息 PROGRESS（Agent→Scheduler）",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T1（FR-012）",
        evidence_anchor="策划书 §6.3 / TABLE 27 R03",
        note="仅展示用途；无 Schema、无版本；P1 不定义。",
    ),
    GapEntry(
        code="MSG-EVIDENCE_REF",
        contract="消息 EVIDENCE_REF（Agent→Scheduler）",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T1（FR-012）",
        evidence_anchor="策划书 §6.3 / TABLE 27 R04",
        note="引用必须存在；但消息本体无 Schema；P1 不定义字段与校验顺序。",
    ),
    GapEntry(
        code="MSG-FINDING",
        contract="消息 FINDING（Agent→Scheduler）",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T1（FR-012）",
        evidence_anchor="策划书 §6.3 / TABLE 27 R05",
        note="无 Schema、无版本；E0 声明不等同证据的规则已由 01 §4.3 约束，但消息字段未冻结。",
    ),
    GapEntry(
        code="MSG-PLAN_PROPOSAL",
        contract="消息 PLAN_PROPOSAL（Planner→Scheduler）",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T1（FR-012；动态规划）",
        evidence_anchor="策划书 §6.3 / TABLE 27 R06",
        note="只提案不裁决；消息无 Schema；P1 不定义 graph_patch 结构。",
    ),
    GapEntry(
        code="MSG-RECOVERY_PROPOSAL",
        contract="消息 RECOVERY_PROPOSAL（Recovery→Scheduler）",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T1（FR-012；完整 Recovery）",
        evidence_anchor="策划书 §6.3 / TABLE 27 R07；05 §9.5",
        note="T0 不复用 Recovery 状态机；本阶段不定义消息或计划结构。",
    ),
    GapEntry(
        code="MSG-VERIFY_REQUEST",
        contract="消息 VERIFY_REQUEST（Verification Agent→Verifier）",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T1（FR-012）",
        evidence_anchor="策划书 §6.3 / TABLE 27 R08",
        note="只请求不裁决；消息无 Schema；P1 不定义 requested_checks 取值集合（OQ-API-3 同源）。",
    ),
    GapEntry(
        code="MSG-VERDICT",
        contract="消息 VERDICT（Verifier→StateMachine）",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T1（FR-012）",
        evidence_anchor="策划书 §6.3 / TABLE 27 R09",
        note="裁决结果的落库形态由报告契约承担（05 §5），消息本体仍无 Schema；P1 不定义信封。",
    ),
    GapEntry(
        code="MSG-ESCALATE",
        contract="消息 ESCALATE（任意角色→Scheduler）",
        g0_status=G0Status.NOT_FROZEN,
        disposition=DISPOSITION_THIS_STAGE,
        blocks_stage="T1（FR-012）",
        evidence_anchor="策划书 §6.3 / TABLE 27 R10",
        note="无 Schema、无版本；P1 不定义 needs/blocking_evidence_ids 的结构。",
    ),
)

GAPS_BY_CODE: Final[Mapping[str, GapEntry]] = MappingProxyType({g.code: g for g in GAPS})


def forbidden_definition_attributes() -> tuple[str, ...]:
    """本结构**刻意缺失**的属性名；实现阶段的结构测试应断言它们不存在。

    返回的是“禁止出现”的槽位名，不是字段定义。
    """
    return ("fields", "properties", "schema", "required", "json_schema")


def by_code(code: str) -> GapEntry:
    """按缺口码取登记项；未登记必须显式失败。"""
    try:
        return GAPS_BY_CODE[code]
    except KeyError as exc:
        raise KeyError(f"未登记的缺口码：{code!r}") from exc


# 自检（实现阶段用，P1 不执行）：
#   len(GAPS) == 13
#   {g.disposition for g in GAPS} == {"本阶段不定义"}
#   all(not hasattr(g, attr) for g in GAPS for attr in forbidden_definition_attributes())
#   {g.code} ⊇ {"OQ-CT-06","OQ-CT-07","GAP-DC-01","GAP-SPA-01"} ∪ 9 个 MSG-*