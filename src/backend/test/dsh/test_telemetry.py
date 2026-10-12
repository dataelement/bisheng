"""DSH telemetry is isolated, correlated and not a ledger. AC-19, AC-23, AC-24, AC-31, AC-32."""

from unittest.mock import Mock

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.core.logger import trace_id_var
from bisheng.dsh.infrastructure import telemetry
from test.dsh.test_model_service import principal, request, service_setup  # noqa: F401


def test_application_enum_preserves_existing_values():
    expected = {
        "WORKFLOW": "workflow",
        "ASSISTANT": "assistant",
        "LINSIGHT": "linsight",
        "DAILY_CHAT": "daily_chat",
        "KNOWLEDGE_BASE": "knowledge_base",
        "KNOWLEDGE_SPACE": "knowledge_space",
        "RAG_TRACEABILITY": "rag_traceability",
        "EVALUATION": "evaluation",
        "MODEL_TEST": "model_test",
        "ASR": "asr",
        "TTS": "tts",
        "UNKNOWN": "unknown",
    }
    assert {item.name: item.value for item in ApplicationTypeEnum if item.name != "DSH_DESKTOP"} == expected
    assert ApplicationTypeEnum.DSH_DESKTOP.value == "dsh_desktop"


async def test_failed_telemetry_does_not_undo_successful_accounting(service_setup, monkeypatch):  # noqa: F811
    service, _llm, ledger, *_ = service_setup
    emit = Mock(side_effect=RuntimeError("telemetry unavailable"))
    monkeypatch.setattr(telemetry, "emit_metric", emit)
    result = await service.complete(principal(), request())
    assert result["usage"]["total_tokens"] == 12 and ledger.used == 102
    assert ledger.events[-1].trace_id == ledger.events[-1].request_id
    assert ledger.events[-1].latency_ms == 0
    fields = emit.call_args.kwargs
    assert emit.call_args.args == ("dsh_settlement",)
    assert set(fields) == {"app_type", "request_id", "tenant_id", "user_id", "model_id", "status", "used_tokens"}


async def test_stream_trace_uses_request_id_and_restores_callers_context(service_setup, monkeypatch):  # noqa: F811
    service, llm, _ledger, *_ = service_setup
    observed = []
    original = llm.astream

    async def stream(*args, **kwargs):
        observed.append(trace_id_var.get())
        async for chunk in original(*args, **kwargs):
            yield chunk

    monkeypatch.setattr(llm, "astream", stream)
    outer = trace_id_var.set("outer-trace")
    try:
        prepared = await service.complete(principal(), request(stream=True))
        assert trace_id_var.get() == "outer-trace"
        await anext(prepared)
        assert observed == [prepared.event.request_id]
        assert trace_id_var.get() == "outer-trace"
        await prepared.aclose()
        assert trace_id_var.get() == "outer-trace"
    finally:
        trace_id_var.reset(outer)
