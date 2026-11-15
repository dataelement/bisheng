"""Real Plan/provider/permission SQL; only Redis and FGA transport are isolated."""

from contextlib import asynccontextmanager
from math import ceil

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import management_tenant_scope
from bisheng.llm.application.model_provider_projection import ModelProjectionBinding, ModelProviderProjectionScope
from bisheng.llm.domain.repositories.model_deletion_repository import _revision
from bisheng.llm.domain.repositories.model_provider_operation_repository import ModelProviderOperationRepository
from bisheng.permission.application.model_sharing_projection import ModelSharingProjectionApplication
from bisheng.permission.domain.models import PermissionProjectionOperation, PermissionProjectionTuple
from bisheng.permission.domain.services.projection_service import ProjectionScopeDeferred
from test.knowledge_unification import test_model_delete_plan_application as actual
from test.knowledge_unification.test_model_share_projection_deferred import Marker

model_owner_tenant = actual.model_owner_tenant
removal_session = actual.removal_session
impact = actual.impact
ready = actual.ready


class Client:
    store_id, model_id = "native-store", "native-model"

    def __init__(self, subjects, active):
        self.rows = {(f"tenant:{value}", "shared_with", "llm_server:2") for value in subjects}
        self.active, self.writes, self.reads, self.unknown = active, [], 0, False

    def validate_business_mutation_size(self, size):
        assert 0 < size <= 90

    async def iter_tuples(self, **kwargs):
        assert self.active[0] == 0 and kwargs["consistency"] == "HIGHER_CONSISTENCY"
        for user, relation, resource in sorted(self.rows):
            yield {"user": user, "relation": relation, "object": resource}

    async def read_tuples(self, **kwargs):
        assert self.active[0] == 0 and kwargs["consistency"] == "HIGHER_CONSISTENCY"
        self.reads += 1
        key = kwargs["user"], kwargs["relation"], kwargs["object"]
        return [{"user": key[0], "relation": key[1], "object": key[2]}] if key in self.rows else []

    async def write_tuples(self, *, writes, deletes):
        assert self.active[0] == 0
        self.writes.append((tuple(writes), tuple(deletes)))
        assert len(writes) + len(deletes) <= 50
        self.rows.update((row["user"], row["relation"], row["object"]) for row in writes)
        self.rows.difference_update((row["user"], row["relation"], row["object"]) for row in deletes)
        if self.unknown:
            self.unknown = False
            raise ConnectionError("commit acknowledgement lost after the actual transport write")


@pytest.fixture
async def sharing_database(ready):
    session, references, plans = ready
    await session.commit()
    metadata = sa.MetaData()
    for model in (PermissionProjectionOperation, PermissionProjectionTuple):
        model.__table__.to_metadata(metadata).c.id.type = sa.Integer()
    async with session.bind.begin() as connection:
        await connection.run_sync(metadata.create_all)
    active = [0]

    @asynccontextmanager
    async def factory():
        active[0] += 1
        try:
            async with AsyncSession(session.bind, expire_on_commit=False) as current:
                yield current
        finally:
            active[0] -= 1

    return factory, references, plans, active


def frame():
    return {
        "version": 1,
        "purpose": "model_share_server",
        "parent_confirmation_id": None,
        "force": False,
        "sharing": None,
        "reserved_target_revisions": {},
        "ack": None,
    }


async def reserved(factory, references, plans, identity):
    repo = ModelProviderOperationRepository(plans)
    async with factory() as session:
        async with session.begin():
            owner = await repo.alock_provider(session, server_id=2)
            capture = actual.application(references, plans)
            from bisheng.llm.application.model_delete_plan import _Scope

            _, actor, reference = await capture._capture(_Scope(session), identity)
            row = await repo.acreate_share_reservation(
                session,
                server_id=2,
                actor_reference=reference,
                server_revision=_revision(owner),
                command_digest="b" * 64,
                metadata=frame(),
            )
    return repo, row, actor


@pytest.mark.parametrize("count", [0, 50, 51, 90, 401, 10001])
async def test_real_large_sharing_journals_bind_once_and_keep_provider_busy_until_business_finalize(
    sharing_database, count
):
    factory, references, plans, active = sharing_database
    with management_tenant_scope(1), actual.native.actor(super_admin=True) as identity:
        actual.web(identity)
        repo, row, actor = await reserved(factory, references, plans, identity)
        client = Client(range(100, 100 + count), active)
        scope = ModelProviderProjectionScope(session_factory=factory, repository=repo)
        from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository

        journals = ProjectionRepository(factory)
        app = ModelSharingProjectionApplication(client=client, marker=Marker(), scope=scope, repository=journals)
        before = await app.aread(server_id=2)
        prepared = await app.aprepare(
            before=before, after=(), confirmation_id=row.id, actor=actor, tenant_id=1, operation=row.operation
        )
        assert len(prepared.batches) == ceil(count / 50)
        if prepared.batches:
            with pytest.raises(ProjectionScopeDeferred):
                await app.service.reconcile_operation(prepared.batches[0].operation_id)
            assert (await journals.aget_operation(prepared.batches[0].operation_id)).status == "PREPARED"
        async with factory() as session:
            async with session.begin():
                await repo.alock_provider(session, server_id=2)
                current = await repo.aread_plan(session, confirmation_id=row.id, lock=True)
                metadata = frame()
                metadata["sharing"] = prepared.metadata()
                await repo.abind(session, current, server_id=2, metadata=metadata)
                binding = ModelProjectionBinding.from_plan(current, repo)
        scope = ModelProviderProjectionScope(session_factory=factory, repository=repo, binding=binding)
        app = ModelSharingProjectionApplication(client=client, marker=Marker(), scope=scope, repository=journals)
        restored = await app.arestore(
            metadata["sharing"],
            confirmation_id=row.id,
            tenant_id=1,
            operation=row.operation,
            operator_id=actor.subject_id,
        )
        await app.aexecute(restored)
        assert len(client.writes) == ceil(count / 50) and client.reads == count and not client.rows
        async with factory() as session:
            async with session.begin():
                current = await repo.aread_plan(session, confirmation_id=row.id)
                assert current.model_execution_state == "RESERVED"  # projection finalize never clears its fence
                await app.arequire_finalized(session, restored)
                await repo.alock_provider(session, server_id=2)
                await repo.aset_state(session, row=current, expected="RESERVED", target="COMPLETED")
        await app.aexecute(restored)
        assert len(client.writes) == ceil(count / 50)
