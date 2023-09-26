import json


template_json = '/Users/gulixin/Desktop/数据/bisheng/⭐研报分析-14825-87904.json'
langflow_node_json = '/Users/gulixin/Desktop/数据/bisheng/langflow_nodes.json'

with open(template_json, 'r') as f:
    data = json.load(f)
    data = data['data']
    nodes = data['nodes']
    edges = data['edges']

langflow_nodes = {}
for node in nodes:
    info = node['data']['node']
    langflow_nodes[node['data']['type']] = info
    langflow_nodes[node['data']['type']]['width'] = node['width']
    langflow_nodes[node['data']['type']]['height'] = node['height']

with open(langflow_node_json, 'w') as f:
    json.dump(langflow_nodes, f, ensure_ascii=False, indent=2)