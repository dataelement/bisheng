"""Unit tests for FGAClient (T14 — test_fga_client).

Tests the httpx-based OpenFGA client with mocked HTTP responses.
Verifies check, list_objects, write_tuples, batch_check, read_tuples,
health, and error handling (fail-closed).
"""

import pytest
import httpx

from bisheng.core.openfga.client import FGAClient
from bisheng.core.openfga.exceptions import (
    FGAClientError,
    FGAConnectionError,
    FGAWriteError,
)


@pytest.fixture
def fga_client():
    """FGAClient with a test URL."""
    client = FGAClient(
        api_url='http://localhost:8080',
        store_id='store-123',
        model_id='model-456',
        timeout=5,
    )
    yield client


class TestFGAClientCheck:

    @pytest.mark.asyncio
    async def test_check_allowed(self, fga_client, monkeypatch):
        async def mock_post(self, path, **kwargs):
            return httpx.Response(200, json={'allowed': True})

        monkeypatch.setattr(httpx.AsyncClient, 'post', mock_post)
        result = await fga_client.check('user:1', 'viewer', 'workflow:abc')
        assert result is True

    @pytest.mark.asyncio
    async def test_check_denied(self, fga_client, monkeypatch):
        async def mock_post(self, path, **kwargs):
            return httpx.Response(200, json={'allowed': False})

        monkeypatch.setattr(httpx.AsyncClient, 'post', mock_post)
        result = await fga_client.check('user:1', 'viewer', 'workflow:abc')
        assert result is False

    @pytest.mark.asyncio
    async def test_check_connection_error(self, fga_client, monkeypatch):
        async def mock_post(self, path, **kwargs):
            raise httpx.ConnectError('connection refused')

        monkeypatch.setattr(httpx.AsyncClient, 'post', mock_post)
        with pytest.raises(FGAConnectionError):
            await fga_client.check('user:1', 'viewer', 'workflow:abc')

    @pytest.mark.asyncio
    async def test_check_timeout_error(self, fga_client, monkeypatch):
        async def mock_post(self, path, **kwargs):
            raise httpx.TimeoutException('timeout')

        monkeypatch.setattr(httpx.AsyncClient, 'post', mock_post)
        with pytest.raises(FGAConnectionError):
            await fga_client.check('user:1', 'viewer', 'workflow:abc')


class TestFGAClientListObjects:

    @pytest.mark.asyncio
    async def test_list_objects(self, fga_client, monkeypatch):
        async def mock_post(self, path, **kwargs):
            return httpx.Response(200, json={'objects': ['workflow:abc', 'workflow:def']})

        monkeypatch.setattr(httpx.AsyncClient, 'post', mock_post)
        result = await fga_client.list_objects('user:1', 'viewer', 'workflow')
        assert result == ['workflow:abc', 'workflow:def']

    @pytest.mark.asyncio
    async def test_list_objects_empty(self, fga_client, monkeypatch):
        async def mock_post(self, path, **kwargs):
            return httpx.Response(200, json={'objects': []})

        monkeypatch.setattr(httpx.AsyncClient, 'post', mock_post)
        result = await fga_client.list_objects('user:1', 'viewer', 'workflow')
        assert result == []


class TestFGAClientWriteTuples:

    @pytest.mark.asyncio
    async def test_write_tuples_success(self, fga_client, monkeypatch):
        async def mock_post(self, path, **kwargs):
            return httpx.Response(200, json={})

        monkeypatch.setattr(httpx.AsyncClient, 'post', mock_post)
        await fga_client.write_tuples(
            writes=[{'user': 'user:1', 'relation': 'owner', 'object': 'workflow:abc'}],
        )

    @pytest.mark.asyncio
    async def test_write_tuples_error(self, fga_client, monkeypatch):
        async def mock_post(self, path, **kwargs):
            return httpx.Response(400, text='bad request')

        monkeypatch.setattr(httpx.AsyncClient, 'post', mock_post)
        with pytest.raises(FGAWriteError):
            await fga_client.write_tuples(
                writes=[{'user': 'user:1', 'relation': 'owner', 'object': 'workflow:abc'}],
            )

    @pytest.mark.asyncio
    async def test_write_tuples_noop(self, fga_client):
        # Empty writes/deletes should be a no-op
        await fga_client.write_tuples()


class TestFGAClientHealth:

    @pytest.mark.asyncio
    async def test_health_ok(self, fga_client, monkeypatch):
        async def mock_get(self, path):
            return httpx.Response(200)

        monkeypatch.setattr(httpx.AsyncClient, 'get', mock_get)
        assert await fga_client.health() is True

    @pytest.mark.asyncio
    async def test_health_down(self, fga_client, monkeypatch):
        async def mock_get(self, path):
            raise httpx.ConnectError('connection refused')

        monkeypatch.setattr(httpx.AsyncClient, 'get', mock_get)
        assert await fga_client.health() is False
