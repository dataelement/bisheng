"""T983: actual multi-target model impact bounds SQL and full receipt CPU.

覆盖 AC: AC-72, AC-87, AC-88, AC-89, AC-90, AC-91
Only persisted coverage status is the existing isolated native test port.
"""

from math import ceil

import pytest
from sqlalchemy import event, insert

from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_llm_refs as original

model_owner_tenant = original.model_owner_tenant
removal_session = original.removal_session
impact = original.impact


@pytest.mark.parametrize(
    "count,mode",
    [
        (401, "empty"),
        (401, "dense"),
        (1001, "empty"),
        (1001, "dense"),
        (10001, "empty"),
        (10001, "sparse"),
        (10001, "dense"),
    ],
)
async def test_real_model_impact_401_1001_10001_keeps_v2_digest_with_bounded_owner_stream(
    impact, monkeypatch, count, mode
):
    session, service, ledger = impact
    ids = tuple(range(11, 16)) + tuple(range(1000, 1000 + count - 5))
    await session.execute(
        insert(LLMModel.__table__),
        [
            {"id": ident, "server_id": 1, "tenant_id": 101, "model_name": str(ident), "model_type": "llm"}
            for ident in ids[5:]
        ],
    )
    await session.execute(
        insert(BusinessReferenceSet.__table__),
        {
            "tenant_id": 101,
            "source_type": "assistant",
            "source_id": "one",
            "source_version": "current",
            "source_revision": 1,
            "extractor_version": "native",
            "digest": "a" * 64,
            "ready": True,
            "effective": True,
        },
    )
    chosen = () if mode == "empty" else (ids[0], ids[count // 2], ids[-1]) if mode == "sparse" else ids
    # Physical IDs interleave target groups. No all-R sorting in the service
    # can be substituted for the original v2 byte sequence.
    positions = {ident: index for index, ident in enumerate(ids)}
    chosen = sorted(chosen, key=lambda ident: (positions[ident] % 200, ident))
    bindings = [
        {
            "tenant_id": 101,
            "source_type": "assistant",
            "source_id": "one",
            "source_version": "current",
            "source_revision": 1,
            "slot_key": f"{slot}-{ident}",
            "target_type": "model",
            "target_id": str(ident),
            "target_tenant_id": 101,
            "target_space_id": None,
            "legacy_invalid_reason": None,
            "legacy_run_id": None,
            "legacy_evidence_key": None,
        }
        for slot in range(3)
        for ident in chosen
    ]
    if bindings:
        await session.execute(insert(BusinessResourceReference.__table__), bindings)
    await session.commit()
    queries, candidates = [], []
    validate = service.runtime.verifier.validate_owner_receipts

    def checked(active, receipts):
        candidates.append(len(receipts))
        return validate(active, receipts)

    def record(_conn, _cursor, query, params, _context, _many):
        if "FROM business_resource_reference" in query:
            queries.append((query, params))

    monkeypatch.setattr(service.runtime.verifier, "validate_owner_receipts", checked)
    event.listen(session.bind.sync_engine, "before_cursor_execute", record)
    try:
        with original.actor() as user:
            result = await original.inspect(impact, user, delete_server=True)
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", record)
    print(
        {
            "targets": count,
            "references": len(bindings),
            "sql": len(queries),
            "max_parameters": max((len(params) for _, params in queries), default=0),
            "validation_calls": len(candidates),
            "validation_candidates": sum(candidates),
        }
    )
    assert len(result.targets) == count and ledger.reads == 0 and not candidates
    if result.check_complete:
        assert len(result.inbound_digest) == 64
        assert dict(result.slot_counts)["assistant"] == len(bindings)
        assert result.blocked is bool(bindings)
    else:
        assert not result.source_counts and not result.blocked
    assert len(queries) <= ceil(count / 200)
    assert max((len(params) for _, params in queries), default=0) <= 400
    assert all("business_reference_set" not in query for query, _ in queries)
    assert not session.new and not session.dirty and not session.deleted
