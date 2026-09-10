"""Fixed-origin HTTP(S) client for DSH's authenticated Gateway surface."""

import json
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import Field, ValidationError, model_validator

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError
from bisheng.dsh.domain.schemas.contracts import DshContract
from bisheng.dsh.infrastructure.service_auth import ServiceAuth


class SeatIntrospection(DshContract):
    active: bool
    seat_id: str | None = None
    session_id: str | None = None
    grant_version: int | None = Field(default=None, strict=True, ge=1)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_active(self):
        if self.active and (not self.seat_id or not self.session_id or self.grant_version is None or self.reason):
            raise ValueError("Incomplete active seat response")
        if not self.active and not self.reason:
            raise ValueError("Inactive seat response requires a stable reason")
        return self


class GatewayCommandRejected(Exception):
    """The trusted command endpoint definitively rejected this immutable intent."""


class GatewayClient:
    PATHS = {
        "introspect": "/api/internal/dsh/introspect",
        "resolve": "/api/internal/dsh/authorizations/resolve",
        "management": "/api/internal/dsh/management/read",
        "self_sessions": "/api/internal/dsh/self/sessions",
        "self_revoke": "/api/internal/dsh/self/sessions/revoke",
        "revoke": "/api/internal/dsh/seats/revoke",
        "reassign": "/api/internal/dsh/seats/reassign",
        "operation": "/api/internal/dsh/operations/read",
        "profiles": "/api/internal/dsh/profiles/upsert",
    }

    def __init__(self, origin: str, auth: ServiceAuth, client: httpx.AsyncClient, timeout: float = 2.0):
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Gateway requires a credential-free HTTP(S) origin")
        self.origin = origin.rstrip("/")
        self.auth = auth
        self.client = client
        self.timeout = timeout

    async def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = self.PATHS[operation]
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        headers = self.auth.sign("POST", path, body)
        headers["Content-Type"] = "application/json"
        try:
            response = await self.client.post(
                self.origin + path, content=body, headers=headers, timeout=self.timeout, follow_redirects=False
            )
            result = response.json()
            if response.status_code != 200:
                if (
                    operation in {"revoke", "reassign"}
                    and response.status_code == 409
                    and isinstance(result, dict)
                    and set(result) == {"error", "request_id"}
                    and isinstance(result["request_id"], str)
                    and bool(result["request_id"])
                    and isinstance(result["error"], dict)
                    and set(result["error"]) == {"code", "type", "message"}
                    and result["error"]["code"] == "authorization_conflict"
                    and result["error"]["type"] == "conflict_error"
                    and isinstance(result["error"]["message"], str)
                ):
                    raise GatewayCommandRejected()
                raise DshAuthorizationUnavailableError()
        except (httpx.HTTPError, ValueError):
            raise DshAuthorizationUnavailableError() from None
        if not isinstance(result, dict) or "status_code" in result or "error" in result:
            raise DshAuthorizationUnavailableError()
        return result

    async def introspect(self, token: str) -> SeatIntrospection:
        result = await self.request("introspect", {"token": token})
        try:
            return SeatIntrospection.model_validate(result)
        except ValidationError:
            raise DshAuthorizationUnavailableError() from None

    async def resolve(self, auth_id: str) -> dict[str, Any]:
        return await self.request("resolve", {"auth_id": auth_id})
