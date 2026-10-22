"""Short-lived local PKCE authorization requests, shared across API replicas."""

import base64
import hashlib
import hmac
from urllib.parse import urlsplit
from uuid import uuid4

from bisheng.common.errcode.dsh import (
    DshAuthorizationExpiredError,
    DshInvalidRequestError,
    DshPkceVerificationFailedError,
    DshTooManyRequestsError,
)


class DshAuthorizationService:
    def __init__(self, redis, origin):
        from bisheng.dsh.domain.repositories.authorization import DshAuthorizationRepository

        self.repository, self.origin = DshAuthorizationRepository(redis), origin

    async def rate(self, action, peer):
        count = await self.repository.rate(action, peer)
        if int(count) > (1200 if action == "authorization" else 6000):
            raise DshTooManyRequestsError()

    async def create(self, body):
        try:
            redirect = urlsplit(body.redirect_uri)
            if (
                redirect.scheme != "http"
                or redirect.hostname != "127.0.0.1"
                or not redirect.port
                or redirect.path != "/dsh/callback"
                or redirect.query
                or redirect.fragment
                or redirect.username is not None
                or redirect.password is not None
            ):
                raise ValueError("Invalid callback")
            raw = base64.urlsafe_b64decode(body.code_challenge + "=")
            if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != body.code_challenge:
                raise ValueError("Invalid challenge")
        except (ValueError, TypeError) as error:
            raise DshInvalidRequestError() from error
        auth_id = str(uuid4())
        payload = body.model_dump()
        await self.repository.save(auth_id, payload)
        return {
            "auth_id": auth_id,
            "authorize_url": self.origin + "/desktop-login?auth_id=" + auth_id,
            "expires_in": 300,
        }

    async def resolve(self, auth_id):
        from uuid import UUID

        try:
            if str(UUID(auth_id)) != auth_id:
                raise ValueError("Invalid id")
        except (ValueError, TypeError, AttributeError) as error:
            raise DshInvalidRequestError() from error
        result = await self.repository.read(auth_id)
        if result is None:
            raise DshAuthorizationExpiredError()
        payload, ttl = result
        return {
            "challenge": payload["code_challenge"],
            "redirect_uri": payload["redirect_uri"],
            "client_id": payload["client_id"],
            "state": payload["state"],
            "expires_in": ttl,
            "device_name": payload.get("device_name"),
            "client_version": payload.get("client_version"),
        }

    @staticmethod
    def verify(challenge, verifier):
        import re

        if not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
            raise DshPkceVerificationFailedError()
        actual = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode().rstrip("=")
        if not hmac.compare_digest(challenge, actual):
            raise DshPkceVerificationFailedError()
