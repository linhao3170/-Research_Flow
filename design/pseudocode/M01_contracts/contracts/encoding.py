"""M01 · contracts/encoding.py — ID / 时间 / 哈希 / JCS 的规则与签名（P1 伪代码）。

阶段：P1｜状态：只钉类型、字面值与检查点，**不实现**生成/规范化/校验。
规范来源：`design/pseudocode/00_BASELINE/ENCODING_RULES.md`、05 §1.3/§1.4/§1.5、
附录 D.6（P0574–P0579）、`contracts/*.schema.json` v1.0、`researchflow/contracts/models.py`。

边界：
  - 正则常量**唯一来源**是 `researchflow.contracts.models`（TASK_ID_PATTERN 等）；
    本文件只按符号名引用，不复制第二份正则（避免两处漂移）。
  - 不定义 `chain_hash` 前像（G0 未冻结，见 05 §13）。
  - 不定义 DC/SPA/Bundle 的 ID 或字段；`[未决]` 项一律不生成。
  - 不实现持久化、唯一性查重、密钥或签名。

实现纪律（P2 起）：
  - 不得用 `json.dumps(..., sort_keys=True)` 冒充 JCS（排序键不同：码点 vs UTF-16 码元）。
  - 不得对哈希做大写、截断、base64 或加前缀。
  - 不得对 Unicode 做 NFC/NFD 规范化。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Sequence, TypeAlias

__all__ = [
    "ID_SPECS",
    "ID_RULES",
    "ID_KINDS_FROZEN",
    "GENESIS_PREV_HASH_PROPOSED",
    "GENESIS_POLICY",
    "UTC_FORMAT",
    "HASH_ALGORITHM",
    "HASH_HEX_LENGTH",
    "CHECKPOINTS",
    "CanonicalizationError",
    "Checkpoint",
    "IdKind",
    "IdSpec",
    "UnfrozenIdKind",
    "canonical_bytes",
    "hash_bytes",
    "hash_payload",
    "new_attempt_id",
    "new_id",
    "now_utc",
]

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | Mapping[str, "JsonValue"] | Sequence["JsonValue"]


# --------------------------------------------------------------------------- ID
class IdKind(StrEnum):
    TASK = "task"
    NODE = "node"
    EVIDENCE = "ev"
    ATTEMPT = "attempt"
    REPORT = "report"
    CERT = "cert"
    DC = "dc"
    SPA = "spa"
    PLAN = "plan"
    BUNDLE = "bundle"


@dataclass(frozen=True, slots=True)
class IdSpec:
    kind: IdKind
    display: str                 # 对外展示名（task_id / evidence_id …）
    prefix: str | None           # None = 无前缀要求 / 不存在
    pattern_symbol: str | None   # models.py 中的常量名；None = 无冻结 pattern
    frozen: bool
    new_id_allowed: bool
    source: str
    note: str


ID_SPECS: Final[Mapping[IdKind, IdSpec]] = MappingProxyType(
    {
        IdKind.TASK: IdSpec(
            kind=IdKind.TASK, display="task_id", prefix="task_",
            pattern_symbol="TASK_ID_PATTERN", frozen=True, new_id_allowed=True,
            source="05 §1.4；附录 D.1/D.6",
            note="全局唯一；删除后不可复用。",
        ),
        IdKind.NODE: IdSpec(
            kind=IdKind.NODE, display="node_id", prefix=None,
            pattern_symbol="NODE_ID_PATTERN", frozen=True, new_id_allowed=False,
            source="05 §1.4「Node 无前缀要求」；D.2",
            note="由 DAG Builder/模板给出；不得生成 node_ 前缀。",
        ),
        IdKind.EVIDENCE: IdSpec(
            kind=IdKind.EVIDENCE, display="evidence_id", prefix="ev_",
            pattern_symbol="EVIDENCE_ID_PATTERN", frozen=True, new_id_allowed=True,
            source="05 §1.4；D.3",
            note="全局唯一，不可复用；只追加。",
        ),
        IdKind.ATTEMPT: IdSpec(
            kind=IdKind.ATTEMPT, display="attempt_id", prefix="attempt_",
            pattern_symbol="ATTEMPT_ID_PATTERN", frozen=True, new_id_allowed=False,
            source="D.3 示例 attempt_02；06 §4.5",
            note="用 new_attempt_id(seq)，≥2 位零填充；重试不得复用。",
        ),
        IdKind.REPORT: IdSpec(
            kind=IdKind.REPORT, display="report_id", prefix="report_",
            pattern_symbol="REPORT_ID_PATTERN", frozen=True, new_id_allowed=True,
            source="05 §1.4；D.4",
            note="全局唯一。",
        ),
        IdKind.CERT: IdSpec(
            kind=IdKind.CERT, display="cert_id", prefix="cert_",
            pattern_symbol="CERT_ID_PATTERN", frozen=True, new_id_allowed=True,
            source="05 §1.4；D.4",
            note="全局唯一；只签发一次。",
        ),
        IdKind.DC: IdSpec(
            kind=IdKind.DC, display="dc_id", prefix=None, pattern_symbol=None,
            frozen=False, new_id_allowed=False,
            source="05 §1.4（仅列 dc_id）；OQ-CT-06/07 同批未决",
            note="无前缀规定、无字段级 Schema；T2 前不得生成。",
        ),
        IdKind.SPA: IdSpec(
            kind=IdKind.SPA, display="spa_id", prefix=None, pattern_symbol=None,
            frozen=False, new_id_allowed=False,
            source="05 §1.4（仅列 spa_id）；T0 无 SPA",
            note="无前缀规定、无字段级 Schema；T0 skipped_nodes 恒为空。",
        ),
        IdKind.PLAN: IdSpec(
            kind=IdKind.PLAN, display="plan_id/plan_hash", prefix=None,
            pattern_symbol=None, frozen=False, new_id_allowed=False,
            source="05 §9.3 决议 5；06 §1.1",
            note="plan_hash = sha256(文件字节) = 内容寻址文件名；plan_id 形态未定义；无 plan_ 前缀。",
        ),
        IdKind.BUNDLE: IdSpec(
            kind=IdKind.BUNDLE, display="(无 bundle_id)", prefix=None,
            pattern_symbol=None, frozen=False, new_id_allowed=False,
            source="05/06 未定义 Evidence Bundle 标识",
            note="只有包内 bundle_manifest.json；不得新造 bundle_ 前缀。",
        ),
    }
)

ID_KINDS_FROZEN: Final[tuple[IdKind, ...]] = (
    IdKind.TASK, IdKind.EVIDENCE, IdKind.ATTEMPT, IdKind.REPORT, IdKind.CERT,
)

ID_RULES: Final[tuple[str, ...]] = (
    "new_id 只接受 TASK/EVIDENCE/REPORT/CERT；ATTEMPT 用 new_attempt_id(seq)。",
    "NODE 无前缀：new_id(NODE) 必须抛 UnfrozenIdKind，不得返回 node_ 前缀。",
    "DC/SPA/PLAN/BUNDLE 未冻结：new_id 必须抛 UnfrozenIdKind，不得给临时形态。",
    "UUID 文本固定 8-4-4-4-12 小写十六进制；拒绝大写、无连字符、花括号、urn:uuid:。",
    "只接受 uuid4 生成（P1 约定）；校验器不得因 version 位非 4 而拒绝（超出 schema）。",
    "ID 不透明：不得从 UUID 推断时间/机器/顺序。",
)


class UnfrozenIdKind(ValueError):
    """请求生成一个没有冻结 ID 规则的 kind。"""

    def __init__(self, kind: IdKind) -> None:
        self.kind = kind
        super().__init__(f"ID kind {kind!r} 未冻结：P1 禁止生成，也不得自造前缀")


def new_id(kind: IdKind) -> str:
    """生成冻结 kind 的 ID。

    规则：
      - TASK → `task_` + uuid4；EVIDENCE → `ev_`；REPORT → `report_`；CERT → `cert_`。
      - NODE/ATTEMPT/DC/SPA/PLAN/BUNDLE → `UnfrozenIdKind`（分别按 ID_RULES）。
      - 结果必须匹配 models.py 对应 `*_PATTERN`；本函数不做大小写归一。

    P1 不实现；P2 由 WP-02 落地并用负例锁定 UnfrozenIdKind 的 kind 字段。
    """
    raise NotImplementedError("P1 伪代码：new_id 的实现属 M01 落地阶段")


def new_attempt_id(seq: int) -> str:
    """`attempt_{seq:02d}`；seq ≥ 1 且按节点单调递增。

    重试必须产生新 attempt_id（06 §4.5），不得复用；零填充至少 2 位，
    seq ≥ 100 时自然变长（pattern 允许 `[0-9]{2,}`）。
    """
    raise NotImplementedError("P1 伪代码：new_attempt_id 的实现属 M01 落地阶段")


# --------------------------------------------------------------------- 时间/哈希
UTC_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S.%fZ"   # 27 字符，微秒精度，UTC
HASH_ALGORITHM: Final[str] = "sha256"
HASH_HEX_LENGTH: Final[int] = 64


def now_utc() -> str:
    """当前 UTC 时间，固定 `YYYY-MM-DDTHH:MM:SS.ffffffZ`。

    规则：
      - 必须 `datetime.now(timezone.utc)`；禁止 `utcnow()`（naive）与本地时区。
      - 必须 `Z` 结尾；不得输出 `+00:00`（读取方仍须接受，schema 允许）。
      - 不四舍五入到秒；截断会制造同秒并列。
      - 该值可进入签名载荷（issued_at），因此同一记录的签发与验签必须使用同一字符串。
    """
    raise NotImplementedError("P1 伪代码：now_utc 的实现属 M01 落地阶段")


def hash_bytes(data: bytes) -> str:
    """`sha256(data).hexdigest()`：64 位小写十六进制。

    文件哈希必须以二进制读取（`rb`）；Windows 文本模式会改写 CRLF，导致跨机不一致。
    """
    raise NotImplementedError("P1 伪代码：hash_bytes 的实现属 M01 落地阶段")


def hash_payload(obj: JsonValue) -> str:
    """`payload_hash = sha256(canonical_bytes(payload))`。

    入参必须是**已解析**的 JSON 值（dict/list/scalar），不是字符串片段；
    若传入 bytes/str，本函数不得自行猜测编码或二次解析。
    """
    raise NotImplementedError("P1 伪代码：hash_payload 的实现属 M01 落地阶段")


# -------------------------------------------------------------------------- JCS
class Checkpoint(StrEnum):
    """规范化/解析阶段必须拒绝的四类输入（+ 一类类型错误）。"""

    DUPLICATE_KEY = "duplicate-key"
    NON_FINITE_NUMBER = "non-finite-number"
    INVALID_UNICODE = "invalid-unicode"
    NON_STRING_KEY = "non-string-key"
    NON_JSON_TYPE = "non-json-type"


@dataclass(frozen=True, slots=True)
class CheckpointSpec:
    checkpoint: Checkpoint
    where: str
    condition: str
    rejection_reason: str
    note: str


CHECKPOINTS: Final[tuple[CheckpointSpec, ...]] = (
    CheckpointSpec(
        checkpoint=Checkpoint.DUPLICATE_KEY,
        where="解析层（parsing.loads_strict 的 object_pairs_hook）",
        condition="同一对象内同一键出现两次",
        rejection_reason="duplicate-key + 键名",
        note="规范化层看不到重复键；不得靠 canonical_bytes 兜底。",
    ),
    CheckpointSpec(
        checkpoint=Checkpoint.NON_FINITE_NUMBER,
        where="解析层 parse_constant；规范化层递归再查",
        condition="NaN / Infinity / -Infinity",
        rejection_reason="non-finite-number",
        note="不得静默转 null 或 0；RFC 8259 不允许。",
    ),
    CheckpointSpec(
        checkpoint=Checkpoint.INVALID_UNICODE,
        where="canonical_bytes 的 UTF-8 编码步骤",
        condition="孤立代理项（lone surrogate）或非法 UTF-8",
        rejection_reason="invalid-unicode / invalid-encoding",
        note="不得依赖 ensure_ascii=True 掩盖；规范化不做 NFC/NFD。",
    ),
    CheckpointSpec(
        checkpoint=Checkpoint.NON_STRING_KEY,
        where="规范化层 + 解析层",
        condition="对象键不是 str",
        rejection_reason="non-string-key",
        note="JSON 对象键本应为字符串；Python dict 可直接构造非法键。",
    ),
    CheckpointSpec(
        checkpoint=Checkpoint.NON_JSON_TYPE,
        where="规范化层入口",
        condition="set/tuple 以外的非 JSON 类型（如 Decimal、datetime、bytes）",
        rejection_reason="non-json-type",
        note="datetime 必须先格式化为 UTC 字符串；bytes 必须先 base64，不得隐式转换。",
    ),
)

FORBIDDEN_IMPLEMENTATIONS: Final[tuple[str, ...]] = (
    "json.dumps(sort_keys=True) 代替 JCS（码点序 ≠ UTF-16 码元序）",
    "hexdigest().upper() / digest() 自转 / 截断前 N 位",
    "对数组做 sorted()/set()/去重",
    "ensure_ascii=True 掩盖非法 Unicode；或做 Unicode 规范化",
    "把 float 的 NaN/Infinity 序列化为 null",
    "在哈希前重排、增删字段或补默认值",
)


def canonical_bytes(obj: JsonValue) -> bytes:
    """JCS（RFC 8785）规范化后的 UTF-8 字节，无 BOM、无多余空白。

    规则：
      1. 对象成员按键排序（UTF-16 code unit 序）；**数组保持原顺序**，不排序不去重。
      2. 字符串按 JCS 转义；不做 Unicode 规范化；输出 UTF-8。
      3. 数字按 JCS/ECMAScript 规则序列化；NaN/Infinity 直接拒绝。
      4. 只接受字符串键；bool 必须先于 int 判断（Python 中 `isinstance(True, int)` 为真）。
      5. 同一逻辑对象两次调用必须得到相同字节；键书写顺序不同必须得到相同字节。

    失败必须抛 `CanonicalizationError(checkpoint=...)`，不得返回近似字节。
    """
    raise NotImplementedError("P1 伪代码：canonical_bytes 的实现属 M01 落地阶段")


class CanonicalizationError(ValueError):
    """规范化拒绝；`checkpoint` 对应 CHECKPOINTS 的枚举值。"""

    def __init__(self, checkpoint: Checkpoint, pointer: str, message: str) -> None:
        self.checkpoint = checkpoint
        self.pointer = pointer
        super().__init__(f"[{checkpoint}] {pointer}: {message}")


# --------------------------------------------------------------- prev_hash 创世值
GENESIS_PREV_HASH_PROPOSED: Final[str] = "0" * 64
GENESIS_POLICY: Final[str] = "OQ-CT-10-OPEN:FORMAT-ONLY"

# `[未决]` OQ-CT-10：首条 prev_hash 的约定值未裁决。
# 当前**建议** 64 个 0，仅以 PROPOSED 常量存在：
#   - 校验器只校验 `[0-9a-f]{64}` 形态；
#   - 不得因首条 != GENESIS_PREV_HASH_PROPOSED 而拒绝；
#   - 不得把 64 个 0 写进测试期望、API 文案或契约必填说明。
# 第二条及以后必须满足 `prev_hash == 上一条 chain_hash`（与 OQ-CT-10 无关）。
# GENESIS_POLICY 仅用于日志/自检展示，不得参与校验分支。


def accept_first_prev_hash(value: str) -> bool:
    """首条 prev_hash 的**唯一**可接受判定：形态合法即可（OQ-CT-10 未决）。

    返回 True 表示形态为 64 位小写十六进制；**不得**比较是否等于全零。
    """
    raise NotImplementedError("P1 伪代码：accept_first_prev_hash 的实现属 M01 落地阶段")