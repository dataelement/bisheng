"""Decide a model's context window and how much of it a request may use as input (F087).

Sources, first match wins (design.md decision 3):

1. ``context_window`` in the model's advanced config (``user_kwargs``).
2. Ollama's "context length" field, sent to Ollama as ``num_ctx``.
3. The provider's model-info API (``context_window_probes``), cached in Redis.
4. Unknown. The caller then leaves the agent framework's defaults untouched.

"Usable input" is what task mode hands to deepagents as
``profile["max_input_tokens"]`` (design.md decision 2).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from loguru import logger

from bisheng.llm.domain.const import LLMServerType
from bisheng.llm.domain.services.context_window_probes import ProbeResult, probe_context_window

if TYPE_CHECKING:
    from bisheng.llm.domain.llm.llm import BishengLLM

# Keys task mode reads out of the advanced config; never sent to the provider.
CONTEXT_WINDOW_KEY = "context_window"

CACHE_KEY_PREFIX = "linsight:context_window:"
CACHE_TTL_SUCCESS = 3600
CACHE_TTL_FAILURE = 300

Source = Literal["manual", "ollama_num_ctx", "deployed", "published", "unknown"]


class _Cache(Protocol):
    async def aget(self, key: str) -> Any: ...

    async def aset(self, key: str, value: Any, expiration: int = 3600) -> Any: ...

    async def adelete(self, key: str) -> Any: ...


@dataclass(frozen=True)
class ModelSnapshot:
    """What the resolver needs from a model, detached from ``BishengLLM``."""

    model_id: int
    model_name: str
    server_type: str
    # Kept out of repr: both can carry API keys, and loguru's traceback
    # diagnostics print local variables.
    model_config: dict = field(repr=False)
    # The chat client's constructor arguments as BishengLLM built them: base URL,
    # API key, proxy, max_tokens (or num_ctx for Ollama).
    client_params: dict = field(repr=False)


@dataclass(frozen=True)
class ContextWindowResult:
    window: int | None
    kind: Literal["total", "input"] | None
    usable_input: int | None
    source: Source


UNKNOWN = ContextWindowResult(window=None, kind=None, usable_input=None, source="unknown")


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def read_user_kwargs(model_config: dict) -> dict:
    """The advanced config as a dict; a malformed one reads as empty."""
    raw = (model_config or {}).get("user_kwargs") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return dict(raw) if isinstance(raw, dict) else {}


def _manual_window(snapshot: ModelSnapshot) -> int | None:
    value = read_user_kwargs(snapshot.model_config).get(CONTEXT_WINDOW_KEY)
    if value is None:
        return None
    window = _positive_int(value)
    if window is None:
        logger.warning(
            "[linsight-context-window] ignoring invalid context_window={!r} model_id={}",
            value,
            snapshot.model_id,
        )
    return window


def _usable_input(snapshot: ModelSnapshot, window: int, kind: str, source: Source) -> ContextWindowResult:
    if kind == "input" or snapshot.server_type == LLMServerType.OLLAMA.value:
        # An input-only limit is already net of output; Ollama has no separate
        # output field — its "context length" field IS the window.
        return ContextWindowResult(window=window, kind=kind, usable_input=window, source=source)
    max_tokens = _positive_int(snapshot.client_params.get("max_tokens"))
    if max_tokens is None:
        return ContextWindowResult(window=window, kind=kind, usable_input=window, source=source)
    if max_tokens >= window:
        logger.warning(
            "[linsight-context-window] max_tokens={} is not below the context window={} model_id={}; "
            "treating the window as unknown",
            max_tokens,
            window,
            snapshot.model_id,
        )
        return UNKNOWN
    return ContextWindowResult(window=window, kind=kind, usable_input=window - max_tokens, source=source)


def _cache_key(model_id: int) -> str:
    return f"{CACHE_KEY_PREFIX}{model_id}"


def _fingerprint(snapshot: ModelSnapshot) -> str:
    """What the cached answer was read against.

    A worker process may still hold the pre-save model config for up to a minute
    (``LLM_CACHE``) and write the old answer back right after the save cleared
    Redis; a value whose fingerprint no longer matches is treated as a miss.
    """
    params = snapshot.client_params
    base = params.get("base_url") or params.get("openai_api_base") or params.get("api_base")
    base = base or params.get("anthropic_api_url") or ""
    raw = f"{snapshot.server_type}|{base}|{snapshot.model_name}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


async def _default_cache() -> _Cache:
    from bisheng.core.cache.redis_manager import get_redis_client

    return await get_redis_client()


class ContextWindowService:
    @classmethod
    async def resolve(cls, llm: BishengLLM) -> ContextWindowResult:
        """Context window and usable input for a built ``BishengLLM``. Never raises."""
        if getattr(llm, "server_info", None) is None or getattr(llm, "model_info", None) is None:
            # Not a model-management model (tests, or a raw langchain model): nothing to read.
            return UNKNOWN
        try:
            snapshot = ModelSnapshot(
                model_id=int(llm.model_id),
                model_name=str(llm.model_name),
                server_type=str(llm.server_info.type),
                model_config=llm.get_model_info_config(),
                client_params=llm._get_llm_params(llm.server_info, llm.model_info),
            )
            return await cls.resolve_snapshot(snapshot)
        except Exception:
            # Resolution is an optimisation: an unknown window keeps the agent on
            # its pre-F087 behaviour, so a failure here must not fail the task.
            logger.opt(exception=True).warning("[linsight-context-window] resolve failed; treating as unknown")
            return UNKNOWN

    @classmethod
    async def resolve_snapshot(cls, snapshot: ModelSnapshot, cache: _Cache | None = None) -> ContextWindowResult:
        manual = _manual_window(snapshot)
        if manual is not None:
            return _usable_input(snapshot, manual, "total", "manual")

        if snapshot.server_type == LLMServerType.OLLAMA.value:
            num_ctx = _positive_int(snapshot.client_params.get("num_ctx"))
            if num_ctx is not None:
                return _usable_input(snapshot, num_ctx, "total", "ollama_num_ctx")

        probed = await cls._probe_cached(snapshot, cache)
        if probed is None:
            return UNKNOWN
        return _usable_input(snapshot, probed.window, probed.kind, probed.source)

    @classmethod
    async def _probe_cached(cls, snapshot: ModelSnapshot, cache: _Cache | None) -> ProbeResult | None:
        key = _cache_key(snapshot.model_id)
        fingerprint = _fingerprint(snapshot)
        try:
            cache = cache or await _default_cache()
            cached = await cache.aget(key)
        except Exception:
            logger.opt(exception=True).warning("[linsight-context-window] cache read failed key={}", key)
            cache, cached = None, None
        if isinstance(cached, dict) and cached.get("fingerprint") == fingerprint:
            if cached.get("failed"):
                return None
            if _positive_int(cached.get("window")) and cached.get("kind") in ("total", "input"):
                return ProbeResult(window=cached["window"], kind=cached["kind"], source=cached["source"])

        probed = await probe_context_window(snapshot)
        if cache is not None:
            value, ttl = (
                ({"failed": True, "fingerprint": fingerprint}, CACHE_TTL_FAILURE)
                if probed is None
                else (
                    {"window": probed.window, "kind": probed.kind, "source": probed.source, "fingerprint": fingerprint},
                    CACHE_TTL_SUCCESS,
                )
            )
            try:
                await cache.aset(key, value, expiration=ttl)
            except Exception:
                logger.opt(exception=True).warning("[linsight-context-window] cache write failed key={}", key)
        return probed

    @classmethod
    async def invalidate(cls, model_ids: Iterable[int], cache: _Cache | None = None) -> None:
        """Drop cached provider answers after the model's configuration changed."""
        try:
            cache = cache or await _default_cache()
            for model_id in model_ids:
                await cache.adelete(_cache_key(model_id))
        except Exception:
            # Worst case the old value lives until its TTL (one hour).
            logger.opt(exception=True).warning("[linsight-context-window] cache invalidation failed")
