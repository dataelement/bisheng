"""Credential-generation check shared by admission and queued execution guards."""

from sqlmodel import select

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCredentialBinding, RuntimeRoute
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session, get_sync_db_session


def statements(app_id, credential_id):
    return (
        select(RuntimeRoute).where(RuntimeRoute.route_key == f"app:{app_id}"),
        select(RuntimeCredentialBinding).where(
            RuntimeCredentialBinding.app_id == app_id, RuntimeCredentialBinding.credential_id == credential_id
        ),
    )


def allowed(route, binding):
    # Existing v1 subjects retain their semantics until a v2 route is installed.
    if route is None:
        return binding is None
    return bool(
        binding
        and binding.state == "active"
        and route.status == "serving"
        and binding.operation_id == route.operation_id
        and binding.version_id == route.version_id
    )


async def is_serving_credential(app_id, credential_id):
    if settings.app_runtime.runtime_protocol_version != 2:
        return True
    route_query, binding_query = statements(app_id, credential_id)
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            return allowed((await session.exec(route_query)).first(), (await session.exec(binding_query)).first())


def is_serving_credential_sync(app_id, credential_id):
    if settings.app_runtime.runtime_protocol_version != 2:
        return True
    route_query, binding_query = statements(app_id, credential_id)
    with bypass_tenant_filter(), get_sync_db_session() as session:
        return allowed(session.exec(route_query).first(), session.exec(binding_query).first())


async def stage_binding(session, binding):
    """Add a candidate in the explicit operation transaction without committing."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import check_scope

    check_scope(binding)
    session.add(binding)
    await session.flush()
