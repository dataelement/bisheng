"""Error codes shared by the shared-space storage contracts (M0 frozen).

Every failure path in F1-F3 must raise :class:`SharedStorageContractError`
with one of the codes below so that business modules (B1-B6) can map errors
to HTTP responses and logging dimensions without depending on module
internals. The classification also encodes the fail-closed policy from
section 8.1 of the refactor spec.
"""
from __future__ import annotations

from enum import Enum


class SharedStorageErrorCode(str, Enum):
    # --- routing / bootstrap (F1) ---
    #: Shared routing state (SQL routing table) does not match this process's
    #: cached routing version - a gray-release inconsistency (risk R16).
    ROUTING_VERSION_MISMATCH = "routing_version_mismatch"
    #: The existing shared collection/index schema does not match the schema
    #: fingerprint recorded at bootstrap - refuse to write (risk R8).
    SCHEMA_FINGERPRINT_MISMATCH = "schema_fingerprint_mismatch"
    #: The tenant's shared storage routing is not enabled/initialised yet.
    SHARED_STORAGE_NOT_ENABLED = "shared_storage_not_enabled"
    #: The tenant routing table is missing an entry for the tenant.
    ROUTING_NOT_CONFIGURED = "routing_not_configured"

    # --- write path (F1/F2) ---
    #: The tenant's SPACE writes are frozen for migration - fail closed.
    TENANT_WRITE_FROZEN = "tenant_write_frozen"
    #: ``knowledge_ids`` reached the hard ARRAY capacity (risk R12).
    MEMBERSHIP_CAPACITY_EXCEEDED = "membership_capacity_exceeded"
    #: ``knowledge_ids`` crossed the soft limit - warn only, not an error code
    #: surfaced by raises; exposed here for metric labels.
    MEMBERSHIP_SOFT_LIMIT_WARN = "membership_soft_limit_warn"
    #: An aggregated membership became empty - callers must short-circuit to
    #: the content tombstone flow instead of writing an empty array (sec 3.4).
    EMPTY_MEMBERSHIP = "empty_membership"
    #: Embedding model/dimension does not match the tenant target model.
    EMBEDDING_MODEL_MISMATCH = "embedding_model_mismatch"

    # --- readiness (F2) ---
    #: Content projection has not converged yet.
    CONTENT_PROJECTION_NOT_READY = "content_projection_not_ready"
    #: Space-membership projection has not converged yet.
    MEMBERSHIP_PROJECTION_NOT_READY = "membership_projection_not_ready"
    #: Entry does not point at the current primary version.
    ENTRY_NOT_ON_PRIMARY_VERSION = "entry_not_on_primary_version"
    #: Entry/document lifecycle is not active - fail closed.
    ENTRY_NOT_ACTIVE = "entry_not_active"

    # --- retrieval scope (F3) ---
    #: One of the requested spaces is not visible/readable for the user.
    SCOPE_SPACE_NOT_VISIBLE = "scope_space_not_visible"
    #: OpenFGA (permission service) is unavailable - fail closed (sec 8.1).
    PERMISSION_SERVICE_UNAVAILABLE = "permission_service_unavailable"
    #: The final per-entry permission check denied the hit.
    PERMISSION_DENIED = "permission_denied"
    #: Explicitly referenced entry cannot be resolved to a visible entry.
    ENTRY_REF_NOT_RESOLVABLE = "entry_ref_not_resolvable"


class SharedStorageContractError(RuntimeError):
    """Raised by shared-storage writer/resolver/readiness implementations.

    Attributes:
        code: Stable machine-readable code, never renamed after freeze.
        tenant_id: Tenant the failure is scoped to, when known.
    """

    def __init__(self, code: SharedStorageErrorCode, message: str, tenant_id: int | None = None):
        super().__init__(f"[{code.value}] {message}")
        self.code = code
        self.tenant_id = tenant_id
