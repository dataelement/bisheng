"""The generic `openai_compatible` provider type: any server speaking the OpenAI API."""

import httpx
from langchain_core.messages import HumanMessage
from langchain_openai import OpenAIEmbeddings

from bisheng.core.ai import CommonRerank
from bisheng.core.ai.llm.chat_openai_compatible import ChatOpenAICompatible
from bisheng.llm.domain.const import LLMServerType
from bisheng.llm.domain.llm import embedding as embedding_module
from bisheng.llm.domain.llm import llm as llm_module
from bisheng.llm.domain.llm import rerank as rerank_module
from bisheng.llm.domain.services.context_window import ModelSnapshot
from bisheng.llm.domain.services.context_window_probes import PROBES, ProbeResult, probe_context_window

TYPE = LLMServerType.OPENAI_COMPATIBLE.value
SERVER_CONFIG = {"openai_api_base": "https://gateway.example.com/v1/", "openai_api_key": "sk-test"}


def test_type_value_fits_the_server_type_column():
    # llm_server.type is CHAR(20)
    assert TYPE == "openai_compatible"
    assert len(TYPE) <= 20


def test_llm_uses_compatible_client_and_sends_max_tokens():
    adapter = llm_module._llm_node_type[TYPE]
    assert adapter["client"] is ChatOpenAICompatible

    params = adapter["params_handler"]({"model": "my-model"}, SERVER_CONFIG, {})
    assert params["base_url"] == "https://gateway.example.com/v1"
    assert params["api_key"] == "sk-test"

    llm = adapter["client"](**params)
    payload = llm._get_request_payload([HumanMessage(content="hi")], max_completion_tokens=256)
    assert payload["max_tokens"] == 256
    assert "max_completion_tokens" not in payload


def test_llm_api_key_is_optional():
    params = llm_module._llm_node_type[TYPE]["params_handler"](
        {"model": "my-model"}, {"openai_api_base": "http://10.0.0.1:8000/v1"}, {}
    )
    assert params["api_key"] == "empty"


def test_embedding_and_rerank_are_registered():
    assert embedding_module._node_type[TYPE]["client"] is OpenAIEmbeddings
    assert rerank_module._node_type[TYPE]["client"] is CommonRerank

    params = rerank_module._node_type[TYPE]["params_handler"]({"model": "bge-reranker"}, SERVER_CONFIG, {})
    assert params["base_url"] == "https://gateway.example.com/v1/"
    assert params["rerank_endpoint"] == "/rerank"


async def test_context_window_probe_reads_models_endpoint():
    assert TYPE in PROBES
    snapshot = ModelSnapshot(
        model_id=1,
        model_name="my-model",
        server_type=TYPE,
        model_config={},
        client_params={"base_url": "https://gateway.example.com/v1", "api_key": "sk-test"},
    )
    body = {"object": "list", "data": [{"id": "my-model", "object": "model", "max_model_len": 32768}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://gateway.example.com/v1/models":
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await probe_context_window(snapshot, client)

    assert result == ProbeResult(window=32768, kind="total", source="deployed")
