"""F016 billing scope: knowledge space, channel image view, answer traceability; others unchanged."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.dsh import DshModelNotAllowedError
from bisheng.dsh.domain.schemas.pricing import CreditSettingState
from bisheng.dsh.domain.services import chat_credits
from test.dsh.pricing_fixtures import LEGACY_EQUIVALENT_PRICING


@pytest.fixture
def dsh_enabled(monkeypatch):
    from bisheng.common.services.config_service import settings

    monkeypatch.setitem(settings.__dict__, "dsh", settings.dsh.model_copy(update={"enabled": True}))


@pytest.mark.parametrize(
    ("app_type", "billed"),
    [
        ("daily_chat", True),
        ("linsight", True),
        ("knowledge_space", True),  # F016
        ("rag_traceability", False),  # workflows use it too; the workbench passes daily_chat
        ("workflow", False),
        ("assistant", False),
        ("knowledge_base", False),
        ("evaluation", False),
        ("model_gateway", False),
        ("model_test", False),
    ],
)
def test_governed_scenarios(dsh_enabled, app_type, billed):
    assert chat_credits.governed(SimpleNamespace(app_type=app_type)) is billed


def test_nothing_is_governed_when_the_enterprise_client_is_off(monkeypatch):
    from bisheng.common.services.config_service import settings

    monkeypatch.setitem(settings.__dict__, "dsh", settings.dsh.model_copy(update={"enabled": False}))
    assert not chat_credits.governed(SimpleNamespace(app_type="knowledge_space"))


@pytest.fixture
def chat_env(monkeypatch):
    from bisheng.common.services.config_service import settings
    from bisheng.core.context import tenant
    from bisheng.dsh import runtime
    from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords

    monkeypatch.setattr(tenant, "get_current_tenant_id", lambda: 1)
    monkeypatch.setattr(
        CurrentIdentityRecords,
        "get",
        AsyncMock(return_value=SimpleNamespace(active=True, tenant_active=True, natural_person=True)),
    )
    policy = SimpleNamespace(allowed_model_ids=[7], rows=[], version=1, quota_epoch=1, monthly_token_limit=1_000_000)
    monkeypatch.setattr(runtime, "read_policy", AsyncMock(return_value=policy))
    admission = AsyncMock(side_effect=lambda event, **kwargs: event)
    service = SimpleNamespace(activate=AsyncMock(), usage=SimpleNamespace(check_and_start=admission), model=object())
    monkeypatch.setattr(runtime, "get_model_runtime", AsyncMock(return_value=service))
    monkeypatch.setattr(runtime, "read_model_pricing", AsyncMock(return_value=LEGACY_EQUIVALENT_PRICING))
    monkeypatch.setattr(runtime, "read_credit_setting", AsyncMock(return_value=CreditSettingState()))
    monkeypatch.setitem(settings.__dict__, "dsh", settings.dsh.model_copy(update={"billing_timezone": "Asia/Shanghai"}))
    return admission


async def test_user_cannot_bill_a_model_outside_their_scope(chat_env):
    with pytest.raises(DshModelNotAllowedError):
        await chat_credits.start(SimpleNamespace(user_id=2, model_info=SimpleNamespace(id=9)))
    chat_env.assert_not_awaited()


async def test_admin_chosen_helper_model_is_billed_without_the_scope_check(chat_env):
    model = SimpleNamespace(user_id=2, model_info=SimpleNamespace(id=9), admin_selected=True)
    _, event, _ = await chat_credits.start(model)
    assert event.model_id == 9
    chat_env.assert_awaited_once()


async def test_unmetered_context_reaches_tasks_created_inside_and_resets():
    async def observe():
        return chat_credits._call_mode()

    assert chat_credits._call_mode() == ""
    with chat_credits.unmetered():
        task = asyncio.create_task(observe())
    assert chat_credits._call_mode() == ""
    assert await task == "unmetered"


async def test_knowledge_source_llm_defaults_to_traceability_and_is_admin_selected(monkeypatch):
    from bisheng.llm.domain.services.llm import LLMService

    created = AsyncMock(return_value="llm")
    monkeypatch.setattr(LLMService, "aget_knowledge_llm", AsyncMock(return_value=SimpleNamespace(source_model_id=5)))
    monkeypatch.setattr(LLMService, "get_bisheng_llm", created)
    await LLMService.get_knowledge_source_llm_async(2)
    assert created.await_args.kwargs["app_type"] is ApplicationTypeEnum.RAG_TRACEABILITY
    assert created.await_args.kwargs["admin_selected"] is True
    await LLMService.get_knowledge_source_llm_async(2, app_type=ApplicationTypeEnum.DAILY_CHAT)
    assert created.await_args.kwargs["app_type"] is ApplicationTypeEnum.DAILY_CHAT
    assert created.await_args.kwargs["app_id"] == "daily_chat"


async def test_traceability_passes_the_scenario_through(monkeypatch):
    from bisheng.common.chat import utils
    from bisheng.llm.domain.services.llm import LLMService

    monkeypatch.setattr(utils.ChatMessageDao, "aget_message_by_id", AsyncMock(return_value=SimpleNamespace(user_id=2)))
    getter = AsyncMock(return_value=None)
    monkeypatch.setattr(LLMService, "get_knowledge_source_llm_async", getter)
    monkeypatch.setattr(utils, "extract_answer_keys_async", AsyncMock(return_value=[]))
    document = SimpleNamespace(metadata={}, page_content="")
    await utils.process_source_document([document], "chat", 1, "answer", app_type=ApplicationTypeEnum.DAILY_CHAT)
    getter.assert_awaited_once_with(2, app_type=ApplicationTypeEnum.DAILY_CHAT)
    getter.reset_mock()
    await utils.process_source_document([document], "chat", 1, "answer")
    getter.assert_awaited_once_with(2)


async def test_image_view_model_is_admin_selected(monkeypatch):
    from bisheng.common.image_view import loop
    from bisheng.llm.domain.services.llm import LLMService

    monkeypatch.setattr(loop, "_image_view_model_id", AsyncMock(return_value="11"))
    created = AsyncMock(return_value="vision")
    monkeypatch.setattr(LLMService, "get_bisheng_llm", created)
    assert await loop.resolve_image_view_llm(1, user_id=2, app_type=ApplicationTypeEnum.DAILY_CHAT) == "vision"
    assert created.await_args.kwargs["admin_selected"] is True
    assert created.await_args.kwargs["app_type"] is ApplicationTypeEnum.DAILY_CHAT


async def test_channel_image_view_is_billed_as_daily_chat(monkeypatch):
    from bisheng.channel.domain.services import channel_chat_service as module

    seen = {}

    async def fake_stream(llm, inputs, registry, *, visual, user_id=None, app_type=None):
        seen["app_type"] = app_type
        yield "chunk"

    service = module.ChannelChatService
    monkeypatch.setattr(module, "run_react_vision_stream", fake_stream)
    monkeypatch.setattr(service, "_resolve_workbench_visual", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "_apply_image_anchors", lambda content, visual: (content, {}))
    stream = service.stream_article_reply(
        llm=object(),
        article_content="text",
        question="q",
        system_prompt="s",
        user_prompt_template="{article_content}{question}",
        history_messages=[],
        model_id=7,
        max_chunk_size=100,
        tenant_id=1,
        user_id=2,
    )
    assert [chunk async for chunk in stream] == ["chunk"]
    assert seen["app_type"] is ApplicationTypeEnum.DAILY_CHAT
