import copy
from typing import Any, Optional


_EDITOR_FLOW_NODE_TYPE = 'flowNode'
_EDITOR_NOTE_NODE_TYPE = 'noteNode'
_CONDITION_NODE_TYPE = 'condition'
_CONDITION_PARAM_KEY = 'condition'
_EDITOR_CONDITION_RIGHT_VALUE_TYPES = {'input', 'ref'}


def _normalize_editor_condition_cases(condition_cases: Any) -> Any:
    if not isinstance(condition_cases, list):
        return condition_cases

    normalized_cases = []
    for raw_case in condition_cases:
        if not isinstance(raw_case, dict):
            normalized_cases.append(raw_case)
            continue

        case = copy.deepcopy(raw_case)
        conditions = case.get('conditions')
        if isinstance(conditions, list):
            normalized_conditions = []
            for raw_condition in conditions:
                if not isinstance(raw_condition, dict):
                    normalized_conditions.append(raw_condition)
                    continue

                condition = copy.deepcopy(raw_condition)
                condition.setdefault('left_label', '')
                condition.setdefault('right_label', '')
                if condition.get('left_var') is None:
                    condition['left_var'] = ''
                if condition.get('right_value') is None:
                    condition['right_value'] = ''
                if condition.get('comparison_operation') is None:
                    condition['comparison_operation'] = ''

                right_value_type = condition.get('right_value_type')
                if right_value_type not in _EDITOR_CONDITION_RIGHT_VALUE_TYPES:
                    condition['right_value_type'] = 'ref' if right_value_type == 'ref' else 'input'

                normalized_conditions.append(condition)
            case['conditions'] = normalized_conditions

        normalized_cases.append(case)

    return normalized_cases


def normalize_workflow_editor_graph(graph_data: Optional[dict], *, in_place: bool = False) -> Optional[dict]:
    if not isinstance(graph_data, dict):
        return graph_data

    nodes = graph_data.get('nodes')
    if not isinstance(nodes, list):
        return graph_data

    normalized_graph = graph_data if in_place else copy.deepcopy(graph_data)
    for node in normalized_graph.get('nodes', []):
        if not isinstance(node, dict):
            continue

        node_data = node.get('data')
        if not isinstance(node_data, dict):
            continue

        node_type = node_data.get('type')
        if node_type:
            if node.get('type') not in {_EDITOR_FLOW_NODE_TYPE, _EDITOR_NOTE_NODE_TYPE}:
                node['type'] = _EDITOR_NOTE_NODE_TYPE if node_type == 'note' else _EDITOR_FLOW_NODE_TYPE

            if node_type == _CONDITION_NODE_TYPE:
                for group in node_data.get('group_params', []):
                    if not isinstance(group, dict):
                        continue
                    for param in group.get('params', []):
                        if not isinstance(param, dict):
                            continue
                        if param.get('key') == _CONDITION_PARAM_KEY:
                            param['value'] = _normalize_editor_condition_cases(param.get('value') or [])

    return normalized_graph
