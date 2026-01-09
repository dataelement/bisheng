from bisheng.workflow.callback.event import NodeEndData
from pydantic import ConfigDict, BaseModel, Field

from bisheng.workflow.nodes.output.output import OutputNode


class OutputFakeNode(BaseModel):
    """ Used to processoutputInterrupt to determine if user input is required """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    output_node: OutputNode
    type: str

    def run(self, state: dict):
        """ Do nothing, just use it to deal withoutputInterrupt to determine if user input is required """
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
