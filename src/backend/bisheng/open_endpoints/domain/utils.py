from fastapi.exceptions import HTTPException

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.services.config_service import settings
from bisheng.user.domain.models.user import UserDao


def get_default_operator() -> UserPayload:
    user_id = settings.get_from_db('default_operator').get('user')
    if not user_id:
        raise HTTPException(status_code=500, detail='Not configureddefault_operatorIIuserConfigure')
    # Find default user information
    login_user = UserDao.get_user(user_id)
    if not login_user:
        raise HTTPException(status_code=500, detail='not founddefault_operatorIIuserUser Information')
    login_user = UserPayload.init_login_user_sync(user_id=login_user.user_id, user_name=login_user.user_name)
    return login_user


async def get_default_operator_async() -> UserPayload:
    user_id = (await settings.aget_from_db('default_operator')).get('user')
    if not user_id:
        raise HTTPException(status_code=500, detail='Not configureddefault_operatorIIuserConfigure')
    # Find default user information
    login_user = await UserDao.aget_user(user_id)
    if not login_user:
        raise HTTPException(status_code=500, detail='not founddefault_operatorIIuserUser Information')
    login_user = await UserPayload.init_login_user(user_id=login_user.user_id, user_name=login_user.user_name)

    return login_user
