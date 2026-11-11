"""M01 · contracts/errors.py — 错误码注册表（P1 伪代码，非运行时实现）。

阶段：P1「契约对齐与配置基座」｜状态：注册表与语义，不含校验/映射实现。
来源：
  - 附录 E.3 / TABLE 69（13 个错误码，全部保留，状态码与语义不得改写）；
  - 05 §1.3/§9.7、06 §4.4/§4.6/§4.5、07 WP-06/WP-07/WP-08/WP-R 的内部失败点。

硬约束：
  1. 同一个 name 只能有一种语义；不得用同一码表示两种原因（skill 约束）。
  2. 附录 E.3 的 13 条：name / http_status 与 06 §4.4 表逐字一致，**不得改**。
  3. 内部码只用于“附录 E.3 未覆盖”的失败点；不得把 E.3 已覆盖的场景另开新码
     （例：token/并发/内存/磁盘/时长超限统一走 RESOURCE_BUDGET_EXCEEDED，
     用 `detail.limit_kind` 区分子类，不新增 LIMIT_* 码）。
  4. 错误响应体统一结构见 06 §4.4：{error_code, message, field_path, correlation_id}；
     `field_path` 仅 SCHEMA_INVALID 必填；不得回显堆栈、SQL、绝对路径、密钥。
  5. 本文件不实现 HTTP 映射、不实现异常类继承树、不实现重试编排。

计数（自检）：
  APPENDIX_E3 = 13；INTERNAL_P1 = 14；合计 27。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

__all__ = [
    "APPENDIX_E3",
    "INTERNAL_P1",
    "REGISTRY",
    "ErrorCode",
    "Retry",
    "Surface",
    "lookup",
    "E3_CODE_COUNT",
    "REGISTRY_SIZE",
]


class Retry(StrEnum):
    """调用方/编排方是否可以安全重试。"""

    NO = "NO"                      # 重试不会改变结果，必须先修输入/状态/配置
    YES_SAFE = "YES_SAFE"          # 幂等，可直接重试
    CONDITIONAL = "CONDITIONAL"    # 仅在满足补充条件后重试（补证据/补事件/降并发）
    NOT_APPLICABLE = "NOT_APPLICABLE"  # 非失败语义（幂等返回/缺口受理）


class Surface(StrEnum):
    """错误码主要暴露面。"""

    API = "API"            # REST 响应体
    STARTUP = "STARTUP"    # 启动守卫；不监听端口，进程退出码 2
    CLI = "CLI"            # verify_bundle / 迁移脚本
    INTERNAL = "INTERNAL"  # 组件间失败，可能不直接出网


@dataclass(frozen=True, slots=True)
class ErrorCode:
    """一个错误码的完整口径。

    `raised_by` 回答“谁抛”，`trigger` 回答“什么时候抛”，二者都是验收要求的一部分；
    只写 name 不写触发点的码视为未定义。
    """

    name: str
    http_status: int
    semantics: str
    raised_by: tuple[str, ...]
    trigger: str
    retryable: Retry
    retry_note: str
    source: str
    surface: Surface
    user_visible: bool


# ---------------------------------------------------------------------------
# 附录 E.3 / TABLE 69：13 个码，逐条保留（ORDER 与 06 §4.4 表一致）
# ---------------------------------------------------------------------------
APPENDIX_E3: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        name="SCHEMA_INVALID",
        http_status=422,
        semantics="请求字段缺失、类型不符、枚举/格式越界、未知字段、JSON 层非法（重复键/NaN/Infinity/非法编码）。",
        raised_by=("api.request_boundary", "contracts.parsing.parse_model"),
        trigger=(
            "POST /api/v1/tasks 等写入口，在进入 StateMachine 之前："
            "JSON 严格解析失败，或 Pydantic 严格模型校验失败时抛出。"
        ),
        retryable=Retry.NO,
        retry_note="按 field_path 修正请求体后重发；同一请求重试必然再失败。",
        source="APPENDIX_E3_TABLE69；06 §4.4；05 §1.2/§1.3",
        surface=Surface.API,
        user_visible=True,
    ),
    ErrorCode(
        name="IDEMPOTENCY_CONFLICT",
        http_status=409,
        semantics="同一 Idempotency-Key 对应了不同的规范化请求体。",
        raised_by=("api.idempotency",),
        trigger=(
            "创建任务时命中已有幂等键，且 request_hash（规范化请求体哈希）与记录不一致；"
            "同键同体应返回原任务而不是本码（06 §4.5）。"
        ),
        retryable=Retry.NO,
        retry_note="换新幂等键，或确认原请求内容；不得复用旧键提交不同内容。",
        source="APPENDIX_E3_TABLE69；06 §4.5",
        surface=Surface.API,
        user_visible=True,
    ),
    ErrorCode(
        name="STATE_TRANSITION_DENIED",
        http_status=409,
        semantics="状态迁移不在允许表内，或守卫不成立，或 previous_state 已过期。",
        raised_by=("state_machine.transition",),
        trigger=(
            "StateMachine 单一入口收到迁移请求时：边不在 05 §9.2/§9.3 允许表、"
            "必填参数缺失（actor/reason_code/rule_version/correlation_id）、"
            "previous_state 与持久化状态不一致，或 INVALIDATED→READY 三条件任一不满足。"
            "失败必须回滚状态，并在独立事务写 DENIED 审计（05 §9.7）。"
        ),
        retryable=Retry.NO,
        retry_note="查询当前状态后重新决策；不得绕过 StateMachine 直写状态。",
        source="APPENDIX_E3_TABLE69；05 §9.2/§9.3/§9.7",
        surface=Surface.API,
        user_visible=True,
    ),
    # OQ-P1-04 裁决（2026-11-11）：不新增 CERTIFICATE_NOT_AVAILABLE 码，用本码 + detail.reason="CERTIFICATE_NOT_AVAILABLE" 表达，HTTP 409。
    ErrorCode(
        name="TOOL_NOT_ALLOWLISTED",
        http_status=403,
        semantics="工具未在 Domain Pack 工具契约注册，或当前角色无该工具权限。",
        raised_by=("tool_registry.resolve", "executor.preflight"),
        trigger=(
            "执行前解析工具/模板时：工具名不在白名单、参数 Schema 不匹配、"
            "或角色权限矩阵拒绝；必须在启动子进程之前拒绝，不得先跑再判。"
        ),
        retryable=Retry.NO,
        retry_note="由管理员审核并登记工具契约；调用方重试不会获得权限。",
        source="APPENDIX_E3_TABLE69；策划书 §5.7/TABLE 24 工具契约",
        surface=Surface.API,
        user_visible=True,
    ),
    ErrorCode(
        name="EVIDENCE_REFERENCE_NOT_FOUND",
        http_status=422,
        semantics="引用了不存在的 evidence_id（消息、报告、包内引用均适用）。",
        raised_by=("collector.resolve_ref", "api.evidence_lookup", "verifier.ref_check"),
        trigger=(
            "解析 evidence_id 引用时查无此记录：消息 FINDING/EVIDENCE_REF 引用、"
            "报告引用的证据、GET /tasks/{id}/evidence 的分页引用；"
            "引用必须存在，不得用“已删除”解释（证据只追加）。"
        ),
        retryable=Retry.NO,
        retry_note="丢弃该引用并记录违规来源；不得补造证据记录。",
        source="APPENDIX_E3_TABLE69；05 §4.4；附录 E.4",
        surface=Surface.API,
        user_visible=True,
    ),
    ErrorCode(
        name="REQUIRED_EVIDENCE_MISSING",
        http_status=409,
        semantics="必检项没有合格证据（缺失、等级不足、哈希不符、或证据已 stale）。",
        raised_by=("gate.evaluate",),
        trigger=(
            "Gate 生成覆盖矩阵时：某 required_check 无证据、只有 E0/E1、"
            "哈希不一致、规则版本不匹配，或该 evidence_id 出现在 evidence_invalidations 中；"
            "此时不得 PASS，更不得签发 VERIFIED 报告。"
        ),
        retryable=Retry.CONDITIONAL,
        retry_note="补做真实执行/独立验证后重新 Gate；不得用文字声明或 E0/E1 顶替。",
        source="APPENDIX_E3_TABLE69；05 §10 I-02/I-10；07 WP-08",
        surface=Surface.API,
        user_visible=True,
    ),
    ErrorCode(
        name="RULESET_VERSION_MISMATCH",
        http_status=409,
        semantics="证据/报告绑定的规则版本与当前规则集不一致。",
        raised_by=("gate.evaluate", "verifier.issue_report"),
        trigger=(
            "Gate 或 Verifier 比对 ruleset_hash 时：TaskSpec.ruleset_hash、证据所用规则、"
            "报告 ruleset_hash 三者不一致，或规则集文件哈希与登记值不符。"
        ),
        retryable=Retry.NO,
        retry_note="按当前规则集重新验证并重签；不得改写历史报告或证据。",
        source="APPENDIX_E3_TABLE69；05 §1.5/§13；07 WP-08",
        surface=Surface.API,
        user_visible=True,
    ),
    ErrorCode(
        name="RESOURCE_BUDGET_EXCEEDED",
        http_status=429,
        semantics="token / wall-clock / 并发 / 内存 / 磁盘 / 验证预算超限。",
        raised_by=("api.verify_entry", "governor.admit", "executor.enforce", "limits.check"),
        trigger=(
            "准入或执行中触达上限时：并发超过 2（配置硬上限）、单任务 wall-clock 超时、"
            "worker 内存超限、任务磁盘配额超限、token 预算耗尽、或验证预算不足。"
            "子类用 `detail.limit_kind` 区分，禁止另开 LIMIT_* 错误码。"
        ),
        retryable=Retry.CONDITIONAL,
        retry_note="排队、降并发、提高预算或缩小任务后重试；超限本身必须留 E2/审计记录。",
        source="APPENDIX_E3_TABLE69；NFR-06；05 §2.1 max_workers 1–2",
        surface=Surface.API,
        user_visible=True,
    ),
    ErrorCode(
        name="RECOVERY_NOT_SAFE",
        http_status=409,
        semantics="恢复或安全剪枝条件不成立。",
        raised_by=("recovery.guard",),  # 仅 T1；T0 无 POST /recover，路由不注册
        trigger=(
            "T1 恢复入口或剪枝判定时：无有效 DC、输入/前驱指纹已变、产物复验失败、"
            "当前规则不再通过、或节点带副作用；T0 不得以任何形式返回本码。"
        ),
        retryable=Retry.CONDITIONAL,
        retry_note="保守重跑（不复用旧结果），或升级人工；不得跳过检查强行恢复。",
        source="APPENDIX_E3_TABLE69；05 §9.5（仅 T1）；决议 6/8",
        surface=Surface.API,
        user_visible=True,
    ),
    ErrorCode(
        name="SIGNATURE_INVALID",
        http_status=422,
        semantics="签名验证失败、密钥已撤销，或信任锚不匹配。",
        raised_by=("verifier.verify_signature", "verify_bundle.trust_check"),
        trigger=(
            "签发前自检或离线验签时：Ed25519 验签失败、key_id 已撤销、"
            "key_fingerprint 不在包外信任锚、或签名载荷字段被改动（含 final_state）。"
        ),
        retryable=Retry.NO,
        retry_note="拒绝该报告/凭证并保留审计；不得用包内自带公钥重建信任。",
        source="APPENDIX_E3_TABLE69；05 §1.5；I-08",
        surface=Surface.API,
        user_visible=True,
    ),
    ErrorCode(
        name="BUNDLE_TAMPERED",
        http_status=422,
        semantics="证据包哈希、Merkle 证明或清单与实际内容不一致。",
        raised_by=("verify_bundle.integrity", "bundle.import"),
        trigger=(
            "导入或离线校验证据包时：bundle_manifest 哈希不符、merkle_proof 校验失败、"
            "artifact 哈希与清单不符、或包内文件缺失/多出。"
        ),
        retryable=Retry.NO,
        retry_note="拒绝导入；重新从原始运行导出证据包，不得修补包内文件。",
        source="APPENDIX_E3_TABLE69；05 §13；07 WP-12/G6-T0",
        surface=Surface.API,
        user_visible=True,
    ),
    ErrorCode(
        name="HARNESS_EVENT_DUPLICATE",
        http_status=200,
        semantics="Harness 事件重复投递，已幂等处理并返回既有结果。",
        raised_by=("harness.ingest",),  # 仅 T2
        trigger=(
            "POST /api/v1/harness/events 收到 (source, session_id, event_id) 与已接收事件相同的投递；"
            "返回 200 + 既有结果，不产生第二条证据。"
        ),
        retryable=Retry.NOT_APPLICABLE,
        retry_note="非失败；同键异体才构成冲突（另判）。",
        source="APPENDIX_E3_TABLE69；06 §4.5；附录 E.4",
        surface=Surface.API,
        user_visible=True,
    ),
    ErrorCode(
        name="HARNESS_EVENT_GAP",
        http_status=202,
        semantics="事件序列存在缺口，已受理但标记缺口。",
        raised_by=("harness.ingest",),  # 仅 T2
        trigger=(
            "POST /api/v1/harness/events 检测到 session 内 seq 跳号时：返回 202 并标记缺口，"
            "请求补发；不得补造事件、不得用缺口数据推进状态。"
        ),
        retryable=Retry.YES_SAFE,
        retry_note="仅补发缺失事件可安全重试；已接收事件不得重放为新证据。",
        source="APPENDIX_E3_TABLE69；附录 F.1",
        surface=Surface.API,
        user_visible=True,
    ),
)

# ---------------------------------------------------------------------------
# P1 内部码：E.3 未覆盖、但 T0 必须能区分的失败点。
# 命名不加前缀，避免与 E.3 混淆；source 一律 INTERNAL_P1。
# OQ-P1-09 裁决（2026-11-11）：内部码一律 user_visible=False，对外只映射 500/503，不进 API 文档。
# ---------------------------------------------------------------------------
INTERNAL_P1: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        name="EVIDENCE_CHAIN_BROKEN",
        http_status=500,
        semantics="证据链断裂：prev_hash 不等于上一条 chain_hash，或 chain_hash 重算不符。",
        raised_by=("collector.append", "collector.verify_chain", "gate.read_chain", "verify_bundle.integrity"),
        trigger=(
            "追加证据前校验前驱、或读取序列做链校验时：prev_hash ≠ 上一条 chain_hash、"
            "chain_hash 与重算值不符、或中间记录被替换。可发现篡改，不得声称绝对不可篡改。"
        ),
        retryable=Retry.NO,
        retry_note="停止追加并调查；不得重算旧记录、不得跳过断裂点继续写。",
        source="INTERNAL_P1；05 §13；07 WP-07；AGENTS §4.12",
        surface=Surface.INTERNAL,
        user_visible=False,
    ),
    ErrorCode(
        name="EVENT_SEQ_GAP",
        http_status=500,
        semantics="同一 task 内 event_seq 跳号（缺记录）。",
        raised_by=("collector.append", "collector.verify_chain"),
        trigger=(
            "写入或校验时发现期望 seq 与实际 seq 之间缺 N 条：记录缺口并标记链不完整；"
            "状态推进必须被阻断（缺口不能被解释为“没有发生”）。"
        ),
        retryable=Retry.CONDITIONAL,
        retry_note="补采真实缺失事件后可继续；不得补造事件填号。",
        source="INTERNAL_P1；05 §4.3/§13；附录 F.1；07 WP-07",
        surface=Surface.INTERNAL,
        user_visible=False,
    ),
    ErrorCode(
        name="EVENT_SEQ_REGRESSION",
        http_status=500,
        semantics="event_seq 回退或重复占用（≤ 上一条）。",
        raised_by=("collector.append",),
        trigger=(
            "追加证据时 event_seq ≤ 该 task 已见最大值：拒绝写入；"
            "幂等重复投递走 ingestion_log 计数，不得占用新 seq。"
        ),
        retryable=Retry.NO,
        retry_note="检查并发分配与重放来源；不得改写已写入的 seq。",
        source="INTERNAL_P1；05 §4.1；06 §1.3 UNIQUE(task_id,event_seq)",
        surface=Surface.INTERNAL,
        user_visible=False,
    ),
    ErrorCode(
        name="CONFIG_MISSING_KEY",
        http_status=503,
        semantics="必填配置键缺失。",
        raised_by=("config.loader", "config.schemas.require_key"),
        trigger=(
            "启动加载 configs/*.yaml 时：任一 required 键不存在（含空文件、缺整段）。"
            "必须拒绝启动，**不得取默认值**（M03 硬规则）。"
        ),
        retryable=Retry.NO,
        retry_note="补齐配置后重启；进程不监听端口，退出码 2。",
        source="INTERNAL_P1；M03_P1；06 §4.6 启动守卫口径",
        surface=Surface.STARTUP,
        user_visible=False,
    ),
    ErrorCode(
        name="CONFIG_UNKNOWN_KEY",
        http_status=503,
        semantics="出现未声明配置键（strict 模式）。",
        raised_by=("config.loader",),
        trigger=(
            "加载时发现 schema 未声明的键：拒绝启动，避免拼写错误被静默忽略、"
            "或 T1/T2 字段提前混入 T0 配置。"
        ),
        retryable=Retry.NO,
        retry_note="删除/改名该键，或按阶段流程扩展 schema（需评审）。",
        source="INTERNAL_P1；M03_P1",
        surface=Surface.STARTUP,
        user_visible=False,
    ),
    ErrorCode(
        name="CONFIG_TYPE_INVALID",
        http_status=503,
        semantics="配置值类型/形态不符，且禁止类型强转。",
        raised_by=("config.loader",),
        trigger=(
            "加载时发现类型不匹配（如 max_workers: \"2\"、bool 写成字符串、路径含非法字符）："
            "拒绝启动；不得把字符串数字静默转 int。"
        ),
        retryable=Retry.NO,
        retry_note="按 schema 修正字面值后重启。",
        source="INTERNAL_P1；M03_P1",
        surface=Surface.STARTUP,
        user_visible=False,
    ),
    ErrorCode(
        name="CONFIG_VALUE_OUT_OF_RANGE",
        http_status=503,
        semantics="配置值越界（硬上限、枚举外、空列表、重复项）。",
        raised_by=("config.loader", "config.limits.check"),
        trigger=(
            "加载或限额装配时：如 limits.max_workers>2、并发配置>2、"
            "gates.required_checks 为空、domainpacks.approved 为空或重复。"
        ),
        retryable=Retry.NO,
        retry_note="按冻结上限修正；不得上调第一版硬上限。",
        source="INTERNAL_P1；05 §2.1；NFR-06",
        surface=Surface.STARTUP,
        user_visible=False,
    ),
    ErrorCode(
        name="FEATURE_FLAG_NOT_PERMITTED",
        http_status=503,
        semantics="T0 不允许的 feature flag 取值（或非法组合）。",
        raised_by=("config.feature_flags.validate", "startup_guard"),
        trigger=(
            "启动时校验六开关：T0 只允许 eg=true 且 dc_spa/vas/agents/adapter/role_off=false；"
            "越权组合（如 role_off=true 但 agents=false）同样拒绝。"
        ),
        retryable=Retry.NO,
        retry_note="恢复 T0 取值；开启 T1/T2 能力必须走阶段评审，不得改配置绕过。",
        source="INTERNAL_P1；M03_P1；AGENTS §5（T0 不接 LLM/Agent/Adapter）",
        surface=Surface.STARTUP,
        user_visible=False,
    ),
    ErrorCode(
        name="DOMAIN_PACK_HOOK_UNFROZEN",
        http_status=503,
        semantics="T0/T1 调用了 CANDIDATE 状态的 DomainPack 钩子。",
        raised_by=("domainpack_hooks.invoke", "wp05.load_domain_pack", "wp08.gate"),
        trigger=(
            "调用五个钩子中任一个时：钩子签名仅为 CANDIDATE（OQ-CT-07 未关闭、字段级 Schema 未冻结），"
            "T0 只允许登记与静态检查，不允许真实调用；一旦调用即拒绝，避免把候选签名当稳定接口。"
        ),
        retryable=Retry.NO,
        retry_note="等待 OQ-CT-07 裁决并冻结字段级 Schema；不得在本阶段“先跑起来”。",
        source="INTERNAL_P1；05 §8；OQ-CT-07；M01 domainpack_hooks",
        surface=Surface.INTERNAL,
        user_visible=False,
    ),
    ErrorCode(
        name="ENV_FINGERPRINT_MISMATCH",
        http_status=500,
        semantics="环境指纹不一致：组成项缺失或任一项不同。",
        raised_by=(
            "config.env_fingerprint.compare_env_fingerprint",
            "verifier.issue_report",
            "gate.env_check",
            "dc.eligibility",  # 仅 T2
        ),
        trigger=(
            "比较 E2 记录/证书 env_fingerprint 与当前环境时：任一组成项不同、"
            "任一侧缺少必需组成项（**缺项按不一致处理，不得按未知跳过**）、"
            "或 PYTHONHASHSEED 为 randomized；证书不得复用、DC 判定必须失效。"
        ),
        retryable=Retry.NO,
        retry_note="在同一环境重新执行并重签；不得只改指纹字段。",
        source="INTERNAL_P1；05 §6；策划书 §8.4 环境指纹；M03 env_fingerprint",
        surface=Surface.INTERNAL,
        user_visible=False,
    ),
    ErrorCode(
        name="ENV_FINGERPRINT_INCOMPLETE",
        http_status=503,
        semantics="本机环境指纹采集失败，无法算出完整指纹。",
        raised_by=("config.env_fingerprint.compute_env_fingerprint",),
        trigger=(
            "采集 OS/CPU、Python、锁文件、关键库、线程变量、locale/TZ、种子策略时："
            "任一项读取异常或返回空值；禁止跳过该项后继续计算。"
        ),
        retryable=Retry.CONDITIONAL,
        retry_note="修复采集（装好依赖、给出锁文件、设置显式环境变量）后重算。",
        source="INTERNAL_P1；M03 env_fingerprint",
        surface=Surface.STARTUP,
        user_visible=False,
    ),
    ErrorCode(
        name="PLAN_HASH_MISMATCH",
        http_status=500,
        semantics="恢复计划文件缺失、哈希不符，或冻结晚于重跑。",
        raised_by=("state_machine.guard_invalidated_ready", "wp_r.plan_store"),
        trigger=(
            "INVALIDATED→READY 守卫三条件任一失败：内容寻址文件不存在/不可读、"
            "sha256(文件字节) ≠ plan_hash 或与 audit_log 冻结记录不一致、"
            "冻结事件晚于本次重跑尝试。"
        ),
        retryable=Retry.NO,
        retry_note="重新生成并冻结计划，或放弃本次复用；不得“计划缺失但放行”。",
        source="INTERNAL_P1；05 §9.3/§13；决议 5；07 WP-R",
        surface=Surface.INTERNAL,
        user_visible=False,
    ),
    ErrorCode(
        name="AUDIT_WRITE_FAILED",
        http_status=500,
        semantics="状态回滚后的 DENIED 审计二次写入也失败，进入降级通道。",
        raised_by=("state_machine.audit_fallback",),
        trigger=(
            "状态迁移失败 → 状态事务已回滚 → 独立事务写 DENIED 审计仍失败时："
            "写单行结构化 JSON 到 stderr（含 audit_write_failed=true），并在测试报告计为测试缺口。"
        ),
        retryable=Retry.NO,
        retry_note="不得静默吞掉；修复存储后补记，不得把缺口写成通过。",
        source="INTERNAL_P1；05 §9.7 决议 7；06 §3",
        surface=Surface.INTERNAL,
        user_visible=False,
    ),
    ErrorCode(
        name="TRUST_ANCHOR_MISSING",
        http_status=503,
        semantics="验签方缺少包外可信指纹/信任锚，或指纹不在锚内。",
        raised_by=("verify_bundle.trust_store", "signing.anchor_lookup"),
        trigger=(
            "离线验签或签发前：未提供外部 trust store、trust store 为空、"
            "或 key_fingerprint 不在锚内；必须 fail-closed，不得回退到包内公钥。"
        ),
        retryable=Retry.NO,
        retry_note="由独立渠道提供信任锚后重验；不得把包内公钥当锚。",
        source="INTERNAL_P1；I-08；05 §6；07 G6-T0",
        surface=Surface.CLI,
        user_visible=False,
    ),
)

E3_CODE_COUNT: Final[int] = len(APPENDIX_E3)          # 必须 = 13
REGISTRY_SIZE: Final[int] = len(APPENDIX_E3) + len(INTERNAL_P1)  # = 27

REGISTRY: Final[Mapping[str, ErrorCode]] = MappingProxyType(
    {code.name: code for code in (*APPENDIX_E3, *INTERNAL_P1)}
)

# 注册表不变量（以数据形式登记，供实现阶段的注册表测试逐条断言；P1 不执行）。
REGISTRY_INVARIANTS: Final[tuple[str, ...]] = (
    "len(APPENDIX_E3) == 13 且 name 集合与 06 §4.4 表完全一致",
    "len(REGISTRY) == 27，键唯一，无同名覆盖",
    "每个 name 只出现一次；同一 name 不得对应两种 semantics",
    "E.3 的 http_status 与 06 §4.4 表逐项一致（含 200/202 两个非错误状态）",
    "每个码都有非空 raised_by 与 trigger（只写 name 视为未定义）",
    "内部码不得复用 E.3 已覆盖的场景（超限统一 RESOURCE_BUDGET_EXCEEDED + limit_kind）",
    "user_visible=True 的码不得在 message/field_path 中携带堆栈、SQL、绝对路径或密钥",
    "内部码一律 user_visible=False，对外只映射 500/503，不进 API 文档（OQ-P1-09）",
)


def lookup(name: str) -> ErrorCode:
    """按码名取注册项。未注册的码必须显式失败，不得返回“通用错误”。"""
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"未注册的错误码：{name!r}") from exc