from typing import Any

from bisheng.api.services.llm import LLMService
from bisheng.workflow.callback.llm_callback import LLMNodeCallbackHandler
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

        self._image_prompt = self.node_params.get('image_prompt', [])

        # 初始化prompt
        self._system_prompt = PromptTemplateParser(template=self.node_params['system_prompt'])
        self._system_variables = self._system_prompt.extract()
        self._user_prompt = PromptTemplateParser(template=self.node_params['user_prompt'])
        self._user_variables = self._user_prompt.extract()

        # 存储日志所需数据
        self._system_prompt_list = []
        self._user_prompt_list = []
        self._batch_variable_list = []
        self._log_reasoning_content = []

        self._enable_web_search = self.node_params.get('enable_web_search', False)

        # 初始化llm对象
        self._stream = True
        self._llm = LLMService.get_bisheng_llm(model_id=self.node_params['model_id'],
                                               enable_web_search=self._enable_web_search,
                                               temperature=self.node_params.get(
                                                   'temperature', 0.3),
                                               params={'stream': self._stream},
                                               cache=False)


    def _run(self, unique_id: str):
        self._system_prompt_list = []
        self._user_prompt_list = []
        self._batch_variable_list = []
        self._log_reasoning_content = []

        result = {}
        if self._tab == 'single':
            result['output'], reasoning_content = self._run_once(None, unique_id, 'output')
            self._log_reasoning_content.append(reasoning_content)
        else:
            for index, one in enumerate(self.node_params['batch_variable']):
                self._batch_variable_list.append(self.get_other_node_variable(one))
                output_key = self.node_params['output'][index]['key']
                result[output_key], reasoning_content = self._run_once(one, unique_id, output_key)
                self._log_reasoning_content.append(reasoning_content)

        if self._output_user:
            for k, v in result.items():
                self.graph_state.save_context(content=v, msg_sender='AI')
        return result

    def parse_log(self, unique_id: str, result: dict) -> Any:
        ret = []
        index = 0
        for k, v in result.items():
            one_ret = [
                {"key": "system_prompt", "value": self._system_prompt_list[index], "type": "params"},
                {"key": "user_prompt", "value": self._user_prompt_list[index], "type": "params"},
            ]
            if self._log_reasoning_content[index]:
                one_ret.append({"key": "思考内容", "value": self._log_reasoning_content[index], "type": "params"})
            one_ret.append({"key": f'{self.id}.{k}', "value": v, "type": "variable"})
            if self._batch_variable_list:
                one_ret.insert(0, {"key": f"{self.id}.batch_variable", "value": self._batch_variable_list[index], "type": "variable"})
            index += 1
            ret.append(one_ret)
        return ret

    def _run_once(self,
                  input_variable: str = None,
                  unique_id: str = None,
                  output_key: str = None) -> (str, str):
        # 说明是引用了批处理的变量, 需要把变量的值替换为用户选择的变量
        special_variable = f'{self.id}.batch_variable'
        variable_map = {}
        for one in self._system_variables:
            if input_variable and one == special_variable:
                variable_map[one] = self.get_other_node_variable(input_variable)
                continue
            variable_map[one] = self.get_other_node_variable(one)
        system = self._system_prompt.format(variable_map)
        self._system_prompt_list.append(system)

        variable_map = {}
        for one in self._user_variables:
            if input_variable and one == special_variable:
                variable_map[one] = self.get_other_node_variable(input_variable)
                continue
            variable_map[one] = self.get_other_node_variable(one)
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
        inputs = []
        if system:
            inputs.append(SystemMessage(content=system))

        human_message = HumanMessage(content=[{
            'type': 'text',
            'text': user
        }])
        human_message = self.contact_file_into_prompt(human_message, self._image_prompt)
        inputs.append(human_message)

        logger.debug(f'llm invoke chat_history: {inputs} {self._image_prompt}')

        result = self._llm.invoke(inputs, config=config)

        return result.content, llm_callback.reasoning_content
