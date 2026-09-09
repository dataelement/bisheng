"""DSH purpose-separated keys derived from the existing SSO shared secret."""

import hashlib
import hmac

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError

ACCESS_KEY_ID = "dsh-access-v1"
OUTBOUND_KEY_ID = "bisheng-to-gateway-v1"
INBOUND_KEY_ID = "gateway-to-bisheng-v1"


def derive_key(secret: str, installation_id: str, purpose: str) -> bytes:
    """HKDF-SHA256, 32 bytes; the same construction is used by Gateway."""
    if not secret or not secret.strip():
        raise ValueError("Configure the existing sso_sync.gateway_hmac_secret before enabling DSH")
    prk = hmac.digest(b"bisheng-dsh-v1", secret.encode(), hashlib.sha256)
    return hmac.digest(prk, f"{installation_id}:{purpose}".encode() + b"\x01", hashlib.sha256)


def configured_key(installation_id: str, purpose: str) -> bytes:
    from bisheng.common.services.config_service import settings

    return derive_key(settings.sso_sync.gateway_hmac_secret, installation_id, purpose)


def access_issuer(installation_id: str) -> str:
    return f"bisheng-dsh:{installation_id}"


class GatewayKeys:
    """Local token verification only; no public-key endpoint or remote key loading."""

    def __init__(self, key: bytes):
        self.key = key

    async def resolve(self, kid: str) -> bytes:
        if kid != ACCESS_KEY_ID:
            raise DshInvalidAccessTokenError()
        return self.key
