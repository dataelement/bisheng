"""Unit tests for FGAClient dual-model shadow write (F013 T05).

Verifies:
- write_tuples sends one POST when legacy_model_id is None
- write_tuples sends two POSTs when legacy_model_id is set
- Shadow write failure is swallowed (logged) and does not raise
- Primary write failure still raises FGAWriteError
- check() ignores legacy_model_id (always uses self._model_id)
"""

from unittest.mock import AsyncMock

import pytest

from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.exceptions import (
    FGAClientError,
    FGAConnectionError,
    FGAWriteError,
)


@pytest.fixture
def primary_only_client():
    return FGAClient(
        api_url='http://localhost:8080',
        store_id='store-1',
        model_id='model-new',
    )


@pytest.fixture
def dual_client():
    return FGAClient(
        api_url='http://localhost:8080',
        store_id='store-1',
        model_id='model-new',
        legacy_model_id='model-old',
    )


WRITES = [{'user': 'user:7', 'relation': 'owner', 'object': 'workflow:abc'}]


@pytest.mark.asyncio
async def test_write_tuples_single_post_when_no_legacy(primary_only_client):
    """No legacy → exactly one POST to /write with primary model id."""
    primary_only_client._post = AsyncMock(return_value={})
    await primary_only_client.write_tuples(writes=WRITES)

    primary_only_client._post.assert_called_once()
    path, body = primary_only_client._post.call_args.args
    assert path == '/stores/store-1/write'
    assert body['authorization_model_id'] == 'model-new'


@pytest.mark.asyncio
async def test_write_tuples_double_post_when_legacy_set(dual_client):
    """Legacy set → two POSTs, second carries legacy model id."""
    dual_client._post = AsyncMock(return_value={})
    await dual_client.write_tuples(writes=WRITES)

    assert dual_client._post.call_count == 2
    first_body = dual_client._post.call_args_list[0].args[1]
    second_body = dual_client._post.call_args_list[1].args[1]
    assert first_body['authorization_model_id'] == 'model-new'
    assert second_body['authorization_model_id'] == 'model-old'
    # Tuples are identical in both
    assert first_body['writes'] == second_body['writes']


@pytest.mark.asyncio
async def test_write_tuples_legacy_failure_swallowed(dual_client):
    """Shadow write failing must not propagate."""
    call_count = {'n': 0}

    async def side_effect(path, body):
        call_count['n'] += 1
        if call_count['n'] == 2:
            raise FGAClientError('legacy 500')
        return {}

    dual_client._post = AsyncMock(side_effect=side_effect)
    await dual_client.write_tuples(writes=WRITES)  # must not raise
    assert call_count['n'] == 2


@pytest.mark.asyncio
async def test_write_tuples_primary_failure_raises(dual_client):
    """Primary write failure raises FGAWriteError; shadow not attempted."""
    dual_client._post = AsyncMock(side_effect=FGAClientError('primary 500'))
    with pytest.raises(FGAWriteError):
        await dual_client.write_tuples(writes=WRITES)
    # Only the primary call attempted
    assert dual_client._post.call_count == 1


@pytest.mark.asyncio
async def test_write_tuples_primary_connection_error_raises(dual_client):
    """Connection errors propagate as-is (fail-closed)."""
    dual_client._post = AsyncMock(side_effect=FGAConnectionError('unreachable'))
    with pytest.raises(FGAConnectionError):
        await dual_client.write_tuples(writes=WRITES)
    assert dual_client._post.call_count == 1


@pytest.mark.asyncio
async def test_write_tuples_empty_inputs_is_noop(dual_client):
    """No writes nor deletes → no POST."""
    dual_client._post = AsyncMock()
    await dual_client.write_tuples()
    dual_client._post.assert_not_called()


@pytest.mark.asyncio
async def test_check_ignores_legacy_model(dual_client):
    """check() must always use the primary model id (AD-04)."""
    dual_client._post = AsyncMock(return_value={'allowed': True})
    await dual_client.check(user='user:1', relation='viewer', object='workflow:abc')
    body = dual_client._post.call_args.args[1]
    assert body['authorization_model_id'] == 'model-new'
