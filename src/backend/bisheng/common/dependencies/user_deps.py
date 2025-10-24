import functools
import json
from typing import List, Dict

from fastapi import Depends

from bisheng.cache.redis import redis_client
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.user import UserLoginOfflineError
from bisheng.database.constants import AdminRole
from bisheng.database.models.group import GroupDao
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.user_role import UserRoleDao
from bisheng.settings import settings
from bisheng.utils.constants import USER_CURRENT_SESSION
from fastapi_jwt_auth import AuthJWT


class UserPayload:

    def __init__(self, **kwargs):
        self.user_id = kwargs.get('user_id')
        self.user_role = kwargs.get('role')
        self.group_cache = {}
        if self.user_role != 'admin':  # 非管理员用户，需要获取他的角色列表
            roles = UserRoleDao.get_user_roles(self.user_id)
            self.user_role = [one.role_id for one in roles]
        self.user_name = kwargs.get('user_name')

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

    @staticmethod
    def async_wrapper_access_check(func):
        """
        异步权限检查的装饰器
        如果是admin用户则不执行后续具体的检查逻辑
        """

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if args[0].is_admin():
                return True
            return await func(*args, **kwargs)

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

    @async_wrapper_access_check
    async def async_access_check(self, owner_user_id: int, target_id: str, access_type: AccessType) -> bool:
        if self.user_id == owner_user_id:
            return True
        flag = await RoleAccessDao.ajudge_role_access(self.user_role, target_id, access_type)
        return True if flag else False

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

    @async_wrapper_access_check
    async def async_check_group_admin(self, group_id: int) -> bool:
        """
            异步检查用户是否是某个组的管理员
        """
        # 判断是否是用户组的管理员
        user_group = await UserGroupDao.aget_user_admin_group(self.user_id, group_id)
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

    def get_user_access_resource_ids(self, access_types: List[AccessType]) -> List[str]:
        """ 查询用户有对应权限的资源ID列表 """
        user_role = UserRoleDao.get_user_roles(self.user_id)
        role_ids = [role.role_id for role in user_role]
        role_access = RoleAccessDao.get_role_access_batch(role_ids, access_types)
        return list(set([one.third_id for one in role_access]))


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
