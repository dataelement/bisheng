"""F016 read-only price catalog endpoints."""

import httpx
from fastapi import FastAPI

from bisheng.common.dependencies.user_deps import UserPayload


async def _client():
    from bisheng.llm.api import pricing

    app = FastAPI()
    app.include_router(pricing.router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_tenant_admin_user] = lambda: object()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_catalog_lists_every_entry():
    async with await _client() as client:
        data = (await client.get("/api/v1/llm/price-catalog")).json()["data"]
    assert data["version"] == "2026-11-10"
    assert any(entry["key"] == "qwen/qwen-max" for entry in data["entries"])


async def test_match_prefills_known_models_and_flags_name_only_matches():
    async with await _client() as client:
        native = (
            await client.get(
                "/api/v1/llm/price-catalog/match", params={"server_type": "qwen", "model_name": "qwen-max"}
            )
        ).json()["data"]
        gateway = (
            await client.get(
                "/api/v1/llm/price-catalog/match", params={"server_type": "openai_compatible", "model_name": "gpt-4.1"}
            )
        ).json()["data"]
        unknown = (
            await client.get("/api/v1/llm/price-catalog/match", params={"server_type": "vllm", "model_name": "my-qwen"})
        ).json()["data"]
    assert native["matched"] and not native["via_name"]
    assert (native["entry"]["input"], native["entry"]["output"]) == ("12", "36")
    assert gateway["matched"] and gateway["via_name"]
    assert unknown == {"matched": False, "via_name": False, "catalog_version": "2026-11-10", "entry": None}


async def test_match_requires_both_parameters():
    async with await _client() as client:
        response = await client.get("/api/v1/llm/price-catalog/match", params={"server_type": "qwen"})
    assert response.status_code == 422


def test_routes_avoid_the_word_config():
    from bisheng.llm.api import pricing

    assert all("config" not in route.path.lower() for route in pricing.router.routes)
