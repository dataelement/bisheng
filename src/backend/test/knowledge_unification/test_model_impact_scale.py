"""T983: actual multi-target model impact bounds SQL and full receipt CPU.

覆盖 AC: AC-72, AC-87, AC-88, AC-89, AC-90, AC-91
Only persisted coverage status is the existing isolated native test port.
"""

import hashlib
from math import ceil
from types import SimpleNamespace

import pytest
from sqlalchemy import event, insert

from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.services.model_reference_service import _binding_digest
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
    expected = hashlib.sha256(b"f118-model-inbound-v2\0")
    for ident, values in enumerate(bindings, 1):
        expected.update(ident.to_bytes(8, "big"))
        expected.update(_binding_digest(SimpleNamespace(id=ident, **values)))
    queries, candidates = [], []
    validate = service.runtime.verifier.validate_owner_receipts

    def checked(active, receipts):
        candidates.append(len(receipts))
        return validate(active, receipts)

    def record(_conn, _cursor, query, params, _context, _many):
        if "LEFT OUTER JOIN business_reference_set" in query:
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
            "max_parameters": max(len(params) for _, params in queries),
            "validation_calls": len(candidates),
            "validation_candidates": sum(candidates),
        }
    )
    assert result.check_complete and result.inbound_digest == expected.hexdigest()
    assert len(result.targets) == count and dict(result.slot_counts)["assistant"] == len(bindings)
    assert result.blocked is bool(bindings) and ledger.reads == 2
    assert ceil(count / 200) <= len(queries) <= ceil(count / 200) + len(bindings) // 200
    assert max(len(params) for _, params in queries) <= 250
    assert candidates == [count, count, count]
    assert not session.new and not session.dirty and not session.deleted
    print({"targets": count, "references": len(bindings), "sql": len(queries), "validation": candidates})
