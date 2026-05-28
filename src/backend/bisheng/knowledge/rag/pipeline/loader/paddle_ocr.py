import base64
import os
import re
from typing import List, Dict, Optional, Tuple

import httpx
import requests
from langchain_core.documents import Document
from loguru import logger

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.mineru import html_table_to_md
from bisheng.knowledge.rag.pipeline.types import TextBbox
from bisheng.utils.exceptions import EtlException


# Matches the inline HTML <table>...</table> blocks PaddleOCR emits in markdown.text.
# DOTALL because tables may wrap across rendered "lines" (though usually single-line).
_TABLE_HTML_RE = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)


class PaddleOcrLoader(BaseBishengLoader):
    """PaddleOCR document loader for parsing documents using PaddleOCR API."""

    # Mapping from PaddleOCR block labels to standard types.
    # Observed labels in production: paragraph_title, doc_title, figure_title,
    # text, aside_text, number, table, formula, list, header, footer,
    # image, header_image, chart, vision_footnote.
    LABEL_TYPE_MAP = {
        "paragraph_title": "Title",
        "doc_title": "Title",
        "figure_title": "Caption",
        "text": "text",
        "aside_text": "text",
        "number": "text",
        "image": "Image",
        "header_image": "Image",
        "chart": "Image",
        "table": "Table",
        "formula": "Formula",
        "list": "List",
        "header": "Header",
        "footer": "Footer",
        "vision_footnote": "Footnote",
    }

    # Image-class labels: when block_content is empty, the block is just a
    # cropped figure with no extracted text — skip it from text indexing.
    _IMAGE_LABELS = {"image", "header_image", "chart"}

    def __init__(
        self,
        url: str,
        auth_token: str | None = None,
        headers: dict | None = None,
        timeout: int = 120,
        retain_images: bool = True,
        filter_page_header_footer: bool = False,
        request_kwargs: dict | None = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.url = url.rstrip("/")
        self.auth_token = auth_token

        self.request_kwargs = request_kwargs if request_kwargs else {}

        self.timeout = timeout
        self.retain_images = retain_images
        self.filter_page_header_footer = filter_page_header_footer

        if headers:
            self.headers = headers
            self.headers["Authorization"] = f"token {self.auth_token}"
        else:
            self.headers = {
                "Authorization": f"token {self.auth_token}",
            }

    @property
    def _detect_file_type(self) -> int:
        """Detect file type from file extension."""
        if self.file_extension == "pdf":
            return 0
        return 1

    def _build_payload(self, b64_data: str) -> dict:
        """Build API request payload."""
        return {
            "file": b64_data,
            "fileType": self._detect_file_type,
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
            **self.request_kwargs,
        }

    def _validate_response(self, result: dict) -> dict:
        """Validate API response and return result dict."""
        if result.get("errorCode", 0) != 0:
            logger.error(f"PaddleOCR API error: {result}")
            raise EtlException(f"PaddleOCR API error: {result.get('errorMsg', 'Unknown error')}")
        return result.get("result", {})

    def _call_api_sync(self, b64_data: str) -> dict:
        """Call PaddleOCR API synchronously."""
        payload = self._build_payload(b64_data)
        try:
            resp = requests.post(
                self.url,
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
            )
        except requests.Timeout as e:
            logger.error(f"PaddleOCR API request timed out: {e}")
            raise EtlException("PaddleOCR API timeout")
        except Exception as e:
            if "Timeout" in str(e):
                logger.error(f"PaddleOCR API request timed out: {e}")
                raise EtlException("PaddleOCR API timeout")
            raise e

        if resp.status_code != 200:
            raise EtlException(f"PaddleOCR API error: status={resp.status_code}, resp={resp.text}")
        try:
            resp_json = resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as e:
            logger.error(f"PaddleOCR API returned invalid JSON: {e}")
            raise EtlException("PaddleOCR API returned invalid JSON response")
        return self._validate_response(resp_json)

    async def _call_api_async(self, b64_data: str) -> dict:
        """Call PaddleOCR API asynchronously."""
        payload = self._build_payload(b64_data)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self.url,
                    json=payload,
                    headers=self.headers,
                )
        except httpx.TimeoutException as e:
            logger.error(f"PaddleOCR API request timed out: {e}")
            raise EtlException("PaddleOCR API timeout")
        except Exception as e:
            if "Timeout" in str(e):
                logger.error(f"PaddleOCR API request timed out: {e}")
                raise EtlException("PaddleOCR API timeout")
            raise e

        if resp.status_code != 200:
            raise EtlException(f"PaddleOCR API error: status={resp.status_code}, resp={resp.text}")
        try:
            resp_json = resp.json()
        except (ValueError, Exception) as e:
            logger.error(f"PaddleOCR API returned invalid JSON: {e}")
            raise EtlException("PaddleOCR API returned invalid JSON response")
        return self._validate_response(resp_json)

    def _map_block_type(self, block_label: str) -> str:
        """Map PaddleOCR block label to standard type."""
        return self.LABEL_TYPE_MAP.get(block_label, block_label)

    def _is_skip_block(self, item: dict) -> bool:
        """Check if a block should be skipped (decorative images, empty content)."""
        block_label = item.get("block_label", "text")
        if self.filter_page_header_footer and block_label in {"header", "footer"}:
            return True
        # Image-class blocks (image / chart / header_image) with no extracted
        # content are purely decorative crops — they contribute no text and
        # would otherwise pollute parsing items with empty entries.
        if block_label in self._IMAGE_LABELS and not item.get("block_content"):
            return True
        return False

    def _extract_parsing_items(self, layout_results: list[dict]) -> list[dict]:
        """Extract ordered parsing items from all pages."""
        items = []
        for page_idx, page_result in enumerate(layout_results):
            parsing_list = page_result.get("prunedResult", {}).get("parsing_res_list", [])
            for item in parsing_list:
                if self._is_skip_block(item):
                    continue
                items.append(
                    {
                        "text": item.get("block_content", ""),
                        "type": self._map_block_type(item.get("block_label", "text")),
                        "bbox": item.get("block_bbox", []),
                        "page": page_idx,
                        "order": item.get("block_order") or 0,
                    }
                )
        return items

    @staticmethod
    def _substitute_image_urls(md_text: str, image_url_mapping: dict[str, str] | None) -> str:
        """Replace API-returned image paths with final (MinIO) URLs.

        Must be applied symmetrically to both the merged text and the per-page text
        used for index computation, otherwise chunk_bbox alignment will drift.
        """
        if not md_text or not image_url_mapping:
            return md_text
        for img_path, final_url in image_url_mapping.items():
            md_text = md_text.replace(img_path, final_url)
        return md_text

    @staticmethod
    def _convert_tables_to_md(md_text: str) -> str:
        """Convert PaddleOCR's inline styled HTML tables to markdown tables.

        PaddleOCR's markdown.text renders tables as single-line
        ``<table border=1 style='...'><tr><td style='...'>...</td>...</table>``
        blobs. These contain none of the default splitter separators
        (``\\n\\n / \\n / 。 / .``), so any table > chunk_size becomes an
        un-splittable chunk and trips KnowledgeFileChunkMaxError. Converting
        them to markdown table form puts ``\\n`` between rows and shrinks
        their byte size 3-4x, letting the splitter break at row boundaries.
        """
        if not md_text or "<table" not in md_text.lower():
            return md_text
        return _TABLE_HTML_RE.sub(lambda m: html_table_to_md(m.group(0)), md_text)

    def _merge_parsing_results(
        self, layout_results: list[dict], image_url_mapping: dict[str, str] | None = None
    ) -> tuple[str, dict, list[dict]]:
        """
        Merge parsing results from all pages.

        Returns:
            Tuple of (merged_text, metadata, parsing_items)
        """
        # Collect markdown text from each page. Tables are converted from styled
        # inline HTML to markdown form here (BEFORE metadata.indexes are computed)
        # so downstream chunk_bbox alignment uses the same text the splitter sees.
        markdown_texts = []
        for page_result in layout_results:
            md_text = self._substitute_image_urls(page_result.get("markdown", {}).get("text", ""), image_url_mapping)
            md_text = self._convert_tables_to_md(md_text)
            if self.filter_page_header_footer and md_text:
                parsing_list = page_result.get("prunedResult", {}).get("parsing_res_list", [])
                for item in parsing_list:
                    if self._is_skip_block(item):
                        block_content = item.get("block_content", "")
                        if block_content:
                            md_text = md_text.replace(block_content, "", 1)
            if md_text:
                markdown_texts.append(md_text)
        merged_text = "\n\n".join(markdown_texts)

        # Build metadata: bboxes, pages, indexes, types
        metadata = dict(bboxes=[], pages=[], indexes=[], types=[])
        text_offset = 0

        for page_idx, page_result in enumerate(layout_results):
            md_text = self._substitute_image_urls(page_result.get("markdown", {}).get("text", ""), image_url_mapping)
            md_text = self._convert_tables_to_md(md_text)
            parsing_list = page_result.get("prunedResult", {}).get("parsing_res_list", [])
            search_pos = 0

            for item in parsing_list:
                if self._is_skip_block(item):
                    continue

                block_content = item.get("block_content", "")
                block_label = item.get("block_label", "text")
                block_bbox = item.get("block_bbox", [])

                # For table blocks, search using the converted markdown form so the
                # offset lines up with what md_text actually contains after conversion.
                search_token = (
                    html_table_to_md(block_content) if block_label == "table" and block_content else block_content
                )

                # Find the position of search_token in this page's markdown
                if search_token and search_token in md_text:
                    local_start = md_text.find(search_token, search_pos)
                    if local_start == -1:
                        local_start = md_text.find(search_token)
                    global_start = text_offset + local_start
                    global_end = global_start + len(search_token)
                    search_pos = local_start + len(search_token)

                    metadata["bboxes"].append(block_bbox)
                    metadata["pages"].append(page_idx)
                    metadata["indexes"].append([global_start, global_end])
                    metadata["types"].append(self._map_block_type(block_label))

            # Update offset for next page (+2 for "\n\n" separator)
            text_offset += len(md_text) + (2 if page_idx < len(layout_results) - 1 else 0)

        parsing_items = self._extract_parsing_items(layout_results)
        return merged_text, metadata, parsing_items

    def parse_bbox_list(self, parsing_items: list[dict]):
        """Build bbox_list from parsing items for TextBbox."""
        if not parsing_items:
            return
        self.bbox_list = []
        for idx, item in enumerate(parsing_items):
            bbox = item.get("bbox", [])
            if not bbox or len(bbox) < 4:
                continue
            try:
                bbox_coords = [float(x) for x in bbox]
            except (ValueError, TypeError):
                logger.warning(f"Invalid bbox value, skipping: {bbox}")
                continue
            self.bbox_list.append(
                TextBbox(
                    text=item.get("text", ""),
                    type=item.get("type", "text"),
                    part_id=str(idx),
                    bbox=bbox_coords,
                    page=item.get("page", 0),
                )
            )

    def _process_images(self, layout_results: list[dict]) -> dict[str, str]:
        """Stage API-returned images under local_image_dir; bytes get uploaded
        later by ImageUploadTransformer.

        Returns ``{api_image_path: final_url}`` so ``_substitute_image_urls`` can
        rewrite the markdown text BEFORE metadata.indexes are computed.
        """
        if not self.retain_images:
            return {}

        image_url_mapping: dict[str, str] = {}
        self.ensure_local_image_dir()

        for page_result in layout_results:
            images = page_result.get("markdown", {}).get("images", {}) or {}
            for img_path, payload in images.items():
                try:
                    image_bytes = self._fetch_image_bytes(payload)
                except Exception:
                    logger.exception(f"paddle: failed to retrieve image {img_path}")
                    continue
                filename = img_path.replace("/", "_")
                local_path = os.path.join(self.local_image_dir, filename)
                with open(local_path, "wb") as f:
                    f.write(image_bytes)
                image_url_mapping[img_path] = self.build_image_url(filename)

        return image_url_mapping

    def _fetch_image_bytes(self, payload: str) -> bytes:
        """Accept either an HTTP(S) URL or a base64 payload.

        PaddleOCR PP-StructureV3 serving returns ``markdown.images`` values in
        different shapes depending on deployment:
          - AIStudio-hosted: presigned HTTPS URLs to BCE OSS objects;
          - self-hosted official PaddleX serving: base64-encoded image bytes
            (sometimes with the ``data:image/...;base64,`` prefix, sometimes raw).
        """
        if payload.startswith(("http://", "https://")):
            resp = requests.get(payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.content
        if payload.startswith("data:image/"):
            _, b64 = payload.split(",", 1)
            return base64.b64decode(b64)
        return base64.b64decode(payload)

    def _build_documents(self, layout_results: List[Dict]) -> List[Document]:
        """Build Document list from layout results."""
        if not layout_results:
            logger.warning(f"PaddleOCR returned empty results for {self.file_name}")
            return [Document(page_content="", metadata=self.file_metadata)]

        image_url_mapping: Dict[str, str] = {}
        if self.retain_images:
            image_url_mapping = self._process_images(layout_results)

        content, metadata, parsing_items = self._merge_parsing_results(layout_results, image_url_mapping)
        self.parse_bbox_list(parsing_items)
        metadata.update(self.file_metadata)

        logger.info(f"PaddleOCR parsed {self.file_name}: {len(content)} chars, {len(self.bbox_list)} bboxes")
        return [Document(page_content=content, metadata=metadata)]

    def load(self) -> list[Document]:
        """Synchronously load and parse document using PaddleOCR API."""
        try:
            with open(self.file_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("ascii")
        except (OSError, FileNotFoundError, PermissionError) as e:
            logger.error(f"Failed to read file {self.file_path}: {e}")
            raise EtlException(f"Cannot read file: {e}")

        api_result = self._call_api_sync(b64_data)
        layout_results = api_result.get("layoutParsingResults", [])
        return self._build_documents(layout_results)

    async def aload(self) -> list[Document]:
        """Asynchronously load and parse document using PaddleOCR API."""
        try:
            with open(self.file_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("ascii")
        except (OSError, FileNotFoundError, PermissionError) as e:
            logger.error(f"Failed to read file {self.file_path}: {e}")
            raise EtlException(f"Cannot read file: {e}")

        api_result = await self._call_api_async(b64_data)
        layout_results = api_result.get("layoutParsingResults", [])
        return self._build_documents(layout_results)
