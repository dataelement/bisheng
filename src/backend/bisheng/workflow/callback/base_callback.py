from abc import ABC

from bisheng.workflow.callback.event import NodeStartData, NodeEndData, OutputMsgChooseData, OutputMsgInputData, \
    UserInputData, GuideWordData, GuideQuestionData, \
    OutputMsgData, StreamMsgData, StreamMsgOverData


class BaseCallback(ABC):

    def __init__(self, *args, **kwargs):
        pass

    def on_node_start(self, data: NodeStartData):
        """ node start event """
        pass

    def on_node_end(self, data: NodeEndData):
        """ node end event """
        pass

    def on_user_input(self, data: UserInputData):
        """ user input event """
        pass

    def on_guide_word(self, data: GuideWordData):
        """ guide word event """
        pass

    def on_guide_question(self, data: GuideQuestionData):
        """ guide question event """
        pass

    def on_stream_msg(self, data: StreamMsgData):
        pass

    def on_stream_over(self, data: StreamMsgOverData):
        pass

    def on_output_msg(self, data: OutputMsgData):
        pass

    def on_output_choose(self, data: OutputMsgChooseData):
        pass

    def on_output_input(self, data: OutputMsgInputData):
        pass
