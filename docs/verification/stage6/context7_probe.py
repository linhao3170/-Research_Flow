#!/usr/bin/env python3
"""Context7 remote MCP 只读探测（仅标准库）。

用途
----
在本机验证 ``https://mcp.context7.com/mcp`` 是否可用、使用什么协议版本、
公开哪些工具，以及匿名（不带 API Key）调用是否返回真实结果。

安全边界
--------
* 只发送公开库名 ``FastAPI`` 与公开文档查询，不发送项目代码、路径、凭据或任何秘密。
* 不读取 ``.credentials.yaml``、环境变量中的密钥或 Harness 凭据存储。
* 不写入任何文件；输出只到 stdout。

退出码：0 全部通过；1 任一阶段失败。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

URL = "https://mcp.context7.com/mcp"
PROTOCOL_VERSION = "2025-06-18"
TIMEOUT_SECONDS = 30


def rpc(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """发送一条 JSON-RPC 请求，解析 Streamable HTTP 的 SSE 响应。"""
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        status = response.status
        body = response.read().decode("utf-8", "replace")
    events: list[dict[str, Any]] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    if not events:
        raise RuntimeError("响应中没有 SSE data 事件")
    return status, events[-1]


def main() -> int:
    print("probe_time_utc=" + datetime.now(timezone.utc).isoformat(timespec="seconds"))
    print("endpoint=" + URL)
    print("credential_header_present=false")
    print("request_payloads=initialize,tools/list,tools/call(resolve-library-id)")

    status, message = rpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "researchflow-probe", "version": "0.0.1"},
            },
        }
    )
    result = message.get("result", {})
    server = result.get("serverInfo", {})
    capabilities = result.get("capabilities", {})
    instructions = result.get("instructions", "")
    print("initialize_http_status=" + str(status))
    print("negotiated_protocol=" + str(result.get("protocolVersion")))
    print("server_name=" + str(server.get("name")))
    print("server_version=" + str(server.get("version")))
    print("capabilities=" + ",".join(sorted(capabilities)))
    print("instructions_chars=" + str(len(instructions)))

    status, message = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = message.get("result", {}).get("tools", [])
    print("tools_list_http_status=" + str(status))
    print("tool_count=" + str(len(tools)))
    for tool in tools:
        annotations = tool.get("annotations", {})
        required = tool.get("inputSchema", {}).get("required", [])
        print(
            "tool="
            + str(tool.get("name"))
            + " readOnlyHint="
            + str(annotations.get("readOnlyHint"))
            + " required="
            + ",".join(required)
        )

    status, message = rpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "resolve-library-id",
                "arguments": {
                    "libraryName": "FastAPI",
                    "query": "Python web framework routing and dependency injection",
                },
            },
        }
    )
    call_result = message.get("result", {})
    blocks = call_result.get("content", [])
    text = ""
    for block in blocks:
        if block.get("type") == "text":
            text += block.get("text", "")
    print("tool_call_http_status=" + str(status))
    print("tool_call_is_error=" + str(bool(call_result.get("isError"))))
    print("tool_call_content_blocks=" + str(len(blocks)))
    print("tool_call_text_chars=" + str(len(text)))
    first_line = text.splitlines()[0] if text else ""
    print("tool_call_first_line=" + first_line[:200])
    if not text or "Context7-compatible library ID" not in text:
        print("PROBE_RESULT=FAIL")
        return 1
    print("PROBE_RESULT=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as error:
        print(f"PROBE_RESULT=FAIL http_status={error.code}")
        print(error.read(500).decode("utf-8", "replace"))
        raise SystemExit(1)
    except Exception as error:  # noqa: BLE001 - 探测脚本需要把所有失败转成退出码
        print(f"PROBE_RESULT=FAIL {type(error).__name__}: {error}")
        raise SystemExit(1)
