# ruff: noqa: RUF002
"""带水印下载 API：禁止再出现「调用未定义 helper」的重复路由覆盖。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.qa_expert.api import endpoints
from bisheng.qa_expert.api.router import router


def _user():
    return SimpleNamespace(user_id=1, user_name="tester", tenant_id=1)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = _user
    return TestClient(app)


def test_watermarked_download_helper_is_defined_once():
    """feat/2.5.0-sg 曾合并出重复 GET，后者调用未定义的 _build_watermarked_download_response。"""
    assert callable(endpoints._build_watermarked_download_response)
    assert callable(endpoints.download_watermarked_asset)
    assert callable(endpoints.download_watermarked_asset_post)


def test_get_and_post_watermarked_download_use_shared_helper():
    client = _client()
    helper = AsyncMock(
        return_value=Response(
            content=b"%PDF-1.4",
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="qa-asset.pdf"'},
        )
    )
    with patch.object(endpoints, "_build_watermarked_download_response", new=helper):
        get_resp = client.get(
            "/api/v1/qa_experts/assets/watermarked-download",
            params={"source": "tmp-dir/a.pdf", "title": "说明.pdf"},
        )
        assert get_resp.status_code == 200
        assert get_resp.content.startswith(b"%PDF")
        helper.assert_awaited()
        assert helper.await_args.args[0] == "tmp-dir/a.pdf"

        helper.reset_mock()
        post_resp = client.post(
            "/api/v1/qa_experts/assets/watermarked-download",
            json={"source": "tmp-dir/b.pdf", "title": "附件.pdf"},
        )
        assert post_resp.status_code == 200
        assert post_resp.content.startswith(b"%PDF")
        helper.assert_awaited()
        assert helper.await_args.args[0] == "tmp-dir/b.pdf"
