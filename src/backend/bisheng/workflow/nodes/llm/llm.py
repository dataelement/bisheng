from loguru import logger
from langchain_core.messages import SystemMessage, HumanMessage

from bisheng.api.services.llm import LLMService
from bisheng.workflow.callback.event import OutputMsgData
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class LLMNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 判断是单次还是批量
        self._tab = self.node_data.tab['value']

        # 是否输出结果给用户
        self._output_user = self.node_params.get("output_user", False)

        # 初始化prompt
        self._system_prompt = PromptTemplateParser(template=self.node_params["system_prompt"])
        self._system_variables = self._system_prompt.extract()
        self._user_prompt = PromptTemplateParser(template=self.node_params["user_prompt"])
        self._user_variables = self._user_prompt.extract()

        # 初始化llm对象
        self._llm = LLMService.get_bisheng_llm(model_id=self.node_params["model_id"])

    def _run(self):
        result = {}
        if self._tab == "single":
            result["output"] = self._run_once(None)
        else:
            for index, one in enumerate(self.node_params["user_question"]):
                output_key = self.node_params["output"][index]["key"]
                result[output_key] = self._run_once(one)

        if self._output_user:
            for key, value in result.items():
                self.callback_manager.on_output_msg(OutputMsgData(node_id=self.id, msg=value))
        return result

    def _run_once(self, input_variable: str = None) -> str:
        # 说明是引用了批处理的变量, 需要把变量的值替换为用户选择的变量
        special_variable = f"{self.id}.batch_variable"
        variable_map = {}
        for one in self._system_variables:
            if input_variable and one == special_variable:
                variable_map[one] = self.graph_state.get_variable_by_str(input_variable)
                continue
            variable_map[one] = self.graph_state.get_variable_by_str(one)
        system = self._system_prompt.format(variable_map)

        variable_map = {}
        for one in self._user_variables:
            if input_variable and one == special_variable:
                variable_map[one] = self.graph_state.get_variable_by_str(input_variable)
                continue
            variable_map[one] = self.graph_state.get_variable_by_str(one)
        user = self._user_prompt.format(variable_map)

        logger.debug(f"workflow llm node prompt: system: {system}\nuser: {user}")

        result = self._llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        return result.content
