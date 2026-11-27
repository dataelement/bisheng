"""A verified password identity, before any session/token delivery side effect."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PasswordLoginIdentity:
    user: Any
    tenant_id: int
    role_ids: tuple[int, ...]
    is_department_admin: bool
    token_version: int
    requires_tenant_selection: bool = False
    tenants_list: list[dict] | None = None
