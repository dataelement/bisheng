"""Exercise first-install provenance, real certification and crash recovery."""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.tenant.application.installation import initialize_installation
from bisheng.tenant.domain.models.installation_bootstrap import InstallationBootstrap
from test.knowledge_unification.test_migration_inventory_repository import TABLES
from test.knowledge_unification.test_migration_inventory_repository import storage as storage


@pytest.fixture
async def installation(tmp_path, storage):
    path = tmp_path / "installation.db"
    engine = sa.create_engine(f"sqlite:///{path}")
    asynchronous = create_async_engine(f"sqlite+aiosqlite:///{path}")
    models = (
        *TABLES,
        Run,
        BusinessReferenceSet,
        BusinessResourceReference,
        ResourceReferenceTombstone,
        InstallationBootstrap,
    )
    metadata = sa.MetaData()
    for model in models:
        model.__table__.to_metadata(metadata)
    try:
        yield engine, metadata, lambda: AsyncSession(asynchronous, expire_on_commit=False)
    finally:
        await asynchronous.dispose()
        engine.dispose()


async def test_fresh_install_and_api_tenant_startup_are_idempotent(installation):
    engine, metadata, sessions = installation
    assert await initialize_installation(engine=engine, metadata=metadata, sessions=sessions, apply=False) == {
        "mode": "preview",
        "initialized": False,
    }
    assert not sa.inspect(engine).get_table_names()
    assert (await initialize_installation(engine=engine, metadata=metadata, sessions=sessions, apply=True))[
        "initialized"
    ]
    # Root already exists before migrations and API startup consume it.
    with engine.begin() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(Tenant.__table__)).scalar_one() == 1
    from bisheng.common.init_data import _init_default_tenant
    from bisheng.knowledge.application.unification_coverage import bootstrap_created_root

    with tenant_execution_scope(1):
        async with sessions() as session:
            await _init_default_tenant(session, reference_bootstrap=bootstrap_created_root)
        async with sessions() as session, session.begin():
            assert not (await session.execute(sa.select(Run.id))).all()
    assert (await initialize_installation(engine=engine, metadata=metadata, sessions=sessions, apply=True))[
        "mode"
    ] == "already_initialized"


async def test_existing_database_never_gets_empty_provenance(installation):
    engine, metadata, sessions = installation
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(Tenant.__table__.insert().values(id=1, tenant_code="old", tenant_name="Old"))
    assert (await initialize_installation(engine=engine, metadata=metadata, sessions=sessions, apply=True))[
        "mode"
    ] == "existing_database"
    with engine.connect() as connection:
        assert connection.execute(sa.select(InstallationBootstrap.__table__)).first() is None
        assert connection.execute(sa.select(Run.__table__)).first() is None


async def test_interrupted_root_creation_retries_atomically_without_reference_certificate(installation, monkeypatch):
    engine, metadata, sessions = installation
    original = AsyncSession.flush

    async def fail(session, *args, **kwargs):
        creating = any(isinstance(row, Tenant) for row in session.new)
        await original(session, *args, **kwargs)
        if creating:
            raise OSError("interrupted before commit")

    monkeypatch.setattr(AsyncSession, "flush", fail)
    with pytest.raises(OSError, match="interrupted"):
        await initialize_installation(engine=engine, metadata=metadata, sessions=sessions, apply=True)
    with engine.connect() as connection:
        assert connection.execute(sa.select(InstallationBootstrap.__table__.c.state)).scalar_one() == "pending"
        assert connection.execute(sa.select(Tenant.__table__)).first() is None
        assert connection.execute(sa.select(Run.__table__)).first() is None
    monkeypatch.setattr(AsyncSession, "flush", original)
    assert (await initialize_installation(engine=engine, metadata=metadata, sessions=sessions, apply=True))[
        "initialized"
    ]


async def test_pending_schema_resumes_without_rewriting_existing_business_or_certifying_coverage(installation):
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.tenant.domain.repositories.installation_repository import InstallationRepository

    engine, metadata, sessions = installation
    with engine.begin() as connection:
        assert InstallationRepository().claim(connection) == "pending"
        metadata.create_all(connection)
        connection.execute(Knowledge.__table__.insert().values(id=7, tenant_id=1, name="Retained", user_id=1))
    assert (await initialize_installation(engine=engine, metadata=metadata, sessions=sessions, apply=True))[
        "initialized"
    ]
    with engine.connect() as connection:
        assert connection.execute(sa.select(Tenant.__table__.c.id)).scalar_one() == 1
        assert connection.execute(sa.select(Knowledge.__table__.c.name)).scalar_one() == "Retained"
        assert connection.execute(sa.select(Run.__table__)).first() is None
        assert connection.execute(sa.select(InstallationBootstrap.__table__.c.state)).scalar_one() == "completed"


async def test_versioned_database_is_not_claimed_even_without_business_tables(installation):
    engine, metadata, sessions = installation
    versions = sa.Table("alembic_version", sa.MetaData(), sa.Column("version_num", sa.String(64)))
    with engine.begin() as connection:
        versions.create(connection)
        connection.execute(versions.insert().values(version_num="previous-release"))
    assert (await initialize_installation(engine=engine, metadata=metadata, sessions=sessions, apply=True))[
        "mode"
    ] == "existing_database"
    assert sa.inspect(engine).get_table_names() == ["alembic_version"]


async def test_pending_claim_resumes_after_only_some_tables_were_created(installation):
    from bisheng.tenant.domain.repositories.installation_repository import InstallationRepository

    engine, metadata, sessions = installation
    with engine.begin() as connection:
        assert InstallationRepository().claim(connection) == "pending"
        Tenant.__table__.create(connection)
    assert (await initialize_installation(engine=engine, metadata=metadata, sessions=sessions, apply=True))[
        "initialized"
    ]
    with tenant_execution_scope(1):
        async with sessions() as session, session.begin():
            assert await session.get(Tenant, 1) is not None
            assert not (await session.execute(sa.select(Run.id))).all()
