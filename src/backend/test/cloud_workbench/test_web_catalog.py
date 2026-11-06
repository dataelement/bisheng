"""Browser application entrances share Desktop's tenant/use/state checks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.app_runtime.domain.services import desktop_apps_service as module


@pytest.mark.asyncio
async def test_catalog_rechecks_each_person_and_keeps_cursor_across_denied_rows(monkeypatch):
    actor = SimpleNamespace(user_id=10, tenant_id=2)

    def app(id, tenant=2, state="online"):
        return SimpleNamespace(
            id=id, tenant_id=tenant, state=state, name=id, slug=id, description="", current_version_id="version"
        )

    rows = [app("allowed"), app("denied"), app("other-tenant", tenant=3), app("stopped", state="stopped")]
    repo = SimpleNamespace(page=AsyncMock(return_value=(rows, "next-page")))
    check = AsyncMock(side_effect=lambda user, **target: user.user_id == 10 and target["resource_id"] == "allowed")
    monkeypatch.setattr(module, "check_action", check)
    result = await module.workbench_page(actor, repo, after="previous-page")
    assert [item["id"] for item in result["items"]] == ["allowed"]
    assert result["next_cursor"] == "next-page"
    assert result["items"][0]["entry_path"] == "/apps/allowed/"
    assert [call.kwargs["action"] for call in check.await_args_list] == ["use", "use"]
    assert not (await module.workbench_page(SimpleNamespace(user_id=11, tenant_id=2), repo))["items"]
    repo.page.assert_any_await(after="previous-page")


def test_web_catalog_is_static_before_application_id_and_requires_current_login():
    from bisheng.app_runtime.api.endpoints.apps import router

    routes = [route.path for route in router.routes]
    assert routes.index("/apps/workbenches") < routes.index("/apps/{app_id}")
    route = next(route for route in router.routes if route.path == "/apps/workbenches")
    assert any(dependency.call.__name__ == "get_login_user" for dependency in route.dependant.dependencies)
