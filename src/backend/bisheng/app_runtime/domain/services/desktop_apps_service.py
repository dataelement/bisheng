"""Desktop identity adapter for the hosted-app catalog (v3.1.0-alpha1 F001: catalog only)."""

from dataclasses import dataclass

from bisheng.common.errcode.dsh import DshUserDisabledError
from bisheng.dsh.domain.services.access import principal_scope


async def current_global_super(user_id):
    # Reuse the same current FGA/RBAC facts as the normal hosted-app entry.
    from bisheng.utils.http_middleware import _check_is_global_super

    return await _check_is_global_super(user_id)


async def check_action(actor, **target):
    from bisheng.permission.application.business_authorization import check_business_action

    return await check_business_action(actor, **target)


@dataclass(frozen=True)
class DesktopActor:
    user_id: int
    tenant_id: int
    user_name: str
    is_global_super: bool = False


class DesktopAppsService:
    def __init__(self, runtime, repository):
        self.runtime, self.repository = runtime, repository

    async def actor(self, principal):
        with principal_scope(principal):
            await self.runtime.sessions.validate(principal)
            identity = await self.runtime.identity.check(principal.tenant_id, principal.user_id)
            if not identity.active or (identity.tenant_id, identity.user_id) != (
                principal.tenant_id,
                principal.user_id,
            ):
                raise DshUserDisabledError()
            return DesktopActor(
                int(principal.user_id),
                int(principal.tenant_id),
                identity.user.username,
                bool(await current_global_super(int(principal.user_id))),
            )

    async def page(self, principal, *, after=None):
        with principal_scope(principal):
            actor = await self.actor(principal)
            return await workbench_page(actor, self.repository, after=after)


async def workbench_page(actor, repository, *, after=None):
    """Desktop catalog: same tenant, online, visible to the actor (spec AC-22 / INV-2).

    ``use`` is the legacy alias of ``visible`` (``normalize_legacy_action``), the
    action the app square filters by. The square also lists stopped apps;
    Desktop lists online ones only. The id keyset and response shape are what
    BISHENG Desktop 1.3.0 validates — keep them (design 决策 3).
    """
    rows, cursor = await repository.page(after=after)
    items = []
    for app in rows:
        if int(app.tenant_id) != actor.tenant_id or app.state != "online":
            continue
        if await check_action(actor, resource_type="app", resource_id=app.id, action="use"):
            items.append(
                {
                    "id": app.id,
                    "name": app.name,
                    "slug": app.slug,
                    "description": app.description,
                    "state": app.state,
                    "version_id": app.current_version_id,
                    "entry_path": f"/apps/{app.slug}/",
                }
            )
    return {"items": items, "next_cursor": cursor}
