from bisheng.database.models.assistant import Assistant, AssistantDao
from bisheng.database.models.flow import Flow, FlowDao, FlowRead
from bisheng.database.models.knowledge import Knowledge, KnowledgeDao, KnowledgeRead
from bisheng.database.models.user import UserDao


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

    db_role_access = AssistantDao.get_assistants_by_access(role_id, name, page_num, page_size)
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
