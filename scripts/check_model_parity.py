"""schema ↔ Pydantic 一致性检查（T0 · WP-02）。

判定分两部分：

1. **行为一致**：`contracts/examples/` 的 72 个用例，JSON Schema（复用 G0
   校验器，含 semantic 层）与 Pydantic 模型的接受/拒绝结论必须完全一致。
2. **结构一致**：逐契约比较 `properties` / `required` / `enum` / `pattern` /
   `additionalProperties`，模型不得多字段、少字段、松枚举。

退出码：0 全部一致；1 存在不一致；2 环境错误。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import BaseModel, ValidationError  # noqa: E402

from researchflow.contracts.models import MODEL_BY_CONTRACT  # noqa: E402
from researchflow.contracts.parsing import (  # noqa: E402
    ContractJSONError,
    parse_model,
)

EXAMPLES_DIR = ROOT / "contracts" / "examples"
DEFAULT_OUTPUT = ROOT / "docs" / "verification" / "t0" / "wp-02" / "model_parity.json"


def _load_contract_validator() -> Any:
    path = ROOT / "scripts" / "validate_contracts.py"
    spec = importlib.util.spec_from_file_location("_rf_contract_validator", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise SystemExit(f"ENVIRONMENT_ERROR 无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _schema_verdict(vc: Any, schemas: dict[str, Any], contract: str, path: Path) -> tuple[bool, str]:
    try:
        document = vc.load_json_strict(path)
    except vc.ContractLoadError as exc:
        return False, f"json:{exc}"
    errors = vc.validate(document, schemas[contract])
    if errors:
        return False, f"schema:{errors[0].keyword}@{errors[0].pointer}"
    semantic = vc.run_semantic(contract, document)
    if semantic:
        return False, f"semantic:{semantic[0].keyword}@{semantic[0].pointer}"
    return True, ""


def _model_verdict(contract: str, path: Path) -> tuple[bool, str]:
    model = MODEL_BY_CONTRACT[contract]
    try:
        parse_model(model, path.read_bytes())
    except ContractJSONError as exc:
        return False, f"json:{exc.keyword}"
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first.get("loc", ())) or "$"
        return False, f"model:{first.get('type')}@{loc}"
    return True, ""


def _literal_values(annotation: Any) -> set[Any] | None:
    if get_origin(annotation) is Literal:
        return set(get_args(annotation))
    return None


def _field_pattern(field: Any) -> str | None:
    for meta in getattr(field, "metadata", ()):
        pattern = getattr(meta, "pattern", None)
        if pattern is not None:
            return pattern
    return None


def _field_max_items(field: Any) -> int | None:
    for meta in getattr(field, "metadata", ()):
        limit = getattr(meta, "max_length", None)
        if limit is not None:
            return int(limit)
    return None


def _compare_node(schema: dict[str, Any], model: type[BaseModel], pointer: str, issues: list[str]) -> None:
    properties: dict[str, Any] = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields = model.model_fields

    for name in sorted(set(properties) - set(fields)):
        issues.append(f"{pointer}.{name}: schema 有、模型缺")
    for name in sorted(set(fields) - set(properties)):
        issues.append(f"{pointer}.{name}: 模型有、schema 缺")

    for name, prop in properties.items():
        field = fields.get(name)
        if field is None:
            continue
        if field.is_required() and name not in required:
            issues.append(f"{pointer}.{name}: 模型必填、schema 可选")
        if not field.is_required() and name in required:
            issues.append(f"{pointer}.{name}: schema 必填、模型可选")

        enum = prop.get("enum")
        if enum is not None:
            literals = _literal_values(field.annotation)
            if literals is None:
                issues.append(f"{pointer}.{name}: schema 有 enum、模型不是 Literal")
            elif literals != set(enum):
                issues.append(
                    f"{pointer}.{name}: 枚举不一致 {sorted(map(str, literals))} != {sorted(map(str, enum))}"
                )

        if prop.get("const") is not None:
            literals = _literal_values(field.annotation)
            if literals != {prop["const"]}:
                issues.append(f"{pointer}.{name}: const={prop['const']!r} 未固化为 Literal")

        pattern = prop.get("pattern")
        if isinstance(pattern, str) and prop.get("type") == "string":
            model_pattern = _field_pattern(field)
            if model_pattern != pattern:
                issues.append(f"{pointer}.{name}: pattern 不一致 {model_pattern!r} != {pattern!r}")

        if prop.get("maxItems") is not None and prop.get("type") == "array":
            if _field_max_items(field) != prop["maxItems"]:
                issues.append(f"{pointer}.{name}: maxItems 不一致")

        annotation = field.annotation
        if (
            prop.get("type") == "object"
            and "properties" in prop
            and isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
        ):
            _compare_node(prop, annotation, f"{pointer}.{name}", issues)

    schema_extra = schema.get("additionalProperties")
    if schema_extra is not None:
        model_extra = model.model_config.get("extra")
        expected = "forbid" if schema_extra is False else "allow" if schema_extra is True else None
        if expected is not None and model_extra != expected:
            issues.append(f"{pointer}: additionalProperties={schema_extra} 但模型 extra={model_extra!r}")


def run() -> tuple[dict[str, Any], list[str]]:
    vc = _load_contract_validator()
    schemas, lint_problems = vc.load_schemas()
    if lint_problems:
        return {}, [f"schema lint: {item}" for item in lint_problems]
    manifest = json.loads((EXAMPLES_DIR / "manifest.json").read_text(encoding="utf-8"))

    rows: list[dict[str, Any]] = []
    disagreements: list[str] = []
    for case in manifest["cases"]:
        contract = case["contract"]
        path = EXAMPLES_DIR / case["file"]
        schema_ok, schema_detail = _schema_verdict(vc, schemas, contract, path)
        model_ok, model_detail = _model_verdict(contract, path)
        agree = schema_ok == model_ok
        rows.append(
            {
                "contract": contract,
                "file": case["file"],
                "layer": case["layer"],
                "expect": case["expect"],
                "schema_accepts": schema_ok,
                "model_accepts": model_ok,
                "agree": agree,
                "schema_detail": schema_detail,
                "model_detail": model_detail,
            }
        )
        if not agree:
            disagreements.append(
                f"{case['file']}: schema={'accept' if schema_ok else 'reject'}"
                f"({schema_detail}) model={'accept' if model_ok else 'reject'}({model_detail})"
            )

    structure: dict[str, Any] = {}
    structure_issues: list[str] = []
    for contract, model in MODEL_BY_CONTRACT.items():
        issues: list[str] = []
        _compare_node(schemas[contract], model, "$", issues)
        structure[contract] = {"ok": not issues, "issues": issues}
        structure_issues.extend(f"{contract}: {item}" for item in issues)

    positives = sum(1 for row in rows if row["expect"] == "valid")
    negatives = len(rows) - positives
    generated_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    report = {
        "generated_at": generated_at,
        "tool": "scripts/check_model_parity.py",
        "contract_version": manifest.get("contract_version"),
        "python": sys.version.split()[0],
        "totals": {
            "cases": len(rows),
            "positives": positives,
            "negatives": negatives,
            "agree": sum(1 for row in rows if row["agree"]),
            "disagree": len(disagreements),
        },
        "structure": structure,
        "cases": rows,
        "result": "PASS" if not disagreements and not structure_issues else "FAIL",
    }
    problems = disagreements + structure_issues
    return report, problems


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    output = DEFAULT_OUTPUT
    if "--json-out" in argv:
        output = Path(argv[argv.index("--json-out") + 1])

    print(f"MODEL_PARITY root={ROOT} python={sys.version.split()[0]}")
    report, problems = run()
    if not report:
        for item in problems:
            print(f"[FAIL] {item}")
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    totals = report["totals"]
    for row in report["cases"]:
        if not row["agree"]:
            print(
                f"[FAIL] {row['file']:<44} schema_accepts={row['schema_accepts']} "
                f"model_accepts={row['model_accepts']} {row['schema_detail']} / {row['model_detail']}"
            )
    for contract, data in report["structure"].items():
        for issue in data["issues"]:
            print(f"[FAIL] structure {contract}: {issue}")

    print(
        f"SUMMARY contracts={len(report['structure'])} cases={totals['cases']} "
        f"positives={totals['positives']} negatives={totals['negatives']} "
        f"agree={totals['agree']} disagree={totals['disagree']} "
        f"structure_problems={len(problems) - totals['disagree']} result={report['result']}"
    )
    print(f"JSON {output}")
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())