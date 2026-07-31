"""FGAClient — async HTTP wrapper around OpenFGA REST API.

Uses httpx instead of the openfga-sdk to avoid an extra dependency (AD-05).
All methods are async. Connection errors raise FGAConnectionError (AD-03 fail-closed).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from bisheng.common.errcode.permission import PermissionMutationTooLargeError

from .exceptions import FGAClientError, FGAConnectionError, FGAModelError, FGAWriteError

logger = logging.getLogger(__name__)
OPENFGA_WRITE_TUPLE_LIMIT = 100
BUSINESS_ATOMIC_TUPLE_LIMIT = 90
OPENFGA_BATCH_CHECK_LIMIT = 50
BUSINESS_BATCH_CHECK_LIMIT = 100
httpx_request_loggers = (
    logging.getLogger("httpx"),
    logging.getLogger("httpx._client"),
)


class _OpenFGAHttpxLogFilter(logging.Filter):
    """Suppress httpx default request logs for OpenFGA requests."""

    def __init__(self, base_url: str):
        super().__init__()
        self._base_url = base_url

    def filter(self, record: logging.LogRecord) -> bool:
        if not str(record.msg).startswith("HTTP Request:"):
            return True
        if not isinstance(record.args, tuple) or len(record.args) < 2:
            return True
        return not str(record.args[1]).startswith(self._base_url)


class FGAClient:
    """Async HTTP client for OpenFGA REST API."""

    def __init__(
        self,
        api_url: str,
        store_id: str,
        model_id: str,
        timeout: int = 5,
    ):
        if not store_id:
            raise ValueError("OpenFGA store_id must be explicitly pinned")
        if not model_id:
            raise ValueError("OpenFGA model_id must be explicitly pinned")
        self._api_url = api_url.rstrip("/")
        self._store_id = store_id
        self._model_id = model_id
        self._timeout = timeout
        self._install_httpx_log_filter()
        self._http = httpx.AsyncClient(
            base_url=self._api_url,
            timeout=httpx.Timeout(timeout),
            event_hooks={"response": [self._log_response]},
        )

    @property
    def store_id(self) -> str:
        return self._store_id

    @property
    def model_id(self) -> str:
        return self._model_id

    # ── Core permission methods ──────────────────────────────────

    async def check(self, user: str, relation: str, object: str, consistency: str | None = None) -> bool:
        """Check if user has relation on object.

        Returns True/False. Raises FGAConnectionError on network failure.

        ``consistency`` maps to OpenFGA's request-level consistency preference
        (e.g. ``"HIGHER_CONSISTENCY"``). It defaults to the server default
        (``MINIMIZE_LATENCY``, eventually consistent); pass
        ``"HIGHER_CONSISTENCY"`` for read-after-write reads that must observe a
        tuple written moments earlier.
        """
        body: dict[str, Any] = {
            "tuple_key": {"user": user, "relation": relation, "object": object},
            "authorization_model_id": self._model_id,
        }
        if consistency:
            body["consistency"] = consistency
        data = await self._post(f"/stores/{self._store_id}/check", body)
        return data.get("allowed", False)

    async def batch_check(
        self,
        checks: list[dict],
        consistency: str | None = None,
    ) -> list[bool]:
        """Batch check multiple tuples in one request.

        Each check: {"user": "...", "relation": "...", "object": "..."}
        Returns list of booleans in same order.
        """
        if not checks:
            return []
        if len(checks) > BUSINESS_BATCH_CHECK_LIMIT:
            raise FGAClientError(f"BatchCheck exceeds {BUSINESS_BATCH_CHECK_LIMIT} checks")
        resolved: list[bool] = []
        for offset in range(0, len(checks), OPENFGA_BATCH_CHECK_LIMIT):
            batch = checks[offset : offset + OPENFGA_BATCH_CHECK_LIMIT]
            body = {
                "authorization_model_id": self._model_id,
                "checks": [
                    {
                        "tuple_key": {
                            "user": check["user"],
                            "relation": check["relation"],
                            "object": check["object"],
                        },
                        "correlation_id": str(index),
                    }
                    for index, check in enumerate(batch)
                ],
            }
            if consistency:
                body["consistency"] = consistency
            data = await self._post(
                f"/stores/{self._store_id}/batch-check",
                body,
            )
            results = data.get("result", {})
            resolved.extend(results.get(str(index), {}).get("allowed", False) for index in range(len(batch)))
        logger.debug(
            "OpenFGA BatchCheck completed: store_id=%s model_id=%s count=%s",
            self._store_id,
            self._model_id,
            len(checks),
        )
        return resolved

    async def list_objects(
        self,
        user: str,
        relation: str,
        type: str,
        consistency: str | None = None,
    ) -> list[str]:
        """List all objects of given type that user has relation on.

        Returns list like ["workflow:abc", "workflow:def"].
        """
        body = {
            "user": user,
            "relation": relation,
            "type": type,
            "authorization_model_id": self._model_id,
        }
        if consistency:
            body["consistency"] = consistency
        data = await self._post(f"/stores/{self._store_id}/list-objects", body)
        return data.get("objects", [])

    # ── Tuple CRUD ───────────────────────────────────────────────

    async def write_tuples(
        self,
        writes: list[dict] | None = None,
        deletes: list[dict] | None = None,
    ) -> None:
        """Batch write and/or delete tuples.

        Each tuple: {"user": "user:7", "relation": "owner", "object": "workflow:abc"}
        Raises FGAWriteError when the atomic request is invalid or fails.
        """
        body = self._build_write_body(writes, deletes)
        if body is None:
            return

        scoped_body = {**body, "authorization_model_id": self._model_id}
        try:
            await self._post(f"/stores/{self._store_id}/write", scoped_body)
        except FGAConnectionError:
            raise
        except FGAClientError as e:
            raise FGAWriteError(str(e)) from e

    def write_tuples_sync(
        self,
        writes: list[dict] | None = None,
        deletes: list[dict] | None = None,
    ) -> None:
        """Synchronous tuple write for Celery tasks without an asyncio loop."""
        body = self._build_write_body(writes, deletes)
        if body is None:
            return

        scoped_body = {**body, "authorization_model_id": self._model_id}
        try:
            self._post_sync(f"/stores/{self._store_id}/write", scoped_body)
        except FGAConnectionError:
            raise
        except FGAClientError as e:
            raise FGAWriteError(str(e)) from e

    def _build_write_body(
        self,
        writes: list[dict] | None = None,
        deletes: list[dict] | None = None,
    ) -> dict | None:
        """Assemble the OpenFGA write request body, or None when nothing to do."""
        operation_count = len(writes or ()) + len(deletes or ())
        if operation_count > OPENFGA_WRITE_TUPLE_LIMIT:
            raise FGAWriteError(f"OpenFGA Write exceeds {OPENFGA_WRITE_TUPLE_LIMIT} tuple operations")
        body: dict[str, Any] = {}
        if writes:
            body["writes"] = {"tuple_keys": [self._tuple_key(t) for t in writes]}
        if deletes:
            body["deletes"] = {"tuple_keys": [self._tuple_key(t) for t in deletes]}
        return body if body else None

    @staticmethod
    def _tuple_key(value: dict) -> dict[str, str]:
        try:
            key = {
                "user": str(value["user"]),
                "relation": str(value["relation"]),
                "object": str(value["object"]),
            }
        except KeyError as exc:
            raise FGAWriteError(f"Invalid tuple key: missing {exc.args[0]}") from exc
        if not all(key.values()):
            raise FGAWriteError("Invalid tuple key: values must be non-empty")
        return key

    @staticmethod
    def validate_business_mutation_size(operation_count: int) -> None:
        """Enforce the business reserve below OpenFGA's service limit."""

        if operation_count > BUSINESS_ATOMIC_TUPLE_LIMIT:
            raise PermissionMutationTooLargeError()

    async def delete_tuples_store_scoped(self, tuples: list[dict]) -> None:
        """Delete Store tuples by exact key using the pinned target model."""

        await self.write_tuples(deletes=tuples)

    def for_model(self, target_model_id: str) -> FGAClient:
        """Create an isolated client for release/migration target validation."""

        return FGAClient(
            api_url=self._api_url,
            store_id=self._store_id,
            model_id=target_model_id,
            timeout=self._timeout,
        )

    async def read_tuples(
        self,
        user: str | None = None,
        relation: str | None = None,
        object: str | None = None,
        consistency: str | None = None,
    ) -> list[dict]:
        """Read tuples matching the given filter.

        Returns list of {"key": {"user": ..., "relation": ..., "object": ...}, "timestamp": ...}.
        """
        tuple_key: dict[str, str] = {}
        if user:
            tuple_key["user"] = user
        if relation:
            tuple_key["relation"] = relation
        if object:
            tuple_key["object"] = object
        tuples: list[dict] = []
        continuation_token: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if tuple_key:
                body["tuple_key"] = tuple_key
            if consistency:
                body["consistency"] = consistency
            if continuation_token:
                body["continuation_token"] = continuation_token
            data = await self._post(f"/stores/{self._store_id}/read", body)
            tuples.extend(t["key"] for t in data.get("tuples", []))
            continuation_token = data.get("continuation_token") or data.get("continuationToken")
            if not continuation_token:
                break
        return tuples

    # ── Store & model management ─────────────────────────────────

    async def create_store(self, name: str) -> str:
        """Create a new store. Returns store_id."""
        data = await self._post("/stores", {"name": name})
        store_id = data.get("id", "")
        if not store_id:
            raise FGAModelError("create_store returned empty id")
        return store_id

    async def list_stores(self) -> list[dict]:
        """List all stores."""
        data = await self._get("/stores")
        return data.get("stores", [])

    async def write_authorization_model(self, model: dict) -> str:
        """Write a new authorization model. Returns model_id."""
        data = await self._post(f"/stores/{self._store_id}/authorization-models", model)
        model_id = data.get("authorization_model_id", "")
        if not model_id:
            raise FGAModelError("write_authorization_model returned empty model_id")
        return model_id

    async def list_authorization_models(self) -> list[dict]:
        """List every immutable model in this Store for idempotent release tools."""

        models: list[dict] = []
        continuation_token: str | None = None
        while True:
            params: dict[str, str | int] = {"page_size": 100}
            if continuation_token:
                params["continuation_token"] = continuation_token
            query = str(httpx.QueryParams(params))
            data = await self._get(f"/stores/{self._store_id}/authorization-models?{query}")
            models.extend(data.get("authorization_models", ()))
            continuation_token = data.get("continuation_token") or data.get("continuationToken")
            if not continuation_token:
                return models

    # ── Health ───────────────────────────────────────────────────

    async def health(self) -> bool:
        """Check OpenFGA server health."""
        try:
            resp = await self._http.get("/healthz")
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._http.aclose()

    # ── Internal helpers ─────────────────────────────────────────

    def _install_httpx_log_filter(self) -> None:
        """Replace httpx's OpenFGA request logs with this module's logger."""
        for httpx_logger in httpx_request_loggers:
            httpx_logger.addFilter(_OpenFGAHttpxLogFilter(self._api_url))

    @staticmethod
    async def _log_response(resp: httpx.Response) -> None:
        """Log httpx request completion under this module logger.

        Debug level on purpose: this fires for *every* OpenFGA call (read/check),
        and permission evaluation issues many per request. At INFO it dominated
        hot-path CPU (std-logging -> loguru InterceptHandler stack-walk) under load.
        """
        logger.debug(
            'HTTP Request: %s %s "%s %s %s"',
            resp.request.method,
            resp.request.url,
            resp.http_version,
            resp.status_code,
            resp.reason_phrase,
        )

    @staticmethod
    def _log_response_sync(resp: httpx.Response) -> None:
        """Log sync httpx request completion under this module logger.

        Debug level on purpose (see _log_response): per-request INFO logging of
        every OpenFGA call dominated hot-path CPU under load.
        """
        logger.debug(
            'HTTP Request: %s %s "%s %s %s"',
            resp.request.method,
            resp.request.url,
            resp.http_version,
            resp.status_code,
            resp.reason_phrase,
        )

    async def _post(self, path: str, body: dict) -> dict:
        """POST JSON and return parsed response."""
        try:
            resp = await self._http.post(path, json=body)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise FGAConnectionError(f"OpenFGA unreachable: {e}") from e
        except httpx.HTTPError as e:
            raise FGAClientError(f"HTTP error: {e}") from e
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise FGAClientError(f"OpenFGA {resp.status_code}: {detail}")
        return resp.json()

    def _post_sync(self, path: str, body: dict) -> dict:
        """POST JSON synchronously and return parsed response."""
        try:
            with httpx.Client(
                base_url=self._api_url,
                timeout=httpx.Timeout(self._timeout),
                event_hooks={"response": [self._log_response_sync]},
            ) as client:
                resp = client.post(path, json=body)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise FGAConnectionError(f"OpenFGA unreachable: {e}") from e
        except httpx.HTTPError as e:
            raise FGAClientError(f"HTTP error: {e}") from e
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise FGAClientError(f"OpenFGA {resp.status_code}: {detail}")
        return resp.json()

    async def _get(self, path: str) -> dict:
        """GET and return parsed response."""
        try:
            resp = await self._http.get(path)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise FGAConnectionError(f"OpenFGA unreachable: {e}") from e
        except httpx.HTTPError as e:
            raise FGAClientError(f"HTTP error: {e}") from e
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise FGAClientError(f"OpenFGA {resp.status_code}: {detail}")
        return resp.json()
