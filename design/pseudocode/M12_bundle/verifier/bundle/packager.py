"""MODULE: M12 · verifier/bundle/packager.py — Evidence Bundle 12 类文件与 manifest 哈希（P6 伪代码）
阶段/追踪: P6「签名与离线凭证」｜FR-009、NFR-07、策划书 §9.5（P0249–P0251）、§7.4 AnchorProof
FR/依赖: FR-009；依赖 M11 payloads/jcs；读取证据/报告/证书/证明，生成包目录；不依赖数据库与模型
不变量/错误码: 12 类必需文件固定；包内不得有私钥/信任库/模型二进制/数据库；manifest 不哈希自身；
              anchor_proof 缺失时必须在 manifest 标 absent，不得写成空文件或伪造证明。
              错误码：BUNDLE_TAMPERED（422）或 SCHEMA_INVALID（422，输入 shape 非法）
写入者: **Bundle Exporter**；只写导出目录；不写证据库、不写状态、不签名、不碰私钥
状态: 伪代码；WP-12 落地；包格式 v1.0 是本阶段内部格式，不是 G0 契约

## 12 类文件的推导（9.5 原文）

  9.5 列了 14 项：bundle_manifest、task_spec、graph、evidence.jsonl、artifact_manifest、
  split_manifest、verification_report、completion_certificate、merkle_proofs、
  anchor_proof（如有）、trusted_key_fingerprint、verify_bundle.py、README、必要的轻量复核数据。

  其中 `anchor_proof` 明确“如有”，`轻量复核数据` 是“必要”时才带；把这两项作为**可选**，
  其余 12 项作为**必需**，正好得到本阶段的“12 类”：

  | # | role | 路径 | 必需 | 被 manifest 哈希 | 来源 |
  |---|---|---|---|---|---|
  | 1 | bundle_manifest | `bundle_manifest.json` | 是 | **否（自身）** | 9.5 |
  | 2 | task_spec | `task_spec.json` | 是 | 是 | 9.5 |
  | 3 | graph | `graph.json` | 是 | 是 | 9.5 |
  | 4 | evidence | `evidence.jsonl` | 是 | 是 | 9.5 |
  | 5 | artifact_manifest | `artifact_manifest.json` | 是 | 是 | 9.5 |
  | 6 | split_manifest | `split_manifest.json` | 是 | 是 | 9.5 |
  | 7 | verification_report | `verification_report.json` | 是 | 是 | 9.5 |
  | 8 | completion_certificate | `completion_certificate.json` | 是 | 是 | 9.5 |
  | 9 | merkle_proofs | `merkle_proofs.json` | 是 | 是 | 9.5 |
  | 10 | trusted_key_fingerprint | `trusted_key_fingerprint.json` | 是 | 是 | 9.5 |
  | 11 | verify_bundle | `verify_bundle.py` | 是 | 是 | 9.5 |
  | 12 | README | `README.md` | 是 | 是 | 9.5 |
  | 可选 | anchor_proof | `anchor_proof.json` | 否 | 是（存在时） | 9.5 “如有” |
  | 可选 | recheck_data | `recheck_data.json` | 否 | 是（存在时） | 9.5 “必要的轻量复核数据” |

  **manifest 不能包含自身哈希**：`sha256(bundle_manifest.json)` 无法写进同一个文件而不改变自身。
  因此 manifest 的 `files` 只列其余 11 个必需文件（+ 可选存在项），整体清单哈希由导出器打印、
  由验签器重新计算并输出；不得在包内伪造一个“manifest_hash”字段冒充自哈希。

## anchor_proof 缺失语义

  7.6 说锚定“优先独立时间戳或第二存储；本地副本只称备份”，7.4 说 AnchorProof 是独立 sidecar，
  “缺失时标 absent”。因此：

  - 没有 anchor proof 时，manifest 写 `"optional": {"anchor_proof": {"status": "absent",
    "reason": "NOT_PROVIDED"}}`，**不写空文件**、不写全零哈希；
  - 验签器把 `anchor=ABSENT` 作为真实状态输出，仍可对完整性/签名/根一致性给出 PASS，
    但不得声称“已外部锚定/已时间戳证明”；
  - 有 anchor proof 时，必须按 7.4 字段带齐，并作为 `files` 条目被哈希；其验签由
    `verify_bundle` 用包外 anchor key 完成（`OQ-P6-09`）。

## 为什么包内不能放信任库/公钥/私钥

  - 信任库进包 = 包可以自证；验签器必须用包外 `--trust-store`。
  - `trusted_key_fingerprint.json` 只允许“声称用了哪把 key 的指纹”，不允许公钥材料；
    出现 `public_key`/`private_key`/`seed` 即拒绝。
  - 私钥、`.pkl/.joblib` 模型、SQLite/DB、`.env`、日志一律禁止进入证据包（7.6 / NFR-07）。
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Final, Mapping, Sequence

from verifier.crypto import jcs
from verifier.crypto.payloads import assert_certificate_signable, parse_rfc3339_utc

__all__ = [
    "ANCHOR_PROOF_FIELDS",
    "BUNDLE_FORMAT_VERSION",
    "OPTIONAL_BUNDLE_FILES",
    "REQUIRED_BUNDLE_FILES",
    "BundleExportResult",
    "BundleFileSpec",
    "BundleInputs",
    "EvidenceEnvelope",
    "PackagerError",
    "assert_no_forbidden_material",
    "assert_no_pem_private_key",
    "assert_packager_boundary",
    "compute_manifest_sha256",
    "export_bundle",
    "plan_bundle",
]

BUNDLE_FORMAT_VERSION: Final[str] = "1.0"
MANIFEST_NAME: Final[str] = "bundle_manifest.json"
_MAX_FILE_BYTES: Final[int] = 256 * 1024 * 1024
_HASH64_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$"
)
_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "private_key",
        "private_key_b64",
        "private_key_seed",
        "key_seed",
        "secret",
        "passphrase",
        "trusted_keys",
    }
)
_FORBIDDEN_SUFFIXES: Final[tuple[str, ...]] = (
    ".key",
    ".pem",
    ".pkl",
    ".joblib",
    ".dill",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".env",
    ".log",
)
ANCHOR_PROOF_FIELDS: Final[tuple[str, ...]] = (
    "certificate_hash",
    "merkle_root",
    "tree_size",
    "anchor_type",
    "timestamp",
    "receipt",
    "proof_signature",
)


class PackagerError(RuntimeError):
    """导出拒绝；映射 `BUNDLE_TAMPERED`(422) 或 `SCHEMA_INVALID`(422)。

    职责：把“缺件/多件/私钥混入/manifest 自指”等原因固定成可断言 reason。
    输入：reason、message、field_path、detail。
    输出：异常。
    副作用：无。
    不变量：message 不含文件内容/密钥。
    错误：本类自身。
    """

    error_code: Final[str] = "BUNDLE_TAMPERED"
    http_status: Final[int] = 422

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        field_path: str = "bundle",
        detail: Mapping[str, object] | None = None,
        error_code: str = "BUNDLE_TAMPERED",
    ) -> None:
        self.error_code = error_code
        self.reason = reason
        self.field_path = field_path
        self.detail = dict(detail or {})
        super().__init__(f"{error_code}/{reason} @ {field_path}: {message}")


@dataclass(frozen=True, slots=True)
class BundleFileSpec:
    """一类包文件；`role` 是与验签器约定的稳定标识，`path` 是包内相对路径。"""

    role: str
    path: str
    required: bool
    media_type: str
    description: str
    source: str
    self_hashed: bool = True

    def __post_init__(self) -> None:
        # 1. 路径必须是 POSIX 相对路径，不得含 .. / 盘符 / 反斜杠。
        if not self.path or self.path.startswith("/") or ".." in self.path.split("/") or "\\" in self.path:
            raise ValueError(f"包内路径非法：{self.path!r}")
        # 2. manifest 自身不得声明为“被哈希”。
        if self.role == "bundle_manifest" and self.self_hashed:
            raise ValueError("bundle_manifest 不能哈希自身")
        # 3. 禁止后缀直接拒绝。
        if any(self.path.lower().endswith(suffix) for suffix in _FORBIDDEN_SUFFIXES):
            raise ValueError(f"禁止进入证据包的文件类型：{self.path!r}")


REQUIRED_BUNDLE_FILES: Final[tuple[BundleFileSpec, ...]] = (
    BundleFileSpec(
        "bundle_manifest",
        MANIFEST_NAME,
        True,
        "application/json",
        "包清单（不哈希自身）",
        "9.5",
        self_hashed=False,
    ),
    BundleFileSpec("task_spec", "task_spec.json", True, "application/json", "任务声明", "9.5"),
    BundleFileSpec("graph", "graph.json", True, "application/json", "任务图", "9.5"),
    BundleFileSpec("evidence", "evidence.jsonl", True, "application/x-ndjson", "证据记录 + payload 信封", "9.5"),
    BundleFileSpec("artifact_manifest", "artifact_manifest.json", True, "application/json", "产物清单", "9.5"),
    BundleFileSpec("split_manifest", "split_manifest.json", True, "application/json", "六字段划分清单", "9.5"),
    BundleFileSpec("verification_report", "verification_report.json", True, "application/json", "验证报告", "9.5"),
    BundleFileSpec(
        "completion_certificate",
        "completion_certificate.json",
        True,
        "application/json",
        "完成凭证",
        "9.5",
    ),
    BundleFileSpec("merkle_proofs", "merkle_proofs.json", True, "application/json", "RFC 9162 包含证明", "9.5"),
    BundleFileSpec(
        "trusted_key_fingerprint",
        "trusted_key_fingerprint.json",
        True,
        "application/json",
        "签发方声称的 key_id→指纹（不是信任源）",
        "9.5/7.6",
    ),
    BundleFileSpec("verify_bundle", "verify_bundle.py", True, "text/x-python", "离线验签工具副本", "9.5"),
    BundleFileSpec("README", "README.md", True, "text/markdown", "包说明与验签命令", "9.5"),
)

OPTIONAL_BUNDLE_FILES: Final[tuple[BundleFileSpec, ...]] = (
    BundleFileSpec("anchor_proof", "anchor_proof.json", False, "application/json", "独立锚定证明（如有）", "9.5/7.4"),
    BundleFileSpec("recheck_data", "recheck_data.json", False, "application/json", "轻量复核数据（必要时）", "9.5"),
)


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    """证据包中的一行：冻结 `EvidenceRecord` + 可选内联 payload。

    `payload` 内联是**包格式**，不是改 `EvidenceRecord` schema；验签器据此重算 payload_hash。
    """

    record: Mapping[str, object]
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.record, Mapping) or not isinstance(self.payload, Mapping):
            raise PackagerError(
                "EVIDENCE_ENVELOPE_INVALID",
                "record/payload 必须是 object",
                error_code="SCHEMA_INVALID",
            )

    def payload_hash(self) -> str:
        """按 `sha256(JCS(payload))` 重算，用于与 record.payload_hash 比对。"""
        return hashlib.sha256(jcs.canonicalize(dict(self.payload))).hexdigest()


@dataclass(frozen=True, slots=True)
class BundleInputs:
    """导出所需的最小输入集合；任何一项缺失都不得“跳过继续”。"""

    task_id: str
    task_spec: Mapping[str, object]
    graph: Mapping[str, object]
    evidence: Sequence[EvidenceEnvelope]
    artifact_manifest: Mapping[str, object]
    split_manifest: Mapping[str, object]
    report: Mapping[str, object]
    certificate: Mapping[str, object]
    merkle_proofs: Mapping[str, object]
    trusted_fingerprints: Mapping[str, object]
    verify_bundle_source: bytes
    readme: str
    anchor_proof: Mapping[str, object] | None = None
    recheck_data: bytes | None = None


@dataclass(frozen=True, slots=True)
class BundleExportResult:
    """导出结果；`manifest_sha256` 是整体清单哈希，打印到日志/标准输出。"""

    bundle_dir: str
    manifest_sha256: str
    file_count: int
    optional_present: tuple[str, ...]
    optional_absent: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Entry:
    spec: BundleFileSpec
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def plan_bundle(inputs: BundleInputs) -> tuple[BundleFileSpec, ...]:
    """校验输入并返回本次应写出的文件规格（含可选存在项）。

    职责：在写盘前拒绝私钥/信任库/模型/DB、ID 不一致、证据 payload 哈希不符、非 VERIFIED。
    输入：`BundleInputs`。
    输出：`BundleFileSpec` 元组（manifest 在最后单独处理）。
    副作用：无（纯校验）。
    不变量：
      1. report/cert 必须通过 M11 的签发前守卫（含 VERIFIED、根/规则一致）；
      2. evidence 非空、task_id 一致、payload_hash 重算一致；
      3. 12 类必需文件齐全；可选文件按是否存在决定；
      4. 输入中不得出现禁止的密钥/模型/DB 材料。
    错误：`PackagerError`（缺项/不一致/禁止材料）。
    """
    # 1. 报告/证书必须是一对可签发的 VERIFIED 事实；复用 M11 守卫，避免两套口径。
    try:
        assert_certificate_signable(inputs.certificate, inputs.report)
    except Exception as exc:
        raise PackagerError(
            "REPORT_OR_CERTIFICATE_NOT_CERTIFIABLE",
            f"报告/证书未通过签发前检查：{getattr(exc, 'reason', type(exc).__name__)}",
            field_path="certificate",
            error_code="SCHEMA_INVALID",
        ) from exc

    # 2. task_id 必须贯穿 task_spec/report/evidence。
    if inputs.task_spec.get("task_id") != inputs.task_id:
        raise PackagerError("TASK_ID_MISMATCH", "task_spec.task_id 与导出任务不一致", field_path="task_id")
    if inputs.report.get("task_id") != inputs.task_id:
        raise PackagerError("TASK_ID_MISMATCH", "report.task_id 与导出任务不一致", field_path="task_id")
    if not inputs.evidence:
        raise PackagerError("EVIDENCE_EMPTY", "证据包不得没有证据", field_path="evidence")

    # 3. 逐条证据：task_id、payload_hash、event_seq/evidence_id 唯一。
    seen_ids: set[str] = set()
    seen_seq: set[int] = set()
    for index, envelope in enumerate(inputs.evidence):
        record = envelope.record
        # 3.0 证据 record 与内联 payload 都不得夹带私钥/私钥种子/PEM。
        assert_no_forbidden_material(record, f"evidence[{index}].record")
        assert_no_forbidden_material(envelope.payload, f"evidence[{index}].payload")
        if record.get("task_id") != inputs.task_id:
            raise PackagerError(
                "EVIDENCE_TASK_MISMATCH",
                "证据记录的 task_id 与导出任务不一致",
                field_path=f"evidence[{index}].task_id",
            )
        expected = record.get("payload_hash")
        actual = envelope.payload_hash()
        if expected != actual:
            raise PackagerError(
                "EVIDENCE_PAYLOAD_HASH_MISMATCH",
                "证据 payload_hash 与内联 payload 不一致",
                field_path=f"evidence[{index}].payload_hash",
                detail={"expected": expected, "actual": actual},
            )
        evidence_id = record.get("evidence_id")
        event_seq = record.get("event_seq")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise PackagerError("EVIDENCE_ID_INVALID", "evidence_id 必须是非空 string", field_path="evidence")
        if isinstance(event_seq, bool) or not isinstance(event_seq, int) or event_seq < 1:
            raise PackagerError("EVIDENCE_SEQ_INVALID", "event_seq 必须是 ≥1 integer", field_path="evidence")
        if evidence_id in seen_ids:
            raise PackagerError("EVIDENCE_ID_DUPLICATED", f"evidence_id 重复：{evidence_id}", field_path="evidence")
        if event_seq in seen_seq:
            raise PackagerError("EVIDENCE_SEQ_DUPLICATED", f"event_seq 重复：{event_seq}", field_path="evidence")
        seen_ids.add(evidence_id)
        seen_seq.add(event_seq)

    # 4. 指纹声明只能是 key_id→fingerprint，不得夹带公钥/私钥。
    _assert_claims_only(inputs.trusted_fingerprints)

    # 5. 输入中不得出现私钥/信任库/模型/DB 等材料。
    _assert_no_forbidden_material(inputs.task_spec, "task_spec")
    _assert_no_forbidden_material(inputs.graph, "graph")
    _assert_no_forbidden_material(inputs.artifact_manifest, "artifact_manifest")
    _assert_no_forbidden_material(inputs.split_manifest, "split_manifest")
    _assert_no_forbidden_material(inputs.merkle_proofs, "merkle_proofs")
    _assert_no_forbidden_material(inputs.report, "report")
    _assert_no_forbidden_material(inputs.certificate, "certificate")
    _assert_no_forbidden_material(inputs.trusted_fingerprints, "trusted_fingerprints")

    # 6. verify_bundle.py 必须是可复制的源码；空文件/超大文件拒绝。
    if not inputs.verify_bundle_source or len(inputs.verify_bundle_source) > 4 * 1024 * 1024:
        raise PackagerError("VERIFY_TOOL_INVALID", "verify_bundle.py 源码为空或过大", field_path="verify_bundle")

    # 7. README 必须非空，并包含验签命令；只拒绝 PEM 私钥头，不拒绝普通文字里的 private_key。
    if not inputs.readme.strip() or "verify_bundle.py" not in inputs.readme:
        raise PackagerError("README_INVALID", "README 必须非空且包含 verify_bundle.py 用法", field_path="README")
    assert_no_pem_private_key(inputs.readme, "README")

    # 8. 可选 anchor proof 只做 shape 检查；结构扫描后不在导出阶段验签。
    if inputs.anchor_proof is not None:
        _assert_anchor_proof_shape(inputs.anchor_proof)
        _assert_no_forbidden_material(inputs.anchor_proof, "anchor_proof")

    # 9. 可选 recheck data 必须是合法 JSON，避免包内放二进制；解析后的结构也要扫描。
    if inputs.recheck_data is not None:
        try:
            parsed_recheck = jcs.parse_strict(inputs.recheck_data)
        except jcs.JcsError as exc:
            raise PackagerError(
                "RECHECK_DATA_INVALID",
                f"recheck_data 必须是合法 JSON：{exc.reason}",
                field_path="recheck_data",
                error_code="SCHEMA_INVALID",
            ) from exc
        _assert_no_forbidden_material(parsed_recheck, "recheck_data")

    # 10. 返回必需 + 可选存在的规格。
    specs: list[BundleFileSpec] = list(REQUIRED_BUNDLE_FILES)
    if inputs.anchor_proof is not None:
        specs.append(OPTIONAL_BUNDLE_FILES[0])
    if inputs.recheck_data is not None:
        specs.append(OPTIONAL_BUNDLE_FILES[1])
    return tuple(specs)


def export_bundle(
    inputs: BundleInputs,
    dest: str | os.PathLike[str],
    *,
    created_at: str | None = None,
) -> BundleExportResult:
    """导出证据包：先写临时目录，再原子 rename；不覆盖已有目录。

    职责：生成 12 类文件 + manifest，计算每文件 sha256/size，写 README/工具副本。
    输入：inputs、目标目录、可选创建时间（测试注入）。
    输出：`BundleExportResult`。
    副作用：创建目录/文件；只写 dest（先 temp 后 rename）。
    不变量：
      1. dest 已存在 → 拒绝，不覆盖；
      2. 所有文件写完、fsync 后才写 manifest、才 rename；
      3. manifest 不列自身；整体 manifest 哈希由返回值给出。
    错误：`PackagerError`（DEST_EXISTS / WRITE_FAILED / ...）。
    """
    # 1. 先校验输入与规格；失败时不创建任何目录。
    specs = plan_bundle(inputs)

    # 2. 目标目录必须不存在；不允许“清空后重写”。
    destination = Path(dest).expanduser().resolve(strict=False)
    if destination.exists():
        raise PackagerError("DEST_EXISTS", f"目标目录已存在，拒绝覆盖：{destination.name}", field_path="dest")

    # 3. 创建同卷临时目录；名字带随机后缀，避免并发撞车。
    temp_dir = destination.parent / f".{destination.name}.tmp-{secrets.token_hex(8)}"
    temp_dir.mkdir(parents=False, exist_ok=False)

    try:
        # 4. 构造每类文件的字节；manifest 最后写。
        entries: list[_Entry] = []
        for spec in specs:
            if spec.role == "bundle_manifest":
                continue
            data = _render_file(spec.role, inputs)
            _write_bytes(temp_dir / spec.path, data)
            entries.append(_Entry(spec=spec, data=data))

        # 5. 计算条目并构造 manifest（不含自身）。
        created = _normalize_created_at(created_at)
        manifest = _build_manifest(inputs, entries, created)
        manifest_bytes = jcs.canonicalize(manifest)

        # 6. manifest 最后写；写完 fsync 文件与目录。
        _write_bytes(temp_dir / MANIFEST_NAME, manifest_bytes)
        _fsync_directory(temp_dir)

        # 7. 原子改名到目标；dest 仍不存在。
        os.replace(temp_dir, destination)
        _fsync_directory(destination.parent)

        # 8. 计算整体清单哈希并返回。
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        optional_present = tuple(entry.spec.role for entry in entries if not entry.spec.required)
        optional_absent = tuple(
            spec.role for spec in OPTIONAL_BUNDLE_FILES if spec.role not in optional_present
        )
        return BundleExportResult(
            bundle_dir=str(destination),
            manifest_sha256=manifest_sha256,
            file_count=len(entries) + 1,
            optional_present=optional_present,
            optional_absent=optional_absent,
        )
    except Exception:
        # 9. 失败清理临时目录；不触碰 dest。
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _render_file(role: str, inputs: BundleInputs) -> bytes:
    """按 role 生成文件字节；固定映射，不允许调用方自定义路径。"""
    # 1. 结构化 JSON 一律用 JCS 字节，保证跨平台稳定。
    if role == "task_spec":
        return jcs.canonicalize(dict(inputs.task_spec))
    if role == "graph":
        return jcs.canonicalize(dict(inputs.graph))
    if role == "artifact_manifest":
        return jcs.canonicalize(dict(inputs.artifact_manifest))
    if role == "split_manifest":
        return jcs.canonicalize(dict(inputs.split_manifest))
    if role == "verification_report":
        return jcs.canonicalize(dict(inputs.report))
    if role == "completion_certificate":
        return jcs.canonicalize(dict(inputs.certificate))
    if role == "merkle_proofs":
        return jcs.canonicalize(dict(inputs.merkle_proofs))
    if role == "trusted_key_fingerprint":
        return jcs.canonicalize(dict(inputs.trusted_fingerprints))

    # 2. evidence.jsonl：一行一个信封，行尾 \n；数组顺序即 event_seq 顺序。
    if role == "evidence":
        lines: list[bytes] = []
        for envelope in inputs.evidence:
            lines.append(
                jcs.canonicalize(
                    {
                        "record": dict(envelope.record),
                        "payload": dict(envelope.payload),
                    }
                )
            )
        return b"\n".join(lines) + b"\n"

    # 3. 工具副本与 README 原样写入；工具哈希由 manifest 记录。
    if role == "verify_bundle":
        return inputs.verify_bundle_source
    if role == "README":
        return inputs.readme.encode("utf-8")

    # 4. 可选文件。
    if role == "anchor_proof" and inputs.anchor_proof is not None:
        return jcs.canonicalize(dict(inputs.anchor_proof))
    if role == "recheck_data" and inputs.recheck_data is not None:
        return inputs.recheck_data

    # 5. 未实现 role 必须 fail-closed，不能写空文件。
    raise PackagerError("BUNDLE_ROLE_UNKNOWN", f"未实现的包文件角色：{role!r}", field_path="bundle")


def _build_manifest(
    inputs: BundleInputs,
    entries: Sequence[_Entry],
    created_at: str,
) -> Mapping[str, object]:
    """构造 bundle_manifest.json 的 body；不包含自身。"""
    # 1. 文件条目：按 role 固定顺序（必需 11 个 + 可选存在项）；不排序，便于人工比对。
    files: list[Mapping[str, object]] = []
    for entry in entries:
        files.append(
            MappingProxyType(
                {
                    "role": entry.spec.role,
                    "path": entry.spec.path,
                    "sha256": entry.sha256,
                    "size": len(entry.data),
                    "media_type": entry.spec.media_type,
                    "required": entry.spec.required,
                }
            )
        )

    # 2. 可选状态：缺失必须标 absent + reason，不得省略。
    optional: dict[str, Mapping[str, object]] = {}
    present_roles = {entry.spec.role for entry in entries}
    for spec in OPTIONAL_BUNDLE_FILES:
        if spec.role in present_roles:
            optional[spec.role] = MappingProxyType({"status": "present", "path": spec.path})
        else:
            optional[spec.role] = MappingProxyType({"status": "absent", "reason": "NOT_PROVIDED"})

    # 3. 计数：12 类必需；manifest 自身不计入 files；hashed_in_manifest = 11。
    required_hashed = sum(1 for spec in REQUIRED_BUNDLE_FILES if spec.self_hashed)
    counts = MappingProxyType(
        {
            "required_classes": len(REQUIRED_BUNDLE_FILES),
            "required_present": len(REQUIRED_BUNDLE_FILES),
            "hashed_in_manifest": len(files),
            "required_hashed": required_hashed,
            "optional_present": sum(1 for status in optional.values() if status["status"] == "present"),
            "optional_absent": sum(1 for status in optional.values() if status["status"] == "absent"),
            "evidence_records": len(inputs.evidence),
        }
    )

    # 4. 清单本体。`manifest` 段描述自身哈希规则，不写自身哈希。
    return MappingProxyType(
        {
            "bundle_format": BUNDLE_FORMAT_VERSION,
            "created_at": created_at,
            "task_id": inputs.task_id,
            "report_id": inputs.report.get("report_id"),
            "cert_id": inputs.certificate.get("cert_id"),
            "manifest": MappingProxyType(
                {
                    "path": MANIFEST_NAME,
                    "self_hashed": False,
                    "sha256_rule": "sha256(exact file bytes); reported by verifier, never embedded",
                }
            ),
            "files": list(files),
            "optional": MappingProxyType(optional),
            "counts": counts,
            "integrity_profile": MappingProxyType(
                {
                    "jcs": "RFC8785",
                    "evidence_envelope": "record+payload/v1",
                    "chain_preimage": "RF-EVIDENCE-CHAIN\\x00v1\\x00 (P4 proposal; OQ-P4-02)",
                    "merkle": "RFC9162",
                }
            ),
            "tool": MappingProxyType(
                {
                    "name": "verify_bundle.py",
                    "bundle_format": BUNDLE_FORMAT_VERSION,
                    "sha256": hashlib.sha256(inputs.verify_bundle_source).hexdigest(),
                }
            ),
        }
    )


def compute_manifest_sha256(bundle_dir: str | os.PathLike[str]) -> str:
    """读取 `bundle_manifest.json` 原始字节并返回 SHA-256。"""
    path = Path(bundle_dir) / MANIFEST_NAME
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bytes(path: Path, data: bytes) -> None:
    """安全写文件：父目录必须已存在，文件不得是符号链接。"""
    # 1. 拒绝超大文件。
    if len(data) > _MAX_FILE_BYTES:
        raise PackagerError("FILE_TOO_LARGE", f"文件超过 {_MAX_FILE_BYTES} 字节", field_path=path.name)
    # 2. 父目录必须存在且不是符号链接。
    if path.is_symlink():
        raise PackagerError("SYMLINK_FORBIDDEN", "包内不得写符号链接", field_path=path.name)
    # 3. 写字节并 fsync。
    with open(path, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    """尽力 fsync 目录；Windows 不支持目录 fd 时静默跳过。"""
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _normalize_created_at(value: str | None) -> str:
    """校验/生成 manifest 创建时间；UTC、带 Z。"""
    # 1. 默认取当前 UTC。
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    # 2. 注入值必须是 UTC RFC 3339；解析后统一成 Z。
    if _UTC_RE.match(value) is None:
        raise PackagerError(
            "CREATED_AT_INVALID",
            "created_at 必须是 UTC RFC 3339",
            field_path="created_at",
            error_code="SCHEMA_INVALID",
        )
    parsed = parse_rfc3339_utc(value, field_path="created_at")
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _assert_anchor_proof_shape(anchor: Mapping[str, object]) -> None:
    """AnchorProof 只做字段/类型检查；验签在 verify_bundle 里用包外 anchor key 完成。"""
    # 1. 字段集合必须恰好是 7.4 的七个字段；不静默接受额外字段。
    unknown = sorted(set(anchor.keys()) - set(ANCHOR_PROOF_FIELDS))
    missing = sorted(set(ANCHOR_PROOF_FIELDS) - set(anchor.keys()))
    if unknown or missing:
        raise PackagerError(
            "ANCHOR_PROOF_SHAPE_INVALID",
            f"AnchorProof 字段不匹配：缺少 {missing}，多出 {unknown}",
            field_path="anchor_proof",
            error_code="SCHEMA_INVALID",
        )
    # 2. 哈希/整数/时间字段。
    for field in ("certificate_hash", "merkle_root"):
        if not isinstance(anchor[field], str) or _HASH64_RE.match(anchor[field]) is None:
            raise PackagerError(
                "ANCHOR_PROOF_SHAPE_INVALID",
                f"{field} 必须是 64 位小写十六进制",
                field_path=f"anchor_proof.{field}",
                error_code="SCHEMA_INVALID",
            )
    if isinstance(anchor["tree_size"], bool) or not isinstance(anchor["tree_size"], int) or anchor["tree_size"] < 1:
        raise PackagerError(
            "ANCHOR_PROOF_SHAPE_INVALID",
            "tree_size 必须是 ≥1 的 integer",
            field_path="anchor_proof.tree_size",
            error_code="SCHEMA_INVALID",
        )
    if not isinstance(anchor["anchor_type"], str) or not anchor["anchor_type"]:
        raise PackagerError(
            "ANCHOR_PROOF_SHAPE_INVALID",
            "anchor_type 必须是非空字符串",
            field_path="anchor_proof.anchor_type",
            error_code="SCHEMA_INVALID",
        )
    if not isinstance(anchor["timestamp"], str) or _UTC_RE.match(anchor["timestamp"]) is None:
        raise PackagerError(
            "ANCHOR_PROOF_SHAPE_INVALID",
            "timestamp 必须是 UTC RFC 3339",
            field_path="anchor_proof.timestamp",
            error_code="SCHEMA_INVALID",
        )
    if not isinstance(anchor["receipt"], (str, Mapping)):
        raise PackagerError(
            "ANCHOR_PROOF_SHAPE_INVALID",
            "receipt 必须是 string 或 object",
            field_path="anchor_proof.receipt",
            error_code="SCHEMA_INVALID",
        )
    if not isinstance(anchor["proof_signature"], str) or not anchor["proof_signature"]:
        raise PackagerError(
            "ANCHOR_PROOF_SHAPE_INVALID",
            "proof_signature 必须是非空 base64 字符串",
            field_path="anchor_proof.proof_signature",
            error_code="SCHEMA_INVALID",
        )


def _assert_claims_only(document: Mapping[str, object]) -> None:
    """`trusted_key_fingerprint.json` 只允许 key_id→fingerprint 声明。"""
    # 1. 顶层允许字段。
    allowed_top = {"schema_version", "claims_only", "keys"}
    unknown = sorted(set(document.keys()) - allowed_top)
    if unknown:
        raise PackagerError(
            "TRUST_CLAIMS_UNKNOWN_FIELD",
            f"指纹声明不允许字段：{unknown}",
            field_path="trusted_fingerprint",
            error_code="SCHEMA_INVALID",
        )
    # 1.1 声明格式版本固定 1.0。
    if document.get("schema_version") != "1.0":
        raise PackagerError(
            "TRUST_CLAIMS_VERSION_UNSUPPORTED",
            "trusted_key_fingerprint.json 的 schema_version 必须是 1.0",
            field_path="trusted_fingerprint.schema_version",
            error_code="SCHEMA_INVALID",
        )
    # 2. 必须显式 claims_only=true，防止被当成信任库使用。
    if document.get("claims_only") is not True:
        raise PackagerError(
            "TRUST_CLAIMS_NOT_MARKED",
            "trusted_key_fingerprint.json 必须标记 claims_only=true",
            field_path="trusted_fingerprint.claims_only",
            error_code="SCHEMA_INVALID",
        )
    # 3. keys 数组逐项只能有 key_id/key_fingerprint；不得出现公钥。
    raw_keys = document.get("keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise PackagerError(
            "TRUST_CLAIMS_EMPTY",
            "指纹声明不得为空",
            field_path="trusted_fingerprint.keys",
            error_code="SCHEMA_INVALID",
        )
    for index, item in enumerate(raw_keys):
        if not isinstance(item, Mapping):
            raise PackagerError(
                "TRUST_CLAIMS_INVALID",
                "keys 元素必须是 object",
                field_path=f"trusted_fingerprint.keys[{index}]",
                error_code="SCHEMA_INVALID",
            )
        if set(item.keys()) != {"key_id", "key_fingerprint"}:
            raise PackagerError(
                "TRUST_CLAIMS_INVALID",
                "每条声明只能含 key_id/key_fingerprint",
                field_path=f"trusted_fingerprint.keys[{index}]",
                error_code="SCHEMA_INVALID",
            )
        if not isinstance(item["key_id"], str) or not item["key_id"]:
            raise PackagerError("TRUST_CLAIMS_INVALID", "key_id 必须非空", error_code="SCHEMA_INVALID")
        if not isinstance(item["key_fingerprint"], str) or _HASH64_RE.match(item["key_fingerprint"]) is None:
            raise PackagerError(
                "TRUST_CLAIMS_INVALID",
                "key_fingerprint 必须是 64 位小写十六进制",
                error_code="SCHEMA_INVALID",
            )


def _assert_no_forbidden_material(value: object, path: str) -> None:
    """递归拒绝显式私钥/私钥种子/secret/passphrase 字段与 PEM 私钥文本。

    注意：`seed`（无前缀）是合法随机种子（TaskSpec.parameters.seed / split_manifest.seed），
    **不得**按裸键名拒绝；私钥种子只认 `private_key_seed` / `key_seed` 等显式键名。
    """
    # 1. 映射：检查键名与值。
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in _FORBIDDEN_KEYS:
                raise PackagerError(
                    "PRIVATE_MATERIAL_IN_BUNDLE",
                    f"证据包输入不得包含 {key!r}",
                    field_path=f"{path}.{key}",
                )
            _assert_no_forbidden_material(item, f"{path}.{key}")
        return
    # 2. 数组：逐项。
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_forbidden_material(item, f"{path}[{index}]")
        return
    # 3. 字符串：拒绝 PEM 私钥头；不拒绝普通业务文本。
    if isinstance(value, str) and "-----BEGIN" in value and "PRIVATE KEY-----" in value:
        raise PackagerError(
            "PRIVATE_MATERIAL_IN_BUNDLE",
            "证据包输入中出现 PEM 私钥文本",
            field_path=path,
        )
    # 4. 其他类型不处理（JCS 层会拒绝非法类型）。
    return


def assert_no_forbidden_material(value: object, path: str) -> None:
    """公开的材料扫描入口；供 `verify_bundle` 复用，行为与 `_assert_no_forbidden_material` 一致。

    只拒绝显式私钥/私钥种子/secret/passphrase 键名与 PEM 私钥文本；
    `seed`（无前缀）是合法随机种子，**不在**禁用集合内。
    """
    _assert_no_forbidden_material(value, path)


def assert_no_pem_private_key(text: str, path: str = "README") -> None:
    """只检查文本中的 PEM 私钥头；用于 README 等普通文字，不按 `private_key` 字样拒绝。"""
    # 1. 非字符串不做文本扫描；结构对象由 assert_no_forbidden_material 负责。
    if not isinstance(text, str):
        raise PackagerError(
            "TEXT_REQUIRED",
            "PEM 扫描输入必须是字符串",
            field_path=path,
            error_code="SCHEMA_INVALID",
        )
    # 2. 只匹配 PEM 私钥头；不匹配普通的 "private_key" 说明文字。
    if "-----BEGIN" in text and "PRIVATE KEY-----" in text:
        raise PackagerError(
            "PRIVATE_MATERIAL_IN_BUNDLE",
            "README 中出现 PEM 私钥文本",
            field_path=path,
        )


def assert_packager_boundary() -> tuple[str, ...]:
    """返回导出器静态边界清单，供测试/评审逐条断言。"""
    # 1. 必需类数量必须是 12，且恰好一个不自哈希。
    if len(REQUIRED_BUNDLE_FILES) != 12:
        raise AssertionError(f"必需包文件类必须是 12，实际 {len(REQUIRED_BUNDLE_FILES)}")
    self_hashed = [spec.role for spec in REQUIRED_BUNDLE_FILES if spec.self_hashed]
    if len(self_hashed) != 11:
        raise AssertionError(f"被 manifest 哈希的必需文件必须是 11，实际 {len(self_hashed)}")
    # 2. 不允许的文件后缀不得出现在任何规格中。
    for spec in (*REQUIRED_BUNDLE_FILES, *OPTIONAL_BUNDLE_FILES):
        if any(spec.path.lower().endswith(suffix) for suffix in _FORBIDDEN_SUFFIXES):
            raise AssertionError(f"禁止后缀进入包：{spec.path}")
    # 3. 返回边界说明。
    return (
        "证据包只有 12 类必需文件；manifest 不自哈希",
        "anchor_proof 缺失时标 absent，不写空文件",
        "包内不得含私钥/信任库/模型二进制/数据库/日志",
        "导出器不签名、不验签、不写证据库/状态",
        "所有 JSON 文件用 JCS 字节，保证跨平台可复算",
    )