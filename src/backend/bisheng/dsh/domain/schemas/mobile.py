"""Optional request models for the mobile access routes.

Every field stays optional so one unexpected value cannot fail parsing. The
service decides which values are actually required and returns a bare 400.
"""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

DESKTOP_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
DISPLAY_NAME_LIMIT = 128
METHOD_LIMIT = 128


class MobileBindRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    desktopId: Any | None = None
    attachSecret: Any | None = None
    displayName: Any | None = None


class MobileUnbindRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    desktopId: Any | None = None


class MobileRpcRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    method: Any | None = None
    payload: Any | None = None


class MobileDesktop(BaseModel):
    model_config = ConfigDict(extra="ignore")

    desktopId: str | None = None
    displayName: str | None = None
    online: bool | None = None


class MobileDesktopList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    desktops: list[MobileDesktop] | None = None


def parse_bind(body: dict) -> tuple[str, str, str] | None:
    parsed = _parse(MobileBindRequest, body)
    if parsed is None or not _identifier(parsed.desktopId) or not _identifier(parsed.attachSecret):
        return None
    if parsed.displayName is None:
        return parsed.desktopId, parsed.attachSecret, ""
    if not isinstance(parsed.displayName, str) or len(parsed.displayName.strip()) > DISPLAY_NAME_LIMIT:
        return None
    return parsed.desktopId, parsed.attachSecret, parsed.displayName.strip()


def parse_unbind(body: dict) -> str | None:
    parsed = _parse(MobileUnbindRequest, body)
    if parsed is None or not _identifier(parsed.desktopId):
        return None
    return parsed.desktopId


def parse_rpc(body: dict) -> tuple[str, dict] | None:
    parsed = _parse(MobileRpcRequest, body)
    if parsed is None or not isinstance(parsed.method, str) or not parsed.method or len(parsed.method) > METHOD_LIMIT:
        return None
    payload = {} if parsed.payload is None else parsed.payload
    if not isinstance(payload, dict):
        return None
    return parsed.method, payload


def _parse(model, body: dict):
    try:
        return model.model_validate(body)
    except ValidationError:
        return None


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and DESKTOP_ID_PATTERN.fullmatch(value) is not None
