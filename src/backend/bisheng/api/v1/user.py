import hashlib

from bisheng.database.base import get_session
from bisheng.database.models.user import User, UserCreate, UserLogin, UserRead
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWT
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/user', tags=['User'])

SECRET_KEY = 'xI$xO.oN$sC}tC^oQ(fF^nK~dB&uT('
ALGORITHM = 'HS256'
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')


@router.post('/regist', response_model=UserRead, status_code=201)
async def regist(*, session: Session = Depends(get_session), user: UserCreate):
    # check if user already exist
    db_user = session.exec(
        select(User).where(User.user_name == user.user_name)
    ).all()
    if db_user:
        raise HTTPException(status_code=404, detail='用户名已存在')
    else:
        user.password = md5_hash(user.password)
        db_user = User.from_orm(user)
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
        return db_user


@router.post('/login', response_model=UserRead, status_code=201)
async def login(
    *,
    session: Session = Depends(get_session),
    user: UserLogin,
    request: Request,
    response: Response
):
    # check if user already exist
    password = md5_hash(user.password)
    db_user = session.exec(
        select(User).where(
            User.user_name == user.user_name, User.password == password
        )
    ).first()
    if db_user:
        # 生成JWT令牌
        token = PyJWT().encode(
            payload={
                'user_name': user.user_name,
                'user_id': db_user.user_id
            },
            key=SECRET_KEY,
            algorithm=ALGORITHM
        )
        host = request.client.host
        response.set_cookie(
            'access_token_cookie', token, max_age=30 * 86400, domain=host
        )
        return db_user
    else:
        raise HTTPException(status_code=500, detail='密码不正确')


def md5_hash(string):
    md5 = hashlib.md5()
    md5.update(string.encode('utf-8'))
    return md5.hexdigest()
