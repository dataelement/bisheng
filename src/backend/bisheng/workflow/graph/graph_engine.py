from typing import Dict, Annotated, Any

from loguru import logger
from langgraph.checkpoint.memory import MemorySaver
from typing_extensions import TypedDict
from langgraph.constants import END, START
from langgraph.graph import StateGraph

from bisheng.workflow.nodes.node_manage import NodeFactory
from bisheng.workflow.edges.edges import EdgeManage
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData, NodeType
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.nodes.base import BaseNode


class TempState(TypedDict):
    # not use, only for langgraph state graph
    flag: bool


class GraphEngine:
    def __init__(self, user_id: str = None, workflow_data: Dict = None, max_steps: int = 0,
                 callback: BaseCallback = None):
        self.user_id = user_id
        self.workflow_data = workflow_data
        self.max_steps = max_steps
        self.callback = callback

        # node_id: NodeInstance
        self.nodes_map = {}
        self.edges = None

        self.build_edges()
        self.build_nodes()

        # init langgraph state graph
        self.graph_builder = StateGraph(TempState)
        self.graph = None
        self.graph_config = {"configurable": {"thread_id": "1"}}

        self.status = WorkflowStatus.RUNNING.value
        self.reason = ""  # 失败原因

    def build_edges(self):
        # init edges
        self.edges = EdgeManage(self.workflow_data.get('edges', []))

    def add_node_edge(self, node_instance: BaseNode):
        """  把节点的边链接起来  """
        # get target nodes
        target_node_ids = self.edges.get_target_node(node_instance.id)
        source_node_ids = self.edges.get_source_node(node_instance.id)
        # 没有任何链接的节点报错
        if not target_node_ids and not source_node_ids:
            raise Exception(f"node {node_instance.name} must have at least one edge")

        # condition 和 output 节点后面需要接 langgraph的 edge_condition
        if node_instance.type in [NodeType.CONDITION.value, NodeType.OUTPUT.value]:
            self.graph_builder.add_conditional_edges(node_instance.id, node_instance.route_node, {
                node_id: node_id for node_id in target_node_ids
            })
            return

        # 链接到target节点
        for node_id in target_node_ids:
            if node_id not in self.nodes_map:
                raise Exception(f"target node {node_id} not found")
            self.graph_builder.add_edge(node_instance.id, node_id)

    def build_nodes(self):
        nodes = self.workflow_data.get('nodes', [])
        if not nodes:
            raise Exception("workflow must have at least one node")

        start_node = None
        end_node = None
        interrupt_nodes = []
        # init nodes
        for node in nodes:
            node_data = BaseNodeData(**node)
            if not node_data.id:
                raise Exception("node must have attribute id")
            node_instance = NodeFactory.instance_node(node_data=node_data, max_steps=self.max_steps, graph=self)
            self.nodes_map[node_data.id] = node_instance

            # add node into langgraph
            self.graph_builder.add_node(node_instance.id, node_instance.run)

            # find special node
            if node_instance.type == NodeType.START.value:
                start_node = node_instance.id
            elif node_instance.type == NodeType.END.value:
                end_node = node_instance.id
            elif node_instance.type in [NodeType.INPUT.value, NodeType.OUTPUT.value]:
                # 需要中止接收用户输入的节点
                interrupt_nodes.append(node_instance.id)

        if not start_node:
            raise Exception("workflow must have start node")
        self.graph_builder.add_edge(START, start_node)
        if end_node:
            self.graph_builder.add_edge(end_node, END)

        # 将其他节点链接起来
        for node_id, node_instance in self.nodes_map.items():
            self.add_node_edge(node_instance)

        # compile langgraph
        self.graph = self.graph_builder.compile(
            checkpointer=MemorySaver(),
            interrupt_before=interrupt_nodes
        )

    def _run(self, input_data: Any):
        try:
            for _ in self.graph.stream({"flag": True}):
                pass
            self.judge_status()
        except Exception as e:
            logger.exception("graph run error")
            self.status = WorkflowStatus.FAILED.value
            self.reason = str(e)

    def run(self):
        self._run({"flag": True})

    def continue_run(self, data: Any):
        # 接收用户输入后，继续执行
        # TODO 处理对应节点的用户输入
        self._run(None)

    def judge_status(self):
        # 判断状态
        snapshot = self.graph.get_state(self.graph_config)
        next_nodes = snapshot.next
        if len(next_nodes) == 0:
            self.status = WorkflowStatus.SUCCESS.value
            return

        # 判断需要执行的node类型，设置对应的引擎状态
        for node_id in next_nodes:
            pass
