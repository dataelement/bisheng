"""Current natural-person identity and one-time browser authorization."""

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import Field

from bisheng.common.errcode.dsh import (
    DshAuthorizationUnavailableError,
    DshInvalidGrantError,
    DshUserDisabledError,
)
from bisheng.dsh.domain.repositories.tickets import TicketRepository
from bisheng.dsh.domain.schemas.contracts import DshContract, DshIdentitySnapshot, DshTenantDisplay, DshUserDisplay
from bisheng.dsh.domain.schemas.identity import IdentityRecord


@dataclass(frozen=True)
class BrowserIdentity:
    tenant_id: str
    user_id: str
    credential_kind: str = "user"


class IdentityRecords(Protocol):
    async def get(self, tenant_id: str, user_id: str) -> IdentityRecord | None: ...


class AuthorizationIntent(DshContract):
    challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    redirect_uri: str
    client_id: str
    instance: str
    state: str = Field(min_length=1, max_length=512)
    expires_in: int = Field(strict=True, ge=1, le=300)


class IdentityService:
    def __init__(self, installation_id: str, tickets: TicketRepository, identities: IdentityRecords, gateway):
        self.installation_id = installation_id
        self.tickets = tickets
        self.identities = identities
        self.gateway = gateway

    async def check(self, tenant_id: str, user_id: str) -> DshIdentitySnapshot:
        if not re.fullmatch(r"[1-9][0-9]*", tenant_id) or not re.fullmatch(r"[1-9][0-9]*", user_id):
            raise DshInvalidGrantError()
        record = await self.identities.get(tenant_id, user_id)
        reason = None
        if record is None or not record.active or not record.natural_person or not record.username.strip():
            reason = "user_disabled"
        elif not record.tenant_active or record.tenant_id != tenant_id or record.user_id != user_id:
            reason = "tenant_unavailable"
        if reason:
            return DshIdentitySnapshot(
                installation_id=self.installation_id, tenant_id=tenant_id, user_id=user_id, active=False, reason=reason
            )
        return DshIdentitySnapshot(
            installation_id=self.installation_id,
            tenant_id=tenant_id,
            user_id=user_id,
            active=True,
            user=DshUserDisplay(
                id=user_id,
                username=record.username,
                display_name=(record.display_name or "").strip() or record.username,
            ),
            tenant=DshTenantDisplay(id=tenant_id, name=(record.tenant_name or "").strip() or f"Tenant {tenant_id}"),
            profile_version=record.profile_version,
        )

    async def authorize(
        self, identity: BrowserIdentity, auth_id: str, *, decision: str = "approve"
    ) -> dict[str, str | int]:
        # Only the browser JWT dependency constructs BrowserIdentity; never use request body identity fields.
        if identity.credential_kind != "user":
            raise DshUserDisabledError()
        snapshot = await self.check(identity.tenant_id, identity.user_id)
        if not snapshot.active:
            raise DshUserDisabledError()
        try:
            intent = AuthorizationIntent.model_validate(await self.gateway.resolve(auth_id))
            parsed = urlsplit(intent.redirect_uri)
            valid_redirect = (
                parsed.scheme == "http"
                and parsed.hostname == "127.0.0.1"
                and parsed.port
                and parsed.path == "/dsh/callback"
                and not parsed.query
                and not parsed.fragment
                and parsed.username is None
                and parsed.password is None
            )
        except ValueError:
            raise DshAuthorizationUnavailableError() from None
        if intent.instance != self.installation_id or intent.client_id != "dsh-desktop" or not valid_redirect:
            raise DshInvalidGrantError()
        if decision == "deny":
            return {"error": "access_denied", "redirect_uri": intent.redirect_uri, "state": intent.state}
        if decision != "approve":
            raise DshInvalidGrantError()
        binding = {
            "auth_id": auth_id,
            "client_id": intent.client_id,
            "redirect_uri": intent.redirect_uri,
            "code_challenge": intent.challenge,
        }
        ttl = min(60, intent.expires_in)
        ticket = await self.tickets.issue(identity.tenant_id, identity.user_id, binding, ttl=ttl)
        return {
            "identity_ticket": ticket,
            "redirect_uri": intent.redirect_uri,
            "state": intent.state,
            "expires_in": ttl,
        }

    async def redeem(self, ticket: str, binding: dict[str, str]) -> DshIdentitySnapshot:
        if set(binding) != {"auth_id", "client_id", "redirect_uri", "code_challenge"}:
            raise DshInvalidGrantError()
        payload = await self.tickets.consume(ticket, binding)
        return await self.check(payload["tenant_id"], payload["user_id"])
