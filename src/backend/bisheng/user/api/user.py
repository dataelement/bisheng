import hashlib
import random
from base64 import b64encode
from datetime import datetime
from io import BytesIO
from typing import Annotated, Dict, List, Optional

import rsa
from captcha.image import ImageCaptcha
from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from fastapi.security import OAuth2PasswordBearer
from loguru import logger
from sqlmodel import select

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schemas import resp_200, CreateUserReq
from bisheng.common.errcode.http_error import UnAuthorizedError, NotFoundError
from bisheng.common.errcode.user import (UserNotPasswordError, UserValidateError, UserPasswordError, UserForbiddenError)
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client, get_redis_client_sync
from bisheng.core.database import get_sync_db_session
from bisheng.database.constants import AdminRole, DefaultRole
from bisheng.database.models.group import GroupDao
from bisheng.database.models.mark_task import MarkTaskDao
from bisheng.database.models.role import Role, RoleCreate, RoleDao, RoleUpdate
from bisheng.database.models.role_access import RoleRefresh, RoleAccessDao, AccessType
from bisheng.database.models.user_group import UserGroupDao
from bisheng.utils import generate_uuid
from bisheng.utils import get_request_ip
from bisheng.utils.constants import CAPTCHA_PREFIX, RSA_KEY, USER_PASSWORD_ERROR, USER_CURRENT_SESSION
from ..domain.models.user import User, UserCreate, UserDao, UserLogin, UserRead, UserUpdate
from ..domain.models.user_role import UserRole, UserRoleCreate, UserRoleDao
from ..domain.services.auth import AuthJwt, LoginUser
from ..domain.services.user import UserService
from ...common.constants.enums.telemetry import BaseTelemetryTypeEnum
from ...common.schemas.telemetry.event_data_schema import UserLoginEventData
from ...common.services import telemetry_service
from ...core.logger import trace_id_var

# build router
router = APIRouter(prefix='', tags=['User'])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')


@router.post('/user/regist')
async def regist(*, user: UserCreate):
    # Captcha Verification
    db_user = await UserService.user_register(user)
    return resp_200(db_user)


@router.post('/user/sso')
async def sso(*, request: Request, user: UserCreate, auth_jwt: AuthJwt = Depends()):
    """ Login interface for closed source gateways """
    if settings.get_system_login_method().bisheng_pro:  # Judgingsso Open or not
        account_name = user.user_name
        user_exist = UserDao.get_unique_user_by_name(account_name)
        if not user_exist:
            # Determine if there is a user under the platform
            user_all = UserDao.get_all_users(page=1, limit=1)
            # Automatically create users
            user_exist = User.model_validate(user)
            logger.info('act=create_user account={}', account_name)
            default_admin = settings.get_system_login_method().admin_username
            # Insert as Super Admin if there is no user on the platform or if the username matches the configured admin username
            if len(user_all) == 0 or (default_admin and default_admin == account_name):
                # Create as Super Admin
                user_exist = await UserDao.add_user_and_admin_role(user_exist)
            else:
                # Create as Normal User
                user_exist = await UserDao.add_user_and_default_role(user_exist)
            await UserGroupDao.add_default_user_group(user_exist.user_id)
        if 1 == user_exist.delete:
            raise UserForbiddenError.http_exception()
        access_token = LoginUser.create_access_token(user_exist, auth_jwt=auth_jwt)

        # Set the logged in user's currentcookie, .jwtValid for an additional hour
        redis_client = await get_redis_client()
        await redis_client.aset(USER_CURRENT_SESSION.format(user_exist.user_id), access_token,
                                settings.cookie_conf.jwt_token_expire_time + 3600)

        # Log Audit Logs
        login_user = await LoginUser.init_login_user(user_id=user_exist.user_id, user_name=user_exist.user_name)
        AuditLogService.user_login(login_user, get_request_ip(request))

        # RecordTelemetryJournal
        await telemetry_service.log_event(user_id=login_user.user_id, event_type=BaseTelemetryTypeEnum.USER_LOGIN,
                                          trace_id=trace_id_var.get(),
                                          event_data=UserLoginEventData(method="oss"))

        return resp_200({'access_token': access_token, 'refresh_token': access_token})
    else:
        raise ValueError('Interface not supported')


def get_error_password_key(username: str):
    return USER_PASSWORD_ERROR.format(username)


def clear_error_password_key(username: str):
    # Count of cleanup password errors
    error_key = get_error_password_key(username)
    get_redis_client_sync().delete(error_key)


@router.post('/user/login')
async def login(*, request: Request, user: UserLogin, auth_jwt: AuthJwt = Depends()):
    return await UserService.user_login(request, user=user, auth_jwt=auth_jwt)


@router.get('/user/admin')
async def get_admins(login_user: LoginUser = Depends(LoginUser.get_login_user)):
    """
    Get all Super Admin accounts
    """
    # check if user already exist
    if not login_user.is_admin():
        raise HTTPException(status_code=500, detail="Quit that! You don't have rights to view this.")
    try:
        # Get all Super Admin accounts
        admins = UserRoleDao.get_admins_user()
        admins_ids = [admin.user_id for admin in admins]
        admin_users = UserDao.get_user_by_ids(admins_ids)
        res = [UserRead(**one.__dict__) for one in admin_users]
        return resp_200(res)
    except Exception:
        raise HTTPException(status_code=500, detail='User information failed')


@router.get('/user/info')
async def get_info(login_user: LoginUser = Depends(LoginUser.get_login_user)):
    user_id = login_user.user_id
    db_user = await UserDao.aget_user(user_id)
    if not db_user:
        raise NotFoundError()
    role, web_menu = await login_user.get_roles_web_menu(db_user)

    admin_group = await UserGroupDao.aget_user_admin_group(user_id)
    admin_group = [one.group_id for one in admin_group]
    return resp_200(UserRead(role=str(role), web_menu=web_menu, admin_groups=admin_group, **db_user.__dict__))


@router.post('/user/logout', status_code=201)
async def logout(auth_jwt: AuthJwt = Depends()):
    auth_jwt.unset_access_token()
    return resp_200()


@router.get('/user/list', status_code=201)
async def list_user(*,
                    name: Optional[str] = None,
                    page_size: Optional[int] = 10,
                    page_num: Optional[int] = 1,
                    group_id: Annotated[List[int], Query()] = None,
                    role_id: Annotated[List[int], Query()] = None,
                    login_user: LoginUser = Depends(LoginUser.get_login_user)):
    groups = group_id
    roles = role_id
    user_admin_groups = []
    if not login_user.is_admin():
        # Query if you are an administrator of another user group under
        user_admin_groups = UserGroupDao.get_user_admin_group(login_user.user_id)
        user_admin_groups = [one.group_id for one in user_admin_groups]
        groups = user_admin_groups
        # Not an administrator of any user group does not have permission to view
        if not groups:
            raise HTTPException(status_code=500, detail="Quit that! You don't have rights to view this.")
        # Filter bygroup_idand administrator permissionsgroupsDoing Intersections
        if group_id:
            groups = list(set(groups) & set(group_id))
            if not groups:
                raise HTTPException(status_code=500, detail="Quit that! You don't have rights to view this.")
        # Query roles under user groups, Intersect with the role filter to get the role that really needs to be queriedID
        group_roles = RoleDao.get_role_by_groups(groups, None, 0, 0)
        if role_id:
            roles = list(set(role_id) & set([one.id for one in group_roles]))
    # Users filtered by user groups and rolesid
    user_ids = []
    if groups:
        # Query users under user groupsID
        groups_user_ids = UserGroupDao.get_groups_user(groups)
        if not groups_user_ids:
            return resp_200({'data': [], 'total': 0})
        user_ids = list(set([one.user_id for one in groups_user_ids]))

    if roles:
        roles_user_ids = UserRoleDao.get_roles_user(roles)
        if not roles_user_ids:
            return resp_200({'data': [], 'total': 0})
        roles_user_ids = [one.user_id for one in roles_user_ids]

        # Automatically close purchase order afteruser_idsis not empty, the description isgroupsDo intersection screening together, otherwise only do role screening
        if user_ids:
            user_ids = list(set(user_ids) & set(roles_user_ids))
            if not user_ids:
                return resp_200({'data': [], 'total': 0})
        else:
            user_ids = list(set(roles_user_ids))

    users, total_count = UserDao.filter_users(user_ids, name, page_num, page_size)
    res = []
    role_dict = {}
    group_dict = {}
    for one in users:
        one_data = one.model_dump()
        user_roles = get_user_roles(one, role_dict)
        user_groups = get_user_groups(one, group_dict)
        # If not hyper-managed, data needs to be filtered, Cannot see the list of roles and user groups within a user group not managed by him
        if user_admin_groups:
            for i in range(len(user_roles) - 1, -1, -1):
                if user_roles[i]["group_id"] not in user_admin_groups:
                    del user_roles[i]
            for i in range(len(user_groups) - 1, -1, -1):
                if user_groups[i]["id"] not in user_admin_groups:
                    del user_groups[i]
        one_data["roles"] = user_roles
        one_data["groups"] = user_groups
        res.append(one_data)

    return resp_200({'data': res, 'total': total_count})


def get_user_roles(user: User, role_cache: Dict) -> List[Dict]:
    # Query a list of roles for a user
    user_roles = UserRoleDao.get_user_roles(user.user_id)
    user_role_ids: List[int] = [one_role.role_id for one_role in user_roles]
    res = []
    for i in range(len(user_role_ids) - 1, -1, -1):
        if role_cache.get(user_role_ids[i]):
            res.append(role_cache.get(user_role_ids[i]))
            del user_role_ids[i]
    # Query database for role information without caching
    if user_role_ids:
        role_list = RoleDao.get_role_by_ids(user_role_ids)
        for role_info in role_list:
            role_cache[role_info.id] = {
                "id": role_info.id,
                "group_id": role_info.group_id,
                "name": role_info.role_name
            }
            res.append(role_cache.get(role_info.id))
    return res


def get_user_groups(user: User, group_cache: Dict) -> List[Dict]:
    # Query a list of roles for a user
    user_groups = UserGroupDao.get_user_group(user.user_id)
    user_group_ids: List[int] = [one_group.group_id for one_group in user_groups]
    res = []
    for i in range(len(user_group_ids) - 1, -1, -1):
        if group_cache.get(user_group_ids[i]):
            res.append(group_cache.get(user_group_ids[i]))
            del user_group_ids[i]
    # Query database for role information without caching
    if user_group_ids:
        group_list = GroupDao.get_group_by_ids(user_group_ids)
        for group_info in group_list:
            group_cache[group_info.id] = {'id': group_info.id, 'name': group_info.group_name}
            res.append(group_cache.get(group_info.id))
    return res


@router.post('/user/update', status_code=201)
async def update(*,
                 request: Request,
                 user: UserUpdate,
                 login_user: LoginUser = Depends(LoginUser.get_login_user)):
    db_user = UserDao.get_user(user.user_id)
    if not db_user:
        raise HTTPException(status_code=500, detail='Pengguna tidak ada')

    if not login_user.is_admin():
        # Check if is an administrator of a user group under
        user_group = UserGroupDao.get_user_group(db_user.user_id)
        user_group = [one.group_id for one in user_group]
        if not login_user.check_groups_admin(user_group):
            raise HTTPException(status_code=500, detail="Quit that! You don't have rights to view this.")

    # check if user already exist
    if db_user and user.delete is not None:
        # Determine if it's an admin
        with get_sync_db_session() as session:
            admin = session.exec(
                select(UserRole).where(UserRole.role_id == 1,
                                       UserRole.user_id == user.user_id)).first()
        if admin:
            raise HTTPException(status_code=500, detail='Cannot operate admin')
        if user.delete == db_user.delete:
            return resp_200()
        db_user.delete = user.delete
    if db_user.delete == 0:  # Enable User
        # Count of cleanup password errors
        clear_error_password_key(db_user.user_name)
    with get_sync_db_session() as session:
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    update_user_delete_hook(request, login_user, db_user)
    return resp_200()


def update_user_delete_hook(request: Request, login_user: LoginUser, user: User) -> bool:
    logger.info(f'update_user_delete_hook: {request}, user={user}')
    if user.delete == 0:  # Enable User
        AuditLogService.recover_user(login_user, get_request_ip(request), user)
    elif user.delete == 1:  # Disabled User
        AuditLogService.forbid_user(login_user, get_request_ip(request), user)
    return True


@router.post('/role/add', status_code=201)
async def create_role(*,
                      request: Request,
                      role: RoleCreate,
                      login_user: LoginUser = Depends(LoginUser.get_login_user)):
    if not role.group_id:
        raise HTTPException(status_code=500, detail='User GroupsIDTidak boleh kosong.')
    if not role.role_name:
        raise HTTPException(status_code=500, detail='msg.role_name_not_be_empty')

    if not login_user.check_group_admin(role.group_id):
        return UnAuthorizedError.return_resp()

    db_role = Role.model_validate(role)
    try:
        with get_sync_db_session() as session:
            session.add(db_role)
            session.commit()
            session.refresh(db_role)
        create_role_hook(request, login_user, db_role)
        return resp_200(db_role)
    except Exception:
        logger.exception('add role error')
        raise HTTPException(status_code=500, detail='Failed to add, check if it is added repeatedly')


def create_role_hook(request: Request, login_user: LoginUser, db_role: Role) -> bool:
    logger.info(f'create_role_hook: {login_user.user_name}, role={db_role}')
    AuditLogService.create_role(login_user, get_request_ip(request), db_role)


@router.patch('/role/{role_id}', status_code=201)
async def update_role(*,
                      request: Request,
                      role_id: int,
                      role: RoleUpdate,
                      login_user: LoginUser = Depends(LoginUser.get_login_user)):
    db_role = RoleDao.get_role_by_id(role_id)
    if not db_role:
        raise HTTPException(status_code=404, detail='This character does not exist')

    if not login_user.check_group_admin(db_role.group_id):
        return UnAuthorizedError.return_resp()

    try:
        if role.role_name:
            db_role.role_name = role.role_name
        if role.remark:
            db_role.remark = role.remark
        with get_sync_db_session() as session:
            session.add(db_role)
            session.commit()
            session.refresh(db_role)
        update_role_hook(request, login_user, db_role)
        return resp_200(db_role)
    except Exception:
        logger.exception(f'update_role')
        raise HTTPException(status_code=500, detail='Update failed, server side exception')


def update_role_hook(request: Request, login_user: LoginUser, db_role: Role) -> bool:
    logger.info(f'update_role_hook: {login_user.user_name}, role={db_role}')
    AuditLogService.update_role(login_user, get_request_ip(request), db_role)


@router.get('/role/list', status_code=200)
async def get_role(*,
                   role_name: str = None,
                   page: int = 0,
                   limit: int = 0,
                   login_user: LoginUser = Depends(LoginUser.get_login_user)):
    """
    Get a list of roles visible to the user, Return different data according to different user permissions
    """
    # Parameter Processing
    if role_name:
        role_name = role_name.strip()

    # Determine if it's a Super Admin
    if login_user.is_admin():
        # Is Super Admin Get All
        group_ids = []
    else:
        # Query if you are an administrator of another user group under
        user_groups = UserGroupDao.get_user_admin_group(login_user.user_id)
        group_ids = [one.group_id for one in user_groups if one.is_group_admin]
        if not group_ids:
            raise HTTPException(status_code=500, detail="Quit that! You don't have rights to view this.")

    # Query a list of all roles
    res = RoleDao.get_role_by_groups(group_ids, role_name, page, limit)
    total = RoleDao.count_role_by_groups(group_ids, role_name)
    return resp_200(data={"data": res, "total": total})


@router.delete('/role/{role_id}', status_code=200)
async def delete_role(*,
                      request: Request,
                      role_id: int, login_user: LoginUser = Depends(LoginUser.get_login_user)):
    db_role = RoleDao.get_role_by_id(role_id)
    if not db_role:
        return resp_200()

    if not login_user.check_group_admin(db_role.group_id):
        return UnAuthorizedError.return_resp()

    if db_role.id == AdminRole or db_role.id == DefaultRole:
        raise HTTPException(status_code=500, detail='Built-in roles cannot be deleted')

    # DeleteroleRelated data
    try:
        RoleDao.delete_role(role_id)
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail='Failed to delete role')
    AuditLogService.delete_role(login_user, get_request_ip(request), db_role)
    return resp_200()


@router.post('/user/role_add', status_code=200)
async def user_addrole(*,
                       request: Request,
                       user_role: UserRoleCreate,
                       login_user: LoginUser = Depends(LoginUser.get_login_user)):
    """
    Resets the role of the user. The scope of the data varies depending on the permissions
    """
    # Get a list of the user's previous roles
    old_roles = UserRoleDao.get_user_roles(user_role.user_id)
    old_roles = [one.role_id for one in old_roles]
    # Determine if the role being edited is Super Admin, Super Admin does not allow editing
    user_role_list = UserRoleDao.get_user_roles(user_role.user_id)
    if any(one.role_id == AdminRole for one in user_role_list):
        raise HTTPException(status_code=500, detail='Editing is not allowed by the system administrator')
    if any(one == AdminRole for one in user_role.role_id):
        raise HTTPException(status_code=500, detail='Setting as system administrator is not allowed')

    if not login_user.is_admin():
        # Determine which user groups you have administrative access to
        admin_group = UserGroupDao.get_user_admin_group(login_user.user_id)
        admin_group = [one.group_id for one in admin_group]
        if not admin_group:
            raise HTTPException(status_code=500, detail='No rights')
        # Get a list of all roles under an admin group
        admin_roles = RoleDao.get_role_by_groups(admin_group, '', 0, 0)
        admin_roles = [one.id for one in admin_roles]
        # Do the intersection to get the list of roles visible to the user group administrator
        for i in range(len(old_roles) - 1, -1, -1):
            if old_roles[i] not in admin_roles:
                del old_roles[i]
        # Determine if the reset role list is in Under the name of the user group administrator
        for i in range(len(user_role.role_id) - 1, -1, -1):
            if user_role.role_id[i] not in admin_roles:
                raise HTTPException(status_code=500, detail=f'No permission to add roles{user_role.role_id[i]}')

    need_add_role = []
    need_delete_role = old_roles.copy()
    for one in user_role.role_id:
        if one not in old_roles:
            # Role needs to be added
            need_add_role.append(one)
        else:
            # All that remains is the list of roles that need to be deleted
            need_delete_role.remove(one)
    if need_add_role:
        UserRoleDao.add_user_roles(user_role.user_id, need_add_role)
    if need_delete_role:
        # Delete the corresponding role list
        UserRoleDao.delete_user_roles(user_role.user_id, need_delete_role)
    update_user_role_hook(request, login_user, user_role.user_id, old_roles, user_role.role_id)
    return resp_200()


def update_user_role_hook(request: Request, login_user: LoginUser, user_id: int,
                          old_roles: List[int], new_roles: List[int]):
    logger.info(f'update_user_role_hook, user_id: {user_id}, old_roles: {old_roles}, new_roles: {new_roles}')
    # Write Audit Log
    role_info = RoleDao.get_role_by_ids(old_roles + new_roles)
    group_ids = list(set([role.group_id for role in role_info]))
    role_dict = {one.id: one.role_name for one in role_info}
    note = "Pre-edit role:"
    for one in old_roles:
        note += role_dict[one] + "、"
    note = note.rstrip("、")
    note += "Post-edited roles:"
    for one in new_roles:
        note += role_dict[one] + "、"
    note = note.rstrip("、")
    AuditLogService.update_user(login_user, get_request_ip(request), user_id, group_ids, note)


@router.post('/role_access/refresh', status_code=200)
async def access_refresh(*, request: Request, data: RoleRefresh,
                         login_user: LoginUser = Depends(LoginUser.get_login_user)):
    db_role = await RoleDao.aget_role_by_id(data.role_id)
    if not db_role:
        raise NotFoundError().http_exception()
    if db_role.id == AdminRole:
        raise UnAuthorizedError.http_exception()
    if not await login_user.async_check_group_admin(db_role.group_id):
        raise UnAuthorizedError.http_exception()

    role_id = data.role_id
    access_type = data.type
    access_id = data.access_id
    await RoleAccessDao.update_role_access_all(role_id, AccessType(access_type), access_id)

    update_role_hook(request, login_user, db_role)
    return resp_200()


@router.get('/role_access/list', status_code=200)
async def access_list(*, role_id: int, access_type: Optional[int] = Query(default=None, alias="type"),
                      login_user: LoginUser = Depends(LoginUser.get_login_user)):
    db_role = await RoleDao.aget_role_by_id(role_id)
    if not db_role:
        raise NotFoundError().http_exception()

    if not await login_user.async_check_group_admin(db_role.group_id):
        return UnAuthorizedError.return_resp()

    access_type = None
    if access_type:
        access_type = AccessType(access_type)
    res = await RoleAccessDao.aget_role_access([role_id], access_type)

    return resp_200({
        'data': res,
        'total': len(res)
    })


@router.get('/user/get_captcha', status_code=200)
async def get_captcha():
    # generate captcha
    chr_all = "abcdefghjkmnpqrstuvwxyABCDEFGHJKMNPQRSTUVWXY3456789"
    chr_4 = ''.join(random.sample(chr_all, 4))
    image = ImageCaptcha().generate_image(chr_4)
    # Right.image To be performedbase 64 <g id="Bold">Code</g>
    buffered = BytesIO()
    image.save(buffered, format='PNG')

    capthca_b64 = b64encode(buffered.getvalue()).decode()
    logger.info('get_captcha captcha_char={}', chr_4)
    # generate key, Generate Simple Uniqueid，
    key = CAPTCHA_PREFIX + generate_uuid()[:8]
    redis_client = await get_redis_client()
    await redis_client.aset(key, chr_4, expiration=300)

    # Add configuration, whether the verification code must be used
    return resp_200({
        'captcha_key': key,
        'captcha': capthca_b64,
        'user_capthca': settings.get_from_db('use_captcha') or False
    })


@router.get('/user/public_key', status_code=200)
async def get_rsa_publish_key():
    # redis Storage
    key = RSA_KEY
    redis_client = await get_redis_client()
    # redis lock
    if await redis_client.asetNx(key, 1):
        # Generate a key pair
        (pubkey, privkey) = rsa.newkeys(512)

        # Save the keys to strings
        await redis_client.aset(key, (pubkey, privkey), 3600)
    else:
        pubkey, privkey = await redis_client.aget(key)

    pubkey_str = pubkey.save_pkcs1().decode()

    return resp_200({'public_key': pubkey_str})


@router.post('/user/reset_password', status_code=200)
async def reset_password(
        *,
        user_id: int = Body(embed=True),
        password: str = Body(embed=True),
        login_user: LoginUser = Depends(LoginUser.get_login_user),
):
    """
    Admin Reset User Password
    """
    # Get user information to change password
    user_info = UserDao.get_user(user_id)
    if not user_info:
        raise HTTPException(status_code=404, detail='Pengguna tidak ada')
    user_payload = LoginUser(**{
        'user_id': user_info.user_id,
        'user_name': user_info.user_name,
        'role': ''
    })
    # If the user being modified is a system administrator, Need to determine if it's me
    if user_payload.is_admin() and login_user.user_id != user_id:
        raise HTTPException(status_code=500, detail='System administrators can only reset passwords themselves')

    # Query the user group the user belongs to
    user_groups = UserGroupDao.get_user_group(user_info.user_id)
    user_group_ids = [one.group_id for one in user_groups]

    # Check if there are administrative permissions for the group
    if not login_user.check_groups_admin(user_group_ids):
        raise HTTPException(status_code=403, detail='No permission to reset password')

    user_info.password = UserService.decrypt_md5_password(password)
    user_info.password_update_time = datetime.now()
    UserDao.update_user(user_info)

    clear_error_password_key(user_info.user_name)
    return resp_200()


@router.post('/user/change_password', status_code=200)
async def change_password(*,
                          password: str = Body(embed=True),
                          new_password: str = Body(embed=True),
                          login_user: LoginUser = Depends(LoginUser.get_login_user)):
    """
    Login user Change my password
    """
    user_info = UserDao.get_user(login_user.user_id)
    if not user_info.password:
        return UserNotPasswordError.return_resp()

    password = UserService.decrypt_md5_password(password)

    # Logged in user told it was the wrong password
    if user_info.password != password:
        return UserPasswordError.return_resp()

    user_info.password = UserService.decrypt_md5_password(new_password)
    user_info.password_update_time = datetime.now()
    UserDao.update_user(user_info)

    clear_error_password_key(user_info.user_name)
    return resp_200()


@router.post('/user/change_password_public', status_code=200)
async def change_password_public(*,
                                 username: str = Body(embed=True),
                                 password: str = Body(embed=True),
                                 new_password: str = Body(embed=True)):
    """
    Not Logged-In Users Change my password
    """

    user_info = UserDao.get_user_by_username(username)
    if not user_info.password:
        return UserValidateError.return_resp()

    if user_info.password != UserService.decrypt_md5_password(password):
        return UserValidateError.return_resp()

    user_info.password = UserService.decrypt_md5_password(new_password)
    user_info.password_update_time = datetime.now()
    UserDao.update_user(user_info)

    clear_error_password_key(username)
    return resp_200()


@router.get('/user/mark', status_code=200)
async def has_mark_access(*, request: Request, login_user: LoginUser = Depends(LoginUser.get_login_user)):
    """
    Get whether the current user has annotation permission,Determine if the current user isadmin Or a user group administrator
    """
    user_groups = UserGroupDao.get_user_group(login_user.user_id)
    user_group_ids = [one.group_id for one in user_groups]

    has_mark_access = False
    # Check if there are administrative permissions for the group
    task = MarkTaskDao.get_task(login_user.user_id)
    if task:
        has_mark_access = True

    return resp_200(data=has_mark_access)


@router.post('/user/create', status_code=200)
async def create_user(*,
                      request: Request,
                      admin_user: LoginUser = Depends(LoginUser.get_admin_user),
                      req: CreateUserReq):
    """
    Super Admin Create User
    """
    logger.info(f'create_user username={admin_user.user_name}, username={req.user_name}')
    data = UserService.create_user(request, admin_user, req)
    return resp_200(data=data)


def md5_hash(string):
    md5 = hashlib.md5()
    md5.update(string.encode('utf-8'))
    return md5.hexdigest()
