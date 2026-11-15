"""MODULE：M19 · api/middleware_idempotency.py — 幂等键与规范化请求哈希的中间件语义（P10 伪代码）。
阶段+追踪：P10「接入、实验与交付」｜06 §4.5、附录 E.4、OQ-DB-2、OQ-P2-12-8
FR+依赖：FR-001/FR-002；依赖 M01 parsing（strict JSON）、M02 idempotency_keys（原子唯一）、M11 JCS 规范化
不变量+错误码：422 先于 409（与既有 app.py 的校验顺序一致）；同键同体回放原 201，同键异体 409；
              幂等键本身不是任务身份，不得用来把同一任务复制成多个样本；中间件不写 tasks/evidence。
              SCHEMA_INVALID(422) / IDEMPOTENCY_CONFLICT(409)
写入者：无。中间件只读幂等记录并注入请求上下文；唯一写入者是 TaskCreationPort 的同事务插入。
状态：伪代码；不启动 ASGI、不解析真实请求、不跑测试。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Final, Mapping, Protocol

from .error_map import build_error_response

__all__ = [
    "CANONICAL_DOMAIN",
    "IDEMPOTENCY_HEADER",
    "MAX_BODY_BYTES",
    "MAX_KEY_LEN",
    "ConflictDecision",
    "IdempotencyBinding",
    "IdempotencyDecision",
    "IdempotencyMiddleware",
    "IdempotencyStore",
    "PreparedRequest",
    "RequestProblem",
    "StoredResponse",
    "assert_middleware_semantics",
    "canonical_request_hash",
    "correlation_id_from_headers",
    "decide_replay",
    "key_from_headers",
    "prepare_request",
    "problem_from_validation",
    "validate_idempotency_key",
]

IDEMPOTENCY_HEADER: Final[str] = "idempotency-key"
CANONICAL_DOMAIN: Final[bytes] = b"RF-IDEMPOTENCY\x00v1\x00"
MAX_KEY_LEN: Final[int] = 255
MAX_BODY_BYTES: Final[int] = 1_048_576  # [P10 约定] 1 MiB；不是冻结契约
_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[\x21-\x7e]{1,255}$")


class RequestProblem(Exception):
    """请求在进入路由前的可渲染问题；`status`/`code`/`field_path` 是断言对象。"""

    def __init__(
        self,
        *,
        status: int,
        code: str | None,
        message: str,
        field_path: str | None = None,
        reason: str | None = None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.field_path = field_path
        self.reason = reason
        self.detail = dict(detail or {})
        super().__init__(message)


class RequestValidator(Protocol):
    """Pydantic 严格校验端口；`validate` 抛 pydantic.ValidationError。"""

    def validate(self, payload: Mapping[str, Any]) -> Any: ...


class CanonicalizeFn(Protocol):
    """JCS（RFC 8785）规范化端口；必须返回无 BOM 的 UTF-8 字节。"""

    def __call__(self, payload: Any) -> bytes: ...


@dataclass(frozen=True, slots=True)
class IdempotencyBinding:
    """一次请求的幂等身份。`request_hash` 覆盖 method + 路由模板 + 规范化体。"""

    scope: str
    key: str
    request_hash: str


@dataclass(frozen=True, slots=True)
class StoredResponse:
    """已提交的 201 回执；body 必须是原始字节，回放不得重新序列化。"""

    scope: str
    key: str
    request_hash: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    task_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    """strict 解析 + 模型校验 + 幂等键校验后的请求上下文。"""

    raw_body: bytes
    payload: Mapping[str, Any] | None
    validated: Any | None
    binding: IdempotencyBinding | None
    problem: RequestProblem | None
    correlation_id: str


class IdempotencyDecision:
    """lookup 的三种结论；没有 IN_PROGRESS，因为原子性由创建端口保证。"""

    MISS: Final[str] = "MISS"
    REPLAY: Final[str] = "REPLAY"
    CONFLICT: Final[str] = "CONFLICT"


@dataclass(frozen=True, slots=True)
class ConflictDecision:
    decision: str
    stored: StoredResponse | None
    reason: str | None


class IdempotencyStore(Protocol):
    """只读查询端口；实现方是 M02 `idempotency_keys`，本中间件不写。"""

    def get(self, scope: str, key: str) -> StoredResponse | None: ...


def validate_idempotency_key(key: str) -> None:
    """可见 ASCII 1–255、无空白；空串不是“未提供”。"""
    # 1. 空串：客户端显式给了空键，不能当成未提供。
    if key == "":
        raise RequestProblem(
            status=422,
            code="SCHEMA_INVALID",
            message="Idempotency-Key 不得为空；省略该头表示不启用幂等。",
            field_path="header.Idempotency-Key",
            reason="IDEMPOTENCY_KEY_EMPTY",
        )
    # 2. 长度与字符集；不做大小写归一（键区分大小写）。
    if len(key) > MAX_KEY_LEN or _KEY_RE.fullmatch(key) is None:
        raise RequestProblem(
            status=422,
            code="SCHEMA_INVALID",
            message="Idempotency-Key 必须是 1–255 个可见 ASCII 字符且不含空白。",
            field_path="header.Idempotency-Key",
            reason="IDEMPOTENCY_KEY_INVALID",
        )
    # 3. 通过；返回 None 表示合法。
    return None


def key_from_headers(headers: Mapping[str, str]) -> str | None:
    """大小写不敏感地取键；重复出现按实现错误拒绝（ASGI 层应已合并）。"""
    # 1. 归一化头名。
    lowered = {str(name).lower(): value for name, value in headers.items()}
    # 2. 未提供 → None，表示不启用幂等。
    if IDEMPOTENCY_HEADER not in lowered:
        return None
    # 3. 取值；HTTP 头值按协议去掉首尾空白，但内部空白保留给校验器拒绝。
    return str(lowered[IDEMPOTENCY_HEADER]).strip()


def correlation_id_from_headers(headers: Mapping[str, str]) -> str:
    """取 X-Correlation-Id；缺失或非法则生成，绝不回显超长/控制字符。"""
    # 1. 归一化并读取。
    lowered = {str(name).lower(): value for name, value in headers.items()}
    raw = str(lowered.get("x-correlation-id", "")).strip()
    # 2. 只接受 1–128 个可见 ASCII；否则生成新值。
    if 1 <= len(raw) <= 128 and all("\x21" <= ch <= "\x7e" for ch in raw):
        return raw
    # 3. 生成 `req-<32hex>`；不写入响应体之外。
    return f"req-{uuid.uuid4().hex}"


def canonical_request_hash(
    *,
    method: str,
    route_template: str,
    payload: Any,
    canonicalize: CanonicalizeFn,
) -> str:
    """sha256(domain || METHOD || LF || route_template || LF || JCS(payload))。"""
    # 1. 域名分隔前缀固定，防止与其它哈希域混用。
    prefix = CANONICAL_DOMAIN
    # 2. 方法必须大写且是已知 HTTP 方法。
    upper = method.upper()
    if upper not in {"POST", "PUT", "PATCH"}:
        raise ValueError(f"幂等哈希不用于该方法：{method!r}")
    # 3. 路由模板必须是常量模板（如 `/api/v1/tasks`），不得带 task_id。
    if "{" in route_template or not route_template.startswith("/"):
        raise ValueError("route_template 必须是已登记的常量路由模板")
    # 4. 规范化体必须是字节；JCS 只排对象键、不排数组。
    body = canonicalize(payload)
    if not isinstance(body, (bytes, bytearray)) or bytes(body).startswith(b"\xef\xbb\xbf"):
        raise ValueError("JCS 必须返回无 BOM 的 UTF-8 字节")
    # 5. 逐段拼接后哈希；输出 64 位小写十六进制。
    material = prefix + upper.encode("ascii") + b"\n" + route_template.encode("utf-8") + b"\n" + bytes(body)
    return hashlib.sha256(material).hexdigest()


def _field_path(location: tuple[Any, ...]) -> str:
    """与 app.py 完全一致的字段路径：去掉 body 前缀，`.` 连接，空为 `$`。"""
    parts = [str(part) for part in location if part != "body"]
    return ".".join(parts) if parts else "$"


def problem_from_validation(exc: Any) -> RequestProblem:
    """把 pydantic.ValidationError 映射成 06 §4.2/§4.4 的 422 语义。"""
    # 1. 取第一条错误；与现有 app.py 一致（不汇总多条）。
    first = exc.errors()[0]
    path = _field_path(tuple(first.get("loc", ())))
    error_type = str(first.get("type", ""))
    # 2. dataset_ref 字符串形态：固定文案，不自动解析。
    if path == "dataset_ref" and error_type in {
        "string_type",
        "model_type",
        "model_attributes_type",
        "dict_type",
    }:
        return RequestProblem(
            status=422,
            code="SCHEMA_INVALID",
            message="dataset_ref must be an object with fields uri, sha256, license.",
            field_path="dataset_ref",
        )
    # 3. 其余字段：`path: detail`；根错误只给 detail。
    detail = str(first.get("msg", "字段校验失败"))
    return RequestProblem(
        status=422,
        code="SCHEMA_INVALID",
        message=f"{path}: {detail}" if path != "$" else detail,
        field_path=path,
    )


def prepare_request(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    method: str,
    route_template: str,
    validator: RequestValidator,
    canonicalize: CanonicalizeFn,
) -> PreparedRequest:
    """解析 → 校验 → 键校验 → 规范哈希。任何 422 都在 409 之前返回。"""
    # 1. 先取 correlation_id；后续所有问题都带它。
    correlation_id = correlation_id_from_headers(headers)
    # 2. UTF-8 解码；失败即 422，不尝试 latin-1 回退。
    try:
        text = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        return PreparedRequest(
            raw_body=raw_body, payload=None, validated=None, binding=None,
            problem=RequestProblem(
                status=422, code="SCHEMA_INVALID",
                message="请求体必须是 UTF-8 编码的 JSON。", field_path="$",
            ),
            correlation_id=correlation_id,
        )
    # 3. strict JSON：重复键 / NaN / Infinity 在解析层拒绝。
    try:
        from researchflow.contracts.parsing import ContractJSONError, loads_strict

        payload = loads_strict(text)
    except ImportError:
        # 伪代码阶段不执行；实现阶段必须真实导入，不得用宽松 json.loads 兜底。
        raise
    except Exception as exc:  # ContractJSONError / UnicodeDecodeError
        pointer = getattr(exc, "pointer", "$")
        message = getattr(exc, "message", "JSON 解析失败")
        return PreparedRequest(
            raw_body=raw_body, payload=None, validated=None, binding=None,
            problem=RequestProblem(
                status=422, code="SCHEMA_INVALID", message=str(message), field_path=str(pointer)
            ),
            correlation_id=correlation_id,
        )
    # 4. 顶层必须是对象；数组/标量不进入模型。
    if not isinstance(payload, dict):
        return PreparedRequest(
            raw_body=raw_body, payload=None, validated=None, binding=None,
            problem=RequestProblem(
                status=422, code="SCHEMA_INVALID",
                message="请求体必须是 JSON 对象。", field_path="$",
            ),
            correlation_id=correlation_id,
        )
    # 5. 模型严格校验；422 优先于任何幂等判断。
    try:
        validated = validator.validate(payload)
    except Exception as exc:
        # 只有 pydantic.ValidationError 才按字段错误渲染；其它异常上抛，避免掩盖缺陷。
        if exc.__class__.__name__ != "ValidationError":
            raise
        return PreparedRequest(
            raw_body=raw_body, payload=payload, validated=None, binding=None,
            problem=problem_from_validation(exc), correlation_id=correlation_id,
        )
    # 6. 取幂等键；未提供 → 不启用幂等（每次创建都是新任务）。
    try:
        key = key_from_headers(headers)
        if key is not None:
            validate_idempotency_key(key)
    except RequestProblem as problem:
        return PreparedRequest(
            raw_body=raw_body, payload=payload, validated=None, binding=None,
            problem=problem, correlation_id=correlation_id,
        )
    # 7. 有键才计算哈希；哈希覆盖方法、路由模板和规范化体。
    binding: IdempotencyBinding | None = None
    if key is not None:
        binding = IdempotencyBinding(
            scope=route_template,
            key=key,
            request_hash=canonical_request_hash(
                method=method, route_template=route_template,
                payload=payload, canonicalize=canonicalize,
            ),
        )
    # 8. 成功返回；`problem=None` 是进入路由的必要条件。
    return PreparedRequest(
        raw_body=raw_body, payload=payload, validated=validated,
        binding=binding, problem=None, correlation_id=correlation_id,
    )


def decide_replay(binding: IdempotencyBinding, stored: StoredResponse | None) -> ConflictDecision:
    """同键同体 → REPLAY；同键异体 → CONFLICT；无记录 → MISS。"""
    # 1. 无记录：交给创建端口做原子插入。
    if stored is None:
        return ConflictDecision(decision=IdempotencyDecision.MISS, stored=None, reason=None)
    # 2. 作用域/键必须匹配；存储实现若串了记录，按实现错误处理。
    if stored.scope != binding.scope or stored.key != binding.key:
        raise ValueError("幂等存储返回了不同 scope/key 的记录")
    # 3. 只缓存成功的 201；其它状态说明创建端口未按契约写入，必须显式失败。
    if stored.status_code != 201:
        raise ValueError(f"幂等记录缓存了非 201 响应：{stored.status_code}")
    # 4. 哈希相同才回放；回放的是已提交任务的原始 201。
    if stored.request_hash == binding.request_hash:
        return ConflictDecision(decision=IdempotencyDecision.REPLAY, stored=stored, reason=None)
    # 5. 哈希不同：409，且不得创建任务、不得覆盖旧记录。
    return ConflictDecision(
        decision=IdempotencyDecision.CONFLICT, stored=None, reason="REQUEST_HASH_MISMATCH"
    )


def _json_bytes(body: Mapping[str, Any]) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class IdempotencyMiddleware:
    """ASGI 中间件：只在登记的 POST 路由上做幂等预检。

    顺序写死：strict parse → 模型校验（422）→ 键校验（422）→ 哈希 → 回放/冲突（409）。
    这样与 `researchflow/api/app.py` 的 422 行为一致；不会出现“先 409 再 422”。
    """

    def __init__(
        self,
        app: Callable[[dict[str, Any], Callable[[], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], Awaitable[None]]], Awaitable[None]],
        *,
        store: IdempotencyStore,
        validator: RequestValidator,
        canonicalize: CanonicalizeFn,
        routes: Mapping[str, str] | None = None,
    ) -> None:
        self.app = app
        self.store = store
        self.validator = validator
        self.canonicalize = canonicalize
        # 路径 → 路由模板（scope）。T0 只登记创建任务；T2 再加 harness events。
        self.routes = dict(routes or {"/api/v1/tasks": "/api/v1/tasks"})

    async def __call__(self, scope: dict[str, Any], receive: Callable[[], Awaitable[dict[str, Any]]], send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        # 1. 只处理登记的 POST；其余原样透传。
        if scope.get("type") != "http" or scope.get("method", "").upper() != "POST":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        route_template = self.routes.get(path)
        if route_template is None:
            await self.app(scope, receive, send)
            return
        # 2. 没有幂等键 → 不读 body、不做哈希，直接透传（保持流式行为）。
        try:
            raw_headers = self._headers(scope)
        except RequestProblem as problem:
            await self._send_problem(scope, send, problem, f"req-{uuid.uuid4().hex}")
            return
        if key_from_headers(raw_headers) is None:
            await self.app(scope, receive, send)
            return
        # 3. 有键才缓冲 body；超过上限按 413（非 E.3）拒绝。
        raw_body = await self._read_body(receive)
        if raw_body is None:
            await self._send_plain(scope, send, status=413, detail="request body too large")
            return
        # 4. 准备请求；422 在 409 之前。
        prepared = prepare_request(
            raw_body=raw_body, headers=raw_headers, method="POST",
            route_template=route_template, validator=self.validator,
            canonicalize=self.canonicalize,
        )
        if prepared.problem is not None:
            await self._send_problem(scope, send, prepared.problem, prepared.correlation_id)
            return
        binding = prepared.binding
        if binding is None:  # 理论上不会发生：有键才进入本分支
            await self.app(scope, receive, send)
            return
        # 5. 只读查询：回放或冲突都在路由之前返回；MISS 才进入原子创建。
        decision = decide_replay(binding, self.store.get(binding.scope, binding.key))
        if decision.decision == IdempotencyDecision.REPLAY:
            assert decision.stored is not None
            await self._send_stored(send, decision.stored)
            return
        if decision.decision == IdempotencyDecision.CONFLICT:
            status, headers, body = build_error_response(
                error_code="IDEMPOTENCY_CONFLICT",
                message="相同 Idempotency-Key 对应不同请求体。",
                correlation_id=prepared.correlation_id,
                reason="REQUEST_HASH_MISMATCH",
            )
            await self._send_json(send, status, headers, body)
            return
        # 6. 注入已解析上下文；路由不得再次宽松解析原始 body。
        scope.setdefault("state", {})["rf.idempotency"] = prepared
        cached_receive = self._replay_receive(raw_body)
        await self.app(scope, cached_receive, send)

    @staticmethod
    def _headers(scope: Mapping[str, Any]) -> dict[str, str]:
        """ASGI headers 是 bytes 对；同名头出现两次按实现错误拒绝。"""
        result: dict[str, str] = {}
        for name, value in scope.get("headers", []):
            key = name.decode("latin-1").lower()
            text = value.decode("latin-1")
            if key in result:
                raise RequestProblem(
                    status=422, code="SCHEMA_INVALID",
                    message=f"请求头 {key} 重复。", field_path=f"header.{key}",
                    reason="DUPLICATE_HEADER",
                )
            result[key] = text
        return result

    @staticmethod
    async def _read_body(receive: Callable[[], Awaitable[dict[str, Any]]]) -> bytes | None:
        """读完 body；超过上限返回 None（调用方发 413）。"""
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                raise RuntimeError("读取 body 时收到非 http.request 消息")
            chunk = bytes(message.get("body", b""))
            total += len(chunk)
            if total > MAX_BODY_BYTES:
                return None
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        return b"".join(chunks)

    @staticmethod
    def _replay_receive(raw_body: bytes) -> Callable[[], Awaitable[dict[str, Any]]]:
        """把已读 body 重新供给路由；只发一次 request + 一次空 more_body。"""
        sent = False

        async def _receive() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": raw_body, "more_body": False}
            return {"type": "http.disconnect"}

        return _receive

    async def _send_problem(self, scope: Mapping[str, Any], send: Callable[[dict[str, Any]], Awaitable[None]], problem: RequestProblem, correlation_id: str) -> None:
        # 1. 有 E.3 码走统一响应体；无码只用于 413 等传输层拒绝。
        if problem.code is not None:
            status, headers, body = build_error_response(
                error_code=problem.code, message=problem.message,
                correlation_id=correlation_id, field_path=problem.field_path,
                reason=problem.reason,
            )
            await self._send_json(send, status, headers, body)
            return
        # 2. 无码：仍带 correlation_id，但不伪造 error_code。
        await self._send_plain(
            scope, send, status=problem.status,
            detail=problem.message, reason=problem.reason, correlation_id=correlation_id,
        )

    async def _send_stored(self, send: Callable[[dict[str, Any]], Awaitable[None]], stored: StoredResponse) -> None:
        # 1. 只回放白名单头；禁止回放 Set-Cookie/Date/Server。
        headers = {
            key: str(value) for key, value in stored.headers.items()
            if key.lower() in {"content-type", "location"}
        }
        headers["content-length"] = str(len(stored.body))
        headers["idempotency-replayed"] = "true"
        # 2. 状态码与 body 原样回放；不得重新序列化。
        await send({"type": "http.response.start", "status": stored.status_code,
                    "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]})
        await send({"type": "http.response.body", "body": stored.body, "more_body": False})

    async def _send_json(self, send: Callable[[dict[str, Any]], Awaitable[None]], status: int, headers: Mapping[str, str], body: Mapping[str, Any]) -> None:
        payload = _json_bytes(body)
        merged = dict(headers)
        merged["content-length"] = str(len(payload))
        await send({"type": "http.response.start", "status": status,
                    "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in merged.items()]})
        await send({"type": "http.response.body", "body": payload, "more_body": False})

    async def _send_plain(self, scope: Mapping[str, Any], send: Callable[[dict[str, Any]], Awaitable[None]], *, status: int, detail: str, reason: str | None = None, correlation_id: str | None = None) -> None:
        # 1. 传输层拒绝：`error_code` 不出现，避免被误读为 E.3 第 14 码。
        body: dict[str, Any] = {"detail": detail, "correlation_id": correlation_id or f"req-{uuid.uuid4().hex}"}
        if reason is not None:
            body["reason"] = reason
        payload = _json_bytes(body)
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                (b"content-length", str(len(payload)).encode("ascii"))]})
        await send({"type": "http.response.body", "body": payload, "more_body": False})


MANUAL_CHECKS: Final[tuple[str, ...]] = (
    "prepare_request 的调用必须先于 store.get 与创建端口调用（422 先于 409）",
    "key 缺失分支必须直接 app(...)，不得 await _read_body（保持流式）",
    "_send_stored 必须发送 stored.body 原字节，不得 json.dumps 重排",
)


def assert_middleware_semantics() -> tuple[str, ...]:
    """静态判据：中间件不得写任务、不得把 409 放在 422 前、不得非幂等重试。

    返回空元组才算通过；涉及调用顺序的三条无法由类型系统表达，登记在
    `MANUAL_CHECKS`，由落地阶段的负例逐条锁定。
    """
    problems: list[str] = []
    # 1. 中间件只依赖 store.get；协议不得暴露写方法（写权限属创建端口）。
    if hasattr(IdempotencyStore, "put") or hasattr(IdempotencyStore, "insert"):
        problems.append("IdempotencyStore 暴露了写方法；写权限应只属于创建端口")
    # 2. 幂等哈希域不得为空，且不得把键本身混入哈希（键是查找维度，不是内容）。
    if not CANONICAL_DOMAIN:
        problems.append("CANONICAL_DOMAIN 为空")
    # 3. 键上限与正则必须一致。
    if MAX_KEY_LEN != 255 or _KEY_RE.pattern != r"^[\x21-\x7e]{1,255}$":
        problems.append("幂等键约束与 255/可见 ASCII 约定不一致")
    # 4. 无 IN_PROGRESS 分支：原子性由创建端口承担。
    if hasattr(IdempotencyDecision, "IN_PROGRESS"):
        problems.append("中间件不得引入 IN_PROGRESS 预占，避免双写幂等表")
    return tuple(problems)