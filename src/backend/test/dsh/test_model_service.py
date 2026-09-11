"""覆盖 AC: AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-27, AC-30, AC-31, AC-34."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from bisheng.common.errcode.dsh import DshModelNotAllowedError, DshUpstreamErrorError
from bisheng.dsh.domain.schemas.chat import ChatCapabilities, DshChatRequest
from bisheng.dsh.domain.services.access import DshPrincipal
from bisheng.dsh.domain.services.model import DshModelService
from test.dsh.test_quota_admission import quota as real_quota  # noqa: F401
from test.dsh.test_quota_admission import running


def principal():
    return DshPrincipal(tenant_id="2", user_id="20", seat_id="seat", session_id="session", grant_version=1)


def request(stream=False):
    return DshChatRequest(model="bisheng:42", messages=[{"role": "user", "content": "hi"}], stream=stream)


class LLM:
    def __init__(self, *, usage=True):
        self.calls = 0
        self.reliable = usage
        self.continue_stream = asyncio.Event()
        self.closed = False

    def measured(self):
        return {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12} if self.reliable else None

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        return AIMessage(content="ok", usage_metadata=self.measured(), response_metadata={"finish_reason": "stop"})

    async def astream(self, messages, **kwargs):
        self.calls += 1
        try:
            yield AIMessageChunk(content="first")
            await self.continue_stream.wait()
            yield AIMessageChunk(content="last", response_metadata={"finish_reason": "stop"})
            yield AIMessageChunk(content="", usage_metadata=self.measured())
        finally:
            self.closed = True


class Ledger:
    def __init__(self):
        self.events = []
        self.used = 90
        self.frozen = False

    async def check_and_start(self, event):
        assert self.used == 90
        self.events.append(event)
        return event

    async def record_usage(self, event, expected_version):
        assert expected_version == 1
        self.events.append(event)
        if event.total_tokens is not None:
            self.used += event.total_tokens
        return event


@pytest.fixture
def service_setup():
    llm, ledger = LLM(), Ledger()
    policy = SimpleNamespace(
        version=1,
        quota_epoch=1,
        quota_sync_state="READY",
        allowed_model_ids=[42],
        rows=[SimpleNamespace(model_id=42, version=1, quota_sync_state="READY")],
        monthly_token_limit=100,
    )
    model = SimpleNamespace(
        id=42, name="Enterprise", model_name="provider", create_time=datetime(2026, 9, 9), config={}
    )
    state = {"online": True}

    async def load_model(model_id):
        if not state["online"]:
            raise DshModelNotAllowedError()
        return model, SimpleNamespace(name="OpenAI", type="openai")

    async def load_policy(user_id):
        return policy

    service = DshModelService(
        policy_reader=load_policy,
        model_loader=load_model,
        llm_builder=lambda *args: llm,
        capabilities_for=lambda *args: ChatCapabilities(),
        usage=ledger,
        now=lambda: datetime(2026, 9, 9, tzinfo=UTC),
    )
    return service, llm, ledger, policy, state


async def test_models_empty_policy_and_immediate_offline(service_setup):
    service, llm, _ledger, policy, state = service_setup
    assert (await service.list_models(principal()))["data"][0]["id"] == "bisheng:42"
    state["online"] = False
    assert (await service.list_models(principal()))["data"] == []
    with pytest.raises(DshModelNotAllowedError):
        await service.complete(principal(), request())
    state["online"] = True
    policy.allowed_model_ids = []
    assert (await service.list_models(principal()))["data"] == []
    assert llm.calls == 0


@pytest.mark.parametrize(
    ("provider_name", "provider_type", "model_name", "alias", "expected"),
    [
        ("百炼", "aliyun", "qwen-max", "model 2", "百炼 / qwen-max"),
        ("DeepSeek", "openai", "deepseek-chat", "model 3", "DeepSeek / deepseek-chat"),
        ("  百炼  ", "aliyun", "  qwen-max  ", "model 2", "百炼 / qwen-max"),
        ("", "openai", "qwen-max", "model 2", "openai / qwen-max"),
        ("   ", "openai", "", "Custom model", "openai / Custom model"),
        ("OpenAI", "openai", "   ", "Custom model", "OpenAI / Custom model"),
    ],
)
async def test_models_display_provider_and_actual_name_with_existing_fallbacks(
    service_setup, provider_name, provider_type, model_name, alias, expected
):
    from bisheng.dsh.admin_runtime import read_available_models

    service, llm, ledger, _policy, _state = service_setup
    model = SimpleNamespace(
        id=42, tenant_id=2, name=alias, model_name=model_name, create_time=datetime(2026, 9, 9), config={}
    )
    server = SimpleNamespace(name=provider_name, type=provider_type)

    async def load_model(_model_id):
        return model, server

    service.model_loader = load_model
    result = await service.list_models(principal())
    assert result == {
        "object": "list",
        "data": [
            {
                "id": "bisheng:42",
                "object": "model",
                "created": 1788912000,
                "owned_by": "bisheng",
                "display_name": expected,
                "capabilities": service.capabilities_for(model, server).client_fields(),
            }
        ],
    }
    from bisheng.dsh.domain.services.access import principal_scope

    with principal_scope(principal()):
        assert (await read_available_models([42], load_model))[0]["name"] == expected
    assert llm.calls == 0 and ledger.events == []


async def test_known_usage_settled_before_success_and_inflight_overage_kept(service_setup):
    service, llm, ledger, _policy, _state = service_setup
    result = await service.complete(principal(), request())
    assert result["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
        "prompt_tokens_details": {"cached_tokens": None, "cache_creation_tokens": None},
    }
    assert ledger.used == 102
    assert ledger.events[-1].status == "SUCCEEDED"
    assert llm.calls == 1


async def test_unknown_usage_returns_answer_and_records_missing_measurement(service_setup):
    service, llm, ledger, _policy, _state = service_setup
    llm.reliable = False
    result = await service.complete(principal(), request())
    assert result["choices"][0]["message"]["content"] == "ok"
    assert result["usage"]["total_tokens"] is None
    assert ledger.events[-1].error_code == "usage_missing"
    assert ledger.events[-1].status == "USAGE_UNKNOWN"
    assert ledger.used == 90 and not ledger.frozen
    assert llm.calls == 1


async def test_stream_first_content_not_buffered_and_unknown_finishes_normally(service_setup):
    service, llm, ledger, _policy, _state = service_setup
    llm.reliable = False
    stream = await service.complete(principal(), request(stream=True))
    first = await asyncio.wait_for(anext(stream), timeout=1)
    assert "first" in first
    assert ledger.events[-1].status == "RUNNING"
    llm.continue_stream.set()
    rest = "".join([part async for part in stream])
    assert "usage_unavailable" not in rest and "[DONE]" in rest
    assert not ledger.frozen


async def test_cancel_stream_records_unknown_and_closes_upstream(service_setup):
    service, llm, ledger, _policy, _state = service_setup
    stream = await service.complete(principal(), request(stream=True))
    await anext(stream)
    await stream.aclose()
    assert llm.closed
    assert ledger.events[-1].status == "USAGE_UNKNOWN"
    assert ledger.events[-1].error_code == "cancelled"


async def test_stream_success_suppresses_optional_usage_but_still_accounts(service_setup):
    service, llm, ledger, _policy, _state = service_setup
    llm.continue_stream.set()
    stream = await service.complete(principal(), request(stream=True))
    data = "".join([part async for part in stream])
    assert data.endswith("data: [DONE]\n\n")
    assert '"usage"' not in data
    assert ledger.used == 102


async def test_close_before_first_read_records_confirmed_zero_without_upstream(service_setup):
    service, llm, ledger, _policy, _state = service_setup
    stream = await service.complete(principal(), request(stream=True))
    await stream.aclose()
    await stream.aclose()
    assert llm.calls == 0
    assert ledger.events[-1].status == "CANCELLED"
    assert ledger.events[-1].total_tokens == 0
    assert ledger.used == 90 and not ledger.frozen


async def test_explicit_usage_stream_chunk_emitted_only_after_settlement(service_setup):
    service, llm, ledger, _policy, _state = service_setup
    llm.continue_stream.set()
    body = request(stream=True).model_copy(update={"stream_options": SimpleNamespace(include_usage=True)})
    stream = await service.complete(principal(), body)
    chunks = [chunk async for chunk in stream]
    assert '"choices":[],"usage":' in chunks[-2]
    assert ledger.events[-1].status == "SUCCEEDED"


async def test_settlement_response_loss_confirms_original_request_without_replay(service_setup):
    service, llm, ledger, _policy, _state = service_setup
    original = ledger.record_usage

    async def lost_response(event, expected_version):
        await original(event, expected_version)
        raise TimeoutError("response lost after durable settlement")

    async def get_request(event):
        return ledger.events[-1]

    ledger.record_usage = lost_response
    ledger.get_request = get_request
    response = await service.complete(principal(), request())
    assert response["usage"]["total_tokens"] == 12
    assert ledger.used == 102 and llm.calls == 1


async def test_provider_failure_without_usage_is_unknown_and_never_replayed(service_setup):
    service, llm, ledger, _policy, _state = service_setup

    async def fail(*args, **kwargs):
        llm.calls += 1
        raise ConnectionError("provider disconnected")

    llm.ainvoke = fail
    with pytest.raises(DshUpstreamErrorError):
        await service.complete(principal(), request())
    assert not ledger.frozen and llm.calls == 1


@pytest.mark.parametrize("lose_response", [False, True])
async def test_real_redis_settlement_and_changed_model_keep_total(service_setup, real_quota, lose_response):  # noqa: F811
    from bisheng.common.errcode.dsh import DshMonthlyTokenLimitExceededError
    from bisheng.dsh.domain.services.usage import DshUsageService

    service, llm, _ledger, policy, _state = service_setup
    policy.allowed_model_ids = [4, 5]
    policy.rows = [SimpleNamespace(model_id=model, version=1, quota_sync_state="READY") for model in (4, 5)]
    policy.monthly_token_limit = 1000

    async def load_model(model_id):
        return SimpleNamespace(id=model_id, name="Enterprise", model_name="test", config={}), SimpleNamespace(
            type="openai"
        )

    service.model_loader = load_model
    usage = DshUsageService(real_quota)
    if lose_response:
        original = usage.record_usage

        async def lost_response(event, expected_version):
            await original(event, expected_version)
            raise TimeoutError("response lost after actual Redis settlement")

        usage.record_usage = lost_response
    service.usage = usage
    llm.measured = lambda: {"input_tokens": 10, "output_tokens": 200, "total_tokens": 210}
    response = await service.complete(principal(), request().model_copy(update={"model": "bisheng:4"}))
    assert response["usage"]["total_tokens"] == 210
    assert await real_quota.redis.hget(real_quota.keys(running())[1], "used") == "1110"
    with pytest.raises(DshMonthlyTokenLimitExceededError):
        await service.complete(principal(), request().model_copy(update={"model": "bisheng:4"}))
    other = await service.complete(principal(), request().model_copy(update={"model": "bisheng:5"}))
    assert other["usage"]["total_tokens"] == 210
    assert llm.calls == 2


async def test_context_length_refusal_preserves_client_error_without_freezing(service_setup):
    import httpx
    from openai import BadRequestError

    from bisheng.common.errcode.dsh import DshContextLengthExceededError

    service, llm, ledger, *_ = service_setup

    async def refuse(*args, **kwargs):
        raise BadRequestError(
            "Too long",
            response=httpx.Response(400, request=httpx.Request("POST", "https://provider.example/chat/completions")),
            body={"code": "context_length_exceeded"},
        )

    llm.ainvoke = refuse
    with pytest.raises(DshContextLengthExceededError):
        await service.complete(principal(), request())
    assert ledger.events[-1].total_tokens is None
    assert not ledger.frozen
