import datetime
import json
from typing import Any, Dict

from langchain.memory import ConversationBufferWindowMemory

from bisheng.chat.types import IgnoreException
from bisheng.database.models.group import GroupDao
from bisheng.database.models.role import RoleDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.workflow.callback.event import GuideQuestionData, GuideWordData
from bisheng.workflow.nodes.base import BaseNode


class StartNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize Current Time
        self.node_params['current_time'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # Initialize chat history
        self.graph_state.history_memory = ConversationBufferWindowMemory(
            k=self.node_params.get('chat_history', 10))
        self._user_info = None

    def _run(self, unique_id: str) -> Dict[str, Any]:
        if self._user_info is None and self.user_id:
            user_db = UserDao.get_user(int(self.user_id))
            user_group = UserGroupDao.get_user_group(int(self.user_id))
            groups = GroupDao.get_group_by_ids([group.group_id for group in user_group])
            group_dict = {group.id: group.group_name for group in groups}
            user_role = UserRoleDao.get_user_roles(int(self.user_id))
            roles = RoleDao.get_role_by_ids([role.role_id for role in user_role])
            user_roles = []
            for one in roles:
                if one.group_id not in group_dict.keys():
                    continue
                user_roles.append(f"{group_dict[one.group_id]}-{one.role_name}")
            if user_db:
                self._user_info = json.dumps({
                    "user_name": user_db.user_name,
                    "user_group": list(group_dict.values()),
                    "user_role": user_roles,
                }, ensure_ascii=False, indent=2)

        if self.node_params['guide_word']:
            self.callback_manager.on_guide_word(
                data=GuideWordData(node_id=self.id, name=self.name, unique_id=unique_id,
                                   guide_word=self.node_params['guide_word']))
        if self.node_params['guide_question']:
            self.callback_manager.on_guide_question(
                data=GuideQuestionData(node_id=self.id, name=self.name, unique_id=unique_id,
                                       guide_question=self.node_params['guide_question']))
        if not self.node_data.v:
            raise IgnoreException(f'{self.name} -- workflow node is update')

        # convert preset_question to dict
        new_preset_question = {}
        for one in self.node_params['preset_question']:
            new_preset_question[one['key']] = one['value']

        # convert custom vars to dict
        custom_vars = {}
        for one in self.node_params.get('custom_variables', []):
            custom_vars[one['key']] = one['value']
        return {
            'current_time': self.node_params['current_time'],
            'chat_history': '',
            'preset_question': new_preset_question,
            'user_info': self._user_info,
            'custom_variables': custom_vars
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
            },
            {
                "key": "user_info",
                "value": result['user_info'],
                "type": "params"
            }
        ]]
