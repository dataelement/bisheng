"""Short-lived browser sessions bound to the active Desktop grant in Redis."""

import secrets
import time

import jwt

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError
from bisheng.dsh.domain.services.access import principal_scope

PREFIX = "dsh:web-session:"


async def session_store():
    from bisheng.core.cache.redis_manager import get_redis_client

    return (await get_redis_client()).async_connection


async def create_web_session(runtime, authorization: str) -> dict:
    from bisheng.user.domain.models.user import UserDao
    from bisheng.user.domain.services.auth import AuthJwt

    principal = await runtime.access.authenticate(authorization)
    # authenticate verified this exact JWT, including its expiration and grant.
    claims = jwt.decode(authorization[7:], options={"verify_signature": False})
    ttl = min(300, int(claims["exp"]) - int(time.time()))
    if ttl < 30:
        raise DshInvalidAccessTokenError()
    with principal_scope(principal):
        user = await UserDao.aget_user(int(principal.user_id))
        if user is None or int(user.delete or 0) == 1:
            raise DshInvalidAccessTokenError()
        key = secrets.token_urlsafe(32)
        subject = {
            "user_id": int(principal.user_id),
            "user_name": user.user_name,
            "tenant_id": int(principal.tenant_id),
            "token_version": int(user.token_version or 0),
            "dsh_web_session": key,
        }
        cookie = AuthJwt().create_access_token(subject, expires_in=ttl)
        redis = await session_store()
        await redis.set(PREFIX + key, authorization, ex=ttl)
    return {"cookie": cookie, "expires_in": ttl}


async def validate_web_session(connection, subject: dict) -> None:
    from bisheng.dsh.access_runtime import get_runtime, get_settings

    key = subject.get("dsh_web_session")
    if not isinstance(key, str) or len(key) != 43:
        raise DshInvalidAccessTokenError()
    redis = await session_store()
    authorization = await redis.get(PREFIX + key)
    if not authorization:
        raise DshInvalidAccessTokenError()
    if isinstance(authorization, bytes):
        authorization = authorization.decode("utf-8")
    runtime = await get_runtime(connection, get_settings())
    principal = await runtime.access.authenticate(authorization)
    if (int(principal.user_id), int(principal.tenant_id)) != (subject["user_id"], subject["tenant_id"]):
        raise DshInvalidAccessTokenError()
