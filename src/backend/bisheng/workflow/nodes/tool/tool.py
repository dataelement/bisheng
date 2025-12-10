from typing import Any

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class ToolNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tool_key = self.node_data.tool_key
        self._tool_info = GptsToolsDao.get_tool_by_tool_key(tool_key=self._tool_key)
        if not self._tool_info:
            raise Exception(f"工具{self._tool_key}不存在")

        self._tool = None

    def _init_tool(self):
        if self._tool:
            return
        self._tool = ToolExecutor.init_by_tool_id_sync(tool_id=self._tool_info.id, app_id=self.workflow_id,
                                                       app_name=self.workflow_name,
                                                       app_type=ApplicationTypeEnum.WORKFLOW, user_id=self.user_id)

    def _run(self, unique_id: str):
        self._init_tool()
        tool_input = self.parse_tool_input()
        output = self._tool.invoke(input=tool_input)
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
