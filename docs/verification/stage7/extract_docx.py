#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 7: read-only DOCX extractor (stdlib only, project Python 3.11.16).

Extracts package inventory, document properties, body order, paragraphs,
tables (including merged-cell markers), sections, headers/footers, fields,
TOC entries, and version/date keyword hits.

Never writes to or modifies the source DOCX.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
V = "{urn:schemas-microsoft-com:vml}"
DC = "{http://purl.org/dc/elements/1.1/}"
DCTERMS = "{http://purl.org/dc/terms/}"
CP = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
EP = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"

DEFAULT_DOCX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx",
)
OUTDIR = os.path.dirname(os.path.abspath(__file__))


def qn(local: str) -> str:
    return W + local


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def write_text(name: str, lines: list[str]) -> str:
    path = os.path.join(OUTDIR, name)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
        fh.write("\n")
    return path


def parse_xml(zf: zipfile.ZipFile, member: str) -> ET.Element | None:
    try:
        return ET.fromstring(zf.read(member))
    except KeyError:
        return None


def style_map(zf: zipfile.ZipFile) -> dict[str, str]:
    root = parse_xml(zf, "word/styles.xml")
    mapping: dict[str, str] = {}
    if root is None:
        return mapping
    for style in root.findall(qn("style")):
        sid = style.get(qn("styleId")) or ""
        name_el = style.find(qn("name"))
        name = name_el.get(qn("val")) if name_el is not None else sid
        mapping[sid] = name or sid
    return mapping


def para_text(p: ET.Element) -> str:
    parts: list[str] = []
    for node in p.iter():
        tag = node.tag
        if tag == qn("t"):
            parts.append(node.text or "")
        elif tag == qn("tab"):
            parts.append("\t")
        elif tag in (qn("br"), qn("cr")):
            parts.append("\n")
        elif tag == qn("noBreakHyphen"):
            parts.append("-")
    return "".join(parts)


def para_field_instr(p: ET.Element) -> list[str]:
    out = []
    for node in p.iter(qn("instrText")):
        if node.text:
            out.append(node.text.strip())
    return out


def para_meta(p: ET.Element, styles: dict[str, str]) -> dict:
    ppr = p.find(qn("pPr"))
    style_id = ""
    style_name = ""
    outline = None
    page_break_before = False
    num_id = None
    ilvl = None
    if ppr is not None:
        ps = ppr.find(qn("pStyle"))
        if ps is not None:
            style_id = ps.get(qn("val")) or ""
            style_name = styles.get(style_id, style_id)
        ol = ppr.find(qn("outlineLvl"))
        if ol is not None:
            outline = ol.get(qn("val"))
        pbb = ppr.find(qn("pageBreakBefore"))
        if pbb is not None:
            val = pbb.get(qn("val"))
            page_break_before = val not in ("0", "false", "off")
        num = ppr.find(qn("numPr"))
        if num is not None:
            nid = num.find(qn("numId"))
            lvl = num.find(qn("ilvl"))
            num_id = nid.get(qn("val")) if nid is not None else None
            ilvl = lvl.get(qn("val")) if lvl is not None else None
    manual_breaks = 0
    for br in p.iter(qn("br")):
        if br.get(qn("type")) == "page":
            manual_breaks += 1
    rendered_breaks = len(list(p.iter(qn("lastRenderedPageBreak"))))
    sect = p.find(qn("pPr") + "/" + qn("sectPr")) if ppr is not None else None
    return {
        "style_id": style_id,
        "style_name": style_name,
        "outline": outline,
        "page_break_before": page_break_before,
        "manual_page_breaks": manual_breaks,
        "last_rendered_page_breaks": rendered_breaks,
        "num_id": num_id,
        "ilvl": ilvl,
        "sect_pr": sect,
    }


def cell_text(tc: ET.Element) -> str:
    paras = []
    for p in tc.findall(qn("p")):
        txt = para_text(p).strip()
        if txt:
            paras.append(txt)
    return " / ".join(paras)


def table_rows(tbl: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in tbl.findall(qn("tr")):
        cells: list[str] = []
        for tc in tr.findall(qn("tc")):
            tcpr = tc.find(qn("tcPr"))
            span = 1
            vmerge = ""
            if tcpr is not None:
                gs = tcpr.find(qn("gridSpan"))
                if gs is not None:
                    try:
                        span = int(gs.get(qn("val")) or "1")
                    except ValueError:
                        span = 1
                vm = tcpr.find(qn("vMerge"))
                if vm is not None:
                    vmerge = vm.get(qn("val")) or "continue"
            txt = cell_text(tc).replace("\n", " ⏎ ")
            label = txt
            if span > 1:
                label = f"{txt} [gridSpan={span}]"
            if vmerge:
                label = f"{txt} [vMerge={vmerge}]"
            cells.append(label)
            for _ in range(span - 1):
                cells.append("<merged>")
        rows.append(cells)
    return rows


def walk_body(container: ET.Element, styles: dict[str, str], state: dict, lines: list[str]) -> None:
    for child in list(container):
        tag = child.tag
        if tag == qn("p"):
            state["p_index"] += 1
            meta = para_meta(child, styles)
            text = para_text(child)
            state["paragraphs"].append(
                {
                    "index": state["p_index"],
                    "style": meta["style_name"],
                    "style_id": meta["style_id"],
                    "outline": meta["outline"],
                    "text": text,
                    "page_break_before": meta["page_break_before"],
                }
            )
            flags = []
            if meta["style_name"].lower().startswith(("heading", "标题")) or meta["outline"] is not None:
                flags.append(f"HEADING(outline={meta['outline']})")
            if meta["page_break_before"]:
                flags.append("PAGE_BREAK_BEFORE")
            if meta["manual_page_breaks"]:
                flags.append(f"PAGE_BREAKS={meta['manual_page_breaks']}")
            if meta["last_rendered_page_breaks"]:
                flags.append(f"RENDERED_BREAKS={meta['last_rendered_page_breaks']}")
            if meta["num_id"]:
                flags.append(f"LIST(numId={meta['num_id']},ilvl={meta['ilvl']})")
            instr = para_field_instr(child)
            if instr:
                flags.append("FIELD=" + " | ".join(instr))
            style = meta["style_name"] or "(none)"
            lines.append(f"[P{state['p_index']:04d}] <{style}> {'; '.join(flags)}")
            for ln in text.split("\n"):
                lines.append(f"    {ln}")
        elif tag == qn("tbl"):
            state["t_index"] += 1
            rows = table_rows(child)
            lines.append(f"[TABLE {state['t_index']:02d}] rows={len(rows)} cols~={max((len(r) for r in rows), default=0)}")
            for ri, row in enumerate(rows, 1):
                lines.append(f"  R{ri:02d}: " + " | ".join(row))
            state["tables"].append({"index": state["t_index"], "rows": rows})
        elif tag == qn("sdt"):
            content = child.find(qn("sdtContent"))
            if content is not None:
                walk_body(content, styles, state, lines)
        elif tag == qn("sectPr"):
            sect_lines = []
            pg = child.find(qn("pgSz"))
            if pg is not None:
                sect_lines.append(f"pgSz w={pg.get(qn('w'))} h={pg.get(qn('h'))} orient={pg.get(qn('orient'))}")
            mar = child.find(qn("pgMar"))
            if mar is not None:
                sect_lines.append("pgMar " + " ".join(f"{k.split('}')[-1]}={v}" for k, v in mar.attrib.items()))
            state["sections"].append("; ".join(sect_lines))
            lines.append("[SECTION] " + "; ".join(sect_lines))


def part_text_lines(root: ET.Element | None) -> list[str]:
    if root is None:
        return []
    out = []
    for p in root.iter(qn("p")):
        out.append(para_text(p).strip())
    return [x for x in out if x]


def main() -> int:
    docx = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DOCX
    docx = os.path.abspath(docx)
    if not os.path.isfile(docx):
        print(f"ERROR: DOCX not found: {docx}")
        return 2

    stat = os.stat(docx)
    digest = sha256_file(docx)
    lines_pkg = [
        "STAGE7 DOCX PACKAGE INVENTORY (read-only)",
        f"PATH={docx}",
        f"SIZE_BYTES={stat.st_size}",
        f"CREATED={stat.st_ctime_ns}",
        f"MODIFIED={stat.st_mtime_ns}",
        f"SHA256={digest}",
        "",
        "MEMBERS:",
    ]
    with zipfile.ZipFile(docx) as zf:
        for info in zf.infolist():
            lines_pkg.append(f"  {info.filename}\t{info.file_size}\tcompressed={info.compress_size}")
        bad = zf.testzip()
        lines_pkg.append("")
        lines_pkg.append(f"ZIP_TEST={'OK' if bad is None else 'BAD:' + str(bad)}")

        core = parse_xml(zf, "docProps/core.xml")
        app = parse_xml(zf, "docProps/app.xml")
        styles = style_map(zf)
        rels = parse_xml(zf, "word/_rels/document.xml.rels")

        lines_props = ["STAGE7 DOCX PROPERTIES (read-only)", f"PATH={docx}", f"SHA256={digest}", "", "[docProps/core.xml]"]
        if core is not None:
            for child in core:
                lines_props.append(f"  {child.tag.split('}')[-1]} = {child.text!r}")
        else:
            lines_props.append("  (missing)")
        lines_props.append("")
        lines_props.append("[docProps/app.xml]")
        if app is not None:
            for child in app:
                lines_props.append(f"  {child.tag.split('}')[-1]} = {child.text!r}")
        else:
            lines_props.append("  (missing)")

        lines_props.append("")
        lines_props.append("[STYLES: heading/outline candidates]")
        for sid, name in sorted(styles.items()):
            low = name.lower()
            if low.startswith(("heading", "标题", "toc", "目录")):
                lines_props.append(f"  styleId={sid} name={name!r}")
        lines_props.append("")
        lines_props.append("[RELATIONSHIPS]")
        if rels is not None:
            for rel in rels:
                lines_props.append(
                    f"  Id={rel.get('Id')} Type={rel.get('Type')} Target={rel.get('Target')} TargetMode={rel.get('TargetMode')}"
                )

        doc = parse_xml(zf, "word/document.xml")
        body = doc.find(qn("body")) if doc is not None else None
        state = {"p_index": 0, "t_index": 0, "paragraphs": [], "tables": [], "sections": []}
        body_lines: list[str] = []
        if body is not None:
            walk_body(body, styles, state, body_lines)

        lines_props.append("")
        lines_props.append("[SECTIONS]")
        for i, s in enumerate(state["sections"], 1):
            lines_props.append(f"  S{i}: {s}")

        lines_props.append("")
        lines_props.append("[COUNTS]")
        lines_props.append(f"  paragraphs={len(state['paragraphs'])}")
        lines_props.append(f"  tables={len(state['tables'])}")
        lines_props.append(f"  sections={len(state['sections'])}")
        lines_props.append(f"  total_text_chars={sum(len(p['text']) for p in state['paragraphs'])}")
        if doc is not None:
            lines_props.append(f"  drawings={len(doc.findall('.//' + qn('drawing')))}")
            lines_props.append(f"  pict={len(doc.findall('.//' + qn('pict')))}")
            lines_props.append(f"  vml_shapes={len(doc.findall('.//' + V + 'shape'))}")
            lines_props.append(f"  textboxes={len(doc.findall('.//' + qn('txbxContent')))}")
            lines_props.append(f"  tracked_insertions={len(doc.findall('.//' + qn('ins')))}")
            lines_props.append(f"  tracked_deletions={len(doc.findall('.//' + qn('del')))}")
            lines_props.append(f"  comment_refs={len(doc.findall('.//' + qn('commentReference')))}")
            page_breaks = 0
            for br in doc.findall('.//' + qn('br')):
                if br.get(qn('type')) == 'page':
                    page_breaks += 1
            lines_props.append(f"  manual_page_breaks={page_breaks}")
            lines_props.append(f"  last_rendered_page_breaks={len(doc.findall('.//' + qn('lastRenderedPageBreak')))}")
            lines_props.append(f"  media_members={len([n for n in zf.namelist() if n.startswith('word/media/')])}")

        lines_props.append("")
        lines_props.append("[HEADERS / FOOTERS]")
        header_parts = [n for n in zf.namelist() if re.match(r"word/(header|footer)\d*\.xml$", n)]
        for member in sorted(header_parts):
            root = parse_xml(zf, member)
            texts = part_text_lines(root)
            instrs: list[str] = []
            if root is not None:
                instrs = [(n.text or "").strip() for n in root.iter(qn("instrText")) if (n.text or "").strip()]
            lines_props.append(f"  {member}: text={texts!r} fields={instrs!r}")

        lines_props.append("")
        lines_props.append("[FIELDS / TOC]")
        instr_all: list[str] = []
        if doc is not None:
            instr_all = [(n.text or "").strip() for n in doc.iter(qn("instrText")) if (n.text or "").strip()]
        for instr in instr_all:
            lines_props.append(f"  FIELD: {instr!r}")
        toc_paras = [
            p for p in state["paragraphs"]
            if p["style"].lower().startswith(("toc", "目录")) or "TOC" in p["text"][:20]
        ]
        for p in toc_paras:
            lines_props.append(f"  TOC P{p['index']:04d} <{p['style']}> {p['text']!r}")

        write_text("00_docx_package.txt", lines_pkg)
        write_text("01_docx_properties.txt", lines_props)
        write_text("02_docx_body.txt", body_lines)

        # Heading / TOC outline filtered view.
        outline_lines = [
            "STAGE7 DOCX OUTLINE (heading styles / outline levels / TOC paragraphs)",
            f"PATH={docx}",
            f"SHA256={digest}",
            "",
        ]
        for p in state["paragraphs"]:
            low = p["style"].lower()
            if low.startswith(("heading", "标题")) or p["outline"] is not None or low.startswith(("toc", "目录")):
                outline_lines.append(
                    f"P{p['index']:04d}\tstyle={p['style']}\toutline={p['outline']}\t{p['text']}"
                )
        write_text("03_docx_outline.txt", outline_lines)

        # Version/date keyword scan with locations.
        patterns = [
            r"v\s*4\.[0-9]+(?:\.[0-9]+)?",
            r"4\.3\.[0-9]",
            r"版本",
            r"修订",
            r"日期",
            r"202[4-6]\s*[年./-]\s*\d{1,2}",
            r"20\d{2}-\d{2}-\d{2}",
            r"第\s*\d+\s*版",
        ]
        scan_lines = [
            "STAGE7 DOCX VERSION/DATE KEYWORD SCAN",
            f"PATH={docx}",
            f"SHA256={digest}",
            "FORMAT: location | style | matched terms | text",
            "",
        ]
        for p in state["paragraphs"]:
            hits = []
            for pat in patterns:
                hits.extend(re.findall(pat, p["text"], flags=re.IGNORECASE))
            if hits:
                uniq = []
                for h in hits:
                    if h not in uniq:
                        uniq.append(h)
                scan_lines.append(
                    f"P{p['index']:04d} | style={p['style']} | hits={uniq!r} | {p['text'][:500]}"
                )
        for t in state["tables"]:
            for ri, row in enumerate(t["rows"], 1):
                joined = " | ".join(row)
                hits = []
                for pat in patterns:
                    hits.extend(re.findall(pat, joined, flags=re.IGNORECASE))
                if hits:
                    uniq = []
                    for h in hits:
                        if h not in uniq:
                            uniq.append(h)
                    scan_lines.append(
                        f"TABLE {t['index']:02d} R{ri:02d} | hits={uniq!r} | {joined[:700]}"
                    )
        write_text("04_docx_version_scan.txt", scan_lines)

        # Table-only dump (for diagram-like tables).
        table_lines = [
            "STAGE7 DOCX TABLES (full dump, merged cells marked)",
            f"PATH={docx}",
            f"SHA256={digest}",
            f"TABLE_COUNT={len(state['tables'])}",
            "",
        ]
        for t in state["tables"]:
            table_lines.append(f"===== TABLE {t['index']:02d} =====")
            for ri, row in enumerate(t["rows"], 1):
                table_lines.append(f"R{ri:02d}: " + " | ".join(row))
            table_lines.append("")
        write_text("05_docx_tables.txt", table_lines)

    print("DOCX_EXTRACT=OK")
    print(f"PATH={docx}")
    print(f"SIZE_BYTES={stat.st_size}")
    print(f"SHA256={digest}")
    print(f"PARAGRAPHS={len(state['paragraphs'])}")
    print(f"TABLES={len(state['tables'])}")
    print(f"OUTDIR={OUTDIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
