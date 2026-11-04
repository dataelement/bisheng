"""Isolate provider argument construction from model clients and infrastructure."""

import ast
import json
from pathlib import Path

import pytest

source = Path(__file__).parents[2] / "bisheng/llm/domain/llm/llm.py"
names = {
    "_get_user_kwargs",
    "_get_openai_params",
    "_get_qwen_params",
    "_get_ollama_params",
    "_get_spark_params",
    "_get_tencent_params",
}
nodes = [
    node for node in ast.parse(source.read_text()).body if isinstance(node, ast.FunctionDef) and node.name in names
]
namespace = {"json": json, "usable_proxy_url": lambda value: value or None}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)


@pytest.mark.parametrize(
    "provider,parameter",
    [
        ("openai", "max_tokens"),
        ("qwen", "max_tokens"),
        ("ollama", "num_ctx"),
        ("spark", "max_tokens"),
        ("tencent", "max_tokens"),
    ],
)
@pytest.mark.parametrize("serialized", [True, False])
def test_advanced_limit_reaches_provider_with_connection_and_runtime_precedence(provider, parameter, serialized):
    advanced = {parameter: 256, "temperature": 0.1, "model": "custom-alias"}
    config = {"user_kwargs": json.dumps(advanced) if serialized else advanced, "enable_web_search": True}
    server = {
        "base_url": "http://inference.test/v1",
        "openai_api_base": "http://inference.test/v1",
        "api_key": "fixture",
        "api_secret": "fixture-secret",
    }
    result = namespace["_get_" + provider + "_params"]({"model": "actual-model", "streaming": False}, server, config)
    assert result[parameter] == 256
    assert result["temperature"] == 0.1
    assert result["model"] == "actual-model"
    assert result["base_url"] == "http://inference.test/v1"
    assert advanced["model"] == "custom-alias"
    if provider == "qwen":
        assert result["extra_body"]["enable_search"] is True


def test_tencent_switch_reaches_the_wire_without_losing_other_body_fields():
    for enabled in [True, False]:
        config = {"enable_web_search": enabled, "user_kwargs": {"extra_body": {"keep": "value"}}}
        result = namespace["_get_tencent_params"](
            {"model": "hunyuan"}, {"openai_api_base": "https://provider.test/v1"}, config
        )
        assert result["extra_body"] == {"keep": "value", "enable_enhancement": enabled}
