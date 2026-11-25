"""Only a genuinely empty schema may acquire first-installation provenance."""

from sqlalchemy import inspect, select

from bisheng.tenant.domain.models.installation_bootstrap import InstallationBootstrap


class InstallationRepository:
    def claim(self, connection):
        table = InstallationBootstrap.__table__
        names = {name.casefold(): name for name in inspect(connection).get_table_names()}
        if table.name in names:
            state = connection.execute(select(table.c.state).where(table.c.id == 1)).scalar_one_or_none()
            if state is not None:
                if state not in {"pending", "completed"}:
                    raise RuntimeError("Unknown installation bootstrap state")
                return state
        # An empty Alembic table can survive an unsuccessful first launch.
        if names.keys() - {table.name, "alembic_version"}:
            return None
        if "alembic_version" in names:
            from sqlalchemy import MetaData, Table

            versions = Table(names["alembic_version"], MetaData(), autoload_with=connection)
            if connection.execute(select(versions).limit(1)).first() is not None:
                return None
        table.create(connection, checkfirst=True)
        connection.execute(table.insert().values(id=1, state="pending"))
        return "pending"

    async def alock(self, session):
        return (
            await session.exec(select(InstallationBootstrap).where(InstallationBootstrap.id == 1).with_for_update())
        ).scalar_one()

    async def ahas_tenant(self, session):
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.database.models.tenant import Tenant

        with bypass_tenant_filter():
            return (await session.exec(select(Tenant.id).limit(1))).first() is not None

    def create_schema(self, connection, metadata):
        from bisheng.core.database.alembic_helpers.online import create_missing_model_tables

        return create_missing_model_tables(connection, metadata)
