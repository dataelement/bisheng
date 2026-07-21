"""按格式路由的统一 PDF 生成回退实现。"""

from __future__ import annotations

import html
import os
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import chardet
import markdown
from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright

from bisheng.common.utils.markdown_cmpnt.md_to_pdf import sanitize_html_for_pdf
from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import (
    get_libreoffice_path,
)

OFFICE_EXTENSIONS = frozenset({"doc", "docx", "ppt", "pptx", "xls", "xlsx", "csv"})
TEXT_WEB_EXTENSIONS = frozenset({"txt", "md", "html"})
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg"})
SUPPORTED_EXTENSIONS = frozenset({"pdf"}) | OFFICE_EXTENSIONS | TEXT_WEB_EXTENSIONS | IMAGE_EXTENSIONS


class PdfConversionError(RuntimeError):
    """源文件无法在受控边界内转换为 PDF。"""


@dataclass(frozen=True)
class ConversionContext:
    timeout_seconds: int = 300
    max_image_pixels: int = 100_000_000


@dataclass(frozen=True)
class ConversionResult:
    pdf_path: Path
    converter: str


def _minimal_subprocess_env(runtime_dir: Path) -> dict[str, str]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    environment = {
        "HOME": str(runtime_dir),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "TMPDIR": str(runtime_dir),
        "XDG_CACHE_HOME": str(runtime_dir / "cache"),
        "XDG_CONFIG_HOME": str(runtime_dir / "config"),
        "XDG_DATA_HOME": str(runtime_dir / "data"),
        "SAL_USE_VCLPLUGIN": "svp",
    }
    for key in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        Path(environment[key]).mkdir(parents=True, exist_ok=True)
    return environment


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    detected = chardet.detect(content).get("encoding") or "utf-8"
    try:
        return content.decode(detected, errors="strict")
    except (LookupError, UnicodeDecodeError):
        return content.decode("utf-8", errors="replace")


def _browser_request_is_allowed(url: str) -> bool:
    return urlsplit(url).scheme.lower() in {"about", "data"}


class OfficePdfConverter:
    def convert(
        self,
        source_path: Path,
        output_dir: Path,
        context: ConversionContext,
    ) -> ConversionResult:
        executable = get_libreoffice_path()
        if not executable:
            raise PdfConversionError("LibreOffice executable is unavailable")
        output_dir.mkdir(parents=True, exist_ok=True)
        runtime_dir = output_dir / ".office-runtime"
        profile_dir = runtime_dir / "profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        office_source = source_path.resolve()
        if source_path.suffix.lower() == ".csv":
            office_source = output_dir / "source_utf8.csv"
            office_source.write_text(
                _decode_text(source_path.read_bytes()),
                encoding="utf-8",
                newline="",
            )

        command = [
            executable,
            "--headless",
            "--safe-mode",
            "--norestore",
            "--nodefault",
            "--nolockcheck",
            "--nofirststartwizard",
            "-env:SingleAppInstance=false",
            f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir.resolve()),
            str(office_source),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=context.timeout_seconds,
                shell=False,
                cwd=str(output_dir),
                env=_minimal_subprocess_env(runtime_dir),
            )
        except subprocess.TimeoutExpired as exc:
            raise PdfConversionError("LibreOffice conversion timed out") from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            raise PdfConversionError("LibreOffice conversion failed") from exc

        output_path = output_dir / f"{office_source.stem}.pdf"
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise PdfConversionError("LibreOffice did not create a PDF")
        return ConversionResult(output_path, "libreoffice")


class TextWebPdfConverter:
    _STYLE = """
    @page { size: A4; margin: 16mm; }
    html, body { color: #111827; font-family: "Noto Sans CJK SC", "WenQuanYi Zen Hei", sans-serif; }
    body { font-size: 11pt; line-height: 1.55; overflow-wrap: anywhere; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; font-family: monospace; }
    code { white-space: pre-wrap; overflow-wrap: anywhere; }
    table { width: 100%; border-collapse: collapse; break-inside: auto; }
    th, td { border: 1px solid #d1d5db; padding: 5px; vertical-align: top; }
    img { max-width: 100%; height: auto; }
    h1, h2, h3, h4 { break-after: avoid; }
    """

    def build_html(self, source_path: Path, extension: str) -> str:
        normalized_extension = extension.lower().lstrip(".")
        text = _decode_text(source_path.read_bytes())
        if normalized_extension == "txt":
            body = f'<pre class="plain-text">{html.escape(text)}</pre>'
        elif normalized_extension == "md":
            body = markdown.markdown(
                text,
                extensions=["extra", "codehilite", "toc", "tables", "sane_lists", "fenced_code"],
            )
        elif normalized_extension == "html":
            body = text
        else:
            raise PdfConversionError("Unsupported text or web extension")
        sanitized_body = sanitize_html_for_pdf(body)
        return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'">
<style>{self._STYLE}</style></head><body>{sanitized_body}</body></html>"""

    def convert(
        self,
        source_path: Path,
        output_dir: Path,
        context: ConversionContext,
    ) -> ConversionResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        extension = source_path.suffix.lower().lstrip(".")
        html_document = self.build_html(source_path, extension)
        output_path = output_dir / "rendered.pdf"
        runtime_dir = output_dir / ".browser-runtime"
        timeout_ms = context.timeout_seconds * 1000
        blocked_request_count = 0

        def handle_route(route) -> None:
            nonlocal blocked_request_count
            if _browser_request_is_allowed(route.request.url):
                route.continue_()
            else:
                blocked_request_count += 1
                route.abort()

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    timeout=timeout_ms,
                    env=_minimal_subprocess_env(runtime_dir),
                )
                browser_context = None
                try:
                    browser_context = browser.new_context(
                        java_script_enabled=False,
                        service_workers="block",
                    )
                    page = browser_context.new_page()
                    page.set_default_timeout(timeout_ms)
                    page.route("**/*", handle_route)
                    page.set_content(
                        html_document,
                        wait_until="domcontentloaded",
                        timeout=timeout_ms,
                    )
                    page.pdf(
                        path=str(output_path),
                        format="A4",
                        print_background=True,
                        prefer_css_page_size=True,
                    )
                finally:
                    if browser_context is not None:
                        browser_context.close()
                    browser.close()
        except Exception as exc:
            raise PdfConversionError(f"Chromium rendering failed ({type(exc).__name__})") from exc

        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise PdfConversionError("Chromium did not create a PDF")
        _ = blocked_request_count
        return ConversionResult(output_path, "playwright")


class ImagePdfConverter:
    def convert(
        self,
        source_path: Path,
        output_dir: Path,
        context: ConversionContext,
    ) -> ConversionResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "image.pdf"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source_path) as image:
                    image.load()
                    if image.width * image.height > context.max_image_pixels:
                        raise PdfConversionError("Image pixel limit exceeded")
                    normalized = ImageOps.exif_transpose(image)
                    if normalized.mode not in {"RGB", "L"}:
                        normalized = normalized.convert("RGB")
                    normalized.save(output_path, "PDF", resolution=150.0)
        except PdfConversionError:
            raise
        except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise PdfConversionError("Image conversion failed") from exc
        return ConversionResult(output_path, "pillow")


class PdfConverterRegistry:
    def __init__(self) -> None:
        self.office = OfficePdfConverter()
        self.text_web = TextWebPdfConverter()
        self.image = ImagePdfConverter()

    @staticmethod
    def group_for_extension(extension: str) -> str:
        normalized = extension.lower().lstrip(".")
        if normalized == "pdf":
            return "pdf"
        if normalized in OFFICE_EXTENSIONS:
            return "office"
        if normalized in TEXT_WEB_EXTENSIONS:
            return "text_web"
        if normalized in IMAGE_EXTENSIONS:
            return "image"
        raise PdfConversionError("Unsupported source extension")

    def convert(
        self,
        source_path: Path,
        output_dir: Path,
        context: ConversionContext,
    ) -> ConversionResult:
        group = self.group_for_extension(source_path.suffix)
        if group == "pdf":
            return ConversionResult(source_path, "original-pdf")
        converter = {
            "office": self.office,
            "text_web": self.text_web,
            "image": self.image,
        }[group]
        return converter.convert(source_path, output_dir, context)
