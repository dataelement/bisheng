"""Page-lease API for department concurrent-session control.

The browser session page holds one lease per tab and renews it here every
``RENEW_INTERVAL_S``. A rejected outcome is not an error response — the page
decides how to surface it — so only an invalid lease id answers 422.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.department.domain.services.department_flow_service import (
    DepartmentFlowService,
    SlotLease,
    SlotOutcome,
    normalize_lease_id,
)

router = APIRouter(prefix="/department-flow", tags=["DepartmentFlow"])

# Both ids come from ``generateUUID(32)`` / ``uuid4().hex`` — 32 hex chars,
# either case. Anything else is rejected before the service is called:
# ``ensure_lease`` would mint a fresh id that this response never returns, so
# the page would keep resending the bad value and add one dead lease per beat.
_LEASE_ID_PATTERN = r"^[0-9a-fA-F]{32}$"


class PresenceLeaseRequest(BaseModel):
    lease_id: str = Field(..., pattern=_LEASE_ID_PATTERN)


class PresenceReleaseRequest(PresenceLeaseRequest):
    department_id: int


def _invalid_lease_id(reason: str) -> HTTPException:
    return HTTPException(status_code=422, detail=reason)


@router.post("/presence/ensure")
async def presence_ensure(
    body: PresenceLeaseRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    outcome, lease = await DepartmentFlowService.ensure_lease(login_user, body.lease_id)
    limited = outcome is not SlotOutcome.SKIPPED
    if outcome is SlotOutcome.SKIPPED:
        # Distinguish "this department has no limit" from "Redis failed open":
        # the page stops heartbeating in the first case and keeps going in the
        # second, otherwise one Redis blip drops it out of the count forever.
        limit, _ = await DepartmentFlowService.resolve_limit_and_dept(login_user)
        limited = limit > 0

    return resp_200(
        data={
            "outcome": outcome.value,
            "department_id": lease.department_id if outcome is SlotOutcome.HELD and lease else None,
            "limited": limited,
        }
    )


async def _read_beacon_body(request: Request) -> dict[str, Any] | None:
    """Read the body from either a normal fetch or a ``sendBeacon`` Blob."""
    raw = await request.body()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


@router.post("/presence/release")
async def presence_release(
    request: Request,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    # ``navigator.sendBeacon`` posts a ``Blob``; reading and parsing the body by
    # hand keeps this working even when the blob's content-type is not the one
    # FastAPI's JSON parser expects.
    body = await _read_beacon_body(request)
    if body is None:
        raise _invalid_lease_id("request body must be a JSON object")

    raw_lease_id = body.get("lease_id")
    lease_id = normalize_lease_id(raw_lease_id if isinstance(raw_lease_id, str) else None)
    if lease_id is None:
        raise _invalid_lease_id("lease_id must be a 32-character hexadecimal string")
    try:
        department_id = int(body.get("department_id"))
    except (TypeError, ValueError):
        raise _invalid_lease_id("department_id must be an integer") from None

    # The member is still ``{login user id}:{lease id}``, so passing another
    # department's id cannot remove somebody else's lease.
    await DepartmentFlowService.release_lease(
        SlotLease(
            department_id=department_id,
            user_id=int(login_user.user_id),
            lease_id=lease_id,
        )
    )
    return resp_200(data=None)
