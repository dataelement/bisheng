"""Protocol adaptation from existing provider implementations, never an authorization list."""

from bisheng.dsh.domain.schemas.chat import ChatCapabilities
from bisheng.dsh.domain.schemas.reasoning import model_parameters, reasoning_declaration


async def desktop_model_capabilities(model, server) -> ChatCapabilities:
    from bisheng.dsh.domain.services.vision import read_vision

    result = model_capabilities(model, server)
    result.vision = (await read_vision(model.id)).vision
    return result


def model_capabilities(model, server) -> ChatCapabilities:
    from langchain_core.language_models import BaseChatModel
    from langchain_openai.chat_models.base import BaseChatOpenAI

    from bisheng.llm.domain.llm.llm import _llm_node_type

    adapter = _llm_node_type.get(server.type, {})
    client = adapter.get("client")
    tools = client is not None and getattr(client, "bind_tools", None) is not BaseChatModel.bind_tools
    reasoning = reasoning_declaration(model.config or {})
    if reasoning is not None and server.type not in {"openai", "azure_openai"}:
        raise ValueError("Provider has no reasoning effort mapping")
    if reasoning is not None and any(
        item.id not in {"none", "minimal", "low", "medium", "high", "xhigh"} for item in reasoning.efforts
    ):
        raise ValueError("Provider does not support the declared effort")
    # Moonshot's existing built-in web-search loop explicitly disables streaming.
    return ChatCapabilities(
        streaming=server.type != "moonshot",
        tools=tools,
        reasoning_content=True,
        # OpenAI SDK adapters accept this input natively or translate it in
        # their existing payload builder (for example ChatQwen -> max_tokens).
        max_completion_tokens=client is not None and issubclass(client, BaseChatOpenAI),
        reasoning=reasoning,
        responses=server.type in {"openai", "azure_openai"}
        and model_parameters(model.config or {}).get("use_responses_api") is True,
        prompt_cache_key=server.type in {"openai", "azure_openai"},
    )
