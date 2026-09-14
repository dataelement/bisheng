from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.commercial_license.domain.services.aggregator import list_license_status


def _row(
    code: str,
    *,
    expire_date: date | None,
    days_remaining: int | None,
    display_state: str,
    checked_at: datetime,
):
    row = MagicMock()
    row.license_code = code
    row.expire_date = expire_date
    row.days_remaining = days_remaining
    row.display_state = display_state
    row.checked_at = checked_at
    row.source_status = None
    row.extra = {}
    return row


@pytest.mark.asyncio
async def test_recomputes_and_only_emits_known_codes():
    now = datetime(2026, 9, 14, 10, 0, 0)
    repo = AsyncMock()
    repo.get_all.return_value = [
        _row("gateway", expire_date=date(2026, 10, 14), days_remaining=99, display_state="normal", checked_at=now),
        _row("etl", expire_date=date(2026, 9, 30), days_remaining=99, display_state="normal", checked_at=now),
        _row("dashboard", expire_date=date(2026, 8, 1), days_remaining=1, display_state="expiring", checked_at=now),
        _row("subscription", expire_date=date(2026, 9, 15), days_remaining=1, display_state="expiring", checked_at=now),
    ]
    repo.get_by_code.return_value = repo.get_all.return_value[1]
    result = await list_license_status(now, repo=repo, etl_sync=None)
    codes = [item["license_code"] for item in result["licenses"]]
    assert codes == ["gateway", "etl", "dashboard"]
    by_code = {item["license_code"]: item for item in result["licenses"]}
    assert by_code["gateway"]["display_state"] == "expiring"
    assert by_code["gateway"]["days_remaining"] == 30
    assert by_code["etl"]["display_state"] == "expiring"
    assert by_code["dashboard"]["display_state"] == "expired"
    assert by_code["etl"]["license_name"] == "etl"


@pytest.mark.asyncio
async def test_missing_row_is_omitted():
    now = datetime(2026, 9, 14, 10, 0, 0)
    repo = AsyncMock()
    repo.get_all.return_value = []
    repo.get_by_code.return_value = None
    etl_sync = AsyncMock()
    result = await list_license_status(now, repo=repo, etl_sync=etl_sync)
    assert result["licenses"] == []
    etl_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_dashboard_row_is_read_without_http():
    now = datetime(2026, 9, 14, 10, 0, 0)
    repo = AsyncMock()
    repo.get_all.return_value = [
        _row("dashboard", expire_date=date(2026, 9, 30), days_remaining=16, display_state="expiring", checked_at=now),
    ]
    repo.get_by_code.return_value = None
    dashboard_http = AsyncMock()
    result = await list_license_status(now, repo=repo, etl_sync=AsyncMock(), dashboard_http=dashboard_http)
    dashboard_http.assert_not_awaited()
    assert result["licenses"][0]["license_code"] == "dashboard"


@pytest.mark.asyncio
async def test_stale_etl_triggers_sync_and_failure_keeps_old_row():
    now = datetime(2026, 9, 14, 10, 0, 0)
    stale = now - timedelta(hours=2)
    repo = AsyncMock()
    etl_row = _row("etl", expire_date=date(2026, 9, 30), days_remaining=16, display_state="expiring", checked_at=stale)
    repo.get_by_code.return_value = etl_row
    repo.get_all.return_value = [etl_row]
    etl_sync = AsyncMock(side_effect=TimeoutError("slow"))
    result = await list_license_status(now, repo=repo, etl_sync=etl_sync)
    etl_sync.assert_awaited_once()
    assert result["licenses"][0]["display_state"] == "expiring"
    assert result["licenses"][0]["days_remaining"] == 16
