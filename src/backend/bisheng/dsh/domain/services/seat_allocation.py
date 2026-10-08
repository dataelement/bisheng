"""Explicit person grants; successful receipts are safe to replay after response loss."""

from bisheng.common.errcode.dsh import (
    DshAuthorizationUnavailableError,
    DshDshDisabledError,
    DshLicenseExpiredError,
    DshLicenseInvalidError,
    DshOperationConflictError,
    DshSeatLimitReachedError,
    DshSeatRevokedError,
    DshUserDisabledError,
)


async def allocate_seats(gateway, operation_id, actor, tenant, user_ids):
    if not user_ids:
        return
    result = await gateway.request(
        "assign_batch",
        {
            "operation_id": operation_id,
            "actor": actor,
            "target": {"tenant_id": str(tenant)},
            "user_ids": [str(value) for value in sorted(set(user_ids))],
        },
    )
    if result.get("operation_id") != operation_id:
        raise DshAuthorizationUnavailableError()
    if result.get("status") == "SUCCEEDED" and result.get("selected") == len(set(user_ids)):
        return
    errors = {
        "seat_limit_reached": DshSeatLimitReachedError,
        "seat_revoked": DshSeatRevokedError,
        "authorization_conflict": DshOperationConflictError,
        "license_expired": DshLicenseExpiredError,
        "license_invalid": DshLicenseInvalidError,
        "dsh_disabled": DshDshDisabledError,
        "user_disabled": DshUserDisabledError,
    }
    if result.get("status") == "FAILED" and result.get("result_code") in errors:
        raise errors[result["result_code"]]()
    raise DshAuthorizationUnavailableError()
