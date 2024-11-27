import re
from typing import List, Optional, Dict

from bisheng.workflow.graph.graph_state import GraphState
from pydantic import BaseModel, Field


class ConditionOne(BaseModel):
    id: str = Field(..., description='Unique id for condition')
    left_var: str = Field(..., description='Left variable')
    comparison_operation: str = Field(..., description='Compare type')
    right_value_type: str = Field(..., description='Right value type')
    right_value: str = Field(..., description='Right value')
    variable_key_value: Dict = Field(default={}, description='variable key value')

    def evaluate(self, graph_state: GraphState) -> bool:
        left_value = graph_state.get_variable_by_str(self.left_var)
        right_value = self.right_value
        if self.right_value_type == 'ref' and self.right_value:
            right_value = graph_state.get_variable_by_str(self.right_value)
            self.variable_key_value[self.right_value] = right_value

        return self.compare_two_value(left_value, right_value)

    def compare_two_value(self, left_value: str, right_value: str) -> bool:
        if self.comparison_operation == 'equals':
            return left_value == right_value
        elif self.comparison_operation == 'not_equals':
            return left_value != right_value
        elif self.comparison_operation == 'contains':
            return left_value.find(right_value) != -1
        elif self.comparison_operation == 'not_contains':
            return left_value.find(right_value) == -1
        elif self.comparison_operation == 'is_empty':
            return left_value == ''
        elif self.comparison_operation == 'is_not_empty':
            return left_value != ''
        elif self.comparison_operation == 'starts_with':
            return left_value.startswith(right_value)
        elif self.comparison_operation == 'ends_with':
            return left_value.endswith(right_value)
        elif self.comparison_operation == 'greater_than':
            return float(left_value) > float(right_value)
        elif self.comparison_operation == 'greater_than_or_equal':
            return float(left_value) >= float(right_value)
        elif self.comparison_operation == 'less_than':
            return float(left_value) < float(right_value)
        elif self.comparison_operation == 'less_than_or_equal':
            return float(left_value) <= float(right_value)
        elif self.comparison_operation == 'regex':
            right = re.compile(right_value)
            return right.search(left_value) is not None
        else:
            raise Exception('not support comparison operator: %s' % self.comparison_operation)


class ConditionCases(BaseModel):

    class Config:
        arbitrary_types_allowed = True

    id: str = Field(..., description='Unique id for case')
    operator: Optional[str] = Field('and', description='Operator for case')
    conditions: Optional[List[ConditionOne]] = Field(None, description='Conditions for case')
    variable_key_value: Dict = Field(default={}, description='variable key value')

    def evaluate_conditions(self, graph_state: GraphState) -> bool:
        # 正常来讲只有else没有conditions
        if not self.conditions:
            return True

        for condition in self.conditions:
            if self.operator == 'and':
                if not condition.evaluate(graph_state):
                    return False
            else:
                if condition.evaluate(graph_state):
                    return True
            self.variable_key_value.update(condition.variable_key_value)
        return True if self.operator == 'and' else False
