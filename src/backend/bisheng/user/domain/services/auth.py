import asyncio
import functools
import json
import logging
from datetime import datetime, timezone
from functools import cached_property
from typing import List, Dict, Any, Optional, Tuple, Iterable

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
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.role_access import AccessType, RoleAccessDao, WebMenuResource
from bisheng.database.models.user_group import UserGroupDao
from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from ..models.user import User, UserDao
from ..models.user_role import UserRoleDao

logger = logging.getLogger(__name__)

# 部门管理员：工作台 + 管理后台全量菜单（含路由用的 sys、仅 UI 的 log/system_config）
_DEPARTMENT_ADMIN_WEB_MENU_FULL = frozenset(
    {e.value for e in WebMenuResource}
    | {'log', 'system_config', 'sys'}
)

# ── AccessType → ReBAC mapping (F008, AD-02) ────────────────
# Maps old RBAC AccessType to one-or-more (relation, object_type) pairs for
# ReBAC delegation. Knowledge libraries are migrating from the historical
# knowledge_space object type to the dedicated knowledge_library type, so the
# adapter must temporarily accept both.
_ACCESS_TYPE_TO_REBAC: Dict[int, Tuple[Tuple[str, str], ...]] = {
    AccessType.KNOWLEDGE: (
        ('can_read', 'knowledge_library'),
        ('can_read', 'knowledge_space'),
    ),
    AccessType.KNOWLEDGE_WRITE: (
        ('can_edit', 'knowledge_library'),
        ('can_edit', 'knowledge_space'),
    ),
    AccessType.WORKFLOW: (('can_read', 'workflow'),),
    AccessType.WORKFLOW_WRITE: (('can_edit', 'workflow'),),
    AccessType.ASSISTANT_READ: (('can_read', 'assistant'),),
    AccessType.ASSISTANT_WRITE: (('can_edit', 'assistant'),),
    AccessType.GPTS_TOOL_READ: (('can_read', 'tool'),),
    AccessType.GPTS_TOOL_WRITE: (('can_edit', 'tool'),),
    AccessType.DASHBOARD: (('can_read', 'dashboard'),),
    AccessType.DASHBOARD_WRITE: (('can_edit', 'dashboard'),),
}


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
    tenant_id: int = Field(default=1, description="Current tenant ID")
    # v2.5.1 F012: JWT invalidation counter carried from JWT payload.
    # Middleware compares this against user.token_version and rejects
    # stale tokens (AC-09). Defaults to 0 so v2.5.0 JWTs still decode.
    token_version: int = Field(
        default=0, description='JWT invalidation counter (F012)',
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.user_id = kwargs.get('user_id')
        self.user_name = kwargs.get('user_name')
        self.user_role = kwargs.get('user_role')
        self.group_cache = kwargs.get('group_cache', {})
        self.tenant_id = kwargs.get('tenant_id', DEFAULT_TENANT_ID)
        # token_version is validated by Pydantic Field(default=0) above.

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
        """Check if the user has permission to a resource.

        F008 adapter: delegates to ReBAC (rebac_check) for mapped AccessType values.
        Falls back to legacy RoleAccessDao for unmapped types (backward compat).
        """
        rebac_targets = self._rebac_targets_for_access_type(access_type)
        if rebac_targets:
            from bisheng.permission.domain.services.owner_service import _run_async_safe
            return any(
                _run_async_safe(self.rebac_check(relation, object_type, str(target_id)))
                for relation, object_type in rebac_targets
            )

        # Legacy fallback for unmapped AccessType
        if self.user_id == owner_user_id:
            return True
        if RoleAccessDao.judge_role_access(self.user_role, target_id, access_type):
            return True
        return False

    @async_wrapper_access_check
    async def async_access_check(self, owner_user_id: int, target_id: str, access_type: AccessType) -> bool:
        """Async permission check — delegates to ReBAC for mapped types."""
        rebac_targets = self._rebac_targets_for_access_type(access_type)
        if rebac_targets:
            results = await asyncio.gather(*[
                self.rebac_check(relation, object_type, str(target_id))
                for relation, object_type in rebac_targets
            ])
            return any(results)

        # Legacy fallback for unmapped AccessType
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

    async def get_user_groups(self, user_id: int) -> List[Dict]:
        """ Query a list of roles for a user """
        user_groups = await UserGroupDao.aget_user_group(user_id)
        user_group_ids: List[int] = [one_group.group_id for one_group in user_groups]
        res = []
        for i in range(len(user_group_ids) - 1, -1, -1):
            if self.group_cache.get(user_group_ids[i]):
                res.append(self.group_cache.get(user_group_ids[i]))
                del user_group_ids[i]
        # Query database for role information without caching
        if user_group_ids:
            group_list = await GroupDao.aget_group_by_ids(user_group_ids)
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
        """Query accessible resource IDs.

        F008 adapter: delegates to ReBAC list_accessible for mapped AccessType.
        Falls back to legacy RoleAccessDao for unmapped types.
        """
        rebac_targets = self._rebac_targets_for_access_types(access_types)
        if rebac_targets:
            from bisheng.permission.domain.services.owner_service import _run_async_safe

            merged: Dict[str, None] = {}
            for relation, object_type in rebac_targets:
                ids = _run_async_safe(self.rebac_list_accessible(relation, object_type)) or []
                for rid in ids:
                    merged[str(rid)] = None
            return list(merged.keys())

        # Legacy fallback
        role_access = RoleAccessDao.get_role_access_batch(self.user_role, access_types)
        return list(set([one.third_id for one in role_access]))

    async def aget_user_access_resource_ids(self, access_types: List[AccessType]) -> List[str]:
        """Async version — delegates to ReBAC for mapped types."""
        rebac_targets = self._rebac_targets_for_access_types(access_types)
        if rebac_targets:
            merged: Dict[str, None] = {}
            results = await asyncio.gather(*[
                self.rebac_list_accessible(relation, object_type)
                for relation, object_type in rebac_targets
            ])
            for ids in results:
                for rid in ids or []:
                    merged[str(rid)] = None
            return list(merged.keys())

        # Legacy fallback
        role_access = await RoleAccessDao.aget_role_access_batch(self.user_role, access_types)
        return list(set([one.third_id for one in role_access]))

    def get_merged_rebac_app_resource_ids(self, *, for_write: bool = False) -> List[str]:
        """合并 workflow + assistant 的 ReBAC 可见 ID（构建/工作台应用列表）。

        ⚠️ 仅供 async 调用方使用 sync 适配器时兜底。新代码请用
        ``aget_merged_rebac_app_resource_ids``：在 FastAPI 的 sync endpoint
        线程池里新建 event loop 调 FGAClient 会跨 loop 失败，导致部门管理员
        看不到下属创建的应用。
        """
        from bisheng.permission.domain.services.owner_service import _run_async_safe

        relation = 'can_edit' if for_write else 'can_read'
        wf_ids = _run_async_safe(self.rebac_list_accessible(relation, 'workflow'))
        asst_ids = _run_async_safe(self.rebac_list_accessible(relation, 'assistant'))
        wf_ids = wf_ids or []
        asst_ids = asst_ids or []
        return list(set(wf_ids) | set(asst_ids))

    async def aget_merged_rebac_app_resource_ids(
        self, *, for_write: bool = False,
    ) -> List[str]:
        """async 版本：合并 workflow + assistant 的 ReBAC 可见 ID。"""
        relation = 'can_edit' if for_write else 'can_read'
        wf_ids = await self.rebac_list_accessible(relation, 'workflow')
        asst_ids = await self.rebac_list_accessible(relation, 'assistant')
        return list(set(wf_ids or []) | set(asst_ids or []))

    # ── ReBAC permission methods (F004, INV-3) ─────────────────

    async def rebac_check(self, relation: str, object_type: str, object_id: str) -> bool:
        """ReBAC permission check — unified entry point for resource-level access.

        Delegates to PermissionService.check() which implements the five-level chain:
        L1 admin → L2 cache → L3 OpenFGA → L4 owner fallback → L5 fail-closed.
        """
        from bisheng.permission.domain.services.permission_service import PermissionService
        return await PermissionService.check(
            user_id=self.user_id,
            relation=relation,
            object_type=object_type,
            object_id=object_id,
            login_user=self,
        )

    async def rebac_list_accessible(self, relation: str, object_type: str) -> Optional[List[str]]:
        """List accessible resource IDs via ReBAC.

        Returns None for admin (caller should not filter).
        Returns list of ID strings for normal users.
        """
        from bisheng.permission.domain.services.permission_service import PermissionService
        return await PermissionService.list_accessible_ids(
            user_id=self.user_id,
            relation=relation,
            object_type=object_type,
            login_user=self,
        )

    @staticmethod
    def _rebac_targets_for_access_type(access_type: AccessType) -> Tuple[Tuple[str, str], ...]:
        return _ACCESS_TYPE_TO_REBAC.get(access_type, ())

    @classmethod
    def _rebac_targets_for_access_types(
        cls, access_types: Iterable[AccessType],
    ) -> List[Tuple[str, str]]:
        merged: Dict[Tuple[str, str], None] = {}
        for access_type in access_types:
            for pair in cls._rebac_targets_for_access_type(access_type):
                merged[pair] = None
        return list(merged.keys())

    # some methods related to AuthJwt
    @classmethod
    def create_access_token(
        cls,
        user: User,
        auth_jwt: AuthJwt,
        tenant_id: int = None,
        token_version: int = None,
    ) -> str:
        """Create access token for user with tenant_id + token_version.

        v2.5.1 F012: ``token_version`` is read from the user row (falls back to
        ``getattr(user, 'token_version', 0)`` so v2.5.0 tests that build a
        bare User pydantic model without that field still work). Embedded in
        the JWT so the middleware can invalidate stale tokens.
        """
        if token_version is None:
            token_version = int(getattr(user, 'token_version', 0) or 0)
        payload = {
            'user_id': user.user_id,
            'user_name': user.user_name,
            'tenant_id': tenant_id or DEFAULT_TENANT_ID,
            'token_version': token_version,
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
    async def init_login_user(
        cls,
        user_id: int,
        user_name: str,
        tenant_id: int = None,
        token_version: int = 0,
    ) -> Self:
        user_roles = await UserRoleDao.aget_user_roles(user_id)
        role_ids = [user_role.role_id for user_role in user_roles]
        login_user = cls(
            user_id=user_id, user_name=user_name, user_role=role_ids,
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
            token_version=token_version,
        )
        return login_user

    @classmethod
    def init_login_user_sync(
        cls,
        user_id: int,
        user_name: str,
        tenant_id: int = None,
        token_version: int = 0,
    ) -> Self:
        user_roles = UserRoleDao.get_user_roles(user_id)
        role_ids = [user_role.role_id for user_role in user_roles]
        login_user = cls(
            user_id=user_id, user_name=user_name, user_role=role_ids,
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
            token_version=token_version,
        )
        return login_user

    @classmethod
    async def get_login_user(cls, auth_jwt: AuthJwt = Depends()) -> Self:
        subject = auth_jwt.get_subject()
        return await cls.init_login_user(
            user_id=subject['user_id'],
            user_name=subject['user_name'],
            tenant_id=subject.get('tenant_id', DEFAULT_TENANT_ID),
            token_version=int(subject.get('token_version', 0) or 0),
        )

    @classmethod
    async def get_admin_user(cls, auth_jwt: AuthJwt = Depends()) -> Self:
        login_user = await cls.get_login_user(auth_jwt)
        if not login_user.is_admin():
            raise UnAuthorizedError.http_exception()
        return login_user

    @classmethod
    async def get_model_admin_user(cls, auth_jwt: AuthJwt = Depends()) -> Self:
        """Allow model-management access to super admins or users with model menu."""
        login_user = await cls.get_login_user(auth_jwt)
        if login_user.is_admin():
            return login_user
        await cls.assert_effective_web_menu_contains(login_user.user_id, 'model')
        return login_user

    @classmethod
    async def get_login_user_from_ws(cls, websocket: WebSocket, auth_jwt: AuthJwt = Depends(), t: str = None) -> Self:
        subject = auth_jwt.get_subject(auth_from="websocket", websocket=websocket, token=t)
        return await cls.init_login_user(
            user_id=subject['user_id'],
            user_name=subject['user_name'],
            tenant_id=subject.get('tenant_id', DEFAULT_TENANT_ID),
            token_version=int(subject.get('token_version', 0) or 0),
        )

    @classmethod
    async def get_admin_user_from_ws(cls, websocket: WebSocket, auth_jwt: AuthJwt = Depends(), t: str = None) -> Self:
        login_user = await cls.get_login_user_from_ws(websocket, auth_jwt, t)
        if not login_user.is_admin():
            raise UnAuthorizedError.http_exception()
        return login_user

    @classmethod
    async def get_roles_web_menu(
        cls,
        user: User,
        *,
        is_department_admin: bool = False,
    ) -> (List[int] | str, List[str]):
        """Resolve role key(s) and web_menu.

        - AC-13: multi-role web_menu is the **union** of each role's WEB_MENU entries.
        - Department admins get workstation + admin console menus in full (PRD 2.5).
        - ``system_config`` is only granted via super-admin or department-admin; it is
          stripped for other users even if legacy role_access rows exist.
        """
        db_user_role = await UserRoleDao.aget_user_roles(user.user_id)
        role = ''
        role_ids = []
        for user_role in db_user_role:
            if user_role.role_id == AdminRole:
                role = 'admin'
            else:
                role_ids.append(user_role.role_id)
        if role != 'admin':
            role = role_ids
            # AC-13: union of all roles' menu permissions
            web_menu = await RoleAccessDao.aget_role_access(role_ids, AccessType.WEB_MENU)
            web_menu = list({one.third_id for one in web_menu})
            if is_department_admin:
                web_menu = list(set(web_menu) | set(_DEPARTMENT_ADMIN_WEB_MENU_FULL))
            else:
                web_menu = [m for m in web_menu if m not in ('system_config', 'sys')]
        else:
            # AC-14: admin returns all WebMenuResource values (including deprecated for compat)
            web_menu = [one.value for one in WebMenuResource]
        return role, web_menu

    @classmethod
    async def assert_effective_web_menu_contains(cls, user_id: int, menu_key: str) -> None:
        """Raise if user's effective web_menu (after dept-admin merge) does not include ``menu_key``."""
        db_user = await UserDao.aget_user(user_id)
        if not db_user:
            raise UnAuthorizedError.http_exception()
        is_department_admin = bool(await DepartmentDao.aget_user_admin_departments(user_id))
        _, web_menu = await cls.get_roles_web_menu(db_user, is_department_admin=is_department_admin)
        if menu_key not in set(web_menu):
            raise UnAuthorizedError.http_exception()
