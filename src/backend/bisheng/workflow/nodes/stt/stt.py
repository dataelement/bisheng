from typing import Any

from bisheng.api.services.llm import LLMService
from bisheng.chat.clients.llm_callback import LLMNodeCallbackHandler
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from loguru import logger


class STTNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 判断是单次还是批量
        # self._tab = self.node_data.tab['value']
        print("STTNode __init__",args,kwargs)
        self._tab = "batch"
        self._output_user = self.node_params.get('output_user', False)
        self._batch_variable_list = {}

        # 初始化llm对象
        self._stream = True
        self._stt = LLMService.get_bisheng_stt(model_id=self.node_params['model_id'])

    def _run(self, unique_id: str):
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
        ret = []
        if self._batch_variable_list:
            ret.insert(0, {"key": "batch_variable", "value": self._batch_variable_list, "type": "params"})
        for k, v in result.items():
            ret.append({"key": f'{self.id}.{k}', "value": v, "type": "variable"})
        return [ret]

    def _run_once(self,
                  input_variable: str = None,
                  unique_id: str = None,
                  output_key: str = None) -> str:
        input_file = self.graph_state.get_variable_by_str(input_variable)
        if type(input_file) == list:
            result = []
            for u in input_file:
                text = self._stt.transcribe(u)
                result.append(text)
        else:
            result = self._stt.transcribe(input_file)
        return result
