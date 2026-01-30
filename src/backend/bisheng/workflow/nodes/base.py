import base64
import copy
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage

from bisheng.core.cache.utils import file_download
from bisheng.user.domain.models.user import UserDao
from bisheng.utils.exceptions import IgnoreException
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import NodeEndData, NodeStartData
from bisheng.workflow.common.node import BaseNodeData, NodeType
from bisheng.workflow.edges.edges import EdgeBase
from bisheng.workflow.graph.graph_state import GraphState
from bisheng.workflow.nodes.prompt_template import PromptTemplateParser


class BaseNode(ABC):

    def __init__(self, node_data: BaseNodeData, workflow_id: str, user_id: int,
                 graph_state: GraphState, target_edges: List[EdgeBase], max_steps: int,
                 callback: BaseCallback, **kwargs: Any):
        self.id = node_data.id
        self.type = node_data.type
        self.name = node_data.name
        self.description = node_data.description
        self.target_edges = target_edges

        # Execute Unique Identification of User
        self.user_id = user_id

        # Global State Management
        self.workflow_id = workflow_id
        self.workflow_name = kwargs.get('workflow_name')
        self.graph_state = graph_state

        # Data of all nodes
        self.node_data = node_data

        # Parameters required for storage nodes Directly usable parameters after processing
        self.node_params = {}

        # The value of the other node variables required to store the node
        self.other_node_variable = {}

        # Used to determine if the maximum number of runs has been exceeded
        self.current_step = 0
        self.max_steps = max_steps

        # Callbacks to handle various events during node execution
        self.callback_manager = callback

        # Storing Temporary Data milvus Collection Name And es Collection Name workflow_id As partition key
        # samecollectionMedium vector data must be the sameembedding_modelGenerated, so the collection name needs to containembedding_model_id
        self.tmp_collection_name = 'tmp_workflow_data_new'

        self.stop_flag = False

        self.exec_unique_id = None

        self.user_info = None

        # Parse Simple Parameters
        self.init_data()

    def init_data(self):
        """ Unified parameter processing, nodes with special needs can be processed when initializing themselves """
        if not self.node_data.group_params:
            return

        for one in self.node_data.group_params:
            for param_info in one.params:
                self.node_params[param_info.key] = copy.deepcopy(param_info.value)

    def init_user_info(self):
        if self.user_info:
            return
        self.user_info = UserDao.get_user(int(self.user_id))

    @abstractmethod
    def _run(self, unique_id: str) -> Dict[str, Any]:
        """
        Run node The returned results are stored in the global variable management and can be used by other nodes
        :return:
        """
        raise NotImplementedError

    def parse_log(self, unique_id: str, result: dict) -> Any:
        """
         Returns the node operation log, the default return is empty
        params:
            result: Node Run Result
        return:  The outermost layer is the rounds, and inside are the logs for each round.
        [
            [
                {
                    "key": "xxx",
                    "value": "xxx",
                    "type": "tool" # tool: Tool Type Logs, variable: Log of global variables, params: Log of node parameter type,keySHOW: keymain body
                }
            ]
        ]
        """
        return []

    def get_other_node_variable(self, variable_key: str) -> Any:
        """ Get the variable values of other nodes from the global variable """
        value = self.graph_state.get_variable_by_str(variable_key)
        self.other_node_variable[variable_key] = value
        return value

    def get_input_schema(self) -> Any:
        """ Returns the form description the user needs to enter """
        return None

    def is_condition_node(self) -> bool:
        """ Whether it is a mutually exclusive node """
        return self.node_data.type == NodeType.CONDITION.value

    def get_milvus_collection_name(self, embedding_model_id: str) -> str:
        return f"{self.tmp_collection_name}_{embedding_model_id}"

    def handle_input(self, user_input: dict) -> Any:
        # Update the data entered by the user to the number of nodes
        self.node_params.update(user_input)

    def route_node(self, state: dict) -> str:
        """
        counterpart&apos;slanggraphright of privacycondition_edgeright of privacyfunction, only special nodes need
        :return: node_ambid
        """
        raise NotImplementedError

    def get_next_node_id(self, source_handle: str) -> list[str]:
        next_nodes = []
        for one in self.target_edges:
            if one.sourceHandle == source_handle:
                next_nodes.append(one.target)
        return next_nodes

    def parse_msg_with_variables(self, msg: str) -> (str, list[str]):
        """
        params:
            msg: user input msg with node variables
        return:
            0: new msg after replaced variable
            1: list of variables node_id.xxxx
        """
        msg_template = PromptTemplateParser(template=msg)
        variables = msg_template.extract()
        if len(variables) > 0:
            var_map = {}
            for one in variables:
                var_map[one] = self.get_other_node_variable(one)
            msg = msg_template.format(var_map)
        return msg, variables

    @staticmethod
    def get_file_base64_data(file_path: str) -> str:
        if file_path.startswith(('http', "https")):
            file_path, _ = file_download(file_path)

        with open(file_path, "rb") as f:
            file_data = f.read()
            base64_data = base64.b64encode(file_data).decode('utf-8')
        return base64_data

    def contact_file_into_prompt(self, human_message: HumanMessage, variable_list: List[str]) -> HumanMessage:
        if not variable_list:
            if isinstance(human_message.content, list):
                human_message.content = human_message.content[0].get('text')
            return human_message
        for image_variable in variable_list:
            image_value = self.get_other_node_variable(image_variable)
            if not image_value:
                continue
            for file_path in image_value:
                base64_image = self.get_file_base64_data(file_path)
                human_message.content.append({
                    "type": "image",
                    "source_type": "base64",
                    "mime_type": "image/jpeg",
                    "data": base64_image,
                })
        return human_message

    def run(self, state: dict) -> Any:
        """
        Run node entry
        :return:
        """
        if self.stop_flag:
            raise IgnoreException('stop by user')
        if self.current_step >= self.max_steps:
            raise IgnoreException(f'{self.name} -- has run more than the maximum number of times.')

        exec_id = uuid.uuid4().hex
        self.exec_unique_id = exec_id
        self.callback_manager.on_node_start(
            data=NodeStartData(unique_id=exec_id, node_id=self.id, name=self.name))

        reason = None
        log_data = None
        try:
            result = self._run(exec_id)
            log_data = self.parse_log(exec_id, result)
            # Store node output in global variables
            if result:
                for key, value in result.items():
                    self.graph_state.set_variable(self.id, key, value)
            self.current_step += 1
        except Exception as e:
            reason = str(e)
            raise e
        finally:
            # The end log of the output node is created byfakeNode Output, Because it is necessary to wait for the user to complete the input before the log can be displayed correctly
            if reason or self.type != NodeType.OUTPUT.value:
                self.callback_manager.on_node_end(data=NodeEndData(
                    unique_id=exec_id, node_id=self.id, name=self.name, reason=reason, log_data=log_data,
                    input_data=self.other_node_variable))
        return state

    async def arun(self, state: dict) -> Any:
        return self.run(state)

    def stop(self):
        self.stop_flag = True
