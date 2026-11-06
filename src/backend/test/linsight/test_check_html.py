"""check_html: the HTML deliverable checker bound next to export_docx / export_pdf.

Self-tested in both directions (builtin_skills/AGENTS.md): every bad sample trips
its check, and a good sample actually reaches the pass verdict. The render layer
needs a Chromium binary; those tests skip where Playwright cannot launch one, and
the degraded path (no browser) is covered separately because stripped customer
images are exactly where it runs.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bisheng.tool.domain.langchain import linsight_html_check as hc

GOOD = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font:16px/1.7 system-ui;max-width:860px;margin:auto;padding:16px}</style></head>
<body><h1>交叉一致性审核报告</h1><p>两份报告在信托名称、规模、期限等 25 项要素上一致，发现 3 处需要关注的差异。</p>
<img alt="" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==">
<a href="https://example.com/source">来源链接不算资源</a><a href="#s1">目录</a></body></html>"""


def _errors(findings):
    return [f for f in findings if f.level == hc.ERROR]


def _topics(findings, level=None):
    return {f.topic for f in findings if level is None or f.level == level}


# ---------------------------------------------------------------------------
# static layer
# ---------------------------------------------------------------------------


def test_good_page_has_no_static_findings():
    assert hc.static_findings(GOOD) == []


@pytest.mark.parametrize(
    "snippet",
    [
        '<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>',
        '<link rel="stylesheet" href="//fonts.googleapis.com/css2?family=Inter">',
        '<img src="output/charts/a.png">',  # relative: the srcDoc preview has no base URL
        '<img srcset="data:image/png;base64,AA 1x, output/b@2x.png 2x">',
        "<style>@import url('https://x.example/a.css');</style>",
        "<style>body{background:url(output/bg.png)}</style>",
        '<div style="background-image:url(&quot;scratch/x.png&quot;)">x</div>',
        '<iframe src="https://example.com"></iframe>',
    ],
)
def test_every_non_inline_resource_is_an_error(snippet):
    html = GOOD.replace("</body>", snippet + "</body>")
    findings = hc.static_findings(html)
    assert _topics(findings, hc.ERROR) == {"非内联资源"}


def test_inert_links_are_not_resources():
    html = GOOD.replace("</head>", '<link rel="canonical" href="https://example.com/x"></head>')
    assert hc.static_findings(html) == []


def test_empty_body_is_an_error():
    html = "<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
    html += "<style>h1{}</style><script>var a='很多很多很多很多很多很多很多很多很多很多字';</script></head><body><h1>标题</h1></body></html>"
    assert "内容为空" in _topics(hc.static_findings(html), hc.ERROR)


def test_missing_head_metadata_is_only_a_warning():
    html = "<html><body><p>" + "正文内容" * 10 + "</p></body></html>"
    findings = hc.static_findings(html)
    assert _errors(findings) == []
    assert {"缺少 doctype", "缺少 viewport", "缺少字符集"} <= _topics(findings, hc.WARN)


def test_fetching_refs_feeds_render_dedup():
    html = GOOD.replace("</body>", '<script src="https://cdn.x/a.js"></script><img src="output/a.png"></body>')
    assert hc.fetching_refs(html) == {"https://cdn.x/a.js", "output/a.png"}


# ---------------------------------------------------------------------------
# report format / verdict ownership
# ---------------------------------------------------------------------------


def test_pass_verdict_only_without_errors():
    ok = hc.format_report("output/a.html", 100, [hc.Finding(hc.WARN, "t", "d")], None, None)
    assert hc.PASS_VERDICT in ok and "ERROR" not in ok
    bad = hc.format_report("output/a.html", 100, [hc.Finding(hc.ERROR, "t", "d")], None, None)
    assert hc.PASS_VERDICT not in bad
    assert "有 1 个 ERROR" in bad


def test_unavailable_renderer_is_stated_not_hidden():
    report = hc.format_report("output/a.html", 100, [], None, "本环境无法启动浏览器")
    assert "渲染检查未执行" in report
    assert "（仅静态检查）" in report


def test_pass_verdict_is_printed_by_this_module_alone():
    """The model stops when it sees the verdict; nothing else may print it."""
    backend_root = Path(hc.__file__).resolve().parents[3]
    offenders = [
        p
        for p in backend_root.rglob("*.py")
        if hc.PASS_VERDICT in p.read_text(encoding="utf-8", errors="ignore") and p.name != "linsight_html_check.py"
    ]
    skills_root = backend_root / "linsight" / "builtin_skills"
    offenders += [
        p for p in skills_root.rglob("*") if p.is_file() and hc.PASS_VERDICT in p.read_text("utf-8", errors="ignore")
    ]
    assert offenders == []


# ---------------------------------------------------------------------------
# tool shell (fake backend)
# ---------------------------------------------------------------------------


class _Backend:
    def __init__(self, files: dict[str, str]):
        self.files = files
        self.written: dict[str, bytes] = {}

    async def aread(self, path, offset=0, limit=2000):
        content = self.files.get(path.lstrip("/"))
        if content is None:
            return SimpleNamespace(error="not found", file_data=None)
        return SimpleNamespace(error=None, file_data={"content": content})

    async def awrite(self, path, content):
        self.written[path] = content
        return SimpleNamespace(error=None, path="/" + path)


async def test_tool_rejects_non_html():
    tool = hc.CheckHtmlTool(backend=_Backend({}))
    assert "只检查 .html" in await tool._arun("output/a.md")


async def test_tool_reports_missing_file_softly():
    tool = hc.CheckHtmlTool(backend=_Backend({}))
    assert "不存在或为空" in await tool._arun("output/a.html")


async def test_tool_degrades_when_no_browser(monkeypatch):
    monkeypatch.setattr(hc, "_render_findings", lambda html, known=frozenset(): ([], None, "本环境无法启动浏览器"))
    backend = _Backend({"output/a.html": GOOD})
    report = await hc.CheckHtmlTool(backend=backend)._arun("/output/a.html")
    assert "渲染检查未执行" in report
    assert hc.PASS_VERDICT in report
    assert backend.written == {}


# ---------------------------------------------------------------------------
# render layer (real Chromium; skipped where it cannot launch)
# ---------------------------------------------------------------------------


def _chromium_available() -> bool:
    _, _, unavailable = hc._render_findings(GOOD)
    return unavailable is None


chromium = pytest.mark.skipif(not _chromium_available(), reason="Playwright Chromium not launchable here")


@chromium
async def test_render_good_page_passes_and_stores_a_screenshot():
    backend = _Backend({"output/report.html": GOOD})
    report = await hc.CheckHtmlTool(backend=backend)._arun("output/report.html")
    assert hc.PASS_VERDICT in report
    assert "ERROR" not in report
    shot = backend.written["scratch/report.check.png"]
    assert shot[:8] == b"\x89PNG\r\n\x1a\n"


@chromium
def test_render_catches_script_errors_and_js_fetches():
    html = GOOD.replace("</body>", "<script>fetch('https://api.example.com/x'); notDefined();</script></body>")
    findings, _, unavailable = hc._render_findings(html, frozenset(hc.fetching_refs(html)))
    assert unavailable is None
    details = " ".join(f.detail for f in _errors(findings))
    assert "notDefined" in details
    assert "api.example.com" in details


@chromium
def test_render_does_not_repeat_what_the_static_pass_reported():
    html = GOOD.replace("</body>", '<script src="https://cdn.x/a.js"></script><img src="output/a.png"></body>')
    findings, _, _ = hc._render_findings(html, frozenset(hc.fetching_refs(html)))
    assert _errors(findings) == []


@chromium
def test_render_flags_horizontal_overflow_as_warning_only():
    html = GOOD.replace("</body>", '<div style="width:2000px">宽</div></body>')
    findings, _, _ = hc._render_findings(html)
    assert "横向溢出" in _topics(findings, hc.WARN)
    assert _errors(findings) == []


@chromium
def test_render_hang_is_an_error_not_a_crash(monkeypatch):
    monkeypatch.setattr(hc, "_RENDER_TIMEOUT_MS", 1500)
    html = GOOD.replace("</body>", "<script>while(true){}</script></body>")
    findings, _, unavailable = hc._render_findings(html)
    assert unavailable is None
    assert [f.topic for f in _errors(findings)] == ["渲染超时"]


@chromium
def test_small_text_check_ignores_scaled_svg_labels():
    """A matplotlib SVG labels its ticks at 10 user units; width:100% scales them up."""
    svg = (
        '<svg viewBox="0 0 200 100" width="100%" xmlns="http://www.w3.org/2000/svg">'
        '<text x="10" y="50" style="font-size:10px">1月</text></svg>'
    )
    html = GOOD.replace("</body>", svg + "</body>")
    findings, _, _ = hc._render_findings(html)
    assert "字号过小" not in _topics(findings)
    # The xmlns URL is a namespace, not a fetch.
    assert hc.static_findings(html) == []
