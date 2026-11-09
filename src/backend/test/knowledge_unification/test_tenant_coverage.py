"""Fresh Root is certified only in its actual INSERT; old Root never inferred empty."""

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.init_data import _init_default_tenant
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.tenant import Tenant
from bisheng.knowledge.application.unification_coverage import bootstrap_created_root, production_coverage_factory
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun as Run
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from test.knowledge_unification.test_migration_inventory_repository import storage as storage
from test.knowledge_unification.test_migration_references_application import no_real_network as no_real_network


@pytest.fixture
async def empty_install(storage):
    async with storage.begin() as connection:
        for model in (Run, BusinessReferenceSet, BusinessResourceReference, ResourceReferenceTombstone):
            await connection.run_sync(lambda conn, model=model: model.__table__.create(conn, checkfirst=True))
    return storage


async def test_actual_original_new_root_creation_signs_same_tx_empty_proof(empty_install):
    with tenant_execution_scope(1):
        async with AsyncSession(empty_install, expire_on_commit=False) as session:
            await _init_default_tenant(session, reference_bootstrap=bootstrap_created_root)
        async with AsyncSession(empty_install) as session, session.begin():
            rows = (await session.execute(sa.select(Run.__table__))).mappings().all()
            assert len(rows) == 1 and rows[0]["origin"] == "empty_tenant"
            assert rows[0]["coverage_epoch"] == 1 and rows[0]["phase"] == "completed"
            assert len(await production_coverage_factory(session).arequire_ready()) == 6
            assert (await production_coverage_factory(session).arequire_global_ready()).verified_tenant_ids == (1,)


async def test_existing_zero_business_root_never_receives_a_new_certificate(empty_install):
    with tenant_execution_scope(1):
        async with AsyncSession(empty_install) as session, session.begin():
            session.add(Tenant(id=1, tenant_code="existing", tenant_name="Existing"))
        async with AsyncSession(empty_install) as session:
            await _init_default_tenant(session, reference_bootstrap=bootstrap_created_root)
        async with AsyncSession(empty_install) as session, session.begin():
            assert not (await session.execute(sa.select(Run.id))).all()


async def test_legacy_before_tenant_with_business_keeps_original_root_and_not_ready(empty_install):
    from bisheng.knowledge.domain.models.knowledge import Knowledge

    with tenant_execution_scope(1):
        async with AsyncSession(empty_install) as session, session.begin():
            session.add(Knowledge(id=99, tenant_id=1, user_id=7, name="Old data", type=0))
        async with AsyncSession(empty_install) as session:
            await _init_default_tenant(session, reference_bootstrap=bootstrap_created_root)
        async with AsyncSession(empty_install) as session, session.begin():
            assert (await session.execute(sa.select(Tenant.id))).scalar_one() == 1
            assert not (await session.execute(sa.select(Run.id))).all()


async def test_root_and_certificate_both_rollback_when_callback_fails(empty_install):
    async def fail(session, tenant):
        await bootstrap_created_root(session, tenant)
        raise OSError("native failure before original creation commit")

    with tenant_execution_scope(1):
        async with AsyncSession(empty_install) as session:
            with pytest.raises(OSError):
                await _init_default_tenant(session, reference_bootstrap=fail)
        async with AsyncSession(empty_install) as session, session.begin():
            assert not (await session.execute(sa.select(Tenant.id))).all()
            assert not (await session.execute(sa.select(Run.id))).all()
