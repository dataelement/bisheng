import functools
import json
from base64 import b64decode
from typing import List, Dict

import rsa
from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.errcode.user import (UserLoginOfflineError, UserNameAlreadyExistError,
                                      UserNeedGroupAndRoleError)
from bisheng.api.JWT import ACCESS_TOKEN_EXPIRE_TIME
from bisheng.api.utils import md5_hash
from bisheng.api.v1.schemas import CreateUserReq
from bisheng.cache.redis import redis_client
from bisheng.database.models.assistant import Assistant, AssistantDao
from bisheng.database.models.flow import Flow, FlowDao, FlowRead
from bisheng.database.models.group import GroupDao
from bisheng.database.models.knowledge import Knowledge, KnowledgeDao, KnowledgeRead
from bisheng.database.models.role import AdminRole, RoleDao
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user import User, UserDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.user_role import UserRoleDao
from bisheng.settings import settings
from bisheng.utils.constants import RSA_KEY, USER_CURRENT_SESSION
from fastapi import Depends, HTTPException, Request
from fastapi_jwt_auth import AuthJWT


class UserPayload:

    def __init__(self, **kwargs):
        self.user_id = kwargs.get('user_id')
        self.user_role = kwargs.get('role')
        self.group_cache = {}
        self.role_cache = {}
        self.bind_role_cache = {}
        self.user_name = kwargs.get('user_name')

        if self.user_role != 'admin':  # 非管理员用户，需要获取他的角色列表
            roles = UserRoleDao.get_user_roles(self.user_id)
            self.user_role = [one.role_id for one in roles]
            user_groups = UserGroupDao.get_user_group(self.user_id)
            group_bind_roles = self.get_group_bind_role([one.group_id for one in user_groups])
            self.user_role.extend([one['id'] for one in group_bind_roles])

    def is_admin(self):
        if self.user_role == 'admin':
            return True
        if isinstance(self.user_role, list):
            for one in self.user_role:
                if one == AdminRole:
                    return True
        return False

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
    def copiable_check(self, owner_user_id: int) -> bool:
        """
            检查用户是否有某个资源复制权限
        """
        # 判断是否属于本人资源
        if self.user_id == owner_user_id:
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

    def get_user_groups(self, user_id: int) -> List[Dict]:
        """ 查询用户的角色列表 """
        user_groups = UserGroupDao.get_user_group(user_id)
        user_group_ids: List[int] = [one_group.group_id for one_group in user_groups]
        res = []
        for i in range(len(user_group_ids) - 1, -1, -1):
            if self.group_cache.get(user_group_ids[i]):
                res.append(self.group_cache.get(user_group_ids[i]))
                del user_group_ids[i]
        # 将没有缓存的角色信息查询数据库
        if user_group_ids:
            group_list = GroupDao.get_group_by_ids(user_group_ids)
            for group_info in group_list:
                self.group_cache[group_info.id] = {'id': group_info.id, 'name': group_info.group_name}
                res.append(self.group_cache.get(group_info.id))
        return res

    def get_user_roles(self, user_id: int) -> List[Dict]:
        """ 查询用户的角色列表 """
        user_roles = UserRoleDao.get_user_roles(user_id)
        user_role_ids: List[int] = [one_role.role_id for one_role in user_roles]
        res = []
        for i in range(len(user_role_ids) - 1, -1, -1):
            if self.role_cache.get(user_role_ids[i]):
                res.append(self.role_cache.get(user_role_ids[i]))
                del user_role_ids[i]
        # 将没有缓存的角色信息查询数据库
        if user_role_ids:
            role_list = RoleDao.get_role_by_ids(user_role_ids)
            for role_info in role_list:
                self.role_cache[role_info.id] = {
                    "id": role_info.id,
                    "group_id": role_info.group_id,
                    "name": role_info.role_name,
                    "is_bind_all": role_info.is_bind_all
                }
                res.append(self.role_cache.get(role_info.id))
        return res

    def get_group_bind_role(self, groups: list[int]) -> List[Dict]:
        """ 获取组的绑定角色 """
        res = {}
        for group_id in groups:
            if group_id not in self.bind_role_cache:
                bind_roles = RoleDao.get_role_by_groups([group_id], None, 0, 0, include_parent=True, only_bind=True)
                self.bind_role_cache[group_id] = bind_roles
            for role in self.bind_role_cache[group_id]:
                res[role.id] = {
                    'id': role.id,
                    'name': role.role_name,
                    'group_id': role.group_id,
                    'is_bind_all': role.is_bind_all
                }
        return list(res.values())


class UserService:

    @classmethod
    def decrypt_md5_password(cls, password: str):
        if value := redis_client.get(RSA_KEY):
            private_key = value[1]
            password = md5_hash(rsa.decrypt(b64decode(password), private_key).decode('utf-8'))
        else:
            password = md5_hash(password)
        return password

    @classmethod
    def create_user(cls, request: Request, login_user: UserPayload, req_data: CreateUserReq):
        """
        创建用户
        """
        exists_user = UserDao.get_user_by_username(req_data.user_name)
        if exists_user:
            # 抛出异常
            raise UserNameAlreadyExistError.http_exception()
        user = User(
            user_name=req_data.user_name,
            password=cls.decrypt_md5_password(req_data.password),
        )
        group_ids = []
        role_ids = []
        for one in req_data.group_roles:
            group_ids.append(one.group_id)
            role_ids.extend(one.role_ids)
        if not group_ids:
            raise UserNeedGroupAndRoleError.http_exception()
        user = UserDao.add_user_with_groups_and_roles(user, group_ids, role_ids)
        return user


def sso_login():
    pass


def gen_user_role(db_user: User):
    # 查询用户的角色列表
    db_user_role = UserRoleDao.get_user_roles(db_user.user_id)
    role = ''
    role_ids = []
    for user_role in db_user_role:
        if user_role.role_id == 1:
            # 是管理员，忽略其他的角色
            role = 'admin'
        else:
            role_ids.append(user_role.role_id)
    if role != 'admin':
        user_groups = UserGroupDao.get_user_group(db_user.user_id)
        if user_groups:
            groups_roles = RoleDao.get_role_by_groups([one.group_id for one in user_groups], include_parent=True, only_bind=True)
            role_ids.extend([one.id for one in groups_roles])
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
    access_token = AuthJWT().create_access_token(subject=json.dumps(payload),
                                                 expires_time=ACCESS_TOKEN_EXPIRE_TIME)

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
        # 登录被挤下线了，http状态码是200, status_code是特殊code
        if current_token != authorize._token:
            raise UserLoginOfflineError.http_exception()
    return user


async def get_admin_user(authorize: AuthJWT = Depends()) -> UserPayload:
    """
    获取超级管理账号，非超级管理员用户，抛出异常
    """
    login_user = await get_login_user(authorize)
    if not login_user.is_admin():
        raise UnAuthorizedError.http_exception()
    return login_user
