from typing import Dict

from bisheng.workflow.graph.graph_engine import GraphEngine


class Workflow:

    def __init__(self, user_id: str = None, graph_config: Dict = None, max_steps: int = 0, timeout: int = 0,
                 callback: callable = None):
        self.user_id = user_id
        self.graph_config = graph_config

        self.graph_engine = GraphEngine(user_id=user_id, graph_config=graph_config)
