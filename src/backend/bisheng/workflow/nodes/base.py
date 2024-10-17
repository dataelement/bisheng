from abc import abstractmethod, ABC
from typing import Any


class BaseNode(ABC):

    def __init__(self, id: str, type: str, name: str, description: str, data: Any,
                 graph: 'Graph', graph_state: 'GraphState', **kwargs: Any):
        self.id = id
        self.type = type
        self.name = name
        self.description = description
        self.data = data
        self.graph = graph
        self.graph_state = graph_state

    @abstractmethod
    def _run(self) -> Any:
        """
        Run node
        :return:
        """
        raise NotImplementedError

    def run(self) -> Any:
        """
        Run node entry
        :return:
        """
        # todo start exec node event
        result = self._run()
        # todo end exec node event
        return result
