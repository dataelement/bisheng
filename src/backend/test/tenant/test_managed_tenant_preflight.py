"""Read-only inventory is scoped and leaves business rows untouched."""

from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.flow import Flow
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.tenant.application.managed_tenant_preflight import inspect_managed_tenant
from bisheng.tool.domain.models.gpts_tools import GptsToolsType
from test.fixtures.managed_tenant import managed_db as managed_db
from test.role.test_effective_roles import policy_db as policy_db


async def test_preflight_narrows_scope_and_preserves_rows(policy_db, monkeypatch):
    from bisheng.tenant.domain.repositories import managed_tenant_preflight

    await policy_db.create(Flow, Knowledge, GptsToolsType)
    monkeypatch.setattr(managed_tenant_preflight, "get_async_db_session", policy_db.sessions)
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            session.add_all(
                [
                    Flow(id="pending-a", name="A", tenant_id=2, user_id=77, flow_type=10, creation_state="PENDING"),
                    Flow(id="foreign-b", name="B", tenant_id=3, user_id=77, flow_type=10, creation_state="PENDING"),
                ]
            )
            await session.commit()
    result = await inspect_managed_tenant(2, [77])
    assert result["read_only"] and len(result["people"]) == 1
    assert result["people"][0]["effective_roles"] == [2, 3]
    assert result["people"][0]["excluded_roles"] == [4, 5]
    assert [item["id"] for item in result["resources"]] == ["pending-a"]
    with bypass_tenant_filter():
        async with policy_db.sessions() as session:
            rows = (await session.exec(select(Flow))).all()
            assert len(rows) == 2 and all(row.creation_state == "PENDING" for row in rows)
