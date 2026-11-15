"""MODULE：M18 · knowledge/retrieval.py — FTS5/BM25 检索、过滤、过期降权与 E1 引用（P8 伪代码）。
阶段+追踪：P8「六角色与知识库」｜FR-013（检索、过期/冲突命中、引用可追溯）｜策划书 §11.4、§11.5
FR+依赖：FR-013；依赖 unit.py（三态/内容哈希）、M01 的 E1/证据口径、M07 Collector（E1 唯一写入者）
不变量+错误码：ktype/scope 过滤在检索层完成；过期知识降权并标 `stale_kb`；冲突标 CONFLICTED 并返回冲突通知，不作为可注入内容；
              检索引用只写 E1（kind=tool_invocation，producer=collector），E1 写失败即 fail-closed 不返回结果。
              SCHEMA_INVALID(422) / AUDIT_WRITE_FAILED(503)（E1 不可用）
写入者：无直接写入。检索引用经 RetrievalEvidencePort 交 Collector；本文件不写证据库、不写知识库。
状态：伪代码；不建 FTS 表、不执行 SQL、不联网。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Final, Mapping, Protocol, Sequence

from .unit import HASH64_PATTERN, KType

__all__ = [
    "DEFAULT_LIMIT",
    "FTS_OPERATORS",
    "MAX_LIMIT",
    "STALE_KB_WEIGHT",
    "ConflictNotice",
    "HitReason",
    "IndexRow",
    "KnowledgeReaderPort",
    "KnowledgeRetrieval",
    "RetrievalEvidenceEvent",
    "RetrievalEvidencePort",
    "RetrievalQuery",
    "RetrievalRefused",
    "RetrievalResult",
    "RetrievalTierRefused",
    "RetrievalHit",
    "assert_filters_are_query_inputs",
    "assert_only_e1",
    "assert_stale_downweighted",
    "build_fts_query",
    "scope_upper_bound",
    "tokenize_query",
]

DEFAULT_LIMIT: Final[int] = 5
MAX_LIMIT: Final[int] = 20
STALE_KB_WEIGHT: Final[float] = 0.5  # 过期降权系数（P8 提议值，非契约；OQ-P8-09）

# FTS5 操作符/注入面：这些串不得原样进入 MATCH。
FTS_OPERATORS: Final[tuple[str, ...]] = ("AND", "OR", "NOT", "NEAR", "*", "(", ")", ":", "^", '"')

TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_]{1,64}")
CJK_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\u4e00-\u9fff]+")
UTC_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$"
)
SCOPE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*(:[A-Za-z0-9][A-Za-z0-9._@/-]*)+$")


class RetrievalRefused(RuntimeError):
    """检索请求被拒；`reason`/`field_path` 是断言对象。"""

    def __init__(self, reason: str, field_path: str, detail: str) -> None:
        self.error_code = "SCHEMA_INVALID"
        self.reason = reason
        self.field_path = field_path
        self.detail = detail
        super().__init__(f"[SCHEMA_INVALID] {field_path}: {reason}（{detail}）")


class RetrievalEvidenceUnavailable(RuntimeError):
    """E1 引用无法记录：检索结果不得返回（fail-closed）。"""

    def __init__(self, detail: str) -> None:
        self.error_code = "AUDIT_WRITE_FAILED"
        self.reason = "RETRIEVAL_E1_UNAVAILABLE"
        self.detail = detail
        super().__init__(f"[AUDIT_WRITE_FAILED] {self.reason}（{detail}）")


class RetrievalTierRefused(RuntimeError):
    """T0 不装配知识检索；调用即拒绝（FR-013 属 T1）。"""

    def __init__(self, tier: str) -> None:
        self.error_code = "FEATURE_FLAG_NOT_PERMITTED"
        self.reason = "KNOWLEDGE_RETRIEVAL_REQUIRES_T1"
        self.detail = f"tier={tier}"
        super().__init__(f"[FEATURE_FLAG_NOT_PERMITTED] {self.reason}（tier={tier}）")


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """一次检索请求。ktypes 必填且已按角色收敛；scope_prefix 为空表示不限 scope。"""

    text: str
    ktypes: tuple[str, ...]
    scope_prefix: str = ""
    limit: int = DEFAULT_LIMIT
    include_deprecated: bool = False
    allow_stale: bool = True

    def __post_init__(self) -> None:
        if not self.ktypes:
            raise RetrievalRefused("KTYPES_REQUIRED", "ktypes", "空 ktype 等于放开知识边界")
        unknown = set(self.ktypes) - {k.value for k in KType}
        if unknown:
            raise RetrievalRefused("KTYPE_UNKNOWN", "ktypes", sorted(unknown)[0])
        if len(set(self.ktypes)) != len(self.ktypes):
            raise RetrievalRefused("KTYPE_DUPLICATE", "ktypes", "")
        if not 1 <= self.limit <= MAX_LIMIT:
            raise RetrievalRefused("LIMIT_OUT_OF_RANGE", "limit", str(self.limit))
        if self.scope_prefix and not SCOPE_PATTERN.fullmatch(self.scope_prefix):
            raise RetrievalRefused("SCOPE_PREFIX_INVALID", "scope_prefix", self.scope_prefix)


@dataclass(frozen=True, slots=True)
class HitReason:
    """命中理由：给“为什么这条被返回”一个可复核的结构，而不是只给分数。"""

    matched_terms: tuple[str, ...]
    filters: tuple[str, ...]
    bm25: float
    rank: int
    stale_downweighted: bool

    def __post_init__(self) -> None:
        if not self.matched_terms:
            raise RetrievalRefused("HIT_REASON_EMPTY", "matched_terms", "命中必须至少有一个词")
        if self.rank < 1:
            raise RetrievalRefused("HIT_RANK_INVALID", "rank", str(self.rank))

    def as_text(self) -> str:
        return (
            f"terms={','.join(self.matched_terms)};filters={','.join(self.filters)};"
            f"bm25={self.bm25:.6f};rank={self.rank};stale_downweighted={self.stale_downweighted}"
        )


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """一条可返回的知识命中。`requires_confirmation` 与 `stale_kb` 必须透传给调用方。"""

    kid: str
    version: int
    content_hash: str
    source_url: str
    ktype: str
    scope: str
    status: str
    text: str
    score: float
    stale_kb: bool
    requires_confirmation: bool
    hit_reason: HitReason
    structured: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in ("ACTIVE", "DEPRECATED"):
            raise RetrievalRefused("HIT_STATUS_NOT_RETRIEVABLE", "status", self.status)
        if not HASH64_PATTERN.fullmatch(self.content_hash):
            raise RetrievalRefused("HIT_HASH_INVALID", "content_hash", self.content_hash)
        if self.stale_kb and not self.requires_confirmation:
            raise RetrievalRefused("STALE_WITHOUT_CONFIRMATION", "requires_confirmation", "过期知识必须要求确认")
        if not self.text.strip():
            raise RetrievalRefused("HIT_TEXT_EMPTY", "text", "")
        if not isinstance(self.structured, Mapping):
            raise RetrievalRefused("HIT_STRUCTURED_NOT_MAPPING", "structured", type(self.structured).__name__)


@dataclass(frozen=True, slots=True)
class ConflictNotice:
    """冲突通知：告诉调用方“这里有冲突，必须升级”，不提供内容注入。"""

    kid: str
    version: int
    scope: str
    ktype: str
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise RetrievalRefused("CONFLICT_REASON_EMPTY", "reason", "")


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """检索结果 + 过滤统计 + E1 事件 ID。"""

    hits: tuple[RetrievalHit, ...]
    stale_hits: tuple[RetrievalHit, ...]
    conflicts: tuple[ConflictNotice, ...]
    query_hash: str
    filters: tuple[str, ...]
    dropped_deprecated: int
    dropped_stale: int
    evidence_event_id: str

    def __post_init__(self) -> None:
        if any(hit.stale_kb for hit in self.hits) != bool(self.stale_hits):
            raise RetrievalRefused("RESULT_STALE_INCONSISTENT", "stale_hits", "stale 标记与列表不一致")
        if not HASH64_PATTERN.fullmatch(self.query_hash):
            raise RetrievalRefused("QUERY_HASH_INVALID", "query_hash", self.query_hash)


@dataclass(frozen=True, slots=True)
class IndexRow:
    """检索层返回的一行（FTS5 join 元数据表的结果）。`bm25` 用 SQLite 原值（越小越相关）。"""

    kid: str
    version: int
    content_hash: str
    source_url: str
    ktype: str
    scope: str
    status: str
    text: str
    effective_at: str
    expires_at: str
    bm25: float
    structured: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ktype not in {k.value for k in KType}:
            raise RetrievalRefused("ROW_KTYPE_UNKNOWN", "ktype", self.ktype)
        if self.status not in ("ACTIVE", "DEPRECATED", "CONFLICTED"):
            raise RetrievalRefused("ROW_STATUS_UNKNOWN", "status", self.status)


class KnowledgeReaderPort(Protocol):
    """只读检索端口。ktype/scope 过滤必须作为查询条件传入，不得在 Python 里后过滤。"""

    def search(
        self,
        *,
        fts_query: str,
        terms: tuple[str, ...],
        ktypes: tuple[str, ...],
        scope_prefix: str,
        limit: int,
        include_deprecated: bool,
    ) -> tuple[IndexRow, ...]: ...

    def latest_version(self, kid: str) -> int: ...


@dataclass(frozen=True, slots=True)
class RetrievalEvidenceEvent:
    """检索引用事件（E1）。level/kind 固定；producer 由 Collector 填。"""

    query_hash: str
    ktypes: tuple[str, ...]
    scope_prefix: str
    hit_refs: tuple[str, ...]
    top_k: int
    stale_count: int
    conflict_count: int
    occurred_at: str
    level: str = "E1"
    kind: str = "tool_invocation"

    def __post_init__(self) -> None:
        if self.level != "E1":
            raise RetrievalRefused("RETRIEVAL_LEVEL_NOT_E1", "level", self.level)
        if self.kind != "tool_invocation":
            raise RetrievalRefused("RETRIEVAL_KIND_INVALID", "kind", self.kind)
        if not HASH64_PATTERN.fullmatch(self.query_hash):
            raise RetrievalRefused("RETRIEVAL_QUERY_HASH_INVALID", "query_hash", self.query_hash)


class RetrievalEvidencePort(Protocol):
    """交给 Collector 追加 E1；返回 evidence/event ID。"""

    def submit(self, event: RetrievalEvidenceEvent) -> str: ...


class ClockPort(Protocol):
    def utc_now_iso(self) -> str: ...


# ---------------------------------------------------------------------------
# 0. 查询构造：分词 + FTS 语法消毒
# ---------------------------------------------------------------------------
def tokenize_query(text: str) -> tuple[str, ...]:
    """把自由文本切成检索词：ASCII 词 + 中文二元组（CJK bigram）。

    中文不切词就没有召回；这里用最保守的 bigram，且在 MODULE.md 登记
    “FTS5 tokenizer 必须与查询侧切分口径一致”为待落实项（OQ-P8-10）。
    """
    if not isinstance(text, str) or not text.strip():
        raise RetrievalRefused("QUERY_EMPTY", "text", "")
    tokens: set[str] = {match.group(0).lower() for match in TOKEN_PATTERN.finditer(text)}
    tokens -= {"and", "or", "not", "near"}
    for run in CJK_RUN_PATTERN.findall(text):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    if not tokens:
        raise RetrievalRefused("QUERY_NO_TERMS", "text", "分词后没有任何可检索词")
    return tuple(sorted(tokens))


def build_fts_query(terms: Sequence[str]) -> str:
    """构造 FTS5 MATCH 串：每个词用双引号包成短语，词间 OR。

    禁止把用户输入原样拼进 MATCH；操作符（NEAR/AND/*/括号/冒号）在这里被词法消除。
    """
    if not terms:
        raise RetrievalRefused("FTS_TERMS_EMPTY", "terms", "")
    cleaned: list[str] = []
    for term in terms:
        is_ascii = TOKEN_PATTERN.fullmatch(term) is not None
        is_cjk = CJK_RUN_PATTERN.fullmatch(term) is not None
        if not (is_ascii or is_cjk):
            raise RetrievalRefused("FTS_TERM_INVALID", "terms", term)
        if term.upper() in FTS_OPERATORS:
            raise RetrievalRefused("FTS_OPERATOR_INJECTED", "terms", term)
        cleaned.append(f'"{term}"')
    return " OR ".join(cleaned)


def scope_upper_bound(prefix: str) -> str:
    """scope 前缀的范围查询上界（与 `scope >= prefix AND scope < upper` 配套）。"""
    if not prefix:
        raise RetrievalRefused("SCOPE_PREFIX_EMPTY", "scope_prefix", "")
    return prefix + "\uffff"


# ---------------------------------------------------------------------------
# 1. 检索主体
# ---------------------------------------------------------------------------
class KnowledgeRetrieval:
    """检索的唯一入口。只读；唯一“写”动作是把 E1 引用事件交给 Collector。"""

    def __init__(self, *, reader: KnowledgeReaderPort, evidence: RetrievalEvidencePort, clock: ClockPort, tier: str = "T1") -> None:
        if tier not in ("T1", "T2"):
            raise RetrievalTierRefused(tier)
        self._reader = reader
        self._evidence = evidence
        self._clock = clock
        self._tier = tier

    def search(self, query: RetrievalQuery, *, now: str | None = None) -> RetrievalResult:
        """执行一次检索。顺序：校验 → 构造 MATCH → 读 → 过滤/降权 → 去重 → 写 E1 → 返回。"""
        # 1. 校验与分词
        terms = tokenize_query(query.text)
        fts_query = build_fts_query(terms)
        now_iso = now or self._clock.utc_now_iso()
        now_dt = self._parse_now(now_iso)

        filters = (
            "ktypes=" + ",".join(sorted(query.ktypes)),
            "scope_prefix=" + (query.scope_prefix or "*"),
            "include_deprecated=" + str(query.include_deprecated),
            "allow_stale=" + str(query.allow_stale),
        )

        # 2. 读（多取一些用于去重与状态过滤；过滤条件已下推）
        rows = self._reader.search(
            fts_query=fts_query,
            terms=terms,
            ktypes=tuple(sorted(query.ktypes)),
            scope_prefix=query.scope_prefix,
            limit=query.limit * 4,
            include_deprecated=query.include_deprecated,
        )

        # 3. 逐行判定：只保留最新 ACTIVE；CONFLICTED 只出通知；DEPRECATED 丢弃或保留
        latest_cache: dict[str, int] = {}
        conflicts: list[ConflictNotice] = []
        candidates: list[RetrievalHit] = []
        dropped_deprecated = 0
        dropped_stale = 0
        for row in rows:
            if row.ktype not in query.ktypes:
                raise RetrievalRefused("ROW_KTYPE_OUT_OF_QUERY", "row.ktype", row.ktype)
            if query.scope_prefix and not row.scope.startswith(query.scope_prefix):
                raise RetrievalRefused("ROW_SCOPE_OUT_OF_QUERY", "row.scope", row.scope)
            latest = latest_cache.get(row.kid)
            if latest is None:
                latest = self._reader.latest_version(row.kid)
                latest_cache[row.kid] = latest
            if row.version != latest:
                continue  # 旧版本不参与默认检索
            if row.status == "CONFLICTED":
                conflicts.append(
                    ConflictNotice(
                        kid=row.kid, version=row.version, scope=row.scope, ktype=row.ktype,
                        reason="KNOWLEDGE_CONFLICTED_REQUIRES_HUMAN",
                    )
                )
                continue
            if row.status == "DEPRECATED":
                if not query.include_deprecated:
                    dropped_deprecated += 1
                    continue
            stale = self._is_stale(row.expires_at, now_dt)
            if stale and not query.allow_stale:
                dropped_stale += 1
                continue
            score = -float(row.bm25)  # SQLite bm25() 越小越相关，取负后越大越好
            if stale:
                score *= STALE_KB_WEIGHT
            candidates.append(
                RetrievalHit(
                    kid=row.kid,
                    version=row.version,
                    content_hash=row.content_hash,
                    source_url=row.source_url,
                    ktype=row.ktype,
                    scope=row.scope,
                    status=row.status,
                    text=row.text,
                    score=score,
                    stale_kb=stale,
                    requires_confirmation=stale,
                    hit_reason=HitReason(
                        matched_terms=terms,
                        filters=filters,
                        bm25=float(row.bm25),
                        rank=1,  # 排序后回填
                        stale_downweighted=stale,
                    ),
                    structured=dict(row.structured),
                )
            )

        # 4. 排序 + 回填 rank + 截断
        candidates.sort(key=lambda hit: (-hit.score, hit.kid, -hit.version))
        hits: list[RetrievalHit] = []
        for index, hit in enumerate(candidates[: query.limit], start=1):
            hits.append(
                RetrievalHit(
                    kid=hit.kid, version=hit.version, content_hash=hit.content_hash,
                    source_url=hit.source_url, ktype=hit.ktype, scope=hit.scope, status=hit.status,
                    text=hit.text, score=hit.score, stale_kb=hit.stale_kb,
                    requires_confirmation=hit.requires_confirmation,
                    hit_reason=HitReason(
                        matched_terms=hit.hit_reason.matched_terms,
                        filters=hit.hit_reason.filters,
                        bm25=hit.hit_reason.bm25,
                        rank=index,
                        stale_downweighted=hit.hit_reason.stale_downweighted,
                    ),
                    structured=hit.structured,
                )
            )

        stale_hits = tuple(hit for hit in hits if hit.stale_kb)
        query_hash = self._query_hash(query, terms)

        # 5. 写 E1（唯一写动作；失败即 fail-closed）
        event = RetrievalEvidenceEvent(
            query_hash=query_hash,
            ktypes=tuple(sorted(query.ktypes)),
            scope_prefix=query.scope_prefix,
            hit_refs=tuple(f"{hit.kid}@{hit.version}#{hit.content_hash}" for hit in hits),
            top_k=len(hits),
            stale_count=len(stale_hits),
            conflict_count=len(conflicts),
            occurred_at=now_iso,
        )
        try:
            event_id = self._evidence.submit(event)
        except Exception as exc:  # noqa: BLE001 - 无 E1 引用则不得使用结果
            raise RetrievalEvidenceUnavailable(type(exc).__name__) from exc

        return RetrievalResult(
            hits=tuple(hits),
            stale_hits=stale_hits,
            conflicts=tuple(conflicts),
            query_hash=query_hash,
            filters=filters,
            dropped_deprecated=dropped_deprecated,
            dropped_stale=dropped_stale,
            evidence_event_id=event_id,
        )

    # -- 内部 -------------------------------------------------------------
    @staticmethod
    def _parse_now(value: str) -> datetime:
        if not UTC_PATTERN.fullmatch(value):
            raise RetrievalRefused("NOW_NOT_UTC", "now", value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise RetrievalRefused("NOW_NOT_UTC", "now", value)
        return parsed

    @classmethod
    def _is_stale(cls, expires_at: str, now: datetime) -> bool:
        return cls._parse_now(expires_at) <= now

    @staticmethod
    def _query_hash(query: RetrievalQuery, terms: tuple[str, ...]) -> str:
        raw = "\x1f".join(
            (
                "|".join(terms),
                "|".join(sorted(query.ktypes)),
                query.scope_prefix,
                str(query.limit),
                str(query.include_deprecated),
                str(query.allow_stale),
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()  # LIB: hashlib.sha256


# ---------------------------------------------------------------------------
# 2. 静态守卫
# ---------------------------------------------------------------------------
def assert_only_e1() -> tuple[str, ...]:
    """检索只写 E1：事件等级/种类固定，本模块没有 E2/E3 写入口。"""
    problems: list[str] = []
    try:
        RetrievalEvidenceEvent(
            query_hash="0" * 64, ktypes=("SPEC",), scope_prefix="", hit_refs=(), top_k=0,
            stale_count=0, conflict_count=0, occurred_at="2026-11-11T00:00:00Z", level="E2",
        )
    except RetrievalRefused:
        pass
    else:
        problems.append("E2 等级的检索事件被放行")
    for name in __all__:
        if any(token in name.lower() for token in ("write_evidence", "append_e2", "append_e3", "persist")):
            problems.append(f"导出了证据写入口 {name}")
    return tuple(problems)


def assert_stale_downweighted() -> tuple[str, ...]:
    """过期知识必须降权、标 stale_kb、要求确认；降权系数在 (0,1)。"""
    problems: list[str] = []
    if not 0.0 < STALE_KB_WEIGHT < 1.0:
        problems.append("STALE_KB_WEIGHT 必须在 (0,1)")
    try:
        RetrievalHit(
            kid="kb_x", version=1, content_hash="0" * 64, source_url="local://x", ktype="SPEC",
            scope="template:x@1.0", status="ACTIVE", text="t", score=1.0, stale_kb=True,
            requires_confirmation=False,
            hit_reason=HitReason(("t",), ("ktypes=SPEC",), -1.0, 1, True),
        )
    except RetrievalRefused:
        pass
    else:
        problems.append("stale_kb=True 但未要求确认，被放行")
    return tuple(problems)


def assert_filters_are_query_inputs() -> tuple[str, ...]:
    """过滤必须是端口入参（下推），不能靠返回后 Python 过滤。"""
    problems: list[str] = []
    code = getattr(KnowledgeReaderPort.search, "__code__", None)
    names = set(code.co_varnames) if code is not None else set(
        getattr(KnowledgeReaderPort.search, "__annotations__", {})
    )
    for required in ("ktypes", "scope_prefix", "include_deprecated"):
        if required not in names:
            problems.append(f"search 缺少过滤参数 {required}")
    return tuple(problems)