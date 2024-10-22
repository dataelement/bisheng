from abc import ABC

from bisheng.workflow.callback.event import NodeStartData, NodeEndData, UserInputData


class BaseCallback(ABC):

    def __init__(self, *args, **kwargs):
        pass

    def node_start(self, data: NodeStartData):
        """ node start event """
        print(f"node start: {data}")

    def node_end(self, data: NodeEndData):
        """ node end event """
        print(f"node end: {data}")

    def user_input(self, data: UserInputData):
        """ user input event """
        print(f"user input: {data}")
