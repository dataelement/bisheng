import json
from typing import Any

import loguru

from bisheng.database.models.user import UserDao
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.interface.vector_store.custom import MilvusWithPermissionCheck
from bisheng.workflow.nodes.base import BaseNode
from bisheng_langchain.chains.retrieval.retrieval_chain import RetrievalChain


class QARetrieverNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 初始化输入
        self._user_question = self.node_params.get('user_question', '')
        self._qa_knowledge_id = self.node_params.get('qa_knowledge_id', [])
        self._score = self.node_params.get('score', 0.6)

        # 初始化retriever，运行中初始化
        self._retriever = None

    def _init_retriever(self):
        if self._retriever:
            return
        # 向量数据库客户端初始化，当前使用Milvus，更合理的使用更通用的工厂方法
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

        loguru.logger.debug(f'jjxx qa_result:{result}')

        # qa 结果是document
        if result['result']:
            # 存检索结果的源文档，key左右加上$作为来源文档key去查询
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
