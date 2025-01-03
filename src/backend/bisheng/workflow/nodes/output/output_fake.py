from bisheng.workflow.callback.event import NodeEndData
from pydantic import BaseModel, Field

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
        self.output_node.callback_manager.on_node_end(data=NodeEndData(
            unique_id=self.output_node.exec_unique_id,
            node_id=self.output_node.id,
            name=self.output_node.name,
            reason=None,
            log_data=self.output_node.parse_log(self.output_node.exec_unique_id, {})))
        return state

    async def arun(self, state: dict):
        return self.run(state)

    def get_input_schema(self):
        return self.output_node.get_input_schema()

    def stop(self):
        pass
