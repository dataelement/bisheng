import re
from typing import List, Optional, Dict

from loguru import logger
from pydantic import ConfigDict, BaseModel, Field

from bisheng.workflow.common.condition import ComparisonType, LogicType
from bisheng.workflow.nodes.base import BaseNode


class ConditionOne(BaseModel):
    id: str = Field(..., description='Unique id for condition')
    left_var: str = Field(..., description='Left variable')
    comparison_operation: str = Field(..., description='Compare type')
    right_value_type: str = Field(..., description='Right value type')
    right_value: str = Field(..., description='Right value')
    variable_key_value: Dict = Field(default={}, description='variable key value')

    def evaluate(self, node_instance: BaseNode) -> bool:
        left_value = node_instance.get_other_node_variable(self.left_var)
        self.variable_key_value[self.left_var] = left_value
        right_value = self.right_value
        if self.right_value_type == 'ref' and self.right_value:
            right_value = node_instance.get_other_node_variable(self.right_value)
            self.variable_key_value[self.right_value] = right_value
        logger.debug(f'condition evaluate ope: {self.comparison_operation},'
                     f' left value: {left_value}, right value: {right_value}')

        return self.compare_two_value(left_value, right_value)

    def compare_two_value(self, left_value: str, right_value: str) -> bool:
        if self.comparison_operation == ComparisonType.EQUAL:
            return left_value == right_value
        elif self.comparison_operation == ComparisonType.NOT_EQUAL:
            return left_value != right_value
        elif self.comparison_operation == ComparisonType.CONTAINS:
            return left_value.find(right_value) != -1
        elif self.comparison_operation == ComparisonType.NOT_CONTAINS:
            return left_value.find(right_value) == -1
        elif self.comparison_operation == ComparisonType.IS_EMPTY:
            return left_value == '' or left_value is None
        elif self.comparison_operation == ComparisonType.IS_NOT_EMPTY:
            return left_value != '' and left_value is not None
        elif self.comparison_operation == ComparisonType.STARTS_WITH:
            return left_value.startswith(right_value)
        elif self.comparison_operation == ComparisonType.ENDS_WITH:
            return left_value.endswith(right_value)
        elif self.comparison_operation == ComparisonType.GREATER_THAN:
            return float(left_value) > float(right_value)
        elif self.comparison_operation == ComparisonType.GREATER_THAN_OR_EQUAL:
            return float(left_value) >= float(right_value)
        elif self.comparison_operation == ComparisonType.LESS_THAN:
            return float(left_value) < float(right_value)
        elif self.comparison_operation == ComparisonType.LESS_THAN_OR_EQUAL:
            return float(left_value) <= float(right_value)
        elif self.comparison_operation == ComparisonType.REGEX:
            right = re.compile(right_value)
            return right.search(left_value) is not None
        else:
            raise Exception('not support comparison operator: %s' % self.comparison_operation)


class ConditionCases(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(..., description='Unique id for case')
    operator: Optional[str] = Field('and', description='Operator for case')
    conditions: Optional[List[ConditionOne]] = Field(None, description='Conditions for case')
    variable_key_value: Dict = Field(default={}, description='variable key value')

    def evaluate_conditions(self, node_instance: BaseNode) -> bool:
        # Normally onlyelseNoconditions
        if not self.conditions:
            return True

        for condition in self.conditions:
            flag = condition.evaluate(node_instance)
            self.variable_key_value.update(condition.variable_key_value)
            if self.operator == LogicType.AND:
                if not flag:
                    return False
            else:
                if flag:
                    return True
        return True if self.operator == LogicType.AND else False
