"""F048 OpenFGA client pin, consistency, and atomic limit contracts.

覆盖 AC: AC-30, AC-31, AC-32, AC-34, AC-69, AC-109, AC-111, AC-112,
AC-160, AC-161, AC-162, AC-163, AC-168, AC-169, AC-170, AC-171
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.permission import PermissionMutationTooLargeError
from bisheng.core.openfga.client import (
    BUSINESS_ATOMIC_TUPLE_LIMIT,
    BUSINESS_BATCH_CHECK_LIMIT,
    OPENFGA_BATCH_CHECK_LIMIT,
    OPENFGA_WRITE_TUPLE_LIMIT,
    FGAClient,
)
from bisheng.core.openfga.exceptions import (
    FGAClientError,
    FGAConnectionError,
    FGAWriteError,
)


@pytest.fixture
def client() -> FGAClient:
    return FGAClient(
        api_url="http://openfga:8080",
        store_id="store-1",
        model_id="model-f048",
    )


@pytest.mark.asyncio
async def test_check_batch_and_list_are_model_scoped_with_consistency(
    client: FGAClient,
) -> None:
    client._post = AsyncMock(
        side_effect=[
            {"allowed": True},
            {
                "result": {
                    "0": {"allowed": True},
                    "1": {"allowed": False},
                }
            },
            {"objects": ["workflow:w1"]},
        ]
    )
    assert await client.check(
        user="user:7",
        relation="can_edit",
        object="workflow:w1",
        consistency="HIGHER_CONSISTENCY",
    )
    assert await client.batch_check(
        [
            {
                "user": "user:7",
                "relation": "can_edit",
                "object": "workflow:w1",
            },
            {
                "user": "user:7",
                "relation": "can_edit",
                "object": "workflow:w2",
            },
        ],
        consistency="HIGHER_CONSISTENCY",
    ) == [True, False]
    assert await client.list_objects(
        user="user:7",
        relation="can_edit",
        type="workflow",
        consistency="HIGHER_CONSISTENCY",
    ) == ["workflow:w1"]

    for call in client._post.call_args_list:
        body = call.args[1]
        assert body["authorization_model_id"] == "model-f048"
        assert body["consistency"] == "HIGHER_CONSISTENCY"


@pytest.mark.asyncio
async def test_stream_list_objects_consumes_normal_end_and_preserves_model_pin(
    client: FGAClient,
) -> None:
    captured = {}

    async def stream(path, body):
        captured.update(path=path, body=body)
        yield {"result": {"object": "workflow:w1"}}
        yield {"result": {"object": "workflow:w1"}}
        yield {"result": {"object": "workflow:w2"}}

    client._streamed_post = stream

    assert await client.stream_list_objects(
        user="user:7",
        relation="visible",
        type="workflow",
        consistency="HIGHER_CONSISTENCY",
    ) == ("workflow:w1", "workflow:w1", "workflow:w2")
    assert captured["path"] == "/stores/store-1/streamed-list-objects"
    assert captured["body"] == {
        "user": "user:7",
        "relation": "visible",
        "type": "workflow",
        "authorization_model_id": "model-f048",
        "consistency": "HIGHER_CONSISTENCY",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    (
        FGAConnectionError("deadline"),
        FGAClientError("service error"),
    ),
)
async def test_stream_list_objects_never_returns_prefix_after_error(
    client: FGAClient,
    error: Exception,
) -> None:
    async def stream(path, body):
        del path, body
        yield {"object": "workflow:prefix"}
        raise error

    client._streamed_post = stream

    with pytest.raises(type(error), match=str(error)):
        await client.stream_list_objects(
            user="user:7",
            relation="visible",
            type="workflow",
        )


@pytest.mark.asyncio
async def test_stream_list_objects_propagates_cancellation_without_prefix(
    client: FGAClient,
) -> None:
    async def stream(path, body):
        del path, body
        yield {"object": "workflow:prefix"}
        raise asyncio.CancelledError

    client._streamed_post = stream

    with pytest.raises(asyncio.CancelledError):
        await client.stream_list_objects(
            user="user:7",
            relation="visible",
            type="workflow",
        )


@pytest.mark.asyncio
async def test_batch_check_splits_business_batch_at_openfga_limit(
    client: FGAClient,
) -> None:
    checks = [
        {
            "user": "user:7",
            "relation": "can_edit",
            "object": f"workflow:w{index}",
        }
        for index in range(BUSINESS_BATCH_CHECK_LIMIT)
    ]
    client._post = AsyncMock(
        side_effect=[
            {"result": {str(index): {"allowed": index % 2 == 0} for index in range(OPENFGA_BATCH_CHECK_LIMIT)}},
            {"result": {str(index): {"allowed": index % 2 == 1} for index in range(OPENFGA_BATCH_CHECK_LIMIT)}},
        ]
    )

    result = await client.batch_check(
        checks,
        consistency="HIGHER_CONSISTENCY",
    )

    assert len(result) == BUSINESS_BATCH_CHECK_LIMIT
    assert result[:OPENFGA_BATCH_CHECK_LIMIT] == [index % 2 == 0 for index in range(OPENFGA_BATCH_CHECK_LIMIT)]
    assert result[OPENFGA_BATCH_CHECK_LIMIT:] == [index % 2 == 1 for index in range(OPENFGA_BATCH_CHECK_LIMIT)]
    assert client._post.await_count == 2
    assert all(len(call.args[1]["checks"]) == OPENFGA_BATCH_CHECK_LIMIT for call in client._post.call_args_list)


@pytest.mark.asyncio
async def test_batch_check_rejects_more_than_business_limit(
    client: FGAClient,
) -> None:
    checks = [
        {
            "user": "user:7",
            "relation": "can_edit",
            "object": f"workflow:w{index}",
        }
        for index in range(BUSINESS_BATCH_CHECK_LIMIT + 1)
    ]

    with pytest.raises(
        FGAClientError,
        match=f"exceeds {BUSINESS_BATCH_CHECK_LIMIT}",
    ):
        await client.batch_check(checks)


@pytest.mark.asyncio
async def test_read_is_store_scoped_and_delete_uses_only_tuple_keys(
    client: FGAClient,
) -> None:
    client._post = AsyncMock(
        side_effect=[
            {
                "tuples": [
                    {
                        "key": {
                            "user": "user:7",
                            "relation": "owner",
                            "object": "workflow:w1",
                        }
                    }
                ]
            },
            {},
        ]
    )
    rows = await client.read_tuples(
        object="workflow:w1",
        consistency="HIGHER_CONSISTENCY",
    )
    assert rows == [
        {
            "user": "user:7",
            "relation": "owner",
            "object": "workflow:w1",
        }
    ]
    read_path, read_body = client._post.call_args_list[0].args
    assert read_path == "/stores/store-1/read"
    assert "authorization_model_id" not in read_body
    assert read_body["consistency"] == "HIGHER_CONSISTENCY"

    await client.delete_tuples_store_scoped(rows)
    write_path, write_body = client._post.call_args_list[1].args
    assert write_path == "/stores/store-1/write"
    assert write_body["authorization_model_id"] == "model-f048"
    assert write_body["deletes"]["tuple_keys"] == rows
    assert all("authorization_model_id" not in row for row in rows)


@pytest.mark.asyncio
async def test_unfiltered_read_omits_empty_tuple_key(
    client: FGAClient,
) -> None:
    client._post = AsyncMock(return_value={"tuples": []})

    assert await client.read_tuples() == []

    read_path, read_body = client._post.call_args.args
    assert read_path == "/stores/store-1/read"
    assert read_body == {"page_size": 100}


@pytest.mark.asyncio
async def test_authorization_model_inventory_is_store_scoped_and_paginated(
    client: FGAClient,
) -> None:
    client._get = AsyncMock(
        side_effect=[
            {
                "authorization_models": [{"id": "model-a"}],
                "continuation_token": "next page",
            },
            {
                "authorization_models": [{"id": "model-b"}],
            },
        ]
    )

    assert await client.list_authorization_models() == [
        {"id": "model-a"},
        {"id": "model-b"},
    ]
    paths = [call.args[0] for call in client._get.call_args_list]
    assert paths[0] == "/stores/store-1/authorization-models?page_size=100"
    assert "continuation_token=next+page" in paths[1]


@pytest.mark.asyncio
async def test_write_is_single_model_and_enforces_openfga_limit(
    client: FGAClient,
) -> None:
    client._post = AsyncMock(return_value={})
    tuples = [
        {
            "user": f"user:{index}",
            "relation": "ordinary_assignee",
            "object": "permission_grant:g1",
        }
        for index in range(OPENFGA_WRITE_TUPLE_LIMIT)
    ]
    await client.write_tuples(writes=tuples)
    client._post.assert_called_once()
    body = client._post.call_args.args[1]
    assert body["authorization_model_id"] == "model-f048"
    assert "on_duplicate" not in body["writes"]

    with pytest.raises(FGAWriteError):
        await client.write_tuples(writes=tuples, deletes=[tuples[0]])
    assert client._post.call_count == 1


@pytest.mark.asyncio
async def test_write_can_ignore_duplicate_tuples_for_reconciliation(
    client: FGAClient,
) -> None:
    client._post = AsyncMock(return_value={})
    relationship = {
        "user": "department:7#member",
        "relation": "visible",
        "object": "knowledge_space:42",
    }

    await client.write_tuples(
        writes=[relationship],
        ignore_duplicate_writes=True,
    )

    body = client._post.call_args.args[1]
    assert body["writes"] == {
        "tuple_keys": [relationship],
        "on_duplicate": "ignore",
    }


def test_business_atomic_limit_is_stricter_than_service_limit() -> None:
    assert BUSINESS_ATOMIC_TUPLE_LIMIT == 90
    assert OPENFGA_WRITE_TUPLE_LIMIT == 100
    FGAClient.validate_business_mutation_size(90)
    with pytest.raises(PermissionMutationTooLargeError):
        FGAClient.validate_business_mutation_size(91)


def test_client_rejects_missing_or_legacy_runtime_model() -> None:
    with pytest.raises(ValueError):
        FGAClient(
            api_url="http://openfga:8080",
            store_id="",
            model_id="model-f048",
        )
    with pytest.raises(ValueError):
        FGAClient(
            api_url="http://openfga:8080",
            store_id="store-1",
            model_id="",
        )
    with pytest.raises(TypeError):
        FGAClient(
            api_url="http://openfga:8080",
            store_id="store-1",
            model_id="model-f048",
            legacy_model_id="model-old",
        )


def test_for_model_reuses_store_without_a_legacy_client(client: FGAClient) -> None:
    migration_client = client.for_model("model-target")
    assert migration_client.store_id == client.store_id
    assert migration_client.model_id == "model-target"
    assert migration_client is not client


@pytest.mark.asyncio
async def test_read_filter_requires_an_object_type(
    client: FGAClient,
) -> None:
    """A filtered Read without an object type is rejected before it is sent.

    OpenFGA answers such a filter with a generic validation_error. The Catalog
    publish path issued one at its final commit step, so the failure only showed
    up as a 500 after the whole publish had already run.
    """

    client._post = AsyncMock()

    with pytest.raises(ValueError, match="object type"):
        await client.read_tuples(user="user:*", relation="active")

    with pytest.raises(ValueError, match="object type"):
        await client.read_tuples(object="permission_catalog_release")

    client._post.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_filter_requires_an_object_id_or_a_user(
    client: FGAClient,
) -> None:
    """A type-only object filter is legal only when a user narrows it."""

    client._post = AsyncMock()
    with pytest.raises(ValueError, match="object id or a user"):
        await client.read_tuples(object="permission_model_release:")
    client._post.assert_not_awaited()

    client._post = AsyncMock(return_value={"tuples": []})
    assert await client.read_tuples(object="permission_model_release:", user="user:*") == []
    _, body = client._post.call_args.args
    assert body["tuple_key"] == {
        "user": "user:*",
        "object": "permission_model_release:",
    }
