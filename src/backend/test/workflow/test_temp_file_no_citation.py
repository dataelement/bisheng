"""F054 T004 — workflow temp files must stop producing citation badges.

A file uploaded into a workflow input node lands in a scratch vector
collection whose ``document_id`` is a random UUID and whose ``knowledge_id``
is the workflow id — neither is an integer, so the RAG citation payload can
never resolve one to a real knowledge file. The badge therefore rendered, hovered
with a name, and opened onto nothing. That is worse than no badge at all, so the
source registration is cut off at two levels (design §3 decision 6):

- A: the temp-file retrieval tool is marked ephemeral at creation, and the agent
     node's citation wrapper skips it.
- B: a guard in the registry refuses to treat a document as citable when it
     carries a document id that is not an integer — defence in depth for any
     other path that might feed such documents in later.

RED until T007/T008 land.
"""

from langchain_core.documents import Document
from langchain_core.tools import BaseTool

from bisheng.citation.domain.services.citation_prompt_helper import (
    _is_citable_rag_document,
    annotate_rag_documents_with_citations,
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
    """Shaped like what the input node writes: UUID document id, workflow id as
    the knowledge id."""
    return Document(
        page_content="临时文件正文",
        metadata={
            "document_id": "3f2a1c9e8b7d4f6a",
            "knowledge_id": "wf-01H9Z",
            "document_name": "上传的报价单.pdf",
            "chunk_index": 0,
        },
    )


# --------------------------------------------------------------------------- #
# Layer A — the agent node does not wrap an ephemeral retrieval tool
# --------------------------------------------------------------------------- #


def test_ephemeral_tool_is_not_wrapped_for_citations():
    tool = _StubKnowledgeTool(knowledge_retriever_tool=object(), ephemeral_source=True)

    assert AgentNode._wrap_citation_tool(tool) is tool


def test_regular_knowledge_tool_is_still_wrapped():
    tool = _StubKnowledgeTool(knowledge_retriever_tool=object())

    assert isinstance(AgentNode._wrap_citation_tool(tool), WorkflowCitationToolWrapper)


def test_web_search_tool_is_still_wrapped():
    assert isinstance(AgentNode._wrap_citation_tool(_StubWebSearchTool()), WorkflowCitationToolWrapper)


def test_a_run_mixing_both_keeps_citations_only_for_the_real_knowledge_base():
    tools = [
        _StubKnowledgeTool(knowledge_retriever_tool=object(), ephemeral_source=True),
        _StubKnowledgeTool(name="real_kb", knowledge_retriever_tool=object()),
        _StubWebSearchTool(),
    ]

    wrapped = AgentNode._wrap_citation_tools(tools)

    assert not isinstance(wrapped[0], WorkflowCitationToolWrapper)
    assert isinstance(wrapped[1], WorkflowCitationToolWrapper)
    assert isinstance(wrapped[2], WorkflowCitationToolWrapper)


# --------------------------------------------------------------------------- #
# Layer B — the registry guard rejects non-integer document ids
# --------------------------------------------------------------------------- #


def test_document_with_non_integer_document_id_is_not_citable():
    assert _is_citable_rag_document(_temp_file_document()) is False


def test_document_with_integer_document_id_is_still_citable():
    document = Document(page_content="正文", metadata={"document_id": 7, "knowledge_id": 1})

    assert _is_citable_rag_document(document) is True


def test_document_with_no_document_id_keeps_its_previous_treatment():
    """Only a *present but unparseable* id is rejected. Documents that simply
    carry no id fall back to metadata grouping exactly as before, so the four
    live entry points are untouched (AC-17)."""
    document = Document(page_content="正文", metadata={"document_name": "a.pdf", "knowledge_id": 1})

    assert _is_citable_rag_document(document) is True


def test_annotate_gives_a_temp_file_document_no_citation_key():
    annotated = annotate_rag_documents_with_citations([_temp_file_document()])

    assert "citation_key" not in annotated[0].metadata
    assert "citation_key:" not in annotated[0].page_content
