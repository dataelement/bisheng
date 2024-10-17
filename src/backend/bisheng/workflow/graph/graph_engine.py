from typing import Dict, cast

from bisheng.workflow.nodes.node_manage import NodeFactory


class GraphEngine:
    def __init__(self, user_id: str = None, graph_config: Dict = None):
        self.user_id = user_id
        self.graph_config = graph_config

        # node_id: NodeInstance
        self.nodes_map = {}
        self.edges = graph_config.get('edges', [])

        self.build_nodes()

    def build_nodes(self):
        nodes = self.graph_config.get('nodes', [])
        if not nodes:
            raise Exception("workflow must have at least one node")

        # init nodes
        for node in nodes:
            if not node["id"]:
                raise Exception("node must have attribute id")
            node_instance = NodeFactory.instance_node(**node)
            self.nodes_map[node['id']] = node
