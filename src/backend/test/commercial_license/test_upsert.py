from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest

from bisheng.commercial_license.domain.services.upsert import (
    keep_previous_on_fetch_failure,
    upsert_mapped,
)
from bisheng.common.errcode.commercial_license import CommercialLicenseInvalidPayloadError


def _mapped(code: str = "gateway") -> dict:
    return {
        "license_code": code,
        "expire_date": date(2026, 9, 30),
        "days_remaining": 16,
        "display_state": "expiring",
        "source_status": "warning",
        "extra": {"version": "trial"},
    }


@pytest.mark.asyncio
async def test_second_upsert_overwrites_same_code():
    repo = AsyncMock()
    first = _mapped()
    second = {**_mapped(), "days_remaining": 10, "display_state": "expiring"}
    await upsert_mapped(repo, first)
    await upsert_mapped(repo, second)
    assert repo.upsert.await_count == 2
    assert repo.upsert.await_args_list[1].args[0].days_remaining == 10


@pytest.mark.asyncio
async def test_illegal_code_is_rejected():
    repo = AsyncMock()
    with pytest.raises(CommercialLicenseInvalidPayloadError):
        await upsert_mapped(repo, _mapped("subscription"))
    repo.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_keep_previous_does_not_write():
    repo = AsyncMock()
    keep_previous_on_fetch_failure("etl")
    repo.upsert.assert_not_awaited()
    repo.get_by_code.assert_not_awaited()


@pytest.mark.asyncio
async def test_keep_previous_does_not_clear_existing_row():
    existing = AsyncMock()
    existing.display_state = "expiring"
    existing.expire_date = date(2026, 9, 30)
    existing.checked_at = datetime(2026, 9, 13)
    repo = AsyncMock()
    repo.get_by_code.return_value = existing
    keep_previous_on_fetch_failure("etl")
    assert existing.display_state == "expiring"
    assert existing.expire_date == date(2026, 9, 30)
    repo.upsert.assert_not_awaited()
