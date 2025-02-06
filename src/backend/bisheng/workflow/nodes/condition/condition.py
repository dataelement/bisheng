from typing import Any

from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.condition.conidition_case import ConditionCases
from loguru import logger


class ConditionNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._next_node_id = None
        self._condition_cases = [ConditionCases(**one) for one in self.node_params['condition']]

        # 存储计算过的变量和值
        self._variable_key_value = {}

    def _run(self, unique_id: str):
        self._variable_key_value = {}
        next_node_ids = None
        for one in self._condition_cases:
            flag = one.evaluate_conditions(self)
            self._variable_key_value.update(one.variable_key_value)
            if flag:
                next_node_ids = self.get_next_node_id(one.id)
                logger.info(f'Condition node {self.id} pass condition {next_node_ids}')
                break

        # 保底逻辑，使用默认的路由
        if next_node_ids is None:
            self._next_node_id = self.get_next_node_id('right_handle')
        else:
            self._next_node_id = next_node_ids

    def parse_log(self, unique_id: str, result: dict) -> Any:
        return [[
            {
                "key": k,
                "value": v,
                "type": "variable"
            } for k, v in self._variable_key_value.items()
        ]]

    def route_node(self, state: dict) -> str:
        return self._next_node_id
