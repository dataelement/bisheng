"""Image capability contract, tenant isolation and provider message forwarding."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from bisheng.common.errcode.dsh import DshUnsupportedParameterError
from bisheng.dsh.domain.schemas.chat import ChatCapabilities, DshChatRequest
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.domain.services.vision import VisionSetting, configure_vision, repository
from bisheng.dsh.infrastructure.chat_adapter import DshChatAdapter

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"image").decode()


def body(url=PNG):
    return DshChatRequest(
        model="bisheng:1",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe"},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ],
    )


def test_image_requires_enabled_capability_and_preserves_blocks():
    with pytest.raises(DshUnsupportedParameterError):
        DshChatAdapter().prepare(body(), object(), ChatCapabilities())
    prepared = DshChatAdapter().prepare(body(), object(), ChatCapabilities(vision=True))
    assert prepared.messages[0].content[1]["image_url"]["url"] == PNG
    assert ChatCapabilities().client_fields()["vision"] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/image.png",
        "file:///etc/passwd",
        "data:image/png;base64,eA==",
        "data:image/svg+xml;base64,eA==",
    ],
)
def test_invalid_image_is_rejected(url):
    with pytest.raises(ValidationError):
        body(url)


@pytest.mark.parametrize("count", [11, 30])
@pytest.mark.parametrize("separate_messages", [False, True])
def test_image_count_is_not_limited_within_size_budget(count, separate_messages):
    image = {"type": "image_url", "image_url": {"url": PNG}}
    messages = (
        [{"role": "user", "content": [image]} for _ in range(count)]
        if separate_messages
        else [{"role": "user", "content": [image] * count}]
    )
    request = DshChatRequest(model="bisheng:1", messages=messages)
    prepared = DshChatAdapter().prepare(request, object(), ChatCapabilities(vision=True))
    forwarded = [part for message in prepared.messages for part in message.content]
    assert len(forwarded) == count
    assert all(part == {"type": "image_url", "image_url": {"url": PNG, "detail": "auto"}} for part in forwarded)


def test_total_image_size_is_still_limited_across_messages():
    url = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * (4 * 1024 * 1024)).decode()
    with pytest.raises(ValidationError, match="total request size limit"):
        DshChatRequest(
            model="bisheng:1",
            messages=[
                {"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]} for _ in range(6)
            ],
        )


def test_single_image_size_is_still_limited():
    url = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024)).decode()
    with pytest.raises(ValidationError, match="at most 5 MiB"):
        body(url)


def test_setting_is_scoped_to_current_tenant():
    with profile_scope(1):
        first = repository(42).key
    with profile_scope(2):
        second = repository(42).key
    assert first != second


async def test_configuration_checks_governed_model_before_saving(monkeypatch):
    from bisheng.dsh.domain.services import vision
    from bisheng.llm.domain.services.llm import LLMService

    store = SimpleNamespace(read=AsyncMock(return_value='{"vision":true}'), save=AsyncMock())
    snapshot = AsyncMock()
    monkeypatch.setattr(LLMService, "get_dsh_model_snapshot", snapshot)
    monkeypatch.setattr(vision, "repository", lambda model_id: store)
    assert await configure_vision(42, VisionSetting(vision=True)) == {"vision": True}
    snapshot.assert_awaited_once_with(42)
    store.save.assert_awaited_once()
    snapshot.side_effect = RuntimeError("forbidden")
    store.save.reset_mock()
    with pytest.raises(RuntimeError):
        await configure_vision(42, VisionSetting(vision=False))
    store.save.assert_not_awaited()
