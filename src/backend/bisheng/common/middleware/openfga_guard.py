"""Sheds requests before OpenFGA is overrun, so saturation degrades into a notice.

The gate itself lives in ``core/openfga/concurrency.py`` and caps outbound
calls. This middleware is the other half: it turns a request away at the door
once the gate is nearly full, before any of the request's side effects have
run. Rejecting mid-request would leave half-finished writes behind, since a
single business request often makes several OpenFGA calls.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import Request
from fastapi.responses import ORJSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from bisheng.api_rate_limit.route_scope import is_api_rate_limit_excluded
from bisheng.common.errcode.server import OpenFgaOverloadedError
from bisheng.core.config.openfga import OpenFgaGuardConf
from bisheng.core.openfga.concurrency import openfga_gate
from bisheng.core.openfga.exceptions import FGAOverloadError

# Settings come from the DB-backed system config, which is itself Redis-cached
# for 100s. This second, much shorter cache keeps a Redis round trip off every
# single request while still picking up an admin edit within seconds.
_CONFIG_TTL_SECONDS = 5.0
_RETRY_AFTER_SECONDS = 60

_cached_conf: tuple[float, OpenFgaGuardConf] | None = None


async def _load_guard_conf() -> OpenFgaGuardConf:
    global _cached_conf
    now = time.monotonic()
    if _cached_conf is not None and now - _cached_conf[0] < _CONFIG_TTL_SECONDS:
        return _cached_conf[1]

    from bisheng.common.services.config_service import settings

    conf = await settings.aget_openfga_guard()
    _cached_conf = (now, conf)
    return conf


class OpenFgaGuardMiddleware(BaseHTTPMiddleware):
    """Turns requests away while the OpenFGA concurrency gate is saturated."""

    @staticmethod
    def _overload_response(reason: str) -> Response:
        percent = openfga_gate.reject_percent
        return ORJSONResponse(
            status_code=OpenFgaOverloadedError.HttpStatus,
            headers={'Retry-After': str(_RETRY_AFTER_SECONDS)},
            content={
                'status_code': OpenFgaOverloadedError.Code,
                'status_message': f'当前服务器资源使用已超过{percent}%，请耐心等待几分钟后重新尝试',  # noqa: RUF001
                'data': {
                    'reason': reason,
                    'retry_after': _RETRY_AFTER_SECONDS,
                },
            },
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Any:
        path = request.url.path
        method = request.method.upper()
        if request.scope.get('type') != 'http' or is_api_rate_limit_excluded(path, method):
            return await call_next(request)

        try:
            conf = await _load_guard_conf()
            openfga_gate.configure(
                enabled=conf.enabled,
                max_in_flight=conf.max_in_flight,
                reject_ratio=conf.reject_ratio,
                acquire_timeout=conf.acquire_timeout,
            )
        except Exception:
            # Fail-open by design: a broken config read must not take the API
            # down with it. The gate keeps whatever settings it already had.
            logger.exception('event=openfga_guard_fail_open path={}', path)
            return await call_next(request)

        if openfga_gate.is_overloaded():
            logger.warning(
                'event=openfga_guard_shed path={} method={} in_flight={} capacity={} threshold={}%',
                path,
                method,
                openfga_gate.in_flight,
                openfga_gate.capacity,
                openfga_gate.reject_percent,
            )
            return self._overload_response('gate_saturated')

        try:
            return await call_next(request)
        except FGAOverloadError as exc:
            # The gate filled up after this request was admitted. Same answer as
            # the door check, just discovered later.
            logger.warning(
                'event=openfga_guard_timeout path={} method={} detail={}',
                path,
                method,
                exc,
            )
            return self._overload_response('gate_wait_timeout')
