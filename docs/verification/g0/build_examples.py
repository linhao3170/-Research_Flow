#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_examples.py — 生成 contracts/examples/ 下的合成正例、反例与 manifest。

定位
----
这是 G0 契约冻结的证据构造脚本，**不是 T0 业务代码**，不进入运行期。
每个反例都显式声明“期望被哪一层的哪个关键字、在哪个实例指针上拒绝”，
由 scripts/validate_contracts.py 独立复算；期望不匹配即 FAIL，不按实际结果回填。

重新生成：
    $py docs/verification/g0/build_examples.py
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "contracts" / "examples"

H1 = "9f2c1d7e5b3a4c6081d2e4f6a8b0c2d4e6f8a0b2c4d6e8f0a2b4c6d8e0f2a4b6"
H2 = "0b1d3f5a7c9e2b4d6f8a0c1e3b5d7f9a2c4e6b8d0f1a3c5e7b9d2f4a6c8e0b1d"
H3 = "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f809"
H4 = "2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a"
H5 = "3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b"
H6 = "4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c"
H7 = "5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d"

TASK_ID = "task_3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10"
REPORT_ID = "report_7d1e2f3a-4b5c-4d6e-8f90-a1b2c3d4e5f6"
CERT_ID = "cert_2b3c4d5e-6f70-4a8b-9c0d-1e2f3a4b5c6d"
EVIDENCE_ID = "ev_9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d"
SIGNATURE = "c2lnbmF0dXJlLXN5bnRoZXRpYy1leGFtcGxlLTAwMDE="

TASKSPEC = {
    "schema_version": "1.0",
    "task_id": TASK_ID,
    "domain_pack": "tabular_ml@1.0.0",
    "goal": "Train and compare tabular classifiers on the bundled synthetic dataset.",
    "dataset_ref": {
        "uri": "local://datasets/synthetic_breast_cancer.csv",
        "sha256": H1,
        "license": "CC-BY-4.0",
    },
    "template_id": "classification_benchmark@1.0.0",
    "parameters": {
        "target": "diagnosis",
        "seed": 42,
        "test_size": 0.2,
        "models": ["logistic_regression"],
    },
    "ruleset_hash": H2,
    "limits": {"wall_time_sec": 1800, "max_workers": 2, "max_memory_mb": 4096},
}

NODESPEC = {
    "schema_version": "1.0",
    "node_id": "train_random_forest",
    "node_type": "ml.train.classifier",
    "template_id": "random_forest@1.0.0",
    "depends_on": ["split_dataset", "preprocess"],
    "input_refs": ["artifact://split_manifest"],
    "parameters_hash": H3,
    "side_effect_class": "PURE_ARTIFACT",
    "retry_policy": {"max_attempts": 2, "backoff_sec": 2},
    "required_checks": ["executor_observed", "artifact_hash", "metric_source"],
}

EVIDENCE = {
    "schema_version": "1.0",
    "evidence_id": EVIDENCE_ID,
    "task_id": TASK_ID,
    "node_id": "train_random_forest",
    "attempt_id": "attempt_02",
    "event_seq": 17,
    "level": "E2",
    "kind": "executor_process_exit",
    "producer": "collector",
    "timestamp": "2026-11-09T09:00:00Z",
    "payload_hash": H4,
    "artifact_refs": ["artifact://model.pkl"],
    "prev_hash": H5,
    "chain_hash": H6,
}

REPORT = {
    "schema_version": "1.0",
    "report_id": REPORT_ID,
    "task_id": TASK_ID,
    "final_state": "VERIFIED",
    "l1_status": "PASS",
    "l2_status": "PASS",
    "l3_status": "PASS",
    "required_check_coverage": {"required": 12, "passed": 12, "missing": 0},
    "ruleset_hash": H2,
    "evidence_root": H7,
    "l3_coverage": 1.0,
    "issued_at": "2026-11-09T09:05:00Z",
    "key_id": "dev-ed25519-2026-11",
    "signature": SIGNATURE,
}

CERT = {
    "schema_version": "1.0",
    "cert_id": CERT_ID,
    "report_id": REPORT_ID,
    "final_state": "VERIFIED",
    "merkle_root": H7,
    "tree_size": 128,
    "ruleset_hash": H2,
    "code_hash": H3,
    "env_fingerprint": H4,
    "l3_coverage": 1.0,
    "skipped_nodes": [],
    "alg": "Ed25519",
    "key_id": "dev-ed25519-2026-11",
    "key_fingerprint": H5,
    "signature": SIGNATURE,
    "issued_at": "2026-11-09T09:06:00Z",
}

BASES = {
    "taskspec": TASKSPEC,
    "nodespec": NODESPEC,
    "evidencerecord": EVIDENCE,
    "verificationreport": REPORT,
    "completioncertificate": CERT,
}

CASES: list[dict] = []
PAYLOADS: dict[str, object] = {}


def base(contract: str) -> dict:
    return copy.deepcopy(BASES[contract])


def add(
    contract: str,
    filename: str,
    payload: object,
    covers: str,
    note: str = "",
    *,
    layer: str = "schema",
    keyword: str | None = None,
    pointer: str | None = None,
    expect: str = "invalid",
) -> None:
    CASES.append(
        {
            "contract": contract,
            "file": filename,
            "expect": expect,
            "layer": layer,
            "keyword": keyword,
            "pointer": pointer,
            "covers": covers,
            "note": note,
        }
    )
    PAYLOADS[filename] = payload


def positive(contract: str, covers: str) -> None:
    add(
        contract,
        f"{contract}.positive.json",
        base(contract),
        covers,
        "合成正例；schema 校验与已登记语义检查均须通过",
        expect="valid",
    )


# --------------------------------------------------------------------------- #
# TaskSpec
# --------------------------------------------------------------------------- #
positive("taskspec", "05 §2.2 正例；决议 9 dataset_ref 对象形态")

d = base("taskspec")
del d["schema_version"]
add("taskspec", "taskspec.negative.1.json", d, "05 §2.3 缺 schema_version → 422", keyword="required", pointer="$")

d = base("taskspec")
d["schema_version"] = "2.0"
add("taskspec", "taskspec.negative.2.json", d, "05 §1.2 未知 MAJOR 必须拒绝", keyword="const", pointer="$.schema_version")

d = base("taskspec")
d["dataset_ref"] = "dataset://breast_cancer@sha256:" + H1
add(
    "taskspec",
    "taskspec.negative.3.json",
    d,
    "决议 9：API 收到字符串 dataset_ref 必须 422",
    "附录 E.1 的字符串样例；ADR-002 统一为对象形态",
    keyword="type",
    pointer="$.dataset_ref",
)

d = base("taskspec")
d["limits"]["max_workers"] = 4
add("taskspec", "taskspec.negative.4.json", d, "05 §2.3 并发超第一版上限 2", keyword="maximum", pointer="$.limits.max_workers")

d = base("taskspec")
d["foo"] = 1
add("taskspec", "taskspec.negative.5.json", d, "05 §2.3 未知顶层字段拒绝", keyword="additionalProperties", pointer="$")

d = base("taskspec")
d["parameters"]["models"] = []
add("taskspec", "taskspec.negative.6.json", d, "05 §2.3 models 空数组拒绝", keyword="minItems", pointer="$.parameters.models")

d = base("taskspec")
d["dataset_ref"]["uri"] = "https://example.com/breast_cancer.csv"
add("taskspec", "taskspec.negative.7.json", d, "05 §2.3 T0 断网，网络 URI 拒绝", keyword="pattern", pointer="$.dataset_ref.uri")

d = base("taskspec")
d["dataset_ref"]["sha256"] = "abc123"
add("taskspec", "taskspec.negative.8.json", d, "05 §2.1 哈希必须 64 位小写十六进制", keyword="pattern", pointer="$.dataset_ref.sha256")

d = base("taskspec")
d["task_id"] = "3f2c9a1e-0b7d-4c55-9a4e-1f6b2d8c7a10"
add("taskspec", "taskspec.negative.9.json", d, "05 §1.4 ID 必须带稳定前缀与 UUID", keyword="pattern", pointer="$.task_id")

d = base("taskspec")
d["limits"]["wall_time_sec"] = 0
add("taskspec", "taskspec.negative.10.json", d, "05 §2.1 wall_time_sec 必须 >0", keyword="exclusiveMinimum", pointer="$.limits.wall_time_sec")

d = base("taskspec")
d["template_id"] = "classification_benchmark"
add("taskspec", "taskspec.negative.11.json", d, "05 §2.1 模板标识必须 name@MAJOR.MINOR.PATCH", keyword="pattern", pointer="$.template_id")

d = base("taskspec")
d["dataset_ref"]["license"] = ""
add("taskspec", "taskspec.negative.12.json", d, "05 §2.1 license 非空", keyword="minLength", pointer="$.dataset_ref.license")

d = base("taskspec")
d["parameters"]["test_size"] = 1.0
add("taskspec", "taskspec.negative.13.json", d, "05 §2.1 test_size 开区间 (0,1)", keyword="exclusiveMaximum", pointer="$.parameters.test_size")

_dump = json.dumps(base("taskspec"), ensure_ascii=False, indent=2)
_dup = _dump.replace('{\n  "schema_version"', '{\n  "goal": "duplicate key",\n  "schema_version"', 1)
add(
    "taskspec",
    "taskspec.negative.14.json",
    _dup,
    "05 §1.3 禁止重复键",
    "原始文本重复 goal 键；RFC 8259 层拒绝",
    layer="json",
    keyword="duplicate-key",
    pointer="$",
)

_nan = json.dumps(base("taskspec"), ensure_ascii=False, indent=2).replace('"seed": 42', '"seed": NaN', 1)
add(
    "taskspec",
    "taskspec.negative.15.json",
    _nan,
    "05 §1.3 禁止 NaN/Infinity",
    "原始文本含 NaN；RFC 8259 层拒绝",
    layer="json",
    keyword="non-finite-number",
    pointer="$",
)

# --------------------------------------------------------------------------- #
# NodeSpec
# --------------------------------------------------------------------------- #
positive("nodespec", "05 §3.2 正例；决议 2 已补 schema_version")

d = base("nodespec")
del d["schema_version"]
add("nodespec", "nodespec.negative.1.json", d, "决议 2：NodeSpec 必须含 schema_version", keyword="required", pointer="$")

d = base("nodespec")
d["schema_version"] = "1.1"
add("nodespec", "nodespec.negative.2.json", d, "05 §1.2 未知 MINOR 需告警；本 schema 冻结 1.0", keyword="const", pointer="$.schema_version")

d = base("nodespec")
d["side_effect_class"] = "MAGIC"
add("nodespec", "nodespec.negative.3.json", d, "OQ-CT-09 候选枚举外取值拒绝", keyword="enum", pointer="$.side_effect_class")

d = base("nodespec")
d["required_checks"] = []
add("nodespec", "nodespec.negative.4.json", d, "05 §3.3 必检项空数组拒绝", keyword="minItems", pointer="$.required_checks")

d = base("nodespec")
d["retry_policy"]["max_attempts"] = 0
add("nodespec", "nodespec.negative.5.json", d, "05 §3.1 max_attempts >=1", keyword="minimum", pointer="$.retry_policy.max_attempts")

d = base("nodespec")
d["retry_policy"]["backoff_sec"] = -1
add("nodespec", "nodespec.negative.6.json", d, "05 §3.1 backoff_sec 不得为负", keyword="minimum", pointer="$.retry_policy.backoff_sec")

d = base("nodespec")
d["node_id"] = "train/random_forest"
add("nodespec", "nodespec.negative.7.json", d, "05 §3.1 node_id 不得含路径分隔符", keyword="pattern", pointer="$.node_id")

d = base("nodespec")
d["priority"] = 1
add("nodespec", "nodespec.negative.8.json", d, "05 §3.1 未声明字段拒绝", keyword="additionalProperties", pointer="$")

d = base("nodespec")
d["parameters_hash"] = "deadbeef"
add("nodespec", "nodespec.negative.9.json", d, "05 §3.1 parameters_hash 必须 64 位十六进制", keyword="pattern", pointer="$.parameters_hash")

d = base("nodespec")
d["depends_on"] = ["split_dataset", "split_dataset"]
add("nodespec", "nodespec.negative.10.json", d, "05 §3.3 重复前驱拒绝", keyword="uniqueItems", pointer="$.depends_on")

d = base("nodespec")
del d["retry_policy"]
add("nodespec", "nodespec.negative.11.json", d, "05 §3.1 retry_policy 必填", keyword="required", pointer="$")

d = base("nodespec")
d["input_refs"] = ["model.pkl"]
add("nodespec", "nodespec.negative.12.json", d, "05 §3.1 input_refs 必须 artifact:// 引用", keyword="pattern", pointer="$.input_refs[0]")

d = base("nodespec")
d["node_id"] = "split_dataset"
d["depends_on"] = ["split_dataset"]
add(
    "nodespec",
    "nodespec.negative.13.json",
    d,
    "05 §3.3 自依赖拒绝（JSON Schema 无法表达，见 SEM-NS-01）",
    "结构合法，仅语义检查拒绝",
    layer="semantic",
    keyword="SEM-NS-01",
    pointer="$.depends_on",
)

# --------------------------------------------------------------------------- #
# EvidenceRecord
# --------------------------------------------------------------------------- #
positive("evidencerecord", "05 §4.2 正例")

d = base("evidencerecord")
del d["schema_version"]
add("evidencerecord", "evidencerecord.negative.1.json", d, "05 §4.1 schema_version 必填", keyword="required", pointer="$")

d = base("evidencerecord")
d["level"] = "E4"
add("evidencerecord", "evidencerecord.negative.2.json", d, "05 §4.1 等级仅 E0–E3", keyword="enum", pointer="$.level")

d = base("evidencerecord")
d["producer"] = "agent"
add(
    "evidencerecord",
    "evidencerecord.negative.3.json",
    d,
    "05 §4.3 E2 不得由 Agent 产出",
    "level->producer 由 allOf/if-then 固化",
    keyword="const",
    pointer="$.producer",
)

d = base("evidencerecord")
d["event_seq"] = 0
add("evidencerecord", "evidencerecord.negative.4.json", d, "附录 F.1 event_seq 从 1 起", keyword="minimum", pointer="$.event_seq")

d = base("evidencerecord")
d["timestamp"] = "2026-11-09T17:00:00+08:00"
add("evidencerecord", "evidencerecord.negative.5.json", d, "05 §1.3 时间必须 UTC（Z 或 +00:00）", keyword="pattern", pointer="$.timestamp")

d = base("evidencerecord")
d["prev_hash"] = H5.upper()
add("evidencerecord", "evidencerecord.negative.6.json", d, "05 §1.3 哈希小写十六进制", keyword="pattern", pointer="$.prev_hash")

d = base("evidencerecord")
del d["kind"]
add("evidencerecord", "evidencerecord.negative.7.json", d, "05 §4.1 kind 必填", keyword="required", pointer="$")

d = base("evidencerecord")
d["artifact_refs"] = ["output/model.pkl"]
add("evidencerecord", "evidencerecord.negative.8.json", d, "05 §4.1 artifact_refs 必须 artifact:// 引用", keyword="pattern", pointer="$.artifact_refs[0]")

d = base("evidencerecord")
d["note"] = "free text"
add("evidencerecord", "evidencerecord.negative.9.json", d, "05 §1.3 未声明字段不得静默纳入", keyword="additionalProperties", pointer="$")

d = base("evidencerecord")
d["evidence_id"] = "ev_9a1b"
add("evidencerecord", "evidencerecord.negative.10.json", d, "05 §1.4 evidence_id 必须 ev_+UUID", keyword="pattern", pointer="$.evidence_id")

d = base("evidencerecord")
d["event_seq"] = "17"
add("evidencerecord", "evidencerecord.negative.11.json", d, "05 §4.1 event_seq 必须是整数", keyword="type", pointer="$.event_seq")

d = base("evidencerecord")
d["level"] = "E0"
d["kind"] = "executor_process_exit"
add(
    "evidencerecord",
    "evidencerecord.negative.12.json",
    d,
    "01 §4.3 E0 只能承载 agent_claim",
    "level->kind 由 allOf/if-then 固化",
    keyword="enum",
    pointer="$.kind",
)

# --------------------------------------------------------------------------- #
# VerificationReport
# --------------------------------------------------------------------------- #
positive("verificationreport", "05 §5.2 正例；决议 2 已补 schema_version")

d = base("verificationreport")
del d["schema_version"]
add("verificationreport", "verificationreport.negative.1.json", d, "决议 2：VerificationReport 必须含 schema_version", keyword="required", pointer="$")

d = base("verificationreport")
d["schema_version"] = "1.0.0"
add("verificationreport", "verificationreport.negative.2.json", d, "05 §1.2 版本格式 MAJOR.MINOR", keyword="const", pointer="$.schema_version")

d = base("verificationreport")
d["final_state"] = "COMPLETED"
add("verificationreport", "verificationreport.negative.3.json", d, "05 §5.1 四态，COMPLETED 属 Task 状态", keyword="enum", pointer="$.final_state")

d = base("verificationreport")
d["l1_status"] = "OK"
add("verificationreport", "verificationreport.negative.4.json", d, "OQ-CT-03 候选枚举外取值拒绝", keyword="enum", pointer="$.l1_status")

d = base("verificationreport")
d["required_check_coverage"] = {"required": 12, "passed": 13, "missing": 0}
add(
    "verificationreport",
    "verificationreport.negative.5.json",
    d,
    "05 §5.2 passed 不得大于 required（SEM-VR-01）",
    "结构合法，算术不变量拒绝",
    layer="semantic",
    keyword="SEM-VR-01",
    pointer="$.required_check_coverage",
)

d = base("verificationreport")
d["required_check_coverage"] = {"required": 12, "passed": 12, "missing": 2}
add(
    "verificationreport",
    "verificationreport.negative.6.json",
    d,
    "05 §5.1 missing 必须等于 required-passed（SEM-VR-01）",
    "结构合法，算术不变量拒绝",
    layer="semantic",
    keyword="SEM-VR-01",
    pointer="$.required_check_coverage",
)

d = base("verificationreport")
d["final_state"] = "VERIFIED"
d["required_check_coverage"] = {"required": 12, "passed": 11, "missing": 1}
add(
    "verificationreport",
    "verificationreport.negative.7.json",
    d,
    "AGENTS §4.10 VERIFIED 必须有完整必检证据（SEM-VR-02）",
    "结构合法，语义检查拒绝",
    layer="semantic",
    keyword="SEM-VR-02",
    pointer="$.final_state",
)

d = base("verificationreport")
d["l3_coverage"] = 1.2
add("verificationreport", "verificationreport.negative.8.json", d, "05 §5.1 l3_coverage 闭区间 [0,1]", keyword="maximum", pointer="$.l3_coverage")

d = base("verificationreport")
d["signature"] = "not base64!"
add("verificationreport", "verificationreport.negative.9.json", d, "05 §5.1 signature 必须 base64", keyword="pattern", pointer="$.signature")

d = base("verificationreport")
d["ruleset_hash"] = "abc"
add("verificationreport", "verificationreport.negative.10.json", d, "05 §5.1 ruleset_hash 64 位十六进制", keyword="pattern", pointer="$.ruleset_hash")

d = base("verificationreport")
d["notes"] = "free text"
add("verificationreport", "verificationreport.negative.11.json", d, "05 §1.3 未声明字段拒绝", keyword="additionalProperties", pointer="$")

d = base("verificationreport")
d["report_id"] = "rep_7d1e2f3a-4b5c-4d6e-8f90-a1b2c3d4e5f6"
add("verificationreport", "verificationreport.negative.12.json", d, "05 §1.4 report_id 必须 report_+UUID", keyword="pattern", pointer="$.report_id")

d = base("verificationreport")
del d["required_check_coverage"]
add("verificationreport", "verificationreport.negative.13.json", d, "05 §5.1 覆盖矩阵必填", keyword="required", pointer="$")

d = base("verificationreport")
d["issued_at"] = "2026-11-09T17:05:00+08:00"
add("verificationreport", "verificationreport.negative.14.json", d, "05 §5.1 签发时间必须 UTC", keyword="pattern", pointer="$.issued_at")

# --------------------------------------------------------------------------- #
# CompletionCertificate
# --------------------------------------------------------------------------- #
positive("completioncertificate", "05 §6.2 正例；决议 2 已补 schema_version 与 issued_at")

d = base("completioncertificate")
del d["schema_version"]
add("completioncertificate", "completioncertificate.negative.1.json", d, "决议 2：CompletionCertificate 必须含 schema_version", keyword="required", pointer="$")

d = base("completioncertificate")
d["schema_version"] = "1.0.0"
add("completioncertificate", "completioncertificate.negative.2.json", d, "05 §1.2 版本格式 MAJOR.MINOR", keyword="const", pointer="$.schema_version")

d = base("completioncertificate")
del d["issued_at"]
add("completioncertificate", "completioncertificate.negative.3.json", d, "决议 2：证书必须补 issued_at", keyword="required", pointer="$")

d = base("completioncertificate")
d["issued_at"] = "2026-11-09T17:06:00+08:00"
add("completioncertificate", "completioncertificate.negative.4.json", d, "05 §1.3 时间必须 UTC", keyword="pattern", pointer="$.issued_at")

d = base("completioncertificate")
d["final_state"] = "PARTIAL"
add("completioncertificate", "completioncertificate.negative.5.json", d, "05 §6.1 证书仅 VERIFIED", keyword="const", pointer="$.final_state")

d = base("completioncertificate")
d["alg"] = "ES256"
add("completioncertificate", "completioncertificate.negative.6.json", d, "05 §6.1 算法固定 Ed25519", keyword="const", pointer="$.alg")

d = base("completioncertificate")
d["skipped_nodes"] = ["train_svm"]
add("completioncertificate", "completioncertificate.negative.7.json", d, "05 §6.2 T0 无 SPA，skipped_nodes 必须为空", keyword="maxItems", pointer="$.skipped_nodes")

d = base("completioncertificate")
d["tree_size"] = 0
add("completioncertificate", "completioncertificate.negative.8.json", d, "05 §6.1 tree_size >=1", keyword="minimum", pointer="$.tree_size")

d = base("completioncertificate")
d["l3_coverage"] = 1.5
add("completioncertificate", "completioncertificate.negative.9.json", d, "05 §6.1 l3_coverage 闭区间 [0,1]", keyword="maximum", pointer="$.l3_coverage")

d = base("completioncertificate")
d["signature"] = "???"
add("completioncertificate", "completioncertificate.negative.10.json", d, "05 §6.1 signature 必须 base64", keyword="pattern", pointer="$.signature")

d = base("completioncertificate")
d["key_fingerprint"] = "a" * 40
add("completioncertificate", "completioncertificate.negative.11.json", d, "I-08 指纹必须 64 位十六进制", keyword="pattern", pointer="$.key_fingerprint")

d = base("completioncertificate")
d["report_id"] = TASK_ID
add("completioncertificate", "completioncertificate.negative.12.json", d, "05 §6.1 report_id 必须 report_+UUID", keyword="pattern", pointer="$.report_id")

d = base("completioncertificate")
d["notes"] = "free text"
add("completioncertificate", "completioncertificate.negative.13.json", d, "05 §1.3 未声明字段拒绝", keyword="additionalProperties", pointer="$")


def main() -> int:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    for stale in EXAMPLES_DIR.glob("*.json"):
        stale.unlink()

    written = 0
    for filename, payload in PAYLOADS.items():
        path = EXAMPLES_DIR / filename
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8", newline="\n")
        else:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        written += 1

    manifest = {
        "manifest_version": "1.0",
        "contract_version": "1.0",
        "generated_by": "docs/verification/g0/build_examples.py",
        "data_classification": "synthetic-example",
        "note": "全部为合成样例：不含真实实验数据、不含密钥、不含个人信息；不得作为实验结果引用。",
        "cases": CASES,
    }
    (EXAMPLES_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"EXAMPLES_WRITTEN files={written} manifest_cases={len(CASES)} dir={EXAMPLES_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())