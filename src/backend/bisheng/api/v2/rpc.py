
import json

from bisheng.settings import settings
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from fastapi_jwt_auth import AuthJWT

# build router
router = APIRouter(prefix='/rpc')


@router.get('/auth')
def set_cookie(Authorize: AuthJWT = Depends()):
    """设置默认"""
    default_user_id = settings.get_from_db('default_operator').get('user')
    payload = {'user_name': 'operator', 'user_id': default_user_id, 'role': [2]}
    # Create the tokens and passing to set_access_cookies or set_refresh_cookies
    access_token = Authorize.create_access_token(subject=json.dumps(payload),
                                                 expires_time=864000)

    return RedirectResponse(settings.get_from_db('default_operator'
                                                 ).get('url')+f'?token={access_token}')
