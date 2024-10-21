from typing import Dict

from bisheng.workflow.graph.graph_engine import GraphEngine


class Workflow:

    def __init__(self, user_id: str = None, graph_config: Dict = None, max_steps: int = 0, timeout: int = 0,
                 callback: callable = None):
        self.user_id = user_id
        self.graph_config = graph_config

        self.graph_engine = GraphEngine(user_id=user_id, graph_config=graph_config)

        self.first_run = True

    def run(self):
        while True:
            if self.first_run:
                self.first_run = False
                self.graph_engine.run()
                continue
            if self.graph_engine.status == 1:
                self.graph_engine.run()
            else:
                break

