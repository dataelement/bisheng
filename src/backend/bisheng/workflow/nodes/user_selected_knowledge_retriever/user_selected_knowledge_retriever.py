from typing import Any

from bisheng.citation.domain.services.citation_prompt_helper import (
    annotate_rag_documents_with_citations,
    cache_citation_registry_items_sync,
    collect_rag_citation_registry_items,
)
from bisheng.workflow.common.citation_keys import (
    WORKFLOW_CITATION_REGISTRY_ITEMS_KEY,
    WORKFLOW_SOURCE_DOCUMENTS_KEY,
)
from bisheng.workflow.nodes.knowledge_retriever.knowledge_retriever import KnowledgeRetriever


class UserSelectedKnowledgeRetriever(KnowledgeRetriever):
    def _run(self, unique_id: str):
        self.user_questions = self.init_user_question()
        self.init_user_info()
        self.apply_runtime_knowledge_selection()
        self.init_multi_retriever()
        ret = {}
        for index, question in enumerate(self.user_questions):
            output_key = self._output_keys[index]
            if question is None:
                question = ""
            self.init_rerank_model()
            question_answer = self.retrieve_question(question)
            question_answer = annotate_rag_documents_with_citations(question_answer)
            citation_items = collect_rag_citation_registry_items(question_answer)
            cache_citation_registry_items_sync(citation_items)
            self.graph_state.set_variable(self.id, WORKFLOW_SOURCE_DOCUMENTS_KEY, question_answer)
            self.graph_state.set_variable(self.id, WORKFLOW_CITATION_REGISTRY_ITEMS_KEY, citation_items)
            ret[output_key] = [
                {
                    "text": one.page_content,
                    "citation_key": one.metadata.get("citation_key"),
                    "metadata": {
                        "chunk_index": one.metadata.get("chunk_index"),
                        "knowledge_id": one.metadata.get("knowledge_id"),
                        "document_id": one.metadata.get("document_id"),
                        "document_name": one.metadata.get("document_name"),
                        "upload_time": one.metadata.get("upload_time"),
                        "update_time": one.metadata.get("update_time"),
                        "uploader": one.metadata.get("uploader"),
                        "updater": one.metadata.get("updater"),
                        "user_metadata": one.metadata.get("user_metadata"),
                    },
                }
                for one in question_answer
            ]
        return ret

    def parse_log(self, unique_id: str, result: dict) -> Any:
        return super().parse_log(unique_id, result)
