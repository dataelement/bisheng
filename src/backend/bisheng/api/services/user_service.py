import json

import functools
from typing import List

from bisheng.api.JWT import ACCESS_TOKEN_EXPIRE_TIME
from bisheng.cache.redis import redis_client
from bisheng.database.models.assistant import Assistant, AssistantDao
from bisheng.database.models.flow import Flow, FlowDao, FlowRead
from bisheng.database.models.knowledge import Knowledge, KnowledgeDao, KnowledgeRead
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user import User, UserDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.user_role import UserRoleDao
from fastapi import HTTPException, Depends
from fastapi_jwt_auth import AuthJWT

from bisheng.settings import settings
from bisheng.utils.constants import USER_CURRENT_SESSION


class UserPayload:

    def __init__(self, **kwargs):
        self.user_id = kwargs.get('user_id')
        self.user_role = kwargs.get('role')
        if self.user_role != 'admin':  # 非管理员用户，需要获取他的角色列表
            roles = UserRoleDao.get_user_roles(self.user_id)
            self.user_role = [one.role_id for one in roles]
        self.user_name = kwargs.get('user_name')

    def is_admin(self):
        return self.user_role == 'admin'

    @staticmethod
    def wrapper_access_check(func):
        """
        权限检查的装饰器
        如果是admin用户则不执行后续具体的检查逻辑
        """

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if args[0].is_admin():
                return True
            return func(*args, **kwargs)

        return wrapper

    @wrapper_access_check
    def access_check(self, owner_user_id: int, target_id: str, access_type: AccessType) -> bool:
        """
            检查用户是否有某个资源的权限
        """
        # 判断是否属于本人资源
        if self.user_id == owner_user_id:
            return True
        # 判断授权
        if RoleAccessDao.judge_role_access(self.user_role, target_id, access_type):
            return True
        return False

    @wrapper_access_check
    def check_group_admin(self, group_id: int) -> bool:
        """
            检查用户是否是某个组的管理员
        """
        # 判断是否是用户组的管理员
        user_group = UserGroupDao.get_user_admin_group(self.user_id)
        if not user_group:
            return False
        for one in user_group:
            if one.group_id == group_id:
                return True
        return False

    @wrapper_access_check
    def check_groups_admin(self, group_ids: List[int]) -> bool:
        """
        检查用户是否是用户组列表中的管理员，有一个就是true
        """
        user_groups = UserGroupDao.get_user_admin_group(self.user_id)
        for one in user_groups:
            if one.is_group_admin and one.group_id in group_ids:
                return True
        return False


def sso_login():
    pass


def gen_user_role(db_user: User):
    # 查询用户的角色列表
    db_user_role = UserRoleDao.get_user_roles(db_user.user_id)
    role = ""
    role_ids = []
    for user_role in db_user_role:
        if user_role.role_id == 1:
            # 是管理员，忽略其他的角色
            role = 'admin'
        else:
            role_ids.append(user_role.role_id)
    if role != "admin":
        # 判断是否是用户组管理员
        db_user_groups = UserGroupDao.get_user_admin_group(db_user.user_id)
        if len(db_user_groups) > 0:
            role = 'group_admin'
        else:
            role = role_ids
    # 获取用户的菜单栏权限列表
    web_menu = RoleAccessDao.get_role_access(role_ids, AccessType.WEB_MENU)
    web_menu = list(set([one.third_id for one in web_menu]))
    return role, web_menu


def gen_user_jwt(db_user: User):
    if 1 == db_user.delete:
        raise HTTPException(status_code=500, detail='该账号已被禁用，请联系管理员')
    # 查询角色
    role, web_menu = gen_user_role(db_user)
    # 生成JWT令牌
    payload = {'user_name': db_user.user_name, 'user_id': db_user.user_id, 'role': role}
    # Create the tokens and passing to set_access_cookies or set_refresh_cookies
    access_token = AuthJWT().create_access_token(subject=json.dumps(payload), expires_time=ACCESS_TOKEN_EXPIRE_TIME)

    refresh_token = AuthJWT().create_refresh_token(subject=db_user.user_name)

    # Set the JWT cookies in the response
    return access_token, refresh_token, role, web_menu


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


async def get_login_user(authorize: AuthJWT = Depends()) -> UserPayload:
    """
    获取当前登录的用户
    """
    # 校验是否过期，过期则直接返回http 状态码的 401
    authorize.jwt_required()

    current_user = json.loads(authorize.get_jwt_subject())
    user = UserPayload(**current_user)

    # 判断是否允许多点登录
    if not settings.get_system_login_method().allow_multi_login:
        # 获取access_token
        current_token = redis_client.get(USER_CURRENT_SESSION.format(user.user_id))
        # 登录被挤下线了，状态码是200， 内部的status_code是403
        if current_token != authorize._token:
            raise HTTPException(status_code=403,
                                detail='您的账户已在另一设备上登录，此设备上的会话已被注销。\n如果这不是您本人的操作，请尽快修改您的账户密码。')
    return user
