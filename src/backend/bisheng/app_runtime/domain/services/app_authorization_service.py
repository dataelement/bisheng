"""Validate application facts before delegating exact actions to F048."""

from bisheng.app_runtime.domain.schemas.app_authorization import (
    APP_ACTIONS,
    MANAGEMENT_ACTIONS,
    AppOperation,
    required_actions,
)
from bisheng.common.errcode.app_factory import AppNotFoundError
from bisheng.common.errcode.permission import InvalidCatalogActionError, PermissionDeniedError
from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_is_management_api
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.permission.application.business_authorization import (
    batch_check_business_actions,
    check_business_action,
)
from bisheng.permission.application.identity import (
    PermissionActor,
    get_current_permission_actor,
    reset_current_permission_actor,
    resolve_permission_actor,
    set_current_permission_actor,
)


class AppAuthorizationService:
    """Application policy owns validity; F048 alone owns permission decisions."""

    @staticmethod
    async def load_app(app_id: str):
        from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeDeliveryRepository

        return await RuntimeDeliveryRepository().get_application(app_id)

    @staticmethod
    async def resolve_actor(identity) -> PermissionActor:
        principal = get_current_open_api_principal()
        contextual_actor = get_current_permission_actor()
        if principal is not None:
            if contextual_actor is None or (
                contextual_actor.subject_type,
                contextual_actor.subject_id,
                contextual_actor.tenant_id,
            ) != (
                principal.authorization_subject_type,
                principal.authorization_subject_id,
                principal.tenant_id,
            ):
                raise PermissionDeniedError(reason="authenticated_actor_unavailable")
            return contextual_actor
        if isinstance(identity, PermissionActor):
            return identity
        if contextual_actor is not None and contextual_actor.subject_type != "user":
            raise PermissionDeniedError(reason="authenticated_actor_unavailable")
        return await resolve_permission_actor(identity)

    @staticmethod
    def validate_facts(app, actor: PermissionActor) -> None:
        scope = get_admin_scope_tenant_id() if get_is_management_api() else None
        tenant_id = scope if scope is not None else actor.tenant_id
        if (
            app is None
            or not getattr(app, "id", None)
            or getattr(app, "state", None) not in {"draft", "online", "pending_capacity", "stopped"}
            or int(getattr(app, "tenant_id", 0) or 0) != int(tenant_id)
            or int(getattr(app, "owner_user_id", 0) or 0) <= 0
            or (int(tenant_id) != actor.tenant_id and not actor.super_admin)
        ):
            raise AppNotFoundError()

    @classmethod
    async def authorize_app(cls, identity, app_id: str, operation: AppOperation | str, *, resume: bool = False):
        app = await cls.load_app(app_id)
        if app is not None and app.id != app_id:
            raise AppNotFoundError()
        return await cls.authorize_loaded_app(identity, app, operation, resume=resume)

    @classmethod
    async def authorize_loaded_app(cls, identity, app, operation: AppOperation | str, *, resume: bool = False):
        try:
            purpose = AppOperation(operation)
        except ValueError as exc:
            raise PermissionDeniedError(reason="unsupported_operation") from exc
        actor = await cls.resolve_actor(identity)
        cls.validate_facts(app, actor)
        if purpose is AppOperation.MANAGEMENT_READ:
            for action in APP_ACTIONS:
                if action not in MANAGEMENT_ACTIONS:
                    continue
                try:
                    allowed = await check_business_action(
                        identity, resource_type="app", resource_id=app.id, action=action, actor=actor
                    )
                except InvalidCatalogActionError:
                    # Disabled actions contribute no permission to this OR query.
                    continue
                if allowed:
                    return app
            raise PermissionDeniedError(
                reason="management_action_required", required_actions=sorted(MANAGEMENT_ACTIONS)
            )
        actions = required_actions(purpose, resume=resume)
        for action in actions:
            if not await check_business_action(
                identity, resource_type="app", resource_id=app.id, action=action, actor=actor
            ):
                raise PermissionDeniedError(reason="action_required", required_actions=list(actions))
        return app

    @classmethod
    async def management_actions(cls, identity, loaded_apps) -> dict[str, frozenset[str]]:
        actor = await cls.resolve_actor(identity)
        candidates = []
        for app in loaded_apps:
            try:
                cls.validate_facts(app, actor)
            except AppNotFoundError:
                continue
            candidates.append(app.id)
        if not candidates:
            return {}
        token = set_current_permission_actor(actor)
        try:
            actions = await batch_check_business_actions(
                identity, resource_type="app", resource_ids=candidates, actions=APP_ACTIONS
            )
        finally:
            reset_current_permission_actor(token)
        return {app_id: value for app_id, value in actions.items() if MANAGEMENT_ACTIONS.intersection(value)}
