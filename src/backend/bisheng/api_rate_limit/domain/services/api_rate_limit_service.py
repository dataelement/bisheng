from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.exc import IntegrityError
from starlette.routing import BaseRoute

from bisheng.api_rate_limit.domain.repositories.implementations.api_rate_limit_repository_impl import (
    ApiRateLimitConfigRepositoryImpl,
    ApiRateLimitRedisRepository,
)
from bisheng.api_rate_limit.domain.schemas.api_rate_limit import (
    DEFAULT_RATE_LIMIT_MESSAGE,
    ApiRateLimitConfig,
    ApiRateLimitConfigUpdate,
    ApiRateLimitRouteCatalog,
    HttpMethod,
    RateLimitMatchType,
    RateLimitPolicy,
)
from bisheng.api_rate_limit.domain.services.api_route_catalog_service import ApiRouteCatalogService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.server import (
    ApiRateLimitConfigConflictError,
    ApiRateLimitConfigSyncError,
    ApiRateLimitForbiddenError,
)
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.database import get_async_db_session
from bisheng.utils.http_middleware import _check_is_global_super


@dataclass(frozen=True)
class ResolvedRateLimitPolicy:
    policy: RateLimitPolicy
    match_type: RateLimitMatchType | None


class ApiRateLimitService:
    @classmethod
    async def _assert_global_super(cls, user_id: int) -> None:
        if not await _check_is_global_super(user_id):
            raise ApiRateLimitForbiddenError()

    @classmethod
    async def _redis_repository(cls) -> ApiRateLimitRedisRepository:
        return ApiRateLimitRedisRepository(await get_redis_client())

    @staticmethod
    def _default_config() -> ApiRateLimitConfig:
        # Keep the empty configuration byte-stable so every replica computes the
        # same digest while Redis is being recovered before the first saved edit.
        return ApiRateLimitConfig(
            revision=0,
            updated_at=datetime.fromtimestamp(0, tz=timezone.utc),
            updated_by=None,
        )

    @classmethod
    async def _load_db_config(cls) -> ApiRateLimitConfig | None:
        async with get_async_db_session() as session:
            record = await ApiRateLimitConfigRepositoryImpl(session).get()
        if record is None or not record.value:
            return None
        return ApiRateLimitConfig.model_validate_json(record.value)

    @classmethod
    async def _persist_db_config(
        cls,
        config: ApiRateLimitConfig,
        *,
        expected_revision: int,
    ) -> None:
        async with get_async_db_session() as session:
            repository = ApiRateLimitConfigRepositoryImpl(session)
            async with session.begin():
                record = await repository.get_for_update()
                current_revision = 0
                if record is not None and record.value:
                    current_revision = ApiRateLimitConfig.model_validate_json(record.value).revision
                if current_revision != expected_revision:
                    raise ApiRateLimitConfigConflictError()
                await repository.write_value(config.model_dump_json(by_alias=True))

    @classmethod
    async def _ensure_active(
        cls,
        config: ApiRateLimitConfig,
        redis_repository: ApiRateLimitRedisRepository,
    ) -> None:
        active = await redis_repository.get_active()
        if (
            active is not None
            and active.revision == config.revision
            and redis_repository.content_digest(active) == redis_repository.content_digest(config)
        ):
            return
        candidate_key = await redis_repository.stage(config)
        if not await redis_repository.activate(candidate_key, config.revision):
            raise ApiRateLimitConfigSyncError()
        active = await redis_repository.get_active()
        if (
            active is None
            or active.revision != config.revision
            or redis_repository.content_digest(active) != redis_repository.content_digest(config)
        ):
            raise ApiRateLimitConfigSyncError()

    @classmethod
    async def get_config(cls, user: UserPayload) -> ApiRateLimitConfig:
        await cls._assert_global_super(user.user_id)
        try:
            config = await cls._load_db_config() or cls._default_config()
            await cls._ensure_active(config, await cls._redis_repository())
            return config
        except BaseErrorCode:
            raise
        except Exception as exc:
            logger.exception("failed to load or activate API rate limit config")
            raise ApiRateLimitConfigSyncError() from exc

    @classmethod
    async def get_route_catalog(
        cls,
        user: UserPayload,
        routes: Sequence[BaseRoute],
        *,
        keyword: str | None = None,
        method: HttpMethod | None = None,
        tag: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> ApiRateLimitRouteCatalog:
        await cls._assert_global_super(user.user_id)
        return ApiRouteCatalogService.list_routes(
            routes,
            keyword=keyword,
            method=method,
            tag=tag,
            page=page,
            page_size=page_size,
        )

    @classmethod
    async def update_config(
        cls,
        user: UserPayload,
        payload: ApiRateLimitConfigUpdate,
    ) -> ApiRateLimitConfig:
        await cls._assert_global_super(user.user_id)
        config = payload.next_config(user_id=user.user_id)
        try:
            redis_repository = await cls._redis_repository()
            candidate_key = await redis_repository.stage(config)
        except Exception as exc:
            logger.exception("failed to stage API rate limit config revision={}", config.revision)
            raise ApiRateLimitConfigSyncError() from exc

        try:
            await cls._persist_db_config(config, expected_revision=payload.expected_revision)
        except ApiRateLimitConfigConflictError:
            raise
        except IntegrityError as exc:
            raise ApiRateLimitConfigConflictError() from exc
        except Exception as exc:
            logger.exception("failed to persist API rate limit config revision={}", config.revision)
            raise ApiRateLimitConfigSyncError() from exc

        try:
            if not await redis_repository.activate(candidate_key, config.revision):
                raise ApiRateLimitConfigSyncError()
            active = await redis_repository.get_active()
            if (
                active is None
                or active.revision != config.revision
                or redis_repository.content_digest(active) != redis_repository.content_digest(config)
            ):
                raise ApiRateLimitConfigSyncError()
        except BaseErrorCode:
            raise
        except Exception as exc:
            logger.exception("failed to activate API rate limit config revision={}", config.revision)
            raise ApiRateLimitConfigSyncError() from exc
        return config

    @classmethod
    async def get_runtime_config(cls) -> ApiRateLimitConfig:
        redis_repository = await cls._redis_repository()
        active = await redis_repository.get_active()
        if active is not None:
            return active

        token = await redis_repository.acquire_recovery_lock()
        if token is None:
            return await redis_repository.get_active() or cls._default_config()
        try:
            config = await cls._load_db_config() or cls._default_config()
            await cls._ensure_active(config, redis_repository)
            return config
        finally:
            try:
                await redis_repository.release_recovery_lock(token)
            except Exception:
                # The lock expires quickly; release failure must not block business traffic.
                logger.exception("failed to release API rate limit recovery lock")

    @classmethod
    def resolve_policy(
        cls,
        config: ApiRateLimitConfig,
        *,
        method: str,
        route_template: str,
    ) -> ResolvedRateLimitPolicy:
        normalized_method = method.upper()
        method_path = next(
            (
                rule
                for rule in config.routes
                if rule.match_type == RateLimitMatchType.METHOD_PATH
                and rule.method is not None
                and rule.method.value == normalized_method
                and rule.path == route_template
            ),
            None,
        )
        path_rule = next(
            (
                rule
                for rule in config.routes
                if rule.match_type == RateLimitMatchType.PATH and rule.path == route_template
            ),
            None,
        )
        prefix_rule = max(
            (
                rule
                for rule in config.routes
                if rule.match_type == RateLimitMatchType.PREFIX and route_template.startswith(rule.path)
            ),
            key=lambda rule: len(rule.path),
            default=None,
        )
        rule = method_path or path_rule or prefix_rule
        if rule is None:
            source = config.global_rule
            match_type = None
        else:
            source = rule
            match_type = rule.match_type
        message = rule.message if rule is not None and rule.message else config.global_rule.message
        return ResolvedRateLimitPolicy(
            policy=RateLimitPolicy(
                limits=source.limits,
                message=message or DEFAULT_RATE_LIMIT_MESSAGE,
            ),
            match_type=match_type,
        )
