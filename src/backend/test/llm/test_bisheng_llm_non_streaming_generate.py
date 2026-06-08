"""Regression tests for the non-streaming `_generate`/`_agenerate` path of BishengLLM.

Background: langchain-openai 1.x stopped aggregating a streaming response inside
`ChatOpenAI._generate` (it returns a raw `Stream` and relies on `_generate_with_cache`
to dispatch streaming models to `_stream`). BishengLLM delegates to the inner model
directly, so for a `streaming=True` inner model `_generate` must aggregate the stream
itself — otherwise it crashes with `'Stream' object has no attribute 'model_dump'`.

Crucially, the workflow LLM node calls `.invoke()` (→ `_agenerate`) but drives its UI
streaming from the `on_llm_new_token` callbacks that fire while the inner model streams.
So the fix must aggregate *via the inner `_stream`* (keeping callbacks firing), not
suppress streaming. These tests lock that behavior.
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk

from bisheng.llm.domain.llm.llm import BishengLLM

_LLM_WRAPPER_SRC = (
    Path(__file__).resolve().parent.parent.parent / 'bisheng' / 'llm' / 'domain' / 'llm' / 'llm.py'
).read_text(encoding='utf-8')


class _RunManager:
    def __init__(self):
        self.tokens = []

    def on_llm_new_token(self, token, **kwargs):
        self.tokens.append(token)


class _StreamingInner:
    """Stub inner chat model that streams two chunks and forbids the non-streaming path."""

    streaming = True

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for tok in ('Hel', 'lo'):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=tok))
            if run_manager is not None:
                run_manager.on_llm_new_token(tok, chunk=chunk)
            yield chunk

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        for chunk in self._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk

    def _generate(self, *args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError('inner._generate must not be called for a streaming model')

    async def _agenerate(self, *args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError('inner._agenerate must not be called for a streaming model')


def _make_wrapper(inner):
    inst = BishengLLM.model_construct(llm=inner)
    object.__setattr__(inst, 'server_info', SimpleNamespace(type='openai'))
    object.__setattr__(inst, 'model_info', SimpleNamespace(model_type='llm'))
    return inst


def test_generate_aggregates_inner_stream_and_fires_token_callbacks():
    rm = _RunManager()
    inst = _make_wrapper(_StreamingInner())
    # Bypass the telemetry/limit-check decorator to test the method body directly.
    result = BishengLLM._generate.__wrapped__(inst, [HumanMessage(content='hi')], run_manager=rm)
    assert result.generations[0].message.content == 'Hello'
    # The inner model streamed, so per-token callbacks fired -> UI streaming preserved.
    assert rm.tokens == ['Hel', 'lo']


def test_agenerate_aggregates_inner_stream_and_fires_token_callbacks():
    rm = _RunManager()
    inst = _make_wrapper(_StreamingInner())
    result = asyncio.run(
        BishengLLM._agenerate.__wrapped__(inst, [HumanMessage(content='hi')], run_manager=rm))
    assert result.generations[0].message.content == 'Hello'
    assert rm.tokens == ['Hel', 'lo']


def test_source_streaming_branch_aggregates_via_inner_stream():
    """Guard the fix shape: both methods must aggregate the inner stream (not suppress it)."""
    for method, agg, inner in (
        ('def _generate(', 'generate_from_stream', 'self.llm._stream('),
        ('async def _agenerate(', 'agenerate_from_stream', 'self.llm._astream('),
    ):
        idx = _LLM_WRAPPER_SRC.index(method)
        body = _LLM_WRAPPER_SRC[idx:idx + 1400]
        assert agg in body, f'{method} must aggregate the inner stream via {agg}'
        assert inner in body, f'{method} must stream via {inner}'
        assert "kwargs['stream'] = False" not in body, f'{method} must not suppress streaming'
