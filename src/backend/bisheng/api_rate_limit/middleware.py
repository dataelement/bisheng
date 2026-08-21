from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import ORJSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.routing import Match

from bisheng.api_rate_limit.domain.repositories.implementations import (
    ApiRateLimitRedisRepository,
    RateLimitDecision,
)
from bisheng.api_rate_limit.domain.schemas import ApiRateLimitConfig, RateLimitLimits
from bisheng.api_rate_limit.domain.services import ApiRateLimitService
from bisheng.api_rate_limit.route_scope import is_api_rate_limit_excluded
from bisheng.common.errcode.server import ApiRateLimitedError
from bisheng.core.cache.redis_manager import get_redis_client

ConfigProvider = Callable[[], Awaitable[ApiRateLimitConfig]]
Counter = Callable[[str, str, RateLimitLimits], Awaitable[RateLimitDecision]]


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Any,
        *,
        config_provider: ConfigProvider | None = None,
        counter: Counter | None = None,
    ) -> None:
        super().__init__(app)
        self._config_provider = config_provider or ApiRateLimitService.get_runtime_config
        self._counter = counter or self._check_counter

    @staticmethod
    async def _check_counter(
        method: str,
        route_template: str,
        limits: RateLimitLimits,
    ) -> RateLimitDecision:
        repository = ApiRateLimitRedisRepository(await get_redis_client())
        return await repository.check(
            method=method,
            route_template=route_template,
            limits=limits,
        )

    @classmethod
    def _is_excluded(cls, path: str, method: str) -> bool:
        return is_api_rate_limit_excluded(path, method)

    @staticmethod
    def _resolve_route_template(request: Request) -> str | None:
        scope = dict(request.scope)
        for route in request.app.router.routes:
            match, _child_scope = route.matches(scope)
            if match == Match.FULL:
                return getattr(route, "path_format", None) or getattr(route, "path", None)
        return None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        method = request.method.upper()
        if request.scope.get("type") != "http" or self._is_excluded(path, method):
            return await call_next(request)

        route_template = self._resolve_route_template(request)
        if route_template is None:
            return await call_next(request)

        try:
            config = await self._config_provider()
            resolved = ApiRateLimitService.resolve_policy(
                config,
                method=method,
                route_template=route_template,
            )
            if resolved.policy.limits.is_disabled():
                return await call_next(request)
            decision = await self._counter(method, route_template, resolved.policy.limits)
        except Exception:
            # Rate limiting is explicitly fail-open when Redis/config runtime access fails.
            logger.exception(
                "event=api_rate_limit_fail_open stage=runtime method={} route_template={}",
                method,
                route_template,
            )
            return await call_next(request)

        if decision.allowed:
            return await call_next(request)

        retry_after = max(1, decision.retry_after)
        logger.warning(
            "event=api_rate_limited method={} route_template={} rule_type={} dimension={} retry_after={} revision={}",
            method,
            route_template,
            resolved.match_type.value if resolved.match_type else "GLOBAL",
            decision.dimension.value if decision.dimension else "unknown",
            retry_after,
            config.revision,
        )
        return ORJSONResponse(
            status_code=ApiRateLimitedError.HttpStatus,
            headers={"Retry-After": str(retry_after)},
            content={
                "status_code": ApiRateLimitedError.Code,
                "status_message": resolved.policy.message,
                "data": {
                    "retry_after": retry_after,
                    "dimension": decision.dimension.value if decision.dimension else None,
                },
            },
        )
