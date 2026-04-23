import json
from typing import Any

from bisheng.citation.domain.services.citation_prompt_helper import (
    annotate_web_results_with_citations,
    cache_citation_registry_items_sync,
    collect_web_citation_registry_items,
)
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng.workflow.common.citation_keys import (
    WORKFLOW_CITATION_REGISTRY_ITEMS_KEY,
    WORKFLOW_SOURCE_DOCUMENTS_KEY,
)
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class ToolNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tool_key = self.node_data.tool_key
        self._tool_info = GptsToolsDao.get_tool_by_tool_key(tool_key=self._tool_key)
        if not self._tool_info:
            raise Exception(f"Tools{self._tool_key}Does not exist")

        self._tool = None

    def _is_web_search_tool(self) -> bool:
        return (
            getattr(self._tool, 'name', None) == 'web_search'
            or getattr(self._tool_info, 'tool_name', None) == 'web_search'
        )

    def _annotate_web_search_output(self, output: Any) -> Any:
        if not isinstance(output, str):
            return output
        try:
            results = json.loads(output)
        except json.JSONDecodeError:
            return output
        if not isinstance(results, list):
            return output

        annotated_results = annotate_web_results_with_citations(results)
        citation_items = collect_web_citation_registry_items(annotated_results)
        cache_citation_registry_items_sync(citation_items)
        self.graph_state.set_variable(self.id, WORKFLOW_SOURCE_DOCUMENTS_KEY, None)
        self.graph_state.set_variable(self.id, WORKFLOW_CITATION_REGISTRY_ITEMS_KEY, citation_items)
        return json.dumps(annotated_results, ensure_ascii=False)

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
        if self._is_web_search_tool():
            output = self._annotate_web_search_output(output)
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
