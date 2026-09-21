"""Current identity data exchanged between repository and domain service."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IdentityRecord:
    tenant_id: str
    user_id: str
    username: str
    display_name: str | None
    tenant_name: str | None
    profile_version: int
    active: bool
    tenant_active: bool
    natural_person: bool
