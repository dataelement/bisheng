from abc import ABC

from bisheng.workflow.callback.event import NodeStartData, NodeEndData, OutputMsgChooseData, OutputMsgInputData, UserInputData, GuideWordData, GuideQuestionData, \
    OutputMsgData


class BaseCallback(ABC):

    def __init__(self, *args, **kwargs):
        pass

    def on_node_start(self, data: NodeStartData):
        """ node start event """
        print(f"node start: {data}")

    def on_node_end(self, data: NodeEndData):
        """ node end event """
        print(f"node end: {data}")

    def on_user_input(self, data: UserInputData):
        """ user input event """
        print(f"user input: {data}")

    def on_guide_word(self, data: GuideWordData):
        """ guide word event """
        print(f"guide word: {data}")

    def on_guide_question(self, data: GuideQuestionData):
        """ guide question event """
        print(f"guide question: {data}")

    def on_output_msg(self, data: OutputMsgData):
        print(f"output msg: {data}")

    def on_output_choose(self, data: OutputMsgChooseData):
        print(f"output choose: {data}")

    def on_output_input(self, data: OutputMsgInputData):
        print(f"output input: {data}")
