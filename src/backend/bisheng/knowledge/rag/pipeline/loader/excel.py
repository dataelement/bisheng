import os
import re

from langchain_core.documents import Document

from bisheng.common.constants.knowledge import KNOWLEDGE_MAX_CHUNK_CHARS
from bisheng.common.errcode.knowledge import KnowledgeExcelChunkMaxError
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.loader.utils.excel_images import (
    ExcelImage,
    extract_excel_images,
)
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_excel import (
    ExcelRowTooLongError,
    convert_file_to_markdown,
)
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter

# Mirrors FileProcessBase.check_separator_rule so callers that do not carry a
# split rule (e.g. the xinchuang delegate) still get the platform defaults.
DEFAULT_SEPARATOR = ["\n\n", "\n", "。", "\\."]
DEFAULT_SEPARATOR_RULE = ["after", "after", "after", "after"]
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 100

# Only the OPC package carries drawings. Legacy .xls is an OLE container, and
# .et is handled by the xinchuang delegate loader before it reaches markdown.
IMAGE_CAPABLE_EXTENSIONS = frozenset({"xlsx"})


def _safe_media_name(name: str) -> str:
    """Keep the staged file name MinIO/URL safe, per the BaseBishengLoader contract."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(name))
    return cleaned or "image"


class ExcelLoader(BaseBishengLoader):
    def __init__(
        self,
        header_rows: list[int] | None = None,
        data_rows: int = 12,
        append_header=True,
        separator: list[str] | None = None,
        separator_rule: list[str] | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        max_chunk_limit: int = KNOWLEDGE_MAX_CHUNK_CHARS,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.header_rows = header_rows or [0, 0]
        self.data_rows = data_rows
        self.append_header = append_header
        self.max_chunk_limit = max_chunk_limit
        self.separator = separator or DEFAULT_SEPARATOR
        self.separator_rule = separator_rule or DEFAULT_SEPARATOR_RULE
        self.chunk_size = chunk_size or DEFAULT_CHUNK_SIZE
        self.chunk_overlap = DEFAULT_CHUNK_OVERLAP if chunk_overlap is None else chunk_overlap

    def _split_long_row_text(self, text: str, budget: int) -> list[str]:
        """Split the plain-text form of a row that cannot fit in one chunk.

        Such a row means a single cell holds more text than a whole segment may
        carry; reducing the row count can no longer help, so the row stops being
        rendered as a table and is split like ordinary text instead.

        ``budget`` is what the chunk has left after the header prefix, and it
        caps chunk_size -- the admin UI lets users raise chunk_size above the
        hard limit. An empty separator is appended as a last resort so text
        holding none of the configured separators still gets broken up.
        """
        chunk_size = max(1, min(self.chunk_size, budget))
        separators = [*self.separator, ""]
        # ElemCharacterTextSplitter indexes separator_rule by separator position,
        # so the two lists must line up exactly.
        rules = list(self.separator_rule)[: len(self.separator)]
        rules += ["after"] * (len(self.separator) - len(rules))
        separator_rule = [*rules, "after"]
        splitter = ElemCharacterTextSplitter(
            separators=separators,
            separator_rule=separator_rule,
            chunk_size=chunk_size,
            chunk_overlap=min(self.chunk_overlap, chunk_size - 1),
            is_separator_regex=True,
        )
        return splitter.split_text(text)

    def _build_document(self, content: str, chunk_index: int) -> Document:
        metadata = self.file_metadata.copy()
        metadata["chunk_index"] = chunk_index
        metadata["bbox"] = ""
        metadata["page"] = 0
        return Document(page_content=content, metadata=metadata)

    def _emit_image_documents(self, images: list[ExcelImage], start_chunk_index: int) -> list[Document]:
        """Stage embedded pictures and turn them into their own markdown chunks.

        Pictures live outside the cell grid and cannot be folded into the table
        markdown: a sheet holding nothing but a drawing (report exporters do
        this) produces no markdown at all, and the renderer's sheet numbering
        skips empty sheets, so there is no chunk to attach them to. Each sheet's
        pictures therefore become their own chunk, captioned with the sheet name
        so the segment still carries some retrievable context.

        Only the bytes are staged on local disk here; ImageUploadTransformer
        performs the MinIO upload, per the image contract in BaseBishengLoader.
        """
        if not images:
            return []

        image_dir = self.ensure_local_image_dir()
        by_sheet: dict[str, list[ExcelImage]] = {}
        for image in images:
            by_sheet.setdefault(image.sheet_name, []).append(image)

        staged: set[str] = set()
        documents: list[Document] = []
        chunk_index = start_chunk_index

        for sheet_name, sheet_images in by_sheet.items():
            heading = f"## {sheet_name}"
            refs: list[str] = []
            for image in sheet_images:
                filename = _safe_media_name(image.media_name)
                # The same media part may be anchored on several sheets; stage once.
                if filename not in staged:
                    with open(os.path.join(image_dir, filename), "wb") as f:
                        f.write(image.content)
                    staged.add(filename)
                refs.append(f"![{filename}]({self.build_image_url(filename)})")

            block = heading
            for ref in refs:
                candidate = f"{block}\n\n{ref}"
                # Keep the heading on every chunk when a sheet has enough pictures
                # to overflow one segment.
                if len(candidate) > self.max_chunk_limit and block != heading:
                    documents.append(self._build_document(block, chunk_index))
                    chunk_index += 1
                    block = f"{heading}\n\n{ref}"
                else:
                    block = candidate
            documents.append(self._build_document(block, chunk_index))
            chunk_index += 1

        return documents

    def load(self) -> list[Document]:
        if os.path.exists(self.file_path):
            self.preview_file_path = self.file_path

        md_file_path = os.path.join(self.tmp_dir, "chunk_md")

        try:
            convert_file_to_markdown(
                input_file_path=self.file_path,
                num_header_rows=self.header_rows,
                rows_per_markdown=self.data_rows,
                base_output_dir=md_file_path,
                append_header=self.append_header,
                max_chars=self.max_chunk_limit,
                long_row_splitter=self._split_long_row_text,
            )
        except ExcelRowTooLongError as e:
            # Only reachable if no splitter was supplied, which cannot happen here.
            raise KnowledgeExcelChunkMaxError() from e

        files = sorted([f for f in os.listdir(md_file_path) if f.endswith(".md")])

        # A file corresponds to only one complete Document Objects, texts It is only after cuttingchunkContents
        documents = []

        for chunk_index, file_name in enumerate(files):
            full_file_name = f"{md_file_path}/{file_name}"
            with open(full_file_name, encoding="utf-8") as f:
                content = f.read()
                # Defensive: the char budget above should have prevented this. If it
                # ever fires, the budget math has drifted from the renderer.
                if len(content) > self.max_chunk_limit:
                    raise KnowledgeExcelChunkMaxError()
                documents.append(self._build_document(content, chunk_index))

        if self.file_extension.lower().lstrip(".") in IMAGE_CAPABLE_EXTENSIONS:
            documents.extend(self._emit_image_documents(extract_excel_images(self.file_path), len(documents)))

        return documents
