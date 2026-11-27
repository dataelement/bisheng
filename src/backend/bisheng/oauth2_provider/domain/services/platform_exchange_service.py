"""Silent first-party exchange to enabled applications without OAuth consent prompts."""

import asyncio
import time
from datetime import UTC, datetime
from uuid import uuid4

import jwt
from pydantic import ValidationError

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.oauth2_provider import (
    OAuth2InvalidAccessTokenError,
    OAuth2InvalidGrantError,
    OAuth2InvalidRequestError,
    OAuth2InvalidScopeError,
    OAuth2InvalidTargetError,
    OAuth2TemporarilyUnavailableError,
)
from bisheng.common.errcode.platform_auth import PlatformAuthError
from bisheng.oauth2_provider.domain.models.platform_exchange import OAuth2PlatformExchangeSession
from bisheng.oauth2_provider.domain.repositories.client import OAuth2ClientRepository
from bisheng.oauth2_provider.domain.repositories.platform_exchange import OAuth2PlatformExchangeRepository
from bisheng.oauth2_provider.domain.repositories.session import OAuth2SessionRepository
from bisheng.oauth2_provider.domain.schemas.exchange import ACCESS_TOKEN_TYPE, IDENTITY_SCOPES
from bisheng.oauth2_provider.domain.schemas.platform_exchange import OAuth2PlatformSubject
from bisheng.oauth2_provider.domain.services.exchange_service import event, timestamp, unavailable
from bisheng.oauth2_provider.infrastructure.key_service import OAUTH2_KEY_ID


class OAuth2PlatformExchangeService:
    def __init__(self, *, keys, session_factory, identity_lookup, platform_validator):
        self.keys = keys
        self._session_factory = session_factory
        self._identity_lookup = identity_lookup
        self._platform_validator = platform_validator

    @staticmethod
    def _target(db, audience, user_id, tenant_id, scopes):
        target = OAuth2ClientRepository(db).get_by_client_id(audience)
        # First-party sessions do not need an OAuth grant opt-in or pairwise policy.
        if not target or not target.enabled or target.is_builtin:
            raise OAuth2InvalidTargetError()
        if not scopes or not scopes <= set(target.allowed_scopes or []) & IDENTITY_SCOPES:
            raise OAuth2InvalidScopeError()
        # Verified first-party sessions exchange silently, independent of OAuth consent.
        return target

    async def _verify_parent(self, reference):
        try:
            await self._platform_validator(reference)
        except PlatformAuthError as exc:
            if exc.reason == "auth_service_unavailable":
                raise OAuth2TemporarilyUnavailableError() from None
            raise OAuth2InvalidGrantError() from None
        except BaseErrorCode as exc:
            raise unavailable(exc) from None

    async def record_consent(self, client, user_id, tenant_id, scopes):
        """Only invoked after explicit, authenticated OAuth consent approval."""

        def record():
            with self._session_factory() as db:
                current = OAuth2ClientRepository(db).get_by_client_id(client.client_id)
                if not current or not current.enabled or current.id != client.id:
                    raise OAuth2InvalidTargetError()
                if not set(scopes) <= set(current.allowed_scopes or []):
                    raise OAuth2InvalidScopeError()
                OAuth2PlatformExchangeRepository(db).save_consent(current, user_id, tenant_id, scopes)

        try:
            await asyncio.to_thread(record)
        except BaseErrorCode:
            raise
        except Exception as exc:
            raise unavailable(exc) from None

    async def revoke_consent(self, client_id, user_id, tenant_id):
        def revoke():
            with self._session_factory() as db:
                client = OAuth2ClientRepository(db).get_by_client_id(client_id)
                if client:
                    OAuth2PlatformExchangeRepository(db).revoke_consent(client, user_id, tenant_id)

        try:
            await asyncio.to_thread(revoke)
        except BaseErrorCode:
            raise
        except Exception as exc:
            raise unavailable(exc) from None

    async def exchange(self, *, origin, subject, audience, scope, requested_token_type=None, _started_at=None):
        t0 = int(time.time()) if _started_at is None else _started_at
        verified = None
        source_client_id = None
        try:
            if (
                not isinstance(audience, str)
                or not 1 <= len(audience) <= 128
                or requested_token_type not in (None, ACCESS_TOKEN_TYPE)
            ):
                raise OAuth2InvalidRequestError()
            try:
                subject = OAuth2PlatformSubject.model_validate(subject)
                reference = subject.reference
                reference_expiry = timestamp(datetime.fromisoformat(reference["expires_at"]))
            except (ValidationError, TypeError, ValueError, KeyError):
                raise OAuth2InvalidGrantError() from None
            if (
                reference.get("kind") != "platform_session"
                or reference.get("user_id") != subject.user_id
                or reference.get("tenant_id") != subject.tenant_id
                or reference_expiry != subject.expires_at
            ):
                raise OAuth2InvalidGrantError()
            scopes = set(scope.split()) if isinstance(scope, str) else set()
            if not scopes or not scopes <= IDENTITY_SCOPES:
                raise OAuth2InvalidScopeError()
            await self._verify_parent(reference)
            identity = await self._identity_lookup(subject.tenant_id, subject.user_id)
            if (
                not identity
                or not identity.active
                or identity.user_id != subject.user_id
                or identity.tenant_id != subject.tenant_id
            ):
                raise OAuth2InvalidGrantError()
            verified = {"sub": str(subject.user_id), "tenant_id": str(subject.tenant_id)}
            source_client_id = subject.client_id
            private = await self.keys.get_private_key()

            def issue():
                with self._session_factory() as db:
                    target = self._target(db, audience, subject.user_id, subject.tenant_id, scopes)
                    expiry = min(subject.expires_at, subject.session_expires_at, t0 + target.access_token_ttl, t0 + 300)
                    now = int(time.time())
                    if expiry <= now:
                        raise OAuth2InvalidGrantError()
                    child = OAuth2SessionRepository(db).create_session(
                        client_id=audience,
                        tenant_id=subject.tenant_id,
                        user_id=subject.user_id,
                        scope=" ".join(sorted(scopes)),
                        refresh_token_hash=None,
                        refresh_ttl_seconds=0,
                        access_ttl_seconds=expiry - now,
                        now=datetime.fromtimestamp(now, UTC).replace(tzinfo=None),
                    )
                    OAuth2PlatformExchangeRepository(db).save(
                        OAuth2PlatformExchangeSession(
                            session_id=child.session_id,
                            source_client_id=subject.client_id,
                            target_client_id=audience,
                            target_registration_id=target.id,
                            user_id=subject.user_id,
                            tenant_id=subject.tenant_id,
                            issuer=origin.rstrip("/"),
                            source_reference=reference,
                            expires_at=child.expires_at,
                        )
                    )
                    claims = {
                        "iss": origin.rstrip("/"),
                        "aud": audience,
                        "sub": str(subject.user_id),
                        "tenant_id": str(subject.tenant_id),
                        "session_id": child.session_id,
                        "scope": child.scope,
                        "token_use": "access",
                        "token_exchange": True,
                        "exchange_source": "platform_session",
                        "client_id": subject.client_id,
                        "iat": now,
                        "exp": expiry,
                        "jti": str(uuid4()),
                    }
                    token = jwt.encode(claims, private, algorithm="ES256", headers={"kid": OAUTH2_KEY_ID})
                    if expiry <= int(time.time()):
                        raise OAuth2InvalidGrantError()
                    return {
                        "access_token": token,
                        "issued_token_type": ACCESS_TOKEN_TYPE,
                        "token_type": "Bearer",
                        "scope": child.scope,
                        "session_id": child.session_id,
                    }, expiry

            result, expiry = await asyncio.to_thread(issue)
            await self._verify_parent(reference)
            if expiry <= int(time.time()):
                raise OAuth2InvalidGrantError()
            result["expires_in"] = expiry - int(time.time())
            event("platform_success", subject.client_id, audience, verified)
            return result
        except BaseErrorCode as exc:
            event("platform_denied_" + str(exc.code), source=source_client_id, target=audience, claims=verified)
            raise
        except Exception as exc:
            event("platform_unavailable", source=source_client_id, target=audience, claims=verified)
            raise unavailable(exc) from None

    async def validate_claims(self, claims):
        try:
            if claims.get("token_exchange") is not True or claims.get("exchange_source") != "platform_session":
                raise OAuth2InvalidAccessTokenError()

            def check():
                with self._session_factory() as db:
                    repo = OAuth2PlatformExchangeRepository(db)
                    user_id, tenant_id = int(claims["sub"]), int(claims["tenant_id"])
                    link = repo.get_link(claims.get("session_id"), user_id, tenant_id)
                    child = OAuth2SessionRepository(db).get_session(claims.get("session_id"))
                    now = int(time.time())
                    if (
                        not link
                        or not child
                        or child.state != "ACTIVE"
                        or timestamp(child.expires_at) <= now
                        or timestamp(link.expires_at) <= now
                        or link.issuer != claims.get("iss")
                        or link.target_client_id != claims.get("aud")
                        or link.source_client_id != claims.get("client_id")
                        or child.client_id != link.target_client_id
                        or child.user_id != user_id
                        or child.tenant_id != tenant_id
                        or type(claims.get("exp")) is not int
                        or claims["exp"] > timestamp(link.expires_at)
                    ):
                        raise OAuth2InvalidAccessTokenError()
                    scopes = set(claims.get("scope", "").split())
                    if not scopes <= set(child.scope.split()):
                        raise OAuth2InvalidAccessTokenError()
                    target = self._target(db, link.target_client_id, user_id, tenant_id, scopes)
                    if (
                        target.id != link.target_registration_id
                        or link.source_reference.get("user_id") != user_id
                        or link.source_reference.get("tenant_id") != tenant_id
                    ):
                        raise OAuth2InvalidAccessTokenError()
                    return dict(link.source_reference)

            reference = await asyncio.to_thread(check)
            await self._verify_parent(reference)
        except BaseErrorCode as exc:
            if exc.code == 28117:
                raise
            raise OAuth2InvalidAccessTokenError() from None
        except (KeyError, TypeError, ValueError):
            raise OAuth2InvalidAccessTokenError() from None
        except Exception as exc:
            raise unavailable(exc) from None
