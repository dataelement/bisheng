import datetime
from typing import Any, Dict

from langchain.memory import ConversationBufferWindowMemory

from bisheng.chat.types import IgnoreException
from bisheng.workflow.callback.event import GuideQuestionData, GuideWordData
from bisheng.workflow.nodes.base import BaseNode


class StartNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 初始化当前时间
        self.node_params['current_time'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # 初始化聊天历史记录
        self.graph_state.history_memory = ConversationBufferWindowMemory(
            k=self.node_params.get('chat_history', 10))

    def _run(self, unique_id: str) -> Dict[str, Any]:
        if self.node_params['guide_word']:
            self.callback_manager.on_guide_word(
                data=GuideWordData(node_id=self.id, unique_id=unique_id, guide_word=self.node_params['guide_word']))
        if self.node_params['guide_question']:
            self.callback_manager.on_guide_question(
                data=GuideQuestionData(node_id=self.id, unique_id=unique_id,
                                       guide_question=self.node_params['guide_question']))
        if not self.node_data.v:
            raise IgnoreException(f'{self.name} -- workflow node is update')

        # 预处理preset_question数据为dict
        new_preset_question = {}
        for one in self.node_params['preset_question']:
            new_preset_question[one['key']] = one['value']

        return {
            'current_time': self.node_params['current_time'],
            'chat_history': '',
            'preset_question': new_preset_question
        }

    def parse_log(self, unique_id: str, result: dict) -> Any:
        return [[
            {
                "key": "current_time",
                "value": result['current_time'],
                "type": "params"
            },
            {
                "key": "preset_question",
                "value": result['preset_question'],
                "type": "params"
            }
        ]]
