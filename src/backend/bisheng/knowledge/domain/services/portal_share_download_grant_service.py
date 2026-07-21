from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

import jwt

from bisheng.common.errcode.knowledge_space import PortalShareDownloadGrantInvalidError
from bisheng.knowledge.domain.schemas.portal_pdf_download_schema import PortalShareDownloadGrantClaims

_GRANT_PURPOSE = "portal_share_pdf_download"
_GRANT_AUDIENCE = "shougang_portal"
_KEY_DOMAIN = b"portal-share-download-grant-v1"


@dataclass(frozen=True)
class IssuedPortalShareDownloadGrant:
    token: str
    expires_at: int


class PortalShareDownloadGrantService:
    def __init__(
        self,
        *,
        secret: str,
        ttl_seconds: int = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not secret:
            raise ValueError("grant secret is required")
        if not 1 <= int(ttl_seconds) <= 900:
            raise ValueError("grant ttl must be between 1 and 900 seconds")
        self._signing_key = hmac.new(secret.encode(), _KEY_DOMAIN, hashlib.sha256).digest()
        self._ttl_seconds = int(ttl_seconds)
        self._clock = clock

    @property
    def signing_key(self) -> bytes:
        return self._signing_key

    def issue(
        self,
        *,
        user_id: int,
        tenant_id: int,
        share_token: str | None = None,
        space_id: int,
        file_id: int,
        allow_download: bool,
        not_after: int | None = None,
    ) -> IssuedPortalShareDownloadGrant:
        if not allow_download:
            raise PortalShareDownloadGrantInvalidError()
        now = int(self._clock())
        expires_at = now + self._ttl_seconds
        if not_after is not None:
            expires_at = min(expires_at, int(not_after))
        if expires_at <= now:
            raise PortalShareDownloadGrantInvalidError()
        claims = PortalShareDownloadGrantClaims(
            sub=str(int(user_id)),
            tenant_id=int(tenant_id),
            share_token=str(share_token),
            space_id=int(space_id),
            file_id=int(file_id),
            allow_download=True,
            iat=now,
            exp=expires_at,
            jti=secrets.token_urlsafe(18),
        )
        token = jwt.encode(
            claims.model_dump(mode="json"),
            self._signing_key,
            algorithm="HS256",
        )
        return IssuedPortalShareDownloadGrant(token=token, expires_at=expires_at)

    def verify(
        self,
        token: str,
        *,
        user_id: int,
        tenant_id: int,
        share_token: str | None = None,
        space_id: int,
        file_id: int,
    ) -> PortalShareDownloadGrantClaims:
        try:
            payload = jwt.decode(
                token,
                self._signing_key,
                algorithms=["HS256"],
                audience=_GRANT_AUDIENCE,
                options={
                    "require": [
                        "v",
                        "purpose",
                        "aud",
                        "sub",
                        "tenant_id",
                        "share_token",
                        "space_id",
                        "file_id",
                        "allow_download",
                        "iat",
                        "exp",
                        "jti",
                    ]
                },
            )
            claims = PortalShareDownloadGrantClaims.model_validate(payload)
            expected = (
                claims.v == 1,
                claims.purpose == _GRANT_PURPOSE,
                claims.aud == _GRANT_AUDIENCE,
                claims.sub == str(int(user_id)),
                claims.tenant_id == int(tenant_id),
                share_token is None or hmac.compare_digest(claims.share_token, str(share_token)),
                claims.space_id == int(space_id),
                claims.file_id == int(file_id),
                claims.allow_download is True,
            )
            if not all(expected):
                raise ValueError("grant context mismatch")
            return claims
        except Exception:
            raise PortalShareDownloadGrantInvalidError() from None
