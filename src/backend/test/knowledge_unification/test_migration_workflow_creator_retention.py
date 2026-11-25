"""Old workflow authors are audit identities, never newly assigned owners."""

from dataclasses import asdict

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_coverage import production_coverage_factory
from bisheng.knowledge.application.unification_sources import RootInventoryRecord, _digest
from bisheng.knowledge.application.unification_structural_retention import (
    validate_native_retentions,
    workflow_creator_retention,
)
from bisheng.knowledge.domain.repositories.unification_control_repository import UnificationControlRepository
from bisheng.knowledge.domain.repositories.unification_inventory_repository import (
    Flow,
    FlowVersion,
    UnificationInventoryRepository,
)
from bisheng.knowledge.domain.repositories.unification_resource_repository import UnificationResourceRepository
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.resource_reference.application.contracts import SourceRootKey, SourceType
from bisheng.user.domain.models.user import User
from test.knowledge_unification import test_migration_structural_retention as original
from test.knowledge_unification.test_migration_source_inventory import graph

resource_native, native, complete = original.resource_native, original.native, original.complete
raw_resource_native = original.raw_resource_native
transport, module, published_input = original.transport, original.module, original.published_input
no_real_network = original.reference_tests.no_real_network
ROOT = "workflow-retained-author"


async def missing_author(database):
    await database.insert(
        Flow,
        [
            {
                "id": ROOT,
                "tenant_id": 101,
                "name": ROOT,
                "user_id": 999,
                "flow_type": 10,
                "is_delete": 0,
                "data": graph(11, 9000),
            }
        ],
    )
    await database.insert(
        FlowVersion,
        [
            {
                "id": 71,
                "tenant_id": 101,
                "flow_id": ROOT,
                "flow_type": 10,
                "name": "saved",
                "data": graph(11, 9000),
                "is_current": 1,
                "is_delete": 0,
            }
        ],
    )


@pytest.mark.parametrize("published_input", [{"reference_seed": missing_author}], indirect=True)
async def test_full_migration_and_completed_resume_preserve_workflow_without_new_account_or_rights(published_input):
    value = published_input
    result = await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)
    assert (
        result.complete
        and await original.reference_tests.app(value).arun_references(**value.input, operator_id=7) == result
    )
    assert not any(obj == f"workflow:{ROOT}" for _, _, obj in value.store.tuples)
    async with value.sessions() as session, session.begin():
        assert (await session.get(Flow, ROOT)).user_id == 999
        assert (await session.get(FlowVersion, 71)).data == graph(11, 9000)
        assert await session.get(User, 999) is None
        assert (await production_coverage_factory(session).arequire_global_ready()).verified_tenant_ids


@pytest.mark.parametrize("published_input", [{"reference_seed": missing_author}], indirect=True)
@pytest.mark.parametrize("drift", ["account", "root", "versions"])
async def test_frozen_author_and_root_or_version_drift_refuse_conversion(published_input, drift):
    value = published_input
    if drift == "account":
        await value.database.insert(User, [{"user_id": 999, "user_name": "reappeared", "password": "test"}])
    elif drift == "root":
        async with value.database.engine.begin() as connection:
            await connection.execute(sa.update(Flow).where(Flow.id == ROOT).values(data={"nodes": [], "changed": True}))
    else:
        await value.database.insert(
            FlowVersion,
            [
                {
                    "id": 72,
                    "tenant_id": 101,
                    "flow_id": ROOT,
                    "flow_type": 10,
                    "name": "new version",
                    "data": graph(11, 9000),
                    "is_current": 0,
                    "is_delete": 0,
                }
            ],
        )
    with pytest.raises(BaseErrorCode):
        await original.reference_tests.app(value).arun_references(**value.input, operator_id=7)


@pytest.mark.parametrize("count", [200, 400])
async def test_root_author_and_version_revalidation_is_bounded(complete, count):
    ids = tuple(f"retained-author-{i:04}" for i in range(count))
    await complete.insert(
        Flow,
        [
            {
                "id": ident,
                "tenant_id": 101,
                "name": ident,
                "user_id": 999,
                "flow_type": 10,
                "is_delete": 0,
                "data": {"nodes": []},
            }
            for ident in ids
        ],
    )
    repository = UnificationInventoryRepository()
    with tenant_execution_scope(101):
        proofs = []
        async with AsyncSession(complete.engine) as session, session.begin():
            for offset in range(0, count, 200):
                rows = await repository.aload_workflow_roots(session, root_ids=ids[offset : offset + 200])
                for row in rows:
                    checksum = _digest(asdict(row))
                    root = RootInventoryRecord(
                        SourceRootKey(101, SourceType.WORKFLOW_VERSION, row.id),
                        999,
                        (row.flow_type, row.status, row.is_delete),
                        checksum,
                        0,
                        checksum,
                    )
                    proofs.append(
                        workflow_creator_retention(root, {"user_id": 999, "exists": False, "delete": None}).data
                    )
        complete.queries.clear()
        async with AsyncSession(complete.engine) as session, session.begin():
            await validate_native_retentions(
                session,
                tuple(proofs),
                resources=UnificationResourceRepository(),
                controls=UnificationControlRepository(),
                permissions=PermissionMigrationSnapshotRepository(),
            )
        assert len(complete.queries) == count // 200 * 3
