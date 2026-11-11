"""MODULE: M11 · verifier/crypto/ed25519_signer.py — Ed25519 签名与验签（P6 伪代码）
阶段/追踪: P6「签名与离线凭证」｜FR-008、NFR-05、策划书 §7.5（RFC 8032 / Ed25519）、§7.6
FR/依赖: FR-008；输入是 payloads.SigningPayload（已含域前缀）与密钥句柄；依赖 cryptography 的 Ed25519 原语
不变量/错误码: 签名只针对 `domain_prefix || JCS(body)`；签名 64 字节、base64 标准编码；公钥 32 字节原始编码；
              私钥不得进入 repr/日志/异常/证据包；验签失败返回 bool + reason，不抛“通用错误”。
              错误码：SIGNATURE_INVALID（422）+ reason；签发期密钥不匹配也用本码
写入者: **无**；不写文件、不写日志、不写证据；只做密码学原语调用
状态: 伪代码；RFC 8032 向量在 WP-11 执行，本文件只钉输入/输出/失败原因

## 算法与编码（写给实现者）

  - 算法固定 **Ed25519（RFC 8032）**；不得自创曲线、哈希或“加盐”流程。
  - 签名输入：`SigningPayload.signing_bytes()` = 域前缀字节 || JCS(body) 的 UTF-8 字节。
    域前缀已经区分 Report / Certificate / DC / SPA，签名者不得再自行拼接 JSON 字段。
  - 签名输出：64 字节原始签名，标准 base64（带 `=` 填充，无换行）。
  - 公钥输入/输出：32 字节原始公钥的标准 base64；**不接受 PEM 混入**，
    避免同一把钥匙出现两种指纹口径。
  - 公钥指纹：`SHA-256(32 字节原始公钥)` 的小写十六进制；证书 `key_fingerprint` 与
    信任锚都按这个口径比较（`fingerprint_public_key`）。
  - 私钥：只通过 `key_lifecycle.PrivateKeyHandle` 暴露 `sign(message)`；
    本模块不提供 `private_bytes()`，也不接受裸私钥字节作为参数。

## 验签失败原因（必须逐条断言）

  | reason | 触发点 |
  |---|---|
  | `ALGORITHM_NOT_ED25519` | 对象 `alg` 不是 Ed25519（证书字段） |
  | `KEY_ID_MISMATCH` | 载荷 `key_id` 与调用方期望的 key_id 不同 |
  | `SIGNATURE_BASE64_INVALID` | 签名不是标准 base64 / 非规范编码 |
  | `SIGNATURE_LENGTH_INVALID` | 解码后不是 64 字节 |
  | `PUBLIC_KEY_BASE64_INVALID` | 公钥不是标准 base64 / 非规范编码 |
  | `PUBLIC_KEY_LENGTH_INVALID` | 解码后不是 32 字节 |
  | `PUBLIC_KEY_INVALID` | 32 字节不是合法 Ed25519 公钥点 |
  | `SIGNATURE_MISMATCH` | 数学验签失败（载荷被改、签名被改、钥匙不对） |

  **不得**把上述原因统一成 `False` 或 `1`；离线验签 CLI 要按原因映射退出码。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from verifier.crypto.payloads import PAYLOAD_SPECS, PayloadKind, SigningPayload

__all__ = [
    "ALGORITHM",
    "RFC8032_VECTOR_1",
    "SignerError",
    "SigningKeyPort",
    "VerifyResult",
    "assert_signer_boundary",
    "check_rfc8032_vector_1",
    "decode_public_key",
    "encode_public_key",
    "fingerprint_public_key",
    "sign",
    "signature_metadata",
    "verify",
    "verify_or_raise",
]

ALGORITHM: Final[str] = "Ed25519"
SIGNATURE_LENGTH: Final[int] = 64
PUBLIC_KEY_LENGTH: Final[int] = 32

# RFC 8032 §7.1 Test 1（空消息）；只用于密码学原语自检，不经过域前缀。
RFC8032_VECTOR_1: Final[Mapping[str, str]] = MappingProxyType(
    {
        "secret_key_hex": "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "public_key_hex": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "message_hex": "",
        "signature_hex": (
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
            "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        ),
    }
)


class SignerError(RuntimeError):
    """签名/验签域拒绝；映射 `SIGNATURE_INVALID`(422)。

    职责：携带可断言的 reason、字段路径与 key_id，不携带私钥、payload 正文或堆栈。
    输入：reason、message、field_path、key_id、detail。
    输出：异常。
    副作用：无。
    不变量：message 不得包含私钥字节、seed、完整载荷；日志只允许 key_id/哈希。
    错误：本类自身；调用方必须断言 reason。
    """

    error_code: Final[str] = "SIGNATURE_INVALID"
    http_status: Final[int] = 422

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        field_path: str = "signature",
        key_id: str | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.reason = reason
        self.field_path = field_path
        self.key_id = key_id
        self.detail = dict(detail or {})
        super().__init__(f"{self.error_code}/{reason} @ {field_path}: {message}")


class SigningKeyPort(Protocol):
    """签发方持有的私钥句柄；只暴露“标识 + 公钥 + 签名”，不暴露私钥字节。"""

    key_id: str
    public_key_b64: str
    fingerprint_sha256: str

    def sign(self, message: bytes) -> bytes:
        """对已经域分离的字节签名，返回 64 字节原始签名。"""
        ...


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """验签结果：bool + 失败原因码；成功时 reason=None。

    职责：把“是否通过”和“为什么失败”一起返回，供 CLI 映射退出码、供负例断言原因。
    输入：ok、reason、error_code、http_status、field_path、detail。
    输出：不可变结果对象。
    副作用：无。
    不变量：ok=True 时 reason/error_code 必须为 None；ok=False 时 reason 必须非空。
    错误：`raise_if_failed()` 抛 `SignerError`。
    """

    ok: bool
    reason: str | None = None
    error_code: str | None = None
    http_status: int = 422
    field_path: str = "signature"
    detail: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        # 1. 成功/失败字段必须自洽，禁止“ok=True 但有 reason”这种含糊结果。
        if self.ok and (self.reason is not None or self.error_code is not None):
            raise ValueError("VerifyResult(ok=True) 不得带 reason/error_code")
        if not self.ok and not self.reason:
            raise ValueError("VerifyResult(ok=False) 必须带 reason")

    def raise_if_failed(self) -> None:
        """失败时抛 `SignerError`；成功时静默返回。"""
        if self.ok:
            return
        raise SignerError(
            self.reason or "SIGNATURE_MISMATCH",
            "验签失败",
            field_path=self.field_path,
            detail=self.detail,
        )


# ---------------------------------------------------------------------------
# 1. 公钥编码 / 指纹
# ---------------------------------------------------------------------------
def encode_public_key(public_key: Ed25519PublicKey) -> str:
    """把 Ed25519 公钥编码为 32 字节原始公钥的 base64。"""
    # 1. 用 Raw/Raw 导出；不用 PEM，避免指纹口径分叉。
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    # 2. 标准 base64，带填充。
    return base64.b64encode(raw).decode("ascii")


def decode_public_key(public_key_b64: str) -> bytes:
    """严格解码公钥 base64 为 32 字节；非规范编码/长度错误一律拒绝。

    职责：统一公钥输入口径。
    输入：base64 字符串。
    输出：32 字节。
    副作用：无。
    不变量：只接受标准 alphabet、正确填充、无空白；解码后必须 32 字节。
    错误：`SignerError`（PUBLIC_KEY_BASE64_INVALID / PUBLIC_KEY_LENGTH_INVALID）。
    """
    # 1. 类型与非空。
    if not isinstance(public_key_b64, str) or not public_key_b64:
        raise SignerError("PUBLIC_KEY_BASE64_INVALID", "公钥必须是非空 base64 字符串", field_path="public_key")
    # 2. 严格解码；`validate=True` 拒绝非 alphabet 字符与错误填充。
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignerError(
            "PUBLIC_KEY_BASE64_INVALID",
            "公钥不是合法标准 base64",
            field_path="public_key",
        ) from exc
    # 3. 规范编码检查：防止攻击者用等价但不同的 base64 表示绕过“同一指纹”比较。
    if base64.b64encode(raw).decode("ascii") != public_key_b64:
        raise SignerError(
            "PUBLIC_KEY_BASE64_INVALID",
            "公钥 base64 不是规范编码",
            field_path="public_key",
        )
    # 4. 长度必须 32。
    if len(raw) != PUBLIC_KEY_LENGTH:
        raise SignerError(
            "PUBLIC_KEY_LENGTH_INVALID",
            f"Ed25519 公钥必须是 {PUBLIC_KEY_LENGTH} 字节，实际 {len(raw)}",
            field_path="public_key",
        )
    return raw


def fingerprint_public_key(public_key_b64: str) -> str:
    """返回公钥指纹：`SHA-256(32 字节原始公钥)` 小写十六进制。"""
    # 1. 严格解码。
    raw = decode_public_key(public_key_b64)
    # 2. 指纹只基于原始公钥字节，不基于 base64 文本或 PEM。
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# 2. 签名
# ---------------------------------------------------------------------------
def sign(payload: SigningPayload, key: SigningKeyPort) -> str:
    """对 `payload.signing_bytes()` 签名，返回标准 base64。

    职责：校验 key_id 一致，调用私钥句柄签名，编码为 base64。
    输入：`SigningPayload`、`SigningKeyPort`。
    输出：base64 字符串（64 字节签名）。
    副作用：只调用 key.sign；不写文件/日志。
    不变量：
      1. 只接受 `PAYLOAD_SPECS` 中已注册的 spec 对象（身份相等，不只内容相等）；
      2. 未冻结协议（DC/SPA）不得签名；
      3. Report/Certificate 的 final_state 必须是 VERIFIED，否则拒绝（不可绕过）；
      4. key.key_id == payload.key_id，否则拒绝（防止签错对象的 key_id）；
      5. 签名输入必须已经含域前缀；
      6. 返回的字符串可被 `verify` 原样接受。
    错误：`SignerError`（SIGNING_PAYLOAD_UNREGISTERED / SIGNING_PAYLOAD_NOT_FROZEN /
          SIGNING_REPORT_NOT_VERIFIED / SIGNING_CERT_NOT_VERIFIED /
          SIGNING_KEY_ID_MISMATCH / SIGNING_FAILED）。
    """
    # 1. 只接受注册 spec；伪造 `PayloadSpec(frozen=True, domain_prefix=...)` 不能绕白名单。
    registered_spec = PAYLOAD_SPECS.get((payload.kind, payload.version))
    if registered_spec is None or payload.spec is not registered_spec:
        raise SignerError(
            "SIGNING_PAYLOAD_UNREGISTERED",
            "签名载荷必须来自 build_payload/select_spec 返回的注册 spec",
            field_path="payload_kind",
            key_id=key.key_id,
        )

    # 2. 未冻结协议（DC/SPA）不得签发；即使调用方用 allow_proposed 构造了载荷。
    if not payload.spec.frozen:
        raise SignerError(
            "SIGNING_PAYLOAD_NOT_FROZEN",
            f"{payload.kind.value} 的 {payload.version} 载荷尚未冻结，T0 不得签发",
            field_path="payload_kind",
            key_id=key.key_id,
        )

    # 3. 只签 VERIFIED 的 Report/Certificate；这是最后一道不可绕过的守卫。
    if payload.kind is PayloadKind.REPORT and payload.body.get("final_state") != "VERIFIED":
        raise SignerError(
            "SIGNING_REPORT_NOT_VERIFIED",
            f"报告 final_state={payload.body.get('final_state')!r}，只有 VERIFIED 允许签名",
            field_path="final_state",
            key_id=key.key_id,
        )
    if payload.kind is PayloadKind.CERTIFICATE and payload.body.get("final_state") != "VERIFIED":
        raise SignerError(
            "SIGNING_CERT_NOT_VERIFIED",
            "证书 final_state 必须是 VERIFIED",
            field_path="final_state",
            key_id=key.key_id,
        )

    # 4. key_id 必须与载荷一致；不一致说明调用方拿错了钥匙。
    if key.key_id != payload.key_id:
        raise SignerError(
            "SIGNING_KEY_ID_MISMATCH",
            f"私钥 key_id={key.key_id!r} 与载荷 key_id={payload.key_id!r} 不一致",
            field_path="key_id",
            key_id=key.key_id,
        )

    # 5. 取已域分离的字节；禁止调用方传裸 JSON。
    message = payload.signing_bytes()

    # 6. 调用密码学原语；私钥句柄内部完成签名，不把私钥带出。
    try:
        signature = key.sign(message)
    except Exception as exc:  # 仅把“签名原语失败”包装成域错误，不吞掉原因类型
        raise SignerError(
            "SIGNING_FAILED",
            f"Ed25519 签名失败（{type(exc).__name__}）",
            key_id=key.key_id,
        ) from exc

    # 7. 长度检查；Ed25519 必须 64 字节。
    if not isinstance(signature, bytes) or len(signature) != SIGNATURE_LENGTH:
        raise SignerError(
            "SIGNING_FAILED",
            f"签名长度必须是 {SIGNATURE_LENGTH} 字节",
            key_id=key.key_id,
        )

    # 8. 标准 base64；带填充、无换行。
    encoded = base64.b64encode(signature).decode("ascii")

    # 9. 返回；调用方只能把 encoded 写入 `signature` 字段。
    return encoded


def signature_metadata(payload: SigningPayload, key: SigningKeyPort, signature_b64: str) -> Mapping[str, object]:
    """返回可安全写入审计日志的签名元数据（不含 payload 正文、不含私钥）。

    职责：给 Verifier 审计事件提供最小字段。
    输入：载荷、密钥句柄、签名 base64。
    输出：只读映射。
    副作用：无。
    不变量：字段只含 kind/version/key_id/fingerprint/哈希；不得含消息字节或私钥。
    错误：`SignerError(SIGNATURE_BASE64_INVALID)`（仅当编码非法；正常路径不抛）。
    """
    # 1. 校验签名编码（复用验签解码路径，保证与 verify 同口径）。
    raw = _decode_signature(signature_b64)
    # 2. 只记录哈希与标识；不记录签名全文（避免日志膨胀/关联风险）。
    return MappingProxyType(
        {
            "algorithm": ALGORITHM,
            "payload_kind": payload.kind.value,
            "schema_version": payload.version,
            "key_id": key.key_id,
            "key_fingerprint": key.fingerprint_sha256,
            "payload_sha256": payload.sha256_hex(),
            "signature_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )


def _decode_signature(signature_b64: str) -> bytes:
    """严格解码 64 字节签名；非规范 base64/长度错误拒绝。"""
    # 1. 类型与非空。
    if not isinstance(signature_b64, str) or not signature_b64:
        raise SignerError("SIGNATURE_BASE64_INVALID", "签名必须是非空 base64 字符串")
    # 2. 严格解码。
    try:
        raw = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignerError("SIGNATURE_BASE64_INVALID", "签名不是合法标准 base64") from exc
    # 3. 规范编码检查。
    if base64.b64encode(raw).decode("ascii") != signature_b64:
        raise SignerError("SIGNATURE_BASE64_INVALID", "签名 base64 不是规范编码")
    # 4. 长度检查。
    if len(raw) != SIGNATURE_LENGTH:
        raise SignerError(
            "SIGNATURE_LENGTH_INVALID",
            f"Ed25519 签名必须是 {SIGNATURE_LENGTH} 字节，实际 {len(raw)}",
        )
    return raw


# ---------------------------------------------------------------------------
# 3. 验签
# ---------------------------------------------------------------------------
def verify(
    payload: SigningPayload,
    signature_b64: str,
    public_key_b64: str,
    *,
    expected_key_id: str | None = None,
    alg: str = ALGORITHM,
) -> VerifyResult:
    """用给定公钥验签；返回 bool + 失败原因码，不用异常表达“签名不对”。

    职责：算法检查、key_id 检查、严格解码、Ed25519 验签。
    输入：载荷、签名 base64、公钥 base64、期望 key_id（可选）、alg（默认 Ed25519）。
    输出：`VerifyResult`。
    副作用：无。
    不变量：
      1. 签名输入必须由 payload 重新构造，不信任对象上的任何“已签名”标记；
      2. 失败原因必须区分编码/长度/钥匙/内容；
      3. 不做“尝试所有公钥”的模糊匹配（由 trust_store 先选钥匙）。
    错误：不抛；调用方用 `raise_if_failed()` 转异常。
    """
    # 1. 算法必须是 Ed25519；不接受 “ed25519”“ED25519”等变体。
    if alg != ALGORITHM:
        return VerifyResult(
            ok=False,
            reason="ALGORITHM_NOT_ED25519",
            error_code="SIGNATURE_INVALID",
            field_path="alg",
            detail={"expected": ALGORITHM, "actual": alg},
        )

    # 2. 期望 key_id 与载荷不一致时，先拒绝，避免用错钥匙得出“内容不对”的结论。
    if expected_key_id is not None and payload.key_id != expected_key_id:
        return VerifyResult(
            ok=False,
            reason="KEY_ID_MISMATCH",
            error_code="SIGNATURE_INVALID",
            field_path="key_id",
            detail={"expected": expected_key_id, "actual": payload.key_id},
        )

    # 3. 严格解码签名；失败原因保留。
    try:
        signature = _decode_signature(signature_b64)
    except SignerError as exc:
        return VerifyResult(
            ok=False,
            reason=exc.reason,
            error_code="SIGNATURE_INVALID",
            field_path=exc.field_path,
        )

    # 4. 严格解码公钥；失败原因保留。
    try:
        raw_public_key = decode_public_key(public_key_b64)
    except SignerError as exc:
        return VerifyResult(
            ok=False,
            reason=exc.reason,
            error_code="SIGNATURE_INVALID",
            field_path=exc.field_path,
        )

    # 5. 构造公钥对象；32 字节不一定是合法点。
    try:
        public_key = Ed25519PublicKey.from_public_bytes(raw_public_key)
    except ValueError:
        return VerifyResult(
            ok=False,
            reason="PUBLIC_KEY_INVALID",
            error_code="SIGNATURE_INVALID",
            field_path="public_key",
        )

    # 6. 重建签名输入并验签。
    message = payload.signing_bytes()
    try:
        public_key.verify(signature, message)
    except InvalidSignature:
        return VerifyResult(
            ok=False,
            reason="SIGNATURE_MISMATCH",
            error_code="SIGNATURE_INVALID",
            field_path="signature",
        )

    # 7. 成功。
    return VerifyResult(ok=True)


def verify_or_raise(
    payload: SigningPayload,
    signature_b64: str,
    public_key_b64: str,
    *,
    expected_key_id: str | None = None,
    alg: str = ALGORITHM,
) -> None:
    """`verify` 的抛异常版本；失败时抛 `SignerError`，成功静默返回。"""
    result = verify(
        payload,
        signature_b64,
        public_key_b64,
        expected_key_id=expected_key_id,
        alg=alg,
    )
    result.raise_if_failed()


# ---------------------------------------------------------------------------
# 4. RFC 8032 自检向量（WP-11 执行；本阶段只定义）
# ---------------------------------------------------------------------------
def check_rfc8032_vector_1() -> VerifyResult:
    """用 RFC 8032 §7.1 Test 1 检查 Ed25519 原语实现。

    职责：证明库的 Ed25519 实现符合标准；**不经过域前缀**，只测原语。
    输入：无（使用 `RFC8032_VECTOR_1`）。
    输出：`VerifyResult`；成功时 ok=True。
    副作用：在内存中生成一次签名；不写文件、不写日志。
    不变量：签名逐字节等于标准向量；公钥逐字节等于标准向量。
    错误：返回 ok=False + SIGNATURE_MISMATCH/PUBLIC_KEY_MISMATCH，不抛。
    """
    # 1. 从标准向量构造私钥。
    secret = bytes.fromhex(RFC8032_VECTOR_1["secret_key_hex"])
    private_key = Ed25519PrivateKey.from_private_bytes(secret)

    # 2. 对空消息签名；向量消息为空。
    signature = private_key.sign(b"")
    expected_signature = bytes.fromhex(RFC8032_VECTOR_1["signature_hex"])
    if signature != expected_signature:
        return VerifyResult(
            ok=False,
            reason="SIGNATURE_MISMATCH",
            error_code="SIGNATURE_INVALID",
            field_path="rfc8032.vector1.signature",
        )

    # 3. 导出公钥并逐字节比较。
    public_key = private_key.public_key()
    raw_public = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    expected_public = bytes.fromhex(RFC8032_VECTOR_1["public_key_hex"])
    if raw_public != expected_public:
        return VerifyResult(
            ok=False,
            reason="PUBLIC_KEY_MISMATCH",
            error_code="SIGNATURE_INVALID",
            field_path="rfc8032.vector1.public_key",
        )

    # 4. 用标准公钥验标准签名。
    try:
        public_key.verify(signature, b"")
    except InvalidSignature:
        return VerifyResult(
            ok=False,
            reason="SIGNATURE_MISMATCH",
            error_code="SIGNATURE_INVALID",
            field_path="rfc8032.vector1.verify",
        )

    # 5. 成功。
    return VerifyResult(ok=True)


# ---------------------------------------------------------------------------
# 5. 边界静态检查
# ---------------------------------------------------------------------------
def assert_signer_boundary() -> tuple[str, ...]:
    """返回签名模块的静态边界清单，供测试/评审逐条断言。

    职责：把“不得导出私钥/不得记录私钥”写成可检查的常量，而不是口头约定。
    输入：无。
    输出：不变量字符串元组。
    副作用：无。
    不变量：`__all__` 不含 `private_bytes`/`private_key`；`SigningKeyPort` 只有 sign。
    错误：无（纯返回）。
    """
    # 1. 公开符号不得包含私钥导出入口。
    forbidden_exports = {"private_bytes", "private_key", "export_private_key", "seed"}
    actual = set(__all__)
    if actual & forbidden_exports:
        raise AssertionError(f"签名模块不得导出私钥入口：{sorted(actual & forbidden_exports)}")

    # 2. 返回可审计的边界说明。
    return (
        "签名输入必须是 SigningPayload.signing_bytes()（含域前缀）",
        "私钥只能以 SigningKeyPort 形式传入，模块不提供导出函数",
        "签名/验签失败不得把私钥、seed、payload 正文写入日志或异常 message",
        "公钥只接受 32 字节原始编码的规范 base64；指纹 = SHA-256(raw)",
        "Ed25519 参数固定，不自创算法或额外哈希",
    )