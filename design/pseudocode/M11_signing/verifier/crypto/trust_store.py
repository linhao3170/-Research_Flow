"""MODULE: M11 · verifier/crypto/trust_store.py — 外部信任锚与公钥指纹（P6 伪代码）
阶段/追踪: P6「签名与离线凭证」｜FR-008/FR-009、NFR-05/NFR-07、策划书 §7.5（P0178）、§7.6（R04）
FR/依赖: FR-009；被 verify_bundle 使用；只依赖 jcs/payloads/ed25519_signer，不依赖数据库/模型/私钥模块
不变量/错误码: 验签只认 `--trust-store` 提供的包外公钥；证书自带的 `key_fingerprint` 只是被比对声明，
              不是信任来源；信任库不得位于证据包内；空库/未知指纹/撤销 key 一律 fail-closed。
              错误码：TRUST_ANCHOR_MISSING（503）或 SIGNATURE_INVALID（422，撤销/过期/指纹不符）
写入者: **无**；只读信任库文件，不写文件、不写日志、不碰私钥
状态: 伪代码；信任库 JSON 格式是 P6 内部格式（非 G0 契约），见 OQ-P6-06

## 为什么“证书自带公钥”不能作为信任来源

  如果验签方从证据包里取公钥，攻击者只需替换包内的公钥并用对应私钥重签，
  整个包就会“自洽地通过”。因此：

  1. 信任决定只来自**包外** `trusted_keys.json`（由独立渠道分发）；
  2. 证书里的 `key_fingerprint` 只用来和信任库比对，**不参与构造信任**；
  3. 证据包里的 `trusted_key_fingerprint.json` 只是“签发方声称用了哪把钥匙”，
     必须与信任库交叉核对；它若出现公钥字段，直接拒绝（`BUNDLE_SUPPLIES_PUBLIC_KEY`）；
  4. `--trust-store` 路径不得位于证据包目录内，防止“包内自带信任库”自证；
  5. 可选 `--trust-store-sha256` 把信任库文件哈希钉在命令行/发布说明里，
     防替换信任库本身。

## 信任库格式（P6 内部，v1.0）

  ```json
  {
    "schema_version": "1.0",
    "policy": "REVOKE_ALL",
    "keys": [
      {
        "key_id": "verifier-key-01",
        "public_key": "<base64(32-byte raw Ed25519 public key)>",
        "fingerprint_sha256": "<sha256(raw public key) hex>",
        "purpose": "signing",
        "status": "ACTIVE",
        "not_before": "2026-11-01T00:00:00Z",
        "not_after": "2027-11-01T00:00:00Z",
        "revoked_at": null,
        "revocation_reason": null
      }
    ]
  }
  ```

  严格拒绝：未知顶层/条目字段、空 keys、重复 key_id/fingerprint、指纹与公钥不符、
  任何 `private_key`/`seed`/`secret`/`passphrase` 字段、`policy != REVOKE_ALL`。

## 残余风险（必须写进评审）

  - 信任库是快照：签发之后再撤销的 key，离线旧快照不会知道；必须重新分发信任库。
  - 信任库本身没有签名；其完整性靠发布渠道 + `--trust-store-sha256` 钉死。
  - 同机管理员可替换信任库与工具；本模块不承诺抵御本机 root（与 §7.7 一致）。
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final, Mapping

from verifier.crypto import jcs
from verifier.crypto.ed25519_signer import decode_public_key
from verifier.crypto.payloads import parse_rfc3339_utc

__all__ = [
    "TRUST_STORE_SCHEMA_VERSION",
    "TrustAnchorError",
    "TrustStore",
    "TrustedKey",
    "assert_bundle_does_not_supply_trust",
    "assert_trust_store_not_inside_bundle",
    "load_trust_store",
]

TRUST_STORE_SCHEMA_VERSION: Final[str] = "1.0"
_REVOCATION_POLICY: Final[str] = "REVOKE_ALL"
_KEY_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_HASH64_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_MAX_TRUST_STORE_BYTES: Final[int] = 1024 * 1024

_KEY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "key_id",
        "public_key",
        "fingerprint_sha256",
        "purpose",
        "status",
        "not_before",
        "not_after",
        "revoked_at",
        "revocation_reason",
    }
)
_FORBIDDEN_MATERIAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "private_key",
        "private_key_b64",
        "private_key_seed",
        "key_seed",
        "secret",
        "passphrase",
        "private",
    }
)


class TrustAnchorError(RuntimeError):
    """信任锚缺失/不可用/被包内材料替换；映射 `TRUST_ANCHOR_MISSING`(503)。

    职责：把“没有可信锚”与“签名不对”分开，避免把配置问题误报成伪造。
    输入：reason、message、field_path、detail。
    输出：异常。
    副作用：无。
    不变量：message 不回显公钥/私钥/信任库全文。
    错误：本类自身。
    """

    error_code: Final[str] = "TRUST_ANCHOR_MISSING"
    http_status: Final[int] = 503

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        field_path: str = "trust_store",
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.reason = reason
        self.field_path = field_path
        self.detail = dict(detail or {})
        super().__init__(f"{self.error_code}/{reason} @ {field_path}: {message}")


class TrustSignatureError(RuntimeError):
    """已找到可信 key，但 key 已撤销/过期/指纹不符；映射 `SIGNATURE_INVALID`(422)。"""

    error_code: Final[str] = "SIGNATURE_INVALID"
    http_status: Final[int] = 422

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        field_path: str = "key_id",
        key_id: str | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.reason = reason
        self.field_path = field_path
        self.key_id = key_id
        self.detail = dict(detail or {})
        super().__init__(f"{self.error_code}/{reason} @ {field_path}: {message}")


class TrustedKeyStatus(StrEnum):
    """信任库中的 key 状态；REVOKED 也可由 revoked_at 非空推导。"""

    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class TrustedKey:
    """一把被外部信任的公钥及其有效期/撤销信息。"""

    key_id: str
    public_key_b64: str
    fingerprint_sha256: str
    purpose: str
    status: TrustedKeyStatus
    not_before: str
    not_after: str
    revoked_at: str | None = None
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        # 1. key_id 形态。
        if not isinstance(self.key_id, str) or _KEY_ID_RE.match(self.key_id) is None:
            raise TrustAnchorError("TRUST_KEY_ID_INVALID", f"key_id 形态非法：{self.key_id!r}", field_path="key_id")
        # 2. 公钥 32 字节；指纹必须重算一致。
        try:
            raw = decode_public_key(self.public_key_b64)
        except Exception as exc:
            raise TrustAnchorError(
                "TRUST_PUBLIC_KEY_INVALID",
                "信任库公钥不是 32 字节规范 base64",
                field_path="public_key",
            ) from exc
        expected = hashlib.sha256(raw).hexdigest()
        if self.fingerprint_sha256 != expected:
            raise TrustAnchorError(
                "TRUST_FINGERPRINT_MISMATCH",
                "信任库 fingerprint 与公钥重算值不一致",
                field_path="fingerprint_sha256",
                detail={"expected": expected, "actual": self.fingerprint_sha256},
            )
        # 3. purpose 与状态。
        if self.purpose not in {"signing", "anchor"}:
            raise TrustAnchorError(
                "TRUST_PURPOSE_INVALID",
                f"purpose 必须是 signing/anchor，实际 {self.purpose!r}",
                field_path="purpose",
            )
        if not isinstance(self.status, TrustedKeyStatus):
            raise TrustAnchorError("TRUST_STATUS_INVALID", "status 必须是 TrustedKeyStatus", field_path="status")
        # 4. 时间窗口。
        try:
            not_before = parse_rfc3339_utc(self.not_before, field_path="not_before")
            not_after = parse_rfc3339_utc(self.not_after, field_path="not_after")
        except Exception as exc:
            raise TrustAnchorError(
                "TRUST_TIME_INVALID",
                "not_before/not_after 必须是 UTC RFC 3339",
                field_path="not_before",
            ) from exc
        if not not_before < not_after:
            raise TrustAnchorError("TRUST_TIME_INVALID", "not_before 必须早于 not_after", field_path="not_before")
        # 5. 撤销字段自洽：REVOKED 必须有 revoked_at；非 REVOKED 不得有 revoked_at。
        if self.status is TrustedKeyStatus.REVOKED:
            if self.revoked_at is None:
                raise TrustAnchorError("TRUST_REVOCATION_INCOMPLETE", "REVOKED key 必须带 revoked_at")
            try:
                parse_rfc3339_utc(self.revoked_at, field_path="revoked_at")
            except Exception as exc:
                raise TrustAnchorError(
                    "TRUST_TIME_INVALID",
                    "revoked_at 必须是 UTC RFC 3339",
                    field_path="revoked_at",
                ) from exc
            if not self.revocation_reason:
                raise TrustAnchorError("TRUST_REVOCATION_INCOMPLETE", "REVOKED key 必须带 reason")
        else:
            if self.revoked_at is not None or self.revocation_reason is not None:
                raise TrustAnchorError(
                    "TRUST_REVOCATION_INCONSISTENT",
                    "非 REVOKED key 不得带 revoked_at/revocation_reason",
                    field_path="revoked_at",
                )

    def is_revoked(self) -> bool:
        """状态为 REVOKED 或带 revoked_at 即视为撤销。"""
        return self.status is TrustedKeyStatus.REVOKED or self.revoked_at is not None

    def assert_within_validity(self, issued_at: str) -> None:
        """检查签发时间是否落在 key 有效期内；越界抛 TrustSignatureError。"""
        moment = parse_rfc3339_utc(issued_at, field_path="issued_at")
        not_before = parse_rfc3339_utc(self.not_before, field_path="not_before")
        not_after = parse_rfc3339_utc(self.not_after, field_path="not_after")
        if moment < not_before:
            raise TrustSignatureError(
                "KEY_NOT_YET_VALID",
                f"签发时间早于 key 生效时间 {self.not_before}",
                field_path="issued_at",
                key_id=self.key_id,
            )
        if moment > not_after:
            raise TrustSignatureError(
                "KEY_EXPIRED",
                f"签发时间晚于 key 过期时间 {self.not_after}",
                field_path="issued_at",
                key_id=self.key_id,
            )


@dataclass(frozen=True, slots=True)
class TrustStore:
    """已加载的外部信任库；只公开 key_id/指纹/公钥，不公开私钥（本来就没有）。"""

    path: str
    document_sha256: str
    keys: Mapping[str, TrustedKey]
    policy: str = _REVOCATION_POLICY

    @classmethod
    def load(
        cls,
        path: str | os.PathLike[str],
        *,
        bundle_root: str | os.PathLike[str] | None = None,
        expected_sha256: str | None = None,
    ) -> "TrustStore":
        """严格加载信任库；空库/包内库/哈希不符/含私钥字段一律拒绝。

        职责：把“外部信任锚”变成可验证的数据结构。
        输入：信任库路径、证据包根（用于拒绝包内自证）、可选钉死哈希。
        输出：`TrustStore`。
        副作用：只读文件。
        不变量：
          1. 文件是普通文件、非符号链接、大小受限；
          2. 不在 bundle_root 内；
          3. 若给 expected_sha256，文件字节哈希必须相等；
          4. keys 非空、唯一、指纹重算一致。
        错误：`TrustAnchorError`（TRUST_STORE_*）。
        """
        # 1. 路径必须存在、是普通文件、非符号链接。
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        if candidate.is_symlink():
            raise TrustAnchorError("TRUST_STORE_SYMLINK", "信任库不得是符号链接", field_path="trust_store")
        try:
            info = candidate.stat()
        except FileNotFoundError as exc:
            raise TrustAnchorError("TRUST_STORE_MISSING", "信任库文件不存在", field_path="trust_store") from exc
        if not candidate.is_file():
            raise TrustAnchorError("TRUST_STORE_NOT_FILE", "信任库必须是普通文件", field_path="trust_store")
        if info.st_size > _MAX_TRUST_STORE_BYTES:
            raise TrustAnchorError("TRUST_STORE_TOO_LARGE", "信任库文件过大", field_path="trust_store")

        # 2. 不得位于证据包内；包内自带信任库等于自证。
        if bundle_root is not None:
            assert_trust_store_not_inside_bundle(candidate, bundle_root)

        # 3. 读取字节并计算哈希；可选钉死值。
        data = candidate.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None:
            if _HASH64_RE.match(expected_sha256) is None:
                raise TrustAnchorError(
                    "TRUST_STORE_PIN_FORMAT_INVALID",
                    "expected_sha256 必须是 64 位小写十六进制",
                    field_path="trust_store_sha256",
                )
            if digest != expected_sha256:
                raise TrustAnchorError(
                    "TRUST_STORE_HASH_MISMATCH",
                    "信任库哈希与钉死值不一致",
                    field_path="trust_store_sha256",
                    detail={"expected": expected_sha256, "actual": digest},
                )

        # 4. 严格 JSON 解析；重复键/NaN 在解析层拒绝。
        try:
            document = jcs.parse_strict(data)
        except jcs.JcsError as exc:
            raise TrustAnchorError(
                "TRUST_STORE_INVALID_JSON",
                f"信任库不是合法 JSON：{exc.reason}",
                field_path="trust_store",
            ) from exc
        if not isinstance(document, Mapping):
            raise TrustAnchorError("TRUST_STORE_INVALID", "信任库顶层必须是 object", field_path="trust_store")

        # 5. 顶层字段严格；未知字段拒绝，防止偷偷塞入“信任开关”。
        allowed_top = {"schema_version", "policy", "keys"}
        unknown_top = sorted(set(document.keys()) - allowed_top)
        if unknown_top:
            raise TrustAnchorError(
                "TRUST_STORE_UNKNOWN_FIELD",
                f"信任库不允许字段：{unknown_top}",
                field_path=unknown_top[0],
            )
        if document.get("schema_version") != TRUST_STORE_SCHEMA_VERSION:
            raise TrustAnchorError(
                "TRUST_STORE_VERSION_UNSUPPORTED",
                f"信任库版本必须是 {TRUST_STORE_SCHEMA_VERSION}",
                field_path="schema_version",
            )
        if document.get("policy", _REVOCATION_POLICY) != _REVOCATION_POLICY:
            raise TrustAnchorError(
                "TRUST_REVOCATION_POLICY_UNSUPPORTED",
                f"只支持 {_REVOCATION_POLICY}，收到 {document.get('policy')!r}",
                field_path="policy",
            )

        # 6. keys 必须是非空数组；逐条严格构造。
        raw_keys = document.get("keys")
        if not isinstance(raw_keys, list) or not raw_keys:
            raise TrustAnchorError("TRUST_STORE_EMPTY", "信任库不得为空", field_path="keys")
        keys: dict[str, TrustedKey] = {}
        fingerprints: set[str] = set()
        for index, raw_key in enumerate(raw_keys):
            item_path = f"keys[{index}]"
            if not isinstance(raw_key, Mapping):
                raise TrustAnchorError("TRUST_STORE_INVALID", "keys 元素必须是 object", field_path=item_path)
            unknown = sorted(set(raw_key.keys()) - _KEY_FIELDS)
            if unknown:
                raise TrustAnchorError(
                    "TRUST_STORE_UNKNOWN_FIELD",
                    f"key 条目不允许字段：{unknown}",
                    field_path=f"{item_path}.{unknown[0]}",
                )
            # 2.1 `_KEY_FIELDS` 已拒绝 private_key/seed/secret 等字段；这里不再用
            #     “禁用 public_key”的扫描（信任库条目本来就允许 public_key）。
            key = TrustedKey(
                key_id=str(raw_key.get("key_id", "")),
                public_key_b64=str(raw_key.get("public_key", "")),
                fingerprint_sha256=str(raw_key.get("fingerprint_sha256", "")),
                purpose=str(raw_key.get("purpose", "")),
                status=_parse_status(raw_key.get("status")),
                not_before=str(raw_key.get("not_before", "")),
                not_after=str(raw_key.get("not_after", "")),
                revoked_at=raw_key.get("revoked_at") if isinstance(raw_key.get("revoked_at"), str) else None,
                revocation_reason=(
                    raw_key.get("revocation_reason")
                    if isinstance(raw_key.get("revocation_reason"), str)
                    else None
                ),
            )
            if key.key_id in keys:
                raise TrustAnchorError("TRUST_KEY_ID_DUPLICATED", f"key_id 重复：{key.key_id}", field_path=item_path)
            if key.fingerprint_sha256 in fingerprints:
                raise TrustAnchorError(
                    "TRUST_FINGERPRINT_DUPLICATED",
                    f"指纹重复：{key.fingerprint_sha256}",
                    field_path=item_path,
                )
            keys[key.key_id] = key
            fingerprints.add(key.fingerprint_sha256)

        # 7. 返回不可变快照。
        return cls(
            path=str(candidate),
            document_sha256=digest,
            keys=MappingProxyType(keys),
            policy=_REVOCATION_POLICY,
        )

    def lookup(
        self,
        key_id: str,
        fingerprint_sha256: str | None,
        issued_at: str,
        *,
        purpose: str = "signing",
    ) -> TrustedKey:
        """按 key_id/指纹/purpose/时间取可信 key；失败区分“不在锚内”与“key 不可用”。

        错误：
          - TRUST_ANCHOR_MISSING/KEY_NOT_IN_TRUST_STORE：锚里没有这把 key；
          - TrustSignatureError：key 撤销/过期/指纹不符/purpose 不符。
        """
        # 1. key_id 必须在信任库内。
        key = self.keys.get(key_id)
        if key is None:
            # 1.1 指纹若命中另一把 key，说明 key_id 被换过，是签名问题而不是缺锚。
            if fingerprint_sha256 is not None:
                for candidate in self.keys.values():
                    if candidate.fingerprint_sha256 == fingerprint_sha256:
                        raise TrustSignatureError(
                            "KEY_ID_MISMATCH",
                            f"指纹属于 key_id={candidate.key_id!r}，不是 {key_id!r}",
                            key_id=key_id,
                        )
            raise TrustAnchorError(
                "KEY_NOT_IN_TRUST_STORE",
                f"key_id 不在外部信任锚内：{key_id!r}",
                field_path="key_id",
                detail={"key_id": key_id},
            )

        # 2. 指纹必须匹配（证书声明的指纹只在这里参与比对，不构造信任）。
        if fingerprint_sha256 is not None and fingerprint_sha256 != key.fingerprint_sha256:
            raise TrustSignatureError(
                "KEY_FINGERPRINT_MISMATCH",
                "声明的 key_fingerprint 与信任锚记录不一致",
                field_path="key_fingerprint",
                key_id=key_id,
            )

        # 3. purpose 必须匹配。
        if key.purpose != purpose:
            raise TrustSignatureError(
                "KEY_PURPOSE_MISMATCH",
                f"key purpose={key.purpose!r}，期望 {purpose!r}",
                field_path="purpose",
                key_id=key_id,
            )

        # 4. 撤销优先；离线默认拒绝全部历史签名。
        if key.is_revoked():
            raise TrustSignatureError(
                "KEY_REVOKED",
                f"key 已撤销：{key_id}",
                field_path="key_id",
                key_id=key_id,
                detail={"revoked_at": key.revoked_at},
            )

        # 5. 有效期检查（按对象自报的 issued_at，仅用于明显越界；不是可信时间）。
        key.assert_within_validity(issued_at)

        # 6. 返回可信 key。
        return key

    def resolve_anchor_key(self) -> TrustedKey:
        """返回唯一的 anchor-purpose 可信 key；0 个或多个都拒绝。

        错误：TRUST_ANCHOR_MISSING/ANCHOR_KEY_MISSING 或 ANCHOR_KEY_AMBIGUOUS。
        """
        candidates = [key for key in self.keys.values() if key.purpose == "anchor" and not key.is_revoked()]
        if not candidates:
            raise TrustAnchorError("ANCHOR_KEY_MISSING", "信任库没有可用的 anchor key", field_path="purpose")
        if len(candidates) > 1:
            raise TrustAnchorError(
                "ANCHOR_KEY_AMBIGUOUS",
                "信任库有多个 anchor key，无法确定 AnchorProof 的验签钥匙",
                field_path="purpose",
            )
        return candidates[0]

    def public_fingerprints(self) -> Mapping[str, str]:
        """返回 key_id → fingerprint 的只读映射；用于与包内声明交叉核对。"""
        return MappingProxyType({key_id: key.fingerprint_sha256 for key_id, key in self.keys.items()})


def load_trust_store(
    path: str | os.PathLike[str],
    *,
    bundle_root: str | os.PathLike[str] | None = None,
    expected_sha256: str | None = None,
) -> TrustStore:
    """`TrustStore.load` 的函数入口；便于 CLI 与测试使用。"""
    return TrustStore.load(path, bundle_root=bundle_root, expected_sha256=expected_sha256)


def assert_trust_store_not_inside_bundle(
    trust_store_path: str | os.PathLike[str],
    bundle_root: str | os.PathLike[str],
) -> None:
    """拒绝“证据包自带信任库”的自证路径。

    职责：比较两个 realpath，信任库不得等于/位于 bundle_root 之下。
    输入：信任库路径、证据包根。
    输出：None。
    副作用：只读文件系统元数据。
    不变量：bundle_root 必须是目录；信任库不得在其子树内。
    错误：`TrustAnchorError(TRUST_STORE_INSIDE_BUNDLE)`。
    """
    # 1. 解析 realpath；不追随符号链接做“看似在外”的判断。
    trust = Path(trust_store_path).expanduser().resolve(strict=False)
    bundle = Path(bundle_root).expanduser().resolve(strict=False)
    # 2. 比较；相同或前缀相同都拒绝。
    try:
        if os.path.commonpath([str(trust), str(bundle)]) == str(bundle):
            raise TrustAnchorError(
                "TRUST_STORE_INSIDE_BUNDLE",
                "信任库不得位于证据包内（包内公钥/信任库不能自证）",
                field_path="trust_store",
            )
    except ValueError:
        # 不同卷必然不在同一子树；放行。
        return


def assert_bundle_does_not_supply_trust(bundle_root: str | os.PathLike[str]) -> None:
    """检查包内 `trusted_key_fingerprint.json` 只有指纹声明，没有公钥/私钥材料。

    职责：阻止证据包用自带公钥构造信任。
    输入：证据包根。
    输出：None。
    副作用：读取一个 JSON 文件；不写。
    不变量：允许 `key_id`/`key_fingerprint`/`fingerprint_sha256`；禁止 public_key/private_key/seed 等。
    错误：`TrustAnchorError(BUNDLE_SUPPLIES_TRUST_MATERIAL)` 或 `TRUST_STORE_INVALID_JSON`。
    """
    # 1. 文件不存在时交给清单检查（缺必检文件由 BUNDLE 层报）。
    candidate = Path(bundle_root) / "trusted_key_fingerprint.json"
    if not candidate.exists():
        return
    # 2. 严格解析。
    try:
        document = jcs.parse_strict(candidate.read_bytes())
    except (OSError, jcs.JcsError) as exc:
        raise TrustAnchorError(
            "BUNDLE_TRUST_CLAIM_INVALID",
            "包内指纹声明不是合法 JSON",
            field_path="trusted_key_fingerprint.json",
        ) from exc
    # 3. 递归扫描禁止字段；公钥只能来自包外信任库。
    if _contains_forbidden_material(document):
        raise TrustAnchorError(
            "BUNDLE_SUPPLIES_TRUST_MATERIAL",
            "证据包不得包含公钥/私钥/seed；信任只能来自包外 trust store",
            field_path="trusted_key_fingerprint.json",
        )


def _contains_forbidden_material(value: object) -> bool:
    """递归检查映射键是否出现私钥/公钥材料字段。"""
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _FORBIDDEN_MATERIAL_KEYS:
                return True
            if normalized in {"public_key", "public_key_b64", "keys"}:
                # `keys` 本身可能只是声明列表；只有其内部出现 public_key 才算违规。
                if normalized == "keys":
                    if _contains_forbidden_material(item):
                        return True
                    continue
                return True
            if _contains_forbidden_material(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden_material(item) for item in value)
    return False


def _parse_status(value: object) -> TrustedKeyStatus:
    """把信任库 status 字段解析为枚举；未知值拒绝。"""
    if isinstance(value, TrustedKeyStatus):
        return value
    if not isinstance(value, str):
        raise TrustAnchorError("TRUST_STATUS_INVALID", f"status 必须是字符串，实际 {type(value).__name__}")
    try:
        return TrustedKeyStatus(value)
    except ValueError as exc:
        raise TrustAnchorError("TRUST_STATUS_INVALID", f"未知 status：{value!r}") from exc