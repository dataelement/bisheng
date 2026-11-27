"""Short-lived local PKCE authorization requests, shared across API replicas."""

import base64
import hashlib
import hmac
from urllib.parse import urlsplit
from uuid import uuid4

from bisheng.common.errcode.dsh import (
    DshAuthorizationExpiredError,
    DshDshDisabledError,
    DshInvalidRequestError,
    DshPkceVerificationFailedError,
    DshTooManyRequestsError,
)
from bisheng.common.errcode.oauth2_provider import (
    OAuth2ClientDisabledError,
    OAuth2ClientNotFoundError,
    OAuth2InvalidRequestError,
)
from bisheng.oauth2_provider.domain.services.client_service import (
    match_redirect_uri,
    validate_pkce_challenge,
)


class DshAuthorizationService:
    def __init__(self, redis, origin, *, oauth2_clients=None):
        from bisheng.dsh.domain.repositories.authorization import DshAuthorizationRepository

        self.repository, self.origin = DshAuthorizationRepository(redis), origin
        self.oauth2_clients = oauth2_clients

    async def rate(self, action, peer):
        count = await self.repository.rate(action, peer)
        if int(count) > (1200 if action == "authorization" else 6000):
            raise DshTooManyRequestsError()

    async def create(self, body, *, origin=None):
        public_origin = self.origin or origin
        if not public_origin:
            raise DshInvalidRequestError()
        require_consent = True
        client_name = "BiSheng Desktop"
        if self.oauth2_clients is not None:
            try:
                client = await self.oauth2_clients.get_active_client_model(body.client_id)
            except OAuth2ClientDisabledError as error:
                raise DshDshDisabledError() from error
            except OAuth2ClientNotFoundError as error:
                raise DshInvalidRequestError() from error
            if not match_redirect_uri(
                body.redirect_uri,
                list(client.redirect_uris or []),
                allow_loopback_port=bool(client.allow_loopback_port),
            ):
                raise DshInvalidRequestError()
            try:
                validate_pkce_challenge(body.code_challenge, body.code_challenge_method)
            except OAuth2InvalidRequestError as error:
                raise DshInvalidRequestError() from error
            require_consent = bool(client.require_consent)
            client_name = client.client_name
        else:
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
        payload["require_consent"] = require_consent
        payload["client_name"] = client_name
        await self.repository.save(auth_id, payload)
        return {
            "auth_id": auth_id,
            "authorize_url": public_origin + "/desktop-login?auth_id=" + auth_id,
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
            "client_name": payload.get("client_name") or "BiSheng Desktop",
            "require_consent": bool(payload.get("require_consent", True)),
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
