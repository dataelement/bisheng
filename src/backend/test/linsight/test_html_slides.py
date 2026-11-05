"""F006: the web-slide branch of the html-report skill (scripts/slides.py and friends).

Self-tested in both directions (builtin_skills/AGENTS.md): a deck filled to every
slot's capacity must fit every page in every theme, and bad input must trip the
build warnings and the self-check. Rendering tests need a launchable Chromium and
skip elsewhere, like test_check_html.py.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import xml.dom.minidom
from pathlib import Path

import pytest

from bisheng.tool.domain.langchain import linsight_html_check as hc

SKILLS = Path(__file__).resolve().parents[2] / "bisheng" / "linsight" / "builtin_skills"
PACK = SKILLS / "html-report"
SCRIPTS = PACK / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_f006_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


slides = _load("slides")
check_slides = _load("check_slides")

_TEXT = "营收增长结构优化成本下降效率提升风险可控数字转型协同发展质量第一"


def _words(n) -> str:
    n = int(n)
    return (_TEXT * (n // len(_TEXT) + 1))[:n]


def _full_deck(theme: str):
    """Every slot of every layout filled to its capacity (bullet slots: max items)."""
    d = slides.Deck.open(theme, footer=_words(50))
    for lid, layout in slides.LAYOUTS.items():
        s = d.add(lid)
        for slot in layout["slots"]:
            name, role, cap = slot["name"], slot["role"], slot["capacity"]
            if name == "footer":
                continue
            if role == "chart":
                d.chart(
                    s,
                    name,
                    "column",
                    ["2022", "2023", "2024", "2025", "2026"],
                    [("营收", [76.6, 88.2, 101.5, 114.4, 128.6]), ("利润", [6, 7, 8, 9, 10])],
                    "0.0",
                )
            elif role == "table":
                d.table(
                    s,
                    name,
                    ["事项", "责任单位", "完成时限", "进度"],
                    [[_words(14), _words(6), "2026-12", "85%"] for _ in range(8)],
                )
            elif role == "image":
                d.drop(s, name)
            elif role == "number":
                d.fill(s, name, "8" * int(cap * 2))
            elif slot["bullets"]:
                k = slot["max_items"]
                d.fill(s, name, [_words(cap // k)] * k)
            else:
                d.fill(s, name, _words(cap))
    return d


def _small_deck():
    d = slides.Deck.open("operating", footer="某集团 · 汇报")
    s = d.add("cover")
    d.fill(s, "title", "2026 年度经营汇报")
    s = d.add("statement")
    d.fill(s, "statement", "营收连续四年增长")
    s = d.add("closing")
    d.fill(s, "title", "谢谢")
    return d


# ---------------------------------------------------------------------------
# consistency with the PPT skill (AC-06 / AC-07)
# ---------------------------------------------------------------------------


def _pptx_catalog():
    return json.loads((SKILLS / "bisheng-pptx" / "templates" / "catalog.json").read_text(encoding="utf-8"))["templates"]


def test_themes_match_the_pptx_catalog():
    catalog = {t["id"]: t for t in _pptx_catalog()}
    assert set(slides.THEMES) == set(catalog)
    for tid, theme in slides.THEMES.items():
        assert theme["name"] == catalog[tid]["name"]
        assert theme["palette"] == catalog[tid]["palette"], f"{tid} palette drifted from the PPT templates"


def test_layouts_are_the_layouts_every_pptx_template_shares():
    shared = set.intersection(*(set(t["layouts"]) for t in _pptx_catalog()))
    assert set(slides.LAYOUTS) == shared


def test_committed_template_is_the_generated_sample():
    committed = (PACK / "assets" / "slides" / "template.html").read_text(encoding="utf-8")
    assert committed == slides.sample_deck().render(), "regenerate with: python scripts/slides.py --template"


# ---------------------------------------------------------------------------
# build API (AC-08 / AC-09 / AC-10)
# ---------------------------------------------------------------------------


def test_over_capacity_is_printed_and_recorded(capsys):
    d = slides.Deck.open("operating")
    s = d.add("statement")
    d.fill(s, "statement", _words(80))
    out = capsys.readouterr().out
    assert "[超容量] 第1页 statement: 80 字 > 容量 60 字" in out
    assert s["over_capacity"] == [{"slot": "statement", "used": 80, "capacity": 60}]
    d.fill(s, "statement", _words(20))
    assert s["over_capacity"] == []


def test_too_many_bullets_are_flagged(capsys):
    d = slides.Deck.open("operating")
    s = d.add("compare")
    d.fill(s, "left.body", ["一", "二", "三", "四", "五"])
    assert "5 条 > 最多 4 条" in capsys.readouterr().out
    assert s["over_capacity"][0]["unit"] == "条"


def test_too_many_table_rows_are_flagged(capsys):
    d = slides.Deck.open("operating")
    s = d.add("table")
    d.table(s, "table", ["a", "b"], [["1", "2"]] * 9)
    assert "9 行 > 容量 8 行" in capsys.readouterr().out


def test_unknown_slot_lists_the_available_ones():
    d = slides.Deck.open("operating")
    s = d.add("cards-3")
    with pytest.raises(KeyError, match="可用插槽"):
        d.fill(s, "card9.title", "x")
    with pytest.raises(ValueError, match=r"deck\.chart"):
        d.fill(s, "title", "ok") or d.fill(d.add("chart-insight"), "chart", "x")


def test_drop_removes_a_whole_group_from_the_page():
    d = slides.Deck.open("operating")
    s = d.add("cards-3")
    for i in (1, 2, 3):
        d.fill(s, f"card{i}.title", f"卡片{i}")
    d.drop(s, "card3")
    html = d.render()
    assert "卡片1" in html and "卡片3" not in html


def test_html_fragment_refuses_scripts_and_is_recorded():
    d = slides.Deck.open("operating")
    s = d.add("statement")
    with pytest.raises(ValueError):
        d.html(s, "support", "<b onclick='x()'>a</b>")
    with pytest.raises(ValueError):
        d.html(s, "support", "<script>1</script>")
    d.html(s, "support", "<b>重点</b>文字")
    assert s["raw_html"] == ["support"]
    assert "<b>重点</b>文字" in d.render()


def test_text_is_escaped():
    d = slides.Deck.open("operating")
    s = d.add("statement")
    d.fill(s, "statement", "<img src=x onerror=alert(1)>")
    assert "<img src=x" not in d.render()


def test_css_vars_are_validated_and_win_over_the_defaults():
    with pytest.raises(ValueError):
        slides.Deck.open("operating", css_vars={"--w": "2000px"})
    with pytest.raises(ValueError):
        slides.Deck.open("operating", css_vars={"--fs-body": "big"})
    d = slides.Deck.open("operating", css_vars={"--fs-body": "24px"})
    d.add("statement")
    html = d.render()
    assert html.index("--fs-body:24px") > html.index("--fs-body: 20px")


@pytest.mark.parametrize("kind", ["column", "bar", "line", "stacked", "pie", "doughnut", "waterfall"])
def test_every_chart_kind_is_well_formed_svg(kind):
    series = (
        [("营收", [10, 12, 15, 18])]
        if kind in ("pie", "doughnut", "waterfall")
        else [
            ("营收", [10, 12, 15, 18]),
            ("利润", [1, 2, 3, 4]),
        ]
    )
    svg = slides.chart_svg(kind, ["一", "二", "三", "四"], series, "0.0")
    xml.dom.minidom.parseString(svg)


def test_chart_input_errors_are_explained():
    with pytest.raises(ValueError, match="个值"):
        slides.chart_svg("column", ["a", "b"], [("s", [1])])
    with pytest.raises(ValueError, match="waterfall"):
        slides.chart_svg("column", ["a"], [("s", [-1])])
    with pytest.raises(ValueError, match="一个系列"):
        slides.chart_svg("pie", ["a"], [("s", [1]), ("t", [2])])


def test_saved_deck_is_self_contained_and_paged(tmp_path):
    d = _small_deck()
    out = d.save(str(tmp_path / "output" / "汇报.html"), manifest_dir=str(tmp_path / "scratch"))
    html = Path(out).read_text(encoding="utf-8")
    assert [f for f in hc.static_findings(html) if f.level == hc.ERROR] == []
    assert html.count('<section class="slide ') == 3
    manifest = json.loads((tmp_path / "scratch" / "汇报.manifest.json").read_text(encoding="utf-8"))
    assert [p["layout_id"] for p in manifest["pages"]] == ["cover", "statement", "closing"]


# ---------------------------------------------------------------------------
# self-check (AC-11)
# ---------------------------------------------------------------------------


def _saved(tmp_path, deck):
    out = deck.save(str(tmp_path / "x.html"), manifest_dir=str(tmp_path))
    return out, str(tmp_path)


def test_check_slides_passes_a_good_deck(tmp_path):
    findings, n = check_slides.check(*_saved(tmp_path, _small_deck()))
    assert n == 3 and findings == []


def test_check_slides_warns_on_content_problems(tmp_path):
    d = slides.Deck.open("operating")
    for _ in range(3):
        s = d.add("statement")
        d.fill(s, "statement", "示例：一句话结论")
    d.add("cards-3")  # title never filled
    s = d.add("chart-insight")
    d.fill(s, "title", "图")
    findings, _ = check_slides.check(*_saved(tmp_path, d))
    text = "\n".join(m for _, m in findings)
    assert {lvl for lvl, _ in findings} == {"WARN"}
    assert "连续三页都是 statement" in text
    assert "像是占位文字" in text
    assert "第4页 title：标题没有填写" in text
    assert "第5页 chart：图表区没有放图表" in text


def test_check_slides_errors_when_the_page_was_hand_edited(tmp_path):
    out, mdir = _saved(tmp_path, _small_deck())
    html = Path(out).read_text(encoding="utf-8")
    Path(out).write_text(html.replace('<section class="slide l-closing', '<div class="x'), encoding="utf-8")
    findings, _ = check_slides.check(out, mdir)
    assert findings[0][0] == "ERROR"
    assert check_slides.check(str(tmp_path / "none.html"), mdir)[0][0][0] == "ERROR"


def test_verdict_is_printed_only_by_the_self_check():
    """The string the model stops on (builtin_skills/AGENTS.md) has one owner per pack."""
    owners = [
        p.relative_to(PACK).as_posix()
        for p in PACK.rglob("*.py")
        if check_slides.PASS_VERDICT in p.read_text(encoding="utf-8")
    ]
    assert owners == ["scripts/check_slides.py"]
    assert check_slides.PASS_VERDICT != hc.PASS_VERDICT


@pytest.mark.parametrize("script", ["list_layouts.py", "check_slides.py", "slides.py"])
def test_scripts_exit_zero(script, tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPTS / script)], capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip()


# ---------------------------------------------------------------------------
# rendering: capacities are calibrated (AC-09) and pages are measured (AC-10)
# ---------------------------------------------------------------------------


def _chromium_available() -> bool:
    _, _, unavailable = hc._render_findings("<html><body><p>x</p></body></html>")
    return unavailable is None


chromium = pytest.mark.skipif(not _chromium_available(), reason="Playwright Chromium not launchable here")


@chromium
@pytest.mark.parametrize("theme", sorted(slides.THEMES))
def test_a_deck_filled_to_capacity_fits_every_page(theme):
    findings, _, unavailable = hc._render_findings(_full_deck(theme).render())
    assert unavailable is None
    assert [f.detail for f in findings if f.topic == "分页溢出"] == []
    pages = len(slides.LAYOUTS)
    assert any(f.detail.startswith(f"共 {pages} 页，逐页测量 {pages} 页，均未溢出") for f in findings)
    assert [f for f in findings if f.level == hc.ERROR] == []


@chromium
def test_the_sample_template_passes_check_html():
    html = (PACK / "assets" / "slides" / "template.html").read_text(encoding="utf-8")
    findings, _, _ = hc._render_findings(html)
    assert [f for f in findings if f.level in (hc.ERROR, hc.WARN)] == []


@chromium
def test_text_past_capacity_overflows_the_page_and_is_measured():
    """The other direction: the capacity is not slack — exceeding it breaks the page."""
    d = slides.Deck.open("operating")
    s = d.add("compare")
    d.fill(s, "title", "对比")
    for side in ("left", "right"):
        d.fill(s, f"{side}.title", _words(22))
        d.fill(s, f"{side}.body", [_words(60)] * 6)
    d.fill(s, "conclusion.text", _words(90))
    findings, _, _ = hc._render_findings(d.render())
    assert [f.detail[:5] for f in findings if f.topic == "分页溢出"] == ["第 1 页"]


@pytest.mark.parametrize("kind", ["column", "line", "stacked"])
def test_value_labels_of_the_tallest_bar_stay_inside_the_chart(kind):
    """114 run 96ce9c75: a 148 bar under a 150 axis put its label above the SVG edge."""
    import re

    svg = slides.chart_svg(kind, ["a", "b", "c", "d"], [("s", [148, 142, 138, 108])])
    ys = [float(y) for y in re.findall(r'<text x="[\d.]+" y="([\d.-]+)" class="vl', svg)]
    assert ys and min(ys) >= 18
