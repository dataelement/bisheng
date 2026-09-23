"""Paginate assigned and revoked seats through the Gateway's state-specific contract."""

import base64
import hashlib
import json

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError, DshInvalidRequestError


async def read_seat_page(request, *, actor, target, cursor, limit, keyword, seat_state, login_state):
    payload = {
        "resource": "seats",
        "actor": actor,
        "target": target,
        "keyword": keyword,
        "login_state": login_state,
    }

    async def fetch(state, cursor, size):
        page = await request("management", {**payload, "seat_state": state, "cursor": cursor, "limit": size})
        if (
            not isinstance(page, dict)
            or set(page) != {"items", "has_more", "next_cursor"}
            or not isinstance(page["items"], list)
            or len(page["items"]) > size
            or type(page["has_more"]) is not bool
            or not (page["next_cursor"] is None or isinstance(page["next_cursor"], str))
            or (page["has_more"] and not page["next_cursor"])
        ):
            raise DshAuthorizationUnavailableError()
        return page

    if seat_state is not None:
        return await fetch(seat_state, cursor, limit)
    binding = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    state, inner = "ASSIGNED", None
    if cursor:
        try:
            saved = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if (
                set(saved) != {"state", "cursor", "binding"}
                or saved["binding"] != binding
                or saved["state"] not in {"ASSIGNED", "REVOKED"}
                or not (saved["cursor"] is None or isinstance(saved["cursor"], str))
            ):
                raise ValueError("Invalid seat cursor")
            state, inner = saved["state"], saved["cursor"]
        except (ValueError, TypeError, KeyError):
            raise DshInvalidRequestError() from None

    def encoded(state, cursor):
        return base64.urlsafe_b64encode(
            json.dumps({"state": state, "cursor": cursor, "binding": binding}).encode()
        ).decode()

    page = await fetch(state, inner, limit)
    if page["has_more"]:
        return {**page, "next_cursor": encoded(state, page["next_cursor"])}
    if state == "REVOKED":
        return page
    remaining = limit - len(page["items"])
    revoked = await fetch("REVOKED", None, max(1, remaining))
    if remaining == 0:
        more = bool(revoked["items"])
        return {**page, "has_more": more, "next_cursor": encoded("REVOKED", None) if more else None}
    return {
        "items": page["items"] + revoked["items"],
        "has_more": revoked["has_more"],
        "next_cursor": encoded("REVOKED", revoked["next_cursor"]) if revoked["has_more"] else None,
    }
