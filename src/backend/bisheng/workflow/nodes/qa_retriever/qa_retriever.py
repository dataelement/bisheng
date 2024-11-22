from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.interface.vector_store.custom import MilvusWithPermissionCheck
from bisheng.workflow.callback.event import OutputMsgData
from bisheng.workflow.nodes.base import BaseNode
from bisheng_langchain.chains.retrieval.retrieval_chain import RetrievalChain


class QARetrieverNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 判断是单次还是批量
        self._tab = self.node_data.tab['value']

        # 是否输出结果给用户
        self._output_user = self.node_params.get('output_user', False)

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
        knowledge_retriever = instantiate_vectorstore(
            node_type='MilvusWithPermissionCheck',
            class_object=MilvusWithPermissionCheck,
            params=params,
        )

        self._retriever = RetrievalChain(retriever=knowledge_retriever)

    def _run(self, unique_id: str):
        self._init_retriever()
        question = self.graph_state.get_variable_by_str(self._user_question)
        result = self._retriever.invoke({'query': question})
        # qa 结果是document
        if result['result']:
            result_str = result['result'][0].page_content
        else:
            result_str = 'None'
        if self._output_user:
            self.callback_manager.on_output_msg(
                OutputMsgData(node_id=self.id,
                              msg=result_str,
                              unique_id=unique_id,
                              output_key=self._user_question))
        ret = {}
        ret['retrieval_result'] = result_str
        return ret
