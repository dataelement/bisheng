"""Purpose-separated desktop signing using the platform's persistent master key."""

import asyncio
import base64
import hashlib
import hmac

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError

KEY_ID = "dsh-local-v1"
ISSUER = "bisheng-dsh"
# Distinct from the access-token key so a refresh successor cannot be used as a JWT key.
REFRESH_SUCCESSOR_LABEL = b"bisheng:dsh:refresh-successor:v1"


def successor_refresh_token(key: bytes, refresh: str) -> str:
    """Derive the only successor of a refresh token. Repeating the input returns the same value."""
    raw = hmac.digest(key, refresh.encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class LocalTokenKeys:
    def __init__(self, secret_reader=None):
        self.secret_reader = secret_reader

    async def _master(self) -> str:
        if self.secret_reader is None:
            from bisheng.user.domain.services.jwt_secret import resolve_jwt_secret

            reader = resolve_jwt_secret
        else:
            reader = self.secret_reader
        return await asyncio.to_thread(reader)

    async def resolve(self, kid):
        if kid != KEY_ID:
            raise DshInvalidAccessTokenError()
        # Distinct from both Web JWT and the removed Gateway shared-secret key.
        master = await self._master()
        return hmac.digest(master.encode(), b"bisheng:dsh:local-access:v1", hashlib.sha256)

    async def resolve_refresh_successor_key(self) -> bytes:
        master = await self._master()
        return hmac.digest(master.encode(), REFRESH_SUCCESSOR_LABEL, hashlib.sha256)
