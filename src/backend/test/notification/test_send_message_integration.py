"""Integration test: verifies maybe_forward_external is called from send_message.

NOTE: InboxMessage model has a circular-import issue (JsonType defined after use)
that prevents direct top-level imports. All model/enum imports are done lazily
inside test functions, after the conftest premock_import_chain() runs.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
@patch("bisheng.message.domain.services.message_service.maybe_forward_external")
async def test_send_message_calls_forwarder_at_the_end(mock_forward):
    """send_message() must call maybe_forward_external(saved_message) at the end."""
    from bisheng.message.domain.services.message_service import MessageService
    from bisheng.message.domain.models.inbox_message import MessageTypeEnum, MessageStatusEnum

    # Build a minimal service instance bypassing __init__
    svc = MessageService.__new__(MessageService)
    svc.message_repository = MagicMock()
    svc.message_read_repository = MagicMock()
    svc._handler_map = {}

    saved = MagicMock(id=42, action_code="request_channel", receiver=[7])
    svc.message_repository.save = AsyncMock(return_value=saved)

    await svc.send_message(
        content=[],
        sender=1,
        message_type=MessageTypeEnum.APPROVE,
        receiver=[7],
        status=MessageStatusEnum.WAIT_APPROVE,
        action_code="request_channel",
    )

    mock_forward.assert_called_once_with(saved)


@pytest.mark.asyncio
@patch("bisheng.message.domain.services.message_service.maybe_forward_external")
async def test_forwarder_exception_does_not_break_send_message(mock_forward):
    """If forwarder raises, send_message must still return the saved message."""
    from bisheng.message.domain.services.message_service import MessageService
    from bisheng.message.domain.models.inbox_message import MessageTypeEnum, MessageStatusEnum

    svc = MessageService.__new__(MessageService)
    svc.message_repository = MagicMock()
    svc.message_read_repository = MagicMock()
    svc._handler_map = {}

    saved = MagicMock(id=43, action_code="approved_channel", receiver=[8])
    svc.message_repository.save = AsyncMock(return_value=saved)
    mock_forward.side_effect = RuntimeError("forwarder bug")

    result = await svc.send_message(
        content=[],
        sender=1,
        message_type=MessageTypeEnum.NOTIFY,
        receiver=[8],
        status=MessageStatusEnum.APPROVED,
        action_code="approved_channel",
    )

    assert result is saved
