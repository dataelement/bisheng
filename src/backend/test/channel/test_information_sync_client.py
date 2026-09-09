from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.channel import BishengInformationServiceError
from bisheng.core.config.settings import IntelligenceCenterConf
from bisheng.core.external.bisheng_information_client.client import BishengInformationClient


def _response(data=None, *, total=0, page=1, page_size=100, code=200, status=200):
    return SimpleNamespace(
        status_code=status,
        body={
            "code": code,
            "data": data if data is not None else [],
            "currentPage": page,
            "PageSize": page_size,
            "totalCount": total,
        },
    )


def _subscription(source_id: str) -> dict:
    return {
        "id": source_id,
        "source_id": f"external-{source_id}",
        "business_type": "website",
        "name": source_id,
        "follow_num": 1,
        "subscribed_at": 1,
        "last_sync_at": 2,
        "article_list_updated_at": 3,
    }


async def test_list_all_subscriptions_validates_and_collects_every_page():
    http_client = SimpleNamespace(
        get=AsyncMock(
            side_effect=[
                _response([_subscription("A")], total=2, page=1, page_size=1),
                _response([_subscription("B")], total=2, page=2, page_size=1),
            ]
        )
    )
    client = BishengInformationClient(
        http_client=http_client,
        get_conf=lambda: IntelligenceCenterConf(base_url="http://information.test", api_key="secret"),
    )

    result = await client.list_all_subscriptions(page_size=1)

    assert [item.id for item in result] == ["A", "B"]
    assert http_client.get.await_count == 2


@pytest.mark.parametrize(
    "responses",
    [
        [_response([_subscription("A")], total=2, page=1), _response([], total=3, page=2)],
        [_response([_subscription("A")], total=2, page=1), _response([_subscription("A")], total=2, page=2)],
        [_response([_subscription("A")], total=2, page=2)],
        [_response([], total=0, code=500)],
    ],
)
async def test_list_all_subscriptions_rejects_incomplete_snapshots(responses):
    client = BishengInformationClient(
        http_client=SimpleNamespace(get=AsyncMock(side_effect=responses)),
        get_conf=lambda: IntelligenceCenterConf(base_url="http://information.test", api_key="secret"),
    )

    with pytest.raises(BishengInformationServiceError) as exc:
        await client.list_all_subscriptions()

    assert "secret" not in str(exc.value)


async def test_single_source_mutations_and_dynamic_key():
    current_key = "key-one"
    http_client = SimpleNamespace(post=AsyncMock(return_value=_response()))
    client = BishengInformationClient(
        http_client=http_client,
        get_conf=lambda: IntelligenceCenterConf(base_url="http://information.test", api_key=current_key),
    )

    await client.subscribe_one("A")
    current_key = "key-two"
    await client.unsubscribe_one("A")

    first = http_client.post.await_args_list[0]
    second = http_client.post.await_args_list[1]
    assert first.kwargs["body"] == {"information_ids": ["A"]}
    assert first.kwargs["headers"]["X-API-Key"] == "key-one"
    assert second.kwargs["body"] == {"information_ids": ["A"]}
    assert second.kwargs["headers"]["X-API-Key"] == "key-two"


async def test_get_information_articles_page_is_async_and_preserves_boundary():
    body = _response(
        {
            "information": _subscription("A"),
            "articles": [
                {
                    "id": "article-1",
                    "title": "one",
                    "original_url": "https://example.test/one",
                    "create_time": "2026-08-26T01:02:03+00:00",
                }
            ],
        },
        total=1,
        page=2,
        page_size=10,
    )
    http_client = SimpleNamespace(get=AsyncMock(return_value=body))
    client = BishengInformationClient(
        http_client=http_client,
        get_conf=lambda: IntelligenceCenterConf(base_url="http://information.test", api_key="secret"),
    )

    result = await client.get_information_articles_page("A", min_create_time=123, page=2, page_size=10)

    assert result.total == 1
    assert result.articles[0].id == "article-1"
    assert http_client.get.await_args.kwargs["params"] == {
        "return_information": False,
        "page": 2,
        "page_size": 10,
        "min_create_time": 123,
    }
