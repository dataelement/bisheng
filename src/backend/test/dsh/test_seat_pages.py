"""All-seat pagination keeps filter and tenant boundaries across both states."""

from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.dsh import DshInvalidRequestError
from bisheng.dsh.domain.services.seat_pages import read_seat_page


async def read(request, **patch):
    return await read_seat_page(
        request,
        **dict(
            actor={"user_id": "1"},
            target={"tenant_id": "2"},
            cursor=None,
            limit=2,
            keyword=None,
            seat_state=None,
            login_state=None,
            **patch,
        ),
    )


@pytest.mark.parametrize("assigned,revoked,limit", [(3, 3, 2), (2, 1, 2), (0, 3, 2), (1, 1, 2), (0, 0, 2)])
async def test_all_pagination(assigned, revoked, limit):
    async def request(_, payload):
        data = list(range(assigned)) if payload["seat_state"] == "ASSIGNED" else list(range(100, 100 + revoked))
        start = int(payload["cursor"] or 0)
        end = start + payload["limit"]
        return {
            "items": data[start:end],
            "has_more": end < len(data),
            "next_cursor": str(end) if end < len(data) else None,
        }

    cursor = None
    found = []
    for _ in range(10):
        page = await read_seat_page(
            request, actor={}, target={}, cursor=cursor, limit=limit, keyword=None, seat_state=None, login_state=None
        )
        assert len(page["items"]) <= limit
        found += page["items"]
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert found == list(range(assigned)) + list(range(100, 100 + revoked))


async def test_cursor_bound_to_tenant_and_filters():
    request = AsyncMock(return_value={"items": [1], "has_more": True, "next_cursor": "next"})
    page = await read(request)
    for patch in [{"target": {"tenant_id": "3"}}, {"keyword": "different"}, {"login_state": "NO_SESSIONS"}]:
        args = {
            "actor": {"user_id": "1"},
            "target": {"tenant_id": "2"},
            "cursor": page["next_cursor"],
            "limit": 2,
            "keyword": None,
            "seat_state": None,
            "login_state": None,
        }
        args.update(patch)
        with pytest.raises(DshInvalidRequestError):
            await read_seat_page(request, **args)
    assert request.await_count == 1
