"""Protocol adaptation from existing provider implementations, never an authorization list."""

from bisheng.dsh.domain.schemas.chat import ChatCapabilities


def model_capabilities(model, server) -> ChatCapabilities:
    from langchain_core.language_models import BaseChatModel

    from bisheng.llm.domain.llm.llm import _llm_node_type

    adapter = _llm_node_type.get(server.type, {})
    client = adapter.get("client")
    tools = client is not None and getattr(client, "bind_tools", None) is not BaseChatModel.bind_tools
    # Moonshot's existing built-in web-search loop explicitly disables streaming.
    return ChatCapabilities(
        streaming=server.type != "moonshot",
        tools=tools,
        reasoning_content=True,
        max_completion_tokens=server.type in {"openai", "azure_openai"},
    )
