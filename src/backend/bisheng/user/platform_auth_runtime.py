"""Application composition for API and worker platform authentication."""

from contextlib import contextmanager
from functools import lru_cache

from bisheng.user.domain.repositories.platform_session import PlatformSessionRepository
from bisheng.user.domain.services.platform_session import PlatformSessionService


@contextmanager
def platform_repository_scope():
    from bisheng.core.database import get_sync_db_session

    with get_sync_db_session() as db, db.begin():
        yield PlatformSessionRepository(db)


@lru_cache(maxsize=1)
def platform_auth_service():
    from bisheng.common.services.config_service import settings
    from bisheng.user.domain.services.jwt_secret import resolve_jwt_secret

    conf = settings.platform_auth

    async def login_policy():
        from loguru import logger
        from redis.exceptions import RedisError
        from sqlalchemy.exc import SQLAlchemyError

        from bisheng.common.errcode.platform_auth import PlatformAuthError

        try:
            return (await settings.aget_system_login_method()).allow_multi_login
        except (SQLAlchemyError, RedisError) as exc:
            logger.exception("Platform login policy unavailable")
            raise PlatformAuthError("auth_service_unavailable") from exc

    return PlatformSessionService(
        platform_repository_scope,
        secret=resolve_jwt_secret(),
        access_seconds=conf.access_ttl_seconds,
        idle_seconds=conf.idle_ttl_seconds,
        grace_seconds=conf.refresh_grace_seconds,
        absolute_seconds=conf.absolute_ttl_seconds,
        login_policy_reader=login_policy,
        issuance_enabled_reader=lambda: settings.platform_auth.enabled,
    )


def get_platform_auth(request):
    return getattr(request.app.state, "platform_auth_service", None) or platform_auth_service()
