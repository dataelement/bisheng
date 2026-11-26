"""First-installation composition before the immutable historical revisions."""

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.tenant import Tenant
from bisheng.tenant.domain.repositories.installation_repository import InstallationRepository


async def initialize_installation(*, engine, metadata, sessions, apply):
    repository = InstallationRepository()
    # Preview never creates the provenance table, schema or default tenant.
    if not apply:
        return {"mode": "preview", "initialized": False}
    with engine.begin() as connection:
        state = repository.claim(connection)
    if state is None:
        return {"mode": "existing_database", "initialized": False}
    if state == "completed":
        return {"mode": "already_initialized", "initialized": True}
    # The committed pending marker makes partial MySQL/DM8 DDL resumable.
    # Schema creation is outside the tenant/certificate transaction (DDL commits).
    with engine.begin() as connection:
        repository.create_schema(connection, metadata)
    with tenant_execution_scope(1):
        async with sessions() as session, session.begin():
            marker = await repository.alock(session)
            if marker.state == "completed":
                return {"mode": "already_initialized", "initialized": True}
            if await repository.ahas_tenant(session):
                raise RuntimeError("Pending first installation already has a tenant; explicit recovery required")
            tenant = Tenant(id=1, tenant_code="default", tenant_name="Default Tenant", status="active")
            session.add(tenant)
            await session.flush()
            marker.state = "completed"
    return {"mode": "initialized", "initialized": True}
