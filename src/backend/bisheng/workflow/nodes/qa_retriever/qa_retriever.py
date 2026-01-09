import json
from typing import Any

from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.interface.vector_store.custom import MilvusWithPermissionCheck
from bisheng.user.domain.models.user import UserDao
from bisheng.workflow.nodes.base import BaseNode
from bisheng_langchain.chains.retrieval.retrieval_chain import RetrievalChain


class QARetrieverNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize input
        self._user_question = self.node_params.get('user_question', '')
        self._qa_knowledge_id = self.node_params.get('qa_knowledge_id', [])
        self._score = self.node_params.get('score', 0.6)

        # Inisialisasiretriever, Running Initialization
        self._retriever = None

    def _init_retriever(self):
        if self._retriever:
            return
        # Vector database client initialization, currently usingMilvus, more rational use of more generic factory methods
        params = {}
        params['search_kwargs'] = {'k': 1, 'score_threshold': self._score}
        params['search_type'] = 'similarity_score_threshold'
        params['collection_name'] = self._qa_knowledge_id  # [{"key":"", "label":""}]
        params['user_name'] = UserDao.get_user(self.user_id).user_name
        params['_is_check_auth'] = False
        knowledge_retriever = instantiate_vectorstore(
            node_type='MilvusWithPermissionCheck',
            class_object=MilvusWithPermissionCheck,
            params=params,
        )

        self._retriever = RetrievalChain(retriever=knowledge_retriever)

    def _run(self, unique_id: str):
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
