"""FGAClient — async HTTP wrapper around OpenFGA REST API.

Uses httpx instead of the openfga-sdk to avoid an extra dependency (AD-05).
All methods are async. Connection errors raise FGAConnectionError (AD-03 fail-closed).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .exceptions import FGAClientError, FGAConnectionError, FGAWriteError, FGAModelError

logger = logging.getLogger(__name__)


class FGAClient:
    """Async HTTP client for OpenFGA REST API."""

    def __init__(self, api_url: str, store_id: str, model_id: str, timeout: int = 5):
        self._api_url = api_url.rstrip('/')
        self._store_id = store_id
        self._model_id = model_id
        self._http = httpx.AsyncClient(
            base_url=self._api_url,
            timeout=httpx.Timeout(timeout),
        )

    @property
    def store_id(self) -> str:
        return self._store_id

    @property
    def model_id(self) -> str:
        return self._model_id

    # ── Core permission methods ──────────────────────────────────

    async def check(self, user: str, relation: str, object: str) -> bool:
        """Check if user has relation on object.

        Returns True/False. Raises FGAConnectionError on network failure.
        """
        body = {
            'tuple_key': {'user': user, 'relation': relation, 'object': object},
            'authorization_model_id': self._model_id,
        }
        data = await self._post(f'/stores/{self._store_id}/check', body)
        return data.get('allowed', False)

    async def batch_check(self, checks: list[dict]) -> list[bool]:
        """Batch check multiple tuples in one request.

        Each check: {"user": "...", "relation": "...", "object": "..."}
        Returns list of booleans in same order.
        """
        body = {
            'authorization_model_id': self._model_id,
            'checks': [
                {
                    'tuple_key': {'user': c['user'], 'relation': c['relation'], 'object': c['object']},
                    'correlation_id': str(i),
                }
                for i, c in enumerate(checks)
            ],
        }
        data = await self._post(f'/stores/{self._store_id}/batch-check', body)
        results = data.get('result', {})
        return [
            results.get(str(i), {}).get('allowed', False)
            for i in range(len(checks))
        ]

    async def list_objects(self, user: str, relation: str, type: str) -> list[str]:
        """List all objects of given type that user has relation on.

        Returns list like ["workflow:abc", "workflow:def"].
        """
        body = {
            'user': user,
            'relation': relation,
            'type': type,
            'authorization_model_id': self._model_id,
        }
        data = await self._post(f'/stores/{self._store_id}/list-objects', body)
        return data.get('objects', [])

    # ── Tuple CRUD ───────────────────────────────────────────────

    async def write_tuples(self, writes: list[dict] = None,
                           deletes: list[dict] = None) -> None:
        """Batch write and/or delete tuples.

        Each tuple: {"user": "user:7", "relation": "owner", "object": "workflow:abc"}
        Raises FGAWriteError on failure.
        """
        body: dict[str, Any] = {}
        if writes:
            body['writes'] = {
                'tuple_keys': [
                    {'user': t['user'], 'relation': t['relation'], 'object': t['object']}
                    for t in writes
                ]
            }
        if deletes:
            body['deletes'] = {
                'tuple_keys': [
                    {'user': t['user'], 'relation': t['relation'], 'object': t['object']}
                    for t in deletes
                ]
            }
        if not body:
            return
        try:
            await self._post(f'/stores/{self._store_id}/write', body)
        except FGAConnectionError:
            raise
        except FGAClientError as e:
            raise FGAWriteError(str(e)) from e

    async def read_tuples(self, user: Optional[str] = None,
                          relation: Optional[str] = None,
                          object: Optional[str] = None) -> list[dict]:
        """Read tuples matching the given filter.

        Returns list of {"key": {"user": ..., "relation": ..., "object": ...}, "timestamp": ...}.
        """
        tuple_key: dict[str, str] = {}
        if user:
            tuple_key['user'] = user
        if relation:
            tuple_key['relation'] = relation
        if object:
            tuple_key['object'] = object
        body = {'tuple_key': tuple_key}
        data = await self._post(f'/stores/{self._store_id}/read', body)
        return [t['key'] for t in data.get('tuples', [])]

    # ── Store & model management ─────────────────────────────────

    async def create_store(self, name: str) -> str:
        """Create a new store. Returns store_id."""
        data = await self._post('/stores', {'name': name})
        store_id = data.get('id', '')
        if not store_id:
            raise FGAModelError('create_store returned empty id')
        return store_id

    async def list_stores(self) -> list[dict]:
        """List all stores."""
        data = await self._get('/stores')
        return data.get('stores', [])

    async def write_authorization_model(self, model: dict) -> str:
        """Write a new authorization model. Returns model_id."""
        data = await self._post(
            f'/stores/{self._store_id}/authorization-models', model
        )
        model_id = data.get('authorization_model_id', '')
        if not model_id:
            raise FGAModelError('write_authorization_model returned empty model_id')
        return model_id

    # ── Health ───────────────────────────────────────────────────

    async def health(self) -> bool:
        """Check OpenFGA server health."""
        try:
            resp = await self._http.get('/healthz')
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._http.aclose()

    # ── Internal helpers ─────────────────────────────────────────

    async def _post(self, path: str, body: dict) -> dict:
        """POST JSON and return parsed response."""
        try:
            resp = await self._http.post(path, json=body)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise FGAConnectionError(f'OpenFGA unreachable: {e}') from e
        except httpx.HTTPError as e:
            raise FGAClientError(f'HTTP error: {e}') from e
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise FGAClientError(f'OpenFGA {resp.status_code}: {detail}')
        return resp.json()

    async def _get(self, path: str) -> dict:
        """GET and return parsed response."""
        try:
            resp = await self._http.get(path)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise FGAConnectionError(f'OpenFGA unreachable: {e}') from e
        except httpx.HTTPError as e:
            raise FGAClientError(f'HTTP error: {e}') from e
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise FGAClientError(f'OpenFGA {resp.status_code}: {detail}')
        return resp.json()
