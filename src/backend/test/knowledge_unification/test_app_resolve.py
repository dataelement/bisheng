"""APP B2 declaration contract. 覆盖 AC: AC-37, AC-68, AC-71, AC-87, AC-89."""

from copy import deepcopy

import pytest

from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.app_publish.domain.services.reference_extractor import (
    extract_app_reference_requests,
    extract_app_references,
)
from bisheng.resource_reference.application.contracts import TargetKey, TargetType
from test.knowledge_unification import test_app_snapshot as saved_fixtures

ctx = saved_fixtures.ctx
resolving = saved_fixtures.resolving
application = saved_fixtures.application
writing = saved_fixtures.writing


def declaration():
    return CapabilityDeclaration.model_validate(
        {
            "models": [{"name": "provider/chat"}, {"name": " model "}],
            "knowledge_bases": [{"id": "007", "name": "ignored"}, {"name": "Documents"}],
        }
    )


def test_semantic_slots_are_order_independent_and_do_not_rewrite_manifest():
    value = declaration()
    original = deepcopy(value.model_dump())
    first = extract_app_reference_requests(value)
    value.models.reverse()
    value.knowledge_bases.reverse()
    assert extract_app_reference_requests(value) == first
    assert {item.requested_name for item in first if item.target_type == TargetType.MODEL} == {
        "provider/chat",
        " model ",
    }
    assert next(item for item in first if item.target_id == "7").requested_name is None
    assert all(len(item.slot_key) < 192 for item in first)
    value.models.reverse()
    value.knowledge_bases.reverse()
    assert value.model_dump() == original


def test_complete_resolved_ids_are_frozen_and_duplicates_do_not_create_index_slots():
    value = declaration()
    value.models.append(value.models[0].model_copy())
    requests = extract_app_reference_requests(value)
    assert len(requests) == 4
    targets = {
        request.slot_key: TargetKey(request.target_type, str(index + 10)) for index, request in enumerate(requests)
    }
    # An explicit numeric knowledge ID is immutable, rather than an optional label.
    explicit = next(request for request in requests if request.target_id)
    targets[explicit.slot_key] = TargetKey(TargetType.KNOWLEDGE_SPACE, "7")
    refs = extract_app_references(value, resolved_targets=targets)
    assert {(ref.slot_key, ref.target) for ref in refs} == set(targets.items())
    assert extract_app_references(CapabilityDeclaration(), resolved_targets={}) == ()


def test_missing_or_extra_resolution_never_becomes_empty_ready():
    value = CapabilityDeclaration(models=[{"name": "missing"}])
    with pytest.raises(ValueError, match="complete"):
        extract_app_references(value, resolved_targets={})
    with pytest.raises(ValueError, match="complete"):
        extract_app_references(CapabilityDeclaration(), resolved_targets={"extra": TargetKey(TargetType.MODEL, "1")})


def test_resolved_target_cannot_replace_numeric_id_or_resource_kind():
    value = CapabilityDeclaration(knowledge_bases=[{"id": "7"}])
    slot = extract_app_reference_requests(value)[0].slot_key
    with pytest.raises(ValueError, match="identity"):
        extract_app_references(value, resolved_targets={slot: TargetKey(TargetType.KNOWLEDGE_SPACE, "8")})
    with pytest.raises(ValueError, match="type"):
        extract_app_references(value, resolved_targets={slot: TargetKey(TargetType.MODEL, "7")})


@pytest.mark.parametrize("ref", [{}, {"id": "nonnumeric"}, {"name": "  "}, {"id": "0"}])
def test_unresolvable_declaration_is_not_silently_discarded(ref):
    with pytest.raises(ValueError):
        extract_app_reference_requests(CapabilityDeclaration(knowledge_bases=[ref]))


async def test_actual_new_version_rejects_qa_and_leaves_business_and_reference_rows_unchanged(writing):
    import sqlalchemy as sa
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
    from bisheng.knowledge.domain.models.knowledge import Knowledge

    async with AsyncSession(writing.engine) as session, session.begin():
        await session.execute(sa.update(Knowledge).where(Knowledge.id == 7).values(type=1))
    before = await saved_fixtures.snapshot(writing.engine)
    with pytest.raises(ResourceReferenceInvalidError):
        await saved_fixtures.module.VersionService._insert_version(saved_fixtures.deployment())
    assert await saved_fixtures.snapshot(writing.engine) == before
