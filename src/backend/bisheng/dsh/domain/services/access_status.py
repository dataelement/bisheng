"""Read login-time seat eligibility independently of quota configuration."""

import asyncio

from loguru import logger

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError
from bisheng.dsh.domain.schemas.admin import SeatItem
from bisheng.dsh.infrastructure.gateway_client import GatewayCommandRejected


async def read_access_statuses(items, *, tenant, actor, snapshot, request):
    result = {row["user_id"]: "UNAVAILABLE" if row["authorized"] else "UNAUTHORIZED" for row in items}
    candidates = [row for row in items if row["authorized"]]
    if not candidates:
        return result
    try:
        license_snapshot = await asyncio.wait_for(snapshot(actor, tenant), timeout=4)
    except (DshAuthorizationUnavailableError, GatewayCommandRejected, TimeoutError):
        logger.warning("DSH seat license snapshot unavailable for tenant {}", tenant)
        return result
    if license_snapshot["status"] != "active":
        return {key: "LICENSE_UNAVAILABLE" if value == "UNAVAILABLE" else value for key, value in result.items()}

    semaphore = asyncio.Semaphore(6)

    async def read(row):
        user_id = row["user_id"]
        async with semaphore:
            try:
                for state in ("ASSIGNED", "REVOKED"):
                    page = await request(
                        "management",
                        {
                            "resource": "seats",
                            "actor": actor,
                            "target": {"tenant_id": str(tenant), "user_id": str(user_id)},
                            "seat_state": state,
                            "cursor": None,
                            "limit": 1,
                        },
                    )
                    if (
                        set(page) != {"items", "next_cursor", "has_more"}
                        or not isinstance(page["items"], list)
                        or len(page["items"]) > 1
                        or page["has_more"] is not False
                        or page["next_cursor"] is not None
                    ):
                        raise ValueError("Invalid single-user seat page")
                    if page["items"]:
                        seat = SeatItem.model_validate(page["items"][0])
                        if int(seat.user_id) != user_id or int(seat.tenant_id) != tenant or seat.state != state:
                            raise ValueError("Seat identity mismatch")
                        result[user_id] = "AUTHORIZED" if state == "ASSIGNED" else "REVOKED"
                        return
                result[user_id] = "UNAUTHORIZED"
            except (DshAuthorizationUnavailableError, GatewayCommandRejected, ValueError, TimeoutError):
                logger.warning("DSH seat snapshot unavailable for tenant {}, user {}", tenant, user_id)

    try:
        await asyncio.wait_for(asyncio.gather(*(read(row) for row in candidates)), timeout=6)
    except TimeoutError:
        logger.warning("DSH seat page lookup timed out for tenant {}", tenant)
    return result
