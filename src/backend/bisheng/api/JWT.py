import json
from typing import List

from pydantic import BaseModel
from fastapi import Depends
from fastapi_jwt_auth import AuthJWT

from bisheng.settings import settings
from bisheng.api.services.user_service import UserPayload


class Settings(BaseModel):
    authjwt_secret_key: str = settings.jwt_secret
    # Configure application to store and get JWT from cookies
    authjwt_token_location: List[str] = ['cookies', 'headers']
    # Disable CSRF Protection for this example. default is True
    authjwt_cookie_csrf_protect: bool = False


async def get_login_user(authorize: AuthJWT = Depends()):
    """
    获取当前登录的用户
    """
    authorize.jwt_required()
    current_user = json.loads(authorize.get_jwt_subject())
    user = UserPayload(**current_user)
    return user
