"""T695: real creator qualification and narrow creation-initial-value HTTP path."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import management_tenant_scope
from bisheng.knowledge.api.endpoints import knowledge_space as api
from bisheng.knowledge.domain.services import knowledge_creation_policy as policy
from bisheng.llm.application import model_default_read
from test.knowledge_unification import test_kn_creation_api as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
consumer = fixtures.consumer
web_create = fixtures.web_create


@pytest.fixture
def initial(web_create, monkeypatch):
    session = object()
    entered = []

    @asynccontextmanager
    async def sessions():
        entered.append(session)
        yield session

    read = AsyncMock(return_value=SimpleNamespace(payload_json="{}"))
    runtime = SimpleNamespace(aget_default=read, arequire_default=AsyncMock(side_effect=AssertionError("execution")))
    monkeypatch.setattr(model_default_read, "_runtime", runtime)
    monkeypatch.setattr(api, "get_async_db_session", sessions, raising=False)
    return SimpleNamespace(web=web_create, session=session, entered=entered, read=read, runtime=runtime)


async def get_settings(initial):
    async with AsyncClient(transport=ASGITransport(app=initial.web.app), base_url="http://test") as client:
        with management_tenant_scope(101):
            return await client.get("/api/v1/knowledge/space/creation-settings")


async def test_original_creation_menu_can_read_initial_values_without_admin_or_existing_space(initial):
    response = await get_settings(initial)
    assert response.status_code == 200
    result = response.json()
    assert result["status_code"] == 200
    assert set(result["data"]) == {"embedding_model", "system_defaults"}
    assert result["data"]["embedding_model"] is None
    defaults = result["data"]["system_defaults"]
    assert set(defaults) == {"document", "table"}
    assert defaults["document"]["force_ocr"] == 1
    assert defaults["document"]["chunk_size"] == 1000
    initial.web.menu.assert_awaited_once()
    initial.web.scope.assert_not_awaited()
    initial.web.service._require_action.assert_not_awaited()
    initial.read.assert_awaited_once_with("linsight_llm", login_user=initial.web.context.user, session=initial.session)
    initial.runtime.arequire_default.assert_not_awaited()
    assert initial.entered == [initial.session]


@pytest.mark.parametrize("model_id", ["11", "999999", "retired-embedding"])
async def test_saved_embedding_id_is_preserved_without_execution_admission_or_secret_projection(initial, model_id):
    initial.read.return_value.payload_json = json.dumps(
        {
            "embedding_model": {"id": model_id, "name": "old embedding", "config": {"secret": "hidden"}},
            "models": [{"id": "999", "name": "unrelated-invalid-chat"}],
            "chat_title_llm": {"id": "998", "name": "unrelated-invalid-title"},
            "provider_config": {"api_key": "hidden"},
        }
    )
    response = await get_settings(initial)
    assert response.status_code == 200
    result = response.json()
    assert result["status_code"] == 200
    assert result["data"]["embedding_model"] == {"id": model_id, "name": "old embedding"}
    assert "hidden" not in response.text
    assert "unrelated-invalid" not in response.text
    initial.runtime.arequire_default.assert_not_awaited()


@pytest.mark.parametrize("failure", ["credential", "menu"])
async def test_original_creation_denial_precedes_default_read(initial, monkeypatch, failure):
    if failure == "credential":
        monkeypatch.setattr(policy, "resolve_web_creation_identity", AsyncMock(side_effect=PermissionDeniedError()))
    else:
        initial.web.menu.side_effect = PermissionDeniedError()
    response = await get_settings(initial)
    assert response.status_code == 200
    assert response.json()["status_code"] != 200
    initial.read.assert_not_awaited()


async def test_default_read_failure_remains_a_business_error_without_empty_success(initial):
    initial.read.side_effect = PermissionDeniedError()
    response = await get_settings(initial)
    assert response.status_code == 200
    assert response.json()["status_code"] != 200
    initial.runtime.arequire_default.assert_not_awaited()


async def test_global_super_keeps_home_identity_while_reading_selected_tenant(initial):
    user = initial.web.context.user
    user.tenant_id = 1
    user.is_global_super = True
    user._runtime_credential_reference = {"kind": "web_session", "user_id": 7, "tenant_id": 1}
    response = await get_settings(initial)
    assert response.status_code == 200 and response.json()["status_code"] == 200
    initial.read.assert_awaited_once_with("linsight_llm", login_user=user, session=initial.session)
    assert user.tenant_id == 1
    initial.web.menu.assert_not_awaited()
