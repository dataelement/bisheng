import copy
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from bisheng.utils.exceptions import IgnoreException
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import NodeEndData, NodeStartData
from bisheng.workflow.common.node import BaseNodeData, NodeType
from bisheng.workflow.edges.edges import EdgeBase
from bisheng.workflow.graph.graph_state import GraphState


class BaseNode(ABC):

    def __init__(self, node_data: BaseNodeData, workflow_id: str, user_id: str,
                 graph_state: GraphState, target_edges: List[EdgeBase], max_steps: int,
                 callback: BaseCallback, **kwargs: Any):
        self.id = node_data.id
        self.type = node_data.type
        self.name = node_data.name
        self.description = node_data.description
        self.target_edges = target_edges

        # 执行用户的唯一标识
        self.user_id = user_id

        # 全局状态管理
        self.workflow_id = workflow_id
        self.graph_state = graph_state

        # 节点全部的数据
        self.node_data = node_data

        # 存储节点所需的参数 处理后的可直接用的参数
        self.node_params = {}

        # 存储节点所需的其他节点变量的值
        self.other_node_variable = {}

        # 用来判断是否运行超过最大次数
        self.current_step = 0
        self.max_steps = max_steps

        # 回调，用来处理节点执行过程中的各种事件
        self.callback_manager = callback

        # 存储临时数据的 milvus 集合名 和 es 集合名 用workflow_id作为分区键
        # ！！！同一个collection中向量数据必须是同一个embedding_model生成的，所以集合名中需要包含embedding_model_id
        self.tmp_collection_name = 'tmp_workflow_data'

        self.stop_flag = False

        self.exec_unique_id = None

        # 简单参数解析
        self.init_data()

    def init_data(self):
        """ 统一的参数处理，节点有特殊需求的可以，自己初始化时处理 """
        if not self.node_data.group_params:
            return

        for one in self.node_data.group_params:
            for param_info in one.params:
                self.node_params[param_info.key] = copy.deepcopy(param_info.value)

    @abstractmethod
    def _run(self, unique_id: str) -> Dict[str, Any]:
        """
        Run node 返回的结果会存储到全局的变量管理里，可以被其他节点使用
        :return:
        """
        raise NotImplementedError

    def parse_log(self, unique_id: str, result: dict) -> Any:
        """
         返回节点运行日志，默认返回为空
        params:
            result: 节点运行结果
        return:  最外层是轮次，里面是每个轮次的日志
        [
            [
                {
                    "key": "xxx",
                    "value": "xxx",
                    "type": "tool" # tool: 工具类型的日志, variable：全局变量的日志, params：节点参数类型的日志，key：展示key本身
                }
            ]
        ]
        """
        return []

    def get_other_node_variable(self, variable_key: str) -> Any:
        """ 从全局变量中获取其他节点的变量值 """
        value = self.graph_state.get_variable_by_str(variable_key)
        self.other_node_variable[variable_key] = value
        return value

    def get_input_schema(self) -> Any:
        """ 返回用户需要输入的表单描述信息 """
        return None

    def is_condition_node(self) -> bool:
        """ 是否是互斥节点 """
        return self.node_data.type == NodeType.CONDITION.value

    def get_milvus_collection_name(self, embedding_model_id: str) -> str:
        return f"{self.tmp_collection_name}_{embedding_model_id}"

    def handle_input(self, user_input: dict) -> Any:
        # 将用户输入的数据更新到节点数里
        self.node_params.update(user_input)

    def route_node(self, state: dict) -> str:
        """
        对应的langgraph的condition_edge的function，只有特殊节点需要
        :return: 节点id
        """
        raise NotImplementedError

    def get_next_node_id(self, source_handle: str) -> list[str]:
        next_nodes = []
        for one in self.target_edges:
            if one.sourceHandle == source_handle:
                next_nodes.append(one.target)
        return next_nodes

    def run(self, state: dict) -> Any:
        """
        Run node entry
        :return:
        """
        if self.stop_flag:
            raise IgnoreException('stop by user')
        if self.current_step >= self.max_steps:
            raise IgnoreException(f'{self.name} -- has run more than the maximum number of times.')

        exec_id = uuid.uuid4().hex
        self.exec_unique_id = exec_id
        self.callback_manager.on_node_start(
            data=NodeStartData(unique_id=exec_id, node_id=self.id, name=self.name))

        reason = None
        log_data = None
        try:
            result = self._run(exec_id)
            log_data = self.parse_log(exec_id, result)
            # 把节点输出存储到全局变量中
            if result:
                for key, value in result.items():
                    self.graph_state.set_variable(self.id, key, value)
            self.current_step += 1
        except Exception as e:
            reason = str(e)
            raise e
        finally:
            # 输出节点的结束日志由fake节点输出, 因为需要等待用户先输入完成，才能正确显示日志
            if reason or self.type != NodeType.OUTPUT.value:
                self.callback_manager.on_node_end(data=NodeEndData(
                    unique_id=exec_id, node_id=self.id, name=self.name, reason=reason, log_data=log_data,
                    input_data=self.other_node_variable))
        return state

    async def arun(self, state: dict) -> Any:
        return self.run(state)

    def stop(self):
        self.stop_flag = True
