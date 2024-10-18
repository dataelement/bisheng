from abc import abstractmethod, ABC
from typing import Any

from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.graph.graph_state import GraphState


class BaseNode(ABC):

    def __init__(self, id: str, type: str, name: str, description: str, data: Any,
                 max_steps: int, graph_state: GraphState, callback: BaseCallback, **kwargs: Any):
        self.id = id
        self.type = type
        self.name = name
        self.description = description
        self.data = data

        # 用来判断是否运行超过最大次数
        self.current_step = 0
        self.max_steps = max_steps

        # workflow 全局的变量管理
        self.graph_state = graph_state

        # 回调，用来处理节点执行过程中的各种事件
        self.callback_manager = callback

    @abstractmethod
    def _run(self) -> Any:
        """
        Run node
        :return:
        """
        raise NotImplementedError

    def run(self, state: 'LangGraphState') -> Any:
        """
        Run node entry
        :return:
        """
        # todo start exec node event
        result = self._run()
        # todo end exec node event
        return result
