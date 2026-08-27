"""Dispatch tests for the OrcaRouter provider registration.

OrcaRouter is an OpenAI-compatible AI gateway that exposes a
provider/model namespace (e.g. ``orcarouter/auto``) behind the same
``/v1/chat/completions`` contract. It is wired through the same
OpenAI-compatible client and params handler as the existing QIAN_FAN /
TENCENT / SILICON providers, so the tests lock the dispatch mapping
rather than duplicating payload tests already covered by
``test_provider_chatmodels.py``.
"""

from bisheng.core.ai.llm.chat_openai_compatible import ChatOpenAICompatible
from bisheng.llm.domain.const import LLMServerType
from bisheng.llm.domain.llm.llm import _get_openai_params, _llm_node_type


def test_orcarouter_server_type_registered():
    assert LLMServerType.ORCAROUTER.value == "orcarouter"


def test_orcarouter_uses_openai_compatible_client():
    assert _llm_node_type[LLMServerType.ORCAROUTER.value]["client"] is ChatOpenAICompatible


def test_orcarouter_uses_openai_params_handler():
    assert _llm_node_type[LLMServerType.ORCAROUTER.value]["params_handler"] is _get_openai_params


def test_orcarouter_params_resolve_endpoint():
    params = _get_openai_params(
        {"model": "orcarouter/auto", "streaming": False},
        {"openai_api_base": "https://api.orcarouter.ai/v1", "openai_api_key": "sk-orca-test"},
        {},
    )
    assert params["base_url"] == "https://api.orcarouter.ai/v1"
    assert params["api_key"] == "sk-orca-test"
    assert params["model"] == "orcarouter/auto"
