#!/usr/bin/env python3
"""Build a web slide deck — one self-contained HTML file — from named layouts and slots.

Use from a build script in the code executor::

    import sys
    sys.path.insert(0, "skills/html-report/scripts")
    from slides import Deck

    deck = Deck.open("operating", footer="某某集团 · 2026 年度经营汇报")
    s = deck.add("cover")
    deck.fill(s, "title", "2026 年度经营汇报：稳中有进")
    deck.drop(s, "kicker")
    s = deck.add("chart-insight")
    deck.fill(s, "title", "营收连续四年增长，年均 13.8%")
    deck.chart(s, "chart", "column", ["2023", "2024", "2025", "2026"], [("营收（亿元）", [88, 101, 114, 128])])
    deck.fill(s, "insight.body", ["2024 年起新业务贡献过半", "2026 年增速略有回落"])
    deck.save("output/年度经营汇报.html")

Why a script and not hand-written HTML: every page is the same markup with different
words. Generating it means the model writes only the words, and a revision touches
one page's ``fill`` calls instead of re-emitting the page.

``list_layouts.py <theme>`` prints every layout and slot with its capacity. ``save``
writes ``scratch/<name>.manifest.json``, which ``check_slides.py`` reads. Pages are
``<section class="slide">`` so ``check_html`` measures them one by one.
"""

from __future__ import annotations

import base64
import html as _html
import json
import mimetypes
import os
import re

__all__ = ["LAYOUTS", "THEMES", "Deck", "text_units"]

_HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.normpath(os.path.join(_HERE, "..", "assets", "slides"))

with open(os.path.join(ASSETS_DIR, "themes.json"), encoding="utf-8") as _fh:
    _THEME_FILE = json.load(_fh)
THEMES = {t["id"]: t for t in _THEME_FILE["themes"]}
WIDTH = _THEME_FILE["canvas"]["width"]
HEIGHT = _THEME_FILE["canvas"]["height"]

_TEXT_ROLES = {"title", "subtitle", "body", "caption", "label", "number", "footer"}
_IMAGE_WARN_BYTES = 2 * 1024 * 1024
_TABLE_MAX_ROWS = 8
# Size variables a deck may override (slides.css :root). Everything else stays fixed.
_CSS_VARS = (
    "--fs-kicker",
    "--fs-title",
    "--fs-lead",
    "--fs-body",
    "--fs-h3",
    "--fs-small",
    "--fs-number",
)  # data rows that fit under the header at the default row height
_FORBIDDEN_FRAGMENT = re.compile(
    r"<\s*(script|style|link|iframe|object|embed|meta|base)\b|\son\w+\s*=|javascript:", re.IGNORECASE
)


def text_units(text: str) -> float:
    """字数: CJK / full-width counts 1, anything else 0.5 — the unit of every capacity."""
    return sum(1.0 if ord(ch) > 0x2E7F else 0.5 for ch in text if ch not in "\r\n")


# ---------------------------------------------------------------------------
# layouts: slot specs (name, role, capacity, bullets). Capacities are calibrated by
# rendering every slot filled to capacity in every theme (test_html_slides.py).
# ---------------------------------------------------------------------------


def _s(name, role, capacity=0, bullets=False, max_items=0):
    spec = {"name": name, "role": role, "capacity": capacity, "bullets": bullets}
    if bullets:
        spec["max_items"] = max_items
    return spec


_HEAD = [_s("kicker", "label", 40), _s("title", "title", 28)]
_LEAD = [_s("lead", "subtitle", 46)]


def _group(prefix, n, *slots):
    return [
        _s(f"{prefix}{i}.{name}", role, cap, bullets) for i in range(1, n + 1) for name, role, cap, bullets in slots
    ]


LAYOUTS = {
    "cover": {
        "name": "封面",
        "use_for": "文稿开头；主标题写核心判断或文稿名称",
        "dark": True,
        "slots": [
            _s("kicker", "label", 40),
            _s("title", "title", 32),
            _s("subtitle", "subtitle", 70),
            _s("org", "label", 40),
            _s("date", "label", 30),
        ],
    },
    "agenda": {
        "name": "目录",
        "use_for": "4–5 个章节的目录",
        "slots": [_s("kicker", "label", 40), _s("title", "title", 12)]
        + _group("item", 5, ("no", "number", 2, False), ("text", "body", 28, False)),
    },
    "section": {
        "name": "章节页",
        "use_for": "章节过渡，一句话交代本章问题",
        "dark": True,
        "slots": [_s("no", "number", 2), _s("title", "title", 20), _s("subtitle", "subtitle", 80)],
    },
    "statement": {
        "name": "观点页",
        "use_for": "一句结论加一段依据，用于关键判断",
        "slots": [
            _s("kicker", "label", 40),
            _s("statement", "title", 60),
            _s("support", "body", 130),
            _s("source", "caption", 70),
        ],
    },
    "two-column": {
        "name": "图文两栏",
        "use_for": "左侧要点、右侧图片或截图；不放图时要点占满全宽",
        "slots": _HEAD + _LEAD + [_s("body", "body", 220, True, 8), _s("image", "image")],
    },
    "cards-3": {
        "name": "三卡片",
        "use_for": "三个并列的举措、成果或特点",
        "slots": _HEAD
        + _LEAD
        + _group("card", 3, ("no", "number", 2, False), ("title", "subtitle", 24, False), ("body", "body", 72, False)),
    },
    "cards-4": {
        "name": "四卡片",
        "use_for": "四个维度或四项工作",
        "slots": _HEAD
        + _group("card", 4, ("no", "number", 2, False), ("title", "subtitle", 18, False), ("body", "body", 60, False)),
    },
    "kpi-4": {
        "name": "关键指标",
        "use_for": "3–4 个关键数字加一句解读",
        "slots": _HEAD
        + _group(
            "kpi",
            4,
            ("number", "number", 5, False),
            ("unit", "caption", 12, False),
            ("label", "label", 10, False),
            ("note", "caption", 36, False),
        )
        + [_s("takeaway.text", "body", 120), _s("source", "caption", 70)],
    },
    "chart-insight": {
        "name": "图表加解读",
        "use_for": "一张趋势或对比图，右侧写读图结论",
        "slots": _HEAD
        + [
            _s("chart", "chart"),
            _s("insight.title", "subtitle", 28),
            _s("insight.body", "body", 100, True, 4),
            _s("source", "caption", 60),
        ],
    },
    "compare": {
        "name": "对比",
        "use_for": "两个方案、改革前后、我们与对标的对比",
        "slots": _HEAD
        + [
            _s("left.title", "subtitle", 22),
            _s("left.body", "body", 130, True, 4),
            _s("right.title", "subtitle", 22),
            _s("right.body", "body", 130, True, 4),
            _s("conclusion.text", "body", 90),
        ],
    },
    "process": {
        "name": "流程",
        "use_for": "3–4 个有先后顺序的步骤",
        "slots": _HEAD
        + _group("step", 4, ("no", "number", 3, False), ("title", "subtitle", 16, False), ("body", "body", 64, False)),
    },
    "timeline": {
        "name": "时间轴",
        "use_for": "3–5 个时间节点的历程或计划",
        "slots": _HEAD
        + _group(
            "node", 5, ("time", "number", 4, False), ("title", "subtitle", 16, False), ("body", "body", 60, False)
        ),
    },
    "table": {
        "name": "表格",
        "use_for": f"任务清单、责任分工、多维对照；不超过 {_TABLE_MAX_ROWS} 行数据",
        "slots": _HEAD + [_s("table", "table"), _s("note", "caption", 110)],
    },
    "closing": {
        "name": "结尾页",
        "use_for": "致谢与联系方式，或收尾的一句话行动号召",
        "dark": True,
        "slots": [_s("title", "title", 12), _s("subtitle", "subtitle", 36), _s("contact", "caption", 88)],
    },
}
for _lid, _layout in LAYOUTS.items():
    _layout["layout_id"] = _lid
    if not _layout.get("dark"):
        _layout["slots"] = [*_layout["slots"], _s("footer", "footer", 50)]


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _esc(text: str) -> str:
    return _html.escape(text, quote=True)


class _View:
    """What a layout renderer sees of one page: escaped slot HTML, or '' when absent."""

    def __init__(self, page: dict):
        self.page = page

    def _absent(self, name: str) -> bool:
        dropped = self.page["dropped"]
        return name in dropped or name.split(".", 1)[0] in dropped

    def has(self, name: str) -> bool:
        """A slot, or a group (``card3``) with at least one filled slot."""
        if self._absent(name):
            return False
        values = self.page["values"]
        return name in values or any(k.startswith(name + ".") for k in values)

    def t(self, name: str, cls: str, tag: str = "div") -> str:
        if self._absent(name) or name not in self.page["values"]:
            return ""
        kind, value = self.page["values"][name]
        attrs = f'class="{cls}" data-slot="{_esc(name)}"'
        if kind == "html":
            return f"<{tag} {attrs}>{value}</{tag}>"
        if kind == "list":
            items = "".join(f"<li>{_esc(x)}</li>" for x in value)
            return f"<ul {attrs}>{items}</ul>"
        if kind == "obj":
            return f"<{tag} {attrs}>{value}</{tag}>"
        return f"<{tag} {attrs}>{'<br>'.join(_esc(x) for x in value.split(chr(10)))}</{tag}>"


def _head(v: _View, lead: bool = False) -> str:
    parts = [v.t("kicker", "kicker"), v.t("title", "title", "h2")]
    if lead:
        parts.append(v.t("lead", "lead", "p"))
    return f'<header class="hd">{"".join(parts)}</header>'


def _r_cover(v):
    return (
        f'<div class="cover-main">{v.t("kicker", "kicker")}{v.t("title", "title", "h1")}'
        f"{v.t('subtitle', 'subtitle', 'p')}</div>"
        f'<div class="cover-meta">{v.t("org", "org")}{v.t("date", "date")}</div>'
    )


def _r_agenda(v):
    rows = "".join(
        f'<li class="item">{v.t(f"item{i}.no", "no")}{v.t(f"item{i}.text", "text")}</li>'
        for i in range(1, 6)
        if v.has(f"item{i}")
    )
    return f'<header class="hd">{v.t("kicker", "kicker")}{v.t("title", "title", "h2")}</header><ol class="bd items">{rows}</ol>'


def _r_section(v):
    return f'{v.t("no", "no")}<div class="section-main">{v.t("title", "title", "h2")}{v.t("subtitle", "subtitle", "p")}</div>'


def _r_statement(v):
    return (
        f'<header class="hd">{v.t("kicker", "kicker")}</header>'
        f'<div class="bd statement-main">{v.t("statement", "statement", "p")}{v.t("support", "support", "p")}'
        f"{v.t('source', 'source', 'p')}</div>"
    )


def _r_two_column(v):
    img = v.t("image", "figure", "figure") if v.has("image") else ""
    cls = "bd cols" if img else "bd cols solo"
    return f'{_head(v, lead=True)}<div class="{cls}">{v.t("body", "points")}{img}</div>'


def _cards(v, n):
    cards = "".join(
        f'<div class="card">{v.t(f"card{i}.no", "no")}{v.t(f"card{i}.title", "card-title", "h3")}'
        f"{v.t(f'card{i}.body', 'card-body', 'p')}</div>"
        for i in range(1, n + 1)
        if v.has(f"card{i}")
    )
    return cards


def _r_cards3(v):
    return f'{_head(v, lead=True)}<div class="bd cards cards-3">{_cards(v, 3)}</div>'


def _r_cards4(v):
    return f'{_head(v)}<div class="bd cards cards-4">{_cards(v, 4)}</div>'


def _r_kpi4(v):
    kpis = "".join(
        f'<div class="kpi">{v.t(f"kpi{i}.label", "kpi-label")}'
        f'<div class="kpi-figure">{v.t(f"kpi{i}.number", "kpi-number", "span")}{v.t(f"kpi{i}.unit", "kpi-unit", "span")}</div>'
        f"{v.t(f'kpi{i}.note', 'kpi-note', 'p')}</div>"
        for i in range(1, 5)
        if v.has(f"kpi{i}")
    )
    takeaway = v.t("takeaway.text", "takeaway", "p")
    return f'{_head(v)}<div class="bd kpi-main"><div class="kpis">{kpis}</div>{takeaway}{v.t("source", "source", "p")}</div>'


def _r_chart_insight(v):
    side = ""
    if v.has("insight"):
        side = f'<aside class="insight">{v.t("insight.title", "insight-title", "h3")}{v.t("insight.body", "points")}</aside>'
    return (
        f'{_head(v)}<div class="bd chart-main">{v.t("chart", "chart", "figure")}{side}</div>'
        f"{v.t('source', 'source source-abs', 'p')}"
    )


def _r_compare(v):
    sides = "".join(
        f'<div class="side side-{k}">{v.t(f"{k}.title", "side-title", "h3")}{v.t(f"{k}.body", "points")}</div>'
        for k in ("left", "right")
        if v.has(k)
    )
    return f'{_head(v)}<div class="bd compare-main"><div class="sides">{sides}</div>{v.t("conclusion.text", "conclusion", "p")}</div>'


def _r_process(v):
    steps = "".join(
        f'<li class="step">{v.t(f"step{i}.no", "no")}{v.t(f"step{i}.title", "step-title", "h3")}'
        f"{v.t(f'step{i}.body', 'step-body', 'p')}</li>"
        for i in range(1, 5)
        if v.has(f"step{i}")
    )
    return f'{_head(v)}<ol class="bd steps">{steps}</ol>'


def _r_timeline(v):
    nodes = "".join(
        f'<li class="node">{v.t(f"node{i}.time", "time")}{v.t(f"node{i}.title", "node-title", "h3")}'
        f"{v.t(f'node{i}.body', 'node-body', 'p')}</li>"
        for i in range(1, 6)
        if v.has(f"node{i}")
    )
    return f'{_head(v)}<ol class="bd nodes">{nodes}</ol>'


def _r_table(v):
    return f'{_head(v)}<div class="bd table-main">{v.t("table", "table-wrap")}{v.t("note", "note", "p")}</div>'


def _r_closing(v):
    return f'<div class="closing-main">{v.t("title", "title", "h2")}{v.t("subtitle", "subtitle", "p")}{v.t("contact", "contact", "p")}</div>'


_RENDER = {
    "cover": _r_cover,
    "agenda": _r_agenda,
    "section": _r_section,
    "statement": _r_statement,
    "two-column": _r_two_column,
    "cards-3": _r_cards3,
    "cards-4": _r_cards4,
    "kpi-4": _r_kpi4,
    "chart-insight": _r_chart_insight,
    "compare": _r_compare,
    "process": _r_process,
    "timeline": _r_timeline,
    "table": _r_table,
    "closing": _r_closing,
}


# ---------------------------------------------------------------------------
# charts: inline SVG coloured by the theme's CSS variables
# ---------------------------------------------------------------------------

_CHART_W, _CHART_H = 700, 440


def _fmt(value: float, number_format: str) -> str:
    pct = number_format.endswith("%")
    core = number_format.rstrip("%")
    decimals = len(core.split(".", 1)[1]) if "." in core else 0
    value = value * 100 if pct else value
    return f"{value:,.{decimals}f}" + ("%" if pct else "")


def _nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    exp = 10 ** (len(str(int(value))) - 1)
    for step in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if step * exp >= value:
            return step * exp
    return 10 * exp


def _legend(names: list[str], w: float) -> str:
    if len(names) < 2:
        return ""
    x, out = 0.0, []
    for i, name in enumerate(names):
        out.append(f'<rect x="{x:.0f}" y="2" width="14" height="14" rx="2" class="s{i % 6}"/>')
        out.append(f'<text x="{x + 20:.0f}" y="15" class="lg">{_esc(name)}</text>')
        x += 36 + text_units(name) * 16
    return f'<g class="legend">{"".join(out)}</g>'


def _bars(kind, categories, series, number_format) -> str:
    w, h = _CHART_W, _CHART_H
    top = 40 if len(series) > 1 else 30
    left, right, bottom = (150, 60, 16) if kind == "bar" else (16, 16, 40)
    pw, ph = w - left - right, h - top - bottom
    stacked = kind == "stacked"
    if stacked:
        vmax = max(sum(s[1][i] for s in series) for i in range(len(categories)))
    else:
        vmax = max(max(s[1]) for s in series)
    vmax = _nice_max(vmax)
    out = [_legend([s[0] for s in series], w)]
    n, m = len(categories), len(series)
    band = (ph if kind == "bar" else pw) / n
    show_labels = n * (1 if stacked else m) <= 16
    for gi in range(5):
        frac = gi / 4
        if kind == "bar":
            x = left + pw * frac
            out.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + ph}" class="grid"/>')
        else:
            y = top + ph * (1 - frac)
            out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + pw}" y2="{y:.1f}" class="grid"/>')
    for ci, cat in enumerate(categories):
        base = 0.0
        for si, (_, values) in enumerate(series):
            val = float(values[ci])
            if kind == "bar":
                thick = band * 0.7 / (1 if stacked else m)
                y = top + band * ci + band * 0.15 + (0 if stacked else thick * si)
                x0 = left + pw * (base / vmax)
                bw = pw * (val / vmax)
                out.append(
                    f'<rect x="{x0:.1f}" y="{y:.1f}" width="{max(bw, 0):.1f}" height="{thick:.1f}" class="s{si % 6}"/>'
                )
                if show_labels:
                    out.append(
                        f'<text x="{x0 + bw + 6:.1f}" y="{y + thick / 2 + 6:.1f}" class="vl">{_fmt(val, number_format)}</text>'
                    )
            else:
                thick = band * 0.62 / (1 if stacked else m)
                x = left + band * ci + band * 0.19 + (0 if stacked else thick * si)
                y1 = top + ph * (1 - (base + val) / vmax)
                y0 = top + ph * (1 - base / vmax)
                out.append(
                    f'<rect x="{x:.1f}" y="{y1:.1f}" width="{thick:.1f}" height="{max(y0 - y1, 0):.1f}" class="s{si % 6}"/>'
                )
                if show_labels and not stacked:
                    out.append(
                        f'<text x="{x + thick / 2:.1f}" y="{y1 - 8:.1f}" class="vl mid">{_fmt(val, number_format)}</text>'
                    )
            if stacked:
                base += val
        if kind == "bar":
            out.append(
                f'<text x="{left - 10}" y="{top + band * ci + band / 2 + 6:.1f}" class="cat end">{_esc(cat)}</text>'
            )
        else:
            out.append(f'<text x="{left + band * ci + band / 2:.1f}" y="{h - 12}" class="cat mid">{_esc(cat)}</text>')
    axis = (
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + ph}" class="axis"/>'
        if kind == "bar"
        else f'<line x1="{left}" y1="{top + ph}" x2="{left + pw}" y2="{top + ph}" class="axis"/>'
    )
    out.append(axis)
    return "".join(out)


def _line(categories, series, number_format) -> str:
    w, h = _CHART_W, _CHART_H
    top = 40 if len(series) > 1 else 30
    left, right, bottom = 24, 24, 40
    pw, ph = w - left - right, h - top - bottom
    vmax = _nice_max(max(max(s[1]) for s in series))
    n = len(categories)
    step = pw / max(n - 1, 1)
    out = [_legend([s[0] for s in series], w)]
    for gi in range(5):
        y = top + ph * (1 - gi / 4)
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + pw}" y2="{y:.1f}" class="grid"/>')
    for si, (_, values) in enumerate(series):
        pts = [(left + step * i, top + ph * (1 - float(v) / vmax)) for i, v in enumerate(values)]
        out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" class="ln l{si % 6}"/>')
        for i, (x, y) in enumerate(pts):
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="s{si % 6}"/>')
            if n <= 12 and (len(series) == 1 or i == n - 1):
                out.append(
                    f'<text x="{x:.1f}" y="{y - 12:.1f}" class="vl mid">{_fmt(float(values[i]), number_format)}</text>'
                )
    for i, cat in enumerate(categories):
        out.append(f'<text x="{left + step * i:.1f}" y="{h - 12}" class="cat mid">{_esc(cat)}</text>')
    return "".join(out)


def _pie(categories, values, number_format, hole: float) -> str:
    import math

    h = _CHART_H
    cx, cy, r = 220, h / 2, 190
    total = sum(float(v) for v in values) or 1.0
    out, angle = [], -math.pi / 2
    for i, v in enumerate(values):
        frac = float(v) / total
        a2 = angle + frac * 2 * math.pi
        large = 1 if frac > 0.5 else 0
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
        if frac >= 0.9999:
            out.append(f'<circle cx="{cx}" cy="{cy:.1f}" r="{r}" class="s{i % 6}"/>')
        else:
            out.append(
                f'<path d="M{cx},{cy:.1f} L{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} Z" class="s{i % 6} slice"/>'
            )
        angle = a2
    if hole:
        out.append(f'<circle cx="{cx}" cy="{cy:.1f}" r="{r * hole:.1f}" class="hole"/>')
    y = cy - len(categories) * 20
    for i, (cat, v) in enumerate(zip(categories, values, strict=True)):
        out.append(f'<rect x="460" y="{y + i * 40:.0f}" width="16" height="16" rx="3" class="s{i % 6}"/>')
        out.append(
            f'<text x="486" y="{y + i * 40 + 14:.0f}" class="lg">{_esc(cat)} {_fmt(float(v), number_format)}'
            f"（{float(v) / total:.0%}）</text>"
        )
    return "".join(out)


def _waterfall(categories, values, number_format) -> str:
    w, h = _CHART_W, _CHART_H
    top, left, right, bottom = 24, 16, 16, 40
    pw, ph = w - left - right, h - top - bottom
    running, tops = 0.0, []
    for i, v in enumerate(values):
        v = float(v)
        if i == 0 or i == len(values) - 1:
            tops.append((0.0, v, "total"))
            running = v
        else:
            lo, hi = (running, running + v) if v >= 0 else (running + v, running)
            tops.append((lo, hi, "up" if v >= 0 else "down"))
            running += v
    vmax = _nice_max(max(t[1] for t in tops))
    n = len(values)
    band = pw / n
    out = []
    for gi in range(5):
        y = top + ph * (1 - gi / 4)
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + pw}" y2="{y:.1f}" class="grid"/>')
    for i, ((lo, hi, kind), cat, v) in enumerate(zip(tops, categories, values, strict=True)):
        x = left + band * i + band * 0.2
        y1, y0 = top + ph * (1 - hi / vmax), top + ph * (1 - lo / vmax)
        cls = {"total": "s0", "up": "s1", "down": "neg"}[kind]
        out.append(
            f'<rect x="{x:.1f}" y="{y1:.1f}" width="{band * 0.6:.1f}" height="{max(y0 - y1, 1):.1f}" class="{cls}"/>'
        )
        out.append(
            f'<text x="{x + band * 0.3:.1f}" y="{y1 - 8:.1f}" class="vl mid">{_fmt(float(v), number_format)}</text>'
        )
        out.append(f'<text x="{left + band * i + band / 2:.1f}" y="{h - 12}" class="cat mid">{_esc(cat)}</text>')
    return "".join(out)


def chart_svg(kind: str, categories, series, number_format: str = "0") -> str:
    categories = [str(c) for c in categories]
    series = [(str(name), [float(x) for x in values]) for name, values in series]
    if not categories or not series:
        raise ValueError("图表需要至少一个类别和一个系列")
    for name, values in series:
        if len(values) != len(categories):
            raise ValueError(f"系列 {name!r} 有 {len(values)} 个值，类别有 {len(categories)} 个")
    if kind in ("column", "bar", "stacked"):
        if min(min(v) for _, v in series) < 0:
            raise ValueError("柱形图暂不支持负值；有增减时用 waterfall")
        body = _bars(kind, categories, series, number_format)
    elif kind == "line":
        body = _line(categories, series, number_format)
    elif kind in ("pie", "doughnut"):
        if len(series) != 1:
            raise ValueError("饼图 / 环形图只接受一个系列")
        body = _pie(categories, series[0][1], number_format, 0.58 if kind == "doughnut" else 0)
    elif kind == "waterfall":
        if len(series) != 1:
            raise ValueError("瀑布图只接受一个系列：第一个和最后一个是总量，中间是增减")
        body = _waterfall(categories, series[0][1], number_format)
    else:
        raise ValueError("kind 取 column / bar / line / stacked / pie / doughnut / waterfall")
    return (
        f'<svg class="ch" viewBox="0 0 {_CHART_W} {_CHART_H}" width="{_CHART_W}" height="{_CHART_H}" '
        f'role="img" xmlns="http://www.w3.org/2000/svg">{body}</svg>'
    )


# ---------------------------------------------------------------------------
# the deck
# ---------------------------------------------------------------------------


class Deck:
    """A deck under construction in one theme."""

    def __init__(self, theme: dict, footer: str | None, title: str | None, css_vars: dict | None = None):
        self.theme = theme
        self.footer = footer
        self.title = title
        self.css_vars = dict(css_vars or {})
        self._pages: list[dict] = []

    @classmethod
    def open(
        cls, theme_id: str, footer: str | None = None, title: str | None = None, css_vars: dict | None = None
    ) -> Deck:
        """Open a theme. ``footer`` goes on every content page; ``title`` is the browser tab title.

        ``css_vars`` overrides size variables for the whole deck, e.g. ``{"--fs-body": "22px"}``
        (one of ``_CSS_VARS``). Capacities assume the defaults, so after enlarging text
        trust check_html's page measurement, not the capacity warnings.
        """
        if theme_id not in THEMES:
            raise ValueError(f"未知主题 {theme_id!r}；可用主题：{', '.join(THEMES)}")
        for key, value in (css_vars or {}).items():
            if key not in _CSS_VARS:
                raise ValueError(f"css_vars 只能改 {', '.join(_CSS_VARS)}，不能改 {key!r}")
            if not re.fullmatch(r"\d{1,3}(\.\d)?px", str(value)):
                raise ValueError(f"{key} 的值要写成像素，如 '22px'，不是 {value!r}")
        return cls(THEMES[theme_id], footer, title, css_vars)

    def add(self, layout_id: str) -> dict:
        """Append a page in ``layout_id`` and return it."""
        if layout_id not in LAYOUTS:
            raise ValueError(f"没有版式 {layout_id!r}；可用：{', '.join(LAYOUTS)}")
        page = {
            "layout_id": layout_id,
            "values": {},
            "filled": {},
            "over_capacity": [],
            "dropped": [],
            "objects": {},
            "raw_html": [],
            "notes": "",
        }
        self._pages.append(page)
        if self.footer and any(s["name"] == "footer" for s in LAYOUTS[layout_id]["slots"]):
            page["values"]["footer"] = ("text", self.footer)
        return page

    # ---- helpers -------------------------------------------------------------
    def _no(self, page: dict) -> int:
        for i, p in enumerate(self._pages):
            if p is page:
                return i + 1
        raise ValueError("这个页面不属于当前 deck，请用 deck.add() 的返回值")

    def _slot(self, page: dict, name: str) -> dict:
        self._no(page)
        for slot in LAYOUTS[page["layout_id"]]["slots"]:
            if slot["name"] == name:
                return slot
        names = [s["name"] for s in LAYOUTS[page["layout_id"]]["slots"]]
        raise KeyError(f"版式 {page['layout_id']} 没有插槽 {name!r}；可用插槽：{', '.join(names)}")

    def _check_capacity(self, page: dict, slot: dict, used: float, unit: str = "字") -> None:
        page["filled"][slot["name"]] = used
        page["over_capacity"] = [e for e in page["over_capacity"] if e["slot"] != slot["name"] or e.get("unit") == "条"]
        if slot["capacity"] and used > slot["capacity"]:
            page["over_capacity"].append({"slot": slot["name"], "used": used, "capacity": slot["capacity"]})
            print(
                f"[超容量] 第{self._no(page)}页 {slot['name']}: {used:g} {unit} > 容量 {slot['capacity']} {unit}"
                " → 精简文案或拆页"
            )

    # ---- text ------------------------------------------------------------------
    def fill(self, page: dict, slot: str, text) -> None:
        """Write text into a slot. A list (or ``\\n``) makes bullet items in a bullet slot, line breaks elsewhere."""
        spec = self._slot(page, slot)
        if spec["role"] not in _TEXT_ROLES:
            raise ValueError(f"插槽 {slot!r} 是 {spec['role']}，请用 deck.chart / deck.table / deck.image")
        if slot in page["dropped"]:
            page["dropped"].remove(slot)
        lines = [str(x) for x in text] if isinstance(text, list | tuple) else str(text).split("\n")
        lines = [x.strip() for x in lines if x.strip()]
        if spec["bullets"]:
            page["values"][slot] = ("list", lines)
            if spec["max_items"] and len(lines) > spec["max_items"]:
                page["over_capacity"].append(
                    {"slot": slot, "used": len(lines), "capacity": spec["max_items"], "unit": "条"}
                )
                print(
                    f"[超容量] 第{self._no(page)}页 {slot}: {len(lines)} 条 > 最多 {spec['max_items']} 条 → 合并要点或拆页"
                )
        else:
            page["values"][slot] = ("text", "\n".join(lines))
        self._check_capacity(page, spec, text_units("".join(lines)))

    def html(self, page: dict, slot: str, fragment: str) -> None:
        """Put a small HTML fragment in a text slot when no layout fits. Styles and scripts are refused."""
        spec = self._slot(page, slot)
        if spec["role"] not in _TEXT_ROLES:
            raise ValueError(f"插槽 {slot!r} 是 {spec['role']}，html 只用于文字插槽")
        if _FORBIDDEN_FRAGMENT.search(fragment):
            raise ValueError("html 片段里不能有 script / style / link / iframe 等标签、事件属性或 javascript: 链接")
        page["values"][slot] = ("html", fragment)
        if slot not in page["raw_html"]:
            page["raw_html"].append(slot)
        self._check_capacity(page, spec, text_units(re.sub(r"<[^>]+>", "", fragment)))

    def drop(self, page: dict, name: str) -> None:
        """Remove a slot or a whole group (``card3`` removes ``card3.*``) you don't need."""
        self._no(page)
        slots = [s["name"] for s in LAYOUTS[page["layout_id"]]["slots"]]
        if name not in slots and not any(s.startswith(name + ".") for s in slots):
            raise KeyError(f"版式 {page['layout_id']} 没有插槽或分组 {name!r}")
        if name not in page["dropped"]:
            page["dropped"].append(name)

    def notes(self, page: dict, text: str) -> None:
        """Speaker notes; kept in the file, not shown on the page."""
        self._no(page)
        page["notes"] = str(text)

    # ---- objects ---------------------------------------------------------------
    def chart(self, page: dict, slot: str, kind: str, categories, series, number_format: str = "0") -> None:
        """Inline SVG chart. kind: column | bar | line | stacked | pie | doughnut | waterfall.

        series: list of (label, values). waterfall: one series, first/last are totals.
        number_format: "0", "0.0", "0%", "0.0%".
        """
        spec = self._slot(page, slot)
        if spec["role"] != "chart":
            raise ValueError(f"插槽 {slot!r} 不是图表区")
        page["values"][slot] = ("obj", chart_svg(kind, categories, series, number_format))
        page["objects"][slot] = kind

    def table(self, page: dict, slot: str, header, rows, highlight_rows=(), col_widths=None) -> None:
        """Table; ``highlight_rows`` are 0-based data-row indexes to flag, ``col_widths`` relative weights."""
        spec = self._slot(page, slot)
        if spec["role"] != "table":
            raise ValueError(f"插槽 {slot!r} 不是表格")
        header = [str(h) for h in header]
        rows = [[str(c) for c in r] for r in rows]
        for i, r in enumerate(rows):
            if len(r) != len(header):
                raise ValueError(f"第 {i + 1} 行有 {len(r)} 列，表头有 {len(header)} 列")
        cols = ""
        if col_widths:
            total = float(sum(col_widths))
            cols = "<colgroup>" + "".join(f'<col style="width:{w / total:.1%}">' for w in col_widths) + "</colgroup>"
        numeric = re.compile(r"^[+\-−]?[\d,.]+%?$")

        def cell(tag, text):
            cls = ' class="n"' if tag == "td" and numeric.match(text.replace(" ", "")) else ""
            return f"<{tag}{cls}>{_esc(text)}</{tag}>"

        head = "<tr>" + "".join(cell("th", h) for h in header) + "</tr>"
        body = "".join(
            f"<tr{' class=hl' if i in set(highlight_rows) else ''}>" + "".join(cell("td", c) for c in r) + "</tr>"
            for i, r in enumerate(rows)
        )
        page["values"][slot] = ("obj", f"<table>{cols}<thead>{head}</thead><tbody>{body}</tbody></table>")
        page["objects"][slot] = "table"
        self._check_capacity(page, {**spec, "capacity": _TABLE_MAX_ROWS}, len(rows), unit="行")

    def image(self, page: dict, slot: str, path: str, fit: str = "cover") -> None:
        """Embed a picture from the workspace (e.g. ``uploads/x.png``) as a data URI. fit: cover | contain."""
        spec = self._slot(page, slot)
        if spec["role"] != "image":
            raise ValueError(f"插槽 {slot!r} 不是图片区")
        mime = mimetypes.guess_type(path)[0] or ""
        if not mime.startswith("image/"):
            raise ValueError(f"{path} 不是图片文件")
        with open(path, "rb") as fh:
            data = fh.read()
        if len(data) > _IMAGE_WARN_BYTES:
            print(f"[提示] 第{self._no(page)}页 {slot}: 图片 {len(data) / 1024 / 1024:.1f} MB，网页会变大，建议先压缩")
        uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        fit = "contain" if fit == "contain" else "cover"
        page["values"][slot] = ("obj", f'<img alt="" src="{uri}" style="object-fit:{fit}">')
        page["objects"][slot] = "image"

    # ---- output ------------------------------------------------------------------
    def _render_page(self, page: dict, no: int, total: int) -> str:
        layout = LAYOUTS[page["layout_id"]]
        view = _View(page)
        inner = _RENDER[page["layout_id"]](view)
        foot = ""
        if not layout.get("dark") or page["layout_id"] == "section":
            foot_text = view.t("footer", "ft-text", "span") if "footer" in page["values"] else "<span></span>"
            foot = f'<footer class="ft">{foot_text}<span class="pg">{no} / {total}</span></footer>'
        notes = f'<aside class="notes" hidden>{_esc(page["notes"])}</aside>' if page["notes"] else ""
        dark = " dark" if layout.get("dark") else ""
        return f'<section class="slide l-{page["layout_id"]}{dark}" data-slide data-layout="{page["layout_id"]}">{inner}{foot}{notes}</section>'

    def render(self) -> str:
        if not self._pages:
            raise ValueError("deck 里还没有页面，先 deck.add(...)")
        with open(os.path.join(ASSETS_DIR, "slides.css"), encoding="utf-8") as fh:
            css = fh.read()
        with open(os.path.join(ASSETS_DIR, "slides.js"), encoding="utf-8") as fh:
            js = fh.read()
        p, d, f = self.theme["palette"], self.theme["dark"], self.theme["fonts"]
        # The second chart series must differ from the first; a theme whose accent is its primary
        # (tech-dark) falls back to the secondary colour.
        series2 = p["secondary"] if p["accent"].lower() == p["primary"].lower() else p["accent"]
        theme_css = (
            f":root{{--primary:#{p['primary']};--secondary:#{p['secondary']};--accent:#{p['accent']};"
            f"--bg:#{p['background']};--surface:#{p['surface']};--text:#{p['text']};--muted:#{p['muted']};"
            f"--dark-bg:#{d['background']};--on-dark:#{d['text']};--series2:#{series2};"
            f"--font-title:{f['title']};--font-body:{f['body']};}}"
        )
        overrides = ""
        if self.css_vars:
            overrides = ":root{" + "".join(f"{k}:{v};" for k, v in self.css_vars.items()) + "}\n"
        title = self.title
        if not title:
            first = self._pages[0]["values"].get("title")
            title = first[1] if first and first[0] == "text" else (self.footer or "演示文稿")
        total = len(self._pages)
        body = "".join(self._render_page(page, i + 1, total) for i, page in enumerate(self._pages))
        return (
            '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{_esc(title.replace(chr(10), ' '))}</title>\n"
            f'<meta name="generator-theme" content="{self.theme["id"]}">\n'
            f"<style>\n{theme_css}\n{css}{overrides}</style>\n</head>\n<body>\n"
            f'<main class="deck">{body}</main>\n<script>\n{js}</script>\n</body>\n</html>\n'
        )

    def save(self, path: str, manifest_dir: str = "scratch") -> str:
        """Write the HTML and ``<manifest_dir>/<name>.manifest.json``; returns the HTML path."""
        doc = self.render()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(doc)
        stem = os.path.splitext(os.path.basename(path))[0]
        os.makedirs(manifest_dir, exist_ok=True)
        manifest = {
            "file": path,
            "theme": self.theme["id"],
            "pages": [
                {
                    "layout_id": p["layout_id"],
                    "filled": p["filled"],
                    "over_capacity": p["over_capacity"],
                    "dropped": p["dropped"],
                    "objects": p["objects"],
                    "raw_html": p["raw_html"],
                    "texts": {
                        k: (v if kind == "text" else " ".join(v) if kind == "list" else "")
                        for k, (kind, v) in p["values"].items()
                        if kind in ("text", "list")
                    },
                }
                for p in self._pages
            ],
        }
        with open(os.path.join(manifest_dir, f"{stem}.manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=1)
        over = sum(len(p["over_capacity"]) for p in self._pages)
        print(
            f"已生成 {path}：{len(self._pages)} 页，主题 {self.theme['name']}（{self.theme['id']}），"
            f"{len(doc.encode('utf-8')) / 1024:.0f} KB；超容量 {over} 处。"
        )
        return path


# ---------------------------------------------------------------------------
# the hand-writing fallback: one sample page per layout
# ---------------------------------------------------------------------------


def sample_deck(theme_id: str = "operating") -> Deck:
    """One page per layout with sample text, written to ``assets/slides/template.html``.

    It is the starting point when no code executor is available: copy the file, keep
    the ``<style>`` and ``<script>``, duplicate the ``<section>`` of the layout you need
    and replace the sample text. ``python slides.py --template`` regenerates it.
    """
    d = Deck.open(theme_id, footer="示例单位 · 示例汇报", title="示例：网页幻灯片模板")
    s = d.add("cover")
    for k, v in {
        "kicker": "示例 · 年度工作汇报",
        "title": "示例：主标题写一句核心判断",
        "subtitle": "示例：副标题补充范围、时间或汇报对象",
        "org": "示例单位名称",
        "date": "2026 年 11 月",
    }.items():
        d.fill(s, k, v)
    s = d.add("agenda")
    d.fill(s, "kicker", "目录")
    d.fill(s, "title", "汇报提纲")
    for i, t in enumerate(["示例：经营概况", "示例：重点工作进展", "示例：问题与原因", "示例：下一步计划"], 1):
        d.fill(s, f"item{i}.no", f"0{i}")
        d.fill(s, f"item{i}.text", t)
    d.drop(s, "item5")
    s = d.add("section")
    d.fill(s, "no", "01")
    d.fill(s, "title", "示例：章节标题")
    d.fill(s, "subtitle", "示例：一句话交代本章要回答的问题")
    s = d.add("statement")
    d.fill(s, "kicker", "示例 · 核心判断")
    d.fill(s, "statement", "示例：用一句话写出这一页要让听众记住的结论")
    d.fill(s, "support", "示例：用一两句话给出依据，数字带单位、期间和来源")
    d.fill(s, "source", "来源：示例资料")
    s = d.add("two-column")
    d.fill(s, "kicker", "示例 · 图文")
    d.fill(s, "title", "示例：标题写结论")
    d.fill(s, "lead", "示例：一句话导语")
    d.fill(s, "body", ["示例：第一条要点", "示例：第二条要点", "示例：第三条要点"])
    d.drop(s, "image")
    for lid, n, group in (("cards-3", 3, "card"), ("cards-4", 4, "card")):
        s = d.add(lid)
        d.fill(s, "kicker", "示例 · 并列要点")
        d.fill(s, "title", "示例：标题写结论")
        if lid == "cards-3":
            d.fill(s, "lead", "示例：一句话导语")
        for i in range(1, n + 1):
            d.fill(s, f"{group}{i}.no", f"0{i}")
            d.fill(s, f"{group}{i}.title", f"示例：要点{i}")
            d.fill(s, f"{group}{i}.body", "示例：两三句话说明这一项的内容与成效")
    s = d.add("kpi-4")
    d.fill(s, "kicker", "示例 · 关键指标")
    d.fill(s, "title", "示例：标题写结论")
    for i, (num, unit, label) in enumerate(
        [
            ("128.6", "亿元", "营业收入"),
            ("10.8", "亿元", "利润总额"),
            ("12.4%", "同比", "增速"),
            ("96", "分", "满意度"),
        ],
        1,
    ):
        d.fill(s, f"kpi{i}.number", num)
        d.fill(s, f"kpi{i}.unit", unit)
        d.fill(s, f"kpi{i}.label", label)
        d.fill(s, f"kpi{i}.note", "示例：一句话解读")
    d.fill(s, "takeaway.text", "示例：一句话总结这组数字说明了什么")
    d.fill(s, "source", "来源：示例资料")
    s = d.add("chart-insight")
    d.fill(s, "kicker", "示例 · 趋势")
    d.fill(s, "title", "示例：标题写结论")
    d.chart(
        s, "chart", "column", ["2023", "2024", "2025", "2026"], [("示例（亿元）", [88.2, 101.5, 114.4, 128.6])], "0.0"
    )
    d.fill(s, "insight.title", "读图要点")
    d.fill(s, "insight.body", ["示例：第一条读图结论", "示例：第二条读图结论"])
    d.fill(s, "source", "来源：示例资料")
    s = d.add("compare")
    d.fill(s, "kicker", "示例 · 对比")
    d.fill(s, "title", "示例：标题写结论")
    for side in ("left", "right"):
        d.fill(s, f"{side}.title", "示例：方案名称")
        d.fill(s, f"{side}.body", ["示例：要点一", "示例：要点二", "示例：要点三"])
    d.fill(s, "conclusion.text", "示例：一句话写出取舍结论")
    s = d.add("process")
    d.fill(s, "kicker", "示例 · 步骤")
    d.fill(s, "title", "示例：标题写结论")
    for i in range(1, 5):
        d.fill(s, f"step{i}.no", f"0{i}")
        d.fill(s, f"step{i}.title", f"示例：步骤{i}")
        d.fill(s, f"step{i}.body", "示例：这一步做什么、谁来做")
    s = d.add("timeline")
    d.fill(s, "kicker", "示例 · 时间轴")
    d.fill(s, "title", "示例：标题写结论")
    for i, t in enumerate(["2026.01", "2026.04", "2026.07", "2026.10"], 1):
        d.fill(s, f"node{i}.time", t)
        d.fill(s, f"node{i}.title", f"示例：节点{i}")
        d.fill(s, f"node{i}.body", "示例：这个节点完成的事项")
    d.drop(s, "node5")
    s = d.add("table")
    d.fill(s, "kicker", "示例 · 清单")
    d.fill(s, "title", "示例：标题写结论")
    d.table(
        s,
        "table",
        ["事项", "责任单位", "完成时限", "进度"],
        [["示例事项一", "示例部门", "2026-12", "85%"], ["示例事项二", "示例部门", "2027-03", "40%"]],
        highlight_rows=(1,),
    )
    d.fill(s, "note", "注：示例说明")
    s = d.add("closing")
    d.fill(s, "title", "谢谢")
    d.fill(s, "subtitle", "示例：欢迎指正")
    d.fill(s, "contact", "示例：联系人与联系方式")
    return d


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--template"]:
        out = os.path.join(ASSETS_DIR, "template.html")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(sample_deck().render())
        print(f"已更新 {out}")
    else:
        print("这是构建库：在构建脚本里 from slides import Deck 使用；--template 重新生成手写模板。")
    sys.exit(0)
