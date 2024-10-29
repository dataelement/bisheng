from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.condition.conidition_case import ConditionCases


class ConditionNode(BaseNode):

    def init_data(self):
        super().init_data()
        self.next_node_id = None
        self.condition_cases = [ConditionCases(**one) for one in self.node_params["condition"]["cases"]]

    def _run(self):
        for one in self.condition_cases:
            if one.evaluate_conditions(self.graph_state):
                self.next_node_id = self.get_next_node_id(one.id)
                break

    def route_node(self, state: dict) -> str:
        return self.next_node_id
