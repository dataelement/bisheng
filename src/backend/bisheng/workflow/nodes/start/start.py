import datetime
from typing import Any, Dict

from bisheng.workflow.callback.event import GuideQuestionData, GuideWordData
from bisheng.workflow.nodes.base import BaseNode
from langchain.memory import ConversationBufferWindowMemory


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
                data=GuideWordData(node_id=self.id, guide_word=self.node_params['guide_word']))
        if self.node_params['guide_question']:
            self.callback_manager.on_guide_question(data=GuideQuestionData(
                node_id=self.id, guide_question=self.node_params['guide_question']))
        return {
            'current_time': self.node_params['current_time'],
            'chat_history': '',
            'preset_question': self.node_params['preset_question']
        }

    def parse_log(self, unique_id: str, result: dict) -> Any:
        return {
            'current_time': result['current_time'],
            'preset_question': result['preset_question']
        }
