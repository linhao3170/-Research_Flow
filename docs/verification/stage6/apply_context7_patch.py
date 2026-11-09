#!/usr/bin/env python3
"""阶段 6：按批准的精确字节写入 Context7 MCP 配置（仅标准库）。

模式
----
* ``backup``：校验源文件后创建同目录备份，并核对备份哈希。
* ``append``：在源文件末尾追加 262 字节（9 行 LF），立即执行三项校验；
  任一项失败自动用备份恢复并 exit 2。
* ``verify``：只读打印当前文件大小、行数、末尾字节、SHA256 与前缀一致性。
* ``restore``：用备份恢复并核对哈希。

安全边界
--------
* 只操作 ``cordis.patch.yml`` 与其同目录备份；不碰其他配置。
* 使用二进制追加，不重新格式化、不改变换行或 BOM。
* 不读取、不写入任何 API Key 或凭据。
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path(r"C:\Users\Administrator\.dsh\profiles\desktop\cordis.patch.yml")
BACKUP = TARGET.with_name(TARGET.name + ".bak-20261108-stage6")

BEFORE_SHA256 = "664CE561366D925DDA1AE382528565218ABB20072211DD36562F4D3CB894FFD8"
AFTER_SHA256 = "6FF6F1FCB6CAE8F732F221710D9E4FFD5C6DF1E26F6EFDADE75F4B9B536159E1"
BEFORE_BYTES = 1200
AFTER_BYTES = 1462
AFTER_LINES = 52

BLOCK = (
    b"- insert:\n"
    b"    - id: mcp-context7\n"
    b'      name: "@deepseek-ai/dsh-mcp-client"\n'
    b"      config:\n"
    b"        serverName: context7\n"
    b"        transport: streamable-http\n"
    b"        url: https://mcp.context7.com/mcp\n"
    b"        toolCallTimeoutMs: 60000\n"
    b"        failOnStartupError: false\n"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def report(label: str, path: Path) -> bytes:
    data = path.read_bytes()
    line_count = data.count(b"\n")
    print(f"{label}_path={path}")
    print(f"{label}_bytes={len(data)}")
    print(f"{label}_lines={line_count}")
    print(f"{label}_last_byte={data[-1] if data else 'EMPTY'}")
    print(f"{label}_sha256={sha256(data)}")
    return data


def require(condition: bool, message: str) -> None:
    if not condition:
        print(f"CHECK_FAIL={message}")
        raise SystemExit(1)
    print(f"CHECK_OK={message}")


def do_backup() -> None:
    require(TARGET.is_file(), "源文件存在")
    require(not BACKUP.exists(), "备份尚不存在（不覆盖旧备份）")
    before = report("before", TARGET)
    require(len(before) == BEFORE_BYTES, "源文件 1200 字节")
    require(sha256(before) == BEFORE_SHA256, "源文件 SHA256=664C…FFD8")
    shutil.copyfile(TARGET, BACKUP)
    after = report("backup", BACKUP)
    require(len(after) == BEFORE_BYTES, "备份 1200 字节")
    require(sha256(after) == BEFORE_SHA256, "备份 SHA256=664C…FFD8")
    require(after == before, "备份与源文件逐字节相同")
    print("BACKUP_RESULT=OK")


def do_append() -> None:
    require(TARGET.is_file(), "源文件存在")
    require(BACKUP.is_file(), "备份存在")
    backup = BACKUP.read_bytes()
    require(len(backup) == BEFORE_BYTES, "备份 1200 字节")
    require(sha256(backup) == BEFORE_SHA256, "备份 SHA256=664C…FFD8")
    before = TARGET.read_bytes()
    require(before == backup, "追加前源文件与备份逐字节相同")

    with TARGET.open("ab") as handle:
        handle.write(BLOCK)

    after = TARGET.read_bytes()
    after_lines = after.count(b"\n")
    print(f"after_bytes={len(after)}")
    print(f"after_lines={after_lines}")
    print(f"after_last_byte={after[-1] if after else 'EMPTY'}")
    print(f"after_sha256={sha256(after)}")
    print(f"prefix_equal_backup={after[:BEFORE_BYTES] == backup}")

    checks = {
        "大小=1462": len(after) == AFTER_BYTES,
        "行数=52": after_lines == AFTER_LINES,
        "末尾换行": after.endswith(b"\n") and after[-1:] == b"\n",
        "SHA256=6FF6…59E1": sha256(after) == AFTER_SHA256,
        "前1200字节与备份一致": after[:BEFORE_BYTES] == backup,
        "无BOM": not after.startswith(b"\xef\xbb\xbf"),
        "无CRLF": b"\r\n" not in after,
    }
    for label, ok in checks.items():
        print(f"CHECK_{'OK' if ok else 'FAIL'}={label}")
    if not all(checks.values()):
        shutil.copyfile(BACKUP, TARGET)
        restored = TARGET.read_bytes()
        print(f"ROLLBACK_sha256={sha256(restored)}")
        print(f"ROLLBACK_bytes={len(restored)}")
        print("ROLLBACK_RESULT=" + ("OK" if restored == backup else "FAIL"))
        print("APPEND_RESULT=FAIL")
        raise SystemExit(2)
    print("APPEND_RESULT=OK")


def do_verify() -> None:
    require(TARGET.is_file(), "源文件存在")
    current = report("current", TARGET)
    backup = BACKUP.read_bytes() if BACKUP.is_file() else b""
    print(f"prefix_equal_backup={current[:BEFORE_BYTES] == backup}")
    print(f"current_sha256_matches_after={sha256(current) == AFTER_SHA256}")
    print("VERIFY_RESULT=OK" if sha256(current) == AFTER_SHA256 else "VERIFY_RESULT=FAIL")


def do_restore() -> None:
    require(BACKUP.is_file(), "备份存在")
    backup = BACKUP.read_bytes()
    require(sha256(backup) == BEFORE_SHA256, "备份 SHA256=664C…FFD8")
    shutil.copyfile(BACKUP, TARGET)
    restored = TARGET.read_bytes()
    require(restored == backup, "恢复后与备份逐字节相同")
    require(sha256(restored) == BEFORE_SHA256, "恢复后 SHA256=664C…FFD8")
    print("RESTORE_RESULT=OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("backup", "append", "verify", "restore"))
    args = parser.parse_args()
    if args.mode == "backup":
        do_backup()
    elif args.mode == "append":
        do_append()
    elif args.mode == "verify":
        do_verify()
    else:
        do_restore()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 - 写入脚本必须把失败转为非零退出
        print(f"ERROR {type(error).__name__}: {error}")
        raise SystemExit(1)
