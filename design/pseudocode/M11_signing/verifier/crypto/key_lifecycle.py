"""MODULE: M11 · verifier/crypto/key_lifecycle.py — key_id、有效期、轮换、撤销与私钥边界（P6 伪代码）
阶段/追踪: P6「签名与离线凭证」｜FR-008、NFR-05、策划书 §7.6（TABLE 33）
FR/依赖: FR-008；被 Verifier 签发路径使用；离线验签只读取 `to_trust_document()` 的公开部分
不变量/错误码: 私钥只允许 Verifier 进程读取；私钥不得进日志/证据包/前端；key_id 唯一、指纹唯一；
              有效期用 UTC 闭区间；撤销只追加、不可撤销“撤销”；历史证书默认 REVOKE_ALL。
              错误码：SIGNATURE_INVALID（422）+ reason；私钥文件/角色错误同码
写入者: **无**；不写密钥文件、不写日志；只读密钥文件并构造内存句柄
状态: 伪代码；Windows ACL/OS key store 属部署（OQ-P6-05/OQ-P6-06），本文件只钉进程/路径/权限检查

## 7.6 的五个环节与本模块落点

  | 环节 | 7.6 要求 | 本模块落点 |
  |---|---|---|
  | 生成 | Verifier 初始化或受控密钥工具生成；开发密钥与交付信任锚分开 | `KeyRecord` 只描述公钥；生成工具不在本文件（部署脚本） |
  | 存储 | 受限目录/ACL/系统密钥存储；最小权限 | `load_private_key` 检查角色、路径、符号链接、POSIX 权限/Windows ACL 声明 |
  | 信任 | 预置公钥指纹；不信任证书自带公钥 | 本模块只导出公开信任文档；信任判断在 `trust_store.py` |
  | 轮换 | key_id、有效期、撤销列表；明确历史证书策略 | `rotate` / `revoke` / `resolve_for_verify` |
  | 锚定 | 优先独立时间戳或第二存储；本地副本只称备份 | 不在本文件；见 `packager` 的 anchor absent 语义 |

## 默认历史策略：REVOKE_ALL（保守）

  离线验签没有可信时钟：对象里的 `issued_at` 是签发方自报的，不能证明“签名发生在撤销之前”。
  因此默认策略是：**key_id 一旦出现在撤销列表，该 key 的所有签名一律拒绝**，
  包括撤销前签发的历史证书。这样不会把“已被攻破的钥匙”继续当成可信来源。

  代价：合法历史在撤销后不可离线验证。要恢复历史验证，必须引入外部时间锚
  （`AnchorProof` 的可信时间戳）或在线撤销状态；两者都不在 T0。该取舍登记为
  `OQ-P6-05`，不得在代码里静默放宽。

## 私钥边界的诚实声明

  `process_role` 与 `env_role` 双检查能阻止“普通 Worker 误用 Verifier 钥匙文件”，
  但**不能**阻止同机管理员/同权限进程读取文件。真正的 OS 级隔离依赖部署时的 ACL、
  受限用户或系统密钥存储（`OQ-P6-06`）。本模块不声称“已实现 OS 沙箱”。
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Final, Mapping, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from verifier.crypto.ed25519_signer import (
    SignerError,
    decode_public_key,
    encode_public_key,
    fingerprint_public_key,
)
from verifier.crypto.payloads import parse_rfc3339_utc

__all__ = [
    "DEFAULT_REVOCATION_POLICY",
    "KEY_ROLE_VERIFIER",
    "KeyLifecycleError",
    "KeyRecord",
    "KeyStatus",
    "Keyring",
    "PrivateKeyHandle",
    "Revocation",
    "assert_private_key_location",
    "assert_verifier_process",
    "load_private_key",
]

KEY_ROLE_VERIFIER: Final[str] = "verifier"
DEFAULT_REVOCATION_POLICY: Final[str] = "REVOKE_ALL"
_KEY_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_PURPOSES: Final[frozenset[str]] = frozenset({"signing", "anchor"})
_MAX_PRIVATE_KEY_BYTES: Final[int] = 16 * 1024


class KeyLifecycleError(RuntimeError):
    """密钥生命周期/私钥读取拒绝；映射 `SIGNATURE_INVALID`(422)。

    职责：把角色、路径、权限、有效期、撤销等原因固定成可断言 reason。
    输入：reason、message、field_path、key_id、detail。
    输出：异常。
    副作用：无。
    不变量：message 不含私钥字节、路径中的用户名、passphrase。
    错误：本类自身；调用方必须断言 reason。
    """

    error_code: Final[str] = "SIGNATURE_INVALID"
    http_status: Final[int] = 422

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        field_path: str = "key",
        key_id: str | None = None,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.reason = reason
        self.field_path = field_path
        self.key_id = key_id
        self.detail = dict(detail or {})
        super().__init__(f"{self.error_code}/{reason} @ {field_path}: {message}")


class KeyStatus(StrEnum):
    """密钥生命周期状态；`REVOKED` 由撤销列表覆盖，不改写 record 本身。"""

    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class KeyRecord:
    """一把公钥及其生命周期元数据；**不含私钥**。"""

    key_id: str
    public_key_b64: str
    fingerprint_sha256: str
    purpose: str
    status: KeyStatus
    not_before: str
    not_after: str
    created_at: str
    replaced_by: str | None = None

    def __post_init__(self) -> None:
        # 1. key_id 形态。
        if not isinstance(self.key_id, str) or _KEY_ID_RE.match(self.key_id) is None:
            raise KeyLifecycleError(
                "KEY_ID_INVALID",
                f"key_id 形态非法：{self.key_id!r}",
                field_path="key_id",
                key_id=self.key_id,
            )
        # 2. 公钥必须是 32 字节原始编码；指纹必须由公钥重算，不能自报。
        try:
            raw = decode_public_key(self.public_key_b64)
            expected_fingerprint = hashlib.sha256(raw).hexdigest()
        except SignerError as exc:
            raise KeyLifecycleError(
                "KEY_PUBLIC_KEY_INVALID",
                f"公钥非法：{exc.reason}",
                field_path="public_key_b64",
                key_id=self.key_id,
            ) from exc
        if self.fingerprint_sha256 != expected_fingerprint:
            raise KeyLifecycleError(
                "KEY_FINGERPRINT_MISMATCH",
                "fingerprint 与公钥重算值不一致",
                field_path="fingerprint_sha256",
                key_id=self.key_id,
                detail={"expected": expected_fingerprint, "actual": self.fingerprint_sha256},
            )
        # 3. purpose 与状态。
        if self.purpose not in _PURPOSES:
            raise KeyLifecycleError(
                "KEY_PURPOSE_INVALID",
                f"purpose 必须是 {sorted(_PURPOSES)} 之一",
                field_path="purpose",
                key_id=self.key_id,
            )
        if not isinstance(self.status, KeyStatus):
            raise KeyLifecycleError(
                "KEY_STATUS_INVALID",
                f"status 必须是 KeyStatus，实际 {type(self.status).__name__}",
                field_path="status",
                key_id=self.key_id,
            )
        # 3.1 REVOKED 只能由撤销列表表达；record 本身不写 REVOKED，避免“撤销了但没时间/原因”。
        if self.status is KeyStatus.REVOKED:
            raise KeyLifecycleError(
                "KEY_STATUS_INVALID",
                "KeyRecord 不得直接标记 REVOKED；必须通过 Keyring.revoke 追加撤销记录",
                field_path="status",
                key_id=self.key_id,
            )
        # 4. 时间必须是 UTC，且 not_before < not_after。
        try:
            not_before = parse_rfc3339_utc(self.not_before, field_path="not_before")
            not_after = parse_rfc3339_utc(self.not_after, field_path="not_after")
            created_at = parse_rfc3339_utc(self.created_at, field_path="created_at")
        except Exception as exc:
            raise KeyLifecycleError(
                "KEY_TIME_INVALID",
                "not_before/not_after/created_at 必须是 UTC RFC 3339",
                field_path="not_before",
                key_id=self.key_id,
            ) from exc
        if not not_before < not_after:
            raise KeyLifecycleError(
                "KEY_TIME_INVALID",
                "not_before 必须早于 not_after",
                field_path="not_before",
                key_id=self.key_id,
            )
        if created_at > not_after:
            raise KeyLifecycleError(
                "KEY_TIME_INVALID",
                "created_at 不得晚于 not_after",
                field_path="created_at",
                key_id=self.key_id,
            )
        # 5. replaced_by 只允许在 RETIRED 时出现，且不能等于自身。
        if self.replaced_by is not None:
            if self.status is not KeyStatus.RETIRED:
                raise KeyLifecycleError(
                    "KEY_REPLACED_BY_INVALID",
                    "只有 RETIRED 密钥可以有 replaced_by",
                    field_path="replaced_by",
                    key_id=self.key_id,
                )
            if self.replaced_by == self.key_id:
                raise KeyLifecycleError(
                    "KEY_REPLACED_BY_INVALID",
                    "replaced_by 不得指向自身",
                    field_path="replaced_by",
                    key_id=self.key_id,
                )


@dataclass(frozen=True, slots=True)
class Revocation:
    """一条撤销记录；只追加，不提供“撤销撤销”的操作。"""

    key_id: str
    revoked_at: str
    reason: str

    def __post_init__(self) -> None:
        # 1. key_id 形态。
        if not isinstance(self.key_id, str) or _KEY_ID_RE.match(self.key_id) is None:
            raise KeyLifecycleError("KEY_ID_INVALID", f"key_id 形态非法：{self.key_id!r}", field_path="key_id")
        # 2. 时间必须是 UTC。
        try:
            parse_rfc3339_utc(self.revoked_at, field_path="revoked_at")
        except Exception as exc:
            raise KeyLifecycleError(
                "KEY_TIME_INVALID",
                "revoked_at 必须是 UTC RFC 3339",
                field_path="revoked_at",
                key_id=self.key_id,
            ) from exc
        # 3. 原因必须非空；撤销不是无记录操作。
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise KeyLifecycleError(
                "KEY_REVOCATION_REASON_MISSING",
                "撤销必须给出非空 reason",
                field_path="reason",
                key_id=self.key_id,
            )


@dataclass(frozen=True, slots=True)
class Keyring:
    """一组公钥 + 撤销列表的不可变快照；轮换/撤销返回新实例。"""

    records: Mapping[str, KeyRecord]
    revocations: tuple[Revocation, ...] = ()

    def __post_init__(self) -> None:
        # 1. key_id 与 fingerprint 都必须唯一；不同 key_id 共用一把钥匙会让撤销失效。
        if not self.records:
            raise KeyLifecycleError("KEYRING_EMPTY", "密钥环不得为空")
        fingerprints: set[str] = set()
        for key_id, record in self.records.items():
            if key_id != record.key_id:
                raise KeyLifecycleError("KEYRING_KEY_MISMATCH", "records 键与 record.key_id 不一致")
            if record.fingerprint_sha256 in fingerprints:
                raise KeyLifecycleError(
                    "KEY_FINGERPRINT_DUPLICATED",
                    f"同一指纹被多把 key 复用：{record.fingerprint_sha256}",
                    key_id=key_id,
                )
            fingerprints.add(record.fingerprint_sha256)
        # 2. 撤销记录必须指向已登记 key，且同一 key 只能撤销一次。
        revoked: set[str] = set()
        for revocation in self.revocations:
            if revocation.key_id not in self.records:
                raise KeyLifecycleError(
                    "KEY_REVOCATION_UNKNOWN_KEY",
                    f"撤销了未登记的 key：{revocation.key_id}",
                    key_id=revocation.key_id,
                )
            if revocation.key_id in revoked:
                raise KeyLifecycleError(
                    "KEY_REVOCATION_DUPLICATED",
                    f"同一 key 重复撤销：{revocation.key_id}",
                    key_id=revocation.key_id,
                )
            revoked.add(revocation.key_id)

    @classmethod
    def from_records(
        cls,
        records: Sequence[KeyRecord],
        revocations: Sequence[Revocation] = (),
    ) -> "Keyring":
        """从序列构造；重复 key_id 显式拒绝。"""
        mapping: dict[str, KeyRecord] = {}
        for record in records:
            if record.key_id in mapping:
                raise KeyLifecycleError("KEY_ID_DUPLICATED", f"key_id 重复：{record.key_id}", key_id=record.key_id)
            mapping[record.key_id] = record
        return cls(records=MappingProxyType(mapping), revocations=tuple(revocations))

    def record(self, key_id: str) -> KeyRecord:
        """按 key_id 取记录；不存在即拒绝。"""
        try:
            return self.records[key_id]
        except KeyError as exc:
            raise KeyLifecycleError("KEY_UNKNOWN", f"未登记 key_id：{key_id!r}", key_id=key_id) from exc

    def revocation_for(self, key_id: str) -> Revocation | None:
        """返回该 key 的撤销记录；没有则 None。"""
        for revocation in self.revocations:
            if revocation.key_id == key_id:
                return revocation
        return None

    def effective_status(self, key_id: str) -> KeyStatus:
        """撤销列表优先于 record.status；撤销后不再回到 ACTIVE。"""
        if self.revocation_for(key_id) is not None:
            return KeyStatus.REVOKED
        return self.record(key_id).status

    def resolve_for_sign(self, key_id: str, at: str) -> KeyRecord:
        """签发路径：只允许 ACTIVE、未撤销、在有效期内的 key。

        错误：KEY_UNKNOWN / KEY_REVOKED / KEY_NOT_ACTIVE / KEY_NOT_YET_VALID / KEY_EXPIRED。
        """
        # 1. 记录存在。
        record = self.record(key_id)
        # 2. 撤销优先。
        if self.revocation_for(key_id) is not None:
            raise KeyLifecycleError("KEY_REVOKED", f"key 已撤销：{key_id}", key_id=key_id)
        # 3. 只有 ACTIVE 能签新东西。
        if record.status is not KeyStatus.ACTIVE:
            raise KeyLifecycleError(
                "KEY_NOT_ACTIVE",
                f"key 状态为 {record.status.value}，不得签发",
                field_path="status",
                key_id=key_id,
            )
        # 4. 有效期检查。
        _assert_within_validity(record, at)
        return record

    def resolve_for_verify(
        self,
        key_id: str,
        fingerprint_sha256: str | None,
        issued_at: str,
        *,
        policy: str = DEFAULT_REVOCATION_POLICY,
    ) -> KeyRecord:
        """验签路径：撤销一律拒绝（REVOKE_ALL）；RETIRED 在有效期内仍可验旧签名。

        错误：KEY_UNKNOWN / KEY_FINGERPRINT_MISMATCH / KEY_REVOKED / KEY_NOT_YET_VALID / KEY_EXPIRED /
              KEY_REVOCATION_POLICY_UNSUPPORTED。
        """
        # 1. 只支持默认策略；其他策略必须显式实现并登记，不得“看起来支持”。
        if policy != DEFAULT_REVOCATION_POLICY:
            raise KeyLifecycleError(
                "KEY_REVOCATION_POLICY_UNSUPPORTED",
                f"未实现的历史策略：{policy!r}",
                field_path="policy",
                key_id=key_id,
            )
        # 2. 记录存在。
        record = self.record(key_id)
        # 3. 指纹可选；提供时必须与记录一致。
        if fingerprint_sha256 is not None and fingerprint_sha256 != record.fingerprint_sha256:
            raise KeyLifecycleError(
                "KEY_FINGERPRINT_MISMATCH",
                "调用方给的指纹与密钥记录不一致",
                field_path="key_fingerprint",
                key_id=key_id,
            )
        # 4. 撤销优先：即使 issued_at 早于撤销时间也拒绝（离线无可信时钟）。
        revocation = self.revocation_for(key_id)
        if revocation is not None:
            raise KeyLifecycleError(
                "KEY_REVOKED",
                f"key 已于 {revocation.revoked_at} 撤销；离线默认拒绝全部历史签名",
                field_path="key_id",
                key_id=key_id,
                detail={"revoked_at": revocation.revoked_at, "policy": policy},
            )
        # 5. 有效期检查。
        _assert_within_validity(record, issued_at)
        return record

    def rotate(
        self,
        old_key_id: str,
        new_record: KeyRecord,
        *,
        retire_at: str | None = None,
    ) -> "Keyring":
        """轮换：旧 key 标记 RETIRED，新 key 加入；不允许有效期空档。

        规则：
          1. 旧 key 必须 ACTIVE 且未撤销；
          2. 新旧 key_id/指纹不同，purpose 相同；
          3. 新 key 的 not_before 不得早于旧 key 的 not_before；
          4. retire_at 默认 = 新 key.not_before；必须落在旧 key 有效期内，且不得早于新 key 生效；
          5. 返回新 Keyring，旧实例不变。
        """
        # 1. 旧记录与状态。
        old = self.record(old_key_id)
        if self.revocation_for(old_key_id) is not None or old.status is not KeyStatus.ACTIVE:
            raise KeyLifecycleError(
                "KEY_NOT_ACTIVE",
                "只有 ACTIVE 且未撤销的 key 可以轮换",
                field_path="status",
                key_id=old_key_id,
            )
        # 2. 新记录不得与现有 key 冲突。
        if new_record.status is not KeyStatus.ACTIVE:
            raise KeyLifecycleError(
                "KEY_NOT_ACTIVE",
                "新 key 必须是 ACTIVE",
                field_path="status",
                key_id=new_record.key_id,
            )
        if new_record.key_id in self.records or new_record.key_id == old_key_id:
            raise KeyLifecycleError("KEY_ID_DUPLICATED", f"新 key_id 已存在：{new_record.key_id}", key_id=new_record.key_id)
        if new_record.fingerprint_sha256 == old.fingerprint_sha256:
            raise KeyLifecycleError("KEY_FINGERPRINT_DUPLICATED", "新旧 key 指纹相同，轮换无意义", key_id=new_record.key_id)
        if new_record.purpose != old.purpose:
            raise KeyLifecycleError("KEY_PURPOSE_MISMATCH", "轮换双方 purpose 必须一致", field_path="purpose")
        # 3. 时间顺序。
        old_before = parse_rfc3339_utc(old.not_before)
        old_after = parse_rfc3339_utc(old.not_after)
        new_before = parse_rfc3339_utc(new_record.not_before)
        if new_before < old_before:
            raise KeyLifecycleError("KEY_ROTATION_ORDER", "新 key 生效时间不得早于旧 key", field_path="not_before")
        retirement = parse_rfc3339_utc(retire_at) if retire_at is not None else new_before
        if retirement < old_before or retirement > old_after:
            raise KeyLifecycleError(
                "KEY_ROTATION_RETIRE_OUT_OF_RANGE",
                "retire_at 必须落在旧 key 有效期内",
                field_path="retire_at",
                key_id=old_key_id,
            )
        new_after = parse_rfc3339_utc(new_record.not_after)
        if new_after < retirement:
            raise KeyLifecycleError(
                "KEY_ROTATION_GAP",
                "新 key 在旧 key 退休前就过期，会留下签名空档",
                field_path="not_after",
                key_id=new_record.key_id,
            )
        if retirement < new_before:
            raise KeyLifecycleError(
                "KEY_ROTATION_GAP",
                "旧 key 退休早于新 key 生效，会留下签名空档",
                field_path="retire_at",
            )
        # 4. 构造退休后的旧记录与新映射。
        retired_old = replace(
            old,
            status=KeyStatus.RETIRED,
            not_after=retirement.isoformat().replace("+00:00", "Z"),
            replaced_by=new_record.key_id,
        )
        records = dict(self.records)
        records[old_key_id] = retired_old
        records[new_record.key_id] = new_record
        # 5. 返回新快照。
        return Keyring(records=MappingProxyType(records), revocations=self.revocations)

    def revoke(self, key_id: str, *, revoked_at: str, reason: str) -> "Keyring":
        """追加撤销；已撤销的 key 再次撤销显式拒绝，不静默覆盖原因。"""
        # 1. 记录必须存在。
        self.record(key_id)
        # 2. 不得重复撤销。
        if self.revocation_for(key_id) is not None:
            raise KeyLifecycleError("KEY_ALREADY_REVOKED", f"key 已撤销：{key_id}", key_id=key_id)
        # 3. 追加并返回新快照。
        revocation = Revocation(key_id=key_id, revoked_at=revoked_at, reason=reason)
        return Keyring(records=self.records, revocations=(*self.revocations, revocation))

    def to_trust_document(self) -> Mapping[str, object]:
        """导出公开信任文档（`trusted_keys.json` 的内容），不含任何私钥。

        输出字段：schema_version、keys[]（key_id/public_key/fingerprint/purpose/status/
        not_before/not_after/revoked_at/revocation_reason）。可由部署方离线分发。
        """
        keys: list[Mapping[str, object]] = []
        for record in sorted(self.records.values(), key=lambda item: item.key_id):
            revocation = self.revocation_for(record.key_id)
            keys.append(
                MappingProxyType(
                    {
                        "key_id": record.key_id,
                        "public_key": record.public_key_b64,
                        "fingerprint_sha256": record.fingerprint_sha256,
                        "purpose": record.purpose,
                        "status": self.effective_status(record.key_id).value,
                        "not_before": record.not_before,
                        "not_after": record.not_after,
                        "revoked_at": revocation.revoked_at if revocation else None,
                        "revocation_reason": revocation.reason if revocation else None,
                    }
                )
            )
        return MappingProxyType(
            {
                "schema_version": "1.0",
                "policy": DEFAULT_REVOCATION_POLICY,
                "keys": list(keys),
            }
        )


def _assert_within_validity(record: KeyRecord, at: str) -> None:
    """检查 `at` 落在 [not_before, not_after] 闭区间；越界区分“未生效/已过期”。"""
    # 1. 解析时间。
    moment = parse_rfc3339_utc(at, field_path="issued_at")
    not_before = parse_rfc3339_utc(record.not_before, field_path="not_before")
    not_after = parse_rfc3339_utc(record.not_after, field_path="not_after")
    # 2. 未生效。
    if moment < not_before:
        raise KeyLifecycleError(
            "KEY_NOT_YET_VALID",
            f"签名时间 {at} 早于 key 生效时间 {record.not_before}",
            field_path="issued_at",
            key_id=record.key_id,
        )
    # 3. 已过期。
    if moment > not_after:
        raise KeyLifecycleError(
            "KEY_EXPIRED",
            f"签名时间 {at} 晚于 key 过期时间 {record.not_after}",
            field_path="issued_at",
            key_id=record.key_id,
        )
    # 4. 通过。
    return


# ---------------------------------------------------------------------------
# 私钥：只允许 Verifier 进程读取
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class PrivateKeyHandle:
    """Verifier 进程内的私钥句柄；只暴露 sign 与公开标识。

    不变量：`_private_key` 不出现在 repr/str/异常；不提供 `private_bytes()`；
             `__reduce__` 拒绝 pickle，避免私钥被序列化进日志/队列/证据包。
    """

    key_id: str
    _private_key: Ed25519PrivateKey
    public_key_b64: str
    fingerprint_sha256: str

    def __repr__(self) -> str:
        # 只显示 key_id；不显示路径、seed、私钥字节。
        return f"<PrivateKeyHandle key_id={self.key_id!r} private=REDACTED>"

    def __str__(self) -> str:
        return self.__repr__()

    def __reduce__(self) -> object:
        # pickle 会把私钥带进任意持久化位置；必须拒绝。
        raise KeyLifecycleError(
            "PRIVATE_KEY_EXPORT_FORBIDDEN",
            "PrivateKeyHandle 不允许 pickle/序列化",
            key_id=self.key_id,
        )

    def sign(self, message: bytes) -> bytes:
        """对域分离后的字节签名；不打印/不缓存 message。"""
        if not isinstance(message, bytes) or not message:
            raise KeyLifecycleError("PRIVATE_KEY_SIGN_EMPTY", "签名消息必须是非空 bytes", key_id=self.key_id)
        return self._private_key.sign(message)

    def public_key(self) -> Ed25519PublicKey:
        """返回对应公钥对象（公开信息，可安全传递）。"""
        return self._private_key.public_key()


def assert_verifier_process(process_role: str, env_role: str | None) -> None:
    """双检查：显式角色与进程环境都必须是 verifier。

    职责：阻止 Executor/Agent/打包器误读私钥。
    输入：调用方声明的角色、进程环境 `RF_PROCESS_ROLE`。
    输出：None。
    副作用：无。
    不变量：两者都等于 `verifier` 才放行；不得只看环境变量（可被伪造）。
    错误：`KeyLifecycleError(PRIVATE_KEY_ROLE_FORBIDDEN)`。
    """
    # 1. 显式角色。
    if process_role != KEY_ROLE_VERIFIER:
        raise KeyLifecycleError(
            "PRIVATE_KEY_ROLE_FORBIDDEN",
            f"只有 Verifier 进程可以读取私钥，当前角色={process_role!r}",
            field_path="process_role",
        )
    # 2. 进程环境。
    if env_role != KEY_ROLE_VERIFIER:
        raise KeyLifecycleError(
            "PRIVATE_KEY_ROLE_FORBIDDEN",
            f"RF_PROCESS_ROLE 必须是 verifier，当前={env_role!r}",
            field_path="RF_PROCESS_ROLE",
        )


def assert_private_key_location(
    path: str | os.PathLike[str],
    key_dir: str | os.PathLike[str],
    *,
    forbidden_roots: Sequence[str | os.PathLike[str]] = (),
) -> Path:
    """检查私钥路径：在 key_dir 内、无符号链接、不落在仓库/工作区/证据包根下。

    职责：把“私钥只放在受限目录”变成代码可检查的路径约束。
    输入：私钥路径、密钥目录、禁止根列表。
    输出：解析后的绝对 Path。
    副作用：读取文件系统元数据，不读私钥内容。
    不变量：最终路径必须在 key_dir 内；路径任一段不得是符号链接；key_dir 不得在 forbidden_roots 内。
    错误：`KeyLifecycleError`（PRIVATE_KEY_PATH_*）。
    """
    # 1. 解析绝对路径；不追随符号链接做“看似在目录内”的判断。
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    key_root = Path(key_dir).expanduser()
    if not key_root.is_absolute():
        key_root = Path.cwd() / key_root

    # 2. 检查路径组件中的符号链接（含最后一个组件）。
    current = candidate
    while True:
        if current.is_symlink():
            raise KeyLifecycleError(
                "PRIVATE_KEY_PATH_SYMLINK",
                f"私钥路径不得包含符号链接：{current.name}",
                field_path="path",
            )
        if current == current.parent:
            break
        current = current.parent

    # 3. 必须在 key_dir 内；用 commonpath 防 `..` 逃逸与同前缀目录。
    try:
        candidate_real = candidate.resolve(strict=False)
        key_root_real = key_root.resolve(strict=False)
        if os.path.commonpath([str(candidate_real), str(key_root_real)]) != str(key_root_real):
            raise KeyLifecycleError(
                "PRIVATE_KEY_PATH_OUTSIDE_KEY_DIR",
                "私钥必须位于配置的 key_dir 内",
                field_path="path",
            )
    except ValueError as exc:
        raise KeyLifecycleError(
            "PRIVATE_KEY_PATH_OUTSIDE_KEY_DIR",
            "私钥路径与 key_dir 不在同一卷",
            field_path="path",
        ) from exc

    # 4. key_dir 不得位于仓库/工作区/证据包等禁止根内。
    for forbidden in forbidden_roots:
        forbidden_real = Path(forbidden).expanduser().resolve(strict=False)
        try:
            if os.path.commonpath([str(key_root_real), str(forbidden_real)]) == str(forbidden_real):
                raise KeyLifecycleError(
                    "PRIVATE_KEY_DIR_FORBIDDEN",
                    "key_dir 不得位于仓库/工作区/证据包内",
                    field_path="key_dir",
                )
        except ValueError:
            continue

    # 5. 返回候选绝对路径。
    return candidate


def load_private_key(
    key_id: str,
    path: str | os.PathLike[str],
    *,
    keyring: Keyring,
    key_dir: str | os.PathLike[str],
    process_role: str,
    acl_verified: bool,
    env_role: str | None = None,
    forbidden_roots: Sequence[str | os.PathLike[str]] = (),
    password_provider: Callable[[], bytes] | None = None,
) -> PrivateKeyHandle:
    """在 Verifier 进程内加载私钥；任何边界不满足都拒绝。

    职责：角色检查、路径检查、权限检查、PEM 解析、公钥与 keyring 对账。
    输入：key_id、私钥路径、keyring、key_dir、角色、ACL 声明、可选环境角色一致性断言、
          禁止根、可选 passphrase provider。
    输出：`PrivateKeyHandle`。
    副作用：读取私钥文件；不写文件、不写日志。
    不变量：
      1. 私钥只能匹配 keyring 中登记的 key_id/公钥/指纹；
      2. 私钥文件不得是符号链接、不得在 key_dir 外；
      3. POSIX 下 mode 不得有 group/other 权限位；Windows 下必须有部署方 ACL 声明；
      4. passphrase 只从回调取，不落盘、不写 env、不写日志；
      5. 角色检查必须读取**真实进程环境** `os.environ["RF_PROCESS_ROLE"]`；
         `env_role` 只能是可选的一致性断言，不能替代真实环境。
    错误：`KeyLifecycleError`（PRIVATE_KEY_*）。
    """
    # 1. 角色双检查：显式角色 + 真实进程环境；env_role 若给出必须与真实值一致。
    actual_env_role = os.environ.get("RF_PROCESS_ROLE")
    assert_verifier_process(process_role, actual_env_role)
    if env_role is not None and env_role != actual_env_role:
        raise KeyLifecycleError(
            "PRIVATE_KEY_ROLE_FORBIDDEN",
            f"env_role={env_role!r} 与真实 RF_PROCESS_ROLE={actual_env_role!r} 不一致",
            field_path="RF_PROCESS_ROLE",
            key_id=key_id,
        )

    # 2. 路径检查。
    candidate = assert_private_key_location(path, key_dir, forbidden_roots=forbidden_roots)

    # 3. 文件必须存在、是普通文件、大小受限。
    try:
        info = candidate.stat()
    except FileNotFoundError as exc:
        raise KeyLifecycleError(
            "PRIVATE_KEY_FILE_MISSING",
            "私钥文件不存在",
            field_path="path",
            key_id=key_id,
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise KeyLifecycleError("PRIVATE_KEY_NOT_REGULAR", "私钥必须是普通文件", field_path="path", key_id=key_id)
    if info.st_size > _MAX_PRIVATE_KEY_BYTES:
        raise KeyLifecycleError(
            "PRIVATE_KEY_FILE_TOO_LARGE",
            f"私钥文件超过 {_MAX_PRIVATE_KEY_BYTES} 字节",
            field_path="path",
            key_id=key_id,
        )

    # 4. 先确认 key_id 已登记，避免为未知 key 读取任何私钥材料。
    record = keyring.record(key_id)

    # 5. POSIX 权限位；Windows 依赖部署方 ACL 声明（不能凭 stat 判断 ACL）。
    if os.name == "posix":
        if info.st_mode & 0o077:
            raise KeyLifecycleError(
                "PRIVATE_KEY_PERMISSIONS_TOO_OPEN",
                "私钥文件不得对 group/other 开放",
                field_path="path",
                key_id=key_id,
            )
    else:
        if acl_verified is not True:
            raise KeyLifecycleError(
                "PRIVATE_KEY_ACL_UNVERIFIED",
                "Windows 下必须由部署方确认 ACL 仅允许 Verifier 账户读取",
                field_path="acl_verified",
                key_id=key_id,
            )

    # 6. 读取并解析 PEM；passphrase 只从回调取。
    data = candidate.read_bytes()
    password = password_provider() if password_provider is not None else None
    try:
        loaded = serialization.load_pem_private_key(data, password=password)
    except TypeError as exc:
        raise KeyLifecycleError(
            "PRIVATE_KEY_PASSPHRASE_REQUIRED",
            "私钥已加密但未提供 passphrase provider",
            field_path="path",
            key_id=key_id,
        ) from exc
    except ValueError as exc:
        raise KeyLifecycleError(
            "PRIVATE_KEY_UNREADABLE",
            "私钥 PEM 无法解析或 passphrase 错误",
            field_path="path",
            key_id=key_id,
        ) from exc
    finally:
        # 7. 尽力清理内存中的 passphrase 与文件字节；Python bytes 不可变，只能减少引用。
        if isinstance(password, bytearray):
            password[:] = b"\x00" * len(password)
        del data

    # 8. 必须是 Ed25519 私钥。
    if not isinstance(loaded, Ed25519PrivateKey):
        raise KeyLifecycleError(
            "PRIVATE_KEY_NOT_ED25519",
            f"私钥类型必须是 Ed25519，实际 {type(loaded).__name__}",
            field_path="path",
            key_id=key_id,
        )

    # 9. 公钥必须与 keyring 登记一致（防“换钥匙文件”）。
    derived_public_b64 = encode_public_key(loaded.public_key())
    derived_fingerprint = fingerprint_public_key(derived_public_b64)
    if derived_public_b64 != record.public_key_b64 or derived_fingerprint != record.fingerprint_sha256:
        raise KeyLifecycleError(
            "PRIVATE_KEY_MISMATCH",
            "私钥推导出的公钥与 keyring 记录不一致",
            field_path="public_key",
            key_id=key_id,
        )

    # 10. 返回不透明句柄；不把文件路径写进对象。
    return PrivateKeyHandle(
        key_id=key_id,
        _private_key=loaded,
        public_key_b64=derived_public_b64,
        fingerprint_sha256=derived_fingerprint,
    )