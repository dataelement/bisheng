"""Task-mode ``check_html`` tool: inspect an HTML deliverable before it ships.

``write_file`` stores whatever string the model hands it and answers "Updated
file …" — the model never learns that its page pulls a CDN script an offline
customer cannot reach, throws on load, or overflows a phone screen. This tool
closes that loop with two layers:

- **Static checks** (pure Python, always run): resources that will not load in
  the places the file is actually opened. The client previews HTML through a
  sandboxed ``srcDoc`` iframe (no base URL, opaque origin) and users download the
  file on its own, so *any* non-inline resource — a CDN URL or a relative
  ``output/x.png`` alike — renders as a hole.
- **Render checks** (headless Chromium via Playwright, best effort): script
  errors, network attempts made from JS, broken images, horizontal overflow at a
  desktop and a phone width, and a desktop screenshot written to ``scratch/``.
  Chromium ships in the standard backend image (``base.Dockerfile``) but not in
  stripped customer images, so a missing browser is reported honestly and never
  fails the task.

Severity follows ``builtin_skills/AGENTS.md``: only ERROR blocks delivery, WARN
never does, and there is no "conditional pass". The pass verdict line is printed
by this tool alone, so the model cannot mistake another message for it.

Same contracts as ``linsight_export``: the WorkspaceBackend is closure-injected,
and every failure is a soft string return (a raise would kill the task).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field

from bisheng.utils import util

CHECK_HTML_TOOL_NAME = "check_html"

# The verdict strings the model watches for. Only this module prints them.
PASS_VERDICT = "检查结论：通过"
FAIL_VERDICT_TEMPLATE = "检查结论：有 {n} 个 ERROR，修复后重新调用 check_html。"

_DESKTOP = (1280, 800)
_PHONE = (390, 844)
_RENDER_TIMEOUT_MS = 15_000
_MAX_SCREENSHOT_HEIGHT = 6000
_SIZE_WARN_BYTES = 3 * 1024 * 1024
_MIN_BODY_TEXT = 20
_MAX_LISTED = 5

ERROR = "ERROR"
WARN = "WARN"


@dataclass(frozen=True)
class Finding:
    level: str
    topic: str
    detail: str


# Tag -> attributes that make the browser fetch something on load. Anchors are
# deliberately absent: a link is navigation, it does not break the page.
_FETCHING_ATTRS = {
    "script": ("src",),
    "img": ("src", "srcset"),
    "iframe": ("src",),
    "frame": ("src",),
    "video": ("src", "poster"),
    "audio": ("src",),
    "source": ("src", "srcset"),
    "track": ("src",),
    "embed": ("src",),
    "object": ("data",),
    "input": ("src",),
}
# <link> fetches only for these rel values; rel="canonical" etc. are inert.
_FETCHING_LINK_RELS = {
    "stylesheet",
    "icon",
    "shortcut",
    "preload",
    "prefetch",
    "modulepreload",
    "manifest",
    "apple-touch-icon",
}
_CSS_URL_RE = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.IGNORECASE)
_CSS_IMPORT_RE = re.compile(r"""@import\s+(?:url\(\s*)?(['"])(.*?)\1""", re.IGNORECASE)


def _is_inline(ref: str) -> bool:
    """True for references that need no fetch: data URIs, fragments, empty values."""
    ref = (ref or "").strip()
    return not ref or ref.startswith("#") or ref.lower().startswith(("data:", "about:", "javascript:"))


class _ResourceScanner(HTMLParser):
    """Collect fetching references and the visible text of an HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str]] = []  # (where, url)
        self.text_parts: list[str] = []
        self.has_doctype = False
        self.has_viewport = False
        self.has_charset = False
        self._skip_depth = 0
        self._in_style = False

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.has_doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            if a.get("name", "").lower() == "viewport":
                self.has_viewport = True
            if "charset" in a or "charset" in a.get("content", "").lower():
                self.has_charset = True
        if tag == "link":
            rels = set(a.get("rel", "").lower().split())
            if rels & _FETCHING_LINK_RELS and not _is_inline(a.get("href", "")):
                self.refs.append((f"<link rel={a.get('rel')}>", a["href"]))
        for attr in _FETCHING_ATTRS.get(tag, ()):
            value = a.get(attr, "")
            if attr == "srcset":
                candidates = [part.strip().split(" ")[0] for part in value.split(",") if part.strip()]
            else:
                candidates = [value]
            for ref in candidates:
                if not _is_inline(ref):
                    self.refs.append((f"<{tag} {attr}>", ref))
        style = a.get("style", "")
        if style:
            self._scan_css(style, f"<{tag} style>")
        if tag in ("script", "style", "template", "noscript"):
            self._skip_depth += 1
            self._in_style = tag == "style"

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "template", "noscript") and self._skip_depth:
            self._skip_depth -= 1
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self._scan_css(data, "<style>")
        elif not self._skip_depth:
            self.text_parts.append(data)

    def _scan_css(self, css: str, where: str) -> None:
        for match in _CSS_IMPORT_RE.finditer(css):
            if not _is_inline(match.group(2)):
                self.refs.append((f"{where} @import", match.group(2)))
        for match in _CSS_URL_RE.finditer(css):
            if not _is_inline(match.group(2)):
                self.refs.append((f"{where} url()", match.group(2)))


def _scan(html: str) -> tuple[_ResourceScanner, str | None]:
    scanner = _ResourceScanner()
    try:
        scanner.feed(html)
        scanner.close()
    except Exception as e:  # html.parser is lenient; this is defence in depth
        return scanner, str(e)
    return scanner, None


def fetching_refs(html: str) -> set[str]:
    """Every non-inline reference the static pass reports, so rendering can skip them."""
    return {ref for _, ref in _scan(html)[0].refs}


def static_findings(html: str) -> list[Finding]:
    """Checks that need no browser. Pure function, safe to unit-test directly."""
    findings: list[Finding] = []
    scanner, parse_error = _scan(html)
    if parse_error:
        findings.append(Finding(WARN, "解析", f"HTML 解析不完整：{parse_error}"))

    seen: set[str] = set()
    for where, ref in scanner.refs:
        if ref in seen:
            continue
        seen.add(ref)
        kind = "外部地址" if re.match(r"^(https?:)?//", ref, re.IGNORECASE) else "相对路径"
        findings.append(
            Finding(
                ERROR,
                "非内联资源",
                f"{where} 引用了{kind} {ref[:120]}：离线环境、预览框和下载后的单个文件都加载不到。"
                "样式和脚本写进 <style>/<script> 标签；图片改成 data: URI 或内联 <svg>；用不上就删掉。",
            )
        )

    body_text = re.sub(r"\s+", "", "".join(scanner.text_parts))
    if len(body_text) < _MIN_BODY_TEXT:
        findings.append(Finding(ERROR, "内容为空", f"页面可见文字只有 {len(body_text)} 个字符，正文没有写进去。"))
    if not scanner.has_doctype:
        findings.append(
            Finding(WARN, "缺少 doctype", "文件开头没有 <!DOCTYPE html>，浏览器会进入怪异模式，排版可能错乱。")
        )
    if not scanner.has_viewport:
        findings.append(
            Finding(
                WARN,
                "缺少 viewport",
                '没有 <meta name="viewport" content="width=device-width, initial-scale=1">，手机上会按桌面宽度缩小显示。',
            )
        )
    if not scanner.has_charset:
        findings.append(Finding(WARN, "缺少字符集", '没有 <meta charset="utf-8">，下载后本地打开中文可能乱码。'))
    size = len(html.encode("utf-8"))
    if size > _SIZE_WARN_BYTES:
        findings.append(
            Finding(WARN, "文件过大", f"文件 {size / 1024 / 1024:.1f} MB，预览加载会很慢；压缩内嵌图片或减少重复样式。")
        )
    return findings


# Runs inside the page. Returns plain JSON so the Python side stays trivial.
_PROBE_JS = """
() => {
  const doc = document.documentElement;
  const broken = [...document.images].filter(i => i.complete && i.naturalWidth === 0)
    .map(i => (i.getAttribute('src') || '').slice(0, 80));
  let small = 0;
  const walker = document.createTreeWalker(document.body || doc, NodeFilter.SHOW_TEXT);
  const counted = new Set();
  while (walker.nextNode()) {
    const el = walker.currentNode.parentElement;
    if (!el || counted.has(el) || !walker.currentNode.textContent.trim()) continue;
    // SVG text reports its size in user units, before the viewBox scales it up.
    if (el.closest('svg')) continue;
    counted.add(el);
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (parseFloat(cs.fontSize) < 12) small++;
  }
  const wide = [...document.querySelectorAll('table')].filter(t => {
    const parent = t.parentElement;
    return parent && t.scrollWidth > parent.clientWidth + 2 && getComputedStyle(parent).overflowX === 'visible';
  }).length;
  return {scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth, broken, small, wide,
          height: doc.scrollHeight};
}
"""


def _render_findings(
    html: str, known_refs: frozenset[str] = frozenset()
) -> tuple[list[Finding], bytes | None, str | None]:
    """Render in headless Chromium. Returns (findings, desktop screenshot, unavailable reason).

    ``known_refs`` are references the static pass already reported. A blocked CDN
    script also surfaces here as a network attempt, a console "Failed to load
    resource" and possibly a broken image; reporting it three more times would
    inflate the ERROR count the model is told to drive to zero.

    Synchronous on purpose: the caller runs it in a worker thread, where the sync
    Playwright API is legal (it is not inside the asyncio loop thread).
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # stripped image without the package
        return [], None, f"本环境没有安装浏览器渲染组件（{type(e).__name__}）"

    findings: list[Finding] = []
    screenshot: bytes | None = None
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as e:  # package present, browser binary missing
                return [], None, f"本环境无法启动浏览器（{str(e).splitlines()[0][:120]}）"
            try:
                for label, (width, height) in (("桌面", _DESKTOP), ("手机", _PHONE)):
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.set_default_timeout(_RENDER_TIMEOUT_MS)
                    errors: list[str] = []
                    requests: list[str] = []
                    page.on("pageerror", lambda exc, errors=errors: errors.append(str(exc)))
                    page.on(
                        "console",
                        lambda msg, errors=errors: errors.append(msg.text) if msg.type == "error" else None,
                    )

                    def _block(route, request, requests=requests):
                        # Offline by construction: nothing leaves the worker, and
                        # every attempt is a finding (JS can fetch what no tag names).
                        # Playwright passes (route, request) positionally, so the
                        # bound list must come after both.
                        requests.append(request.url)
                        route.abort()

                    page.route("**/*", _block)
                    try:
                        page.set_content(html, wait_until="load")
                        page.wait_for_timeout(300)
                        probe = page.evaluate(_PROBE_JS)
                    except Exception as e:
                        findings.append(
                            Finding(
                                ERROR,
                                "渲染超时",
                                f"{label}宽度下页面在 {_RENDER_TIMEOUT_MS // 1000} 秒内没有加载完"
                                f"（可能有死循环或卡住的脚本）：{str(e).splitlines()[0][:120]}",
                            )
                        )
                        page.close()
                        # A page that hangs at one width hangs at the other too;
                        # one finding is the truth, two would double the count.
                        break

                    if label == "桌面":
                        for msg in dict.fromkeys(errors).keys():
                            # The blocked fetch behind this message is reported
                            # as a network attempt (or statically) already.
                            if msg.startswith("Failed to load resource"):
                                continue
                            findings.append(Finding(ERROR, "脚本报错", msg[:200]))
                        new_requests = [
                            u for u in dict.fromkeys(requests) if not any(ref in u for ref in known_refs if ref)
                        ]
                        for url in new_requests[:_MAX_LISTED]:
                            findings.append(
                                Finding(ERROR, "网络请求", f"页面脚本尝试加载 {url[:120]}，离线环境会失败。")
                            )
                        broken = [s for s in probe["broken"] if s not in known_refs]
                        for src in broken[:_MAX_LISTED]:
                            findings.append(Finding(ERROR, "图片裂开", f"图片 {src or '(无 src)'} 没有显示出来。"))
                        if probe["small"]:
                            findings.append(
                                Finding(WARN, "字号过小", f"有 {probe['small']} 处文字小于 12px，阅读吃力。")
                            )
                        try:
                            clip_h = min(int(probe["height"]), _MAX_SCREENSHOT_HEIGHT)
                            screenshot = page.screenshot(
                                full_page=True, clip={"x": 0, "y": 0, "width": width, "height": max(clip_h, 1)}
                            )
                        except Exception:
                            logger.debug("check_html screenshot failed", exc_info=True)
                    overflow = int(probe["scrollWidth"]) - int(probe["clientWidth"])
                    if overflow > 2:
                        findings.append(
                            Finding(
                                WARN,
                                "横向溢出",
                                f"{label}宽度（{width}px）下页面比屏幕宽 {overflow}px，会出现横向滚动条。",
                            )
                        )
                    if probe["wide"]:
                        findings.append(
                            Finding(
                                WARN,
                                "表格超宽",
                                f"{label}宽度下有 {probe['wide']} 张表格超出容器；给外层加 overflow-x:auto。",
                            )
                        )
                    page.close()
            finally:
                browser.close()
    except Exception as e:
        logger.exception("check_html render failed")
        return findings, screenshot, f"渲染检查中途出错（{str(e).splitlines()[0][:120]}）"
    return findings, screenshot, None


def format_report(path: str, size: int, findings: list[Finding], shot_path: str | None, unavailable: str | None) -> str:
    errors = [f for f in findings if f.level == ERROR]
    warns = [f for f in findings if f.level == WARN]
    lines = [f"check_html 报告：{path}（{size / 1024:.1f} KB）"]
    if errors:
        lines.append("ERROR（必须修复）：")
        lines += [f"- [{f.topic}] {f.detail}" for f in errors]
    if warns:
        lines.append("WARN（建议修复，不影响交付）：")
        lines += [f"- [{f.topic}] {f.detail}" for f in warns]
    if unavailable:
        lines.append(f"渲染检查未执行：{unavailable}。以上只是静态检查结果。")
    if shot_path:
        lines.append(f"截图：{shot_path}（桌面宽度 {_DESKTOP[0]}px）。模型支持读图时可以 read_file 查看版式。")
    if errors:
        lines.append(FAIL_VERDICT_TEMPLATE.format(n=len(errors)))
    else:
        lines.append(PASS_VERDICT + ("（仅静态检查）" if unavailable else "") + "。")
    return "\n".join(lines)


class _CheckHtmlInput(BaseModel):
    path: str = Field(..., description="要检查的 HTML 文件路径，例如 output/report.html")


class CheckHtmlTool(BaseTool):
    name: str = CHECK_HTML_TOOL_NAME
    description: str = (
        "检查 output/ 下的 HTML 交付物能否在离线环境、预览框和下载后正常显示。\n"
        "写完 html 后调用一次；报告里有 ERROR 就用 edit_file 修复后再调用，WARN 可酌情修复。\n"
        "返回静态检查和浏览器渲染检查的结果，渲染成功时还会把桌面截图存到 scratch/。"
    )
    args_schema: type[BaseModel] = _CheckHtmlInput
    # Closure-injected WorkspaceBackend (see linsight_export); never shown to the LLM.
    backend: Any = None

    def _run(self, *args, **kwargs) -> str:
        return "not supported in sync mode, please use async version"

    async def _arun(self, path: str, **kwargs) -> str:
        if not path.lower().endswith((".html", ".htm")):
            return f"check_html 只检查 .html 文件，{path} 不是。"
        res = await self.backend.aread(path, limit=None)
        fd = None if getattr(res, "error", None) else getattr(res, "file_data", None)
        html = (fd.get("content") if isinstance(fd, dict) else getattr(fd, "content", None)) if fd else None
        if not html:
            return f"check_html 失败：{path} 不存在或为空，请先用 write_file 写好。"

        findings = static_findings(html)
        try:
            render, shot, unavailable = await util.sync_func_to_async(_render_findings)(
                html, frozenset(fetching_refs(html))
            )
        except Exception as e:
            logger.exception("check_html render dispatch failed")
            render, shot, unavailable = [], None, f"渲染检查无法启动（{type(e).__name__}）"
        findings += render

        shot_path = None
        if shot and hasattr(self.backend, "awrite"):
            stem = os.path.splitext(os.path.basename(path))[0] or "page"
            try:
                written = await self.backend.awrite(f"scratch/{stem}.check.png", shot)
                shot_path = getattr(written, "path", None) or f"scratch/{stem}.check.png"
            except Exception:
                logger.debug("check_html could not store the screenshot", exc_info=True)
        return format_report(path, len(html.encode("utf-8")), findings, shot_path, unavailable)
