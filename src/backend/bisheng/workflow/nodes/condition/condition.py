from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.condition.conidition_case import ConditionCases
from loguru import logger


class ConditionNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._next_node_id = None
        self._condition_cases = [ConditionCases(**one) for one in self.node_params['condition']]

    def _run(self, unique_id: str):
        for one in self._condition_cases:
            if one.evaluate_conditions(self.graph_state):
                self._next_node_id = self.get_next_node_id(one.id)
                logger.info(f'Condition node {self.id} pass condition {self._next_node_id}')
                break

        # 保底逻辑，使用默认的路由
        if self._next_node_id is None:
            self._next_node_id = self.get_next_node_id('right_handle')

    def route_node(self, state: dict) -> str:
        return self._next_node_id
