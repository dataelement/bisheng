"""Tenant-configurable data-scope narrowing for open-platform tokens (F066).

A tenant can narrow every personal access token to holder-created knowledge
only (PRD v2.9 D21).  The narrowing is a data-export control, not a permission
grant: it is evaluated *before* any identity shortcut and before any OpenFGA
query, so administrator facts never widen a narrowed token.

The permission layer must stay business-independent (constitution C4 /
INV-10), so ownership facts are supplied through a resolver protocol that the
knowledge domain implements and registers at assembly time.  With a narrowed
actor and no registered resolver the answer is always "denied" — fail closed.
"""

from __future__ import annotations

from typing import Protocol

# Single vocabulary shared by the tenant policy column, the policy cache and
# the actor field.  Unknown future values are interpreted as the narrow scope
# by the policy reader (fail closed); a missing cache key means a pre-F066
# writer and therefore the wide default.
DATA_SCOPE_ALL = "all_visible"
DATA_SCOPE_PERSONAL = "personal_only"


class DataScopeOwnershipResolver(Protocol):
    """Business-owned ownership facts consumed by the permission layer."""

    def governed_resource_types(self) -> frozenset[str]:
        """Resource types the narrowing applies to; others stay untouched."""
        ...

    async def filter_owned(
        self,
        *,
        holder_user_id: int,
        tenant_id: int,
        resource_type: str,
        resource_ids: tuple[str, ...],
    ) -> frozenset[str]:
        """Return the subset of ``resource_ids`` created by the holder."""
        ...

    async def owned_ids(
        self,
        *,
        holder_user_id: int,
        tenant_id: int,
        resource_type: str,
    ) -> frozenset[str]:
        """Return every holder-created id of ``resource_type`` (for lists)."""
        ...


_resolver: DataScopeOwnershipResolver | None = None


def register_data_scope_resolver(resolver: DataScopeOwnershipResolver) -> None:
    global _resolver
    _resolver = resolver


def get_data_scope_resolver() -> DataScopeOwnershipResolver | None:
    return _resolver


__all__ = [
    "DATA_SCOPE_ALL",
    "DATA_SCOPE_PERSONAL",
    "DataScopeOwnershipResolver",
    "get_data_scope_resolver",
    "register_data_scope_resolver",
]
