"""Same-user RFC 8693 exchange with bounded child sessions."""

import asyncio
import re
import time
import traceback
from datetime import UTC, datetime
from uuid import uuid4

import jwt
from loguru import logger
from sqlalchemy.exc import IntegrityError

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.oauth2_provider import (
    OAuth2ExchangePolicyConflictError,
    OAuth2InvalidAccessTokenError,
    OAuth2InvalidClientAuthError,
    OAuth2InvalidGrantError,
    OAuth2InvalidRequestError,
    OAuth2InvalidScopeError,
    OAuth2InvalidTargetError,
    OAuth2TemporarilyUnavailableError,
    OAuth2UnauthorizedClientError,
)
from bisheng.oauth2_provider.domain.models.exchange import OAuth2ExchangePolicy, OAuth2ExchangeSession
from bisheng.oauth2_provider.domain.repositories.client import OAuth2ClientRepository
from bisheng.oauth2_provider.domain.repositories.exchange import OAuth2ExchangeRepository
from bisheng.oauth2_provider.domain.repositories.session import OAuth2SessionRepository
from bisheng.oauth2_provider.domain.schemas.exchange import (
    ACCESS_TOKEN_TYPE,
    EXCHANGE_GRANT_TYPE,
    IDENTITY_SCOPES,
    OAuth2ExchangePolicyResponse,
)
from bisheng.oauth2_provider.infrastructure.key_service import OAUTH2_KEY_ID


def timestamp(value):
    return int(value.replace(tzinfo=UTC).timestamp())


def policy_response(row):
    return OAuth2ExchangePolicyResponse(**{key: getattr(row, key) for key in OAuth2ExchangePolicyResponse.model_fields})


def event(result, source=None, target=None, claims=None):
    identity = claims or {}
    target = target if isinstance(target, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", target) else None
    logger.info(
        "OAuth exchange event={} result={} source={} target={} user={} tenant={}",
        str(uuid4()),
        result,
        source,
        target,
        identity.get("sub"),
        identity.get("tenant_id"),
    )


def unavailable(exc):
    # Stack locations only: exception text and frame locals can contain credentials.
    logger.error(
        "OAuth exchange dependency failure type={} stack={}",
        type(exc).__name__,
        ";".join(f"{frame.filename}:{frame.lineno}:{frame.name}" for frame in traceback.extract_tb(exc.__traceback__)),
    )
    return OAuth2TemporarilyUnavailableError()


class OAuth2ExchangeService:
    def __init__(self, *, clients, keys, session_factory, identity_lookup):
        self.clients, self.keys = clients, keys
        self._session_factory, self._identity_lookup = session_factory, identity_lookup
        self._platform_validator = None

    async def list_policies(self, source_client_id=None, page=1, page_size=50):
        def operation():
            with self._session_factory() as db:
                rows, total = OAuth2ExchangeRepository(db).list_policies(source_client_id, page, page_size)
                return [policy_response(row) for row in rows], total

        return await asyncio.to_thread(operation)

    async def put_policy(self, source_client_id, target_client_id, body, actor_user_id):
        if source_client_id == target_client_id:
            raise OAuth2InvalidTargetError()
        scopes = set(body.allowed_scopes)
        if not scopes or not scopes <= IDENTITY_SCOPES:
            raise OAuth2InvalidScopeError()

        def operation():
            with self._session_factory() as db:
                repo = OAuth2ExchangeRepository(db)
                row = repo.get_policy(source_client_id, target_client_id)
                if row is None or body.enabled:
                    clients = OAuth2ClientRepository(db)
                    source, target = (
                        clients.get_by_client_id(source_client_id),
                        clients.get_by_client_id(target_client_id),
                    )
                    if (
                        not source
                        or not target
                        or not source.enabled
                        or not target.enabled
                        or source.client_type != "confidential"
                        or EXCHANGE_GRANT_TYPE not in source.grant_types
                    ):
                        raise OAuth2InvalidTargetError()
                    if not scopes <= set(source.allowed_scopes) & set(target.allowed_scopes):
                        raise OAuth2InvalidScopeError()
                if row is None:
                    row = OAuth2ExchangePolicy(
                        source_client_id=source_client_id,
                        target_client_id=target_client_id,
                        created_by=actor_user_id,
                        updated_by=actor_user_id,
                        allowed_scopes=sorted(scopes),
                        enabled=body.enabled,
                    )
                row.allowed_scopes, row.enabled, row.updated_by = sorted(scopes), body.enabled, actor_user_id
                return policy_response(repo.save(row))

        try:
            result = await asyncio.to_thread(operation)
        except IntegrityError:
            raise OAuth2ExchangePolicyConflictError() from None
        event("policy_updated", source_client_id, target_client_id, {"sub": actor_user_id})
        return result

    def _check_source(self, row, secret):
        if row is None or not row.enabled or row.client_type != "confidential":
            raise OAuth2InvalidClientAuthError()
        self.clients.authenticate_client(row, secret)
        if EXCHANGE_GRANT_TYPE not in row.grant_types:
            raise OAuth2UnauthorizedClientError()

    @staticmethod
    def _claims(claims, source):
        if claims.get("aud") != source or claims.get("token_use") != "access" or "token_exchange" in claims:
            raise OAuth2InvalidGrantError()
        for field in ("sub", "tenant_id"):
            value = claims.get(field)
            if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or int(value) <= 0:
                raise OAuth2InvalidGrantError()
        for field in ("session_id", "jti", "scope"):
            if not isinstance(claims.get(field), str) or not claims[field]:
                raise OAuth2InvalidGrantError()
        if len(claims["session_id"]) > 36:
            raise OAuth2InvalidGrantError()
        for field in ("exp", "iat"):
            if type(claims.get(field)) is not int:
                raise OAuth2InvalidGrantError()

    @staticmethod
    def _state(db, source, target, claims, scopes):
        clients, sessions, repo = OAuth2ClientRepository(db), OAuth2SessionRepository(db), OAuth2ExchangeRepository(db)
        a, b = clients.get_by_client_id(source), clients.get_by_client_id(target)
        policy = repo.get_policy(source, target)
        parent = sessions.get_session(claims["session_id"])
        if not a or not a.enabled or a.client_type != "confidential" or EXCHANGE_GRANT_TYPE not in a.grant_types:
            raise OAuth2InvalidClientAuthError()
        if not b or not b.enabled or source == target or not policy or not policy.enabled:
            raise OAuth2InvalidTargetError()
        if (
            parent is None
            or parent.client_id != source
            or parent.user_id != int(claims["sub"])
            or parent.tenant_id != int(claims["tenant_id"])
            or parent.state != "ACTIVE"
            or timestamp(parent.expires_at) <= int(time.time())
            or repo.get_link(parent.session_id)
        ):
            raise OAuth2InvalidGrantError()
        permitted = (
            set(claims["scope"].split())
            & set(parent.scope.split())
            & set(a.allowed_scopes)
            & set(b.allowed_scopes)
            & set(policy.allowed_scopes)
            & IDENTITY_SCOPES
        )
        if not scopes <= permitted:
            raise OAuth2InvalidScopeError()
        return a, b, parent

    async def exchange_token(
        self,
        *,
        origin,
        client_id,
        client_secret,
        subject_token,
        subject_token_type,
        audience,
        scope,
        requested_token_type=None,
    ):
        t0 = int(time.time())
        verified = None
        authenticated = None
        try:
            if (
                subject_token_type != ACCESS_TOKEN_TYPE
                or requested_token_type not in (None, ACCESS_TOKEN_TYPE)
                or not subject_token
                or not audience
                or not client_id
            ):
                raise OAuth2InvalidRequestError()
            scopes = set(scope.split()) if isinstance(scope, str) else set()
            if not scopes or not scopes <= IDENTITY_SCOPES:
                raise OAuth2InvalidScopeError()

            def authenticate():
                with self._session_factory() as db:
                    row = OAuth2ClientRepository(db).get_by_client_id(client_id)
                    self._check_source(row, client_secret)

            await asyncio.to_thread(authenticate)
            authenticated = client_id
            public, private = await self.keys.get_public_key(), await self.keys.get_private_key()
            try:
                claims = jwt.decode(
                    subject_token,
                    public,
                    algorithms=["ES256"],
                    audience=client_id,
                    issuer=origin.rstrip("/"),
                    options={
                        "require": [
                            "iss",
                            "aud",
                            "sub",
                            "tenant_id",
                            "session_id",
                            "scope",
                            "token_use",
                            "exp",
                            "iat",
                            "jti",
                        ],
                        "strict_aud": True,
                    },
                )
                self._claims(claims, client_id)
            except (jwt.PyJWTError, TypeError, ValueError):
                raise OAuth2InvalidGrantError() from None

            # Verify claim/session binding before recording a trusted identity.
            def check():
                with self._session_factory() as db:
                    self._state(db, client_id, audience, claims, scopes)

            await asyncio.to_thread(check)
            identity = await self._identity_lookup(int(claims["tenant_id"]), int(claims["sub"]))
            if (
                not identity
                or not identity.active
                or identity.user_id != int(claims["sub"])
                or identity.tenant_id != int(claims["tenant_id"])
            ):
                raise OAuth2InvalidGrantError()
            verified = claims

            def issue():
                with self._session_factory() as db:
                    a, b, parent = self._state(db, client_id, audience, claims, scopes)
                    self._check_source(a, client_secret)
                    expiry = min(claims["exp"], timestamp(parent.expires_at), t0 + b.access_token_ttl, t0 + 300)
                    now = int(time.time())
                    if expiry <= now:
                        raise OAuth2InvalidGrantError()
                    row = OAuth2SessionRepository(db).create_session(
                        client_id=audience,
                        tenant_id=identity.tenant_id,
                        user_id=identity.user_id,
                        scope=" ".join(sorted(scopes)),
                        refresh_token_hash=None,
                        refresh_ttl_seconds=0,
                        access_ttl_seconds=expiry - now,
                        now=datetime.fromtimestamp(now, UTC).replace(tzinfo=None),
                    )
                    OAuth2ExchangeRepository(db).save(
                        OAuth2ExchangeSession(
                            session_id=row.session_id,
                            source_session_id=parent.session_id,
                            source_client_id=client_id,
                            target_client_id=audience,
                            tenant_id=identity.tenant_id,
                            user_id=identity.user_id,
                            issuer=origin.rstrip("/"),
                            created_at=row.created_at,
                            expires_at=row.expires_at,
                        )
                    )
                    payload = {
                        "iss": origin.rstrip("/"),
                        "aud": audience,
                        "sub": str(identity.user_id),
                        "tenant_id": str(identity.tenant_id),
                        "session_id": row.session_id,
                        "scope": row.scope,
                        "token_use": "access",
                        "iat": now,
                        "exp": expiry,
                        "jti": str(uuid4()),
                        "token_exchange": True,
                        "client_id": client_id,
                    }
                    token = jwt.encode(payload, private, algorithm="ES256", headers={"kid": OAUTH2_KEY_ID})
                    if expiry <= int(time.time()):
                        raise OAuth2InvalidGrantError()
                    return {
                        "access_token": token,
                        "issued_token_type": ACCESS_TOKEN_TYPE,
                        "token_type": "Bearer",
                        "expires_in": expiry - int(time.time()),
                        "scope": row.scope,
                        "session_id": row.session_id,
                    }, expiry

            result, expiry = await asyncio.to_thread(issue)
            if expiry <= int(time.time()):
                raise OAuth2InvalidGrantError()
            result["expires_in"] = expiry - int(time.time())
            event("success", authenticated, audience, verified)
            return result
        except BaseErrorCode as exc:
            event("denied_" + str(exc.code), authenticated, audience, verified)
            raise
        except Exception as exc:
            event("unavailable", authenticated, audience, verified)
            raise unavailable(exc) from None

    async def validate_exchange_claims(self, claims):
        if "exchange_source" in claims:
            if claims["exchange_source"] != "platform_session" or self._platform_validator is None:
                raise OAuth2InvalidAccessTokenError()
            return await self._platform_validator(claims)
        try:
            if claims.get("token_exchange") is not True:
                raise OAuth2InvalidAccessTokenError()

            def check():
                with self._session_factory() as db:
                    repo, sessions = OAuth2ExchangeRepository(db), OAuth2SessionRepository(db)
                    link = repo.get_link(claims.get("session_id"), int(claims["tenant_id"]), int(claims["sub"]))
                    child = sessions.get_session(claims.get("session_id"))
                    now = int(time.time())
                    if (
                        not link
                        or not child
                        or child.state != "ACTIVE"
                        or timestamp(child.expires_at) <= now
                        or link.issuer != claims.get("iss")
                        or claims.get("aud") != link.target_client_id
                        or claims.get("client_id") != link.source_client_id
                        or child.client_id != link.target_client_id
                        or child.user_id != link.user_id
                        or child.tenant_id != link.tenant_id
                        or type(claims.get("exp")) is not int
                        or claims["exp"] > timestamp(link.expires_at)
                        or timestamp(link.expires_at) <= now
                    ):
                        raise OAuth2InvalidAccessTokenError()
                    if not isinstance(claims.get("scope"), str) or not set(claims["scope"].split()) <= set(
                        child.scope.split()
                    ):
                        raise OAuth2InvalidAccessTokenError()
                    parent_claims = {**claims, "session_id": link.source_session_id, "scope": child.scope}
                    self._state(
                        db, link.source_client_id, link.target_client_id, parent_claims, set(child.scope.split())
                    )

            await asyncio.to_thread(check)
        except (BaseErrorCode, KeyError, TypeError, ValueError):
            raise OAuth2InvalidAccessTokenError() from None
        except Exception as exc:
            raise unavailable(exc) from None
