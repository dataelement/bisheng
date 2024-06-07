from bisheng.database.models.assistant import Assistant, AssistantDao
from bisheng.database.models.flow import Flow, FlowDao, FlowRead
from bisheng.database.models.knowledge import Knowledge, KnowledgeDao, KnowledgeRead
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user import UserDao


class UserPayload:

    def __init__(self, **kwargs):
        self.user_id = kwargs.get('user_id')
        self.user_role = kwargs.get('role')

    def is_admin(self):
        return self.user_role == 'admin'

    def access_check(self, owner_user_id: int, target_id: str, access_type: AccessType) -> bool:
        if self.is_admin():
            return True
        # 判断是否属于本人资源
        if self.user_id == owner_user_id:
            return True
        # 判断授权
        if RoleAccessDao.judge_role_access(self.user_role, target_id, access_type):
            return True
        return False


def sso_login():

    pass


def get_knowledge_list_by_access(role_id: int, name: str, page_num: int, page_size: int):

    count_filter = []
    if name:
        count_filter.append(Knowledge.name.like('%{}%'.format(name)))

    db_role_access = KnowledgeDao.get_knowledge_by_access(role_id, page_num, page_size)
    total_count = KnowledgeDao.get_count_by_filter(count_filter)
    # 补充用户名
    user_ids = [access[0].user_id for access in db_role_access]
    db_users = UserDao.get_user_by_ids(user_ids)
    user_dict = {user.user_id: user.user_name for user in db_users}

    return {
        'data': [
            KnowledgeRead.validate({
                'name': access[0].name,
                'user_name': user_dict.get(access[0].user_id),
                'user_id': access[0].user_id,
                'update_time': access[0].update_time,
                'id': access[0].id
            }) for access in db_role_access
        ],
        'total':
        total_count
    }


def get_flow_list_by_access(role_id: int, name: str, page_num: int, page_size: int):

    count_filter = []
    if name:
        count_filter.append(Flow.name.like('%{}%'.format(name)))

    db_role_access = FlowDao.get_flow_by_access(role_id, name, page_num, page_size)
    total_count = FlowDao.get_count_by_filters(count_filter)
    # 补充用户名
    user_ids = [access[0].user_id for access in db_role_access]
    db_users = UserDao.get_user_by_ids(user_ids)
    user_dict = {user.user_id: user.user_name for user in db_users}

    return {
        'data': [
            FlowRead.validate({
                'name': access[0].name,
                'user_name': user_dict.get(access[0].user_id),
                'user_id': access[0].user_id,
                'update_time': access[0].update_time,
                'id': access[0].id
            }) for access in db_role_access
        ],
        'total':
        total_count
    }


def get_assistant_list_by_access(role_id: int, name: str, page_num: int, page_size: int):

    count_filter = []
    if name:
        count_filter.append(Assistant.name.like('%{}%'.format(name)))

    db_role_access = AssistantDao.get_assistants_by_access(role_id, name, page_size, page_num)
    total_count = AssistantDao.get_count_by_filters(count_filter)
    # 补充用户名
    user_ids = [access[0].user_id for access in db_role_access]
    db_users = UserDao.get_user_by_ids(user_ids)
    user_dict = {user.user_id: user.user_name for user in db_users}

    return {
        'data': [{
            'name': access[0].name,
            'user_name': user_dict.get(access[0].user_id),
            'user_id': access[0].user_id,
            'update_time': access[0].update_time,
            'id': access[0].id
        } for access in db_role_access],
        'total':
        total_count
    }
