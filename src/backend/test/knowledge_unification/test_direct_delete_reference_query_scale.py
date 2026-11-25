"""T969: native full collector budgets include D1, real Owner and receipt CPU."""

from math import ceil

import pytest
import sqlalchemy as sa

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet as SourceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference as Binding
from test.knowledge_unification.test_direct_delete_reference_query import (
    api,
    selections,
)
from test.knowledge_unification.test_direct_delete_reference_query import (
    context as context,
)
from test.knowledge_unification.test_direct_delete_reference_query import (
    db as db,
)
from test.knowledge_unification.test_direct_delete_reference_query import (
    deletion_tenant as deletion_tenant,
)


@pytest.mark.parametrize("count,sparse", [(401, False), (1001, False), (10001, False), (10001, True)])
async def test_real_scope_owner_stream_and_complete_receipt_validation_have_separate_budgets(
    context, monkeypatch, count, sparse
):
    ctx = context
    ids = (50, *range(1000, 1000 + count - 1))
    selected = (ids[0], ids[count // 2], ids[-1]) if sparse else ids
    async with ctx.db.sessions() as session:
        await session.execute(
            sa.insert(File.__table__),
            [
                {
                    "id": ident,
                    "tenant_id": 101,
                    "knowledge_id": 1,
                    "user_id": 7,
                    "file_name": str(ident),
                    "file_type": 1,
                    "file_level_path": "/50",
                    "level": 1,
                    "status": 2,
                }
                for ident in ids[1:]
            ],
        )
        await session.execute(
            sa.insert(SourceSet.__table__).values(
                tenant_id=101,
                source_type="assistant",
                source_id="bulk-private",
                source_version="current",
                source_revision=3,
                extractor_version="native",
                digest="a" * 64,
                ready=True,
                effective=True,
            )
        )
        await session.execute(
            sa.insert(Binding.__table__),
            [
                {
                    "tenant_id": 101,
                    "source_type": "assistant",
                    "source_id": "bulk-private",
                    "source_version": "current",
                    "source_revision": 3,
                    "slot_key": f"{ident}-{slot}",
                    "target_type": "knowledge_file",
                    "target_id": str(ident),
                    "target_tenant_id": 101,
                    "target_space_id": "1",
                }
                for ident in selected
                for slot in range(3)
            ],
        )
        await session.commit()
    ctx.db.statements.clear()
    async with ctx.db.sessions() as session, session.begin():
        baseline = await ctx.scope.aread_delete_scope(session, space_id=1, selections=selections(("folder", 50)))
        assert len(baseline.resources) == count
    owner_sql, validation = [], []
    verify, validate = ctx.runtime.verifier.averify_owner_targets, ctx.runtime.verifier.validate_owner_receipts

    async def measured(session, targets):
        assert len(targets) == count
        before = len(ctx.db.statements)
        result = await verify(session, targets)
        owner_sql.extend(ctx.db.statements[before:])
        return result

    def validated(session, receipts):
        validation.append(len(receipts))
        return validate(session, receipts)

    monkeypatch.setattr(ctx.runtime.verifier, "averify_owner_targets", measured)
    monkeypatch.setattr(ctx.runtime.verifier, "validate_owner_receipts", validated)
    ctx.db.statements.clear()
    collector = api().DirectDeleteReferenceQuery(
        runtime=ctx.runtime, coverage_factory=ctx.factory, scope_repository=ctx.scope
    )
    async with ctx.db.sessions() as session, session.begin():
        result = await collector.acollect(session, space_id=1, selections=selections(("folder", 50)))
    hints = [(sql, params) for sql, params in ctx.db.statements if "FROM business_resource_reference" in sql]
    references = len(selected) * 3
    assert not owner_sql and not validation and not ctx.ledgers
    assert len(result.references) == references and len(result.sources) == 1
    assert dict(result.source_counts)["assistant"] == 1
    assert dict(result.slot_counts)["assistant"] == references
    assert len(hints) <= ceil(count / 200)
    assert max(len(params) for _, params in hints) <= 400
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in ctx.db.statements)
    assert not any("business_reference_set" in sql for sql, _ in hints)
