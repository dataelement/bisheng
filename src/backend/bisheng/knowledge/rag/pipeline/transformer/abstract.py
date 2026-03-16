from functools import cached_property
from typing import Sequence, Any

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng_langchain.rag.extract_info import extract_title


class AbstractTransformer(BaseDocumentTransformer):
    """
    Use LLM to extract the abstract of the document, and add it to the metadata of the document.
    """

    def __init__(self, invoke_user_id: int) -> None:
        self.invoke_user_id = invoke_user_id
        self.max_chunk_content = 7000

    @cached_property
    def llm_config(self):
        return KnowledgeUtils.get_knowledge_abstract_llm(self.invoke_user_id)

    def transform_documents(
            self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        llm, abstract_config = self.llm_config
        text = ""
        for document in documents:
            text += document.page_content
            if len(text) > self.max_chunk_content:
                break
        if text:
            abstract = extract_title(llm, text, max_length=self.max_chunk_content,
                                     abstract_prompt=abstract_config.abstract_prompt)
            for document in documents:
                document.metadata['abstract'] = abstract
        return documents
