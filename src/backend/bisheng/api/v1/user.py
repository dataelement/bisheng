import hashlib
import json
import random
import string
import uuid
from base64 import b64decode, b64encode
from io import BytesIO
from typing import List, Optional, Dict, Annotated
from uuid import UUID

import rsa
from bisheng.api.services.captcha import verify_captcha
from bisheng.api.services.user_service import gen_user_jwt, get_assistant_list_by_access, UserPayload
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
from bisheng.utils.constants import CAPTCHA_PREFIX, RSA_KEY
from bisheng.utils.logger import logger
from captcha.image import ImageCaptcha
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.security import OAuth2PasswordBearer
from fastapi_jwt_auth import AuthJWT
from sqlalchemy import and_, func
from sqlmodel import delete, select

# build router
router = APIRouter(prefix='', tags=['User'])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')


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
            if value := redis_client.get(RSA_KEY):
                private_key = value[1]
                db_user.password = md5_hash(
                    rsa.decrypt(b64decode(user.password), private_key).decode('utf-8'))
            else:
                db_user.password = md5_hash(user.password)
            with session_getter() as session:
                session.add(db_user)
                session.flush()
                session.refresh(db_user)
                # 默认加入普通用户
                if db_user.user_id != 1:
                    db_user_role = UserRole(user_id=db_user.user_id, role_id=2)
                    session.add(db_user_role)
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

    # check if user already exist
    if value := redis_client.get(RSA_KEY):
        private_key = value[1]
        password = md5_hash(rsa.decrypt(b64decode(user.password), private_key).decode('utf-8'))
    else:
        password = md5_hash(user.password)

    with session_getter() as session:
        db_user = session.exec(
            select(User).where(User.user_name == user.user_name,
                               User.password == password)).first()
    if db_user:
        access_token, refresh_token, role = gen_user_jwt(db_user)

        # Set the JWT cookies in the response
        Authorize.set_access_cookies(access_token)
        Authorize.set_refresh_cookies(refresh_token)

        return resp_200(UserRead(role=str(role), access_token=access_token, **db_user.__dict__))
    else:
        raise HTTPException(status_code=500, detail='密码不正确')


@router.get('/user/info', response_model=UnifiedResponseModel[UserRead], status_code=201)
async def get_info(Authorize: AuthJWT = Depends()):
    # check if user already exist
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    try:
        user_id = payload.get('user_id')
        with session_getter() as session:
            user = session.get(User, user_id)
            # 查询角色
            db_user_role = session.exec(select(UserRole).where(UserRole.user_id == user_id)).all()
        if next((user_role for user_role in db_user_role if user_role.role_id == 1), None):
            # 是管理员，忽略其他的角色
            role = 'admin'
        else:
            role = [user_role.role_id for user_role in db_user_role]
        return resp_200(UserRead(role=str(role), **user.__dict__))
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
                    Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    login_user = UserPayload(**payload)
    if login_user.is_admin():
        groups = group_id
    else:
        # 查询下是否是其他用户组的管理员
        user_groups = UserGroupDao.get_user_group(login_user.user_id)
        groups = []
        for one in user_groups:
            if one.is_group_admin:
                groups.append(one.group_id)
        # 不是任何用户组的管理员无查看权限
        if not groups:
            raise HTTPException(status_code=500, detail='无查看权限')
        # 将筛选条件的group_id和管理员有权限的groups做交集
        if group_id:
            groups = list(set(groups) & set(group_id))
            if not groups:
                raise HTTPException(status_code=500, detail='无查看权限')

    user_ids = []
    if groups:
        groups_user_ids = UserGroupDao.get_groups_admins(groups)
        if not groups_user_ids:
            return resp_200({'data': [], 'total': 0})
        user_ids = list(set([one.user_id for one in groups_user_ids]))
    if role_id:
        roles_user_ids = UserRoleDao.get_roles_user(role_id)
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
        one_data["roles"] = get_user_roles(one, role_dict)
        one_data["groups"] = get_user_groups(one, group_dict)
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
async def get_role(*, role_name: str = None, Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    if role_name:
        role_name = role_name.strip()
        sql = select(Role.role_name, Role.remark, Role.create_time, Role.update_time, Role.id)
        count_sql = select(func.count(Role.id))
        if role_name:
            sql = sql.where(Role.role_name.like(f'%{role_name}%'))
            count_sql = count_sql.where(Role.role_name.like(f'%{role_name}%'))

        sql = sql.order_by(Role.update_time.desc())
        with session_getter() as session:
            roles = session.exec(sql)
        db_role = roles.mappings().all()

    else:
        # 默认不返回 管理员和普通用户，因为用户无法设置
        with session_getter() as session:
            db_role = session.exec(select(Role).where(Role.id > 1)).all()
    return resp_200([jsonable_encoder(role) for role in db_role])


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


def md5_hash(string):
    md5 = hashlib.md5()
    md5.update(string.encode('utf-8'))
    return md5.hexdigest()
