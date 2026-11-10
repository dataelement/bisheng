"""AC-21: live model candidates use the authorized tenant catalog, never audit facts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.llm.domain.services.llm import LLMService
from test.dsh.test_model_audit_flow import ADMIN, BASE, LOCAL_ADMIN, USER, fixture


async def test_model_options_use_current_catalog_with_tenant_scope_search_and_pagination(monkeypatch):
    async def ids():
        return [42, 43] if get_current_tenant_id() == 2 else [44]

    async def load(model_id):
        tenant = get_current_tenant_id()
        assert model_id in ([42, 43] if tenant == 2 else [44])
        return (
            SimpleNamespace(
                id=model_id, tenant_id=tenant, model_name="Current model" if model_id != 44 else "Other", name="unused"
            ),
            SimpleNamespace(name="Provider", type="openai"),
        )

    loader = AsyncMock(side_effect=ids)
    monkeypatch.setattr(LLMService, "get_dsh_model_ids", loader)
    monkeypatch.setattr(LLMService, "get_dsh_model_snapshot", load)
    async with fixture() as (harness, client, _objects):
        # Candidate selection must not open the audit repository or scan audit records.
        harness.queries.repository_scope = lambda: pytest.fail("Audit repository was queried for model candidates")
        response = await client.get(BASE + "/models", headers=LOCAL_ADMIN, params={"page_size": 1})
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["data"] == {"data": [{"id": 42, "name": "Provider / Current model"}], "total": 1}
        next_page = await client.get(BASE + "/models", headers=LOCAL_ADMIN, params={"page_size": 1, "page": 2})
        assert next_page.json()["data"] == {"data": [], "total": 1}
        searched = await client.get(BASE + "/models", headers=LOCAL_ADMIN, params={"keyword": "current"})
        assert searched.json()["data"]["total"] == 1
        deleted = await client.get(BASE + "/models", headers=LOCAL_ADMIN, params={"keyword": "Deleted"})
        assert deleted.json()["data"] == {"data": [], "total": 0}
        root = await client.get(BASE + "/models", headers=ADMIN, params={"tenant_id": 3})
        assert root.json()["data"] == {"data": [{"id": 44, "name": "Provider / Other"}], "total": 1}
        count = loader.await_count
        assert (await client.get(BASE + "/models", headers=LOCAL_ADMIN, params={"tenant_id": 3})).status_code == 403
        assert (await client.get(BASE + "/models", headers=USER)).status_code == 403
        assert loader.await_count == count


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 101}, {"keyword": "x" * 2049}])
async def test_model_options_bound_pagination_and_search(params):
    async with fixture() as (_harness, client, _objects):
        assert (await client.get(BASE + "/models", headers=ADMIN, params=params)).status_code == 422
