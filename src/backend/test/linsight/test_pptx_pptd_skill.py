"""F014: the built-in PPT skill (``bisheng-pptx``) on the PPTD engine.

Static checks run everywhere. The engine tests need the PPTD runtime
(``/opt/pptd-runtime``, or ``PPTD_RUNTIME``) and skip without it; CI images and
source deployments install it via ``pptd_runtime/install.sh``.
"""

from __future__ import annotations

import importlib.util
import io
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from bisheng.linsight.domain.services import builtin_skill_seeder as seeder

PACK = seeder.BUILTIN_SKILLS_DIR / "bisheng-pptx"
SCRIPT = PACK / "scripts" / "pptd.py"
TEMPLATES = PACK / "templates"
RUNTIME = Path(os.environ.get("PPTD_RUNTIME", "/opt/pptd-runtime"))
HAS_ENGINE = (RUNTIME / "bin" / "node").exists() and (RUNTIME / "engine" / "lib" / "bin.js").exists()
needs_engine = pytest.mark.skipif(not HAS_ENGINE, reason="PPTD runtime not installed")

TEMPLATE_IDS = sorted(p.name for p in TEMPLATES.iterdir() if p.is_dir() and p.name != "licenses")


def _load_pptd():
    spec = importlib.util.spec_from_file_location("pptd_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pptd = _load_pptd()


def run_pptd(*args, cwd: Path, runtime: Path | None = None) -> str:
    env = dict(os.environ)
    if runtime is not None:
        env["PPTD_RUNTIME"] = str(runtime)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)], cwd=cwd, capture_output=True, text=True, env=env, timeout=300
    )
    assert proc.returncode == 0, f"pptd.py must exit 0 (the executor drops stdout otherwise):\n{proc.stderr}"
    return proc.stdout


def write_project(root: Path, pages: list[dict], theme: dict | None = None) -> Path:
    (root / "pages").mkdir(parents=True)
    manifest = {
        "version": "v2",
        "title": "测试",
        "size": [960, 540],
        "pages": [f"pages/{i + 1:02d}.page" for i in range(len(pages))],
    }
    if theme:
        manifest["theme"] = theme
    (root / "deck.pptd").write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    for i, page in enumerate(pages):
        (root / manifest["pages"][i]).write_text(yaml.safe_dump(page, allow_unicode=True), encoding="utf-8")
    return root


def text_el(eid, text, size, y=60):
    return {
        "elementId": eid,
        "elementType": "text",
        "bounds": [48, y, 860, 60],
        "content": {"text": text, "fontSize": size, "fontFamily": {"latin": "Arial", "ea": "Microsoft YaHei"}},
    }


# --------------------------------------------------------------------------- #
# pack shape
# --------------------------------------------------------------------------- #
def test_frontmatter_keeps_the_identity_and_adds_no_default_check():
    """AC-17: same name + display name so the seeder updates the existing row in place;
    no default-checked (2026-11-11 decision)."""
    meta, _ = seeder.discover_builtin_bundles()["bisheng-pptx"]
    assert meta["name"] == "bisheng-pptx"
    assert set(meta) <= {"name", "description", "metadata"}
    assert meta["metadata"] == {"display-name": "PPT 制作"}
    assert "网页报告" in meta["description"], "the .pptx / web-slides boundary must be stated (AC-05)"


def test_old_python_pptx_pipeline_is_gone():
    _, files = seeder.discover_builtin_bundles()["bisheng-pptx"]
    assert sorted(p for p in files if p.startswith("scripts/")) == ["scripts/pptd.py"]
    assert not any(p.endswith((".pptx", ".json")) for p in files)


_BRANDS = re.compile(r"(?i)(?<![a-z])dsh(?![a-z])|deepseek|workbuddy|bisheng|毕昇|灵思|linsight|dataelement")


def test_no_brand_on_the_customer_readable_surface():
    """AC-13. The skill id and in-pack paths (``bisheng-pptx``) are technical identifiers
    and stay; everything else a customer can read must be brand-free."""
    _, files = seeder.discover_builtin_bundles()["bisheng-pptx"]
    for rel, data in files.items():
        if rel.startswith("templates/licenses/"):
            continue
        text = data.decode("utf-8").replace("bisheng-pptx", "")
        hit = _BRANDS.search(text)
        assert not hit, f"{rel} mentions {hit.group(0)!r}"


def test_seventeen_templates_each_with_a_complete_reference_project():
    assert len(TEMPLATE_IDS) == 17 and "gov-red" in TEMPLATE_IDS
    for tid in TEMPLATE_IDS:
        src = TEMPLATES / tid / "source-zh"
        assert (TEMPLATES / tid / "design.md").is_file(), tid
        manifest = yaml.safe_load((src / "deck.pptd").read_text(encoding="utf-8"))
        assert manifest["template"]["id"] == tid, f"{tid}: deck.pptd template id"
        assert len(manifest["pages"]) == 12, tid
        for rel in manifest["pages"]:
            page = yaml.safe_load((src / rel).read_text(encoding="utf-8"))
            assert page["elements"], f"{tid}/{rel} is empty"


def test_catalog_lists_every_template_and_puts_gov_red_first():
    catalog = (TEMPLATES / "catalog.md").read_text(encoding="utf-8")
    listed = re.findall(r"^\| ([a-z0-9-]+) \|", catalog, flags=re.M)
    assert listed[0] == "gov-red"
    assert sorted(listed) == TEMPLATE_IDS


def test_adapted_templates_keep_their_license():
    notice = (TEMPLATES / "LICENSES.md").read_text(encoding="utf-8")
    for tid in TEMPLATE_IDS:
        assert tid in notice, f"{tid} has no provenance line"
    for name in ("zara-MIT.txt", "html-anything-Apache-2.0.txt"):
        assert (TEMPLATES / "licenses" / name).is_file()


def test_paths_the_prompt_teaches_exist():
    """Call the tools the way the prompt teaches (builtin_skills/AGENTS.md, Working method)."""
    root = seeder.BUILTIN_SKILLS_DIR
    prose = (PACK / "SKILL.md").read_text(encoding="utf-8") + (PACK / "references" / "pptd.md").read_text(
        encoding="utf-8"
    )
    paths = set(re.findall(r"skills/(bisheng-pptx/[\w./-]+\.(?:py|md|page))", prose))
    assert paths
    for rel in paths:
        assert (root / rel).is_file(), f"prompt points at missing {rel}"


# --------------------------------------------------------------------------- #
# pptd.py without the engine
# --------------------------------------------------------------------------- #
def test_missing_engine_is_reported_and_exits_zero(tmp_path):
    """AC-04: tell the user, never fall back."""
    out = run_pptd("check", tmp_path, cwd=tmp_path, runtime=tmp_path / "nowhere")
    assert "当前环境未安装 PPT 引擎，请联系管理员" in out
    assert pptd.FAIL in out and pptd.PASS not in out
    out = run_pptd("env", cwd=tmp_path, runtime=tmp_path / "nowhere")
    assert "不可用" in out


def test_font_floor_flags_small_body_note_and_table_text(tmp_path):
    """AC-09, bad direction."""
    table = {
        "elementId": "t",
        "elementType": "table",
        "bounds": [48, 200, 860, 200],
        "style": "$grid",
        "rows": [[{"text": "指标"}, {"text": "数值"}], [{"text": "营业收入"}, {"text": "386 亿元"}]],
    }
    theme = {"tableStyles": {"grid": {"cellStyle": {"fontSize": 9.5}, "firstRowStyle": {"fontSize": 8}}}}
    page = {
        "elements": [
            text_el("body", "这是一段超过二十四个字的正文，用来说明字号过小时在投影上无法看清的问题。", 10),
            text_el("note", "来源：示例", 8, y=140),
            table,
        ]
    }
    issues = pptd.font_issues(str(write_project(tmp_path / "deck", [page], theme)))
    joined = "\n".join(issues)
    assert "「body」 正文 10pt < 11pt" in joined
    assert "「note」 短标签/注释 8pt < 9pt" in joined
    assert "「t」 表格正文 9.5pt < 11pt" in joined
    assert "「t」 表头 8pt < 9pt" in joined


def test_font_floor_passes_readable_text_and_resolves_styles(tmp_path):
    """AC-09, good direction — the floor must be satisfiable."""
    theme = {"textStyles": {"body": {"fontSize": 13}}}
    page = {
        "elements": [
            {
                "elementId": "styled",
                "elementType": "text",
                "bounds": [48, 60, 860, 60],
                "content": {"text": "正文" * 20, "style": "$body"},
            },
            text_el("note", "来源：示例", 9, y=140),
        ]
    }
    assert pptd.font_issues(str(write_project(tmp_path / "deck", [page], theme))) == []


def test_missing_pyyaml_skips_the_floor_instead_of_blocking(tmp_path, monkeypatch):
    """A skipped check is not a finding: it must not block render."""
    import builtins

    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_yaml)
    assert pptd.font_issues(str(tmp_path)) is None


def test_gov_red_reference_pages_meet_the_floor():
    assert pptd.font_issues(str(TEMPLATES / "gov-red" / "source-zh")) == []


def test_fix_fonts_rewrites_mac_and_linux_cjk_faces(tmp_path):
    """AC-10: Windows has none of PingFang / Noto; leave Latin faces alone."""
    deck = tmp_path / "x.pptx"
    with zipfile.ZipFile(deck, "w") as z:
        z.writestr(
            "ppt/slides/slide1.xml",
            '<a:ea typeface="Noto Sans CJK SC"/><a:ea typeface="PingFang SC"/><a:latin typeface="Arial"/>',
        )
        z.writestr("docProps/thumbnail.jpeg", b"\xff\xd8binary")
    assert pptd.fix_fonts(str(deck)) == 2
    with zipfile.ZipFile(deck) as z:
        xml = z.read("ppt/slides/slide1.xml").decode()
        assert z.read("docProps/thumbnail.jpeg") == b"\xff\xd8binary"
    assert xml.count('typeface="Microsoft YaHei"') == 2 and 'typeface="Arial"' in xml


# --------------------------------------------------------------------------- #
# with the engine
# --------------------------------------------------------------------------- #
def _typefaces(pptx: Path) -> set[str]:
    with zipfile.ZipFile(pptx) as z:
        xml = "".join(z.read(n).decode("utf-8") for n in z.namelist() if n.startswith("ppt/slides/slide"))
    return set(re.findall(r'typeface="([^"]+)"', xml))


@needs_engine
def test_gov_red_checks_and_renders_with_windows_fonts(tmp_path):
    """AC-01 / AC-10 / AC-12: native objects only, YaHei + Arial only."""
    import shutil

    shutil.copytree(TEMPLATES / "gov-red" / "source-zh", tmp_path / "scratch" / "deck")
    out = run_pptd("check", "scratch/deck", cwd=tmp_path)
    assert pptd.PASS in out, out
    out = run_pptd("render", "scratch/deck", "output/政企红.pptx", cwd=tmp_path)
    assert "已导出" in out and "12 页" in out, out
    deck = tmp_path / "output" / "政企红.pptx"
    assert _typefaces(deck) <= {"Microsoft YaHei", "Arial"}
    with zipfile.ZipFile(deck) as z:
        media = [n for n in z.namelist() if n.startswith("ppt/media/") and not n.endswith("/")]
        assert not media, f"no full-page images: {media}"


@needs_engine
def test_render_refuses_a_deck_below_the_floor(tmp_path):
    write_project(tmp_path / "scratch" / "deck", [{"elements": [text_el("t", "正文" * 20, 9)]}])
    out = run_pptd("render", "scratch/deck", "output/x.pptx", cwd=tmp_path)
    assert "未导出" in out and not (tmp_path / "output" / "x.pptx").exists()


@needs_engine
def test_convert_turns_an_uploaded_pptx_into_an_editable_project(tmp_path):
    """AC-15 / AC-16: convert -> check -> render round trip on a python-pptx deck."""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(10), Inches(1.5))
    box.text_frame.text = "二零二六年度工作总结"
    box.text_frame.paragraphs[0].runs[0].font.size = Pt(36)
    buf = io.BytesIO()
    prs.save(buf)
    (tmp_path / "upload.pptx").write_bytes(buf.getvalue())

    out = run_pptd("convert", "upload.pptx", "scratch/deck", cwd=tmp_path)
    assert "已转换为 PPTD 工程" in out and "不带原母版" in out, out
    assert (tmp_path / "scratch" / "deck" / "deck.pptd").is_file()
    assert "二零二六年度工作总结" in "".join(
        p.read_text(encoding="utf-8") for p in (tmp_path / "scratch" / "deck").rglob("*.page")
    )


def test_gov_red_is_the_generator_output(tmp_path):
    """The committed gov-red project must be reproducible from its generator."""
    generator = Path(__file__).resolve().parents[2] / "scripts" / "pptd_templates" / "gen_gov_red.py"
    subprocess.run([sys.executable, str(generator), str(tmp_path / "out")], check=True, capture_output=True)
    committed = TEMPLATES / "gov-red" / "source-zh"
    produced = {
        p.relative_to(tmp_path / "out").as_posix(): p.read_bytes() for p in (tmp_path / "out").rglob("*") if p.is_file()
    }
    expected = {p.relative_to(committed).as_posix(): p.read_bytes() for p in committed.rglob("*") if p.is_file()}
    assert produced == expected, "regenerate with scripts/pptd_templates/gen_gov_red.py"
