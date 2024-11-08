from typing import Any, Dict, Optional

from langchain.memory import ConversationBufferWindowMemory
from pydantic import BaseModel


class GraphState(BaseModel):
    """ 所有节点的 全局状态管理 """

    # 存储聊天历史
    history_memory: Optional[ConversationBufferWindowMemory]

    # 全局变量池
    variables_pool: Dict[str, Dict[str, Any]] = {}

    def get_history_memory(self) -> str:
        """ 获取聊天历史记录 """
        return self.history_memory.load_memory_variables({})[self.history_memory.memory_key]

    def save_context(self, question: str, answer: str) -> None:
        """  保存聊天记录 """
        self.history_memory.save_context({'input': question}, {'output': answer})

    def set_variable(self, node_id: str, key: str, value: Any):
        """ 将节点产生的数据放到全局变量里 """
        if node_id not in self.variables_pool:
            self.variables_pool[node_id] = {}
        self.variables_pool[node_id][key] = value

    def get_variable(self, node_id: str, key: str) -> Any:
        """ 从全局变量中获取数据 """
        if node_id not in self.variables_pool:
            return None

        # todo 某些特殊变量的处理 chat_history、source_document等
        if key == 'chat_history':
            return self.get_history_memory()
        return self.variables_pool[node_id].get(key)

    def get_variable_by_str(self, contact_key: str) -> Any:
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
        variable_val = self.get_variable(node_id, var_key)

        # 数组变量的处理
        if variable_val_index:
            variable_val_index = int(variable_val_index)
            if not isinstance(variable_val, list) or len(variable_val) <= variable_val_index:
                raise Exception(f'variable {contact_key} is not array or index out of range')
            return variable_val[variable_val_index]

        # todo 某些特殊变量的处理
        return variable_val
