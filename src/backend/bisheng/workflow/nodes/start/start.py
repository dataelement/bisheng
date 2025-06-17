import datetime
from typing import Any, Dict

from bisheng.chat.types import IgnoreException
from bisheng.utils.exceptions import IgnoreException
from bisheng.workflow.callback.event import GuideQuestionData, GuideWordData
from bisheng.workflow.nodes.base import BaseNode
from langchain.memory import ConversationBufferWindowMemory
from bisheng.database.models.user import UserDao
from bisheng.database.models.group import GroupDao
from bisheng.database.models.user_group import UserGroupDao
from loguru import logger


class StartNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 初始化当前时间
        self.node_params['current_time'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.node_params['user_info'] = self.get_user_info()
        # 初始化聊天历史记录
        self.graph_state.history_memory = ConversationBufferWindowMemory(
            k=self.node_params.get('chat_history', 10))

        logger.debug(
            f"jjxx StartNode init node_data.v:{self.node_data.v} type_v:{type(self.node_data.v)} node_data:{self.node_data}")

    def _run(self, unique_id: str) -> Dict[str, Any]:
        if self.node_params['guide_word']:
            self.callback_manager.on_guide_word(
                data=GuideWordData(node_id=self.id, unique_id=unique_id, guide_word=self.node_params['guide_word']))
        if self.node_params['guide_question']:
            self.callback_manager.on_guide_question(
                data=GuideQuestionData(node_id=self.id, unique_id=unique_id,
                                       guide_question=self.node_params['guide_question']))

        logger.debug(f"jjxx StartNode _run node_data.v:{self.node_data.v} type_v:{type(self.node_data.v)} node_data:{self.node_data}")

        if not self.node_data.v:
            raise IgnoreException(f'{self.name} -- workflow node is update')

        # 预处理preset_question数据为dict
        new_preset_question = {}
        for one in self.node_params['preset_question']:
            new_preset_question[one['key']] = one['value']

        return {
            'current_time': self.node_params['current_time'],
            'user_info': self.node_params.get('user_info', ''),
            'chat_history': '',
            'preset_question': new_preset_question
        }

    def get_user_info(self):
        user_id = int(self.user_id)
        user = UserDao.get_user(int(self.user_id))
        if user:
            user_groups = UserGroupDao.get_user_group(user_id)
            all_groups = []
            if user_groups:
                for user_group in user_groups:
                    group = GroupDao.get_user_group(user_group.group_id)
                    if group:
                        sub_groups = []
                        parent_groups = GroupDao.get_parent_groups(group.code)
                        if parent_groups:
                            for parent_group in parent_groups:
                                sub_groups.append(parent_group.group_name)
                        sub_groups.append(group.group_name)
                        all_groups.append("/".join(sub_groups))

            group_str = ";".join(all_groups)

            return f"<user_info>\n用户名：{user.user_name}\n用户职位：{user.position}\n用户组织架构：{group_str}\n</user_info>"
        else:
            return f"<user_info></user_info>"


    def parse_log(self, unique_id: str, result: dict) -> Any:
        return [[
            {
                "key": "current_time",
                "value": result['current_time'],
                "type": "params"
            },
            {
                "key": "user_info",
                "value": result.get('user_info', ''),
                "type": "params"
            },
            {
                "key": "preset_question",
                "value": result['preset_question'],
                "type": "params"
            }
        ]]
