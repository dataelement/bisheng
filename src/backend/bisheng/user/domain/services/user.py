from base64 import b64decode
from datetime import datetime
from typing import List

import rsa
from fastapi import Request, Depends

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schemas import CreateUserReq
from bisheng.common.constants.enums.telemetry import BaseTelemetryTypeEnum
from bisheng.common.errcode.user import (UserNameAlreadyExistError,
                                         UserNeedGroupAndRoleError, UserForbiddenError, CaptchaError, UserValidateError,
                                         UserPasswordMaxTryError, UserPasswordExpireError, UserNameTooLongError)
from bisheng.common.schemas.api import resp_200
from bisheng.common.schemas.telemetry.event_data_schema import UserLoginEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client_sync, get_redis_client
from bisheng.core.logger import trace_id_var
from bisheng.database.models.user_group import UserGroupDao
from bisheng.user.domain.models.user import User, UserDao, UserLogin, UserRead, UserCreate
from bisheng.utils import md5_hash, get_request_ip
from bisheng.utils.constants import RSA_KEY
from .auth import LoginUser, AuthJwt
from .captcha import verify_captcha
from ..const import USER_PASSWORD_ERROR, USER_CURRENT_SESSION


class UserService:

    @classmethod
    def decrypt_md5_password(cls, password: str):
        if value := get_redis_client_sync().get(RSA_KEY):
            private_key = value[1]
            password = md5_hash(rsa.decrypt(b64decode(password), private_key).decode('utf-8'))
        else:
            password = md5_hash(password)
        return password

    @classmethod
    def create_user(cls, request: Request, login_user: LoginUser, req_data: CreateUserReq):
        """
        Create User
        """
        exists_user = UserDao.get_user_by_username(req_data.user_name)
        if exists_user:
            # Throwing an exception?
            raise UserNameAlreadyExistError.http_exception()
        user = User(
            user_name=req_data.user_name,
            password=cls.decrypt_md5_password(req_data.password),
        )
        group_ids = []
        role_ids = []
        for one in req_data.group_roles:
            group_ids.append(one.group_id)
            role_ids.extend(one.role_ids)
        if not group_ids or not role_ids:
            raise UserNeedGroupAndRoleError.http_exception()
        user = UserDao.add_user_with_groups_and_roles(user, group_ids, role_ids)
        return user

    @staticmethod
    def get_error_password_key(username: str):
        return USER_PASSWORD_ERROR.format(username)

    @classmethod
    async def clear_error_password_key(cls, username: str):
        # Count of cleanup password errors
        error_key = cls.get_error_password_key(username)
        (await get_redis_client()).delete(error_key)

    @classmethod
    async def judge_user_password(cls, db_user: User, password: str) -> None:
        redis_client = await get_redis_client()

        password_conf = await settings.get_password_conf()
        if not db_user.password:
            raise UserValidateError()

        if db_user.password == password:
            # Determine if the password has not been changed for a long time
            if password_conf.password_valid_period and password_conf.password_valid_period > 0:
                if (datetime.now() - db_user.password_update_time).days >= password_conf.password_valid_period:
                    raise UserPasswordExpireError()
            return

        # Determine if the number of errors needs to be logged
        if not password_conf.login_error_time_window or not password_conf.max_error_times:
            raise UserValidateError()
        # Number of errors plus1
        error_key = cls.get_error_password_key(db_user.user_name)
        error_num = await redis_client.aincr(error_key)
        if error_num == 1:
            # First time setupkeyExpiration date
            await redis_client.aexpire_key(error_key, password_conf.login_error_time_window * 60)
        if error_num and int(error_num) >= password_conf.max_error_times:
            # Maximum number of errors reached, account banned
            db_user.delete = 1
            await UserDao.aupdate_user(db_user)
            raise UserPasswordMaxTryError()
        raise UserValidateError()

    @classmethod
    async def user_register(cls, user: UserCreate):
        # Captcha Verification
        if settings.get_from_db('use_captcha'):
            if not user.captcha_key or not await verify_captcha(user.captcha, user.captcha_key):
                raise CaptchaError()

        db_user = User.model_validate(user)

        # check if user already exist
        user_exists = await UserDao.aget_user_by_username(db_user.user_name)
        if user_exists:
            raise UserNameAlreadyExistError()
        if len(db_user.user_name) > 30:
            raise UserNameTooLongError()
        db_user.password = cls.decrypt_md5_password(user.password)
        # Under JudgmentadminDoes the user exist
        admin = await UserDao.aget_user(1)
        if admin:
            db_user = await UserDao.add_user_and_default_role(db_user)
        else:
            db_user.user_id = 1
            db_user = await UserDao.add_user_and_admin_role(db_user)
        # Write users to the default user group
        await UserGroupDao.add_default_user_group(db_user.user_id)
        return db_user

    @classmethod
    async def user_login(cls, request: Request, user: UserLogin, auth_jwt: AuthJwt = Depends()):
        if await settings.aget_from_db('use_captcha'):
            if not user.captcha_key or not await verify_captcha(user.captcha, user.captcha_key):
                raise CaptchaError()

        # get user info
        db_user = await UserDao.aget_user_by_username(user.user_name)
        # verify user exists
        if not db_user:
            return UserValidateError.return_resp()
        if db_user.delete == 1:
            raise UserForbiddenError()

        # verify password
        password = cls.decrypt_md5_password(user.password)
        await cls.judge_user_password(db_user, password)

        # gen jwt token
        access_token = LoginUser.create_access_token(user=db_user, auth_jwt=auth_jwt)

        # set cookies
        LoginUser.set_access_cookies(access_token, auth_jwt=auth_jwt)

        # Set the logged in user's currentcookie, .jwtValid for an additional hour
        redis_client = await get_redis_client()
        await redis_client.aset(USER_CURRENT_SESSION.format(db_user.user_id), access_token,
                                auth_jwt.cookie_conf.jwt_token_expire_time + 3600)

        # Log Audit Logs
        login_user = await LoginUser.init_login_user(db_user.user_id, db_user.user_name)
        AuditLogService.user_login(login_user, get_request_ip(request))

        # RecordTelemetryJournal
        await telemetry_service.log_event(user_id=db_user.user_id, event_type=BaseTelemetryTypeEnum.USER_LOGIN,
                                          trace_id=trace_id_var.get(),
                                          event_data=UserLoginEventData(method="password"))

        return resp_200(UserRead(access_token=access_token, **db_user.__dict__))

    @classmethod
    def get_user_all_info(cls, *, start_time: datetime = None, end_time: datetime = None, user_ids: List[int] = None,
                          page: int = 1, page_size: int = 100) -> List[User]:
        """ Get user information, including user group and role information """
        return UserDao.get_user_with_group_role(page=page, page_size=page_size, user_ids=user_ids,
                                                start_time=start_time, end_time=end_time)

    @classmethod
    def get_first_user(cls) -> User | None:
        """ Get the first user """
        return UserDao.get_first_user()

    @classmethod
    async def get_user_by_id(cls, user_id: int) -> User | None:
        """ Get user by username """
        return await UserDao.aget_user(user_id)
