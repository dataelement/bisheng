import re
from collections.abc import Sequence
from functools import cached_property
from typing import Any

from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils

# Default prompts for document-abstract extraction. The system prompt is used
# only when the knowledge base does not configure a custom abstract_prompt; the
# human prompt always carries the document content.
DEFAULT_ABSTRACT_SYSTEM_PROMPT = """# role
你是一名经验丰富的“文档摘要专家”，擅长针对不同类型的文档（例如：书籍、论文、标书、研究报告、规章制度、合同协议、会议纪要、产品手册、运维手册、需求说明书等）进行精准识别，并根据文档类型灵活调整摘要风格，例如：
- 报告类文档需强调研究发现或核心观点；
- 制度类文档需突出制度目的及适用范围；
- 合同类文档需明确合同主体及关键条款；
- 会议纪要需聚焦会议议题与决策结果；
- 产品说明需提炼产品功能与使用场景。

# task
接下来你将收到一篇文档的主要内容，请你：
1. 判断并简要说明该文档属于上述哪种类型；
2. 使用2～3句话概括文档的核心内容和关键结论，强调信息的准确性、完整性与清晰度。

# result example
【文档类型】：会议纪要
【摘要】：本文档为公司季度业务会议纪要，会议围绕本季度销售目标的达成情况展开，最终决定下一季度加强市场推广投入，并设立专门团队负责新产品上市工作，以改善销售表现。"""

DEFAULT_ABSTRACT_HUMAN_PROMPT = """
文档内容如下：
{context}

文档摘要：
"""


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

    def _extract_abstract(self, llm, text: str, abstract_prompt: str | None) -> str:
        """Invoke the LLM to summarize the document content.

        Re-implemented locally with LangChain's message API (replacing the
        deprecated bisheng_langchain LLMChain.run pipeline). The configured
        abstract_prompt overrides the default system prompt when present; the
        document content is passed as a plain message value, so curly braces in
        the text need no escaping.
        """
        system_prompt = abstract_prompt or DEFAULT_ABSTRACT_SYSTEM_PROMPT
        human_prompt = DEFAULT_ABSTRACT_HUMAN_PROMPT.format(context=text[: self.max_chunk_content])
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]
        response = llm.invoke(messages)
        return response.content if hasattr(response, "content") else str(response)

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
            # Abstract generation is a best-effort enhancement, not part of the
            # core parsing flow. If the LLM call fails for any reason (timeout,
            # content-audit rejection, invalid model config, ...), leave the
            # abstract empty so the file still parses successfully instead of
            # being marked FAILED. The exception type is intentionally broad:
            # any summary failure is non-critical, and the failure is logged.
            try:
                abstract = self._extract_abstract(llm, text, abstract_config.abstract_prompt)
                clean_abstract = parse_document_title(abstract)
            except Exception:
                logger.opt(exception=True).warning(
                    "abstract generation failed for file_id={}; leaving abstract empty",
                    getattr(self.knowledge_file, "id", None),
                )
                clean_abstract = ""
            if self.knowledge_file:
                self.knowledge_file.abstract = clean_abstract
            for document in documents:
                document.metadata["abstract"] = clean_abstract
        return documents
