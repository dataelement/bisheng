"""Local desktop token issuance, rotation and device ownership."""

import asyncio
import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from bisheng.common.errcode.dsh import (
    ERROR_BY_CLIENT_CODE,
    DshAuthorizationConflictError,
    DshAuthorizationUnavailableError,
    DshInvalidAccessTokenError,
    DshInvalidRefreshTokenError,
    DshSessionRevokedError,
    DshUserDisabledError,
)
from bisheng.dsh.domain.services.access import DshPrincipal, principal_scope
from bisheng.dsh.infrastructure.token_keys import ISSUER, KEY_ID


class DshLocalSessionService:
    def __init__(
        self,
        repository_scope,
        identities,
        keys,
        *,
        access_seconds=300,
        session_seconds=2592000,
        refresh_grace_seconds=0,
        now=None,
    ):
        self.repository_scope, self.identities, self.keys = repository_scope, identities, keys
        self.access_seconds, self.session_seconds = access_seconds, session_seconds
        self.refresh_grace_seconds = refresh_grace_seconds
        self.now = now or (lambda: datetime.now(UTC).replace(tzinfo=None))

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
    def digest(refresh):
        if not isinstance(refresh, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", refresh):
            raise DshInvalidRefreshTokenError()
        return hashlib.sha256(refresh.encode()).hexdigest()

    async def exchange(self, identity, auth_id, authorization):
        if not identity.active:
            raise DshUserDisabledError()
        principal = DshPrincipal(tenant_id=identity.tenant_id, user_id=identity.user_id, session_id=auth_id)
        refresh = secrets.token_urlsafe(32)
        now = self.now()
        with principal_scope(principal):
            row = await self.run(
                lambda repository: repository.create(
                    tenant_id=int(identity.tenant_id),
                    user_id=int(identity.user_id),
                    auth_id=auth_id,
                    device_label=authorization.get("device_name"),
                    client_version=authorization.get("client_version"),
                    expires_at=now + timedelta(seconds=self.session_seconds),
                    digest=self.digest(refresh),
                    now=now,
                )
            )
        return await self.response(identity, row, refresh)

    async def refresh(self, refresh):
        digest = self.digest(refresh)
        located = await self.run(lambda repository: repository.locate_refresh(digest))
        if located is None:
            raise DshInvalidRefreshTokenError()
        principal = DshPrincipal(
            tenant_id=str(located["tenant_id"]), user_id=str(located["user_id"]), session_id=located["session_id"]
        )
        next_refresh = secrets.token_urlsafe(32)
        with principal_scope(principal):
            identity = await self.identities.check(principal.tenant_id, principal.user_id)
            if not identity.active:
                raise DshUserDisabledError()
            row, error = await self.run(
                lambda repository: repository.rotate(
                    principal.session_id,
                    digest,
                    self.digest(next_refresh),
                    self.now(),
                    self.refresh_grace_seconds,
                )
            )
        # Replay revocation must commit before raising the public error.
        if error:
            raise ERROR_BY_CLIENT_CODE[error]()
        return await self.response(identity, row, next_refresh)

    async def response(self, identity, row, refresh):
        now = int(self.now().replace(tzinfo=UTC).timestamp())
        absolute = int(row["expires_at"].replace(tzinfo=UTC).timestamp())
        expires = min(now + self.access_seconds, absolute)
        if expires <= now:
            raise ERROR_BY_CLIENT_CODE["session_expired"]()
        claims = {
            "iss": ISSUER,
            "aud": "bisheng-dsh-model",
            "sub": identity.user_id,
            "tenant_id": identity.tenant_id,
            "session_id": row["session_id"],
            "session_version": row["version"],
            "iat": now,
            "exp": expires,
            "jti": str(uuid4()),
        }
        token = jwt.encode(
            claims,
            await self.keys.resolve(KEY_ID),
            algorithm="HS256",
            headers={"typ": "bisheng-dsh-access+jwt", "kid": KEY_ID},
        )
        return {
            "token_type": "Bearer",
            "access_token": token,
            "expires_in": expires - now,
            "refresh_token": refresh,
            "refresh_expires_in": absolute - now,
            "session_id": row["session_id"],
            "session_expires_at": row["expires_at"].replace(tzinfo=UTC).isoformat(),
            "user": identity.user.model_dump(),
            "tenant": identity.tenant.model_dump(),
        }

    async def validate(self, principal):
        row = await self.run(lambda repository: self._read(repository, principal.session_id))
        if row is None or (str(row["tenant_id"]), str(row["user_id"]), row["version"]) != (
            principal.tenant_id,
            principal.user_id,
            principal.session_version,
        ):
            raise DshInvalidAccessTokenError()
        if row["state"] != "ACTIVE":
            raise DshSessionRevokedError()
        if self.now() >= row["expires_at"]:
            raise ERROR_BY_CLIENT_CODE["session_expired"]()

    @staticmethod
    def _read(repository, session_id):
        row = repository.get(session_id)
        return repository.snapshot(row) if row else None

    async def page(self, tenant_id, user_id, *, cursor=None, limit=20):
        principal = DshPrincipal(tenant_id=str(tenant_id), user_id=str(user_id), session_id="management")
        with principal_scope(principal):
            page = await self.run(lambda repository: repository.page(int(user_id), cursor=cursor, limit=limit))
        page["items"] = [
            {
                "session_id": row["session_id"],
                "device_label": row["device_label"],
                "client_version": row["client_version"],
                "state": row["state"],
                "expires_at": row["expires_at"].replace(tzinfo=UTC).isoformat(),
                "created_at": row["created_at"].replace(tzinfo=UTC).isoformat(),
                "last_seen_at": None,
            }
            for row in page["items"]
        ]
        return page

    async def revoke(self, tenant_id, user_id, session_id):
        principal = DshPrincipal(tenant_id=str(tenant_id), user_id=str(user_id), session_id=session_id)

        def change(repository):
            row = repository.get(session_id, lock=True)
            if row is None or row.tenant_id != int(tenant_id) or row.user_id != int(user_id):
                raise DshInvalidAccessTokenError()
            repository.revoke(row)

        with principal_scope(principal):
            await self.run(change)
        return {"session_id": session_id, "state": "REVOKED"}

    async def logout_refresh(self, refresh):
        located = await self.run(lambda repository: repository.locate_refresh(self.digest(refresh)))
        if located is None:
            raise DshInvalidRefreshTokenError()
        if self.now() >= located["expires_at"]:
            raise ERROR_BY_CLIENT_CODE["session_expired"]()
        await self.revoke(located["tenant_id"], located["user_id"], located["session_id"])
