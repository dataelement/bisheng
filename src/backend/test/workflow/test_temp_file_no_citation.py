"""F062 T013 — workflow temp knowledge base IS registered as citation_type=temp.

Replaces F054 T004 / AC-16 / AC-17: ephemeral retrieval tools are wrapped
again, but the wrapper records tempsearch_ keys rather than rag keys.
UUID documents still must not be treated as citable RAG.
"""

from langchain_core.documents import Document
from langchain_core.tools import BaseTool

from bisheng.citation.domain.schemas.citation_schema import CitationType
from bisheng.citation.domain.services.citation_prompt_helper import (
    _is_citable_rag_document,
    annotate_rag_documents_with_citations,
    annotate_temp_documents_with_citations,
    collect_temp_citation_registry_items,
)
from bisheng.workflow.nodes.agent.agent import AgentNode, WorkflowCitationToolWrapper


class _StubKnowledgeTool(BaseTool):
    """Stands in for KnowledgeRagTool: the wrapper only looks at the name, the
    presence of ``knowledge_retriever_tool`` and the ephemeral marker. The
    wrapper validates its ``tool`` field as a BaseTool, so this is a real one."""

    name: str = "kb_tool"
    description: str = "desc"
    knowledge_retriever_tool: object = None
    ephemeral_source: bool = False

    def _run(self, *args, **kwargs):  # pragma: no cover - never invoked
        return ""


class _StubWebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = "desc"

    def _run(self, *args, **kwargs):  # pragma: no cover - never invoked
        return ""


def _temp_file_document() -> Document:
    return Document(
        page_content="临时文件正文",
        metadata={
            "document_id": "3f2a1c9e8b7d4f6a",
            "knowledge_id": "wf-01H9Z",
            "document_name": "上传的报价单.pdf",
            "chunk_index": 0,
        },
    )


def test_ephemeral_tool_is_wrapped_for_temp_citations():
    tool = _StubKnowledgeTool(knowledge_retriever_tool=object(), ephemeral_source=True)

    wrapped = AgentNode._wrap_citation_tool(tool)
    assert isinstance(wrapped, WorkflowCitationToolWrapper)
    assert getattr(wrapped.tool, "ephemeral_source", False) is True


def test_regular_knowledge_tool_is_still_wrapped():
    tool = _StubKnowledgeTool(knowledge_retriever_tool=object())

    assert isinstance(AgentNode._wrap_citation_tool(tool), WorkflowCitationToolWrapper)


def test_web_search_tool_is_still_wrapped():
    assert isinstance(AgentNode._wrap_citation_tool(_StubWebSearchTool()), WorkflowCitationToolWrapper)


def test_a_run_mixing_both_wraps_ephemeral_and_real_knowledge():
    tools = [
        _StubKnowledgeTool(knowledge_retriever_tool=object(), ephemeral_source=True),
        _StubKnowledgeTool(name="real_kb", knowledge_retriever_tool=object()),
        _StubWebSearchTool(),
    ]

    wrapped = AgentNode._wrap_citation_tools(tools)

    assert isinstance(wrapped[0], WorkflowCitationToolWrapper)
    assert getattr(wrapped[0].tool, "ephemeral_source", False) is True
    assert isinstance(wrapped[1], WorkflowCitationToolWrapper)
    assert isinstance(wrapped[2], WorkflowCitationToolWrapper)


def test_document_with_non_integer_document_id_is_not_citable_as_rag():
    assert _is_citable_rag_document(_temp_file_document()) is False


def test_document_with_integer_document_id_is_still_citable():
    document = Document(page_content="正文", metadata={"document_id": 7, "knowledge_id": 1})

    assert _is_citable_rag_document(document) is True


def test_annotate_rag_still_gives_temp_file_no_rag_key():
    annotated = annotate_rag_documents_with_citations([_temp_file_document()])

    assert "citation_key" not in annotated[0].metadata or not str(
        annotated[0].metadata.get("citation_key", "")
    ).startswith("knowledgesearch_")


def test_annotate_temp_registers_tempsearch_items():
    annotated = annotate_temp_documents_with_citations([_temp_file_document()])
    items = collect_temp_citation_registry_items(annotated)
    assert annotated[0].metadata["citation_key"].startswith("tempsearch_")
    assert items[0].type == CitationType.TEMP
