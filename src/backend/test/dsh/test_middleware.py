"""F062 precise credential routing. 覆盖 AC: AC-04, AC-13, AC-30, AC-31, AC-32."""

import httpx
from fastapi import FastAPI

from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.utils.http_middleware import CustomMiddleware


async def test_dsh_paths_never_decode_browser_cookie_or_enable_tenant_bypass(monkeypatch):
    import bisheng.utils.http_middleware as middleware

    decoded = []
    monkeypatch.setattr(middleware, "_decode_jwt_subject", lambda token: decoded.append(token))
    app = FastAPI()
    app.add_middleware(CustomMiddleware)

    @app.get("/api/v1/dsh/models")
    async def models():
        return {"tenant": get_current_tenant_id(), "bypass": is_tenant_filter_bypassed()}

    @app.get("/api/v1/dsh/model-other")
    async def other():
        return {}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bisheng.example") as client:
        response = await client.get(
            "/api/v1/dsh/models",
            headers={"Authorization": "Bearer dsh-token"},
            cookies={"access_token_cookie": "browser-cookie"},
        )
        assert response.json() == {"tenant": None, "bypass": False}
        assert decoded == []
        await client.get("/api/v1/dsh/model-other", headers={"Authorization": "Bearer ordinary"})
        assert decoded
