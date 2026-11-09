#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_contracts.py — ResearchFlow G0 契约正/反例校验器（仅标准库）。

用途
----
1. 对 contracts/*.schema.json 做结构 lint：$id / title / schema_version / additionalProperties、
   未知关键字、$ref 本地化、required 与 properties 一致、pattern 可编译。
2. 对 contracts/examples/ 下由 manifest.json 声明的正例执行通过校验、反例执行拒绝校验，
   并核对“拒绝原因”本身（keyword + 实例指针），避免反例因为别的原因碰巧被拒。
3. 三层分离，输出中逐层标注：
   - schema     JSON Schema Draft 2020-12 结构校验（本脚本内置子集实现）
   - semantic   JSON Schema 无法表达的跨字段不变量（SEM-* 清单见 docs/design/05 §13）
   - json       RFC 8259 层：重复键、NaN/Infinity（05 §1.3）

边界
----
- 本脚本是 G0 冻结物的一部分，不是 T0 业务代码；不连接数据库、不读私钥、不访问网络。
- 内置校验器不是完整 Draft 2020-12 实现：只支持显式登记的关键字，遇到未登记关键字直接报错
  （fail closed），因此不会出现“关键字拼错却静默放行”。
- 正例/反例均为合成样例（synthetic），不含真实实验数据。

用法
----
    $py scripts/validate_contracts.py            # 全量：lint + 全部用例
    $py scripts/validate_contracts.py --selftest # 校验器自检（内置 schema/实例对）
    $py scripts/validate_contracts.py --contract taskspec
    $py scripts/validate_contracts.py --verbose

退出码
------
    0  全部 PASS
    1  存在 FAIL（lint、用例或覆盖检查）
    2  环境/用法错误

解释器：项目基线 Python 3.11.16（64 位），见 AGENTS.md §3。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = REPO_ROOT / "contracts"
EXAMPLES_DIR = CONTRACTS_DIR / "examples"
MANIFEST_PATH = EXAMPLES_DIR / "manifest.json"

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_VERSION_CONST = "1.0"

# 已实现关键字（出现其它关键字 -> lint FAIL，避免拼写错误静默放行）。
IMPLEMENTED_KEYWORDS = {
    "$schema",
    "$id",
    "$ref",
    "$defs",
    "$comment",
    "title",
    "description",
    "type",
    "properties",
    "additionalProperties",
    "propertyNames",
    "required",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "enum",
    "const",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
}

SUPPORTED_FORMATS = {"date-time", "uri"}

# 单个 schema 内部的下级 schema 位置。
SINGLE_CHILD_KEYWORDS = (
    "items",
    "additionalProperties",
    "propertyNames",
    "not",
    "if",
    "then",
    "else",
)
LIST_CHILD_KEYWORDS = ("allOf", "anyOf", "oneOf")
MAP_CHILD_KEYWORDS = ("properties", "patternProperties", "$defs")


class SchemaDefect(Exception):
    """schema 本身不合法（lint 阶段捕获）。"""


class ContractLoadError(Exception):
    """样例文件在 RFC 8259 层即被拒绝。"""

    def __init__(self, keyword: str, message: str) -> None:
        super().__init__(message)
        self.keyword = keyword
        self.pointer = "$"


@dataclass(frozen=True)
class Error:
    pointer: str
    keyword: str
    message: str

    def render(self) -> str:
        return f"{self.pointer} {self.keyword}: {self.message}"


# --------------------------------------------------------------------------- #
# 值类型判定
# --------------------------------------------------------------------------- #


def _json_type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise SchemaDefect(f"实例含非 JSON 值：{type(value)!r}")


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, float):
            return math.isfinite(value) and value.is_integer()
        return False
    raise SchemaDefect(f"未支持的 type: {expected!r}")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_equal(left: Any, right: Any) -> bool:
    return _canonical(left) == _canonical(right)


def _child(pointer: str, name: str) -> str:
    return f"$.{name}" if pointer == "$" else f"{pointer}.{name}"


# --------------------------------------------------------------------------- #
# format 校验（只实现 date-time 与 uri）
# --------------------------------------------------------------------------- #

_RFC3339_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?([Zz]|[+-]\d{2}:\d{2})$"
)
_URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]*$")


def _is_rfc3339_datetime(value: str) -> bool:
    match = _RFC3339_RE.match(value)
    if match is None:
        return False
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    if not 1 <= month <= 12:
        return False
    try:
        import datetime

        datetime.date(year, month, day)
    except ValueError:
        return False
    if hour > 23 or minute > 59 or second > 60:
        return False
    zone = match.group(8)
    if zone not in ("Z", "z"):
        if int(zone[1:3]) > 23 or int(zone[4:6]) > 59:
            return False
    return True


def _check_format(value: str, fmt: str, pointer: str) -> list[Error]:
    if fmt == "date-time":
        if not _is_rfc3339_datetime(value):
            return [Error(pointer, "format", f"{value!r} 不是 RFC 3339 date-time")]
        return []
    if fmt == "uri":
        if not _URI_RE.match(value):
            return [Error(pointer, "format", f"{value!r} 不是绝对 URI")]
        return []
    raise SchemaDefect(f"未支持的 format: {fmt!r}")


# --------------------------------------------------------------------------- #
# JSON Schema 子集校验器
# --------------------------------------------------------------------------- #


def resolve_ref(ref: str, root: Any) -> Any:
    if not ref.startswith("#/"):
        raise SchemaDefect(f"只允许本地 $ref（#/$defs/...），发现 {ref!r}")
    node = root
    for raw in ref[2:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or token not in node:
            raise SchemaDefect(f"$ref 无法解析：{ref!r}")
        node = node[token]
    return node


def validate(instance: Any, schema: Any, pointer: str = "$", root: Any = None, depth: int = 0) -> list[Error]:
    if root is None:
        root = schema
    if depth > 64:
        raise SchemaDefect("schema 递归过深或存在循环 $ref")
    if isinstance(schema, bool):
        return [] if schema else [Error(pointer, "false-schema", "schema 为 false，拒绝一切实例")]
    if not isinstance(schema, dict):
        raise SchemaDefect(f"schema 节点必须是对象或布尔值，实际 {type(schema)!r}")

    errors: list[Error] = []

    if "$ref" in schema:
        errors.extend(validate(instance, resolve_ref(schema["$ref"], root), pointer, root, depth + 1))

    declared = schema.get("type")
    if declared is not None:
        expected = declared if isinstance(declared, list) else [declared]
        if not any(_matches_type(instance, item) for item in expected):
            got = _json_type_of(instance)
            return errors + [Error(pointer, "type", f"期望 {expected}，实际 {got}")]

    if "const" in schema and not _json_equal(instance, schema["const"]):
        errors.append(Error(pointer, "const", f"期望常量 {schema['const']!r}，实际 {instance!r}"))

    if "enum" in schema and not any(_json_equal(instance, item) for item in schema["enum"]):
        errors.append(Error(pointer, "enum", f"{instance!r} 不在枚举 {schema['enum']!r} 中"))

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(Error(pointer, "minLength", f"长度 {len(instance)} < {schema['minLength']}"))
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(Error(pointer, "maxLength", f"长度 {len(instance)} > {schema['maxLength']}"))
        if "pattern" in schema:
            try:
                matched = re.search(schema["pattern"], instance) is not None
            except re.error as exc:  # pragma: no cover - lint 已拦截
                raise SchemaDefect(f"pattern 无法编译：{schema['pattern']!r}: {exc}") from exc
            if not matched:
                errors.append(Error(pointer, "pattern", f"{instance!r} 不匹配 {schema['pattern']!r}"))
        if "format" in schema:
            errors.extend(_check_format(instance, schema["format"], pointer))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(Error(pointer, "minimum", f"{instance} < {schema['minimum']}"))
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(Error(pointer, "maximum", f"{instance} > {schema['maximum']}"))
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(
                Error(pointer, "exclusiveMinimum", f"{instance} <= {schema['exclusiveMinimum']}")
            )
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            errors.append(
                Error(pointer, "exclusiveMaximum", f"{instance} >= {schema['exclusiveMaximum']}")
            )

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(Error(pointer, "minItems", f"元素数 {len(instance)} < {schema['minItems']}"))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(Error(pointer, "maxItems", f"元素数 {len(instance)} > {schema['maxItems']}"))
        if schema.get("uniqueItems") is True:
            seen: dict[str, int] = {}
            for index, item in enumerate(instance):
                key = _canonical(item)
                if key in seen:
                    errors.append(
                        Error(pointer, "uniqueItems", f"元素 {index} 与 {seen[key]} 重复")
                    )
                else:
                    seen[key] = index
        if "items" in schema:
            for index, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], f"{pointer}[{index}]", root, depth + 1))

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        pattern_properties = schema.get("patternProperties", {})
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(Error(pointer, "required", f"缺少必填字段 {name!r}"))
        for name, sub_schema in properties.items():
            if name in instance:
                errors.extend(validate(instance[name], sub_schema, _child(pointer, name), root, depth + 1))
        if "propertyNames" in schema:
            for name in instance:
                for error in validate(name, schema["propertyNames"], pointer, root, depth + 1):
                    errors.append(error)
        additional = schema.get("additionalProperties", True)
        if additional is not True:
            for name, value in instance.items():
                if name in properties:
                    continue
                if any(re.search(pattern, name) for pattern in pattern_properties):
                    continue
                if additional is False:
                    errors.append(
                        Error(pointer, "additionalProperties", f"不允许未声明字段 {name!r}")
                    )
                else:
                    errors.extend(validate(value, additional, _child(pointer, name), root, depth + 1))

    for sub_schema in schema.get("allOf", []):
        errors.extend(validate(instance, sub_schema, pointer, root, depth + 1))
    if "anyOf" in schema:
        if not any(not validate(instance, sub, pointer, root, depth + 1) for sub in schema["anyOf"]):
            errors.append(Error(pointer, "anyOf", "没有任何 anyOf 分支通过"))
    if "oneOf" in schema:
        passed = sum(1 for sub in schema["oneOf"] if not validate(instance, sub, pointer, root, depth + 1))
        if passed != 1:
            errors.append(Error(pointer, "oneOf", f"通过分支数 {passed} != 1"))
    if "not" in schema and not validate(instance, schema["not"], pointer, root, depth + 1):
        errors.append(Error(pointer, "not", "实例命中了 not 分支"))
    if "if" in schema:
        if not validate(instance, schema["if"], pointer, root, depth + 1):
            if "then" in schema:
                errors.extend(validate(instance, schema["then"], pointer, root, depth + 1))
        elif "else" in schema:
            errors.extend(validate(instance, schema["else"], pointer, root, depth + 1))

    return errors


# --------------------------------------------------------------------------- #
# schema lint
# --------------------------------------------------------------------------- #


def lint_schema(contract: str, schema: Any) -> list[str]:
    issues: list[str] = []
    if not isinstance(schema, dict):
        return [f"{contract}: 根节点必须是 JSON 对象"]

    if schema.get("$schema") != DRAFT_2020_12:
        issues.append(f"{contract}: $schema 必须为 {DRAFT_2020_12}")
    schema_id = schema.get("$id")
    if not isinstance(schema_id, str) or not schema_id.startswith("https://"):
        issues.append(f"{contract}: 必须有绝对 https $id")
    if not isinstance(schema.get("title"), str) or not schema.get("title"):
        issues.append(f"{contract}: 必须有非空 title")
    if schema.get("type") != "object":
        issues.append(f"{contract}: 根 type 必须为 object")
    if "additionalProperties" not in schema:
        issues.append(f"{contract}: 根必须显式声明 additionalProperties")
    elif schema["additionalProperties"] is not False:
        issues.append(f"{contract}: 根 additionalProperties 必须为 false（未知顶层字段拒绝）")

    properties = schema.get("properties")
    if not isinstance(properties, dict):
        issues.append(f"{contract}: 必须有 properties")
        properties = {}
    version_schema = properties.get("schema_version")
    if not isinstance(version_schema, dict):
        issues.append(f"{contract}: 必须声明 schema_version")
    elif version_schema.get("const") != SCHEMA_VERSION_CONST:
        issues.append(f"{contract}: schema_version.const 必须为 {SCHEMA_VERSION_CONST!r}")
    if "schema_version" not in schema.get("required", []):
        issues.append(f"{contract}: schema_version 必须在 required 中")

    def walk(node: Any, path: str, conditional: bool = False) -> None:
        if isinstance(node, bool):
            return
        if not isinstance(node, dict):
            issues.append(f"{contract}: {path} 不是合法的 schema 节点")
            return
        for keyword in node:
            if keyword not in IMPLEMENTED_KEYWORDS:
                issues.append(f"{contract}: {path} 含未实现/未知关键字 {keyword!r}")
        if "properties" in node and not isinstance(node["properties"], dict):
            issues.append(f"{contract}: {path}.properties 必须是对象")
        # 对象形状必须显式声明 additionalProperties；if/then/else 里的投影子 schema 只约束已有字段，
        # 不是新的对象形状，因此不要求（也不能）声明 additionalProperties。
        if node.get("type") == "object" and "additionalProperties" not in node:
            issues.append(f"{contract}: {path} 是对象 schema 但未显式声明 additionalProperties")
        if "properties" in node and node.get("type") != "object" and not conditional:
            issues.append(f"{contract}: {path} 含 properties 但未声明 type: object")
        required = node.get("required")
        sub_properties = node.get("properties") or {}
        if isinstance(required, list):
            for name in required:
                if name not in sub_properties:
                    issues.append(f"{contract}: {path}.required 含未声明字段 {name!r}")
        if "pattern" in node:
            try:
                re.compile(node["pattern"])
            except re.error as exc:
                issues.append(f"{contract}: {path}.pattern 无法编译：{exc}")
        if "format" in node and node["format"] not in SUPPORTED_FORMATS:
            issues.append(f"{contract}: {path}.format 未支持：{node['format']!r}")
        if "$ref" in node and not (isinstance(node["$ref"], str) and node["$ref"].startswith("#/")):
            issues.append(f"{contract}: {path}.$ref 必须是本地引用")
        if "enum" in node:
            enum = node["enum"]
            if not isinstance(enum, list) or not enum:
                issues.append(f"{contract}: {path}.enum 必须是非空数组")
            else:
                keys = [_canonical(item) for item in enum]
                if len(set(keys)) != len(keys):
                    issues.append(f"{contract}: {path}.enum 存在重复项")
        for keyword in MAP_CHILD_KEYWORDS:
            mapping = node.get(keyword)
            if isinstance(mapping, dict):
                for name, sub in mapping.items():
                    walk(sub, f"{path}.{keyword}.{name}", conditional)
        for keyword in SINGLE_CHILD_KEYWORDS:
            if keyword in node:
                walk(node[keyword], f"{path}.{keyword}", conditional or keyword in ("if", "then", "else"))
        for keyword in LIST_CHILD_KEYWORDS:
            children = node.get(keyword)
            if isinstance(children, list):
                for index, sub in enumerate(children):
                    walk(sub, f"{path}.{keyword}[{index}]", conditional)

    walk(schema, "$")
    return issues


# --------------------------------------------------------------------------- #
# 语义不变量（JSON Schema 无法表达）
# --------------------------------------------------------------------------- #


def sem_nodespec_01(doc: dict[str, Any]) -> list[Error]:
    """SEM-NS-01：节点不得依赖自身（自依赖）。"""
    node_id = doc.get("node_id")
    depends_on = doc.get("depends_on") or []
    if isinstance(node_id, str) and isinstance(depends_on, list) and node_id in depends_on:
        return [Error("$.depends_on", "SEM-NS-01", f"节点不能依赖自身：{node_id!r}")]
    return []


def sem_verificationreport_01(doc: dict[str, Any]) -> list[Error]:
    """SEM-VR-01：passed<=required 且 missing==required-passed。"""
    coverage = doc.get("required_check_coverage")
    if not isinstance(coverage, dict):
        return []
    required = coverage.get("required")
    passed = coverage.get("passed")
    missing = coverage.get("missing")
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in (required, passed, missing)):
        return []
    errors: list[Error] = []
    if passed > required:
        errors.append(
            Error("$.required_check_coverage", "SEM-VR-01", f"passed={passed} 大于 required={required}")
        )
    if missing != required - passed:
        errors.append(
            Error(
                "$.required_check_coverage",
                "SEM-VR-01",
                f"missing={missing} 不等于 required-passed={required - passed}",
            )
        )
    return errors


def sem_verificationreport_02(doc: dict[str, Any]) -> list[Error]:
    """SEM-VR-02：final_state=VERIFIED 时不得存在必检项缺口。"""
    if doc.get("final_state") != "VERIFIED":
        return []
    coverage = doc.get("required_check_coverage")
    missing = coverage.get("missing") if isinstance(coverage, dict) else None
    if isinstance(missing, int) and not isinstance(missing, bool) and missing > 0:
        return [
            Error("$.final_state", "SEM-VR-02", f"VERIFIED 报告不得有缺口：missing={missing}")
        ]
    return []


SEMANTIC_CHECKS: dict[str, list[Any]] = {
    "taskspec": [],
    "nodespec": [sem_nodespec_01],
    "evidencerecord": [],
    "verificationreport": [sem_verificationreport_01, sem_verificationreport_02],
    "completioncertificate": [],
}


def run_semantic(contract: str, doc: dict[str, Any]) -> list[Error]:
    errors: list[Error] = []
    for check in SEMANTIC_CHECKS.get(contract, []):
        errors.extend(check(doc))
    return errors


# --------------------------------------------------------------------------- #
# 严格 JSON 装载
# --------------------------------------------------------------------------- #


def load_json_strict(path: Path) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        for key, _ in pairs:
            if key in seen:
                raise ContractLoadError("duplicate-key", f"重复键 {key!r}")
            seen.add(key)
        return dict(pairs)

    def reject_constant(token: str) -> Any:
        raise ContractLoadError("non-finite-number", f"出现非有限数 {token}")

    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text, object_pairs_hook=no_duplicates, parse_constant=reject_constant)
    except json.JSONDecodeError as exc:
        raise ContractLoadError("json-syntax", f"JSON 语法错误：{exc}") from exc


# --------------------------------------------------------------------------- #
# 用例执行
# --------------------------------------------------------------------------- #


@dataclass
class CaseResult:
    contract: str
    file: str
    layer: str
    expected: str
    status: str  # PASS / FAIL
    detail: str
    covers: str = ""


def _match_errors(errors: Iterable[Error], keyword: str, pointer: str) -> bool:
    return any(error.keyword == keyword and error.pointer == pointer for error in errors)


def run_case(case: dict[str, Any], schemas: dict[str, Any]) -> CaseResult:
    contract = case["contract"]
    layer = case["layer"]
    expected = case["expect"]
    path = EXAMPLES_DIR / case["file"]
    detail = ""
    status = "PASS"

    if not path.is_file():
        return CaseResult(contract, case["file"], layer, expected, "FAIL", "文件不存在")

    if layer == "json":
        try:
            load_json_strict(path)
        except ContractLoadError as exc:
            if expected == "invalid" and exc.keyword == case["keyword"]:
                return CaseResult(contract, case["file"], layer, expected, "PASS", f"{exc.keyword} @ {exc.pointer}")
            return CaseResult(
                contract, case["file"], layer, expected, "FAIL", f"实际拒绝原因 {exc.keyword} != 期望 {case['keyword']}"
            )
        return CaseResult(contract, case["file"], layer, expected, "FAIL", "期望被 JSON 层拒绝，实际装载成功")

    try:
        doc = load_json_strict(path)
    except ContractLoadError as exc:
        return CaseResult(contract, case["file"], layer, expected, "FAIL", f"JSON 层拒绝：{exc}")

    schema_errors = validate(doc, schemas[contract])
    semantic_errors = run_semantic(contract, doc) if layer == "semantic" else []

    if expected == "valid":
        errors = schema_errors + semantic_errors
        if errors:
            return CaseResult(
                contract,
                case["file"],
                layer,
                expected,
                "FAIL",
                "正例被拒：" + "; ".join(error.render() for error in errors[:3]),
            )
        return CaseResult(contract, case["file"], layer, expected, "PASS", "通过")

    keyword = case["keyword"]
    pointer = case["pointer"]
    if layer == "semantic":
        if schema_errors:
            return CaseResult(
                contract,
                case["file"],
                layer,
                expected,
                "FAIL",
                "语义反例必须先通过结构校验，实际结构错误：" + "; ".join(e.render() for e in schema_errors[:3]),
            )
        errors = semantic_errors
    else:
        errors = schema_errors

    if not errors:
        return CaseResult(contract, case["file"], layer, expected, "FAIL", "反例未被拒绝")
    if not _match_errors(errors, keyword, pointer):
        actual = "; ".join(error.render() for error in errors[:3])
        return CaseResult(
            contract,
            case["file"],
            layer,
            expected,
            "FAIL",
            f"拒绝原因不匹配：期望 {keyword} @ {pointer}；实际 {actual}",
        )
    return CaseResult(contract, case["file"], layer, expected, "PASS", f"{keyword} @ {pointer}")


# --------------------------------------------------------------------------- #
# 覆盖检查
# --------------------------------------------------------------------------- #


def check_coverage(manifest: dict[str, Any], schemas: dict[str, Any], strict_files: bool = True) -> list[str]:
    problems: list[str] = []
    cases = manifest.get("cases", [])
    if not isinstance(cases, list) or not cases:
        return ["manifest.cases 为空"]

    listed: dict[str, int] = {}
    for case in cases:
        name = case.get("file", "")
        listed[name] = listed.get(name, 0) + 1
    for name, count in listed.items():
        if count > 1:
            problems.append(f"manifest: {name} 被登记 {count} 次")
    if strict_files:
        on_disk = {p.name for p in EXAMPLES_DIR.glob("*.json") if p.name != "manifest.json"}
        for name in sorted(on_disk - set(listed)):
            problems.append(f"examples: {name} 存在但未登记到 manifest")
        for name in sorted(set(listed) - on_disk):
            problems.append(f"examples: {name} 已登记但文件缺失")

    for contract in schemas:
        contract_cases = [c for c in cases if c.get("contract") == contract]
        positives = [c for c in contract_cases if c.get("expect") == "valid"]
        negatives = [c for c in contract_cases if c.get("expect") == "invalid"]
        if len(positives) != 1:
            problems.append(f"{contract}: 正例必须恰好 1 个，实际 {len(positives)}")
        if len(negatives) < 5:
            problems.append(f"{contract}: 反例少于 5 个，实际 {len(negatives)}")
        layers = {c.get("layer") for c in negatives}
        if "schema" not in layers:
            problems.append(f"{contract}: 缺少 schema 层反例")
        if SEMANTIC_CHECKS.get(contract) and "semantic" not in layers:
            problems.append(f"{contract}: 已登记语义检查但缺少 semantic 层反例")
    for contract in cases:
        if contract.get("contract") not in schemas:
            problems.append(f"manifest: 未知契约 {contract.get('contract')!r}")
    return problems


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #


SELFTEST_PAIRS: list[tuple[str, Any, Any, str | None, str | None, str | None]] = [
    # (说明, schema, instance, 期望 keyword, 期望 pointer, 期望层)
    (
        "const 通过",
        {"type": "object", "properties": {"v": {"const": "1.0"}}, "required": ["v"], "additionalProperties": False},
        {"v": "1.0"},
        None,
        None,
        None,
    ),
    (
        "const 拒绝",
        {"type": "object", "properties": {"v": {"const": "1.0"}}, "required": ["v"], "additionalProperties": False},
        {"v": "2.0"},
        "const",
        "$.v",
        None,
    ),
    (
        "required 拒绝",
        {"type": "object", "properties": {"v": {"const": "1.0"}}, "required": ["v"], "additionalProperties": False},
        {},
        "required",
        "$",
        None,
    ),
    (
        "additionalProperties 拒绝",
        {"type": "object", "properties": {"v": {"type": "string"}}, "required": [], "additionalProperties": False},
        {"v": "x", "extra": 1},
        "additionalProperties",
        "$",
        None,
    ),
    (
        "pattern 拒绝",
        {"type": "object", "properties": {"h": {"pattern": "^[0-9a-f]{4}$"}}, "required": [], "additionalProperties": False},
        {"h": "ABCD"},
        "pattern",
        "$.h",
        None,
    ),
    (
        "if/then 拒绝",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["level", "producer"],
            "properties": {"level": {"enum": ["E2"]}, "producer": {"type": "string"}},
            "allOf": [
                {
                    "if": {"properties": {"level": {"const": "E2"}}, "required": ["level"]},
                    "then": {"properties": {"producer": {"const": "collector"}}},
                }
            ],
        },
        {"level": "E2", "producer": "agent"},
        "const",
        "$.producer",
        None,
    ),
    (
        "maxItems 拒绝",
        {"type": "object", "properties": {"a": {"type": "array", "maxItems": 0}}, "required": [], "additionalProperties": False},
        {"a": ["x"]},
        "maxItems",
        "$.a",
        None,
    ),
    (
        "uniqueItems 拒绝",
        {"type": "object", "properties": {"a": {"type": "array", "uniqueItems": True}}, "required": [], "additionalProperties": False},
        {"a": ["x", "x"]},
        "uniqueItems",
        "$.a",
        None,
    ),
    (
        "format 接受合法 RFC 3339（UTC 约束由 pattern 承担）",
        {"type": "object", "properties": {"t": {"format": "date-time"}}, "required": [], "additionalProperties": False},
        {"t": "2026-11-09T17:30:00+08:00"},
        None,
        None,
        "format 只判断 RFC 3339 合法性；是否 UTC 由 pattern 拒绝",
    ),
    (
        "format 拒绝非法日历日期",
        {"type": "object", "properties": {"t": {"format": "date-time"}}, "required": [], "additionalProperties": False},
        {"t": "2026-13-01T00:00:00Z"},
        "format",
        "$.t",
        None,
    ),
]


def run_selftest() -> int:
    failures = 0
    for index, (label, schema, instance, keyword, pointer, note) in enumerate(SELFTEST_PAIRS, start=1):
        errors = validate(instance, schema)
        if keyword is None:
            ok = not errors
            detail = "通过" if ok else errors[0].render()
        else:
            ok = _match_errors(errors, keyword, pointer)
            detail = errors[0].render() if errors else "未被拒绝"
        status = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        suffix = f"  # {note}" if note else ""
        print(f"[{status}] selftest.{index:02d} {label}: {detail}{suffix}")
    print(f"SELFTEST {len(SELFTEST_PAIRS) - failures}/{len(SELFTEST_PAIRS)} PASS")
    return 0 if failures == 0 else 1


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def load_schemas() -> tuple[dict[str, Any], list[str]]:
    schemas: dict[str, Any] = {}
    problems: list[str] = []
    for path in sorted(CONTRACTS_DIR.glob("*.schema.json")):
        contract = path.name[: -len(".schema.json")]
        try:
            schemas[contract] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}: JSON 语法错误 {exc}")
            continue
        for issue in lint_schema(contract, schemas[contract]):
            problems.append(f"{path.name}: {issue}")
    if not schemas:
        problems.append("contracts/ 下没有 *.schema.json")
    return schemas, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ResearchFlow G0 契约正/反例校验器")
    parser.add_argument("--selftest", action="store_true", help="只跑校验器自检")
    parser.add_argument("--contract", help="只校验指定契约（文件名前缀，如 taskspec）")
    parser.add_argument("--verbose", action="store_true", help="输出每条用例的细节")
    args = parser.parse_args(argv)

    if args.selftest:
        print(f"CONTRACTS_SELFTEST root={REPO_ROOT} python={sys.version.split()[0]}")
        return run_selftest()

    print(f"CONTRACTS_VALIDATE root={REPO_ROOT} python={sys.version.split()[0]} engine=builtin-2020-12-subset")
    if not MANIFEST_PATH.is_file():
        print(f"ENVIRONMENT_ERROR manifest 缺失：{MANIFEST_PATH}")
        return 2

    schemas, problems = load_schemas()
    if args.contract:
        if args.contract not in schemas:
            print(f"ENVIRONMENT_ERROR 未找到契约 {args.contract!r}")
            return 2
        schemas = {args.contract: schemas[args.contract]}

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    cases = [case for case in manifest.get("cases", []) if case.get("contract") in schemas]

    coverage_problems = check_coverage({"cases": cases}, schemas, strict_files=not args.contract)
    if problems or coverage_problems:
        for item in problems:
            print(f"[FAIL] lint    {item}")
        for item in coverage_problems:
            print(f"[FAIL] coverage {item}")
        print(f"SUMMARY lint_fail={len(problems)} coverage_fail={len(coverage_problems)} exit=1")
        return 1

    results = [replace(run_case(case, schemas), covers=case.get("covers", "")) for case in cases]
    for result in results:
        print(
            f"[{result.status}] {result.contract:<22} {result.layer:<8} {result.file:<34} {result.detail}"
        )
        if args.verbose and result.covers:
            print(f"        covers: {result.covers}")

    passed = sum(1 for result in results if result.status == "PASS")
    failed = len(results) - passed
    for contract in schemas:
        subset = [result for result in results if result.contract == contract]
        ok = sum(1 for result in subset if result.status == "PASS")
        print(
            f"CONTRACT {contract:<22} cases={len(subset):<3} pass={ok:<3} "
            f"fail={len(subset) - ok:<3} {'PASS' if ok == len(subset) and subset else 'FAIL'}"
        )

    print(f"SUMMARY contracts={len(schemas)} cases={len(results)} pass={passed} fail={failed} exit={0 if failed == 0 else 1}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())