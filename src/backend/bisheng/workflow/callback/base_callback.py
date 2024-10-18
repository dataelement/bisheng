from abc import ABC

from bisheng.workflow.callback.event import NodeStartData


class BaseCallback(ABC):

    def __init__(self, *args, **kwargs):
        pass

    def node_start(self, data: NodeStartData):
        """ node start event """

    def node_end(self, data: NodeEndData):
        """ node end event """
        pass
