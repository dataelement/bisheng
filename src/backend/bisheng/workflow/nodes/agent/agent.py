from bisheng.api.services.llm import LLMService
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class AgentNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 判断是知识库还是临时文件列表
        self._knowledge_type = self.node_params['retrieved_result']['type']
        self._knowledge_value = [
            one['key'] for one in self.node_params['retrieved_result']['value']
        ]

        self._knowledge_auth = self.node_params['user_auth']
        self._max_chunk_size = self.node_params['max_chunk_size']
        self._sort_chunks = False

        # 解析prompt
        self._system_prompt = PromptTemplateParser(template=self.node_params['system_prompt'])
        self._system_variables = self._system_prompt.extract()
        self._user_prompt = PromptTemplateParser(template=self.node_params['user_prompt'])
        self._user_variables = self._user_prompt.extract()

        # 聊天消息
        self._chat_history_flag = self.node_params['chat_history_flag']['flag']
        self._chat_history_num = self.node_params['chat_history_flag']['number']

        self._llm = LLMService.get_bisheng_llm(model_id=self.node_params['model_id'],
                                               temperature=self.node_params.get(
                                                   'temperature', 0.3))

        # 是否输出结果给用户
        self._output_user = self.node_params.get('output_user', False)

        self._milvus = None
        self._es = None

    def _run(self, unique_id: str):
        # result = {}
        # if self._tab == 'single':
        #     result['output'] = self._run_once(None, unique_id, 'output')
        # else:
        #     for index, one in enumerate(self.node_params['batch_variable']):
        #         output_key = self.node_params['output'][index]['key']
        #         result[output_key] = self._run_once(one, unique_id, output_key)

        # if not self._stream and self._output_user:
        #     # 非stream 模式，处理结果
        #     for k, v in result.items():
        #         self.callback_manager.on_output_msg(
        #             OutputMsgData(
        #                 node_id=self.id,
        #                 msg=v,
        #                 unique_id=unique_id,
        #                 output_key=k,
        #             ))
        # return result
        pass

    def _run_once(self, input_variable: str = None, unique_id: str = None, output_key: str = None):
        """
        input_variable: 输入变量，如果是batch，则需要传入一个list，否则为None
        """
        pass
