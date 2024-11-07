from typing import Any

from bisheng.utils.minio_client import MinioClient
from bisheng.workflow.callback.event import OutputMsgChooseData, OutputMsgData, OutputMsgInputData
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class OutputNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # minio
        self._minio_client = MinioClient()
        self._output_type = self.node_params['output_way']['type']

        # 非选择型交互，则下个节点就是连线的target。选择型交互，需要根据用户输入来判断
        self._next_node_id = self.target_edges[0].target

    def handle_input(self, user_input: dict) -> Any:
        self.node_params['output_way']['value'] = user_input['output_way']

    def get_input_schema(self) -> Any:
        # 说明不需要交互
        if self._output_type not in ['input', 'choose']:
            return None
        group_params = self.node_data.dict(include={'group_params'})
        return group_params['group_params']

    def route_node(self, state: dict) -> str:
        # 选择型交互需要根据用户的输入，来判断下个节点
        if self._output_type == 'choose':
            return self.get_next_node_id(self.node_params['output_way']['value'])
        return self._next_node_id

    def _run(self, unique_id: str):
        self.parse_output_msg()
        self.send_output_msg()
        return self.node_params

    def parse_output_msg(self):
        """ 填充msg中的变量，获取文件的share地址 """
        msg = self.node_params['output_msg']['msg']
        files = self.node_params['output_msg']['files']

        self.node_params['output_msg']['msg'] = self.parse_template_msg(msg)

        for one in files:
            if not one['path'].startswith(('http', 'https')):
                one['path'] = self._minio_client.clear_minio_share_host(
                    self._minio_client.get_share_link(one['path']))

    def send_output_msg(self):
        """ 发送output节点的消息 """
        msg_params = {
            'node_id': self.id,
            'msg': self.node_params['output_msg']['msg'],
            'files': self.node_params['output_msg']['files']
        }
        # 需要交互则有group_params
        if self._output_type == 'input':
            msg_params['key'] = 'output_way'
            msg_params['input_msg'] = self.parse_template_msg(
                self.node_params['output_way']['value'])
            self.callback_manager.on_output_input(data=OutputMsgInputData(**msg_params))
        elif self._output_type == 'choose':
            msg_params['key'] = 'output_way'
            msg_params['options'] = self.node_data.get_variable_info('output_way').options
            self.callback_manager.on_output_choose(data=OutputMsgChooseData(**msg_params))
        else:
            self.callback_manager.on_output_msg(OutputMsgData(**msg_params))

    def parse_template_msg(self, msg: str):
        msg_template = PromptTemplateParser(template=msg)
        variables = msg_template.extract()
        if len(variables) > 0:
            var_map = {}
            for one in variables:
                # todo: 引用qa知识库节点时，展示溯源情况
                var_map[one] = self.graph_state.get_variable_by_str(one)
            msg = msg_template.format(var_map)
        return msg