import copy
import random
import string
import time
from collections import defaultdict
from typing import Dict, Generator, List, Type, Union
from prompts.task_definitions import TASK2COMPONENTS
from template.template import load_template_node
from bisheng.interface.listing import ALL_TYPES_DICT


def parse_node(node_name, node_info):
    template_dicts = {
        key: value
        for key, value in node_info['template'].items()
        if isinstance(value, dict)
    }

    node_base_classes = node_info['base_classes']
    node_vertex_type = (
        node_name
        if 'Tool' not in node_base_classes or node_info['template']['_type'].islower()
        else node_info['template']['_type']
    )
    node_base_type = None
    for base_type, value in ALL_TYPES_DICT.items():
        if node_vertex_type in value:
            node_base_type = base_type
            break

    node_base_info = {
        'params': template_dicts,
        'required_inputs': node_info['required_inputs'],
        'required_candidate_nodes': node_info['required_candidate_nodes'],
        'optional_inputs': node_info['optional_inputs'],
        'optional_candidate_nodes': node_info['optional_candidate_nodes'],
        'vertex_type': node_vertex_type,
        'base_type': node_base_type
    }
    return node_base_info


class GraphGenerator:
    """A class generate a graph of nodes and edges."""

    def __init__(self, tasks, task_tweaks, skill='', description=''):
        self.tasks = tasks
        self.task_tweaks = task_tweaks
        self.task_descriptions = [task['description'] for task in tasks]
        self.template_nodes = load_template_node()
        self.node_id_set = set()
        self.skill = skill
        self.description = description

    def build_graph(self):
        """
        build langflow graph
        """
        # phase1: generate each task nodes and edges
        task_graphs = []
        for task_index, task in enumerate(self.tasks):
            task_graph = self.build_nodes_edges(task)
            task_graph = self.instantiate_nodes_edges(task_graph)
            task_graphs.append(task_graph)

        # phase2: multi combine method
        if len(task_graphs) > 1:
            # only support zero shot agent
            whole_graph = self.combine_task_graphs(task_graphs)
        else:
            whole_graph = task_graphs[0]

        # phase3: format langflow json
        langfow_json = self.format_graph(whole_graph)
        return langfow_json

    def build_nodes_edges(self, task):
        """

        """
        step = task['step']
        task_type = task['task_type']
        master_node = task['master_node']
        components = copy.deepcopy(TASK2COMPONENTS[task_type])
        if master_node not in components:
            raise ValueError(f'master node {master_node} is not in components. Please check.')
        # master_node为根节点
        graph_nodes, graph_edges, graph_params, graph_nodes_info = self.generate(master_node, components, 1)
        # print('graph_nodes:', graph_nodes)
        # print('graph_edges:', graph_edges)
        # print('graph_params:', graph_params)
        # print('graph_nodes_info:', graph_nodes_info)
        return graph_nodes, graph_edges, graph_params, graph_nodes_info

    def generate(self, cur_node, components, layer):
        """
        generate nodes and edges
        """
        node_info = self.template_nodes[cur_node]
        required_inputs = node_info['required_inputs']
        required_candidate_nodes = node_info['required_candidate_nodes']
        optional_inputs = node_info['optional_inputs']
        optional_candidate_nodes = node_info['optional_candidate_nodes']

        node_index = components.index(cur_node)
        components.pop(node_index)

        find_required_nodes = []
        find_required_inputs = []
        for index, candidate_nodes in enumerate(required_candidate_nodes):
            find_node = False
            # 从后往前遍历，找到合适的组件
            for component_index in range(len(components)-1, -1, -1):
                if components[component_index] in candidate_nodes:
                    find_required_nodes.append(components[component_index])
                    find_required_inputs.append(required_inputs[index])
                    find_node = True
                    break

            if not find_node:
                raise ValueError(
                    f'Not find {cur_node} required input node which type is {required_inputs[index]} in components.')

        find_optional_nodes = []
        find_optional_inputs = []
        for index, candidate_nodes in enumerate(optional_candidate_nodes):
            for component_index in range(len(components)-1, -1, -1):
                if components[component_index] in candidate_nodes:
                    find_optional_nodes.append(components[component_index])
                    find_optional_inputs.append(optional_inputs[index])
                    break

        # print(f'cur node: {cur_node}')
        # print(f'find_required_nodes: {find_required_nodes}')
        # print(f'find_required_inputs: {find_required_inputs}')
        # print(f'find_optional_nodes: {find_optional_nodes}')
        # print(f'find_optional_inputs: {find_optional_inputs}')
        # print(f'remain components: {components}')

        graph_nodes = []
        graph_edges = []
        graph_params = []
        graph_node_info = []
        if find_required_nodes + find_optional_nodes:
            path_num = 0
            for node in (find_required_nodes + find_optional_nodes):
                res_nodes, res_edges, res_params, res_nodes_info = self.generate(node, components, layer+1)
                graph_nodes.extend(res_nodes)
                graph_edges.extend(res_edges)
                graph_params.extend(res_params)
                graph_node_info.extend(res_nodes_info)
                path_num += res_nodes_info[-1]['path_num']
        else:
            path_num = 1

        graph_nodes.append(cur_node)
        graph_edges.extend(
            [(pre_node, cur_node) for pre_node in (find_required_nodes + find_optional_nodes)])
        graph_params.extend(find_required_inputs + find_optional_inputs)
        graph_node_info.append({'cur_node': cur_node, 'path_num': path_num,
            'layer': layer, 'pre_nodes': find_required_nodes + find_optional_nodes,
            'param_info': node_info})

        return graph_nodes, graph_edges, graph_params, graph_node_info

    def instantiate_nodes_edges(self, graph):
        """
        instantiate each node with id
        """
        graph_nodes, graph_edges, graph_params, graph_nodes_info = graph
        node_instantiate_objs = {}
        for index, node in enumerate(graph_nodes):
            while True:
                node_id = ''.join([random.choice(string.ascii_letters)] +
                                  [random.choice(string.ascii_letters + string.digits) for _ in range(4)])
                if node_id not in self.node_id_set:
                    self.node_id_set.add(node_id)
                    break
            node_instantiate = node + '-' + node_id
            node_instantiate_objs[node] = node_instantiate
            graph_nodes[index] = node_instantiate

        for index, node_info in enumerate(graph_nodes_info):
            node_info['cur_node'] = node_instantiate_objs[node_info['cur_node']]
            node_info['pre_nodes'] = [node_instantiate_objs[elem] for elem in node_info['pre_nodes']]

        new_graph_edges = []
        for edge in graph_edges:
            new_graph_edges.append((node_instantiate_objs[edge[0]], node_instantiate_objs[edge[1]]))

        return graph_nodes, new_graph_edges, graph_params, graph_nodes_info

    def combine_task_graphs(self, task_graphs):
        """
        Use Tools and ZeroShotAgent to combine task graphs
        """
        whole_graph_nodes = []
        whole_graph_edges = []
        whole_graph_params = []
        whole_graph_nodes_info = []
        tool_instantiate_list = []
        total_path_num = 0
        for task_graph in task_graphs:
            tool_type = 'Tool'
            while True:
                tool_id = ''.join([random.choice(string.ascii_letters)] +
                                  [random.choice(string.ascii_letters + string.digits) for _ in range(4)])
                if tool_id not in self.node_id_set:
                    self.node_id_set.add(tool_id)
                    break
            tool_instantiate = tool_type + '-' + tool_id
            tool_instantiate_list.append(tool_instantiate)

            graph_nodes, graph_edges, graph_params, graph_nodes_info = task_graph
            whole_graph_nodes.extend(graph_nodes)
            whole_graph_nodes.append(tool_instantiate)

            whole_graph_edges.extend(graph_edges)
            whole_graph_edges.append((graph_nodes[-1], tool_instantiate))

            whole_graph_params.extend(graph_params)
            whole_graph_params.append(('function', 'func'))

            for node_info in graph_nodes_info:
                # Tool and ZeroShotAgent
                node_info['layer'] = node_info['layer'] + 2
            whole_graph_nodes_info.extend(graph_nodes_info)
            whole_graph_nodes_info.append({'cur_node': tool_instantiate,
                'path_num': graph_nodes_info[-1]['path_num'],
                'layer': 2, 'pre_nodes': [graph_nodes[-1]],
                'param_info': self.template_nodes[tool_type]})

            total_path_num += graph_nodes_info[-1]['path_num']

        while True:
            agent_id = ''.join([random.choice(string.ascii_letters)] +
                              [random.choice(string.ascii_letters + string.digits) for _ in range(4)])
            if agent_id not in self.node_id_set:
                self.node_id_set.add(agent_id)
                break

        agent_type = 'ZeroShotAgent'
        zero_shot_agent_instantiate = agent_type + '-' + agent_id
        whole_graph_nodes.append(zero_shot_agent_instantiate)
        whole_graph_edges.extend(
            (tool_instantiate, zero_shot_agent_instantiate) for tool_instantiate in tool_instantiate_list)
        whole_graph_params.extend(('BaseTool', 'tools') for _ in tool_instantiate_list)
        whole_graph_nodes_info.append({'cur_node': zero_shot_agent_instantiate, 'path_num': total_path_num,
                'layer': 1, 'pre_nodes': tool_instantiate_list,
                'param_info': self.template_nodes[agent_type]})

        return whole_graph_nodes, whole_graph_edges, whole_graph_params, whole_graph_nodes_info

    def format_graph(self, graph, mean_width=384, mean_height=400, x_interval=50, y_interval=50):
        """
        format nodes and edges to langflow json
        """
        graph_nodes, graph_edges, graph_params, graph_nodes_info = graph

        res_json = dict()
        res_json['edges'] = []
        for index, edge in enumerate(graph_edges):
            edge_json = {}
            edge_json['style'] = {"stroke": "#555"}
            edge_json['source'] = edge[0]
            edge_json['target'] = edge[1]
            edge_json['animated'] = False
            edge_json['selected'] = False
            edge_json['className'] = ''

            base_classes = self.template_nodes[edge[0][:-6]]['base_classes']
            edge_json['sourceHandle'] = edge[0][:-6] + '|' + edge[0] + '|' + '|'.join(base_classes)
            edge_json['targetHandle'] = graph_params[index][0] + "|" + graph_params[index][1] + "|" + edge[1]
            edge_json['id'] = "reactflow__edge-" + edge[0] + edge_json['sourceHandle'] + '-' + edge[1] + edge_json['targetHandle']
            res_json['edges'].append(edge_json)

        graph_nodes_info = sorted(graph_nodes_info, key=lambda elem: elem['layer'])
        # print(graph_nodes_info)

        # decide height
        total_path_num = graph_nodes_info[0]['path_num']
        # decide width
        total_layer_num = graph_nodes_info[-1]['layer']

        total_width = mean_width * total_layer_num + x_interval * (total_layer_num - 1)
        total_height = mean_height * total_path_num + y_interval * (total_path_num - 1)
        start_x = list(range(50, total_width, total_width//total_layer_num))

        node_info_dict = dict()
        for node_info in graph_nodes_info:
            node_info_dict[node_info['cur_node']] = {'path_num': node_info['path_num'],
                                                     'layer': node_info['layer'],
                                                     'param_info': node_info['param_info']}

        # root node: layer = 1
        node_info_dict[graph_nodes_info[0]['cur_node']]['height_range'] = (0, 1)
        for node_info in graph_nodes_info:
            node_height_range = node_info_dict[node_info['cur_node']]['height_range']
            pre_nodes = node_info['pre_nodes']
            delta = (node_height_range[1] - node_height_range[0]) / node_info['path_num']
            left = node_height_range[0]
            for pre_node in pre_nodes:
                right = delta * node_info_dict[pre_node]['path_num'] + left
                node_info_dict[pre_node]['height_range'] = (left, right)
                left = right

            # node position x
            node_info_dict[node_info['cur_node']]['x'] = start_x[total_layer_num - int(node_info_dict[node_info['cur_node']]['layer'])]
            # node position y
            node_info_dict[node_info['cur_node']]['y'] = int((node_height_range[0] + node_height_range[1])/2 * total_height)

        res_json['nodes'] = []
        for node_name, node_info in node_info_dict.items():
            position_x = node_info['x']
            position_y = node_info['y']
            node_type = node_name[:-6]
            langflow_node = {}
            langflow_node['width'] = mean_width
            langflow_node['height'] = mean_height
            langflow_node['id'] = node_name
            langflow_node['data'] = {'id': node_name, 'node': node_info['param_info'],
                                     'type': node_type, 'value': None}
            langflow_node['type'] = 'genericNode'
            langflow_node['position'] = {'x': position_x, 'y': position_y}
            langflow_node['selected'] = False
            langflow_node['positionAbsolute'] = {'x': position_x, 'y': position_y}
            langflow_node['dragging'] = False
            res_json['nodes'].append(langflow_node)

        res_json['viewport'] = {'x': 51.129, 'y': 46.625, 'zoom': 0.425}

        langflow_json = dict()
        langflow_json['name'] = self.skill
        langflow_json['user_id'] = 1
        langflow_json['description'] = self.description
        langflow_json['data'] = res_json
        langflow_json['logo'] = None
        langflow_json['status'] = 1
        langflow_json['create_time'] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        langflow_json['update_time'] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

        flow_id = '-'.join([''.join([random.choice(string.ascii_letters + string.digits) for _ in range(8)]),
                            ''.join([random.choice(string.ascii_letters + string.digits) for _ in range(4)]),
                            ''.join([random.choice(string.ascii_letters + string.digits) for _ in range(4)]),
                            ''.join([random.choice(string.ascii_letters + string.digits) for _ in range(4)]),
                            ''.join([random.choice(string.ascii_letters + string.digits) for _ in range(12)])
                           ])
        langflow_json['id'] = flow_id
        langflow_json['user_name'] = None

        return langflow_json

