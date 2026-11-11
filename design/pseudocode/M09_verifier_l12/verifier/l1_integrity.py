"""MODULE: M09 · verifier/l1_integrity.py — L1 过程完整性复核（P5 伪代码）
阶段/追踪: P5「门控与三级验证」｜FR-007、策划书 §9.1 L1、05 §13
FR/依赖: FR-007；依赖 M07 chain/merkle 只读端口、M01 冻结 schema、M03 时间规则
不变量/错误码: L1 只读证据与目录索引，不执行代码、不重训、不改证据；七项检查缺一不可：
             schema、payload 哈希、artifact 哈希、event_seq、chain、Merkle、目录复用。
             任一项 FAIL → L1 FAIL；不得用 PASS 掩盖“未检查”。
             错误码：SCHEMA_INVALID（422）、BUNDLE_TAMPERED（422）、EVIDENCE_CHAIN_BROKEN（500）、
             EVENT_SEQ_GAP/EVENT_SEQ_REGRESSION（500）、EVIDENCE_REFERENCE_NOT_FOUND（422）
写入者: **无**；Verifier 只读，不写证据/状态/报告
状态: 伪代码；不建环境、不跑测试、不写业务代码

## L1 能证明什么、不能证明什么（写死）

  **能证明**（相对于交给它的证据集与目录索引）：
  1. 每条记录符合冻结 schema，task/level/kind/producer 组合合法；
  2. payload 与 artifact 的 SHA-256 与记录/清单一致；
  3. event_seq 从 1 起严格 +1，prev_hash/chain_hash 可重算；
  4. 按 event_seq 构造的 Merkle 根等于 expected_evidence_root，且每条记录有 inclusion proof；
  5. 每个 attempt 有独立目录，没有两个 attempt 共用 inode/realpath，Verifier 目录与 Executor 目录分离。

  **不能证明**：
  - 代码真的被执行过（L1 不启动进程、不训练模型）；
  - 证据时间戳/进程身份是真实的（Collector/Executor 被替换时 E2 可能失真，§7.7）；
  - 指标正确（L2 的职责）、结果可复现（L3 的职责）；
  - 攻击者同时控制证据库并能重算整条链时，L1 可能“看起来通过”（哈希链只提高可发现性）。

  因此 L1 PASS 的准确表述是“**证据集在结构与指纹上自洽**”，不是“任务真实完成”。

## 七项检查与拒绝点

  | check_id | 判据 | 失败语义 |
  |---|---|---|
  | `L1-SCHEMA` | 每条记录过冻结 schema；schema_version=1.0；task_id 一致 | SCHEMA_INVALID |
  | `L1-PAYLOAD-HASH` | sha256(payload sidecar bytes) == payload_hash | BUNDLE_TAMPERED |
  | `L1-ARTIFACT-HASH` | 每个 artifact_ref 重算值 == E2 清单值 | BUNDLE_TAMPERED / EVIDENCE_REFERENCE_NOT_FOUND |
  | `L1-EVENT-SEQ` | seq 首项=1、严格 +1、evidence_id 唯一 | EVENT_SEQ_GAP/REGRESSION |
  | `L1-CHAIN-HASH` | prev_hash 接链；chain_hash 重算一致 | EVIDENCE_CHAIN_BROKEN |
  | `L1-MERKLE` | 根 == expected_evidence_root；每条 inclusion proof 通过 | BUNDLE_TAMPERED |
  | `L1-DIRECTORY-REUSE` | attempt 目录键唯一、inode/realpath 不重复、Verifier 目录分离 | SCHEMA_INVALID |

## 目录复用检测为什么属于 L1

  `attempt_id` 每次真实执行必须唯一；如果两个 attempt 指向同一个目录，说明“第二次执行”
  可能只是复用了第一次的产物。L1 用 `(st_dev, st_ino)` 与 `realpath` 双判据检测，
  并要求 attempt 目录创建时间不早于任务创建时间。目录索引由 Verifier 采集，不由 Executor 自报。
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping, Protocol, Sequence

__all__ = [
    "L1_PROVES",
    "L1_DOES_NOT_PROVE",
    "AttemptDirectory",
    "CheckStatus",
    "EvidenceRecordView",
    "IntegrityError",
    "L1Check",
    "L1Input",
    "L1IntegrityVerifier",
    "L1Result",
    "assert_l1_boundary",
]

L1_PROVES: Final[tuple[str, ...]] = (
    "证据记录符合冻结 schema",
    "payload/产物 SHA-256 与记录一致",
    "event_seq 连续且链哈希可重算",
    "Merkle 根与 inclusion proof 一致",
    "attempt 目录独立、Verifier 与 Executor 目录分离",
)
L1_DOES_NOT_PROVE: Final[tuple[str, ...]] = (
    "代码真的被执行过",
    "时间戳/进程身份不可伪造",
    "指标正确或结果可复现",
    "整套证据由攻击者同时控制时仍不可伪造",
)

_HASH64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$")


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    NOT_RUN = "NOT_RUN"


class IntegrityError(RuntimeError):
    """L1 程序性错误；常规不一致写成 L1Check，不抛异常。"""

    def __init__(
        self,
        error_code: str,
        reason: str,
        message: str,
        *,
        field_path: str = "",
        http_status: int = 422,
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.error_code = error_code
        self.reason = reason
        self.field_path = field_path
        self.http_status = http_status
        self.detail = MappingProxyType(dict(detail or {}))
        super().__init__(f"{error_code}/{reason} @ {field_path}: {message}")


# ---------------------------------------------------------------------------
# 1. 只读视图与端口
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EvidenceRecordView:
    """L1 看到的 EvidenceRecord；与冻结 schema 字段一一对应。"""

    schema_version: str
    evidence_id: str
    task_id: str
    node_id: str
    attempt_id: str
    event_seq: int
    level: str
    kind: str
    producer: str
    timestamp: str
    payload_hash: str
    prev_hash: str
    chain_hash: str
    artifact_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AttemptDirectory:
    """一次 attempt 的目录指纹；由 Verifier 直接采集，不由 Executor 自报。

    `device`/`inode` 来自 `os.stat` 的 `st_dev`/`st_ino`；`realpath` 已解析链接。
    """

    task_id: str
    node_id: str
    attempt_id: str
    realpath: str
    device: int
    inode: int
    created_at: str

    def key(self) -> tuple[str, str, str]:
        return (self.task_id, self.node_id, self.attempt_id)


class RecordSchemaPort(Protocol):
    def validate(self, record: EvidenceRecordView) -> None: ...


class PayloadReaderPort(Protocol):
    def read(self, payload_hash: str) -> bytes | None: ...


class ArtifactHasherPort(Protocol):
    def sha256(self, *, task_id: str, attempt_id: str, ref: str) -> str | None: ...


class ChainHashPort(Protocol):
    def recompute(self, record: EvidenceRecordView) -> str: ...


class MerklePort(Protocol):
    """M07 merkle 的只读端口；叶子是 chain_hash 的 32 字节。"""

    def root(self, leaves: Sequence[bytes]) -> str: ...
    def inclusion_proof(self, leaves: Sequence[bytes], index: int) -> tuple[str, ...]: ...
    def verify_inclusion(
        self,
        leaf: bytes,
        index: int,
        proof: Sequence[str],
        root: str,
        tree_size: int,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class L1Input:
    """L1 的只读输入；目录索引缺失按 fail-closed 处理。"""

    task_id: str
    records: tuple[EvidenceRecordView, ...]
    expected_evidence_root: str
    artifact_manifest: Mapping[str, str]
    directories: tuple[AttemptDirectory, ...]
    verifier_workspace: str
    task_created_at: str
    record_schema: RecordSchemaPort
    payload_reader: PayloadReaderPort
    artifact_hasher: ArtifactHasherPort
    chain_hasher: ChainHashPort
    merkle: MerklePort

    def __post_init__(self) -> None:
        if not self.task_id.startswith("task_"):
            raise IntegrityError("SCHEMA_INVALID", "TASK_ID_INVALID",
                                 "task_id 形态非法", field_path="task_id")
        if len(self.expected_evidence_root) != 64:
            raise IntegrityError(
                "SCHEMA_INVALID", "EVIDENCE_ROOT_INVALID",
                "expected_evidence_root 必须是 64 位十六进制", field_path="expected_evidence_root",
            )
        if not os.path.isabs(self.verifier_workspace):
            raise IntegrityError(
                "SCHEMA_INVALID", "VERIFIER_WORKSPACE_NOT_ABSOLUTE",
                "verifier_workspace 必须是绝对路径", field_path="verifier_workspace",
            )
        if not _UTC.match(self.task_created_at):
            raise IntegrityError(
                "SCHEMA_INVALID", "TASK_CREATED_AT_INVALID",
                "task_created_at 必须是 UTC RFC 3339", field_path="task_created_at",
            )


@dataclass(frozen=True, slots=True)
class L1Check:
    """一项 L1 检查；失败必须给出 expected/actual，便于负例断言。"""

    check_id: str
    status: CheckStatus
    message: str
    expected: str = ""
    actual: str = ""
    evidence_ids: tuple[str, ...] = ()
    detail: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class L1Result:
    """L1 结论；没有 `execution_proof` 字段，也没有 VERIFIED 字样。"""

    status: CheckStatus
    checks: tuple[L1Check, ...]
    evidence_root: str
    tree_size: int
    checked_records: int

    def failures(self) -> tuple[L1Check, ...]:
        return tuple(check for check in self.checks if check.status is CheckStatus.FAIL)

    @property
    def l1_status(self) -> str:
        """报告字段 `l1_status` 的投影；只允许 PASS/FAIL/SKIP/NOT_RUN。"""
        return self.status.value

    def assert_no_execution_claim(self) -> None:
        if self.status is CheckStatus.PASS and self.checked_records == 0:
            raise IntegrityError(
                "SCHEMA_INVALID", "L1_PASS_WITHOUT_RECORDS",
                "没有记录不能 PASS", field_path="records",
            )


# ---------------------------------------------------------------------------
# 2. L1 实现
# ---------------------------------------------------------------------------
class L1IntegrityVerifier:
    """L1 七项复核；只读、确定性、可重算。"""

    CHECK_SCHEMA: Final[str] = "L1-SCHEMA"
    CHECK_PAYLOAD: Final[str] = "L1-PAYLOAD-HASH"
    CHECK_ARTIFACT: Final[str] = "L1-ARTIFACT-HASH"
    CHECK_SEQ: Final[str] = "L1-EVENT-SEQ"
    CHECK_CHAIN: Final[str] = "L1-CHAIN-HASH"
    CHECK_MERKLE: Final[str] = "L1-MERKLE"
    CHECK_DIRECTORY: Final[str] = "L1-DIRECTORY-REUSE"
    CHECK_ORDER: Final[tuple[str, ...]] = (
        CHECK_SCHEMA, CHECK_PAYLOAD, CHECK_ARTIFACT, CHECK_SEQ, CHECK_CHAIN,
        CHECK_MERKLE, CHECK_DIRECTORY,
    )

    def run(self, l1_input: L1Input) -> L1Result:
        """按 CHECK_ORDER 执行；所有检查都跑完后统一给结论（不早停）。"""
        checks = [
            self._check_schema(l1_input),
            self._check_payload_hashes(l1_input),
            self._check_artifact_hashes(l1_input),
            self._check_event_seq(l1_input),
            self._check_chain(l1_input),
            self._check_merkle(l1_input),
            self._check_directory_reuse(l1_input),
        ]
        leaves = [bytes.fromhex(record.chain_hash) for record in l1_input.records
                  if _HASH64.match(record.chain_hash)]
        tree_size = len(leaves)
        status = CheckStatus.FAIL if any(check.status is CheckStatus.FAIL for check in checks) \
            else CheckStatus.PASS
        result = L1Result(
            status=status,
            checks=tuple(checks),
            evidence_root=l1_input.expected_evidence_root,
            tree_size=tree_size,
            checked_records=len(l1_input.records),
        )
        result.assert_no_execution_claim()
        return result

    # -- 2.1 schema -------------------------------------------------------
    def _check_schema(self, l1_input: L1Input) -> L1Check:
        """冻结 schema 复核；空记录直接 FAIL（L1 不能对空集 PASS）。"""
        if not l1_input.records:
            return L1Check(self.CHECK_SCHEMA, CheckStatus.FAIL, "没有证据记录")
        problems: list[str] = []
        ids: list[str] = []
        for record in l1_input.records:
            ids.append(record.evidence_id)
            if record.schema_version != "1.0":
                problems.append(f"{record.evidence_id}: schema_version={record.schema_version!r}")
            if record.task_id != l1_input.task_id:
                problems.append(f"{record.evidence_id}: task_id 不一致")
            try:
                l1_input.record_schema.validate(record)
            except Exception as exc:
                problems.append(f"{record.evidence_id}: {exc}")
        if len(set(ids)) != len(ids):
            problems.append("evidence_id 重复")
        if problems:
            return L1Check(
                self.CHECK_SCHEMA, CheckStatus.FAIL, "schema 复核失败",
                actual="; ".join(problems[:10]), evidence_ids=tuple(ids),
            )
        return L1Check(
            self.CHECK_SCHEMA, CheckStatus.PASS, "全部记录符合冻结 schema",
            evidence_ids=tuple(ids),
        )

    # -- 2.2 payload / artifact ------------------------------------------
    def _check_payload_hashes(self, l1_input: L1Input) -> L1Check:
        """逐条重算 payload sidecar 的 SHA-256。"""
        if not l1_input.records:
            return L1Check(self.CHECK_PAYLOAD, CheckStatus.FAIL, "没有记录可复核")
        bad: list[str] = []
        ids: list[str] = []
        for record in l1_input.records:
            ids.append(record.evidence_id)
            payload = l1_input.payload_reader.read(record.payload_hash)
            if payload is None:
                bad.append(f"{record.evidence_id}: payload 缺失")
                continue
            actual = hashlib.sha256(payload).hexdigest()
            if actual != record.payload_hash:
                bad.append(f"{record.evidence_id}: {actual} != {record.payload_hash}")
        if bad:
            return L1Check(
                self.CHECK_PAYLOAD, CheckStatus.FAIL, "payload 哈希不符",
                actual="; ".join(bad[:10]), evidence_ids=tuple(ids),
            )
        return L1Check(
            self.CHECK_PAYLOAD, CheckStatus.PASS, "payload 哈希全部一致",
            evidence_ids=tuple(ids),
        )

    def _check_artifact_hashes(self, l1_input: L1Input) -> L1Check:
        """产物重算哈希与 E2 清单比对；没有产物时 PASS（0 项，显式记录）。"""
        bad: list[str] = []
        ids: list[str] = []
        checked = 0
        for record in l1_input.records:
            for ref in record.artifact_refs:
                checked += 1
                ids.append(record.evidence_id)
                key = f"{record.attempt_id}:{ref}"
                expected = l1_input.artifact_manifest.get(key)
                actual = l1_input.artifact_hasher.sha256(
                    task_id=record.task_id, attempt_id=record.attempt_id, ref=ref,
                )
                if expected is None:
                    bad.append(f"{record.evidence_id}: {ref} 未登记哈希")
                elif actual is None:
                    bad.append(f"{record.evidence_id}: {ref} 产物缺失")
                elif actual != expected:
                    bad.append(f"{record.evidence_id}: {ref} {actual} != {expected}")
        if bad:
            return L1Check(
                self.CHECK_ARTIFACT, CheckStatus.FAIL, "产物哈希不符",
                actual="; ".join(bad[:10]), evidence_ids=tuple(ids),
                detail={"checked": checked},
            )
        return L1Check(
            self.CHECK_ARTIFACT, CheckStatus.PASS, f"产物哈希一致（{checked} 项）",
            evidence_ids=tuple(ids), detail={"checked": checked},
        )

    # -- 2.3 seq / chain --------------------------------------------------
    def _check_event_seq(self, l1_input: L1Input) -> L1Check:
        """event_seq 从 1 起严格 +1；不排序，按传入的存储顺序检查。"""
        if not l1_input.records:
            return L1Check(self.CHECK_SEQ, CheckStatus.FAIL, "没有记录")
        for index, record in enumerate(l1_input.records):
            expected = index + 1
            if record.event_seq != expected:
                return L1Check(
                    self.CHECK_SEQ, CheckStatus.FAIL, "event_seq 不连续",
                    expected=str(expected), actual=str(record.event_seq),
                    evidence_ids=(record.evidence_id,),
                )
        return L1Check(self.CHECK_SEQ, CheckStatus.PASS, "event_seq 连续")

    def _check_chain(self, l1_input: L1Input) -> L1Check:
        """prev_hash 接链 + chain_hash 重算；首条只校形态（OQ-CT-10）。"""
        if not l1_input.records:
            return L1Check(self.CHECK_CHAIN, CheckStatus.FAIL, "没有记录")
        for index, record in enumerate(l1_input.records):
            if index == 0:
                if not _HASH64.match(record.prev_hash):
                    return L1Check(
                        self.CHECK_CHAIN, CheckStatus.FAIL, "首条 prev_hash 形态非法",
                        actual=record.prev_hash, evidence_ids=(record.evidence_id,),
                    )
            elif record.prev_hash != l1_input.records[index - 1].chain_hash:
                return L1Check(
                    self.CHECK_CHAIN, CheckStatus.FAIL, "prev_hash 不接上一条 chain_hash",
                    expected=l1_input.records[index - 1].chain_hash,
                    actual=record.prev_hash, evidence_ids=(record.evidence_id,),
                )
            try:
                recomputed = l1_input.chain_hasher.recompute(record)
            except Exception as exc:
                return L1Check(
                    self.CHECK_CHAIN, CheckStatus.FAIL, f"chain_hash 重算失败：{exc}",
                    evidence_ids=(record.evidence_id,),
                )
            if recomputed != record.chain_hash:
                return L1Check(
                    self.CHECK_CHAIN, CheckStatus.FAIL, "chain_hash 与重算值不符",
                    expected=recomputed, actual=record.chain_hash,
                    evidence_ids=(record.evidence_id,),
                )
        return L1Check(self.CHECK_CHAIN, CheckStatus.PASS, "链哈希全部一致")

    # -- 2.4 Merkle -------------------------------------------------------
    def _check_merkle(self, l1_input: L1Input) -> L1Check:
        """按 event_seq 顺序构造叶子；根与 expected 比对；逐条验证 inclusion。"""
        if not l1_input.records:
            return L1Check(self.CHECK_MERKLE, CheckStatus.FAIL, "没有记录，无法构造 Merkle 树")
        invalid = [record.evidence_id for record in l1_input.records if not _HASH64.match(record.chain_hash)]
        if invalid:
            return L1Check(
                self.CHECK_MERKLE, CheckStatus.FAIL, "chain_hash 形态非法，无法构造叶子",
                actual=", ".join(invalid[:10]), evidence_ids=tuple(invalid),
            )
        leaves = [bytes.fromhex(record.chain_hash) for record in l1_input.records]
        root = l1_input.merkle.root(leaves)
        if root != l1_input.expected_evidence_root:
            return L1Check(
                self.CHECK_MERKLE, CheckStatus.FAIL, "Merkle 根与 expected_evidence_root 不符",
                expected=l1_input.expected_evidence_root, actual=root,
            )
        bad: list[str] = []
        for index, record in enumerate(l1_input.records):
            proof = l1_input.merkle.inclusion_proof(leaves, index)
            ok = l1_input.merkle.verify_inclusion(
                leaves[index], index, proof, root, len(leaves),
            )
            if not ok:
                bad.append(record.evidence_id)
        if bad:
            return L1Check(
                self.CHECK_MERKLE, CheckStatus.FAIL, "inclusion proof 校验失败",
                actual=", ".join(bad[:10]), evidence_ids=tuple(bad),
            )
        return L1Check(
            self.CHECK_MERKLE, CheckStatus.PASS,
            f"Merkle 根一致，{len(leaves)} 条 inclusion proof 全部通过",
            expected=root, actual=root,
        )

    # -- 2.5 目录复用 -----------------------------------------------------
    def _check_directory_reuse(self, l1_input: L1Input) -> L1Check:
        """attempt 目录键唯一；inode/realpath 不重复；与 Verifier 目录分离。"""
        if not l1_input.directories:
            return L1Check(
                self.CHECK_DIRECTORY, CheckStatus.FAIL,
                "没有目录索引：无法证明 attempt 目录独立（fail-closed）",
            )
        problems: list[str] = []
        seen_keys: dict[tuple[str, str, str], AttemptDirectory] = {}
        seen_inodes: dict[tuple[int, int], AttemptDirectory] = {}
        seen_paths: dict[str, AttemptDirectory] = {}
        for directory in l1_input.directories:
            key = directory.key()
            if key in seen_keys:
                problems.append(f"{key}: attempt 目录键重复")
            seen_keys[key] = directory
            inode_key = (directory.device, directory.inode)
            if inode_key in seen_inodes and seen_inodes[inode_key].key() != key:
                problems.append(f"{key}: 与 {seen_inodes[inode_key].key()} 共用 inode")
            seen_inodes[inode_key] = directory
            path_key = os.path.normcase(directory.realpath)
            if path_key in seen_paths and seen_paths[path_key].key() != key:
                problems.append(f"{key}: 与 {seen_paths[path_key].key()} 共用 realpath")
            seen_paths[path_key] = directory
            if not _UTC.match(directory.created_at):
                problems.append(f"{key}: created_at 不是 UTC RFC 3339")
            else:
                try:
                    created = _parse_utc(directory.created_at)
                    task_created = _parse_utc(l1_input.task_created_at)
                except ValueError as exc:
                    problems.append(f"{key}: 时间无法解析（{exc}）")
                else:
                    if created < task_created:
                        problems.append(f"{key}: 目录创建早于任务创建")
            if _is_within(l1_input.verifier_workspace, directory.realpath) or _is_within(
                directory.realpath, l1_input.verifier_workspace
            ):
                problems.append(f"{key}: Verifier 工作目录与 attempt 目录重叠")
        for record in l1_input.records:
            if (record.task_id, record.node_id, record.attempt_id) not in seen_keys:
                problems.append(f"{record.evidence_id}: attempt 目录未登记")
        if problems:
            return L1Check(
                self.CHECK_DIRECTORY, CheckStatus.FAIL, "目录复用/分离检查失败",
                actual="; ".join(problems[:10]),
            )
        return L1Check(
            self.CHECK_DIRECTORY, CheckStatus.PASS,
            f"{len(l1_input.directories)} 个 attempt 目录独立且与 Verifier 分离",
        )


# ---------------------------------------------------------------------------
# 3. 工具
# ---------------------------------------------------------------------------
def _parse_utc(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("时间必须带时区")
    return parsed.astimezone(timezone.utc)


def _is_within(parent: str, child: str) -> bool:
    """纯路径判断（不碰文件系统）；不同盘符返回 False。"""
    try:
        parent_real = os.path.normcase(os.path.realpath(parent))
        child_real = os.path.normcase(os.path.realpath(child))
        return os.path.commonpath([parent_real, child_real]) == parent_real
    except ValueError:
        return False


def assert_l1_boundary() -> list[str]:
    """L1 不得执行代码、起进程、训练模型或写文件。"""
    problems: list[str] = []
    import sys

    module = sys.modules[__name__]
    for attr in ("subprocess", "Popen", "fit", "predict", "Gate", "StateMachine"):
        if hasattr(module, attr):
            problems.append(f"l1_integrity 暴露禁用名 {attr!r}")
    if L1_PROVES == L1_DOES_NOT_PROVE:
        problems.append("L1 的能/不能证明声明被混同")
    if "VERIFIED" in CheckStatus.__members__:
        problems.append("L1 不得使用 VERIFIED 状态")
    return problems