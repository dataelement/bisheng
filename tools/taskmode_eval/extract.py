"""Turn deliverable files into text (for checks and the judge) plus a short format summary."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

TEXT_EXT = {"md", "txt", "json", "csv", "py", "yaml", "yml", "xml"}


class _Html(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text, self.scripts, self._in = [], [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._in = tag

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._in = None

    def handle_data(self, data):
        if self._in == "script":
            self.scripts.append(data)
        elif self._in is None and data.strip():
            self.text.append(data.strip())


def _docx(path: Path) -> tuple[str, dict]:
    import docx

    d = docx.Document(str(path))
    lines, styles, fonts = [], {}, {}
    for p in d.paragraphs:
        if p.text.strip():
            lines.append(p.text)
            styles[p.style.name] = styles.get(p.style.name, 0) + 1
            for r in p.runs[:1]:
                key = f"{r.font.name or p.style.font.name}/{r.font.size.pt if r.font.size else (p.style.font.size.pt if p.style.font.size else None)}"
                fonts[key] = fonts.get(key, 0) + 1
    for ti, t in enumerate(d.tables):
        lines.append(f"[表格{ti + 1}]")
        for row in t.rows:
            cells = []
            for c in row.cells:
                if not cells or cells[-1] != c.text:
                    cells.append(c.text.strip())
            lines.append(" | ".join(cells))
    sec = d.sections[0] if d.sections else None
    fmt = {
        "paragraphs": len(lines),
        "tables": len(d.tables),
        "styles": dict(sorted(styles.items(), key=lambda x: -x[1])[:12]),
        "fonts_first_run": dict(sorted(fonts.items(), key=lambda x: -x[1])[:8]),
        "page_cm": [round(sec.page_width.cm, 1), round(sec.page_height.cm, 1)] if sec and sec.page_width else None,
        "margins_cm": [round(x.cm, 2) for x in (sec.top_margin, sec.bottom_margin, sec.left_margin, sec.right_margin)]
        if sec and sec.top_margin
        else None,
    }
    return "\n".join(lines), fmt


def _pptx(path: Path) -> tuple[str, dict]:
    from pptx import Presentation

    prs = Presentation(str(path))
    lines, layouts = [], []
    for i, s in enumerate(prs.slides, 1):
        layouts.append(s.slide_layout.name)
        lines.append(f"--- 第{i}页（版式：{s.slide_layout.name}）")
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                lines.append(sh.text_frame.text.strip())
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    lines.append(" | ".join(c.text.strip() for c in row.cells))
            if getattr(sh, "has_chart", False) and sh.has_chart:
                lines.append("[图表]")
        if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
            lines.append("[备注] " + s.notes_slide.notes_text_frame.text.strip()[:300])
    fmt = {
        "slides": len(prs.slides),
        "masters": [m.name for m in prs.slide_masters] if hasattr(prs, "slide_masters") else None,
        "layouts_used": layouts,
        "size_in": [round(prs.slide_width.inches, 2), round(prs.slide_height.inches, 2)],
    }
    return "\n".join(lines), fmt


def _xlsx(path: Path) -> tuple[str, dict]:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True)
    wbf = openpyxl.load_workbook(str(path), data_only=False)
    lines, sheets = [], {}
    for ws in wb.worksheets:
        rows = [r for r in ws.iter_rows(values_only=True) if any(v not in (None, "") for v in r)]
        sheets[ws.title] = {"rows": len(rows), "cols": ws.max_column}
        lines.append(f"--- sheet：{ws.title}")
        for r in rows[:400]:
            lines.append(" | ".join("" if v is None else str(v) for v in r))
        if len(rows) > 400:
            lines.append(f"……（省略 {len(rows) - 400} 行）")
    formulas = sum(
        1
        for ws in wbf.worksheets
        for row in ws.iter_rows()
        for c in row
        if isinstance(c.value, str) and c.value.startswith("=")
    )
    return "\n".join(lines), {"sheets": sheets, "formula_cells": formulas}


def _pdf(path: Path) -> tuple[str, dict]:
    with tempfile.TemporaryDirectory() as td:
        try:
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "txt:Text", "--outdir", td, str(path)],
                capture_output=True,
                timeout=180,
            )
            out = list(Path(td).glob("*.txt"))
            if out:
                return out[0].read_text(encoding="utf-8", errors="ignore"), {}
        except Exception:
            pass
    return "", {"note": "PDF 未能抽取文字"}


def _html(path: Path) -> tuple[str, dict]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    p = _Html()
    p.feed(raw)
    scripts = "\n".join(p.scripts)
    charts = len(re.findall(r"echarts\.init|new Chart\(|Plotly\.newPlot|<canvas|<svg", raw))
    text = "\n".join(p.text)
    if scripts.strip():
        text += "\n[脚本中的数据]\n" + scripts[:20000]
    return text, {"chart_markers": charts, "bytes": len(raw)}


def extract_file(path: Path) -> tuple[str, dict]:
    ext = path.suffix.lower().lstrip(".")
    try:
        if ext == "docx":
            return _docx(path)
        if ext == "pptx":
            return _pptx(path)
        if ext in ("xlsx", "xlsm"):
            return _xlsx(path)
        if ext == "pdf":
            return _pdf(path)
        if ext in ("html", "htm"):
            return _html(path)
        if ext in TEXT_EXT:
            return path.read_text(encoding="utf-8", errors="ignore"), {}
        return "", {"note": f"未抽取文本的类型 {ext}"}
    except Exception as e:
        return "", {"error": f"抽取失败：{e}"}


def extract_run(run_case_dir: Path) -> dict:
    """Return {answer, files: [{name, ext, text, fmt}]} for one runs/<id>/<case>/r<k> directory."""
    answer = (run_case_dir / "answer.md").read_text(encoding="utf-8") if (run_case_dir / "answer.md").exists() else ""
    files = []
    fdir = run_case_dir / "files"
    if fdir.is_dir():
        for p in sorted(fdir.iterdir()):
            if p.is_file():
                text, fmt = extract_file(p)
                files.append(
                    {"name": p.name, "ext": p.suffix.lower().lstrip("."), "text": text, "fmt": fmt, "path": str(p)}
                )
    return {"answer": answer, "files": files}


def first_json(text: str):
    """Parse the first JSON object/array in text (tolerates ``` fences and surrounding prose)."""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    candidates = [m.group(1)] if m else []
    candidates.append(t)
    for c in candidates:
        try:
            return json.loads(c)
        except Exception:
            pass
        for opener in ("{", "["):
            i = c.find(opener)
            while i != -1:
                try:
                    obj, _ = json.JSONDecoder().raw_decode(c[i:])
                    return obj
                except Exception:
                    i = c.find(opener, i + 1)
                    if i > 20000:
                        break
    return None
