import copy
from typing import Any, Optional


_EDITOR_FLOW_NODE_TYPE = 'flowNode'
_EDITOR_NOTE_NODE_TYPE = 'noteNode'
_CONDITION_NODE_TYPE = 'condition'
_CONDITION_PARAM_KEY = 'condition'
_EDITOR_CONDITION_RIGHT_VALUE_TYPES = {'input', 'ref'}


def _iter_variable_refs(node_data: dict):
    node_id = str(node_data.get('id', '') or '')
    if not node_id:
        return

    node_name = str(node_data.get('name', '') or node_id)
    for group in node_data.get('group_params', []) or []:
        if not isinstance(group, dict):
            continue
        for param in group.get('params', []) or []:
            if not isinstance(param, dict):
                continue

            param_key = param.get('key')
            if not isinstance(param_key, str) or not param_key:
                continue

            param_global = param.get('global')
            param_value = param.get('value')
            param_label = str(param.get('label') or param_key)

            if isinstance(param_global, str) and param_global.startswith('code:') and isinstance(param_value, list):
                for item in param_value:
                    if not isinstance(item, dict):
                        continue
                    item_key = item.get('value') or item.get('key')
                    if not item_key:
                        continue
                    item_label = str(item.get('label') or item.get('key') or item_key)
                    yield f'{node_id}.{item_key}', f'{node_name}/{item_label}'
                continue

            if param_global in {'key', 'self'}:
                yield f'{node_id}.{param_key}', f'{node_name}/{param_label}'
                continue

            if param_global == 'item:form_input' and isinstance(param_value, list):
                for item in param_value:
                    if not isinstance(item, dict):
                        continue
                    base_label = str(item.get('label') or item.get('key') or '')
                    for sub_key_name in ('key', 'file_content', 'file_path', 'image_file'):
                        sub_key = item.get(sub_key_name)
                        if not sub_key:
                            continue
                        suffix = base_label or str(sub_key)
                        yield f'{node_id}.{sub_key}', f'{node_name}/{suffix}'


def _build_variable_label_map(nodes: list[dict]) -> dict[str, str]:
    variable_labels: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_data = node.get('data')
        if not isinstance(node_data, dict):
            continue
        for ref, label in _iter_variable_refs(node_data):
            variable_labels[ref] = label
    return variable_labels


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
    variable_labels = _build_variable_label_map(normalized_graph.get('nodes', []))
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
                            for case in param['value'] or []:
                                if not isinstance(case, dict):
                                    continue
                                for condition in case.get('conditions') or []:
                                    if not isinstance(condition, dict):
                                        continue
                                    if not condition.get('left_label'):
                                        condition['left_label'] = variable_labels.get(condition.get('left_var') or '', '')
                                    if (
                                        condition.get('right_value_type') == 'ref'
                                        and not condition.get('right_label')
                                    ):
                                        condition['right_label'] = variable_labels.get(
                                            condition.get('right_value') or '',
                                            '',
                                        )

    return normalized_graph
