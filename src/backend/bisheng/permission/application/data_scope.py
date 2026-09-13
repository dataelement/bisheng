"""Application-facing exports for the F066 data-scope narrowing contract.

Business modules depend on ``permission.application`` only (constitution C4);
this module re-exports the domain-level protocol and registry so the knowledge
domain can register its ownership resolver without importing permission
domain services directly.
"""

from bisheng.permission.domain.services.data_scope import (
    DATA_SCOPE_ALL,
    DATA_SCOPE_PERSONAL,
    DataScopeOwnershipResolver,
    get_data_scope_resolver,
    register_data_scope_resolver,
)

__all__ = [
    "DATA_SCOPE_ALL",
    "DATA_SCOPE_PERSONAL",
    "DataScopeOwnershipResolver",
    "get_data_scope_resolver",
    "register_data_scope_resolver",
]
