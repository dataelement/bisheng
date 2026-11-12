"""T873: full model targets, bounded SQL fragments and consistent physical lock order."""

import math
import re
from collections import Counter

import pytest
from sqlalchemy import event

from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.repositories.reference_target_repository import ModelReferenceTargetRepository
from bisheng.resource_reference.application.contracts import TargetKey
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.models.resource_reference_tombstone import ResourceReferenceTombstone
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_llm_refs as original

model_owner_tenant = original.model_owner_tenant
removal_session = original.removal_session
impact = original.impact


@pytest.mark.parametrize("count", [401, 1001])
async def test_complete_native_targets_do_not_create_per_target_sql_or_expression_depth_failure(impact, count):
    session, service, _ = impact
    session.add_all(
        LLMModel(id=1000 + i, server_id=1, tenant_id=101, model_name=f"model-{i}", model_type="llm", online=True)
        for i in range(count - 5)
    )
    await session.commit()
    statements = []

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def seen(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, parameters))

    with original.actor() as identity:
        result = await service.ainspect_removed_models(
            session, identity=identity, server_id=1, retained_model_ids=(), delete_server=True
        )
    assert len(result.targets) == count and result.check_complete and not result.blocked
    by_table = Counter(re.search(r"\bFROM\s+([^\s,]+)", statement, re.I)[1] for statement, _ in statements)
    assert by_table["resource_reference_tombstone"] == math.ceil(count / 200)
    assert by_table["llm_model"] == 4
    assert by_table["business_resource_reference"] == math.ceil(count / 200)
    assert len(statements) <= 40
    for statement, _ in statements:
        for values in re.findall(r"\bIN\s*\(([^)]*)\)", statement, re.I):
            assert values.count("?") <= 200
    # Exact target groups bound the whole query as well as each IN fragment.
    # Empty groups still need one query to prove the complete absence of refs.
    inbound = [row for row in statements if "FROM business_resource_reference" in row[0]]
    assert len(inbound) == math.ceil(count / 200)
    assert all(len(parameters) <= 204 for _, parameters in inbound)
    assert all("LEFT OUTER JOIN business_reference_set" in statement for statement, _ in inbound)


def deleted(ident, owner=101):
    return ResourceReferenceTombstone(
        tenant_id=owner,
        target_type="model",
        target_id=str(ident),
        target_tenant_id=owner,
        operation_id=f"deleted-{owner}-{ident}",
        operation_type="model_delete_server",
        stage="deleted",
        actor_type="user",
        actor_id="7",
    )


async def test_tombstone_batches_are_global_string_index_order_not_numeric_chunk_order(impact):
    session, _, _ = impact
    ids = (*range(1000, 1201), 2)
    session.add_all(deleted(ident) for ident in ids)
    # A foreign tombstone with the same target ID is not this Owner's evidence.
    session.add(deleted(2, owner=202))
    await session.commit()
    statements = []

    @event.listens_for(session.sync_session, "do_orm_execute")
    def seen(state):
        if state.is_select and "FROM resource_reference_tombstone" in str(state.statement):
            statements.append(state.statement)

    result = await ModelReferenceTargetRepository().alock_targets(
        session, tuple(TargetKey("model", str(ident)) for ident in reversed(ids)), None, "owner_query"
    )
    observations = result
    assert [int(item.key.target_id) for item in observations] == sorted(ids)
    assert all(item.deletion.operation_id == f"deleted-101-{item.key.target_id}" for item in observations)
    assert len(statements) == 2
    requested = []
    for statement in statements:
        assert statement._for_update_arg is not None
        order = tuple(str(column) for column in statement._order_by_clauses)
        assert order == (
            "resource_reference_tombstone.target_type",
            "resource_reference_tombstone.target_id",
            "resource_reference_tombstone.target_tenant_id",
        )
        for value in statement.compile().params.values():
            if isinstance(value, list):
                assert len(value) <= 200
                requested.extend(value)
    assert requested == sorted(str(ident) for ident in ids)
    assert not session.new and not session.dirty


async def test_reference_predicate_preserves_exact_types_without_cartesian_target_membership(impact):
    session, _, _ = impact
    values = (
        ("model", "11"),
        ("model", "22"),
        ("knowledge_space", "11"),
        ("knowledge_space", "33"),
        ("knowledge_file", "11"),
    )
    for i, (kind, ident) in enumerate(values):
        session.add(
            BusinessResourceReference(
                tenant_id=101,
                source_type="assistant",
                source_id="mixed",
                source_version="current",
                slot_key=f"slot-{i}",
                target_type=kind,
                target_id=ident,
                target_tenant_id=101,
                target_space_id="99" if kind == "knowledge_file" else None,
                source_revision=1,
            )
        )
    await session.flush()
    query = ReferenceRepository._target_query((TargetKey("model", "11"), TargetKey("knowledge_space", "33")))
    actual = tuple((row.target_type, row.target_id) for row in (await session.execute(query)).scalars())
    assert actual == (("model", "11"), ("knowledge_space", "33"))


async def test_missing_targets_without_deletion_evidence_stay_missing_and_do_not_guess_owners(impact):
    session, _, _ = impact
    actual = await ModelReferenceTargetRepository().alock_targets(
        session, (TargetKey("model", "999999"),), None, "owner_query"
    )
    item = actual[0]
    assert not item.exists and item.target_tenant_id == 101 and item.deletion is None
    assert not session.new and not session.dirty
