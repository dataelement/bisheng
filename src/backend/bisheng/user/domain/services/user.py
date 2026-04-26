from base64 import b64decode
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from urllib.parse import unquote, urlsplit

import rsa
from fastapi import Request, Depends, UploadFile, HTTPException
from loguru import logger

from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.errcode.user import (
    CaptchaError,
    UserForbiddenError,
    UserValidateError,
    UserPasswordMaxTryError,
    UserPasswordExpireError,
    UserNameTooLongError,
    UserNoRoleForLoginError,
    UserNoWebMenuForLoginError,
)
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.common.schemas.telemetry.event_data_schema import UserLoginEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client_sync, get_redis_client
from bisheng.core.database import get_async_db_session
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.minio.minio_manager import get_minio_storage, get_minio_storage_sync
from bisheng.database.constants import AdminRole, DefaultRole
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.permission.domain.services.legacy_rbac_sync_service import LegacyRBACSyncService
from bisheng.user.domain.models.user import User, UserDao, UserLogin, UserRead, UserCreate
from bisheng.user.domain.models.user_role import UserRoleDao
from bisheng.utils import md5_hash, get_request_ip, generate_uuid
from bisheng.utils.constants import RSA_KEY
from .auth import LoginUser, AuthJwt
from .captcha import verify_captcha
from ..const import USER_PASSWORD_ERROR, USER_CURRENT_SESSION

if TYPE_CHECKING:
    from bisheng.api.v1.schemas import CreateUserReq

# Allowed avatar file types and their MIME types
ALLOWED_AVATAR_TYPES = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'image/gif': '.gif',
}
MAX_AVATAR_SIZE = 10 * 1024 * 1024  # 10MB
AVATAR_OBJECT_PREFIX = 'avatar/'


class UserService:
    @classmethod
    async def ainvalidate_jwt_after_account_disabled(cls, user_id: int) -> None:
        """禁用账号后立刻让已签发的 JWT 失效（F012 ``token_version``），并清理管理端 scope 缓存。"""
        try:
            await UserDao.aincrement_token_version(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                'aincrement_token_version failed after account disabled user_id=%s: %s',
                user_id, exc,
            )
            return
        try:
            from bisheng.admin.domain.services.tenant_scope import TenantScopeService
            await TenantScopeService.clear_on_token_version_bump(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                'clear_on_token_version_bump failed after account disabled user_id=%s: %s',
                user_id, exc,
            )

    @classmethod
    def _normalize_avatar_object_name(cls, avatar: str | None, bucket: str | None = None) -> str | None:
        if not avatar:
            return avatar

        avatar = avatar.strip()
        path = urlsplit(avatar).path if '://' in avatar or avatar.startswith('/') else avatar.split('?', 1)[0]
        path = unquote(path).lstrip('/')

        if bucket and path.startswith(f'{bucket}/'):
            path = path[len(bucket) + 1:]

        if path.startswith(AVATAR_OBJECT_PREFIX):
            return path
        return None

    @classmethod
    def get_avatar_share_link_sync(cls, avatar: str | None) -> str | None:
        if not avatar:
            return avatar

        minio_client = get_minio_storage_sync()
        object_name = cls._normalize_avatar_object_name(avatar, minio_client.bucket)
        if not object_name:
            return avatar
        return minio_client.get_share_link_sync(object_name)

    @classmethod
    async def get_avatar_share_link(cls, avatar: str | None) -> str | None:
        if not avatar:
            return avatar

        minio_client = await get_minio_storage()
        object_name = cls._normalize_avatar_object_name(avatar, minio_client.bucket)
        if not object_name:
            return avatar
        return await minio_client.get_share_link(object_name)

    @classmethod
    async def build_user_read(cls, user: User, **kwargs) -> UserRead:
        user_data = user.model_dump()
        user_data.update(kwargs)
        user_data['avatar'] = await cls.get_avatar_share_link(user_data.get('avatar'))
        return UserRead(**user_data)

    @classmethod
    def build_user_read_sync(cls, user: User, **kwargs) -> UserRead:
        user_data = user.model_dump()
        user_data.update(kwargs)
        user_data['avatar'] = cls.get_avatar_share_link_sync(user_data.get('avatar'))
        return UserRead(**user_data)

    @classmethod
    def decrypt_password_plain(cls, password: str) -> str:
        """RSA 解密得到明文密码（未做 MD5）；无 RSA 配置时视为明文开发模式。"""
        if value := get_redis_client_sync().get(RSA_KEY):
            private_key = value[1]
            return rsa.decrypt(b64decode(password), private_key).decode('utf-8')
        return password

    @classmethod
    def decrypt_md5_password(cls, password: str):
        plain = cls.decrypt_password_plain(password)
        return md5_hash(plain)

    @classmethod
    def create_user(cls, request: Request, login_user: LoginUser, req_data: 'CreateUserReq'):
        """
        Create User
        """
        user = User(
            user_name=req_data.user_name,
            password=cls.decrypt_md5_password(req_data.password),
            source='local',
            # Default external_id to user_name so password login (which queries
            # external_id only since 94323e3ec) works out of the box. SSO-synced
            # users set their own external_id via org_sync, not through here.
            external_id=req_data.user_name,
        )
        group_ids = []
        role_ids = []
        for one in req_data.group_roles or []:
            group_ids.append(one.group_id)
            role_ids.extend(one.role_ids)
        group_ids = list(dict.fromkeys(group_ids))
        role_ids = list(dict.fromkeys(role_ids))
        if not role_ids:
            role_ids = [DefaultRole]
        user = UserDao.add_user_with_groups_and_roles(user, group_ids, role_ids)
        return user

    @staticmethod
    def get_error_password_key(user_id: int) -> str:
        return USER_PASSWORD_ERROR.format(int(user_id))

    @classmethod
    async def clear_error_password_key(cls, user_id: int):
        error_key = cls.get_error_password_key(user_id)
        (await get_redis_client()).delete(error_key)

    @classmethod
    async def judge_user_password(cls, db_user: User, password: str) -> None:
        redis_client = await get_redis_client()

        password_conf = await settings.get_password_conf()
        if not db_user.password:
            raise UserValidateError()

        if db_user.password == password:
            # Determine if the password has not been changed for a long time
            if password_conf.password_valid_period and password_conf.password_valid_period > 0:
                if (datetime.now() - db_user.password_update_time).days >= password_conf.password_valid_period:
                    raise UserPasswordExpireError()
            return

        # Determine if the number of errors needs to be logged
        if not password_conf.login_error_time_window or not password_conf.max_error_times:
            raise UserValidateError()
        # Number of errors plus1
        error_key = cls.get_error_password_key(db_user.user_id)
        error_num = await redis_client.aincr(error_key)
        if error_num == 1:
            # First time setupkeyExpiration date
            await redis_client.aexpire_key(error_key, password_conf.login_error_time_window * 60)
        if error_num and int(error_num) >= password_conf.max_error_times:
            # Maximum number of errors reached, account banned
            db_user.delete = 1
            await UserDao.aupdate_user(db_user)
            await cls.ainvalidate_jwt_after_account_disabled(db_user.user_id)
            raise UserPasswordMaxTryError()
        raise UserValidateError()

    @classmethod
    async def user_register(cls, user: UserCreate):
        # Captcha Verification
        if settings.get_from_db('use_captcha'):
            if not user.captcha_key or not await verify_captcha(user.captcha, user.captcha_key):
                raise CaptchaError()

        db_user = User.model_validate(user)
        person_id = (db_user.external_id or "").strip()
        if not person_id:
            raise UserValidateError(msg='Person ID is required')
        existing_pid = await UserDao.aget_by_external_id(person_id)
        if existing_pid:
            raise UserValidateError(msg='Person ID already exists')
        db_user.external_id = person_id

        # 允许用户名重复；人员唯一性由 external_id / user_id 等保证
        if len(db_user.user_name) > 30:
            raise UserNameTooLongError()
        db_user.password = cls.decrypt_md5_password(user.password)
        # Under JudgmentadminDoes the user exist
        admin = await UserDao.aget_user(1)
        if admin:
            db_user = await UserDao.add_user_and_default_role(db_user)
            await LegacyRBACSyncService.sync_user_auth_created(
                db_user.user_id,
                [DefaultRole],
            )
        else:
            db_user.user_id = 1
            db_user = await UserDao.add_user_and_admin_role(db_user)
            await LegacyRBACSyncService.sync_user_auth_created(
                db_user.user_id,
                [AdminRole],
            )
        if settings.multi_tenant.enabled:
            await cls._ensure_user_default_tenant_association(db_user.user_id)
        await cls._ensure_user_guest_department_membership(db_user.user_id)
        return db_user

    @classmethod
    async def _ensure_user_guest_department_membership(cls, user_id: int) -> None:
        """注册完成后自动加入“临时访客”部门（主部门）。"""
        from bisheng.database.models.department import Department, UserDepartment
        from sqlmodel import select

        guest_dept_id = 'BS@guest'
        async with get_async_db_session() as session:
            dept = (
                await session.exec(
                    select(Department).where(
                        Department.dept_id == guest_dept_id,
                        Department.status == 'active',
                    )
                )
            ).first()
            if not dept:
                return
            exists = (
                await session.exec(
                    select(UserDepartment).where(
                        UserDepartment.user_id == user_id,
                        UserDepartment.department_id == dept.id,
                    )
                )
            ).first()
            if exists:
                return
            session.add(UserDepartment(
                user_id=user_id,
                department_id=dept.id,
                is_primary=1,
                source='local',
            ))
            await session.commit()
            from bisheng.department.domain.services.department_change_handler import (
                DepartmentChangeHandler,
            )
            ops = DepartmentChangeHandler.on_members_added(dept.id, [user_id])
            await DepartmentChangeHandler.execute_async(ops)

    @classmethod
    async def _ensure_user_default_tenant_association(cls, user_id: int) -> None:
        """When multi-tenant is on, every user must have at least one ``user_tenant`` row to log in."""
        from bisheng.core.context.tenant import DEFAULT_TENANT_ID
        from bisheng.database.models.tenant import TenantDao, UserTenantDao

        existing = await UserTenantDao.aget_user_tenants(user_id)
        if existing:
            return
        code = (settings.multi_tenant.default_tenant_code or 'default').strip() or 'default'
        tenant = await TenantDao.aget_by_code(code)
        tenant_id = tenant.id if tenant else DEFAULT_TENANT_ID
        await UserTenantDao.aadd_user_to_tenant(user_id=user_id, tenant_id=tenant_id, is_default=1)

    @classmethod
    async def _reject_login_if_user_has_no_usable_access(
        cls, db_user: User,
    ) -> Optional[UnifiedResponseModel]:
        """无角色且非部门/用户组管理员时拒绝登录；有角色但生效菜单既不包含工作台也不包含管理后台时拒绝登录。

        需审批模式下角色可仅勾选一级菜单（workstation/admin）而无二级项，仍视为有菜单权限，允许登录。
        """
        roles = await UserRoleDao.aget_user_roles(db_user.user_id)
        if not roles:
            if await DepartmentDao.aget_user_admin_departments(db_user.user_id):
                return None
            group_admins = await UserGroupDao.aget_user_admin_group(db_user.user_id)
            if group_admins:
                return None
            return UserNoRoleForLoginError.return_resp()

        if any(ur.role_id == AdminRole for ur in roles):
            return None
        if await DepartmentDao.aget_user_admin_departments(db_user.user_id):
            return None

        if not await LoginUser.user_has_workbench_or_admin_effective_menu(db_user):
            return UserNoWebMenuForLoginError.return_resp()
        return None

    @classmethod
    async def user_login(cls, request: Request, user: UserLogin, auth_jwt: AuthJwt = Depends()):
        from bisheng.api.services.audit_log import AuditLogService

        if await settings.aget_from_db('use_captcha'):
            if not user.captcha_key or not await verify_captcha(user.captcha, user.captcha_key):
                raise CaptchaError()

        # 支持用户名或 external_id；重名时对候选用户依次校验密码
        candidates = await UserDao.aget_login_candidates_by_account(user.user_name)
        if not candidates:
            # 禁用账号不会进入候选列表；单独提示，避免与「账号或密码错误」混淆
            if await UserDao.aexists_disabled_login_account(user.user_name):
                return UserForbiddenError.return_resp()
            return UserValidateError.return_resp()

        password = cls.decrypt_md5_password(user.password)
        db_user = None
        for c in candidates:
            if c.delete == 1:
                continue
            try:
                await cls.judge_user_password(c, password)
                db_user = c
                break
            except UserPasswordExpireError:
                raise
            except UserPasswordMaxTryError:
                raise
            except UserValidateError:
                # 该候选用户密码不匹配，尝试下一个同名账号
                continue
        if not db_user:
            return UserValidateError.return_resp()

        await cls.clear_error_password_key(db_user.user_id)

        no_role_resp = await cls._reject_login_if_user_has_no_usable_access(db_user)
        if no_role_resp is not None:
            return no_role_resp

        # Multi-tenant login flow
        tenant_id = None
        requires_tenant_selection = False
        tenants_list = None

        if settings.multi_tenant.enabled:
            from bisheng.database.models.tenant import UserTenantDao, TenantDao
            from bisheng.common.errcode.tenant import NoTenantsAvailableError
            from bisheng.core.context.tenant import DEFAULT_TENANT_ID, bypass_tenant_filter
            user_tenants = await UserTenantDao.aget_user_tenants_with_details(db_user.user_id)
            active_tenants = [t for t in user_tenants if t.get('status') == 'active']

            if len(active_tenants) == 0:
                # 注册/历史数据可能未写入 user_tenant；若默认租户存在则自动挂接，避免无法登录
                code = (settings.multi_tenant.default_tenant_code or 'default').strip() or 'default'
                with bypass_tenant_filter():
                    default_tenant = await TenantDao.aget_by_code(code)
                    if default_tenant is None:
                        default_tenant = await TenantDao.aget_by_id(DEFAULT_TENANT_ID)
                if default_tenant and default_tenant.status == 'active':
                    await UserTenantDao.aadd_user_to_tenant(
                        user_id=db_user.user_id,
                        tenant_id=default_tenant.id,
                        is_default=1,
                    )
                    user_tenants = await UserTenantDao.aget_user_tenants_with_details(db_user.user_id)
                    active_tenants = [t for t in user_tenants if t.get('status') == 'active']
                if len(active_tenants) == 0:
                    raise NoTenantsAvailableError()
            elif len(active_tenants) == 1:
                tenant_id = active_tenants[0]['tenant_id']
                await UserTenantDao.aupdate_last_access_time(db_user.user_id, tenant_id)
            else:
                # Multiple tenants: issue temporary JWT with tenant_id=0
                tenant_id = 0
                requires_tenant_selection = True
                tenants_list = active_tenants

        # v2.5.1 F012: resolve canonical leaf tenant + bump token_version.
        # sync_user is a no-op when the resolved leaf already matches the
        # active user_tenant row; otherwise it swaps the row, writes the
        # audit log and rewrites FGA tuples. Fail-open: if the service
        # errors (unusual — typically config missing) we fall back to the
        # tenant_id computed above so the user can still log in.
        try:
            from bisheng.tenant.domain.constants import UserTenantSyncTrigger
            from bisheng.tenant.domain.services.user_tenant_sync_service import (
                UserTenantSyncService,
            )
            leaf = await UserTenantSyncService.sync_user(
                db_user.user_id, trigger=UserTenantSyncTrigger.LOGIN,
            )
            # Override tenant_id for JWT payload — the resolver is the
            # authoritative source for leaf tenancy in v2.5.1.
            if leaf is not None and getattr(leaf, 'id', None):
                tenant_id = leaf.id
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                'F012 login-time tenant sync failed for user %d: %s — '
                'falling back to legacy tenant resolution',
                db_user.user_id, exc,
            )

        # Fetch fresh token_version (sync_user may have just bumped it) and
        # embed in the JWT payload so the middleware can reject stale tokens.
        fresh_token_version = 0
        try:
            fresh_token_version = await UserDao.aget_token_version(db_user.user_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug('aget_token_version failed for %d: %s', db_user.user_id, exc)

        # gen jwt token
        access_token = LoginUser.create_access_token(
            user=db_user, auth_jwt=auth_jwt, tenant_id=tenant_id,
            token_version=fresh_token_version,
        )

        # set cookies
        LoginUser.set_access_cookies(access_token, auth_jwt=auth_jwt)

        # Set the logged in user's currentcookie, .jwtValid for an additional hour
        redis_client = await get_redis_client()
        await redis_client.aset(USER_CURRENT_SESSION.format(db_user.user_id), access_token,
                                auth_jwt.cookie_conf.jwt_token_expire_time + 3600)

        # Log Audit Logs
        login_user = await LoginUser.init_login_user(db_user.user_id, db_user.user_name)
        AuditLogService.user_login(login_user, get_request_ip(request))

        # RecordTelemetryJournal
        await telemetry_service.log_event(user_id=db_user.user_id, event_type=BaseTelemetryTypeEnum.USER_LOGIN,
                                          trace_id=trace_id_var.get(),
                                          event_data=UserLoginEventData(method="password"))

        # Build response with tenant info. is_global_super is already a bool
        # on LoginUser, populated by init_login_user; surface it so the
        # frontend can render admin menus without a /user/info round-trip.
        extra_fields = {
            'access_token': access_token,
            'is_global_super': login_user.is_global_super,
        }
        if requires_tenant_selection:
            extra_fields['requires_tenant_selection'] = True
            extra_fields['tenants'] = tenants_list
        if tenant_id and tenant_id > 0:
            extra_fields['tenant_id'] = tenant_id
            tenant_info = next((t for t in (tenants_list or []) if t.get('tenant_id') == tenant_id), None)
            if not tenant_info and settings.multi_tenant.enabled:
                from bisheng.database.models.tenant import TenantDao
                from bisheng.core.context.tenant import bypass_tenant_filter
                with bypass_tenant_filter():
                    t_obj = await TenantDao.aget_by_id(tenant_id)
                if t_obj:
                    extra_fields['tenant_name'] = t_obj.tenant_name

        return resp_200(await cls.build_user_read(db_user, **extra_fields))

    @classmethod
    def get_user_all_info(cls, *, start_time: datetime = None, end_time: datetime = None, user_ids: List[int] = None,
                          page: int = 1, page_size: int = 100) -> List[User]:
        """ Get user information, including user group and role information """
        return UserDao.get_user_with_group_role(page=page, page_size=page_size, user_ids=user_ids,
                                                start_time=start_time, end_time=end_time)

    @classmethod
    def get_first_user(cls) -> User | None:
        """ Get the first user """
        return UserDao.get_first_user()

    @classmethod
    async def get_user_by_id(cls, user_id: int) -> User | None:
        """ Get user by username """
        return await UserDao.aget_user(user_id)

    @classmethod
    async def update_avatar(cls, user_id: int, file: UploadFile) -> str:
        """
        Update user avatar
        :param user_id: User ID
        :param file: Uploaded avatar file
        :return: Avatar URL
        """
        # Validate file type
        if file.content_type not in ALLOWED_AVATAR_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f'Invalid file type. Allowed types: jpg, png, webp, gif'
            )

        # Read file content to check size
        content = await file.read()
        if len(content) > MAX_AVATAR_SIZE:
            raise HTTPException(
                status_code=400,
                detail='File size exceeds limit. Maximum size: 10MB'
            )

        # Generate object name for MinIO
        file_ext = ALLOWED_AVATAR_TYPES[file.content_type]
        object_name = f'avatar/{user_id}/{generate_uuid()}{file_ext}'

        # Upload to MinIO
        minio_client = await get_minio_storage()
        await minio_client.put_object(
            object_name=object_name,
            file=content,
            content_type=file.content_type,
        )

        # Update user avatar in database
        user = await UserDao.aget_user(user_id)
        if user:
            user.avatar = object_name
            await UserDao.aupdate_user(user)

        return await cls.get_avatar_share_link(object_name)
