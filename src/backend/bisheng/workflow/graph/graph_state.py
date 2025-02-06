from typing import Any, Dict, Optional, List

from langchain.memory import ConversationBufferWindowMemory
from langchain_core.messages import AIMessage, HumanMessage, get_buffer_string, BaseMessage
from pydantic import BaseModel, Field


class GraphState(BaseModel):
    """ 所有节点的 全局状态管理 """

    # 存储聊天历史
    history_memory: Optional[ConversationBufferWindowMemory]

    # 全局变量池
    variables_pool: Dict[str, Dict[str, Any]] = Field(default={}, description='全局变量池: {node_id: {key: value}}')

    def get_history_memory(self, count: int) -> str:
        """ 获取聊天历史记录
        因为不是1对1，所以重写 buffer_as_str"""
        if not count:
            count = self.history_memory.k
        messages = self.history_memory.chat_memory.messages[-count:]
        return get_buffer_string(
            messages,
            human_prefix=self.history_memory.human_prefix,
            ai_prefix=self.history_memory.ai_prefix,
        )

    def get_history_list(self, count: int) -> List[BaseMessage]:
        return self.history_memory.buffer_as_messages[-count:]


    def save_context(self, content: str, msg_sender: str) -> None:
        """  保存聊天记录
        workflow 特殊情况，过程会有多轮交互，所以不是一条对一条，重制消息结构"""
        if msg_sender == 'human':
            self.history_memory.chat_memory.add_messages([HumanMessage(content=content)])
        elif msg_sender == 'AI':
            self.history_memory.chat_memory.add_messages([AIMessage(content=content)])

    def set_variable(self, node_id: str, key: str, value: Any):
        """ 将节点产生的数据放到全局变量里 """
        if node_id not in self.variables_pool:
            self.variables_pool[node_id] = {}
        self.variables_pool[node_id][key] = value

    def get_variable(self, node_id: str, key: str, count: Optional[int] = None) -> Any:
        """ 从全局变量中获取数据 """
        if node_id not in self.variables_pool:
            return None

        if key == 'chat_history':
            return self.get_history_memory(count=count)
        return self.variables_pool[node_id].get(key)

    def get_variable_by_str(self, contact_key: str, history_count: Optional[int] = None) -> Any:
        """
        从全局变量中获取数据
        contact_key: node_id.key#index  #index不一定需要
        """
        tmp_list = contact_key.split('.', 1)
        node_id = tmp_list[0]
        var_key = tmp_list[1]
        variable_val_index = None
        if var_key.find('#') != -1:
            var_key, variable_val_index = var_key.split('#')
        variable_val = self.get_variable(node_id, var_key, history_count)

        # 数组变量的处理
        if variable_val_index:
            if isinstance(variable_val, list):
                variable_val_index = int(variable_val_index)
                if len(variable_val) <= variable_val_index:
                    raise Exception(f'variable {contact_key} index out of range')
                return variable_val[variable_val_index]
            elif isinstance(variable_val, dict):
                return variable_val.get(variable_val_index)
            else:
                raise Exception(f'variable {contact_key} is not a list or dict, not support #index')

        return variable_val

    def set_variable_by_str(self, contact_key: str, value: Any):
        tmp_list = contact_key.split('.', 1)
        node_id = tmp_list[0]
        var_key = tmp_list[1]
        if var_key.find('#') != -1:
            var_key, variable_val_index = var_key.split('#')
            old_value = self.get_variable(node_id, var_key)
            if not old_value:
                old_value = ['' for i in variable_val_index]
            if len(old_value) <= int(variable_val_index):
                old_value.extend(['' for i in range(int(variable_val_index) - len(old_value) + 1)])
            old_value[int(variable_val_index)] = value
            value = old_value
        self.set_variable(node_id, var_key, value)

    def get_all_variables(self) -> Dict[str, Any]:
        """ 获取所有的变量，key为node_id.key的格式 """
        ret = {}
        for node_id, node_variables in self.variables_pool.items():
            for key, value in node_variables.items():
                ret[f'{node_id}.{key}'] = self.get_variable(node_id, key)
                # 特殊处理下 preset_question key
                if key == 'preset_question':
                    for one in range(len(value)):
                        ret[f'{node_id}.{key}#{one}'] = value[one]
        return ret
