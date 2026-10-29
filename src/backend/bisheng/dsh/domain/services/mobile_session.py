"""Phone refresh sessions issue platform JWTs, not desktop access tokens."""

import asyncio
import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from bisheng.common.errcode.dsh import (
    DshAuthorizationConflictError,
    DshAuthorizationUnavailableError,
    DshInvalidRefreshTokenError,
    DshMobileLoggedInElsewhereError,
    DshMobileTenantUnavailableError,
    DshMobileTokenVersionError,
    DshMobileUserDisabledError,
    DshRefreshTokenReusedError,
    DshSessionExpiredError,
    DshSessionRevokedError,
)
from bisheng.dsh.domain.services.access import DshPrincipal, principal_scope

_REFRESH_ERRORS = {
    "invalid_refresh_token": DshInvalidRefreshTokenError,
    "refresh_token_reused": DshRefreshTokenReusedError,
    "session_expired": DshSessionExpiredError,
    "session_revoked": DshSessionRevokedError,
    "user_disabled": DshMobileUserDisabledError,
    "tenant_unavailable": DshMobileTenantUnavailableError,
    "token_version_changed": DshMobileTokenVersionError,
    "logged_in_elsewhere": DshMobileLoggedInElsewhereError,
}


class MobileAccount:
    def __init__(
        self,
        *,
        user_id: int,
        tenant_id: int,
        user_name: str | None = None,
        token_version: int = 0,
        user_active: bool = True,
        tenant_active: bool = True,
    ):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.user_name = user_name
        self.token_version = token_version
        self.user_active = user_active
        self.tenant_active = tenant_active


class RedisCurrentSession:
    """The single-login Redis key stores the raw access token, never the refresh token."""

    async def get(self, user_id: int) -> str | None:
        from bisheng.core.cache.redis_manager import get_redis_client
        from bisheng.user.domain.const import USER_CURRENT_SESSION

        redis = await get_redis_client()
        value = await redis.aget(USER_CURRENT_SESSION.format(user_id))
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def put(self, user_id: int, token: str, ttl: int) -> None:
        from bisheng.core.cache.redis_manager import get_redis_client
        from bisheng.user.domain.const import USER_CURRENT_SESSION

        redis = await get_redis_client()
        await redis.aset(USER_CURRENT_SESSION.format(user_id), token, expiration=ttl)


class MobileSessionService:
    def __init__(
        self,
        repository_scope,
        *,
        session_seconds: int = 2592000,
        access_seconds: int = 86400,
        now=None,
        load_account=None,
        issue_access_token=None,
        allow_multi_login=None,
        current_session=None,
    ):
        self.repository_scope = repository_scope
        self.session_seconds = session_seconds
        self.access_seconds = access_seconds
        self.now = now or (lambda: datetime.now(UTC).replace(tzinfo=None))
        self.load_account = load_account or self._load_account
        self.issue_access_token = issue_access_token or self._issue_access_token
        self.allow_multi_login = allow_multi_login or self._allow_multi_login
        self.current_session = current_session or RedisCurrentSession()

    async def run(self, action):
        def execute():
            with self.repository_scope() as repository:
                return action(repository)

        try:
            return await asyncio.to_thread(execute)
        except IntegrityError as error:
            raise DshAuthorizationConflictError() from error
        except SQLAlchemyError as error:
            raise DshAuthorizationUnavailableError() from error

    @staticmethod
    def digest(refresh: str) -> str:
        if not isinstance(refresh, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", refresh):
            raise DshInvalidRefreshTokenError()
        return hashlib.sha256(refresh.encode()).hexdigest()

    @staticmethod
    def access_digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def open(self, user_id, tenant_id, user_name=None) -> dict:
        account = await self.load_account(int(user_id), int(tenant_id), user_name)
        self._require_active(account)
        refresh = secrets.token_urlsafe(32)
        access = self.issue_access_token(account)
        now = self.now()
        principal = DshPrincipal(tenant_id=str(account.tenant_id), user_id=str(account.user_id), session_id="mobile")
        with principal_scope(principal):
            row = await self.run(
                lambda repository: repository.create(
                    tenant_id=account.tenant_id,
                    user_id=account.user_id,
                    token_version=int(account.token_version or 0),
                    expires_at=now + timedelta(seconds=self.session_seconds),
                    digest=self.digest(refresh),
                    access_hash=self.access_digest(access),
                    now=now,
                )
            )
        await self.current_session.put(account.user_id, access, self.access_seconds + 3600)
        return self.payload(account, row, access, refresh)

    async def refresh(self, refresh: str | None) -> dict:
        digest = self.digest(refresh or "")
        located = await self.run(lambda repository: repository.locate_refresh(digest))
        if located is None:
            raise DshInvalidRefreshTokenError()
        account = await self.load_account(int(located["user_id"]), int(located["tenant_id"]), None)
        reject = self._reject_reason(account, int(located["token_version"] or 0))
        require_current = not await self._multi_login_allowed()
        current_hash = None
        if require_current and reject is None:
            current = await self.current_session.get(account.user_id)
            current_hash = self.access_digest(current) if current else None
        next_refresh = secrets.token_urlsafe(32)
        access = None if reject else self.issue_access_token(account)
        principal = DshPrincipal(
            tenant_id=str(located["tenant_id"]),
            user_id=str(located["user_id"]),
            session_id=located["session_id"],
        )
        with principal_scope(principal):
            row, error = await self.run(
                lambda repository: repository.rotate(
                    located["session_id"],
                    digest,
                    self.digest(next_refresh),
                    self.now(),
                    reject=reject,
                    next_access_hash=None if access is None else self.access_digest(access),
                    require_current=require_current,
                    current_hash=current_hash,
                )
            )
        if error:
            raise _REFRESH_ERRORS[error]()
        await self.current_session.put(account.user_id, access, self.access_seconds + 3600)
        return self.payload(account, row, access, next_refresh)

    async def revoke(self, refresh: str | None) -> None:
        try:
            digest = self.digest(refresh or "")
        except DshInvalidRefreshTokenError:
            return
        located = await self.run(lambda repository: repository.locate_refresh(digest))
        if located is None:
            return
        principal = DshPrincipal(
            tenant_id=str(located["tenant_id"]),
            user_id=str(located["user_id"]),
            session_id=located["session_id"],
        )
        with principal_scope(principal):
            await self.run(lambda repository: repository.revoke_by_digest(digest))

    @staticmethod
    def _require_active(account: MobileAccount) -> None:
        if not account.user_active:
            raise DshMobileUserDisabledError()
        if not account.tenant_active:
            raise DshMobileTenantUnavailableError()

    @staticmethod
    def _reject_reason(account: MobileAccount, issued_version: int) -> str | None:
        if not account.user_active:
            return "user_disabled"
        if not account.tenant_active:
            return "tenant_unavailable"
        if int(account.token_version or 0) != issued_version:
            return "token_version_changed"
        return None

    @staticmethod
    def payload(account: MobileAccount, row: dict, access: str, refresh: str) -> dict:
        user_id = account.user_id
        tenant_id = account.tenant_id
        return {
            "access_token": access,
            "refresh_token": refresh,
            "session_id": row["session_id"],
            "user_id": user_id,
            "user_name": account.user_name,
            "tenant_id": tenant_id,
            "user": {"id": user_id, "user_id": user_id, "display_name": account.user_name},
            "tenant": {"id": tenant_id, "tenant_id": tenant_id},
        }

    async def _load_account(self, user_id: int, tenant_id: int, user_name: str | None) -> MobileAccount:
        from bisheng.core.cache.redis_manager import get_redis_client
        from bisheng.tenant.domain.services.tenant_service import DISABLED_TENANT_KEY
        from bisheng.user.domain.models.user import UserDao

        user = await UserDao.aget_user(user_id)
        active = user is not None and not int(getattr(user, "delete", 0) or 0)
        version = await UserDao.aget_token_version(user_id) if active else 0
        name = getattr(user, "user_name", None) if user is not None else user_name
        tenant_active = True
        try:
            redis = await get_redis_client()
            if await redis.aget(DISABLED_TENANT_KEY.format(tenant_id)):
                tenant_active = False
        except Exception:
            # Redis outage matches the request middleware: do not lock every phone out.
            tenant_active = True
        return MobileAccount(
            user_id=user_id,
            tenant_id=tenant_id,
            user_name=name or user_name,
            token_version=int(version or 0),
            user_active=active,
            tenant_active=tenant_active,
        )

    @staticmethod
    def _issue_access_token(account: MobileAccount) -> str:
        from bisheng.user.domain.services.auth import AuthJwt, LoginUser

        user = SimpleNamespace(
            user_id=account.user_id,
            user_name=account.user_name or "",
            token_version=account.token_version,
        )
        return LoginUser.create_access_token(
            user,
            AuthJwt(),
            tenant_id=account.tenant_id,
            token_version=account.token_version,
        )

    async def _multi_login_allowed(self) -> bool:
        allowed = self.allow_multi_login()
        if asyncio.iscoroutine(allowed):
            allowed = await allowed
        return bool(allowed)

    @staticmethod
    def _allow_multi_login() -> bool:
        try:
            from bisheng.common.services.config_service import settings

            return bool(settings.get_system_login_method().allow_multi_login)
        except Exception:
            return True


def build_mobile_session_service() -> MobileSessionService:
    from bisheng.common.services.config_service import settings
    from bisheng.dsh.domain.repositories.mobile_session import MobileSessionRepository
    from bisheng.dsh.operations_runtime import repository_scope

    return MobileSessionService(
        lambda: repository_scope(MobileSessionRepository),
        session_seconds=settings.dsh.mobile_session_ttl_seconds,
        access_seconds=settings.cookie_conf.jwt_token_expire_time,
    )
