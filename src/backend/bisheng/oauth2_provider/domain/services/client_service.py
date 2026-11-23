"""OAuth 2.0 / OIDC client administration, redirect URI validation, secret hashing and PKCE."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from contextlib import AbstractContextManager
from urllib.parse import urlsplit

from bisheng.common.errcode.oauth2_provider import (
    OAuth2BuiltinClientProtectedError,
    OAuth2ClientAlreadyExistsError,
    OAuth2ClientDisabledError,
    OAuth2ClientNotFoundError,
    OAuth2InvalidClientAuthError,
    OAuth2InvalidRedirectUriError,
    OAuth2InvalidRequestError,
    OAuth2InvalidScopeError,
    OAuth2PkceVerificationFailedError,
)
from bisheng.oauth2_provider.domain.models.client import OAuth2Client
from bisheng.oauth2_provider.domain.repositories.client import OAuth2ClientRepository
from bisheng.oauth2_provider.domain.repositories.session import OAuth2SessionRepository
from bisheng.oauth2_provider.domain.schemas.client import (
    OAuth2ClientCreate,
    OAuth2ClientResponse,
    OAuth2ClientSecretResponse,
    OAuth2ClientUpdate,
)

_PBKDF2_ITERATIONS = 200_000
_ALLOWED_GRANT_TYPES = {"authorization_code", "refresh_token"}
_SUPPORTED_SCOPES = {"openid", "profile", "email", "offline_access", "dsh"}
_PKCE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_PKCE_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def hash_client_secret(secret: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt.encode("ascii"), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${base64.urlsafe_b64encode(dk).decode('ascii')}"


def verify_client_secret(secret: str, stored_hash: str | None) -> bool:
    if not secret or not stored_hash:
        return False
    parts = stored_hash.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
        salt = parts[2]
        expected = parts[3]
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt.encode("ascii"), iterations)
    actual = base64.urlsafe_b64encode(dk).decode("ascii")
    return hmac.compare_digest(actual, expected)


def validate_registered_redirect_uri(uri: str) -> str:
    cleaned = uri.strip()
    parsed = urlsplit(cleaned)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OAuth2InvalidRedirectUriError(msg=f"Invalid redirect_uri: {uri}")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        # Allow http for enterprise intranet deployments, but reject malformed hostnames.
        pass
    return cleaned


def match_redirect_uri(candidate: str, registered_uris: list[str], *, allow_loopback_port: bool) -> bool:
    if not candidate:
        return False
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    if candidate in registered_uris:
        return True
    if not allow_loopback_port or parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return False
    if not parsed.port or parsed.query:
        return False
    for reg in registered_uris:
        reg_parsed = urlsplit(reg)
        if (
            reg_parsed.scheme == "http"
            and reg_parsed.hostname == parsed.hostname
            and reg_parsed.port is None
            and reg_parsed.path == parsed.path
            and not reg_parsed.query
        ):
            return True
    return False


def validate_pkce_challenge(challenge: str, method: str) -> None:
    if method != "S256" or not _PKCE_CHALLENGE_RE.fullmatch(challenge):
        raise OAuth2InvalidRequestError(msg="Invalid PKCE code_challenge or code_challenge_method")
    try:
        raw = base64.urlsafe_b64decode(challenge + "=")
        if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != challenge:
            raise ValueError("Invalid base64url challenge")
    except (ValueError, TypeError) as exc:
        raise OAuth2InvalidRequestError(msg="Invalid PKCE code_challenge") from exc


def verify_pkce_verifier(challenge: str, verifier: str | None) -> None:
    if not isinstance(verifier, str) or not _PKCE_VERIFIER_RE.fullmatch(verifier):
        raise OAuth2PkceVerificationFailedError()
    actual = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    if not hmac.compare_digest(challenge, actual):
        raise OAuth2PkceVerificationFailedError()


def to_client_response(client: OAuth2Client) -> OAuth2ClientResponse:
    return OAuth2ClientResponse(
        id=int(client.id or 0),
        client_id=client.client_id,
        client_name=client.client_name,
        description=client.description,
        client_type="public" if client.client_type == "public" else "confidential",
        has_secret=bool(client.client_secret_hash),
        redirect_uris=list(client.redirect_uris or []),
        allow_loopback_port=bool(client.allow_loopback_port),
        allowed_scopes=list(client.allowed_scopes or []),
        grant_types=list(client.grant_types or []),
        require_pkce=bool(client.require_pkce),
        require_consent=bool(client.require_consent),
        enabled=bool(client.enabled),
        is_builtin=bool(client.is_builtin),
        access_token_ttl=int(client.access_token_ttl),
        refresh_token_ttl=int(client.refresh_token_ttl),
        create_time=client.create_time,
        update_time=client.update_time,
    )


class OAuth2ClientService:
    def __init__(self, session_factory: Callable[[], AbstractContextManager]):
        self._session_factory = session_factory

    def _validate_scopes_and_grants(self, scopes: list[str], grant_types: list[str]) -> tuple[list[str], list[str]]:
        cleaned_scopes = [s.strip() for s in scopes if s and s.strip()]
        if not cleaned_scopes or any(s not in _SUPPORTED_SCOPES for s in cleaned_scopes):
            raise OAuth2InvalidScopeError()
        cleaned_grants = [g.strip() for g in grant_types if g and g.strip()]
        if not cleaned_grants or any(g not in _ALLOWED_GRANT_TYPES for g in cleaned_grants):
            raise OAuth2InvalidRequestError(msg="Unsupported grant_type in client configuration")
        return list(dict.fromkeys(cleaned_scopes)), list(dict.fromkeys(cleaned_grants))

    async def ensure_builtin_dsh_client(self) -> OAuth2ClientResponse:
        def _op():
            with self._session_factory() as db:
                row = OAuth2ClientRepository(db).ensure_builtin_dsh_client()
                return to_client_response(row)

        return await asyncio.to_thread(_op)

    async def list_clients(
        self, *, keyword: str | None = None, page: int = 1, page_size: int = 50
    ) -> tuple[list[OAuth2ClientResponse], int]:
        def _op():
            with self._session_factory() as db:
                repo = OAuth2ClientRepository(db)
                repo.ensure_builtin_dsh_client()
                rows, total = repo.list_clients(keyword=keyword, page=page, page_size=page_size)
                return [to_client_response(row) for row in rows], total

        return await asyncio.to_thread(_op)

    async def get_client(self, client_id: str) -> OAuth2ClientResponse:
        def _op():
            with self._session_factory() as db:
                repo = OAuth2ClientRepository(db)
                if client_id == "dsh-desktop":
                    repo.ensure_builtin_dsh_client()
                row = repo.get_by_client_id(client_id)
                if row is None:
                    raise OAuth2ClientNotFoundError()
                return to_client_response(row)

        return await asyncio.to_thread(_op)

    async def get_active_client_model(self, client_id: str) -> OAuth2Client:
        def _op():
            with self._session_factory() as db:
                repo = OAuth2ClientRepository(db)
                if client_id == "dsh-desktop":
                    repo.ensure_builtin_dsh_client()
                row = repo.get_by_client_id(client_id)
                if row is None:
                    raise OAuth2ClientNotFoundError()
                if not row.enabled:
                    raise OAuth2ClientDisabledError()
                return OAuth2Client.model_validate(row.model_dump())

        return await asyncio.to_thread(_op)

    async def create_client(self, body: OAuth2ClientCreate) -> OAuth2ClientSecretResponse:
        redirect_uris = [validate_registered_redirect_uri(u) for u in body.redirect_uris]
        scopes, grant_types = self._validate_scopes_and_grants(body.allowed_scopes, body.grant_types)
        client_id = body.client_id or f"bs_{secrets.token_urlsafe(12)}"
        raw_secret = f"bss_{secrets.token_urlsafe(32)}" if body.client_type == "confidential" else None
        secret_hash = hash_client_secret(raw_secret) if raw_secret else None
        require_pkce = True if body.client_type == "public" else body.require_pkce

        def _op():
            with self._session_factory() as db:
                repo = OAuth2ClientRepository(db)
                if repo.get_by_client_id(client_id) is not None:
                    raise OAuth2ClientAlreadyExistsError()
                model = OAuth2Client(
                    client_id=client_id,
                    client_name=body.client_name.strip(),
                    description=body.description.strip() if body.description else None,
                    client_type=body.client_type,
                    client_secret_hash=secret_hash,
                    redirect_uris=list(dict.fromkeys(redirect_uris)),
                    allow_loopback_port=body.allow_loopback_port,
                    allowed_scopes=scopes,
                    grant_types=grant_types,
                    require_pkce=require_pkce,
                    require_consent=body.require_consent,
                    enabled=body.enabled,
                    is_builtin=False,
                    access_token_ttl=body.access_token_ttl,
                    refresh_token_ttl=body.refresh_token_ttl,
                )
                created = repo.create(model)
                return OAuth2ClientSecretResponse(client=to_client_response(created), client_secret=raw_secret)

        return await asyncio.to_thread(_op)

    async def update_client(self, client_id: str, body: OAuth2ClientUpdate) -> OAuth2ClientResponse:
        def _op():
            with self._session_factory() as db:
                repo = OAuth2ClientRepository(db)
                if client_id == "dsh-desktop":
                    repo.ensure_builtin_dsh_client()
                row = repo.get_by_client_id(client_id)
                if row is None:
                    raise OAuth2ClientNotFoundError()
                if body.client_name is not None:
                    row.client_name = body.client_name.strip()
                if body.description is not None:
                    row.description = body.description.strip() or None
                if body.redirect_uris is not None:
                    row.redirect_uris = list(
                        dict.fromkeys(validate_registered_redirect_uri(u) for u in body.redirect_uris)
                    )
                if body.allow_loopback_port is not None:
                    row.allow_loopback_port = body.allow_loopback_port
                if body.allowed_scopes is not None or body.grant_types is not None:
                    scopes, grants = self._validate_scopes_and_grants(
                        body.allowed_scopes if body.allowed_scopes is not None else list(row.allowed_scopes or []),
                        body.grant_types if body.grant_types is not None else list(row.grant_types or []),
                    )
                    row.allowed_scopes = scopes
                    row.grant_types = grants
                if body.require_pkce is not None:
                    row.require_pkce = True if row.client_type == "public" else body.require_pkce
                if body.require_consent is not None:
                    row.require_consent = body.require_consent
                if body.enabled is not None:
                    row.enabled = body.enabled
                if body.access_token_ttl is not None:
                    row.access_token_ttl = body.access_token_ttl
                if body.refresh_token_ttl is not None:
                    row.refresh_token_ttl = body.refresh_token_ttl
                updated = repo.save(row)
                return to_client_response(updated)

        return await asyncio.to_thread(_op)

    async def rotate_secret(self, client_id: str) -> OAuth2ClientSecretResponse:
        raw_secret = f"bss_{secrets.token_urlsafe(32)}"
        secret_hash = hash_client_secret(raw_secret)

        def _op():
            with self._session_factory() as db:
                repo = OAuth2ClientRepository(db)
                row = repo.get_by_client_id(client_id)
                if row is None:
                    raise OAuth2ClientNotFoundError()
                if row.client_type != "confidential":
                    raise OAuth2InvalidRequestError(msg="Public clients do not have a client_secret")
                row.client_secret_hash = secret_hash
                updated = repo.save(row)
                return OAuth2ClientSecretResponse(client=to_client_response(updated), client_secret=raw_secret)

        return await asyncio.to_thread(_op)

    async def delete_client(self, client_id: str) -> None:
        def _op():
            with self._session_factory() as db:
                repo = OAuth2ClientRepository(db)
                row = repo.get_by_client_id(client_id)
                if row is None:
                    raise OAuth2ClientNotFoundError()
                if row.is_builtin:
                    raise OAuth2BuiltinClientProtectedError()
                OAuth2SessionRepository(db).revoke_by_client_id(client_id)
                repo.delete(row)

        await asyncio.to_thread(_op)

    @staticmethod
    def authenticate_client(client: OAuth2Client, client_secret: str | None) -> None:
        if client.client_type == "confidential":
            if not verify_client_secret(client_secret or "", client.client_secret_hash):
                raise OAuth2InvalidClientAuthError()
        elif client_secret:
            raise OAuth2InvalidClientAuthError()
