from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from bisheng.dsh.domain.schemas.contracts import DshTokenUsage
from bisheng.dsh.domain.services import chat_credits


@pytest.fixture
def accounting(monkeypatch):
    execution = SimpleNamespace(usage=DshTokenUsage(), provider_request_id=None)
    state = (None, None, execution)
    start = AsyncMock(return_value=state)
    finish = AsyncMock()
    monkeypatch.setattr(chat_credits, "governed", lambda model: True)
    monkeypatch.setattr(chat_credits, "start", start)
    monkeypatch.setattr(chat_credits, "finish", finish)
    return start, finish, execution


async def test_normal_generation_settles_once_with_exact_usage(accounting):
    start, finish, execution = accounting

    @chat_credits.account_async
    async def generate(model):
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="ok",
                        usage_metadata={
                            "input_tokens": 12,
                            "output_tokens": 7,
                            "total_tokens": 19,
                        },
                    )
                )
            ]
        )

    await generate(object())
    start.assert_awaited_once()
    finish.assert_awaited_once()
    assert finish.await_args.args[1] is True
    assert execution.usage.total_tokens == 19


async def test_stream_consumes_final_usage_and_closes_on_cancel(accounting):
    _start, finish, execution = accounting
    closed = []

    @chat_credits.account_async_stream
    async def stream(model):
        try:
            yield ChatGenerationChunk(message=AIMessageChunk(content="first"))
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    usage_metadata={
                        "input_tokens": 12,
                        "output_tokens": 7,
                        "total_tokens": 19,
                    },
                )
            )
        finally:
            closed.append(True)

    assert len([part async for part in stream(object())]) == 2
    assert execution.usage.total_tokens == 19
    finish.assert_awaited_once()
    finish.reset_mock()
    iterator = stream(object())
    await anext(iterator)
    await iterator.aclose()
    assert len(closed) == 2
    finish.assert_awaited_once()
    assert finish.await_args.args[1] is False


async def test_upstream_failure_is_settled_and_admission_failure_skips_provider(accounting):
    start, finish, execution = accounting
    calls = []

    @chat_credits.account_async
    async def generate(model):
        calls.append(True)
        raise RuntimeError("provider failed")

    with pytest.raises(RuntimeError, match="provider failed"):
        await generate(object())
    assert execution.usage.total_tokens is None
    finish.assert_awaited_once()
    start.side_effect = ValueError("quota exhausted")
    finish.reset_mock()
    with pytest.raises(ValueError, match="quota exhausted"):
        await generate(object())
    assert calls == [True]
    finish.assert_not_awaited()


def test_streaming_usage_accumulates_input_and_output_chunks():
    from bisheng.dsh.infrastructure.chat_adapter import accumulate_usage

    first = AIMessageChunk(content="", usage_metadata={"input_tokens": 120, "output_tokens": 0, "total_tokens": 120})
    last = AIMessageChunk(content="", usage_metadata={"input_tokens": 0, "output_tokens": 19, "total_tokens": 19})
    usage = accumulate_usage(accumulate_usage(DshTokenUsage(), first), last)
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (120, 19, 139)


@pytest.mark.parametrize("requested_id", ["7", 7])
async def test_chat_admission_uses_loaded_model_id(monkeypatch, requested_id):
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
    monkeypatch.setattr(
        runtime,
        "read_policy",
        AsyncMock(
            return_value=SimpleNamespace(
                allowed_model_ids=[7],
                rows=[SimpleNamespace(model_id=7, credit_rate=125)],
                version=1,
                quota_epoch=1,
                monthly_token_limit=1_000_000,
            )
        ),
    )
    admission = AsyncMock(side_effect=lambda event, **kwargs: event)
    service = SimpleNamespace(
        activate=AsyncMock(),
        usage=SimpleNamespace(check_and_start=admission),
        model=object(),
    )
    monkeypatch.setattr(runtime, "get_model_runtime", AsyncMock(return_value=service))
    monkeypatch.setattr(settings.dsh, "billing_timezone", "Asia/Shanghai")
    _, event, _ = await chat_credits.start(
        SimpleNamespace(user_id=2, model_id=requested_id, model_info=SimpleNamespace(id=7)),
    )
    assert event.model_id == 7
    assert event.credit_rate == 125
    admission.assert_awaited_once()


@pytest.mark.parametrize("succeeded,known,status", [(True, True, "SUCCEEDED"), (False, True, "FAILED"), (False, False, "USAGE_UNKNOWN")])
async def test_chat_finishes_through_real_shared_settlement(succeeded, known, status):
    from datetime import UTC, datetime

    from bisheng.dsh.domain.schemas.usage import UsageEvent
    from bisheng.dsh.domain.services.model import DshModelService

    now = datetime(2026, 10, 22, tzinfo=UTC)
    event = UsageEvent(request_id="chat-ledger", tenant_id=1, user_id=2, session_id="chat",
                       model_id=7, credit_rate=125, usage_month="2026-10", billing_timezone="Asia/Shanghai",
                       policy_version=1, event_version=1, quota_epoch=1, status="RUNNING", started_at=now)
    ledger = SimpleNamespace(record_usage=AsyncMock())
    service = DshModelService(policy_reader=None, model_loader=None, llm_builder=None,
                              capabilities_for=None, usage=ledger, now=lambda: now)
    execution = SimpleNamespace(usage=DshTokenUsage(input_tokens=12, output_tokens=7, total_tokens=19)
                                if known else DshTokenUsage(), provider_request_id="provider-request")
    await chat_credits.finish((service, event, execution), succeeded)
    ledger.record_usage.assert_awaited_once()
    terminal, version = ledger.record_usage.await_args.args
    assert terminal.status == status
    assert terminal.billed_tokens == (24 if known else None)
    assert terminal.provider_request_id == "provider-request"
    assert terminal.error_code == (None if succeeded else "chat_call_interrupted")
    assert version == 1
