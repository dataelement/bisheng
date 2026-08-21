from unittest.mock import AsyncMock

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.testclient import TestClient

from bisheng.api_rate_limit.domain.repositories.implementations import RateLimitDecision
from bisheng.api_rate_limit.domain.schemas import ApiRateLimitConfig, RateLimitDimension
from bisheng.api_rate_limit.middleware import ApiRateLimitMiddleware


def _build_app(config_provider, counter):
    app = FastAPI()
    app.add_middleware(ApiRateLimitMiddleware, config_provider=config_provider, counter=counter)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://portal.test"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/items/{item_id}")
    async def item(item_id: int):
        return {"item_id": item_id}

    @app.get("/api/v1/stream")
    async def stream():
        async def chunks():
            yield "data: ok\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    @app.get("/api/v1/admin/api-rate-limit/config")
    async def own_config():
        return {"ok": True}

    @app.get("/api/v1/admin/api-rate-limit/routes")
    async def own_routes():
        return {"items": []}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("ok")
        await websocket.close()

    return app


def _limited_config(message="配置的提示"):
    return ApiRateLimitConfig.model_validate({"revision": 3, "global": {"limits": {"second": 1}, "message": message}})


def test_dynamic_route_returns_429_contract_and_cors_headers():
    provider = AsyncMock(return_value=_limited_config())
    counter = AsyncMock(
        return_value=RateLimitDecision(
            allowed=False,
            dimension=RateLimitDimension.SECOND,
            retry_after=1,
        )
    )
    client = TestClient(_build_app(provider, counter))

    response = client.get(
        "/api/v1/items/42",
        headers={"Origin": "http://portal.test"},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert response.headers["access-control-allow-origin"] == "http://portal.test"
    assert response.json() == {
        "status_code": 10042,
        "status_message": "配置的提示",
        "data": {"retry_after": 1, "dimension": "second"},
    }
    counter.assert_awaited_once()
    assert counter.await_args.args[:2] == ("GET", "/api/v1/items/{item_id}")


def test_redis_failure_fails_open_and_preserves_endpoint_response():
    provider = AsyncMock(side_effect=RuntimeError("redis down"))
    counter = AsyncMock()
    client = TestClient(_build_app(provider, counter))

    response = client.get("/api/v1/items/7")

    assert response.status_code == 200
    assert response.json() == {"item_id": 7}
    counter.assert_not_awaited()


def test_excluded_and_unmatched_paths_do_not_touch_runtime_config():
    provider = AsyncMock(return_value=_limited_config())
    counter = AsyncMock()
    client = TestClient(_build_app(provider, counter))

    assert client.get("/api/v1/admin/api-rate-limit/config").status_code == 200
    assert client.get("/api/v1/admin/api-rate-limit/routes").status_code == 200
    assert client.get("/missing").status_code == 404
    provider.assert_not_awaited()
    counter.assert_not_awaited()


def test_sse_request_counts_once_at_connection_establishment():
    provider = AsyncMock(return_value=_limited_config())
    counter = AsyncMock(return_value=RateLimitDecision(allowed=True))
    client = TestClient(_build_app(provider, counter))

    response = client.get("/api/v1/stream", headers={"Accept": "text/event-stream"})

    assert response.status_code == 200
    assert response.text == "data: ok\n\n"
    counter.assert_awaited_once()


def test_websocket_bypasses_rate_limit_middleware():
    provider = AsyncMock(return_value=_limited_config())
    counter = AsyncMock()
    client = TestClient(_build_app(provider, counter))

    with client.websocket_connect("/ws") as websocket:
        assert websocket.receive_text() == "ok"

    provider.assert_not_awaited()
    counter.assert_not_awaited()
