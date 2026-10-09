"""Capacity is enforced at the authoritative Gateway batch command."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError, DshSeatLimitReachedError
from bisheng.dsh.domain.services.seat_allocation import allocate_seats


@pytest.mark.parametrize(
    "status,code,error",
    [("FAILED", "seat_limit_reached", DshSeatLimitReachedError), ("PENDING", None, DshAuthorizationUnavailableError)],
)
async def test_batch_results_are_explicit(status, code, error):
    gateway = SimpleNamespace(
        request=AsyncMock(return_value={"operation_id": "op", "status": status, "result_code": code})
    )
    with pytest.raises(error):
        await allocate_seats(gateway, "op", {}, 2, list(range(15)))


async def test_success_requires_matching_receipt_and_member_count():
    gateway = SimpleNamespace(
        request=AsyncMock(return_value={"operation_id": "other", "status": "SUCCEEDED", "selected": 1})
    )
    with pytest.raises(DshAuthorizationUnavailableError):
        await allocate_seats(gateway, "op", {}, 2, [20])
