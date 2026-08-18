"""Auto-publish configuration service.

Reads portal auto-publish rules and provides rule matching for the
post-parse hook. Configuration is cached in Redis with a short TTL
to avoid querying the portal config store on every file parse.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_CACHE_KEY_PREFIX = "auto_publish_rules"
_CACHE_TTL_SECONDS = 30


@dataclass(frozen=True)
class AutoPublishRule:
    """In-memory representation of a single auto-publish rule."""

    id: str
    enabled: bool
    document_type_code: str
    target_space_id: int | None = None
    source_space_ids: list[int] = field(default_factory=list)


class AutoPublishConfigService:
    """Reads and caches portal auto-publish rules for the post-parse hook."""

    @classmethod
    async def get_enabled_rules(cls, tenant_id: int) -> list[AutoPublishRule]:
        """Return enabled auto-publish rules from portal config.

        Uses Redis cache with 30s TTL to avoid frequent DB reads.
        Falls back to direct DB read on cache miss.
        """
        from bisheng.core.cache.redis_manager import get_redis_client

        cache_key = f"{_CACHE_KEY_PREFIX}:{tenant_id}"

        # Try cache first
        try:
            redis = await get_redis_client()
            cached = redis.get(cache_key)
            if cached is not None:
                # RedisClient.get() already unpickles the value
                if isinstance(cached, list):
                    return [cls._dict_to_rule(r) for r in cached if isinstance(r, dict) and r.get("enabled", False)]
        except Exception:
            logger.debug("auto_publish_config cache read failed, falling back to DB")

        # Cache miss - read from portal config
        raw_rules = await cls._load_rules_from_config(tenant_id)

        # Cache for TTL (RedisClient.set uses pickle serialization)
        try:
            redis = await get_redis_client()
            redis.set(cache_key, raw_rules, expiration=_CACHE_TTL_SECONDS)
        except Exception:
            logger.debug("auto_publish_config cache write failed")

        return [cls._dict_to_rule(r) for r in raw_rules if isinstance(r, dict) and r.get("enabled", False)]

    @classmethod
    async def _load_rules_from_config(cls, tenant_id: int) -> list[dict]:
        """Load raw auto_publish_rules from the portal config store.

        Reads the raw JSON from the Config table directly because the BiSheng-side
        PortalConfig Pydantic model may not yet declare the auto_publish_rules field.
        """
        from bisheng.core.database import get_async_db_session
        from bisheng.shougang_portal_config.domain.repositories.implementations.portal_admin_config_repository_impl import (
            PortalAdminConfigRepositoryImpl,
        )

        async with get_async_db_session() as session:
            repository = PortalAdminConfigRepositoryImpl(session)
            config_record = await repository.get(tenant_id)
            if config_record is None or not config_record.value:
                return []

        # Parse the raw JSON to extract auto_publish_rules
        try:
            raw_config = json.loads(config_record.value)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "auto_publish_config: failed to parse portal config JSON for tenant_id=%s",
                tenant_id,
            )
            return []

        portal = raw_config.get("portal")
        if not isinstance(portal, dict):
            return []

        raw_rules = portal.get("auto_publish_rules")
        if not isinstance(raw_rules, list):
            return []

        # Filter to valid dicts only
        return [r for r in raw_rules if isinstance(r, dict)]

    @classmethod
    def _dict_to_rule(cls, data: dict) -> AutoPublishRule:
        """Convert a raw dict to an AutoPublishRule dataclass instance."""
        return AutoPublishRule(
            id=str(data.get("id", "")),
            enabled=bool(data.get("enabled", False)),
            document_type_code=str(data.get("document_type_code", "")),
            target_space_id=data.get("target_space_id"),
            source_space_ids=data.get("source_space_ids") or [],
        )

    @classmethod
    def match_rule(
        cls,
        rules: list[AutoPublishRule],
        source_space_id: int,
        file_category_code: str,
    ) -> AutoPublishRule | None:
        """Match a file against auto-publish rules.

        Returns the first matching enabled rule, or None.

        A rule matches when:
        1. rule.enabled is True
        2. rule.document_type_code == file_category_code (case-insensitive, stripped)
        3. source_space_id is in rule.source_space_ids
        """
        if not file_category_code:
            return None
        normalized_code = file_category_code.strip().upper()
        for rule in rules:
            if not rule.enabled:
                continue
            if rule.document_type_code.strip().upper() != normalized_code:
                continue
            if source_space_id in rule.source_space_ids:
                return rule
        return None
