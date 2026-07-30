"""Shared Redis heartbeat evidence for every F048 runtime process."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from bisheng.core.cache.redis_manager import get_redis_client

HEARTBEAT_KEY_PREFIX = "f048:runtime:heartbeat"
DEFAULT_HEARTBEAT_TTL_SECONDS = 45


class RuntimeHeartbeatStorePort(Protocol):
    """Persistence contract used by the OpenFGA runtime manager."""

    async def publish(
        self,
        *,
        role: str,
        instance_id: str,
        payload: dict[str, Any],
    ) -> None: ...

    async def remove(self, *, role: str, instance_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class RuntimeHeartbeatEvidence:
    role: str
    instance_id: str
    ready: bool
    store_id: str
    model_id: str
    model_checksum: str
    catalog_release_id: int
    catalog_checksum: str
    dual_model_mode: bool
    legacy_model_id: str | None
    observed_at: str

    @classmethod
    def from_payload(
        cls,
        *,
        role: str,
        instance_id: str,
        payload: object,
    ) -> RuntimeHeartbeatEvidence:
        if not isinstance(payload, dict):
            raise ValueError("F048 runtime heartbeat payload must be a mapping")
        required_strings = (
            "store_id",
            "model_id",
            "model_checksum",
            "catalog_checksum",
        )
        if any(not isinstance(payload.get(key), str) or not payload[key] for key in required_strings):
            raise ValueError("F048 runtime heartbeat pin is incomplete")
        catalog_release_id = payload.get("catalog_release_id")
        if not isinstance(catalog_release_id, int) or catalog_release_id <= 0:
            raise ValueError("F048 runtime heartbeat Catalog pin is invalid")
        return cls(
            role=role,
            instance_id=instance_id,
            ready=payload.get("ready") is True,
            store_id=payload["store_id"],
            model_id=payload["model_id"],
            model_checksum=payload["model_checksum"],
            catalog_release_id=catalog_release_id,
            catalog_checksum=payload["catalog_checksum"],
            dual_model_mode=payload.get("dual_model_mode") is True,
            legacy_model_id=(str(payload["legacy_model_id"]) if payload.get("legacy_model_id") else None),
            observed_at=str(payload.get("observed_at") or ""),
        )


def heartbeat_key(*, role: str, instance_id: str) -> str:
    normalized_role = role.strip().casefold()
    normalized_instance = instance_id.strip()
    if not normalized_role or ":" in normalized_role:
        raise ValueError("F048 heartbeat role is invalid")
    if not normalized_instance or ":" in normalized_instance:
        raise ValueError("F048 heartbeat instance ID is invalid")
    return f"{HEARTBEAT_KEY_PREFIX}:{normalized_role}:{normalized_instance}"


class RedisRuntimeHeartbeatStore:
    """Publish process evidence with a short TTL and enumerate it by SCAN."""

    def __init__(self, *, ttl_seconds: int = DEFAULT_HEARTBEAT_TTL_SECONDS) -> None:
        if ttl_seconds < 10:
            raise ValueError("F048 heartbeat TTL must be at least 10 seconds")
        self._ttl_seconds = ttl_seconds

    async def publish(
        self,
        *,
        role: str,
        instance_id: str,
        payload: dict[str, Any],
    ) -> None:
        redis = await get_redis_client()
        await redis.aset(
            heartbeat_key(role=role, instance_id=instance_id),
            {
                **payload,
                "observed_at": datetime.now(UTC).isoformat(),
            },
            expiration=self._ttl_seconds,
        )

    async def remove(self, *, role: str, instance_id: str) -> None:
        redis = await get_redis_client()
        await redis.adelete(heartbeat_key(role=role, instance_id=instance_id))


async def list_runtime_heartbeats() -> tuple[RuntimeHeartbeatEvidence, ...]:
    """Read all live F048 heartbeats without Redis ``KEYS``."""

    redis = await get_redis_client()
    pattern = f"{HEARTBEAT_KEY_PREFIX}:*"
    raw_keys = [key async for key in redis.async_connection.scan_iter(match=pattern)]
    if not raw_keys:
        return ()
    keys = [key.decode("utf-8") if isinstance(key, bytes) else str(key) for key in raw_keys]
    values = await redis.amget(keys) or []
    if len(values) != len(keys):
        # A heartbeat may expire between SCAN and MGET. Re-read only live keys.
        live: list[tuple[str, object]] = []
        for key in keys:
            value = await redis.aget(key)
            if value is not None:
                live.append((key, value))
    else:
        live = list(zip(keys, values, strict=True))

    evidence: list[RuntimeHeartbeatEvidence] = []
    prefix = f"{HEARTBEAT_KEY_PREFIX}:"
    for key, value in live:
        suffix = key.removeprefix(prefix)
        role, separator, instance_id = suffix.partition(":")
        if not separator:
            raise ValueError(f"Invalid F048 runtime heartbeat key: {key}")
        evidence.append(
            RuntimeHeartbeatEvidence.from_payload(
                role=role,
                instance_id=instance_id,
                payload=value,
            )
        )
    return tuple(sorted(evidence, key=lambda row: (row.role, row.instance_id)))
