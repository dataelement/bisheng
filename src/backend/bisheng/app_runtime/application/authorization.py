"""Public application-action protocol; no ORM objects escape this boundary."""

from bisheng.app_runtime.domain.schemas.app_authorization import APP_ACTIONS, MANAGEMENT_ACTIONS, AppOperation
from bisheng.app_runtime.domain.services.app_authorization_service import AppAuthorizationService


async def authorize_app(identity, app_id: str, operation: AppOperation | str, *, resume: bool = False) -> None:
    await AppAuthorizationService.authorize_app(identity, app_id, operation, resume=resume)


async def management_actions(identity, loaded_apps) -> dict[str, frozenset[str]]:
    return await AppAuthorizationService.management_actions(identity, loaded_apps)


__all__ = ["APP_ACTIONS", "MANAGEMENT_ACTIONS", "AppOperation", "authorize_app", "management_actions"]


async def resolve_app_actor(identity):
    return await AppAuthorizationService.resolve_actor(identity)


async def editable_app_ids(identity, tenant_id):
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeDeliveryRepository

    apps = await RuntimeDeliveryRepository().list_applications()
    actions = await AppAuthorizationService.management_actions(
        identity, [app for app in apps if app.tenant_id == tenant_id]
    )
    return tuple(sorted(app_id for app_id, values in actions.items() if "edit" in values))


async def management_actions_for_ids(identity, app_ids):
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeDeliveryRepository

    if not app_ids:
        return {}
    rows = await RuntimeDeliveryRepository().list_applications(app_ids)
    return await AppAuthorizationService.management_actions(identity, rows)
