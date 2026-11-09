#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 7: read-only version-string evidence for the authoritative DOCX.

Counts literal version tokens in every package part and prints the surrounding
context. Does not modify the source file.
"""

from __future__ import annotations

import hashlib
import os
import re
import zipfile

DOCX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx",
)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "07_version_strings.txt")
TOKENS = ["v4.3.1", "v4.3.0", "v4.2", "4.3.1", "4.3.0"]


def main() -> int:
    digest = hashlib.sha256(open(DOCX, "rb").read()).hexdigest().upper()
    lines = [
        "STAGE7 DOCX VERSION STRING EVIDENCE (read-only)",
        f"PATH={DOCX}",
        f"SIZE_BYTES={os.path.getsize(DOCX)}",
        f"SHA256={digest}",
        "",
    ]
    with zipfile.ZipFile(DOCX) as zf:
        for part in [
            "word/document.xml",
            "word/header1.xml",
            "word/footer1.xml",
            "docProps/core.xml",
            "docProps/app.xml",
        ]:
            try:
                raw = zf.read(part).decode("utf-8")
            except KeyError:
                lines.append(f"[{part}] MISSING")
                continue
            lines.append(f"[{part}]")
            for token in TOKENS:
                count = raw.count(token)
                lines.append(f"  token={token!r} count={count}")
                if count:
                    for m in re.finditer(re.escape(token), raw):
                        start = max(0, m.start() - 90)
                        end = min(len(raw), m.end() + 90)
                        context = re.sub(r"<[^>]+>", " ", raw[start:end])
                        context = re.sub(r"\s+", " ", context).strip()
                        lines.append(f"    ...{context}...")
            lines.append("")

        # Filename token check.
        lines.append("[FILENAME]")
        for token in TOKENS:
            lines.append(f"  token={token!r} count={os.path.basename(DOCX).count(token)}")
        lines.append("")

        # Text-level counts from the extracted body, if present.
        body_path = os.path.join(os.path.dirname(OUT), "02_docx_body.txt")
        if os.path.isfile(body_path):
            text = open(body_path, encoding="utf-8").read()
            lines.append("[EXTRACTED_TEXT 02_docx_body.txt]")
            for token in TOKENS:
                lines.append(f"  token={token!r} count={text.count(token)}")
            lines.append("")

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print("VERSION_EVIDENCE=OK")
    print(f"OUT={OUT}")
    print(f"SHA256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
