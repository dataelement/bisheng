"""AC-13: observed response failures must remain independent from model outcome."""

import asyncio
from unittest.mock import Mock

import pytest
from starlette.responses import JSONResponse

from bisheng.dsh.api.responses import AuditObservedResponse


@pytest.mark.parametrize(
    "error,reason",
    [
        (ConnectionResetError("private"), "peer_disconnected"),
        (BrokenPipeError("private"), "peer_disconnected"),
        (asyncio.CancelledError(), "response_cancelled"),
        (OSError("private"), "send_failed"),
    ],
)
async def test_response_exception_fact_preserves_transport_behavior(error, reason):
    capture = Mock()
    response = AuditObservedResponse(JSONResponse({"ok": True}), capture)

    async def failed_send(_message):
        raise error

    with pytest.raises(type(error)):
        await response({"type": "http"}, None, failed_send)
    capture.response.assert_called_once_with("INTERRUPTED", reason)
    capture.terminal.assert_not_called()
