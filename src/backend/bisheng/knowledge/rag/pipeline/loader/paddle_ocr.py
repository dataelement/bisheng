import base64
import os
from typing import List, Dict, Optional, Tuple

import httpx
import requests
from langchain_core.documents import Document
from loguru import logger

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.utils.pdf_header_footer import filter_repeated_header_footer_blocks
from bisheng.knowledge.rag.pipeline.types import TextBbox
from bisheng.utils.exceptions import EtlException


class PaddleOcrLoader(BaseBishengLoader):
    """PaddleOCR document loader for parsing documents using PaddleOCR API."""

    # Mapping from PaddleOCR block labels to standard types
    LABEL_TYPE_MAP = {
        "paragraph_title": "Title",
        "text": "text",
        "image": "Image",
        "table": "Table",
        "formula": "Formula",
        "list": "List",
        "header": "Header",
        "footer": "Footer",
    }

    def __init__(
            self,
            url: str,
            auth_token: Optional[str] = None,
            headers: Optional[Dict] = None,
            timeout: int = 120,
            retain_images: bool = True,
            filter_page_header_footer: bool = False,
            request_kwargs: Optional[Dict] = None,
            *args,
            **kwargs,
    ):
        super(PaddleOcrLoader, self).__init__(*args, **kwargs)
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

    def _build_payload(self, b64_data: str) -> Dict:
        """Build API request payload."""
        return {
            "file": b64_data,
            "fileType": self._detect_file_type,
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
            **self.request_kwargs
        }

    def _validate_response(self, result: Dict) -> Dict:
        """Validate API response and return result dict."""
        if result.get("errorCode", 0) != 0:
            logger.error(f"PaddleOCR API error: {result}")
            raise EtlException(
                f"PaddleOCR API error: {result.get('errorMsg', 'Unknown error')}"
            )
        return result.get("result", {})

    def _call_api_sync(self, b64_data: str) -> Dict:
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
            raise EtlException(
                f"PaddleOCR API error: status={resp.status_code}, resp={resp.text}"
            )
        try:
            resp_json = resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as e:
            logger.error(f"PaddleOCR API returned invalid JSON: {e}")
            raise EtlException(f"PaddleOCR API returned invalid JSON response")
        return self._validate_response(resp_json)

    async def _call_api_async(self, b64_data: str) -> Dict:
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
            raise EtlException(
                f"PaddleOCR API error: status={resp.status_code}, resp={resp.text}"
            )
        try:
            resp_json = resp.json()
        except (ValueError, Exception) as e:
            logger.error(f"PaddleOCR API returned invalid JSON: {e}")
            raise EtlException(f"PaddleOCR API returned invalid JSON response")
        return self._validate_response(resp_json)

    def _map_block_type(self, block_label: str) -> str:
        """Map PaddleOCR block label to standard type."""
        return self.LABEL_TYPE_MAP.get(block_label, block_label)

    def _is_skip_block(self, item: Dict) -> bool:
        """Check if a block should be skipped (decorative images, empty content)."""
        block_label = item.get("block_label", "text")
        block_order = item.get("block_order")
        if self.filter_page_header_footer and block_label in {"header", "footer"}:
            return True
        if block_label == "image" and not item.get("block_content"):
            return True
        if block_order is None and block_label == "image":
            return True
        return False

    def _extract_parsing_items(
            self, layout_results: List[Dict]
    ) -> List[Dict]:
        """Extract ordered parsing items from all pages."""
        items = []
        for page_idx, page_result in enumerate(layout_results):
            parsing_list = page_result.get("prunedResult", {}).get("parsing_res_list", [])
            for item in parsing_list:
                if self._is_skip_block(item):
                    continue
                items.append({
                    "text": item.get("block_content", ""),
                    "type": self._map_block_type(item.get("block_label", "text")),
                    "bbox": item.get("block_bbox", []),
                    "page": page_idx,
                    "order": item.get("block_order") or 0,
                })
        return items

    def _merge_parsing_results(
            self, layout_results: List[Dict]
    ) -> Tuple[str, Dict, List[Dict]]:
        """
        Merge parsing results from all pages.

        Returns:
            Tuple of (merged_text, metadata, parsing_items)
        """
        # Collect markdown text from each page
        markdown_texts = []
        for page_result in layout_results:
            md_text = page_result.get("markdown", {}).get("text", "")
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
            md_text = page_result.get("markdown", {}).get("text", "")
            parsing_list = page_result.get("prunedResult", {}).get("parsing_res_list", [])
            search_pos = 0

            for item in parsing_list:
                if self._is_skip_block(item):
                    continue

                block_content = item.get("block_content", "")
                block_bbox = item.get("block_bbox", [])

                # Find the position of block_content in this page's markdown
                if block_content and block_content in md_text:
                    local_start = md_text.find(block_content, search_pos)
                    if local_start == -1:
                        local_start = md_text.find(block_content)
                    global_start = text_offset + local_start
                    global_end = global_start + len(block_content)
                    search_pos = local_start + len(block_content)

                    metadata["bboxes"].append(block_bbox)
                    metadata["pages"].append(page_idx)
                    metadata["indexes"].append([global_start, global_end])
                    metadata["types"].append(self._map_block_type(item.get("block_label", "text")))

            # Update offset for next page (+2 for "\n\n" separator)
            text_offset += len(md_text) + (2 if page_idx < len(layout_results) - 1 else 0)

        parsing_items = self._extract_parsing_items(layout_results)
        return merged_text, metadata, parsing_items

    def parse_bbox_list(self, parsing_items: List[Dict]):
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
            self.bbox_list.append(TextBbox(
                text=item.get("text", ""),
                type=item.get("type", "text"),
                part_id=str(idx),
                bbox=bbox_coords,
                page=item.get("page", 0),
            ))

    def _process_images(self, layout_results: List[Dict]) -> Dict[str, str]:
        """Download and save images from API response."""
        if not self.retain_images:
            return {}

        local_image_result = {}
        self.local_image_dir = os.path.join(self.tmp_dir, "images")
        os.makedirs(self.local_image_dir, exist_ok=True)

        for page_result in layout_results:
            images = page_result.get("markdown", {}).get("images", {})
            for img_path, img_url in images.items():
                try:
                    resp = requests.get(img_url, timeout=self.timeout)
                    if resp.status_code == 200:
                        safe_name = img_path.replace("/", "_")
                        local_path = os.path.join(self.local_image_dir, safe_name)
                        with open(local_path, "wb") as f:
                            f.write(resp.content)
                        local_image_result[img_path] = local_path
                        logger.debug(f"Saved image: {local_path}")
                except Exception as e:
                    logger.warning(f"Failed to download image {img_path}: {e}")

        return local_image_result

    def _build_documents(
            self, layout_results: List[Dict]
    ) -> List[Document]:
        """Build Document list from layout results."""
        if not layout_results:
            logger.warning(f"PaddleOCR returned empty results for {self.file_name}")
            return [Document(page_content="", metadata=self.file_metadata)]

        if self.retain_images:
            self._process_images(layout_results)

        content, metadata, parsing_items = self._merge_parsing_results(layout_results)
        self.parse_bbox_list(parsing_items)
        metadata.update(self.file_metadata)

        logger.info(
            f"PaddleOCR parsed {self.file_name}: "
            f"{len(content)} chars, {len(self.bbox_list)} bboxes"
        )
        return [Document(page_content=content, metadata=metadata)]

    def load(self) -> List[Document]:
        """Synchronously load and parse document using PaddleOCR API."""
        try:
            with open(self.file_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("ascii")
        except (FileNotFoundError, PermissionError, IOError) as e:
            logger.error(f"Failed to read file {self.file_path}: {e}")
            raise EtlException(f"Cannot read file: {e}")

        api_result = self._call_api_sync(b64_data)
        layout_results = api_result.get("layoutParsingResults", [])
        return self._build_documents(layout_results)

    async def aload(self) -> List[Document]:
        """Asynchronously load and parse document using PaddleOCR API."""
        try:
            with open(self.file_path, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode("ascii")
        except (FileNotFoundError, PermissionError, IOError) as e:
            logger.error(f"Failed to read file {self.file_path}: {e}")
            raise EtlException(f"Cannot read file: {e}")

        api_result = await self._call_api_async(b64_data)
        layout_results = api_result.get("layoutParsingResults", [])
        return self._build_documents(layout_results)
