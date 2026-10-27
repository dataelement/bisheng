"""F051 T020: one stable base URL, wherever the platform is deployed.

AC-30 is "single and stable": not per tenant, not per key, not per deployment
form. The three resolution sources are already covered for skill packs; what is
asserted here is that the model face's URL is derived from the same one place
and that two different credentials get the same answer.
"""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from bisheng.common.services.config_service import settings
from bisheng.open_api.domain.services.public_base_url import MODEL_GATEWAY_BASE_PATH, model_gateway_base_url
from test.open_api.model_gateway_fixtures import service_account_principal


class _FakeRequest:
    def __init__(self, headers: dict, scheme: str = "http"):
        self.headers = headers
        self.scope = {"root_path": "", "server": ("10.0.0.5", 7860)}
        self.url = type("U", (), {"scheme": scheme})()


@pytest.fixture(autouse=True)
def _no_configured_base_url(monkeypatch):
    monkeypatch.setattr(settings.open_api, "public_base_url", "")


def test_the_operator_declared_address_wins(monkeypatch):
    monkeypatch.setattr(settings.open_api, "public_base_url", "https://portal.example.com/bisheng")

    assert model_gateway_base_url(_FakeRequest({})) == (f"https://portal.example.com/bisheng{MODEL_GATEWAY_BASE_PATH}")


def test_the_reverse_proxy_headers_are_used_next():
    url = model_gateway_base_url(_FakeRequest({"x-forwarded-proto": "https", "x-forwarded-host": "kb.example.com"}))

    assert url == f"https://kb.example.com{MODEL_GATEWAY_BASE_PATH}"


def test_the_host_header_is_the_last_resort():
    url = model_gateway_base_url(_FakeRequest({"host": "192.168.106.114:3001"}))

    assert url == f"http://192.168.106.114:3001{MODEL_GATEWAY_BASE_PATH}"


def test_the_url_keeps_the_v1_segment_and_has_no_trailing_slash():
    url = model_gateway_base_url(_FakeRequest({"host": "kb.example.com"}))

    # Most engines treat "ends with /v1" as the check for an OpenAI-compatible
    # address, and official clients append only /chat/completions or /models.
    assert url.endswith("/api/v2/model/v1")
    assert not url.endswith("/")


async def test_whoami_hands_every_key_the_same_address(monkeypatch):
    from bisheng.main import app

    monkeypatch.setattr(settings.open_platform, "enabled", True)
    monkeypatch.setattr(settings.open_api, "public_base_url", "https://kb.example.com")
    monkeypatch.setattr(
        "bisheng.open_api.domain.repositories.credential_repository.CredentialRepository.get",
        AsyncMock(return_value=None),
    )

    urls = set()
    for tenant_id, credential_id in ((9, 7), (11, 8)):
        monkeypatch.setattr(
            "bisheng.open_api.api.dependencies.validate_bearer",
            AsyncMock(return_value=service_account_principal(tenant_id=tenant_id, credential_id=credential_id)),
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v2/auth/whoami", headers={"Authorization": "Bearer x"})
        urls.add(response.json()["data"]["model_base_url"])

    assert urls == {"https://kb.example.com/api/v2/model/v1"}


async def test_whoami_reports_no_address_where_the_face_is_not_deployed(monkeypatch):
    from bisheng.main import app

    monkeypatch.setattr(settings.open_platform, "enabled", False)
    monkeypatch.setattr(
        "bisheng.open_api.domain.repositories.credential_repository.CredentialRepository.get",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal()),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v2/auth/whoami", headers={"Authorization": "Bearer x"})

    assert response.json()["data"]["model_base_url"] == ""
