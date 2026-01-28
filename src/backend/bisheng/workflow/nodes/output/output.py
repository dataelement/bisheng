import json
from typing import Any

from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.workflow.callback.event import OutputMsgChooseData, OutputMsgData, OutputMsgInputData
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class OutputNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # minio
        self._minio_client = get_minio_storage_sync()
        # Interaction Type
        self._output_type = self.node_params['output_result']['type']
        self._output_result = self.node_params['output_result']['value']

        # Result of user processing
        self._handled_output_result = self._output_result

        # user input msg
        if 'output_msg' in self.node_params:
            _original_output_msg = self.node_params['output_msg']
        else:
            _original_output_msg = self.node_params['message']
        self._output_msg = _original_output_msg['msg']
        self._output_files = _original_output_msg['files']

        # Message Content After Variable Replacement
        self._parsed_output_msg = ''
        self._parsed_files = []

        self._source_documents = []

        # Non-selective interaction, then the next node is wiredtarget. Selective interactions, which need to be judged based on user input
        self._next_node_id = [one.target for one in self.target_edges]

    def handle_input(self, user_input: dict) -> Any:
        # Needs to be depositedstate，
        self.graph_state.save_context(content=json.dumps(user_input, ensure_ascii=False), msg_sender='human')
        self._handled_output_result = user_input['output_result']
        self.graph_state.set_variable(self.id, 'output_result', user_input['output_result'])

    def get_input_schema(self) -> Any:
        # Explain that no interaction is required
        if self._output_type not in ['input', 'choose']:
            return None
        group_params = self.node_data.dict(include={'group_params'})
        return group_params['group_params']

    def is_condition_node(self) -> bool:
        return self._output_type == 'choose'

    def route_node(self, state: dict) -> str | list[str]:
        # Selective interaction requires judging the next node based on the user's input
        if self._output_type == 'choose':
            return self.get_next_node_id(self._handled_output_result)
        return self._next_node_id

    def _run(self, unique_id: str):
        self._source_documents = []
        self.parse_output_msg()
        self.send_output_msg(unique_id)
        res = {
            'message': self._parsed_output_msg,
            'output_result': self._handled_output_result
        }
        return res

    def parse_log(self, unique_id: str, result: dict) -> Any:
        ret = [
            {
                "key": "output_msg",
                "value": self._parsed_output_msg,
                "type": "params"
            }
        ]
        if self._output_type == 'input':
            ret.append({
                "key": "output_result",
                "value": self._handled_output_result,
                "type": "key"
            })
        return [ret]

    def parse_output_msg(self):
        """ Paddingmsgvariable in, get the file'sshare<g id="Bold">Address:</g> """
        self._parsed_output_msg = self.parse_template_msg(self._output_msg)

        if self._parsed_files:
            return
        for one in self._output_files:
            one['path'] = self._minio_client.get_share_link_sync(one['path'])
            self._parsed_files.append(one)

    def send_output_msg(self, unique_id: str):
        """ SendoutputNode's Message """
        msg_params = {
            'name': self.name,
            'unique_id': unique_id,
            'node_id': self.id,
            'msg': self._parsed_output_msg,
            'files': self._parsed_files,
            'output_key': '',
            'source_documents': self._source_documents
        }
        # where interaction is required, there isgroup_params
        if self._output_type == 'input':
            msg_params['key'] = 'output_result'
            msg_params['input_msg'] = self.parse_template_msg(self._output_result)
            self.callback_manager.on_output_input(data=OutputMsgInputData(**msg_params))
        elif self._output_type == 'choose':
            msg_params['key'] = 'output_result'
            msg_params['options'] = self.node_data.get_variable_info('output_result').options
            self.callback_manager.on_output_choose(data=OutputMsgChooseData(**msg_params))
        else:
            self.graph_state.save_context(content=self._parsed_output_msg,
                                          msg_sender='AI')
            self.callback_manager.on_output_msg(OutputMsgData(**msg_params))

    def parse_template_msg(self, msg: str):
        msg_template = PromptTemplateParser(template=msg)
        variables = msg_template.extract()
        if len(variables) > 0:
            var_map = {}
            for one in variables:
                node_id = one.split('.')[0]
                # CiteqaDemonstrate traceability when using the Knowledge Base node
                if node_id.startswith('qa_retriever'):
                    self._source_documents = self.graph_state.get_variable(node_id, '$retrieved_result$')
                var_map[one] = self.get_other_node_variable(one)
            msg = msg_template.format(var_map)
        return msg
