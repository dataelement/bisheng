from typing import Any

from bisheng.api.services.llm import LLMService
from bisheng.chat.clients.llm_callback import LLMNodeCallbackHandler
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger


class LLMNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 判断是单次还是批量
        self._tab = self.node_data.tab['value']

        # 是否输出结果给用户
        self._output_user = self.node_params.get('output_user', False)

        # 初始化prompt
        self._system_prompt = PromptTemplateParser(template=self.node_params['system_prompt'])
        self._system_variables = self._system_prompt.extract()
        self._system_prompt_list = []
        self._user_prompt = PromptTemplateParser(template=self.node_params['user_prompt'])
        self._user_variables = self._user_prompt.extract()
        self._user_prompt_list = []

        self._batch_variable_list = []

        # 初始化llm对象
        self._stream = True
        self._llm = LLMService.get_bisheng_llm(model_id=self.node_params['model_id'],
                                               params={'stream': self._stream},
                                               cache=False)

    def _run(self, unique_id: str):
        self._system_prompt_list = []
        self._user_prompt_list = []
        self._batch_variable_list = []
        result = {}
        if self._tab == 'single':
            result['output'] = self._run_once(None, unique_id, 'output')
        else:
            for index, one in enumerate(self.node_params['batch_variable']):
                output_key = self.node_params['output'][index]['key']
                result[output_key] = self._run_once(one, unique_id, output_key)

        if self._output_user:
            # 非stream 模式，处理结果
            for k, v in result.items():
                self.graph_state.save_context(content=v, msg_sender='AI')
        return result

    def parse_log(self, unique_id: str, result: dict) -> Any:
        ret = {
            'system_prompt': self._system_prompt_list,
            'user_prompt': self._user_prompt_list,
            'output': result
        }
        if self._batch_variable_list:
            ret['batch_variable'] = self._batch_variable_list
        return ret

    def _run_once(self,
                  input_variable: str = None,
                  unique_id: str = None,
                  output_key: str = None) -> str:
        # 说明是引用了批处理的变量, 需要把变量的值替换为用户选择的变量
        special_variable = f'{self.id}.batch_variable'
        variable_map = {}
        for one in self._system_variables:
            if input_variable and one == special_variable:
                variable_map[one] = self.graph_state.get_variable_by_str(input_variable)
                self._batch_variable_list.append(variable_map[one])
                continue
            variable_map[one] = self.graph_state.get_variable_by_str(one)
        system = self._system_prompt.format(variable_map)
        self._system_prompt_list.append(system)

        variable_map = {}
        for one in self._user_variables:
            if input_variable and one == special_variable:
                variable_map[one] = self.graph_state.get_variable_by_str(input_variable)
                continue
            variable_map[one] = self.graph_state.get_variable_by_str(one)
        user = self._user_prompt.format(variable_map)
        self._user_prompt_list.append(user)

        logger.debug(
            f'outputkey={output_key} workflow llm node prompt: system: {system}\nuser: {user}')
        llm_callback = LLMNodeCallbackHandler(callback=self.callback_manager,
                                              unique_id=unique_id,
                                              node_id=self.id,
                                              output=self._output_user,
                                              output_key=output_key)
        config = RunnableConfig(callbacks=[llm_callback])

        result = self._llm.invoke([SystemMessage(content=system),
                                   HumanMessage(content=user)],
                                  config=config)

        return result.content
