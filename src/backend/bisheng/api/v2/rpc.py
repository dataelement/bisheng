
import json
from typing import Optional

from bisheng.database.base import get_session
from bisheng.database.models.user import User
from bisheng.database.models.user_role import UserRole
from bisheng.settings import settings
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from fastapi_jwt_auth import AuthJWT
from sqlmodel import Session, select

# build router
router = APIRouter(prefix='/rpc')


@router.get('/auth')
def set_cookie(*, deptId: Optional[str] = None, deptName: Optional[str] = None,
               session: Session = Depends(get_session),
               Authorize: AuthJWT = Depends()):
    """设置默认"""
    if deptId:
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
        user_id = settings.get_from_db('default_operator').get('user')
    else:
        user_id = db_user.user_id
        user_name = db_user.user_name

    payload = {'user_name': user_name, 'user_id': user_id, 'role': [2]}

    # Create the tokens and passing to set_access_cookies or set_refresh_cookies
    access_token = Authorize.create_access_token(subject=json.dumps(payload),
                                                 expires_time=864000)

    return RedirectResponse(settings.get_from_db('default_operator'
                                                 ).get('url')+f'?token={access_token}')
