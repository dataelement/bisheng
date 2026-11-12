"""F015 token-usage contract shared by every DSH adapter (design §4.4).

After normalization ``input_tokens`` counts every input token including cache
reads and cache writes, ``cache_creation_tokens`` sums every cache-write bucket,
``total = input + output`` and ``cache_read + cache_creation <= input``.
"""

from loguru import logger

from bisheng.common.services.metric_log import emit_metric
from bisheng.dsh.domain.schemas.contracts import DshTokenUsage

INT64_MAX = 9_223_372_036_854_775_807


def measured(*values):
    """First well-formed count; missing or malformed optional detail must not invalidate totals."""
    return next((value for value in values if type(value) is int and 0 <= value <= INT64_MAX), None)


def cache_writes(details: dict, raw_details: dict, raw: dict):
    """Cache-write tokens across sources.

    langchain-anthropic reports TTL buckets (``ephemeral_5m/1h_input_tokens``) and then
    sets the generic ``cache_creation`` to 0, so the buckets must win when present.
    """
    buckets = [measured(details.get(key)) for key in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")]
    if any(buckets):
        return sum(value or 0 for value in buckets)
    return measured(
        details.get("cache_creation"),
        raw_details.get("cache_creation_tokens"),
        raw_details.get("cache_creation_input_tokens"),  # Qwen explicit cache
        raw.get("cache_creation_input_tokens"),
    )


def enforce_inclusive(usage: DshTokenUsage, *, model_id: int, request_id: str) -> DshTokenUsage:
    """Apply the contract to a call's settled totals, once, before pricing.

    Cached tokens larger than the input cannot come from an input that includes them:
    the source reported input exclusive of cache, so add the cached tokens back rather
    than under-bill (design decision 16) and report it.
    """
    if usage.total_tokens is None:
        return usage
    cached = (usage.cache_read_tokens or 0) + (usage.cache_creation_tokens or 0)
    if cached <= usage.input_tokens:
        return usage
    logger.warning("DSH usage reported input exclusive of cache; adding cached tokens back request={}", request_id)
    emit_metric("dsh_usage_contract", model_id=model_id, request_id=request_id, corrected=True)
    input_tokens = usage.input_tokens + cached
    return usage.model_copy(update={"input_tokens": input_tokens, "total_tokens": input_tokens + usage.output_tokens})
