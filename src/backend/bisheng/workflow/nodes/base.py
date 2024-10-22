from abc import abstractmethod, ABC
from typing import Any

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.common.node import BaseNodeData
from bisheng.workflow.graph.graph_state import GraphState


class BaseNode(ABC):

    def __init__(self, node_data: BaseNodeData, max_steps: int, callback: BaseCallback, **kwargs: Any):
        self.id = node_data.id
        self.type = node_data.type
        self.name = node_data.name
        self.description = node_data.description

        # 节点全部的数据
        self.node_data = node_data

        # 存储节点所需的参数 处理后的可直接用的参数
        self.node_params = {}

        # 用来判断是否运行超过最大次数
        self.current_step = 0
        self.max_steps = max_steps

        # 回调，用来处理节点执行过程中的各种事件
        self.callback_manager = callback

        self.init_data()

    def init_data(self):
        """ 节点有特殊数据需要处理的，可以继承此函数处理 """
        for one in self.node_data.group_params:
            for param_info in one.params:
                self.node_params[param_info.key] = param_info.value

    @abstractmethod
    def _run(self) -> Any:
        """
        Run node
        :return:
        """
        raise NotImplementedError

    def handle_input(self, user_input: dict) -> Any:
        # 将用户输入的数据更新到节点数里
        self.node_params.update(user_input)

    def route_node(self, state: dict) -> str:
        """
        对应的langgraph的condition_edge的function，只有特殊节点需要
        :return: 节点id
        """
        raise NotImplementedError

    def run(self, state: dict) -> Any:
        """
        Run node entry
        :return:
        """
        # todo start exec node event
        print(f"start exec node: {self.id}")
        if self.current_step >= self.max_steps:
            raise Exception(f"node {self.name} exceeded more than max steps")
        result = self._run()
        self.current_step += 1
        print(f"end exec node: {self.id}")
        # todo end exec node event
        return state
