"""Pydantic payload schemas for F014 Gateway → bisheng SSO sync endpoints.

Two top-level requests:
  - :class:`LoginSyncRequest` for ``POST /api/v1/internal/sso/login-sync``
    (single-user, SSO login trigger; returns a signed JWT).
  - :class:`DepartmentsSyncRequest` for ``POST /api/v1/departments/sync``
    (batch Gateway-driven department upsert + remove).

See spec.md §5.1 / §5.2. Field semantics:

- ``ts`` carries the source-system timestamp that :class:`OrgSyncTsGuard`
  uses to enforce INV-T12 (ts max wins; same ts with upsert-vs-remove →
  remove wins). For batch endpoints, individual items may omit ``ts`` and
  fall back to the batch-level ``source_ts``.
- ``primary_dept_external_id`` is optional — absent value represents the
  "user has no HR department" case and falls back to Root tenant (PRD
  §5.6.3 tolerance rule).
- ``parent_external_id = None`` on :class:`DepartmentUpsertItem` means the
  department is a direct child of Root (top-level).
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class UserAttrsDTO(BaseModel):
    """Soft user attributes pushed alongside SSO login. All fields optional
    because the upstream HR system may not populate every attribute."""
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class TenantMappingItem(BaseModel):
    """Optional auxiliary input to auto-mount a Child Tenant on a department
    the first time it appears in SSO (PRD §5.2.3). Idempotent — a second
    payload referencing the same ``dept_external_id`` is ignored because
    bisheng's ``is_tenant_root`` flag wins.
    """
    dept_external_id: str
    tenant_code: str
    tenant_name: str
    initial_quota: Optional[dict] = None
    initial_admin_external_ids: Optional[List[str]] = None


class LoginSyncRequest(BaseModel):
    external_user_id: str = Field(
        ...,
        description='Stable HR/SSO user ID; keyed together with source="sso".',
    )
    primary_dept_external_id: Optional[str] = Field(
        default=None,
        description=(
            'Primary (main) department external_id. Absent = no HR dept, '
            'user falls back to Root tenant (spec §3 tolerance rule).'
        ),
    )
    secondary_dept_external_ids: Optional[List[str]] = Field(
        default=None,
        description='Moonlighting / secondary memberships (is_primary=0).',
    )
    user_attrs: UserAttrsDTO = Field(default_factory=UserAttrsDTO)
    root_tenant_id: int = Field(
        default=1,
        description='Gateway supplies Root id for validation; always 1 in MVP.',
    )
    tenant_mapping: Optional[List[TenantMappingItem]] = Field(
        default=None,
        description='Optional auto-mount directives (PRD §5.2.3).',
    )
    ts: int = Field(
        ...,
        description='Source system timestamp (seconds). Required by INV-T12.',
    )


class LoginSyncResponse(BaseModel):
    user_id: int
    leaf_tenant_id: int
    token: str


class DepartmentUpsertItem(BaseModel):
    external_id: str
    name: str
    parent_external_id: Optional[str] = Field(
        default=None,
        description='None = top-level (direct child of Root).',
    )
    sort: int = 0
    ts: Optional[int] = Field(
        default=None,
        description=(
            'Per-item ts. Falls back to batch source_ts when absent so '
            'legacy Gateway versions keep working.'
        ),
    )


class DepartmentsSyncRequest(BaseModel):
    upsert: List[DepartmentUpsertItem] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)
    source_ts: Optional[int] = Field(
        default=None,
        description=(
            'Batch-level ts used as fallback when an individual upsert/remove '
            'item carries no ts of its own.'
        ),
    )


class BatchResult(BaseModel):
    applied_upsert: int = 0
    applied_remove: int = 0
    skipped_ts_conflict: int = 0
    orphan_triggered: List[int] = Field(default_factory=list)
    errors: List[dict] = Field(default_factory=list)
