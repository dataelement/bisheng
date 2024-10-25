from typing import Any
import uuid

from bisheng.utils.minio_client import MinioClient
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class OutputNode(BaseNode):

    def init_data(self):
        super().init_data()
        # minio
        self.minio_client = MinioClient()

    def get_input_schema(self) -> Any:
        # 说明不需要交互
        if self.node_params["output_type"]["type"] == "":
            return None
        group_params = self.node_data.dict(include={"group_params"})
        return group_params

    def _run(self):
        # 需要交互，则通过pre_run执行了节点的处理逻辑
        if self.node_params["output_type"] != "":
            return self.node_params

    def pre_run(self):
        """ 先把需要用户输入的message发给用户，后面节点执行时不需要再发送消息 """
        exec_id = uuid.UUID().hex
        self.node_start_end_event = False
        self.callback_manager.on_node_start(
            data=NodeStartData(unique_id=exec_id, node_id=self.id, name=self.name)  # type: ignore
        )

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
