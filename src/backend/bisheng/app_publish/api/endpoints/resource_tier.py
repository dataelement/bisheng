"""``/api/v1/resource-tiers`` — the system page's "resource tiers" tab (AC-45 / T065).

Session-authenticated and **platform super-admin only**. Two endpoints, and
what is absent is the design as much as what is present:

* **No ``DELETE``.** ``app_version.tier_id`` is a frozen reference; a deleted
  tier would leave an old version unable to resolve its spec when it is
  re-enabled (AC-47). Retirement is ``PATCH {enabled: false}`` — new publishes
  can no longer choose the tier, running apps keep running and their specs
  keep resolving. Neither the DAO nor the service offers deletion, and
  ``test_resource_tier_api.py`` pins the route table so nobody adds one here.
* **No ``POST``.** The three tiers are seeded from F054's ``DEFAULT_TIERS``
  (AC-44); the product explicitly rules out custom specs, so there is nothing
  to create.
* **Not under ``/apps``.** ``bisheng/api/router.py`` mounts F054's router
  before this one, and F054 owns ``GET /apps/{app_id}`` — a ``GET
  /apps/resource-tiers`` would be swallowed by that route and answer 16101.

Refusals ride inside the 200 envelope (16260 for a non-super-admin, 16207 when
the runtime layer is off), because the platform's response interceptor turns a
real 403 on a GET into a full-page navigation to ``/403`` (design 坑 22).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from bisheng.app_publish.api.endpoints.deploy import require_app_runtime_enabled
from bisheng.app_publish.domain.services.resource_tier_service import ResourceTierService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_publish import AppTierAdminForbiddenError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200

router = APIRouter(prefix="/resource-tiers", tags=["HostedAppResourceTier"])


async def require_platform_super_admin(user: UserPayload = Depends(UserPayload.get_login_user)) -> UserPayload:
    """16260 — tier management is not a tenant-admin surface (AC-45).

    Tiers are platform-level and shared across tenants (no ``tenant_id``
    column), so a Child Admin retuning one would be changing every other
    tenant's limits. ``is_global_super`` is resolved at login from the FGA
    tuple with the RBAC ``AdminRole`` fallback; the role check next to it is
    the same fallback for payloads built without the login path (tests,
    legacy call sites).
    """
    if user.is_global_super or user.is_admin():
        return user
    raise AppTierAdminForbiddenError(
        msg="仅平台超级管理员可以管理资源档位",
        details={"reason": "super_admin_only"},
    )


class ResourceTierPatch(BaseModel):
    """Inline-edit body. Every field optional; only the ones sent are applied.

    ``code`` is not a field on purpose (renaming would dangle frozen
    ``app_version.tier_id`` references) and neither is ``sort_order`` (the tab
    does not expose it). Range and blank checks live in the service so the
    failure is a 16262 naming the field, not a 422 the tab cannot localise.
    """

    name: str | None = Field(default=None, description="Display name")
    cpu_millicores: int | None = Field(default=None, description="CPU limit in millicores (positive integer)")
    memory_mb: int | None = Field(default=None, description="Memory limit in MB (positive integer)")
    description: str | None = Field(default=None, description="Plain-language guidance shown to publishers")
    enabled: bool | None = Field(default=None, description="False retires the tier for NEW publishes only")


@router.get(
    "",
    response_model=UnifiedResponseModel[list],
    summary="Resource tiers with their in-use application counts",
)
async def list_resource_tiers(
    _user: UserPayload = Depends(require_platform_super_admin),
    _enabled: None = Depends(require_app_runtime_enabled),
):
    """AC-45 — the admin list: name / CPU / memory / guidance / enabled / ``in_use_app_count``.

    Retired tiers are included; ``in_use_app_count`` is ``COUNT(DISTINCT
    app_id)`` over versions whose ``terminal_state`` is ``online`` — a rejected
    or withdrawn submission never became somebody's running app.
    """
    return resp_200(data=await ResourceTierService.list_tiers_for_admin())


@router.patch(
    "/{tier_code}",
    response_model=UnifiedResponseModel[dict],
    summary="Retune, describe, disable or re-enable one resource tier",
)
async def update_resource_tier(
    tier_code: str,
    body: ResourceTierPatch,
    user: UserPayload = Depends(require_platform_super_admin),
    _enabled: None = Depends(require_app_runtime_enabled),
):
    """AC-45 / AC-47 — inline edit; ``enabled=false`` blocks new selections only.

    Running applications keep their limits until their next publish or
    re-online (F054 AC-64): limits are fixed when the container is created and
    nothing here touches a running instance. Every effective change is audited
    as ``app.tier_update``.
    """
    patch = body.model_dump(exclude_unset=True)
    return resp_200(data=await ResourceTierService.retune_tier(tier_code, actor=user, **patch))
