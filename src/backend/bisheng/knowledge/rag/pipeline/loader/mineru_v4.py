"""Adapt MinerU V4 ZIP and Middle JSON to the BiSheng loader contract."""

from __future__ import annotations

import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

import fitz
import httpx
from langchain_core.documents import Document
from loguru import logger
from PIL import Image

from bisheng.core.config.settings import MineruV4Conf
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.mineru import html_table_to_md
from bisheng.knowledge.rag.pipeline.loader.mineru_v4_client import MineruV4Client, MineruV4Error
from bisheng.knowledge.rag.pipeline.loader.utils.pdf_header_footer import filter_repeated_header_footer_blocks
from bisheng.knowledge.rag.pipeline.types import TextBbox


class MineruV4Loader(BaseBishengLoader):
    MAX_MEMBERS = 4096
    MAX_MEMBER_BYTES = 128 * 1024 * 1024
    MAX_UNCOMPRESSED_BYTES = 768 * 1024 * 1024
    IMAGE_REF = re.compile(r"(?<![A-Za-z0-9_./-])(?:\./)?(images/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+)")
    IMAGE_MARKDOWN = re.compile(r"!\[[^\]]*\]\(\s*(?:\./)?images/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\s*\)")
    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

    def __init__(
        self,
        filter_page_header_footer: bool = False,
        force_ocr: bool = False,
        retain_images: bool = True,
        *args,
        **kwargs,
    ):
        config_fields = set(MineruV4Conf.model_fields)
        config_values = {key: kwargs.pop(key) for key in list(kwargs) if key in config_fields}
        super().__init__(*args, **kwargs)
        self.config = MineruV4Conf(**config_values)
        self.client = MineruV4Client(self.config)
        self.filter_page_header_footer = filter_page_header_footer
        self.force_ocr = force_ocr
        self.retain_images = retain_images

    @staticmethod
    def _valid_member(name: str) -> bool:
        parts = name.rstrip("/").split("/")
        return bool(
            name
            and not name.startswith("/")
            and "\\" not in name
            and all(part not in {"", ".", ".."} for part in parts)
        )

    @staticmethod
    def _read_limited(source, limit: int) -> bytes:
        data = source.read(limit + 1)
        if len(data) > limit:
            raise MineruV4Error("MinerU V4 ZIP member exceeds size limit")
        return data

    def _read_zip(self, archive_path: str) -> tuple[dict, dict[str, str]]:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                infos = archive.infolist()
                if len(infos) > self.MAX_MEMBERS:
                    raise MineruV4Error("MinerU V4 ZIP has too many members")
                names = set()
                total = 0
                for info in infos:
                    if not self._valid_member(info.filename) or info.filename in names:
                        raise MineruV4Error("MinerU V4 ZIP has unsafe or duplicate members")
                    names.add(info.filename)
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise MineruV4Error("MinerU V4 ZIP contains a symbolic link")
                    if info.file_size > self.MAX_MEMBER_BYTES:
                        raise MineruV4Error("MinerU V4 ZIP member exceeds size limit")
                    total += info.file_size
                    if total > self.MAX_UNCOMPRESSED_BYTES:
                        raise MineruV4Error("MinerU V4 ZIP exceeds uncompressed size limit")
                if "middle_json.json" not in names:
                    raise MineruV4Error("MinerU V4 ZIP has no Middle JSON")
                with archive.open("middle_json.json") as source:
                    middle = json.loads(self._read_limited(source, self.MAX_MEMBER_BYTES))
                if (
                    not isinstance(middle, dict)
                    or middle.get("schema") != "docvortex.middle"
                    or middle.get("schema_version") != "2.0"
                ):
                    raise MineruV4Error("MinerU V4 Middle JSON schema is unsupported")
                if not isinstance(middle.get("pages"), list) or not middle["pages"]:
                    raise MineruV4Error("MinerU V4 Middle JSON has no pages")
                images: dict[str, str] = {}
                used: set[str] = set()
                actual_total = 0
                for info in infos:
                    if info.filename.startswith("images/") and not info.is_dir():
                        if Path(info.filename).suffix.lower() not in self.IMAGE_SUFFIXES:
                            raise MineruV4Error("MinerU V4 ZIP contains an unsupported image type")
                        if not self.retain_images:
                            continue
                        filename = PurePosixPath(info.filename).name
                        if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename) or filename in used:
                            raise MineruV4Error("MinerU V4 ZIP image name is unsafe or duplicated")
                        used.add(filename)
                        target = Path(self.ensure_local_image_dir()) / filename
                        member_size = 0
                        with archive.open(info) as source, target.open("wb") as output:
                            while chunk := source.read(1024 * 1024):
                                member_size += len(chunk)
                                actual_total += len(chunk)
                                if member_size > self.MAX_MEMBER_BYTES or actual_total > self.MAX_UNCOMPRESSED_BYTES:
                                    raise MineruV4Error("MinerU V4 ZIP image exceeds size limit")
                                output.write(chunk)
                        images[info.filename] = self.build_image_url(filename)
        except (zipfile.BadZipFile, json.JSONDecodeError, RuntimeError) as exc:
            raise MineruV4Error("MinerU V4 ZIP is invalid") from exc
        return middle, images

    @staticmethod
    def _spans(value) -> str:
        if isinstance(value, str):
            return value
        if not isinstance(value, list):
            return ""
        pieces = []
        for item in value:
            if not isinstance(item, dict):
                raise MineruV4Error("MinerU V4 span is invalid")
            kind = item.get("type")
            content = item.get("content")
            if kind == "equation_inline":
                pieces.append(f"${content}$")
            elif kind == "code_inline":
                pieces.append(f"`{content}`")
            elif kind == "hyperlink":
                pieces.append(f"[{MineruV4Loader._spans(content)}]({item.get('url', '')})")
            elif kind == "text":
                pieces.append(MineruV4Loader._spans(content))
            else:
                raise MineruV4Error(f"MinerU V4 span type {kind} is unsupported")
        return "".join(pieces)

    @staticmethod
    def _image_path(block: dict) -> str | None:
        for field in ("image_path", "img_path", "image_source"):
            value = block.get(field)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict) and isinstance(value.get("path"), str):
                return value["path"]
        return None

    def _render_block(self, block: dict) -> str:
        kind = block.get("type")
        content = block.get("content")
        if kind in {
            "text",
            "ref_text",
            "header",
            "footer",
            "page_number",
            "aside_text",
            "page_footnote",
            "doc_title",
            "paragraph_title",
            "image_caption",
            "image_footnote",
            "table_caption",
            "table_footnote",
            "chart_caption",
            "chart_footnote",
            "code_caption",
            "code_footnote",
            "algorithm_body",
        }:
            text = self._spans(content)
            if kind in {"doc_title", "paragraph_title"} and text:
                level = block.get("level", 1 if kind == "doc_title" else 2)
                level = min(max(int(level), 1), 6)
                return f"{'#' * level} {text}"
            return text
        if kind in {"equation", "code_body", "image_body", "table_body", "chart_body"}:
            path = self._image_path(block)
            body = self._spans(content)
            if kind == "equation":
                return f"$${body}$$" if body else ""
            if kind == "table_body":
                body = html_table_to_md(re.sub(r"<tr\b[^>]*>", "<tr>", body, flags=re.IGNORECASE))
            if kind == "code_body":
                body = f"```\n{body}\n```" if body else ""
            if path and self.retain_images:
                body = f"![image]({path})" + (f"\n{body}" if body else "")
            return body
        if kind in {"image", "table", "chart", "code", "list", "index"}:
            if not isinstance(content, list):
                raise MineruV4Error(f"MinerU V4 {kind} block has invalid content")
            parts = [self._render_block(item) for item in content if isinstance(item, dict)]
            if len(parts) != len(content):
                raise MineruV4Error(f"MinerU V4 {kind} block has invalid children")
            if not any(parts):
                path = self._image_path(block)
                if path and self.retain_images:
                    parts = [f"![image]({path})"]
            return "\n".join(part for part in parts if part)
        raise MineruV4Error(f"MinerU V4 block type {kind} is unsupported")

    def _rewrite_image_refs(self, text: str, image_urls: dict[str, str]) -> str:
        if not self.retain_images:
            text = self.IMAGE_MARKDOWN.sub("", text)
            return self.IMAGE_REF.sub("", text)

        def replace(match: re.Match) -> str:
            reference = match.group(1)
            if reference not in image_urls:
                raise MineruV4Error(f"MinerU V4 image asset is missing: {reference}")
            return image_urls[reference]

        return self.IMAGE_REF.sub(replace, text)

    def _page_dimensions(self, middle: dict) -> dict[int, tuple[float, float]]:
        layout = (middle.get("extensions") or {}).get("docvortex_layout") or {}
        pages = layout.get("pages") or []
        dimensions = {
            item["page_idx"]: (item["width_pt"], item["height_pt"])
            for item in pages
            if isinstance(item, dict)
            and isinstance(item.get("page_idx"), int)
            and isinstance(item.get("width_pt"), (int, float))
            and isinstance(item.get("height_pt"), (int, float))
        }
        if dimensions:
            return dimensions
        if self.file_extension in {"png", "jpg", "jpeg", "bmp"}:
            try:
                with Image.open(self.file_path) as source:
                    return {0: (float(source.width), float(source.height))}
            except (OSError, ValueError):
                logger.warning("mineru_v4: source image geometry unavailable; skipping bbox scaling")
                return {}
        if self.file_extension != "pdf":
            return {}
        try:
            with fitz.open(self.file_path) as document:
                return {index: (page.rect.width, page.rect.height) for index, page in enumerate(document)}
        except (fitz.FileDataError, fitz.EmptyFileError):
            logger.warning("mineru_v4: source PDF geometry unavailable; skipping bbox scaling")
            return {}

    @staticmethod
    def _bbox(value, dimensions: tuple[float, float] | None) -> list[int]:
        if not dimensions or not isinstance(value, list) or len(value) != 4:
            return []
        if not all(isinstance(item, (int, float)) and 0 <= item <= 1 for item in value):
            return []
        x0, y0, x1, y1 = value
        if x1 <= x0 or y1 <= y0:
            return []
        width, height = dimensions
        # Keep chunk coordinates aligned with the integer keys used by preview labels.
        return [int(x0 * width), int(y0 * height), int(x1 * width), int(y1 * height)]

    @property
    def is_cloud(self) -> bool:
        """True for the hosted mineru.net API, which takes a public URL."""
        return self.config.api_url.rstrip("/").endswith("/extract/task")

    @property
    def is_upload(self) -> bool:
        """True for the hosted upload API, which pushes the bytes instead."""
        return self.config.api_url.rstrip("/").endswith("/agent/parse/file")

    def _load_upload(self) -> list[Document]:
        from bisheng.knowledge.rag.pipeline.loader.mineru_v4_cloud_client import MineruV4UploadClient

        markdown = MineruV4UploadClient(self.config).parse_uploaded(self.file_path, self.file_name)
        metadata = dict(self.file_metadata)
        # This endpoint returns markdown only, so there are no bbox coordinates
        # to attach; citation highlighting simply has nothing to draw here.
        metadata.update({"bboxes": [], "pages": [], "indexes": [], "types": []})
        logger.info("mineru_v4 upload parsed {}: {} chars", self.file_name, len(markdown))
        return [Document(page_content=markdown, metadata=metadata)]

    # -- hosted mineru.net API ---------------------------------------------------------

    #: Cloud ``content_list.json`` labels → the shared type vocabulary.
    CLOUD_TYPE_MAP = {
        "text": "text",
        "title": "Title",
        "table": "Table",
        "image": "Image",
        "equation": "Formula",
        "list": "List",
        "header": "Header",
        "footer": "Footer",
        "page_number": "text",
        "aside_text": "text",
    }

    def _cloud_public_url(self, store) -> tuple[str, str]:
        """Stage the document and return (public link, object name).

        The hosted API downloads the file itself, so the object must be reachable
        from the public internet through ``object_storage.minio.sharepoint``. The
        link is signed *before* uploading: a loopback or RFC1918 host can never
        work, and checking first avoids staging an object we would have to delete.

        The caller owns the returned object and must remove it afterwards.
        """
        from uuid import uuid4

        suffix = Path(self.file_name).suffix or ".pdf"
        object_name = f"mineru-cloud/{uuid4().hex}{suffix}"
        url = store.get_share_link_sync(object_name, bucket=store.tmp_bucket, clear_host=False, expire_days=1)

        host = (httpx.URL(url).host or "").lower()
        private = (
            host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
            or host.startswith(("10.", "192.168.", "127.", "169.254."))
            or host.endswith(".local")
            or any(host.startswith(f"172.{n}.") for n in range(16, 32))
        )
        if private:
            raise MineruV4Error(
                "The hosted MinerU API fetches documents itself, but object_storage.minio.sharepoint "
                f"resolves to {host!r}, which is not reachable from the internet. Point sharepoint at a "
                "public address, or use a self-hosted MinerU V4 deployment instead."
            )
        store.put_object_tmp_sync(object_name, self.file_path)
        return url, object_name

    def _load_cloud(self) -> list[Document]:
        from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
        from bisheng.knowledge.rag.pipeline.loader.mineru_v4_cloud_client import MineruV4CloudClient

        store = get_minio_storage_sync()
        url, object_name = self._cloud_public_url(store)
        try:
            client = MineruV4CloudClient(self.config)
            archive_path = client.parse(url, self.tmp_dir)
            return self._build_cloud_documents(*self._read_cloud_zip(archive_path))
        finally:
            # Best-effort cleanup: the staged copy exists only to be fetched once,
            # and a leftover must not fail a parse that already succeeded.
            try:
                store.remove_object_sync(bucket_name=store.tmp_bucket, object_name=object_name)
            except Exception:
                logger.warning("mineru_v4 cloud: could not remove staged object {}", object_name)

    def _read_cloud_zip(self, archive_path: str) -> tuple[str, list[dict], dict[str, str]]:
        """Read the hosted zip: ``full.md`` + ``*_content_list.json`` + ``images/``."""
        try:
            archive = zipfile.ZipFile(archive_path)
        except zipfile.BadZipFile as exc:
            raise MineruV4Error("MinerU V4 cloud result is not a ZIP") from exc
        with archive:
            infos = archive.infolist()
            if len(infos) > self.MAX_MEMBERS:
                raise MineruV4Error("MinerU V4 cloud ZIP has too many members")
            names = {info.filename for info in infos}
            total = 0
            for info in infos:
                if not self._valid_member(info.filename):
                    raise MineruV4Error("MinerU V4 cloud ZIP contains an unsafe member")
                total += info.file_size
                if total > self.MAX_UNCOMPRESSED_BYTES:
                    raise MineruV4Error("Mineru V4 cloud ZIP exceeds uncompressed size limit")

            md_names = sorted(n for n in names if n.endswith("full.md"))
            list_names = sorted(n for n in names if n.endswith("_content_list.json"))
            if not md_names or not list_names:
                raise MineruV4Error("MinerU V4 cloud ZIP is missing full.md or the content list")
            content = archive.read(md_names[0]).decode("utf-8", "replace")
            entries = json.loads(archive.read(list_names[0]))
            if not isinstance(entries, list):
                raise MineruV4Error("MinerU V4 cloud content list is not a list")

            image_urls: dict[str, str] = {}
            if self.retain_images:
                for info in infos:
                    if not info.filename.startswith("images/") or info.is_dir():
                        continue
                    filename = PurePosixPath(info.filename).name
                    if Path(filename).suffix.lower() not in self.IMAGE_SUFFIXES:
                        continue
                    target = Path(self.ensure_local_image_dir()) / filename
                    with archive.open(info) as source, target.open("wb") as output:
                        output.write(self._read_limited(source, self.MAX_MEMBER_BYTES))
                    image_urls[info.filename] = self.build_image_url(filename)
                content = self._rewrite_image_refs(content, image_urls)
        return content, entries, image_urls

    def _build_cloud_documents(self, content: str, entries: list[dict], image_urls: dict[str, str]) -> list[Document]:
        """Turn ``content_list.json`` entries into bbox metadata over ``full.md``.

        Bboxes are used by citation highlighting; an entry whose text cannot be
        located in the markdown is skipped rather than attached to a wrong span.
        """
        metadata: dict = {"bboxes": [], "pages": [], "indexes": [], "types": []}
        used: list[tuple[int, int]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            text = (entry.get("text") or "").strip()
            bbox = entry.get("bbox")
            page = entry.get("page_idx")
            if not text or not isinstance(bbox, list) or len(bbox) < 4 or not isinstance(page, int):
                continue
            token = self._rewrite_image_refs(text, image_urls)
            start = 0
            found = -1
            while True:
                p = content.find(token, start)
                if p == -1:
                    break
                end = p + len(token)
                if not any(p < ue and end > us for us, ue in used):
                    found = p
                    break
                start = p + 1
            if found == -1:
                continue
            used.append((found, found + len(token)))
            metadata["bboxes"].append([float(v) for v in bbox[:4]])
            metadata["pages"].append(page)
            metadata["indexes"].append([found, found + len(token)])
            metadata["types"].append(self.CLOUD_TYPE_MAP.get(str(entry.get("type") or "text"), "text"))

        for idx, item in enumerate(metadata["bboxes"]):
            self.bbox_list.append(
                TextBbox(
                    text=content[metadata["indexes"][idx][0] : metadata["indexes"][idx][1]],
                    type=metadata["types"][idx],
                    part_id=str(idx),
                    bbox=item,
                    page=metadata["pages"][idx],
                )
            )
        metadata.update(self.file_metadata)
        logger.info("mineru_v4 cloud parsed {}: {} chars, {} bboxes", self.file_name, len(content), len(self.bbox_list))
        return [Document(page_content=content, metadata=metadata)]

    def load(self) -> list[Document]:
        if self.is_cloud:
            return self._load_cloud()
        if self.is_upload:
            return self._load_upload()
        ocr_mode = "ocr" if self.force_ocr else self.config.ocr_mode
        archive_path = self.client.parse(self.file_path, self.file_name, ocr_mode, self.tmp_dir)
        middle, image_urls = self._read_zip(archive_path)
        dimensions = self._page_dimensions(middle)
        blocks = []
        last_page = -1
        for page in middle["pages"]:
            if (
                not isinstance(page, dict)
                or not isinstance(page.get("page_idx"), int)
                or not isinstance(page.get("blocks"), list)
            ):
                raise MineruV4Error("MinerU V4 Middle JSON page is invalid")
            page_idx = page["page_idx"]
            if page_idx <= last_page:
                raise MineruV4Error("MinerU V4 Middle JSON pages are out of order")
            last_page = page_idx
            for block in page["blocks"]:
                if not isinstance(block, dict):
                    raise MineruV4Error("MinerU V4 Middle JSON block is invalid")
                text = self._rewrite_image_refs(self._render_block(block), image_urls).strip()
                if not text:
                    continue
                blocks.append(
                    {
                        "text": text,
                        "type": block.get("type", "text"),
                        "page": page_idx,
                        "bbox": self._bbox(block.get("bbox"), dimensions.get(page_idx)),
                    }
                )
        if self.filter_page_header_footer:
            blocks = filter_repeated_header_footer_blocks(blocks)
        if not blocks:
            raise MineruV4Error("MinerU V4 parse result has no readable content")
        content_parts = []
        metadata = {"bboxes": [], "pages": [], "indexes": [], "types": []}
        self.bbox_list = []
        position = 0
        for index, block in enumerate(blocks):
            text = block["text"] + "\n\n"
            content_parts.append(text)
            metadata["bboxes"].append(block["bbox"])
            metadata["pages"].append(block["page"])
            metadata["indexes"].append([position, position + len(text)])
            metadata["types"].append(block["type"])
            position += len(text)
            if block["bbox"]:
                self.bbox_list.append(
                    TextBbox(text=text, type=block["type"], part_id=str(index), bbox=block["bbox"], page=block["page"])
                )
        metadata.update(self.file_metadata)
        logger.info("mineru_v4: parsed {} blocks and {} images", len(blocks), len(image_urls))
        return [Document(page_content="".join(content_parts), metadata=metadata)]
