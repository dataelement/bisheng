from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.runnables import RunnableConfig

from bisheng.citation.domain.services.citation_prompt_helper import (
    annotate_rag_documents_with_citations,
    cache_citation_registry_items_sync,
    collect_rag_citation_registry_items,
)
from bisheng.workflow.callback.event import OutputMsgData, StreamMsgOverData
from bisheng.workflow.callback.llm_callback import LLMNodeCallbackHandler
from bisheng.workflow.common.citation_keys import (
    WORKFLOW_CITATION_REGISTRY_ITEMS_KEY,
    WORKFLOW_SOURCE_DOCUMENTS_KEY,
)
from bisheng.workflow.nodes.rag.rag import RagNode


class UserSelectedKnowledgeRagNode(RagNode):
    def _run(self, unique_id: str):
        ret = {}
        self.init_user_info()
        self.apply_runtime_knowledge_selection()
        self._log_source_documents = {}
        self._log_system_prompt = []
        self._log_user_prompt = []
        self._log_reasoning_content = {}

        self.init_qa_prompt()

        self.user_questions = self.init_user_question()
        for index, question in enumerate(self.user_questions):
            output_key = self._output_keys[index]
            if question is None:
                question = ""
            question_answer = self.rag_one_question(question, output_key, unique_id)
            ret[output_key] = question_answer
        return ret

    def rag_one_question(self, question: str, output_key: str, unique_id: str) -> str:
        self.init_multi_retriever()
        self.init_rerank_model()
        source_documents = self.retrieve_question(question)

        qa_chain = create_stuff_documents_chain(llm=self._llm, prompt=self._qa_prompt)
        source_documents_with_citations = annotate_rag_documents_with_citations(source_documents)
        citation_items = collect_rag_citation_registry_items(source_documents_with_citations)
        cache_citation_registry_items_sync(citation_items)
        self.graph_state.set_variable(self.id, WORKFLOW_SOURCE_DOCUMENTS_KEY, source_documents_with_citations)
        self.graph_state.set_variable(self.id, WORKFLOW_CITATION_REGISTRY_ITEMS_KEY, citation_items)
        inputs = {
            "context": source_documents_with_citations,
        }
        if "question" in self._qa_prompt.input_variables:
            inputs["question"] = question

        llm_callback = LLMNodeCallbackHandler(
            callback=self.callback_manager,
            unique_id=unique_id,
            node_id=self.id,
            node_name=self.name,
            output=self._output_user,
            output_key=output_key,
            cancel_llm_end=True,
        )
        result = qa_chain.invoke(inputs, config=RunnableConfig(callbacks=[llm_callback]))

        if self._output_user:
            self.graph_state.save_context(content=result, msg_sender="AI")
            if llm_callback.output_len == 0:
                self.callback_manager.on_output_msg(
                    OutputMsgData(
                        node_id=self.id,
                        name=self.name,
                        msg=result,
                        unique_id=unique_id,
                        output_key=output_key,
                        source_documents=source_documents_with_citations,
                        citation_registry_items=citation_items,
                    )
                )
            else:
                self.callback_manager.on_stream_over(
                    StreamMsgOverData(
                        node_id=self.id,
                        name=self.name,
                        msg=result,
                        reasoning_content=llm_callback.reasoning_content,
                        unique_id=unique_id,
                        source_documents=source_documents_with_citations,
                        citation_registry_items=citation_items,
                        output_key=output_key,
                    )
                )

        self._log_reasoning_content[output_key] = llm_callback.reasoning_content
        self._log_source_documents[output_key] = source_documents_with_citations
        return result
