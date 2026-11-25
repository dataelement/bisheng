"""AC-02/10/11: metadata and installation need no reference tables at all."""

from unittest.mock import AsyncMock

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.application.metadata_owner import MetadataProcessingOwner
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.tenant.application.installation import initialize_installation


async def test_metadata_reads_real_configuration_without_models_or_reference_tables():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: Knowledge.__table__.create(conn))
    with tenant_execution_scope(101):
        async with AsyncSession(engine) as session, session.begin():
            session.add(
                Knowledge(
                    id=7,
                    tenant_id=101,
                    name="e2e-reference-space",
                    type=3,
                    model="999",
                    model_config_revision=3,
                    index_generation="generation",
                )
            )
        owner = MetadataProcessingOwner(model_owner=AsyncMock(side_effect=AssertionError("model reference admission")))
        async with AsyncSession(engine) as session, session.begin():
            result = await owner._amodel_configuration(session, 7, identity=object())
        assert result.model_config_revision == 3 and result.index_generation == "generation"
    await engine.dispose()


async def test_fresh_install_creates_default_tenant_without_coverage_or_run(tmp_path):
    path = tmp_path / "installation.db"
    sync = sa.create_engine(f"sqlite:///{path}")
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    metadata = sa.MetaData()
    Tenant.__table__.to_metadata(metadata)

    def sessions():
        return AsyncSession(engine, expire_on_commit=False)

    try:
        assert (await initialize_installation(engine=sync, metadata=metadata, sessions=sessions, apply=True))[
            "initialized"
        ]
        assert (await initialize_installation(engine=sync, metadata=metadata, sessions=sessions, apply=True))[
            "mode"
        ] == "already_initialized"
        with sync.connect() as connection:
            assert connection.execute(sa.select(Tenant.id)).scalar_one() == 1
            assert "knowledge_unification_run" not in sa.inspect(connection).get_table_names()
    finally:
        await engine.dispose()
        sync.dispose()
