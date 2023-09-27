import hashlib
import json

from sqlalchemy import func

from bisheng.database.base import get_session
from bisheng.database.models.user import (User, UserCreate, UserLogin, UserRead, UserUpdate)
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.security import OAuth2PasswordBearer
from fastapi_jwt_auth import AuthJWT
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/user', tags=['User'])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')


@router.post('/regist', response_model=UserRead, status_code=201)
async def regist(*, session: Session = Depends(get_session), user: UserCreate):
    # check if user already exist
    db_user = session.exec(select(User).where(User.user_name == user.user_name)).all()
    if db_user:
        raise HTTPException(status_code=500, detail='账号已存在')
    else:
        user.password = md5_hash(user.password)
        db_user = User.from_orm(user)
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
        return db_user


@router.post('/login', response_model=UserRead, status_code=201)
async def login(*, session: Session = Depends(get_session), user: UserLogin, Authorize: AuthJWT = Depends()):
    # check if user already exist
    password = md5_hash(user.password)
    db_user = session.exec(select(User).where(User.user_name == user.user_name, User.password == password)).first()
    if db_user:
        if 1 == db_user.delete:
            raise HTTPException(status_code=500, detail='该账号已被禁用，请联系管理员')
        # 生成JWT令牌
        payload = {'user_name': user.user_name, 'user_id': db_user.user_id, 'role': db_user.role}
        # Create the tokens and passing to set_access_cookies or set_refresh_cookies
        access_token = Authorize.create_access_token(subject=json.dumps(payload), expires_time=86400)
        refresh_token = Authorize.create_refresh_token(subject=user.user_name)

        # Set the JWT cookies in the response
        Authorize.set_access_cookies(access_token)
        Authorize.set_refresh_cookies(refresh_token)
        return db_user
    else:
        raise HTTPException(status_code=500, detail='密码不正确')


@router.post('/logout', status_code=201)
async def logout(Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    Authorize.unset_jwt_cookies()
    return {'msg': 'Successfully logout'}


@router.get('/list', status_code=201)
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
        sql = sql.offset((page_num - 1) * page_size).limit(page_size)
    users = session.exec(sql).all()
    return {"data": [jsonable_encoder(UserRead.from_orm(user)) for user in users], "total": total_count}


@router.post('/update', status_code=201)
async def update(*, user: UserUpdate, session: Session = Depends(get_session), Authorize: AuthJWT = Depends()):
    Authorize.jwt_required()
    if 'admin' != json.loads(Authorize.get_jwt_subject()).get('role'):
        raise HTTPException(status_code=500, detail='无查看权限')

    db_user = session.get(User, user.user_id)
    if db_user and user.delete is not None:
        if db_user.role == 'admin':
            raise HTTPException(status_code=500, detail='不能操作管理员')
        db_user.delete = user.delete

    session.add(db_user)
    session.commit()
    return {'msg': 'success'}


def md5_hash(string):
    md5 = hashlib.md5()
    md5.update(string.encode('utf-8'))
    return md5.hexdigest()
