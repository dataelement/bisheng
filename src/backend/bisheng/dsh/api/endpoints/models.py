"""Frozen Desktop model endpoints, authenticated independently of browser cookies."""

import asyncio
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from bisheng.common.errcode.dsh import DshInvalidAccessTokenError, DshModelNotAllowedError, DshQuotaUnavailableError
from bisheng.dsh.api.dependencies import DshRuntime, get_runtime
from bisheng.dsh.api.responses import DshRoute
from bisheng.dsh.domain.schemas.chat import DshChatRequest
from bisheng.dsh.domain.services.access import DshPrincipal, principal_scope
from bisheng.dsh.domain.services.model import PreparedStream
from bisheng.dsh.runtime import get_model_runtime, read_persisted_usage, read_policy

router = APIRouter(route_class=DshRoute)


async def desktop_principal(request: Request, runtime: DshRuntime = Depends(get_runtime)) -> DshPrincipal:
    if len(request.headers.getlist("authorization")) != 1:
        raise DshInvalidAccessTokenError()
    return await runtime.access.authenticate(request.headers["authorization"])


class DshStreamingResponse(StreamingResponse):
    def __init__(self, stream: PreparedStream):
        self.prepared_stream = stream
        super().__init__(stream, media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Also runs if the peer leaves before the iterator's first read.
            await asyncio.shield(self.prepared_stream.aclose())


@router.get("/dsh/models")
async def models(principal: DshPrincipal = Depends(desktop_principal), runtime: DshRuntime = Depends(get_runtime)):
    service = await get_model_runtime(runtime)
    return await service.model.list_models(principal)


@router.post("/dsh/chat/completions")
async def complete(
    body: DshChatRequest,
    principal: DshPrincipal = Depends(desktop_principal),
    runtime: DshRuntime = Depends(get_runtime),
):
    service = await get_model_runtime(runtime)
    result = await service.complete(principal, body)
    return DshStreamingResponse(result) if isinstance(result, PreparedStream) else result


def billing_period(now: datetime, timezone: str) -> dict:
    local = now.astimezone(ZoneInfo(timezone))
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return {
        "month": start.strftime("%Y-%m"),
        "billing_timezone": timezone,
        "period_start": rfc3339(start),
        "reset_at": rfc3339(end),
    }


def rfc3339(value: datetime) -> str:
    # SQL timestamps are stored as UTC without an offset.
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@router.get("/dsh/usage")
async def usage(
    principal: DshPrincipal = Depends(desktop_principal),
    runtime: DshRuntime = Depends(get_runtime),
    model: Annotated[
        str | None,
        Query(
            pattern=r"^bisheng:[1-9][0-9]*$",
            max_length=27,
            description="Optional selected model; omitted returns informational totals without pooling allowances.",
        ),
    ] = None,
):
    period = billing_period(datetime.now(UTC), runtime.settings.billing_timezone)
    snapshot = None
    model_id = int(model.removeprefix("bisheng:")) if model else None
    selected_limit = None
    with principal_scope(principal):
        if model_id is not None:
            try:
                policy = await read_policy(int(principal.user_id))
            except Exception as exc:
                raise DshQuotaUnavailableError() from exc
            selected = (
                next((item for item in policy.model_configs if item.model_id == model_id), None) if policy else None
            )
            if selected is None:
                raise DshModelNotAllowedError()
            selected_limit = selected.monthly_token_limit
        try:
            service = await get_model_runtime(runtime)
            snapshot = await service.prepare_month(principal, period["month"])
        except Exception:
            try:
                snapshot = await read_persisted_usage(int(principal.user_id), period["month"])
            except Exception:
                snapshot = None
        if snapshot is None:
            try:
                policy = await read_policy(int(principal.user_id))
                limit = selected_limit if model_id is not None else (policy.monthly_token_limit if policy else None)
            except Exception:
                limit = None
            return {
                **period,
                "used": None,
                "limit": limit,
                "remaining": None,
                "source": "unavailable",
                "as_of": None,
                "quota_state": "unavailable",
            }
    if model_id is not None:
        used = (snapshot.get("models") or {}).get(str(model_id))
        limit = (snapshot.get("model_limits") or {}).get(str(model_id))
        if used is None or limit is None:
            return {
                **period,
                "used": None,
                "limit": selected_limit,
                "remaining": None,
                "source": "unavailable",
                "as_of": None,
                "quota_state": "unavailable",
            }
        snapshot = {**snapshot, "used": used, "limit": limit, "remaining": max(limit - used, 0)}
    live = snapshot["source"] == "live"
    state = "unavailable"
    if live and snapshot["quota_state"] == "ready":
        state = "available" if snapshot["remaining"] > 0 else "exhausted"
    return {
        **period,
        "used": snapshot["used"],
        "limit": snapshot["limit"],
        "remaining": snapshot["remaining"],
        "source": "live" if live else "persisted",
        "as_of": rfc3339(snapshot["as_of"]),
        "quota_state": state,
    }
