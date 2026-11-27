"""Standard OAuth 2.0 / OIDC Provider authorization, consent, token, userinfo and revocation service."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import jwt

from bisheng.common.errcode.oauth2_provider import (
    OAuth2AuthorizationExpiredError,
    OAuth2ClientDisabledError,
    OAuth2ClientNotFoundError,
    OAuth2InvalidAccessTokenError,
    OAuth2InvalidClientAuthError,
    OAuth2InvalidGrantError,
    OAuth2InvalidRedirectUriError,
    OAuth2InvalidRequestError,
    OAuth2InvalidScopeError,
    OAuth2UnsupportedGrantTypeError,
    OAuth2UserInactiveError,
)
from bisheng.oauth2_provider.domain.models.client import OAuth2Client
from bisheng.oauth2_provider.domain.repositories.session import OAuth2SessionRepository
from bisheng.oauth2_provider.domain.schemas.auth import (
    OAuth2ConsentDecisionResponse,
    OAuth2ConsentDetails,
    OAuth2TokenResponse,
    OAuth2UserInfoResponse,
)
from bisheng.oauth2_provider.domain.services.client_service import (
    OAuth2ClientService,
    match_redirect_uri,
    validate_pkce_challenge,
    verify_pkce_verifier,
)
from bisheng.oauth2_provider.infrastructure.code_store import OAuth2CodeStore
from bisheng.oauth2_provider.infrastructure.key_service import OAUTH2_KEY_ID, OAuth2KeyService


@dataclass(frozen=True)
class OAuth2UserIdentity:
    user_id: int
    tenant_id: int
    username: str
    display_name: str
    email: str | None
    tenant_name: str
    active: bool = True


IdentityLookup = Callable[[int, int], Awaitable[OAuth2UserIdentity | None]]


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _append_query_params(url: str, params: dict[str, str]) -> str:
    parts = urlsplit(url)
    existing = dict(parse_qsl(parts.query, keep_blank_values=True))
    existing.update({k: v for k, v in params.items() if v is not None})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(existing), parts.fragment))


class OAuth2AuthService:
    def __init__(
        self,
        *,
        clients: OAuth2ClientService,
        code_store: OAuth2CodeStore,
        keys: OAuth2KeyService,
        session_factory: Callable[[], AbstractContextManager],
        identity_lookup: IdentityLookup,
    ):
        self.clients = clients
        self.code_store = code_store
        self.keys = keys
        self._session_factory = session_factory
        self._identity_lookup = identity_lookup
        self._exchange_validator = None
        self._consent_recorder = None

    @staticmethod
    def build_openid_metadata(origin: str) -> dict[str, Any]:
        base = origin.rstrip("/")
        return {
            "issuer": base,
            "authorization_endpoint": f"{base}/api/v1/oauth2/authorize",
            "token_endpoint": f"{base}/api/v1/oauth2/token",
            "userinfo_endpoint": f"{base}/api/v1/oauth2/userinfo",
            "revocation_endpoint": f"{base}/api/v1/oauth2/revoke",
            "jwks_uri": f"{base}/api/v1/oauth2/jwks",
            "response_types_supported": ["code"],
            "grant_types_supported": [
                "authorization_code",
                "refresh_token",
                "urn:ietf:params:oauth:grant-type:token-exchange",
            ],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["ES256"],
            "scopes_supported": ["openid", "profile", "email", "offline_access", "dsh"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
            "code_challenge_methods_supported": ["S256"],
            "claims_supported": [
                "sub",
                "iss",
                "aud",
                "exp",
                "iat",
                "nonce",
                "preferred_username",
                "name",
                "email",
                "tenant_id",
                "tenant_name",
            ],
        }

    async def start_authorization(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        response_type: str,
        scope: str | None,
        state: str | None,
        code_challenge: str | None,
        code_challenge_method: str | None,
        nonce: str | None,
        device_name: str | None = None,
    ) -> tuple[str, OAuth2Client, dict[str, Any]]:
        if response_type != "code":
            raise OAuth2InvalidRequestError(msg="Only response_type=code is supported")
        client = await self.clients.get_active_client_model(client_id)
        if "authorization_code" not in (client.grant_types or []):
            raise OAuth2UnsupportedGrantTypeError()
        if not match_redirect_uri(
            redirect_uri, list(client.redirect_uris or []), allow_loopback_port=client.allow_loopback_port
        ):
            raise OAuth2InvalidRedirectUriError()

        requested_scopes = [s for s in (scope or "openid profile").split() if s]
        allowed_scopes = set(client.allowed_scopes or [])
        if not requested_scopes or any(s not in allowed_scopes for s in requested_scopes):
            raise OAuth2InvalidScopeError()

        if client.require_pkce:
            if not code_challenge or not code_challenge_method:
                raise OAuth2InvalidRequestError(msg="PKCE code_challenge and code_challenge_method=S256 are required")
            validate_pkce_challenge(code_challenge, code_challenge_method)
        elif code_challenge:
            validate_pkce_challenge(code_challenge, code_challenge_method or "")

        request_id = str(uuid4())
        payload = {
            "client_id": client.client_id,
            "client_registration_id": client.id,
            "redirect_uri": redirect_uri,
            "scopes": requested_scopes,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "nonce": nonce,
            "device_name": device_name,
        }
        await self.code_store.save_request(request_id, payload)
        return request_id, client, payload

    async def get_consent_details(self, request_id: str) -> OAuth2ConsentDetails:
        found = await self.code_store.read_request(request_id)
        if found is None:
            raise OAuth2AuthorizationExpiredError()
        payload, ttl = found
        client = await self.clients.get_active_client_model(payload["client_id"])
        if payload.get("client_registration_id") != client.id:
            raise OAuth2AuthorizationExpiredError()
        return OAuth2ConsentDetails(
            request_id=request_id,
            client_id=client.client_id,
            client_name=client.client_name,
            client_description=client.description,
            scopes=list(payload.get("scopes") or []),
            redirect_uri=payload["redirect_uri"],
            state=payload.get("state"),
            require_consent=bool(client.require_consent),
            expires_in=ttl,
        )

    async def approve_request_direct(
        self,
        *,
        request_id: str,
        user_id: int,
        tenant_id: int,
    ) -> str:
        res = await self.submit_consent(
            request_id=request_id, user_id=user_id, tenant_id=tenant_id, decision="approve", _record_consent=False
        )
        return res.redirect_uri

    async def submit_consent(
        self,
        *,
        request_id: str,
        user_id: int,
        tenant_id: int,
        decision: str,
        _record_consent: bool = True,
    ) -> OAuth2ConsentDecisionResponse:
        payload = await self.code_store.consume_request(request_id)
        if payload is None:
            raise OAuth2AuthorizationExpiredError()
        client = await self.clients.get_active_client_model(payload["client_id"])
        if payload.get("client_registration_id") != client.id:
            raise OAuth2AuthorizationExpiredError()
        redirect_uri = payload["redirect_uri"]
        state = payload.get("state")

        if decision == "deny":
            params = {"error": "access_denied"}
            if state:
                params["state"] = state
            return OAuth2ConsentDecisionResponse(redirect_uri=_append_query_params(redirect_uri, params))

        identity = await self._identity_lookup(tenant_id, user_id)
        if identity is None or not identity.active:
            raise OAuth2UserInactiveError()

        if decision != "approve":
            raise OAuth2InvalidRequestError()
        if _record_consent and client.require_consent and self._consent_recorder is not None:
            await self._consent_recorder(client, identity.user_id, identity.tenant_id, payload["scopes"])
        code = secrets.token_urlsafe(32)
        await self.code_store.save_code(
            code,
            {
                "client_id": client.client_id,
                "client_registration_id": client.id,
                "redirect_uri": redirect_uri,
                "scopes": payload["scopes"],
                "code_challenge": payload.get("code_challenge"),
                "code_challenge_method": payload.get("code_challenge_method"),
                "nonce": payload.get("nonce"),
                "device_name": payload.get("device_name"),
                "user_id": identity.user_id,
                "tenant_id": identity.tenant_id,
            },
        )
        params = {"code": code}
        if state:
            params["state"] = state
        return OAuth2ConsentDecisionResponse(redirect_uri=_append_query_params(redirect_uri, params))

    async def _sign_tokens(
        self,
        *,
        origin: str,
        client: OAuth2Client,
        identity: OAuth2UserIdentity,
        session_id: str,
        scopes: list[str],
        nonce: str | None = None,
    ) -> tuple[str, str | None]:
        private_key = await self.keys.get_private_key()
        now_ts = int(datetime.now(UTC).timestamp())
        issuer = origin.rstrip("/")
        scope_str = " ".join(scopes)

        access_payload = {
            "iss": issuer,
            "sub": str(identity.user_id),
            "aud": client.client_id,
            "tenant_id": str(identity.tenant_id),
            "session_id": session_id,
            "scope": scope_str,
            "token_use": "access",
            "iat": now_ts,
            "exp": now_ts + int(client.access_token_ttl),
            "jti": str(uuid4()),
        }
        access_token = jwt.encode(access_payload, private_key, algorithm="ES256", headers={"kid": OAUTH2_KEY_ID})

        id_token = None
        if "openid" in scopes:
            id_payload: dict[str, Any] = {
                "iss": issuer,
                "sub": str(identity.user_id),
                "aud": client.client_id,
                "iat": now_ts,
                "exp": now_ts + int(client.access_token_ttl),
                "tenant_id": str(identity.tenant_id),
                "tenant_name": identity.tenant_name,
            }
            if "profile" in scopes:
                id_payload["preferred_username"] = identity.username
                id_payload["name"] = identity.display_name
            if "email" in scopes and identity.email:
                id_payload["email"] = identity.email
            if nonce:
                id_payload["nonce"] = nonce
            id_token = jwt.encode(id_payload, private_key, algorithm="ES256", headers={"kid": OAUTH2_KEY_ID})
        return access_token, id_token

    async def exchange_code(
        self,
        *,
        origin: str,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str | None,
        client_secret: str | None,
    ) -> OAuth2TokenResponse:
        client = await self.clients.get_active_client_model(client_id)
        if "authorization_code" not in (client.grant_types or []):
            raise OAuth2UnsupportedGrantTypeError()
        self.clients.authenticate_client(client, client_secret)

        code_data = await self.code_store.consume_code(code)
        if code_data is None:
            raise OAuth2InvalidGrantError()
        if (
            code_data["client_id"] != client.client_id
            or code_data["redirect_uri"] != redirect_uri
            or code_data.get("client_registration_id") != client.id
        ):
            raise OAuth2InvalidGrantError()

        if client.require_pkce or code_data.get("code_challenge"):
            verify_pkce_verifier(code_data["code_challenge"], code_verifier)

        identity = await self._identity_lookup(int(code_data["tenant_id"]), int(code_data["user_id"]))
        if identity is None or not identity.active:
            raise OAuth2UserInactiveError()

        scopes = list(code_data.get("scopes") or [])
        scope_str = " ".join(scopes)
        issue_refresh = "offline_access" in scopes and "refresh_token" in (client.grant_types or [])
        raw_refresh = f"bsrt_{secrets.token_urlsafe(32)}" if issue_refresh else None
        refresh_hash = _sha256_hex(raw_refresh) if raw_refresh else None

        def _create_session() -> str:
            with self._session_factory() as db:
                row = OAuth2SessionRepository(db).create_session(
                    client_id=client.client_id,
                    tenant_id=identity.tenant_id,
                    user_id=identity.user_id,
                    scope=scope_str,
                    refresh_token_hash=refresh_hash,
                    refresh_ttl_seconds=int(client.refresh_token_ttl),
                    access_ttl_seconds=int(client.access_token_ttl),
                    device_name=code_data.get("device_name"),
                )
                return str(row.session_id)

        session_id = await asyncio.to_thread(_create_session)
        access_token, id_token = await self._sign_tokens(
            origin=origin,
            client=client,
            identity=identity,
            session_id=session_id,
            scopes=scopes,
            nonce=code_data.get("nonce"),
        )
        return OAuth2TokenResponse(
            access_token=access_token,
            expires_in=int(client.access_token_ttl),
            scope=scope_str,
            refresh_token=raw_refresh,
            refresh_expires_in=int(client.refresh_token_ttl) if raw_refresh else None,
            id_token=id_token,
            session_id=session_id,
        )

    async def refresh_access_token(
        self,
        *,
        origin: str,
        refresh_token: str,
        client_id: str | None,
        client_secret: str | None,
    ) -> OAuth2TokenResponse:
        token_hash = _sha256_hex(refresh_token)
        new_raw_refresh = f"bsrt_{secrets.token_urlsafe(32)}"
        new_hash = _sha256_hex(new_raw_refresh)
        now = datetime.utcnow()

        def _lookup():
            with self._session_factory() as db:
                repo = OAuth2SessionRepository(db)
                rt = repo.get_refresh_token(token_hash)
                if rt is None:
                    return None
                sess = repo.get_session(rt.session_id)
                if sess is None:
                    return None
                return {
                    "rt_client_id": rt.client_id,
                    "rt_session_id": rt.session_id,
                    "rt_state": rt.state,
                    "rt_expires_at": rt.expires_at,
                    "sess_state": sess.state,
                    "sess_expires_at": sess.expires_at,
                    "sess_tenant_id": int(sess.tenant_id),
                    "sess_user_id": int(sess.user_id),
                }

        looked = await asyncio.to_thread(_lookup)
        if looked is None:
            raise OAuth2InvalidGrantError()

        resolved_client_id = client_id or looked["rt_client_id"]
        if resolved_client_id != looked["rt_client_id"]:
            raise OAuth2InvalidClientAuthError()

        client = await self.clients.get_active_client_model(resolved_client_id)
        if "refresh_token" not in (client.grant_types or []):
            raise OAuth2UnsupportedGrantTypeError()
        self.clients.authenticate_client(client, client_secret)

        if looked["rt_state"] == "USED":
            # Refresh token replay detected -> revoke entire session family.
            def _revoke_replay():
                with self._session_factory() as db:
                    OAuth2SessionRepository(db).revoke_session(looked["rt_session_id"], now=now)

            await asyncio.to_thread(_revoke_replay)
            raise OAuth2InvalidGrantError()

        if (
            looked["rt_state"] != "ACTIVE"
            or looked["sess_state"] != "ACTIVE"
            or looked["rt_expires_at"] <= now
            or looked["sess_expires_at"] <= now
        ):
            raise OAuth2InvalidGrantError()

        identity = await self._identity_lookup(looked["sess_tenant_id"], looked["sess_user_id"])
        if identity is None or not identity.active:
            raise OAuth2UserInactiveError()

        def _rotate() -> tuple[str, str] | None:
            with self._session_factory() as db:
                repo = OAuth2SessionRepository(db)
                live_rt = repo.get_refresh_token(token_hash)
                if live_rt is None:
                    return None
                rotated = repo.rotate_refresh_token(
                    old_token=live_rt,
                    new_token_hash=new_hash,
                    refresh_ttl_seconds=int(client.refresh_token_ttl),
                    access_ttl_seconds=int(client.access_token_ttl),
                    now=now,
                )
                if rotated is None:
                    return None
                updated_sess, _ = rotated
                return str(updated_sess.session_id), str(updated_sess.scope)

        rotated = await asyncio.to_thread(_rotate)
        if rotated is None:
            raise OAuth2InvalidGrantError()
        updated_session_id, updated_scope = rotated
        scopes = [s for s in updated_scope.split() if s]
        access_token, id_token = await self._sign_tokens(
            origin=origin,
            client=client,
            identity=identity,
            session_id=updated_session_id,
            scopes=scopes,
        )
        return OAuth2TokenResponse(
            access_token=access_token,
            expires_in=int(client.access_token_ttl),
            scope=updated_scope,
            refresh_token=new_raw_refresh,
            refresh_expires_in=int(client.refresh_token_ttl),
            id_token=id_token,
            session_id=updated_session_id,
        )

    async def decode_access_token(self, bearer_header: str) -> dict[str, Any]:
        if not bearer_header or not bearer_header.lower().startswith("bearer "):
            raise OAuth2InvalidAccessTokenError()
        token = bearer_header.split(" ", 1)[1].strip()
        if not token:
            raise OAuth2InvalidAccessTokenError()
        public_key = await self.keys.get_public_key()
        try:
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["ES256"],
                options={"verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise OAuth2InvalidAccessTokenError() from exc
        if claims.get("token_use") != "access" or not claims.get("sub") or not claims.get("session_id"):
            raise OAuth2InvalidAccessTokenError()
        return claims

    async def userinfo(self, bearer_header: str) -> OAuth2UserInfoResponse:
        claims = await self.decode_access_token(bearer_header)
        session_id = str(claims["session_id"])
        if "token_exchange" in claims:
            if self._exchange_validator is None:
                raise OAuth2InvalidAccessTokenError()
            await self._exchange_validator(claims)

        def _check_session():
            with self._session_factory() as db:
                sess = OAuth2SessionRepository(db).get_session(session_id)
                if sess is None:
                    return None
                return {
                    "state": sess.state,
                    "scope": sess.scope,
                    "expires_at": sess.expires_at,
                    "client_id": sess.client_id,
                    "tenant_id": int(sess.tenant_id),
                    "user_id": int(sess.user_id),
                }

        sess = await asyncio.to_thread(_check_session)
        if sess is None or sess["state"] != "ACTIVE" or sess["expires_at"] <= datetime.utcnow():
            raise OAuth2InvalidAccessTokenError()

        try:
            client = await self.clients.get_active_client_model(sess["client_id"])
        except (OAuth2ClientDisabledError, OAuth2ClientNotFoundError) as exc:
            raise OAuth2InvalidAccessTokenError() from exc
        if not client.enabled:
            raise OAuth2InvalidAccessTokenError()

        identity = await self._identity_lookup(sess["tenant_id"], sess["user_id"])
        if identity is None or not identity.active:
            raise OAuth2InvalidAccessTokenError()

        scopes = set(str(claims.get("scope", "")).split()) & set(sess["scope"].split())
        return OAuth2UserInfoResponse(
            sub=str(identity.user_id),
            preferred_username=identity.username if "profile" in scopes else None,
            name=identity.display_name if "profile" in scopes else None,
            email=identity.email if "email" in scopes else None,
            tenant_id=str(identity.tenant_id),
            tenant_name=identity.tenant_name,
        )

    async def revoke_token(self, *, token: str, client_id: str | None = None, client_secret: str | None = None) -> None:
        # Authenticate supplied credentials even for an unknown token (RFC 7009).
        if client_id:
            client = await self.clients.get_active_client_model(client_id)
            self.clients.authenticate_client(client, client_secret)
        if not token:
            return
        token_hash = _sha256_hex(token)

        def _lookup_refresh():
            with self._session_factory() as db:
                rt = OAuth2SessionRepository(db).get_refresh_token(token_hash)
                return (rt.client_id, rt.session_id) if rt is not None else None

        match = await asyncio.to_thread(_lookup_refresh)
        if match is None:
            try:
                claims = await self.decode_access_token(f"Bearer {token}")
            except OAuth2InvalidAccessTokenError:
                return  # Unknown token: RFC 7009 idempotent success.
            session_id = str(claims["session_id"])

            def _lookup_session():
                with self._session_factory() as db:
                    sess = OAuth2SessionRepository(db).get_session(session_id)
                    return (sess.client_id, sess.session_id) if sess is not None else None

            match = await asyncio.to_thread(_lookup_session)
        if match is None:
            return
        owner_client_id, session_id = match
        if client_id is not None and client_id != owner_client_id:
            raise OAuth2InvalidClientAuthError()
        if client_id is None:
            owner = await self.clients.get_active_client_model(owner_client_id)
            # Public clients remain compatible; confidential clients must identify
            # themselves and authenticate for either access or refresh revocation.
            if owner.client_type == "confidential":
                raise OAuth2InvalidClientAuthError()

        def _do_revoke():
            with self._session_factory() as db:
                OAuth2SessionRepository(db).revoke_session(session_id)

        await asyncio.to_thread(_do_revoke)
