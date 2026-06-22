import json
from collections.abc import Sequence
from typing import Any

from langchain_core.documents import BaseDocumentTransformer, Document
from loguru import logger

from bisheng.common.errcode.knowledge import KnowledgeFileChunkMaxError
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter


class SplitterTransformer(BaseDocumentTransformer):
    """
    Splits text documents using ElemCharacterTextSplitter.
    """

    def __init__(
        self,
        separator: list[str] | None = None,
        separator_rule: list[str] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
        **kwargs,
    ) -> None:
        self.text_splitter = ElemCharacterTextSplitter(
            separators=separator,
            separator_rule=separator_rule,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            is_separator_regex=True,
            **kwargs,
        )
        self.max_chunk_limit = 10000

    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:
        documents = self.text_splitter.split_documents(documents)
        for index, one in enumerate(documents):
            one.metadata["chunk_index"] = index
            one.metadata["bbox"] = json.dumps({"chunk_bboxes": one.metadata.get("chunk_bboxes", "")})
            one.metadata["page"] = (
                one.metadata["chunk_bboxes"][0].get("page")
                if one.metadata.get("chunk_bboxes", None)
                else one.metadata.get("page", 0)
            )
            chunk_length = len(one.page_content)
            if chunk_length > self.max_chunk_limit:
                source = (
                    one.metadata.get("source") or one.metadata.get("file_name") or one.metadata.get("file_path", "")
                )
                preview = one.page_content[:200].replace("\n", "\\n")
                logger.warning(
                    f"Knowledge chunk length exceeds limit: source={source}, chunk_index={index}, "
                    f"length={chunk_length}, limit={self.max_chunk_limit}, preview={preview}"
                )
                raise KnowledgeFileChunkMaxError()
        return documents
