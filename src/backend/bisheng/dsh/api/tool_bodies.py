"""Bounded strict JSON parsing after the endpoint's credential dependencies."""

from bisheng.common.errcode.dsh import DshToolArgumentsInvalidError, DshToolInputTooLargeError
from bisheng.utils.bounded_json import strict_json


async def read_tool_body(request, limit, model):
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise DshToolArgumentsInvalidError()
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise DshToolArgumentsInvalidError()
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise DshToolInputTooLargeError()
        body.extend(chunk)
    try:
        return model.model_validate(strict_json(bytes(body).decode("utf-8")))
    except (ValueError, UnicodeError, RecursionError):
        raise DshToolArgumentsInvalidError() from None
