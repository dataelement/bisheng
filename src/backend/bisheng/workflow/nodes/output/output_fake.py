from pydantic import BaseModel

from bisheng.workflow.nodes.output.output import OutputNode


class OutputFakeNode(BaseModel):
    """ 用来处理output的中断，判断是否需要用户的输入 """

    class Config:
        arbitrary_types_allowed = True

    id: str
    output_node: OutputNode
    type: str

    def run(self, state: dict):
        """ 什么都不执行，只是用来处理output的中断，判断是否需要用户的输入 """
        return state

    async def arun(self, state: dict):
        return self.run(state)

    def get_input_schema(self):
        return self.output_node.get_input_schema()
