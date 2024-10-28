from langchain_core.messages import SystemMessage, HumanMessage

from bisheng.api.services.llm import LLMService
from bisheng.workflow.callback.event import OutputMsgData
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class LLMNode(BaseNode):

    def init_data(self):
        super().init_data()

        # 判断是单次还是批量
        self.tab = self.node_data.tab['value']

        # 是否输出结果给用户
        self.output_user = self.node_params.get("output_user", False)

        # 初始化prompt
        self.system_prompt = PromptTemplateParser(template=self.node_params["system_prompt"])
        self.system_variables = self.system_prompt.extract()
        self.user_prompt = PromptTemplateParser(template=self.node_params["user_prompt"])
        self.user_variables = self.user_prompt.extract()

        # 初始化llm对象
        self.llm = LLMService.get_bisheng_llm(model_id=self.node_params["model_id"],
                                              temperature=self.node_params.get("temperature", 0.3))

    def _run(self):
        result = {}
        if self.tab == "single":
            result["output"] = self._run_once(None)
        else:
            for index, one in enumerate(self.node_params["user_question"]):
                result[self.node_params["output"][index]] = self._run_once(one)

        if self.output_user:
            for key, value in result.items():
                self.callback_manager.on_output_msg(OutputMsgData(node_id=self.id, msg=value))
        return result

    def _run_once(self, input_variable: str = None) -> str:
        # 说明是引用了批处理的变量, 需要把变量的值替换为用户选择的变量
        special_variable = f"{self.id}.batch_variable"
        variable_map = {}
        for one in self.system_variables:
            if input_variable and one == special_variable:
                variable_map[one] = self.graph_state.get_variable_by_str(input_variable)
                continue
            variable_map[one] = self.graph_state.get_variable_by_str(one)
        system = self.system_prompt.format(variable_map)

        variable_map = {}
        for one in self.user_variables:
            if input_variable and one == special_variable:
                variable_map[one] = self.graph_state.get_variable_by_str(input_variable)
                continue
            variable_map[one] = self.graph_state.get_variable_by_str(one)
        user = self.user_prompt.format(variable_map)

        result = self.llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        return result.content
