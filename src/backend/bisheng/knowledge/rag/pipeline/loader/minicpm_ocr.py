"""MiniCPM-OCR loader: page-level Markdown from an OpenAI-compatible endpoint."""

import asyncio
import base64
import re
import time
from concurrent.futures import ThreadPoolExecutor

import fitz
import httpx
import requests
from langchain_core.documents import Document
from loguru import logger

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.mineru import html_table_to_md
from bisheng.utils.exceptions import EtlException

# MIME types for the image inputs that reuse this loader (see FileExtensionMap).
IMAGE_MIME_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "bmp": "image/bmp",
}

# MiniCPM-OCR may emit tables as inline HTML, which has no splitter separators
# and grows 3-4x in size; converting to Markdown keeps chunks splittable.
_TABLE_HTML_RE = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)


class MinicpmOcrLoader(BaseBishengLoader):
    """Parse PDF pages or a single image with a MiniCPM-OCR inference service.

    The service must expose the OpenAI chat-completions API (vLLM, SGLang,
    llama.cpp, ...). MiniCPM-OCR expects the page image *before* the prompt, so
    each request carries the rendered page as an ``image_url`` part followed by
    the configured instruction text.

    This loader sends whole pages instead of cropped regions: MiniCPM-OCR's
    official document parsing SDK instead runs PP-DocLayoutV3 layout detection
    locally and sends cropped regions, so reading order on complex multi-column
    pages can differ. Output is page-level Markdown only: the service returns no
    block bounding boxes, so ``bbox_list`` stays empty and ``metadata.bboxes``
    holds one empty entry per page.
    """

    _RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        base_url: str,
        model: str = "minicpm-ocr",
        api_key: str = "",
        prompt: str = "Text Recognition:",
        timeout: int = 120,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        concurrency: int = 4,
        dpi: int = 200,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        mm_processor_kwargs: dict | None = None,
        request_kwargs: dict | None = None,
        headers: dict | None = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.base_url = (base_url or "").rstrip("/")
        if not self.base_url:
            raise EtlException("MiniCPM-OCR base_url is not configured")
        self.model = model
        self.prompt = prompt
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.retry_backoff = max(0.0, retry_backoff)
        self.concurrency = max(1, concurrency)
        self.dpi = dpi
        self.max_tokens = max_tokens
        self.temperature = temperature
        # Not sent by default: vLLM only accepts request-level processor kwargs
        # with --trust-request-mm-kwargs, and other backends ignore them. The
        # official deployments already pin downsample_mode=4x server-side.
        self.mm_processor_kwargs = dict(mm_processor_kwargs or {})
        # Server-specific body fields (e.g. chat_template_kwargs, top_k).
        self.request_kwargs = dict(request_kwargs or {})
        self.headers = dict(headers or {})
        if api_key:
            self.headers.setdefault("Authorization", f"Bearer {api_key}")

    @property
    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _page_images(self) -> list[tuple[bytes, str]]:
        """Return one ``(image_bytes, mime_type)`` pair per page.

        Image inputs are sent as-is (they are already a single page); PDFs are
        rasterized page by page at ``dpi``.
        """
        mime_type = IMAGE_MIME_TYPES.get((self.file_extension or "").lower())
        if mime_type:
            try:
                with open(self.file_path, "rb") as handle:
                    return [(handle.read(), mime_type)]
            except OSError as e:
                logger.error(f"Failed to read file {self.file_path}: {e}")
                raise EtlException(f"Cannot read file: {e}")

        try:
            document = fitz.open(self.file_path)
        except Exception as e:
            logger.error(f"Failed to open file {self.file_path} for MiniCPM-OCR: {e}")
            raise EtlException(f"Cannot open file: {e}")

        try:
            matrix = fitz.Matrix(self.dpi / 72, self.dpi / 72)
            images = []
            for page in document:
                images.append((page.get_pixmap(matrix=matrix).tobytes("png"), "image/png"))
        except Exception as e:
            logger.error(f"Failed to render {self.file_path} to images: {e}")
            raise EtlException(f"Cannot render PDF pages: {e}")
        finally:
            document.close()

        if not images:
            raise EtlException("MiniCPM-OCR found no pages to parse")
        return images

    def _page_payloads(self) -> list[dict]:
        return [self._build_payload(data, mime) for data, mime in self._page_images()]

    def _build_payload(self, image_bytes: bytes, mime_type: str) -> dict:
        b64_data = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            # ``request_kwargs`` may carry server-specific fields; managed keys win.
            **self.request_kwargs,
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        # MiniCPM-OCR reads the image first, instruction last.
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64_data}"},
                        },
                        {"type": "text", "text": self.prompt},
                    ],
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if self.mm_processor_kwargs:
            payload["mm_processor_kwargs"] = self.mm_processor_kwargs
        return payload

    def _should_retry(self, status_code: int) -> bool:
        return status_code in self._RETRYABLE_HTTP_STATUS_CODES

    def _retry_delay(self, retry_index: int) -> float:
        return self.retry_backoff * (2**retry_index)

    def _log_retry(self, page_number: int, reason: str, retry_number: int, delay: float) -> None:
        logger.warning(
            "MiniCPM-OCR temporarily unavailable for page {} ({}); retry {}/{} in {}s",
            page_number,
            reason,
            retry_number,
            self.max_retries,
            delay,
        )

    def _extract_text(self, response_json: dict, page_number: int) -> str:
        """Pull the Markdown out of one chat-completions response."""
        try:
            choice = response_json["choices"][0]
            message = choice["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise EtlException(
                f"MiniCPM-OCR returned an unexpected response for page {page_number}: {response_json}"
            ) from e
        if choice.get("finish_reason") == "length":
            raise EtlException(
                f"MiniCPM-OCR output for page {page_number} was truncated "
                f"(max_tokens={self.max_tokens}); raise max_tokens or lower dpi"
            )
        if not isinstance(content, str):
            raise EtlException(f"MiniCPM-OCR returned non-text content for page {page_number}")
        if not content.strip() and message.get("reasoning_content"):
            # Thinking mode writes the transcription to reasoning_content and
            # leaves content empty, so the service must run with thinking off.
            raise EtlException(
                f"MiniCPM-OCR returned empty content for page {page_number} but filled reasoning_content; "
                "disable thinking on the service (e.g. --default-chat-template-kwargs "
                "'{\"enable_thinking\": false}' for vLLM, --reasoning off for llama.cpp)"
            )
        return content.strip()

    def _recognize_sync(self, page_number: int, payload: dict) -> str:
        for retry_index in range(self.max_retries + 1):
            try:
                response = requests.post(
                    self._endpoint,
                    json=payload,
                    headers=self.headers,
                    timeout=self.timeout,
                )
            except requests.ConnectTimeout as e:
                # Connecting failed: transient, unlike a read timeout.
                if retry_index >= self.max_retries:
                    raise EtlException(f"MiniCPM-OCR connection failed on page {page_number}: {e}") from e
                delay = self._retry_delay(retry_index)
                self._log_retry(page_number, str(e), retry_index + 1, delay)
                time.sleep(delay)
                continue
            except requests.Timeout as e:
                logger.error(f"MiniCPM-OCR request timed out on page {page_number}: {e}")
                raise EtlException(f"MiniCPM-OCR timeout on page {page_number}") from e
            except requests.ConnectionError as e:
                if retry_index >= self.max_retries:
                    raise EtlException(f"MiniCPM-OCR connection failed on page {page_number}: {e}") from e
                delay = self._retry_delay(retry_index)
                self._log_retry(page_number, str(e), retry_index + 1, delay)
                time.sleep(delay)
                continue
            except requests.RequestException as e:
                raise EtlException(f"MiniCPM-OCR request failed on page {page_number}: {e}") from e

            if self._should_retry(response.status_code) and retry_index < self.max_retries:
                delay = self._retry_delay(retry_index)
                self._log_retry(page_number, f"status={response.status_code}", retry_index + 1, delay)
                time.sleep(delay)
                continue
            if response.status_code != 200:
                raise EtlException(
                    f"MiniCPM-OCR API error on page {page_number}: "
                    f"status={response.status_code}, resp={response.text[:500]}"
                )
            try:
                response_json = response.json()
            except ValueError as e:
                raise EtlException("MiniCPM-OCR returned invalid JSON response") from e
            return self._extract_text(response_json, page_number)

        raise AssertionError("unreachable")

    async def _recognize_async(self, client: httpx.AsyncClient, page_number: int, payload: dict) -> str:
        for retry_index in range(self.max_retries + 1):
            try:
                response = await client.post(self._endpoint, json=payload, headers=self.headers)
            except httpx.ConnectTimeout as e:
                if retry_index >= self.max_retries:
                    raise EtlException(f"MiniCPM-OCR connection failed on page {page_number}: {e}") from e
                delay = self._retry_delay(retry_index)
                self._log_retry(page_number, str(e), retry_index + 1, delay)
                await asyncio.sleep(delay)
                continue
            except httpx.TimeoutException as e:
                logger.error(f"MiniCPM-OCR request timed out on page {page_number}: {e}")
                raise EtlException(f"MiniCPM-OCR timeout on page {page_number}") from e
            except httpx.TransportError as e:
                if retry_index >= self.max_retries:
                    raise EtlException(f"MiniCPM-OCR connection failed on page {page_number}: {e}") from e
                delay = self._retry_delay(retry_index)
                self._log_retry(page_number, str(e), retry_index + 1, delay)
                await asyncio.sleep(delay)
                continue
            except httpx.HTTPError as e:
                raise EtlException(f"MiniCPM-OCR request failed on page {page_number}: {e}") from e

            if self._should_retry(response.status_code) and retry_index < self.max_retries:
                delay = self._retry_delay(retry_index)
                self._log_retry(page_number, f"status={response.status_code}", retry_index + 1, delay)
                await asyncio.sleep(delay)
                continue
            if response.status_code != 200:
                raise EtlException(
                    f"MiniCPM-OCR API error on page {page_number}: "
                    f"status={response.status_code}, resp={response.text[:500]}"
                )
            try:
                response_json = response.json()
            except ValueError as e:
                raise EtlException("MiniCPM-OCR returned invalid JSON response") from e
            return self._extract_text(response_json, page_number)

        raise AssertionError("unreachable")

    @staticmethod
    def _convert_tables_to_md(md_text: str) -> str:
        """Convert inline HTML tables to Markdown so chunks stay splittable."""
        if not md_text or "<table" not in md_text.lower():
            return md_text
        return _TABLE_HTML_RE.sub(lambda m: html_table_to_md(m.group(0)), md_text)

    def _build_document(self, page_texts: list[str]) -> Document:
        """Merge page Markdown into one Document with page-level metadata.

        ``indexes`` are computed against the final content string (including the
        ``\\n\\n`` separators) so chunk attribution in later transformers stays
        aligned; empty pages contribute no entry but keep their original number.
        ``pages`` is 0-based, matching the other external parsers.
        """
        metadata = {
            **self.file_metadata,
            "bboxes": [],
            "pages": [],
            "indexes": [],
            "types": [],
        }
        parts: list[str] = []
        offset = 0
        for page_index, text in enumerate(page_texts):
            text = self._convert_tables_to_md(text).strip()
            if not text:
                continue
            if parts:
                offset += 2  # "\n\n" between pages
            metadata["bboxes"].append([])
            metadata["pages"].append(page_index)
            metadata["indexes"].append([offset, offset + len(text)])
            metadata["types"].append("text")
            parts.append(text)
            offset += len(text)

        if not parts:
            raise EtlException("MiniCPM-OCR returned no readable content")

        logger.info(f"MiniCPM-OCR parsed {self.file_name}: {len(parts)} non-empty pages")
        return Document(page_content="\n\n".join(parts), metadata=metadata)

    def load(self) -> list[Document]:
        """Synchronously parse the document, one request per page."""
        payloads = self._page_payloads()
        page_texts = [""] * len(payloads)
        with ThreadPoolExecutor(max_workers=min(self.concurrency, len(payloads))) as pool:
            futures = [
                pool.submit(self._recognize_sync, page_number, payload)
                for page_number, payload in enumerate(payloads, start=1)
            ]
            try:
                for index, future in enumerate(futures):
                    page_texts[index] = future.result()
            except BaseException:
                # Cancel queued pages so a failed file stops consuming requests.
                for future in futures:
                    future.cancel()
                raise
        return [self._build_document(page_texts)]

    async def aload(self) -> list[Document]:
        """Asynchronously parse the document with bounded page concurrency."""
        # Rasterizing and base64-encoding are CPU-bound; keep the loop responsive.
        payloads = await asyncio.to_thread(self._page_payloads)
        semaphore = asyncio.Semaphore(self.concurrency)

        async def recognize(page_number: int, payload: dict, client: httpx.AsyncClient) -> str:
            async with semaphore:
                return await self._recognize_async(client, page_number, payload)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            tasks = [
                asyncio.create_task(recognize(page_number, payload, client))
                for page_number, payload in enumerate(payloads, start=1)
            ]
            try:
                page_texts = await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    task.cancel()
                # Drain inside the client context so cancellations don't hit a closed client.
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
        return [self._build_document(list(page_texts))]
