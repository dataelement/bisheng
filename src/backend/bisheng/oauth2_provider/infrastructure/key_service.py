"""Deterministic ES256 (P-256) signing keys and JWKS derived from platform JWT master secret.

Every API replica derives the exact same asymmetric keypair without shared filesystem state (C8),
allowing external OIDC clients to verify id_token and access_token purely via standard JWKS.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from collections.abc import Callable
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec

OAUTH2_KEY_ID = "bisheng-oauth2-es256-v1"
OAUTH2_SIGNING_LABEL = b"bisheng:oauth2:es256:v1"
# Order n of NIST P-256 (secp256r1)
_SECP256R1_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def _b64url_uint(value: int, length: int) -> str:
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).decode("ascii").rstrip("=")


class OAuth2KeyService:
    def __init__(self, secret_reader: Callable[[], str] | None = None):
        self.secret_reader = secret_reader

    async def _master(self) -> str:
        if self.secret_reader is None:
            from bisheng.user.domain.services.jwt_secret import resolve_jwt_secret

            reader = resolve_jwt_secret
        else:
            reader = self.secret_reader
        return await asyncio.to_thread(reader)

    async def get_private_key(self) -> ec.EllipticCurvePrivateKey:
        master = await self._master()
        digest = hmac.digest(master.encode("utf-8"), OAUTH2_SIGNING_LABEL, hashlib.sha256)
        private_value = (int.from_bytes(digest, "big") % (_SECP256R1_ORDER - 1)) + 1
        return ec.derive_private_key(private_value, ec.SECP256R1())

    async def get_public_key(self) -> ec.EllipticCurvePublicKey:
        return (await self.get_private_key()).public_key()

    async def get_jwks(self) -> dict[str, list[dict[str, Any]]]:
        public_key = await self.get_public_key()
        numbers = public_key.public_numbers()
        return {
            "keys": [
                {
                    "kty": "EC",
                    "crv": "P-256",
                    "use": "sig",
                    "alg": "ES256",
                    "kid": OAUTH2_KEY_ID,
                    "x": _b64url_uint(numbers.x, 32),
                    "y": _b64url_uint(numbers.y, 32),
                }
            ]
        }
