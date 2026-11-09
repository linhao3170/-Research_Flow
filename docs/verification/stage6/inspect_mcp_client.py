#!/usr/bin/env python3
"""只读检查 DeepSeek Harness 0.2.2-rc.1 安装包内的 MCP Client 实现（仅标准库）。

用途
----
直接读取 ``D:\deepseek_harness1\resources\app.asar`` 的头部与指定条目，
证明当前桌面版实际携带的 ``@deepseek-ai/dsh-mcp-client`` 版本、传输方式、
配置字段与 bundle 解析顺序。不读取 ``.dsh`` profile 下的 0.1.0-rc.8 包来推断行为。

约束
----
* 只读；不修改安装目录，不写入缓存，不安装依赖。
* 不输出凭据、令牌或任何秘密。
* 退出码：0 读取成功；1 关键条目缺失或解析失败。
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from typing import Any

ASAR_PATH = Path(r"D:\deepseek_harness1\resources\app.asar")


class Asar:
    def __init__(self, path: Path) -> None:
        self._file = path.open("rb")
        prefix = self._file.read(16)
        if len(prefix) != 16:
            raise RuntimeError("asar 头部长度不足")
        header_size = struct.unpack("<I", prefix[4:8])[0]
        json_length = struct.unpack("<I", prefix[12:16])[0]
        self._data_base = 8 + header_size
        self._header = json.loads(self._file.read(json_length).decode("utf-8"))
        self.entries: dict[str, dict[str, Any]] = {}
        self._walk(self._header)

    def _walk(self, node: dict[str, Any], prefix: str = "") -> None:
        for name, value in node.get("files", {}).items():
            path = f"{prefix}/{name}" if prefix else name
            if "files" in value:
                self._walk(value, path)
            else:
                self.entries[path] = value

    def read(self, path: str) -> bytes:
        entry = self.entries[path]
        self._file.seek(self._data_base + int(entry["offset"]))
        return self._file.read(int(entry["size"]))

    def text(self, path: str) -> str:
        return self.read(path).decode("utf-8", "replace")

    def close(self) -> None:
        self._file.close()


def find_lines(text: str, needles: list[str], limit: int = 8) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if any(needle in line for needle in needles):
            found.append((number, line.strip()))
            if len(found) >= limit:
                break
    return found


def main() -> int:
    if not ASAR_PATH.is_file():
        print(f"ASAR_MISSING={ASAR_PATH}")
        return 1
    asar = Asar(ASAR_PATH)
    try:
        desktop = json.loads(asar.text("dsh/desktop-runtime.json"))
        release = desktop["release"]
        print("desktop_runtime_version=" + str(release["version"]))
        print("desktop_runtime_node=" + str(release["nodeVersion"]))
        print("desktop_runtime_pnpm=" + str(release["pnpmVersion"]))

        dsh_pkg = json.loads(asar.text("dsh/package.json"))
        print("dsh_package_name=" + str(dsh_pkg.get("name")))
        print("dsh_package_version=" + str(dsh_pkg.get("version")))
        dependencies = dsh_pkg.get("dependencies", {})
        for name in (
            "@deepseek-ai/dsh-mcp-client",
            "@deepseek-ai/dsh-mcp-resources",
            "@deepseek-ai/dsh-app-boot",
        ):
            print(f"dependency {name}={dependencies.get(name)}")

        client_pkg = json.loads(
            asar.text("dsh/node_modules/@deepseek-ai/dsh-mcp-client/package.json")
        )
        print("mcp_client_version=" + str(client_pkg.get("version")))
        print(
            "mcp_sdk_dependency="
            + str(client_pkg.get("dependencies", {}).get("@modelcontextprotocol/client"))
        )

        client_source = asar.text(
            "dsh/node_modules/@deepseek-ai/dsh-mcp-client/lib/index.js"
        )
        print("--- mcp-client config schema / transport ---")
        for number, line in find_lines(
            client_source,
            [
                'z.const("stdio")',
                'z.const("streamable-http")',
                "StreamableHTTPClientTransport",
                "serverName: z.string().required()",
                "headers: z.dict(String)",
                "DEFAULT_TOOL_CALL_TIMEOUT_MS =",
                "failOnStartupError: z.boolean()",
            ],
            12,
        ):
            print(f"lib/index.js:{number}: {line[:240]}")

        app_boot = asar.text("dsh/node_modules/@deepseek-ai/dsh-app-boot/lib/index.js")
        print("--- profile bundle resolution ---")
        for needle in (
            "Module resolution is two-anchor by construction",
            "installation anchor first",
            "always comes from",
        ):
            for number, line in find_lines(app_boot, [needle], 1):
                print(f"lib/index.js:{number}: {line[:240]}")

        base_patch = asar.text("dsh/node_modules/@deepseek-ai/dsh-base/cordis.patch.yml")
        print("--- dsh-base mcp rows ---")
        print("base_has_mcp_resources=" + str("id: mcp-resources" in base_patch))
        print("base_has_mcp_client=" + str("id: mcp-client" in base_patch))

        client_readme = asar.text(
            "dsh/node_modules/@deepseek-ai/dsh-mcp-client/README.md"
        )
        print("--- mcp-client README capability statements ---")
        for number, line in find_lines(
            client_readme,
            [
                "No server is enabled by default",
                "Choose stdio for a local program",
                "Streamable HTTP",
                "MCP prompt templates are unsupported",
            ],
            6,
        ):
            print(f"README.md:{number}: {line[:240]}")
    finally:
        asar.close()
    print("INSPECT_RESULT=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - 证据脚本需要报告所有失败
        print(f"INSPECT_RESULT=FAIL {type(error).__name__}: {error}")
        raise SystemExit(1)
