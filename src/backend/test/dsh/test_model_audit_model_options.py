"""Tenant-scoped historical model names do not depend on live model configuration."""

import pytest

from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest
from test.dsh.model_audit_fixtures import NOW, audit_session
from test.dsh.test_model_audit_flow import ADMIN, BASE, LOCAL_ADMIN, USER, fixture


async def test_model_names_are_tenant_scoped_distinct_paginated_and_survive_deleted_configuration():
    async with fixture() as (harness, client, _objects):
        for tenant, names in (
            (2, ["Deleted model", "Deleted model", "Current model", "Literal%name", ""]),
            (3, ["Other tenant"]),
        ):
            with audit_session(harness.engine, tenant) as session:
                for index, name in enumerate(names):
                    session.add(
                        DshModelAuditRequest(
                            request_id=f"{tenant}-{index}", user_id=20, model_id=999, model_name=name, started_at=NOW
                        )
                    )
                session.commit()
        response = await client.get(BASE + "/models", headers=LOCAL_ADMIN, params={"page_size": 1})
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["data"] == {"data": ["Current model"], "total": 3}
        next_page = await client.get(BASE + "/models", headers=LOCAL_ADMIN, params={"page_size": 1, "page": 2})
        assert next_page.json()["data"] == {"data": ["Deleted model"], "total": 3}
        searched = await client.get(BASE + "/models", headers=LOCAL_ADMIN, params={"keyword": "%"})
        assert searched.json()["data"] == {"data": ["Literal%name"], "total": 1}
        root = await client.get(BASE + "/models", headers=ADMIN, params={"tenant_id": 3})
        assert root.json()["data"] == {"data": ["Other tenant"], "total": 1}
        assert (await client.get(BASE + "/models", headers=LOCAL_ADMIN, params={"tenant_id": 3})).status_code == 403
        assert (await client.get(BASE + "/models", headers=USER)).status_code == 403


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 101}, {"keyword": "x" * 129}])
async def test_model_options_bound_pagination_and_search(params):
    async with fixture() as (_harness, client, _objects):
        assert (await client.get(BASE + "/models", headers=ADMIN, params=params)).status_code == 422
