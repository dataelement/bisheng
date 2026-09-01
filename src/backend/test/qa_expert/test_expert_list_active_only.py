# ruff: noqa: RUF002
"""邀请/榜单列表只返回有效专家；管理列表默认仍含停用。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.database.models.qa_expert import Expert
from bisheng.qa_expert.api import endpoints
from bisheng.qa_expert.api.router import router
from bisheng.qa_expert.domain.repositories import ExpertRepository


async def test_list_status_one_hides_disabled_experts(flow_env):
    env = flow_env
    env.as_user(env.portal_admin)
    active = await env.seed_expert(user_id=601, name="active-list")
    disabled = await env.seed_expert(user_id=602, name="disabled-list")

    disable_resp = await env.client.post(f"/api/v1/qa_experts/experts/{int(disabled.id)}/disable")
    assert disable_resp.json()["status_code"] == 200
    row = await env.reload_row(Expert, id=int(disabled.id))
    assert int(row.status) == 0

    repo = ExpertRepository()
    all_rows, _all_total = await repo.list_all(skip=0, limit=200)
    all_ids = {int(item.id) for item in all_rows}
    assert int(active.id) in all_ids
    assert int(disabled.id) in all_ids

    active_rows, _active_total = await repo.list_all(skip=0, limit=200, status=1)
    active_ids = {int(item.id) for item in active_rows}
    assert int(active.id) in active_ids
    assert int(disabled.id) not in active_ids

    again_rows, _ = await repo.list_all(skip=0, limit=200, status=1)
    assert int(disabled.id) not in {int(item.id) for item in again_rows}


def test_list_experts_query_status_accepts_string_one():
    """门户榜单会带 status=1 查询串, 必须能转成整数, 不能 422。"""
    service = SimpleNamespace(list_experts=AsyncMock(return_value=([], 0)))
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[endpoints.get_expert_service] = lambda: service
    client = TestClient(app)

    resp = client.get(
        "/api/v1/qa_experts/experts",
        params={
            "page": 1,
            "limit": 8,
            "sort_by": "expert_score",
            "sort_order": "desc",
            "status": "1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 200
    service.list_experts.assert_awaited()
    assert service.list_experts.await_args.kwargs["status"] == 1
