import json
from typing import Optional

from bisheng.database.base import get_session
from bisheng.database.models.user import User
from bisheng.database.models.user_role import UserRole
from bisheng.settings import settings
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from fastapi_jwt_auth import AuthJWT
from loguru import logger
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/rpc')


@router.get('/auth')
def set_cookie(*,
               deptId: Optional[str] = None,
               deptName: Optional[str] = None,
               menu: Optional[str] = '',
               user_id: Optional[int] = None,
               role_id: Optional[int] = None,
               session: Session = Depends(get_session),
               Authorize: AuthJWT = Depends()):
    """设置默认"""
    if deptId:
        # this interface should update user model, and now the main ref don't mathes
        db_user = session.exec(select(User).where(User.dept_id == deptId)).first()
        if not db_user:
            db_user = User(user_name=deptName, password='none', dept_id=deptId)
            session.add(db_user)
            session.flush()
            db_user_role = UserRole(user_id=db_user.user_id, role_id=2)
            session.add(db_user_role)
            session.commit()
            session.refresh(db_user)
    if not deptId:
        dept_user_id = settings.get_from_db('default_operator').get('user')
    else:
        dept_user_id = db_user.user_id

    payload = {'user_name': deptName, 'user_id': dept_user_id, 'role': [2]}
    # admin
    role_admin = session.query(UserRole).where(UserRole.user_id == user_id,
                                               UserRole.role_id == 1).first()
    try:
        if user_id and role_id == 1:
            if not role_admin:
                # keep
                admin_user = session.get(User, user_id)
                if not admin_user:
                    db_user = User(id=user_id, user_name=deptName, password='none', dept_id=deptId)
                    session.add(db_user)
                db_user_role = UserRole(user_id=user_id, role_id=1)
                session.add(db_user_role)
            payload = {'user_name': deptName, 'user_id': user_id, 'role': 'admin'}
        elif user_id:
            if role_admin:
                # delete
                session.delete(role_admin)
        session.commit()
    except Exception as e:
        logger.error(str(e))
        session.rollback()

    # Create the tokens and passing to set_access_cookies or set_refresh_cookies
    access_token = Authorize.create_access_token(subject=json.dumps(payload), expires_time=864000)

    return RedirectResponse(
        settings.get_from_db('default_operator').get('url') + '/' + menu +
        f'?token={access_token}')
