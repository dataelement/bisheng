"""The internal plan adds one INSERT and constant actor work to real Core SQL."""

import importlib
import re
from collections import Counter
from math import ceil

import pytest
from sqlalchemy import event, insert, update

from bisheng.database.models.tenant import Tenant
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from test.knowledge_unification import test_model_delete_plan_application as actual

model_owner_tenant = actual.model_owner_tenant
removal_session = actual.removal_session
impact = actual.impact
ready = actual.ready


@pytest.mark.parametrize("count", [401, 10001])
async def test_native_many_target_plan_keeps_one_core_scan_one_insert_and_constant_actor_work(
    ready, monkeypatch, count
):
    session, references, plans = ready
    ids = tuple(range(11, 16)) + tuple(range(1000, 1000 + count - 5))
    await session.execute(
        insert(LLMModel.__table__),
        [
            {"id": ident, "server_id": 1, "tenant_id": 101, "model_name": str(ident), "model_type": "llm"}
            for ident in ids[5:]
        ],
    )
    await session.execute(
        BusinessResourceReference.__table__.delete().where(BusinessResourceReference.tenant_id == 101)
    )
    await session.execute(BusinessReferenceSet.__table__.delete().where(BusinessReferenceSet.tenant_id == 101))
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
    await session.execute(
        insert(BusinessResourceReference.__table__),
        [
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
            }
            for slot in range(3)
            for ident in ids
        ],
    )
    await session.commit()
    await session.execute(update(Tenant).where(Tenant.id == 101).values(tenant_name="outer TX"))
    app = actual.application(references, plans)
    module = importlib.import_module("bisheng.llm.application.model_delete_plan")
    resolve, actors = module.resolve_permission_actor, []

    async def counted(*args, **kwargs):
        actors.append(1)
        return await resolve(*args, **kwargs)

    monkeypatch.setattr(module, "resolve_permission_actor", counted)
    statements = []

    def record(_c, _cu, sql, params, _ctx, _many):
        statements.append((sql, params))

    event.listen(session.bind.sync_engine, "before_cursor_execute", record)
    try:
        with actual.native.actor() as user:
            result = await app.aplan_server_delete(session, identity=actual.web(user), server_id=1)
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", record)
    selects = [sql for sql, _ in statements if sql.lstrip().upper().startswith("SELECT")]
    by_table = Counter(re.search(r"\bFROM\s+([^\s,]+)", sql, re.I)[1] for sql in selects)
    inbound = [(sql, params) for sql, params in statements if "FROM business_resource_reference" in sql]
    assert len(result.inspection.targets) == count
    assert sum(dict(result.inspection.slot_counts).values()) == 3 * count
    assert by_table["llm_model"] == 4 and by_table["llm_server"] == 3
    assert by_table["resource_reference_tombstone"] == ceil(count / 200)
    assert len(inbound) <= ceil(count / 200) + 3 * count // 200
    assert max(len(params) for _, params in inbound) <= 204
    assert len(selects) <= 23 + 2 * ceil(count / 200) + 3 * count // 200
    assert sum(sql.lstrip().upper().startswith("INSERT INTO KNOWLEDGE_OPERATION_PLAN") for sql, _ in statements) == 1
    assert not any(sql.lstrip().upper().startswith(("UPDATE", "DELETE")) for sql, _ in statements)
    assert len(actors) == 3
    print(
        {
            "targets": count,
            "references": 3 * count,
            "selects": len(selects),
            "by_table": dict(by_table),
            "plan_inserts": 1,
            "extra_actor_calls": len(actors),
        }
    )
