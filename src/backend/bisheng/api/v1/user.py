import hashlib
import json
import random
import string
import uuid
from base64 import b64decode, b64encode
from datetime import datetime
from io import BytesIO
from typing import List, Optional, Dict, Annotated
from uuid import UUID

import rsa

from bisheng.api.JWT import get_login_user
from bisheng.api.errcode.user import UserNotPasswordError, UserValidateError, UserPasswordExpireError
from bisheng.api.services.captcha import verify_captcha
from bisheng.api.services.user_service import gen_user_jwt, get_assistant_list_by_access, UserPayload, gen_user_role
from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.cache.redis import redis_client
from bisheng.database.base import session_getter
from bisheng.database.models.flow import Flow
from bisheng.database.models.group import GroupDao
from bisheng.database.models.knowledge import Knowledge
from bisheng.database.models.role import Role, RoleCreate, RoleUpdate, RoleDao
from bisheng.database.models.role_access import AccessType, RoleAccess, RoleRefresh
from bisheng.database.models.user import User, UserCreate, UserDao, UserLogin, UserRead, UserUpdate
from bisheng.database.models.user_group import UserGroupDao
from bisheng.database.models.user_role import UserRole, UserRoleCreate, UserRoleDao
from bisheng.settings import settings
from bisheng.utils.constants import CAPTCHA_PREFIX, RSA_KEY, USER_PASSWORD_ERROR
from bisheng.utils.logger import logger
from captcha.image import ImageCaptcha
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.encoders import jsonable_encoder
from fastapi.security import OAuth2PasswordBearer
from fastapi_jwt_auth import AuthJWT
from sqlalchemy import and_, func
from sqlmodel import delete, select

# build router
router = APIRouter(prefix='', tags=['User'])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')


def decrypt_md5_password(password: str):
    if value := redis_client.get(RSA_KEY):
        private_key = value[1]
        password = md5_hash(rsa.decrypt(b64decode(password), private_key).decode('utf-8'))
    else:
        password = md5_hash(password)
    return password


@router.post('/user/regist', response_model=UnifiedResponseModel[UserRead], status_code=201)
async def regist(*, user: UserCreate):
    # 验证码校验
    if settings.get_from_db('use_captcha'):
        if not user.captcha_key or not await verify_captcha(user.captcha, user.captcha_key):
            raise HTTPException(status_code=500, detail='验证码错误')

    db_user = User.model_validate(user)
    # check if admin user
    with session_getter() as session:
        admin = session.exec(select(User).where(User.user_id == 1)).all()
    if not admin:
        db_user.user_id = 1
        db_user_role = UserRole(user_id=db_user.user_id, role_id=1)
        with session_getter() as session:
            session.add(db_user_role)
            session.commit()

    # check if user already exist
    with session_getter() as session:
        name_user = session.exec(select(User).where(User.user_name == user.user_name)).all()
    if name_user and name_user[0].user_id != 1:
        raise HTTPException(status_code=500, detail='账号已存在')
    else:
        try:
            db_user.password = decrypt_md5_password(user.password)
            with session_getter() as session:
                session.add(db_user)
                session.flush()
                session.refresh(db_user)
                # 默认加入普通用户
                if db_user.user_id != 1:
                    db_user_role = UserRole(user_id=db_user.user_id, role_id=2)
                    session.add(db_user_role)
                # 将用户写入到默认用户组下
                UserGroupDao.add_default_user_group(db_user.user_id)
                session.commit()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f'数据库写入错误， {str(e)}') from e
        return resp_200(db_user)


@router.post('/user/sso', response_model=UnifiedResponseModel[UserRead], status_code=201)
async def sso(*, user: UserCreate, Authorize: AuthJWT = Depends()):
    '''给sso提供的接口'''
    if True:  # 判断sso 是否打开
        account_name = user.user_name
        user_exist = UserDao.get_unique_user_by_name(account_name)
        if not user_exist:
            logger.info('act=create_user account={}', account_name)
            user_exist = UserDao.create_user(user)
            UserGroupDao.add_default_user_group(user_exist.user_id)

        access_token, refresh_token, _ = gen_user_jwt(user_exist)
        return resp_200({'access_token': access_token, 'refresh_token': refresh_token})
    else:
        raise ValueError('不支持接口')


@router.post('/user/login', response_model=UnifiedResponseModel[UserRead], status_code=201)
async def login(*, user: UserLogin, Authorize: AuthJWT = Depends()):
    # 验证码校验
    if settings.get_from_db('use_captcha'):
        if not user.captcha_key or not await verify_captcha(user.captcha, user.captcha_key):
            raise HTTPException(status_code=500, detail='验证码错误')

    password = decrypt_md5_password(user.password)

    db_user = UserDao.get_user_by_username(user.user_name)
    # 检查密码
    if not db_user or not db_user.password:
        return UserValidateError.return_resp()

    if 1 == db_user.delete:
        raise HTTPException(status_code=500, detail='该账号已被禁用，请联系管理员')

    password_conf = settings.get_password_conf()

    if db_user.password and db_user.password != password:
        # 判断是否需要记录错误次数
        if not password_conf.login_error_time_window or not password_conf.max_error_times:
            return UserValidateError.return_resp()
        error_key = USER_PASSWORD_ERROR + db_user.user_name
        error_num = redis_client.get(error_key)
        if error_num and int(error_num) >= password_conf.max_error_times:
            # 错误次数到达上限，封禁账号
            db_user.delete = 1
            UserDao.update_user(db_user)
            raise HTTPException(status_code=500, detail='该账号已被禁用，请联系管理员')

        # 设置错误次数
        redis_client.incr(error_key, password_conf.login_error_time_window * 60)
        return UserValidateError.return_resp()

    # 判断下密码是否长期未修改
    if password_conf.password_valid_period and password_conf.password_valid_period > 0:
        if (datetime.now() - db_user.password_update_time).days >= password_conf.password_valid_period:
            return UserPasswordExpireError.return_resp()

    access_token, refresh_token, role = gen_user_jwt(db_user)

    # Set the JWT cookies in the response
    Authorize.set_access_cookies(access_token)
    Authorize.set_refresh_cookies(refresh_token)

    return resp_200(UserRead(role=str(role), access_token=access_token, **db_user.__dict__))


@router.get('/user/admin', response_model=UnifiedResponseModel[UserRead], status_code=200)
async def get_admins(Authorize: AuthJWT = Depends()):
    """
    获取所有的超级管理员账号
    """
    # check if user already exist
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    login_user = UserPayload(**payload)
    if not login_user.is_admin():
        raise HTTPException(status_code=500, detail='无查看权限')
    try:
        # 获取所有超级管理员账号
        admins = UserRoleDao.get_admins_user()
        admins_ids = [admin.user_id for admin in admins]
        admin_users = UserDao.get_user_by_ids(admins_ids)
        res = [UserRead(**one.__dict__) for one in admin_users]
        return resp_200(res)
    except Exception:
        raise HTTPException(status_code=500, detail='用户信息失败')


@router.get('/user/info', response_model=UnifiedResponseModel[UserRead], status_code=201)
async def get_info(Authorize: AuthJWT = Depends()):
    # check if user already exist
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    try:
        user_id = payload.get('user_id')
        db_user = UserDao.get_user(user_id)
        role = gen_user_role(db_user)
        return resp_200(UserRead(role=str(role), **db_user.__dict__))
    except Exception:
        raise HTTPException(status_code=500, detail='用户信息失败')


@router.post('/user/logout', status_code=201)
async def logout(Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    Authorize.unset_jwt_cookies()
    return resp_200()


@router.get('/user/list', status_code=201)
async def list_user(*,
                    name: Optional[str] = None,
                    page_size: Optional[int] = 10,
                    page_num: Optional[int] = 1,
                    group_id: Annotated[List[int], Query()] = None,
                    role_id: Annotated[List[int], Query()] = None,
                    login_user: UserPayload = Depends(get_login_user)):
    groups = group_id
    roles = role_id
    user_admin_groups = []
    if not login_user.is_admin():
        # 查询下是否是其他用户组的管理员
        user_admin_groups = UserGroupDao.get_user_admin_group(login_user.user_id)
        user_admin_groups = [one.group_id for one in user_admin_groups]
        groups = user_admin_groups
        # 不是任何用户组的管理员无查看权限
        if not groups:
            raise HTTPException(status_code=500, detail='无查看权限')
        # 将筛选条件的group_id和管理员有权限的groups做交集
        if groups:
            groups = list(set(groups) & set(group_id))
            if not groups:
                raise HTTPException(status_code=500, detail='无查看权限')
    # 通过用户组和角色过滤出来的用户id
    user_ids = []
    if groups:
        # 查询用户组下的用户ID
        groups_user_ids = UserGroupDao.get_groups_admins(groups)
        if not groups_user_ids:
            return resp_200({'data': [], 'total': 0})
        user_ids = list(set([one.user_id for one in groups_user_ids]))
        # 查询用户组下的角色, 和角色筛选条件做交集，得到真正去查询的角色ID
        group_roles = RoleDao.get_role_by_groups(groups, None, 0, 0)
        if role_id:
            roles = list(set(role_id) & set([one.id for one in group_roles]))
    if roles:
        roles_user_ids = UserRoleDao.get_roles_user(roles)
        if not roles_user_ids:
            return resp_200({'data': [], 'total': 0})
        roles_user_ids = [one.user_id for one in roles_user_ids]

        # 如果user_ids不为空，说明是groups一起做交集筛选，否则是只做角色筛选
        if user_ids:
            user_ids = list(set(user_ids) & set(roles_user_ids))
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
        # 如果不是超级管理，则需要将数据过滤, 不能看到非他操作用户管理的用户组内的角色和用户组列表
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

    return resp_200({
        'data': res,
        'total': total_count
    })


def get_user_roles(user: User, role_cache: Dict) -> List[Dict]:
    # 查询用户的角色列表
    user_roles = UserRoleDao.get_user_roles(user.user_id)
    user_role_ids: List[int] = [one_role.role_id for one_role in user_roles]
    res = []
    for i in range(len(user_role_ids) - 1, -1, -1):
        if role_cache.get(user_role_ids[i]):
            res.append(role_cache.get(user_role_ids[i]))
            del user_role_ids[i]
    # 将没有缓存的角色信息查询数据库
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
    # 查询用户的角色列表
    user_groups = UserGroupDao.get_user_group(user.user_id)
    user_group_ids: List[int] = [one_group.group_id for one_group in user_groups]
    res = []
    for i in range(len(user_group_ids) - 1, -1, -1):
        if group_cache.get(user_group_ids[i]):
            res.append(group_cache.get(user_group_ids[i]))
            del user_group_ids[i]
    # 将没有缓存的角色信息查询数据库
    if user_group_ids:
        group_list = GroupDao.get_group_by_ids(user_group_ids)
        for group_info in group_list:
            group_cache[group_info.id] = {
                "id": group_info.id,
                "name": group_info.group_name
            }
            res.append(group_cache.get(group_info.id))
    return res


@router.post('/user/update', status_code=201)
async def update(*, user: UserUpdate, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')
    with session_getter() as session:
        db_user = session.get(User, user.user_id)
    # check if user already exist
    if db_user and user.delete is not None:
        # 判断是否是管理员
        with session_getter() as session:
            admin = session.exec(
                select(UserRole).where(UserRole.role_id == 1,
                                       UserRole.user_id == user.user_id)).first()
        if admin:
            raise HTTPException(status_code=500, detail='不能操作管理员')
        db_user.delete = user.delete
    with session_getter() as session:
        session.add(db_user)
        session.commit()
    return resp_200()


@router.post('/role/add', status_code=201)
async def create_role(*, role: RoleCreate, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    if not role.role_name:
        raise HTTPException(status_code=500, detail='角色名称不能为空')

    db_role = Role.model_validate(role)
    try:
        with session_getter() as session:
            session.add(db_role)
            session.commit()
            session.refresh(db_role)
        return resp_200(db_role)
    except Exception:
        raise HTTPException(status_code=500, detail='添加失败，检查是否重复添加')


@router.patch('/role/{role_id}', status_code=201)
async def update_role(*, role_id: int, role: RoleUpdate, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    with session_getter() as session:
        db_role = session.get(Role, role_id)
    try:
        if role.role_name:
            db_role.role_name = role.role_name
        if role.remark:
            db_role.remark = role.remark

        with session_getter() as session:
            session.add(db_role)
            session.commit()
            session.refresh(db_role)
        return resp_200(db_role)
    except Exception:
        raise HTTPException(status_code=500, detail='添加失败，检查是否重复添加')


@router.get('/role/list', status_code=200)
async def get_role(*,
                   role_name: str = None,
                   page: int = 0,
                   limit: int = 0,
                   login_user: UserPayload = Depends(get_login_user)):
    """
    获取用户可见的角色列表， 根据用户权限不同返回不同的数据
    """
    # 参数处理
    if role_name:
        role_name = role_name.strip()

    # 判断是否是超级管理员
    if login_user.is_admin():
        # 是超级管理员获取全部
        group_ids = []
    else:
        # 查询下是否是其他用户组的管理员
        user_groups = UserGroupDao.get_user_admin_group(login_user.user_id)
        group_ids = [one.group_id for one in user_groups if one.is_group_admin]
        if not group_ids:
            raise HTTPException(status_code=500, detail='无查看权限')

    # 查询所有的角色列表
    res = RoleDao.get_role_by_groups(group_ids, role_name, page, limit)
    total = RoleDao.count_role_by_groups(group_ids, role_name)
    return resp_200(data={
        "data": res,
        "total": total
    })


@router.delete('/role/{role_id}', status_code=200)
async def delete_role(*, role_id: int, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    with session_getter() as session:
        db_role = session.get(Role, role_id)
    if db_role.role_name in {'系统管理员', '普通用户'}:
        raise HTTPException(status_code=500, detail='内置角色不能删除')

    # 删除role相关的数据
    try:
        with session_getter() as session:
            session.delete(db_role)
            session.exec(delete(UserRole).where(UserRole.role_id == role_id))
            session.exec(delete(RoleAccess).where(RoleAccess.role_id == role_id))
            session.commit()
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail='删除角色失败')
    return resp_200()


@router.post('/user/role_add', status_code=200)
async def user_addrole(*, userRole: UserRoleCreate, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无设置权限')

    with session_getter() as session:
        db_role = session.exec(select(UserRole).where(
            UserRole.user_id == userRole.user_id, )).all()
    role_ids = {role.role_id for role in db_role}
    db_roles = []
    for role_id in userRole.role_id:
        if role_id not in role_ids:
            db_role = UserRole(user_id=userRole.user_id, role_id=role_id)
            db_roles.append(db_role)
        else:
            role_ids.remove(role_id)
    if db_roles:
        with session_getter() as session:
            session.add_all(db_roles)
            session.commit()
    if role_ids:
        with session_getter() as session:
            session.exec(
                delete(UserRole).where(UserRole.user_id == userRole.user_id,
                                       UserRole.role_id.in_(role_ids)))
            session.commit()
    return resp_200()


@router.get('/user/role', status_code=200)
async def get_user_role(*, user_id: int, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无设置权限')

    with session_getter() as session:
        db_userroles = session.exec(select(UserRole).where(UserRole.user_id == user_id)).all()

    role_ids = [role.role_id for role in db_userroles]
    with session_getter() as session:
        db_role = session.exec(select(Role).where(Role.id.in_(role_ids))).all()
    role_name_dict = {role.id: role.role_name for role in db_role}

    res = []
    for db_user_role in db_userroles:
        user_role = db_user_role.__dict__
        if db_user_role.role_id not in role_name_dict:
            # 错误数据
            continue
        user_role['role_name'] = role_name_dict[db_user_role.role_id]
        res.append(user_role)

    return resp_200(res)


@router.post('/role_access/refresh', status_code=200)
async def access_refresh(*, data: RoleRefresh, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    role_id = data.role_id
    access_type = data.type
    access_id = data.access_id
    # delete old access
    with session_getter() as session:
        session.exec(
            delete(RoleAccess).where(RoleAccess.role_id == role_id,
                                     RoleAccess.type == access_type))
        session.commit()
    # 添加新的权限
    with session_getter() as session:
        for third_id in access_id:
            if access_type in [AccessType.FLOW.value, AccessType.ASSISTANT_READ.value]:
                third_id = UUID(third_id).hex
            role_access = RoleAccess(role_id=role_id, third_id=str(third_id), type=access_type)
            session.add(role_access)
        session.commit()
    return resp_200()


@router.get('/role_access/list', status_code=200)
async def access_list(*, role_id: int, type: Optional[int] = None, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    sql = select(RoleAccess).where(RoleAccess.role_id == role_id)
    count_sql = select(func.count(RoleAccess.id)).where(RoleAccess.role_id == role_id)
    if type:
        sql.where(RoleAccess.type == type)
        count_sql.where(RoleAccess.type == type)

    with session_getter() as session:
        db_role_access = session.exec(sql).all()
        total_count = session.scalar(count_sql)
    # uuid 和str的转化
    for access in db_role_access:
        if access.type in [AccessType.FLOW.value, AccessType.ASSISTANT_READ.value]:
            access.third_id = UUID(access.third_id)

    return resp_200({
        'data': [jsonable_encoder(access) for access in db_role_access],
        'total': total_count
    })


@router.get('/role_access/list_type', status_code=200)
async def data_by_role(*,
                       role_id: int,
                       page_size: int,
                       page_num: str,
                       name: Optional[str] = None,
                       role_type: str = 'assistant',
                       Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    if role_type == 'assistant':
        return resp_200(get_assistant_list_by_access(role_id, name, page_num, page_size))
    elif role_type == '':
        pass
    else:
        return resp_200()


@router.get('/role_access/knowledge', status_code=200)
async def knowledge_list(*,
                         role_id: int,
                         page_size: int,
                         page_num: str,
                         name: Optional[str] = None,
                         Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    statment = select(Knowledge,
                      RoleAccess).join(RoleAccess,
                                       and_(RoleAccess.role_id == role_id,
                                            RoleAccess.type == AccessType.KNOWLEDGE.value,
                                            RoleAccess.third_id == Knowledge.id),
                                       isouter=True)
    count_sql = select(func.count(Knowledge.id))

    if name:
        statment = statment.where(Knowledge.name.like('%' + name + '%'))
        count_sql = count_sql.where(Knowledge.name.like('%' + name + '%'))
    if page_num and page_size and page_num != 'undefined':
        page_num = int(page_num)
        statment = statment.order_by(RoleAccess.type.desc()).order_by(
            Knowledge.update_time.desc()).offset((page_num - 1) * page_size).limit(page_size)

    with session_getter() as session:
        db_role_access = session.exec(statment).all()
        total_count = session.scalar(count_sql)

    # 补充用户名
    user_ids = [access[0].user_id for access in db_role_access]
    with session_getter() as session:
        db_users = session.exec(select(User).where(User.user_id.in_(user_ids))).all()
    user_dict = {user.user_id: user.user_name for user in db_users}

    return resp_200({
        'data': [{
            'name': access[0].name,
            'user_name': user_dict.get(access[0].user_id),
            'user_id': access[0].user_id,
            'update_time': access[0].update_time,
            'id': access[0].id
        } for access in db_role_access],
        'total':
            total_count
    })


@router.get('/role_access/flow', status_code=200)
async def flow_list(*,
                    role_id: int,
                    page_size: int,
                    page_num: int,
                    name: Optional[str] = None,
                    Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    statment = select(Flow.id, Flow.name, Flow.user_id, Flow.update_time,
                      RoleAccess).join(RoleAccess,
                                       and_(RoleAccess.role_id == role_id,
                                            RoleAccess.type == AccessType.FLOW.value,
                                            RoleAccess.third_id == Flow.id),
                                       isouter=True)
    count_sql = select(func.count(Flow.id))

    if name:
        statment = statment.where(Flow.name.like('%' + name + '%'))
        count_sql = count_sql.where(Flow.name.like('%' + name + '%'))

    if page_num and page_size:
        statment = statment.order_by(RoleAccess.type.desc()).order_by(
            Flow.update_time.desc()).offset((page_num - 1) * page_size).limit(page_size)

    with session_getter() as session:
        db_role_access = session.exec(statment).all()
        total_count = session.scalar(count_sql)

    # 补充用户名
    user_ids = [access[2] for access in db_role_access]
    with session_getter() as session:
        db_users = session.exec(select(User).where(User.user_id.in_(user_ids))).all()
    user_dict = {user.user_id: user.user_name for user in db_users}
    return resp_200({
        'data': [{
            'name': access[1],
            'user_name': user_dict.get(access[2]),
            'user_id': access[2],
            'update_time': access[3],
            'id': access[0]
        } for access in db_role_access],
        'total':
            total_count
    })


@router.get('/user/get_captcha', status_code=200)
async def get_captcha():
    # generate captcha
    chr_all = string.ascii_letters + string.digits
    chr_4 = ''.join(random.sample(chr_all, 4))
    image = ImageCaptcha().generate_image(chr_4)
    # 对image 进行base 64 编码
    buffered = BytesIO()
    image.save(buffered, format='PNG')

    capthca_b64 = b64encode(buffered.getvalue()).decode()
    logger.info('get_captcha captcha_char={}', chr_4)
    # generate key, 生成简单的唯一id，
    key = CAPTCHA_PREFIX + uuid.uuid4().hex[:8]
    redis_client.set(key, chr_4, expiration=300)

    # 增加配置，是否必须使用验证码
    return resp_200({
        'captcha_key': key,
        'captcha': capthca_b64,
        'user_capthca': settings.get_from_db('use_captcha') or False
    })


@router.get('/user/public_key', status_code=200)
async def get_rsa_publish_key():
    # redis 存储
    key = RSA_KEY
    # redis lock
    if redis_client.setNx(key, 1):
        # Generate a key pair
        (pubkey, privkey) = rsa.newkeys(512)

        # Save the keys to strings
        redis_client.set(key, (pubkey, privkey), 3600)
    else:
        pubkey, privkey = redis_client.get(key)

    pubkey_str = pubkey.save_pkcs1().decode()

    return resp_200({'public_key': pubkey_str})


@router.post("/user/reset_password", status_code=200)
async def reset_password(*,
                         user_id: int = Body(embed=True),
                         password: str = Body(embed=True),
                         login_user: UserPayload = Depends(get_login_user)):
    """
    管理员重置用户密码
    """
    if not login_user.is_admin():
        raise HTTPException(status_code=403, detail='没有权限重置密码')
    # 获取要修改密码的用户信息
    user_info = UserDao.get_user(user_id)
    if not user_info:
        raise HTTPException(status_code=404, detail='用户不存在')

    # 查询用户所在的用户组
    user_groups = UserGroupDao.get_user_group(user_info.user_id)
    user_group_ids = [one.group_id for one in user_groups]

    # 检查是否有分组的管理权限
    if not login_user.check_groups_admin(user_group_ids):
        raise HTTPException(status_code=403, detail='没有权限重置密码')

    user_info.password = decrypt_md5_password(password)
    user_info.password_update_time = datetime.now()
    UserDao.update_user(user_info)
    return resp_200()


@router.post("/user/change_password", status_code=200)
async def change_password(*,
                          password: str = Body(embed=True),
                          new_password: str = Body(embed=True),
                          login_user: UserPayload = Depends(get_login_user)):
    """
    登录用户 修改自己的密码
    """
    user_info = UserDao.get_user(login_user.user_id)
    if not user_info.password:
        return UserNotPasswordError.return_resp()

    password = decrypt_md5_password(password)

    if user_info.password != md5_hash(password):
        return UserValidateError.return_resp()

    user_info.password = decrypt_md5_password(new_password)
    user_info.password_update_time = datetime.now()
    UserDao.update_user(user_info)
    return resp_200()


@router.post("/user/change_password_public", status_code=200)
async def change_password_public(*, username: str, password: str, new_password: str):
    """
    未登录用户 修改自己的密码
    """

    user_info = UserDao.get_user_by_username(username)
    if not user_info.password:
        return UserValidateError.return_resp()

    if user_info.password != decrypt_md5_password(password):
        return UserValidateError.return_resp()

    user_info.password = decrypt_md5_password(new_password)
    user_info.password_update_time = datetime.now()
    UserDao.update_user(user_info)
    return resp_200()


def md5_hash(string):
    md5 = hashlib.md5()
    md5.update(string.encode('utf-8'))
    return md5.hexdigest()
