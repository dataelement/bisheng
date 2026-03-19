import re
from functools import cached_property
from typing import Sequence, Any, Dict

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng_langchain.rag.extract_info import extract_title


def extract_code_blocks(markdown_code_block: str):
    # Define regular expression patterns
    pattern = r"```\w*\s*(.*?)```"

    # Use re.DOTALL letting . Ability to match line breaks
    matches = re.findall(pattern, markdown_code_block, re.DOTALL)

    # Remove whitespace at both ends of each code block
    return [match.strip() for match in matches]


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


class AbstractTransformer(BaseDocumentTransformer):
    """
    Use LLM to extract the abstract of the document, and add it to the metadata of the document.
    """

    def __init__(self, invoke_user_id: int, preview_cache_key: str = None, file_metadata: Dict = None,
                 knowledge_file=None) -> None:
        self.invoke_user_id = invoke_user_id
        self.preview_cache_key = preview_cache_key
        self.file_metadata = file_metadata or {}
        self.max_chunk_content = 7000
        self.knowledge_file = knowledge_file

    @cached_property
    def llm_config(self):
        return KnowledgeUtils.get_knowledge_abstract_llm(self.invoke_user_id)

    def transform_documents(
            self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:

        llm, abstract_config = self.llm_config
        if not llm:
            return documents

        text = ""
        for document in documents:
            if len(text) > self.max_chunk_content:
                break
            text += document.page_content
        if text:
            abstract = extract_title(llm, text, max_length=self.max_chunk_content,
                                     abstract_prompt=abstract_config.abstract_prompt)
            clean_abstract = parse_document_title(abstract)
            if self.knowledge_file:
                self.knowledge_file.abstract = clean_abstract
            for document in documents:
                document.metadata['abstract'] = clean_abstract
        return documents
