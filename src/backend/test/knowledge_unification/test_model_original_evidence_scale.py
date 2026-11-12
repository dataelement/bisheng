"""T885: actual binding SQL plus measured original-evidence scan work."""

from collections import Counter

import pytest
from sqlalchemy import event

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.repositories import reference_target_repository as target_module
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference as Binding
from test.knowledge_unification import test_model_deletion_repository as original

model_owner_tenant = original.model_owner_tenant
removal_session = original.removal_session
SOURCE = SourceKey(101, "assistant", "scale", "current")


def binding(target_id, slot, *, source=SOURCE, **kwargs):
    return Binding(
        tenant_id=source.tenant_id,
        source_type=source.source_type.value,
        source_id=source.source_id,
        source_version=source.source_version,
        slot_key=slot,
        target_type="model",
        target_id=str(target_id),
        target_tenant_id=101,
        source_revision=1,
        **kwargs,
    )


@pytest.mark.parametrize("count", [401, 1001])
async def test_actual_bind_does_not_rescan_every_old_slot_for_each_model(removal_session, monkeypatch, count):
    session = removal_session
    ids = tuple(range(1000, 1000 + count))
    session.add_all(
        LLMModel(id=ident, server_id=1, tenant_id=101, model_name=f"scale-{ident}", model_type="llm") for ident in ids
    )
    session.add_all(binding(ident, f"model-{ident}-{slot}") for ident in ids for slot in range(3))
    await session.commit()
    candidates, statements = [], []
    actual = target_module._original

    def measured(rows, key):
        candidates.append(len(rows))
        return actual(rows, key)

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def seen(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    monkeypatch.setattr(target_module, "_original", measured)
    observations = await target_module.ModelReferenceTargetRepository().alock_targets(
        session, tuple(TargetKey("model", str(ident)) for ident in reversed(ids)), SOURCE, "bind"
    )
    assert len(observations) == count and all(item.exists for item in observations)
    assert tuple(int(item.key.target_id) for item in observations) == ids
    assert all(item.original.source_id == "scale" and item.original.slot_key.endswith("-0") for item in observations)
    # Counts the actual scan input, not elapsed time or a reimplementation of
    # the index. Old code supplies 3*count rows to each of count calls.
    assert len(candidates) == count and sum(candidates) <= 3 * count
    tables = Counter(statement.split("FROM ", 1)[1].split()[0] for statement in statements if "FROM " in statement)
    assert tables["business_resource_reference"] == 1
    assert len(statements) <= 20
    assert not session.new and not session.dirty


async def test_duplicate_slots_keep_first_row_and_other_sources_or_versions_do_not_conflict(removal_session):
    session = removal_session
    first = binding(11, "first")
    session.add_all(
        (
            first,
            binding(11, "second"),
            binding(11, "historical", source=SourceKey(101, "assistant", "scale", "v1"), target_space_id="99"),
            binding(11, "another", source=SourceKey(101, "assistant", "another", "current"), target_space_id="98"),
        )
    )
    await session.commit()
    result = await target_module.ModelReferenceTargetRepository().alock_targets(
        session, (TargetKey("model", "11"),), SOURCE, "bind"
    )
    assert len(result) == 1 and result[0].original.id == first.id and result[0].original.slot_key == "first"


@pytest.mark.parametrize("field,changed", [("target_space_id", "99"), ("legacy_run_id", "other-run")])
async def test_same_target_conflicting_original_evidence_is_still_rejected(removal_session, field, changed):
    session = removal_session
    evidence = {
        "legacy_invalid_reason": "target_missing",
        "legacy_run_id": "original-run",
        "legacy_evidence_key": "frozen-key",
    }
    session.add_all((binding(999999, "one", **evidence), binding(999999, "two", **(evidence | {field: changed}))))
    await session.commit()
    with pytest.raises(ResourceReferenceInvalidError) as caught:
        await target_module.ModelReferenceTargetRepository().alock_targets(
            session, (TargetKey("model", "999999"),), SOURCE, "bind"
        )
    assert caught.value.kwargs["reason"] == "reference_original_evidence_conflict"
