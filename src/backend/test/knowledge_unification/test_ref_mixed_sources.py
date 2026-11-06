"""T433: mixed defaults/knowledge roots share locks, never their source receipts.

覆盖 AC: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91, AC-92
SQLite checks transaction state; physical MySQL/DM8 lock scheduling is separate.
"""

from dataclasses import replace

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanConflictError,
    ReferenceCoverageNotReadyError,
    ResourceReferenceInvalidError,
)
from bisheng.resource_reference.application.contracts import SourceBindingChange, SourceKey, TargetKey
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_ref_batch as batch
from test.knowledge_unification import test_ref_repo as refs

tenant_events = refs.tenant_events
KEYS = (
    SourceKey(101, "model_default", "linsight_llm", "current"),
    SourceKey(101, "knowledge", "7", "current"),
)


class MixedOwner(batch.SqlOwner):
    async def aprelock_mixed_targets(self, session, keys, source_keys):
        await super().aprelock_targets(session, keys, source_keys)


@pytest.fixture
async def components():
    database = create_async_engine("sqlite+aiosqlite://")
    async with database.begin() as connection:
        await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=refs.TABLES))
        await connection.run_sync(batch.metadata.create_all)
    events = []
    owner = MixedOwner(events)
    verifier = ReferenceTargetVerifier({"model": owner})
    repo = ReferenceRepository(verifier=verifier)
    runtime = ReferenceBindingRuntime(repo, verifier)
    with refs.tenant(101):
        async with AsyncSession(database) as session:
            yield session, runtime, owner, events
    await database.dispose()


def changes(events, *, keys=KEYS, new_source=True):
    values = []
    for index, key in enumerate(keys):

        async def root(session, key=key):
            events.append(("root", key.source_type.value, key.source_id))

        values.append(SourceBindingChange(key, (batch.ref(index + 1),), "v1", root, new_source=new_source))
    return tuple(values)


async def test_global_union_precedes_sorted_roots_and_all_sets_rollback(components):
    session, runtime, _owner, events = components
    prepared = await runtime.aprepare_mixed_source_bindings(session, changes(events))
    assert tuple(item.source_key for item in prepared) == tuple(reversed(KEYS))
    assert events[0] == ("prelock", ("1", "2"), tuple(reversed(KEYS)))
    assert [event for event in events if event[0] == "root"] == [
        ("root", "knowledge", "7"),
        ("root", "model_default", "linsight_llm"),
    ]
    assert all(event[0] == "verify" for event in events[1:3])
    for item in prepared:
        await runtime.aapply_source_bindings(session, item)
    assert (await runtime.repository.aget_root_guard(session, KEYS[0])).source_revision == 1
    assert (await runtime.repository.aget_root_guard(session, KEYS[1])).source_revision == 1
    await session.rollback()
    assert await runtime.repository.aget_source_set(session, KEYS[0]) is None
    assert await runtime.repository.aget_source_set(session, KEYS[1]) is None


async def test_roots_keep_independent_cas_revisions_and_receipts(components):
    session, runtime, _owner, events = components
    for item in await runtime.aprepare_mixed_source_bindings(session, changes(events)):
        await runtime.aapply_source_bindings(session, item)
    await session.commit()

    async def lock(session):
        pass

    one = await runtime.aprepare_source_bindings(
        session, KEYS[0], (batch.ref(2),), extractor_version="v1", lock_source_root=lock
    )
    await runtime.aapply_source_bindings(session, one)
    await session.commit()
    prepared = await runtime.aprepare_mixed_source_bindings(session, changes(events, new_source=False))
    assert {item.source_key: item.new_revision for item in prepared} == {KEYS[0]: 3, KEYS[1]: 2}
    wrong = replace(prepared[0], source_key=KEYS[0])
    with pytest.raises(ResourceReferenceInvalidError):
        await runtime.aapply_source_bindings(session, wrong)


@pytest.mark.parametrize(
    "kind", ["foreign", "other_source", "other_target", "duplicate", "same_root", "restore_default"]
)
async def test_mixed_rejects_unsupported_identity_before_prelock(components, kind):
    session, runtime, _owner, events = components
    items = changes(events)
    if kind == "foreign":
        items = (replace(items[0], source_key=replace(KEYS[0], tenant_id=202)), items[1])
    elif kind == "other_source":
        items = (replace(items[0], source_key=replace(KEYS[0], source_type="assistant")), items[1])
    elif kind == "other_target":
        items = (replace(items[0], references=(replace(batch.ref(1), target=TargetKey("knowledge_space", "1")),)),)
    elif kind == "duplicate":
        items = (items[0], items[0])
    elif kind == "restore_default":
        items = (replace(items[0], references=(), effective=False), items[1])
    else:
        items = (items[0], replace(items[0], source_key=replace(KEYS[0], source_version="v2")))
    with pytest.raises(ResourceReferenceInvalidError):
        await runtime.aprepare_mixed_source_bindings(session, items)
    assert events == []


async def test_existing_missing_coverage_fails_before_owner_or_root(components):
    session, runtime, _owner, events = components
    with pytest.raises(ReferenceCoverageNotReadyError):
        await runtime.aprepare_mixed_source_bindings(session, changes(events, new_source=False))
    assert events == []


async def test_candidate_drift_on_second_root_rolls_back_whole_operation(components):
    session, runtime, _owner, events = components
    for item in await runtime.aprepare_mixed_source_bindings(session, changes(events)):
        await runtime.aapply_source_bindings(session, item)
    await session.commit()
    items = changes(events, new_source=False)

    async def drift(s):
        await s.execute(
            update(BusinessReferenceSet)
            .where(
                BusinessReferenceSet.source_type == "model_default",
                BusinessReferenceSet.source_version == "__root__",
            )
            .values(source_revision=2)
        )

    items = (replace(items[0], lock_source_root=drift), items[1])
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await runtime.aprepare_mixed_source_bindings(session, items)
    await session.rollback()
    assert (await runtime.repository.aget_root_guard(session, KEYS[0])).source_revision == 1


async def test_same_root_batch_contract_is_not_weakened(components):
    session, runtime, _owner, events = components
    await session.begin()
    with pytest.raises(ResourceReferenceInvalidError):
        await runtime.verifier.averify_batch_targets(session, tuple((key, ()) for key in KEYS))
    assert events == []


async def test_empty_model_union_still_enters_owner_auxiliary_lock_plan(components):
    session, runtime, _owner, events = components
    items = tuple(replace(item, references=()) for item in changes(events))
    await runtime.aprepare_mixed_source_bindings(session, items)
    assert events[0] == ("prelock", (), tuple(reversed(KEYS)))
    assert [event[0] for event in events] == ["prelock", "root", "root"]
