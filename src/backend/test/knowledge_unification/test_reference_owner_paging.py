"""T651: bounded inbound reads use actual model Owner and source identities."""

from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.llm.application.reference_target_owner import ModelReferenceTargetOwner
from bisheng.resource_reference.application.contracts import TargetKey
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_model_reference_owner as models

model_owner_tenant = models.model_owner_tenant


@pytest.fixture
async def inbound():
    database = create_async_engine("sqlite+aiosqlite://")
    async with database.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(conn, tables=[*models.TABLES, BusinessReferenceSet.__table__])
        )
    async with AsyncSession(database, expire_on_commit=False) as session:
        await session.run_sync(models.setup)
        await session.commit()
        verifier = ReferenceTargetVerifier({"model": ModelReferenceTargetOwner()})
        repository = ReferenceRepository(verifier=verifier)
        await session.begin()
        receipts = await verifier.averify_owner_targets(session, (TargetKey("model", "11"),))
        scope = repository.target_owner_scope(session, receipts)
        yield session, repository, scope
    await database.dispose()


def seed(session, *, tenant=101, source_type="assistant", source_id="same", version="current", slots=1):
    source = BusinessReferenceSet(
        tenant_id=tenant,
        source_type=source_type,
        source_id=source_id,
        source_version=version,
        source_revision=3,
        extractor_version="test-v1",
        digest="a" * 64,
        ready=True,
        effective=True,
    )
    session.add(source)
    rows = [
        BusinessResourceReference(
            tenant_id=tenant,
            source_type=source_type,
            source_id=source_id,
            source_version=version,
            slot_key=f"model:{index}",
            target_type="model",
            target_id="11",
            target_tenant_id=101,
            source_revision=3,
        )
        for index in range(slots)
    ]
    session.add_all(rows)
    return source, rows


async def test_pages_cover_cross_tenant_full_source_keys_without_cartesian_or_truncation(inbound):
    session, repository, scope = inbound
    expected = []
    for tenant, kind, version in [
        (101, "assistant", "current"),
        (202, "assistant", "current"),
        (202, "workflow_version", "v1"),
        (202, "workflow_version", "v2"),
    ]:
        _, rows = seed(session, tenant=tenant, source_type=kind, version=version, slots=103)
        expected.extend(rows)
    await session.flush()
    observed, cursor = [], None
    while True:
        page = await repository.alist_inbound_for_owner_page(session, scope, after_id=cursor, limit=37)
        assert len(page) <= 37
        if not page:
            break
        observed.extend(page)
        cursor = page[-1].id
    assert [row.id for row in observed] == sorted(row.id for row in expected)
    assert len(observed) == 412
    assert len({(row.tenant_id, row.source_type, row.source_id, row.source_version) for row in observed}) == 4


@pytest.mark.parametrize("limit,after_id", [(0, None), (201, None), (True, None), (2, -1), (2, True)])
async def test_page_bounds_are_strict(inbound, limit, after_id):
    session, repository, scope = inbound
    with pytest.raises(ValueError):
        await repository.alist_inbound_for_owner_page(session, scope, limit=limit, after_id=after_id)


async def test_scope_cannot_be_forged_expanded_or_reused_after_commit(inbound):
    session, repository, scope = inbound
    for forged in [replace(scope), replace(scope, targets=(TargetKey("model", "33"),)), (TargetKey("model", "11"),)]:
        with pytest.raises(ResourceReferenceInvalidError):
            await repository.alist_inbound_for_owner_page(session, forged)
    await session.commit()
    await session.begin()
    with pytest.raises(ResourceReferenceInvalidError):
        await repository.alist_inbound_for_owner_page(session, scope)


@pytest.mark.parametrize("broken", ["missing", "not-ready", "revision", "inactive"])
async def test_incomplete_source_facts_never_silently_disappear(inbound, broken):
    session, repository, scope = inbound
    source, rows = seed(session)
    if broken == "missing":
        session.expunge(source)
    elif broken == "not-ready":
        source.ready = False
    elif broken == "revision":
        rows[0].source_revision = 2
    else:
        source.effective = False
    await session.flush()
    with pytest.raises(ReferenceCoverageNotReadyError):
        await repository.alist_inbound_for_owner_page(session, scope)


async def test_original_legacy_binding_is_returned_without_state_filtering(inbound):
    session, repository, scope = inbound
    _, rows = seed(session)
    rows[0].target_tenant_id = None
    rows[0].legacy_invalid_reason = "target_missing"
    rows[0].legacy_run_id, rows[0].legacy_evidence_key = "frozen-run", "frozen-evidence"
    await session.flush()
    page = await repository.alist_inbound_for_owner_page(session, scope)
    assert page == (rows[0],)
    assert page[0].legacy_invalid_reason == "target_missing"
