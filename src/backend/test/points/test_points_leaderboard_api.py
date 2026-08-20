# ruff: noqa: RUF002
"""首页积分榜 HTTP：未登录可读，且走查询服务（公司解析在 domain 单测覆盖）。"""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bisheng.points.api.dependencies import get_optional_login_user, get_points_query_service
from bisheng.points.api.router import router
from bisheng.points.domain.schemas.points_schema import PointLeaderboardItem, PointLeaderboardResponse


def _app(*, user, service):
    """只挂积分路由，覆盖可选登录与查询服务。"""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_optional_login_user] = lambda: user
    app.dependency_overrides[get_points_query_service] = lambda: service
    return app


def _service(*, company_id: int | None):
    """记录 leaderboard 入参，返回固定一条榜。"""
    calls: list[tuple] = []
    items = []
    if company_id is not None:
        items = [
            PointLeaderboardItem(
                rank=1,
                user_id=10,
                user_name="张三",
                dept_name="炼铁作业部",
                balance=100,
                period_score=40,
            )
        ]

    async def leaderboard(tenant_id, period, user):
        calls.append((tenant_id, period, user))
        return PointLeaderboardResponse(period=period, refreshed_at=None, items=items)

    return SimpleNamespace(leaderboard=leaderboard, calls=calls)


def test_guest_get_leaderboard_ok_without_login():
    """未登录 GET 积分榜：HTTP 200，且把 user=None 交给查询服务。"""
    svc = _service(company_id=54)
    client = TestClient(_app(user=None, service=svc))
    resp = client.get("/api/v1/points/leaderboard?period=month")
    body = resp.json()
    assert resp.status_code == 200, body
    assert body.get("status_code") == 200
    data = body.get("data") or {}
    assert data.get("period") == "month"
    assert len(data.get("items") or []) == 1
    assert (data["items"][0] or {}).get("user_name") == "张三"
    assert svc.calls[0][2] is None
    again = client.get("/api/v1/points/leaderboard?period=month")
    assert again.json()["status_code"] == 200
    assert len((again.json().get("data") or {}).get("items") or []) == 1


def test_admin_get_leaderboard_passes_login_user():
    """平台超管 GET 积分榜：仍 200，身份原样传给查询服务（公司解析在 domain）。"""
    admin = SimpleNamespace(user_id=1, tenant_id=1, is_admin=lambda: True, is_global_super=True)
    svc = _service(company_id=54)
    client = TestClient(_app(user=admin, service=svc))
    resp = client.get("/api/v1/points/leaderboard")
    body = resp.json()
    assert resp.status_code == 200, body
    assert body.get("status_code") == 200
    assert svc.calls[0][2] is admin


def test_guest_leaderboard_empty_items_when_service_empty():
    """无公司节点时接口仍 200，items 为空，再读仍空。"""
    svc = _service(company_id=None)
    client = TestClient(_app(user=None, service=svc))
    resp = client.get("/api/v1/points/leaderboard")
    body = resp.json()
    assert body.get("status_code") == 200
    assert (body.get("data") or {}).get("items") == []
    again = client.get("/api/v1/points/leaderboard")
    assert (again.json().get("data") or {}).get("items") == []
