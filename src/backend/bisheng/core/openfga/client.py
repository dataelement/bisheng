"""FGAClient — async HTTP wrapper around OpenFGA REST API.

Uses httpx instead of the openfga-sdk to avoid an extra dependency (AD-05).
All methods are async. Connection errors raise FGAConnectionError (AD-03 fail-closed).
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from .exceptions import FGAClientError, FGAConnectionError, FGAModelError, FGAWriteError

logger = logging.getLogger(__name__)
httpx_request_loggers = (
    logging.getLogger("httpx"),
    logging.getLogger("httpx._client"),
)


@dataclass
class FGAReadStats:
    read_count: int = 0
    cache_hit_count: int = 0
    singleflight_wait_count: int = 0


_fga_read_stats_var: contextvars.ContextVar[FGAReadStats | None] = contextvars.ContextVar(
    "fga_read_stats",
    default=None,
)


def begin_fga_read_stats() -> contextvars.Token:
    return _fga_read_stats_var.set(FGAReadStats())


def get_fga_read_stats() -> FGAReadStats:
    stats = _fga_read_stats_var.get()
    return stats if stats is not None else FGAReadStats()


def finish_fga_read_stats(token: contextvars.Token) -> FGAReadStats:
    stats = get_fga_read_stats()
    _fga_read_stats_var.reset(token)
    return stats


def _increment_fga_read_stat(field: str, amount: int = 1) -> None:
    stats = _fga_read_stats_var.get()
    if stats is not None:
        setattr(stats, field, getattr(stats, field) + amount)


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
        legacy_model_id: str | None = None,
        read_tuple_cache_ttl: float = 5.0,
    ):
        self._api_url = api_url.rstrip("/")
        self._store_id = store_id
        self._model_id = model_id
        self._legacy_model_id = legacy_model_id  # F013: dual-model gray release
        self._timeout = timeout
        self._read_tuple_cache_ttl = float(read_tuple_cache_ttl)
        self._read_tuple_cache: dict[tuple[str, str, str, str, str], tuple[float, list[dict]]] = {}
        self._read_tuple_inflight: dict[
            tuple[str, str, str, str, str],
            tuple[asyncio.Task[list[dict]], int],
        ] = {}
        self._read_tuple_lock = asyncio.Lock()
        self._read_tuple_cache_generation = 0
        self._install_httpx_log_filter()
        self._http = httpx.AsyncClient(
            base_url=self._api_url,
            timeout=httpx.Timeout(timeout),
            trust_env=False,
            event_hooks={"response": [self._log_response]},
        )

    @property
    def store_id(self) -> str:
        return self._store_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def legacy_model_id(self) -> str | None:
        """Legacy model id for shadow writes during gray period; None when disabled."""
        return self._legacy_model_id

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

    async def batch_check(self, checks: list[dict]) -> list[bool]:
        """Batch check multiple tuples in one request.

        Each check: {"user": "...", "relation": "...", "object": "..."}
        Returns list of booleans in same order.
        """
        body = {
            "authorization_model_id": self._model_id,
            "checks": [
                {
                    "tuple_key": {"user": c["user"], "relation": c["relation"], "object": c["object"]},
                    "correlation_id": str(i),
                }
                for i, c in enumerate(checks)
            ],
        }
        data = await self._post(f"/stores/{self._store_id}/batch-check", body)
        results = data.get("result", {})
        resolved = [results.get(str(i), {}).get("allowed", False) for i in range(len(checks))]
        logger.info(
            "[openfga-debug] batch_check store_id=%s model_id=%s checks=%s raw_result=%s resolved=%s",
            self._store_id,
            self._model_id,
            checks,
            results,
            resolved,
        )
        return resolved

    async def list_objects(self, user: str, relation: str, type: str) -> list[str]:
        """List all objects of given type that user has relation on.

        Returns list like ["workflow:abc", "workflow:def"].
        """
        body = {
            "user": user,
            "relation": relation,
            "type": type,
            "authorization_model_id": self._model_id,
        }
        data = await self._post(f"/stores/{self._store_id}/list-objects", body)
        return data.get("objects", [])

    # ── Tuple CRUD ───────────────────────────────────────────────

    async def write_tuples(self, writes: list[dict] = None, deletes: list[dict] = None) -> None:
        """Batch write and/or delete tuples.

        Each tuple: {"user": "user:7", "relation": "owner", "object": "workflow:abc"}
        Raises FGAWriteError on failure of the primary model write.

        F013: when legacy_model_id is set (dual_model_mode in OpenFGAConf), a
        shadow write is sent to the legacy model for the gray release window.
        Shadow failures are logged at WARNING and never propagate — the legacy
        model is being phased out and must not block production writes.
        """
        body = self._build_write_body(writes, deletes)
        if body is None:
            return

        # Primary write (current authorization model)
        primary_body = {**body, "authorization_model_id": self._model_id}
        try:
            await self._post(f"/stores/{self._store_id}/write", primary_body)
        except FGAConnectionError:
            raise
        except FGAClientError as e:
            raise FGAWriteError(str(e)) from e
        self.clear_read_tuples_cache()

        # Shadow write (legacy model during gray period; failures swallowed)
        if self._legacy_model_id:
            shadow_body = {**body, "authorization_model_id": self._legacy_model_id}
            try:
                await self._post(f"/stores/{self._store_id}/write", shadow_body)
            except Exception as e:
                logger.warning(
                    "Shadow write to legacy model %s failed (ignored): %s",
                    self._legacy_model_id,
                    e,
                )

    def write_tuples_sync(self, writes: list[dict] = None, deletes: list[dict] = None) -> None:
        """Synchronous tuple write for Celery tasks without an asyncio loop."""
        body = self._build_write_body(writes, deletes)
        if body is None:
            return

        primary_body = {**body, "authorization_model_id": self._model_id}
        try:
            self._post_sync(f"/stores/{self._store_id}/write", primary_body)
        except FGAConnectionError:
            raise
        except FGAClientError as e:
            raise FGAWriteError(str(e)) from e
        self.clear_read_tuples_cache()

        if self._legacy_model_id:
            shadow_body = {**body, "authorization_model_id": self._legacy_model_id}
            try:
                self._post_sync(f"/stores/{self._store_id}/write", shadow_body)
            except Exception as e:
                logger.warning(
                    "Shadow write to legacy model %s failed (ignored): %s",
                    self._legacy_model_id,
                    e,
                )

    def _build_write_body(self, writes: list[dict] = None, deletes: list[dict] = None) -> dict | None:
        """Assemble the OpenFGA write request body, or None when nothing to do."""
        body: dict[str, Any] = {}
        if writes:
            body["writes"] = {
                "tuple_keys": [{"user": t["user"], "relation": t["relation"], "object": t["object"]} for t in writes]
            }
        if deletes:
            body["deletes"] = {
                "tuple_keys": [{"user": t["user"], "relation": t["relation"], "object": t["object"]} for t in deletes]
            }
        return body if body else None

    async def read_tuples(
        self, user: str | None = None, relation: str | None = None, object: str | None = None
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
        cache_key = self._read_tuple_cache_key(user, relation, object)
        cached = self._get_cached_read_tuples(cache_key)
        if cached is not None:
            _increment_fga_read_stat("cache_hit_count")
            return cached

        task, _is_owner, generation = await self._get_or_create_read_tuple_task(cache_key, tuple_key)
        if not _is_owner:
            _increment_fga_read_stat("singleflight_wait_count")

        try:
            tuples = await task
        except Exception:
            await self._clear_read_tuple_inflight(cache_key, task)
            raise

        await self._store_read_tuple_cache(cache_key, task, tuples, generation)
        return self._copy_tuples(tuples)

    async def _read_tuples_uncached(self, tuple_key: dict[str, str]) -> list[dict]:
        tuples: list[dict] = []
        continuation_token: str | None = None
        while True:
            body: dict[str, Any] = {"tuple_key": tuple_key, "page_size": 100}
            if continuation_token:
                body["continuation_token"] = continuation_token
            _increment_fga_read_stat("read_count")
            data = await self._post(f"/stores/{self._store_id}/read", body)
            tuples.extend(t["key"] for t in data.get("tuples", []))
            continuation_token = data.get("continuation_token") or data.get("continuationToken")
            if not continuation_token:
                break
        return tuples

    def clear_read_tuples_cache(self, objects: Iterable[str] | None = None) -> None:
        self._read_tuple_cache_generation += 1
        if objects is None:
            self._read_tuple_cache.clear()
            return
        object_set = {str(item) for item in objects if item}
        if not object_set:
            self._read_tuple_cache.clear()
            return
        for key in list(self._read_tuple_cache):
            if key[-1] in object_set or not key[-1]:
                self._read_tuple_cache.pop(key, None)

    def _read_tuple_cache_key(
        self,
        user: str | None,
        relation: str | None,
        object: str | None,
    ) -> tuple[str, str, str, str, str]:
        return (
            self._store_id,
            self._model_id,
            user or "",
            relation or "",
            object or "",
        )

    def _get_cached_read_tuples(
        self,
        cache_key: tuple[str, str, str, str, str],
    ) -> list[dict] | None:
        if self._read_tuple_cache_ttl <= 0:
            return None
        cached = self._read_tuple_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, tuples = cached
        if expires_at <= time.monotonic():
            self._read_tuple_cache.pop(cache_key, None)
            return None
        return self._copy_tuples(tuples)

    async def _get_or_create_read_tuple_task(
        self,
        cache_key: tuple[str, str, str, str, str],
        tuple_key: dict[str, str],
    ) -> tuple[asyncio.Task[list[dict]], bool, int]:
        async with self._read_tuple_lock:
            cached = self._get_cached_read_tuples(cache_key)
            if cached is not None:
                _increment_fga_read_stat("cache_hit_count")
                task = asyncio.create_task(self._return_read_tuples(cached))
                return task, False, self._read_tuple_cache_generation

            inflight = self._read_tuple_inflight.get(cache_key)
            if inflight is not None:
                task, generation = inflight
                if generation == self._read_tuple_cache_generation:
                    return task, False, generation
                self._read_tuple_inflight.pop(cache_key, None)

            generation = self._read_tuple_cache_generation
            task = asyncio.create_task(self._read_tuples_uncached(dict(tuple_key)))
            self._read_tuple_inflight[cache_key] = (task, generation)
            return task, True, generation

    @staticmethod
    async def _return_read_tuples(tuples: list[dict]) -> list[dict]:
        return tuples

    async def _store_read_tuple_cache(
        self,
        cache_key: tuple[str, str, str, str, str],
        task: asyncio.Task[list[dict]],
        tuples: list[dict],
        generation: int,
    ) -> None:
        async with self._read_tuple_lock:
            current = self._read_tuple_inflight.get(cache_key)
            if current is not None and current[0] is task:
                self._read_tuple_inflight.pop(cache_key, None)
            if self._read_tuple_cache_ttl <= 0:
                return
            if generation != self._read_tuple_cache_generation:
                return
            self._read_tuple_cache[cache_key] = (
                time.monotonic() + self._read_tuple_cache_ttl,
                self._copy_tuples(tuples),
            )

    async def _clear_read_tuple_inflight(
        self,
        cache_key: tuple[str, str, str, str, str],
        task: asyncio.Task[list[dict]],
    ) -> None:
        async with self._read_tuple_lock:
            current = self._read_tuple_inflight.get(cache_key)
            if current is not None and current[0] is task:
                self._read_tuple_inflight.pop(cache_key, None)

    @staticmethod
    def _copy_tuples(tuples: list[dict]) -> list[dict]:
        return [dict(tuple_item) for tuple_item in tuples]

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
                trust_env=False,
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
