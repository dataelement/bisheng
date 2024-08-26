from fastapi.exceptions import HTTPException

from bisheng.api.services.user_service import UserPayload
from bisheng.database.models.user import UserDao, User
from bisheng.settings import settings


def get_default_operator() -> UserPayload:
    user_id = settings.get_from_db('default_operator').get('user')
    if not user_id:
        raise HTTPException(status_code=500, detail='未配置default_operator中user配置')
    # 查找默认用户信息
    login_user = UserDao.get_user(user_id)
    if not login_user:
        raise HTTPException(status_code=500, detail='未找到default_operator中user的用户信息')
    login_user = UserPayload(**{
        'user_id': login_user.user_id,
        'user_name': login_user.user_name,
        'role': ''
    })
    return login_user
