"""Extract document titles from various file formats without using LLMs."""

import base64
import os
import re
from io import BytesIO

from loguru import logger


class FileTitleExtractError(Exception):
    """Raised when title extraction fails for a specific file."""

    pass


def sanitize_file_name(name: str, max_length: int = 200) -> str | None:
    """Clean a candidate file name so it is safe for storage and display.

    Removes leading/trailing whitespace, replaces path separators and other
    illegal characters, collapses multiple spaces, and truncates to the
    configured max length. Returns ``None`` if the sanitized name is empty.
    """
    if not name:
        return None
    # Strip extension-agnostic surrounding whitespace first
    name = name.strip()
    # Replace common path/illegal characters with a safe delimiter
    name = re.sub(r'[\\/:*?"<>|]', " ", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return None
    # Account for a potential suffix like ``(1).pdf`` by keeping a margin
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    return name if name else None


def _read_first_text_block(file_path: str, max_bytes: int = 4096) -> str | None:
    """Read the first non-empty line/paragraph from a plain text file."""
    try:
        with open(file_path, "rb") as f:
            raw = f.read(max_bytes)
        if not raw:
            return None
        # Try common encodings
        for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="ignore")
        for line in text.splitlines():
            line = line.strip()
            if line:
                return line
    except Exception as e:
        # Title extraction is best-effort; a read failure should not block parsing.
        logger.warning("read_first_text_block failed: {}", e)
    return None


class BaseTitleExtractor:
    """Base class for format-specific title extractors."""

    def extract(self, file_path: str) -> str | None:
        raise NotImplementedError


class TxtTitleExtractor(BaseTitleExtractor):
    """Extract title from plain text files.

    Strategy:
        1. Read the first non-empty line.
        2. Treat it as the title only if it is a reasonably short text block.
    """

    def extract(self, file_path: str) -> str | None:
        first = _read_first_text_block(file_path)
        if not first:
            return None
        # A title is usually a single short line or paragraph. Reject very long
        # blocks that are more likely body text.
        if len(first) > 200:
            return None
        return first.strip()


class MarkdownTitleExtractor(BaseTitleExtractor):
    """Extract title from Markdown files.

    Strategy:
        1. YAML front matter ``title`` field.
        2. First level-1 heading.
        3. First short text block as fallback.
    """

    _YAML_TITLE_RE = re.compile(r"^---\s*\n.*?^title:\s*(.+?)\n.*?^---\s*\n", re.M | re.S)
    _H1_RE = re.compile(r"^#\s+(.+)$", re.M)

    def extract(self, file_path: str) -> str | None:
        try:
            with open(file_path, "rb") as f:
                raw = f.read(8192)
            text = raw.decode("utf-8", errors="ignore")
            # YAML front matter
            m = self._YAML_TITLE_RE.search(text)
            if m:
                title = m.group(1).strip().strip('"').strip("'")
                if title:
                    return title
            # First H1
            m = self._H1_RE.search(text)
            if m:
                title = m.group(1).strip()
                if title:
                    return title
            # Fallback to first short block
            return TxtTitleExtractor().extract(file_path)
        except Exception as e:
            # Title extraction is best-effort; a parse failure should not block parsing.
            logger.warning("markdown title extract failed: {}", e)
        return None


class HtmlTitleExtractor(BaseTitleExtractor):
    """Extract title from HTML files.

    Strategy:
        1. ``<title>`` tag content.
        2. First ``<h1>`` tag content.
        3. Combine both when one is clearly a subset of the other.
    """

    def extract(self, file_path: str) -> str | None:
        try:
            from bs4 import BeautifulSoup

            with open(file_path, "rb") as f:
                raw = f.read(8192)
            text = raw.decode("utf-8", errors="ignore")
            soup = BeautifulSoup(text, "html.parser")

            title_tag = soup.find("title")
            h1_tag = soup.find("h1")

            title_text = title_tag.get_text(strip=True) if title_tag else None
            h1_text = h1_tag.get_text(strip=True) if h1_tag else None

            if title_text and h1_text:
                # Prefer the shorter one if one contains the other; otherwise prefer h1
                if title_text in h1_text:
                    return h1_text
                if h1_text in title_text:
                    return title_text
                return h1_text
            return title_text or h1_text
        except Exception as e:
            # Title extraction is best-effort; a parse failure should not block parsing.
            logger.warning("html title extract failed: {}", e)
        return None


class DocxTitleExtractor(BaseTitleExtractor):
    """Extract title from DOCX files.

    Strategy:
        1. Document core properties ``title``.
        2. Paragraph with style name ``Title``.
        3. Largest, centered paragraph on the first page.
    """

    def extract(self, file_path: str) -> str | None:
        try:
            from docx import Document
            from docx.enum.text import WD_ALIGN_PARAGRAPH

            doc = Document(file_path)

            # 1. Core properties
            title = doc.core_properties.title
            if title and title.strip():
                return title.strip()

            # 2. Style named Title
            for para in doc.paragraphs:
                if para.style and para.style.name and "Title" in para.style.name:
                    text = para.text.strip()
                    if text:
                        return text

            # 3. First page largest centered paragraph
            first_page_candidates = []
            for para in doc.paragraphs:
                text = para.text.strip()
                if not text:
                    continue
                # Approximate font size from runs
                sizes = [run.font.size.pt for run in para.runs if run.font.size and run.font.size.pt]
                max_size = max(sizes) if sizes else 0
                is_centered = para.alignment == WD_ALIGN_PARAGRAPH.CENTER
                # Stop scanning once we are well past the first page (heuristic)
                if len(first_page_candidates) > 20:
                    break
                first_page_candidates.append((max_size, is_centered, text))

            if not first_page_candidates:
                return None

            # Prefer centered paragraphs; among them pick the largest font
            centered = [c for c in first_page_candidates if c[1]]
            pool = centered if centered else first_page_candidates
            pool.sort(key=lambda x: x[0], reverse=True)
            return pool[0][2]
        except Exception as e:
            # Title extraction is best-effort; a parse failure should not block parsing.
            logger.warning("docx title extract failed: {}", e)
        return None


class DocTitleExtractor(BaseTitleExtractor):
    """Extract title from legacy DOC files.

    Strategy:
        1. Try python-docx directly (some .doc files are readable).
        2. Convert to DOCX via LibreOffice and reuse DocxTitleExtractor.
    """

    def extract(self, file_path: str) -> str | None:
        try:
            return DocxTitleExtractor().extract(file_path)
        except Exception:
            pass
        try:
            from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import (
                convert_doc_to_docx,
            )

            docx_path = convert_doc_to_docx(file_path)
            if docx_path and os.path.exists(docx_path):
                return DocxTitleExtractor().extract(docx_path)
        except Exception as e:
            # Title extraction is best-effort; a parse failure should not block parsing.
            logger.warning("doc title extract failed: {}", e)
        return None


class PptxTitleExtractor(BaseTitleExtractor):
    """Extract title from PPTX files.

    Strategy:
        1. Title placeholder on the first slide.
        2. Largest font text on the first slide.
    """

    def extract(self, file_path: str) -> str | None:
        try:
            from pptx import Presentation
            from pptx.enum.shapes import PP_PLACEHOLDER

            prs = Presentation(file_path)
            if not prs.slides:
                return None
            first_slide = prs.slides[0]

            # 1. Title placeholder
            for shape in first_slide.shapes:
                if not shape.has_text_frame:
                    continue
                if shape.placeholder_format is not None and shape.placeholder_format.type in (
                    PP_PLACEHOLDER.TITLE,
                    PP_PLACEHOLDER.CENTER_TITLE,
                ):
                    text = shape.text_frame.text.strip()
                    if text:
                        return text

            # 2. Largest font text on first slide
            candidates = []
            for shape in first_slide.shapes:
                if not shape.has_text_frame:
                    continue
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if not text:
                        continue
                    sizes = [run.font.size.pt for run in para.runs if run.font.size and run.font.size.pt]
                    max_size = max(sizes) if sizes else 0
                    candidates.append((max_size, text))

            if not candidates:
                return None
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]
        except Exception as e:
            # Title extraction is best-effort; a parse failure should not block parsing.
            logger.warning("pptx title extract failed: {}", e)
        return None


class PptTitleExtractor(BaseTitleExtractor):
    """Extract title from legacy PPT files.

    Strategy:
        1. Try python-pptx directly.
        2. Convert to PPTX via LibreOffice and reuse PptxTitleExtractor.
    """

    def extract(self, file_path: str) -> str | None:
        try:
            return PptxTitleExtractor().extract(file_path)
        except Exception:
            pass
        try:
            from bisheng.knowledge.rag.pipeline.loader.utils.libreoffice_converter import (
                convert_ppt_to_pptx,
            )

            pptx_path = convert_ppt_to_pptx(file_path)
            if pptx_path and os.path.exists(pptx_path):
                return PptxTitleExtractor().extract(pptx_path)
        except Exception as e:
            # Title extraction is best-effort; a parse failure should not block parsing.
            logger.warning("ppt title extract failed: {}", e)
        return None


class ExcelTitleExtractor(BaseTitleExtractor):
    """Extract title from XLS/XLSX files.

    Strategy:
        1. Workbook properties title.
        2. Top merged cell value on the first worksheet.
        3. Cell A1 on the first worksheet.
    """

    def extract(self, file_path: str) -> str | None:
        try:
            from openpyxl import load_workbook

            path = file_path
            if file_path.lower().endswith(".xls"):
                from bisheng.knowledge.rag.pipeline.loader.utils.md_from_excel import (
                    xls_to_xlsx,
                )

                converted = xls_to_xlsx(file_path)
                if converted and os.path.exists(converted):
                    path = converted
                else:
                    return None

            wb = load_workbook(path, read_only=True, data_only=True)

            # 1. Workbook properties
            if wb.properties and wb.properties.title:
                title = wb.properties.title.strip()
                if title:
                    return title

            if not wb.sheetnames:
                return None
            ws = wb[wb.sheetnames[0]]

            # 2. Top merged cell
            if ws.merged_cells.ranges:
                for merged_range in ws.merged_cells.ranges:
                    min_col, min_row, _, _ = merged_range.bounds
                    if min_row <= 3:  # Near the top of the sheet
                        value = ws.cell(row=min_row, column=min_col).value
                        if value and str(value).strip():
                            return str(value).strip()

            # 3. Cell A1
            value = ws.cell(row=1, column=1).value
            if value and str(value).strip():
                return str(value).strip()
        except Exception as e:
            # Title extraction is best-effort; a parse failure should not block parsing.
            logger.warning("excel title extract failed: {}", e)
        return None


class CsvTitleExtractor(BaseTitleExtractor):
    """CSV files usually only contain field names, no document title."""

    def extract(self, _file_path: str) -> str | None:
        return None


class PdfTitleExtractor(BaseTitleExtractor):
    """Extract title from PDF files.

    Strategy:
        1. Metadata title.
        2. Largest text block near the top of the first page.
        3. OCR the top region of the first page (if PaddleOCR is configured).
    """

    def __init__(self, ocr_top_ratio: float = 0.25) -> None:
        self.ocr_top_ratio = ocr_top_ratio

    def extract(self, file_path: str) -> str | None:
        try:
            import fitz  # pymupdf

            doc = fitz.open(file_path)
            # 1. Metadata
            metadata = doc.metadata or {}
            title = metadata.get("title")
            if title and title.strip():
                return title.strip()

            if not doc:
                return None
            page = doc[0]

            # 2. First page top/largest text block
            blocks = page.get_text("dict").get("blocks", [])
            text_blocks = []
            for b in blocks:
                if "lines" not in b:
                    continue
                for line in b["lines"]:
                    for span in line["spans"]:
                        text = span.get("text", "").strip()
                        if not text:
                            continue
                        size = span.get("size", 0)
                        bbox = span.get("bbox")
                        y0 = bbox[1] if bbox else 0
                        text_blocks.append((y0, size, text))

            if text_blocks:
                # Prefer blocks in the top 30% of the page
                page_height = page.rect.height
                top_blocks = [b for b in text_blocks if b[0] < page_height * 0.3]
                pool = top_blocks if top_blocks else text_blocks
                # Largest font, then topmost
                pool.sort(key=lambda x: (x[1], -x[0]), reverse=True)
                best = pool[0][2]
                if best:
                    return best

            # 3. OCR top region
            ocr_title = self._ocr_top_region(page)
            if ocr_title:
                return ocr_title
        except Exception as e:
            # Title extraction is best-effort; a parse failure should not block parsing.
            logger.warning("pdf title extract failed: {}", e)
        return None

    def _ocr_top_region(self, page) -> str | None:
        try:
            import fitz  # pymupdf

            from bisheng.core.config.settings import settings

            ocr_conf = settings.knowledge.paddle_ocr
            url = ocr_conf.url.strip() if ocr_conf.url else ""
            if not url:
                return None

            # Render top region of the first page to an image
            clip = fitz.Rect(
                0,
                0,
                page.rect.width,
                page.rect.height * self.ocr_top_ratio,
            )
            pix = page.get_pixmap(clip=clip, dpi=150)
            img_bytes = pix.tobytes("png")
            b64_data = base64.b64encode(img_bytes).decode("utf-8")

            from bisheng.knowledge.rag.pipeline.loader.paddle_ocr import PaddleOcrLoader

            loader = PaddleOcrLoader(
                url=url,
                auth_token=ocr_conf.auth_token or None,
                headers=ocr_conf.headers or None,
                timeout=ocr_conf.timeout or 60,
            )
            result = loader._call_api_sync(b64_data)
            layout_results = result.get("layoutAnalysisResult", [])
            items = loader._extract_parsing_items(layout_results)
            if not items:
                return None
            # Pick topmost title-ish or text block
            title_items = [i for i in items if i.get("type") == "Title"]
            pool = title_items if title_items else items
            pool.sort(key=lambda x: x.get("bbox", [0, 0, 0, 0])[1])
            return pool[0].get("text", "").strip() or None
        except Exception as e:
            # Title extraction is best-effort; OCR failure should not block parsing.
            logger.warning("pdf ocr title extract failed: {}", e)
        return None


class ImageTitleExtractor(BaseTitleExtractor):
    """Extract title from images via OCR.

    Strategy:
        1. Crop the top region of the image.
        2. Call PaddleOCR HTTP API.
        3. Return the topmost text block.
    """

    def __init__(self, ocr_top_ratio: float = 0.25) -> None:
        self.ocr_top_ratio = ocr_top_ratio

    def extract(self, file_path: str) -> str | None:
        try:
            from bisheng.core.config.settings import settings

            ocr_conf = settings.knowledge.paddle_ocr
            url = ocr_conf.url.strip() if ocr_conf.url else ""
            if not url:
                return None

            from PIL import Image

            with Image.open(file_path) as img:
                width, height = img.size
                top_height = max(1, int(height * self.ocr_top_ratio))
                crop_box = (0, 0, width, top_height)
                cropped = img.crop(crop_box)
                buffer = BytesIO()
                cropped.save(buffer, format="PNG")
                b64_data = base64.b64encode(buffer.getvalue()).decode("utf-8")

            from bisheng.knowledge.rag.pipeline.loader.paddle_ocr import PaddleOcrLoader

            loader = PaddleOcrLoader(
                url=url,
                auth_token=ocr_conf.auth_token or None,
                headers=ocr_conf.headers or None,
                timeout=ocr_conf.timeout or 60,
            )
            result = loader._call_api_sync(b64_data)
            layout_results = result.get("layoutAnalysisResult", [])
            items = loader._extract_parsing_items(layout_results)
            if not items:
                return None
            # Prefer title labels, otherwise pick topmost text
            title_items = [i for i in items if i.get("type") == "Title"]
            pool = title_items if title_items else items
            pool.sort(key=lambda x: x.get("bbox", [0, 0, 0, 0])[1])
            return pool[0].get("text", "").strip() or None
        except Exception as e:
            # Title extraction is best-effort; OCR failure should not block parsing.
            logger.warning("image title extract failed: {}", e)
        return None


class FileTitleExtractorService:
    """Facade for extracting document titles from supported file formats."""

    _EXTRACTORS: dict[str, BaseTitleExtractor] = {
        "txt": TxtTitleExtractor(),
        "md": MarkdownTitleExtractor(),
        "html": HtmlTitleExtractor(),
        "docx": DocxTitleExtractor(),
        "doc": DocTitleExtractor(),
        "pptx": PptxTitleExtractor(),
        "ppt": PptTitleExtractor(),
        "xlsx": ExcelTitleExtractor(),
        "xls": ExcelTitleExtractor(),
        "csv": CsvTitleExtractor(),
        "pdf": PdfTitleExtractor(),
        "png": ImageTitleExtractor(),
        "jpg": ImageTitleExtractor(),
        "jpeg": ImageTitleExtractor(),
    }

    @classmethod
    def extract_title(cls, file_path: str) -> str | None:
        """Extract the title from *file_path* based on its extension.

        Returns the raw title string or ``None`` if no title could be extracted.
        The caller is responsible for sanitizing the result before using it as a
        file name.
        """
        if not file_path or not os.path.exists(file_path):
            logger.info("title extraction skipped, file missing file_path={}", file_path)
            return None
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        extractor = cls._EXTRACTORS.get(ext)
        logger.info("title extraction dispatch file_path={} extension={} extractor={}", file_path, ext, type(extractor).__name__ if extractor else None)
        if extractor is None:
            logger.info("no title extractor for extension: {}", ext)
            return None
        try:
            title = extractor.extract(file_path)
            logger.info(
                "title extraction done file_path={} extension={} title={}",
                file_path,
                ext,
                title,
            )
            return title
        except Exception as e:
            # Title extraction is best-effort; a parse failure should not block parsing.
            logger.warning("title extraction failed for {}: {}", file_path, e)
            return None
