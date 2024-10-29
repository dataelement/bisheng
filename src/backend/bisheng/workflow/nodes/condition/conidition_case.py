import re
from typing import Optional, List

from pydantic import BaseModel, Field

from bisheng.workflow.graph.graph_state import GraphState


class ConditionOne(BaseModel):
    id: str = Field(..., description="Unique id for condition")
    left_var: str = Field(..., description="Left variable")
    comparison_operator: str = Field(..., description="Compare type")
    right_value_type: str = Field(..., description="Right value type")
    right_value: str = Field(..., description="Right value")

    def evaluate(self, graph_state: GraphState) -> bool:
        left_value = graph_state.get_variable_by_str(self.left_var)
        right_value = self.right_value
        if self.right_value_type == "ref" and self.right_value:
            right_value = graph_state.get_variable_by_str(self.right_value)

        return self.compare_two_value(left_value, right_value)

    def compare_two_value(self, left_value: str, right_value: str) -> bool:
        if self.comparison_operator == "=":
            return left_value == right_value
        elif self.comparison_operator == "!=":
            return left_value != right_value
        elif self.comparison_operator == "contains":
            return left_value.find(right_value) != -1
        elif self.comparison_operator == "not contains":
            return left_value.find(right_value) == -1
        elif self.comparison_operator == "empty":
            return left_value == ""
        elif self.comparison_operator == "not empty":
            return left_value != ""
        elif self.comparison_operator == "startswith":
            return right_value.startswith(left_value)
        elif self.comparison_operator == "endswith":
            return right_value.endswith(left_value)
        elif self.comparison_operator == ">":
            return float(left_value) > float(right_value)
        elif self.comparison_operator == ">=":
            return float(left_value) >= float(right_value)
        elif self.comparison_operator == "<":
            return float(left_value) < float(right_value)
        elif self.comparison_operator == "<=":
            return float(left_value) <= float(right_value)
        elif self.comparison_operator == "regex":
            right = re.compile(right_value)
            return right.search(left_value) is not None
        else:
            raise Exception("not support comparison operator: %s" % self.comparison_operator)


class ConditionCases(BaseModel):
    class Config:
        arbitrary_types_allowed = True

    id: str = Field(..., description="Unique id for case")
    operator: Optional[str] = Field("and", description="Operator for case")
    conditions: Optional[List[ConditionOne]] = Field(None, description="Conditions for case")

    def evaluate_conditions(self, graph_state: GraphState) -> bool:
        # 正常来讲只有else没有conditions
        if not self.conditions:
            return True

        for condition in self.conditions:
            if self.operator == "and":
                if not condition.evaluate(graph_state):
                    return False
            else:
                if condition.evaluate(graph_state):
                    return True
        return True if self.operator == "and" else False
