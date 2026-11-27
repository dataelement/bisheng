"""Strict exchange request parsing and global policy administration."""

import json
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.oauth2_provider import OAuth2InvalidRequestError
from bisheng.common.schemas.api import PageData, resp_200
from bisheng.oauth2_provider.domain.schemas.exchange import OAuth2ExchangePolicyUpdate
from bisheng.oauth2_provider.domain.schemas.platform_exchange import PLATFORM_SESSION_TOKEN_TYPE
from bisheng.oauth2_provider.runtime import get_oauth2_runtime

admin_router = APIRouter(prefix="/oauth2/exchange-policies", tags=["OAuth2 Exchange Admin"])


async def require_global_admin(user=Depends(UserPayload.get_login_user)):
    if not getattr(user, "is_global_super", False):
        raise HTTPException(status_code=403, detail="Global administrator required")
    return user


@admin_router.get("")
async def list_policies(
    source_client_id: str | None = Query(None, max_length=128),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user=Depends(require_global_admin),
    runtime=Depends(get_oauth2_runtime),
):
    rows, total = await runtime.exchange.list_policies(source_client_id, page, page_size)
    return resp_200(data=PageData(data=rows, total=total))


@admin_router.put("/{source_client_id}/{target_client_id}")
async def put_policy(
    source_client_id: str,
    target_client_id: str,
    body: OAuth2ExchangePolicyUpdate,
    user=Depends(require_global_admin),
    runtime=Depends(get_oauth2_runtime),
):
    if not 1 <= len(source_client_id) <= 128 or not 1 <= len(target_client_id) <= 128:
        raise OAuth2InvalidRequestError()
    result = await runtime.exchange.put_policy(source_client_id, target_client_id, body, int(user.user_id))
    return resp_200(data=result)


async def parse_exchange(request):
    raw = await request.body()
    if len(raw) > 65536 or request.query_params:
        raise OAuth2InvalidRequestError()
    try:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() == "application/json":
            pairs = json.loads(raw, object_pairs_hook=lambda value: value)
        else:
            pairs = parse_qsl(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=16)
        if not isinstance(pairs, list):
            raise ValueError("Invalid body")
        result = {}
        for key, value in pairs:
            if not isinstance(key, str) or not isinstance(value, str) or key in result:
                raise ValueError("Invalid field")
            result[key] = value
    except (ValueError, TypeError, UnicodeError):
        raise OAuth2InvalidRequestError() from None
    allowed = {
        "grant_type",
        "client_id",
        "client_secret",
        "subject_token",
        "subject_token_type",
        "requested_token_type",
        "audience",
        "scope",
    }
    if set(result) - allowed or any(
        len(result.get(key, "")) > limit
        for key, limit in [("subject_token", 16384), ("audience", 128), ("client_id", 128), ("scope", 512)]
    ):
        raise OAuth2InvalidRequestError()
    if result.get("subject_token_type") == PLATFORM_SESSION_TOKEN_TYPE:
        if (
            "client_id" in result
            or "client_secret" in result
            or (
                "authorization" in request.headers
                and not request.headers["authorization"].lower().startswith("bearer ")
            )
        ):
            raise OAuth2InvalidRequestError()
    elif "authorization" in request.headers:
        if (
            not request.headers["authorization"].lower().startswith("basic ")
            or "client_id" in result
            or "client_secret" in result
        ):
            raise OAuth2InvalidRequestError()
    return result
