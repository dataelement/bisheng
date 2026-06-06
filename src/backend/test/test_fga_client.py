"""Unit tests for FGAClient (T14 — test_fga_client).

Tests the httpx-based OpenFGA client with mocked HTTP responses.
Verifies check, list_objects, write_tuples, batch_check, read_tuples,
health, and error handling (fail-closed).
"""

import asyncio

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


class TestFGAClientReadTuplesCache:

    @pytest.mark.asyncio
    async def test_read_tuples_uses_ttl_cache_for_same_filter(self, fga_client, monkeypatch):
        calls = 0

        async def fake_post(path, body):
            nonlocal calls
            calls += 1
            return {
                'tuples': [
                    {
                        'key': {
                            'user': 'user:7',
                            'relation': 'viewer',
                            'object': body['tuple_key']['object'],
                        }
                    }
                ]
            }

        monkeypatch.setattr(fga_client, '_post', fake_post)

        first = await fga_client.read_tuples(object='knowledge_file:120')
        first[0]['relation'] = 'mutated'
        second = await fga_client.read_tuples(object='knowledge_file:120')

        assert calls == 1
        assert second == [
            {'user': 'user:7', 'relation': 'viewer', 'object': 'knowledge_file:120'}
        ]

    @pytest.mark.asyncio
    async def test_read_tuples_refreshes_after_ttl_expiry(self, fga_client, monkeypatch):
        calls = 0

        async def fake_post(path, body):
            nonlocal calls
            calls += 1
            return {
                'tuples': [
                    {
                        'key': {
                            'user': f'user:{calls}',
                            'relation': 'viewer',
                            'object': body['tuple_key']['object'],
                        }
                    }
                ]
            }

        fga_client._read_tuple_cache_ttl = 0.01
        monkeypatch.setattr(fga_client, '_post', fake_post)

        assert await fga_client.read_tuples(object='knowledge_file:120') == [
            {'user': 'user:1', 'relation': 'viewer', 'object': 'knowledge_file:120'}
        ]
        assert await fga_client.read_tuples(object='knowledge_file:120') == [
            {'user': 'user:1', 'relation': 'viewer', 'object': 'knowledge_file:120'}
        ]
        await asyncio.sleep(0.02)
        assert await fga_client.read_tuples(object='knowledge_file:120') == [
            {'user': 'user:2', 'relation': 'viewer', 'object': 'knowledge_file:120'}
        ]
        assert calls == 2

    @pytest.mark.asyncio
    async def test_read_tuples_does_not_cache_failures(self, fga_client, monkeypatch):
        calls = 0

        async def fake_post(path, body):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise FGAClientError('read failed')
            return {
                'tuples': [
                    {
                        'key': {
                            'user': 'user:7',
                            'relation': 'viewer',
                            'object': body['tuple_key']['object'],
                        }
                    }
                ]
            }

        monkeypatch.setattr(fga_client, '_post', fake_post)

        with pytest.raises(FGAClientError):
            await fga_client.read_tuples(object='knowledge_file:120')
        assert await fga_client.read_tuples(object='knowledge_file:120') == [
            {'user': 'user:7', 'relation': 'viewer', 'object': 'knowledge_file:120'}
        ]
        assert calls == 2

    @pytest.mark.asyncio
    async def test_write_tuples_clears_related_read_cache(self, fga_client, monkeypatch):
        calls = 0

        async def fake_post(path, body):
            nonlocal calls
            if path.endswith('/read'):
                calls += 1
                return {
                    'tuples': [
                        {
                            'key': {
                                'user': f'user:{calls}',
                                'relation': 'viewer',
                                'object': body['tuple_key']['object'],
                            }
                        }
                    ]
                }
            return {}

        monkeypatch.setattr(fga_client, '_post', fake_post)

        await fga_client.read_tuples(object='knowledge_file:120')
        await fga_client.write_tuples(
            writes=[{'user': 'user:7', 'relation': 'viewer', 'object': 'knowledge_file:120'}],
        )
        refreshed = await fga_client.read_tuples(object='knowledge_file:120')

        assert refreshed == [
            {'user': 'user:2', 'relation': 'viewer', 'object': 'knowledge_file:120'}
        ]
        assert calls == 2


    @pytest.mark.asyncio
    async def test_write_tuples_prevents_new_reads_from_joining_stale_inflight(self, fga_client, monkeypatch):
        calls = 0
        first_read_started = asyncio.Event()
        release_first_read = asyncio.Event()

        async def fake_post(path, body):
            nonlocal calls
            if path.endswith('/read'):
                calls += 1
                current_call = calls
                if current_call == 1:
                    first_read_started.set()
                    await release_first_read.wait()
                return {
                    'tuples': [
                        {
                            'key': {
                                'user': f'user:{current_call}',
                                'relation': 'viewer',
                                'object': body['tuple_key']['object'],
                            }
                        }
                    ]
                }
            return {}

        monkeypatch.setattr(fga_client, '_post', fake_post)

        first_read = asyncio.create_task(fga_client.read_tuples(object='knowledge_file:120'))
        await first_read_started.wait()

        await fga_client.write_tuples(
            writes=[{'user': 'user:7', 'relation': 'viewer', 'object': 'knowledge_file:120'}],
        )
        second_read = asyncio.create_task(fga_client.read_tuples(object='knowledge_file:120'))
        await asyncio.sleep(0)

        release_first_read.set()
        first_result, second_result = await asyncio.gather(first_read, second_read)

        assert first_result == [
            {'user': 'user:1', 'relation': 'viewer', 'object': 'knowledge_file:120'}
        ]
        assert second_result == [
            {'user': 'user:2', 'relation': 'viewer', 'object': 'knowledge_file:120'}
        ]
        assert calls == 2


class TestFGAClientReadTuplesSingleflight:

    @pytest.mark.asyncio
    async def test_concurrent_same_key_reads_share_one_openfga_request(self, fga_client, monkeypatch):
        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_post(path, body):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return {
                'tuples': [
                    {
                        'key': {
                            'user': 'user:7',
                            'relation': 'viewer',
                            'object': body['tuple_key']['object'],
                        }
                    }
                ]
            }

        monkeypatch.setattr(fga_client, '_post', fake_post)

        tasks = [
            asyncio.create_task(fga_client.read_tuples(object='knowledge_file:120'))
            for _ in range(5)
        ]
        await started.wait()
        release.set()
        results = await asyncio.gather(*tasks)

        assert calls == 1
        assert all(result == results[0] for result in results)

    @pytest.mark.asyncio
    async def test_concurrent_read_failure_cleans_inflight_state(self, fga_client, monkeypatch):
        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def failing_post(path, body):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            raise FGAClientError('read failed')

        monkeypatch.setattr(fga_client, '_post', failing_post)
        tasks = [
            asyncio.create_task(fga_client.read_tuples(object='knowledge_file:120'))
            for _ in range(3)
        ]
        await started.wait()
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert calls == 1
        assert all(isinstance(result, FGAClientError) for result in results)
        assert fga_client._read_tuple_inflight == {}

        async def success_post(path, body):
            return {'tuples': []}

        monkeypatch.setattr(fga_client, '_post', success_post)
        assert await fga_client.read_tuples(object='knowledge_file:120') == []

    @pytest.mark.asyncio
    async def test_concurrent_different_key_reads_do_not_share_request(self, fga_client, monkeypatch):
        objects = []

        async def fake_post(path, body):
            objects.append(body['tuple_key']['object'])
            await asyncio.sleep(0)
            return {'tuples': []}

        monkeypatch.setattr(fga_client, '_post', fake_post)

        await asyncio.gather(
            fga_client.read_tuples(object='knowledge_file:120'),
            fga_client.read_tuples(object='knowledge_file:121'),
        )

        assert sorted(objects) == ['knowledge_file:120', 'knowledge_file:121']


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
