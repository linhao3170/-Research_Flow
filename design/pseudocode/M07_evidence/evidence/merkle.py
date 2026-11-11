"""M07 · evidence/merkle.py — RFC 9162 Merkle 树、tree_size 与 inclusion proof（P4 伪代码）。
阶段：P4「模板与证据链」｜追踪：FR-005（证据根可校验）、FR-006（Gate/报告）、策划书 §7.3
依赖：M07 chain.StoredRecord（叶数据 = chain_hash 的 32 字节）、P3/P4 无第三方 Merkle 库
不变量：叶 0x00、内部 0x01；叶顺序 = event_seq 升序，不排序、不去重；空树有确定根；
        单叶 proof 为空；奇数叶按 RFC 9162 的 k 分裂递归，**不复制末叶**；验证用常量时间比较
错误码：BUNDLE_TAMPERED（422，proof/root 不匹配）；SCHEMA_INVALID（422，构造参数非法）
写入者：**只读/纯计算**；Verifier 构造 proof，verify_bundle 验证；Collector 不写 Merkle
状态：伪代码；标准测试向量属 WP-11，P4 只钉算法与三种边界

## RFC 9162 定义（逐字对应）

    MTH({})        = SHA-256()                                  # 空树
    MTH({d0})      = SHA-256(0x00 || d0)                        # 单叶
    MTH(D[n])      = SHA-256(0x01 || MTH(D[0:k]) || MTH(D[k:n]))
                     k = 小于 n 的最大 2 的幂

  `D[i]` 是本项目第 i 条证据的 `chain_hash` 的 32 字节（不是 hex 字符串）。
  因为 chain_hash 已经覆盖整条记录，叶数据用 chain_hash 即可把记录绑定进树；
  不需要把整条 JSON 再序列化进叶（会把记录字段顺序带进证明，增加跨实现差异）。

## 三种边界（验收判据 1）

  1. **空树**：`root = SHA-256(b"")`，`tree_size=0`；`inclusion_proof()` 抛
     `EMPTY_TREE`，**不返回** `None`/空 proof 冒充“通过”。
  2. **单叶**：`root = SHA-256(0x00 || leaf)`；`inclusion_proof()` 返回空元组；
     验证时 `sn=0`、`r=leaf_hash`，直接与 root 比较。
  3. **奇数叶**：按 `k = 小于 n 的最大 2 的幂` 分裂，右侧可能是 1/3/… 叶；
     递归到单叶后**直接提升**为父节点的右子哈希，**不复制**最后一叶。
     复制末叶是 Bitcoin 的变体，不是 RFC 9162；会让标准 inclusion proof 失效。

## 验证算法

  用 RFC 9162 §2.1.3.2 的 `fn/sn` 算法，而不是“按 index 奇偶折叠”的完美树算法。
  后者在 n 不是 2 的幂时会算错根。实现里保留 `fn == sn` 分支与右移循环。
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Final, Sequence

__all__ = [
    "EMPTY_ROOT",
    "LEAF_PREFIX",
    "NODE_PREFIX",
    "MerkleProof",
    "MerkleProofError",
    "MerkleTree",
    "MerkleVerification",
    "largest_power_of_two_less_than",
    "leaf_hash",
    "node_hash",
    "verify_inclusion",
]

LEAF_PREFIX: Final[bytes] = b"\x00"
NODE_PREFIX: Final[bytes] = b"\x01"

# 空树根 = SHA-256()；不是“全零”，也不是 None。
EMPTY_ROOT: Final[str] = hashlib.sha256(b"").hexdigest()

_HASH64 = re.compile(r"^[0-9a-f]{64}$")
TEST_VECTOR_SOURCE: Final[str] = "RFC 9162 §2.1.3–2.1.4；标准向量在 WP-11 接入"


class MerkleProofError(ValueError):
    """Merkle 构造/验证拒绝。"""

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        error_code: str = "SCHEMA_INVALID",
        detail: dict[str, object] | None = None,
    ) -> None:
        self.reason = reason
        self.error_code = error_code
        self.http_status = 422
        self.detail = detail or {}
        super().__init__(f"{error_code}/{reason}: {message}")


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _require_hash64(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not _HASH64.match(value):
        raise MerkleProofError("HASH_FORMAT_INVALID", f"{field} 必须是 64 位小写十六进制")
    return value


def leaf_hash(chain_hash: str) -> str:
    """`SHA-256(0x00 || bytes.fromhex(chain_hash))`，返回小写 hex。"""
    raw = bytes.fromhex(_require_hash64(chain_hash, field="chain_hash"))
    return _sha256(LEAF_PREFIX + raw).hex()


def node_hash(left_hex: str, right_hex: str) -> str:
    """`SHA-256(0x01 || left || right)`，左右顺序不可交换。"""
    left = bytes.fromhex(_require_hash64(left_hex, field="left"))
    right = bytes.fromhex(_require_hash64(right_hex, field="right"))
    return _sha256(NODE_PREFIX + left + right).hex()


def largest_power_of_two_less_than(n: int) -> int:
    """小于 n 的最大 2 的幂；n ≥ 2。RFC 9162 的 k。"""
    if isinstance(n, bool) or not isinstance(n, int) or n < 2:
        raise MerkleProofError("TREE_SIZE_INVALID", f"n 必须是 ≥2 的 integer，实际 {n!r}")
    return 1 << ((n - 1).bit_length() - 1)


def _mth(leaves: Sequence[str]) -> str:
    """递归计算 MTH；leaves 是**叶哈希**（已做 0x00 前缀），按 event_seq 顺序。"""
    n = len(leaves)
    if n == 0:
        # 边界 1：空树。返回确定根，不返回 None。
        return EMPTY_ROOT
    if n == 1:
        # 边界 2：单叶。叶哈希已在 leaf_hash() 里加过 0x00。
        return leaves[0]
    k = largest_power_of_two_less_than(n)
    if n % 2 == 1:
        # 边界 3：奇数叶。右子树可以是 1/3/… 叶；不复制末叶，递归到单叶后提升。
        return node_hash(_mth(leaves[:k]), _mth(leaves[k:]))
    # 偶数叶也按 k 分裂（不是 n//2；n=6 时 k=4，右子树 2 叶）。
    return node_hash(_mth(leaves[:k]), _mth(leaves[k:]))


def _path(m: int, leaves: Sequence[str]) -> tuple[str, ...]:
    """RFC 9162 §2.1.3.1 的 PATH(m, D[n])，从叶到根。"""
    n = len(leaves)
    if n == 0:
        raise MerkleProofError("EMPTY_TREE", "空树没有 inclusion proof")
    if n == 1:
        return ()
    k = largest_power_of_two_less_than(n)
    if m < k:
        return _path(m, leaves[:k]) + (_mth(leaves[k:]),)
    return _path(m - k, leaves[k:]) + (_mth(leaves[:k]),)


@dataclass(frozen=True, slots=True)
class MerkleProof:
    """一条 inclusion proof；`audit_path` 是从叶到根的兄弟哈希（小写 hex）。"""

    leaf_index: int
    tree_size: int
    audit_path: tuple[str, ...]
    root_hash: str

    def __post_init__(self) -> None:
        if isinstance(self.leaf_index, bool) or not isinstance(self.leaf_index, int):
            raise MerkleProofError("INDEX_INVALID", "leaf_index 必须是 integer")
        if isinstance(self.tree_size, bool) or not isinstance(self.tree_size, int):
            raise MerkleProofError("TREE_SIZE_INVALID", "tree_size 必须是 integer")
        if self.tree_size < 0 or self.leaf_index < 0:
            raise MerkleProofError("INDEX_INVALID", "leaf_index/tree_size 不得为负")
        if self.tree_size == 0:
            raise MerkleProofError("EMPTY_TREE", "空树没有 inclusion proof")
        if self.leaf_index >= self.tree_size:
            raise MerkleProofError("INDEX_OUT_OF_RANGE", "leaf_index 必须 < tree_size")
        for item in self.audit_path:
            _require_hash64(item, field="audit_path")
        _require_hash64(self.root_hash, field="root_hash")

    def as_dict(self) -> dict[str, object]:
        return {
            "leaf_index": self.leaf_index,
            "tree_size": self.tree_size,
            "audit_path": list(self.audit_path),
            "root_hash": self.root_hash,
        }


@dataclass(frozen=True, slots=True)
class MerkleVerification:
    """验证结果；失败原因必须可断言。"""

    ok: bool
    reason: str = ""
    computed_root: str = ""
    detail: dict[str, object] | None = None


def verify_inclusion(
    *,
    leaf_hash_hex: str,
    leaf_index: int,
    tree_size: int,
    audit_path: Sequence[str],
    root_hash: str,
) -> MerkleVerification:
    """RFC 9162 §2.1.3.2 的 inclusion proof 验证。

    返回 `MerkleVerification`，不抛异常（调用方决定是否 fail-closed）；
    参数形态非法时返回 `ok=False, reason=...`，不把异常当“验证通过”。
    """
    try:
        _require_hash64(leaf_hash_hex, field="leaf_hash")
        _require_hash64(root_hash, field="root_hash")
    except MerkleProofError as exc:
        return MerkleVerification(False, exc.reason, detail={"message": str(exc)})
    if isinstance(leaf_index, bool) or not isinstance(leaf_index, int) or leaf_index < 0:
        return MerkleVerification(False, "INDEX_INVALID")
    if isinstance(tree_size, bool) or not isinstance(tree_size, int) or tree_size < 0:
        return MerkleVerification(False, "TREE_SIZE_INVALID")
    if tree_size == 0:
        return MerkleVerification(False, "EMPTY_TREE")
    if leaf_index >= tree_size:
        return MerkleVerification(False, "INDEX_OUT_OF_RANGE")
    if len(audit_path) > tree_size.bit_length():
        return MerkleVerification(False, "PROOF_TOO_LONG")

    fn = leaf_index
    sn = tree_size - 1
    r = leaf_hash_hex
    for sibling in audit_path:
        try:
            _require_hash64(sibling, field="audit_path")
        except MerkleProofError as exc:
            return MerkleVerification(False, exc.reason, detail={"message": str(exc)})
        if sn == 0:
            return MerkleVerification(False, "PROOF_TOO_LONG")
        if (fn & 1) or (fn == sn):
            # 当前节点是右子（或右边界）：sibling 在左。
            r = node_hash(sibling, r)
            if not (fn & 1):
                while fn != 0 and not (fn & 1):
                    fn >>= 1
                    sn >>= 1
        else:
            # 当前节点是左子：sibling 在右。
            r = node_hash(r, sibling)
        fn >>= 1
        sn >>= 1

    if sn != 0:
        return MerkleVerification(False, "PROOF_TOO_SHORT", computed_root=r)
    if not hmac.compare_digest(r, root_hash):
        return MerkleVerification(False, "ROOT_MISMATCH", computed_root=r)
    return MerkleVerification(True, computed_root=r)


class MerkleTree:
    """按 event_seq 顺序构建的 RFC 9162 树。

    `chain_hashes` 必须是**已按 event_seq 升序**的 64-hex；本类不排序。
    空序列合法（size=0），但 `inclusion_proof()` 会拒绝。
    """

    def __init__(self, chain_hashes: Sequence[str]) -> None:
        self._chain_hashes = tuple(chain_hashes)
        self._leaves = tuple(leaf_hash(item) for item in self._chain_hashes)
        self._root: str | None = None

    @classmethod
    def from_records(cls, records: Sequence[object]) -> "MerkleTree":
        """从 `StoredRecord` 序列构建；要求 event_seq 恰为 1..n（不缺不重）。"""
        hashes: list[str] = []
        for index, record in enumerate(records):
            seq = getattr(record, "event_seq", None)
            if seq != index + 1:
                raise MerkleProofError(
                    "LEAF_ORDER_INVALID",
                    f"第 {index} 条的 event_seq 是 {seq!r}，期望 {index + 1}；叶必须按 event_seq 定序",
                )
            chain_hash = getattr(record, "chain_hash", None)
            hashes.append(_require_hash64(chain_hash, field="chain_hash"))
        return cls(hashes)

    @property
    def tree_size(self) -> int:
        return len(self._leaves)

    @property
    def root(self) -> str:
        if self._root is None:
            self._root = _mth(self._leaves)
        return self._root

    @property
    def empty(self) -> bool:
        return self.tree_size == 0

    def leaf_hash_at(self, index: int) -> str:
        if self.tree_size == 0:
            raise MerkleProofError("EMPTY_TREE", "空树没有叶")
        if index < 0 or index >= self.tree_size:
            raise MerkleProofError("INDEX_OUT_OF_RANGE", f"index={index} 不在 [0,{self.tree_size})")
        return self._leaves[index]

    def inclusion_proof(self, leaf_index: int) -> MerkleProof:
        """构造 inclusion proof；三种边界：空树抛、单叶空路径、奇数叶递归。"""
        if self.tree_size == 0:
            raise MerkleProofError("EMPTY_TREE", "空树不能构造 inclusion proof")
        if leaf_index < 0 or leaf_index >= self.tree_size:
            raise MerkleProofError("INDEX_OUT_OF_RANGE", f"leaf_index={leaf_index} 越界")
        path = _path(leaf_index, self._leaves)
        return MerkleProof(
            leaf_index=leaf_index,
            tree_size=self.tree_size,
            audit_path=path,
            root_hash=self.root,
        )

    def verify(self, proof: MerkleProof) -> MerkleVerification:
        """验证一条 proof 是否属于本树；tree_size/leaf_index 必须一致。"""
        if proof.tree_size != self.tree_size:
            return MerkleVerification(
                False, "TREE_SIZE_MISMATCH",
                detail={"expected": self.tree_size, "actual": proof.tree_size},
            )
        return verify_inclusion(
            leaf_hash_hex=self.leaf_hash_at(proof.leaf_index),
            leaf_index=proof.leaf_index,
            tree_size=proof.tree_size,
            audit_path=proof.audit_path,
            root_hash=self.root,
        )