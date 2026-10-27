"""F111: built-in PPT templates and the ``Deck`` builder of the ``bisheng-pptx`` skill.

Covers AC-01 (five templates, ≥12 editable layouts, the 13 common families),
AC-05 (native, editable objects), AC-06 (no prototype pages in the delivered file)
and AC-07 (East-Asian fonts declared).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.oxml.ns import qn

from bisheng.linsight.domain.services.builtin_skill_seeder import BUILTIN_SKILLS_DIR

SKILL_DIR = BUILTIN_SKILLS_DIR / "bisheng-pptx"
SCRIPTS = SKILL_DIR / "scripts"
TEMPLATES = SKILL_DIR / "templates"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from deck_template import Deck, text_units  # noqa: E402

TEMPLATE_IDS = ["gov-red", "blueprint", "operating", "tech-dark", "classroom"]
COMMON = [
    "cover",
    "agenda",
    "section",
    "statement",
    "two-column",
    "cards-3",
    "cards-4",
    "kpi-4",
    "chart-insight",
    "compare",
    "process",
    "timeline",
    "table",
    "closing",
]
CJK_FONTS = {"微软雅黑", "黑体"}


def _spec(template_id: str) -> dict:
    return json.loads((TEMPLATES / template_id / "layouts.json").read_text(encoding="utf-8"))


def _all_text(prs) -> str:
    chunks = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                chunks.append(shape.text_frame.text)
            if shape.has_table:
                for row in shape.table.rows:
                    chunks.extend(cell.text for cell in row.cells)
    return "\n".join(chunks)


# --------------------------------------------------------------------------- #
# the shipped templates
# --------------------------------------------------------------------------- #
def test_catalog_lists_the_five_templates():
    catalog = json.loads((TEMPLATES / "catalog.json").read_text(encoding="utf-8"))
    assert [t["id"] for t in catalog["templates"]] == TEMPLATE_IDS
    for entry in catalog["templates"]:
        assert entry["layout_count"] >= 12
        assert entry["scenes"] and entry["name"]


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_template_matches_its_slot_manifest(template_id):
    spec = _spec(template_id)
    path = TEMPLATES / template_id / "template.pptx"
    assert path.stat().st_size < 500 * 1024, "pre-commit rejects files over 500KB"
    prs = Presentation(str(path))
    assert len(prs.slides) == len(spec["layouts"]) >= 12
    ids = [layout["layout_id"] for layout in spec["layouts"]]
    assert set(COMMON) <= set(ids), f"missing common layouts: {set(COMMON) - set(ids)}"
    assert len(ids) > len(COMMON), "each template carries at least one specialty layout"

    for layout in spec["layouts"]:
        slide = prs.slides[layout["slide_index"]]
        names = {shape.name for shape in slide.shapes}
        for slot in layout["slots"]:
            if slot["role"] == "image_area":
                assert f"{slot['name']}.box" in names
                continue
            assert slot["name"] in names, f"{template_id}/{layout['layout_id']}: slot {slot['name']} not on page"
            if "capacity" in slot:
                assert text_units(slot["sample"]) <= slot["capacity"]
        for group, members in layout["groups"].items():
            assert set(members) <= names, f"{template_id}/{layout['layout_id']}: group {group} incomplete"


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_template_declares_east_asian_fonts(template_id):
    prs = Presentation(str(TEMPLATES / template_id / "template.pptx"))
    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    ea = run._r.find(f"{qn('a:rPr')}/{qn('a:ea')}")
                    assert ea is not None and ea.get("typeface") in CJK_FONTS, (
                        f"{template_id}: run {run.text!r} in {shape.name} has no CJK <a:ea>"
                    )
    theme_xml = (
        prs.slide_masters[0]
        .part.part_related_by("http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme")
        .blob.decode("utf-8")
    )
    assert "微软雅黑" in theme_xml


# --------------------------------------------------------------------------- #
# Deck: clone, fill, native objects, save
# --------------------------------------------------------------------------- #
@pytest.fixture()
def photo(tmp_path) -> str:
    path = tmp_path / "photo.png"
    Image.new("RGB", (1600, 900), "#336699").save(path)
    return str(path)


def _build_sample(tmp_path, photo, template_id="gov-red", footer="示范集团 · 年度汇报"):
    deck = Deck.open(template_id, footer=footer)
    s = deck.add("cover")
    deck.fill(s, "title", "2026 年度工作汇报")
    deck.fill(s, "subtitle", "向集团党委汇报")
    deck.fill(s, "kicker", "年度汇报")
    deck.fill(s, "org", "示范集团")
    deck.fill(s, "date", "2026 年 12 月")
    if "highlight" in deck.layouts["cover"]["groups"]:
        deck.drop(s, "highlight")

    s = deck.add("cards-3")
    deck.fill(s, "title", "三项改革全部落地")
    deck.fill(s, "kicker", "02 · 改革")
    deck.fill(s, "lead", "改革围绕降本、提效、强管控展开")
    for i in (1, 2):
        deck.fill(s, f"card{i}.no", f"0{i}")
        deck.fill(s, f"card{i}.title", f"改革{i}")
        deck.fill(s, f"card{i}.body", "做了什么，带来什么变化。")
    deck.drop(s, "card3")

    s = deck.add("chart-insight")
    deck.fill(s, "title", "营收四年增长 48%")
    deck.fill(s, "kicker", "03 · 经营")
    deck.chart(s, "chart", "column", ["2022", "2023", "2024", "2025"], [("营收（亿元）", [82, 95, 108, 121])])
    deck.fill(s, "insight.title", "读图")
    deck.fill(s, "insight.body", ["2024 年起提速", "新业务贡献过半"])
    deck.fill(s, "source", "来源：年报")

    s = deck.add("table")
    deck.fill(s, "title", "重点任务清单")
    deck.fill(s, "kicker", "04 · 任务")
    rows = [[f"任务{i}", "办公室", "2026-12", "推进中"] for i in range(1, 7)]
    deck.table(s, "table", ["事项", "责任单位", "时限", "进展"], rows, highlight_rows=(1,))
    deck.fill(s, "note", "第二项需要协调。")

    s = deck.add("two-column")
    deck.fill(s, "title", "现场照片")
    deck.fill(s, "kicker", "05 · 现场")
    deck.fill(s, "lead", "项目已投产")
    deck.fill(s, "body", ["要点一", "要点二"])
    deck.image(s, "image", photo)

    s = deck.add("closing")
    deck.fill(s, "title", "感谢聆听")
    deck.drop(s, "subtitle")
    deck.fill(s, "contact", "示范集团办公室")

    out = tmp_path / "output" / "年度汇报.pptx"
    manifest_path = deck.save(str(out), manifest_dir=str(tmp_path / "scratch"))
    return out, Path(manifest_path)


def test_deck_round_trip_drops_prototypes_and_keeps_native_objects(tmp_path, photo):
    out, manifest_path = _build_sample(tmp_path, photo)
    prs = Presentation(str(out))
    assert len(prs.slides) == 6, "prototype pages must not reach the delivered file (AC-06)"

    text = _all_text(prs)
    assert "2026 年度工作汇报" in text and "示范集团 · 年度汇报" in text
    for leftover in ("示例：主标题写一句核心判断或文稿名称", "示例：要点三的小标题"):
        assert leftover not in text

    cards = prs.slides[1]
    assert not [s for s in cards.shapes if s.name.startswith("card3.")], "drop('card3') removes the whole group"

    chart_page = prs.slides[2]
    charts = [s for s in chart_page.shapes if s.has_chart]
    assert len(charts) == 1 and charts[0].name == "chart"
    assert list(charts[0].chart.plots[0].categories) == ["2022", "2023", "2024", "2025"]

    table_page = prs.slides[3]
    tables = [s for s in table_page.shapes if s.has_table]
    assert len(tables) == 1 and len(tables[0].table.rows) == 7

    picture_page = prs.slides[4]
    assert any(s.shape_type == 13 for s in picture_page.shapes), "image() inserts a real picture"
    assert not [s for s in picture_page.shapes if s.name.startswith("image.")], "placeholder box/label removed"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["template"] == "gov-red"
    assert [p["layout_id"] for p in manifest["pages"]] == [
        "cover",
        "cards-3",
        "chart-insight",
        "table",
        "two-column",
        "closing",
    ]
    assert manifest["pages"][2]["objects"] == {"chart": "column"}
    assert manifest["pages"][0]["unfilled"] == []


def test_cloned_chart_pages_do_not_share_a_chart_part(tmp_path):
    deck = Deck.open("operating")
    for values in ([1, 2, 3], [7, 8, 9]):
        s = deck.add("chart-insight")
        deck.chart(s, "chart", "line", ["a", "b", "c"], [("x", values)])
    out = tmp_path / "two.pptx"
    deck.save(str(out), manifest_dir=str(tmp_path))
    prs = Presentation(str(out))
    parts = [s.chart.part.partname for slide in prs.slides for s in slide.shapes if s.has_chart]
    assert len(parts) == 2 and len(set(parts)) == 2
    first = [s for s in prs.slides[0].shapes if s.has_chart][0].chart
    assert list(first.plots[0].series[0].values) == [1, 2, 3]


def test_waterfall_and_footer_removal(tmp_path):
    deck = Deck.open("operating", footer=None)
    s = deck.add("bridge")
    deck.chart(s, "chart", "waterfall", ["起点", "价格", "销量", "终点"], [("变动", [100, 5, -3, 102])], "0.0")
    out = tmp_path / "bridge.pptx"
    deck.save(str(out), manifest_dir=str(tmp_path))
    slide = Presentation(str(out)).slides[0]
    assert not [sh for sh in slide.shapes if sh.name == "footer"], "footer=None removes the footer slot"
    chart = [sh for sh in slide.shapes if sh.has_chart][0].chart
    assert list(chart.plots[0].series[0].values) == [0.0, 100.0, 102.0, 0.0]  # invisible base: +5 sits on 100, -3 hangs from 105
    assert list(chart.plots[0].series[1].values) == [100.0, 5.0, 3.0, 102.0]


def test_over_capacity_is_reported_and_recorded(tmp_path, capsys):
    deck = Deck.open("blueprint")
    s = deck.add("statement")
    deck.fill(s, "statement", "超" * 200)
    assert "[超容量]" in capsys.readouterr().out
    manifest = json.loads(Path(deck.save(str(tmp_path / "x.pptx"), manifest_dir=str(tmp_path))).read_text())
    over = manifest["pages"][0]["over_capacity"]
    assert over and over[0]["slot"] == "statement" and over[0]["used"] == 200


def test_unfilled_slots_are_listed(tmp_path):
    deck = Deck.open("classroom")
    s = deck.add("cards-4")
    deck.fill(s, "title", "四个维度")
    manifest = json.loads(Path(deck.save(str(tmp_path / "y.pptx"), manifest_dir=str(tmp_path))).read_text())
    assert "card1.title" in manifest["pages"][0]["unfilled"]
    assert "title" not in manifest["pages"][0]["unfilled"]


def test_helpful_errors_for_unknown_names():
    deck = Deck.open("tech-dark")
    with pytest.raises(ValueError, match="没有版式"):
        deck.add("no-such-layout")
    s = deck.add("kpi-4")
    with pytest.raises(KeyError, match="可用插槽"):
        deck.fill(s, "nope", "x")
    chart_page = deck.add("chart-insight")
    with pytest.raises(ValueError, match="deck.chart"):
        deck.fill(chart_page, "chart", "x")
    with pytest.raises(ValueError, match="未知模板"):
        Deck.open("does-not-exist")
