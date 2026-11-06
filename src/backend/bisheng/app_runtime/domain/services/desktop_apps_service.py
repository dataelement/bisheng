"""Desktop identity adapters for hosted app access and development."""

from dataclasses import dataclass

from bisheng.common.errcode.app_factory import AppManageForbiddenError, AppNotFoundError
from bisheng.common.errcode.dsh import DshUserDisabledError
from bisheng.dsh.domain.services.access import principal_scope


async def current_global_super(user_id):
    # Reuse the same current FGA/RBAC facts as the normal hosted-app entry.
    from bisheng.utils.http_middleware import _check_is_global_super

    return await _check_is_global_super(user_id)


async def require_action(actor, **target):
    from bisheng.permission.application.business_authorization import require_business_action

    await require_business_action(actor, **target)


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
    def __init__(self, runtime, repository, sessions):
        self.runtime, self.repository, self.sessions = runtime, repository, sessions

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

    async def require(self, principal, app_id, *actions):
        with principal_scope(principal):
            actor = await self.actor(principal)
            app = await self.repository.get(app_id)
            if app is None or app.state == "deleted" or int(app.tenant_id) != actor.tenant_id:
                raise AppNotFoundError()
            for action in actions:
                await require_action(actor, resource_type="app", resource_id=app.id, action=action)
            return actor, app

    async def page(self, principal, *, after=None, managed=False):
        with principal_scope(principal):
            actor = await self.actor(principal)
            return await hosted_app_page(actor, self.repository, after=after, managed=managed)

    async def launch(self, principal, app_id):
        _actor, app = await self.require(principal, app_id, "use")
        if app.state != "online":
            raise AppManageForbiddenError()
        ticket = await self.sessions.issue(principal, app_id=app.id, slug=app.slug)
        return {
            "app_id": app.id,
            "slug": app.slug,
            "entry_path": f"/apps/{app.slug}/",
            "launch_path": f"/apps/{app.slug}/_desktop",
            "ticket": ticket,
            "expires_in": 60,
        }


async def hosted_app_page(actor, repository, *, after=None, managed=False):
    """One tenant- and action-scoped catalog for Desktop and browser app entrances."""
    rows, cursor = await repository.page(after=after)
    items = []
    for app in rows:
        if int(app.tenant_id) != actor.tenant_id or app.state == "deleted":
            continue
        if not managed and app.state != "online":
            continue
        action = "edit" if managed else "use"
        if await check_action(actor, resource_type="app", resource_id=app.id, action=action):
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
