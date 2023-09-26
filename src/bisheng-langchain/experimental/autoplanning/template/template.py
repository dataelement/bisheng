import os
import sys
import json
import requests

dirname, filename = os.path.split(os.path.abspath(__file__))


def load_template_node(replace=False):
    """
    template node
    """
    save_file = os.path.join(dirname, 'langflow_nodes.json')
    if (not replace) and os.path.exists(save_file):
        with open(save_file, 'r') as f:
            template_nodes = json.load(f)

        return template_nodes
    else:
        # Callable[[str], int], Type[pydantic.main.BaseModel]
        base_elem_type = ['str', 'int', 'bool', 'code', 'float', 'file',
                          "Literal'all'", 'Any', 'Callable[[str], int]',
                          'Type[pydantic.main.BaseModel]']

        req_res = requests.get(url='https://bisheng.dataelem.com/api/v1/all')
        node_info = json.loads(req_res.text)
        template_nodes = {}
        for node_class, node_list in node_info.items():
            template_nodes.update(node_list)

        for node in template_nodes:
            base_classes = template_nodes[node]['base_classes']
            template_dicts = {
                key: value
                for key, value in template_nodes[node]['template'].items()
                if isinstance(value, dict)
            }
            required_inputs = [
                (template_dicts[key]['type'], key)
                for key, value in template_dicts.items()
                if value['required'] and value['type'] not in base_elem_type
            ]
            optional_inputs = [
                (template_dicts[key]['type'], key)
                for key, value in template_dicts.items()
                if not value['required'] and value['type'] not in base_elem_type
            ]

            template_nodes[node]['required_inputs'] = required_inputs
            template_nodes[node]['optional_inputs'] = optional_inputs
            template_nodes[node]['required_candidate_nodes'] = []
            template_nodes[node]['optional_candidate_nodes'] = []

            for required_type, para_name in required_inputs:
                candidate_nodes = []
                for next_node in template_nodes:
                    if next_node != node:
                        base_classes = template_nodes[next_node]['base_classes']
                        valid = any(
                            class_type == required_type
                            for class_type in base_classes
                        )
                        if valid:
                            candidate_nodes.append(next_node)

                template_nodes[node]['required_candidate_nodes'].append(candidate_nodes)

            for optional_type, para_name in optional_inputs:
                candidate_nodes = []
                for next_node in template_nodes:
                    if next_node != node:
                        base_classes = template_nodes[next_node]['base_classes']
                        valid = any(
                            class_type == optional_type
                            for class_type in base_classes
                        )
                        if valid:
                            candidate_nodes.append(next_node)

                template_nodes[node]['optional_candidate_nodes'].append(candidate_nodes)

        with open(save_file, 'w') as f:
            json.dump(template_nodes, f, ensure_ascii=False, indent=2)

        return template_nodes


if __name__ == '__main__':
    load_template_node(replace=True)