"""Exercise production provider methods without loading application services."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from bisheng.common.services.failure_context import FailureContextAdapter, failure_boundary


@pytest.mark.parametrize(
    "file,cls,method,provider,kind,service",
    [
        ("llm", "BishengLLM", "_generate", "llm", "sync", "llm"),
        ("llm", "BishengLLM", "_agenerate", "llm", "async", "llm"),
        ("llm", "BishengLLM", "_stream", "llm", "stream", "llm"),
        ("llm", "BishengLLM", "_astream", "llm", "astream", "llm"),
        ("embedding", "BishengEmbedding", "embed_documents", "embeddings", "sync", "embedding"),
        ("embedding", "BishengEmbedding", "embed_query", "embeddings", "sync", "embedding"),
        ("rerank", "BishengRerank", "compress_documents", "rerank", "sync", "rerank"),
        ("rerank", "BishengRerank", "acompress_documents", "rerank", "async", "rerank"),
        ("asr", "BishengASR", "ainvoke", "asr", "async", "asr"),
        ("tts", "BishengTTS", "ainvoke", "tts", "async", "tts"),
    ],
)
async def test_actual_provider_boundary_keeps_source_and_same_exception(file, cls, method, provider, kind, service):
    path = Path(__file__).resolve().parents[2] / "bisheng/llm/domain/llm" / f"{file}.py"
    tree = ast.parse(path.read_text())
    node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == cls)
    func = next(
        node for node in node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method
    )
    # Outer quota/telemetry decorators are deliberately excluded: provider calls
    # must annotate BELOW those guards, not relabel a platform quota rejection.
    func.decorator_list = [
        d for d in func.decorator_list if isinstance(d, ast.Call) and getattr(d.func, "id", "") == "failure_boundary"
    ]
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, func], type_ignores=[]))
    ns = {"failure_boundary": failure_boundary, "_raise_as_context_overflow": lambda exc: None}
    exec(compile(module, str(path), "exec"), ns)
    error = RuntimeError("password=secret")

    def sync(*args, **kwargs):
        raise error

    async def asynchronous(*args, **kwargs):
        raise error

    def stream(*args, **kwargs):
        yield "partial"
        raise error

    async def astream(*args, **kwargs):
        yield "partial"
        raise error

    implementation = {"sync": sync, "async": asynchronous, "stream": stream, "astream": astream}[kind]
    inner_name = {"asr": "transcribe", "tts": "synthesize"}.get(file, method)
    inner = SimpleNamespace(**{inner_name: implementation})
    subject = SimpleNamespace(**{provider: inner})
    ns["normalize_reasoning_content"] = lambda item: item
    args = (subject, [], "q") if file == "rerank" else (subject, [])
    with pytest.raises(RuntimeError) as caught:
        if kind == "sync":
            ns[method](*args)
        elif kind == "async":
            await ns[method](*args)
        elif kind == "stream":
            iterator = ns[method](*args)
            assert next(iterator) == "partial"
            next(iterator)
        else:
            iterator = ns[method](*args)
            assert await anext(iterator) == "partial"
            await anext(iterator)
    assert caught.value is error
    assert FailureContextAdapter.from_error(error)["service"] == service
