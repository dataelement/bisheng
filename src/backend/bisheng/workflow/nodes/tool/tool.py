from typing import Any

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.database.models.gpts_tools import GptsToolsDao
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class ToolNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tool_key = self.node_data.tool_key
        self._tool_info = GptsToolsDao.get_tool_by_tool_key(tool_key=self._tool_key)
        if not self._tool_info:
            raise Exception(f"工具{self._tool_key}不存在")
        if self._tool_info.is_preset:
            self._tool = AssistantAgent.sync_init_preset_tools(tool_list=[self._tool_info], llm=None)[0]
        else:
            self._tool = AssistantAgent.sync_init_personal_tools([self._tool_info])[0]

    def _run(self, unique_id: str):
        tool_input = self.parse_tool_input()
        output = self._tool.run(tool_input=tool_input)
        return {
            "output": output
        }

    def parse_log(self, unique_id: str, result: dict) -> Any:
        return {
            'input': self.parse_tool_input(),
            'output': result
        }

    def parse_tool_input(self) -> dict:
        ret = {}
        for key, val in self.node_params.items():
            if key == "output":
                continue
            ret[key] = self.parse_template_msg(val)
        return ret

    def parse_template_msg(self, msg: str):
        msg_template = PromptTemplateParser(template=msg)
        variables = msg_template.extract()
        if len(variables) > 0:
            var_map = {}
            for one in variables:
                # todo: 引用qa知识库节点时，展示溯源情况
                var_map[one] = self.graph_state.get_variable_by_str(one)
            msg = msg_template.format(var_map)
        return msg
