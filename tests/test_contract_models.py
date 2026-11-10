"""WP-02 契约模型测试：72 个冻结用例 + 拒绝原因断言。

按 AGENTS §8，反例不能只断言"被拒绝"，还必须断言拒绝原因（错误码/字段路径）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from researchflow.contracts.models import MODEL_BY_CONTRACT
from researchflow.contracts.parsing import ContractJSONError, parse_model

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "contracts" / "examples"
MANIFEST = json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = MANIFEST["cases"]
BY_FILE = {case["file"]: case for case in CASES}


def _run(case: dict[str, Any]) -> Any:
    model = MODEL_BY_CONTRACT[case["contract"]]
    return parse_model(model, (EXAMPLES / case["file"]).read_bytes())


def _errors(filename: str) -> list[dict[str, Any]]:
    with pytest.raises(ValidationError) as info:
        _run(BY_FILE[filename])
    return info.value.errors()


@pytest.mark.parametrize("case", CASES, ids=[case["file"] for case in CASES])
def test_verdict_matches_frozen_manifest(case: dict[str, Any]) -> None:
    if case["expect"] == "valid":
        _run(case)
    else:
        with pytest.raises((ValidationError, ContractJSONError)):
            _run(case)


def test_positive_examples_are_forward_compatible() -> None:
    accepted = [case["file"] for case in CASES if case["expect"] == "valid" and _run(case)]
    assert len(accepted) == 5


def test_missing_schema_version_rejected_for_required() -> None:
    errors = _errors("taskspec.negative.1.json")
    assert any(error["loc"] == ("schema_version",) and error["type"] == "missing" for error in errors)


def test_unknown_version_rejected_for_const() -> None:
    errors = _errors("taskspec.negative.2.json")
    assert any(error["loc"] == ("schema_version",) and error["type"] == "literal_error" for error in errors)


def test_dataset_ref_string_rejected_with_field_path() -> None:
    errors = _errors("taskspec.negative.3.json")
    assert any(
        error["loc"] == ("dataset_ref",) and error["type"] in {"string_type", "model_type", "dict_type"}
        for error in errors
    )


def test_unknown_top_level_field_rejected_as_extra() -> None:
    errors = _errors("taskspec.negative.5.json")
    assert any(error["type"] == "extra_forbidden" and error["loc"] == ("foo",) for error in errors)


def test_nested_limit_upper_bound_rejected() -> None:
    errors = _errors("taskspec.negative.4.json")
    assert any(
        error["loc"] == ("limits", "max_workers") and error["type"] == "less_than_equal"
        for error in errors
    )


def test_empty_models_list_rejected() -> None:
    errors = _errors("taskspec.negative.6.json")
    assert any(error["loc"] == ("parameters", "models") for error in errors)


def test_invalid_dataset_uri_rejected_for_pattern() -> None:
    errors = _errors("taskspec.negative.7.json")
    assert any(error["loc"] == ("dataset_ref", "uri") and error["type"] == "string_pattern_mismatch" for error in errors)


def test_duplicate_key_rejected_at_json_layer() -> None:
    with pytest.raises(ContractJSONError) as info:
        _run(BY_FILE["taskspec.negative.14.json"])
    assert info.value.keyword == "duplicate-key"


def test_nan_rejected_at_json_layer() -> None:
    with pytest.raises(ContractJSONError) as info:
        _run(BY_FILE["taskspec.negative.15.json"])
    assert info.value.keyword == "non-finite-number"


def test_duplicate_dependency_rejected() -> None:
    errors = _errors("nodespec.negative.10.json")
    assert any(error["loc"] == ("depends_on",) and "重复" in str(error["msg"]) for error in errors)


def test_self_dependency_rejected_by_sem_ns_01() -> None:
    errors = _errors("nodespec.negative.13.json")
    assert any("SEM-NS-01" in str(error["msg"]) for error in errors)


def test_level_producer_mismatch_rejected() -> None:
    errors = _errors("evidencerecord.negative.3.json")
    assert any(error["loc"] == () and "producer" in str(error["msg"]) for error in errors)


def test_level_kind_mismatch_rejected() -> None:
    errors = _errors("evidencerecord.negative.12.json")
    assert any("kind" in str(error["msg"]) and "E0" in str(error["msg"]) for error in errors)


def test_coverage_arithmetic_rejected_by_sem_vr_01() -> None:
    for filename in ("verificationreport.negative.5.json", "verificationreport.negative.6.json"):
        errors = _errors(filename)
        assert any("SEM-VR-01" in str(error["msg"]) for error in errors), filename


def test_verified_with_missing_checks_rejected_by_sem_vr_02() -> None:
    errors = _errors("verificationreport.negative.7.json")
    assert any("SEM-VR-02" in str(error["msg"]) for error in errors)


def test_skipped_nodes_non_empty_rejected() -> None:
    errors = _errors("completioncertificate.negative.7.json")
    assert any(error["loc"] == ("skipped_nodes",) for error in errors)