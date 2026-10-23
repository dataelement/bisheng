from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.commercial_license.domain.services.etl_sync import etl_license_info_url, sync_etl_license


def test_strips_predict_path_to_origin():
    assert etl_license_info_url("http://host:8000/v1/etl4llm/predict") == "http://host:8000/api/license_info"


def test_empty_url_returns_none():
    assert etl_license_info_url("") is None
    assert etl_license_info_url(None) is None


@pytest.mark.asyncio
async def test_empty_url_does_not_request_or_insert():
    repo = AsyncMock()
    http_get = AsyncMock()
    await sync_etl_license(repo, etl_url="", http_get=http_get)
    http_get.assert_not_awaited()
    repo.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_500_keeps_previous_row():
    repo = AsyncMock()
    existing = MagicMock()
    existing.display_state = "expiring"
    existing.expire_date = "keep"
    repo.get_by_code.return_value = existing
    http_get = AsyncMock(return_value=MagicMock(status_code=500, body={}, error="server"))
    await sync_etl_license(repo, etl_url="http://host:8000/v1/etl4llm/predict", http_get=http_get)
    repo.upsert.assert_not_awaited()
    assert existing.display_state == "expiring"


@pytest.mark.asyncio
async def test_status_fail_keeps_previous_row():
    repo = AsyncMock()
    http_get = AsyncMock(return_value=MagicMock(status_code=200, body={"status": "fail"}, error=None))
    await sync_etl_license(repo, etl_url="http://host:8000/predict", http_get=http_get)
    repo.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_keeps_previous_row():
    repo = AsyncMock()
    http_get = AsyncMock(side_effect=TimeoutError("timeout"))
    await sync_etl_license(repo, etl_url="http://host:8000/predict", http_get=http_get)
    repo.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_upserts_etl_row():
    repo = AsyncMock()
    http_get = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            body={
                "license_type": "trial",
                "expiration_time": 1851379200,
                "remaining_days": 16,
                "expired": False,
                "usable": True,
                "disabled": False,
            },
            error=None,
        )
    )
    await sync_etl_license(repo, etl_url="http://host:8000/v1/etl4llm/predict", http_get=http_get)
    http_get.assert_awaited_once()
    assert http_get.await_args.args[0] == "http://host:8000/api/license_info"
    repo.upsert.assert_awaited_once()
    row = repo.upsert.await_args.args[0]
    assert row.license_code == "etl"
    assert row.days_remaining == 16
