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

from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator


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
        description=(
            'Stable upstream user ID; paired with source on the user row (``sso`` '
            'for generic HMAC sync, ``wecom`` for Gateway wecom batch in '
            '``/internal/sso/gateway-wecom-org-sync``).'
        ),
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
    #: 企微「部门负责人」对应的部门 external_id（与 departments/sync 中 id 字符串一致）；
    #: 同步后写入 OpenFGA ``department:{id}#admin@user:{uid}``。
    #: 若本字段**出现在 JSON 中**（含空数组 ``[]``），则对当前用户在所有 SSO
    #: 成员部门上与该列表对账：仅撤销 ``department_admin_grant.grant_source=sso``
    #: 的部门管理员 FGA；管理端写入的 ``manual`` 不受影响。省略字段则不改 FGA/标记表。
    department_admin_external_ids: Optional[List[str]] = Field(
        default=None,
        description=(
            'WeCom leader dept external_ids; when sent (including []), reconciles '
            'FGA admin for SSO member departments, revoking only sso-tracked grants.'
        ),
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
    #: 企微等上游账号是否已禁用。为 True 时同步 ``user.delete=1`` 并走短流程（不签发 JWT）；
    #: 为 False 时确保 ``user.delete=0``。省略时保持 bisheng 既有 ``delete`` 与校验逻辑（兼容旧 Gateway）。
    account_disabled: Optional[bool] = Field(
        default=None,
        description=(
            'If True, mark user as disabled in bisheng and skip full login/JWT. '
            'If False, ensure user is enabled. Omitted: legacy behavior (do not change delete).'
        ),
    )
    #: 为 True 时不单独写 ``org_sync_log``（由 Gateway 批量接口统一落一条）。
    skip_org_sync_log: bool = Field(
        default=False,
        description='Internal: suppress per-call org_sync_log flush (batch endpoint).',
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
    #: When True (Gateway full WeCom tree), archive active departments of the
    #: same ``row_source`` whose ``external_id`` is missing from ``upsert``.
    full_snapshot: bool = Field(
        default=False,
        description=(
            'Authoritative full tree: after upsert/remove, archive synced '
            'departments absent from upsert (PRD §5 absent third-party IDs).'
        ),
    )
    #: WeCom ``department/list`` ids (flat). When set, absent reconcile uses
    #: this set instead of ``upsert`` external_ids so deletes are detected
    #: even if the tree DFS omitted nodes.
    snapshot_external_ids: Optional[List[str]] = Field(
        default=None,
        description='Authoritative flat WeCom department id list for absent reconcile.',
    )

    @field_validator('snapshot_external_ids', mode='before')
    @classmethod
    def _normalize_snapshot_external_ids(
        cls, v: Optional[List[Union[str, int]]],
    ) -> Optional[List[str]]:
        if v is None:
            return None
        out: List[str] = []
        for x in v:
            if x is None:
                continue
            s = str(x).strip()
            if s:
                out.append(s)
        return out


class GatewayWecomOrgSyncRequest(BaseModel):
    """Gateway 单次企微推送：部门批量 + 多成员 login-sync，对应一条 ``org_sync_log``。"""

    departments: DepartmentsSyncRequest
    members: List[LoginSyncRequest] = Field(default_factory=list)


class BatchResult(BaseModel):
    applied_upsert: int = 0
    applied_remove: int = 0
    skipped_ts_conflict: int = 0
    orphan_triggered: List[int] = Field(default_factory=list)
    errors: List[dict] = Field(default_factory=list)


class GatewayWecomOrgSyncResult(BaseModel):
    department_result: BatchResult
    member_sync_ok: int = 0
    member_sync_fail: int = 0
    member_errors: List[dict] = Field(default_factory=list)
    #: PRD: 本次导入名单外的 ``source=wecom`` 活跃用户被禁用并强退（不在名单中）
    absent_wecom_users_disabled: int = 0
