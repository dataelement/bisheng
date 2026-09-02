import os
import re
from typing import List

from langchain_core.documents import Document

from bisheng.common.errcode.knowledge import KnowledgeExcelChunkMaxError
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.utils.excel_images import ExcelImage, extract_excel_images
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_excel import convert_file_to_markdown

# Only the OPC package carries drawings. Legacy .xls is an OLE container (and is
# converted to xlsx by the markdown step, but that copy drops the drawings), csv
# has no package at all.
IMAGE_CAPABLE_EXTENSIONS = frozenset({"xlsx"})


def _safe_media_name(name: str) -> str:
    """Keep the staged file name MinIO/URL safe, per the BaseBishengLoader contract."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(name))
    return cleaned or "image"


class ExcelLoader(BaseBishengLoader):
    def __init__(self, header_rows: List[int] = None, data_rows: int = 12, append_header=True,
                 *args, **kwargs):
        super(ExcelLoader, self).__init__(*args, **kwargs)
        self.header_rows = header_rows or [0, 0]
        self.data_rows = data_rows
        self.append_header = append_header
        self.max_chunk_limit = 10000

    def _build_document(self, content: str, chunk_index: int) -> Document:
        metadata = self.file_metadata.copy()
        metadata["chunk_index"] = chunk_index
        metadata["bbox"] = ""
        metadata["page"] = 0
        return Document(page_content=content, metadata=metadata)

    def _read_table_chunk(self, md_dir: str, file_name: str) -> str:
        with open(os.path.join(md_dir, file_name), "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) > self.max_chunk_limit:
            raise KnowledgeExcelChunkMaxError()
        return content

    def _image_chunks(self, sheet_name: str, images: list[ExcelImage]) -> list[str]:
        """Stage one sheet's pictures and return the markdown block(s) that reference them.

        Pictures live outside the cell grid and cannot be folded into the table
        markdown: a sheet holding nothing but a drawing (report exporters do this)
        produces no table markdown at all. Each sheet's pictures therefore become
        their own chunk, captioned with the sheet name so the segment still carries
        some retrievable context.

        Only the bytes are staged on local disk here; ImageUploadTransformer performs
        the MinIO upload, per the image contract in BaseBishengLoader.
        """
        image_dir = self.ensure_local_image_dir()
        heading = f"## {sheet_name}"
        refs: list[str] = []
        for image in images:
            filename = _safe_media_name(image.media_name)
            # The same media part may be anchored on several sheets; stage once.
            staged_path = os.path.join(image_dir, filename)
            if not os.path.exists(staged_path):
                with open(staged_path, "wb") as f:
                    f.write(image.content)
            refs.append(f"![{filename}]({self.build_image_url(filename)})")

        chunks: list[str] = []
        block = heading
        for ref in refs:
            candidate = f"{block}\n\n{ref}"
            # Keep the heading on every chunk when a sheet has enough pictures to
            # overflow one segment.
            if len(candidate) > self.max_chunk_limit and block != heading:
                chunks.append(block)
                block = f"{heading}\n\n{ref}"
            else:
                block = candidate
        chunks.append(block)
        return chunks

    def load(self) -> List[Document]:
        md_file_path = os.path.join(self.tmp_dir, "chunk_md")

        sheet_order = convert_file_to_markdown(input_file_path=self.file_path,
                                               num_header_rows=self.header_rows,
                                               rows_per_markdown=self.data_rows,
                                               base_output_dir=md_file_path,
                                               append_header=self.append_header) or []

        files = sorted([f for f in os.listdir(md_file_path) if f.endswith(".md")])

        images_by_sheet: dict[str, list[ExcelImage]] = {}
        if self.file_extension.lower().lstrip(".") in IMAGE_CAPABLE_EXTENSIONS:
            for image in extract_excel_images(self.file_path):
                images_by_sheet.setdefault(image.sheet_name, []).append(image)

        # Chunks follow the workbook: sheet by sheet, each sheet's table chunks first
        # and its pictures right after. A picture-only sheet has no table chunks and
        # still yields its picture chunk in its own place, so a report whose first
        # sheet is a screenshot and whose second sheet is the data comes out as
        # [picture, table], not [table, picture].
        contents: list[str] = []
        consumed: set[str] = set()
        for sheet_name, sheet_prefix in sheet_order:
            if sheet_prefix is not None:
                prefix = f"{sheet_prefix:02d}"
                for file_name in files:
                    if file_name.startswith(prefix) and file_name not in consumed:
                        contents.append(self._read_table_chunk(md_file_path, file_name))
                        consumed.add(file_name)
            sheet_images = images_by_sheet.pop(sheet_name, None)
            if sheet_images:
                contents.extend(self._image_chunks(sheet_name, sheet_images))

        # Anything the sheet map did not account for (csv has no sheets; a picture on
        # a sheet the converter never saw) keeps the old file order at the end.
        for file_name in files:
            if file_name not in consumed:
                contents.append(self._read_table_chunk(md_file_path, file_name))
        for sheet_name, sheet_images in images_by_sheet.items():
            contents.extend(self._image_chunks(sheet_name, sheet_images))

        return [self._build_document(content, index) for index, content in enumerate(contents)]
