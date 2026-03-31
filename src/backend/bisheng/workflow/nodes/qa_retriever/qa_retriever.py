import json
from typing import Any

from bisheng.core.vectorstore.multi_retriever import MultiRetriever
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.workflow.nodes.base import BaseNode
from bisheng_langchain.chains.retrieval.retrieval_chain import RetrievalChain


class QARetrieverNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize input
        self._user_question = self.node_params.get('user_question', '')
        self._qa_knowledge_id = [one.get("key") for one in self.node_params.get('qa_knowledge_id', []) if one]
        self._score = self.node_params.get('score', 0.6)

        # Inisialisasiretriever, Running Initialization
        self._retriever = None

    def _init_retriever(self):
        if self._retriever:
            return

        knowledge_vector_list = KnowledgeRag.get_multi_knowledge_vectorstore_sync(self.user_id,
                                                                                  knowledge_ids=self._qa_knowledge_id,
                                                                                  check_auth=False,
                                                                                  user_name=self.user_info.user_name,
                                                                                  include_es=False)
        all_milvus = []
        all_milvus_filter = []
        for knowledge_id, vectorstore_info in knowledge_vector_list.items():
            milvus_vectorstore = vectorstore_info.get("milvus")
            all_milvus.append(milvus_vectorstore)
            all_milvus_filter.append({"k": 1, "param": {"ef": 110}, "score_threshold": self._score})

        multi_milvus_retriever = MultiRetriever(
            vectors=all_milvus,
            search_kwargs=all_milvus_filter,
            finally_k=100
        )

        self._retriever = RetrievalChain(retriever=multi_milvus_retriever)

    def _run(self, unique_id: str):
        self.init_user_info()
        self._init_retriever()
        question = self.get_other_node_variable(self._user_question)
        result = self._retriever.invoke({'query': question})
        # qa have a result; turn out to bedocument
        if result['result']:
            # the source documents that store the retrieval results,keyLeft and right plus$As source documentkeyGo to inquiry
            self.graph_state.set_variable(self.id, '$retrieved_result$', result['result'][0])
            result_str = json.loads(result['result'][0].metadata['extra'])['answer']
        else:
            result_str = ''
            self.graph_state.set_variable(self.id, '$retrieved_result$', None)

        return {
            'retrieved_result': result_str
        }

    def parse_log(self, unique_id: str, result: dict) -> Any:
        return [[
            {
                "key": "user_question",
                "value": self.get_other_node_variable(self._user_question),
                "type": "params"
            },
            {
                "key": "retrieved_result",
                "value": result['retrieved_result'],
                "type": "params"
            }
        ]]
