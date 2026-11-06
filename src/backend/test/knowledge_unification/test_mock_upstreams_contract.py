"""W6 §8 upstream wire contracts, using real clients on loopback only.

Supports AC-06/38/48/49/50/52/53/54 E2E fixtures; this is not a
real provider, middleware, index-reset, or browser acceptance result.
"""

import asyncio
import base64
import hashlib
import json
import math
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import fitz
import httpx
import openai
import pytest
import requests
import uvicorn
from langchain_openai import OpenAIEmbeddings

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.core.ai.llm.chat_openai_compatible import ChatOpenAICompatible
from bisheng.knowledge.rag.base_file_pipeline import BaseFilePipeline, FileExtensionMap
from bisheng.knowledge.rag.pipeline.loader import etl4lm
from bisheng.utils.exceptions import EtlException
from test.e2e.helpers import f118_mock_upstreams


@pytest.fixture(scope="module")
def upstream():
    app = f118_mock_upstreams.create_app()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "local mock did not start"
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive()


@pytest.fixture
def api(upstream):
    with httpx.Client(base_url=upstream, timeout=5, trust_env=False) as client:
        assert client.post("/__control/reset").status_code == 200
        yield client
        assert client.post("/__control/reset").status_code == 200


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def embedding_row(api, model, text):
    rows = api.get("/__control/stats").json()["embedding"]
    return next(row for row in rows if row["model"] == model and row["input_sha256"] == digest(text))


@pytest.mark.parametrize("dimension", [8, 16])
@pytest.mark.parametrize("encoding", [None, "base64", "float"])
def test_sdk_decodes_real_fixed_float32_dimensions(api, dimension, encoding):
    """AC-48/49: actual SDK default base64 and explicit float have fixed dimensions."""
    model = f"f118-embed-{dimension}"
    with openai.OpenAI(
        api_key="e2e-f118-mock", base_url=str(api.base_url) + "/v1", http_client=httpx.Client(trust_env=False)
    ) as client:
        kwargs = {} if encoding is None else {"encoding_format": encoding}
        result = client.embeddings.create(model=model, input=["e2e-f118-alpha", "e2e-f118-beta"], **kwargs)
        assert result.object == "list" and result.model == model
        vectors = []
        for index, item in enumerate(result.data):
            assert item.index == index and item.object == "embedding"
            vector = item.embedding
            if encoding == "base64":
                raw = base64.b64decode(vector, validate=True)
                assert len(raw) == dimension * 4
                vector = struct.unpack("<" + "f" * dimension, raw)
            assert len(vector) == dimension and all(math.isfinite(value) for value in vector)
            assert sum(value * value for value in vector) > 0
            assert list(vector) == list(
                struct.unpack("<" + "f" * dimension, struct.pack("<" + "f" * dimension, *vector))
            )
            vectors.append(list(vector))
        repeat = client.embeddings.create(model=model, input="e2e-f118-alpha", encoding_format="float")
        assert repeat.data[0].embedding == vectors[0]
        assert vectors[0] != vectors[1]


async def test_real_langchain_sync_and_async_embedding_use_the_same_wire(api):
    """AC-06/48: configured real OpenAI-compatible clients send strings, not token IDs."""
    with httpx.Client(trust_env=False) as sync_http:
        async with httpx.AsyncClient(trust_env=False) as async_http:
            client = OpenAIEmbeddings(
                model="f118-embed-8",
                api_key="e2e-f118-mock",
                base_url=str(api.base_url) + "/v1",
                check_embedding_ctx_length=False,
                http_client=sync_http,
                http_async_client=async_http,
            )
            values = client.embed_documents(["e2e-f118-sync", "e2e-f118-other"])
            assert len(values) == 2 and all(len(value) == 8 for value in values)
            assert await client.aembed_query("e2e-f118-sync") == values[0]
    assert embedding_row(api, "f118-embed-8", "e2e-f118-sync")["attempts"] == 2


@pytest.mark.parametrize(
    "changes",
    [{"model": "unknown"}, {"dimensions": 16}, {"input": []}, {"input": [12]}, {"encoding_format": "unknown"}],
)
def test_embedding_rejects_unsupported_models_inputs_and_dimension_overrides(api, changes):
    """AC-48: a model cannot silently turn into another physical vector dimension."""
    response = api.post("/v1/embeddings", json={"model": "f118-embed-8", "input": "e2e-f118", **changes})
    assert response.status_code == 400 and response.json()["error"]["type"] == "invalid_request_error"


async def test_real_chat_client_handles_nonstream_probe_and_stream_with_usage(api):
    """AC-38/50: actual chat probe and knowledge-answer streaming use Chat Completions."""
    with httpx.Client(trust_env=False) as sync_http:
        async with httpx.AsyncClient(trust_env=False) as async_http:
            client = ChatOpenAICompatible(
                model="f118-chat",
                api_key="e2e-f118-mock",
                base_url=str(api.base_url) + "/v1",
                streaming=False,
                stream_usage=True,
                http_client=sync_http,
                http_async_client=async_http,
            )
            answer = client.invoke("hello")
            assert answer.content.startswith("F118 mock") and answer.usage_metadata["total_tokens"] > 0
            chunks = [chunk async for chunk in client.astream("e2e-f118-question")]
            assert "".join(chunk.content for chunk in chunks) == answer.content
            assert sum((chunk.usage_metadata or {}).get("total_tokens", 0) for chunk in chunks) > 0
    totals = api.get("/__control/stats").json()["totals"]
    assert totals["chat_nonstream"] == totals["chat_stream"] == 1


@pytest.mark.parametrize("include_usage", [False, True])
def test_sse_frames_have_role_content_stop_optional_usage_and_done(api, include_usage):
    """AC-38: wire-level SSE framing is consumed in the same order by real SDKs."""
    response = api.post(
        "/v1/chat/completions",
        json={
            "model": "f118-chat",
            "messages": [{"role": "user", "content": "e2e-f118"}],
            "stream": True,
            "stream_options": {"include_usage": include_usage},
            "temperature": 0,
            "max_tokens": 32,
        },
    )
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [part.removeprefix("data: ") for part in response.text.strip().split("\n\n")]
    assert frames.pop() == "[DONE]"
    events = [json.loads(frame) for frame in frames]
    assert events[0]["choices"][0]["delta"]["role"] == "assistant"
    assert any(event["choices"] and event["choices"][0]["delta"].get("content") for event in events)
    stops = [event for event in events if event["choices"] and event["choices"][0]["finish_reason"] == "stop"]
    assert len(stops) == 1
    usage = [event for event in events if not event["choices"]]
    assert bool(usage) == include_usage
    if include_usage:
        assert events[-1]["choices"] == [] and events[-1]["usage"]["total_tokens"] > 0


@pytest.fixture
def pdf_file(tmp_path):
    path = tmp_path / "e2e-f118-etl-target.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((50, 50), "e2e-f118 PDF fixture")
        document.save(path)
    return path


def etl_loader(api, pdf_file, **kwargs):
    return etl4lm.Etl4lmLoader(
        url=str(api.base_url) + "/v1/etl4llm/predict",
        ocr_sdk_url="",
        file_path=str(pdf_file),
        file_metadata={"fixture": "e2e-f118"},
        file_extension="pdf",
        tmp_dir=str(pdf_file.parent),
        timeout=5,
        **kwargs,
    )


def test_real_etl_loader_sends_base64_json_to_complete_url_and_gets_nonempty_document(api, pdf_file, monkeypatch):
    """AC-50/53: real requests + PDF loader roundtrip preserves the existing ETL wire."""
    post = Mock(wraps=requests.post)
    monkeypatch.setattr(etl4lm.requests, "post", post)
    loader = etl_loader(api, pdf_file, request_kwargs={"force_ocr": False, "parameters": {"start": 2, "n": 3}})
    documents = loader.load()
    assert len(documents) == 1 and pdf_file.name in documents[0].page_content
    assert documents[0].page_content.startswith("F118_ETL_FIXTURE")
    assert documents[0].metadata["fixture"] == "e2e-f118"
    post.assert_called_once()
    assert post.call_args.args[0] == str(api.base_url) + "/v1/etl4llm/predict"
    payload = post.call_args.kwargs["json"]
    assert payload == {
        "filename": pdf_file.name,
        "b64_data": [base64.b64encode(pdf_file.read_bytes()).decode()],
        "mode": "partition",
        "force_ocr": False,
        "enable_formula": True,
        "filter_page_header_footer": False,
        "ocr_sdk_url": "",
        "parameters": {"start": 2, "n": 3},
    }
    assert api.get("/__control/stats").json()["totals"]["etl"] == 1
    assert api.get("/v1/etl4llm/files/sample").status_code == 404


@pytest.mark.parametrize("extension", ["txt", "md"])
@pytest.mark.parametrize("mode", ["auto", "hierarchical"])
def test_actual_text_and_markdown_loaders_do_not_call_etl(api, tmp_path, extension, mode):
    """AC-50/53: txt/md remain local even with the test ETL service available."""

    class LocalPipeline(BaseFilePipeline):
        @property
        def file_metadata(self):
            return {"fixture": "e2e-f118"}

    path = tmp_path / f"e2e-f118-local.{extension}"
    path.write_text("# E2E heading\n\ne2e_f118_local_document\n", encoding="utf8")
    pipeline = LocalPipeline(invoke_user_id=7, file_name=path.name, file_rule=FileProcessBase(split_mode=mode))
    pipeline.local_file_path, pipeline.tmp_dir = str(path), str(tmp_path)
    loader = getattr(pipeline, FileExtensionMap[extension]["loader"])()
    assert not isinstance(loader, etl4lm.Etl4lmLoader)
    assert "e2e_f118_local_document" in "\n".join(document.page_content for document in loader.load())
    assert api.get("/__control/stats").json()["totals"]["etl"] == 0


def test_targeted_embedding_failure_is_not_consumed_by_probes_and_is_not_sdk_retried(api):
    """AC-52/54: one nonretryable upstream failure exposes real job failure/retry."""
    assert (
        api.post(
            "/__control/fail-next", json={"kind": "embedding", "model": "f118-embed-8", "marker": "e2e-f118-fail"}
        ).status_code
        == 200
    )
    with openai.OpenAI(
        api_key="e2e-f118-mock", base_url=str(api.base_url) + "/v1", http_client=httpx.Client(trust_env=False)
    ) as client:
        client.embeddings.create(model="f118-embed-8", input=["hello", "Test text", "test"])
        client.embeddings.create(model="f118-embed-16", input="e2e-f118-fail")
        assert api.get("/__control/stats").json()["pending_failure"] is not None
        with pytest.raises(openai.BadRequestError):
            client.embeddings.create(model="f118-embed-8", input="e2e-f118-fail")
        assert embedding_row(api, "f118-embed-8", "e2e-f118-fail")["attempts"] == 1
        client.embeddings.create(model="f118-embed-8", input="e2e-f118-fail")
    row = embedding_row(api, "f118-embed-8", "e2e-f118-fail")
    assert row == {"model": "f118-embed-8", "input_sha256": digest("e2e-f118-fail"), "attempts": 2, "failed": 1}
    stats = api.get("/__control/stats").json()
    assert stats["totals"]["embedding"] == 4 and stats["pending_failure"] is None
    assert "e2e-f118-fail" not in json.dumps(stats)


def test_real_etl_once_failure_keeps_payload_hash_and_succeeds_next_attempt(api, pdf_file):
    """AC-52/53/54: ETL 503 is a real loader failure; retry uses the same source bytes."""
    assert api.post("/__control/fail-next", json={"kind": "etl", "marker": "etl-target"}).status_code == 200
    loader = etl_loader(api, pdf_file)
    with pytest.raises(EtlException):
        loader.load()
    assert loader.load()[0].page_content
    stats = api.get("/__control/stats").json()
    assert stats["totals"]["etl"] == 2 and stats["pending_failure"] is None
    assert stats["etl"] == [
        {
            "filename": pdf_file.name,
            "content_sha256": hashlib.sha256(pdf_file.read_bytes()).hexdigest(),
            "attempts": 2,
            "failed": 1,
        }
    ]


async def test_concurrent_requests_consume_exactly_one_marker_failure(api):
    """AC-52/54: concurrent matching attempts cannot consume a once rule twice."""
    assert api.post("/__control/fail-next", json={"kind": "embedding", "marker": "e2e-f118-race"}).status_code == 200
    async with httpx.AsyncClient(base_url=str(api.base_url), trust_env=False, timeout=5) as client:
        responses = await asyncio.gather(
            *(client.post("/v1/embeddings", json={"model": "f118-embed-8", "input": "e2e-f118-race"}) for _ in range(8))
        )
    assert sorted(response.status_code for response in responses) == [200] * 7 + [400]
    row = embedding_row(api, "f118-embed-8", "e2e-f118-race")
    assert row["attempts"] == 8 and row["failed"] == 1


def test_control_stats_reset_and_unsupported_protocols_are_explicit(api):
    """AC-49/52: counters isolate probes by digest; unsupported protocols do not fake success."""
    assert api.get("/healthz").json() == {"status": "ok"}
    assert api.post("/__control/fail-next", json={"kind": "embedding", "marker": ""}).status_code == 400
    assert api.post("/__control/fail-next", json={"kind": "chat", "marker": "e2e-f118"}).status_code == 400
    assert api.post("/v1/responses", json={}).status_code == 404
    assert (
        api.post(
            "/v1/chat/completions", json={"model": "f118-chat", "messages": [], "tools": [{"type": "function"}]}
        ).status_code
        == 400
    )
    api.post("/v1/embeddings", json={"model": "f118-embed-8", "input": "e2e-f118-private-input"})
    assert api.post("/__control/fail-next", json={"kind": "etl", "marker": "e2e-f118"}).status_code == 200
    assert api.post("/__control/reset").status_code == 200
    assert api.get("/__control/stats").json() == {
        "totals": {"embedding": 0, "chat_nonstream": 0, "chat_stream": 0, "etl": 0},
        "embedding": [],
        "etl": [],
        "pending_failure": None,
    }


def test_helper_cli_imports_without_bisheng_config_or_working_directory(tmp_path):
    """AC-06: helper is independently runnable without business config/database imports."""
    result = subprocess.run(
        [sys.executable, str(Path(f118_mock_upstreams.__file__).resolve()), "--help"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": "", "config": str(tmp_path / "missing-business-config.yaml")},
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0 and "--host" in result.stdout and "--port" in result.stdout
