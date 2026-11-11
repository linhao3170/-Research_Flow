"""MODULE: M11 · verifier/crypto/jcs.py — RFC 8785 JCS 规范化与严格 JSON 解析（P6 伪代码）
阶段/追踪: P6「签名与离线凭证」｜FR-008、NFR-05、策划书 §7.5（P0174–P0178）、附录 D.6（P0575–P0577）
FR/依赖: FR-008；被 payloads.py、ed25519_signer.py、bundle.packager、verify_bundle 调用；**不依赖数据库与模型**
不变量/错误码: 只排对象键、数组严格保序；拒绝重复键/NaN/Infinity/孤立代理项/非法 JSON；数字按 JCS/ECMAScript
              规范化，不做四舍五入；输出 UTF-8 无 BOM。错误码：SCHEMA_INVALID（422）+
              reason ∈ {JCS_DUPLICATE_KEY, JCS_NON_FINITE, JCS_INVALID_UNICODE, JCS_UNSAFE_INTEGER,
              JCS_UNSUPPORTED_TYPE, JCS_KEY_NOT_STRING, JCS_DEPTH_EXCEEDED, JCS_INVALID_JSON}
写入者: **无**；纯函数，只返回对象/bytes，不写文件、不写日志、不写证据、不碰私钥
状态: 伪代码；标准测试向量与 WP-11 落地属实现阶段，本文件只钉算法、拒绝点与反例

## 为什么不能用 `json.dumps(..., sort_keys=True)` 冒充 JCS

  1. **键序不同**：Python `sort_keys` 按 Unicode 码点排序；RFC 8785 按 UTF-16 code unit 排序。
     astral 字符（emoji、部分 CJK 扩展）在 UTF-16 中是代理对（0xD800–0xDFFF），
     码点 U+1F600 会排在 U+FF01 之后，而 UTF-16 序中 0xD83D 在 0xFF01 之前。
     两套序在跨语言验签时会产生不同字节，签名必然对不上。
  2. **数字格式不同**：Python `repr(float)` 与 ECMAScript `Number::toString` 在
     `1e20`、`1e-7`、`-0.0` 等边界上的输出不同；JCS 规定按 ECMAScript 规则。
  3. **默认转义不同**：`json.dumps` 默认 `ensure_ascii=True`，会把非 ASCII 转成 `\\uXXXX`；
     JCS 要求直接输出 UTF-8。`ensure_ascii=False` 仍不处理代理项与 `/` 的细节。
  4. **不拒绝重复键**：`json.loads` 默认“后者覆盖前者”，重复键会被静默吞掉；
     JCS 输入必须是合法 JSON，且附录 D.6 明确禁止重复键。
  5. **不拒绝 NaN/Infinity**：Python 默认接受；JCS 只允许有限数。

  因此本文件自己实现：严格解析 → 递归校验 → 规范化序列化；**不得**把
  `json.dumps` 的结果当作 JCS 字节。

## 数组保序（显式反例）

  输入 A：`{"tags": ["b", "a"], "nested": [{"k": 2}, {"k": 1}]}`
  输入 B：`{"tags": ["a", "b"], "nested": [{"k": 1}, {"k": 2}]}`

  JCS(A) = `{"nested":[{"k":2},{"k":1}],"tags":["b","a"]}`
  JCS(B) = `{"nested":[{"k":1},{"k":2}],"tags":["a","b"]}`

  **`JCS(A) != JCS(B)`**。若实现把数组整体按字典序重排，两者会相等——
  这是签名语义被改变的硬错误，不是“格式更整齐”。`assert_array_order_is_preserved()`
  把这条反例固化成可断言函数；`GUARD-M11-01` 以“两者必须不同”为通过条件。

## 拒绝项与拒绝点（附录 D.6 / 7.5）

  | 拒绝项 | 拒绝点 | reason |
  |---|---|---|
  | 重复键 | **解析层** `_no_duplicate_pairs` | `JCS_DUPLICATE_KEY` |
  | `NaN` / `Infinity` / `-Infinity` | 解析层 `_reject_non_finite`；规范化层再查一次 | `JCS_NON_FINITE` |
  | 非法 UTF-8 / 非法 JSON / BOM | 解析层 | `JCS_INVALID_JSON` |
  | 孤立代理项（lone surrogate） | 字符串校验与 UTF-8 编码 | `JCS_INVALID_UNICODE` |
  | 非字符串对象键 | 规范化层 | `JCS_KEY_NOT_STRING` |
  | 超出 IEEE-754 安全整数范围 | 规范化层 | `JCS_UNSAFE_INTEGER` |
  | 非 JSON 类型（set/datetime/Decimal 等） | 规范化层 | `JCS_UNSUPPORTED_TYPE` |
  | 嵌套过深 | 解析层与规范化层 | `JCS_DEPTH_EXCEEDED` |

## 与 M01 `contracts/parsing.py` 的关系

  M01 的 `loads_strict` 是**生产解析器**；本文件为离线验签工具提供同口径的最小实现
  （`NFR-07`：证据包在无数据库环境独立验证）。两者必须对同一语料给出相同的接受/拒绝结论；
  发生分歧时以冻结的附录 D.6 与 RFC 8785 为准，并登记 OQ，不得各改一边。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Final, Mapping, TypeAlias, Union

__all__ = [
    "ARRAY_ORDER_COUNTEREXAMPLE",
    "ECMASCRIPT_NUMBER_NOTE",
    "JCS_STRING_ESCAPES",
    "MAX_DEPTH",
    "MAX_SAFE_INTEGER",
    "MIN_SAFE_INTEGER",
    "JcsError",
    "assert_array_order_is_preserved",
    "assert_utf16_sort_not_codepoint_sort",
    "canonicalize",
    "loads_strict",
    "parse_strict",
    "utf16_sort_key",
    "validate_value",
]

JsonScalar: TypeAlias = Union[str, int, float, bool, None]
JsonValue: TypeAlias = Union[JsonScalar, list["JsonValue"], dict[str, "JsonValue"]]

# 非契约常量：只防病态输入，不写成接口上限。
MAX_DEPTH: Final[int] = 64
MAX_SAFE_INTEGER: Final[int] = 2**53 - 1
MIN_SAFE_INTEGER: Final[int] = -(2**53 - 1)

# JCS 字符串转义表：只转义必须转义的字符；`/` 不转义，非 ASCII 不转成 \\uXXXX。
JCS_STRING_ESCAPES: Final[Mapping[str, str]] = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}

# 显式反例：第一项是原顺序的 JCS 输出，第二项是“若错误地整体排序数组”会得到的输出。
ARRAY_ORDER_COUNTEREXAMPLE: Final[tuple[bytes, bytes]] = (
    b'{"nested":[{"k":2},{"k":1}],"tags":["b","a"]}',
    b'{"nested":[{"k":1},{"k":2}],"tags":["a","b"]}',
)

# 数字规范的实现提示：不得直接用 Python repr 作为最终实现，必须用通过 RFC 8785 测试向量的
# ECMAScript 数字序列化（如 Ryu / 双转换算法）。本文件只写算法骨架。
ECMASCRIPT_NUMBER_NOTE: Final[str] = (
    "JCS numbers follow ECMAScript Number::toString; use an RFC 8785-verified serializer, "
    "not json.dumps/repr, for cross-language signatures."
)

_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"^(\d+)\.(\d+)$")
_UTF16_BE: Final[str] = "utf-16-be"


class JcsError(ValueError):
    """JCS 解析/规范化拒绝。

    职责：把“哪一步、哪个字段、为什么拒绝”固定成可断言的 reason + field_path。
    输入：reason、message、field_path、detail。
    输出：异常（不返回部分结果）。
    副作用：无。
    不变量：`error_code` 恒为 `SCHEMA_INVALID`，`http_status` 恒为 422；
             不得把 Python 内部异常类型/堆栈写进 message 给最终用户。
    错误：本类自身；调用方必须按 reason 断言，不能只断言“抛了异常”。
    """

    error_code: Final[str] = "SCHEMA_INVALID"
    http_status: Final[int] = 422

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        field_path: str = "payload",
        detail: Mapping[str, object] | None = None,
    ) -> None:
        self.reason = reason
        self.field_path = field_path
        self.detail = dict(detail or {})
        super().__init__(f"{self.error_code}/{reason} @ {field_path}: {message}")


# ---------------------------------------------------------------------------
# 1. 严格解析（重复键 / 非有限数 / BOM / 非法 UTF-8）
# ---------------------------------------------------------------------------
def parse_strict(data: str | bytes) -> JsonValue:
    """按 JSON + 附录 D.6 约束解析文本，拒绝 `json.loads` 默认会放过的输入。

    职责：把字节/字符串解析成 JSON 值，并在解析层拒绝重复键、NaN/Infinity、BOM、非法 UTF-8。
    输入：`str`（已是文本）或 `bytes`（严格 UTF-8）。
    输出：`JsonValue`；对象为 `dict[str, JsonValue]`，数组为 `list[JsonValue]`。
    副作用：无；不写文件、不写日志。
    不变量：返回的对象不含重复键；不含非有限数；不含孤立代理项；嵌套深度 ≤ MAX_DEPTH。
    错误：`JcsError`（reason = JCS_INVALID_JSON / JCS_DUPLICATE_KEY / JCS_NON_FINITE /
          JCS_INVALID_UNICODE / JCS_DEPTH_EXCEEDED）。
    """
    # 1. 字节按严格 UTF-8 解码；非法字节序列拒绝，不做 errors="replace"。
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise JcsError("JCS_INVALID_JSON", f"不是合法 UTF-8：{exc.reason}") from exc
    elif isinstance(data, str):
        text = data
    else:
        raise JcsError("JCS_INVALID_JSON", f"输入必须是 str/bytes，实际 {type(data).__name__}")

    # 2. 拒绝 BOM 与空文档；JCS 输出无 BOM，输入也不接受 BOM。
    if text.startswith("\ufeff"):
        raise JcsError("JCS_INVALID_JSON", "输入不得带 UTF-8 BOM")
    if not text.strip():
        raise JcsError("JCS_INVALID_JSON", "输入为空")

    # 3. 用三个 hook 把解析层的漏洞堵死：
    #    object_pairs_hook 查重复键；parse_constant 拒 NaN/Infinity；parse_float/int 保持原类型。
    try:
        value = json.loads(
            text,
            object_pairs_hook=_no_duplicate_pairs,
            parse_constant=_reject_non_finite,
            parse_float=float,
            parse_int=int,
        )
    except JcsError:
        raise
    except json.JSONDecodeError as exc:
        raise JcsError(
            "JCS_INVALID_JSON",
            f"非法 JSON：{exc.msg}（line={exc.lineno}, column={exc.colno}）",
        ) from exc

    # 4. 递归校验类型、深度、Unicode、数字范围；不依赖 json 模块的宽松行为。
    validate_value(value)

    # 5. 返回已校验的值。
    return value


def loads_strict(data: str | bytes) -> JsonValue:
    """`parse_strict` 的同义入口；保留独立名字，避免调用方误用 `json.loads`。"""
    return parse_strict(data)


def _no_duplicate_pairs(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    """`object_pairs_hook`：同一对象内重复键立即拒绝，不采用“后者覆盖前者”。

    职责：把 JSON 对象构造为 dict，同时检查键重复。
    输入：json 模块给出的 (key, value) 顺序对。
    输出：dict。
    副作用：无。
    不变量：键必须是 str；每个键最多出现一次。
    错误：`JcsError(JCS_DUPLICATE_KEY)`；`JcsError(JCS_KEY_NOT_STRING)`。
    """
    # 1. 逐对检查键类型。
    result: dict[str, JsonValue] = {}
    seen: set[str] = set()
    for key, value in pairs:
        # 1.1 JSON 语法保证键是字符串；这里再查一次，防自定义 hook 调用。
        if not isinstance(key, str):
            raise JcsError("JCS_KEY_NOT_STRING", f"对象键必须是字符串，实际 {type(key).__name__}")
        # 1.2 重复键拒绝；不得静默覆盖，也不得合并。
        if key in seen:
            raise JcsError(
                "JCS_DUPLICATE_KEY",
                f"对象内重复键 {key!r}",
                field_path=key,
            )
        # 1.3 记录并写入。
        seen.add(key)
        result[key] = value
    # 2. 返回构造结果。
    return result


def _reject_non_finite(token: str) -> JsonValue:
    """`parse_constant`：拒绝 `NaN` / `Infinity` / `-Infinity`，不转成 null 或 0。"""
    raise JcsError("JCS_NON_FINITE", f"JSON 不允许非有限数：{token!r}")


# ---------------------------------------------------------------------------
# 2. 递归校验（类型 / 深度 / Unicode / 数字范围）
# ---------------------------------------------------------------------------
def validate_value(
    value: object,
    *,
    field_path: str = "payload",
    _depth: int = 0,
) -> None:
    """检查一个 Python 值是否可被 JCS 规范化；只校验，不返回新对象。

    职责：统一拒绝非 JSON 类型、超深嵌套、孤立代理项、非有限数与超安全整数。
    输入：任意 Python 对象；field_path 用于错误定位；_depth 为内部递归计数。
    输出：None；通过即静默返回。
    副作用：无。
    不变量：接受集合 = JSON 标量 + list + dict[str, ...]；bool 不得被当作 int。
    错误：`JcsError`（reason 见模块头表）。
    """
    # 1. 深度保护：超过上限即拒绝，避免递归栈耗尽。
    if _depth > MAX_DEPTH:
        raise JcsError(
            "JCS_DEPTH_EXCEEDED",
            f"嵌套深度超过 {MAX_DEPTH}",
            field_path=field_path,
        )

    # 2. 标量：None / bool / str / int / float。
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        # 2.1 字符串必须能编码为 UTF-8；孤立代理项在此被拒。
        _assert_valid_unicode(value, field_path)
        return
    if isinstance(value, int):
        # 2.2 整数必须在 IEEE-754 安全范围内；超出会跨语言丢精度。
        if value > MAX_SAFE_INTEGER or value < MIN_SAFE_INTEGER:
            raise JcsError(
                "JCS_UNSAFE_INTEGER",
                f"整数超出 IEEE-754 安全范围：{value}",
                field_path=field_path,
            )
        return
    if isinstance(value, float):
        # 2.3 只允许有限数；-0.0 合法，序列化为 0。
        if not math.isfinite(value):
            raise JcsError("JCS_NON_FINITE", f"非有限浮点数：{value!r}", field_path=field_path)
        return

    # 3. 数组：只接受 list；tuple 不自动转换，避免调用方误以为会被接受。
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_value(item, field_path=f"{field_path}[{index}]", _depth=_depth + 1)
        return

    # 4. 对象：键必须是 str；递归检查每个值。
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise JcsError(
                    "JCS_KEY_NOT_STRING",
                    f"对象键必须是字符串，实际 {type(key).__name__}",
                    field_path=field_path,
                )
            _assert_valid_unicode(key, f"{field_path}.<key>")
            validate_value(item, field_path=f"{field_path}.{key}", _depth=_depth + 1)
        return

    # 5. 其他类型（set/tuple/datetime/Decimal/bytes）一律拒绝，不尝试“猜”转换。
    raise JcsError(
        "JCS_UNSUPPORTED_TYPE",
        f"不是 JSON 类型：{type(value).__name__}",
        field_path=field_path,
    )


def _assert_valid_unicode(text: str, field_path: str) -> None:
    """拒绝孤立代理项；其他 Unicode 码点（含非 BMP 字符）原样保留。

    职责：把“字符串是否能编码为 UTF-8”作为唯一 Unicode 合法性判据。
    输入：str 与字段路径。
    输出：None。
    副作用：无。
    不变量：不做 NFC/NFD、不做大小写折叠——任何规范化都会改变字面值。
    错误：`JcsError(JCS_INVALID_UNICODE)`。
    """
    # 1. 用严格 UTF-8 编码探测孤立代理项；不做任何替换。
    try:
        text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise JcsError(
            "JCS_INVALID_UNICODE",
            f"字符串含孤立代理项或不可编码字符（position={exc.start}）",
            field_path=field_path,
        ) from exc
    # 2. 通过即返回。
    return


# ---------------------------------------------------------------------------
# 3. 规范化序列化
# ---------------------------------------------------------------------------
def canonicalize(value: object) -> bytes:
    """按 RFC 8785 生成规范化 UTF-8 字节串（无 BOM、无多余空白）。

    职责：对象键递归排序、数组保序、字符串按 JCS 转义、数字按 ECMAScript 规则输出。
    输入：JSON 值（见 `validate_value`）。
    输出：UTF-8 字节串。
    副作用：无。
    不变量：
      1. 同一语义对象多次调用得到逐字节相同的输出；
      2. 数组元素顺序严格保持输入顺序（见模块头反例）；
      3. 对象键按 UTF-16 code unit 排序，不按 Python 默认码点序；
      4. 输出不以 BOM 开头、末尾无换行。
    错误：`JcsError`；不会返回“部分规范化”的结果。
    """
    # 1. 先完整校验，避免写到一半才发现非法值。
    validate_value(value)

    # 2. 递归写入片段；用 list 收集，最后一次性 join，避免 O(n^2) 拼接。
    chunks: list[str] = []
    _write_value(value, chunks, field_path="payload", _depth=0)

    # 3. 编码为 UTF-8；此处不再做 errors="replace"。
    try:
        return "".join(chunks).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise JcsError("JCS_INVALID_UNICODE", f"规范化结果无法编码为 UTF-8：{exc.reason}") from exc


def _write_value(value: object, out: list[str], *, field_path: str, _depth: int) -> None:
    """把一个已校验的值写入片段列表；分支必须显式 return。"""
    # 1. 深度兜底（validate_value 已查过；这里是纵深防御）。
    if _depth > MAX_DEPTH:
        raise JcsError("JCS_DEPTH_EXCEEDED", f"嵌套深度超过 {MAX_DEPTH}", field_path=field_path)

    # 2. null / bool 必须先于 int 判断（bool 是 int 的子类）。
    if value is None:
        out.append("null")
        return
    if value is True:
        out.append("true")
        return
    if value is False:
        out.append("false")
        return

    # 3. 字符串。
    if isinstance(value, str):
        out.append(_serialize_string(value, field_path))
        return

    # 4. 整数与浮点数。
    if isinstance(value, int):
        out.append(_serialize_integer(value, field_path))
        return
    if isinstance(value, float):
        out.append(_serialize_float(value, field_path))
        return

    # 5. 数组：按原顺序逐个写入，**不排序、不去重**。
    if isinstance(value, list):
        out.append("[")
        for index, item in enumerate(value):
            if index > 0:
                out.append(",")
            _write_value(item, out, field_path=f"{field_path}[{index}]", _depth=_depth + 1)
        out.append("]")
        return

    # 6. 对象：键排序后写入；值递归规范化。
    if isinstance(value, Mapping):
        out.append("{")
        for index, key in enumerate(sorted(value.keys(), key=utf16_sort_key)):
            if not isinstance(key, str):
                raise JcsError(
                    "JCS_KEY_NOT_STRING",
                    f"对象键必须是字符串，实际 {type(key).__name__}",
                    field_path=field_path,
                )
            if index > 0:
                out.append(",")
            out.append(_serialize_string(key, f"{field_path}.<key>"))
            out.append(":")
            _write_value(
                value[key],
                out,
                field_path=f"{field_path}.{key}",
                _depth=_depth + 1,
            )
        out.append("}")
        return

    # 7. 理论上不可达；保持 fail-closed，不返回空串。
    raise JcsError(
        "JCS_UNSUPPORTED_TYPE",
        f"不是 JSON 类型：{type(value).__name__}",
        field_path=field_path,
    )


def utf16_sort_key(text: str) -> bytes:
    """JCS 对象键排序键：UTF-16 大端字节序，等价于 UTF-16 code unit 序。

    职责：给 `sorted(..., key=...)` 提供与 RFC 8785 一致的比较键。
    输入：str。
    输出：UTF-16BE 编码字节；逐字节比较即 code unit 比较。
    副作用：无。
    不变量：不做 Unicode 规范化；调用前字符串必须已通过 Unicode 校验。
    错误：`JcsError(JCS_INVALID_UNICODE)`。
    """
    # 1. 先校验孤立代理项；否则 utf-16-be 编码会抛 UnicodeEncodeError。
    _assert_valid_unicode(text, "payload.<key>")
    # 2. 返回无 BOM 的 UTF-16BE 字节。
    return text.encode(_UTF16_BE, errors="strict")


def _serialize_string(text: str, field_path: str) -> str:
    """按 JCS 规则输出带引号的字符串；只转义必须转义的字符。

    职责：`"`、`\\`、控制字符按表转义；`/` 不转义；非 ASCII 原样输出。
    输入：str 与字段路径。
    输出：含双引号的 JSON 字符串片段。
    副作用：无。
    不变量：控制字符 < 0x20 一律 `\\u00xx`（小写十六进制）；不产生 `\\/`。
    错误：`JcsError(JCS_INVALID_UNICODE)`。
    """
    # 1. 校验合法性。
    _assert_valid_unicode(text, field_path)

    # 2. 逐字符转义；用 list 避免字符串反复拼接。
    parts: list[str] = ['"']
    for char in text:
        # 2.1 固定转义表。
        if char in JCS_STRING_ESCAPES:
            parts.append(JCS_STRING_ESCAPES[char])
            continue
        # 2.2 其他控制字符统一 \\u00xx；不使用 \\x 或八进制。
        code = ord(char)
        if code < 0x20:
            parts.append(f"\\u{code:04x}")
            continue
        # 2.3 其余字符（含非 ASCII、U+2028/U+2029）原样输出；不做 HTML 安全转义。
        parts.append(char)
    parts.append('"')

    # 3. 返回片段。
    return "".join(parts)


def _serialize_integer(value: int, field_path: str) -> str:
    """整数按十进制输出；拒绝超出 IEEE-754 安全范围的值。

    职责：防止 `2^53+1` 这类整数在另一语言被读成相邻浮点数后签名对不上。
    输入：int（bool 已在上层排除）。
    输出：十进制字符串。
    副作用：无。
    不变量：不做千分位、不加 `+`、不加 `.0`。
    错误：`JcsError(JCS_UNSAFE_INTEGER)`。
    """
    # 1. 安全范围检查。
    if value > MAX_SAFE_INTEGER or value < MIN_SAFE_INTEGER:
        raise JcsError(
            "JCS_UNSAFE_INTEGER",
            f"整数超出 IEEE-754 安全范围：{value}",
            field_path=field_path,
        )
    # 2. Python int 的十进制表示没有前导零、没有 `+`，可直接使用。
    return str(value)


def _serialize_float(value: float, field_path: str) -> str:
    """浮点数按 ECMAScript Number::toString 规则输出；`-0.0` 输出 `0`。

    职责：把有限 float 转成 JCS 规定的十进制/指数形式。
    输入：有限 float。
    输出：字符串。
    副作用：无。
    不变量：不做四舍五入到固定小数位；不使用 `repr` 的 `e-07` 写法（指数不带前导零）。
    错误：`JcsError(JCS_NON_FINITE)`。
    """
    # 1. 非有限数拒绝；不转 null。
    if not math.isfinite(value):
        raise JcsError("JCS_NON_FINITE", f"非有限浮点数：{value!r}", field_path=field_path)

    # 2. 零（含 -0.0）统一输出 "0"；ECMAScript 不保留负零的字面形式。
    if value == 0.0:
        return "0"

    # 3. 分离符号后交给正数序列化器。
    if value < 0:
        return "-" + _serialize_positive_float(-value, field_path)
    return _serialize_positive_float(value, field_path)


def _serialize_positive_float(value: float, field_path: str) -> str:
    """正有限 float 的 ECMAScript 序列化骨架。

    职责：得到最短往返十进制数字，再按 ECMAScript 的 n/k 规则排版。
    输入：> 0 的有限 float。
    输出：字符串。
    副作用：无。
    不变量：指数形式不带前导零；`1e21` 起用指数，`1e-6` 仍用小数。
    错误：`JcsError`（仅防御性）。
    """
    # 1. 取最短往返数字。注意：Python repr 在极少数边界与 ECMAScript 的最短表示
    #    可能选择不同数字；落地实现必须换成通过 RFC 8785 测试向量的序列化器。
    # LIB: ECMAScript shortest round-trip digits; use a verified Ryu/Grisu implementation.
    text = repr(value)

    # 2. 拆成 digits（无小数点）+ 十进制点位置 n。
    if "e" in text or "E" in text:
        mantissa, exponent_text = re.split("[eE]", text, maxsplit=1)
        exponent = int(exponent_text)
    else:
        mantissa, exponent = text, 0

    if "." in mantissa:
        integer_part, fraction_part = mantissa.split(".", maxsplit=1)
    else:
        integer_part, fraction_part = mantissa, ""

    digits = integer_part + fraction_part
    point_position = len(integer_part) + exponent

    # 3. 去前导零（同时左移小数点）；至少保留一位数字。
    while len(digits) > 1 and digits[0] == "0":
        digits = digits[1:]
        point_position -= 1

    # 4. 去尾随零；最短表示不需要它们。
    while len(digits) > 1 and digits[-1] == "0":
        digits = digits[:-1]

    # 5. 按 ECMAScript 的 k/n 规则排版：
    #    k = 有效数字个数；n = 小数点位置（10^n 量级）。
    k = len(digits)
    n = point_position

    # 5.1 k <= n <= 21：整数，补 n-k 个零。
    if k <= n <= 21:
        return digits + "0" * (n - k)
    # 5.2 0 < n <= 21：小数点落在数字中间。
    if 0 < n <= 21:
        return digits[:n] + "." + digits[n:]
    # 5.3 -6 < n <= 0：0.00...digits。
    if -6 < n <= 0:
        return "0." + "0" * (-n) + digits
    # 5.4 其余用指数形式：d[.ddd]e±(n-1)，指数不带前导零。
    exponent_value = n - 1
    sign = "+" if exponent_value >= 0 else "-"
    mantissa_out = digits if k == 1 else digits[0] + "." + digits[1:]
    return f"{mantissa_out}e{sign}{abs(exponent_value)}"


# ---------------------------------------------------------------------------
# 4. 显式反例与一致性守卫（P6 验收判据 1）
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ArrayOrderCounterexample:
    """数组保序反例的断言结果；`preserved=False` 表示实现缺陷。"""

    original: bytes
    sorted_variant: bytes
    preserved: bool
    expected_original: bytes
    expected_sorted_variant: bytes


def assert_array_order_is_preserved() -> ArrayOrderCounterexample:
    """固化“数组不得整体排序”的反例，返回可断言的比较结果。

    职责：证明 JCS 只排对象键、不排数组；若两者相等，说明实现把数组排序了。
    输入：无。
    输出：`ArrayOrderCounterexample`；`preserved` 必须为 True。
    副作用：无。
    不变量：`original` 与 `sorted_variant` 必须不同；两者都等于模块头列出的期望字节。
    错误：`JcsError`（仅当输入构造失败；正常路径不抛）。
    """
    # 1. 构造仅数组顺序不同的两个对象。
    original = {"tags": ["b", "a"], "nested": [{"k": 2}, {"k": 1}]}
    sorted_variant = {"tags": ["a", "b"], "nested": [{"k": 1}, {"k": 2}]}

    # 2. 分别规范化。
    left = canonicalize(original)
    right = canonicalize(sorted_variant)

    # 3. 返回断言结果；调用方必须断言 preserved is True 且字节等于期望值。
    return ArrayOrderCounterexample(
        original=left,
        sorted_variant=right,
        preserved=left != right,
        expected_original=ARRAY_ORDER_COUNTEREXAMPLE[0],
        expected_sorted_variant=ARRAY_ORDER_COUNTEREXAMPLE[1],
    )


@dataclass(frozen=True, slots=True)
class Utf16SortCounterexample:
    """UTF-16 排序与 Python 码点排序的差异；`differs=False` 表示用了错误的排序。"""

    jcs_order: tuple[str, ...]
    python_codepoint_order: tuple[str, ...]
    differs: bool


def assert_utf16_sort_not_codepoint_sort() -> Utf16SortCounterexample:
    """固化“JCS 键序不是 Python 码点序”的反例。

    职责：展示 astral 字符与 BMP 高位字符的排序差异，防止用 `json.dumps(sort_keys=True)`。
    输入：无。
    输出：`Utf16SortCounterexample`；`differs` 必须为 True。
    副作用：无。
    不变量：JCS 序中 emoji 在前（UTF-16 0xD83D < 0xFF01）；Python 码点序相反。
    错误：`JcsError`（仅 Unicode 校验失败时）。
    """
    # 1. 选两个键：U+1F600（UTF-16 代理对 D83D DE00）与 U+FF01（BMP）。
    keys = ("\U0001F600", "\uFF01")

    # 2. JCS 序 = UTF-16 code unit 序。
    jcs_order = tuple(sorted(keys, key=utf16_sort_key))

    # 3. Python 默认序 = Unicode 码点序。
    python_order = tuple(sorted(keys))

    # 4. 返回差异；调用方必须断言 differs is True。
    return Utf16SortCounterexample(
        jcs_order=jcs_order,
        python_codepoint_order=python_order,
        differs=jcs_order != python_order,
    )


def assert_version_string(version: str) -> tuple[int, int]:
    """解析 `MAJOR.MINOR`；只做格式检查，不决定兼容策略（由 payloads.py 决定）。

    职责：把版本字符串拆成整数对，拒绝 `1`、`1.0.0`、`v1.0`、前导零等写法。
    输入：str。
    输出：(major, minor)。
    副作用：无。
    不变量：两段均为非负整数；本函数不做“支持哪个 MAJOR”的判断。
    错误：`JcsError(JCS_INVALID_JSON)`（版本格式非法，沿用 422 协议错误）。
    """
    # 1. 类型与正则检查。
    if not isinstance(version, str):
        raise JcsError("JCS_INVALID_JSON", f"版本必须是字符串，实际 {type(version).__name__}")
    match = _VERSION_RE.match(version)
    if match is None:
        raise JcsError("JCS_INVALID_JSON", f"版本必须形如 MAJOR.MINOR：{version!r}")

    # 2. 拆成整数；拒绝前导零（"01.0"）。
    major_text, minor_text = match.group(1), match.group(2)
    if (len(major_text) > 1 and major_text.startswith("0")) or (
        len(minor_text) > 1 and minor_text.startswith("0")
    ):
        raise JcsError("JCS_INVALID_JSON", f"版本段不得有前导零：{version!r}")

    # 3. 返回。
    return int(major_text), int(minor_text)