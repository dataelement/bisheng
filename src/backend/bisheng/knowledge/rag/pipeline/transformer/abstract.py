import re
from collections.abc import Sequence
from functools import cached_property
from typing import Any

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng_langchain.rag.extract_info import extract_abstract


def extract_code_blocks(markdown_code_block: str):
    # Define regular expression patterns
    pattern = r"```\w*\s*(.*?)```"

    # Use re.DOTALL letting . Ability to match line breaks
    matches = re.findall(pattern, markdown_code_block, re.DOTALL)

    # Remove whitespace at both ends of each code block
    return [match.strip() for match in matches]


def strip_abstract_labels(text: str) -> str:
    """Strip redundant LLM label prefixes from a generated document abstract.

    Default abstract prompts historically asked for lines like
    ``【文档类型】：…`` / ``【摘要】：…``. The portal UI already shows a
    "文档摘要" heading, so those labels are decorative noise and must be
    removed before storage or backfill.
    """
    if not text:
        return text
    cleaned = re.sub(r"(?m)^【文档类型】[^\n]*(?:\n|$)", "", text)
    cleaned = cleaned.strip()
    # Leading label with optional full-width/half-width colon, then bare label.
    cleaned = re.sub(r"^【摘要】[：:]\s*", "", cleaned)
    cleaned = re.sub(r"^【摘要】\s*", "", cleaned)
    return cleaned.strip()


def parse_document_title(title: str) -> str:
    """
    Parse document titles, removing special characters and extra spaces
    :param title: Original title
    :return: Post-processing title
    """
    # Removing the Thinking Model'sthinkChange Content
    title = re.sub("<think>.*</think>", "", title, flags=re.S).strip()

    # If there is amd The code fast marker removes the code block marker
    if final_title := extract_code_blocks(title):
        title = "\n".join(final_title)
    return title


def clean_document_abstract(abstract: str) -> str:
    """Normalize an LLM abstract before persisting it on KnowledgeFile."""
    return strip_abstract_labels(parse_document_title(abstract))


class AbstractTransformer(BaseDocumentTransformer):
    """
    Use LLM to extract the abstract of the document, and add it to the metadata of the document.
    """

    def __init__(self, invoke_user_id: int, file_metadata: dict = None, knowledge_file=None) -> None:
        self.invoke_user_id = invoke_user_id
        self.file_metadata = file_metadata or {}
        self.max_chunk_content = 7000
        self.knowledge_file = knowledge_file

    @cached_property
    def llm_config(self):
        # Resolve the system-config row against the Knowledge file's owner
        # tenant (F022 INV-T18). KnowledgeFile.tenant_id is the Flow- or
        # KB-owner; falling back to None defers to ContextVar / Root.
        tenant_id = getattr(self.knowledge_file, "tenant_id", None) if self.knowledge_file else None
        return KnowledgeUtils.get_knowledge_abstract_llm(self.invoke_user_id, tenant_id=tenant_id)

    def transform_documents(self, documents: Sequence[Document], **kwargs: Any) -> Sequence[Document]:

        llm, abstract_config = self.llm_config
        if not llm:
            return documents

        text = ""
        for document in documents:
            if len(text) > self.max_chunk_content:
                break
            text += document.page_content
        if text:
            abstract = extract_abstract(
                llm,
                text,
                max_length=self.max_chunk_content,
                abstract_prompt=abstract_config.abstract_prompt,
            )
            clean_abstract = clean_document_abstract(abstract)
            if self.knowledge_file:
                self.knowledge_file.abstract = clean_abstract
            for document in documents:
                document.metadata["abstract"] = clean_abstract
        return documents
