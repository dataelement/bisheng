import operator
from typing import Annotated, Any, Dict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from loguru import logger
from typing_extensions import TypedDict

from bisheng.utils.exceptions import IgnoreException
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import UserInputData
from bisheng.workflow.common.node import BaseNodeData, NodeType
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.edges.edges import EdgeManage
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.node_manage import NodeFactory
from bisheng.workflow.nodes.output.output_fake import OutputFakeNode


class TempState(TypedDict):
    # not use, only for langgraph state graph
    flag: Annotated[bool, operator.add]


class GraphEngine:

    def __init__(self,
                 user_id: str = None,
                 workflow_id: str = None,
                 workflow_data: Dict = None,
                 async_mode: bool = False,
                 max_steps: int = 0,
                 callback: BaseCallback = None):
        self.user_id = user_id
        self.workflow_id = workflow_id
        self.workflow_data = workflow_data
        self.max_steps = max_steps
        self.async_mode = async_mode
        # 回调
        self.callback = callback

        # node_id: NodeInstance
        self.nodes_map = {}
        # record how many nodes fan in this node
        self.nodes_fan_in = {}  # node_id: [node_ids]
        # record how many nodes next to this node
        self.nodes_next_nodes = {}  # node_id: {node_ids}

        self.edges = None
        self.graph_state = GraphState()

        # init langgraph state graph
        self.graph_builder = StateGraph(TempState)
        self.graph = None
        self.graph_config = {'configurable': {'thread_id': '1'}, 'recursion_limit': 50}

        self.status = WorkflowStatus.RUNNING.value
        self.reason = ''  # 失败原因

        self.build_edges()
        self.build_nodes()

    def build_edges(self):
        # init edges
        self.edges = EdgeManage(self.workflow_data.get('edges', []))

    def add_node_edge(self, node_instance: BaseNode):
        """  把节点的边链接起来  """
        if node_instance.type == NodeType.END.value or node_instance.type == NodeType.FAKE_OUTPUT.value:
            return
        # get target nodes
        target_node_ids = self.edges.get_target_node(node_instance.id)
        source_node_ids = self.edges.get_source_node(node_instance.id)
        # 没有任何链接的节点报错
        if not target_node_ids and not source_node_ids:
            raise Exception(
                f'node {node_instance.name} {node_instance.id} must have at least one edge')

        # output 节点后跟一个fake 节点用来处理中断
        if node_instance.type == NodeType.OUTPUT.value:
            fake_node = self.nodes_map[f'{node_instance.id}_fake']
            if self.async_mode:
                self.graph_builder.add_node(fake_node.id, fake_node.arun)
            else:
                self.graph_builder.add_node(fake_node.id, fake_node.run)
            self.graph_builder.add_edge(node_instance.id, fake_node.id)
            self.graph_builder.add_conditional_edges(
                fake_node.id, node_instance.route_node,
                {node_id: node_id
                 for node_id in target_node_ids})
            return

        # condition 和 output 节点后面需要接 langgraph的 edge_condition
        if node_instance.type == NodeType.CONDITION.value:
            self.graph_builder.add_conditional_edges(
                node_instance.id, node_instance.route_node,
                {node_id: node_id
                 for node_id in target_node_ids})
            return

        # 链接到target节点
        for node_id in target_node_ids:
            if node_id not in self.nodes_map:
                raise Exception(f'target node {node_id} not found')
            if self.nodes_fan_in.get(node_id) and len(self.nodes_fan_in.get(node_id)) > 1:
                # need wait all fan in node exec over
                continue
            self.graph_builder.add_edge(node_instance.id, node_id)

    def build_more_fan_in_node(self):
        for node_id, source_ids in self.nodes_fan_in.items():
            if not source_ids or len(source_ids) <= 1:
                continue
            wait_nodes, no_wait_nodes = self.parse_fan_in_node(node_id)
            if wait_nodes:
                self.graph_builder.add_edge([f'{one}_fake' if one.startswith('output_') else one for one in wait_nodes],
                                            node_id)
            if no_wait_nodes:
                for one in no_wait_nodes:
                    self.graph_builder.add_edge(f'{one}_fake' if one.startswith('output_') else one, node_id)

    def parse_fan_in_node(self, node_id: str):
        source_ids = self.nodes_fan_in.get(node_id)
        all_next_nodes = self.nodes_next_nodes.get(node_id)
        wait_nodes = []
        no_wait_nodes = []
        for one in source_ids:
            if one in all_next_nodes:
                no_wait_nodes.append(one)
            else:
                wait_nodes.append(one)
        return wait_nodes, no_wait_nodes

    def build_nodes(self):
        nodes = self.workflow_data.get('nodes', [])
        if not nodes:
            raise Exception('workflow must have at least one node')

        start_node = None
        end_nodes = []
        interrupt_nodes = []
        # init nodes
        for node in nodes:
            node_data = BaseNodeData(**node.get('data', {}))
            if not node_data.id:
                raise Exception('node must have attribute id')

            node_instance = NodeFactory.instance_node(node_type=node_data.type,
                                                      node_data=node_data,
                                                      user_id=self.user_id,
                                                      workflow_id=self.workflow_id,
                                                      graph_state=self.graph_state,
                                                      target_edges=self.edges.get_target_edges(
                                                          node_data.id),
                                                      max_steps=self.max_steps,
                                                      callback=self.callback)
            self.nodes_map[node_data.id] = node_instance
            self.nodes_fan_in[node_instance.id] = self.edges.get_source_node(node_instance.id)
            if node_instance.type not in [NodeType.START.value, NodeType.END.value]:
                self.nodes_next_nodes[node_instance.id] = self.edges.get_next_nodes(node_instance.id,
                                                                                    exclude=[node_instance.id])

            # add node into langgraph
            if self.async_mode:
                self.graph_builder.add_node(node_instance.id, node_instance.arun)
            else:
                self.graph_builder.add_node(node_instance.id, node_instance.run)

            # find special node
            if node_instance.type == NodeType.START.value:
                start_node = node_instance.id
            elif node_instance.type == NodeType.END.value:
                end_nodes.append(node_instance.id)
            elif node_instance.type == NodeType.INPUT.value:
                # 需要中止接收用户输入的节点
                interrupt_nodes.append(node_instance.id)
            elif node_instance.type == NodeType.OUTPUT.value:
                # 需要中止接收用户输入的节点
                fake_node = OutputFakeNode(id=f'{node_instance.id}_fake',
                                           output_node=node_instance,
                                           type=NodeType.FAKE_OUTPUT.value)
                self.nodes_map[fake_node.id] = fake_node
                interrupt_nodes.append(fake_node.id)

        if not start_node:
            raise Exception('workflow must have start node')
        self.graph_builder.add_edge(START, start_node)
        if end_nodes:
            for end_node in end_nodes:
                self.graph_builder.add_edge(end_node, END)

        # 将其他节点链接起来
        for node_id, node_instance in self.nodes_map.items():
            self.add_node_edge(node_instance)

        self.build_more_fan_in_node()

        # compile langgraph
        self.graph = self.graph_builder.compile(checkpointer=MemorySaver(),
                                                interrupt_before=interrupt_nodes)
        self.graph_config['recursion_limit'] = (len(nodes) - len(end_nodes) - 1) * self.max_steps

        # import datetime
        # with open(f"./bisheng/data/graph/graph_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.png",
        #           'wb') as f:
        #     f.write(self.graph.get_graph().draw_mermaid_png())

    def _run(self, input_data: Any):
        try:
            self.status = WorkflowStatus.RUNNING.value
            for _ in self.graph.stream(input_data, config=self.graph_config):
                pass
            self.judge_status()
        except IgnoreException as e:
            logger.warning(f'graph ignore error: {e}')
            self.status = WorkflowStatus.FAILED.value
            self.reason = str(e)
        except Exception as e:
            logger.exception('graph run error')
            self.status = WorkflowStatus.FAILED.value
            self.reason = str(e)

    async def _arun(self, input_data: Any):
        try:
            self.status = WorkflowStatus.RUNNING.value
            async for _ in self.graph.astream(input_data, config=self.graph_config):
                pass
            self.judge_status()
        except IgnoreException as e:
            logger.warning(f'graph ignore error: {e}')
            self.status = WorkflowStatus.FAILED.value
            self.reason = str(e)
        except Exception as e:
            logger.exception('graph arun error')
            self.status = WorkflowStatus.FAILED.value
            self.reason = str(e)

    def run(self):
        self._run({'flag': True})

    async def arun(self):
        await self._arun({'flag': True})

    def continue_run(self, data: Any = None):
        """
        接收用户的输入
        data：{node_id: {key: value}}
        """
        # 接收用户输入后，继续执行
        if data is None:
            data = {}

        # 将用户输入赋值给对应的节点
        for node_id, node_params in data.items():
            node_instance = self.nodes_map[node_id]
            node_instance.handle_input(node_params)

        # 继续执行graph
        self._run(None)

    async def acontinue_run(self, data: Any = None):
        """
        接收用户的输入
        data：{node_id: {key: value}}
        """
        # 接收用户输入后，继续执行
        if data is None:
            data = {}

        # 将用户输入赋值给对应的节点
        for node_id, node_params in data.items():
            node_instance = self.nodes_map[node_id]
            node_instance.handle_input(node_params)

        # 继续执行graph
        await self._arun(None)

    def judge_status(self):
        # 判断状态
        snapshot = self.graph.get_state(self.graph_config)
        next_nodes = snapshot.next
        # 说明执行已完成
        if len(next_nodes) == 0:
            self.status = WorkflowStatus.SUCCESS.value
            return

        # 判断需要执行的node类型，设置对应的引擎状态
        for node_id in next_nodes:
            node_instance = self.nodes_map[node_id]
            if node_instance.type == NodeType.INPUT.value:
                input_schema = node_instance.get_input_schema()
                if input_schema:
                    # 回调需要用户输入的事件
                    self.status = WorkflowStatus.INPUT.value
                    self.callback.on_user_input(
                        UserInputData(node_id=node_id, group_params=input_schema))
                    return
            elif node_instance.type == NodeType.FAKE_OUTPUT.value:
                intput_schema = node_instance.get_input_schema()
                if intput_schema:
                    # output 节点需要用户输入
                    self.status = WorkflowStatus.INPUT.value
                    return

    def stop(self):
        for _, node_instance in self.nodes_map.items():
            node_instance.stop()
