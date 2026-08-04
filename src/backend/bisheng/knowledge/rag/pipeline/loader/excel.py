import os

from langchain_core.documents import Document

from bisheng.common.constants.knowledge import KNOWLEDGE_MAX_CHUNK_CHARS
from bisheng.common.errcode.knowledge import KnowledgeExcelChunkMaxError
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
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
                one_metadata = self.file_metadata.copy()
                one_metadata["chunk_index"] = chunk_index
                one_metadata["bbox"] = ""
                one_metadata["page"] = 0
                # Defensive: the char budget above should have prevented this. If it
                # ever fires, the budget math has drifted from the renderer.
                if len(content) > self.max_chunk_limit:
                    raise KnowledgeExcelChunkMaxError()
                documents.append(Document(page_content=content, metadata=one_metadata))

        return documents
