"""MODULE: M12 · verifier/bundle/verify_bundle.py — 离线证据包验签 CLI（P6 伪代码）
阶段/追踪: P6「签名与离线凭证」｜FR-009、NFR-07、策划书 §9.5（P0249–P0251）、§7.5、§7.6
FR/依赖: FR-009；依赖 M11 jcs/payloads/ed25519_signer/trust_store 与 packager 的格式常量；
          **不连数据库、不连模型、不联网、不读私钥**
不变量/错误码: 验签只认 `--trust-store`；包内公钥/信任库一律不作为信任源；检查顺序固定、fail-fast；
             每个失败映射不同退出码；**不得统一返回 1**；正例通过不构成完成证据，五类负例必须逐条断言原因。
              错误码：BUNDLE_TAMPERED（422）/ SIGNATURE_INVALID（422）/ TRUST_ANCHOR_MISSING（503）/
              RULESET_VERSION_MISMATCH（409）等，按检查阶段映射 CLI 退出码
写入者: **无**；只读证据包与信任库，只写 stdout/stderr；不写证据、不写状态、不产生新凭证
状态: 伪代码；WP-12 落地；包格式 v1.0（P6 内部格式）；真实执行证据见 NEGATIVE_TESTS 落地记录

## 命令

    python verify_bundle.py ./evidence_bundle --trust-store ./trusted_keys.json
    python verify_bundle.py ./evidence_bundle --trust-store ./trusted_keys.json \
        --trust-store-sha256 <64-hex> --json

  退出码见 `EXIT_CODE_TABLE`；0 只表示“完整性 + 签名 + 根一致性 + 策略”全部通过，
  不表示“L1/L2/L3 重新验证通过”（P6 不做），也不表示“已外部锚定”（anchor 可为 ABSENT）。

## 检查顺序（fail-fast，后面的检查不再执行）

  1. 环境与依赖（9）        —— 禁止 sqlite3/researchflow/sklearn/torch/joblib/requests 等
  2. 证据包根（4）          —— 存在、目录、非符号链接
  3. 信任锚（3）            —— 包外、非空、严格 JSON、可选钉死哈希、无包内自证
  4. 清单（4）              —— manifest 结构/12 类/计数/完整性 profile、不自哈希
  5. 文件清单与哈希（4）    —— 必需文件齐全、无多出文件、路径不逃逸、逐文件 sha256/size
  6. 内容解析（4）          —— 严格 JSON、payload 白名单、证据 record/payload 哈希、无重复
  7. 链与根（6）            —— event_seq/prev 链、chain_hash 重算、Merkle 根/树大小/规则版本/划分哈希
  8. 签名（5）              —— Report/Certificate Ed25519、key_id/指纹、撤销/有效期、声明交叉核对
  9. 策略（7）              —— 仅 VERIFIED、报告/证书/任务一致、覆盖算术、时间顺序、T0 无 SPA
 10. 锚定（8）              —— anchor 缺失=ABSENT；存在则验签；失败不降级为通过
 11. 汇总（0）              —— 输出 manifest 哈希、evidence_root、anchor 状态

## 退出码表（≥6 个不同值；逐条可断言）

  | code | 名称 | 含义 | 典型触发 |
  |---:|---|---|---|
  | 0 | `VERIFIED` | 全部检查通过 | 真包 + 正确外部信任锚 |
  | 2 | `USAGE_ERROR` | 参数/用法错误 | 缺 `--trust-store`、未知参数、路径参数缺失 |
  | 3 | `TRUST_ANCHOR_ERROR` | 信任锚不可用 | 信任库缺失/为空/在包内/哈希不符/ key 不在锚内 |
  | 4 | `BUNDLE_INTEGRITY_ERROR` | 包不完整或被改 | 缺 split_manifest、文件哈希不符、多出文件、JSON 非法、payload 哈希不符 |
  | 5 | `SIGNATURE_ERROR` | 签名不可信 | 破签名、改报告状态、签名格式错、key 撤销/过期、指纹不符 |
  | 6 | `ROOT_CONSISTENCY_ERROR` | 根/链/规则不一致 | 改证据记录、event_seq 断档、Merkle 根不符、tree_size 不符、规则版本不符 |
  | 7 | `POLICY_ERROR` | 签名有效但不得作为完成凭证 | 非 VERIFIED、报告/证书 ID 不一致、覆盖缺口、T0 出现 skipped_nodes |
  | 8 | `ANCHOR_ERROR` | AnchorProof 存在但无效 | anchor 签名错、certificate_hash 不符、anchor key 缺失/歧义 |
  | 9 | `ENVIRONMENT_ERROR` | 离线工具环境不满足 | 依赖了 DB/模型库、Python < 3.11、内部异常 |

  **不得返回 1**：1 是“未分类失败”的懒惰写法，会让负例无法区分原因；
  未预期异常统一 9，且 stderr 只输出脱敏摘要（`--debug` 才输出堆栈，仍不得含密钥）。
  `KeyboardInterrupt` 按 OS 约定返回 130，它不是验签结论。

## 五类负例（必须逐条断言退出码）

  | 负例 | 操作 | 期望退出码 | 期望 reason |
  |---|---|---:|---|
  | 改 payload | 改 evidence.jsonl 的 payload 内容，保留 record | 4 | `EVIDENCE_PAYLOAD_HASH_MISMATCH` |
  | 换公钥 | 换签名钥匙并用攻击者 key 重签/替换指纹声明 | 3 | `KEY_NOT_IN_TRUST_STORE` |
  | 删 split_manifest | 删除文件但不改 manifest | 4 | `REQUIRED_FILE_MISSING` |
  | 改报告状态 | 把 report.final_state 改成 PARTIAL/VERIFIED 另一值 | 5 | `SIGNATURE_MISMATCH` |
  | 破签名 | 改 signature 最后一个字节/截断 base64 | 5 | `SIGNATURE_MISMATCH` / `SIGNATURE_BASE64_INVALID` |

## 边界（不得越界声明）

  - **不重跑 L1/L2/L3**：只验文件完整性、签名、根一致性；`split_manifest` 的内部哈希会重算，
    但“划分是否真的按该 seed 生成”属 L2/L3，P6 不判。
  - **不生成新凭证**：不签报告/证书、不写证据、不写状态。
  - **chain_hash 前像未冻结**（`OQ-P4-02`）：本工具按 P4 提案 `RF-EVIDENCE-CHAIN\\x00v1\\x00`
    重算，并在摘要里标 `chain_preimage=P4_PROPOSAL_V1`；算法变更必须升包格式版本。
  - **anchor 缺失不是失败**：7.4/7.6 允许“本地副本只称备份”；缺失输出 `anchor=ABSENT`，
    不得写成“已锚定”。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final, Mapping, Sequence

from verifier.bundle import packager
from verifier.crypto import ed25519_signer, jcs, payloads, trust_store

__all__ = [
    "EXIT_OK",
    "EXIT_USAGE",
    "EXIT_TRUST",
    "EXIT_INTEGRITY",
    "EXIT_SIGNATURE",
    "EXIT_ROOT",
    "EXIT_POLICY",
    "EXIT_ANCHOR",
    "EXIT_ENVIRONMENT",
    "EXIT_CODE_TABLE",
    "CheckResult",
    "Outcome",
    "assert_exit_code_table",
    "main",
]

EXIT_OK: Final[int] = 0
EXIT_USAGE: Final[int] = 2
EXIT_TRUST: Final[int] = 3
EXIT_INTEGRITY: Final[int] = 4
EXIT_SIGNATURE: Final[int] = 5
EXIT_ROOT: Final[int] = 6
EXIT_POLICY: Final[int] = 7
EXIT_ANCHOR: Final[int] = 8
EXIT_ENVIRONMENT: Final[int] = 9

TOOL_VERSION: Final[str] = "1.0.0-p6"
CHAIN_DOMAIN: Final[bytes] = b"RF-EVIDENCE-CHAIN\x00v1\x00"
ANCHOR_DOMAIN: Final[bytes] = b"RF-ANCHOR-V1\x00"
MAX_JSON_BYTES: Final[int] = 16 * 1024 * 1024
MAX_EVIDENCE_BYTES: Final[int] = 256 * 1024 * 1024

_HASH64_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^ev_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_TASK_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^task_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_ATTEMPT_ID_RE: Final[re.Pattern[str]] = re.compile(r"^attempt_[0-9]{2,}$")
_NODE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_UTC_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|\+00:00)$"
)
_ARTIFACT_REF_RE: Final[re.Pattern[str]] = re.compile(r"^artifact://[A-Za-z0-9][A-Za-z0-9._/-]*$")

_FORBIDDEN_MODULES: Final[tuple[str, ...]] = (
    "sqlite3",
    "researchflow",
    "sklearn",
    "torch",
    "joblib",
    "requests",
    "pandas",
    "urllib3",
)

_LEVEL_KINDS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "E0": ("agent_claim",),
        "E1": ("tool_invocation", "harness_trace"),
        "E2": ("executor_launch", "executor_process_exit", "artifact_observed"),
        "E3": ("verifier_recheck",),
    }
)
_PRODUCER_BY_LEVEL: Final[Mapping[str, str]] = MappingProxyType(
    {"E0": "collector", "E1": "collector", "E2": "collector", "E3": "verifier"}
)

_RECORD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "evidence_id",
        "task_id",
        "node_id",
        "attempt_id",
        "event_seq",
        "level",
        "kind",
        "producer",
        "timestamp",
        "payload_hash",
        "artifact_refs",
        "prev_hash",
        "chain_hash",
    }
)
_RECORD_REQUIRED: Final[frozenset[str]] = _RECORD_FIELDS - {"artifact_refs"}

_SPLIT_FIELDS: Final[tuple[str, ...]] = (
    "dataset_hash",
    "split",
    "seed",
    "row_id_hash",
    "fold_assignment_hash",
    "semantics",
)


@dataclass(frozen=True, slots=True)
class ExitCodeInfo:
    """退出码表的一行；用于文档、自检和 `--help`。"""

    code: int
    name: str
    meaning: str
    triggers: str


EXIT_CODE_TABLE: Final[tuple[ExitCodeInfo, ...]] = (
    ExitCodeInfo(0, "VERIFIED", "全部检查通过", "真包 + 正确外部信任锚"),
    ExitCodeInfo(2, "USAGE_ERROR", "参数/用法错误", "缺 --trust-store、未知参数"),
    ExitCodeInfo(3, "TRUST_ANCHOR_ERROR", "信任锚不可用", "信任库缺失/为空/在包内/哈希不符/未知 key"),
    ExitCodeInfo(4, "BUNDLE_INTEGRITY_ERROR", "包不完整或被改", "缺件/多件/哈希不符/JSON 非法/payload 哈希不符"),
    ExitCodeInfo(5, "SIGNATURE_ERROR", "签名不可信", "破签名/改状态/格式错/key 撤销或过期/指纹不符"),
    ExitCodeInfo(6, "ROOT_CONSISTENCY_ERROR", "根/链/规则不一致", "改记录/seq 断档/Merkle 根或 tree_size 不符/规则版本不符"),
    ExitCodeInfo(7, "POLICY_ERROR", "签名有效但不得作为完成凭证", "非 VERIFIED/ID 不一致/覆盖缺口/T0 出现 SPA"),
    ExitCodeInfo(8, "ANCHOR_ERROR", "AnchorProof 无效", "anchor 签名错/certificate_hash 不符/anchor key 缺失"),
    ExitCodeInfo(9, "ENVIRONMENT_ERROR", "离线环境不满足", "依赖 DB/模型库/Python 版本/内部异常"),
)


class _CheckFailure(Exception):
    """内部检查失败；携带检查名、退出码、reason、字段路径与脱敏 detail。"""

    def __init__(
        self,
        check: str,
        exit_code: int,
        reason: str,
        message: str,
        *,
        field_path: str = "bundle",
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.check = check
        self.exit_code = exit_code
        self.reason = reason
        self.field_path = field_path
        self.detail = dict(detail or {})
        super().__init__(message)


class _UsageError(Exception):
    """CLI 用法错误；映射退出码 2，不打印堆栈。"""


@dataclass(frozen=True, slots=True)
class CheckResult:
    """一项检查的结果；`status` 只允许 PASS/FAIL/SKIP。"""

    check: str
    status: str
    exit_code: int = 0
    reason: str | None = None
    detail: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "FAIL", "SKIP"}:
            raise ValueError(f"非法检查状态：{self.status!r}")


@dataclass(frozen=True, slots=True)
class Outcome:
    """一次验签的完整结果；退出码由第一个 FAIL 决定。"""

    exit_code: int
    checks: tuple[CheckResult, ...]
    summary: Mapping[str, object]

    @property
    def passed(self) -> bool:
        return self.exit_code == EXIT_OK


@dataclass
class _State:
    """一次运行的只读视图 + 已解析对象；不跨调用复用。"""

    root: Path
    trust: trust_store.TrustStore | None = None
    manifest: Mapping[str, object] = field(default_factory=dict)
    manifest_sha256: str = ""
    entries: dict[str, Mapping[str, object]] = field(default_factory=dict)
    paths: dict[str, Path] = field(default_factory=dict)
    objects: dict[str, object] = field(default_factory=dict)
    evidence: list[Mapping[str, object]] = field(default_factory=list)
    report_payload: payloads.SigningPayload | None = None
    certificate_payload: payloads.SigningPayload | None = None
    checks: list[CheckResult] = field(default_factory=list)

    def pass_check(self, name: str, detail: Mapping[str, object] | None = None) -> None:
        """记录一项 PASS；detail 只放计数/哈希前缀/状态，不放公钥或正文。"""
        self.checks.append(CheckResult(name, "PASS", detail=detail))


# ---------------------------------------------------------------------------
# 0. CLI
# ---------------------------------------------------------------------------
class _ArgumentParser(argparse.ArgumentParser):
    """把 argparse 的 `sys.exit(2)` 收敛成可返回的 `_UsageError`。"""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise _UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数；`--trust-store` 必填，路径不做 shell 展开以外的解释。"""
    parser = _ArgumentParser(
        prog="verify_bundle.py",
        description="ResearchFlow Evidence Bundle 离线验签（不依赖数据库与模型）",
        epilog="退出码见 MODULE.md；0=通过，2/3/4/5/6/7/8/9 各有独立含义；不会返回 1。",
    )
    parser.add_argument("bundle_dir", help="证据包目录")
    parser.add_argument("--trust-store", required=True, help="包外可信公钥 JSON")
    parser.add_argument("--trust-store-sha256", default=None, help="可选：钉死信任库文件哈希")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--quiet", action="store_true", help="只输出 RESULT 行")
    parser.add_argument("--debug", action="store_true", help="内部异常时输出堆栈（仍脱敏）")
    parser.add_argument("--version", action="version", version=f"%(prog)s {TOOL_VERSION}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口；返回退出码，不抛 SystemExit（`__main__` 再转）。"""
    # 1. 退出码表自检：必须 ≥6 个不同非零值，且不含 1。
    try:
        assert_exit_code_table()
    except AssertionError:
        print("ENVIRONMENT_ERROR/EXIT_CODE_TABLE_INVALID", file=sys.stderr)
        return EXIT_ENVIRONMENT

    # 2. 解析参数；用法错误返回 2。
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except _UsageError as exc:
        print(f"USAGE_ERROR: {exc}", file=sys.stderr)
        return EXIT_USAGE

    # 3. 执行检查；所有已知异常映射到固定退出码。
    try:
        outcome = _run(args)
    except KeyboardInterrupt:
        # OS 约定；不是验签结论。
        return 130
    except Exception as exc:  # 最后一道 fail-closed
        print(f"ENVIRONMENT_ERROR/INTERNAL: {type(exc).__name__}", file=sys.stderr)
        if getattr(args, "debug", False):
            import traceback

            traceback.print_exc()
        return EXIT_ENVIRONMENT

    # 4. 输出并返回。
    _emit(outcome, json_mode=bool(args.json), quiet=bool(args.quiet))
    return outcome.exit_code


def _run(args: argparse.Namespace) -> Outcome:
    """按固定顺序执行检查；第一个失败即返回。"""
    state = _State(root=Path(args.bundle_dir).expanduser().resolve(strict=False))
    try:
        # 1. 环境。
        _phase_environment(state)
        # 2. 包根。
        _phase_bundle_root(state)
        # 3. 信任锚（必须在读包内容前建立）。
        _phase_trust(state, args.trust_store, args.trust_store_sha256)
        # 4. 清单。
        _phase_manifest(state)
        # 5. 文件清单/哈希。
        _phase_inventory(state)
        # 6. 解析内容。
        _phase_parse(state)
        # 7. 链与根。
        _phase_roots(state)
        # 8. 签名。
        _phase_signatures(state)
        # 9. 策略。
        _phase_policy(state)
        # 10. 锚定。
        _phase_anchor(state)
        # 11. 成功。
        return Outcome(
            exit_code=EXIT_OK,
            checks=tuple(state.checks),
            summary=_summary(state, anchor=_anchor_status(state)),
        )
    except _CheckFailure as failure:
        failed = CheckResult(
            failure.check,
            "FAIL",
            exit_code=failure.exit_code,
            reason=failure.reason,
            detail=MappingProxyType(
                {
                    **failure.detail,
                    "field_path": failure.field_path,
                    "message": str(failure),
                }
            ),
        )
        return Outcome(
            exit_code=failure.exit_code,
            checks=(*state.checks, failed),
            summary=_summary(state, anchor=_anchor_status(state)),
        )
    except trust_store.TrustAnchorError as exc:
        return _failed_outcome(state, "trust", EXIT_TRUST, exc.reason, exc.field_path, str(exc))
    except trust_store.TrustSignatureError as exc:
        return _failed_outcome(state, "signature", EXIT_SIGNATURE, exc.reason, exc.field_path, str(exc))
    except ed25519_signer.SignerError as exc:
        return _failed_outcome(state, "signature", EXIT_SIGNATURE, exc.reason, exc.field_path, str(exc))
    except jcs.JcsError as exc:
        return _failed_outcome(state, "parse", EXIT_INTEGRITY, exc.reason, exc.field_path, str(exc))
    except payloads.PayloadError as exc:
        return _failed_outcome(state, "parse", EXIT_INTEGRITY, exc.reason, exc.field_path, str(exc))
    except packager.PackagerError as exc:
        return _failed_outcome(state, "inventory", EXIT_INTEGRITY, exc.reason, exc.field_path, str(exc))
    except OSError as exc:
        return _failed_outcome(state, "read", EXIT_INTEGRITY, "IO_ERROR", "bundle", str(exc))
    except Exception as exc:  # 未预期异常不得伪装成 1
        return _failed_outcome(
            state,
            "internal",
            EXIT_ENVIRONMENT,
            "INTERNAL_ERROR",
            "bundle",
            f"{type(exc).__name__}: {exc}",
        )


def _failed_outcome(
    state: _State,
    check: str,
    exit_code: int,
    reason: str,
    field_path: str,
    message: str,
) -> Outcome:
    """把已知异常收敛成 Outcome；message 只保留脱敏摘要。"""
    failed = CheckResult(
        check,
        "FAIL",
        exit_code=exit_code,
        reason=reason,
        detail=MappingProxyType({"field_path": field_path, "message": message}),
    )
    return Outcome(
        exit_code=exit_code,
        checks=(*state.checks, failed),
        summary=_summary(state, anchor=_anchor_status(state)),
    )


def _emit(outcome: Outcome, *, json_mode: bool, quiet: bool) -> None:
    """输出人读/机读结果；不输出公钥、证据正文或信任库全文。"""
    # 1. JSON 模式。
    if json_mode:
        document = {
            "result": "PASS" if outcome.passed else "FAIL",
            "exit_code": outcome.exit_code,
            "checks": [
                {
                    "check": check.check,
                    "status": check.status,
                    "exit_code": check.exit_code,
                    "reason": check.reason,
                    "detail": dict(check.detail) if check.detail else None,
                }
                for check in outcome.checks
            ],
            "summary": dict(outcome.summary),
        }
        print(jcs.canonicalize(document).decode("utf-8"))
        return

    # 2. 人读模式；quiet 只留 RESULT。
    if not quiet:
        print("ResearchFlow Evidence Bundle verification")
        for key in ("bundle", "manifest_sha256", "report_id", "cert_id", "evidence_root", "tree_size", "anchor"):
            if key in outcome.summary:
                print(f"{key}: {outcome.summary[key]}")
        print("")
        for check in outcome.checks:
            line = f"[{check.status}] {check.check}"
            if check.reason:
                line += f" ({check.reason})"
            print(line)
        print("")
    print(f"RESULT: {'PASS' if outcome.passed else 'FAIL'} (exit {outcome.exit_code})")


def _summary(state: _State, *, anchor: str) -> Mapping[str, object]:
    """构造脱敏摘要；缺失字段用 None，不伪造值。"""
    report = state.objects.get("verification_report")
    certificate = state.objects.get("completion_certificate")
    report_map = report if isinstance(report, Mapping) else {}
    cert_map = certificate if isinstance(certificate, Mapping) else {}
    return MappingProxyType(
        {
            "bundle": str(state.root),
            "manifest_sha256": state.manifest_sha256 or None,
            "files_checked": len(state.paths),
            "evidence_records": len(state.evidence),
            "report_id": report_map.get("report_id"),
            "cert_id": cert_map.get("cert_id"),
            "evidence_root": report_map.get("evidence_root"),
            "tree_size": cert_map.get("tree_size"),
            "anchor": anchor,
            "chain_preimage": "P4_PROPOSAL_V1",
            "tool_version": TOOL_VERSION,
        }
    )


def _anchor_status(state: _State) -> str:
    """从 manifest 读 anchor 状态；未解析时返回 UNKNOWN，不默认 ABSENT。"""
    optional = state.manifest.get("optional")
    if not isinstance(optional, Mapping):
        return "UNKNOWN"
    anchor = optional.get("anchor_proof")
    if not isinstance(anchor, Mapping):
        return "UNKNOWN"
    status = anchor.get("status")
    return str(status).upper() if status in {"present", "absent"} else "UNKNOWN"


# ---------------------------------------------------------------------------
# 1. 环境
# ---------------------------------------------------------------------------
def _phase_environment(state: _State) -> None:
    """检查解释器版本与“离线工具不得依赖”的模块。"""
    # 1. Python 版本；项目基线 3.11。
    if sys.version_info < (3, 11):
        raise _CheckFailure(
            "environment",
            EXIT_ENVIRONMENT,
            "PYTHON_VERSION_UNSUPPORTED",
            f"需要 Python ≥3.11，实际 {sys.version.split()[0]}",
            field_path="python",
        )
    # 2. 禁止模块已加载：DB、业务包、模型/网络库。
    loaded = [name for name in _FORBIDDEN_MODULES if name in sys.modules]
    if loaded:
        raise _CheckFailure(
            "environment",
            EXIT_ENVIRONMENT,
            "FORBIDDEN_DEPENDENCY_LOADED",
            f"离线验签环境加载了禁止模块：{loaded}",
            field_path="sys.modules",
            detail={"modules": loaded},
        )
    state.pass_check("environment", {"python": sys.version.split()[0]})


# ---------------------------------------------------------------------------
# 2. 证据包根
# ---------------------------------------------------------------------------
def _phase_bundle_root(state: _State) -> None:
    """确认 bundle_dir 是存在的真实目录，且不是符号链接。"""
    # 1. 存在性。
    if not state.root.exists():
        raise _CheckFailure(
            "bundle_root",
            EXIT_INTEGRITY,
            "BUNDLE_NOT_FOUND",
            "证据包目录不存在",
            field_path="bundle_dir",
        )
    # 2. 目录 + 非符号链接 + realpath。
    if state.root.is_symlink():
        raise _CheckFailure(
            "bundle_root",
            EXIT_INTEGRITY,
            "BUNDLE_ROOT_SYMLINK",
            "证据包根不得是符号链接",
            field_path="bundle_dir",
        )
    if not state.root.is_dir():
        raise _CheckFailure(
            "bundle_root",
            EXIT_INTEGRITY,
            "BUNDLE_ROOT_NOT_DIR",
            "证据包路径必须是目录",
            field_path="bundle_dir",
        )
    state.root = state.root.resolve(strict=True)
    state.pass_check("bundle_root")


# ---------------------------------------------------------------------------
# 3. 信任锚
# ---------------------------------------------------------------------------
def _phase_trust(state: _State, trust_path: str, expected_sha256: str | None) -> None:
    """加载包外信任库；任何失败都映射 3，不得回退到包内公钥。"""
    # 1. 拒绝 URL 形式；信任库必须是本地文件。
    if isinstance(trust_path, str) and trust_path.lower().startswith(("http://", "https://")):
        raise _CheckFailure(
            "trust",
            EXIT_TRUST,
            "TRUST_STORE_REMOTE_FORBIDDEN",
            "信任库必须来自本地包外文件，不得联网获取",
            field_path="trust_store",
        )
    # 2. 加载；`TrustStore.load` 自己检查包内/空库/哈希/字段。
    try:
        state.trust = trust_store.load_trust_store(
            trust_path,
            bundle_root=state.root,
            expected_sha256=expected_sha256,
        )
    except trust_store.TrustAnchorError as exc:
        raise _CheckFailure(
            "trust",
            EXIT_TRUST,
            exc.reason,
            str(exc),
            field_path=exc.field_path,
            detail=exc.detail,
        ) from exc
    state.pass_check("trust", {"trust_store_sha256": state.trust.document_sha256, "keys": len(state.trust.keys)})


# ---------------------------------------------------------------------------
# 4. 清单
# ---------------------------------------------------------------------------
def _phase_manifest(state: _State) -> None:
    """读取并校验 bundle_manifest.json 的结构、12 类计数与完整性 profile。"""
    # 1. 读文件（严格 JSON、非符号链接、大小受限）。
    manifest_path = state.root / packager.MANIFEST_NAME
    document = _read_json(manifest_path, state.root, max_bytes=MAX_JSON_BYTES, role="bundle_manifest")
    if not isinstance(document, Mapping):
        raise _CheckFailure("manifest", EXIT_INTEGRITY, "MANIFEST_NOT_OBJECT", "manifest 顶层必须是 object")
    state.manifest = document
    state.manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    # 2. 顶层字段。
    required_top = {
        "bundle_format",
        "created_at",
        "task_id",
        "report_id",
        "cert_id",
        "manifest",
        "files",
        "optional",
        "counts",
        "integrity_profile",
        "tool",
    }
    missing = sorted(required_top - set(document.keys()))
    unknown = sorted(set(document.keys()) - required_top)
    if missing or unknown:
        raise _CheckFailure(
            "manifest",
            EXIT_INTEGRITY,
            "MANIFEST_FIELDS_INVALID",
            f"manifest 字段不完整：缺少 {missing}，多出 {unknown}",
        )
    if document.get("bundle_format") != packager.BUNDLE_FORMAT_VERSION:
        raise _CheckFailure(
            "manifest",
            EXIT_INTEGRITY,
            "BUNDLE_FORMAT_UNSUPPORTED",
            f"只支持 bundle_format={packager.BUNDLE_FORMAT_VERSION}",
            field_path="bundle_format",
        )
    if not isinstance(document.get("created_at"), str) or _UTC_RE.match(str(document["created_at"])) is None:
        raise _CheckFailure("manifest", EXIT_INTEGRITY, "MANIFEST_CREATED_AT_INVALID", "created_at 必须是 UTC")

    # 3. manifest 自描述：不得自哈希、路径固定。
    descriptor = document.get("manifest")
    if not isinstance(descriptor, Mapping):
        raise _CheckFailure("manifest", EXIT_INTEGRITY, "MANIFEST_SELF_DESCRIPTOR_INVALID", "manifest 段必须是 object")
    if descriptor.get("path") != packager.MANIFEST_NAME or descriptor.get("self_hashed") is not False:
        raise _CheckFailure(
            "manifest",
            EXIT_INTEGRITY,
            "MANIFEST_SELF_HASHED",
            "manifest 不得哈希自身",
            field_path="manifest",
        )

    # 4. files 列表：必需角色齐全、无重复、无 manifest 自身。
    required_roles = [
        spec.role for spec in packager.REQUIRED_BUNDLE_FILES if spec.role != "bundle_manifest"
    ]
    optional_roles = [spec.role for spec in packager.OPTIONAL_BUNDLE_FILES]
    raw_files = document.get("files")
    if not isinstance(raw_files, list):
        raise _CheckFailure("manifest", EXIT_INTEGRITY, "MANIFEST_FILES_INVALID", "files 必须是数组")
    entries: dict[str, Mapping[str, object]] = {}
    for index, entry in enumerate(raw_files):
        if not isinstance(entry, Mapping):
            raise _CheckFailure("manifest", EXIT_INTEGRITY, "MANIFEST_FILE_ENTRY_INVALID", "files 元素必须是 object")
        expected_keys = {"role", "path", "sha256", "size", "media_type", "required"}
        if set(entry.keys()) != expected_keys:
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_FILE_ENTRY_INVALID",
                f"文件条目字段必须是 {sorted(expected_keys)}",
                field_path=f"files[{index}]",
            )
        role = entry["role"]
        if not isinstance(role, str) or role in entries:
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_ROLE_DUPLICATED",
                f"role 非法或重复：{role!r}",
                field_path=f"files[{index}].role",
            )
        if role == "bundle_manifest":
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_SELF_HASHED",
                "files 不得包含 bundle_manifest 自身",
                field_path=f"files[{index}].role",
            )
        if role not in required_roles and role not in optional_roles:
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_ROLE_UNKNOWN",
                f"未知包文件角色：{role!r}",
                field_path=f"files[{index}].role",
            )
        if not isinstance(entry["sha256"], str) or _HASH64_RE.match(entry["sha256"]) is None:
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_FILE_HASH_INVALID",
                "sha256 必须是 64 位小写十六进制",
                field_path=f"files[{index}].sha256",
            )
        if isinstance(entry["size"], bool) or not isinstance(entry["size"], int) or entry["size"] < 0:
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_FILE_SIZE_INVALID",
                "size 必须是非负 integer",
                field_path=f"files[{index}].size",
            )
        if not isinstance(entry["required"], bool):
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_FILE_REQUIRED_INVALID",
                "required 必须是 boolean",
                field_path=f"files[{index}].required",
            )
        entries[role] = entry

    if set(entries.keys()) - set(required_roles) - set(optional_roles):
        raise _CheckFailure("manifest", EXIT_INTEGRITY, "MANIFEST_ROLE_UNKNOWN", "存在未知角色")
    missing_required = sorted(set(required_roles) - set(entries.keys()))
    if missing_required:
        raise _CheckFailure(
            "manifest",
            EXIT_INTEGRITY,
            "REQUIRED_FILE_MISSING",
            f"manifest 缺少必需文件条目：{missing_required}",
            detail={"missing_roles": missing_required},
        )
    state.entries = entries

    # 5. 路径必须与规格一致；禁止调用方自定义路径。
    specs = {spec.role: spec for spec in (*packager.REQUIRED_BUNDLE_FILES, *packager.OPTIONAL_BUNDLE_FILES)}
    for role, entry in entries.items():
        spec = specs[role]
        # 5.1 先做路径安全校验：`../`/绝对路径必须在“路径相等”之前以 PATH_TRAVERSAL 拒绝。
        if not isinstance(entry["path"], str):
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_FILE_ENTRY_INVALID",
                f"{role} 的 path 必须是 string",
                field_path=f"files[{role}].path",
            )
        _assert_relative_path(entry["path"], check="manifest")
        if entry["path"] != spec.path:
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_PATH_MISMATCH",
                f"{role} 路径应为 {spec.path!r}，实际 {entry['path']!r}",
                field_path=f"files[{role}].path",
            )
        if entry["required"] is not spec.required:
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_REQUIRED_FLAG_MISMATCH",
                f"{role} 的 required 标记与规格不一致",
                field_path=f"files[{role}].required",
            )

    # 6. optional 状态：缺失必须标 absent，存在必须与 files 一致。
    optional = document.get("optional")
    if not isinstance(optional, Mapping) or set(optional.keys()) != set(optional_roles):
        raise _CheckFailure("manifest", EXIT_INTEGRITY, "MANIFEST_OPTIONAL_INVALID", "optional 必须覆盖两个可选角色")
    for role in optional_roles:
        status = optional[role]
        if not isinstance(status, Mapping) or status.get("status") not in {"present", "absent"}:
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_OPTIONAL_STATUS_INVALID",
                f"{role} 的 status 必须是 present/absent",
                field_path=f"optional.{role}",
            )
        if status["status"] == "present" and role not in entries:
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_OPTIONAL_MISMATCH",
                f"{role} 标 present 但 files 无条目",
                field_path=f"optional.{role}",
            )
        if status["status"] == "absent" and role in entries:
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_OPTIONAL_MISMATCH",
                f"{role} 标 absent 但 files 有条目",
                field_path=f"optional.{role}",
            )
        if status["status"] == "absent" and not status.get("reason"):
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_OPTIONAL_REASON_MISSING",
                f"{role} 标 absent 必须写 reason",
                field_path=f"optional.{role}",
            )

    # 7. 计数自洽；12 类必需、11 个被哈希。
    counts = document.get("counts")
    if not isinstance(counts, Mapping):
        raise _CheckFailure("manifest", EXIT_INTEGRITY, "MANIFEST_COUNTS_INVALID", "counts 必须是 object")
    expected_counts = {
        "required_classes": 12,
        "required_present": 12,
        "required_hashed": 11,
        "hashed_in_manifest": len(entries),
    }
    for key, expected in expected_counts.items():
        if counts.get(key) != expected:
            raise _CheckFailure(
                "manifest",
                EXIT_INTEGRITY,
                "MANIFEST_COUNTS_MISMATCH",
                f"counts.{key} 应为 {expected}，实际 {counts.get(key)!r}",
                field_path=f"counts.{key}",
            )

    # 8. 完整性 profile 必须与验签器实现一致；未知 profile 不猜测。
    profile = document.get("integrity_profile")
    if not isinstance(profile, Mapping):
        raise _CheckFailure("manifest", EXIT_INTEGRITY, "INTEGRITY_PROFILE_INVALID", "integrity_profile 必须是 object")
    if profile.get("jcs") != "RFC8785" or profile.get("merkle") != "RFC9162":
        raise _CheckFailure(
            "manifest",
            EXIT_INTEGRITY,
            "INTEGRITY_PROFILE_UNSUPPORTED",
            "只支持 JCS RFC8785 + Merkle RFC9162",
            field_path="integrity_profile",
        )
    if "RF-EVIDENCE-CHAIN" not in str(profile.get("chain_preimage", "")):
        raise _CheckFailure(
            "manifest",
            EXIT_INTEGRITY,
            "CHAIN_PREIMAGE_UNSUPPORTED",
            "不支持的 chain_hash 前像 profile",
            field_path="integrity_profile.chain_preimage",
        )

    # 9. tool 段与 verify_bundle.py 文件哈希交叉核对（实际哈希在 inventory 阶段算）。
    tool = document.get("tool")
    if not isinstance(tool, Mapping) or tool.get("name") != "verify_bundle.py":
        raise _CheckFailure("manifest", EXIT_INTEGRITY, "TOOL_DESCRIPTOR_INVALID", "tool 段必须描述 verify_bundle.py")
    if tool.get("bundle_format") != document.get("bundle_format"):
        raise _CheckFailure(
            "manifest",
            EXIT_INTEGRITY,
            "TOOL_FORMAT_MISMATCH",
            "tool.bundle_format 与 bundle_format 不一致",
            field_path="tool.bundle_format",
        )

    state.pass_check("manifest", {"manifest_sha256": state.manifest_sha256})


# ---------------------------------------------------------------------------
# 5. 文件清单与哈希
# ---------------------------------------------------------------------------
def _phase_inventory(state: _State) -> None:
    """逐文件检查存在性/路径/哈希/size，并拒绝任何多出文件。"""
    # 1. 解析每个条目的相对路径；构建 path 映射。
    for role, entry in state.entries.items():
        relative = _assert_relative_path(str(entry["path"]))
        # 1.1 先看未解析路径本身是否是符号链接；再 resolve，避免“指向包外”先报 PATH_ESCAPE。
        candidate = state.root / relative
        if candidate.is_symlink():
            raise _CheckFailure(
                "inventory",
                EXIT_INTEGRITY,
                "SYMLINK_FORBIDDEN",
                f"包内文件不得是符号链接：{role}",
                field_path=role,
            )
        path = _resolve_inside(state.root, relative)
        state.paths[role] = path

    # 2. 必需文件必须存在；可选 absent 必须不存在。
    for role in state.entries:
        path = state.paths[role]
        if path.is_symlink():
            raise _CheckFailure(
                "inventory",
                EXIT_INTEGRITY,
                "SYMLINK_FORBIDDEN",
                f"包内文件不得是符号链接：{role}",
                field_path=role,
            )
        if not path.exists() or not path.is_file():
            raise _CheckFailure(
                "inventory",
                EXIT_INTEGRITY,
                "REQUIRED_FILE_MISSING",
                f"必需文件不存在：{role}",
                field_path=role,
            )

    # 3. 可选 absent：路径不得存在；存在即“多出文件”。
    for spec in packager.OPTIONAL_BUNDLE_FILES:
        if spec.role in state.entries:
            continue
        if (state.root / spec.path).exists():
            raise _CheckFailure(
                "inventory",
                EXIT_INTEGRITY,
                "OPTIONAL_FILE_UNEXPECTED",
                f"{spec.role} 标 absent 但文件存在",
                field_path=spec.path,
            )

    # 4. 逐文件哈希/size。
    for role, entry in state.entries.items():
        path = state.paths[role]
        actual_size, actual_hash = _hash_file(path, max_bytes=MAX_EVIDENCE_BYTES)
        if actual_size != entry["size"]:
            raise _CheckFailure(
                "inventory",
                EXIT_INTEGRITY,
                "FILE_SIZE_MISMATCH",
                f"{role} 大小不符",
                field_path=role,
                detail={"expected": entry["size"], "actual": actual_size},
            )
        if actual_hash != entry["sha256"]:
            raise _CheckFailure(
                "inventory",
                EXIT_INTEGRITY,
                "FILE_HASH_MISMATCH",
                f"{role} sha256 不符",
                field_path=role,
                detail={"expected": entry["sha256"], "actual": actual_hash},
            )

    # 4.1 tool.sha256 必须与包内 verify_bundle.py 的实际哈希一致；否则清单自述不可信。
    tool_descriptor = state.manifest.get("tool")
    if not isinstance(tool_descriptor, Mapping) or tool_descriptor.get("sha256") != state.entries["verify_bundle"]["sha256"]:
        raise _CheckFailure(
            "inventory",
            EXIT_INTEGRITY,
            "TOOL_HASH_MISMATCH",
            "manifest.tool.sha256 与包内 verify_bundle.py 不符",
            field_path="tool.sha256",
        )

    # 5. 无多出文件：遍历包根，只允许 manifest + 条目路径；目录可以存在但不得藏文件。
    allowed = {packager.MANIFEST_NAME} | {str(entry["path"]) for entry in state.entries.values()}
    for relative in _iter_files(state.root):
        if relative not in allowed:
            raise _CheckFailure(
                "inventory",
                EXIT_INTEGRITY,
                "EXTRA_FILE",
                f"包内出现清单外文件：{relative}",
                field_path=relative,
            )

    # 6. 包内指纹声明不得夹带公钥/私钥（信任只能来自包外）。
    try:
        trust_store.assert_bundle_does_not_supply_trust(state.root)
    except trust_store.TrustAnchorError as exc:
        raise _CheckFailure(
            "trust",
            EXIT_TRUST,
            exc.reason,
            str(exc),
            field_path=exc.field_path,
        ) from exc

    state.pass_check("inventory", {"files": len(state.paths)})


# ---------------------------------------------------------------------------
# 6. 内容解析
# ---------------------------------------------------------------------------
def _phase_parse(state: _State) -> None:
    """严格解析 JSON/JSONL，校验 payload 白名单与证据 payload 哈希。"""
    # 1. 结构化 JSON 文件。
    for role in (
        "task_spec",
        "graph",
        "artifact_manifest",
        "split_manifest",
        "verification_report",
        "completion_certificate",
        "merkle_proofs",
        "trusted_key_fingerprint",
    ):
        state.objects[role] = _read_json(state.paths[role], state.root, max_bytes=MAX_JSON_BYTES, role=role)

    # 1.1 结构化对象不得夹带显式私钥/私钥种子/PEM；seed 是合法随机种子，不在此列。
    for role in ("task_spec", "graph", "artifact_manifest", "split_manifest", "merkle_proofs"):
        _assert_no_forbidden_material(state.objects[role], role)

    # 2. Report/Certificate 走 M11 白名单 shape；未知字段在这里拒绝（4）。
    report = _as_mapping(state.objects["verification_report"], "verification_report")
    certificate = _as_mapping(state.objects["completion_certificate"], "completion_certificate")
    state.report_payload = payloads.build_payload(payloads.PayloadKind.REPORT, report)
    state.certificate_payload = payloads.build_payload(payloads.PayloadKind.CERTIFICATE, certificate)

    # 3. evidence.jsonl：逐行 envelope；不得有空行/重复 ID/重复 seq。
    evidence_path = state.paths["evidence"]
    raw = _read_bytes(evidence_path, state.root, max_bytes=MAX_EVIDENCE_BYTES)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _CheckFailure("parse", EXIT_INTEGRITY, "EVIDENCE_NOT_UTF8", "evidence.jsonl 不是 UTF-8") from exc
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        raise _CheckFailure("parse", EXIT_INTEGRITY, "EVIDENCE_EMPTY", "evidence.jsonl 不得为空")
    seen_ids: set[str] = set()
    seen_seq: set[int] = set()
    for index, line in enumerate(lines):
        try:
            envelope = jcs.parse_strict(line)
        except jcs.JcsError as exc:
            raise _CheckFailure(
                "parse",
                EXIT_INTEGRITY,
                "EVIDENCE_JSON_INVALID",
                f"第 {index + 1} 行不是合法 JSON：{exc.reason}",
                field_path=f"evidence[{index}]",
            ) from exc
        if not isinstance(envelope, Mapping) or set(envelope.keys()) != {"record", "payload"}:
            raise _CheckFailure(
                "parse",
                EXIT_INTEGRITY,
                "EVIDENCE_ENVELOPE_INVALID",
                "每行必须是 {record, payload}",
                field_path=f"evidence[{index}]",
            )
        record = _validate_evidence_record(envelope["record"], index)
        payload = _as_mapping(envelope["payload"], f"evidence[{index}].payload")
        # 证据 record 与 payload 都不得含显式私钥材料；seed 是合法随机种子。
        _assert_no_forbidden_material(record, f"evidence[{index}].record")
        _assert_no_forbidden_material(payload, f"evidence[{index}].payload")
        actual_hash = hashlib.sha256(jcs.canonicalize(dict(payload))).hexdigest()
        if record["payload_hash"] != actual_hash:
            raise _CheckFailure(
                "parse",
                EXIT_INTEGRITY,
                "EVIDENCE_PAYLOAD_HASH_MISMATCH",
                f"证据 {index + 1} 的 payload_hash 与内联 payload 不符",
                field_path=f"evidence[{index}].record.payload_hash",
                detail={"expected": record["payload_hash"], "actual": actual_hash},
            )
        evidence_id = str(record["evidence_id"])
        event_seq = int(record["event_seq"])
        if evidence_id in seen_ids:
            raise _CheckFailure("parse", EXIT_INTEGRITY, "EVIDENCE_ID_DUPLICATED", f"evidence_id 重复：{evidence_id}")
        if event_seq in seen_seq:
            raise _CheckFailure("parse", EXIT_INTEGRITY, "EVIDENCE_SEQ_DUPLICATED", f"event_seq 重复：{event_seq}")
        seen_ids.add(evidence_id)
        seen_seq.add(event_seq)
        state.evidence.append({"record": record, "payload": payload})

    # 4. split_manifest 六字段 + manifest_hash。
    _validate_split_manifest(_as_mapping(state.objects["split_manifest"], "split_manifest"))

    # 5. merkle_proofs 结构。
    _validate_merkle_proofs(_as_mapping(state.objects["merkle_proofs"], "merkle_proofs"))

    # 6. 指纹声明结构（claims_only，无公钥）。
    _validate_trust_claims(_as_mapping(state.objects["trusted_key_fingerprint"], "trusted_key_fingerprint"))

    state.pass_check("parse", {"evidence_records": len(state.evidence)})


# ---------------------------------------------------------------------------
# 7. 链与根
# ---------------------------------------------------------------------------
def _phase_roots(state: _State) -> None:
    """重算 event_seq/prev 链、chain_hash、Merkle 根、tree_size、规则版本与划分哈希。"""
    # 1. event_seq 必须从 1 连续；顺序即文件顺序（不排序）。
    records = [envelope["record"] for envelope in state.evidence]
    for index, record in enumerate(records):
        expected_seq = index + 1
        if record["event_seq"] != expected_seq:
            raise _CheckFailure(
                "roots",
                EXIT_ROOT,
                "EVENT_SEQ_GAP",
                f"event_seq 应为 {expected_seq}，实际 {record['event_seq']}",
                field_path=f"evidence[{index}].event_seq",
            )

    # 2. prev_hash 链：首条只校形态；后续必须等于上一条 chain_hash。
    for index, record in enumerate(records):
        if index == 0:
            continue
        previous = records[index - 1]
        if record["prev_hash"] != previous["chain_hash"]:
            raise _CheckFailure(
                "roots",
                EXIT_ROOT,
                "EVIDENCE_CHAIN_BROKEN",
                f"第 {index + 1} 条 prev_hash 不等于上一条 chain_hash",
                field_path=f"evidence[{index}].prev_hash",
            )

    # 3. chain_hash 重算；前像按 P4 提案（未冻结，OQ-P4-02）。
    for index, record in enumerate(records):
        expected = _compute_chain_hash(record)
        if record["chain_hash"] != expected:
            raise _CheckFailure(
                "roots",
                EXIT_ROOT,
                "EVIDENCE_CHAIN_HASH_MISMATCH",
                f"第 {index + 1} 条 chain_hash 重算不符",
                field_path=f"evidence[{index}].chain_hash",
                detail={"expected": expected, "actual": record["chain_hash"]},
            )

    # 4. Merkle 根（RFC 9162；叶 = chain_hash 32 字节）。
    computed_root = _compute_merkle_root([str(record["chain_hash"]) for record in records])
    report = _as_mapping(state.objects["verification_report"], "verification_report")
    certificate = _as_mapping(state.objects["completion_certificate"], "completion_certificate")
    proofs = _as_mapping(state.objects["merkle_proofs"], "merkle_proofs")

    if report.get("evidence_root") != computed_root:
        raise _CheckFailure(
            "roots",
            EXIT_ROOT,
            "EVIDENCE_ROOT_MISMATCH",
            "报告 evidence_root 与证据 Merkle 根不符",
            field_path="verification_report.evidence_root",
            detail={"expected": computed_root, "actual": report.get("evidence_root")},
        )
    if certificate.get("merkle_root") != computed_root:
        raise _CheckFailure(
            "roots",
            EXIT_ROOT,
            "CERT_MERKLE_ROOT_MISMATCH",
            "证书 merkle_root 与证据 Merkle 根不符",
            field_path="completion_certificate.merkle_root",
            detail={"expected": computed_root, "actual": certificate.get("merkle_root")},
        )
    if proofs.get("root") != computed_root:
        raise _CheckFailure(
            "roots",
            EXIT_ROOT,
            "PROOF_ROOT_MISMATCH",
            "merkle_proofs.root 与证据 Merkle 根不符",
            field_path="merkle_proofs.root",
        )

    # 5. tree_size 必须等于证据条数。
    tree_size = len(records)
    if certificate.get("tree_size") != tree_size:
        raise _CheckFailure(
            "roots",
            EXIT_ROOT,
            "TREE_SIZE_MISMATCH",
            "证书 tree_size 与证据条数不符",
            field_path="completion_certificate.tree_size",
            detail={"expected": tree_size, "actual": certificate.get("tree_size")},
        )
    if proofs.get("tree_size") != tree_size:
        raise _CheckFailure(
            "roots",
            EXIT_ROOT,
            "PROOF_TREE_SIZE_MISMATCH",
            "merkle_proofs.tree_size 与证据条数不符",
            field_path="merkle_proofs.tree_size",
        )

    # 6. 规则版本三方一致：task_spec / report / certificate。
    task_spec = _as_mapping(state.objects["task_spec"], "task_spec")
    task_ruleset = task_spec.get("ruleset_hash")
    if not isinstance(task_ruleset, str) or _HASH64_RE.match(task_ruleset) is None:
        raise _CheckFailure(
            "roots",
            EXIT_ROOT,
            "TASK_RULESET_HASH_INVALID",
            "task_spec.ruleset_hash 必须是 64 位小写十六进制",
            field_path="task_spec.ruleset_hash",
        )
    ruleset_values = {
        "task_spec.ruleset_hash": task_ruleset,
        "verification_report.ruleset_hash": report.get("ruleset_hash"),
        "completion_certificate.ruleset_hash": certificate.get("ruleset_hash"),
    }
    if len(set(ruleset_values.values())) != 1:
        raise _CheckFailure(
            "roots",
            EXIT_ROOT,
            "RULESET_HASH_MISMATCH",
            f"规则版本不一致：{ruleset_values}",
            field_path="ruleset_hash",
        )

    # 7. split_manifest 内部 manifest_hash 重算。
    split = _as_mapping(state.objects["split_manifest"], "split_manifest")
    recomputed_split_hash = hashlib.sha256(
        jcs.canonicalize({field: split[field] for field in _SPLIT_FIELDS})
    ).hexdigest()
    if split.get("manifest_hash") != recomputed_split_hash:
        raise _CheckFailure(
            "roots",
            EXIT_ROOT,
            "SPLIT_MANIFEST_HASH_MISMATCH",
            "split_manifest.manifest_hash 重算不符",
            field_path="split_manifest.manifest_hash",
        )

    # 8. 逐条 inclusion proof；必须覆盖全部叶子。
    proofs_list = proofs.get("proofs")
    if not isinstance(proofs_list, list) or len(proofs_list) != tree_size:
        raise _CheckFailure(
            "roots",
            EXIT_ROOT,
            "INCLUSION_PROOFS_INCOMPLETE",
            "inclusion proof 必须覆盖全部证据",
            field_path="merkle_proofs.proofs",
        )
    for index, proof in enumerate(proofs_list):
        if not isinstance(proof, Mapping):
            raise _CheckFailure("roots", EXIT_ROOT, "INCLUSION_PROOF_INVALID", "proof 必须是 object")
        expected_leaf = _leaf_hash(str(records[index]["chain_hash"]))
        if proof.get("event_seq") != index + 1:
            raise _CheckFailure(
                "roots",
                EXIT_ROOT,
                "INCLUSION_PROOF_ORDER",
                "proof.event_seq 必须与证据顺序一致",
                field_path=f"merkle_proofs.proofs[{index}].event_seq",
            )
        if proof.get("leaf_hash") != expected_leaf:
            raise _CheckFailure(
                "roots",
                EXIT_ROOT,
                "INCLUSION_PROOF_LEAF_MISMATCH",
                "proof.leaf_hash 与 chain_hash 叶哈希不符",
                field_path=f"merkle_proofs.proofs[{index}].leaf_hash",
            )
        path = proof.get("audit_path")
        if not isinstance(path, list) or any(
            not isinstance(item, str) or _HASH64_RE.match(item) is None for item in path
        ):
            raise _CheckFailure(
                "roots",
                EXIT_ROOT,
                "INCLUSION_PROOF_INVALID",
                "audit_path 必须是 hash64 数组",
                field_path=f"merkle_proofs.proofs[{index}].audit_path",
            )
        if not _verify_inclusion(index, tree_size, expected_leaf, path, computed_root):
            raise _CheckFailure(
                "roots",
                EXIT_ROOT,
                "INCLUSION_PROOF_INVALID",
                "inclusion proof 无法还原到 Merkle 根",
                field_path=f"merkle_proofs.proofs[{index}]",
            )

    state.pass_check(
        "roots",
        {
            "evidence_root": computed_root,
            "tree_size": tree_size,
            "ruleset_hash": report.get("ruleset_hash"),
        },
    )


# ---------------------------------------------------------------------------
# 8. 签名
# ---------------------------------------------------------------------------
def _phase_signatures(state: _State) -> None:
    """用包外信任锚验 Report/Certificate 签名，并交叉核对包内指纹声明。"""
    # 1. 前置对象。
    assert state.trust is not None
    assert state.report_payload is not None
    assert state.certificate_payload is not None
    report_body = state.report_payload.body
    cert_body = state.certificate_payload.body

    # 2. 证书算法固定 Ed25519；先拒绝，避免用错原语。
    if cert_body["alg"] != "Ed25519":
        raise _CheckFailure(
            "signature",
            EXIT_SIGNATURE,
            "ALGORITHM_NOT_ED25519",
            f"证书 alg={cert_body['alg']!r}，只接受 Ed25519",
            field_path="completion_certificate.alg",
        )

    # 3. Report：key_id 必须命中包外信任锚；报告没有 key_fingerprint，按 key_id 解析。
    report_key = state.trust.lookup(
        str(report_body["key_id"]),
        None,
        str(report_body["issued_at"]),
        purpose="signing",
    )
    report_signature = _as_string(state.objects["verification_report"], "verification_report", "signature")
    report_result = ed25519_signer.verify(
        state.report_payload,
        report_signature,
        report_key.public_key_b64,
        expected_key_id=report_key.key_id,
    )
    if not report_result.ok:
        raise _CheckFailure(
            "signature",
            EXIT_SIGNATURE,
            report_result.reason or "SIGNATURE_MISMATCH",
            "报告签名验证失败",
            field_path="verification_report.signature",
        )

    # 4. Certificate：key_id + key_fingerprint 都必须命中同一把包外 key。
    cert_key = state.trust.lookup(
        str(cert_body["key_id"]),
        str(cert_body["key_fingerprint"]),
        str(cert_body["issued_at"]),
        purpose="signing",
    )
    cert_signature = _as_string(state.objects["completion_certificate"], "completion_certificate", "signature")
    cert_result = ed25519_signer.verify(
        state.certificate_payload,
        cert_signature,
        cert_key.public_key_b64,
        expected_key_id=cert_key.key_id,
    )
    if not cert_result.ok:
        raise _CheckFailure(
            "signature",
            EXIT_SIGNATURE,
            cert_result.reason or "SIGNATURE_MISMATCH",
            "证书签名验证失败",
            field_path="completion_certificate.signature",
        )

    # 5. 包内指纹声明必须与信任锚一致；声明的指纹不是信任来源，只是被核对的对象。
    claims = _claim_map(_as_mapping(state.objects["trusted_key_fingerprint"], "trusted_key_fingerprint"))
    report_claim = claims.get(str(report_body["key_id"]))
    cert_claim = claims.get(str(cert_body["key_id"]))
    if report_claim != report_key.fingerprint_sha256:
        raise _CheckFailure(
            "signature",
            EXIT_SIGNATURE,
            "TRUSTED_FINGERPRINT_CLAIM_MISMATCH",
            "包内声明的报告 key 指纹与信任锚不一致",
            field_path="trusted_key_fingerprint",
        )
    if cert_claim != cert_key.fingerprint_sha256 or cert_claim != cert_body["key_fingerprint"]:
        raise _CheckFailure(
            "signature",
            EXIT_SIGNATURE,
            "TRUSTED_FINGERPRINT_CLAIM_MISMATCH",
            "包内声明的证书 key 指纹与信任锚/证书不一致",
            field_path="trusted_key_fingerprint",
        )

    state.pass_check(
        "signature",
        {
            "report_key_id": report_key.key_id,
            "cert_key_id": cert_key.key_id,
            "report_fingerprint": report_key.fingerprint_sha256,
            "cert_fingerprint": cert_key.fingerprint_sha256,
        },
    )


# ---------------------------------------------------------------------------
# 9. 策略
# ---------------------------------------------------------------------------
def _phase_policy(state: _State) -> None:
    """检查 VERIFIED、ID 一致、覆盖算术、时间顺序、T0 无 SPA。"""
    report = _as_mapping(state.objects["verification_report"], "verification_report")
    certificate = _as_mapping(state.objects["completion_certificate"], "completion_certificate")
    task_spec = _as_mapping(state.objects["task_spec"], "task_spec")

    # 1. 仅 VERIFIED 可作为完成凭证。
    if report.get("final_state") != "VERIFIED":
        raise _CheckFailure(
            "policy",
            EXIT_POLICY,
            "REPORT_NOT_VERIFIED",
            f"报告 final_state={report.get('final_state')!r}，不是 VERIFIED",
            field_path="verification_report.final_state",
        )
    if certificate.get("final_state") != "VERIFIED":
        raise _CheckFailure(
            "policy",
            EXIT_POLICY,
            "CERT_NOT_VERIFIED",
            "证书 final_state 不是 VERIFIED",
            field_path="completion_certificate.final_state",
        )

    # 2. ID 贯穿：证书→报告→任务→证据。
    if certificate.get("report_id") != report.get("report_id"):
        raise _CheckFailure(
            "policy",
            EXIT_POLICY,
            "CERT_REPORT_ID_MISMATCH",
            "证书 report_id 与报告不一致",
            field_path="completion_certificate.report_id",
        )
    if report.get("task_id") != task_spec.get("task_id"):
        raise _CheckFailure(
            "policy",
            EXIT_POLICY,
            "REPORT_TASK_ID_MISMATCH",
            "报告 task_id 与 task_spec 不一致",
            field_path="verification_report.task_id",
        )
    for index, envelope in enumerate(state.evidence):
        if envelope["record"]["task_id"] != report.get("task_id"):
            raise _CheckFailure(
                "policy",
                EXIT_POLICY,
                "EVIDENCE_TASK_ID_MISMATCH",
                f"第 {index + 1} 条证据 task_id 与报告不一致",
                field_path=f"evidence[{index}].record.task_id",
            )

    # 3. 覆盖计数算术与 VERIFIED 完整性（SEM-VR-01/02；不重跑 Gate）。
    coverage = report.get("required_check_coverage")
    if not isinstance(coverage, Mapping):
        raise _CheckFailure("policy", EXIT_POLICY, "COVERAGE_MISSING", "报告缺少 coverage")
    required = coverage.get("required")
    passed = coverage.get("passed")
    missing = coverage.get("missing")
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (required, passed, missing)):
        raise _CheckFailure("policy", EXIT_POLICY, "COVERAGE_SHAPE_INVALID", "coverage 计数必须是 integer")
    if passed > required or missing != required - passed:
        raise _CheckFailure(
            "policy",
            EXIT_POLICY,
            "COVERAGE_ARITHMETIC_INVALID",
            "coverage 算术不成立（passed<=required 且 missing=required-passed）",
            field_path="verification_report.required_check_coverage",
        )
    if missing != 0 or passed != required:
        raise _CheckFailure(
            "policy",
            EXIT_POLICY,
            "COVERAGE_INCOMPLETE",
            "VERIFIED 报告不得有必检缺口",
            field_path="verification_report.required_check_coverage",
        )

    # 4. 报告/证书跨文档数值一致。
    if certificate.get("l3_coverage") != report.get("l3_coverage"):
        raise _CheckFailure(
            "policy",
            EXIT_POLICY,
            "L3_COVERAGE_MISMATCH",
            "证书 l3_coverage 与报告不一致",
            field_path="completion_certificate.l3_coverage",
        )

    # 5. T0 无 SPA；skipped_nodes 必须为空。
    if certificate.get("skipped_nodes") != []:
        raise _CheckFailure(
            "policy",
            EXIT_POLICY,
            "SPA_NOT_ALLOWED_T0",
            "T0 不允许 SPA，skipped_nodes 必须为空数组",
            field_path="completion_certificate.skipped_nodes",
        )

    # 6. 时间顺序：证据时间 ≤ 报告签发 ≤ 证书签发。
    report_issued = payloads.parse_rfc3339_utc(str(report.get("issued_at")), field_path="issued_at")
    cert_issued = payloads.parse_rfc3339_utc(str(certificate.get("issued_at")), field_path="issued_at")
    if cert_issued < report_issued:
        raise _CheckFailure(
            "policy",
            EXIT_POLICY,
            "CERT_ISSUED_BEFORE_REPORT",
            "证书签发时间早于报告",
            field_path="completion_certificate.issued_at",
        )
    latest_evidence = max(
        payloads.parse_rfc3339_utc(str(envelope["record"]["timestamp"]), field_path="timestamp")
        for envelope in state.evidence
    )
    if report_issued < latest_evidence:
        raise _CheckFailure(
            "policy",
            EXIT_POLICY,
            "REPORT_ISSUED_BEFORE_EVIDENCE",
            "报告签发时间早于最后一条证据",
            field_path="verification_report.issued_at",
        )

    state.pass_check("policy")


# ---------------------------------------------------------------------------
# 10. 锚定
# ---------------------------------------------------------------------------
def _phase_anchor(state: _State) -> None:
    """AnchorProof 缺失=ABSENT（不失败）；存在则用包外 anchor key 验签。"""
    # 1. manifest 已校验过 optional 结构。
    optional = _as_mapping(state.manifest["optional"], "optional")
    status = _as_mapping(optional["anchor_proof"], "optional.anchor_proof")
    if status.get("status") == "absent":
        state.pass_check("anchor", {"anchor": "ABSENT", "reason": status.get("reason")})
        return

    # 2. present：文件必须在清单与路径中。
    if "anchor_proof" not in state.paths:
        raise _CheckFailure("anchor", EXIT_ANCHOR, "ANCHOR_FILE_MISSING", "manifest 标 present 但无文件")
    anchor = _as_mapping(
        _read_json(state.paths["anchor_proof"], state.root, max_bytes=MAX_JSON_BYTES, role="anchor_proof"),
        "anchor_proof",
    )

    # 3. 字段/类型。
    if set(anchor.keys()) != set(packager.ANCHOR_PROOF_FIELDS):
        raise _CheckFailure(
            "anchor",
            EXIT_ANCHOR,
            "ANCHOR_FIELDS_INVALID",
            "AnchorProof 字段集合不符合 7.4",
            field_path="anchor_proof",
        )
    certificate = _as_mapping(state.objects["completion_certificate"], "completion_certificate")
    cert_file_hash = hashlib.sha256(state.paths["completion_certificate"].read_bytes()).hexdigest()
    if anchor.get("certificate_hash") != cert_file_hash:
        raise _CheckFailure(
            "anchor",
            EXIT_ANCHOR,
            "ANCHOR_CERT_HASH_MISMATCH",
            "anchor.certificate_hash 与证书文件哈希不符",
            field_path="anchor_proof.certificate_hash",
        )
    if anchor.get("merkle_root") != certificate.get("merkle_root"):
        raise _CheckFailure(
            "anchor",
            EXIT_ANCHOR,
            "ANCHOR_MERKLE_ROOT_MISMATCH",
            "anchor.merkle_root 与证书不一致",
            field_path="anchor_proof.merkle_root",
        )
    if anchor.get("tree_size") != certificate.get("tree_size"):
        raise _CheckFailure(
            "anchor",
            EXIT_ANCHOR,
            "ANCHOR_TREE_SIZE_MISMATCH",
            "anchor.tree_size 与证书不一致",
            field_path="anchor_proof.tree_size",
        )
    if not isinstance(anchor.get("timestamp"), str) or _UTC_RE.match(str(anchor["timestamp"])) is None:
        raise _CheckFailure("anchor", EXIT_ANCHOR, "ANCHOR_TIMESTAMP_INVALID", "anchor.timestamp 必须是 UTC")
    if not isinstance(anchor.get("anchor_type"), str) or not anchor["anchor_type"]:
        raise _CheckFailure("anchor", EXIT_ANCHOR, "ANCHOR_TYPE_INVALID", "anchor_type 必须非空")
    if not isinstance(anchor.get("receipt"), (str, Mapping)):
        raise _CheckFailure("anchor", EXIT_ANCHOR, "ANCHOR_RECEIPT_INVALID", "receipt 必须是 string/object")

    # 4. 用包外 anchor key 验 `domain_prefix || JCS(除 proof_signature 外的字段)`。
    assert state.trust is not None
    anchor_key = state.trust.resolve_anchor_key()
    proof_signature = anchor.get("proof_signature")
    if not isinstance(proof_signature, str) or not proof_signature:
        raise _CheckFailure("anchor", EXIT_ANCHOR, "ANCHOR_SIGNATURE_MISSING", "proof_signature 必须非空")
    message = ANCHOR_DOMAIN + jcs.canonicalize(
        {field: anchor[field] for field in packager.ANCHOR_PROOF_FIELDS if field != "proof_signature"}
    )
    try:
        raw_signature = _decode_b64(proof_signature, "ANCHOR_SIGNATURE_BASE64_INVALID")
        raw_public = ed25519_signer.decode_public_key(anchor_key.public_key_b64)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(raw_public)
        public_key.verify(raw_signature, message)
    except _CheckFailure:
        raise
    except Exception as exc:
        raise _CheckFailure(
            "anchor",
            EXIT_ANCHOR,
            "ANCHOR_SIGNATURE_INVALID",
            f"AnchorProof 验签失败（{type(exc).__name__}）",
            field_path="anchor_proof.proof_signature",
        ) from exc

    state.pass_check("anchor", {"anchor": "PRESENT", "anchor_key_id": anchor_key.key_id})


# ---------------------------------------------------------------------------
# 11. 校验辅助
# ---------------------------------------------------------------------------
def _read_bytes(path: Path, root: Path, *, max_bytes: int) -> bytes:
    """读取包内文件：非符号链接、路径在根内、大小受限。"""
    # 1. 路径与符号链接。
    _assert_within_root(path, root)
    if path.is_symlink():
        raise _CheckFailure("read", EXIT_INTEGRITY, "SYMLINK_FORBIDDEN", f"不得读取符号链接：{path.name}")
    # 2. 大小。
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise _CheckFailure("read", EXIT_INTEGRITY, "FILE_READ_FAILED", f"无法读取 {path.name}") from exc
    if size > max_bytes:
        raise _CheckFailure("read", EXIT_INTEGRITY, "FILE_TOO_LARGE", f"{path.name} 超过大小上限")
    # 3. 读取。
    return path.read_bytes()


def _read_json(path: Path, root: Path, *, max_bytes: int, role: str) -> object:
    """读取并严格解析 JSON；重复键/NaN/非法 Unicode 在 jcs 层拒绝。"""
    data = _read_bytes(path, root, max_bytes=max_bytes)
    try:
        return jcs.parse_strict(data)
    except jcs.JcsError as exc:
        raise _CheckFailure(
            "parse",
            EXIT_INTEGRITY,
            "JSON_INVALID",
            f"{role} 不是合法 JSON：{exc.reason}",
            field_path=role,
        ) from exc


def _hash_file(path: Path, *, max_bytes: int) -> tuple[int, str]:
    """流式计算文件 size + sha256；不把大文件整体读入内存。"""
    # 1. 大小预检。
    size = path.stat().st_size
    if size > max_bytes:
        raise _CheckFailure("inventory", EXIT_INTEGRITY, "FILE_TOO_LARGE", f"{path.name} 超过大小上限")
    # 2. 分块哈希。
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return size, digest.hexdigest()


def _assert_relative_path(path: str, *, check: str = "inventory") -> str:
    """拒绝绝对路径/盘符/UNC/反斜杠/`..`/空段；返回原 POSIX 相对路径。

    `check` 只影响失败结果的检查名（manifest/inventory），不改变拒绝原因。
    """
    if not path or path.startswith("/") or "\\" in path:
        raise _CheckFailure(check, EXIT_INTEGRITY, "PATH_INVALID", f"包内路径非法：{path!r}")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _CheckFailure(check, EXIT_INTEGRITY, "PATH_TRAVERSAL", f"包内路径不得含 . / .. / 空段：{path!r}")
    if ":" in parts[0]:
        raise _CheckFailure(check, EXIT_INTEGRITY, "PATH_ABSOLUTE", f"包内路径不得带盘符：{path!r}")
    return path


def _resolve_inside(root: Path, relative: str) -> Path:
    """把相对路径解析到包根内；realpath 不得逃逸。"""
    candidate = (root / relative).resolve(strict=False)
    _assert_within_root(candidate, root)
    return candidate


def _assert_within_root(path: Path, root: Path) -> None:
    """确认路径在包根内；跨卷直接拒绝。"""
    try:
        if os.path.commonpath([str(path.resolve(strict=False)), str(root)]) != str(root):
            raise _CheckFailure("inventory", EXIT_INTEGRITY, "PATH_ESCAPE", "包内路径逃逸到根之外")
    except ValueError as exc:
        raise _CheckFailure("inventory", EXIT_INTEGRITY, "PATH_ESCAPE", "包内路径与根不在同一卷") from exc


def _iter_files(root: Path) -> Sequence[str]:
    """遍历包内所有文件（相对 POSIX 路径）；拒绝符号链接目录。"""
    result: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for directory in dirnames:
            if (base / directory).is_symlink():
                raise _CheckFailure(
                    "inventory",
                    EXIT_INTEGRITY,
                    "SYMLINK_FORBIDDEN",
                    "包内不得含符号链接目录",
                    field_path=str((base / directory).relative_to(root)),
                )
        for filename in filenames:
            path = base / filename
            if path.is_symlink():
                raise _CheckFailure(
                    "inventory",
                    EXIT_INTEGRITY,
                    "SYMLINK_FORBIDDEN",
                    "包内不得含符号链接文件",
                    field_path=str(path.relative_to(root)),
                )
            result.append(path.relative_to(root).as_posix())
    return tuple(sorted(result))


def _as_mapping(value: object, role: str) -> Mapping[str, object]:
    """要求 object；否则以 4 退出。"""
    if not isinstance(value, Mapping):
        raise _CheckFailure("parse", EXIT_INTEGRITY, "OBJECT_REQUIRED", f"{role} 必须是 object", field_path=role)
    return value


def _as_string(document: object, role: str, field: str) -> str:
    """取 object 的字符串字段；缺失/类型错以 4 退出。"""
    mapping = _as_mapping(document, role)
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise _CheckFailure(
            "parse",
            EXIT_INTEGRITY,
            "STRING_FIELD_REQUIRED",
            f"{role}.{field} 必须是非空 string",
            field_path=f"{role}.{field}",
        )
    return value


def _assert_no_forbidden_material(value: object, path: str) -> None:
    """复用 packager 的显式私钥材料扫描；命中统一映射为解析阶段 4。"""
    try:
        packager.assert_no_forbidden_material(value, path)
    except packager.PackagerError as exc:
        raise _CheckFailure(
            "parse",
            EXIT_INTEGRITY,
            exc.reason,
            str(exc),
            field_path=exc.field_path,
        ) from exc


def _validate_evidence_record(value: object, index: int) -> Mapping[str, object]:
    """按冻结 EvidenceRecord 字段/枚举/等级-类型-写入者校验；未知字段拒绝。"""
    record = _as_mapping(value, f"evidence[{index}].record")
    unknown = sorted(set(record.keys()) - _RECORD_FIELDS)
    missing = sorted(_RECORD_REQUIRED - set(record.keys()))
    if unknown or missing:
        raise _CheckFailure(
            "parse",
            EXIT_INTEGRITY,
            "EVIDENCE_RECORD_FIELDS_INVALID",
            f"证据记录字段不完整：缺少 {missing}，多出 {unknown}",
            field_path=f"evidence[{index}].record",
        )
    if record.get("schema_version") != "1.0":
        raise _CheckFailure("parse", EXIT_INTEGRITY, "EVIDENCE_SCHEMA_VERSION", "证据 schema_version 必须是 1.0")
    for field, pattern in (
        ("evidence_id", _EVIDENCE_ID_RE),
        ("task_id", _TASK_ID_RE),
        ("node_id", _NODE_ID_RE),
        ("attempt_id", _ATTEMPT_ID_RE),
    ):
        if not isinstance(record.get(field), str) or pattern.match(str(record[field])) is None:
            raise _CheckFailure(
                "parse",
                EXIT_INTEGRITY,
                "EVIDENCE_RECORD_FIELD_INVALID",
                f"{field} 形态非法",
                field_path=f"evidence[{index}].record.{field}",
            )
    event_seq = record.get("event_seq")
    if isinstance(event_seq, bool) or not isinstance(event_seq, int) or event_seq < 1:
        raise _CheckFailure("parse", EXIT_INTEGRITY, "EVIDENCE_SEQ_INVALID", "event_seq 必须是 ≥1 integer")
    level = record.get("level")
    kind = record.get("kind")
    if level not in _LEVEL_KINDS or kind not in _LEVEL_KINDS[level]:
        raise _CheckFailure(
            "parse",
            EXIT_INTEGRITY,
            "EVIDENCE_LEVEL_KIND_INVALID",
            f"level/kind 组合非法：{level!r}/{kind!r}",
            field_path=f"evidence[{index}].record.level",
        )
    if record.get("producer") != _PRODUCER_BY_LEVEL[level]:
        raise _CheckFailure(
            "parse",
            EXIT_INTEGRITY,
            "EVIDENCE_PRODUCER_INVALID",
            "producer 与 level 不匹配",
            field_path=f"evidence[{index}].record.producer",
        )
    if not isinstance(record.get("timestamp"), str) or _UTC_RE.match(str(record["timestamp"])) is None:
        raise _CheckFailure("parse", EXIT_INTEGRITY, "EVIDENCE_TIMESTAMP_INVALID", "timestamp 必须是 UTC")
    for field in ("payload_hash", "prev_hash", "chain_hash"):
        if not isinstance(record.get(field), str) or _HASH64_RE.match(str(record[field])) is None:
            raise _CheckFailure(
                "parse",
                EXIT_INTEGRITY,
                "EVIDENCE_HASH_INVALID",
                f"{field} 必须是 hash64",
                field_path=f"evidence[{index}].record.{field}",
            )
    artifact_refs = record.get("artifact_refs", [])
    if not isinstance(artifact_refs, list) or any(
        not isinstance(item, str) or _ARTIFACT_REF_RE.match(item) is None for item in artifact_refs
    ):
        raise _CheckFailure(
            "parse",
            EXIT_INTEGRITY,
            "EVIDENCE_ARTIFACT_REFS_INVALID",
            "artifact_refs 必须是 artifact:// 数组",
            field_path=f"evidence[{index}].record.artifact_refs",
        )
    if len(set(artifact_refs)) != len(artifact_refs):
        raise _CheckFailure("parse", EXIT_INTEGRITY, "EVIDENCE_ARTIFACT_REFS_DUPLICATED", "artifact_refs 不得重复")
    return record


def _validate_split_manifest(split: Mapping[str, object]) -> None:
    """六字段 + schema_version + manifest_hash；不得缺字段，不得用缺省值代替。"""
    allowed = set(_SPLIT_FIELDS) | {"schema_version", "manifest_hash"}
    unknown = sorted(set(split.keys()) - allowed)
    missing = sorted(allowed - set(split.keys()))
    if unknown or missing:
        raise _CheckFailure(
            "parse",
            EXIT_INTEGRITY,
            "SPLIT_MANIFEST_FIELDS_INVALID",
            f"split_manifest 字段不匹配：缺少 {missing}，多出 {unknown}",
            field_path="split_manifest",
        )
    for field in ("dataset_hash", "row_id_hash", "fold_assignment_hash", "manifest_hash"):
        if not isinstance(split[field], str) or _HASH64_RE.match(str(split[field])) is None:
            raise _CheckFailure(
                "parse",
                EXIT_INTEGRITY,
                "SPLIT_HASH_INVALID",
                f"{field} 必须是 hash64",
                field_path=f"split_manifest.{field}",
            )
    if isinstance(split["seed"], bool) or not isinstance(split["seed"], int):
        raise _CheckFailure("parse", EXIT_INTEGRITY, "SPLIT_SEED_INVALID", "seed 必须是 integer")
    for field in ("split", "semantics"):
        if not isinstance(split[field], Mapping):
            raise _CheckFailure("parse", EXIT_INTEGRITY, "SPLIT_OBJECT_INVALID", f"{field} 必须是 object")


def _validate_merkle_proofs(proofs: Mapping[str, object]) -> None:
    """proofs 结构：root/tree_size/leaf_algorithm/proofs[]。"""
    allowed = {"root", "tree_size", "leaf_algorithm", "proofs"}
    unknown = sorted(set(proofs.keys()) - allowed)
    missing = sorted(allowed - set(proofs.keys()))
    if unknown or missing:
        raise _CheckFailure(
            "parse",
            EXIT_INTEGRITY,
            "MERKLE_PROOFS_FIELDS_INVALID",
            f"merkle_proofs 字段不匹配：缺少 {missing}，多出 {unknown}",
        )
    if not isinstance(proofs["root"], str) or _HASH64_RE.match(str(proofs["root"])) is None:
        raise _CheckFailure("parse", EXIT_INTEGRITY, "MERKLE_ROOT_INVALID", "root 必须是 hash64")
    if isinstance(proofs["tree_size"], bool) or not isinstance(proofs["tree_size"], int) or proofs["tree_size"] < 1:
        raise _CheckFailure("parse", EXIT_INTEGRITY, "MERKLE_TREE_SIZE_INVALID", "tree_size 必须是 ≥1 integer")
    if proofs["leaf_algorithm"] != "RFC9162":
        raise _CheckFailure("parse", EXIT_INTEGRITY, "MERKLE_ALGORITHM_UNSUPPORTED", "只支持 RFC9162")
    if not isinstance(proofs["proofs"], list):
        raise _CheckFailure("parse", EXIT_INTEGRITY, "MERKLE_PROOFS_NOT_ARRAY", "proofs 必须是数组")


def _validate_trust_claims(document: Mapping[str, object]) -> None:
    """包内指纹声明：claims_only=true、schema_version=1.0、keys 只含 key_id/key_fingerprint。"""
    if document.get("schema_version") != "1.0":
        raise _CheckFailure(
            "parse",
            EXIT_INTEGRITY,
            "TRUST_CLAIMS_VERSION_UNSUPPORTED",
            "trusted_key_fingerprint.json 的 schema_version 必须是 1.0",
        )
    if document.get("claims_only") is not True:
        raise _CheckFailure(
            "parse",
            EXIT_INTEGRITY,
            "TRUST_CLAIMS_NOT_MARKED",
            "trusted_key_fingerprint.json 必须 claims_only=true",
        )
    keys = document.get("keys")
    if not isinstance(keys, list) or not keys:
        raise _CheckFailure("parse", EXIT_INTEGRITY, "TRUST_CLAIMS_EMPTY", "指纹声明不得为空")
    for index, item in enumerate(keys):
        if not isinstance(item, Mapping) or set(item.keys()) != {"key_id", "key_fingerprint"}:
            raise _CheckFailure(
                "parse",
                EXIT_INTEGRITY,
                "TRUST_CLAIMS_INVALID",
                "每条声明只能含 key_id/key_fingerprint",
                field_path=f"trusted_key_fingerprint.keys[{index}]",
            )


def _claim_map(document: Mapping[str, object]) -> dict[str, str]:
    """把指纹声明转成 key_id→fingerprint；重复 key_id 拒绝。"""
    result: dict[str, str] = {}
    for item in document["keys"]:
        key_id = str(item["key_id"])
        fingerprint = str(item["key_fingerprint"])
        if key_id in result:
            raise _CheckFailure("signature", EXIT_SIGNATURE, "TRUST_CLAIM_DUPLICATED", f"key_id 声明重复：{key_id}")
        result[key_id] = fingerprint
    return result


def _compute_chain_hash(record: Mapping[str, object]) -> str:
    """按 P4 提案重算 chain_hash；算法未冻结（OQ-P4-02），变更必须升包格式。"""
    projection = {
        "schema_version": record["schema_version"],
        "evidence_id": record["evidence_id"],
        "task_id": record["task_id"],
        "node_id": record["node_id"],
        "attempt_id": record["attempt_id"],
        "event_seq": record["event_seq"],
        "level": record["level"],
        "kind": record["kind"],
        "producer": record["producer"],
        "timestamp": record["timestamp"],
        "payload_hash": record["payload_hash"],
        "artifact_refs": record.get("artifact_refs", []),
        "prev_hash": record["prev_hash"],
    }
    return hashlib.sha256(CHAIN_DOMAIN + jcs.canonicalize(projection)).hexdigest()


def _leaf_hash(chain_hash: str) -> str:
    """RFC 9162 叶哈希：SHA-256(0x00 || chain_hash 32 字节)。"""
    return hashlib.sha256(b"\x00" + bytes.fromhex(chain_hash)).hexdigest()


def _node_hash(left: str, right: str) -> str:
    """RFC 9162 内部节点：SHA-256(0x01 || left || right)。"""
    return hashlib.sha256(b"\x01" + bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()


def _largest_power_of_two_less_than(n: int) -> int:
    """小于 n 的最大 2 的幂；n ≥ 2。"""
    return 1 << ((n - 1).bit_length() - 1)


def _mth(leaves: Sequence[str]) -> str:
    """RFC 9162 MTH；leaves 是叶哈希（已加 0x00）。"""
    n = len(leaves)
    if n == 0:
        return hashlib.sha256(b"").hexdigest()
    if n == 1:
        return leaves[0]
    k = _largest_power_of_two_less_than(n)
    return _node_hash(_mth(leaves[:k]), _mth(leaves[k:]))


def _compute_merkle_root(chain_hashes: Sequence[str]) -> str:
    """由 chain_hash 列表计算 Merkle 根；顺序即 event_seq。"""
    return _mth([_leaf_hash(chain_hash) for chain_hash in chain_hashes])


def _verify_inclusion(
    index: int,
    tree_size: int,
    leaf_hash: str,
    audit_path: Sequence[str],
    root: str,
) -> bool:
    """RFC 9162 §2.1.3.2 的 fn/sn 验证；不是“按 index 奇偶折叠”的完美树算法。"""
    # 1. 单叶：空路径，叶即根。
    if tree_size == 1:
        return not audit_path and leaf_hash == root
    # 2. fn/sn 循环。
    fn = index
    sn = tree_size - 1
    result = leaf_hash
    for sibling in audit_path:
        if fn % 2 == 1 or fn == sn:
            result = _node_hash(sibling, result)
            while fn % 2 == 0 and fn != 0:
                fn >>= 1
                sn >>= 1
        else:
            result = _node_hash(result, sibling)
        fn >>= 1
        sn >>= 1
    # 3. 必须归约到单节点且等于根。
    return sn == 0 and result == root


def _decode_b64(value: str, reason: str) -> bytes:
    """解码 AnchorProof 签名；非标准 base64 以 8 退出。"""
    import base64
    import binascii

    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _CheckFailure("anchor", EXIT_ANCHOR, reason, "签名不是合法 base64") from exc
    if base64.b64encode(raw).decode("ascii") != value:
        raise _CheckFailure("anchor", EXIT_ANCHOR, reason, "签名 base64 不是规范编码")
    if len(raw) != 64:
        raise _CheckFailure("anchor", EXIT_ANCHOR, "ANCHOR_SIGNATURE_LENGTH_INVALID", "Ed25519 签名必须是 64 字节")
    return raw


def assert_exit_code_table() -> None:
    """退出码表自检：≥6 个不同非零值、不含 1、名称唯一。"""
    codes = [item.code for item in EXIT_CODE_TABLE]
    if len(codes) < 6:
        raise AssertionError("退出码表必须至少 6 个值")
    if len(set(codes)) != len(codes):
        raise AssertionError("退出码不得重复")
    if 1 in codes:
        raise AssertionError("不得使用退出码 1 作为通用失败")
    if len({item.name for item in EXIT_CODE_TABLE}) != len(EXIT_CODE_TABLE):
        raise AssertionError("退出码名称不得重复")
    if EXIT_OK != 0:
        raise AssertionError("通过必须是 0")


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main(sys.argv[1:]))