from typing import Any
import uuid

from bisheng.utils.minio_client import MinioClient
from bisheng.workflow.callback.event import OutputMsgData
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class OutputNode(BaseNode):

    def init_data(self):
        super().init_data()
        # minio
        self.minio_client = MinioClient()
        self.next_node = None
        self.output_type = self.node_params["submitted_result"]["type"]

        self.next_node_id = None
        if self.output_type != "choose":
            # 非选择型交互，则下个节点就是连线的target
            self.next_node_id = self.target_edges[0].target

    def handle_input(self, user_input: dict) -> Any:
        self.node_params["submitted_result"]["value"] = user_input["submitted_result"]

    def get_input_schema(self) -> Any:
        # 说明不需要交互
        if self.output_type == "":
            return None
        group_params = self.node_data.dict(include={"group_params"})
        return group_params

    def route_node(self, state: dict) -> str:
        return self.next_node_id

    def _run(self):
        # 需要交互，则通过pre_run已提前执行过节点的处理逻辑
        if self.output_type != "":
            if self.output_type == "choose":
                self.next_node_id = self.get_next_node_id(self.node_params["submitted_result"]["value"])
            return self.node_params

        # 不需要交互，执行节点的
        self.parse_output_msg()
        self.send_output_msg()
        return self.node_params

    def pre_run(self):
        """ 先把需要用户输入的message发给用户，后面节点执行时不需要再发送消息 """
        exec_id = uuid.uuid4().hex
        self.node_start_end_event = False
        self.callback_manager.on_node_start(
            data=NodeStartData(unique_id=exec_id, node_id=self.id, name=self.name)  # type: ignore
        )
        self.parse_output_msg()
        self.send_output_msg()

    def parse_output_msg(self):
        """ 填充msg中的变量，获取文件的share地址 """
        msg = self.node_params["output_msg"]["msg"]
        files = self.node_params["output_msg"]["files"]

        msg_template = PromptTemplateParser(template=msg)
        variables = msg_template.extract()
        if len(variables) > 0:
            var_map = {}
            for one in variables:
                var_map[one] = self.graph_state.get_variable_by_str(one)
            msg = msg_template.format(var_map)
        self.node_params["output_msg"]["msg"] = msg

        for one in files:
            one["path"] = self.minio_client.clear_minio_share_host(self.minio_client.get_share_link(one["path"]))

    def send_output_msg(self):
        """ 发送output节点的消息 """
        group_params = None
        # 需要交互则有group_params
        if self.output_type != "":
            group_params = self.node_data.dict(include={"group_params"})
        self.callback_manager.on_output_msg(OutputMsgData(node_id=self.id,
                                                          msg=self.node_params["output_msg"]["msg"],
                                                          group_params=group_params["group_params"]))
