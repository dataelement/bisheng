from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.condition.conidition_case import ConditionCases


class ConditionNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._next_node_id = None
        self._condition_cases = [
            ConditionCases(**one) for one in self.node_params['condition']['cases']
        ]

    def _run(self, unique_id: str):
        for one in self._condition_cases:
            if one.evaluate_conditions(self.graph_state):
                self._next_node_id = self.get_next_node_id(one.id)
                break

        # 保底逻辑，按道理不会运行
        if self._next_node_id is None:
            self._next_node_id = self.target_edges[0].target

    def route_node(self, state: dict) -> str:
        return self._next_node_id
