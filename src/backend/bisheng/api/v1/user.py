import hashlib
import json
from typing import Optional
from uuid import UUID

from bisheng.database.base import get_session
from bisheng.database.models.flow import Flow
from bisheng.database.models.knowledge import Knowledge
from bisheng.database.models.role import Role, RoleCreate, RoleUpdate
from bisheng.database.models.role_access import AccessType, RoleAccess, RoleRefresh
from bisheng.database.models.user import User, UserCreate, UserLogin, UserRead, UserUpdate
from bisheng.database.models.user_role import UserRole, UserRoleCreate
from bisheng.utils.logger import logger
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.security import OAuth2PasswordBearer
from fastapi_jwt_auth import AuthJWT
from sqlalchemy import and_, func
from sqlmodel import Session, delete, select

# build router
router = APIRouter(prefix='', tags=['User'])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')


@router.post('/user/regist', response_model=UserRead, status_code=201)
async def regist(*, session: Session = Depends(get_session), user: UserCreate):
    db_user = User.from_orm(user)
    # check if admin user
    admin = session.exec(select(User).where(User.user_id == 1)).all()
    if not admin:
        db_user_role = UserRole(user_id=db_user.user_id, role_id=1)
        db_user.user_id = 1

    # check if user already exist
    name_user = session.exec(select(User).where(User.user_name == user.user_name)).all()
    if name_user:
        raise HTTPException(status_code=500, detail='账号已存在')
    else:
        try:
            db_user.password = md5_hash(user.password)
            session.add(db_user)
            session.flush()
            session.refresh(db_user)
            # 默认加入普通用户
            if db_user != 1:
                db_user_role = UserRole(user_id=db_user.user_id, role_id=2)
                session.add(db_user_role)
            session.commit()
        except Exception as e:
            session.rollback()
            raise HTTPException(status_code=500, detail=f'数据库写入错误， {str(e)}')
        return db_user


@router.post('/user/login', response_model=UserRead, status_code=201)
async def login(*,
                session: Session = Depends(get_session),
                user: UserLogin,
                Authorize: AuthJWT = Depends()):
    # check if user already exist
    password = md5_hash(user.password)
    db_user = session.exec(
        select(User).where(User.user_name == user.user_name, User.password == password)).first()
    if db_user:
        if 1 == db_user.delete:
            raise HTTPException(status_code=500, detail='该账号已被禁用，请联系管理员')
        # 查询角色
        db_user_role = session.exec(
            select(UserRole).where(UserRole.user_id == db_user.user_id)).all()

        if next((user_role for user_role in db_user_role if user_role.role_id == 1), None):
            # 是管理员，忽略其他的角色
            role = 'admin'
        else:
            role = [user_role.role_id for user_role in db_user_role]
        # 生成JWT令牌
        payload = {'user_name': user.user_name, 'user_id': db_user.user_id, 'role': role}
        # Create the tokens and passing to set_access_cookies or set_refresh_cookies
        access_token = Authorize.create_access_token(subject=json.dumps(payload),
                                                     expires_time=86400)

        refresh_token = Authorize.create_refresh_token(subject=user.user_name)

        # Set the JWT cookies in the response
        Authorize.set_access_cookies(access_token)
        Authorize.set_refresh_cookies(refresh_token)

        return UserRead(role=str(role), **db_user.__dict__)
    else:
        raise HTTPException(status_code=500, detail='密码不正确')


@router.get('/user/info', response_model=UserRead, status_code=201)
async def get_info(session: Session = Depends(get_session), Authorize: AuthJWT = Depends()):
    # check if user already exist
    Authorize.jwt_required()
    payload = json.loads(Authorize.get_jwt_subject())
    try:
        user_id = payload.get('user_id')
        user = session.get(User, user_id)
        # 查询角色
        db_user_role = session.exec(select(UserRole).where(UserRole.user_id == user_id)).all()
        if next((user_role for user_role in db_user_role if user_role.role_id == 1), None):
            # 是管理员，忽略其他的角色
            role = 'admin'
        else:
            role = [user_role.role_id for user_role in db_user_role]
        return UserRead(role=str(role), **user.__dict__)
    except Exception:
        raise HTTPException(status_code=500, detail='用户信息失败')


@router.post('/user/logout', status_code=201)
async def logout(Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    Authorize.unset_jwt_cookies()
    return {'msg': 'Successfully logout'}


@router.get('/user/list', status_code=201)
async def list(*,
               name: str,
               page_size: int,
               page_num: int,
               session: Session = Depends(get_session),
               Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')
    sql = select(User)
    count_sql = select(func.count(User.user_id))
    if name:
        sql = sql.where(User.user_name.like(f'%{name}%'))
        count_sql = count_sql.where(User.user_name.like(f'%{name}%'))
    total_count = session.scalar(count_sql)

    if page_size and page_num:
        sql = sql.order_by(User.user_id.desc()).offset((page_num - 1) * page_size).limit(page_size)
    users = session.exec(sql).all()
    return {
        'data': [jsonable_encoder(UserRead.from_orm(user)) for user in users],
        'total': total_count
    }


@router.post('/user/update', status_code=201)
async def update(*,
                 user: UserUpdate,
                 session: Session = Depends(get_session),
                 Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    db_user = session.get(User, user.user_id)
    if db_user and user.delete is not None:
        # 判断是否是管理员
        admin = session.exec(
            select(UserRole).where(UserRole.role_id == 1,
                                   UserRole.user_id == user.user_id)).first()
        if admin:
            raise HTTPException(status_code=500, detail='不能操作管理员')
        db_user.delete = user.delete

    session.add(db_user)
    session.commit()
    return {'msg': 'success'}


@router.post('/role/add', status_code=201)
async def create_role(*,
                      role: RoleCreate,
                      session: Session = Depends(get_session),
                      Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    if not role.role_name:
        raise HTTPException(status_code=500, detail='角色名称不能为空')

    db_role = Role.from_orm(role)
    try:
        session.add(db_role)
        session.commit()
        session.refresh(db_role)
        return {'data': jsonable_encoder(db_role)}
    except Exception as e:
        logger.excepition(e)
        raise HTTPException(status_code=500, detail='添加失败，检查是否重复添加')


@router.patch('/role/{role_id}', status_code=201)
async def update_role(*,
                      role_id: int,
                      role: RoleUpdate,
                      session: Session = Depends(get_session),
                      Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    db_role = session.get(Role, role_id)
    try:
        if role.role_name:
            db_role.role_name = role.role_name
        if role.remark:
            db_role.remark = role.remark

        session.add(db_role)
        session.commit()
        session.refresh(db_role)
        return {'data': jsonable_encoder(db_role)}
    except Exception as e:
        logger.excepition(e)
        raise HTTPException(status_code=500, detail='添加失败，检查是否重复添加')


@router.get('/role/list', status_code=200)
async def get_role(*, session: Session = Depends(get_session), Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')
    # 默认不返回 管理员和普通用户，因为用户无法设置
    db_role = session.exec(select(Role).where(Role.id > 1)).all()
    return {'data': [jsonable_encoder(role) for role in db_role]}


@router.delete('/role/{role_id}', status_code=200)
async def delete_role(*,
                      role_id: int,
                      session: Session = Depends(get_session),
                      Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    db_role = session.get(Role, role_id)
    if db_role.role_name in {'系统管理员', '普通用户'}:
        raise HTTPException(status_code=500, detail='内置角色不能删除')

    # 删除role相关的数据
    try:
        session.delete(db_role)
        session.exec(delete(UserRole).where(UserRole.role_id == role_id))
        session.exec(delete(RoleAccess).where(RoleAccess.role_id == role_id))
        session.commit()
    except Exception as e:
        logger.exception(e)
        session.rollback()
        raise HTTPException(status_code=500, detail='删除角色失败')
    return {'message': 'success'}


@router.post('/user/role_add', status_code=200)
async def user_addrole(*,
                       userRole: UserRoleCreate,
                       session: Session = Depends(get_session),
                       Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无设置权限')

    db_role = session.exec(select(UserRole).where(UserRole.user_id == userRole.user_id, )).all()
    role_ids = {role.role_id for role in db_role}
    for role_id in userRole.role_id:
        if role_id not in role_ids:
            db_role = UserRole(user_id=userRole.user_id, role_id=role_id)
            session.add(db_role)
        else:
            role_ids.remove(role_id)
    if role_ids:
        session.exec(
            delete(UserRole).where(UserRole.user_id == userRole.user_id,
                                   UserRole.role_id.in_(role_ids)))
    session.commit()
    return {'message': 'success'}


@router.get('/user/role', status_code=200)
async def get_user_role(*,
                        user_id: int,
                        session: Session = Depends(get_session),
                        Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无设置权限')

    db_userroles = session.exec(select(UserRole).where(UserRole.user_id == user_id)).all()

    role_ids = [role.role_id for role in db_userroles]
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

    return {'message': 'success', 'data': res}


@router.post('/role_access/refresh', status_code=200)
async def access_refresh(*,
                         data: RoleRefresh,
                         session: Session = Depends(get_session),
                         Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    role_id = data.role_id
    access_type = data.type
    access_id = data.access_id
    # delete old access
    session.exec(
        delete(RoleAccess).where(RoleAccess.role_id == role_id, RoleAccess.type == access_type))
    session.commit()
    # 添加新的权限
    for id in access_id:
        if access_type == AccessType.FLOW.value:
            id = UUID(id).hex
        role_access = RoleAccess(role_id=role_id, third_id=str(id), type=access_type)
        session.add(role_access)
    session.commit()
    return {'msg': 'success'}


@router.get('/role_access/list', status_code=200)
async def access_list(*,
                      role_id: int,
                      type: Optional[int] = None,
                      session: Session = Depends(get_session),
                      Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    sql = select(RoleAccess).where(RoleAccess.role_id == role_id)
    count_sql = select(func.count(RoleAccess.id)).where(RoleAccess.role_id == role_id)
    if type:
        sql.where(RoleAccess.type == type)
        count_sql.where(RoleAccess.type == type)

    db_role_access = session.exec(sql).all()
    total_count = session.scalar(count_sql)
    # uuid 和str的转化
    for access in db_role_access:
        if access.type == AccessType.FLOW.value:
            access.third_id = UUID(access.third_id)

    return {
        'msg': 'success',
        'data': [jsonable_encoder(access) for access in db_role_access],
        'total': total_count
    }


@router.get('/role_access/knowledge', status_code=200)
async def knowledge_list(*,
                         role_id: int,
                         page_size: int,
                         page_num: str,
                         name: Optional[str] = None,
                         session: Session = Depends(get_session),
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

    db_role_access = session.exec(statment).all()
    total_count = session.scalar(count_sql)

    # 补充用户名
    user_ids = [access[0].user_id for access in db_role_access]
    db_users = session.query(User).filter(User.user_id.in_(user_ids)).all()
    user_dict = {user.user_id: user.user_name for user in db_users}

    return {
        'msg':
        'success',
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


@router.get('/role_access/flow', status_code=200)
async def flow_list(*,
                    role_id: int,
                    page_size: int,
                    page_num: int,
                    name: Optional[str] = None,
                    session: Session = Depends(get_session),
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

    db_role_access = session.exec(statment).all()
    total_count = session.scalar(count_sql)

    # 补充用户名
    user_ids = [access[2] for access in db_role_access]
    db_users = session.query(User).filter(User.user_id.in_(user_ids)).all()
    user_dict = {user.user_id: user.user_name for user in db_users}
    return {
        'msg':
        'success',
        'data': [{
            'name': access[1],
            'user_name': user_dict.get(access[2]),
            'user_id': access[2],
            'update_time': access[3],
            'id': access[0]
        } for access in db_role_access],
        'total':
        total_count
    }


def md5_hash(string):
    md5 = hashlib.md5()
    md5.update(string.encode('utf-8'))
    return md5.hexdigest()


if __name__ == '__main__':
    payload = {
        'UserId': 1300000000111,
        'TenantId': 1300000000001,
        'Account': 'admin',
        'RealName': '系统管理员',
        'AccountType': 4,
    }
