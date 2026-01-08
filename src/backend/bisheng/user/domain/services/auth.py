import functools
import json
from datetime import datetime, timezone
from functools import cached_property
from typing import List, Dict, Any, Optional

import jwt
from fastapi import Request, Response, Depends
from pydantic import BaseModel, Field
from starlette.websockets import WebSocket
from typing_extensions import Self

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.exceptions.auth import JWTDecodeError
from bisheng.common.services.config_service import settings
from bisheng.database.constants import AdminRole
from bisheng.database.models.group import GroupDao
from bisheng.database.models.role_access import AccessType, RoleAccessDao
from bisheng.database.models.user_group import UserGroupDao
from ..models.user import User
from ..models.user_role import UserRoleDao


class AuthJwt:
    def __init__(self, req: Request = None, res: Response = None):
        self.req = req
        self.res = res
        self.jwt_secret = settings.jwt_secret
        self.cookie_conf = settings.cookie_conf
        self._access_cookie_key = "access_token_cookie"
        self._encode_algorithm = "HS256"
        self._decode_algorithms = [self._encode_algorithm]

    def create_access_token(self, subject: dict) -> str:
        """ create jwt token """
        if isinstance(subject, dict):
            subject = json.dumps(subject)
        payload = {
            'sub': subject,
            'exp': int(datetime.now(timezone.utc).timestamp()) + self.cookie_conf.jwt_token_expire_time,
            'iss': self.cookie_conf.jwt_iss
        }
        token = jwt.encode(payload, self.jwt_secret, algorithm=self._encode_algorithm)
        return token

    def set_access_token(self, token: str, response: Response = None, max_age: int = None) -> None:
        """ set jwt token to cookie """
        response = response or self.res
        response.set_cookie(
            self._access_cookie_key,
            token,
            max_age=max_age or self.cookie_conf.max_age,
            path=self.cookie_conf.path,
            domain=self.cookie_conf.domain,
            secure=self.cookie_conf.secure,
            httponly=self.cookie_conf.httponly,
            samesite=self.cookie_conf.samesite
        )

    def unset_access_token(self) -> None:
        self.res.delete_cookie(
            self._access_cookie_key,
            path=self.cookie_conf.path,
            domain=self.cookie_conf.domain
        )

    def get_subject(self,
                    auth_from: str = "request",
                    token: Optional[str] = None,
                    websocket: Optional[WebSocket] = None) -> Dict:
        """ decode jwt token """
        if auth_from == "request":
            if not token:
                token = self.req.cookies.get(self._access_cookie_key)
        elif auth_from == "websocket":
            if websocket:
                token = websocket.cookies.get(self._access_cookie_key)
        elif auth_from == "headers":
            if not token:
                token = self.req.headers.get("Authorization").split(" ")[-1]
        else:
            raise ValueError("unsupported auth_from value")
        return self.decode_jwt_token(token)

    def decode_jwt_token(self, token: str) -> Dict:
        """ decode jwt token """
        try:
            payload = jwt.decode(token, self.jwt_secret, issuer=self.cookie_conf.jwt_iss,
                                 algorithms=self._decode_algorithms)
            return json.loads(payload.get('sub'))
        except Exception as e:
            raise JWTDecodeError(status_code=422, message=str(e))


class LoginUser(BaseModel):
    user_id: int
    user_name: str = Field(default="")
    user_role: List[int] = Field(default_factory=list, description="Users GroupsIDVertical")
    group_cache: Dict[int, Any] = Field(default_factory=dict, description="User Group Cache")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.user_id = kwargs.get('user_id')
        self.user_name = kwargs.get('user_name')
        self.user_role = kwargs.get('user_role')
        self.group_cache = kwargs.get('group_cache', {})

        if not self.user_role:
            self.user_role = []
            user_role = UserRoleDao.get_user_roles(self.user_id)
            self.user_role = [user_role.role_id for user_role in user_role]

    @cached_property
    def _check_admin(self):
        if isinstance(self.user_role, list):
            for one in self.user_role:
                if one == AdminRole:
                    return True
        return False

    def is_admin(self):
        return self._check_admin

    @staticmethod
    def wrapper_access_check(func):
        """
        Decorator for permissions check
        ifadminThe user does not perform subsequent specific check logic
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
        Decorator for asynchronous permission checking
        ifadminThe user does not perform subsequent specific check logic
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
            Check if the user has permission to a resource
        """
        # Determine if it belongs to my resource
        if self.user_id == owner_user_id:
            return True
        # Judgment Authorization
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
            Check if the user has permission to copy a resource
        """
        # Determine if it belongs to my resource
        if self.user_id == owner_user_id:
            return True
        return False

    @wrapper_access_check
    def check_group_admin(self, group_id: int) -> bool:
        """
            Check if the user is an administrator of a group
        """
        # Determine if you are an administrator of a user group
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
            Asynchronously check if the user is an administrator of a group
        """
        # Determine if you are an administrator of a user group
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
        Check if the user is an administrator in the user group list, one of which istrue
        """
        user_groups = UserGroupDao.get_user_admin_group(self.user_id)
        for one in user_groups:
            if one.is_group_admin and one.group_id in group_ids:
                return True
        return False

    def get_user_groups(self, user_id: int) -> List[Dict]:
        """ Query a list of roles for a user """
        user_groups = UserGroupDao.get_user_group(user_id)
        user_group_ids: List[int] = [one_group.group_id for one_group in user_groups]
        res = []
        for i in range(len(user_group_ids) - 1, -1, -1):
            if self.group_cache.get(user_group_ids[i]):
                res.append(self.group_cache.get(user_group_ids[i]))
                del user_group_ids[i]
        # Query database for role information without caching
        if user_group_ids:
            group_list = GroupDao.get_group_by_ids(user_group_ids)
            for group_info in group_list:
                self.group_cache[group_info.id] = {'id': group_info.id, 'name': group_info.group_name}
                res.append(self.group_cache.get(group_info.id))
        return res

    async def get_user_group_ids(self, user_id: int = None):
        if user_id is None:
            user_id = self.user_id
        user_groups = await UserGroupDao.aget_user_group(user_id)
        return [one_group.group_id for one_group in user_groups]

    def get_user_access_resource_ids(self, access_types: List[AccessType]) -> List[str]:
        """ Query resources for which the user has the corresponding permissionsIDVertical """
        role_access = RoleAccessDao.get_role_access_batch(self.user_role, access_types)
        return list(set([one.third_id for one in role_access]))

    async def aget_user_access_resource_ids(self, access_types: List[AccessType]) -> List[str]:
        """ Resources with corresponding permissions for asynchronous query usersIDVertical """
        role_access = await RoleAccessDao.aget_role_access_batch(self.user_role, access_types)
        return list(set([one.third_id for one in role_access]))

    # some methods related to AuthJwt
    @classmethod
    def create_access_token(cls, user: User, auth_jwt: AuthJwt) -> str:
        """ Create access for userstoken """
        payload = {
            'user_id': user.user_id,
            'user_name': user.user_name
        }
        token = auth_jwt.create_access_token(subject=payload)
        return token

    @classmethod
    def set_access_cookies(cls, token: str, auth_jwt: AuthJwt, **kwargs) -> None:
        """ set access token into cookie """
        auth_jwt.set_access_token(token, **kwargs)

    @classmethod
    def unset_access_cookies(cls, auth_jwt: AuthJwt) -> None:
        auth_jwt.unset_access_token()

    @classmethod
    async def init_login_user(cls, user_id: int, user_name: str) -> Self:
        user_roles = await UserRoleDao.aget_user_roles(user_id)
        role_ids = [user_role.role_id for user_role in user_roles]
        login_user = cls(user_id=user_id, user_name=user_name, user_role=role_ids)
        return login_user

    @classmethod
    def init_login_user_sync(cls, user_id: int, user_name: str) -> Self:
        user_roles = UserRoleDao.get_user_roles(user_id)
        role_ids = [user_role.role_id for user_role in user_roles]
        login_user = cls(user_id=user_id, user_name=user_name, user_role=role_ids)
        return login_user

    @classmethod
    async def get_login_user(cls, auth_jwt: AuthJwt = Depends()) -> Self:
        subject = auth_jwt.get_subject()
        return await cls.init_login_user(user_id=subject['user_id'], user_name=subject['user_name'])

    @classmethod
    async def get_admin_user(cls, auth_jwt: AuthJwt = Depends()) -> Self:
        login_user = await cls.get_login_user(auth_jwt)
        if not login_user.is_admin():
            raise UnAuthorizedError.http_exception()
        return login_user

    @classmethod
    async def get_login_user_from_ws(cls, websocket: WebSocket, auth_jwt: AuthJwt = Depends(), t: str = None) -> Self:
        subject = auth_jwt.get_subject(auth_from="websocket", websocket=websocket, token=t)
        return await cls.init_login_user(user_id=subject['user_id'], user_name=subject['user_name'])

    @classmethod
    async def get_admin_user_from_ws(cls, websocket: WebSocket, auth_jwt: AuthJwt = Depends(), t: str = None) -> Self:
        login_user = await cls.get_login_user_from_ws(websocket, auth_jwt, t)
        if not login_user.is_admin():
            raise UnAuthorizedError.http_exception()
        return login_user

    @classmethod
    async def get_roles_web_menu(cls, user: User) -> (List[int] | str, List[str]):
        """ get user roles and web menu """
        db_user_role = await UserRoleDao.aget_user_roles(user.user_id)
        role = ''
        role_ids = []
        for user_role in db_user_role:
            if user_role.role_id == AdminRole:
                role = 'admin'
            else:
                role_ids.append(user_role.role_id)
        if role != 'admin':
            # is user group admin ?
            db_user_groups = await UserGroupDao.aget_user_admin_group(user.user_id)
            if len(db_user_groups) > 0:
                role = 'group_admin'
            else:
                role = role_ids
        # Get a list of a user's menu bar permissions
        web_menu = await RoleAccessDao.aget_role_access(role_ids, AccessType.WEB_MENU)
        web_menu = list(set([one.third_id for one in web_menu]))

        return role, web_menu
