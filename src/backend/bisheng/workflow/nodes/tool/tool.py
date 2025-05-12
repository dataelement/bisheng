from typing import Any

from bisheng.api.services.assistant_agent import AssistantAgent
from bisheng.database.constants import ToolPresetType
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
        if self._tool_info.is_preset == ToolPresetType.PRESET.value:
            self._tool = AssistantAgent.sync_init_preset_tools(tool_list=[self._tool_info], llm=None)[0]
        elif self._tool_info.is_preset == ToolPresetType.API.value:
            self._tool = AssistantAgent.sync_init_personal_tools([self._tool_info])[0]
        else:
            self._tool = AssistantAgent.sync_init_mcp_tools([self._tool_info])[0]

    def _run(self, unique_id: str):
        tool_input = self.parse_tool_input()
        output = self._tool.run(tool_input=tool_input)
        return {
            "output": output
        }

    def parse_log(self, unique_id: str, result: dict) -> Any:
        tool_input = self.parse_tool_input()
        ret = [
            {
                "key": k,
                "value": v,
                "type": "params"
            } for k, v in tool_input.items()
        ]
        ret.append({
            "key": "output",
            "value": result.get("output", ''),
            "type": "params"
        })
        return [ret]

    def parse_tool_input(self) -> dict:
        ret = {}
        for key, val in self.node_params.items():
            if key == "output":
                continue
            new_val = self.parse_template_msg(val)
            if new_val == '' or new_val is None:
                continue
            ret[key] = new_val

        return ret

    def parse_template_msg(self, msg: str):
        msg_template = PromptTemplateParser(template=msg)
        variables = msg_template.extract()
        if len(variables) > 0:
            var_map = {}
            for one in variables:
                var_map[one] = self.get_other_node_variable(one)
            msg = msg_template.format(var_map)
        return msg
