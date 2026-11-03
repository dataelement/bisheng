"""覆盖 AC: AC-15、AC-36、AC-37、AC-43、AC-48、AC-50. Original business entry points."""

import pytest

from bisheng.app_runtime.domain.constants import AppState

pytestmark = pytest.mark.usefixtures("app_db", "fake_orchestrator")


async def test_owner_gets_a_streamed_csv_and_cache_is_removed(api_app, app_factory, app_owner, tmp_path, monkeypatch):
    from bisheng.app_runtime.domain.services.app_data_service import AppDataService

    app, _ = await app_factory(state=AppState.ONLINE.value)
    root = tmp_path / "export-one"
    root.mkdir()
    path = root / "export.csv"
    data = b"id,name\n1,fixture\n"
    path.write_bytes(data)

    async def call(*args, **kwargs):
        return path

    monkeypatch.setattr(AppDataService, "_call", call)
    async with api_app(app_owner.payload) as client:
        response = await client.get(f"/api/v1/apps/{app.id}/data/export", params={"table": "users"})
    assert response.status_code == 200 and response.content == data
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert not path.exists() and not root.exists()


async def test_result_lookup_uses_current_natural_owner(api_app, app_factory, app_owner, normal_user, monkeypatch):
    from bisheng.app_runtime.domain.services.runtime_data_session_service import RuntimeDataSessionService

    app, _ = await app_factory(state=AppState.ONLINE.value)
    seen = []

    async def recover(self, target, actor, operation_id):
        seen.append((target.id, actor.user_id, operation_id))
        return {"state": "done", "result": {"after": {"name": "new"}}}

    monkeypatch.setattr(RuntimeDataSessionService, "recover", recover)
    async with api_app(app_owner.payload) as client:
        allowed = await client.get(f"/api/v1/apps/{app.id}/data/operations/original/result")
    assert allowed.status_code == 200 and allowed.json()["data"]["state"] == "done"
    async with api_app(normal_user.payload) as client:
        denied = await client.get(f"/api/v1/apps/{app.id}/data/operations/original/result")
    assert denied.json()["status_code"] == 16162
    assert len(seen) == 1 and seen[0][1] == app_owner.payload.user_id
